#!/usr/bin/env python3
"""Mapping-driven parser for cell expansion provenance bundles.

This parser reads a provenance/process-monitoring bundle plus an Excel mapping
workbook, then emits:

- LabCAS collection/dataset/file cfgs under the metadata root
- archive-ready copies of publishable source artifacts
- LinkML-friendly collection/dataset/file YAML payloads and manifests
- a normalized manifest JSON for downstream inspection/debugging
- an ingestion report with missing files and mapping diagnostics
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import yaml


LOG = logging.getLogger("cell_provenance")

XLSX_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}

MANIFEST_VERSION = 1
DEFAULT_COLLECTION = "cell_expansion_collection"
DEFAULT_COLLECTION_NAME = "Cell Expansion Collection"
DEFAULT_COLLECTION_DESCRIPTION = (
    "LabCAS collection for cell expansion process history and linkable provenance models."
)
DEFAULT_OWNER_PRINCIPAL = "cn=All NIST,ou=groups,o=NIST"
DEFAULT_LINKML_OWNER_PRINCIPAL = "all_NIST"
DEFAULT_COLLECTION_ENUM = "cell_line_Provenance"
DEFAULT_DATA_CATEGORY = "Process Monitoring"
DEFAULT_LINKML_DATA_CATEGORY = "maintenance"
DEFAULT_DIVISION = "Biosystems and Biomaterials Division, Division 644"
DEFAULT_DIVISION_ENUM = "644_biosystems_and_biomaterials_division"
DEFAULT_PRINCIPAL_NAME = "John Elliott"
DEFAULT_PRINCIPAL_EMAIL = "john.elliott@nist.gov"
DEFAULT_CORE_CAPABILITIES = [
    "Automation",
    "Biomaterial Measurements",
    "Cell Measurements",
    "Genomic Measurements",
]
DEFAULT_PRIMARY_FOCUS_AREAS = ["Regenerative Medicine and Advanced Therapies (RMAT)"]
DEFAULT_DATA_PROCESSING_LEVEL = "Raw"
DEFAULT_DATA_FILE_CONTEXT = "Process Monitoring Data"
DEFAULT_FILE_CONTENT_TYPE = "Instrument Output"
DEFAULT_PRIMARY_FACET_FIELDS = [
    "cell_short_name",
    "cell_composite_name",
    "unit_operation_instance",
    "step",
    "component_name",
    "component_type",
    "culture_container_replicate_code",
    "passage_number",
    "input_connector",
    "output_connector",
]
DEFAULT_NON_PRIMARY_FACET_FIELDS = [
    "culture_container_replicate_multiplier",
    "culture_container_replicate_number",
    "previous_date_time",
    "delta_time",
    "cell_unique_id",
    "data_list",
]


def _bool_text(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=True)
    return str(value).strip()


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_to_text(item) for item in value if _to_text(item)]
    text = _to_text(value)
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"[;|]", text) if part.strip()]
    return parts or [text]


def _snake_case(text: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", text)
    second = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first)
    second = second.replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-zA-Z0-9_]+", "_", second).strip("_").lower()


def _safe_segment(text: str) -> str:
    cleaned = text.strip().replace("/", "_").replace("\x00", "")
    if cleaned in {"", ".", ".."}:
        return "node"
    return cleaned


def _safe_cfg_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-") or "node"


def _file_size(path: Path) -> str:
    try:
        return str(path.stat().st_size)
    except FileNotFoundError:
        return ""


def _mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _file_type_extension(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "unknown"


def _sorted_unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return sorted(out)


def _linkml_starting_material_type(value: str) -> str:
    token = _snake_case(value)
    if "cell" in token:
        return "cells"
    return token or "cells"


def _first_nonempty(values: Iterable[str]) -> str:
    for value in values:
        if value:
            return value
    return ""


def _max_int_text(values: Iterable[str]) -> str:
    ints: List[int] = []
    for value in values:
        text = _to_text(value)
        if not text:
            continue
        try:
            ints.append(int(float(text)))
        except ValueError:
            continue
    if not ints:
        return ""
    return str(max(ints))


def _min_text(values: Iterable[str]) -> str:
    items = sorted(v for v in values if v)
    return items[0] if items else ""


def _max_text(values: Iterable[str]) -> str:
    items = sorted(v for v in values if v)
    return items[-1] if items else ""


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False)


def _write_cfg(path: Path, header: str, data: Dict[str, Any]) -> None:
    lines = [f"[{header}]"]
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, list):
            text = "|".join(item for item in (_to_text(v) for v in value) if item)
        else:
            text = _to_text(value)
        if text:
            lines.append(f"{key}={text}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _xlsx_col_index(cell_ref: str) -> int | None:
    match = re.match(r"([A-Z]+)", cell_ref or "")
    if not match:
        return None
    letters = match.group(1)
    index = 0
    for char in letters:
        index = (index * 26) + (ord(char) - ord("A") + 1)
    return index - 1


def _read_xlsx_rows(path: Path) -> Dict[str, List[List[str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Workbook not found: {path}")

    with ZipFile(path) as archive:
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", XLSX_NS):
                shared_strings.append(
                    "".join(node.text or "" for node in item.iterfind(".//a:t", XLSX_NS))
                )

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("pr:Relationship", XLSX_NS)
        }

        def _cell_value(cell: ET.Element) -> str:
            cell_type = cell.attrib.get("t")
            if cell_type == "s":
                value = cell.find("a:v", XLSX_NS)
                return shared_strings[int(value.text)] if value is not None else ""
            if cell_type == "inlineStr":
                return "".join(node.text or "" for node in cell.findall(".//a:t", XLSX_NS))
            value = cell.find("a:v", XLSX_NS)
            return value.text or "" if value is not None else ""

        rows_by_sheet: Dict[str, List[List[str]]] = {}
        sheets = workbook.find("a:sheets", XLSX_NS)
        for sheet in list(sheets) if sheets is not None else []:
            rel_id = sheet.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            target = rel_map[rel_id].lstrip("/")
            sheet_xml = ET.fromstring(archive.read(f"xl/{target}"))
            sheet_rows: List[List[str]] = []
            for row in sheet_xml.findall(".//a:sheetData/a:row", XLSX_NS):
                row_values: Dict[int, str] = {}
                max_index = -1
                for cell in row.findall("a:c", XLSX_NS):
                    idx = _xlsx_col_index(cell.attrib.get("r", ""))
                    if idx is None:
                        idx = len(row_values)
                    row_values[idx] = _cell_value(cell)
                    if idx > max_index:
                        max_index = idx
                dense = ["" for _ in range(max_index + 1)]
                for idx, value in row_values.items():
                    dense[idx] = value
                while dense and not dense[-1]:
                    dense.pop()
                sheet_rows.append(dense)
            rows_by_sheet[sheet.attrib["name"]] = sheet_rows
    return rows_by_sheet


@dataclass(frozen=True)
class SchemaField:
    source_field: str
    source_scope: str
    source_definition: str
    example_value: str
    notes: str
    permissible_values: str
    schema_range: str
    target_slot: str
    preferred_name: str


@dataclass(frozen=True)
class SlotDefinition:
    slot_name: str
    title: str
    description: str
    required_in_schema: bool
    recommended_in_schema: str
    permissible_values: str
    default_value: str


@dataclass(frozen=True)
class MappingModel:
    schema_fields: Dict[str, SchemaField]
    collection_slots: Dict[str, SlotDefinition]
    dataset_slots: Dict[str, SlotDefinition]
    file_slots: Dict[str, SlotDefinition]
    activity_source_fields: List[str]
    entity_source_fields: List[str]


@dataclass
class ComponentRecord:
    component_name: str
    component_type: str
    attributes: Dict[str, str]
    required_fields: List[str]
    source_file: Path | None
    raw_item: Dict[str, Any]


@dataclass(frozen=True)
class BundleLayout:
    bundle_root: Path
    collated_file: Path
    bundle_name: str
    workbook_file: Path | None
    schema_files: List[Path]
    component_files: Dict[str, Path]


@dataclass
class PublishSource:
    file_name: str
    source_path: Path
    source_rel_path: str
    artifact_role: str
    primary_component: ComponentRecord | None = None
    related_components: List[ComponentRecord] = field(default_factory=list)
    reference_values: List[str] = field(default_factory=list)


@dataclass
class FileArtifact:
    file_name: str
    source_path: Path
    source_rel_path: str
    archive_file: Path
    file_id: str
    metadata: Dict[str, Any]
    linkml_payload: Dict[str, Any]
    cfg_file: Path
    mapped_file: Path
    artifact_role: str


def _slot_rows(rows: Sequence[List[str]]) -> Dict[str, SlotDefinition]:
    out: Dict[str, SlotDefinition] = {}
    for row in rows[1:]:
        slot_name = _to_text(row[0] if len(row) > 0 else "")
        if not slot_name:
            continue
        out[slot_name] = SlotDefinition(
            slot_name=slot_name,
            title=_to_text(row[1] if len(row) > 1 else ""),
            description=_to_text(row[2] if len(row) > 2 else ""),
            required_in_schema=_bool_text(row[3] if len(row) > 3 else ""),
            recommended_in_schema=_to_text(row[4] if len(row) > 4 else ""),
            permissible_values=_to_text(row[5] if len(row) > 5 else ""),
            default_value=_to_text(row[6] if len(row) > 6 else ""),
        )
    return out


def _schema_rows(rows: Sequence[List[str]]) -> Dict[str, SchemaField]:
    out: Dict[str, SchemaField] = {}
    for row in rows[1:]:
        source_field = _to_text(row[0] if len(row) > 0 else "")
        if not source_field:
            continue
        out[source_field] = SchemaField(
            source_field=source_field,
            source_scope=_to_text(row[1] if len(row) > 1 else ""),
            source_definition=_to_text(row[2] if len(row) > 2 else ""),
            example_value=_to_text(row[3] if len(row) > 3 else ""),
            notes=_to_text(row[4] if len(row) > 4 else ""),
            permissible_values=_to_text(row[5] if len(row) > 5 else ""),
            schema_range=_to_text(row[6] if len(row) > 6 else ""),
            target_slot=_to_text(row[7] if len(row) > 7 else "") or _snake_case(source_field),
            preferred_name=_to_text(row[8] if len(row) > 8 else ""),
        )
    return out


def _component_sheet_fields(rows: Sequence[List[str]]) -> tuple[str, List[str]]:
    component_type = ""
    variable_names: List[str] = []
    in_table = False

    for row in rows:
        label = _to_text(row[0] if len(row) > 0 else "")
        if not label:
            continue
        if label == "Component Type":
            component_type = _to_text(row[1] if len(row) > 1 else "")
            continue
        if label == "VariableName":
            in_table = True
            continue
        if not in_table:
            continue
        variable_name = label
        if variable_name:
            variable_names.append(variable_name)
    return component_type, _sorted_unique(variable_names)


def _workbook_component_field_union(
    rows_by_sheet: Dict[str, List[List[str]]], component_type: str
) -> List[str]:
    collected: List[str] = []
    for rows in rows_by_sheet.values():
        current_type, variable_names = _component_sheet_fields(rows)
        if current_type == component_type:
            collected.extend(variable_names)
    return _sorted_unique(collected)


def load_mapping_model(path: Path) -> MappingModel:
    rows = _read_xlsx_rows(path)
    required_sheets = {
        "CellLineExpansionSchema",
        "CollectionLevel_slots",
        "DatasetLevel_slots",
        "FileLevel_slots",
    }
    missing = sorted(sheet for sheet in required_sheets if sheet not in rows)
    if missing:
        raise RuntimeError(f"Workbook missing required sheets: {missing}")

    return MappingModel(
        schema_fields=_schema_rows(rows["CellLineExpansionSchema"]),
        collection_slots=_slot_rows(rows["CollectionLevel_slots"]),
        dataset_slots=_slot_rows(rows["DatasetLevel_slots"]),
        file_slots=_slot_rows(rows["FileLevel_slots"]),
        activity_source_fields=_workbook_component_field_union(rows, "Activity"),
        entity_source_fields=_workbook_component_field_union(rows, "Entity"),
    )


def _component_source_files(bundle_dir: Path) -> Dict[str, Path]:
    component_dir = bundle_dir / "Bundle Individual Files"
    if not component_dir.exists():
        return {}
    out: Dict[str, Path] = {}
    for path in sorted(component_dir.glob("*.json")):
        out[path.stem] = path
    return out


def _looks_like_bundle_payload(path: Path) -> bool:
    try:
        raw = _load_json(path)
    except Exception:
        return False
    if not isinstance(raw, list) or not raw:
        return False
    return all(
        isinstance(item, dict)
        and "ComponentName" in item
        and "ComponentType" in item
        and isinstance(item.get("Attributes"), list)
        for item in raw
    )


def discover_bundle_layout(bundle_dir: Path) -> BundleLayout:
    if not bundle_dir.exists():
        raise RuntimeError(f"Bundle path does not exist: {bundle_dir}")
    if not bundle_dir.is_dir():
        raise RuntimeError(f"Bundle path must be a directory: {bundle_dir}")

    preferred = bundle_dir / f"{bundle_dir.name}.json"
    candidates: List[Path] = []
    if preferred.exists():
        candidates.append(preferred)
    for path in sorted(bundle_dir.glob("*.json")):
        if path not in candidates:
            candidates.append(path)

    valid = [path for path in candidates if _looks_like_bundle_payload(path)]
    if not valid:
        raise RuntimeError(f"No collated bundle JSON found in {bundle_dir}")
    if len(valid) > 1:
        raise RuntimeError(
            f"Ambiguous collated bundle JSON candidates in {bundle_dir}: "
            + ", ".join(path.name for path in valid)
        )
    collated_file = valid[0]

    workbook_files = sorted(bundle_dir.glob("*.xlsx"))
    schema_dir = bundle_dir / "Schemas"
    schema_files = sorted(schema_dir.glob("*.json")) if schema_dir.exists() else []

    return BundleLayout(
        bundle_root=bundle_dir,
        collated_file=collated_file,
        bundle_name=collated_file.stem,
        workbook_file=workbook_files[0] if workbook_files else None,
        schema_files=schema_files,
        component_files=_component_source_files(bundle_dir),
    )


def load_components(bundle: BundleLayout) -> List[ComponentRecord]:
    collated_file = bundle.collated_file

    raw = _load_json(collated_file)
    if not isinstance(raw, list):
        raise RuntimeError(f"Expected collated bundle list in {collated_file}")

    source_files = bundle.component_files
    components: List[ComponentRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        component_name = _to_text(item.get("ComponentName"))
        component_type = _to_text(item.get("ComponentType"))
        attrs = item.get("Attributes")
        if not component_name or not component_type or not isinstance(attrs, list):
            continue
        attribute_map: Dict[str, str] = {}
        required_fields: List[str] = []
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            key = _to_text(attr.get("VariableName"))
            if not key:
                continue
            attribute_map[key] = _to_text(attr.get("Value"))
            if _bool_text(attr.get("Required")):
                required_fields.append(key)
        components.append(
            ComponentRecord(
                component_name=component_name,
                component_type=component_type,
                attributes=attribute_map,
                required_fields=sorted(set(required_fields)),
                source_file=source_files.get(component_name),
                raw_item=item,
            )
        )
    if not components:
        raise RuntimeError(f"No component records found in {collated_file}")
    return components


def _parse_data_list(value: str) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [item.strip() for item in value.split("|") if item.strip()]
    if isinstance(parsed, list):
        return [_to_text(item) for item in parsed if _to_text(item)]
    return []


def _resolve_reference(bundle_dir: Path, rel_path: str) -> Path:
    candidate = Path(rel_path)
    if candidate.is_absolute():
        return candidate
    return (bundle_dir / candidate).resolve()


def _component_field(record: ComponentRecord, field_name: str) -> str:
    return _to_text(record.attributes.get(field_name))


def _strip_version_suffix(text: str) -> str:
    return re.sub(r"_v\d+$", "", text)


def _dataset_version(bundle: BundleLayout) -> str:
    for candidate in [bundle.bundle_name, bundle.bundle_root.name]:
        match = re.search(r"_v(\d+)$", candidate)
        if match:
            return match.group(1)
    return "1"


def _bundle_instance_id(bundle: BundleLayout, components: Sequence[ComponentRecord]) -> str:
    explicit = _first_nonempty(
        _component_field(component, "UnitOperationInstance") for component in components
    )
    if explicit:
        return explicit
    for candidate in [bundle.bundle_name, bundle.bundle_root.name]:
        if candidate.endswith("_Bundle"):
            return _strip_version_suffix(candidate[: -len("_Bundle")])
    return _strip_version_suffix(bundle.bundle_name)


def _collection_metadata(model: MappingModel, collection: str) -> Dict[str, Any]:
    def _slot_default(slots: Dict[str, SlotDefinition], slot_name: str, fallback: Any) -> Any:
        value = slots.get(slot_name).default_value if slot_name in slots else ""
        if value:
            return value
        return fallback

    return {
        "CollectionName": DEFAULT_COLLECTION_NAME,
        "CollectionId": collection,
        "CollectionDescription": _slot_default(
            model.collection_slots, "collection_description", DEFAULT_COLLECTION_DESCRIPTION
        ),
        "DatasetId": collection,
        "DatasetName": DEFAULT_COLLECTION_NAME,
        "DatasetVersion": "1",
        "LeadPoC": _slot_default(
            model.collection_slots, "principal_contact_name", DEFAULT_PRINCIPAL_NAME
        ),
        "LeadPoCEmail": _slot_default(
            model.collection_slots, "principal_contact_email", DEFAULT_PRINCIPAL_EMAIL
        ),
        "DataCustodian": _slot_default(
            model.collection_slots, "data_custodian_name", DEFAULT_PRINCIPAL_NAME
        ),
        "DataCustodianEmail": _slot_default(
            model.collection_slots, "data_custodian_email", DEFAULT_PRINCIPAL_EMAIL
        ),
        "DataCategory": _slot_default(
            model.collection_slots, "data_category", DEFAULT_DATA_CATEGORY
        ),
        "CoreCapabilities": _as_list(
            _slot_default(
                model.collection_slots, "core_capabilities", DEFAULT_CORE_CAPABILITIES
            )
        ),
        "PrimaryFocusAreas": _as_list(
            _slot_default(
                model.collection_slots, "primary_focus_areas", DEFAULT_PRIMARY_FOCUS_AREAS
            )
        ),
        "ParticipatingNISTDivision": _slot_default(
            model.collection_slots, "participating_NIST_division", DEFAULT_DIVISION
        ),
        "OwnerPrincipal": _slot_default(
            model.collection_slots, "owner_principal", DEFAULT_OWNER_PRINCIPAL
        ),
        "collection_name": DEFAULT_COLLECTION_NAME,
        "collection_description": _slot_default(
            model.collection_slots, "collection_description", DEFAULT_COLLECTION_DESCRIPTION
        ),
        "principal_contact_name": _slot_default(
            model.collection_slots, "principal_contact_name", DEFAULT_PRINCIPAL_NAME
        ),
        "principal_contact_email": _slot_default(
            model.collection_slots, "principal_contact_email", DEFAULT_PRINCIPAL_EMAIL
        ),
        "data_custodian_name": _slot_default(
            model.collection_slots, "data_custodian_name", DEFAULT_PRINCIPAL_NAME
        ),
        "data_custodian_email": _slot_default(
            model.collection_slots, "data_custodian_email", DEFAULT_PRINCIPAL_EMAIL
        ),
        "data_category": _slot_default(
            model.collection_slots, "data_category", DEFAULT_DATA_CATEGORY
        ),
        "core_capabilities": _as_list(
            _slot_default(
                model.collection_slots, "core_capabilities", DEFAULT_CORE_CAPABILITIES
            )
        ),
        "primary_focus_areas": _as_list(
            _slot_default(
                model.collection_slots, "primary_focus_areas", DEFAULT_PRIMARY_FOCUS_AREAS
            )
        ),
        "participating_NIST_division": _slot_default(
            model.collection_slots, "participating_NIST_division", DEFAULT_DIVISION
        ),
        "associated_consortium": _to_text(
            model.collection_slots.get("associated_consortium", SlotDefinition("", "", "", False, "", "", "")).default_value
        ),
        "owner_principal": _slot_default(
            model.collection_slots, "owner_principal", DEFAULT_OWNER_PRINCIPAL
        ),
        "collection_ID": collection,
        "collection_version": _to_text(
            model.collection_slots.get("collection_version", SlotDefinition("", "", "", False, "", "", "")).default_value
        )
        or "1",
        "id": collection,
        "labcasId": collection,
        "name": DEFAULT_COLLECTION_NAME,
        "labcasName": DEFAULT_COLLECTION_NAME,
        "labcas_node_type": "collections",
    }


def _bundle_summary(
    bundle: BundleLayout,
    components: Sequence[ComponentRecord],
    collection: str,
    model: MappingModel,
    missing_refs: Sequence[str],
) -> Dict[str, Any]:
    version = _dataset_version(bundle)
    instance_id = _bundle_instance_id(bundle, components)
    dataset_title = f"{instance_id}_v{version}"
    dataset_id = f"{collection}/{dataset_title}"
    start_time = _min_text(_component_field(component, "ActivityDateTime") for component in components)
    end_time = _max_text(_component_field(component, "ActivityDateTime") for component in components)
    input_connector = _first_nonempty(
        _component_field(component, "InputConnector") for component in components
    )
    last_activity = sorted(
        components,
        key=lambda item: (
            int(_component_field(item, "UnitOperationInstanceStep") or "0"),
            item.component_name,
        ),
    )[-1]
    output_connector = _first_nonempty(
        [
            _component_field(last_activity, "OutputConnector"),
            _first_nonempty(
                _component_field(component, "OutputConnector") for component in reversed(components)
            ),
        ]
    )
    activity_count = sum(1 for component in components if component.component_type == "Activity")
    entity_count = sum(1 for component in components if component.component_type == "Entity")

    dataset_description = (
        f"Cell expansion provenance bundle {instance_id} version {version} with "
        f"{activity_count} activities, {entity_count} entities, provenance bundle artifacts, "
        "and any associated process-monitoring files discovered from DataList references."
    )

    summary: Dict[str, Any] = {
        "dataset_title": dataset_title,
        "dataset_description": dataset_description,
        "dataset_ID": dataset_id,
        "DatasetId": dataset_id,
        "DatasetName": dataset_title,
        "DatasetVersion": version,
        "CollectionId": collection,
        "CollectionName": DEFAULT_COLLECTION_NAME,
        "DataCustodian": DEFAULT_PRINCIPAL_NAME,
        "DataCustodianEmail": DEFAULT_PRINCIPAL_EMAIL,
        "OwnerPrincipal": DEFAULT_OWNER_PRINCIPAL,
        "CollectionDescription": DEFAULT_COLLECTION_DESCRIPTION,
        "UnitOperationInstance": instance_id,
        "unit_operation_instance": instance_id,
        "component_name": instance_id,
        "component_type": "Bundle",
        "input_connector": input_connector,
        "output_connector": output_connector,
        "cell_composite_name": _first_nonempty(
            _component_field(component, "CellCompositeName") for component in components
        ),
        "cell_short_name": _first_nonempty(
            _component_field(component, "CellShortName") for component in components
        ),
        "cell_unique_id": _first_nonempty(
            _component_field(component, "CellUniqueID") for component in components
        ),
        "passage_number": _max_int_text(
            _component_field(component, "PassageNumber") for component in components
        ),
        "data_capture_start_date": start_time,
        "data_capture_end_date": end_time,
        "original_upload_location": str(bundle.bundle_root),
        "step": "",
        "data_submitter": DEFAULT_PRINCIPAL_NAME,
        "starting_material_type": "cell line",
        "missing_referenced_file_count": str(len(missing_refs)),
        "component_count": str(len(components)),
        "activity_count": str(activity_count),
        "entity_count": str(entity_count),
        "raw_data_category": DEFAULT_DATA_CATEGORY,
    }

    protocol_slot = model.dataset_slots.get("protocol_ID")
    if protocol_slot is not None:
        summary["protocol_ID"] = instance_id
    if bundle.workbook_file is not None:
        summary["workflow_id"] = str(bundle.workbook_file)
        summary["workflow_type"] = "Workflow"
    return summary


def _linkml_collection_payload(collection: str) -> Dict[str, Any]:
    return {
        "collection_name": DEFAULT_COLLECTION_ENUM,
        "collection_description": DEFAULT_COLLECTION_DESCRIPTION,
        "principal_contact_name": DEFAULT_PRINCIPAL_NAME,
        "principal_contact_email": DEFAULT_PRINCIPAL_EMAIL,
        "data_custodian_name": DEFAULT_PRINCIPAL_NAME,
        "data_custodian_email": DEFAULT_PRINCIPAL_EMAIL,
        "data_category": DEFAULT_LINKML_DATA_CATEGORY,
        "participating_NIST_division": [DEFAULT_DIVISION_ENUM],
        "owner_principal": DEFAULT_LINKML_OWNER_PRINCIPAL,
        "collection_ID": collection,
    }


def _linkml_dataset_payload(summary: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "dataset_title": summary["dataset_title"],
        "dataset_description": summary["dataset_description"],
        "dataset_ID": summary["dataset_ID"],
        "data_custodian_name": DEFAULT_PRINCIPAL_NAME,
        "data_custodian_email": DEFAULT_PRINCIPAL_EMAIL,
        "data_submitter": DEFAULT_PRINCIPAL_NAME,
        "starting_material_type": _linkml_starting_material_type(
            summary.get("starting_material_type", "cell line")
        ),
        "data_capture_start_date": summary.get("data_capture_start_date", ""),
        "data_capture_end_date": summary.get("data_capture_end_date", ""),
        "original_upload_location": summary.get("original_upload_location", ""),
    }
    protocol_id = summary.get("protocol_ID", "")
    if protocol_id:
        payload["protocol_ID"] = protocol_id
    return {key: value for key, value in payload.items() if value}


def _linkml_file_payload(path: Path, artifact_role: str, collection: str) -> Dict[str, Any]:
    if artifact_role == "data":
        content_type = "instrument_output"
    elif artifact_role == "schema":
        content_type = "reference_file"
    else:
        content_type = "documentation"

    return {
        "file_name": path.name,
        "data_processing_level": "raw",
        "data_file_context": "telemetry_data",
        "file_content_type": content_type,
        "collection_ID": collection,
        "owner_principal": DEFAULT_LINKML_OWNER_PRINCIPAL,
        "file_description": (
            "Cell expansion provenance artifact"
            if artifact_role != "schema"
            else "JSON schema used to validate cell expansion provenance payloads"
        ),
        "file_type_extension": _file_type_extension(path),
        "MIME_type": _mime_type(path),
        "file_size": _file_size(path),
    }


def _component_metadata(
    component: ComponentRecord,
    mapping: MappingModel,
) -> Dict[str, Any]:
    allowed_fields = set(mapping.activity_source_fields)
    metadata: Dict[str, Any] = {
        "component_name": component.component_name,
        "component_type": component.component_type,
        "ComponentName": component.component_name,
        "ComponentType": component.component_type,
    }
    raw_metadata: Dict[str, str] = {}
    preserved_extra_fields: Dict[str, str] = {}
    for source_field, value in component.attributes.items():
        raw_metadata[source_field] = value
        if source_field not in allowed_fields:
            preserved_extra_fields[source_field] = value
            continue
        schema = mapping.schema_fields.get(source_field)
        target_slot = schema.target_slot if schema else _snake_case(source_field)
        metadata[target_slot] = value
        if target_slot == "unit_operation_instance_step":
            metadata["step"] = value
    if raw_metadata:
        metadata["raw_source_metadata"] = raw_metadata
    if preserved_extra_fields:
        metadata["supplemental_source_metadata"] = preserved_extra_fields
        metadata["preserved_extra_fields"] = sorted(preserved_extra_fields.keys())
    return metadata


def _source_relative_path(path: Path, bundle_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(bundle_dir.resolve()))
    except ValueError:
        return path.name


def _component_sort_key(component: ComponentRecord) -> tuple[int, str, str]:
    step_text = _component_field(component, "UnitOperationInstanceStep") or "0"
    try:
        step = int(float(step_text))
    except ValueError:
        step = 0
    return step, component.component_type, component.component_name


def _safe_download_segment(label: str, value: str) -> str:
    safe_label = _safe_cfg_name(_snake_case(label))
    safe_value = _safe_cfg_name(_to_text(value) or "unknown")
    return f"{safe_label}-{safe_value}"


def _full_bundle_download_file_name(bundle: BundleLayout) -> str:
    return f"{_safe_download_segment('unit_operation_instance', bundle.bundle_name)}__bundle-full.json"


def _component_bundle_download_file_name(component: ComponentRecord) -> str:
    hierarchy_parts = [
        _safe_download_segment(
            "unit_operation_instance",
            _component_field(component, "UnitOperationInstance") or component.component_name,
        ),
        _safe_download_segment(
            "step",
            _component_field(component, "UnitOperationInstanceStep"),
        ),
        _safe_download_segment("component_type", component.component_type),
        _safe_download_segment("component_name", component.component_name),
    ]
    return "__".join(hierarchy_parts) + ".json"


def _preferred_component(components: Sequence[ComponentRecord]) -> ComponentRecord | None:
    if not components:
        return None
    return sorted(
        components,
        key=lambda component: (
            component.component_type != "Activity",
            _component_sort_key(component),
        ),
    )[0]


def _component_bundle_source_files(
    bundle: BundleLayout,
    components: Sequence[ComponentRecord],
    staging_dir: Path,
) -> Dict[str, Path]:
    source_files = dict(bundle.component_files)
    generated_dir = staging_dir / "bundle_artifacts" / "component_bundles"
    for component in components:
        if component.component_name in source_files:
            continue
        component_file = generated_dir / f"{component.component_name}.json"
        _write_json(component_file, [component.raw_item])
        source_files[component.component_name] = component_file
    return source_files


def _bundle_publish_sources(
    bundle: BundleLayout,
    components: Sequence[ComponentRecord],
    staging_dir: Path,
) -> List[PublishSource]:
    sources = [
        PublishSource(
            file_name=_full_bundle_download_file_name(bundle),
            source_path=bundle.collated_file,
            source_rel_path=_source_relative_path(bundle.collated_file, bundle.bundle_root),
            artifact_role="bundle_manifest",
        )
    ]

    if bundle.workbook_file is not None:
        sources.append(
            PublishSource(
                file_name=bundle.workbook_file.name,
                source_path=bundle.workbook_file,
                source_rel_path=_source_relative_path(bundle.workbook_file, bundle.bundle_root),
                artifact_role="bundle_workbook",
            )
        )

    component_files = _component_bundle_source_files(bundle, components, staging_dir)
    component_lookup = {component.component_name: component for component in components}
    for component_name in sorted(component_lookup.keys()):
        component = component_lookup[component_name]
        source_path = component_files[component_name]
        rel_path = _source_relative_path(source_path, bundle.bundle_root)
        if source_path.parent.name == "component_bundles":
            rel_path = f"Bundle Individual Files/{source_path.name}"
        sources.append(
            PublishSource(
                file_name=_component_bundle_download_file_name(component),
                source_path=source_path,
                source_rel_path=rel_path,
                artifact_role="component_bundle",
                primary_component=component,
                related_components=[component],
            )
        )

    for source_path in bundle.schema_files:
        sources.append(
            PublishSource(
                file_name=source_path.name,
                source_path=source_path,
                source_rel_path=_source_relative_path(source_path, bundle.bundle_root),
                artifact_role="schema",
            )
        )
    return sources


def _reference_publish_sources(
    bundle: BundleLayout,
    components: Sequence[ComponentRecord],
) -> tuple[List[PublishSource], List[str]]:
    reference_map: Dict[str, Dict[str, Any]] = {}
    for component in components:
        for rel_path in _parse_data_list(_component_field(component, "DataList")):
            resolved = _resolve_reference(bundle.bundle_root, rel_path)
            key = str(resolved)
            entry = reference_map.setdefault(
                key,
                {
                    "path": resolved,
                    "reference_values": [],
                    "components": [],
                },
            )
            if rel_path not in entry["reference_values"]:
                entry["reference_values"].append(rel_path)
            if component not in entry["components"]:
                entry["components"].append(component)

    publish_sources: List[PublishSource] = []
    missing_references: List[str] = []
    for entry in reference_map.values():
        source_path = entry["path"]
        if not source_path.exists():
            missing_references.extend(entry["reference_values"])
            continue
        related_components = sorted(entry["components"], key=_component_sort_key)
        publish_sources.append(
            PublishSource(
                file_name=source_path.name,
                source_path=source_path,
                source_rel_path=_source_relative_path(source_path, bundle.bundle_root),
                artifact_role="data",
                primary_component=_preferred_component(related_components),
                related_components=related_components,
                reference_values=list(entry["reference_values"]),
            )
        )
    return publish_sources, _sorted_unique(missing_references)


def _file_metadata(
    source: PublishSource,
    collection: str,
    dataset_summary: Dict[str, Any],
    mapping: MappingModel,
) -> Dict[str, Any]:
    source_path = source.source_path
    artifact_role = source.artifact_role
    metadata: Dict[str, Any] = {
        "FileName": source.file_name,
        "FileType": _file_type_extension(source_path),
        "FileSize": _file_size(source_path),
        "MIMEType": _mime_type(source_path),
        "OwnerPrincipal": DEFAULT_OWNER_PRINCIPAL,
        "DataProcessingLevel": DEFAULT_DATA_PROCESSING_LEVEL,
        "DataFileContext": DEFAULT_DATA_FILE_CONTEXT,
        "FileContentType": "Documentation" if artifact_role != "data" else DEFAULT_FILE_CONTENT_TYPE,
        "SourceRelativePath": source.source_rel_path,
        "artifact_role": artifact_role,
        "data_processing_level": "raw",
        "data_file_context": DEFAULT_DATA_FILE_CONTEXT,
        "file_content_type": "documentation" if artifact_role != "data" else "instrument_output",
        "file_description": f"Cell expansion {artifact_role.replace('_', ' ')} artifact",
        "protocol_ID": dataset_summary["UnitOperationInstance"],
        "collection_ID": collection,
        "owner_principal": DEFAULT_OWNER_PRINCIPAL,
        "raw_data_category": DEFAULT_DATA_CATEGORY,
    }

    if artifact_role == "bundle_manifest":
        metadata["download_bundle_scope"] = "dataset"
        metadata["download_bundle_type"] = "full_bundle"
    elif artifact_role == "component_bundle":
        metadata["download_bundle_scope"] = "component"
        metadata["download_bundle_type"] = "sub_bundle"
    elif artifact_role == "data":
        metadata["download_bundle_scope"] = "component"
        metadata["download_bundle_type"] = "data"

    component = source.primary_component
    if component is not None:
        metadata.update(_component_metadata(component, mapping))
        if artifact_role == "data":
            metadata["file_description"] = (
                f"Instrument output associated with {component.component_name}"
            )
        elif artifact_role == "component_bundle":
            metadata["file_description"] = (
                f"Component sub-bundle for {component.component_name}"
            )
        else:
            metadata["file_description"] = (
                f"{component.component_type} provenance component for {component.component_name}"
            )
    else:
        metadata.update(
            {
                "component_name": dataset_summary["dataset_title"],
                "component_type": "BundleArtifact" if artifact_role != "schema" else "Schema",
                "unit_operation_instance": dataset_summary["UnitOperationInstance"],
                "step": dataset_summary.get("step", ""),
                "cell_composite_name": dataset_summary.get("cell_composite_name", ""),
                "input_connector": dataset_summary.get("input_connector", ""),
                "output_connector": dataset_summary.get("output_connector", ""),
                "passage_number": dataset_summary.get("passage_number", ""),
            }
        )
    if source.related_components:
        metadata["related_component_names"] = [
            component.component_name for component in source.related_components
        ]
        metadata["related_component_types"] = [
            component.component_type for component in source.related_components
        ]
    if source.reference_values:
        metadata["data_list_references"] = list(source.reference_values)
    return metadata


def _copy_publishable_file(source_path: Path, archive_file: Path) -> None:
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, archive_file)


def build_aggregate_bundle_payload(components: Sequence[ComponentRecord]) -> List[Dict[str, Any]]:
    return [component.raw_item for component in components]


def _build_download_packages(
    dataset_summary: Dict[str, Any],
    components: Sequence[ComponentRecord],
    artifacts: Sequence[FileArtifact],
) -> Dict[str, Any]:
    full_bundle_file_ids = [
        artifact.file_id for artifact in artifacts if artifact.artifact_role == "bundle_manifest"
    ]
    supporting_bundle_file_ids = [
        artifact.file_id
        for artifact in artifacts
        if artifact.artifact_role in {"schema", "bundle_workbook"}
    ]
    data_file_ids = [artifact.file_id for artifact in artifacts if artifact.artifact_role == "data"]
    component_bundle_ids = {
        artifact.metadata.get("component_name", ""): artifact.file_id
        for artifact in artifacts
        if artifact.artifact_role == "component_bundle"
    }

    data_file_ids_by_component: Dict[str, List[str]] = {}
    for artifact in artifacts:
        if artifact.artifact_role != "data":
            continue
        related_names = artifact.metadata.get("related_component_names", [])
        if not isinstance(related_names, list):
            related_names = _as_list(related_names)
        for component_name in related_names:
            bucket = data_file_ids_by_component.setdefault(component_name, [])
            if artifact.file_id not in bucket:
                bucket.append(artifact.file_id)

    component_packages = []
    for component in sorted(components, key=_component_sort_key):
        component_bundle_id = component_bundle_ids.get(component.component_name, "")
        component_data_file_ids = sorted(data_file_ids_by_component.get(component.component_name, []))
        bundle_file_ids = [component_bundle_id] if component_bundle_id else []
        component_packages.append(
            {
                "component_name": component.component_name,
                "component_type": component.component_type,
                "step": _component_field(component, "UnitOperationInstanceStep"),
                "activity_base_type": _component_field(component, "ActivityBaseType"),
                "bundle_file_ids": bundle_file_ids,
                "data_file_ids": component_data_file_ids,
                "everything_file_ids": _sorted_unique(bundle_file_ids + component_data_file_ids),
            }
        )

    aggregate_examples = []
    activity_groups: Dict[str, List[ComponentRecord]] = {}
    for component in components:
        activity_base_type = _component_field(component, "ActivityBaseType")
        if activity_base_type:
            activity_groups.setdefault(activity_base_type, []).append(component)
    for activity_base_type, grouped_components in sorted(activity_groups.items()):
        aggregate_examples.append(
            {
                "selector": {"activity_base_type": activity_base_type},
                "component_names": [component.component_name for component in grouped_components],
                "bundle_payload": build_aggregate_bundle_payload(grouped_components),
            }
        )

    return {
        "dataset_packages": {
            "bundle": {
                "bundle_file_ids": full_bundle_file_ids,
                "data_file_ids": [],
                "everything_file_ids": full_bundle_file_ids,
            },
            "data": {
                "bundle_file_ids": [],
                "data_file_ids": data_file_ids,
                "everything_file_ids": data_file_ids,
            },
            "everything": {
                "bundle_file_ids": full_bundle_file_ids + supporting_bundle_file_ids,
                "data_file_ids": data_file_ids,
                "everything_file_ids": _sorted_unique(
                    full_bundle_file_ids + supporting_bundle_file_ids + data_file_ids
                ),
            },
        },
        "component_packages": component_packages,
        "aggregate_bundle_recipes": {
            "builder": "concatenate_selected_component_bundles",
            "supported_selector_fields": [
                "component_name",
                "component_type",
                "activity_base_type",
                "step",
                "input_connector",
                "output_connector",
            ],
            "examples": aggregate_examples,
        },
        "dataset_id": dataset_summary["DatasetId"],
    }


def _build_normalized_manifest(
    collection: str,
    collection_metadata: Dict[str, Any],
    dataset_summary: Dict[str, Any],
    artifacts: Sequence[FileArtifact],
    download_packages: Dict[str, Any],
) -> Dict[str, Any]:
    dataset_metadata = {
        key: value
        for key, value in dataset_summary.items()
        if key
        not in {
            "DatasetId",
            "DatasetName",
            "DatasetVersion",
            "CollectionId",
            "CollectionName",
            "dataset_ID",
            "dataset_title",
            "dataset_description",
        }
    }
    files = []
    for artifact in artifacts:
        files.append(
            {
                "id": artifact.file_id,
                "parent_id": dataset_summary["DatasetId"],
                "name": artifact.file_name,
                "path": artifact.file_id,
                "metadata": {
                    key: value
                    for key, value in artifact.metadata.items()
                    if key
                    not in {
                        "FileName",
                        "FileId",
                        "DatasetId",
                        "DatasetName",
                        "DatasetVersion",
                        "CollectionId",
                        "CollectionName",
                        "id",
                    }
                },
            }
        )

    return {
        "version": MANIFEST_VERSION,
        "format": "labcas_normalized_manifest",
        "collection": {
            "id": collection,
            "name": DEFAULT_COLLECTION_NAME,
            "metadata": {
                key: value
                for key, value in collection_metadata.items()
                if key not in {"id", "labcasId", "labcasName", "name", "labcas_node_type"}
            },
        },
        "datasets": [
            {
                "id": dataset_summary["DatasetId"],
                "parent_id": collection,
                "name": dataset_summary["dataset_title"],
                "metadata": dataset_metadata,
            }
        ],
        "files": files,
        "packages": download_packages,
    }


def generate(
    bundle_dir: Path,
    workbook_path: Path,
    output_dir: Path,
    staging_dir: Path,
    archive_root: Path,
    collection: str = DEFAULT_COLLECTION,
) -> Dict[str, Any]:
    mapping = load_mapping_model(workbook_path)
    bundle = discover_bundle_layout(bundle_dir)
    components = load_components(bundle)

    allowed_source_fields = set(mapping.activity_source_fields)

    source_fields = sorted(
        {field for component in components for field in component.attributes.keys()}
        | {"ComponentName", "ComponentType"}
    )
    fields_outside_activity_allowlist = sorted(
        field
        for field in source_fields
        if field not in allowed_source_fields and field not in {"ComponentName", "ComponentType"}
    )
    mapped_fields = set(mapping.schema_fields.keys())
    unmapped_source_fields = sorted(
        field for field in source_fields if field in allowed_source_fields and field not in mapped_fields
    )
    unmatched_mapping_rows = sorted(
        field
        for field in mapping.schema_fields.keys()
        if field in allowed_source_fields and field not in source_fields
    )
    entity_only_preserved_fields = sorted(
        {
            field
            for component in components
            if component.component_type == "Entity"
            for field in component.attributes.keys()
            if field not in allowed_source_fields
        }
    )

    missing_required_values: List[Dict[str, str]] = []
    for component in components:
        for field in component.required_fields:
            if not _component_field(component, field):
                missing_required_values.append(
                    {
                        "component_name": component.component_name,
                        "field": field,
                    }
                )

    resolved_reference_sources, missing_referenced_files = _reference_publish_sources(
        bundle, components
    )

    collection_metadata = _collection_metadata(mapping, collection)
    dataset_summary = _bundle_summary(
        bundle=bundle,
        components=components,
        collection=collection,
        model=mapping,
        missing_refs=missing_referenced_files,
    )

    metadata_root = output_dir / collection
    dataset_dir = metadata_root / dataset_summary["dataset_title"]
    archive_dataset_dir = archive_root / collection / dataset_summary["dataset_title"]

    for path in [
        dataset_dir,
        archive_dataset_dir,
        staging_dir / "bulk",
        staging_dir / "files_bulk",
        staging_dir / "bundle_artifacts",
    ]:
        if path.exists():
            shutil.rmtree(path)
    for path in [
        staging_dir / "collectionlevel.yaml",
        staging_dir / "download_packages.json",
        staging_dir / "ingestion_report.json",
    ]:
        if path.exists():
            path.unlink()

    dataset_dir.mkdir(parents=True, exist_ok=True)
    archive_dataset_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    collection_cfg = metadata_root / f"{collection}.cfg"
    collection_json = metadata_root / f"{collection}.json"
    _write_cfg(collection_cfg, "Collection", collection_metadata)
    _write_json(collection_json, collection_metadata)

    dataset_cfg = dataset_dir / f"{dataset_summary['dataset_title']}.cfg"
    dataset_fields = dict(dataset_summary)
    dataset_fields.update(
        {
            "id": str(dataset_dir),
            "CollectionDescription": collection_metadata["CollectionDescription"],
            "primary_facet_fields": DEFAULT_PRIMARY_FACET_FIELDS,
            "non_primary_facet_fields": DEFAULT_NON_PRIMARY_FACET_FIELDS,
            "activity_source_allowlist": mapping.activity_source_fields,
        }
    )
    _write_cfg(dataset_cfg, "Dataset", dataset_fields)

    collection_payload = _linkml_collection_payload(collection)
    collection_payload_file = staging_dir / "collectionlevel.yaml"
    _write_yaml(collection_payload_file, collection_payload)

    dataset_payload = _linkml_dataset_payload(dataset_summary)
    dataset_payload_file = staging_dir / "bulk" / f"{dataset_summary['dataset_title']}.yaml"
    _write_yaml(dataset_payload_file, dataset_payload)

    dataset_manifest = [
        {
            "dataset_key": dataset_summary["dataset_title"],
            "dataset_id": dataset_summary["DatasetId"],
            "mapped_file": str(dataset_payload_file),
            "file_cfg": str(dataset_cfg),
            "archive_file": str(archive_dataset_dir),
        }
    ]
    dataset_manifest_file = staging_dir / "bulk" / "validation_manifest.json"
    _write_json(dataset_manifest_file, dataset_manifest)

    artifacts: List[FileArtifact] = []
    file_manifest_rows: List[Dict[str, str]] = []

    publishable_sources = _bundle_publish_sources(bundle, components, staging_dir)
    publishable_sources.extend(resolved_reference_sources)

    for index, source in enumerate(publishable_sources, start=1):
        file_name = source.file_name
        file_id = f"{dataset_summary['DatasetId']}/{file_name}"
        archive_file = archive_dataset_dir / file_name
        _copy_publishable_file(source.source_path, archive_file)

        metadata = _file_metadata(
            source=source,
            collection=collection,
            dataset_summary=dataset_summary,
            mapping=mapping,
        )
        metadata.update(
            {
                "CollectionId": collection,
                "CollectionName": DEFAULT_COLLECTION_NAME,
                "DatasetId": dataset_summary["DatasetId"],
                "DatasetName": dataset_summary["dataset_title"],
                "DatasetVersion": dataset_summary["DatasetVersion"],
                "FileName": file_name,
                "FileId": file_id,
                "id": file_id,
            }
        )

        cfg_file = dataset_dir / f"{file_name}.cfg"
        _write_cfg(cfg_file, "File", metadata)

        linkml_payload = _linkml_file_payload(
            path=source.source_path,
            artifact_role=source.artifact_role,
            collection=collection,
        )
        mapped_file = (
            staging_dir
            / "files_bulk"
            / f"{index:04d}_{_safe_cfg_name(file_name.lower())}.yaml"
        )
        _write_yaml(mapped_file, linkml_payload)

        artifacts.append(
            FileArtifact(
                file_name=file_name,
                source_path=source.source_path,
                source_rel_path=source.source_rel_path,
                archive_file=archive_file,
                file_id=file_id,
                metadata=metadata,
                linkml_payload=linkml_payload,
                cfg_file=cfg_file,
                mapped_file=mapped_file,
                artifact_role=source.artifact_role,
            )
        )
        file_manifest_rows.append(
            {
                "file_id": file_id,
                "mapped_file": str(mapped_file),
                "cfg_file": str(cfg_file),
                "archive_file": str(archive_file),
            }
        )

    file_manifest_file = staging_dir / "files_bulk" / "file_validation_manifest.json"
    _write_json(file_manifest_file, file_manifest_rows)

    download_packages = _build_download_packages(
        dataset_summary=dataset_summary,
        components=components,
        artifacts=artifacts,
    )
    download_packages_file = staging_dir / "download_packages.json"
    _write_json(download_packages_file, download_packages)

    normalized_manifest = _build_normalized_manifest(
        collection=collection,
        collection_metadata=collection_metadata,
        dataset_summary=dataset_summary,
        artifacts=artifacts,
        download_packages=download_packages,
    )
    normalized_manifest_file = metadata_root / f"{collection}.manifest.json"
    _write_json(normalized_manifest_file, normalized_manifest)

    report = {
        "collection": collection,
        "dataset_id": dataset_summary["DatasetId"],
        "dataset_title": dataset_summary["dataset_title"],
        "dataset_version": dataset_summary["DatasetVersion"],
        "bundle_dir": str(bundle.bundle_root),
        "collated_bundle_file": str(bundle.collated_file),
        "workbook_path": str(workbook_path),
        "activity_source_allowlist": mapping.activity_source_fields,
        "entity_source_fields": mapping.entity_source_fields,
        "fields_outside_activity_allowlist": fields_outside_activity_allowlist,
        "entity_only_preserved_fields": entity_only_preserved_fields,
        "primary_facet_fields": DEFAULT_PRIMARY_FACET_FIELDS,
        "non_primary_facet_fields": DEFAULT_NON_PRIMARY_FACET_FIELDS,
        "component_count": len(components),
        "publishable_file_count": len(artifacts),
        "resolved_reference_file_count": len(resolved_reference_sources),
        "missing_referenced_file_count": len(missing_referenced_files),
        "missing_referenced_files": _sorted_unique(missing_referenced_files),
        "unmapped_source_fields": unmapped_source_fields,
        "unused_mapping_rows": unmatched_mapping_rows,
        "missing_required_values": missing_required_values,
        "synthetic_component_bundle_count": sum(
            1 for component in components if component.source_file is None
        ),
        "download_packages_file": str(download_packages_file),
        "publishable_files": [
            {
                "file_name": artifact.file_name,
                "source_rel_path": artifact.source_rel_path,
                "artifact_role": artifact.artifact_role,
                "archive_file": str(artifact.archive_file),
                "cfg_file": str(artifact.cfg_file),
            }
            for artifact in artifacts
        ],
    }
    report_file = staging_dir / "ingestion_report.json"
    _write_json(report_file, report)

    if missing_referenced_files:
        LOG.warning(
            "Missing referenced files (%d): %s",
            len(_sorted_unique(missing_referenced_files)),
            ", ".join(_sorted_unique(missing_referenced_files)),
        )
    if missing_required_values:
        LOG.warning("Missing required component values: %d", len(missing_required_values))
    if unmapped_source_fields:
        LOG.warning("Unmapped source fields: %s", ", ".join(unmapped_source_fields))
    if fields_outside_activity_allowlist:
        LOG.warning(
            "Fields seen outside activity allowlist: %s",
            ", ".join(fields_outside_activity_allowlist),
        )
    if entity_only_preserved_fields:
        LOG.info(
            "Preserved entity-only fields outside activity allowlist: %s",
            ", ".join(entity_only_preserved_fields),
        )
    if unmatched_mapping_rows:
        LOG.warning("Mapping rows not matched in source: %s", ", ".join(unmatched_mapping_rows))

    LOG.info(
        "Generated collection=%s dataset=%s files=%d manifest=%s",
        collection,
        dataset_summary["dataset_title"],
        len(artifacts),
        normalized_manifest_file,
    )

    return {
        "collection_cfg": str(collection_cfg),
        "dataset_cfg": str(dataset_cfg),
        "collection_payload": str(collection_payload_file),
        "dataset_manifest": str(dataset_manifest_file),
        "file_manifest": str(file_manifest_file),
        "download_packages": str(download_packages_file),
        "normalized_manifest": str(normalized_manifest_file),
        "report": str(report_file),
        "dataset_id": dataset_summary["DatasetId"],
        "file_count": len(artifacts),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse a cell expansion provenance bundle into LabCAS metadata and staged validation payloads.",
    )
    parser.add_argument(
        "--bundle-dir",
        default="/data/raw/CellExpansion-04092026_Bundle",
        help="Directory containing the cell expansion bundle.",
    )
    parser.add_argument(
        "--workbook",
        default="/data/raw/conf/CellLineCrossWalk.xlsx",
        help="Excel workbook containing the mapping model.",
    )
    parser.add_argument(
        "--output-dir",
        default="/metadata",
        help="Metadata root where collection/dataset/file cfgs are written.",
    )
    parser.add_argument(
        "--staging-dir",
        default="/data/staging/cell_expansion",
        help="Directory for LinkML YAML payloads, manifests, and ingestion reports.",
    )
    parser.add_argument(
        "--archive-root",
        default="/data/archive/nist",
        help="Archive root where publishable files are copied.",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help="Collection id/directory name for the generated metadata.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    result = generate(
        bundle_dir=Path(args.bundle_dir),
        workbook_path=Path(args.workbook),
        output_dir=Path(args.output_dir),
        staging_dir=Path(args.staging_dir),
        archive_root=Path(args.archive_root),
        collection=args.collection,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

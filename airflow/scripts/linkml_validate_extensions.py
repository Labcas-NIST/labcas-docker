#!/usr/bin/env python3
"""Validate Flow Cytometry and/or Cell Provenance records with NIST LinkML.

The Flow Cytometry workbook values use human-readable enum titles.  The generated
LinkML datamodel expects enum codes, so this validator performs a deterministic
title-to-code normalization before loading each record.

The Cell Provenance bundle separates activities from their resulting entities.
This validator reconstructs the connector/activity fields required by the
CellLineExpansionExtension and reports every derived field in the audit log.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml
from nist_labcas_linkml.datamodel import nist_labcas_linkml as model


FLOW_CLASS = "FlowCytometryStandardsConsortiumExtention"
CELL_CLASS = "CellLineExpansionExtension"

FLOW_SLOT_MAP = {
    "WorkingGroup": "working_group",
    "InstrumentCode": "instrument_code",
    "ExperimentType": "experiment_type",
    "SiteCode": "site_code",
    "MaterialCode": "material_code",
    "SampleName": "sample_name",
    "ExperimentID": "experiment_ID",
    "DataFormat": "data_format",
    "StudyID": "study_ID",
    "PrincipleContactID": "principal_contact_ID",
    "DataProcessingLevel": "data_processing_level",
    "ReplicateNumber": "replicate_number",
    "ProtocolID": "protocol_ID",
}

CELL_SLOT_MAP = {
    "ActivityDateTime": "activity_date_time",
    "PreviousDateTime": "previous_date_time",
    "DeltaTime": "delta_time",
    "UnitOperationInstance": "unit_operation_instance",
    "UnitOperationInstanceStep": "unit_operation_instance_step",
    "CellCompositeName": "cell_composite_name",
    "CellShortName": "cell_short_name",
    "CellUniqueID": "cell_unique_id",
    "PassageNumber": "passage_number",
    "CultureContainerReplicateMultiplier": "culture_container_replicate_multiplier",
    "CultureContainerReplicateNumber": "culture_container_replicate_number",
    "CultureContainerReplicateCode": "culture_container_replicate_code",
    "PreviousCultureContainerReplicateCode": "previous_culture_container_replicate_code",
    "DataList": "data_list",
    "InputConnector": "input_connector",
    "OutputConnector": "output_connector",
}

CELL_INT_SLOTS = {
    "unit_operation_instance_step",
    "passage_number",
    "culture_container_replicate_multiplier",
    "culture_container_replicate_number",
}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _enum_code(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")


def _flow_value(slot: str, value: str) -> str:
    if slot == "experiment_type":
        return _enum_code(value).lower()
    if slot in {
        "instrument_code",
        "site_code",
        "material_code",
        "sample_name",
        "study_ID",
        "principal_contact_ID",
    }:
        return _enum_code(value)
    if slot == "data_processing_level":
        return value.lower()
    return value


def _validate_flow(manifest_path: Path, verbose_pass: bool) -> Tuple[int, int]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload.get("files", [])
    if not isinstance(files, list) or not files:
        raise ValueError(f"Flow Cytometry manifest has no file records: {manifest_path}")

    klass = getattr(model, FLOW_CLASS)
    passed = 0
    failed = 0
    print(f"SOURCE group=flow_cytometry path={manifest_path} records={len(files)}")
    for index, record in enumerate(files, start=1):
        metadata = record.get("metadata", {})
        mapped = {
            target: _flow_value(target, str(metadata[source]).strip())
            for source, target in FLOW_SLOT_MAP.items()
            if str(metadata.get(source, "")).strip()
        }
        mapped["FCSC_ILS_filename"] = str(record.get("name", "")).strip()
        label = str(record.get("id") or record.get("path") or f"record-{index}")
        try:
            klass(**mapped)
            passed += 1
            if verbose_pass:
                print(
                    f"EXTENSION PASS group=flow_cytometry class={FLOW_CLASS} "
                    f"label={label}"
                )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(
                f"EXTENSION FAIL group=flow_cytometry class={FLOW_CLASS} "
                f"label={label} error={type(exc).__name__}: {exc}"
            )
    print(
        f"EXTENSION SUMMARY group=flow_cytometry class={FLOW_CLASS} "
        f"total={len(files)} passes={passed} fails={failed}"
    )
    return passed, failed


def _cell_attributes(component: Dict[str, Any]) -> Dict[str, Any]:
    return {
        str(item.get("VariableName", "")): item.get("Value")
        for item in component.get("Attributes", [])
        if str(item.get("VariableName", "")).strip()
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _iso_datetime(value: str) -> str:
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", value)
    if not match:
        return value
    year, month, day, hour, minute, second = match.groups()
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}Z"


def _activity_type(component_name: str) -> str:
    suffix = component_name.rsplit("_", 1)[-1]
    normalized = suffix.replace("-", "")
    aliases = {
        "Start": "Start",
        "Passage": "Passage",
        "Monitor": "Monitor",
        "MediaChange": "MediaChange",
        "End": "End",
    }
    if normalized not in aliases:
        raise ValueError(f"Cannot derive activity type from component name: {component_name}")
    return aliases[normalized]


def _step(attributes: Dict[str, Any]) -> int:
    value = _text(attributes.get("UnitOperationInstanceStep")) or "0"
    return int(float(value))


def _connector_cell_name(*values: str) -> str:
    for value in values:
        if not value:
            continue
        if "_CellExpansion-" in value:
            return value.split("_CellExpansion-", 1)[0]
        if "_" in value:
            return value.split("_", 1)[0]
    return ""


def _replicate_code(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"_(rep[^_]+)$", value, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _data_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if _text(item)]
    text = _text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [text]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if _text(item)]
    return [str(parsed)]


def _schema_required_rule_slots(schema_path: Path) -> Dict[str, List[str]]:
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    rules = schema["classes"][CELL_CLASS].get("rules", [])
    required: Dict[str, List[str]] = {}
    for rule in rules:
        preconditions = rule.get("preconditions", {}).get("slot_conditions", {})
        condition = preconditions.get("activity_base_type", {})
        activity_type = condition.get("equals_string")
        if not activity_type:
            continue
        postconditions = rule.get("postconditions", {}).get("slot_conditions", {})
        required[activity_type] = sorted(
            slot for slot, settings in postconditions.items() if settings.get("required")
        )
    return required


def _validate_cell(
    bundle_path: Path, schema_path: Path, verbose_pass: bool
) -> Tuple[int, int]:
    components = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(components, list) or not components:
        raise ValueError(f"Cell Provenance bundle has no component records: {bundle_path}")

    indexed: List[Tuple[Dict[str, Any], Dict[str, Any]]] = [
        (component, _cell_attributes(component)) for component in components
    ]
    activities_by_step = {
        _step(attributes): (component, attributes)
        for component, attributes in indexed
        if _text(component.get("ComponentType")) == "Activity"
    }
    entities_by_step = {
        _step(attributes): (component, attributes)
        for component, attributes in indexed
        if _text(component.get("ComponentType")) == "Entity"
    }
    required_by_activity = _schema_required_rule_slots(schema_path)
    klass = getattr(model, CELL_CLASS)
    passed = 0
    failed = 0
    print(f"SOURCE group=cell_provenance path={bundle_path} records={len(components)}")

    for component, attributes in indexed:
        step = _step(attributes)
        activity_component, activity_attributes = activities_by_step[step]
        entity_component, entity_attributes = entities_by_step[step]
        activity_type = _activity_type(_text(activity_component.get("ComponentName")))
        mapped: Dict[str, Any] = {
            "component_name": _text(component.get("ComponentName")),
            "component_type": _text(component.get("ComponentType")),
            "activity_base_type": activity_type,
        }
        derived: List[str] = ["activity_base_type"]

        for source, target in CELL_SLOT_MAP.items():
            value = attributes.get(source)
            text = _text(value)
            if not text:
                continue
            if target in CELL_INT_SLOTS:
                mapped[target] = int(float(text))
            elif target in {"activity_date_time", "previous_date_time"}:
                mapped[target] = _iso_datetime(text)
            elif target == "data_list":
                mapped[target] = _data_list(value)
            else:
                mapped[target] = text

        activity_input = _text(activity_attributes.get("InputConnector"))
        activity_output = _text(activity_attributes.get("OutputConnector"))
        entity_name = _text(entity_component.get("ComponentName"))
        if not mapped.get("input_connector"):
            mapped["input_connector"] = activity_input
            derived.append("input_connector")
        if not mapped.get("output_connector"):
            mapped["output_connector"] = activity_output or entity_name
            derived.append("output_connector")
        if not mapped.get("cell_composite_name"):
            mapped["cell_composite_name"] = _connector_cell_name(
                entity_name,
                mapped.get("input_connector", ""),
                mapped.get("output_connector", ""),
            )
            derived.append("cell_composite_name")
        if not mapped.get("activity_date_time") and _text(
            entity_attributes.get("ActivityDateTime")
        ):
            mapped["activity_date_time"] = _iso_datetime(
                _text(entity_attributes["ActivityDateTime"])
            )
            derived.append("activity_date_time")
        if not mapped.get("passage_number") and _text(entity_attributes.get("PassageNumber")):
            mapped["passage_number"] = int(float(_text(entity_attributes["PassageNumber"])))
            derived.append("passage_number")
        if not mapped.get("culture_container_replicate_code"):
            code = _text(entity_attributes.get("CultureContainerReplicateCode"))
            code = code or _replicate_code(entity_name)
            if code:
                mapped["culture_container_replicate_code"] = code
                derived.append("culture_container_replicate_code")
        if activity_type == "Passage" and not mapped.get(
            "previous_culture_container_replicate_code"
        ):
            previous_code = _replicate_code(mapped.get("input_connector", ""))
            if previous_code:
                mapped["previous_culture_container_replicate_code"] = previous_code
                derived.append("previous_culture_container_replicate_code")
        if activity_type == "Start":
            composite = mapped.get("cell_composite_name", "")
            if not mapped.get("cell_short_name") and composite:
                mapped["cell_short_name"] = composite.split("-rack", 1)[0]
                derived.append("cell_short_name")
            if not mapped.get("cell_unique_id") and "-rack" in composite:
                mapped["cell_unique_id"] = "rack" + composite.split("-rack", 1)[1]
                derived.append("cell_unique_id")

        label = mapped["component_name"]
        try:
            klass(**mapped)
            missing_rule_slots = [
                slot
                for slot in required_by_activity.get(activity_type, [])
                if mapped.get(slot) in (None, "", [])
            ]
            if missing_rule_slots:
                raise ValueError(
                    "LinkML rule requires populated slots: " + ", ".join(missing_rule_slots)
                )
            passed += 1
            print(
                f"DERIVED group=cell_provenance label={label} fields={','.join(sorted(set(derived)))}"
            )
            if verbose_pass:
                print(
                    f"EXTENSION PASS group=cell_provenance class={CELL_CLASS} "
                    f"label={label}"
                )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(
                f"EXTENSION FAIL group=cell_provenance class={CELL_CLASS} "
                f"label={label} derived={','.join(sorted(set(derived)))} "
                f"error={type(exc).__name__}: {exc}"
            )

    print(
        f"EXTENSION SUMMARY group=cell_provenance class={CELL_CLASS} "
        f"total={len(components)} passes={passed} fails={failed}"
    )
    return passed, failed


def _require_files(paths: Iterable[Path]) -> None:
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Required validation input not found: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Flow Cytometry and/or Cell Provenance records."
    )
    parser.add_argument("--flow-manifest")
    parser.add_argument("--cell-bundle")
    parser.add_argument("--schema")
    parser.add_argument("--verbose-pass", default="true")
    parser.add_argument("--strict", default="true")
    args = parser.parse_args()

    if not args.flow_manifest and not args.cell_bundle:
        parser.error("provide --flow-manifest, --cell-bundle, or both")
    if args.cell_bundle and not args.schema:
        parser.error("--schema is required with --cell-bundle")

    verbose_pass = _parse_bool(args.verbose_pass)
    flow_fails = 0
    cell_fails = 0
    if args.flow_manifest:
        flow_manifest = Path(args.flow_manifest)
        _require_files([flow_manifest])
        _, flow_fails = _validate_flow(flow_manifest, verbose_pass)
    if args.cell_bundle:
        cell_bundle = Path(args.cell_bundle)
        schema_path = Path(args.schema)
        _require_files([cell_bundle, schema_path])
        _, cell_fails = _validate_cell(cell_bundle, schema_path, verbose_pass)
    total_fails = flow_fails + cell_fails
    print(
        f"EXTENSION OVERALL flow_fails={flow_fails} cell_fails={cell_fails} "
        f"total_fails={total_fails} strict={_parse_bool(args.strict)}"
    )
    return 1 if _parse_bool(args.strict) and total_fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

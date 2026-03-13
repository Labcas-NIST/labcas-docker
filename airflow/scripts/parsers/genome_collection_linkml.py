#!/usr/bin/env python3
"""Map collection metadata JSON into LinkML CollectionLevel YAML."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml


def _first_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            text = str(item).strip()
            if text:
                return text
        return ""
    return str(value).strip()


def _as_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def _norm_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _pick_collection_enum(raw: Dict[str, Any], default_value: str) -> str:
    candidates = [
        _first_text(raw.get("CollectionId")),
        _first_text(raw.get("CollectionName")),
        _first_text(raw.get("Collection")),
    ]
    for candidate in candidates:
        token = _norm_token(candidate)
        if not token:
            continue
        if "genome" in token and "editing" in token:
            return "genome_editing_consortium"
        if "flow" in token and "cyto" in token:
            return "flow_cytometry_standards_consortium"
        if "microbial" in token:
            return "microbial_metrology"
        if "cell" in token and "line" in token:
            return "cell_line_Provenance"
        if "wg2" in token:
            return "NIST_GEC_WG2_schema"
    return default_value


def _pick_data_category(raw: Dict[str, Any], default_value: str) -> str:
    candidates = (
        _as_text_list(raw.get("DataCategory"))
        + _as_text_list(raw.get("StudyType"))
        + _as_text_list(raw.get("Discipline"))
    )
    for candidate in candidates:
        token = _norm_token(candidate)
        if "interlab" in token or "inter_laboratory" in token:
            return "interlaboratory_study"
        if "maint" in token:
            return "maintenance"
        if "character" in token:
            return "characterization"
    return default_value


def _pick_divisions(raw: Dict[str, Any], default_value: str) -> List[str]:
    candidates = (
        _as_text_list(raw.get("ParticipatingNISTDivision"))
        + _as_text_list(raw.get("Participating_NIST_division"))
        + _as_text_list(raw.get("NISTDivision"))
    )
    mapped: List[str] = []
    for candidate in candidates:
        token = _norm_token(candidate)
        if token.startswith("630") or "material_measurement_laboratory_office" in token:
            mapped.append("630_material_measurement_laboratory_office")
        elif token.startswith("640") or "office_of_reference_materials" in token:
            mapped.append("640_office_of_reference_materials")
        elif token.startswith("641") or "office_of_data_and_informatics" in token:
            mapped.append("641_office_of_data_and_informatics")
        elif token.startswith("642") or "materials_science_and_engineering" in token:
            mapped.append("642_materials_science_and_engineering_division")
        elif token.startswith("643") or "materials_measurement_science" in token:
            mapped.append("643_materials_measurement_science_division")
        elif token.startswith("644") or "biosystems" in token:
            mapped.append("644_biosystems_and_biomaterials_division")
        elif token.startswith("645") or "biomolecular" in token:
            mapped.append("645_biomolecular_measurement_division")
        elif token.startswith("646") or "chemical_sciences" in token:
            mapped.append("646_chemical_sciences_division")
        elif token.startswith("647") or "applied_chemicals" in token:
            mapped.append("647_applied_chemicals_and_materials_division")
        elif token in {
            "630_material_measurement_laboratory_office",
            "640_office_of_reference_materials",
            "641_office_of_data_and_informatics",
            "642_materials_science_and_engineering_division",
            "643_materials_measurement_science_division",
            "644_biosystems_and_biomaterials_division",
            "645_biomolecular_measurement_division",
            "646_chemical_sciences_division",
            "647_applied_chemicals_and_materials_division",
        }:
            mapped.append(token)
    if not mapped:
        mapped = [default_value]
    deduped: List[str] = []
    seen = set()
    for value in mapped:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def map_collection(
    raw: Dict[str, Any],
    default_collection_enum: str,
    default_data_category: str,
    default_division: str,
) -> Dict[str, Any]:
    principal_name = (
        _first_text(raw.get("principal_contact_name"))
        or _first_text(raw.get("PrincipalContactName"))
        or _first_text(raw.get("LeadPoC"))
    )
    if not principal_name:
        principal_name = "Unknown Principal Contact"

    payload: Dict[str, Any] = {
        "collection_name": _pick_collection_enum(raw, default_collection_enum),
        "principal_contact_name": principal_name,
        "data_category": _pick_data_category(raw, default_data_category),
        "participating_NIST_division": _pick_divisions(raw, default_division),
    }

    optional_map = {
        "collection_description": _first_text(raw.get("CollectionDescription")),
        "principal_contact_email": _first_text(raw.get("LeadPoCEmail")),
        "data_custodian_name": _first_text(raw.get("DataCustodian")),
        "data_custodian_email": _first_text(raw.get("DataCustodianEmail")),
        "associated_consortium": _first_text(raw.get("Consortium")),
        "collection_ID": _first_text(raw.get("CollectionId")),
        "owner_principal": _first_text(raw.get("OwnerPrincipal")),
        "collection_version": _first_text(raw.get("CollectionVersion")),
        "URL_link": _first_text(raw.get("CollectionUrl")),
        "URL_link_description": _first_text(raw.get("CollectionUrlDescription")),
    }
    for key, value in optional_map.items():
        if value:
            payload[key] = value
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Map collection metadata JSON to LinkML CollectionLevel YAML.",
    )
    parser.add_argument(
        "--input-file",
        default="/data/raw/genome_editing_consortium/collection_metadata.json",
        help="Path to collection metadata JSON.",
    )
    parser.add_argument(
        "--output-file",
        default="/data/staging/genome_editing_consortium/collectionlevel.yaml",
        help="Destination CollectionLevel YAML path.",
    )
    parser.add_argument(
        "--default-collection-enum",
        default="genome_editing_consortium",
        help="Fallback value for CollectionEnum when source fields are ambiguous.",
    )
    parser.add_argument(
        "--default-data-category",
        default="interlaboratory_study",
        help="Fallback DataCategoryEnum value.",
    )
    parser.add_argument(
        "--default-division",
        default="644_biosystems_and_biomaterials_division",
        help="Fallback ParticipatingNISTDivisionEnum value.",
    )
    args = parser.parse_args()

    src = Path(args.input_file)
    if not src.exists():
        raise FileNotFoundError(f"Input file not found: {src}")

    raw = json.loads(src.read_text(encoding="utf-8"))
    mapped = map_collection(
        raw=raw,
        default_collection_enum=args.default_collection_enum,
        default_data_category=args.default_data_category,
        default_division=args.default_division,
    )

    out = Path(args.output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(mapped, sort_keys=False), encoding="utf-8")
    print(f"Wrote mapped CollectionLevel payload to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

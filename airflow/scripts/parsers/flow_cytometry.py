#!/usr/bin/env python3
"""
Flow Cytometry (NIST WG1/WG2/WG3) metadata parser.

Reads WG spreadsheets from an input directory, builds a dataset hierarchy
(WorkingGroup → InstrumentCode → SiteCode → ProtocolID → …), and writes
LabCAS-style cfg files under the chosen output directory.

It can also emit a single normalized manifest JSON that captures the same
collection/dataset/file structure in one document.

CLI usage:
  python flow_cytometry.py --input-dir /data/raw --output-dir /metadata \
                           --collection fcs_interlab_study
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, Iterable, List
import json

import pandas as pd


LOG = logging.getLogger("flow_cyt_parser")
MANIFEST_VERSION = 1
HIERARCHY_FIELDS = [
    "WorkingGroup",
    "InstrumentCode",
    "SiteCode",
    "ProtocolID",
    "ExperimentType",
    "SampleName",
    "PrincipleContactID",
    "DataProcessingLevel",
    "StudyID",
    "MaterialCode",
    "ExperimentID",
    "ReplicateNumber",
    "DataFormat",
]


def _coerce_str(v) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def _iter_excel_files(input_dir: Path) -> Iterable[Path]:
    # Patterns seen in WG tables
    pats = ("WG*part*Table.xlsx", "wg*-ver*-all.xlsx")
    for pat in pats:
        for p in input_dir.glob(pat):
            yield p


def parse(input_dir: Path, collection: str) -> List[Dict]:
    """Parse WG1/2/3 spreadsheets to normalized row dicts.

    Returns a list of rows with keys:
      - FileName (string)
      - DatasetId (hierarchical id)
      - CollectionId/CollectionName (collection)
      - DatasetName (last path segment)
      - DatasetVersion (default "1")
      - file_id (DatasetId/FileName)
      - plus original spreadsheet columns coerced to strings
    """
    in_path = Path(input_dir)
    if not in_path.exists():
        raise RuntimeError(f"Input directory does not exist: {in_path}")

    excel_files = list(_iter_excel_files(in_path))
    if not excel_files:
        raise RuntimeError(f"No WG1/2/3 Excel files found in {in_path}")

    out_rows: List[Dict] = []
    for excel in excel_files:
        try:
            xls = pd.ExcelFile(excel)
            sheet = "Sheet1" if "Sheet1" in xls.sheet_names else xls.sheet_names[0]
        except Exception as e:
            raise RuntimeError(f"Failed to read Excel file {excel}: {e}")

        df = pd.read_excel(excel, sheet_name=sheet, dtype=str).fillna("")
        for _, r in df.iterrows():
            row = {k: _coerce_str(v) for k, v in r.to_dict().items()}

            filename = (
                row.get("New FCSC ILS Filename")
                or row.get("FCSC ILS Filename")
                or row.get("FileName")
            )
            filename = _coerce_str(filename).strip()
            if not filename:
                # Some rows are dataset-only lines (e.g., "NoFile"). Skip file cfg.
                continue

            # Preserve legacy detail: append -001 to WorkingGroup if present
            if row.get("WorkingGroup"):
                row["WorkingGroup"] = f"{row['WorkingGroup']}-001"

            # Build dataset_id from non-empty hierarchy fields
            segments: List[str] = []
            for f in HIERARCHY_FIELDS:
                v = row.get(f, "").strip()
                if v:
                    segments.append(v)
            dataset_id = "/".join([collection] + segments) if segments else collection
            file_id = f"{dataset_id}/{filename}"

            # Normalize record
            record = dict(row)
            record["DatasetId"] = dataset_id
            record["CollectionId"] = collection
            record.setdefault("CollectionName", collection)
            record.setdefault("DatasetName", dataset_id.split("/")[-1] if dataset_id else "")
            record.setdefault("DatasetVersion", "1")
            record["FileName"] = filename
            record["file_id"] = file_id

            out_rows.append(record)

    LOG.info("Parsed %d files from %d spreadsheet(s)", len(out_rows), len(excel_files))
    return out_rows


def write_cfgs(files: List[Dict], output_dir: Path) -> None:
    """Write dataset and file cfgs under output_dir/Collection/..."""
    root = Path(output_dir)
    for rec in files:
        dataset_id = _coerce_str(rec.get("DatasetId", ""))
        filename = _coerce_str(rec.get("FileName", "")).strip()
        if not dataset_id or not filename:
            continue

        parts = dataset_id.split("/") + [filename]

        # Dataset fields exclude the file name
        ds_fields = dict(rec)
        ds_fields.pop("FileName", None)
        ds_fields.pop("New FCSC ILS Filename", None)

        # Build the [File] cfg once (ensure id=file_id first)
        file_cfg = "[File]\n"
        file_cfg += f"id={_coerce_str(rec.get('file_id', ''))}\n"
        for k in ds_fields:
            if k == "file_id":
                continue
            v = _coerce_str(rec.get(k, ""))
            if v != "":
                file_cfg += f"{k}={v}\n"

        # Write dataset cfgs for each level in the hierarchy
        for i in range(0, len(parts) - 1):
            ds_dir = root.joinpath(*parts[0 : i + 1])
            ds_dir.mkdir(parents=True, exist_ok=True)

            local_ds_fields = dict(ds_fields)
            local_ds_fields["id"] = str(ds_dir)
            local_ds_fields["DatasetName"] = parts[i]

            ds_cfg = "[Dataset]\n"
            for k in local_ds_fields:
                v = _coerce_str(local_ds_fields.get(k, ""))
                if v != "":
                    ds_cfg += f"{k}={v}\n"

            cfg_path = ds_dir / f"{parts[i]}.cfg"
            with cfg_path.open("w", encoding="utf-8") as fh:
                fh.write(ds_cfg)

        # File-level cfg in the deepest directory
        deepest_dir = root.joinpath(*parts[:-1])
        deepest_dir.mkdir(parents=True, exist_ok=True)
        file_cfg_path = deepest_dir / f"{filename}.cfg"
        with file_cfg_path.open("w", encoding="utf-8") as fh:
            fh.write(file_cfg)


def _collection_root_metadata(collection: str) -> Dict[str, object]:
    """Return collection-level metadata for the flow cytometry collection."""
    coll_id = "NIST_Flow_Cytometry_Standards_Consortium"
    description = (
        "Flow Cytometry Standards Consortium Interlaboratory Study -  WG1 and WG2 data"
    )

    return {
        "DatasetVersion": ["1"],
        "SubmittingInstitutuionID": ["NIST"],
        "AssayType": ["Flow Cytometry"],
        "SampleName": [
            "CellSample2-AllCellsDonor2-Lot3066774",
            "ERF-Bead",
            "CellSample3-AllCellsDonor3-Lot3069118",
            "ERF-FC-Bead",
            "Matrix-3",
            "Matrix-1",
            "FMO-Cell",
            "Synthetic-Cell",
            "Matrix-2",
            "8-Peak-Bead",
            "CellSample1-AllCellsDonor1-Lot3063593",
            "Test-Cell",
        ],
        "StudyID": ["FCSC_WG2-001", "FCSC_WG1-001"],
        "DatasetName": [coll_id],
        "SubmittingInvestigatorID": ["John Elliott"],
        "DataFormat": ["FCS"],
        "MaterialCode": [
            "PE-bead",
            "PerCP-Cy5.5-lyoPBMC-cell",
            "DQC-bead",
            "APC-Cy7-bead",
            "URBmix-bead",
            "V450-bead",
            "PE-lyoPBMC-cell",
            "PE-Cy7-lyoPBMC-cell",
            "FITC-lyoPBMC-cell",
            "PE-Cy7-bead",
            "V500C-bead",
            "FITC-bead",
            "APC-Cy7-lyoPBMC-cell",
            "APC-lyoPBMC-cell",
            "APC-bead",
            "panel1-TruCytes",
            "PerCP-Cy5.5-bead",
            "V450-lyoPBMC-cell",
            "ACmix-bead",
            "V500C-lyoPBMC-cell",
        ],
        "ExperimentID": ["e3", "e2", "e4", "e1"],
        "FileType": ["excel", "flow cytometry standard", "zip", "pdf", "Unknown"],
        "ExperimentType": [
            "Compensation-Control",
            "FMO-Control",
            "Test-Sample",
            "Calibration-And-Standardization",
            "Bead-Sample",
            "QC-Sample",
            "Cell-Sample",
        ],
        "CollectionName": "NIST Flow Cytometry Standards Consortium",
        "ReplicateNumber": ["3", "2", "1"],
        "SiteID": ["NIST"],
        "Study": [
            "NIST Flow Cytometry Standards Consortium- WG2 Interlaboratory Study",
            "NIST Flow Cytometry Standards Consortium- WG1 Interlaboratory Study",
        ],
        "WorkingGroup": ["WG2-001", "WG1-001"],
        "SiteCode": [
            "FDACBER",
            "NISTGB-KP",
            "Q2LabSol",
            "BMSSeattle",
            "LMNXSEA",
            "WRAIR",
            "ISAC",
            "BMSWarren",
            "SPHERO",
            "AgilentSC",
            "CellBio",
            "TFS",
            "AgilentSD",
            "UDel",
            "BCLS",
            "SSBS",
            "NISTGB-GC",
            "AZGBBIO",
            "BDSJ",
            "NISTGB-LW",
            "NIBSC",
            "AZSSF",
            "MSKCC",
            "KITE",
        ],
        "ProtocolID": ["SOP-p1", "SOP-03", "SOP-02", "SOP-01"],
        "DataProcessingLevel": ["Raw"],
        "id": coll_id,
        "labcasId": [coll_id],
        "name": [coll_id],
        "labcasName": [coll_id],
        "CollectionDescription": description,
        "LeadPoC": ["Lili Wang"],
        "LeadPoCEmail": ["lili.wang@nist.gov"],
        "StudyType": ["Interlab"],
        "Discipline": ["Cytometry"],
        "DataCustodian": ["John Elliott"],
        "DataCustodianEmail": ["john.elliott@nist.gov"],
        "OwnerPrincipal": [
            "cn=All NIST,ou=groups,o=NIST",
            "cn=Flow Cytometry Standards Consortium,ou=groups,o=NIST",
        ],
        "Consortium": ["NIST Flow Cytometry Standards Consortium"],
        "Organism": ["Homo sapiens"],
        "CollectionId": [coll_id],
        "DatePublished": ["20_12_2024__10_25_36"],
        "PublishId": ["20_12_2024__10_25_36"],
        "labcas_node_type": ["collections"],
        "DatasetId": [coll_id],
    }


def write_collection_root_artifacts(output_dir: Path, collection: str) -> None:
    """Write collection-level cfg and json at output_dir/<collection>/.

    The metadata is tailored for the NIST Flow Cytometry Standards Consortium
    so the publish crawler can pick up and publish a collections document.
    """
    root_dir = output_dir / collection
    root_dir.mkdir(parents=True, exist_ok=True)

    data = _collection_root_metadata(collection)

    # Write CFG (lists joined by '|')
    cfg_path = root_dir / f"{collection}.cfg"
    lines = ["[Collection]"]
    for k, v in data.items():
        if isinstance(v, list):
            lines.append(f"{k}={'|'.join(v)}")
        else:
            lines.append(f"{k}={v}")
    cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Write JSON mirror for visibility/debugging
    json_path = root_dir / f"{collection}.json"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _normalize_manifest_value(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, list):
        out: List[str] = []
        seen = set()
        for item in value:
            normalized = _normalize_manifest_value(item)
            if normalized is None:
                continue
            if isinstance(normalized, list):
                for nested in normalized:
                    if nested not in seen:
                        out.append(nested)
                        seen.add(nested)
                continue
            if normalized not in seen:
                out.append(normalized)
                seen.add(normalized)
        return out or None
    if isinstance(value, (int, float)):
        value = str(value)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _normalize_scalar_metadata(data: Dict[str, object]) -> Dict[str, object]:
    excluded = {
        "id",
        "labcasId",
        "labcasName",
        "name",
        "labcas_node_type",
        "CollectionId",
        "DatasetId",
        "FileId",
        "file_id",
        "CollectionName",
        "DatasetName",
        "DatasetVersion",
        "FileName",
        "FileVersion",
        "FileLocation",
        "RealFileLocation",
        "PublishDate",
        "DatePublished",
        "PublishId",
    }
    normalized: Dict[str, object] = {}
    for key, value in data.items():
        if key in excluded:
            continue
        normalized_value = _normalize_manifest_value(value)
        if normalized_value is None:
            continue
        normalized[key] = normalized_value
    return normalized


def _ancestor_dataset_ids(dataset_id: str) -> List[str]:
    parts = [part for part in dataset_id.split("/") if part]
    return ["/".join(parts[: idx + 1]) for idx in range(1, len(parts))]


def _common_metadata(items: List[Dict[str, object]]) -> Dict[str, object]:
    if not items:
        return {}
    common = dict(items[0])
    for item in items[1:]:
        for key in list(common.keys()):
            if key not in item or item[key] != common[key]:
                common.pop(key, None)
    return common


def _subtract_parent_metadata(
    metadata: Dict[str, object], parent_metadata: Dict[str, object]
) -> Dict[str, object]:
    return {key: value for key, value in metadata.items() if parent_metadata.get(key) != value}


def build_normalized_manifest(files: List[Dict], collection: str) -> Dict[str, object]:
    datasets: Dict[str, Dict[str, object]] = {}
    dataset_records: Dict[str, List[Dict[str, object]]] = {}
    cleaned_file_records: List[Dict[str, object]] = []
    files_out: List[Dict[str, object]] = []
    collection_metadata = _normalize_scalar_metadata(_collection_root_metadata(collection))

    for rec in files:
        dataset_id = _coerce_str(rec.get("DatasetId", ""))
        filename = _coerce_str(rec.get("FileName", "")).strip()
        if not dataset_id or not filename:
            continue

        file_id = _coerce_str(rec.get("file_id", f"{dataset_id}/{filename}"))
        file_metadata = _normalize_scalar_metadata(rec)
        cleaned_file_records.append(
            {
                "dataset_id": dataset_id,
                "file_id": file_id,
                "filename": filename,
                "metadata": file_metadata,
            }
        )
        for node_id in _ancestor_dataset_ids(dataset_id):
            dataset_records.setdefault(node_id, []).append(file_metadata)

    collection_common = _common_metadata([item["metadata"] for item in cleaned_file_records])
    for key, value in collection_common.items():
        collection_metadata.setdefault(key, value)

    dataset_common: Dict[str, Dict[str, object]] = {
        node_id: _common_metadata(records) for node_id, records in dataset_records.items()
    }

    for node_id in sorted(dataset_common.keys(), key=lambda item: (item.count("/"), item)):
        parent_id = node_id.rsplit("/", 1)[0]
        parent_metadata = collection_common if parent_id == collection else dataset_common.get(parent_id, {})
        datasets[node_id] = {
            "id": node_id,
            "parent_id": parent_id,
            "name": node_id.rsplit("/", 1)[-1],
            "metadata": _subtract_parent_metadata(dataset_common[node_id], parent_metadata),
        }

    for item in cleaned_file_records:
        dataset_id = item["dataset_id"]
        file_id = item["file_id"]
        filename = item["filename"]
        parent_metadata = dataset_common.get(dataset_id, collection_common)
        files_out.append(
            {
                "id": file_id,
                "parent_id": dataset_id,
                "name": filename,
                "path": file_id,
                "metadata": _subtract_parent_metadata(item["metadata"], parent_metadata),
            }
        )

    return {
        "version": MANIFEST_VERSION,
        "format": "labcas_normalized_manifest",
        "collection": {
            "id": collection,
            "name": collection,
            "metadata": {
                **collection_metadata,
                "CollectionName": _collection_root_metadata(collection)["CollectionName"],
                "CollectionDescription": _collection_root_metadata(collection)["CollectionDescription"],
                "OwnerPrincipal": _collection_root_metadata(collection)["OwnerPrincipal"],
            },
        },
        "datasets": list(datasets.values()),
        "files": files_out,
    }


def write_normalized_manifest(files: List[Dict], output_dir: Path, collection: str) -> Path:
    root_dir = output_dir / collection
    root_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_normalized_manifest(files, collection)
    manifest_path = root_dir / f"{collection}.manifest.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, separators=(",", ":"))
    return manifest_path


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse NIST Flow Cytometry WG1/2/3 spreadsheets to LabCAS cfgs",
    )
    parser.add_argument("--input-dir", default="/data/raw", help="Directory with WG*.xlsx files")
    parser.add_argument("--output-dir", default="/metadata", help="Directory to write cfgs")
    parser.add_argument("--collection", default="fcs_interlab_study", help="Collection name")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Write only the normalized manifest and collection JSON, not per-node cfg sidecars",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, ...)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    files = parse(Path(args.input_dir), collection=args.collection)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.manifest_only:
        write_cfgs(files, out_dir)
        write_collection_root_artifacts(out_dir, args.collection)
    manifest_path = write_normalized_manifest(files, out_dir, args.collection)
    LOG.info(
        "Wrote %s and %s for %d files under %s",
        "normalized manifest",
        "cfgs" if not args.manifest_only else "no cfgs",
        len(files),
        args.output_dir,
    )
    LOG.info("Normalized manifest path: %s", manifest_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

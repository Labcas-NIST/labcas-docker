#!/usr/bin/env python3
"""
Flow Cytometry (NIST WG1/WG2/WG3) metadata parser.

Reads WG spreadsheets from an input directory, builds a dataset hierarchy
(WorkingGroup → InstrumentCode → SiteCode → ProtocolID → …), and writes
LabCAS-style cfg files under the chosen output directory.

CLI usage:
  python flow_cytometry.py --input-dir /data/raw --output-dir /metadata \
                           --collection fcs_interlab_study
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd


LOG = logging.getLogger("flow_cyt_parser")


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

    hierarchy_fields = [
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
            for f in hierarchy_fields:
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


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse NIST Flow Cytometry WG1/2/3 spreadsheets to LabCAS cfgs",
    )
    parser.add_argument("--input-dir", default="/data/raw", help="Directory with WG*.xlsx files")
    parser.add_argument("--output-dir", default="/metadata", help="Directory to write cfgs")
    parser.add_argument("--collection", default="fcs_interlab_study", help="Collection name")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, ...)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    files = parse(Path(args.input_dir), collection=args.collection)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    write_cfgs(files, Path(args.output_dir))
    LOG.info("Wrote cfgs for %d files under %s", len(files), args.output_dir)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


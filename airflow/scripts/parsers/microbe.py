#!/usr/bin/env python3
"""NIST Microbial Strain metadata parser.

Reads the CoreNMSC V 1.0.csv metadata template and emits a collection cfg plus
a single dataset/file pair for publishing.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Dict, List


LOG = logging.getLogger("microbial_strain_parser")


def _normalize_header(header: str) -> str:
    return header.strip().lstrip("\ufeff")


def _read_metadata(input_file: Path) -> Dict[str, str]:
    if not input_file.exists():
        raise RuntimeError(f"Metadata CSV does not exist: {input_file}")

    with input_file.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        headers = next(reader, None)
        if not headers:
            raise RuntimeError(f"Metadata CSV is empty: {input_file}")

        header_map = {_normalize_header(h): idx for idx, h in enumerate(headers)}
        text_idx = header_map.get("Text")
        value_idx = header_map.get("Value")
        if text_idx is None or value_idx is None:
            raise RuntimeError(
                "Metadata CSV must contain 'Text' and 'Value' columns."
            )

        meta: Dict[str, str] = {}
        for row in reader:
            text = row[text_idx].strip() if text_idx < len(row) else ""
            if not text:
                continue
            value = row[value_idx].strip() if value_idx < len(row) else ""
            if value == "":
                continue
            meta[text] = value

    LOG.info("Parsed %d metadata fields from %s", len(meta), input_file)
    return meta


def _write_cfg(path: Path, header: str, data: Dict[str, str]) -> None:
    lines: List[str] = [f"[{header}]"]
    for key, value in data.items():
        if value != "":
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_collection_root_artifacts(output_dir: Path, collection: str, meta: Dict[str, str]) -> None:
    root_dir = output_dir / collection
    root_dir.mkdir(parents=True, exist_ok=True)

    description = "Microbial strain collection"
    material_id = meta.get("MicrobialMaterialID", "").strip()
    if material_id:
        description = f"Microbial strain metadata for {material_id}"

    data: Dict[str, str] = {
        "CollectionName": collection,
        "CollectionId": collection,
        "CollectionDescription": description,
        "DatasetId": collection,
        "DatasetName": collection,
        "DatasetVersion": "1",
        "Consortium": "NIST",
        "OwnerPrincipal": "cn=All NIST,ou=groups,o=NIST",
        "id": collection,
        "labcasId": collection,
        "name": collection,
        "labcasName": collection,
        "labcas_node_type": "collections",
    }

    cfg_path = root_dir / f"{collection}.cfg"
    _write_cfg(cfg_path, "Collection", data)

    json_path = root_dir / f"{collection}.json"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_dataset_and_file_cfgs(
    meta: Dict[str, str],
    output_dir: Path,
    collection: str,
    dataset: str,
    file_name: str,
) -> None:
    root_dir = output_dir / collection
    dataset_dir = root_dir / dataset
    dataset_dir.mkdir(parents=True, exist_ok=True)

    dataset_id = f"{collection}/{dataset}"
    dataset_fields: Dict[str, str] = dict(meta)
    dataset_fields.update(
        {
            "DatasetId": dataset_id,
            "CollectionId": collection,
            "CollectionName": collection,
            "DatasetName": dataset,
            "DatasetVersion": "1",
            "id": str(dataset_dir),
        }
    )

    dataset_cfg = dataset_dir / f"{dataset}.cfg"
    _write_cfg(dataset_cfg, "Dataset", dataset_fields)

    file_id = f"{dataset_id}/{file_name}"
    file_cfg_lines: List[str] = ["[File]", f"id={file_id}"]
    for key, value in dataset_fields.items():
        if key == "id":
            continue
        if value != "":
            file_cfg_lines.append(f"{key}={value}")

    file_cfg = dataset_dir / f"{file_name}.cfg"
    file_cfg.write_text("\n".join(file_cfg_lines) + "\n", encoding="utf-8")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse CoreNMSC microbial metadata into LabCAS cfgs",
    )
    parser.add_argument(
        "--input-file",
        default="/data/raw/CoreNMSC V 1.0.csv",
        help="CoreNMSC metadata CSV input",
    )
    parser.add_argument(
        "--output-dir",
        default="/metadata",
        help="Directory to write cfgs",
    )
    parser.add_argument(
        "--collection",
        default="microbial_strain",
        help="Collection name",
    )
    parser.add_argument(
        "--dataset",
        default="strain",
        help="Dataset name",
    )
    parser.add_argument(
        "--file-name",
        default="MALDI V 1.0.csv",
        help="File name to publish under the dataset",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, ...)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    meta = _read_metadata(Path(args.input_file))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_collection_root_artifacts(out_dir, args.collection, meta)
    write_dataset_and_file_cfgs(meta, out_dir, args.collection, args.dataset, args.file_name)
    LOG.info("Wrote cfgs for collection %s under %s", args.collection, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

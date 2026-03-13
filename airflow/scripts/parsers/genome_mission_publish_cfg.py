#!/usr/bin/env python3
"""Generate LabCAS collection/dataset/file cfgs from mapped genomic metadata."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List

import yaml


LOG = logging.getLogger("genome_mission_publish_cfg")


def _load_mapped(mapped_file: Path) -> Dict[str, str]:
    if not mapped_file.exists():
        raise RuntimeError(f"Mapped YAML does not exist: {mapped_file}")

    with mapped_file.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if not isinstance(raw, dict):
        raise RuntimeError(f"Expected mapped YAML object, got: {type(raw).__name__}")

    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _write_cfg(path: Path, header: str, data: Dict[str, str]) -> None:
    lines: List[str] = [f"[{header}]"]
    for key, value in data.items():
        if value != "":
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_collection_root_artifacts(
    output_dir: Path,
    collection: str,
    mapped: Dict[str, str],
) -> None:
    root_dir = output_dir / collection
    root_dir.mkdir(parents=True, exist_ok=True)

    dataset_title = mapped.get("dataset_title", "Genomic Hello World Dataset")
    dataset_description = mapped.get(
        "dataset_description",
        "Genomic hello-world collection generated from genome_mission mapper output.",
    )
    dataset_version = mapped.get("DatasetVersion", "1")

    data: Dict[str, str] = {
        "CollectionName": collection,
        "CollectionId": collection,
        "CollectionDescription": dataset_description,
        "DatasetId": collection,
        "DatasetName": dataset_title,
        "DatasetVersion": dataset_version,
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
    mapped: Dict[str, str],
    output_dir: Path,
    collection: str,
    dataset: str,
    file_name: str,
) -> None:
    root_dir = output_dir / collection
    dataset_dir = root_dir / dataset
    dataset_dir.mkdir(parents=True, exist_ok=True)

    dataset_id = f"{collection}/{dataset}"
    dataset_fields: Dict[str, str] = dict(mapped)
    dataset_fields.update(
        {
            "DatasetId": dataset_id,
            "CollectionId": collection,
            "CollectionName": collection,
            "DatasetName": dataset,
            "DatasetVersion": mapped.get("DatasetVersion", "1"),
            "id": str(dataset_dir),
        }
    )

    dataset_cfg = dataset_dir / f"{dataset}.cfg"
    _write_cfg(dataset_cfg, "Dataset", dataset_fields)

    file_id = f"{dataset_id}/{file_name}"
    file_fields: Dict[str, str] = dict(dataset_fields)
    file_fields.pop("id", None)
    file_fields["id"] = file_id

    file_cfg = dataset_dir / f"{file_name}.cfg"
    _write_cfg(file_cfg, "File", file_fields)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate LabCAS cfg files for genomic hello-world publishing.",
    )
    parser.add_argument(
        "--mapped-file",
        default="/data/staging/genomic_helloworld/datasetlevel.yaml",
        help="Mapped Datasetlevel YAML from genome_mission parser.",
    )
    parser.add_argument(
        "--output-dir",
        default="/metadata",
        help="Directory where LabCAS cfg files will be written.",
    )
    parser.add_argument(
        "--collection",
        default="genomic_helloworld",
        help="Collection name.",
    )
    parser.add_argument(
        "--dataset",
        default="mission",
        help="Dataset name.",
    )
    parser.add_argument(
        "--file-name",
        default="GENOMIC-HELLO-001.fastq",
        help="Published file name under dataset.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, ...).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mapped = _load_mapped(Path(args.mapped_file))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_collection_root_artifacts(out_dir, args.collection, mapped)
    write_dataset_and_file_cfgs(
        mapped,
        out_dir,
        args.collection,
        args.dataset,
        args.file_name,
    )
    LOG.info(
        "Wrote genomic publish cfgs for collection=%s dataset=%s under %s",
        args.collection,
        args.dataset,
        args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

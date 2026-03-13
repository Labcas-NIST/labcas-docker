#!/usr/bin/env python3
"""Normalize generated LabCAS metadata JSON before Solr publish."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def _scalar(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return ""
        return str(value[0]).strip()
    if value is None:
        return ""
    return str(value).strip()


def _iter_files(root: Path, collection: str, publish_id: str) -> Iterable[Path]:
    coll = root / collection
    pattern = f"*_labcasmet_{publish_id}.json"
    yield from coll.rglob(pattern)


def normalize_file(path: Path, collection: str) -> bool:
    raw = json.loads(path.read_text(encoding="utf-8"))
    changed = False

    node_type = _scalar(raw.get("labcas_node_type"))
    node_id = _scalar(raw.get("id"))
    labcas_id = _scalar(raw.get("labcasId"))

    collection_id = _scalar(raw.get("CollectionId")) or collection
    collection_name = _scalar(raw.get("CollectionName")) or collection_id

    if _scalar(raw.get("CollectionId")) != collection_id:
        raw["CollectionId"] = collection_id
        changed = True
    if _scalar(raw.get("CollectionName")) != collection_name:
        raw["CollectionName"] = collection_name
        changed = True

    if node_type in {"datasets", "files"}:
        dataset_id = _scalar(raw.get("DatasetId"))
        if not dataset_id:
            if node_type == "datasets":
                dataset_id = labcas_id or node_id
            elif node_type == "files" and node_id:
                dataset_id = node_id.rsplit("/", 1)[0] if "/" in node_id else collection_id
        dataset_name = _scalar(raw.get("DatasetName")) or (
            dataset_id.rsplit("/", 1)[-1] if dataset_id else ""
        )
        if dataset_id and _scalar(raw.get("DatasetId")) != dataset_id:
            raw["DatasetId"] = dataset_id
            changed = True
        if dataset_name and _scalar(raw.get("DatasetName")) != dataset_name:
            raw["DatasetName"] = dataset_name
            changed = True

    if node_type == "files":
        file_name = _scalar(raw.get("FileName")) or (node_id.rsplit("/", 1)[-1] if node_id else "")
        dataset_version = _scalar(raw.get("DatasetVersion")) or "1"
        if file_name and _scalar(raw.get("FileName")) != file_name:
            raw["FileName"] = file_name
            changed = True
        if _scalar(raw.get("DatasetVersion")) != dataset_version:
            raw["DatasetVersion"] = dataset_version
            changed = True

    if changed:
        path.write_text(json.dumps(raw, indent=4) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize generated metadata JSON for a specific publish_id.",
    )
    parser.add_argument("--collection", required=True, help="Collection id")
    parser.add_argument("--publish-id", required=True, help="Publish id suffix in _labcasmet_<id>.json")
    parser.add_argument(
        "--generated-root",
        default="/data/generated_metadata",
        help="Root generated metadata directory",
    )
    args = parser.parse_args()

    root = Path(args.generated_root)
    files = list(_iter_files(root, args.collection, args.publish_id))
    if not files:
        raise SystemExit(
            f"No generated metadata files found for collection={args.collection} publish_id={args.publish_id}"
        )

    changed = 0
    for path in files:
        if normalize_file(path, args.collection):
            changed += 1

    print(f"normalized_files={len(files)} changed={changed} publish_id={args.publish_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

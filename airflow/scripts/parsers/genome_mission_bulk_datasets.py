#!/usr/bin/env python3
"""Generate many dataset cfgs from genome-editing dataset metadata docs."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from genome_mission import _map_to_datasetlevel
from genome_mission_publish_cfg import write_collection_root_artifacts


LOG = logging.getLogger("genome_mission_bulk_datasets")


def _first_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            text = str(item).strip()
            if text:
                return text
        return ""
    text = str(value).strip()
    return text


def _safe_segment(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip()).strip("._-")
    return cleaned or "dataset"


def _collection_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _fs_segment(text: str) -> str:
    s = text.strip().replace("/", "_").replace("\x00", "")
    if s in {"", ".", ".."}:
        return "dataset"
    return s


def _dataset_parts(
    source_dataset_id: str,
    collection: str,
    fallback_name: str,
    index: int,
) -> List[str]:
    src = source_dataset_id.strip("/")
    if not src:
        src = fallback_name.strip()
    if not src:
        src = f"dataset_{index:04d}"

    parts = [p.strip() for p in src.split("/") if p.strip()]
    if len(parts) > 1:
        first = _collection_token(parts[0])
        collection_tokens = {
            _collection_token(collection),
            _collection_token("Genome_Editing_Consortium"),
            _collection_token("NIST Genome Editing Consortium"),
        }
        if first in collection_tokens:
            parts = parts[1:]
    if not parts:
        parts = [f"dataset_{index:04d}"]

    return parts


def _write_cfg(path: Path, header: str, data: Dict[str, str]) -> None:
    lines: List[str] = [f"[{header}]"]
    for key, value in data.items():
        if value != "":
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_docs(input_file: Path) -> List[Dict[str, Any]]:
    with input_file.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    response = raw.get("response")
    if isinstance(response, dict):
        docs = response.get("docs")
        if isinstance(docs, list):
            return [d for d in docs if isinstance(d, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def generate(
    input_file: Path,
    output_dir: Path,
    staging_dir: Path,
    collection: str,
    source_file: Path,
    archive_root: Path,
    publish_file_name: str,
    collection_metadata_file: Path | None = None,
) -> Tuple[int, Path]:
    docs = _load_docs(input_file)
    if not docs:
        raise RuntimeError(f"No metadata docs found in {input_file}")

    if not source_file.exists():
        raise RuntimeError(f"Source file for staged dataset entries does not exist: {source_file}")

    coll_dir = output_dir / collection
    coll_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    archive_collection_dir = archive_root / collection
    archive_collection_dir.mkdir(parents=True, exist_ok=True)

    if collection_metadata_file and collection_metadata_file.exists():
        with collection_metadata_file.open("r", encoding="utf-8") as fh:
            collection_raw = json.load(fh)
        mapped_collection = _map_to_datasetlevel(collection_raw)
        write_collection_root_artifacts(output_dir, collection, mapped_collection)

    manifest: List[Dict[str, str]] = []
    seen_dataset_ids: Dict[str, int] = {}

    for idx, doc in enumerate(docs, start=1):
        mapped = _map_to_datasetlevel(doc)
        source_dataset_id = _first_text(doc.get("DatasetId"))
        fallback_name = _first_text(doc.get("DatasetName")) or mapped.get("dataset_title", "")
        parts = _dataset_parts(source_dataset_id, collection, fallback_name, idx)
        fs_parts = [_fs_segment(p) for p in parts]
        dataset_rel_path = "/".join(fs_parts)
        dataset_id = f"{collection}/{dataset_rel_path}"

        count = seen_dataset_ids.get(dataset_id, 0) + 1
        seen_dataset_ids[dataset_id] = count
        if count > 1:
            fs_parts[-1] = f"{fs_parts[-1]}_{count}"
            dataset_rel_path = "/".join(fs_parts)
            dataset_id = f"{collection}/{dataset_rel_path}"

        dataset_dir = coll_dir.joinpath(*fs_parts)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        dataset_name = _first_text(doc.get("DatasetName")) or fs_parts[-1]

        dataset_fields: Dict[str, str] = {
            str(k): str(v) for k, v in mapped.items() if v is not None and str(v) != ""
        }
        dataset_fields.update(
            {
                "DatasetId": dataset_id,
                "CollectionId": collection,
                "CollectionName": collection,
                "DatasetName": dataset_name,
                "DatasetVersion": "1",
                "id": str(dataset_dir),
            }
        )

        dataset_cfg = dataset_dir / f"{fs_parts[-1]}.cfg"
        _write_cfg(dataset_cfg, "Dataset", dataset_fields)

        file_id = f"{dataset_id}/{publish_file_name}"
        file_fields = dict(dataset_fields)
        file_fields.pop("id", None)
        file_fields["id"] = file_id
        file_cfg = dataset_dir / f"{publish_file_name}.cfg"
        _write_cfg(file_cfg, "File", file_fields)

        archive_dataset_dir = archive_collection_dir.joinpath(*fs_parts)
        archive_dataset_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, archive_dataset_dir / publish_file_name)

        mapped_file = staging_dir / f"{idx:04d}_{'_'.join(_safe_segment(p).lower() for p in fs_parts)}.yaml"
        with mapped_file.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(mapped, fh, sort_keys=False)

        manifest.append(
            {
                "dataset_key": dataset_rel_path,
                "dataset_id": dataset_id,
                "mapped_file": str(mapped_file),
                "file_cfg": str(file_cfg),
                "archive_file": str(archive_dataset_dir / publish_file_name),
            }
        )

    manifest_path = staging_dir / "validation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return len(manifest), manifest_path


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate many LabCAS dataset cfgs from a Genome Editing docs JSON.",
    )
    parser.add_argument(
        "--input-file",
        default="/data/raw/genome_editing_consortium/dataset_metadata.json",
        help="Input JSON with response.docs",
    )
    parser.add_argument(
        "--output-dir",
        default="/metadata",
        help="Root metadata directory",
    )
    parser.add_argument(
        "--staging-dir",
        default="/data/staging/genome_editing_consortium/bulk",
        help="Directory for mapped YAML files and manifest",
    )
    parser.add_argument(
        "--collection",
        default="genome_editing_consortium",
        help="Target collection id",
    )
    parser.add_argument(
        "--source-file",
        default="/data/raw/genome_editing_consortium/dataset_metadata.json",
        help="File to stage under each generated dataset in archive",
    )
    parser.add_argument(
        "--archive-root",
        default="/data/archive/nist",
        help="Archive root where staged files are copied",
    )
    parser.add_argument(
        "--publish-file-name",
        default="dataset_metadata.json",
        help="File name published under each generated dataset",
    )
    parser.add_argument(
        "--collection-metadata-file",
        default="/data/raw/genome_editing_consortium/collection_metadata.json",
        help="Optional collection-level metadata JSON to write collection cfg/json",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    count, manifest_path = generate(
        input_file=Path(args.input_file),
        output_dir=Path(args.output_dir),
        staging_dir=Path(args.staging_dir),
        collection=args.collection,
        source_file=Path(args.source_file),
        archive_root=Path(args.archive_root),
        publish_file_name=args.publish_file_name,
        collection_metadata_file=Path(args.collection_metadata_file)
        if args.collection_metadata_file
        else None,
    )
    LOG.info("Generated %d dataset cfgs; manifest: %s", count, manifest_path)
    print(f"Generated {count} datasets; manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

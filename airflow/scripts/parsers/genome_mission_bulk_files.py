#!/usr/bin/env python3
"""Generate File-level cfg/yaml artifacts from genome-editing file metadata docs."""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


LOG = logging.getLogger("genome_mission_bulk_files")


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


def _split_choices(value: Any) -> List[str]:
    if isinstance(value, list):
        items = value
    elif value is None:
        items = []
    else:
        items = [value]
    out: List[str] = []
    for item in items:
        for part in str(item).split(","):
            token = part.strip()
            if token:
                out.append(token)
    return out


def _norm_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def _collection_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _fs_segment(text: str) -> str:
    s = text.strip().replace("/", "_").replace("\x00", "")
    if s in {"", ".", ".."}:
        return "node"
    return s


def _safe_cfg_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-") or "file"


def _strip_collection_prefix(parts: List[str], collection: str) -> List[str]:
    if not parts:
        return parts
    token = _collection_token(parts[0])
    valid = {
        _collection_token(collection),
        _collection_token("Genome_Editing_Consortium"),
        _collection_token("NIST Genome Editing Consortium"),
    }
    if token in valid:
        return parts[1:]
    return parts


def _enum_pick(value: Any, aliases: Dict[str, str], fallback: str | None = None) -> str | None:
    for raw in _split_choices(value):
        key = _norm_token(raw)
        if key in aliases:
            return aliases[key]
    return fallback


def _map_filelevel(doc: Dict[str, Any]) -> Dict[str, str]:
    processing_map = {
        "raw": "raw",
        "intermediate": "intermediate",
        "derived": "derived",
        "not_applicable": "na",
        "na": "na",
    }
    context_map = {
        "benchmark_data": "benchmark_data",
        "telemetry_data": "telemetry_data",
        "exploratory_data": "exploratory_data",
        "reference_material_data": "reference_material_data",
        "deliverable_data": "deliverable_data",
        "code": "code",
        "not_applicable": "na",
        "na": "na",
    }
    content_map = {
        "documentation": "documentation",
        "sop": "SOP",
        "instrument_output": "instrument_output",
        "results": "results",
        "reference_file": "reference_file",
        "protocol": "protocol",
        "executable_code": "executable_code",
    }
    assay_map = {
        "dna_sequencing": "DNA_sequencing",
        "dna_fragment_analysis": "DNA_fragment_analysis",
        "fluorescent_imaging": "fluorescent_imaging",
    }

    file_name = _first_text(doc.get("FileName"))
    mapped: Dict[str, str] = {
        "file_name": file_name,
        "data_processing_level": _enum_pick(doc.get("DataProcessingLevel"), processing_map, "na") or "na",
        "data_file_context": _enum_pick(doc.get("DataFileContext"), context_map, "na") or "na",
        "file_content_type": _enum_pick(doc.get("FileContentType"), content_map, "documentation")
        or "documentation",
    }

    assay = _enum_pick(doc.get("AssayTechnique"), assay_map)
    if assay:
        mapped["assay_technique"] = assay

    file_description = _first_text(doc.get("FileDescription"))
    if file_description:
        mapped["file_description"] = file_description

    date_mod = _first_text(doc.get("DateMod"))
    if date_mod:
        mapped["date_file_generated"] = date_mod

    md5sum = _first_text(doc.get("ICmd5sum"))
    if md5sum:
        mapped["md5sum"] = md5sum

    file_type = _first_text(doc.get("FileType"))
    if file_type:
        mapped["file_type_extension"] = file_type

    file_size = _first_text(doc.get("FileSize"))
    if file_size:
        mapped["file_size"] = file_size

    mime_type = _first_text(doc.get("MIMEType"))
    if mime_type:
        mapped["MIME_type"] = mime_type

    collection_id = _first_text(doc.get("CollectionId"))
    if collection_id:
        mapped["collection_ID"] = collection_id

    return mapped


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
    archive_root: Path,
    staging_dir: Path,
    collection: str,
    touch_missing_files: bool = True,
) -> Tuple[int, Path]:
    docs = _load_docs(input_file)
    if not docs:
        raise RuntimeError(f"No metadata docs found in {input_file}")

    coll_dir = output_dir / collection
    coll_dir.mkdir(parents=True, exist_ok=True)
    archive_coll_dir = archive_root / collection
    archive_coll_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    manifest: List[Dict[str, str]] = []
    seen_ids: Dict[str, int] = {}

    for idx, doc in enumerate(docs, start=1):
        raw_dataset_id = _first_text(doc.get("DatasetId"))
        raw_file_id = _first_text(doc.get("id")) or _first_text(doc.get("FileId"))

        ds_parts = _strip_collection_prefix(
            [p.strip() for p in raw_dataset_id.strip("/").split("/") if p.strip()],
            collection,
        )
        file_parts = _strip_collection_prefix(
            [p.strip() for p in raw_file_id.strip("/").split("/") if p.strip()],
            collection,
        )

        if not file_parts:
            file_name = _first_text(doc.get("FileName")) or f"file_{idx:05d}"
            file_parts = ds_parts + [file_name]

        if not ds_parts and len(file_parts) > 1:
            ds_parts = file_parts[:-1]
        if not ds_parts:
            ds_parts = [f"dataset_{idx:05d}"]

        ds_fs_parts = [_fs_segment(p) for p in ds_parts]
        file_name = _fs_segment(file_parts[-1]) if file_parts else _fs_segment(_first_text(doc.get("FileName")))
        if not file_name:
            file_name = f"file_{idx:05d}"
        file_fs_parts = ds_fs_parts + [file_name]

        dataset_rel = "/".join(ds_fs_parts)
        file_rel = "/".join(file_fs_parts)
        dataset_id = f"{collection}/{dataset_rel}"
        file_id = f"{collection}/{file_rel}"

        dup = seen_ids.get(file_id, 0) + 1
        seen_ids[file_id] = dup
        if dup > 1:
            stem, dot, ext = file_name.partition(".")
            file_name = f"{stem}_{dup}{dot}{ext}" if dot else f"{file_name}_{dup}"
            file_fs_parts = ds_fs_parts + [file_name]
            file_rel = "/".join(file_fs_parts)
            file_id = f"{collection}/{file_rel}"

        dataset_dir = coll_dir.joinpath(*ds_fs_parts)
        dataset_dir.mkdir(parents=True, exist_ok=True)

        archive_file = archive_coll_dir.joinpath(*file_fs_parts)
        archive_file.parent.mkdir(parents=True, exist_ok=True)
        if touch_missing_files and not archive_file.exists():
            archive_file.touch()

        mapped = _map_filelevel(doc)
        mapped["file_name"] = file_name

        mapped_file = staging_dir / f"{idx:05d}_{_safe_cfg_name('_'.join(file_fs_parts).lower())}.yaml"
        with mapped_file.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(mapped, fh, sort_keys=False)

        dataset_name = _first_text(doc.get("DatasetName")) or ds_fs_parts[-1]
        file_fields: Dict[str, str] = {str(k): str(v) for k, v in mapped.items() if v is not None and str(v) != ""}
        file_fields.update(
            {
                "CollectionId": collection,
                "CollectionName": collection,
                "DatasetId": dataset_id,
                "DatasetName": dataset_name,
                "DatasetVersion": _first_text(doc.get("DatasetVersion")) or "1",
                "FileName": file_name,
                "FileId": file_id,
                "id": file_id,
            }
        )

        passthrough = [
            "FileDownloadId",
            "FileLocation",
            "FileVersion",
            "OwnerPrincipal",
            "LeadPoC",
            "LeadPoCEmail",
            "DataCustodian",
            "DataCustodianEmail",
            "CollectionDescription",
            "Consortium",
            "StudyType",
            "Discipline",
            "Organism",
            "MaterialType",
        ]
        for key in passthrough:
            value = _first_text(doc.get(key))
            if value:
                file_fields[key] = value

        cfg_path = dataset_dir / f"{file_name}.cfg"
        _write_cfg(cfg_path, "File", file_fields)

        manifest.append(
            {
                "dataset_id": dataset_id,
                "file_id": file_id,
                "mapped_file": str(mapped_file),
                "cfg_file": str(cfg_path),
                "archive_file": str(archive_file),
            }
        )

    manifest_path = staging_dir / "file_validation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return len(manifest), manifest_path


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate file-level LabCAS cfgs from Genome Editing file metadata docs.",
    )
    parser.add_argument(
        "--input-file",
        default="/data/raw/genome_editing_consortium/file_metadata.json",
        help="Input JSON with response.docs",
    )
    parser.add_argument(
        "--output-dir",
        default="/metadata",
        help="Root metadata directory",
    )
    parser.add_argument(
        "--archive-root",
        default="/data/archive/nist",
        help="Archive root where placeholder files are created",
    )
    parser.add_argument(
        "--staging-dir",
        default="/data/staging/genome_editing_consortium/files_bulk",
        help="Directory for mapped YAML files and manifest",
    )
    parser.add_argument(
        "--collection",
        default="genome_editing_consortium",
        help="Target collection id",
    )
    parser.add_argument(
        "--touch-missing-files",
        default="true",
        help="Create placeholder files for missing archive files (true/false).",
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
    touch = str(args.touch_missing_files).strip().lower() in {"1", "true", "yes", "y"}
    count, manifest_path = generate(
        input_file=Path(args.input_file),
        output_dir=Path(args.output_dir),
        archive_root=Path(args.archive_root),
        staging_dir=Path(args.staging_dir),
        collection=args.collection,
        touch_missing_files=touch,
    )
    LOG.info("Generated %d file cfgs; manifest: %s", count, manifest_path)
    print(f"Generated {count} files; manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

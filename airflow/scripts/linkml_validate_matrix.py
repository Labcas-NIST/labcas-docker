#!/usr/bin/env python3
"""Validate collection/dataset/file payloads across LinkML class levels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from linkml_runtime.loaders import yaml_loader
from linkml_runtime.utils.yamlutils import YAMLRoot
from nist_labcas_linkml.datamodel import nist_labcas_linkml as model


Target = Tuple[str, Path]


def _parse_bool(text: str) -> bool:
    return text.strip().lower() in {"1", "true", "yes", "y"}


def _to_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    prefixed = Path("/") / path
    if prefixed.exists():
        return prefixed
    return path


def _load_manifest(path: Path) -> List[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected list manifest: {path}")
    return payload


def _resolve_class(class_name: str):
    resolved = getattr(model, class_name, None)
    if (
        not isinstance(resolved, type)
        or resolved is YAMLRoot
        or not issubclass(resolved, YAMLRoot)
    ):
        raise ValueError(f"Unknown LinkML class: {class_name}")
    return resolved


def _available_model_classes() -> List[str]:
    names: List[str] = []
    for name, value in vars(model).items():
        if (
            isinstance(value, type)
            and value is not YAMLRoot
            and issubclass(value, YAMLRoot)
            and name.endswith("Extension")
        ):
            names.append(name)
    return sorted(names)


def _parse_level_map(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in [v.strip() for v in text.split(",") if v.strip()]:
        if ":" not in item:
            raise ValueError(f"Invalid level map entry '{item}' (expected level:Class)")
        level, class_name = item.split(":", 1)
        out[level.strip()] = class_name.strip()
    for required in ("collection", "dataset", "file"):
        if required not in out:
            raise ValueError(f"Missing primary class for level '{required}'")
    return out


def _collection_targets(path: Path) -> List[Target]:
    return [("collection", _to_path(str(path)))]


def _dataset_targets(manifest_path: Path) -> List[Target]:
    targets: List[Target] = []
    for idx, row in enumerate(_load_manifest(manifest_path), start=1):
        key = str(row.get("dataset_key") or row.get("dataset_id") or f"dataset_{idx}")
        mapped_file = row.get("mapped_file")
        if not mapped_file:
            continue
        targets.append((key, _to_path(str(mapped_file))))
    return targets


def _file_targets(manifest_path: Path) -> List[Target]:
    targets: List[Target] = []
    for idx, row in enumerate(_load_manifest(manifest_path), start=1):
        key = str(row.get("file_id") or row.get("id") or f"file_{idx}")
        mapped_file = row.get("mapped_file")
        if not mapped_file:
            continue
        targets.append((key, _to_path(str(mapped_file))))
    return targets


def _validate_targets(
    level: str,
    class_name: str,
    targets: Iterable[Target],
    group: str,
    max_fail_samples: int,
    verbose_pass: bool,
) -> Tuple[int, int]:
    klass = _resolve_class(class_name)
    total = 0
    passed = 0
    failed = 0
    fail_samples = 0
    for label, path in targets:
        total += 1
        try:
            obj = yaml_loader.load(str(path), target_class=klass)
            if obj is None:
                raise ValueError("Loader returned None")
            passed += 1
            if verbose_pass:
                print(
                    f"{group} PASS level={level} class={class_name} label={label} path={path}"
                )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if fail_samples < max_fail_samples:
                fail_samples += 1
                print(
                    f"{group} FAIL level={level} class={class_name} label={label} path={path} error={type(exc).__name__}: {exc}"
                )
    print(
        f"{group} SUMMARY level={level} class={class_name} total={total} passes={passed} fails={failed}"
    )
    return passed, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate collection/dataset/file manifests across LinkML class levels.",
    )
    parser.add_argument("--collection-input", required=True)
    parser.add_argument("--dataset-manifest", required=True)
    parser.add_argument("--file-manifest", required=True)
    parser.add_argument(
        "--primary-level-map",
        default="collection:CollectionLevel,dataset:Datasetlevel,file:FileLevel",
        help="Comma-separated level:Class map.",
    )
    parser.add_argument(
        "--cross-classes",
        default="CoreILSExtension,GenomeEditingILSExtension,GenomicsDNAExtractionExtension,GenomicsDNAAmplificationExtension",
        help="Comma-separated class list to validate across selected levels.",
    )
    parser.add_argument(
        "--cross-levels",
        default="dataset,file",
        help="Comma-separated levels for cross-class validation.",
    )
    parser.add_argument(
        "--strict-primary",
        default="true",
        help="Fail process when primary class validation has failures.",
    )
    parser.add_argument(
        "--strict-cross",
        default="false",
        help="Fail process when cross-class validation has failures.",
    )
    parser.add_argument(
        "--max-fail-samples",
        type=int,
        default=20,
        help="Max failure samples to print per (group, level, class).",
    )
    parser.add_argument(
        "--verbose-pass",
        default="false",
        help="Print PASS line for each validated payload.",
    )
    args = parser.parse_args()

    primary_map = _parse_level_map(args.primary_level_map)
    cross_classes = [v.strip() for v in args.cross_classes.split(",") if v.strip()]
    if len(cross_classes) == 1 and cross_classes[0].upper() in {
        "ALL_OTHERS",
        "ALL_OTHER_CLASSES",
    }:
        primary_classes = set(primary_map.values())
        cross_classes = [
            name for name in _available_model_classes() if name not in primary_classes
        ]
    cross_levels = [v.strip() for v in args.cross_levels.split(",") if v.strip()]
    strict_primary = _parse_bool(args.strict_primary)
    strict_cross = _parse_bool(args.strict_cross)
    verbose_pass = _parse_bool(args.verbose_pass)
    print(
        f"CONFIG primary_map={primary_map} cross_classes_count={len(cross_classes)} cross_levels={cross_levels} strict_primary={strict_primary} strict_cross={strict_cross}"
    )

    targets_by_level: Dict[str, List[Target]] = {
        "collection": _collection_targets(_to_path(args.collection_input)),
        "dataset": _dataset_targets(_to_path(args.dataset_manifest)),
        "file": _file_targets(_to_path(args.file_manifest)),
    }
    for level, targets in targets_by_level.items():
        print(f"TARGETS level={level} count={len(targets)}")

    primary_fails = 0
    cross_fails = 0
    total_checks = 0

    for level in ("collection", "dataset", "file"):
        class_name = primary_map[level]
        _, fails = _validate_targets(
            level=level,
            class_name=class_name,
            targets=targets_by_level[level],
            group="PRIMARY",
            max_fail_samples=args.max_fail_samples,
            verbose_pass=verbose_pass,
        )
        primary_fails += fails
        total_checks += len(targets_by_level[level])

    for class_name in cross_classes:
        for level in cross_levels:
            if level not in targets_by_level:
                raise ValueError(f"Unknown cross level: {level}")
            _, fails = _validate_targets(
                level=level,
                class_name=class_name,
                targets=targets_by_level[level],
                group="CROSS",
                max_fail_samples=args.max_fail_samples,
                verbose_pass=verbose_pass,
            )
            cross_fails += fails
            total_checks += len(targets_by_level[level])

    print(
        f"OVERALL total_checks={total_checks} primary_fails={primary_fails} cross_fails={cross_fails} strict_primary={strict_primary} strict_cross={strict_cross}"
    )

    if strict_primary and primary_fails > 0:
        return 1
    if strict_cross and cross_fails > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

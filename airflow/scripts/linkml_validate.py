#!/usr/bin/env python3
"""Validate an input document against nist-labcas-linkml classes."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Type

from linkml_runtime.loaders import yaml_loader
from linkml_runtime.utils.yamlutils import YAMLRoot
from nist_labcas_linkml.datamodel import nist_labcas_linkml as model


def _available_target_classes() -> List[str]:
    names = []
    for name, value in vars(model).items():
        if not isinstance(value, type):
            continue
        if value is YAMLRoot:
            continue
        if issubclass(value, YAMLRoot):
            names.append(name)
    return sorted(names)


def _resolve_target_class(name: str) -> Type[YAMLRoot]:
    target = getattr(model, name, None)
    if not isinstance(target, type) or not issubclass(target, YAMLRoot):
        choices = ", ".join(_available_target_classes())
        raise ValueError(f"Unknown target class '{name}'. Available classes: {choices}")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a YAML/JSON file against a nist-labcas-linkml target class."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the YAML/JSON document to validate.",
    )
    parser.add_argument(
        "--class-name",
        required=True,
        help="Target class in nist_labcas_linkml.datamodel.nist_labcas_linkml",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    target_class = _resolve_target_class(args.class_name)
    obj = yaml_loader.load(str(input_path), target_class=target_class)
    if obj is None:
        raise ValueError(f"Validation failed: no object was loaded from {input_path}")

    print(
        f"Validation passed for {input_path} against class {target_class.__name__}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Project a revision-bound repository-write classification report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from daedalus.gates.repository.write_classification import (
    RepositoryWriteClassificationError,
    parse_inventory_v2,
    project_classification_input,
)
from daedalus.spine.envelope import canonical_json


def _object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RepositoryWriteClassificationError(
            f"could not read JSON object from {path}"
        ) from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RepositoryWriteClassificationError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", type=Path)
    parser.add_argument("classifications", type=Path)
    parser.add_argument("--require-classification-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        inventory = parse_inventory_v2(_object(args.inventory))
        report = project_classification_input(
            inventory,
            _object(args.classifications),
        )
    except RepositoryWriteClassificationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(canonical_json(report.to_dict()))
    if args.require_classification_ready and not report.classification_ready:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

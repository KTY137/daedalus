#!/usr/bin/env python3
"""Emit the canonical generation-2 repository write inventory as JSON."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2Error,
    scan_repository_write_surfaces_v2,
)
from daedalus.spine.envelope import canonical_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report the revision-bound generation-2 write inventory."
    )
    parser.add_argument("repository_root", nargs="?", default=".")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument(
        "--require-closed",
        action="store_true",
        help="exit 2 when any inventory blocker remains",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = scan_repository_write_surfaces_v2(
            Path(args.repository_root),
            source_revision=args.source_revision,
        )
    except RepositoryWriteInventoryV2Error as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(canonical_json(report.to_dict()))
    if args.require_closed and not report.closed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

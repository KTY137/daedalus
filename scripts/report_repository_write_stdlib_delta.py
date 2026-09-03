from __future__ import annotations

import argparse
import sys
from pathlib import Path

from daedalus.gates.repository.write_stdlib_delta import (
    RepositoryWriteStdlibDeltaError,
    scan_repository_write_stdlib_delta,
)
from daedalus.spine.envelope import canonical_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report additive stdlib/process write surfaces missed by the "
            "current canonical repository-write inventory"
        )
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
    )
    parser.add_argument("--source-revision", required=True)
    parser.add_argument(
        "--require-no-additional-surfaces",
        action="store_true",
        help="exit 1 when the additive delta contains findings",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = scan_repository_write_stdlib_delta(
            args.repository_root,
            source_revision=args.source_revision,
        )
    except RepositoryWriteStdlibDeltaError as exc:
        sys.stderr.write(f"repository-write stdlib delta refused: {exc}\n")
        return 2
    sys.stdout.write(canonical_json(report.to_dict()) + "\n")
    if args.require_no_additional_surfaces and report.findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

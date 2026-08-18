#!/usr/bin/env python3
"""Emit an additive GateReport-v3 without claiming a security boundary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

# Direct invocation puts scripts/ at sys.path[0]; the package lives one level
# up.  Guarded so pytest/module imports keep their existing resolution.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from daedalus.gates.report_v3 import build_gate0_report_v3


_ERROR_SCHEMA = "daedalus-gate-report-v3-error/1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Emit GateReport-v3 with the canonical repository-write inventory. "
            "This discovery CLI cannot assert security-boundary closure."
        )
    )
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument(
        "--conformance-receipts",
        type=Path,
        default=None,
        help=(
            "directory of persisted runtime-conformance receipt bundles; "
            "omitting it keeps the fail-closed unbound blocker"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_gate0_report_v3(
            args.repository_root,
            source_revision=args.source_revision,
            security_boundary_claimed=False,
            runtime_conformance_receipt_dir=args.conformance_receipts,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": _ERROR_SCHEMA,
                    "closed": False,
                    "error": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    print(
        json.dumps(
            report.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if report.closed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Report/block drift in the Gate-0 effectful entrypoint registry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daedalus.spine.effect_boundary import check_conformance, human_matrix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the deterministic Daedalus effect-boundary inventory. "
            "This is a conformance/drift check, not an OS sandbox."
        )
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require-gate0",
        action="store_true",
        help="also fail while any inventoried entrypoint is not centrally wired",
    )
    args = parser.parse_args(argv)

    report = check_conformance(args.root)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(human_matrix(report))
    if not report.structurally_conformant:
        return 2
    if args.require_gate0 and not report.gate0_closed:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

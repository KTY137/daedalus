from __future__ import annotations

import argparse
import json
from pathlib import Path

from .report import build_gate0_report


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m daedalus.gates")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("--gate", type=int, choices=(0,), required=True)
    report.add_argument("--repo-root", type=Path, default=Path.cwd())
    report.add_argument("--source-revision", required=True)
    args = parser.parse_args()

    result = build_gate0_report(args.repo_root, source_revision=args.source_revision)
    text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

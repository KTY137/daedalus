# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daedalus.gates.report import assert_monotonic, load_gate_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--require-monotonic", action="store_true")
    parser.add_argument("--require-closed", action="store_true")
    args = parser.parse_args()

    report = load_gate_report(args.report)
    if args.require_monotonic:
        if args.baseline is None:
            parser.error("--baseline is required with --require-monotonic")
        regressions = assert_monotonic(report, load_gate_report(args.baseline))
        if regressions:
            print(json.dumps({"regressions": list(regressions)}, indent=2))
            return 1
    if args.require_closed and not report.closed:
        print(json.dumps({"closed": False, "blockers": list(report.blockers)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

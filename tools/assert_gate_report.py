from __future__ import annotations

import argparse
import hmac
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daedalus.gates.baseline import GateBaselineError, load_gate0_baseline
from daedalus.gates.report import GateReport, assert_monotonic, load_gate_report

_BASELINE_V2_SCHEMA = "daedalus-gate-baseline/2"


class _BaselineRefused(RuntimeError):
    """The supplied baseline is unreadable, unbound, or fails its digest pin."""


def _read_json_object(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise _BaselineRefused(f"baseline could not be parsed: {exc}") from exc
    if not isinstance(payload, dict):
        raise _BaselineRefused("baseline root must be a JSON object")
    return payload


def _regressions(
    report: GateReport,
    baseline_path: Path,
    expected_sha256: str | None,
) -> tuple[str, ...]:
    """Blocker rows present in the current report but absent from the baseline.

    The committed baseline is a migration comparison anchor: it freezes the
    blocker set of one reviewed source revision so that later revisions may
    only shrink it. It is NOT a status store — it never asserts current gate
    state, and resolving a blocker requires regenerating nothing; only adding
    a blocker requires a new, reviewed baseline.
    """
    peeked = _read_json_object(baseline_path)
    if peeked.get("schema") == _BASELINE_V2_SCHEMA:
        baseline = load_gate0_baseline(baseline_path)
        if expected_sha256 is not None and not hmac.compare_digest(
            expected_sha256, baseline.digest
        ):
            raise _BaselineRefused(
                "baseline digest does not match the --baseline-sha256 pin"
            )
        if report.gate != baseline.gate:
            raise _BaselineRefused("cannot compare different gates")
        return tuple(sorted(set(report.blockers) - set(baseline.blockers)))
    baseline_report = load_gate_report(baseline_path)
    if expected_sha256 is not None:
        serialized = peeked.get("report_sha256")
        if not isinstance(serialized, str) or not hmac.compare_digest(
            expected_sha256, serialized
        ):
            raise _BaselineRefused(
                "baseline report digest does not match the --baseline-sha256 pin"
            )
    return assert_monotonic(report, baseline_report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--baseline",
        type=Path,
        help=(
            "committed blocker baseline: either a daedalus-gate-baseline/2 "
            "artifact or a full gate report of the baseline revision"
        ),
    )
    parser.add_argument(
        "--baseline-sha256",
        help=(
            "externally pinned digest of the baseline artifact "
            "(baseline_sha256 for v2 baselines, report_sha256 for reports)"
        ),
    )
    parser.add_argument("--require-monotonic", action="store_true")
    parser.add_argument("--require-closed", action="store_true")
    args = parser.parse_args()

    if args.baseline_sha256 is not None and args.baseline is None:
        parser.error("--baseline-sha256 requires --baseline")

    report = load_gate_report(args.report)
    if args.require_monotonic:
        if args.baseline is None:
            parser.error("--baseline is required with --require-monotonic")
        try:
            regressions = _regressions(
                report,
                args.baseline,
                args.baseline_sha256,
            )
        except (_BaselineRefused, GateBaselineError, ValueError) as exc:
            sys.stderr.write(f"gate report baseline refused: {exc}\n")
            return 2
        if regressions:
            print(json.dumps({"regressions": list(regressions)}, indent=2))
            return 1
    if args.require_closed and not report.closed:
        print(json.dumps({"closed": False, "blockers": list(report.blockers)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from daedalus.gates.baseline import (
    GateBaselineBindingError,
    GateBaselineError,
    assess_gate0_monotonicity,
    create_gate0_baseline,
    load_current_gate_report,
    load_gate0_baseline,
    load_gate0_monotonicity_receipt,
)
from daedalus.gates.baseline_verifier import (
    GateMonotonicityBlocked,
    verify_gate0_monotonicity_receipt,
)


def _canonical_json(value: dict) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and verify revision-bound Gate-0 blocker baselines."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--report", type=Path, required=True)
    create.add_argument("--baseline-id", required=True)
    create.add_argument("--source-tree-revision", required=True)
    create.add_argument("--created-at", required=True)

    compare = commands.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--current-report", type=Path, required=True)
    compare.add_argument("--expected-baseline-sha256", required=True)
    compare.add_argument("--current-source-tree-revision", required=True)
    compare.add_argument("--assessment-id", required=True)
    compare.add_argument("--assessed-at", required=True)
    compare.add_argument("--require-monotonic", action="store_true")

    verify = commands.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--baseline", type=Path, required=True)
    verify.add_argument("--current-report", type=Path, required=True)
    verify.add_argument("--expected-baseline-sha256", required=True)
    verify.add_argument("--current-source-tree-revision", required=True)
    verify.add_argument("--require-monotonic", action="store_true")
    return parser


def _create(args: argparse.Namespace) -> int:
    report = load_current_gate_report(args.report)
    baseline = create_gate0_baseline(
        report,
        baseline_id=args.baseline_id,
        source_tree_revision=args.source_tree_revision,
        created_at=args.created_at,
    )
    sys.stdout.write(_canonical_json(baseline.to_dict()) + "\n")
    return 0


def _compare(args: argparse.Namespace) -> int:
    baseline = load_gate0_baseline(args.baseline)
    current = load_current_gate_report(args.current_report)
    receipt = assess_gate0_monotonicity(
        baseline,
        current,
        expected_baseline_sha256=args.expected_baseline_sha256,
        current_source_tree_revision=args.current_source_tree_revision,
        assessment_id=args.assessment_id,
        assessed_at=args.assessed_at,
    )
    sys.stdout.write(_canonical_json(receipt.to_dict()) + "\n")
    if args.require_monotonic and receipt.status != "passed":
        return 1
    return 0


def _verify(args: argparse.Namespace) -> int:
    receipt = load_gate0_monotonicity_receipt(args.receipt)
    baseline = load_gate0_baseline(args.baseline)
    current = load_current_gate_report(args.current_report)
    verified = verify_gate0_monotonicity_receipt(
        receipt,
        baseline,
        current,
        expected_baseline_sha256=args.expected_baseline_sha256,
        current_source_tree_revision=args.current_source_tree_revision,
        require_monotonic=args.require_monotonic,
    )
    sys.stdout.write(_canonical_json(verified.to_dict()) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            return _create(args)
        if args.command == "compare":
            return _compare(args)
        if args.command == "verify":
            return _verify(args)
        raise AssertionError("unreachable command")
    except (
        GateBaselineError,
        GateBaselineBindingError,
        GateMonotonicityBlocked,
        ValueError,
    ) as exc:
        sys.stderr.write(f"Gate-0 baseline refused: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

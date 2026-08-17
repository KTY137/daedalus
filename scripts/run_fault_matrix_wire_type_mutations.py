"""Targeted mutations for exact fault-contract wire scalar types."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fault_mutation_sandbox import run_campaign

MODULE = Path("daedalus/gates/fault_matrix.py")
TESTS = (
    "tests/gates/test_fault_matrix_exact_durable_state.py",
    "tests/gates/test_fault_matrix_wire_type_review.py",
)
MUTATIONS = (
    (
        "scenario-array-type-bypass",
        "        if any(type(payload[field]) is not list for field in array_fields):\n",
        "        if False:\n",
    ),
    (
        "verification-bool-type-bypass",
        "        if any(type(payload[field]) is not bool for field in bool_fields):\n",
        "        if False:\n",
    ),
    (
        "verification-failure-count-type-bypass",
        '        if type(payload["failure_count"]) is not int:\n',
        "        if False:\n",
    ),
)


def main() -> int:
    return run_campaign(
        ROOT,
        MODULE,
        TESTS,
        MUTATIONS,
        prefix="daedalus-fault-wire-",
        summary="killed {count} exact wire-type mutants",
    )


if __name__ == "__main__":
    raise SystemExit(main())

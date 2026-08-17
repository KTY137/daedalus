"""Targeted mutations for exact durable fault-state verification."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fault_mutation_sandbox import run_campaign

MODULE = Path("daedalus/gates/fault_matrix.py")
TESTS = (
    "tests/gates/test_fault_matrix_exact_durable_state.py",
    "tests/gates/test_fault_matrix_contract_review.py",
)
MUTATIONS = (
    (
        "exact-marker-set-to-subset",
        "            and receipt.durable_markers == spec.expected_durable_markers\n",
        "            and set(spec.expected_durable_markers).issubset(receipt.durable_markers)\n",
    ),
    (
        "exact-durable-claim-escalation",
        '            "exact_durable_states_verified": passed,\n',
        '            "exact_durable_states_verified": True,\n',
    ),
)


def main() -> int:
    return run_campaign(
        ROOT,
        MODULE,
        TESTS,
        MUTATIONS,
        prefix="daedalus-fault-durable-",
        summary="killed {count} exact durable-state mutants",
    )


if __name__ == "__main__":
    raise SystemExit(main())

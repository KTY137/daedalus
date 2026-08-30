# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Bounded mutation campaign for the exact Gate-0 fault matrix contract."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fault_mutation_sandbox import run_campaign

MODULE = Path("daedalus/gates/fault_matrix.py")
TESTS = (
    "tests/gates/test_fault_matrix_contract.py",
    "tests/gates/test_fault_matrix_contract_schema.py",
)

MUTATIONS = (
    (
        "fingerprint-source-revision-bypass",
        '            "source_revision": _exact_revision(\n                source_revision,\n                "source_revision",\n            ),\n',
        '            "source_revision": "0" * 40,\n',
    ),
    (
        "manifest-source-revision-bypass",
        "    if manifest.source_revision != source_revision:\n",
        "    if False:\n",
    ),
    (
        "missing-inventory-bypass",
        "    missing = tuple(sorted(expected_ids - observed_ids))\n",
        "    missing = ()\n",
    ),
    (
        "extra-inventory-bypass",
        "    extra = tuple(sorted(observed_ids - expected_ids))\n",
        "    extra = ()\n",
    ),
    (
        "scenario-spec-binding-bypass",
        "            receipt.scenario_spec_sha256 == spec.digest\n",
        "            True\n",
    ),
    (
        "runtime-binding-bypass",
        "            and receipt.harness_runtime_sha256 == harness_runtime\n",
        "            and True\n",
    ),
    (
        "toolchain-binding-bypass",
        "            and receipt.toolchain_manifest_sha256 == toolchain_manifest\n",
        "            and True\n",
    ),
    (
        "injection-fingerprint-binding-bypass",
        "            and receipt.injection_fingerprint_sha256\n            == manifest.injection_fingerprint(spec)\n",
        "            and True\n",
    ),
    (
        "restart-policy-binding-bypass",
        "            and receipt.observed_restart_policy == spec.restart_policy\n",
        "            and True\n",
    ),
    (
        "process-termination-binding-bypass",
        "            and receipt.process_termination_observed\n            is spec.process_termination\n",
        "            and True\n",
    ),
    (
        "checkout-mutation-bypass",
        "            and receipt.primary_checkout_before_sha256\n            == receipt.primary_checkout_after_sha256\n",
        "            and True\n",
    ),
    (
        "automatic-reexecution-observation-bypass",
        "            and receipt.automatic_reexecution_performed is False\n",
        "            and True\n",
    ),
    (
        "llm-evidence-observation-bypass",
        "            and receipt.llm_evidence_used is False\n",
        "            and True\n",
    ),
    (
        "unconditional-pass",
        '        status="passed" if not blockers else "failed",\n',
        '        status="passed",\n',
    ),
    (
        "projection-reverification-bypass",
        "        if exact != self:\n",
        "        if False:\n",
    ),
    (
        "failed-evidence-projection-bypass",
        '        if self.status != "passed":\n',
        "        if False:\n",
    ),
    (
        "scenario-auto-reexecution-claim-escalation",
        '            "automatic_reexecution_allowed": False,\n',
        '            "automatic_reexecution_allowed": True,\n',
    ),
    (
        "manifest-closure-claim-escalation",
        '            "inventory_complete_claimed": False,\n            "faults_executed": False,\n            "gate_transition_authorized": False,\n            "closed": False,\n',
        '            "inventory_complete_claimed": False,\n            "faults_executed": False,\n            "gate_transition_authorized": False,\n            "closed": True,\n',
    ),
    (
        "verification-closure-claim-escalation",
        '            "llm_evidence_absent": passed,\n            "gate_transition_authorized": False,\n            "closed": False,\n',
        '            "llm_evidence_absent": passed,\n            "gate_transition_authorized": False,\n            "closed": True,\n',
    ),
)


def main() -> int:
    return run_campaign(
        ROOT,
        MODULE,
        TESTS,
        MUTATIONS,
        prefix="daedalus-fault-matrix-",
        summary="killed {count} exact fault-matrix mutants",
    )


if __name__ == "__main__":
    raise SystemExit(main())

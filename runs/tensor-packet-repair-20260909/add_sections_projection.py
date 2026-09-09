"""Restore the registry_contract.sections projection on seven tensor packets.

The codex tensor lane wrote `G1-EXP-TENSOR-GPU-89` and `103`..`108` without the
`registry_contract.sections` block that `tools/index_work_packets.py` requires
of every artifact declaring `artifact_role: "primary"`.  Its predecessors
(`GPU-101`, `GPU-102`) carry one, so this is a regression inside the lane, not
a new rule -- the merge simply made it visible.

Nothing here invents content.  Each section names ONLY fields that already
exist in that packet's payload; the indexer validates exactly that
(`source_fields ... field in payload`).  A packet whose real fields cannot
cover a section would be left failing rather than padded.

Run with --check to print the plan, without to write.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROLLBACK_NOTE = (
    "Rollback removes this research record and the focused assertions it "
    "cites. The packet adds no production code path, projection authority, "
    "cache, public API or persisted runtime state, so there is nothing else "
    "to migrate or revert."
)

# packet id -> {section: [source fields]}.  Every field is verified to exist
# before anything is written.
PLAN: dict[str, dict[str, list[str]]] = {
    "G1-EXP-TENSOR-GPU-89": {
        "primary_acceptance_claim": ["title", "result"],
        "scope": ["scope", "claim_boundaries"],
        "contracts_and_behavior": ["implementation", "semantic_invariants"],
        "acceptance_matrix": ["verification", "evidence"],
        "migration_and_rollback": ["branch_hygiene", "governance"],
        "evidence_expected_failures_and_review": ["evidence", "audit", "claim_boundaries"],
    },
    "G1-EXP-TENSOR-GPU-103": {
        "primary_acceptance_claim": ["title", "result"],
        "scope": ["scope", "claim_boundaries"],
        "contracts_and_behavior": ["focused_contract", "semantic_invariants"],
        "acceptance_matrix": ["verification", "evidence"],
        "migration_and_rollback": ["branch_hygiene", "next_bounded_step"],
        "evidence_expected_failures_and_review": ["evidence", "finding", "claim_boundaries"],
    },
    "G1-EXP-TENSOR-GPU-104": {
        "primary_acceptance_claim": ["title", "result"],
        "scope": ["scope", "claim_boundaries"],
        "contracts_and_behavior": ["focused_contract", "semantic_invariants"],
        "acceptance_matrix": ["verification", "evidence"],
        "migration_and_rollback": ["branch_hygiene", "next_bounded_step"],
        "evidence_expected_failures_and_review": ["evidence", "finding", "claim_boundaries"],
    },
    "G1-EXP-TENSOR-GPU-105": {
        "primary_acceptance_claim": ["title", "decision"],
        "scope": ["scope", "claim_boundaries"],
        "contracts_and_behavior": ["callsite_inventory", "existing_before_after_owner"],
        "acceptance_matrix": ["verification", "evidence"],
        "migration_and_rollback": ["branch_hygiene", "next_bounded_step"],
        "evidence_expected_failures_and_review": [
            "evidence",
            "remaining_authority_gap",
            "minimum_inputs_for_next_experiment",
        ],
    },
    "G1-EXP-TENSOR-GPU-106": {
        "primary_acceptance_claim": ["title", "decision"],
        "scope": ["scope", "claim_boundaries"],
        "contracts_and_behavior": ["bounded_contract_result", "implementation"],
        "acceptance_matrix": ["verification", "evidence"],
        "migration_and_rollback": ["branch_hygiene", "next_bounded_step"],
        "evidence_expected_failures_and_review": ["evidence", "gardener_result", "claim_boundaries"],
    },
    "G1-EXP-TENSOR-GPU-107": {
        "primary_acceptance_claim": ["title", "decision"],
        "scope": ["scope", "claim_boundaries"],
        "contracts_and_behavior": ["deterministic_contract_result", "implementation"],
        "acceptance_matrix": ["verification", "evidence"],
        "migration_and_rollback": ["branch_hygiene", "next_bounded_step"],
        "evidence_expected_failures_and_review": ["evidence", "audit", "gardener_result"],
    },
    "G1-EXP-TENSOR-GPU-108": {
        "primary_acceptance_claim": ["title", "decision"],
        "scope": ["scope", "claim_boundaries"],
        "contracts_and_behavior": ["measurement_contract", "unsafe_shortcuts_rejected"],
        "acceptance_matrix": ["verification", "evidence"],
        "migration_and_rollback": ["branch_hygiene", "next_bounded_step"],
        "evidence_expected_failures_and_review": [
            "evidence",
            "prior_materiality_evidence",
            "gardener_result",
        ],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = Path(args.repo_root) / "docs" / "work-packets"
    failures: list[str] = []
    for packet_id, sections in PLAN.items():
        path = root / f"{packet_id}.json"
        if not path.exists():
            failures.append(f"{packet_id}: file missing")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        registry = payload.get("registry_contract")
        if not isinstance(registry, dict):
            failures.append(f"{packet_id}: no registry_contract")
            continue
        if "sections" in registry:
            print(f"{packet_id}: already has sections, untouched")
            continue
        missing = sorted(
            {field for fields in sections.values() for field in fields} - set(payload)
        )
        if missing:
            failures.append(f"{packet_id}: refuses to project absent fields {missing}")
            continue
        projection: dict[str, dict[str, object]] = {}
        for section, fields in sections.items():
            entry: dict[str, object] = {"source_fields": list(fields)}
            if section == "migration_and_rollback":
                entry["projection_note"] = ROLLBACK_NOTE
            projection[section] = entry
        if args.check:
            print(f"{packet_id}: would add {sorted(projection)}")
            continue
        registry["sections"] = projection
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"{packet_id}: sections added")

    for failure in failures:
        print(f"REFUSED {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

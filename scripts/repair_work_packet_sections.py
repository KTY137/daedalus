"""Derive the missing ``registry_contract.sections`` projection on JSON Work Packets.

``tools/index_work_packets.py`` requires every artifact declaring
``artifact_role: "primary"`` to project the six contract sections onto fields
that actually exist in its payload.  The codex tensor lane has now shipped
three separate waves of packets without that block (GPU-89 and 103-108 on
2026-09-09 morning, then 109-111 the same afternoon), each time turning the
work-packet index red on integration.

The first repair hard-coded a per-packet plan.  That is the wrong shape for a
recurring tax: it needs editing every time the lane invents a field name.  This
version instead declares, per section, an ORDERED PREFERENCE LIST of field
names, and picks the ones a given packet actually has.

Two rules keep this honest, and they are the reason it may be run unattended:

1. **Nothing is invented.**  A section is only written from fields present in
   that packet's payload.  The indexer enforces the same thing
   (``source_fields ... field in payload``); this refuses first, with a better
   message.
2. **A packet that cannot be covered is REFUSED, not padded.**  If any of the
   six sections has no candidate field, the packet is reported and left
   untouched.  A section pointed at an unrelated field would be worse than a
   red index: it would make the registry lie quietly instead of loudly.

Run with ``--check`` to print the plan and write nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ROLLBACK_NOTE = (
    "Rollback removes this research record and the focused assertions it "
    "cites. The packet adds no production code path, projection authority, "
    "cache, public API or persisted runtime state, so there is nothing else "
    "to migrate or revert."
)

#: section -> ordered candidate field names. Earlier entries are preferred.
#: Every candidate is a field these packets genuinely use for that purpose;
#: the lists are unions over the waves seen so far, not guesses.
PREFERENCES: dict[str, tuple[str, ...]] = {
    "primary_acceptance_claim": (
        "title", "result", "decision", "finding",
        "bounded_contract_result", "deterministic_contract_result",
        "measurement_contract", "gardener_result",
    ),
    "scope": ("scope", "claim_boundaries", "domain"),
    "contracts_and_behavior": (
        "focused_contract", "measurement_contract", "semantic_invariants",
        "implementation", "callsite_inventory", "bounded_contract_result",
        "deterministic_contract_result", "diagnostic_contract_migration",
        "existing_before_after_owner", "audit", "focused_contract_head",
    ),
    "acceptance_matrix": ("verification", "evidence", "measurement", "audit"),
    "migration_and_rollback": (
        "branch_hygiene", "next_bounded_step", "bounded_next_step",
        "governance", "implementation_head",
    ),
    "evidence_expected_failures_and_review": (
        "evidence", "finding", "claim_boundaries", "gardener_result",
        "unsafe_shortcuts_rejected", "remaining_authority_gap",
        "minimum_inputs_for_next_experiment", "prior_materiality_evidence",
        "audit", "verification",
    ),
}

#: How many fields to name per section, at most. More than this is noise in the
#: registry; fewer is fine when the packet simply has fewer.
MAX_FIELDS_PER_SECTION = 3


def plan_for(payload: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Return (projection plan, uncoverable sections)."""
    present = set(payload)
    plan: dict[str, list[str]] = {}
    uncoverable: list[str] = []
    for section, candidates in PREFERENCES.items():
        chosen = [name for name in candidates if name in present]
        if not chosen:
            uncoverable.append(section)
            continue
        plan[section] = chosen[:MAX_FIELDS_PER_SECTION]
    return plan, uncoverable


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=str(REPO))
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--glob", default="*.json",
        help="restrict to packets whose filename matches this glob",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root) / "docs" / "work-packets"
    refused: list[str] = []
    touched = 0
    for path in sorted(root.glob(args.glob)):
        if path.name == "index.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            refused.append(f"{path.name}: unparseable ({exc})")
            continue
        registry = payload.get("registry_contract")
        if not isinstance(registry, dict):
            continue
        if registry.get("artifact_role") != "primary":
            continue
        if "sections" in registry:
            continue

        plan, uncoverable = plan_for(payload)
        if uncoverable:
            refused.append(
                f"{path.name}: no field covers {uncoverable}; left untouched "
                "rather than pointed at something unrelated"
            )
            continue

        projection: dict[str, dict[str, object]] = {}
        for section, fields in plan.items():
            entry: dict[str, object] = {"source_fields": list(fields)}
            if section == "migration_and_rollback":
                entry["projection_note"] = ROLLBACK_NOTE
            projection[section] = entry

        if args.check:
            print(f"{path.name}: would add {sorted(projection)}")
            for section, fields in sorted(plan.items()):
                print(f"    {section} <- {fields}")
            continue

        registry["sections"] = projection
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"{path.name}: sections added from {sorted(plan)}")
        touched += 1

    if not args.check:
        print(f"packets repaired: {touched}")
    for line in refused:
        print(f"REFUSED {line}", file=sys.stderr)
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())

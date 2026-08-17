"""Bounded mutation campaign for the whole-matrix binding and its verdict contract.

Every mutation below turns a refusal into a silent pass -- an unbound bundle that
reports nothing, a declaration granted without its decision document, a
development-key run allowed to carry a security-boundary claim, a retyped
blocker count accepted as evidence.  If any of them survives, the binding is
decoration rather than a guard and the campaign fails loudly.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fault_mutation_sandbox import run_campaign

BINDING = Path("daedalus/gates/fault_matrix_binding.py")
VERDICT = Path("daedalus/runtimes/whole_fault_matrix.py")
TESTS = (
    "tests/gates/test_fault_matrix_binding.py",
    "tests/gates/test_runtime_conformance_binding.py",
    "tests/runtimes/test_whole_fault_matrix.py",
)

BINDING_MUTATIONS = (
    (
        "unbound-reports-nothing",
        '        failures=(f"{UNBOUND_PREFIX}:{reason}",),\n',
        "        failures=(),\n",
    ),
    (
        "ambiguous-evidence-silently-picks-one",
        "            if len(matching) != 1:\n"
        '                return _unbound(f"ambiguous-evidence:{len(candidates)}")\n'
        "            verdict_path = matching[0]\n",
        "            verdict_path = candidates[0]\n",
    ),
    (
        "declaration-without-a-decision-document",
        "    if not decision.is_file():\n",
        "    if False:\n",
    ),
    (
        "declaration-may-widen-its-own-scope",
        "    if claimed_rows != tuple(sorted(blocked)):\n",
        "    if False:\n",
    ),
    (
        "receipt-need-not-bind-this-verdict",
        '        or matrix.get("matrix_sha256") != verdict.matrix_sha256\n',
        "        or False\n",
    ),
    (
        "receipt-schema-unchecked",
        '    if not isinstance(payload, dict) or payload.get("schema") != RECEIPT_SCHEMA:\n',
        "    if not isinstance(payload, dict):\n",
    ),
    (
        "custody-contradiction-dropped-when-nothing-to-declare",
        "        return (), (), contradiction\n",
        "        return (), (), None\n",
    ),
    (
        "custody-contradiction-ignored",
        "    if contradiction is not None:\n",
        "    if False:\n",
    ),
    (
        "stale-revision-ignored",
        "    if not revision_matches:\n",
        "    if False:\n",
    ),
    (
        "development-keys-may-attest-closure",
        "        and verdict.production_key_material\n",
        "        and True\n",
    ),
    (
        "boundary-overclaim-permitted",
        "    if security_boundary_claimed and not attests_closure:\n",
        "    if False:\n",
    ),
    (
        "bound-blockers-dropped",
        "    failures = [row for row in verdict.blockers if row not in set(declared)]\n",
        "    failures = []\n",
    ),
)

VERDICT_MUTATIONS = (
    (
        "retyped-closed-flag-accepted",
        '        if _exact_bool(body["closed"], "closed") != verdict.closed:\n',
        "        if False:\n",
    ),
    (
        "retyped-blocker-count-accepted",
        '        if _exact_int(body["blocker_count"], "blocker_count") != verdict.blocker_count:\n',
        "        if False:\n",
    ),
    (
        "column-observation-total-unchecked",
        "        if self.observations != sum(column.observations for column in columns):\n",
        "        if False:\n",
    ),
    (
        "non-canonical-storage-accepted",
        "        if dict(body) != verdict.to_dict():\n",
        "        if False:\n",
    ),
    (
        "inner-closed-flag-unchecked",
        '    if _exact_bool(body["closed"], "verification.closed") != attested.closed:\n',
        "    if False:\n",
    ),
)


def main() -> int:
    run_campaign(
        ROOT,
        BINDING,
        TESTS,
        BINDING_MUTATIONS,
        prefix="daedalus-whole-matrix-binding-",
        summary="killed {count} whole-matrix binding mutants",
    )
    run_campaign(
        ROOT,
        VERDICT,
        TESTS,
        VERDICT_MUTATIONS,
        prefix="daedalus-whole-matrix-verdict-",
        summary="killed {count} whole-matrix verdict-contract mutants",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

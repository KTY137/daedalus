#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded trust-boundary mutations for repository-write evidence production.

Two files, one runner: the kernel producers that retain what a granted and
terminalised wave lease leaves behind, and the in-process classification
producer that reads that store and decides whether a surface may be central.
They are one chain -- a guard disabled on either side produces the same lie --
so they are mutated against one baseline.

Each mutation names exactly one source anchor.  A needle that resolves twice is
a runner error, not a survivor: two guards sharing one anchor means disabling
one of them goes unnoticed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "daedalus/kernel/offload_lease.py"
PRODUCER = ROOT / "scripts/declare_write_surfaces.py"
KERNEL_TESTS = "tests/kernel/test_write_evidence_records.py"
PRODUCER_TESTS = "tests/gates/test_write_evidence_producer.py"
#: The issuer's refusal predicate, and the producer's lease-dominance guard.
#: Same two files, same chain: the predicate decides which doors can hold a
#: lease at all and the guard decides which writes that lease covers, so a
#: guard disabled on either side produces the same lie.
RULE_TESTS = "tests/kernel/test_effect_lease_issuer_rule.py"
DOMINANCE_TESTS = "tests/gates/test_write_surface_lease_dominance.py"
#: The authority/subject split. Same chain again: the predicate decides which
#: doors can hold a lease, the guard decides which writes it covers, and this
#: decides WHOSE control root judges the request and WHICH checkout the
#: containment contracts measure. A guard disabled on any of the three
#: produces a receipt about something nobody checked.
SPLIT_TESTS = "tests/kernel/test_lease_authority_subject_split.py"
#: The attempt door, landed by 11dc0195. Referenced so the guard its wrapper
#: carries gets an anchor of its own instead of sharing the wave wrapper's.
ATTEMPT_TESTS = "tests/kernel/test_attempt_lease.py"

# name -> (target file, needle, replacement, test node id)
MUTATIONS: dict[str, tuple[Path, str, str, str]] = {
    # --- the disjointness recorder: it records, it never decides ----------
    "record-a-refused-containment-decision": (
        KERNEL,
        "    if decision.allowed is not True:\n",
        "    if False and decision.allowed is not True:\n",
        f"{KERNEL_TESTS}::test_a_refused_decision_is_not_a_disjointness_receipt",
    ),
    "record-another-contract-as-disjointness": (
        KERNEL,
        "    if decision.contract != WORKTREE_CONTAINMENT_CONTRACT:\n",
        "    if False and decision.contract != WORKTREE_CONTAINMENT_CONTRACT:\n",
        f"{KERNEL_TESTS}::test_another_contract_cannot_be_recorded_as_disjointness",
    ),
    "record-two-names-for-one-root-as-disjoint": (
        KERNEL,
        "    if primary_sha256 == target_sha256:\n",
        "    if False and primary_sha256 == target_sha256:\n",
        f"{KERNEL_TESTS}::"
        "test_two_roots_with_one_identity_contradict_the_recorded_decision",
    ),
    # --- the fingerprint definition ---------------------------------------
    # A path digest would satisfy the chain's 64-hex shape check and disagree
    # with every other producer of the same root.
    "fingerprint-the-path-string-instead-of-the-root": (
        KERNEL,
        '        "device": int(status.st_dev),\n        "inode": int(status.st_ino),\n',
        '        "device": 0,\n        "inode": 0,\n',
        f"{KERNEL_TESTS}::"
        "test_two_producers_agree_on_one_root_and_it_is_not_a_path_digest",
    ),
    # --- the terminal record: terminal state, or nothing ------------------
    "record-a-granted-only-lease-as-terminal": (
        KERNEL,
        "    if replay is None:\n",
        "    if False and replay is None:\n",
        f"{KERNEL_TESTS}::test_a_granted_only_lease_produces_no_terminal_record",
    ),
    "record-a-started-only-execution-as-terminal": (
        KERNEL,
        "    if replay.pending_reconciliation or terminal is None:\n",
        "    if False and (replay.pending_reconciliation or terminal is None):\n",
        f"{KERNEL_TESTS}::test_a_started_only_execution_produces_no_terminal_record",
    ),
    "emit-the-kernels-uppercase-terminal-state": (
        KERNEL,
        "    state = str(replay.state).lower()\n",
        "    state = str(replay.state)\n",
        f"{KERNEL_TESTS}::test_a_terminal_execution_is_recorded_in_lowercase",
    ),
    # --- the issuer key round-trip (MEASURED: 1-in-7 before the flag) -----
    "write-the-issuer-key-in-text-mode": (
        KERNEL,
        "os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, \"O_BINARY\", 0),\n"
        "                0o600,\n",
        "os.O_CREAT | os.O_EXCL | os.O_WRONLY,\n"
        "                0o600,\n",
        f"{KERNEL_TESTS}::test_the_issuer_key_survives_its_own_write",
    ),
    # --- what a reader of the store refuses -------------------------------
    "accept-a-tampered-record": (
        PRODUCER,
        '            if _record_sha256(record) != record.get("record_sha256"):\n',
        '            if False and _record_sha256(record) != record.get("record_sha256"):\n',
        f"{KERNEL_TESTS}::test_a_tampered_record_is_refused_by_its_own_digest",
    ),
    "accept-a-record-from-another-control-root": (
        PRODUCER,
        '            if record.get("control_root_sha256") != control_root_sha256:\n',
        '            if False and record.get("control_root_sha256") != control_root_sha256:\n',
        f"{KERNEL_TESTS}::test_a_record_from_another_control_root_is_refused",
    ),
    "accept-a-record-bound-to-another-revision": (
        PRODUCER,
        '            if record.get("source_revision") != source_revision:\n',
        '            if False and record.get("source_revision") != source_revision:\n',
        f"{KERNEL_TESTS}::test_a_record_bound_to_another_revision_is_refused",
    ),
    # --- the replay in front of the central row ---------------------------
    "trust-the-retained-field-instead-of-replaying": (
        PRODUCER,
        "            replay_non_runtime_effect_subject(\n"
        '                replay_subject, expected_execution_id=str(terminal["execution_id"])\n'
        "            )\n",
        "            pass\n",
        f"{PRODUCER_TESTS}::test_a_terminal_record_naming_another_execution_is_refused",
    ),
    "serialise-an-admitted-row-into-the-declaration": (
        PRODUCER,
        "    if admitted:\n        raise DeclarationError(\n",
        "    if False and admitted:\n        raise DeclarationError(\n",
        f"{PRODUCER_TESTS}::test_the_declaration_file_refuses_to_carry_an_admitted_row",
    ),
    # --- the issuer's refusal predicate -----------------------------------
    # One mutation per conjunct of `issuable_row`. Disabling any of them turns
    # the issuer back into what the hard-coded ENTRYPOINT_ID was protecting
    # against: a helper that mints a capability for a row whose guards it did
    # not run, or whose effects the scope it builds cannot bound.
    "issue-for-a-row-whose-contracts-this-issuer-cannot-run": (
        KERNEL,
        "    unrunnable = sorted(set(spec.guard_contracts) - ISSUER_CONTRACTS)\n",
        "    unrunnable = []\n",
        f"{RULE_TESTS}::"
        "test_a_row_whose_contracts_this_issuer_cannot_run_is_refused_by_name",
    ),
    "issue-for-a-runtime-bearing-row": (
        KERNEL,
        "    if spec.runtime_id:\n        reasons.append(\n",
        "    if False and spec.runtime_id:\n        reasons.append(\n",
        f"{RULE_TESTS}::test_a_runtime_bearing_row_is_refused",
    ),
    "issue-for-a-non-central-row": (
        KERNEL,
        "    if spec.wiring is not Wiring.CENTRAL:\n",
        "    if False and spec.wiring is not Wiring.CENTRAL:\n",
        f"{RULE_TESTS}::test_a_non_central_row_is_refused",
    ),
    "issue-for-a-row-whose-effects-the-scope-cannot-bound": (
        KERNEL,
        "    unboundable = sorted(declared_effects - ISSUER_EFFECTS)\n",
        "    unboundable = []\n",
        f"{RULE_TESTS}::test_a_row_whose_effects_the_scope_cannot_bound_is_refused",
    ),
    "bound-an-effect-with-a-contract-the-row-never-declared": (
        KERNEL,
        "        if EFFECT_BOUNDS[effect] not in spec.guard_contracts\n",
        "        if False and EFFECT_BOUNDS[effect] not in spec.guard_contracts\n",
        f"{RULE_TESTS}::test_the_gate_door_is_refused_for_an_unfenced_write",
    ),
    # --- what a grant for a row that is not python.offload may carry -------
    "decide-a-contract-the-row-did-not-declare": (
        KERNEL,
        '    if "containment.attempt" in declared_contracts:\n',
        "    if True:\n",
        f"{RULE_TESTS}::test_the_grant_can_really_start_an_execution",
    ),
    "grant-a-write-root-to-a-row-that-declares-no-write": (
        KERNEL,
        "    if not writes:\n        declared_paths = ()\n",
        "    if False and not writes:\n        declared_paths = ()\n",
        f"{RULE_TESTS}::test_a_row_without_egress_or_spend_is_granted_neither",
    ),
    "retain-a-disjointness-record-for-a-row-that-took-no-decision": (
        KERNEL,
        "    if not (declared_contracts & CONTAINMENT_CONTRACTS):\n",
        "    if False and not (declared_contracts & CONTAINMENT_CONTRACTS):\n",
        f"{RULE_TESTS}::"
        "test_a_row_with_no_containment_contract_retains_no_disjointness_record",
    ),
    # AMBIGUOUS SINCE 11dc0195, and the runner caught it: `acquire_attempt_lease`
    # landed with a guard whose first line is identical to the wave wrapper's,
    # so the old one-line needle resolved twice. Two guards sharing one anchor
    # means disabling one goes unnoticed, which is precisely what this runner
    # refuses to allow -- so each needle now carries the message that names its
    # own wrapper, and the second guard gets an anchor of its own.
    "let-the-wave-wrapper-be-told-which-row": (
        KERNEL,
        '    if "entrypoint_id" in kwargs:\n'
        "        raise TypeError(\n"
        '            "acquire_wave_offload_lease() issues for python.offload only; call "\n',
        '    if kwargs.pop("entrypoint_id", None) and False:\n'
        "        raise TypeError(\n"
        '            "acquire_wave_offload_lease() issues for python.offload only; call "\n',
        f"{RULE_TESTS}::test_the_wave_wrapper_refuses_to_be_told_which_row",
    ),
    "let-the-attempt-wrapper-be-told-which-row": (
        KERNEL,
        '    if "entrypoint_id" in kwargs:\n'
        "        raise TypeError(\n"
        '            "acquire_attempt_lease() issues for python.attempt only; call "\n',
        '    if kwargs.pop("entrypoint_id", None) and False:\n'
        "        raise TypeError(\n"
        '            "acquire_attempt_lease() issues for python.attempt only; call "\n',
        f"{ATTEMPT_TESTS}::test_the_wrapper_pins_the_row_and_demands_the_effect_key",
    ),
    # --- the lease-dominance guard ----------------------------------------
    # A door that HELD a lease is not a write that was UNDER one.
    "classify-a-surface-the-lease-does-not-dominate-as-central": (
        PRODUCER,
        "            and lease_dominated\n",
        "            and True\n",
        f"{DOMINANCE_TESTS}::"
        "test_a_write_between_the_receipt_and_the_lease_is_not_central",
    ),
    "seed-the-leased-region-from-the-free-receipt-call": (
        PRODUCER,
        "        and isinstance(node.func, ast.Attribute)\n"
        '        and node.func.attr == "begin_effect"\n',
        '        and getattr(node.func, "attr", getattr(node.func, "id", "")) '
        '== "begin_effect"\n',
        f"{DOMINANCE_TESTS}::"
        "test_a_door_that_consumes_no_lease_has_an_empty_leased_region",
    ),
    "report-an-authenticated-door-that-classified-nothing-as-silence": (
        PRODUCER,
        "        if not held:\n",
        "        if not held and False:\n",
        f"{DOMINANCE_TESTS}::"
        "test_an_authenticated_door_that_classifies_nothing_says_so",
    ),
    "reuse-the-anchor-region-as-the-leased-region": (
        PRODUCER,
        "        leased_positions = frozenset()\n        leased_refusal = (\n",
        "        leased_positions = positions\n        leased_refusal = (\n",
        f"{DOMINANCE_TESTS}::"
        "test_a_door_that_consumes_no_lease_has_an_empty_leased_region",
    ),
    # --- the authority/subject split --------------------------------------
    # Three guards, therefore three anchors. The count follows the guards, not
    # a target: `repo_root` used to decide the control root, the write fence
    # and the measured checkout all at once, and each of those is a separate
    # way for a candidate to be judged by something it chose.
    "let-the-subject-root-choose-the-authority": (
        KERNEL,
        "    subject_checkout = (\n"
        "        str(Path(subject_root).resolve()) if subject_root is not None else root\n"
        "    )\n",
        "    subject_checkout = (\n"
        "        str(Path(subject_root).resolve()) if subject_root is not None else root\n"
        "    )\n"
        "    root = subject_checkout\n",
        f"{SPLIT_TESTS}::test_the_write_fence_stays_the_operators",
    ),
    "measure-containment-over-the-default-manager": (
        KERNEL,
        "    if worktree_root is not None:\n"
        "        return str(root), str(Path(worktree_root).resolve())\n",
        "    if False and worktree_root is not None:\n"
        "        return str(root), str(Path(worktree_root).resolve())\n",
        f"{SPLIT_TESTS}::test_the_roots_helper_returns_the_callers_pair",
    ),
    "ignore-the-authority-checkout-when-measuring-containment": (
        KERNEL,
        "    if authority is not None and authority != root:\n",
        "    if False and authority is not None and authority != root:\n",
        f"{SPLIT_TESTS}::"
        "test_a_planned_root_inside_the_authority_checkout_is_refused",
    ),
}


def _run(*tests: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        timeout=600,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    originals = {path: path.read_text(encoding="utf-8") for path in (KERNEL, PRODUCER)}
    try:
        baseline = _run(
            KERNEL_TESTS, PRODUCER_TESTS, RULE_TESTS, DOMINANCE_TESTS,
            SPLIT_TESTS, ATTEMPT_TESTS,
        )
    except subprocess.TimeoutExpired:
        print("baseline timed out", file=sys.stderr)
        return 2
    if baseline.returncode != 0:
        print("baseline failed before mutations", file=sys.stderr)
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    timeouts: list[str] = []
    try:
        for name, (target, needle, replacement, test_id) in MUTATIONS.items():
            original = originals[target]
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            target.write_text(original.replace(needle, replacement, 1), encoding="utf-8")
            try:
                completed = _run(test_id)
            except subprocess.TimeoutExpired:
                timeouts.append(name)
            else:
                if completed.returncode == 0:
                    survivors.append(name)
            finally:
                target.write_text(original, encoding="utf-8")
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} write-evidence production mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

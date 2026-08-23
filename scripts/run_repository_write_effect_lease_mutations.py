#!/usr/bin/env python3
"""Run bounded trust-boundary mutations for repository-write Effect-Lease replay."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_effect_lease.py"
TEST_FILE = "tests/gates/test_repository_write_effect_lease.py"
REVIEW_FILE = "tests/gates/test_repository_write_effect_lease_review.py"
ADMISSION_FILE = "tests/gates/test_repository_write_non_runtime_conformity_admission.py"
V2_FILE = "tests/gates/test_repository_write_effect_lease_non_runtime.py"
MUTATIONS = {
    "allow-missing-start": (
        "if replay is None:\n        raise RepositoryWriteEffectLeaseBindingError(",
        "if False and replay is None:\n        raise RepositoryWriteEffectLeaseBindingError(",
        "test_missing_start_refuses_automatic_reexecution",
    ),
    "allow-pending-start": (
        "if terminal is None or replay.pending_reconciliation:",
        "if False and (terminal is None or replay.pending_reconciliation):",
        "test_started_execution_refuses_automatic_reexecution",
    ),
    "ignore-terminal-digest": (
        "if terminal.receipt_sha256 != receipt_sha256:",
        "if False and terminal.receipt_sha256 != receipt_sha256:",
        "test_terminal_digest_entrypoint_and_state_substitution_refuse",
    ),
    "ignore-entrypoint-binding": (
        "if subject.entrypoint_id != entrypoint_id:",
        "if False and subject.entrypoint_id != entrypoint_id:",
        "test_terminal_digest_entrypoint_and_state_substitution_refuse",
    ),
    "ignore-terminal-state": (
        "if replay.state.lower() != terminal_state:",
        "if False and replay.state.lower() != terminal_state:",
        "test_terminal_digest_entrypoint_and_state_substitution_refuse",
    ),
    "accept-extra-subjects": (
        "if set(subject_snapshot) != required_receipts:",
        "if not required_receipts.issubset(set(subject_snapshot)):",
        "test_exact_subject_set_and_revision_are_required",
    ),
    "ignore-predecessor-materialization": (
        '"runtime_materialization": (\n            runtime_report.materialization_digest,\n            materialization.digest,\n        ),',
        '"runtime_materialization": (\n            materialization.digest,\n            materialization.digest,\n        ),',
        "test_predecessor_detachment_refuses_before_effect_inspection",
    ),
    "claim-gate-closure": (
        '"closed": False,',
        '"closed": True,',
        "",
    ),
    # This stage alone never authenticates a surface: the effect-lease replay
    # proves one stage ran, not that every applicable stage did.  The literal
    # was unpinned until now, so a flip to ``True`` here would have travelled
    # into the report with nothing noticing.
    "forge-evidence-authentication": (
        '"evidence_authenticated": False,',
        '"evidence_authenticated": True,',
        "",
    ),
    # --- the typed non-runtime replay ------------------------------------
    # The check the classification row calls before it will admit a binding.
    # Without this branch a runtime-bound authorization replays as a
    # non-runtime one and buys its way out of the conformity stage.
    "replay-a-runtime-subject-as-non-runtime": (
        "    if subject.runtime_bound:\n"
        "        raise RepositoryWriteEffectLeaseBindingError(\n"
        '            "surface declared non-runtime replays as a runtime-bound authorization"\n'
        "        )\n",
        "    if False:\n"
        "        raise RepositoryWriteEffectLeaseBindingError(\n"
        '            "surface declared non-runtime replays as a runtime-bound authorization"\n'
        "        )\n",
        f"{ADMISSION_FILE}::test_binding_whose_execution_replays_as_runtime_is_refused",
    ),
    "ignore-the-binding-execution-identity": (
        "    if subject.execution.execution_id != expected_execution_id:\n",
        "    if False and subject.execution.execution_id != expected_execution_id:\n",
        f"{ADMISSION_FILE}::test_a_signature_is_not_a_replay",
    ),
    # --- the /2 consumer --------------------------------------------------
    # Demanding a conformance record for an excused surface is the /1 rule
    # again, and it would make the relaxation unreachable.
    "demand-a-conformance-record-for-an-excused-surface": (
        "        if not excused and type(runtime_record) is not RuntimeConformanceReplayRecord:\n",
        "        if type(runtime_record) is not RuntimeConformanceReplayRecord:\n",
        f"{V2_FILE}::test_zero_receipts_with_a_binding_verifies_and_records_a_null_digest",
    ),
    "accept-a-mismatched-excused-surface-set": (
        "    if declared_non_runtime != excused_surfaces:\n",
        "    if False and declared_non_runtime != excused_surfaces:\n",
        f"{V2_FILE}::test_a_row_without_an_admission_cannot_be_excused_by_the_predecessor",
    ),
}


def _run(*tests: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        timeout=180,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    try:
        baseline = _run(TEST_FILE, REVIEW_FILE)
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
        for name, (needle, replacement, test_name) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            # A node id that already names its file travels as written;
            # the older anchors name only a test in TEST_FILE.
            if not test_name:
                selected = REVIEW_FILE
            elif "::" in test_name:
                selected = test_name
            else:
                selected = f"{TEST_FILE}::{test_name}"
            try:
                completed = _run(selected)
            except subprocess.TimeoutExpired:
                timeouts.append(name)
            else:
                if completed.returncode == 0:
                    survivors.append(name)
            finally:
                TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} repository-write Effect-Lease mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

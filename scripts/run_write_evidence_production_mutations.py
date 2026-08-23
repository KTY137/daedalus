#!/usr/bin/env python3
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
        baseline = _run(KERNEL_TESTS, PRODUCER_TESTS)
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

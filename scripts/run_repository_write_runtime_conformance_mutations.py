#!/usr/bin/env python3
"""Run bounded mutations against runtime-conformance semantic replay."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_runtime_conformance.py"
TEST_FILE = "tests/gates/test_repository_write_runtime_conformance.py"
MUTATIONS = {
    "forge-complete-semantics": (
        '"semantic_receipts_verified": False',
        '"semantic_receipts_verified": True',
        "test_runtime_conformance_is_replayed_against_active_persisted_trust",
    ),
    "forge-evidence-authentication": (
        '"evidence_authenticated": False',
        '"evidence_authenticated": True',
        "test_runtime_conformance_is_replayed_against_active_persisted_trust",
    ),
    "forge-gate-binding": (
        '"gate_report_bound": False',
        '"gate_report_bound": True',
        "test_runtime_conformance_is_replayed_against_active_persisted_trust",
    ),
    "forge-closed": (
        '"closed": False',
        '"closed": True',
        "test_runtime_conformance_is_replayed_against_active_persisted_trust",
    ),
    "allow-local-production": (
        "if noncentral:",
        "if False and noncentral:",
        "test_every_production_row_must_be_central",
    ),
    "allow-duplicate-runtime-binding": (
        "if len(runtime_bindings) != 1:",
        "if False and len(runtime_bindings) != 1:",
        "test_duplicate_runtime_bindings_fail_before_subject_selection",
    ),
    "ignore-subject-set": (
        "if set(subject_snapshot) != required_receipts:",
        "if False and set(subject_snapshot) != required_receipts:",
        "test_runtime_receipt_reference_must_have_exact_subject",
    ),
    "ignore-ledger-set": (
        "if set(ledger_snapshot) != required_runtime_ids:",
        "if False and set(ledger_snapshot) != required_runtime_ids:",
        "test_trust_ledger_set_is_exact",
    ),
    "allow-expired-trust": (
        "if now >= _parse_utc(record.expires_at, \"runtime trust expires_at\"):",
        "if False and now >= _parse_utc(record.expires_at, \"runtime trust expires_at\"):",
        "test_unadmitted_quarantined_and_expired_trust_fail",
    ),
    "ignore-predecessor-chain": (
        "if mismatches:\n        raise RepositoryWriteRuntimeConformanceBindingError(\n            \"repository-write runtime predecessor chain mismatch: \"",
        "if False and mismatches:\n        raise RepositoryWriteRuntimeConformanceBindingError(\n            \"repository-write runtime predecessor chain mismatch: \"",
        "test_predecessor_report_cannot_be_detached",
    ),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
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
                original.replace(needle, replacement),
                encoding="utf-8",
            )
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        f"{TEST_FILE}::{test_name}",
                    ],
                    cwd=ROOT,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=45,
                    env={
                        **os.environ,
                        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                    },
                )
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
    print(f"killed {len(MUTATIONS)} runtime-replay mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

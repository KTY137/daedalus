#!/usr/bin/env python3
"""Run bounded adversarial mutations against guard structural replay."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository/write_guard_structure.py"
TEST_FILE = "tests/gates/test_repository_write_guard_structure.py"
MUTATIONS = {
    "forge-guard-semantics": (
        '"guard_contract_semantics_verified": False',
        '"guard_contract_semantics_verified": True',
        "test_guard_structure_joins_authenticated_subjects_without_behavior_claim",
    ),
    "forge-evidence-authentication": (
        '"evidence_authenticated": False',
        '"evidence_authenticated": True',
        "test_guard_structure_joins_authenticated_subjects_without_behavior_claim",
    ),
    "forge-gate-binding": (
        '"gate_report_bound": False',
        '"gate_report_bound": True',
        "test_guard_structure_joins_authenticated_subjects_without_behavior_claim",
    ),
    "forge-closed": (
        '"closed": False',
        '"closed": True',
        "test_guard_structure_joins_authenticated_subjects_without_behavior_claim",
    ),
    "allow-unguarded-production": (
        "if invalid_rows:",
        "if False and invalid_rows:",
        "test_inventory_only_production_path_cannot_pass_vacuously",
    ),
    "ignore-manifest-contract-set": (
        "if set(manifest_by_contract) != required_contracts:",
        "if False and set(manifest_by_contract) != required_contracts:",
        "test_manifest_contract_set_must_equal_production_contracts",
    ),
    "allow-duplicate-binding": (
        "len(bindings) != 1 for bindings in bindings_by_contract.values()",
        "False and len(bindings) != 1 for bindings in bindings_by_contract.values()",
        "test_duplicate_guard_binding_for_one_contract_is_refused",
    ),
    "ignore-target-binding": (
        "if entry.implementation_target != target:",
        "if False and entry.implementation_target != target:",
        "test_guard_evidence_target_must_equal_authenticated_manifest",
    ),
    "ignore-source-binding": (
        "if entry.implementation_sha256 != implementation_sha256:",
        "if False and entry.implementation_sha256 != implementation_sha256:",
        "test_guard_evidence_digest_must_equal_authenticated_manifest",
    ),
    "ignore-chain-mismatch": (
        "if mismatches:",
        "if False and mismatches:",
        "test_cross_layer_source_and_manifest_reports_cannot_be_detached",
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
                    timeout=40,
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
    print(f"killed {len(MUTATIONS)} guard-structure mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

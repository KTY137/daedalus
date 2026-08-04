#!/usr/bin/env python3
"""Run bounded mutations against guard-behavior attestation authentication."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/guard_behavior_attestation.py"
TEST_FILE = "tests/gates/test_guard_behavior_attestation.py"
MUTATIONS = {
    "forge-guard-semantics": (
        '"guard_contract_semantics_verified": False',
        '"guard_contract_semantics_verified": True',
        "test_issue_parse_verify_is_deterministic_and_honestly_open",
    ),
    "forge-runtime-conformance": (
        '"runtime_conformance_verified": False',
        '"runtime_conformance_verified": True',
        "test_issue_parse_verify_is_deterministic_and_honestly_open",
    ),
    "forge-evidence-authentication": (
        '"evidence_authenticated": False',
        '"evidence_authenticated": True',
        "test_issue_parse_verify_is_deterministic_and_honestly_open",
    ),
    "forge-gate-binding": (
        '"gate_report_bound": False',
        '"gate_report_bound": True',
        "test_issue_parse_verify_is_deterministic_and_honestly_open",
    ),
    "forge-closed": (
        '"closed": False',
        '"closed": True',
        "test_issue_parse_verify_is_deterministic_and_honestly_open",
    ),
    "bypass-signature": (
        "if not hmac.compare_digest(\n        expected_signature, attestation.signature_sha256\n    ):",
        "if False and not hmac.compare_digest(\n        expected_signature, attestation.signature_sha256\n    ):",
        "test_signature_is_checked_before_subject_bindings",
    ),
    "bypass-contract-set": (
        "if case_contracts != required_contracts:",
        "if False and case_contracts != required_contracts:",
        "test_contract_set_substitution_refuses",
    ),
    "bypass-positive-negative-coverage": (
        "if expected_outcomes != _OUTCOMES:",
        "if False and expected_outcomes != _OUTCOMES:",
        "test_multiple_contracts_require_exact_positive_and_negative_coverage",
    ),
    "bypass-failed-case": (
        "if any(\n            case.observed_outcome != case.expected_outcome\n            for case in contract_cases\n        ):",
        "if False and any(\n            case.observed_outcome != case.expected_outcome\n            for case in contract_cases\n        ):",
        "test_failed_case_refuses_authenticated_projection",
    ),
    "allow-noncanonical-wire": (
        "if raw != canonical:",
        "if False and raw != canonical:",
        "test_noncanonical_valid_wire_is_rejected_before_schema_projection",
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
            for cached in (TARGET.parent / "__pycache__").glob(
                "guard_behavior_attestation.*.pyc"
            ):
                cached.unlink()
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
                    timeout=30,
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
                for cached in (TARGET.parent / "__pycache__").glob(
                    "guard_behavior_attestation.*.pyc"
                ):
                    cached.unlink()
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if survivors or timeouts:
        if survivors:
            print(
                "surviving mutations: " + ", ".join(survivors),
                file=sys.stderr,
            )
        if timeouts:
            print(
                "timed-out mutations: " + ", ".join(timeouts),
                file=sys.stderr,
            )
        return 1
    print(f"killed {len(MUTATIONS)} guard-behavior mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

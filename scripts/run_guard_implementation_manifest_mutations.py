#!/usr/bin/env python3
"""Run bounded mutations against guard-manifest authentication."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/guard_implementation_manifest.py"
TEST_FILE = "tests/gates/test_guard_implementation_manifest.py"
MUTATIONS = {
    "forge-guard-semantics": (
        '"guard_contract_semantics_verified": False',
        '"guard_contract_semantics_verified": True',
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
        "if not hmac.compare_digest(\n        expected_signature,\n        manifest.signature_sha256,\n    ):",
        "if False and not hmac.compare_digest(\n        expected_signature,\n        manifest.signature_sha256,\n    ):",
        "test_signed_entry_or_subject_substitution_fails",
    ),
    "bypass-stale-revision": (
        "if manifest.source_revision != revision:",
        "if False and manifest.source_revision != revision:",
        "test_stale_revision_and_classification_fail_after_authentication",
    ),
    "bypass-stale-classification": (
        "if manifest.classification_digest != classification_digest:",
        "if False and manifest.classification_digest != classification_digest:",
        "test_stale_revision_and_classification_fail_after_authentication",
    ),
    "allow-noncanonical-wire": (
        "if raw != canonical:",
        "if False and raw != canonical:",
        "test_noncanonical_wire_is_rejected_before_schema_projection",
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
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} guard-manifest mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

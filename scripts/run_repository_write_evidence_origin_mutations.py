#!/usr/bin/env python3
"""Run bounded adversarial mutations against origin authentication."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_evidence_origin.py"
TESTS = (
    "tests/gates/test_repository_write_evidence_origin.py",
    "tests/gates/test_repository_write_evidence_origin_review.py",
)
MUTATIONS = {
    "forge-semantic-verification": (
        '"semantic_receipts_verified": False',
        '"semantic_receipts_verified": True',
    ),
    "forge-evidence-authentication": (
        '"evidence_authenticated": False',
        '"evidence_authenticated": True',
    ),
    "forge-gate-binding": (
        '"gate_report_bound": False',
        '"gate_report_bound": True',
    ),
    "forge-closed": (
        '"closed": False',
        '"closed": True',
    ),
    "allow-incomplete-materialization": (
        "if not materialization.materialization_complete:",
        "if False and not materialization.materialization_complete:",
    ),
    "ignore-signature": (
        "if not hmac.compare_digest(\n"
        "        attestation.signature_sha256,\n"
        "        expected_signature,\n"
        "    ):",
        "if False and not hmac.compare_digest(\n"
        "        attestation.signature_sha256,\n"
        "        expected_signature,\n"
        "    ):",
    ),
    "accept-future-attestation": (
        "if issued > instant:",
        "if False and issued > instant:",
    ),
    "accept-expired-attestation": (
        "if instant >= expires:",
        "if False and instant >= expires:",
    ),
    "ignore-size-bound": (
        "if len(raw) > _MAX_ATTESTATION_BYTES:",
        "if False and len(raw) > _MAX_ATTESTATION_BYTES:",
    ),
    "ignore-canonical-bytes": (
        "if raw != canonical:",
        "if False and raw != canonical:",
    ),
    "ignore-record-set-binding": (
        "if not hmac.compare_digest(self.record_set_sha256, expected_set):",
        "if False and not hmac.compare_digest(self.record_set_sha256, expected_set):",
    ),
    "ignore-collector-binding": (
        '"collector_id": (attestation.collector_id, collector),',
        '"collector_id": (collector, collector),',
    ),
    "ignore-source-revision-binding": (
        '"source_revision": (attestation.source_revision, revision),',
        '"source_revision": (revision, revision),',
    ),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    survivors: list[str] = []
    try:
        for name, (needle, replacement) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            TARGET.write_text(
                original.replace(needle, replacement),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *TESTS],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            )
            if completed.returncode == 0:
                survivors.append(name)
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if survivors:
        print(
            "surviving mutations: " + ", ".join(survivors),
            file=sys.stderr,
        )
        return 1
    print(f"killed {len(MUTATIONS)} origin-authentication mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run bounded adversarial mutations against evidence materialization."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_evidence_materialization.py"
TESTS = (
    "tests/gates/test_repository_write_evidence_materialization.py",
    "tests/gates/test_repository_write_evidence_materialization_review.py",
)
MUTATIONS = {
    "forge-closed": ('"closed": False', '"closed": True'),
    "forge-origin-authentication": (
        '"origin_authenticated": False',
        '"origin_authenticated": True',
    ),
    "forge-semantic-verification": (
        '"semantic_receipts_verified": False',
        '"semantic_receipts_verified": True',
    ),
    "allow-vacuous-completeness": (
        "return self.binding_count > 0 and not self.missing_locators",
        "return not self.missing_locators",
    ),
    "ignore-raw-digest": (
        "if raw_sha256 != binding.sha256:",
        "if False and raw_sha256 != binding.sha256:",
    ),
    "ignore-canonical-bytes": (
        "if raw != canonical:",
        "if False and raw != canonical:",
    ),
    "ignore-size-bound": (
        "if len(raw) > _MAX_EVIDENCE_BYTES:",
        "if False and len(raw) > _MAX_EVIDENCE_BYTES:",
    ),
    "forge-partial-canonical-verification": (
        '"canonical_bytes_verified": self.materialization_complete',
        '"canonical_bytes_verified": True',
    ),
    "forge-partial-binding-verification": (
        '"binding_verified": self.materialization_complete',
        '"binding_verified": True',
    ),
    "allow-unexpected-blobs": (
        "if set(blobs) - expected_locators:",
        "if False and set(blobs) - expected_locators:",
    ),
    "allow-reused-evidence": (
        '        if binding.locator in expected_locators:\n'
        '            raise RepositoryWriteEvidenceMaterializationError(\n'
        '                "evidence locator is reused across bindings"\n'
        '            )\n'
        '        if binding.sha256 in seen_blob_digests:\n'
        '            raise RepositoryWriteEvidenceMaterializationError(\n'
        '                "evidence blob digest is reused across bindings"\n'
        '            )',
        '        # mutated: reused locators and digests accepted',
    ),
    "ignore-payload-digest": (
        'if document["payload_sha256"] != payload_sha256:',
        'if False and document["payload_sha256"] != payload_sha256:',
    ),
    "accept-false-runtime-conformance": (
        'if payload["conformant"] is not True:',
        'if False and payload["conformant"] is not True:',
    ),
    "accept-false-checkout-disjointness": (
        'if payload["disjoint"] is not True:',
        'if False and payload["disjoint"] is not True:',
    ),
    "accept-reachable-retirement": (
        'if payload["production_reachable"] is not False:',
        'if False and payload["production_reachable"] is not False:',
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
                original.replace(needle, replacement), encoding="utf-8"
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
        print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} evidence-materialization mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

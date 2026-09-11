#!/usr/bin/env python3
"""Run bounded mutations over repository-write artifact byte verification."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository/write_artifact_verifier.py"
TESTS = (
    "tests/gates/test_repository_write_artifact_verifier.py",
    "tests/gates/test_repository_write_artifact_verifier_types.py",
    "tests/gates/test_repository_write_artifact_verifier_review.py",
    "tests/gates/test_repository_write_artifact_verifier_schema.py",
)

MUTATIONS = {
    "accept-non-exact-bytes": (
        "    if type(raw) is not bytes:\n",
        "    if False and type(raw) is not bytes:\n",
    ),
    "accept-empty-or-oversized-bytes": (
        "    if not raw or len(raw) > _MAX_ARTIFACT_BYTES:\n",
        "    if False and (not raw or len(raw) > _MAX_ARTIFACT_BYTES):\n",
    ),
    "accept-artifact-subclass": (
        "    if type(artifact) is not RepositoryWriteArtifactEvidence:\n",
        "    if False and type(artifact) is not RepositoryWriteArtifactEvidence:\n",
    ),
    "accept-report-subclass": (
        "    if type(report) is not GateReportV3:\n",
        "    if False and type(report) is not GateReportV3:\n",
    ),
    "skip-content-digest": (
        "    if content_sha256 != artifact.artifact_content_sha256:\n",
        "    if False and content_sha256 != artifact.artifact_content_sha256:\n",
    ),
    "skip-report-binding": (
        "    if report_blockers:\n",
        "    if False and report_blockers:\n",
    ),
    "accept-noncanonical-inventory-payload": (
        "    if payload != inventory.to_dict():\n",
        "    if False and payload != inventory.to_dict():\n",
    ),
    "skip-inventory-digest": (
        "    if inventory.digest != artifact.inventory_sha256:\n",
        "    if False and inventory.digest != artifact.inventory_sha256:\n",
    ),
    "skip-scan-input-digest": (
        "    if inventory.scan_input_sha256 != artifact.scan_input_sha256:\n",
        "    if False and inventory.scan_input_sha256 != artifact.scan_input_sha256:\n",
    ),
    "skip-file-count": (
        "    if inventory.files_scanned != artifact.files_scanned:\n",
        "    if False and inventory.files_scanned != artifact.files_scanned:\n",
    ),
    "skip-failure-set-digest": (
        "    if canonical_sha(list(failures)) != artifact.failure_set_sha256:\n",
        "    if False and canonical_sha(list(failures)) != artifact.failure_set_sha256:\n",
    ),
    "skip-failure-count": (
        "    if len(failures) != artifact.failure_count:\n",
        "    if False and len(failures) != artifact.failure_count:\n",
    ),
    "accept-incomplete-receipt-checks": (
        "        if self.checks != _VERIFICATION_CHECKS:\n",
        "        if False and self.checks != _VERIFICATION_CHECKS:\n",
    ),
}


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    try:
        baseline = _run()
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
        for name, (needle, replacement) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            try:
                completed = _run()
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
    print(f"killed {len(MUTATIONS)} repository-write verifier mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

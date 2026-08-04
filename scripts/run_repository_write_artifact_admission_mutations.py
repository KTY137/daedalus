#!/usr/bin/env python3
"""Run bounded mutations over atomic repository-write artifact admission."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_artifact_admission.py"
TESTS = (
    "tests/gates/test_repository_write_artifact_admission.py",
    "tests/gates/test_repository_write_artifact_admission_adversarial.py",
    "tests/gates/test_repository_write_artifact_admission_review.py",
    "tests/gates/test_repository_write_artifact_admission_schema.py",
)


@dataclass(frozen=True)
class Mutation:
    needle: str
    replacement: str
    expected_count: int = 1
    replace_count: int = 1


MUTATIONS = {
    "accept-artifact-subclass": Mutation(
        "    if type(artifact) is not RepositoryWriteArtifactEvidence:\n",
        "    if False and type(artifact) is not RepositoryWriteArtifactEvidence:\n",
    ),
    "accept-report-subclass": Mutation(
        "    if type(report) is not GateReportV3:\n",
        "    if False and type(report) is not GateReportV3:\n",
    ),
    "accept-root-subclass": Mutation(
        "    if type(root) is not RepositoryWriteArtifactCASRoot:\n",
        "    if False and type(root) is not RepositoryWriteArtifactCASRoot:\n",
    ),
    "detach-source-revision": Mutation(
        "        if resolution.source_revision != verification.source_revision:\n",
        "        if False and resolution.source_revision != verification.source_revision:\n",
        expected_count=1,
    ),
    "detach-source-tree-revision": Mutation(
        "        if resolution.source_tree_revision != verification.source_tree_revision:\n",
        "        if False and resolution.source_tree_revision != verification.source_tree_revision:\n",
        expected_count=1,
    ),
    "detach-artifact-evidence": Mutation(
        "        if resolution.artifact_evidence_sha256 != verification.artifact_evidence_sha256:\n",
        "        if False and resolution.artifact_evidence_sha256 != verification.artifact_evidence_sha256:\n",
        expected_count=1,
    ),
    "detach-content-digest": Mutation(
        "    if resolution.artifact_content_sha256 != verification.artifact_content_sha256:\n",
        "    if False and resolution.artifact_content_sha256 != verification.artifact_content_sha256:\n",
    ),
    "detach-gate-report": Mutation(
        "    if verification.gate_report_v3_sha256 != report_sha256:\n",
        "    if False and verification.gate_report_v3_sha256 != report_sha256:\n",
    ),
    "omit-verification-receipt-binding": Mutation(
        '            "verification_receipt_sha256": verification.digest,\n',
        "",
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
        for name, mutation in MUTATIONS.items():
            count = original.count(mutation.needle)
            if count != mutation.expected_count:
                raise RuntimeError(
                    f"mutation {name} expected {mutation.expected_count} source "
                    f"anchors, found {count}"
                )
            mutated = original.replace(
                mutation.needle,
                mutation.replacement,
                mutation.replace_count,
            )
            TARGET.write_text(mutated, encoding="utf-8")
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
    print(f"killed {len(MUTATIONS)} repository-write admission mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

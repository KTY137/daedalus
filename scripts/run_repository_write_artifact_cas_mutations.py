#!/usr/bin/env python3
"""Run bounded mutations over repository-write artifact CAS resolution."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository/write_artifact_cas.py"
TESTS = (
    "tests/gates/test_repository_write_artifact_cas.py",
    "tests/gates/test_repository_write_artifact_cas_adversarial.py",
    "tests/gates/test_repository_write_artifact_cas_receipt.py",
    "tests/gates/test_repository_write_artifact_cas_review.py",
    "tests/gates/test_repository_write_artifact_cas_schema.py",
    "tests/gates/test_repository_write_artifact_cas_toctou.py",
)

MUTATIONS = {
    "accept-root-subclass": (
        "    if type(root) is not RepositoryWriteArtifactCASRoot:\n",
        "    if False and type(root) is not RepositoryWriteArtifactCASRoot:\n",
    ),
    "accept-artifact-subclass": (
        "    if type(artifact) is not RepositoryWriteArtifactEvidence:\n",
        "    if False and type(artifact) is not RepositoryWriteArtifactEvidence:\n",
    ),
    "accept-stale-revision": (
        "    if artifact.source_revision != root.source_revision:\n",
        "    if False and artifact.source_revision != root.source_revision:\n",
    ),
    "accept-symlink-object": (
        "    if candidate.is_symlink():\n",
        "    if False and candidate.is_symlink():\n",
    ),
    "accept-hard-link-alias": (
        "    if before.st_nlink != 1:\n",
        "    if False and before.st_nlink != 1:\n",
    ),
    "accept-oversized-object": (
        "    if before.st_size < 1 or before.st_size > _MAX_ARTIFACT_BYTES:\n",
        "    if False and (before.st_size < 1 or before.st_size > _MAX_ARTIFACT_BYTES):\n",
    ),
    "accept-opened-descriptor-substitution": (
        "        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):\n",
        "        if False and (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):\n",
    ),
    "skip-content-digest": (
        "    if content_sha256 != artifact.artifact_content_sha256:\n",
        "    if False and content_sha256 != artifact.artifact_content_sha256:\n",
    ),
    "accept-post-read-path-replacement": (
        "    if identity_after != identity_before:\n        raise RepositoryWriteArtifactCASError(\n            \"artifact CAS object changed after read\"\n        )\n",
        "    if False and identity_after != identity_before:\n        raise RepositoryWriteArtifactCASError(\n            \"artifact CAS object changed after read\"\n        )\n",
    ),
    "accept-shard-redirection": (
        "    if _normal(parent) != _normal(resolved_parent) or not resolved_parent.is_dir():\n",
        "    if False and (_normal(parent) != _normal(resolved_parent) or not resolved_parent.is_dir()):\n",
    ),
    "accept-receipt-locator-substitution": (
        "        if _locator_sha256(self.locator) != self.artifact_content_sha256:\n",
        "        if False and _locator_sha256(self.locator) != self.artifact_content_sha256:\n",
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
    print(f"killed {len(MUTATIONS)} repository-write CAS mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

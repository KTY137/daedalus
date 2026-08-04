#!/usr/bin/env python3
"""Run bounded mutations over repository-write artifact evidence."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_evidence.py"
TESTS = (
    "tests/gates/test_repository_write_evidence.py",
    "tests/gates/test_repository_write_evidence_provenance.py",
    "tests/gates/test_repository_write_evidence_review.py",
)

MUTATIONS = {
    "accept-foreign-locator": (
        "        if _locator_sha256(self.locator) != self.artifact_content_sha256:\n",
        "        if False and _locator_sha256(self.locator) != self.artifact_content_sha256:\n",
    ),
    "accept-provenance-subclass": (
        "        if type(self.provenance) is not ContractProvenance:\n",
        "        if False and type(self.provenance) is not ContractProvenance:\n",
    ),
    "accept-legacy-generation": (
        "            if generation != 2:\n",
        "            if False and generation != 2:\n",
    ),
    "drop-artifact-content-provenance-binding": (
        "                    self.artifact_content_sha256,\n",
        "                    self.inventory_sha256,\n",
    ),
    "accept-non-v3-report": (
        "        if type(report) is not GateReportV3:\n",
        "        if False and type(report) is not GateReportV3:\n",
    ),
    "drop-inventory-digest-comparison": (
        "        if self.inventory_sha256 != report.repository_write_inventory_sha256:\n",
        "        if False and self.inventory_sha256 != report.repository_write_inventory_sha256:\n",
    ),
    "drop-failure-set-comparison": (
        "        if self.failure_set_sha256 != expected_failure_digest:\n",
        "        if False and self.failure_set_sha256 != expected_failure_digest:\n",
    ),
    "drop-failure-count-comparison": (
        "        if self.failure_count != len(report.repository_write_failures):\n",
        "        if False and self.failure_count != len(report.repository_write_failures):\n",
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
    print(f"killed {len(MUTATIONS)} repository-write evidence mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

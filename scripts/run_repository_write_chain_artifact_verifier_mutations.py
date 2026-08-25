#!/usr/bin/env python3
"""Run bounded mutations against chain-result artifact verification."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "daedalus/gates/repository_write_chain_evidence.py"
VERIFIER = ROOT / "daedalus/gates/repository_write_chain_artifact_verifier.py"
TESTS = ("tests/gates/test_repository_write_chain_artifact_verifier.py",)
MUTATIONS = {
    "accept-forged-derived-authentication": (
        EVIDENCE,
        "        if self.evidence_authenticated != derived_authenticated:\n",
        "        if False and self.evidence_authenticated != derived_authenticated:\n",
    ),
    "accept-content-digest-substitution": (
        VERIFIER,
        "    if content_sha256 != artifact.artifact_content_sha256:\n",
        "    if False and content_sha256 != artifact.artifact_content_sha256:\n",
    ),
    "accept-foreign-report-binding": (
        VERIFIER,
        "    if blockers:\n",
        "    if False and blockers:\n",
    ),
    "accept-noncanonical-chain-bytes": (
        VERIFIER,
        "    if exact != canonical:\n",
        "    if False and exact != canonical:\n",
    ),
    "accept-chain-evidence-field-substitution": (
        VERIFIER,
        "        if getattr(artifact, field_name) != expected_value:\n",
        "        if False and getattr(artifact, field_name) != expected_value:\n",
    ),
    "accept-report-chain-failure-state-contradiction": (
        VERIFIER,
        "    if result.evidence_authenticated == report_has_failures:\n",
        "    if False and result.evidence_authenticated == report_has_failures:\n",
    ),
}


def main() -> int:
    originals = {
        target: target.read_text(encoding="utf-8")
        for target, _, _ in MUTATIONS.values()
    }
    survivors: list[str] = []
    try:
        for name, (target, needle, replacement) in MUTATIONS.items():
            original = originals[target]
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            target.write_text(
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
            target.write_text(original, encoding="utf-8")
    finally:
        for target, original in originals.items():
            target.write_text(original, encoding="utf-8")
    if survivors:
        print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} chain-artifact verifier mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

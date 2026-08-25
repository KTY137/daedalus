#!/usr/bin/env python3
"""Run bounded mutations against GateReport-v4 chain-result binding."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/report_v4.py"
TESTS = (
    "tests/gates/test_gate_report_v4_chain_binding.py",
    "tests/gates/test_gate_report_v4_chain_identity.py",
)
MUTATIONS = {
    "accept-foreign-classification": (
        "    if chain_result.classification_digest != projection.digest:\n",
        "    if False and chain_result.classification_digest != projection.digest:\n",
    ),
    "accept-candidate-blocker-substitution": (
        "        if record.candidate_blockers != tuple(sorted(set(row.candidate_blockers))):\n",
        "        if False and record.candidate_blockers != tuple(sorted(set(row.candidate_blockers))):\n",
    ),
    "accept-stage-applicability-substitution": (
        "        if record.applicable != expected_applicable:\n",
        "        if False and record.applicable != expected_applicable:\n",
    ),
    "allow-missing-chain-digest": (
        "        if self.repository_write_chain_result_sha256 is None:\n",
        "        if False and self.repository_write_chain_result_sha256 is None:\n",
    ),
    "strip-authentication-failures-without-binding": (
        "    if not binding.bound:\n",
        "    if False and not binding.bound:\n",
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
            TARGET.write_text(original.replace(needle, replacement), encoding="utf-8")
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
    print(f"killed {len(MUTATIONS)} GateReport-v4 chain-binding mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

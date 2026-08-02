#!/usr/bin/env python3
"""Run canonical local/CI verification profiles for the G0→G1 stack."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

G0_TESTS = (
    "tests/kernel/test_artifact_identity.py",
    "tests/kernel/test_owner_approval.py",
    "tests/kernel/test_sealed_promotion.py",
    "tests/kernel/test_runtime_conformance_harness.py",
    "tests/kernel/test_docker_sandbox_policy.py",
    "tests/kernel/test_fourfold_evidence.py",
    "tests/kernel/test_fourfold_approval_integration.py",
    "tests/gates/test_gate_report.py",
    "tests/test_effect_boundary.py",
)

G1_TESTS = (
    "tests/ignition/test_voltage_ignition.py",
    "tests/kernel/test_fourfold_evidence.py",
    "tests/kernel/test_fourfold_approval_integration.py",
    "tests/kernel/test_owner_approval.py",
    "tests/twin/test_wiki_reference.py",
    "tests/twin/test_reference_hardening.py",
)

PROFILES = {
    "g0": G0_TESTS,
    "g1": G1_TESTS,
    "consolidated": tuple(dict.fromkeys((*G0_TESTS, *G1_TESTS))),
}


def _run(argv: list[str]) -> None:
    completed = subprocess.run(argv, cwd=ROOT, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=tuple(PROFILES))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--skip-plan", action="store_true")
    args = parser.parse_args(argv)
    tests = PROFILES[args.profile]
    if args.list:
        print("\n".join(tests))
        return 0
    if not args.skip_plan:
        _run([sys.executable, "tools/iron_plan_guard.py", "verify"])
    _run([sys.executable, "-m", "pytest", "-q", *tests])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

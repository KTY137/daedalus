#!/usr/bin/env python3
"""Run canonical local/CI verification profiles for the G0→G1 stack."""
from __future__ import annotations

import argparse
import importlib.util
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
    "tests/test_architecture_boundaries.py",
    # The hierarchy programme is scored by these two and they were absent:
    # `run_gate_checks g1` never ran the import census or the Work Packet
    # registry, which is part of why four failures sat unnoticed on
    # integration/g1-hierarchy for ten commits.
    "tests/contracts/",
    # Over-declaration. These are the ONLY instrument in this repository that
    # checks whether a registry row declares an effect it cannot justify --
    # `check_conformance` has 24 finding codes and not one of them does. They
    # were in no profile, so the gate reported green while the derivation went
    # blind on every door that reaches the network or reads a credential.
    # They are RED as of 2026-09-01 and they are meant to be: 14 of 42 declared
    # effects lost their derivable justification to the refactor. Restoring the
    # walk clears them. Widening BRIDGES, deleting effects from the rows, or
    # relaxing an assertion clears the symptom and re-blinds the instrument.
    "tests/test_registry_new_doors.py",
    "tests/test_registry_retired_rows.py",
    # The derivation those two rely on now follows facades, alias shims,
    # inherited doors and annotated ports. This file plants a real sink behind
    # each of those constructs and checks every fixture against a blinded
    # control, so a construct the walk quietly stops following fails HERE
    # rather than being absorbed as "no witness found". Listed in the profile
    # for the same reason the two above are: an over-declaration instrument
    # that no profile runs is an instrument that goes blind unobserved.
    "tests/test_registry_facade_order.py",
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


#: ``pytest`` exits 5 when it collected nothing. A profile that selects no
#: test is a broken profile, not a passing gate.
_PYTEST_NO_TESTS_COLLECTED = 5


def _require_pytest() -> None:
    """Refuse to report a gate result from an interpreter without pytest.

    Defence in depth, not a leak being plugged. ``sys.executable`` is whatever
    launched this script, and on this machine the bare ``python`` on PATH is a
    different environment without pytest. That case already fails: ``python -m
    pytest <paths>`` prints "No module named pytest" and exits **1**
    [MEASURED 2026-09-01], which ``_run`` propagates.

    What it does not do is say *why*. Exit 1 is indistinguishable from a real
    test failure, so the operator reads "the gate failed" and starts debugging
    the tests instead of the interpreter. This names the actual cause before
    the subprocess runs.
    """

    if importlib.util.find_spec("pytest") is None:
        raise SystemExit(
            f"COULD NOT MEASURE: {sys.executable} has no pytest, so no gate "
            "result can be produced. Run this with the interpreter that owns "
            "the test dependencies (the repository virtualenv)."
        )


def _run(argv: list[str]) -> None:
    completed = subprocess.run(argv, cwd=ROOT, check=False)
    if completed.returncode == _PYTEST_NO_TESTS_COLLECTED:
        raise SystemExit(
            "COULD NOT MEASURE: the profile collected no tests. A renamed or "
            "deleted path silently empties a profile; that is a broken "
            "profile, not a passing gate."
        )
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
    _require_pytest()
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.run_gate_checks",
        REGISTRY_BY_ID["tools.run_gate_checks"].effects,
        (process_guard_boundary_decision(),),
    )
    _run([sys.executable, "-m", "pytest", "-q", *tests])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

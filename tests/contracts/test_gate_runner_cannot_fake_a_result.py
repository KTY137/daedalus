"""The canonical gate runner must name the reason it produced no result.

"No failures" and "I could not look" are different answers, and only the
first is a gate result. Measured 2026-09-01 through ``subprocess.run`` -- the
same call ``_run`` makes -- an interpreter without pytest exits **1** and a
profile that collects nothing exits **5**, so both were already caught by
``if completed.returncode:``. What they were not was *distinguishable*: exit 1
reads as a failing test, and the operator debugs the suite instead of the
interpreter.

An earlier version of this file claimed the missing-pytest case exited 0. That
came from ``cmd | tail; echo $?``, which reports ``tail``'s status, not the
command's. The claim was wrong; the guards are kept as defence in depth and
for the diagnostic they add.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "tools" / "run_gate_checks.py"


def _runner():
    spec = importlib.util.spec_from_file_location("_gate_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_refuses_when_its_interpreter_has_no_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    monkeypatch.setattr(
        runner.importlib.util, "find_spec", lambda name: None
    )

    with pytest.raises(SystemExit) as excinfo:
        runner._require_pytest()

    assert "COULD NOT MEASURE" in str(excinfo.value)


def test_runner_passes_through_when_pytest_is_importable() -> None:
    # This suite is running under pytest, so the guard must stand aside.
    _runner()._require_pytest()


def test_runner_refuses_a_profile_that_collected_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pytest exit code 5 means "collected nothing", not "nothing failed".

    A renamed or deleted path silently empties a profile. Without this the
    runner would report the emptied profile as a passing gate.
    """

    runner = _runner()

    class _Completed:
        returncode = runner._PYTEST_NO_TESTS_COLLECTED

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: _Completed())

    with pytest.raises(SystemExit) as excinfo:
        runner._run(["irrelevant"])

    assert "COULD NOT MEASURE" in str(excinfo.value)


def test_runner_still_propagates_a_real_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()

    class _Completed:
        returncode = 1

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: _Completed())

    with pytest.raises(SystemExit) as excinfo:
        runner._run(["irrelevant"])

    assert excinfo.value.code == 1


def test_g1_profile_scores_the_instruments_the_hierarchy_work_is_judged_by() -> None:
    """The import census and the Work Packet registry belong to the g1 gate.

    They were absent from every profile, so `run_gate_checks g1` never ran
    them. Four failures -- one of them a real architectural regression --
    sat unnoticed on integration/g1-hierarchy for ten commits.
    """

    profile = _runner().PROFILES["g1"]

    assert "tests/contracts/" in profile
    assert "tests/test_architecture_boundaries.py" in profile

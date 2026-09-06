"""The preflight stops failing hosts over an opt-in capability.

WHY (G1-MAP-06, 2026-09-03). `tools/gate_host_preflight.py` answers whether a
machine may produce a gate discrimination receipt. On a clean checkout of this
repository it answers **NOT FIT**, for exactly one of twelve checks:

    [FAIL] module coverage: NOT IMPORTABLE
    NOT FIT: 1 required check(s) failed.

Two things are wrong with that, and they compound.

FIRST, coverage is not installable from this project at all. It appears in no
extra in `pyproject.toml` and `uv.lock` contains zero occurrences of it, so an
environment built the documented way cannot satisfy the check the repository
itself imposes.

SECOND, and this is the load-bearing one: the run being gated does not use
coverage. Coverage-guided discrimination is OPT-IN --
`gate_discrimination.run(..., coverage_guided: bool = False)`, exposed as a
`--coverage-guided` store_true flag, and without it `coverage_state` is
`"not_requested"` and the module is never invoked. The committed receipt
`runs/spine/gate_discrimination.json` was produced exactly that way:
`coverage_guided: false`. So the preflight failed hosts for a capability the
default run does not exercise.

WHY IT MATTERED RATHER THAN BEING TIDY. `docs/STATUS.md` records that promotion
is blocked "on runs/spine/gate_discrimination.json being stale at HEAD -- a
measurement, not a pen stroke". It is stale. Refreshing it is what clears that
block, and the instrument deciding whether this machine may refresh it said no,
over a module the refresh would not have loaded.

THE PREFLIGHT'S OWN JUSTIFICATION does not survive the check either. It fails a
host because "a gate run on this host would not measure what the receipt would
claim it measured". For coverage that is false: the receipt carries
`coverage_guided` and `coverage_state`, so a run without it says so rather than
claiming the stronger measurement.

WHAT IS DELIBERATELY NOT CLAIMED: that coverage is unimportant.
Coverage-guided discrimination is stronger evidence, which is why it stays
listed and reported. It is optional, not irrelevant, and declaring it in the
test extra remains the separate half of this fix.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import gate_host_preflight as pre  # noqa: E402


def test_pytest_is_still_required() -> None:
    """The gate IS a pytest run. That one is not negotiable."""
    assert "pytest" in pre.REQUIRED_MODULES


def test_coverage_is_not_required() -> None:
    assert "coverage" not in pre.REQUIRED_MODULES


def test_coverage_is_still_reported() -> None:
    """Optional, not dropped: a receipt's strength should stay visible."""
    assert "coverage" in pre.OPTIONAL_MODULES


def test_the_required_set_did_not_quietly_empty() -> None:
    """A guard against 'fixing' this by requiring nothing at all."""
    assert len(pre.REQUIRED_MODULES) >= 1


def test_coverage_never_appears_as_a_required_failure() -> None:
    """The end-to-end claim, run against this repository.

    coverage is not importable here -- that is the whole finding -- so if the
    verdict still depends on it, this fails.
    """
    report = pre.run_checks(ROOT)
    required_failures = [
        c.name for c in report.checks if c.required and not c.ok
    ]
    assert not any("coverage" in n for n in required_failures), required_failures


def test_coverage_is_still_visible_in_the_report() -> None:
    """Optional means reported-and-not-fatal, not omitted.

    A receipt produced without coverage is weaker, and the preflight should
    still say so; it just must not refuse the host over it.
    """
    report = pre.run_checks(ROOT)
    assert any("coverage" in c.name for c in report.checks)

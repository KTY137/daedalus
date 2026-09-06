"""The one door the Gate-1 fault matrix exercises.

WHY THIS FILE EXISTS
--------------------
Until G1-RENOVATION-02A every node in this directory drove
``daedalus.ignition.runner.run_voltage_ignition`` -- the 2026-08 in-process
rehearsal, with synthetic ``"1"*40`` revisions -- while ``python -m
daedalus.ignition`` ran ``daedalus.ignition.gate1.run_gate1_ignition``. Two
implementations for one Gate-1 clause is the "second implementation truth" plan
§13 forbids, and it meant the fail-closed matrix the activation checklist cites
as settled did not cover the shipped path at all
[MEASURED 2026-09-06, G1-RENOVATION-01 §3 finding 1].

Every fault row is now expressed against ``run_gate1_ignition`` or against a
named seam of :mod:`daedalus.ignition.gate1`. The row texts are unchanged; what
they are asserted about is not.

WHY THE EXPENSIVE FIXTURES ARE SESSION-SCOPED
---------------------------------------------
The shipped door runs pytest as a subprocess a dozen times per invocation (two
attempt gates, the base and composed suites, the anchored-node roles, one
negative control per check, one coverage revert per data/knowledge subject).
Two of the ten rows need a completed run and a completed replay; they share ONE
pair here rather than paying for four.

The helpers are FIXTURES rather than module functions on purpose: this
directory has no ``__init__.py``, so a test module here is imported top-level
and cannot import its own conftest by name without colliding with
``tests/conftest.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest

from daedalus.ignition import gate1
from daedalus.spine import picker as spine_picker
from daedalus.spine.killswitch import KillSwitch
from daedalus.spine.ledger import SpineLedger


@pytest.fixture(scope="session")
def ignition_authority(tmp_path_factory):
    """The operator prerequisites ``acquire_attempt_lease`` reads, isolated.

    The lease's AUTHORITY is the installation checkout (``gate1.py:906``), so a
    test run that did not pin these would arm its verdict on -- and append to --
    the operator's real kill switch, spine ledger, budget ledger and worktree
    root. ``tests/test_ignition_gate1.py`` pins the first two at module scope;
    this pins those plus the three environment declarations, because the
    session-scoped fixtures below are set up BEFORE the function-scoped autouse
    pin in ``tests/conftest.py`` gets its turn.

    MEASURED 2026-09-06 while writing this: without the armed switch every
    attempt is refused a lease ("the kill switch for the installation control
    root is engaged"), the operator never runs, and the row under test measures
    the switch instead of the fault it injected.
    """

    state = tmp_path_factory.mktemp("ignition-authority")
    switch = KillSwitch(state / "permit")
    switch.arm()
    ledger_path = state / "spine.sqlite3"
    SpineLedger(ledger_path).close()
    patcher = pytest.MonkeyPatch()
    patcher.setattr(
        spine_picker,
        "resolve_spine_db_path",
        lambda *_args, **_kwargs: (ledger_path, None),
    )
    patcher.setenv("DAEDALUS_SPINE_DB", str(state / "chat-spine.sqlite3"))
    patcher.setenv("DAEDALUS_BUDGET_LEDGER", str(state / "budget-ledger.json"))
    patcher.setenv("DAEDALUS_WORKTREE_ROOT", str(state / "worktrees"))
    try:
        yield switch
    finally:
        patcher.undo()
        switch.stop("ignition fault matrix complete")


@pytest.fixture(scope="session")
def door(ignition_authority):
    """One invocation of the shipped Gate-1 door.

    ``python -m daedalus.ignition`` calls exactly this function
    (``daedalus/ignition/__main__.py:66``); the only additions here are the
    isolated kill switch and a frozen clock, so a replay comparison is not
    decided by when the test happened to run.
    """

    def _run(**kwargs):
        kwargs.setdefault("fixture_root", gate1.DEFAULT_FIXTURE)
        kwargs.setdefault("collected_at", "2026-09-06T00:00:00Z")
        kwargs.setdefault("gate_timeout_s", 300)
        return gate1.run_gate1_ignition(switch=ignition_authority, **kwargs)

    return _run


@pytest.fixture(scope="session")
def door_exit_code():
    """The exit code the door reports for a result.

    Spelled the way ``daedalus/ignition/__main__.py:78`` spells it. A row that
    asserts "this refuses" has to assert it about the thing an operator and a
    CI job actually read.
    """

    return lambda result: 1 if (result.blockers or result.packet is None) else 0


class DoorRun(NamedTuple):
    """One completed run of the door, plus the scratch tree it kept.

    ``workspace`` is retained (``run_gate1_ignition`` deletes its scratch only
    when it made one itself, ``gate1.py:1349``) so a row can read the composed
    candidate tree the attempts actually produced instead of trusting the
    receipt's description of it.
    """

    result: object
    workspace: Path

    @property
    def candidate_root(self) -> Path:
        return self.workspace / "candidate"

    @property
    def base_repo(self) -> Path:
        return self.workspace / "target"


@pytest.fixture(scope="session")
def gate1_replay(door, tmp_path_factory):
    """The shipped door, run twice into ONE receipt directory.

    The second run is the replay: same fixture, same frozen clock, same
    evaluator bundle, its predecessor complete. Rows that need "and the
    supported restart reproduces the original digests exactly" read this pair
    instead of paying for a run of their own.
    """

    root = tmp_path_factory.mktemp("gate1-door")
    first = door(receipt_root=root / "receipts", workspace=root / "ws-1")
    second = door(receipt_root=root / "receipts", workspace=root / "ws-2")
    return DoorRun(first, root / "ws-1"), DoorRun(second, root / "ws-2")

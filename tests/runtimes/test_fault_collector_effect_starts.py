# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Boundary tests for the three fault-matrix collector doors wired 2026-08-18.

Each of these ``main()`` entrypoints was inventory_only with a note saying its
central wiring would "land with the live-runtime lane's runtime-bound chain".
That reasoning did not survive review: none of the three carries a
``runtime_id`` and none needs a lease, so nothing about them was ever waiting
on that chain.  They are now canonical effect starts.

Every door gets the same pair -- a refusal when the guard chain says no, and a
completed run when it says yes -- plus one mutation probe for the family that
has a second, non-trivial contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    EffectStartRefused,
    GuardDecision,
    Wiring,
)


def _denied(contract: str = "budget.process_guard"):
    def _factory():
        return GuardDecision(contract, False, "spend net refused by this test")

    return _factory


# --------------------------------------------------------------------------
# runtimes.fixture_fault_collector
# --------------------------------------------------------------------------


def test_fixture_collector_row_is_central_and_declares_its_spawn() -> None:
    row = REGISTRY_BY_ID["runtimes.fixture_fault_collector"]
    assert row.wiring is Wiring.CENTRAL
    assert "budget.process_guard" in row.guard_contracts
    assert any(anchor.call == "begin_effect" for anchor in row.anchors)
    # the runner seam anchor must survive the wiring, not be replaced by it
    assert any(anchor.call == "subprocess_pytest_runner" for anchor in row.anchors)


def test_fixture_collector_refuses_before_spawning_when_the_guard_denies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusal without the chain: no pytest process, no evidence directory."""
    import daedalus.budget as budget
    from daedalus.runtimes import fixture_fault_collector as module

    monkeypatch.setattr(budget, "process_guard_boundary_decision", _denied())

    def _must_not_run(*args, **kwargs):  # pragma: no cover - must never execute
        raise AssertionError("the collector spawned work after a denied start")

    monkeypatch.setattr(module, "run_fixture_fault_catalog", _must_not_run)

    run_dir = tmp_path / "run"
    with pytest.raises(EffectStartRefused, match="budget.process_guard"):
        module.main(
            [
                "--run-dir",
                str(run_dir),
                "--source-revision",
                "a" * 40,
                "--repo-root",
                str(tmp_path),
            ]
        )
    assert not run_dir.exists(), "a refused start must leave no evidence behind"


def test_fixture_collector_runs_when_the_guard_chain_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run with the chain: the boundary is not in the way of the happy path."""
    import daedalus.budget as budget
    from daedalus.runtimes import fixture_fault_collector as module

    started: list[str] = []

    def _allowed():
        started.append("budget.process_guard")
        return GuardDecision("budget.process_guard", True, "spend net installed")

    monkeypatch.setattr(budget, "process_guard_boundary_decision", _allowed)
    monkeypatch.setattr(module, "run_fixture_fault_catalog", lambda **kwargs: ())

    exit_code = module.main(
        [
            "--run-dir",
            str(tmp_path / "run"),
            "--source-revision",
            "a" * 40,
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    assert started == ["budget.process_guard"], (
        "the real contract must run exactly once per collector run"
    )


# --------------------------------------------------------------------------
# runtimes.live_fault_collector
# --------------------------------------------------------------------------


def test_live_collector_row_is_central_and_anchored() -> None:
    row = REGISTRY_BY_ID["runtimes.live_fault_collector"]
    assert row.wiring is Wiring.CENTRAL
    assert "budget.process_guard" in row.guard_contracts
    assert any(anchor.call == "begin_effect" for anchor in row.anchors)


def test_live_collector_refuses_before_probing_when_the_guard_denies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import daedalus.budget as budget
    from daedalus.runtimes import live_fault_collector as module

    monkeypatch.setattr(budget, "process_guard_boundary_decision", _denied())

    def _must_not_run(*args, **kwargs):  # pragma: no cover - must never execute
        raise AssertionError("the collector probed after a denied start")

    monkeypatch.setattr(module, "run_live_fault_catalog", _must_not_run)

    run_dir = tmp_path / "run"
    with pytest.raises(EffectStartRefused, match="budget.process_guard"):
        module.main(
            ["--run-dir", str(run_dir), "--source-revision", "b" * 40]
        )
    assert not run_dir.exists()


def test_live_collector_starts_once_even_though_main_can_self_delegate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The start sits after the canonical-module delegation, so it fires once.

    ``live_fault_collector.main`` re-dispatches to the canonical module when it
    was loaded as ``__main__``.  A boundary call placed before that hand-off
    would start the same effect twice and mint two receipts for one run.
    """
    import daedalus.budget as budget
    from daedalus.runtimes import live_fault_collector as module

    starts: list[str] = []

    def _allowed():
        starts.append("budget.process_guard")
        return GuardDecision("budget.process_guard", True, "spend net installed")

    from daedalus.runtimes import live_probe_drivers

    monkeypatch.setattr(budget, "process_guard_boundary_decision", _allowed)
    # main() imports this one at call time, so it is patched at its source
    monkeypatch.setattr(
        live_probe_drivers, "build_live_probe_executors", lambda **kwargs: ()
    )
    monkeypatch.setattr(module, "run_live_fault_catalog", lambda **kwargs: ())

    exit_code = module.main(
        ["--run-dir", str(tmp_path / "run"), "--source-revision", "b" * 40]
    )
    assert exit_code == 0
    assert starts == ["budget.process_guard"], "exactly one start per run"


# --------------------------------------------------------------------------
# runtimes.container_fault_driver
# --------------------------------------------------------------------------


def test_wiring_these_doors_did_not_change_what_their_spawns_cost() -> None:
    """The spend net is a net, not a toll booth on the collectors' own work.

    Both wired collectors spawn: pytest processes and docker containers.  If
    installing the guard priced those, the boundary call would have quietly
    changed the behaviour of the runs it was supposed to only observe -- and a
    budget-exhausted host would start failing fault collection.

    It does not: the interposer prices by vendor, and neither argv classifies
    as one.  A real vendor spawn from the same process still does, which is the
    cover these rows genuinely gained.
    """
    from daedalus.budget import classify_argv

    assert classify_argv(["python", "-m", "pytest", "-q"]) is None
    assert classify_argv(["docker", "run", "--rm", "image"]) is None
    assert classify_argv(["claude", "-p", "prompt"]) is not None


def test_container_driver_row_is_central_with_both_real_contracts() -> None:
    row = REGISTRY_BY_ID["runtimes.container_fault_driver"]
    assert row.wiring is Wiring.CENTRAL
    assert {"containment.attempt", "budget.process_guard"} <= set(row.guard_contracts)
    assert any(anchor.call == "begin_effect" for anchor in row.anchors)
    assert any(anchor.call == "run_in_docker_sandbox" for anchor in row.anchors)


def test_container_driver_containment_decision_reads_the_real_binding() -> None:
    """The containment decision resolves a fact, it does not assert one."""
    from daedalus.runtimes import container_fault_driver as module

    decision = module.containment_boundary_decision()
    assert decision.contract == "containment.attempt"
    assert decision.allowed is True
    assert "daedalus.kernel.sandbox" in decision.evidence
    assert decision.evidence.strip(), "an empty evidence string is refused upstream"


def test_container_driver_refuses_before_spawning_when_the_guard_denies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import daedalus.budget as budget
    from daedalus.runtimes import container_fault_driver as module

    monkeypatch.setattr(budget, "process_guard_boundary_decision", _denied())

    def _must_not_run(*args, **kwargs):  # pragma: no cover - must never execute
        raise AssertionError("the driver published after a denied start")

    monkeypatch.setattr(module, "publish_container_faults", _must_not_run)

    out_dir = tmp_path / "out"
    with pytest.raises(EffectStartRefused, match="budget.process_guard"):
        module.main(
            [
                "--source-revision",
                "c" * 40,
                "--output-dir",
                str(out_dir),
                "--repo-root",
                str(tmp_path),
            ]
        )
    assert not out_dir.exists()


def test_container_driver_runs_when_the_guard_chain_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import daedalus.budget as budget
    from daedalus.runtimes import container_fault_driver as module

    monkeypatch.setattr(
        budget,
        "process_guard_boundary_decision",
        lambda: GuardDecision("budget.process_guard", True, "spend net installed"),
    )
    monkeypatch.setattr(
        module,
        "publish_container_faults",
        lambda **kwargs: {"failed": 0, "blocked": 0},
    )

    exit_code = module.main(
        [
            "--source-revision",
            "c" * 40,
            "--output-dir",
            str(tmp_path / "out"),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert exit_code == 0


def test_container_driver_refuses_when_the_containment_call_is_swapped_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation probe for the collector family's second contract.

    The containment decision only earns its place if replacing the bounded
    sandbox with something else actually stops the run.  Swap the symbol this
    module will call for a look-alike defined elsewhere: the decision must go
    negative and the start must be refused *before* any container is published.
    """
    import daedalus.budget as budget
    from daedalus.runtimes import container_fault_driver as module

    def _look_alike_sandbox(*args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("an unbounded spawn path was used")

    monkeypatch.setattr(module, "run_in_docker_sandbox", _look_alike_sandbox)
    monkeypatch.setattr(
        budget,
        "process_guard_boundary_decision",
        lambda: GuardDecision("budget.process_guard", True, "spend net installed"),
    )

    def _must_not_run(*args, **kwargs):  # pragma: no cover - must never execute
        raise AssertionError("the driver published with an unbounded spawn path")

    monkeypatch.setattr(module, "publish_container_faults", _must_not_run)

    # the decision itself flips first...
    decision = module.containment_boundary_decision()
    assert decision.allowed is False
    assert "not daedalus.kernel.sandbox" in decision.evidence

    # ...and the boundary turns that into a refusal
    out_dir = tmp_path / "out"
    with pytest.raises(EffectStartRefused, match="containment.attempt"):
        module.main(
            [
                "--source-revision",
                "c" * 40,
                "--output-dir",
                str(out_dir),
                "--repo-root",
                str(tmp_path),
            ]
        )
    assert not out_dir.exists()

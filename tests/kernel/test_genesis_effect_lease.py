"""The canonical non-runtime Effect Lease for ``python.genesis``."""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.kernel.offload_lease import (
    WaveOffloadLease,
    acquire_effect_lease,
)
from daedalus.orchestration.workspace_containment import resolve_worktree_root
from daedalus.sensitivity import Policy
from daedalus.spine.killswitch import KillSwitch


ENTRYPOINT_ID = "python.genesis"
REVISION = "d" * 40


@pytest.fixture
def genesis_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "authority-repo"
    repo.mkdir()
    monkeypatch.setenv(
        "DAEDALUS_KILLSWITCH",
        str(tmp_path / "control" / "killswitch"),
    )
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))

    switch = KillSwitch(repo_root=repo)
    switch.arm(force=True, note="genesis registry lease test")
    yield repo, switch


def test_genesis_lease_grants_only_write_and_process_bounds(genesis_authority) -> None:
    repo, switch = genesis_authority
    attempt_ledger = repo / "runs" / "spine" / "spine.sqlite3"
    assert not attempt_ledger.exists()

    granted = acquire_effect_lease(
        repo,
        entrypoint_id=ENTRYPOINT_ID,
        source_revision=REVISION,
        mission_id="genesis-test",
        attempt_id="genesis-attempt-test",
        positions=1,
        writable_paths=("candidate/",),
        tools=("python",),
        max_spend_usd=99.0,
        timeout_s=30,
        contained=True,
        containment_evidence="checkout-external Genesis Attempt workspace",
        write_policy=Policy(write_allow=("candidate/",)),
        switch=switch,
        worktree_root_resolver=resolve_worktree_root,
    )

    assert isinstance(granted, WaveOffloadLease), getattr(granted, "reasons", None)
    assert granted.lease.entrypoint_id == ENTRYPOINT_ID
    assert granted.lease.requested_effects == (
        "filesystem_write",
        "process_control",
        "process_spawn",
    )
    assert tuple(
        sorted(decision.contract for decision in granted.authorization.guard_decisions)
    ) == (
        "budget.process_guard",
        "containment.attempt",
        "containment.worktree",
        "provider.write_policy",
    )
    assert not attempt_ledger.exists()

    scope = granted.lease.effect_scope
    assert scope.read_only is False
    assert scope.writable_paths == ("candidate",)
    assert "python" in scope.tools
    assert scope.egress_endpoints == ()
    assert scope.secret_refs == ()
    assert scope.max_cost_microusd == 0

    execution = granted.execution_for(0, ("candidate/",))
    start = granted.authorization.begin_effect(execution)
    assert start.execute is True
    terminal = granted.authorization.finish_effect(
        start.receipt,
        outcome="COMPLETED",
    )
    assert terminal.receipt_sha256

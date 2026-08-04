from __future__ import annotations

from pathlib import Path

import daedalus.kairos.gated_writes as gated_writes
from daedalus.kairos.promotion_manager_boundary import _BoundaryState
from daedalus.kairos.promotion_manager_replay import (
    _ReplayAuditedExecutionLedger,
)
from daedalus.kernel.promotion_execution import PromotionExecutionLedger


class DummyLedger(PromotionExecutionLedger):
    def __init__(self) -> None:
        # No Event Store is opened. Tests use this object only to inspect the
        # already-installed per-call wrapper selection.
        pass


def test_live_module_preserves_existing_strangler_and_canonical_ledger_type() -> None:
    assert gated_writes._RETAINED_SOURCE_NAME == "_gated_writes_legacy.py.src"
    assert gated_writes.PromotionExecutionLedger is PromotionExecutionLedger
    assert gated_writes._REAL_PROMOTION_EXECUTION_LEDGER is PromotionExecutionLedger
    assert "promote_candidates" in gated_writes.__all__
    assert "install_promotion_manager_boundary" not in gated_writes.__all__
    assert "install_promotion_manager_replay_boundary" not in gated_writes.__all__
    assert not hasattr(gated_writes, "_install_promotion_manager_boundary")
    assert not hasattr(gated_writes, "_install_promotion_manager_replay_boundary")


def test_live_module_selects_typed_replay_proxy() -> None:
    state = gated_writes._promotion_manager_boundary_state
    assert isinstance(state, _BoundaryState)
    assert state.ledger_type is PromotionExecutionLedger
    assert state.ledger_wrapper is _ReplayAuditedExecutionLedger
    assert gated_writes._promotion_manager_replay_wrapper is (
        _ReplayAuditedExecutionLedger
    )
    wrapped = state.wrap_ledger(DummyLedger())
    assert isinstance(wrapped, PromotionExecutionLedger)
    assert type(wrapped) is _ReplayAuditedExecutionLedger


def test_live_public_callable_is_the_scoped_manager_wrapper() -> None:
    state = gated_writes._promotion_manager_boundary_state
    public = gated_writes.promote_candidates
    assert getattr(public, "__self__", None) is state
    assert getattr(public, "__func__", None) is getattr(
        state.promote_candidates,
        "__func__",
        None,
    )
    assert callable(gated_writes._ACCOUNTED_PROMOTE_CANDIDATES)
    assert gated_writes._ACCOUNTED_PROMOTE_CANDIDATES is not public


def test_live_untyped_ledger_is_not_laundered_or_executed(tmp_path: Path) -> None:
    forged = object()
    result = gated_writes.promote_candidates(
        str(tmp_path),
        [],
        project=None,
        availability={},
        consumed_approval=None,
        evidence_packet=None,
        target_ref="experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        promotion_execution_ledger=forged,
    )
    assert result["promoted"] == []
    assert result["not_gated"] == []
    assert len(result["refused"]) == 1
    assert "mandatory before any promotion effect" in result["refused"][0]["reason"]
    assert gated_writes._promotion_manager_boundary_state.active_manager.get() is None


def test_installation_does_not_authorize_or_close_gate() -> None:
    source = Path(gated_writes.__file__).read_text(encoding="utf-8").lower()
    assert "issue_owner_approval" not in source
    assert "closed=true" not in source
    assert "automatic promotion" not in source

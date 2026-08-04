from __future__ import annotations

import inspect
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
    for private_name in (
        "_install_promotion_manager_boundary",
        "_install_promotion_manager_replay_boundary",
        "_make_public_promotion_wrapper",
        "_wraps",
    ):
        assert not hasattr(gated_writes, private_name)


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


def test_live_public_callable_remains_function_compatible() -> None:
    state = gated_writes._promotion_manager_boundary_state
    public = gated_writes.promote_candidates
    parent = gated_writes._ACCOUNTED_PROMOTE_CANDIDATES
    assert inspect.isfunction(public)
    assert inspect.unwrap(public) is parent
    assert public.__wrapped__ is parent
    assert public.__name__ == parent.__name__ == "promote_candidates"
    assert public.__qualname__ == parent.__qualname__
    assert public.__module__ == parent.__module__ == gated_writes.__name__
    assert inspect.signature(public) == inspect.signature(parent)
    assert callable(state.promote_candidates)
    assert parent is state.parent_promote_candidates
    assert public is not parent


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

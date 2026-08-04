from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.kairos.promotion_manager_boundary import (
    _AuditedExecutionLedger,
    install_promotion_manager_boundary,
)
from daedalus.kairos.promotion_manager_replay import (
    _ReplayAuditedExecutionLedger,
    install_promotion_manager_replay_boundary,
)
from daedalus.kernel.promotion_execution import PromotionExecutionLedger


class DummyManager:
    def __init__(self, root: Path) -> None:
        self.repo_path = root
        self.worktree_root = root / ".worktrees"


class DummyLedger(PromotionExecutionLedger):
    def __init__(self) -> None:
        # This object is used only to prove the public type boundary.  No Event
        # Store operation is invoked in these installation tests.
        pass


class Recorder:
    def __init__(self) -> None:
        self.seen: list[object] = []

    def __call__(self, *_args, **kwargs):
        ledger = kwargs.get("promotion_execution_ledger")
        self.seen.append(ledger)
        return {
            "typed": isinstance(ledger, PromotionExecutionLedger),
            "ledger_type": type(ledger),
        }


def namespace(recorder: Recorder) -> dict[str, object]:
    return {
        "GitWorktreeManager": DummyManager,
        "PromotionExecutionLedger": PromotionExecutionLedger,
        "promote_candidates": recorder,
    }


def test_manager_installation_preserves_public_ledger_type() -> None:
    recorder = Recorder()
    target = namespace(recorder)
    install_promotion_manager_boundary(target)

    assert target["PromotionExecutionLedger"] is PromotionExecutionLedger
    result = target["promote_candidates"](
        "repo",
        [],
        promotion_execution_ledger=DummyLedger(),
    )
    assert result["typed"] is True
    assert result["ledger_type"] is _AuditedExecutionLedger
    assert isinstance(recorder.seen[-1], PromotionExecutionLedger)


def test_replay_installation_selects_typed_replay_proxy_without_factory_swap() -> None:
    recorder = Recorder()
    target = namespace(recorder)
    install_promotion_manager_boundary(target)
    install_promotion_manager_replay_boundary(target)

    assert target["PromotionExecutionLedger"] is PromotionExecutionLedger
    result = target["promote_candidates"](
        "repo",
        [],
        promotion_execution_ledger=DummyLedger(),
    )
    assert result["typed"] is True
    assert result["ledger_type"] is _ReplayAuditedExecutionLedger
    assert isinstance(recorder.seen[-1], PromotionExecutionLedger)


def test_invalid_ledger_is_not_laundered_through_proxy_type() -> None:
    recorder = Recorder()
    target = namespace(recorder)
    install_promotion_manager_boundary(target)
    install_promotion_manager_replay_boundary(target)
    forged = object()

    result = target["promote_candidates"](
        "repo",
        [],
        promotion_execution_ledger=forged,
    )
    assert result["typed"] is False
    assert recorder.seen[-1] is forged


def test_installers_refuse_duplicate_or_out_of_order_installation() -> None:
    recorder = Recorder()
    target = namespace(recorder)
    with pytest.raises(RuntimeError, match="target is invalid"):
        install_promotion_manager_replay_boundary(target)

    install_promotion_manager_boundary(target)
    with pytest.raises(RuntimeError, match="already installed"):
        install_promotion_manager_boundary(target)

    install_promotion_manager_replay_boundary(target)
    with pytest.raises(RuntimeError, match="already installed"):
        install_promotion_manager_replay_boundary(target)

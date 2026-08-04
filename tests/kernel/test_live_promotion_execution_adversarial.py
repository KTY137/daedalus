from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.kairos.gated_writes as gated_writes
import daedalus.kernel.promotion as promotion
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_fingerprint import fingerprint_primary_checkout
from daedalus.spine.attempt import AttemptResult, GateResult, PatchArtifact, STATE_CLEAN
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
INTEGRATION = "b" * 40
NOW = datetime(2026, 8, 4, 1, 0, tzinfo=timezone.utc).isoformat()


def _candidate():
    diff = b"diff --git a/source.py b/source.py\n+changed\n"
    artifact = PatchArtifact(
        task_id="task-1",
        branch="candidate-1",
        base_revision=REVISION,
        diff_bytes=diff,
        diff_sha256=hashlib.sha256(diff).hexdigest(),
        changed_paths=("source.py",),
        created_ts=NOW,
    )
    result = AttemptResult(
        state=STATE_CLEAN,
        task_id="task-1",
        started_ts=NOW,
        finished_ts=NOW,
        duration_s=0.1,
        effect_key="effect-1",
        branch="candidate-1",
        base_revision=REVISION,
        artifact=artifact,
        gates=GateResult(passed=True, name="fixture"),
    )
    return gated_writes.GatedCandidate(assignment=None, spec=None, result=result)


def _authorization() -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-1",
        "candidate_artifact_sha256": "1" * 64,
        "evidence_packet_sha256": "2" * 64,
        "source_revision": REVISION,
        "target_ref": "experimental",
        "live_target_revision": REVISION,
        "approval_consumption_sha256": "3" * 64,
    }
    return PromotionAuthorization(**body, authorization_sha256=canonical_sha(body))


def _consumed():
    return SimpleNamespace(
        verified=SimpleNamespace(expected_target_revision=REVISION)
    )


def _install(monkeypatch, tmp_path: Path, ledger: PromotionExecutionLedger, *, mutate=False):
    auth = _authorization()
    order: list[str] = []

    class Manager:
        def __init__(self, root):
            order.append("manager")
            self.worktree_root = tmp_path / "worktrees"

    class Lock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            assert ledger.pending(), "start must exist before lock-file mutation"
            order.append("lock")
            return self

        def __exit__(self, *_args):
            return False

    def authorize(**_kwargs):
        order.append("authorize")
        return auth

    def resolve(_root, ref):
        order.append(f"resolve:{ref}")
        return INTEGRATION if ref == "integration-1" else REVISION

    def promote_locked(root, _manager, candidates, **_kwargs):
        order.append("mutate")
        if mutate:
            (Path(root) / "source.py").write_text("mutated\n", encoding="utf-8")
        return {
            "promoted": [{"task_id": candidates[0].result.task_id, "promoted": True}],
            "refused": [],
            "integration_branch": "integration-1",
        }

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", Manager)
    monkeypatch.setattr(gated_writes, "_PromotionLock", Lock)
    monkeypatch.setattr(promotion, "authorize_persisted_promotion", authorize)
    monkeypatch.setattr(promotion, "resolve_live_target_revision", resolve)
    monkeypatch.setattr(gated_writes._legacy, "_promote_locked", promote_locked)
    return auth, order


def _call(repo: Path, ledger: PromotionExecutionLedger):
    return gated_writes.promote_candidates(
        str(repo),
        [_candidate()],
        project=None,
        availability={},
        consumed_approval=_consumed(),
        evidence_packet=object(),
        target_ref="experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        promotion_execution_ledger=ledger,
        ledger_path=repo.parent / "events.sqlite3",
    )


def test_missing_execution_ledger_refuses_before_authority_or_manager(
    monkeypatch,
    tmp_path: Path,
) -> None:
    reached = False

    def forbidden(*_args, **_kwargs):
        nonlocal reached
        reached = True
        raise AssertionError("boundary primitive reached")

    monkeypatch.setattr(promotion, "authorize_persisted_promotion", forbidden)
    monkeypatch.setattr(gated_writes, "GitWorktreeManager", forbidden)
    report = gated_writes.promote_candidates(
        str(tmp_path),
        [_candidate()],
        project=None,
        availability={},
        consumed_approval=_consumed(),
        evidence_packet=object(),
        target_ref="experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
    )
    assert not reached
    assert report["promoted"] == []
    assert "PromotionExecutionLedger" in report["refused"][0]["reason"]


def test_terminal_replay_returns_receipt_without_lock_or_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.py").write_text("original\n", encoding="utf-8")
    ledger = PromotionExecutionLedger(tmp_path / "promotion.sqlite3")
    _, order = _install(monkeypatch, tmp_path, ledger)

    first = _call(repo, ledger)
    assert first["promoted"]
    assert not ledger.pending()

    class ForbiddenLock:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("terminal replay must not acquire promotion lock")

    monkeypatch.setattr(gated_writes, "_PromotionLock", ForbiddenLock)
    before = tuple(order)
    replay = _call(repo, ledger)
    assert replay == first
    assert "mutate" not in order[len(before):]


def test_pending_restart_never_reexecutes_automatically(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.py").write_text("original\n", encoding="utf-8")
    ledger = PromotionExecutionLedger(tmp_path / "promotion.sqlite3")
    auth, order = _install(monkeypatch, tmp_path, ledger)
    ledger.begin(
        auth,
        start_id=f"promotion-start-{auth.authorization_sha256[:24]}",
        primary_checkout_before_sha256=fingerprint_primary_checkout(repo),
    )

    report = _call(repo, ledger)
    assert report["promotion_execution_pending_reconciliation"] is True
    assert "lock" not in order
    assert "mutate" not in order
    assert len(ledger.pending()) == 1


def test_primary_checkout_mutation_is_persisted_as_fault_not_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.py").write_text("original\n", encoding="utf-8")
    original_fingerprint = fingerprint_primary_checkout(repo)
    ledger = PromotionExecutionLedger(tmp_path / "promotion.sqlite3")
    auth, _ = _install(monkeypatch, tmp_path, ledger, mutate=True)

    report = _call(repo, ledger)
    assert report["fault"]
    assert not ledger.pending()
    replay = ledger.begin(
        auth,
        start_id=f"promotion-start-{auth.authorization_sha256[:24]}",
        primary_checkout_before_sha256=original_fingerprint,
    )
    assert replay.execute is False
    assert replay.completion is not None
    assert replay.completion.receipt.outcome == "faulted"

from __future__ import annotations

from types import SimpleNamespace

import pytest

import daedalus.kairos.gated_writes as gated_writes
import daedalus.kernel.promotion as promotion
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_receipts import (
    PromotionLedger,
    PromotionReceiptStateError,
)
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
INTEGRATION = "b" * 40
PRIMARY = "1" * 64
PRIMARY_CHANGED = "2" * 64


def _authorization() -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-live-receipt-1",
        "candidate_artifact_sha256": "3" * 64,
        "evidence_packet_sha256": "4" * 64,
        "source_revision": REVISION,
        "target_ref": "refs/heads/experimental",
        "live_target_revision": REVISION,
        "approval_consumption_sha256": "5" * 64,
    }
    return PromotionAuthorization(**body, authorization_sha256=canonical_sha(body))


def _candidate():
    artifact = SimpleNamespace(
        is_empty=False,
        base_revision=REVISION,
        diff_sha256="6" * 64,
        changed_paths=("src/example.py",),
    )
    result = SimpleNamespace(
        ok=True,
        artifact=artifact,
        task_id="task-1",
        state="clean",
    )
    return SimpleNamespace(result=result)


def _install(
    monkeypatch,
    tmp_path,
    *,
    fingerprints,
    report=None,
    raised=None,
    integration_revision=INTEGRATION,
):
    authorization = _authorization()
    calls = {"mutations": 0, "fingerprints": 0}

    class Manager:
        def __init__(self, _root):
            self.worktree_root = tmp_path / "worktrees"

    class Lock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def authorize(**_kwargs):
        return authorization

    def resolve(_root, _target_ref):
        return REVISION

    values = iter(fingerprints)

    def fingerprint(_root):
        calls["fingerprints"] += 1
        value = next(values)
        if isinstance(value, BaseException):
            raise value
        return value

    def promote_locked(_root, _manager, _candidates, **kwargs):
        calls["mutations"] += 1
        if raised is not None:
            raise raised
        if report is not None:
            return report(kwargs["integration_branch"]) if callable(report) else report
        return {
            "promoted": [{"task_id": "task-1", "promoted": True}],
            "refused": [],
            "integration_branch": kwargs["integration_branch"],
        }

    def branch_revision(_root, _branch):
        return integration_revision

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", Manager)
    monkeypatch.setattr(gated_writes, "_PromotionLock", Lock)
    monkeypatch.setattr(promotion, "authorize_persisted_promotion", authorize)
    monkeypatch.setattr(promotion, "resolve_live_target_revision", resolve)
    monkeypatch.setattr(gated_writes, "_primary_checkout_fingerprint", fingerprint)
    monkeypatch.setattr(gated_writes, "_promote_locked", promote_locked)
    monkeypatch.setattr(gated_writes, "_branch_revision", branch_revision)
    return authorization, calls


def _promote(tmp_path, ledger, candidate):
    return gated_writes.promote_candidates(
        str(tmp_path),
        [candidate],
        project=None,
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref="refs/heads/experimental",
        approval_ledger=object(),
        promotion_ledger=ledger,
        owner_keyring={("owner", "key"): b"x" * 32},
        ledger_path=tmp_path / "events.sqlite3",
    )


def test_terminal_replay_returns_receipt_without_second_mutation(monkeypatch, tmp_path) -> None:
    _authorization_value, calls = _install(
        monkeypatch,
        tmp_path,
        fingerprints=(PRIMARY, PRIMARY, PRIMARY),
    )
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    candidate = _candidate()

    first = _promote(tmp_path, ledger, candidate)
    replay = _promote(tmp_path, ledger, candidate)

    assert calls["mutations"] == 1
    assert first["promotion_receipt"]["outcome"] == "succeeded"
    assert first["promotion_start"]["replayed"] is False
    assert replay["promotion_receipt"] == first["promotion_receipt"]
    assert replay["promotion_start"]["replayed"] is True
    assert replay["promoted"] == first["promoted"]
    assert ledger.pending() == ()


def test_pending_start_is_fault_reconciled_without_mutation(monkeypatch, tmp_path) -> None:
    authorization, calls = _install(
        monkeypatch,
        tmp_path,
        fingerprints=(PRIMARY, PRIMARY),
        integration_revision=None,
    )
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    start = ledger.begin(
        authorization,
        start_id=gated_writes._stable_start_id(authorization),
        primary_checkout_before_sha256=PRIMARY,
    )
    assert start.execute

    report = _promote(tmp_path, ledger, _candidate())

    assert calls["mutations"] == 0
    assert report["promotion_receipt"]["outcome"] == "faulted"
    assert report["promotion_start"]["replayed"] is True
    assert "automatic execution was refused" in report["fault"]
    assert ledger.pending() == ()


def test_primary_checkout_change_forces_fault_receipt(monkeypatch, tmp_path) -> None:
    _authorization_value, calls = _install(
        monkeypatch,
        tmp_path,
        fingerprints=(PRIMARY, PRIMARY_CHANGED),
    )
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")

    report = _promote(tmp_path, ledger, _candidate())

    assert calls["mutations"] == 1
    assert report["promotion_receipt"]["outcome"] == "faulted"
    assert "primary checkout fingerprint changed" in report["fault"]
    assert report["promotion_receipt"]["primary_checkout_before_sha256"] == PRIMARY
    assert report["promotion_receipt"]["primary_checkout_after_sha256"] == PRIMARY_CHANGED


def test_retained_mutation_exception_is_persisted_as_fault(monkeypatch, tmp_path) -> None:
    _authorization_value, calls = _install(
        monkeypatch,
        tmp_path,
        fingerprints=(PRIMARY, PRIMARY),
        raised=RuntimeError("integration crash"),
        integration_revision=None,
    )
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")

    report = _promote(tmp_path, ledger, _candidate())

    assert calls["mutations"] == 1
    assert report["promotion_receipt"]["outcome"] == "faulted"
    assert "integration crash" in report["fault"]
    assert ledger.pending() == ()


def test_missing_after_fingerprint_leaves_non_executable_pending_start(monkeypatch, tmp_path) -> None:
    _authorization_value, calls = _install(
        monkeypatch,
        tmp_path,
        fingerprints=(PRIMARY, RuntimeError("unstable checkout")),
    )
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")

    report = _promote(tmp_path, ledger, _candidate())

    assert calls["mutations"] == 1
    assert report["promotion_receipt"] is None
    assert report["pending_reconciliation"] is True
    assert "could not be measured" in report["refused"][0]["reason"]
    assert len(ledger.pending()) == 1


class _FailingCompletionLedger(PromotionLedger):
    def complete(self, *args, **kwargs):
        raise PromotionReceiptStateError("disk full")


def test_terminal_persistence_failure_leaves_pending_and_never_claims_success(monkeypatch, tmp_path) -> None:
    _authorization_value, calls = _install(
        monkeypatch,
        tmp_path,
        fingerprints=(PRIMARY, PRIMARY),
    )
    ledger = _FailingCompletionLedger(tmp_path / "promotion.sqlite3")

    report = _promote(tmp_path, ledger, _candidate())

    assert calls["mutations"] == 1
    assert report["promoted"] == []
    assert report["promotion_receipt"] is None
    assert report["pending_reconciliation"] is True
    assert "PromotionReceipt persistence failed" in report["refused"][0]["reason"]
    assert len(ledger.pending()) == 1


def test_refusal_is_receipted_without_claiming_promotion(monkeypatch, tmp_path) -> None:
    def refused(branch):
        return {
            "promoted": [],
            "refused": [
                {
                    "task_id": "task-1",
                    "promoted": False,
                    "reason": "gate failed",
                    "integration_branch": branch,
                }
            ],
            "integration_branch": branch,
        }

    _authorization_value, calls = _install(
        monkeypatch,
        tmp_path,
        fingerprints=(PRIMARY, PRIMARY),
        report=refused,
    )
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")

    report = _promote(tmp_path, ledger, _candidate())

    assert calls["mutations"] == 1
    assert report["promoted"] == []
    assert report["promotion_receipt"]["outcome"] == "refused"
    assert report["refused"][0]["reason"] == "gate failed"

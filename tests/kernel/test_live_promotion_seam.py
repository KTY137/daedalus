from __future__ import annotations

from types import SimpleNamespace

import pytest

import daedalus.kairos.gated_writes as gated_writes
import daedalus.kernel.promotion as promotion
from daedalus.kernel import PromotionAuthorization, PromotionLedger
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
OTHER_REVISION = "b" * 40


def _candidate(*, base_revision: str = REVISION, ok: bool = True, empty: bool = False):
    artifact = SimpleNamespace(
        is_empty=empty,
        base_revision=base_revision,
        diff_sha256="c" * 64,
        changed_paths=("src/example.py",),
    )
    result = SimpleNamespace(
        ok=ok,
        artifact=artifact,
        task_id="task-1",
        state="clean" if ok else "gates_failed",
    )
    return SimpleNamespace(result=result)


def _authorization(live_target_revision: str = REVISION) -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-1",
        "candidate_artifact_sha256": "c" * 64,
        "evidence_packet_sha256": "d" * 64,
        "source_revision": REVISION,
        "target_ref": "refs/heads/experimental",
        "live_target_revision": live_target_revision,
        "approval_consumption_sha256": "e" * 64,
    }
    return PromotionAuthorization(
        **body,
        authorization_sha256=canonical_sha(body),
    )


def _install_boundary_fakes(monkeypatch, tmp_path, *, authorization=None, failure=None):
    order: list[str] = []
    calls: dict[str, object] = {}

    class Manager:
        def __init__(self, root):
            calls["manager_root"] = root
            self.worktree_root = tmp_path / "worktrees"

    class Lock:
        def __init__(self, path, *, timeout_s):
            calls["lock_path"] = path
            calls["lock_timeout_s"] = timeout_s

        def __enter__(self):
            order.append("lock-enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            order.append("lock-exit")
            return False

    chosen = authorization or _authorization()

    def resolve(root, target_ref):
        order.append("resolve-target")
        calls["resolved"] = (root, target_ref)
        return chosen.live_target_revision

    def authorize(**kwargs):
        order.append("authorize-persisted")
        calls["authorization_kwargs"] = kwargs
        if failure is not None:
            raise failure
        return chosen

    def fingerprint(_root):
        order.append("fingerprint-primary")
        return "f" * 64, True

    def integration_revision(_root, branch):
        order.append("resolve-integration")
        calls["integration_branch"] = branch
        return "9" * 40

    def promote_locked(root, manager, candidates, **kwargs):
        order.append("create-integration")
        calls["promote_locked"] = (root, manager, candidates, kwargs)
        return {
            "promoted": [{"task_id": "task-1", "promoted": True}],
            "refused": [],
            "integration_branch": "integration-test",
        }

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", Manager)
    monkeypatch.setattr(gated_writes, "_PromotionLock", Lock)
    monkeypatch.setattr(promotion, "resolve_live_target_revision", resolve)
    monkeypatch.setattr(promotion, "authorize_persisted_promotion", authorize)
    monkeypatch.setattr(gated_writes, "_primary_checkout_fingerprint", fingerprint)
    monkeypatch.setattr(gated_writes, "_resolve_integration_revision", integration_revision)
    monkeypatch.setattr(gated_writes._legacy, "_promote_locked", promote_locked)
    return order, calls


def _promote(tmp_path, candidate, **changes):
    values = dict(
        repo_root=str(tmp_path),
        candidates=[candidate],
        project=None,
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref="refs/heads/experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        promotion_ledger=PromotionLedger(tmp_path / "promotion.sqlite3"),
        ledger_path=tmp_path / "events.sqlite3",
    )
    values.update(changes)
    return gated_writes.promote_candidates(**values)


def test_persisted_authorization_and_start_precede_integration(monkeypatch, tmp_path) -> None:
    order, calls = _install_boundary_fakes(monkeypatch, tmp_path)
    candidate = _candidate()

    report = _promote(tmp_path, candidate)

    assert order == [
        "lock-enter",
        "resolve-target",
        "authorize-persisted",
        "fingerprint-primary",
        "create-integration",
        "fingerprint-primary",
        "resolve-integration",
        "lock-exit",
    ]
    assert report["authorization"]["live_target_revision"] == REVISION
    assert report["promotion_receipt"]["outcome"] == "succeeded"
    assert report["promotion_receipt"]["integration_revision"] == "9" * 40
    assert report["promotion_replayed"] is False
    kwargs = calls["authorization_kwargs"]
    assert kwargs["approval_ledger"] is not None
    assert kwargs["owner_keyring"]
    assert kwargs["candidates"] == [candidate]
    assert kwargs["live_target_revision"] == REVISION


def test_authorization_failure_creates_no_start_or_integration(monkeypatch, tmp_path) -> None:
    order, _ = _install_boundary_fakes(
        monkeypatch,
        tmp_path,
        failure=promotion.PromotionAuthorizationError("foreign persisted receipt"),
    )
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")

    report = _promote(tmp_path, _candidate(), promotion_ledger=ledger)

    assert order == [
        "lock-enter",
        "resolve-target",
        "authorize-persisted",
        "lock-exit",
    ]
    assert ledger.pending() == ()
    assert report["promoted"] == []
    assert report["authorization"] is None
    assert "foreign persisted receipt" in report["refused"][0]["reason"]


def test_stale_candidate_cannot_start_receipt_or_regenerate(monkeypatch, tmp_path) -> None:
    order, _ = _install_boundary_fakes(
        monkeypatch,
        tmp_path,
        authorization=_authorization(OTHER_REVISION),
    )
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")

    report = _promote(
        tmp_path,
        _candidate(base_revision=REVISION),
        promotion_ledger=ledger,
    )

    assert "create-integration" not in order
    assert "fingerprint-primary" not in order
    assert ledger.pending() == ()
    assert report["promoted"] == []
    assert "stale regeneration requires new evidence" in report["refused"][0]["reason"]


def test_multi_candidate_legacy_batch_refuses_before_lock_or_manager(monkeypatch, tmp_path) -> None:
    def forbidden_manager(_root):
        raise AssertionError("manager must not be constructed")

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", forbidden_manager)
    report = gated_writes.promote_candidates(
        str(tmp_path),
        [_candidate(), _candidate()],
        project=None,
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref="refs/heads/experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        promotion_ledger=PromotionLedger(tmp_path / "promotion.sqlite3"),
        ledger_path=tmp_path / "events.sqlite3",
    )

    assert report["promoted"] == []
    assert report["authorization"] is None
    assert all("exactly one candidate" in row["reason"] for row in report["refused"])


def test_ungated_candidate_refuses_before_lock(monkeypatch, tmp_path) -> None:
    entered = False

    class ForbiddenLock:
        def __init__(self, *_args, **_kwargs):
            nonlocal entered
            entered = True

    monkeypatch.setattr(gated_writes, "_PromotionLock", ForbiddenLock)
    report = _promote(tmp_path, _candidate(ok=False))

    assert not entered
    assert report["promoted"] == []
    assert "clean non-empty candidate" in report["refused"][0]["reason"]


def test_lock_refusal_does_not_reference_unissued_authorization(monkeypatch, tmp_path) -> None:
    class Manager:
        def __init__(self, _root):
            self.worktree_root = tmp_path / "worktrees"

    class RefusingLock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            raise gated_writes.PromotionUnavailable("promotion lock unavailable")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", Manager)
    monkeypatch.setattr(gated_writes, "_PromotionLock", RefusingLock)

    report = _promote(tmp_path, _candidate())

    assert report["promoted"] == []
    assert report["authorization"] is None
    assert "promotion lock unavailable" in report["refused"][0]["reason"]


def test_strangler_preserves_existing_import_surface() -> None:
    assert gated_writes.GatedCandidate is gated_writes._legacy.GatedCandidate
    assert gated_writes.gate_candidates is gated_writes._legacy.gate_candidates
    assert gated_writes.run_write_wave is gated_writes._legacy.run_write_wave
    assert gated_writes.promote_candidates is not gated_writes._legacy.promote_candidates

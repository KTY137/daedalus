from __future__ import annotations

from types import SimpleNamespace

import pytest

import daedalus.kairos.gated_writes as gated_writes
import daedalus.kernel.promotion as promotion


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


class _Authorization:
    def __init__(self, live_target_revision: str = REVISION):
        self.live_target_revision = live_target_revision
        self.authorization_sha256 = "d" * 64

    def to_dict(self) -> dict[str, str]:
        return {
            "authorization_sha256": self.authorization_sha256,
            "live_target_revision": self.live_target_revision,
        }


class _FakePromotionLedger:
    def __init__(self, _path=None, *, order=None, calls=None):
        self.order = [] if order is None else order
        self.calls = {} if calls is None else calls

    def begin(self, authorization, **kwargs):
        self.order.append("persist-start")
        self.calls["begin"] = (authorization, kwargs)
        start = SimpleNamespace(
            start_sha256="e" * 64,
            to_dict=lambda: {"start_sha256": "e" * 64},
        )
        return SimpleNamespace(execute=True, completion=None, start=start)

    def complete(self, start, **kwargs):
        self.order.append("persist-receipt")
        self.calls["complete"] = (start, kwargs)
        receipt = SimpleNamespace(
            start_sha256=start.start_sha256,
            to_dict=lambda: {
                "start_sha256": start.start_sha256,
                "outcome": kwargs["outcome"],
            },
        )
        report = kwargs["report"]
        return SimpleNamespace(
            receipt=receipt,
            report_dict=lambda: dict(report),
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

    def resolve(root, target_ref):
        order.append("resolve-target")
        calls["resolved"] = (root, target_ref)
        return (authorization or _Authorization()).live_target_revision

    def authorize(**kwargs):
        order.append("authorize-persisted")
        calls["authorization_kwargs"] = kwargs
        if failure is not None:
            raise failure
        return authorization or _Authorization()

    fingerprints = iter(("1" * 64, "1" * 64))

    def fingerprint(_root):
        order.append("fingerprint-primary")
        return next(fingerprints)

    def promote_locked(root, manager, candidates, **kwargs):
        order.append("create-integration")
        calls["promote_locked"] = (root, manager, candidates, kwargs)
        return {
            "promoted": [{"task_id": "task-1", "promoted": True}],
            "refused": [],
            "integration_branch": kwargs["integration_branch"],
        }

    def branch_revision(_root, branch):
        order.append("resolve-integration")
        calls["integration_branch"] = branch
        return REVISION

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", Manager)
    monkeypatch.setattr(gated_writes, "_PromotionLock", Lock)
    monkeypatch.setattr(promotion, "resolve_live_target_revision", resolve)
    monkeypatch.setattr(promotion, "authorize_persisted_promotion", authorize)
    monkeypatch.setattr(gated_writes, "_primary_checkout_fingerprint", fingerprint)
    monkeypatch.setattr(gated_writes, "_branch_revision", branch_revision)
    monkeypatch.setattr(gated_writes._legacy, "_promote_locked", promote_locked)
    monkeypatch.setattr(gated_writes, "PromotionLedger", _FakePromotionLedger)
    calls["promotion_ledger"] = _FakePromotionLedger(order=order, calls=calls)
    return order, calls


def _promote(tmp_path, candidate, **changes):
    promotion_ledger = changes.pop("promotion_ledger", None)
    if promotion_ledger is None:
        promotion_ledger = gated_writes.PromotionLedger(
            tmp_path / "promotion-receipts.sqlite3"
        )
    values = dict(
        repo_root=str(tmp_path),
        candidates=[candidate],
        project=None,
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref="refs/heads/experimental",
        approval_ledger=object(),
        promotion_ledger=promotion_ledger,
        owner_keyring={("owner", "key"): b"x" * 32},
        ledger_path=tmp_path / "events.sqlite3",
    )
    values.update(changes)
    return gated_writes.promote_candidates(**values)


def test_authorization_start_and_receipt_occur_inside_lock_in_order(monkeypatch, tmp_path) -> None:
    order, calls = _install_boundary_fakes(monkeypatch, tmp_path)
    candidate = _candidate()

    report = _promote(
        tmp_path,
        candidate,
        promotion_ledger=calls["promotion_ledger"],
    )

    assert order == [
        "lock-enter",
        "resolve-target",
        "authorize-persisted",
        "fingerprint-primary",
        "persist-start",
        "create-integration",
        "fingerprint-primary",
        "resolve-integration",
        "persist-receipt",
        "lock-exit",
    ]
    assert report["authorization"]["live_target_revision"] == REVISION
    assert report["promotion_receipt"]["outcome"] == "succeeded"
    kwargs = calls["authorization_kwargs"]
    assert kwargs["approval_ledger"] is not None
    assert kwargs["owner_keyring"]
    assert kwargs["candidates"] == [candidate]
    assert kwargs["live_target_revision"] == REVISION
    assert calls["begin"][1]["primary_checkout_before_sha256"] == "1" * 64
    assert calls["complete"][1]["primary_checkout_after_sha256"] == "1" * 64


def test_authorization_failure_creates_no_start_or_integration(monkeypatch, tmp_path) -> None:
    order, calls = _install_boundary_fakes(
        monkeypatch,
        tmp_path,
        failure=promotion.PromotionAuthorizationError("foreign persisted receipt"),
    )

    report = _promote(
        tmp_path,
        _candidate(),
        promotion_ledger=calls["promotion_ledger"],
    )

    assert order == [
        "lock-enter",
        "resolve-target",
        "authorize-persisted",
        "lock-exit",
    ]
    assert "begin" not in calls
    assert "promote_locked" not in calls
    assert report["promoted"] == []
    assert report["authorization"] is None
    assert "foreign persisted receipt" in report["refused"][0]["reason"]


def test_stale_candidate_cannot_persist_start_or_regenerate(monkeypatch, tmp_path) -> None:
    order, calls = _install_boundary_fakes(
        monkeypatch,
        tmp_path,
        authorization=_Authorization(OTHER_REVISION),
    )

    report = _promote(
        tmp_path,
        _candidate(base_revision=REVISION),
        promotion_ledger=calls["promotion_ledger"],
    )

    assert "persist-start" not in order
    assert "create-integration" not in order
    assert report["promoted"] == []
    assert "stale regeneration requires new evidence" in report["refused"][0]["reason"]


def test_multi_candidate_batch_refuses_before_lock_or_manager(monkeypatch, tmp_path) -> None:
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
        promotion_ledger=gated_writes.PromotionLedger(
            tmp_path / "promotion-receipts.sqlite3"
        ),
        owner_keyring={("owner", "key"): b"x" * 32},
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


def test_lock_refusal_does_not_create_start(monkeypatch, tmp_path) -> None:
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
    assert report["promotion_start"] is None
    assert "promotion lock unavailable" in report["refused"][0]["reason"]


def test_strangler_preserves_existing_import_surface() -> None:
    assert gated_writes.GatedCandidate is gated_writes._legacy.GatedCandidate
    assert gated_writes.gate_candidates is gated_writes._legacy.gate_candidates
    assert gated_writes.run_write_wave is gated_writes._legacy.run_write_wave
    assert gated_writes.promote_candidates is not gated_writes._legacy.promote_candidates

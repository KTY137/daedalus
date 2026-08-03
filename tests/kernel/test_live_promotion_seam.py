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

    def to_dict(self) -> dict[str, str]:
        return {
            "authorization_sha256": "d" * 64,
            "live_target_revision": self.live_target_revision,
        }


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
        ledger_path=tmp_path / "events.sqlite3",
    )
    values.update(changes)
    return gated_writes.promote_candidates(**values)


def test_persisted_authorization_occurs_inside_lock_before_integration(monkeypatch, tmp_path) -> None:
    order, calls = _install_boundary_fakes(monkeypatch, tmp_path)
    candidate = _candidate()

    report = _promote(tmp_path, candidate)

    assert order == [
        "lock-enter",
        "resolve-target",
        "authorize-persisted",
        "create-integration",
        "lock-exit",
    ]
    assert report["authorization"]["live_target_revision"] == REVISION
    kwargs = calls["authorization_kwargs"]
    assert kwargs["approval_ledger"] is not None
    assert kwargs["owner_keyring"]
    assert kwargs["candidates"] == [candidate]
    assert kwargs["live_target_revision"] == REVISION


def test_authorization_failure_creates_no_integration_worktree(monkeypatch, tmp_path) -> None:
    order, _ = _install_boundary_fakes(
        monkeypatch,
        tmp_path,
        failure=promotion.PromotionAuthorizationError("foreign persisted receipt"),
    )

    report = _promote(tmp_path, _candidate())

    assert order == [
        "lock-enter",
        "resolve-target",
        "authorize-persisted",
        "lock-exit",
    ]
    assert report["promoted"] == []
    assert report["authorization"] is None
    assert "foreign persisted receipt" in report["refused"][0]["reason"]


def test_stale_candidate_cannot_trigger_legacy_regeneration(monkeypatch, tmp_path) -> None:
    order, _ = _install_boundary_fakes(
        monkeypatch,
        tmp_path,
        authorization=_Authorization(OTHER_REVISION),
    )

    report = _promote(tmp_path, _candidate(base_revision=REVISION))

    assert "create-integration" not in order
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

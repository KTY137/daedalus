from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import daedalus.kairos.gated_writes as gated_writes
import daedalus.kernel.promotion as promotion
from daedalus.spine.attempt import (
    AttemptResult,
    GateResult,
    PatchArtifact,
    STATE_CLEAN,
    STATE_GATES_FAILED,
)


REVISION = "a" * 40
OTHER_REVISION = "b" * 40
NOW = datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc).isoformat()


def _candidate(
    *,
    base_revision: str = REVISION,
    ok: bool = True,
    empty: bool = False,
    suffix: str = "one",
):
    diff = b"" if empty else f"diff --git a/x b/x\n+{suffix}\n".encode()
    artifact = PatchArtifact(
        task_id=f"task-{suffix}",
        branch=f"candidate-{suffix}",
        base_revision=base_revision,
        diff_bytes=diff,
        diff_sha256=hashlib.sha256(diff).hexdigest(),
        changed_paths=("src/example.py",),
        created_ts=NOW,
    )
    result = AttemptResult(
        state=STATE_CLEAN if ok else STATE_GATES_FAILED,
        task_id=artifact.task_id,
        started_ts=NOW,
        finished_ts=NOW,
        duration_s=0.1,
        effect_key=f"effect-{suffix}",
        branch=artifact.branch,
        base_revision=base_revision,
        artifact=artifact,
        gates=GateResult(passed=ok, name="fixture-gate"),
    )
    return gated_writes.GatedCandidate(
        assignment=None,
        spec=None,
        result=result,
    )


class _Authorization:
    def __init__(self, live_target_revision: str = REVISION):
        self.live_target_revision = live_target_revision

    def to_dict(self) -> dict[str, str]:
        return {
            "authorization_sha256": "d" * 64,
            "live_target_revision": self.live_target_revision,
        }


def _consumed(expected_target_revision: str = REVISION):
    return SimpleNamespace(
        verified=SimpleNamespace(
            expected_target_revision=expected_target_revision,
        )
    )


def _install_boundary_fakes(
    monkeypatch,
    tmp_path,
    *,
    authorization=None,
    failure=None,
    on_authorize=None,
):
    order: list[str] = []
    calls: dict[str, object] = {"authorization_kwargs": []}
    authorization_count = 0

    class Manager:
        def __init__(self, root):
            order.append("manager")
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
        nonlocal authorization_count
        authorization_count += 1
        phase = "authorize-preflight" if authorization_count == 1 else "authorize-live"
        order.append(phase)
        calls["authorization_kwargs"].append(kwargs)
        if on_authorize is not None:
            on_authorize(kwargs)
        if failure is not None:
            raise failure
        return authorization or _Authorization()

    def promote_locked(root, manager, candidates, **kwargs):
        order.append("create-integration")
        calls["promote_locked"] = (root, manager, candidates, kwargs)
        return {
            "promoted": [{"task_id": candidates[0].result.task_id, "promoted": True}],
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
        consumed_approval=_consumed(),
        evidence_packet=object(),
        target_ref="refs/heads/experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        ledger_path=tmp_path / "events.sqlite3",
    )
    values.update(changes)
    return gated_writes.promote_candidates(**values)


def test_capability_auth_precedes_effects_and_live_auth_precedes_integration(
    monkeypatch,
    tmp_path,
) -> None:
    order, calls = _install_boundary_fakes(monkeypatch, tmp_path)
    candidate = _candidate()

    report = _promote(tmp_path, candidate)

    assert order == [
        "authorize-preflight",
        "manager",
        "lock-enter",
        "resolve-target",
        "authorize-live",
        "create-integration",
        "lock-exit",
    ]
    assert report["authorization"]["live_target_revision"] == REVISION
    preflight, live = calls["authorization_kwargs"]
    for kwargs in (preflight, live):
        assert kwargs["approval_ledger"] is not None
        assert kwargs["owner_keyring"]
        assert len(kwargs["candidates"]) == 1
        assert kwargs["candidates"][0].result == candidate.result
        assert kwargs["candidates"][0] is not candidate
    assert preflight["live_target_revision"] == REVISION
    assert live["live_target_revision"] == REVISION


def test_capability_auth_failure_creates_no_manager_lock_git_or_integration(
    monkeypatch,
    tmp_path,
) -> None:
    order, _ = _install_boundary_fakes(
        monkeypatch,
        tmp_path,
        failure=promotion.PromotionAuthorizationError("foreign persisted receipt"),
    )

    report = _promote(tmp_path, _candidate())

    assert order == ["authorize-preflight"]
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
    assert order[-1] == "lock-exit"
    assert report["promoted"] == []
    assert "stale regeneration requires new evidence" in report["refused"][0]["reason"]


def test_multi_candidate_legacy_batch_refuses_before_auth_lock_or_manager(monkeypatch, tmp_path) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no authority or effect primitive may be reached")

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", forbidden)
    monkeypatch.setattr(promotion, "authorize_persisted_promotion", forbidden)
    report = gated_writes.promote_candidates(
        str(tmp_path),
        [_candidate(suffix="one"), _candidate(suffix="two")],
        project=None,
        availability={},
        consumed_approval=_consumed(),
        evidence_packet=object(),
        target_ref="refs/heads/experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        ledger_path=tmp_path / "events.sqlite3",
    )

    assert report["promoted"] == []
    assert report["authorization"] is None
    assert all("exactly one candidate" in row["reason"] for row in report["refused"])


def test_ungated_candidate_refuses_before_auth_or_effect(monkeypatch, tmp_path) -> None:
    reached = False

    def forbidden(*_args, **_kwargs):
        nonlocal reached
        reached = True
        raise AssertionError("no authority or effect primitive may be reached")

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", forbidden)
    monkeypatch.setattr(promotion, "authorize_persisted_promotion", forbidden)
    report = _promote(tmp_path, _candidate(ok=False))

    assert not reached
    assert report["promoted"] == []
    assert "clean non-empty gated artifact" in report["refused"][0]["reason"]


def test_mismatched_patch_digest_refuses_before_auth_manager_or_lock(monkeypatch, tmp_path) -> None:
    reached = False

    def forbidden(*_args, **_kwargs):
        nonlocal reached
        reached = True
        raise AssertionError("no authority or effect primitive may be reached")

    candidate = _candidate()
    bad_artifact = replace(candidate.result.artifact, diff_sha256="0" * 64)
    candidate.result = replace(candidate.result, artifact=bad_artifact)
    monkeypatch.setattr(gated_writes, "GitWorktreeManager", forbidden)
    monkeypatch.setattr(promotion, "authorize_persisted_promotion", forbidden)

    report = _promote(tmp_path, candidate)

    assert not reached
    assert report["promoted"] == []
    assert "patch digest does not match patch bytes" in report["refused"][0]["reason"]


def test_result_swap_after_authorization_cannot_change_applied_bytes(monkeypatch, tmp_path) -> None:
    candidate = _candidate(suffix="approved")
    approved_result = candidate.result
    replacement = _candidate(suffix="replacement").result

    def swap_original(_kwargs) -> None:
        candidate.result = replacement

    order, calls = _install_boundary_fakes(
        monkeypatch,
        tmp_path,
        on_authorize=swap_original,
    )

    report = _promote(tmp_path, candidate)

    assert order[-2:] == ["create-integration", "lock-exit"]
    assert report["promoted"]
    applied = calls["promote_locked"][2][0].result
    assert applied == approved_result
    assert applied.artifact.diff_bytes != replacement.artifact.diff_bytes
    assert candidate.result == replacement


def test_lock_refusal_follows_successful_preflight_and_has_no_live_authorization(
    monkeypatch,
    tmp_path,
) -> None:
    order, _ = _install_boundary_fakes(monkeypatch, tmp_path)

    class RefusingLock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            order.append("lock-refused")
            raise gated_writes.PromotionUnavailable("promotion lock unavailable")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(gated_writes, "_PromotionLock", RefusingLock)

    report = _promote(tmp_path, _candidate())

    assert order == ["authorize-preflight", "manager", "lock-refused"]
    assert report["promoted"] == []
    assert report["authorization"] is None
    assert "promotion lock unavailable" in report["refused"][0]["reason"]


def test_strangler_preserves_existing_import_surface() -> None:
    assert gated_writes.GatedCandidate is gated_writes._legacy.GatedCandidate
    assert gated_writes.gate_candidates is gated_writes._legacy.gate_candidates
    assert gated_writes.run_write_wave is gated_writes._legacy.run_write_wave
    assert gated_writes.promote_candidates is not gated_writes._legacy.promote_candidates
    assert "snapshot_promotion_candidates" not in gated_writes.__all__
    assert not hasattr(gated_writes, "snapshot_promotion_candidates")

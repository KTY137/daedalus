from __future__ import annotations

from types import SimpleNamespace

import daedalus.kairos.gated_writes as gated_writes
import daedalus.kernel.promotion as promotion
from daedalus.kernel import PromotionAuthorization, PromotionLedger
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40


def _candidate():
    artifact = SimpleNamespace(
        is_empty=False,
        base_revision=REVISION,
        diff_sha256="c" * 64,
        changed_paths=("src/example.py",),
    )
    result = SimpleNamespace(
        ok=True,
        artifact=artifact,
        task_id="task-1",
        state="clean",
    )
    return SimpleNamespace(result=result)


def _authorization() -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-receipt-live",
        "candidate_artifact_sha256": "c" * 64,
        "evidence_packet_sha256": "d" * 64,
        "source_revision": REVISION,
        "target_ref": "refs/heads/experimental",
        "live_target_revision": REVISION,
        "approval_consumption_sha256": "e" * 64,
    }
    return PromotionAuthorization(
        **body,
        authorization_sha256=canonical_sha(body),
    )


class TrackingLedger(PromotionLedger):
    def __init__(self, path, order):
        self.order = order
        super().__init__(path)

    def begin(self, *args, **kwargs):
        self.order.append("persist-start")
        return super().begin(*args, **kwargs)

    def complete(self, *args, **kwargs):
        self.order.append("persist-terminal")
        return super().complete(*args, **kwargs)

    def verify_receipt(self, *args, **kwargs):
        self.order.append("verify-terminal")
        return super().verify_receipt(*args, **kwargs)


def _install(
    monkeypatch,
    tmp_path,
    order,
    *,
    promote_report=None,
    promote_error=None,
    fingerprints=None,
):
    authorization = _authorization()
    fingerprint_values = iter(fingerprints or [("f" * 64, True), ("f" * 64, True)])

    class Manager:
        def __init__(self, _root):
            self.worktree_root = tmp_path / "worktrees"

    class Lock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            order.append("lock-enter")
            return self

        def __exit__(self, *_args):
            order.append("lock-exit")
            return False

    def resolve_target(_root, _ref):
        order.append("resolve-target")
        return REVISION

    def authorize(**_kwargs):
        order.append("authorize")
        return authorization

    def fingerprint(_root):
        order.append("fingerprint")
        return next(fingerprint_values)

    def promote_locked(*_args, **_kwargs):
        order.append("mutate-integration")
        if promote_error is not None:
            raise promote_error
        return promote_report or {
            "promoted": [{"task_id": "task-1", "promoted": True}],
            "refused": [],
            "integration_branch": "integration-test",
        }

    def resolve_integration(_root, branch):
        order.append("resolve-integration")
        assert branch == "integration-test"
        return "9" * 40

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", Manager)
    monkeypatch.setattr(gated_writes, "_PromotionLock", Lock)
    monkeypatch.setattr(promotion, "resolve_live_target_revision", resolve_target)
    monkeypatch.setattr(promotion, "authorize_persisted_promotion", authorize)
    monkeypatch.setattr(gated_writes, "_primary_checkout_fingerprint", fingerprint)
    monkeypatch.setattr(gated_writes, "_resolve_integration_revision", resolve_integration)
    monkeypatch.setattr(gated_writes._legacy, "_promote_locked", promote_locked)
    return authorization


def _call(tmp_path, ledger):
    return gated_writes.promote_candidates(
        str(tmp_path),
        [_candidate()],
        project=None,
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref="refs/heads/experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        promotion_ledger=ledger,
        ledger_path=tmp_path / "events.sqlite3",
    )


def test_start_is_durable_before_retained_mutation_and_terminal_after(monkeypatch, tmp_path):
    order = []
    _install(monkeypatch, tmp_path, order)
    ledger = TrackingLedger(tmp_path / "promotion.sqlite3", order)

    report = _call(tmp_path, ledger)

    assert order == [
        "lock-enter",
        "resolve-target",
        "authorize",
        "fingerprint",
        "persist-start",
        "mutate-integration",
        "fingerprint",
        "resolve-integration",
        "persist-terminal",
        "verify-terminal",
        "lock-exit",
    ]
    assert report["promotion_receipt"]["outcome"] == "succeeded"
    assert ledger.pending() == ()


def test_exact_terminal_replay_never_reenters_integration(monkeypatch, tmp_path):
    first_order = []
    _install(monkeypatch, tmp_path, first_order)
    ledger = TrackingLedger(tmp_path / "promotion.sqlite3", first_order)
    first = _call(tmp_path, ledger)
    assert first["promotion_replayed"] is False

    replay_order = []
    _install(monkeypatch, tmp_path, replay_order)
    ledger.order = replay_order
    replay = _call(tmp_path, ledger)

    assert "mutate-integration" not in replay_order
    assert "persist-terminal" not in replay_order
    assert replay["promotion_replayed"] is True
    assert replay["promotion_receipt"] == first["promotion_receipt"]


def test_pending_start_blocks_automatic_reexecution(monkeypatch, tmp_path):
    order = []
    authorization = _install(monkeypatch, tmp_path, order)
    ledger = TrackingLedger(tmp_path / "promotion.sqlite3", order)
    start_id, _ = gated_writes._record_ids(authorization)
    ledger.begin(
        authorization,
        start_id=start_id,
        primary_checkout_before_sha256="f" * 64,
    )
    order.clear()

    report = _call(tmp_path, ledger)

    assert "mutate-integration" not in order
    assert report["promotion_pending_reconciliation"] is True
    assert report["promotion_receipt"] is None
    assert len(ledger.pending()) == 1


def test_primary_checkout_change_forces_faulted_receipt(monkeypatch, tmp_path):
    order = []
    _install(
        monkeypatch,
        tmp_path,
        order,
        fingerprints=[("f" * 64, True), ("0" * 64, False)],
    )
    ledger = TrackingLedger(tmp_path / "promotion.sqlite3", order)

    report = _call(tmp_path, ledger)

    assert report["promoted"] == [{"task_id": "task-1", "promoted": True}]
    assert report["fault"]["code"] == "primary-checkout-identity-changed"
    assert report["promotion_receipt"]["outcome"] == "faulted"
    assert report["promotion_receipt"]["primary_checkout_before_sha256"] != (
        report["promotion_receipt"]["primary_checkout_after_sha256"]
    )


def test_execution_exception_is_terminalized_as_fault(monkeypatch, tmp_path):
    order = []
    _install(
        monkeypatch,
        tmp_path,
        order,
        promote_error=RuntimeError("do not expose this detail"),
    )
    ledger = TrackingLedger(tmp_path / "promotion.sqlite3", order)

    report = _call(tmp_path, ledger)

    assert report["promotion_receipt"]["outcome"] == "faulted"
    assert report["fault"] == {
        "code": "promotion-execution-error",
        "type": "RuntimeError",
    }
    assert "do not expose this detail" not in str(report)
    assert ledger.pending() == ()


def test_refused_integration_is_persisted_without_claiming_success(monkeypatch, tmp_path):
    order = []
    _install(
        monkeypatch,
        tmp_path,
        order,
        promote_report={
            "promoted": [],
            "refused": [
                {
                    "task_id": "task-1",
                    "promoted": False,
                    "reason": "cumulative gate refused",
                }
            ],
            "integration_branch": "integration-test",
        },
    )
    ledger = TrackingLedger(tmp_path / "promotion.sqlite3", order)

    report = _call(tmp_path, ledger)

    assert report["promotion_receipt"]["outcome"] == "refused"
    assert report["promotion_receipt"]["integration_branch"] == "integration-test"
    assert report["promotion_receipt"]["integration_revision"] == "9" * 40


def test_dirty_primary_refuses_before_start(monkeypatch, tmp_path):
    order = []
    _install(
        monkeypatch,
        tmp_path,
        order,
        fingerprints=[("f" * 64, False)],
    )
    ledger = TrackingLedger(tmp_path / "promotion.sqlite3", order)

    report = _call(tmp_path, ledger)

    assert "persist-start" not in order
    assert "mutate-integration" not in order
    assert ledger.pending() == ()
    assert "must be clean" in report["refused"][0]["reason"]


def test_noncanonical_promotion_ledger_cannot_authorize_mutation(monkeypatch, tmp_path):
    class ForbiddenManager:
        def __init__(self, _root):
            raise AssertionError("manager must not be constructed")

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", ForbiddenManager)
    report = gated_writes.promote_candidates(
        str(tmp_path),
        [_candidate()],
        project=None,
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref="refs/heads/experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        promotion_ledger=object(),
        ledger_path=tmp_path / "events.sqlite3",
    )

    assert report["promoted"] == []
    assert "canonical PromotionLedger" in report["refused"][0]["reason"]

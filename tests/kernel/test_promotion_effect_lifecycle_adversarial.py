from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path

import pytest

from daedalus.kairos import promotion_effect_lifecycle as lifecycle
from daedalus.kernel.promotion_effect_replay import inspect_promotion_effect_execution
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    PromotionReconciliationDisposition,
    inspect_promotion_reconciliation,
)
from daedalus.kernel.promotion_terminalization import (
    PromotionEffectTerminalizationError,
)


def _load(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EFFECT = _load(
    "_promotion_effect_lifecycle_adversarial_capability_fixture",
    "test_promotion_effect_capability.py",
)
_PROMOTION = _load(
    "_promotion_effect_lifecycle_adversarial_execution_fixture",
    "test_promotion_replay_projection.py",
)
build_capability = _EFFECT.build_capability
authorization = _PROMOTION.authorization
successful_report = _PROMOTION.successful_report
PRIMARY = _PROMOTION.PRIMARY
INTEGRATION = _PROMOTION.INTEGRATION


def _call(capability, ledger: PromotionExecutionLedger, *, owner_keyring=None):
    return lifecycle.promote_candidates_with_effect_lifecycle(
        ".",
        [object()],
        project="project-1",
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref=capability.promotion.target_ref,
        promotion_effect_capability=capability,
        approval_ledger=object(),
        owner_keyring=(
            {("owner", "key"): b"secret"}
            if owner_keyring is None
            else owner_keyring
        ),
        promotion_execution_ledger=ledger,
    )


def _persist_terminal(capability, ledger: PromotionExecutionLedger) -> None:
    begin = ledger.begin(
        capability.promotion,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    ledger.complete(
        begin.start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=successful_report(capability.promotion),
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )


def test_exact_subject_preauthorization_binds_live_target_and_full_authorization(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    submitted = (object(),)
    snapshots = (object(),)
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        lifecycle,
        "resolve_live_target_revision",
        lambda root, target_ref: (
            observed.update(root=root, target_ref=target_ref)
            or auth.live_target_revision
        ),
    )
    monkeypatch.setattr(
        lifecycle,
        "snapshot_promotion_candidates",
        lambda candidates: (
            observed.update(candidates=candidates) or snapshots
        ),
    )

    def authorize(**kwargs):
        observed.update(authorize_kwargs=kwargs)
        return auth

    monkeypatch.setattr(lifecycle, "authorize_persisted_promotion", authorize)
    lifecycle._preauthorize_exact_subject(
        repo_root=str(tmp_path),
        candidates=submitted,
        capability=capability,
        approval_ledger="approval-ledger",
        owner_keyring={("owner", "key"): b"secret"},
        consumed_approval="consumed",
        evidence_packet="evidence",
        target_ref=auth.target_ref,
    )
    assert observed["target_ref"] == auth.target_ref
    assert observed["candidates"] == submitted
    kwargs = observed["authorize_kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["candidates"] == snapshots
    assert kwargs["live_target_revision"] == auth.live_target_revision


def test_preauthorization_refuses_capability_subject_substitution(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    substituted = authorization(candidate_artifact_sha256="9" * 64)
    monkeypatch.setattr(
        lifecycle,
        "resolve_live_target_revision",
        lambda root, target_ref: auth.live_target_revision,
    )
    monkeypatch.setattr(
        lifecycle,
        "snapshot_promotion_candidates",
        lambda candidates: tuple(candidates),
    )
    monkeypatch.setattr(
        lifecycle,
        "authorize_persisted_promotion",
        lambda **kwargs: substituted,
    )
    with pytest.raises(
        lifecycle.PromotionEffectLifecycleError,
        match="does not bind",
    ):
        lifecycle._preauthorize_exact_subject(
            repo_root=str(tmp_path),
            candidates=(object(),),
            capability=capability,
            approval_ledger=object(),
            owner_keyring={("owner", "key"): b"secret"},
            consumed_approval=object(),
            evidence_packet=object(),
            target_ref=auth.target_ref,
        )
    assert inspect_promotion_effect_execution(capability) is None


def test_fresh_delegate_pending_window_is_never_reexecuted(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    calls = 0
    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", lambda **_: None)

    def persist_start_only(*args, **kwargs):
        nonlocal calls
        calls += 1
        ledger.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
        return {"forged": "delegate-return-is-not-authority"}

    monkeypatch.setattr(
        lifecycle.gated_writes,
        "promote_candidates",
        persist_start_only,
    )
    try:
        first = _call(capability, ledger)
        assert calls == 1
        assert first["promotion_effect_pending_reconciliation"] is True
        assert (
            first["promotion_effect_lifecycle"]["disposition"]
            == "promotion-pending-reconciliation"
        )

        second = _call(capability, ledger)
        assert calls == 1
        assert second["promotion_effect_pending_reconciliation"] is True
        assert (
            inspect_promotion_reconciliation(capability, ledger).disposition
            is PromotionReconciliationDisposition.PROMOTION_PENDING
        )
    finally:
        ledger.close()


def test_concurrent_effect_start_never_enters_delegate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    original_begin = type(capability).begin
    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", lambda **_: None)

    def concurrent_begin(self):
        started = original_begin(self)
        assert started.execute is True
        return dataclasses.replace(started, execute=False)

    monkeypatch.setattr(type(capability), "begin", concurrent_begin)

    def forbidden(*args, **kwargs):
        raise AssertionError("concurrent effect start must suppress execution")

    monkeypatch.setattr(lifecycle.gated_writes, "promote_candidates", forbidden)
    try:
        report = _call(capability, ledger)
        assert report["promotion_effect_pending_reconciliation"] is True
        assert (
            report["promotion_effect_lifecycle"]["disposition"]
            == "effect-only-pending-reconciliation"
        )
        effect = inspect_promotion_effect_execution(capability)
        assert effect is not None and effect.terminal is None
    finally:
        ledger.close()


def test_terminalizer_failure_stays_pending_and_never_reenters_delegate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    _persist_terminal(capability, ledger)

    def forbidden_delegate(*args, **kwargs):
        raise AssertionError("terminal-only restart must not call promotion")

    def fail_terminalizer(*args, **kwargs):
        raise PromotionEffectTerminalizationError("injected terminal fault")

    monkeypatch.setattr(
        lifecycle.gated_writes,
        "promote_candidates",
        forbidden_delegate,
    )
    monkeypatch.setattr(lifecycle, "terminalize_promotion_effect", fail_terminalizer)
    try:
        report = _call(capability, ledger)
        assert report["promotion_effect_pending_reconciliation"] is True
        assert report["promotion_effect_error"]["type"] == (
            "PromotionEffectTerminalizationError"
        )
        projection = inspect_promotion_reconciliation(capability, ledger)
        assert (
            projection.disposition
            is PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED
        )
    finally:
        ledger.close()


def test_empty_owner_keyring_refuses_before_effect_start(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")

    def forbidden(**kwargs):
        raise AssertionError("preauthorization must not run without owner keyring")

    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", forbidden)
    try:
        with pytest.raises(
            lifecycle.PromotionEffectLifecycleError,
            match="owner keyring is required",
        ):
            _call(capability, ledger, owner_keyring={})
        assert inspect_promotion_effect_execution(capability) is None
    finally:
        ledger.close()


def test_pending_error_message_is_bounded(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", lambda **_: None)
    monkeypatch.setattr(
        lifecycle.gated_writes,
        "promote_candidates",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("x" * 5000)),
    )
    try:
        report = _call(capability, ledger)
        assert len(report["promotion_effect_error"]["message"]) == 512
        assert report["promotion_effect_pending_reconciliation"] is True
    finally:
        ledger.close()

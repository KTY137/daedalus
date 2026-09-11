from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel.effects import (
    EffectLeaseBindingMismatch,
    LeasedEffectStartReceipt,
)
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization


class RecordingLedger:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []
        self.result = object()

    def finish(self, receipt, **kwargs):
        self.calls.append((receipt, dict(kwargs)))
        return self.result


class RecordingTrustLedger:
    """Conforming ``RuntimeTrustLedgerPort`` stand-in that records lookups.

    This fixture previously injected a bare ``object()``. That was inert: it
    implemented nothing, and it only survived because the field carried a type
    annotation and no runtime check. Once ``RuntimeBoundEffectAuthorization``
    began verifying the injected port, the stale fixture made these two tests
    fail for a reason unrelated to their subject.

    A recorder is used instead of a silent stub so the terminal-receipt tests
    can assert positively that ``finish_effect`` never consults runtime trust.
    That is deliberate behaviour, not an omission: the external effect has
    already happened by the time a terminal receipt is written, so a trust
    lookup here could only strand a durable start receipt permanently open.
    Trust is rechecked where it can still prevent an effect -- verify, grant
    and both sides of ``begin_effect``.
    """

    def __init__(self) -> None:
        self.lookups: list[dict[str, object]] = []

    def require_active(self, **kwargs):
        self.lookups.append(dict(kwargs))
        return SimpleNamespace(
            runtime_id="runtime-1",
            envelope_sha256="a" * 64,
            conformance_receipt_sha256="b" * 64,
            runtime_manifest_sha256="c" * 64,
            source_revision="0" * 40,
            expires_at="2026-08-03T12:00:00+00:00",
            record_sha256="d" * 64,
        )


def authorization(*, lease_sha256: str = "1" * 64):
    request = SimpleNamespace(digest="2" * 64)
    policy = SimpleNamespace(digest="3" * 64)
    lease = SimpleNamespace(
        digest=lease_sha256,
        request_sha256=request.digest,
        policy_decision_sha256=policy.digest,
    )
    ledger = RecordingLedger()
    trust = RecordingTrustLedger()
    value = RuntimeBoundEffectAuthorization(
        capability=SimpleNamespace(lease=lease),
        request=request,
        policy_decision=policy,
        effect_ledger=ledger,
        runtime_trust_ledger=trust,
        lease_keyring={},
        runtime_authority_keyring={},
        guard_decisions=(object(),),
        current_kill_switch_generation=0,
        registry={},
    )
    return value, ledger, trust


def receipt(*, lease_sha256: str) -> LeasedEffectStartReceipt:
    return LeasedEffectStartReceipt(
        lease_sha256=lease_sha256,
        execution_id="execution-1",
        idempotency_key="idempotency-1",
        execution_request_sha256="4" * 64,
        boundary_receipt_sha256="5" * 64,
        started_at="2026-08-03T11:30:00+00:00",
        receipt_sha256="6" * 64,
    )


def test_runtime_authorization_refuses_foreign_terminal_receipt_before_ledger() -> None:
    auth, ledger, trust = authorization(lease_sha256="1" * 64)

    with pytest.raises(EffectLeaseBindingMismatch, match="different runtime effect lease"):
        auth.finish_effect(
            receipt(lease_sha256="9" * 64),
            outcome="cancelled",
            detail_sha256="7" * 64,
        )

    assert ledger.calls == []
    assert trust.lookups == []


def test_runtime_authorization_delegates_own_terminal_receipt_exactly_once() -> None:
    auth, ledger, trust = authorization(lease_sha256="1" * 64)
    start = receipt(lease_sha256="1" * 64)

    result = auth.finish_effect(
        start,
        outcome="completed",
        output_digests=("8" * 64,),
        detail_sha256="7" * 64,
    )

    assert result is ledger.result
    assert ledger.calls == [
        (
            start,
            {
                "outcome": "completed",
                "output_digests": ("8" * 64,),
                "detail_sha256": "7" * 64,
            },
        )
    ]
    assert trust.lookups == []


def test_counter_review_requires_binding_before_terminal_delegation() -> None:
    source = Path("daedalus/kernel/runtime_effects.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    runtime_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "RuntimeBoundEffectAuthorization"
    )
    finish = next(
        node
        for node in runtime_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "finish_effect"
    )

    assert isinstance(finish.body[0], ast.If)
    comparison = finish.body[0].test
    assert isinstance(comparison, ast.Compare)
    assert isinstance(comparison.ops[0], ast.NotEq)
    assert any(
        isinstance(node, ast.Attribute)
        and node.attr == "lease_sha256"
        for node in ast.walk(comparison)
    )
    assert any(
        isinstance(node, ast.Attribute)
        and node.attr == "digest"
        for node in ast.walk(comparison)
    )
    finish_calls = [
        node
        for node in ast.walk(finish)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "finish"
    ]
    assert len(finish_calls) == 1

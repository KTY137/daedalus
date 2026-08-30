# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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


def authorization(*, lease_sha256: str = "1" * 64):
    request = SimpleNamespace(digest="2" * 64)
    policy = SimpleNamespace(digest="3" * 64)
    lease = SimpleNamespace(
        digest=lease_sha256,
        request_sha256=request.digest,
        policy_decision_sha256=policy.digest,
    )
    ledger = RecordingLedger()
    value = RuntimeBoundEffectAuthorization(
        capability=SimpleNamespace(lease=lease),
        request=request,
        policy_decision=policy,
        effect_ledger=ledger,
        runtime_trust_ledger=object(),
        lease_keyring={},
        runtime_authority_keyring={},
        guard_decisions=(object(),),
        current_kill_switch_generation=0,
        registry={},
    )
    return value, ledger


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
    auth, ledger = authorization(lease_sha256="1" * 64)

    with pytest.raises(EffectLeaseBindingMismatch, match="different runtime effect lease"):
        auth.finish_effect(
            receipt(lease_sha256="9" * 64),
            outcome="cancelled",
            detail_sha256="7" * 64,
        )

    assert ledger.calls == []


def test_runtime_authorization_delegates_own_terminal_receipt_exactly_once() -> None:
    auth, ledger = authorization(lease_sha256="1" * 64)
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

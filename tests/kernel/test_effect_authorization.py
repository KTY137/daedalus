from __future__ import annotations

import ast
import dataclasses
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pytest

import daedalus.kernel.authorization as authorization_module
from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseBindingMismatch,
    EffectLeaseExpired,
    EffectLeaseLedger,
    EffectLeaseSignatureError,
    issue_effect_lease,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)

REVISION = "a" * 40
POLICY_SHA = "b" * 64
SECRET = b"generic-effect-authorization-secret-32-bytes-minimum"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def spec(*, runtime_id: str = "") -> EntrypointSpec:
    return EntrypointSpec(
        id="python.central-operation",
        surface=Surface.PYTHON,
        target="tests.fake:run",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("containment.attempt",),
        wiring=Wiring.CENTRAL,
        runtime_id=runtime_id,
    )


def registry(*, runtime_id: str = ""):
    row = spec(runtime_id=runtime_id)
    return {row.id: row}


def scope() -> EffectScope:
    return EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        tools=("python",),
        max_cost_microusd=0,
        timeout_s=60,
        max_concurrency=1,
        kill_switch_ref="mission-kill",
    )


def request(*, runtime: bool = False) -> EffectLeaseRequest:
    manifest = "c" * 64 if runtime else None
    conformance = "d" * 64 if runtime else None
    inputs = tuple(value for value in (manifest, conformance) if value)
    return EffectLeaseRequest(
        request_id="request-1",
        mission_id="mission-1",
        attempt_id="attempt-1",
        entrypoint_id="python.central-operation",
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
        ),
        effect_scope=scope(),
        idempotency_namespace="mission-1-attempt-1",
        kill_switch_generation=7,
        runtime_manifest_sha256=manifest,
        runtime_conformance_sha256=conformance,
        provenance=ContractProvenance(
            origin="tests.generic-effect-authorization",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=inputs,
            trace_id="mission-1",
        ),
    )


def decision(req: EffectLeaseRequest) -> PolicyDecision:
    return PolicyDecision(
        decision_id="decision-1",
        subject_id=req.request_id,
        subject_sha256=req.digest,
        policy_version="2026-08-03",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded test operation",),
        effect_scope=req.effect_scope,
        provenance=ContractProvenance(
            origin="tests.generic-effect-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(req.digest, POLICY_SHA),
            trace_id="mission-1",
        ),
    )


def lease(*, runtime: bool = False):
    req = request(runtime=runtime)
    policy = decision(req)
    value = issue_effect_lease(
        req,
        policy,
        lease_id="lease-1",
        issuer_key_id="lease-key-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        secret=SECRET,
        registry=registry(runtime_id="runtime-1" if runtime else ""),
    )
    return value, req, policy


def authorization(
    tmp_path,
    *,
    runtime: bool = False,
    generation: int = 7,
    generation_reader: Callable[[], int] | None = None,
):
    value, req, policy = lease(runtime=runtime)
    return NonRuntimeEffectAuthorization(
        lease=value,
        request=req,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "effects.sqlite3"),
        lease_keyring={"lease-key-1": SECRET},
        guard_decisions=(
            GuardDecision("containment.attempt", True, "artifact:sha256:" + "e" * 64),
        ),
        kill_switch_generation_reader=(
            generation_reader if generation_reader is not None else lambda: generation
        ),
        registry=registry(runtime_id="runtime-1" if runtime else ""),
    )


def execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="execution-1",
        idempotency_key="idem-1",
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
        ),
        writable_paths=("workspace/out.txt",),
        tools=("python",),
        kill_switch_ref="mission-kill",
        kill_switch_generation=7,
    )


def test_grant_start_terminal_and_exact_replay(tmp_path) -> None:
    auth = authorization(tmp_path)
    auth.grant()

    first = auth.begin_effect(execution())
    assert first.execute is True

    foreign = dataclasses.replace(first.receipt, lease_sha256="0" * 64)
    with pytest.raises(EffectLeaseBindingMismatch, match="different effect lease"):
        auth.finish_effect(foreign, outcome="completed")

    terminal = auth.finish_effect(
        first.receipt,
        outcome="completed",
        output_digests=("f" * 64,),
    )
    assert terminal.outcome == "COMPLETED"
    assert terminal.output_digests == ("f" * 64,)

    replay = auth.begin_effect(execution())
    assert replay.execute is False
    assert replay.receipt == first.receipt


def test_non_runtime_boundary_refuses_runtime_bypass(tmp_path) -> None:
    with pytest.raises(EffectLeaseBindingMismatch, match="RuntimeBound"):
        authorization(tmp_path, runtime=True)


def test_request_policy_and_signature_mismatches_fail_closed(tmp_path) -> None:
    value, req, policy = lease()
    ledger = EffectLeaseLedger(tmp_path / "effects.sqlite3")

    wrong_request = dataclasses.replace(req, attempt_id="attempt-2")
    with pytest.raises(EffectLeaseBindingMismatch, match="request"):
        NonRuntimeEffectAuthorization(
            lease=value,
            request=wrong_request,
            policy_decision=policy,
            effect_ledger=ledger,
            lease_keyring={"lease-key-1": SECRET},
            guard_decisions=(
                GuardDecision("containment.attempt", True, "evidence"),
            ),
            kill_switch_generation_reader=lambda: 7,
            registry=registry(),
        )

    tampered = dataclasses.replace(value, signature_sha256="9" * 64)
    auth = NonRuntimeEffectAuthorization(
        lease=tampered,
        request=req,
        policy_decision=policy,
        effect_ledger=ledger,
        lease_keyring={"lease-key-1": SECRET},
        guard_decisions=(
            GuardDecision("containment.attempt", True, "evidence"),
        ),
        kill_switch_generation_reader=lambda: 7,
        registry=registry(),
    )
    with pytest.raises(EffectLeaseSignatureError, match="signature"):
        auth.verify()


def test_stale_generation_and_missing_guards_are_refused(tmp_path) -> None:
    stale = authorization(tmp_path, generation=8)
    with pytest.raises(EffectLeaseBindingMismatch, match="kill-switch"):
        stale.verify()

    value, req, policy = lease()
    with pytest.raises(EffectLeaseBindingMismatch, match="guard"):
        NonRuntimeEffectAuthorization(
            lease=value,
            request=req,
            policy_decision=policy,
            effect_ledger=EffectLeaseLedger(tmp_path / "other.sqlite3"),
            lease_keyring={"lease-key-1": SECRET},
            guard_decisions=(),
            kill_switch_generation_reader=lambda: 7,
            registry=registry(),
        )


@pytest.mark.parametrize("bad_value", [True, -1, "7", None])
def test_live_generation_authority_must_return_nonnegative_integer(
    tmp_path, bad_value
) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        authorization(tmp_path, generation_reader=lambda: bad_value)


def test_live_generation_is_reread_before_every_material_boundary(tmp_path) -> None:
    state = {"generation": 7}
    auth = authorization(
        tmp_path,
        generation_reader=lambda: state["generation"],
    )
    auth.grant()

    state["generation"] = 8
    with pytest.raises(EffectLeaseBindingMismatch, match="kill-switch"):
        auth.begin_effect(execution())
    assert auth.effect_ledger.execution_state("execution-1") is None


def test_generation_flip_after_durable_start_is_cancelled_before_release(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"generation": 7}
    auth = authorization(
        tmp_path,
        generation_reader=lambda: state["generation"],
    )
    auth.grant()
    original_begin = auth.effect_ledger.begin

    def begin_then_revoke(*args, **kwargs):
        result = original_begin(*args, **kwargs)
        state["generation"] = 8
        return result

    monkeypatch.setattr(auth.effect_ledger, "begin", begin_then_revoke)
    with pytest.raises(EffectLeaseBindingMismatch, match="kill-switch"):
        auth.begin_effect(execution())
    assert auth.effect_ledger.execution_state("execution-1") == "CANCELLED"


def test_completed_terminal_requires_live_generation_but_cancellation_does_not(
    tmp_path,
) -> None:
    state = {"generation": 7}
    auth = authorization(
        tmp_path,
        generation_reader=lambda: state["generation"],
    )
    auth.grant()
    started = auth.begin_effect(execution())

    state["generation"] = 8
    with pytest.raises(EffectLeaseBindingMismatch, match="kill-switch"):
        auth.finish_effect(
            started.receipt,
            outcome="completed",
            output_digests=("f" * 64,),
        )
    assert auth.effect_ledger.execution_state("execution-1") == "STARTED"

    terminal = auth.finish_effect(started.receipt, outcome="cancelled")
    assert terminal.outcome == "CANCELLED"
    assert terminal.output_digests == ()


def test_facade_owns_verification_grant_start_and_terminal_clocks(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public_parameters = {
        name: tuple(inspect.signature(getattr(NonRuntimeEffectAuthorization, name)).parameters)
        for name in ("verify", "grant", "begin_effect", "finish_effect")
    }
    assert public_parameters["verify"] == ("self",)
    assert public_parameters["grant"] == ("self",)
    assert public_parameters["begin_effect"] == ("self", "execution")
    assert public_parameters["finish_effect"] == (
        "self",
        "start_receipt",
        "outcome",
        "output_digests",
        "detail_sha256",
    )

    auth = authorization(tmp_path / "expired-grant")
    monkeypatch.setattr(
        authorization_module,
        "_utc_now",
        lambda: NOW + timedelta(hours=2),
    )
    with pytest.raises(EffectLeaseExpired, match="expired"):
        auth.grant()

    auth = authorization(tmp_path / "expired-start")
    monkeypatch.setattr(
        authorization_module,
        "_utc_now",
        lambda: NOW + timedelta(seconds=1),
    )
    auth.grant()
    monkeypatch.setattr(
        authorization_module,
        "_utc_now",
        lambda: NOW + timedelta(hours=2),
    )
    with pytest.raises(EffectLeaseExpired, match="expired"):
        auth.begin_effect(execution())
    assert auth.effect_ledger.execution_state("execution-1") is None


def test_counter_review_pins_authority_separation() -> None:
    source = Path("daedalus/kernel/authorization.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }

    assert "issue_effect_lease" not in imported
    assert "issue_effect_lease" not in calls
    assert "promote_candidates" not in calls
    assert "run" not in calls
    assert "verify_effect_lease" in calls
    assert {"grant", "begin", "finish"} <= calls
    assert "RuntimeBoundEffectAuthorization" in source
    assert "kill_switch_generation_reader" in source
    assert "current_kill_switch_generation: int" not in source
    assert "self.current_kill_switch_generation" not in source
    assert "_POST_START_AUTHORITY_FAILURE_SHA256" in source
    assert "granted_at: datetime" not in source
    assert "started_at: datetime" not in source
    assert "finished_at: datetime" not in source

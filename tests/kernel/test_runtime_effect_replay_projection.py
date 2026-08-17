from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import daedalus.kernel.runtime_effect_replay as runtime_effect_replay
import daedalus.kernel.runtime_effects as runtime_effects
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest, EffectLeaseLedger
from daedalus.kernel.runtime_effect_replay import (
    RuntimeEffectReplayProjectionError,
    inspect_runtime_effect_execution,
)
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    issue_runtime_bound_effect_lease,
)
from daedalus.runtimes.trust_store import RuntimeTrustLedger
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)


NOW = datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)
REVISION = "1" * 40
POLICY_SHA = "2" * 64
MANIFEST_SHA = "3" * 64
IDENTITY_SHA = "4" * 64
RECEIPT_SHA = "5" * 64
ENVELOPE_SHA = "6" * 64
TRUST_KEY = b"runtime-replay-trust-integrity-key-material-32-bytes"
LEASE_KEY = b"runtime-replay-effect-lease-secret-material-32-bytes"
AUTHORITY_KEY = b"runtime-replay-authority-key-material-at-least-32-bytes"
FORGED_TRUST_SHA = "f" * 64


def _registry():
    row = EntrypointSpec(
        id="provider.test-runtime-replay",
        surface=Surface.CODEX,
        target="tests.fake:run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        runtime_id="codex_cli",
    )
    return {row.id: row}


def _scope() -> EffectScope:
    return EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        tools=("codex",),
        max_cost_microusd=100,
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="mission-kill",
    )


def _request() -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id="runtime-replay-request-1",
        mission_id="mission-1",
        attempt_id="attempt-1",
        entrypoint_id="provider.test-runtime-replay",
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        effect_scope=_scope(),
        idempotency_namespace="mission-1-attempt-1",
        kill_switch_generation=7,
        runtime_manifest_sha256=MANIFEST_SHA,
        runtime_conformance_sha256=RECEIPT_SHA,
        provenance=ContractProvenance(
            origin="tests.runtime-effect-replay",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(MANIFEST_SHA, RECEIPT_SHA),
            trace_id="mission-1",
        ),
    )


def _policy(request: EffectLeaseRequest) -> PolicyDecision:
    return PolicyDecision(
        decision_id="runtime-replay-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-04",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded trusted runtime replay",),
        effect_scope=request.effect_scope,
        provenance=ContractProvenance(
            origin="tests.runtime-effect-replay-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="mission-1",
        ),
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="runtime-replay-execution-1",
        idempotency_key="runtime-replay-idempotency-1",
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        writable_paths=("workspace/out.txt",),
        tools=("codex",),
        max_cost_microusd=100,
        kill_switch_ref="mission-kill",
        kill_switch_generation=7,
    )


def _trust_ledger(tmp_path, monkeypatch: pytest.MonkeyPatch):
    ledger = RuntimeTrustLedger(
        tmp_path / "runtime-trust.sqlite3",
        integrity_key=TRUST_KEY,
    )
    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        lambda *args, **kwargs: None,
    )
    manifest = SimpleNamespace(
        runtime_id="codex_cli",
        digest=MANIFEST_SHA,
        source_revision=REVISION,
    )
    identity = SimpleNamespace(digest=IDENTITY_SHA)
    receipt = SimpleNamespace(
        digest=RECEIPT_SHA,
        finished_at=(NOW - timedelta(minutes=10)).isoformat(),
    )
    envelope = SimpleNamespace(
        runtime_id=manifest.runtime_id,
        runtime_manifest_sha256=manifest.digest,
        probe_identity_sha256=identity.digest,
        conformance_receipt_sha256=receipt.digest,
        source_revision=REVISION,
        digest=ENVELOPE_SHA,
    )
    record = ledger.admit(
        envelope,
        identity,
        receipt,
        manifest,
        trusted_envelope_sha256s=(ENVELOPE_SHA,),
        admitted_at=NOW - timedelta(minutes=9),
        expires_at=NOW + timedelta(hours=2),
    )
    return ledger, record


def _authorization(tmp_path, monkeypatch: pytest.MonkeyPatch):
    trust_ledger, record = _trust_ledger(tmp_path, monkeypatch)
    request = _request()
    policy = _policy(request)
    capability = issue_runtime_bound_effect_lease(
        request,
        policy,
        lease_id="runtime-replay-lease-1",
        lease_issuer_key_id="runtime-replay-lease-key-1",
        lease_issuer_secret=LEASE_KEY,
        runtime_envelope_sha256=ENVELOPE_SHA,
        runtime_trust_ledger=trust_ledger,
        runtime_authority_key_id="runtime-replay-authority-key-1",
        runtime_authority_secret=AUTHORITY_KEY,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        registry=_registry(),
    )
    authorization = RuntimeBoundEffectAuthorization(
        capability=capability,
        request=request,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "effect-leases.sqlite3"),
        runtime_trust_ledger=trust_ledger,
        lease_keyring={"runtime-replay-lease-key-1": LEASE_KEY},
        runtime_authority_keyring={
            "runtime-replay-authority-key-1": AUTHORITY_KEY
        },
        guard_decisions=(
            GuardDecision(
                "budget.process_guard",
                True,
                "artifact-locator:sha256:" + "a" * 64,
            ),
        ),
        current_kill_switch_generation=7,
        registry=_registry(),
    )
    return authorization, record


def _set_runtime_clock(
    monkeypatch: pytest.MonkeyPatch,
    *values: datetime,
) -> None:
    iterator = iter(values)
    monkeypatch.setattr(
        "daedalus.kernel.runtime_effects._utc_now",
        lambda: next(iterator),
    )


def test_persisted_runtime_lease_without_start_projects_none(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(monkeypatch, NOW)
    authorization.grant()
    assert inspect_runtime_effect_execution(authorization, _execution()) is None


def test_started_runtime_execution_projects_active_trust(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(
        monkeypatch,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1, microseconds=1),
    )
    authorization.grant()
    started = authorization.begin_effect(_execution())
    assert started.execute is True

    projection = inspect_runtime_effect_execution(
        dataclasses.replace(
            authorization,
            current_kill_switch_generation=99,
        ),
        _execution(),
    )
    assert projection is not None
    assert projection.pending_reconciliation is True
    assert projection.execution.start_receipt == started.receipt
    assert projection.runtime_trust_record == record
    assert projection.verified_at == started.receipt.started_at


def test_terminal_runtime_execution_round_trips_exactly(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(
        monkeypatch,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1, microseconds=1),
    )
    authorization.grant()
    start = authorization.begin_effect(_execution()).receipt
    monkeypatch.setattr(
        "daedalus.kernel.effects._utc_now",
        lambda: NOW + timedelta(seconds=2),
    )
    terminal = authorization.finish_effect(
        start,
        outcome="completed",
        output_digests=("b" * 64,),
    )
    projection = inspect_runtime_effect_execution(authorization, _execution())
    assert projection is not None
    assert projection.pending_reconciliation is False
    assert projection.execution.terminal_receipt == terminal
    assert projection.runtime_trust_record == record


def test_wrong_runtime_authority_key_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(
        monkeypatch,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1, microseconds=1),
    )
    authorization.grant()
    authorization.begin_effect(_execution())
    forged = dataclasses.replace(
        authorization,
        runtime_authority_keyring={
            "runtime-replay-authority-key-1":
                b"wrong-runtime-authority-key-material-32-bytes"
        },
    )
    with pytest.raises(
        RuntimeEffectReplayProjectionError,
        match="historical start verification",
    ):
        inspect_runtime_effect_execution(forged, _execution())


def test_quarantined_runtime_trust_refuses_historical_projection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(
        monkeypatch,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1, microseconds=1),
    )
    authorization.grant()
    authorization.begin_effect(_execution())
    authorization.runtime_trust_ledger.quarantine(
        runtime_id=record.runtime_id,
        envelope_sha256=record.envelope_sha256,
        reason="runtime revoked after start",
        quarantined_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(
        RuntimeEffectReplayProjectionError,
        match="historical start verification",
    ):
        inspect_runtime_effect_execution(authorization, _execution())


def test_inner_execution_substitution_is_wrapped_in_runtime_domain(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(
        monkeypatch,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1, microseconds=1),
    )
    authorization.grant()
    authorization.begin_effect(_execution())
    substituted = dataclasses.replace(
        _execution(),
        idempotency_key="runtime-replay-other-idempotency",
    )
    with pytest.raises(
        RuntimeEffectReplayProjectionError,
        match="inner Effect-Lease replay failed",
    ):
        inspect_runtime_effect_execution(authorization, substituted)


def _forge_trust_digest(capability, *, resign: bool):
    """Swap the bound trust-record digest without tripping the constructor.

    ``RuntimeBoundEffectLease.__post_init__`` requires the provenance to bind
    every referenced digest, so a bare ``dataclasses.replace`` of the digest is
    unconstructible. The forgery therefore rebinds provenance too, which is what
    a real attacker would have to do.
    """

    provenance = dataclasses.replace(
        capability.provenance,
        input_digests=tuple(
            sorted(set(capability.provenance.input_digests) | {FORGED_TRUST_SHA})
        ),
    )
    forged = dataclasses.replace(
        capability,
        runtime_trust_record_sha256=FORGED_TRUST_SHA,
        provenance=provenance,
    )
    if not resign:
        return forged
    return dataclasses.replace(
        forged,
        signature_sha256=runtime_effects._signature(
            forged.signing_digest, AUTHORITY_KEY
        ),
    )


@pytest.mark.parametrize(
    ("resign", "cause"),
    [
        (False, "runtime-bound effect lease signature mismatch"),
        (True, "runtime trust record identity changed after capability issuance"),
    ],
    ids=["stale-signature", "resigned"],
)
def test_runtime_trust_record_digest_must_equal_signed_capability(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    resign: bool,
    cause: str,
) -> None:
    authorization, _record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(
        monkeypatch,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1, microseconds=1),
    )
    authorization.grant()
    authorization.begin_effect(_execution())
    forged = dataclasses.replace(
        authorization,
        capability=_forge_trust_digest(authorization.capability, resign=resign),
    )
    with pytest.raises(
        RuntimeEffectReplayProjectionError,
        match="historical start verification",
    ) as raised:
        inspect_runtime_effect_execution(forged, _execution())
    # Each forgery must be stopped by its own guard: the stale-signature variant
    # by authentication, the resigned variant by the ledger identity comparison.
    assert str(raised.value.__cause__) == cause


def test_verified_runtime_trust_digest_cannot_be_detached(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(
        monkeypatch,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1, microseconds=1),
    )
    authorization.grant()
    authorization.begin_effect(_execution())

    monkeypatch.setattr(
        runtime_effect_replay,
        "verify_runtime_bound_effect_lease",
        lambda *args, **kwargs: SimpleNamespace(
            record_sha256="f" * 64,
            runtime_id=record.runtime_id,
        ),
    )
    with pytest.raises(
        RuntimeEffectReplayProjectionError,
        match="record differs",
    ):
        inspect_runtime_effect_execution(authorization, _execution())


def test_verified_runtime_identity_cannot_be_detached(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, record = _authorization(tmp_path, monkeypatch)
    _set_runtime_clock(
        monkeypatch,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1, microseconds=1),
    )
    authorization.grant()
    authorization.begin_effect(_execution())

    monkeypatch.setattr(
        runtime_effect_replay,
        "verify_runtime_bound_effect_lease",
        lambda *args, **kwargs: SimpleNamespace(
            record_sha256=(
                authorization.capability.runtime_trust_record_sha256
            ),
            runtime_id="other_runtime",
        ),
    )
    with pytest.raises(
        RuntimeEffectReplayProjectionError,
        match="identity differs",
    ):
        inspect_runtime_effect_execution(authorization, _execution())


def test_projection_requires_exact_types() -> None:
    with pytest.raises(TypeError, match="RuntimeBoundEffectAuthorization"):
        inspect_runtime_effect_execution(object(), _execution())

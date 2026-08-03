from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest, EffectLeaseLedger
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    RuntimeBoundEffectLease,
    RuntimeLeaseBindingMismatch,
    RuntimeLeaseSignatureError,
    issue_runtime_bound_effect_lease,
    verify_runtime_bound_effect_lease,
)
from daedalus.runtimes.trust_store import (
    RuntimeTrustBindingMismatch,
    RuntimeTrustLedger,
    RuntimeTrustNotFound,
    RuntimeTrustQuarantined,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)

NOW = datetime(2026, 8, 3, 2, 0, tzinfo=timezone.utc)
REVISION = "1" * 40
POLICY_SHA = "2" * 64
MANIFEST_SHA = "3" * 64
IDENTITY_SHA = "4" * 64
RECEIPT_SHA = "5" * 64
ENVELOPE_SHA = "6" * 64
TRUST_KEY = b"runtime-trust-ledger-integrity-key-material-32-bytes"
LEASE_KEY = b"effect-lease-kernel-secret-material-32-bytes-minimum"
AUTHORITY_KEY = b"runtime-lease-authority-key-material-at-least-32-bytes"


def central_runtime_spec(*, runtime_id: str = "codex_cli") -> EntrypointSpec:
    return EntrypointSpec(
        id="provider.test-runtime",
        surface=Surface.CODEX,
        target="tests.fake:run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        runtime_id=runtime_id,
    )


def registry(*, runtime_id: str = "codex_cli"):
    spec = central_runtime_spec(runtime_id=runtime_id)
    return {spec.id: spec}


def scope() -> EffectScope:
    return EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        tools=("codex",),
        max_cost_microusd=100,
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="mission-kill",
    )


def request(
    *,
    revision: str = REVISION,
    manifest_sha: str = MANIFEST_SHA,
    receipt_sha: str = RECEIPT_SHA,
) -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id="runtime-lease-request-1",
        mission_id="mission-1",
        attempt_id="attempt-1",
        entrypoint_id="provider.test-runtime",
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        effect_scope=scope(),
        idempotency_namespace="mission-1-attempt-1",
        kill_switch_generation=7,
        runtime_manifest_sha256=manifest_sha,
        runtime_conformance_sha256=receipt_sha,
        provenance=ContractProvenance(
            origin="tests.runtime-lease-request",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=(manifest_sha, receipt_sha),
            trace_id="mission-1",
        ),
    )


def decision(req: EffectLeaseRequest) -> PolicyDecision:
    return PolicyDecision(
        decision_id="runtime-policy-1",
        subject_id=req.request_id,
        subject_sha256=req.digest,
        policy_version="2026-08-03",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded trusted runtime",),
        effect_scope=req.effect_scope,
        provenance=ContractProvenance(
            origin="tests.runtime-lease-policy",
            source_revision=req.provenance.source_revision,
            created_at=NOW.isoformat(),
            input_digests=(req.digest, POLICY_SHA),
            trace_id="mission-1",
        ),
    )


def execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="runtime-execution-1",
        idempotency_key="runtime-idem-1",
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


def trust_objects(
    *,
    envelope_sha: str = ENVELOPE_SHA,
    manifest_sha: str = MANIFEST_SHA,
    receipt_sha: str = RECEIPT_SHA,
    revision: str = REVISION,
    observed_at: datetime | None = None,
):
    manifest = SimpleNamespace(
        runtime_id="codex_cli",
        digest=manifest_sha,
        source_revision=revision,
    )
    identity = SimpleNamespace(digest=IDENTITY_SHA)
    receipt = SimpleNamespace(
        digest=receipt_sha,
        finished_at=(observed_at or NOW - timedelta(minutes=10)).isoformat(),
    )
    envelope = SimpleNamespace(
        runtime_id=manifest.runtime_id,
        runtime_manifest_sha256=manifest.digest,
        probe_identity_sha256=identity.digest,
        conformance_receipt_sha256=receipt.digest,
        source_revision=revision,
        digest=envelope_sha,
    )
    return envelope, identity, receipt, manifest


def admitted_ledger(tmp_path, monkeypatch, *, expires_at=None):
    ledger = RuntimeTrustLedger(
        tmp_path / "runtime-trust.sqlite3", integrity_key=TRUST_KEY
    )
    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        lambda *args, **kwargs: None,
    )
    envelope, identity, receipt, manifest = trust_objects()
    record = ledger.admit(
        envelope,
        identity,
        receipt,
        manifest,
        trusted_envelope_sha256s=(envelope.digest,),
        admitted_at=NOW,
        expires_at=expires_at or NOW + timedelta(hours=2),
    )
    return ledger, record


def issue(trust_ledger: RuntimeTrustLedger, *, req=None, expires_at=None, envelope_sha=ENVELOPE_SHA):
    req = req or request()
    policy = decision(req)
    capability = issue_runtime_bound_effect_lease(
        req,
        policy,
        lease_id="runtime-lease-1",
        lease_issuer_key_id="lease-key-1",
        lease_issuer_secret=LEASE_KEY,
        runtime_envelope_sha256=envelope_sha,
        runtime_trust_ledger=trust_ledger,
        runtime_authority_key_id="runtime-authority-1",
        runtime_authority_secret=AUTHORITY_KEY,
        issued_at=NOW + timedelta(seconds=1),
        expires_at=expires_at or NOW + timedelta(minutes=30),
        registry=registry(),
    )
    return req, policy, capability


def verify(capability, req, policy, trust_ledger, *, now=None):
    return verify_runtime_bound_effect_lease(
        capability,
        request=req,
        policy_decision=policy,
        lease_keyring={"lease-key-1": LEASE_KEY},
        runtime_authority_keyring={"runtime-authority-1": AUTHORITY_KEY},
        runtime_trust_ledger=trust_ledger,
        current_kill_switch_generation=7,
        now=now or NOW + timedelta(seconds=2),
        registry=registry(),
    )


def authorization(tmp_path, trust_ledger, req, policy, capability):
    return RuntimeBoundEffectAuthorization(
        capability=capability,
        request=req,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "effect-leases.sqlite3"),
        runtime_trust_ledger=trust_ledger,
        lease_keyring={"lease-key-1": LEASE_KEY},
        runtime_authority_keyring={"runtime-authority-1": AUTHORITY_KEY},
        guard_decisions=(
            GuardDecision(
                "budget.process_guard",
                True,
                "artifact-locator:sha256:" + "a" * 64,
            ),
        ),
        current_kill_switch_generation=7,
        registry=registry(),
    )


def test_runtime_capability_round_trip_grant_start_and_replay(
    tmp_path, monkeypatch
) -> None:
    trust_ledger, record = admitted_ledger(tmp_path, monkeypatch)
    req, policy, capability = issue(trust_ledger)

    assert RuntimeBoundEffectLease.from_dict(capability.to_dict()) == capability
    assert verify(capability, req, policy, trust_ledger) == record

    auth = authorization(tmp_path, trust_ledger, req, policy, capability)
    auth.grant(granted_at=NOW + timedelta(seconds=2))
    first = auth.begin_effect(execution(), started_at=NOW + timedelta(seconds=3))
    second = auth.begin_effect(execution(), started_at=NOW + timedelta(seconds=3))
    assert first.execute is True
    assert second.execute is False
    assert second.receipt == first.receipt


def test_runtime_lease_cannot_be_issued_without_persisted_active_trust(
    tmp_path,
) -> None:
    trust_ledger = RuntimeTrustLedger(
        tmp_path / "runtime-trust.sqlite3", integrity_key=TRUST_KEY
    )
    with pytest.raises(RuntimeTrustNotFound, match="not admitted"):
        issue(trust_ledger)


def test_runtime_identity_revision_and_receipt_repackaging_fail_closed(
    tmp_path, monkeypatch
) -> None:
    trust_ledger, _ = admitted_ledger(tmp_path, monkeypatch)
    with pytest.raises(RuntimeTrustNotFound, match="not admitted"):
        issue(trust_ledger, envelope_sha="f" * 64)
    with pytest.raises(RuntimeTrustBindingMismatch, match="runtime_manifest_sha256"):
        issue(trust_ledger, req=request(manifest_sha="e" * 64))
    with pytest.raises(RuntimeTrustBindingMismatch, match="conformance_receipt_sha256"):
        issue(trust_ledger, req=request(receipt_sha="d" * 64))
    with pytest.raises(RuntimeTrustBindingMismatch, match="source_revision"):
        issue(trust_ledger, req=request(revision="2" * 40))


def test_effect_lease_cannot_outlive_runtime_trust(tmp_path, monkeypatch) -> None:
    trust_ledger, _ = admitted_ledger(
        tmp_path, monkeypatch, expires_at=NOW + timedelta(minutes=5)
    )
    with pytest.raises(RuntimeLeaseBindingMismatch, match="cannot outlive"):
        issue(trust_ledger, expires_at=NOW + timedelta(minutes=6))


def test_quarantine_after_grant_blocks_start_before_external_effect(
    tmp_path, monkeypatch
) -> None:
    trust_ledger, record = admitted_ledger(tmp_path, monkeypatch)
    req, policy, capability = issue(trust_ledger)
    auth = authorization(tmp_path, trust_ledger, req, policy, capability)
    auth.grant(granted_at=NOW + timedelta(seconds=2))
    trust_ledger.quarantine(
        runtime_id=record.runtime_id,
        envelope_sha256=record.envelope_sha256,
        reason="binary-revoked",
        quarantined_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(RuntimeTrustQuarantined, match="binary-revoked"):
        auth.begin_effect(execution(), started_at=NOW + timedelta(seconds=4))
    assert auth.effect_ledger.execution_state("runtime-execution-1") is None


def test_runtime_authority_signature_and_record_identity_are_exact(
    tmp_path, monkeypatch
) -> None:
    trust_ledger, _ = admitted_ledger(tmp_path, monkeypatch)
    req, policy, capability = issue(trust_ledger)
    bad_signature = dataclasses.replace(capability, signature_sha256="f" * 64)
    with pytest.raises(RuntimeLeaseSignatureError, match="signature"):
        verify(bad_signature, req, policy, trust_ledger)
    with pytest.raises(RuntimeLeaseSignatureError, match="unknown"):
        verify_runtime_bound_effect_lease(
            capability,
            request=req,
            policy_decision=policy,
            lease_keyring={"lease-key-1": LEASE_KEY},
            runtime_authority_keyring={},
            runtime_trust_ledger=trust_ledger,
            current_kill_switch_generation=7,
            now=NOW + timedelta(seconds=2),
            registry=registry(),
        )


def test_non_runtime_entrypoint_cannot_be_wrapped_as_runtime_trust(
    tmp_path, monkeypatch
) -> None:
    trust_ledger, _ = admitted_ledger(tmp_path, monkeypatch)
    req = request()
    with pytest.raises(EffectLeaseBindingMismatch, match="non-runtime"):
        issue_runtime_bound_effect_lease(
            req,
            decision(req),
            lease_id="runtime-lease-1",
            lease_issuer_key_id="lease-key-1",
            lease_issuer_secret=LEASE_KEY,
            runtime_envelope_sha256=ENVELOPE_SHA,
            runtime_trust_ledger=trust_ledger,
            runtime_authority_key_id="runtime-authority-1",
            runtime_authority_secret=AUTHORITY_KEY,
            issued_at=NOW + timedelta(seconds=1),
            expires_at=NOW + timedelta(minutes=30),
            registry=registry(runtime_id=""),
        )

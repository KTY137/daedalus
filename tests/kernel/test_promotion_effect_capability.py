from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    issue_effect_lease,
)
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_effects import (
    PROMOTION_EFFECTS,
    PROMOTION_ENTRYPOINT_ID,
    PROMOTION_GUARD_CONTRACTS,
    PROMOTION_TARGET,
    PromotionEffectBindingMismatch,
    PromotionEffectCapability,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
CANDIDATE_SHA = "b" * 64
EVIDENCE_SHA = "c" * 64
APPROVAL_SHA = "d" * 64
POLICY_SHA = "e" * 64
SECRET = b"promotion-effect-capability-secret-32-bytes-minimum"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def promotion(**updates) -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-1",
        "candidate_artifact_sha256": CANDIDATE_SHA,
        "evidence_packet_sha256": EVIDENCE_SHA,
        "source_revision": REVISION,
        "target_ref": "refs-heads-main",
        "live_target_revision": REVISION,
        "approval_consumption_sha256": APPROVAL_SHA,
    }
    body.update(updates)
    return PromotionAuthorization(
        **body,
        authorization_sha256=canonical_sha(body),
    )


def row(**updates) -> EntrypointSpec:
    body = {
        "id": PROMOTION_ENTRYPOINT_ID,
        "surface": Surface.PYTHON,
        "target": PROMOTION_TARGET,
        "effects": (
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        "guard_contracts": PROMOTION_GUARD_CONTRACTS,
        "wiring": Wiring.CENTRAL,
    }
    body.update(updates)
    return EntrypointSpec(**body)


def build_capability(
    tmp_path,
    *,
    promotion_value: PromotionAuthorization | None = None,
    registry_row: EntrypointSpec | None = None,
    authorization_registry_row: EntrypointSpec | None = None,
    attempt_id: str | None = None,
    provenance_inputs: tuple[str, ...] | None = None,
    scope_value: EffectScope | None = None,
    execution_updates: dict | None = None,
    guard_updates: dict[str, GuardDecision] | None = None,
) -> PromotionEffectCapability:
    subject = promotion_value or promotion()
    issue_row = registry_row or row()
    registry = {PROMOTION_ENTRYPOINT_ID: issue_row}
    inputs = provenance_inputs
    if inputs is None:
        inputs = (
            subject.authorization_sha256,
            subject.candidate_artifact_sha256,
            subject.evidence_packet_sha256,
            subject.approval_consumption_sha256,
        )
    scope = scope_value or EffectScope(
        read_only=False,
        writable_paths=("integration-worktrees", "state"),
        tools=("git", "python"),
        timeout_s=300,
        max_concurrency=1,
        kill_switch_ref="promotion-kill",
    )
    request = EffectLeaseRequest(
        request_id="promotion-effect-request-1",
        mission_id="mission-1",
        attempt_id=attempt_id or subject.promotion_id,
        entrypoint_id=PROMOTION_ENTRYPOINT_ID,
        requested_effects=PROMOTION_EFFECTS,
        effect_scope=scope,
        idempotency_namespace="promotion-effects",
        kill_switch_generation=7,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.promotion-effect-capability",
            source_revision=subject.source_revision,
            created_at=NOW.isoformat(),
            input_digests=inputs,
            trace_id="mission-1",
        ),
    )
    policy = PolicyDecision(
        decision_id="promotion-effect-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-04",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded owner-approved promotion",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.promotion-effect-policy",
            source_revision=subject.source_revision,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="mission-1",
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="promotion-effect-lease-1",
        issuer_key_id="promotion-effect-key-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        secret=SECRET,
        registry=registry,
    )
    guards = {
        "containment.worktree": GuardDecision(
            "containment.worktree",
            True,
            "artifact:sha256:" + "f" * 64,
        ),
        "promotion.owner_approval": GuardDecision(
            "promotion.owner_approval",
            True,
            "artifact:sha256:" + subject.approval_consumption_sha256,
        ),
        "spine.intent_ledger": GuardDecision(
            "spine.intent_ledger",
            True,
            "artifact:sha256:" + "1" * 64,
        ),
    }
    guards.update(guard_updates or {})
    authorization = NonRuntimeEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "effects.sqlite3"),
        lease_keyring={"promotion-effect-key-1": SECRET},
        guard_decisions=tuple(guards.values()),
        kill_switch_generation_reader=lambda: 7,
        registry={
            PROMOTION_ENTRYPOINT_ID: authorization_registry_row or issue_row
        },
    )
    execution_body = {
        "execution_id": subject.promotion_id,
        "idempotency_key": subject.authorization_sha256,
        "requested_effects": PROMOTION_EFFECTS,
        "writable_paths": (
            "integration-worktrees/promotion-1",
            "state/spine.sqlite3",
        ),
        "tools": ("git",),
        "kill_switch_ref": "promotion-kill",
        "kill_switch_generation": 7,
    }
    execution_body.update(execution_updates or {})
    return PromotionEffectCapability(
        promotion=subject,
        authorization=authorization,
        execution=EffectExecutionRequest(**execution_body),
    )


def test_grant_begin_finish_and_exact_replay(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()

    started = capability.begin()
    assert started.execute is True
    terminal = capability.finish(
        started.receipt,
        outcome="completed",
        output_digests=("2" * 64,),
    )
    assert terminal.outcome == "COMPLETED"
    assert terminal.output_digests == ("2" * 64,)

    replay = capability.begin()
    assert replay.execute is False
    assert replay.receipt == started.receipt


def test_repacked_promotion_authorization_is_refused(tmp_path) -> None:
    original = promotion()
    repacked = dataclasses.replace(
        original,
        candidate_artifact_sha256="9" * 64,
    )
    with pytest.raises(PromotionEffectBindingMismatch, match="digest"):
        build_capability(tmp_path, promotion_value=repacked)


@pytest.mark.parametrize(
    ("attempt_id", "execution_updates", "match"),
    [
        ("promotion-2", None, "request_attempt"),
        (None, {"execution_id": "promotion-2"}, "execution_id"),
        (None, {"idempotency_key": "other-idempotency"}, "idempotency_key"),
        (
            None,
            {"requested_effects": (Effect.FILESYSTEM_WRITE.value,)},
            "execution_effects",
        ),
    ],
)
def test_cross_subject_execution_is_refused(
    tmp_path, attempt_id, execution_updates, match
) -> None:
    with pytest.raises(PromotionEffectBindingMismatch, match=match):
        build_capability(
            tmp_path,
            attempt_id=attempt_id,
            execution_updates=execution_updates,
        )


def test_request_provenance_must_bind_entire_promotion_subject(tmp_path) -> None:
    subject = promotion()
    with pytest.raises(PromotionEffectBindingMismatch, match="provenance"):
        build_capability(
            tmp_path,
            promotion_value=subject,
            provenance_inputs=(
                subject.authorization_sha256,
                subject.candidate_artifact_sha256,
                subject.evidence_packet_sha256,
            ),
        )


@pytest.mark.parametrize(
    "bad_row",
    [
        row(wiring=Wiring.LOCAL_GUARDS),
        row(target="tests.fake:promote"),
        row(effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN)),
        row(guard_contracts=("promotion.owner_approval",)),
        row(runtime_id="runtime-not-allowed"),
    ],
)
def test_registry_row_must_be_exact_prospective_central_contract(
    tmp_path, bad_row
) -> None:
    with pytest.raises(PromotionEffectBindingMismatch, match="registry row mismatch"):
        build_capability(
            tmp_path,
            authorization_registry_row=bad_row,
        )


def test_owner_guard_evidence_binds_consumed_approval(tmp_path) -> None:
    with pytest.raises(PromotionEffectBindingMismatch, match="approval consumption"):
        build_capability(
            tmp_path,
            guard_updates={
                "promotion.owner_approval": GuardDecision(
                    "promotion.owner_approval",
                    True,
                    "artifact:sha256:" + "8" * 64,
                )
            },
        )


@pytest.mark.parametrize(
    "guard_updates",
    [
        {
            "containment.worktree": GuardDecision(
                "containment.worktree", False, "denied"
            )
        },
        {
            "spine.intent_ledger": GuardDecision(
                "spine.intent_ledger", True, ""
            )
        },
        {
            "unexpected.guard": GuardDecision(
                "unexpected.guard", True, "evidence"
            )
        },
    ],
)
def test_guard_set_is_exact_allowed_and_evidenced(tmp_path, guard_updates) -> None:
    with pytest.raises(PromotionEffectBindingMismatch, match="guard|denied|empty"):
        build_capability(tmp_path, guard_updates=guard_updates)


def test_hidden_egress_and_missing_git_are_refused(tmp_path) -> None:
    egress_scope = EffectScope(
        read_only=False,
        writable_paths=("integration-worktrees", "state"),
        egress_endpoints=("https://example.com",),
        tools=("git",),
        timeout_s=300,
        kill_switch_ref="promotion-kill",
    )
    with pytest.raises(PromotionEffectBindingMismatch, match="egress"):
        build_capability(
            tmp_path / "egress",
            scope_value=egress_scope,
            execution_updates={"egress_endpoints": ("https://example.com",)},
        )

    no_git_scope = EffectScope(
        read_only=False,
        writable_paths=("integration-worktrees", "state"),
        tools=("python",),
        timeout_s=300,
        kill_switch_ref="promotion-kill",
    )
    with pytest.raises(PromotionEffectBindingMismatch, match="git_tool"):
        build_capability(tmp_path / "no-git", scope_value=no_git_scope)


@pytest.mark.parametrize(
    "malformed",
    [
        promotion(promotion_id="promotion with spaces"),
        promotion(candidate_artifact_sha256="B" * 64),
        promotion(source_revision="z" * 40),
        promotion(target_ref="refs heads main"),
        promotion(approval_consumption_sha256="not-a-digest"),
        dataclasses.replace(promotion(), authorization_sha256="not-a-digest"),
    ],
)
def test_digest_valid_but_noncanonical_promotion_fields_are_refused(
    tmp_path, malformed
) -> None:
    capability = build_capability(tmp_path)
    with pytest.raises(PromotionEffectBindingMismatch, match="noncanonical"):
        PromotionEffectCapability(
            promotion=malformed,
            authorization=capability.authorization,
            execution=capability.execution,
        )


def test_widened_signed_lease_scope_is_refused_before_delegation(tmp_path) -> None:
    capability = build_capability(tmp_path)
    widened_scope = EffectScope(
        read_only=False,
        writable_paths=(".",),
        tools=("git", "python"),
        timeout_s=300,
        kill_switch_ref="promotion-kill",
    )
    widened_lease = dataclasses.replace(
        capability.authorization.lease,
        effect_scope=widened_scope,
    )
    widened_authorization = dataclasses.replace(
        capability.authorization,
        lease=widened_lease,
    )
    with pytest.raises(PromotionEffectBindingMismatch, match="lease_scope"):
        PromotionEffectCapability(
            promotion=capability.promotion,
            authorization=widened_authorization,
            execution=capability.execution,
        )

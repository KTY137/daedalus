from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseConcurrencyError,
    EffectLeaseLedger,
    EffectLeaseScopeError,
    issue_effect_lease,
)
from daedalus.kernel.offload_lease import (
    WaveLeaseDenied,
    WaveOffloadLease,
    acquire_wave_offload_lease,
    control_root,
    rebuild_effect_lease_authorization,
)
from daedalus.limit_policy import (
    ENV_EXECUTION_LIMIT_POLICY,
    MODE_BOUNDED,
    MODE_CUSTOM,
    MODE_UNBOUNDED_EXECUTION,
    ExecutionLimitPolicy,
    LimitAxes,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.killswitch import KillSwitch
from daedalus.orchestration.workspace_containment import resolve_worktree_root
from daedalus.runtimes.admission.offload_egress import admit_offload_egress


REVISION = "d" * 40
POLICY_SHA = "e" * 64
SECRET = b"effect-limit-policy-test-secret-material"
NOW = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _axes(**changes: bool) -> LimitAxes:
    values = {field.name: True for field in dataclasses.fields(LimitAxes)}
    values.update(changes)
    return LimitAxes(**values)


def _spec(
    effects: tuple[Effect, ...] = (Effect.PROCESS_SPAWN, Effect.SPEND),
) -> EntrypointSpec:
    return EntrypointSpec(
        id="python.limit-policy-test",
        surface=Surface.PYTHON,
        target="tests.fake:run",
        effects=effects,
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
    )


def _request(
    scope: EffectScope,
    *,
    effects: tuple[Effect, ...] = (Effect.PROCESS_SPAWN, Effect.SPEND),
    suffix: str = "1",
) -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id=f"limit-policy-request-{suffix}",
        mission_id="limit-policy-mission",
        attempt_id=f"limit-policy-attempt-{suffix}",
        entrypoint_id="python.limit-policy-test",
        requested_effects=tuple(effect.value for effect in effects),
        effect_scope=scope,
        idempotency_namespace=f"limit-policy-{suffix}",
        kill_switch_generation=4,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.effect-limit-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            trace_id="limit-policy-test",
        ),
    )


def _decision(request: EffectLeaseRequest, *, suffix: str = "1") -> PolicyDecision:
    return PolicyDecision(
        decision_id=f"limit-policy-decision-{suffix}",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-30",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("owner execution limit policy captured",),
        effect_scope=request.effect_scope,
        provenance=ContractProvenance(
            origin="tests.effect-limit-policy-decision",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="limit-policy-test",
        ),
    )


def _lease(
    scope: EffectScope,
    *,
    effects: tuple[Effect, ...] = (Effect.PROCESS_SPAWN, Effect.SPEND),
    suffix: str = "1",
):
    spec = _spec(effects)
    request = _request(scope, effects=effects, suffix=suffix)
    decision = _decision(request, suffix=suffix)
    lease = issue_effect_lease(
        request,
        decision,
        lease_id=f"limit-policy-lease-{suffix}",
        issuer_key_id="limit-policy-key",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        secret=SECRET,
        registry={spec.id: spec},
    )
    return spec, request, decision, lease


def _grant(
    tmp_path: Path,
    scope: EffectScope,
    *,
    suffix: str,
):
    spec, request, decision, lease = _lease(scope, suffix=suffix)
    ledger = EffectLeaseLedger(tmp_path / f"{suffix}.sqlite3")
    ledger.grant(
        lease,
        request=request,
        policy_decision=decision,
        keyring={"limit-policy-key": SECRET},
        current_kill_switch_generation=4,
        granted_at=NOW + timedelta(seconds=1),
        registry={spec.id: spec},
    )
    return spec, request, decision, lease, ledger


def _execution(suffix: str, *, cost: int = 999_999_999) -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id=f"limit-policy-execution-{suffix}",
        idempotency_key=f"limit-policy-idempotency-{suffix}",
        requested_effects=(Effect.PROCESS_SPAWN.value, Effect.SPEND.value),
        tools=("python",),
        max_cost_microusd=cost,
        kill_switch_ref="limit-policy-kill",
        kill_switch_generation=4,
    )


def _begin(
    ledger: EffectLeaseLedger,
    lease,
    request: EffectLeaseRequest,
    decision: PolicyDecision,
    spec: EntrypointSpec,
    execution: EffectExecutionRequest,
    *,
    offset_s: int,
):
    return ledger.begin(
        lease,
        execution,
        request=request,
        policy_decision=decision,
        keyring={"limit-policy-key": SECRET},
        guard_decisions=(
            GuardDecision(
                "budget.process_guard",
                True,
                "artifact-locator:sha256:" + "f" * 64,
            ),
        ),
        current_kill_switch_generation=4,
        started_at=NOW + timedelta(seconds=offset_s),
        registry={spec.id: spec},
    )


def test_effect_scope_roundtrips_explicit_unbounded_resource_axes() -> None:
    scope = EffectScope(
        read_only=True,
        tools=("python",),
        max_cost_microusd=None,
        max_concurrency=None,
        timeout_s=None,
        kill_switch_ref="limit-policy-kill",
    )

    assert scope.has_effects is True
    assert EffectScope.from_dict(dataclasses.asdict(scope)) == scope


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "2"])
def test_effect_scope_rejects_invalid_finite_concurrency(bad: object) -> None:
    with pytest.raises(ValueError, match="positive integer or null"):
        EffectScope(max_concurrency=bad)  # type: ignore[arg-type]


def test_policy_decision_allows_resource_nulls_but_requires_kill_switch() -> None:
    scope = EffectScope(
        read_only=True,
        tools=("python",),
        max_cost_microusd=None,
        max_concurrency=None,
        timeout_s=None,
        kill_switch_ref="limit-policy-kill",
    )
    request = _request(scope)

    assert _decision(request).effect_scope == scope

    without_kill = dataclasses.replace(scope, kill_switch_ref="")
    with pytest.raises(ValueError, match="kill_switch_ref"):
        PolicyDecision(
            decision_id="limit-policy-no-kill",
            subject_id=request.request_id,
            subject_sha256=request.digest,
            policy_version="2026-08-30",
            policy_sha256=POLICY_SHA,
            verdict="allow",
            reasons=("must still be bounded by kill switch",),
            effect_scope=without_kill,
            provenance=ContractProvenance(
                origin="tests.effect-limit-policy-decision",
                source_revision=REVISION,
                created_at=NOW.isoformat(),
                input_digests=(request.digest, POLICY_SHA),
                trace_id="limit-policy-test",
            ),
        )


def test_issue_accepts_unbounded_resources_with_every_security_scope() -> None:
    effects = (
        Effect.FILESYSTEM_WRITE,
        Effect.PROCESS_SPAWN,
        Effect.NETWORK_EGRESS,
        Effect.SECRETS,
        Effect.SPEND,
    )
    scope = EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        egress_endpoints=("https://provider.example.test",),
        tools=("python",),
        secret_refs=("provider-key",),
        max_cost_microusd=None,
        max_concurrency=None,
        timeout_s=None,
        kill_switch_ref="limit-policy-kill",
    )

    _spec_value, request, decision, lease = _lease(
        scope, effects=effects, suffix="security-complete"
    )

    assert lease.effect_scope == request.effect_scope == decision.effect_scope
    assert lease.effect_scope.max_cost_microusd is None
    assert lease.effect_scope.max_concurrency is None
    assert lease.effect_scope.timeout_s is None


@pytest.mark.parametrize(
    ("scope", "match"),
    [
        (
            EffectScope(
                read_only=True,
                egress_endpoints=("https://provider.example.test",),
                tools=("python",),
                secret_refs=("provider-key",),
                max_concurrency=None,
                kill_switch_ref="limit-policy-kill",
            ),
            "write effects require bounded writable_paths",
        ),
        (
            EffectScope(
                read_only=False,
                writable_paths=("workspace",),
                tools=("python",),
                secret_refs=("provider-key",),
                max_concurrency=None,
                kill_switch_ref="limit-policy-kill",
            ),
            "network effects require explicit egress_endpoints",
        ),
        (
            EffectScope(
                read_only=False,
                writable_paths=("workspace",),
                egress_endpoints=("https://provider.example.test",),
                secret_refs=("provider-key",),
                max_concurrency=None,
                kill_switch_ref="limit-policy-kill",
            ),
            "process effects require explicit tools",
        ),
        (
            EffectScope(
                read_only=False,
                writable_paths=("workspace",),
                egress_endpoints=("https://provider.example.test",),
                tools=("python",),
                max_concurrency=None,
                kill_switch_ref="limit-policy-kill",
            ),
            "secret effects require explicit secret_refs",
        ),
    ],
)
def test_unbounded_resources_never_relax_effect_security_scope(
    scope: EffectScope,
    match: str,
) -> None:
    effects = (
        Effect.FILESYSTEM_WRITE,
        Effect.PROCESS_SPAWN,
        Effect.NETWORK_EGRESS,
        Effect.SECRETS,
        Effect.SPEND,
    )
    request = _request(scope, effects=effects, suffix="security-refusal")
    decision = _decision(request, suffix="security-refusal")

    with pytest.raises(EffectLeaseScopeError, match=match):
        issue_effect_lease(
            request,
            decision,
            lease_id="limit-policy-security-refusal",
            issuer_key_id="limit-policy-key",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
            secret=SECRET,
            registry={_spec(effects).id: _spec(effects)},
        )


def test_unbounded_spend_accepts_any_declared_cost_but_not_cost_without_spend(
    tmp_path: Path,
) -> None:
    scope = EffectScope(
        read_only=True,
        tools=("python",),
        max_cost_microusd=None,
        max_concurrency=1,
        timeout_s=None,
        kill_switch_ref="limit-policy-kill",
    )
    spec, request, decision, lease, ledger = _grant(
        tmp_path, scope, suffix="unbounded-spend"
    )

    allowed = _begin(
        ledger,
        lease,
        request,
        decision,
        spec,
        _execution("unbounded-spend"),
        offset_s=2,
    )
    assert allowed.execute is True

    cost_without_spend = EffectExecutionRequest(
        execution_id="limit-policy-execution-no-spend",
        idempotency_key="limit-policy-idempotency-no-spend",
        requested_effects=(Effect.PROCESS_SPAWN.value,),
        tools=("python",),
        max_cost_microusd=1,
        kill_switch_ref="limit-policy-kill",
        kill_switch_generation=4,
    )
    with pytest.raises(EffectLeaseScopeError, match="cost supplied without the spend effect"):
        _begin(
            ledger,
            lease,
            request,
            decision,
            spec,
            cost_without_spend,
            offset_s=3,
        )


def test_null_concurrency_skips_count_ceiling_while_finite_still_enforces(
    tmp_path: Path,
) -> None:
    unbounded_scope = EffectScope(
        read_only=True,
        tools=("python",),
        max_cost_microusd=None,
        max_concurrency=None,
        timeout_s=None,
        kill_switch_ref="limit-policy-kill",
    )
    spec, request, decision, lease, ledger = _grant(
        tmp_path, unbounded_scope, suffix="unbounded-concurrency"
    )
    assert _begin(
        ledger,
        lease,
        request,
        decision,
        spec,
        _execution("unbounded-concurrency-1"),
        offset_s=2,
    ).execute
    assert _begin(
        ledger,
        lease,
        request,
        decision,
        spec,
        _execution("unbounded-concurrency-2"),
        offset_s=3,
    ).execute

    bounded_scope = dataclasses.replace(unbounded_scope, max_concurrency=1)
    b_spec, b_request, b_decision, b_lease, b_ledger = _grant(
        tmp_path, bounded_scope, suffix="bounded-concurrency"
    )
    assert _begin(
        b_ledger,
        b_lease,
        b_request,
        b_decision,
        b_spec,
        _execution("bounded-concurrency-1"),
        offset_s=2,
    ).execute
    with pytest.raises(EffectLeaseConcurrencyError, match="ceiling reached"):
        _begin(
            b_ledger,
            b_lease,
            b_request,
            b_decision,
            b_spec,
            _execution("bounded-concurrency-2"),
            offset_s=3,
        )


@pytest.fixture
def armed_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KillSwitch:
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    monkeypatch.delenv(ENV_EXECUTION_LIMIT_POLICY, raising=False)
    switch = KillSwitch(repo_root=REPO_ROOT)
    switch.arm(note="effect limit policy test")
    assert control_root(REPO_ROOT) == tmp_path
    return switch


def _acquire_wave(
    switch: KillSwitch,
    *,
    attempt_id: str,
    limit_policy: ExecutionLimitPolicy | None = None,
    write_policy_blocked: tuple[str, ...] = (),
):
    return acquire_wave_offload_lease(
        REPO_ROOT,
        source_revision=REVISION,
        mission_id="limit-policy-mission",
        attempt_id=attempt_id,
        positions=3,
        writable_paths=("docs/limit-policy.md",),
        lanes=("ollama",),
        max_spend_usd=0.25,
        timeout_s=900,
        containment_evidence="isolated limit-policy test wave",
        write_policy_blocked=write_policy_blocked,
        switch=switch,
        limit_policy=limit_policy,
        egress_admission=admit_offload_egress,
        worktree_root_resolver=resolve_worktree_root,
    )


def test_issuer_maps_custom_policy_to_nullable_scope_and_evidences_snapshot(
    armed_switch: KillSwitch,
) -> None:
    policy = ExecutionLimitPolicy(
        mode=MODE_CUSTOM,
        configured=_axes(
            mission_spend=False,
            wall_time=False,
            concurrency=False,
        ),
    )

    granted = _acquire_wave(
        armed_switch,
        attempt_id="custom-unbounded-resource-axes",
        limit_policy=policy,
    )

    assert isinstance(granted, WaveOffloadLease)
    scope = granted.lease.effect_scope
    assert scope.max_cost_microusd is None
    assert scope.timeout_s is None
    assert scope.max_concurrency is None
    assert granted.limit_policy is policy
    assert granted.authorization.execution_limit_policy is policy
    assert granted.receipt()["execution_limit_policy"] == {
        "policy": policy.as_dict(),
        "effective": policy.effective.as_dict(),
        "fingerprint_sha256": policy.fingerprint_sha256,
    }

    subject_path = (
        Path(granted.evidence_root)
        / "lease-subject"
        / f"{granted.evidence_records['lease_subject']}.json"
    )
    subject = json.loads(subject_path.read_text(encoding="utf-8"))
    assert subject["execution_limit_policy"] == granted.receipt()[
        "execution_limit_policy"
    ]
    rebuilt = rebuild_effect_lease_authorization(
        subject,
        keyring=granted.authorization.lease_keyring,
        ledger_path=granted.ledger_path,
    )
    assert rebuilt.execution_limit_policy == policy


def test_rebuild_rejects_tampered_limit_policy_evidence(
    armed_switch: KillSwitch,
) -> None:
    policy = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)
    granted = _acquire_wave(
        armed_switch,
        attempt_id="tampered-policy-evidence",
        limit_policy=policy,
    )
    assert isinstance(granted, WaveOffloadLease)
    subject_path = (
        Path(granted.evidence_root)
        / "lease-subject"
        / f"{granted.evidence_records['lease_subject']}.json"
    )
    subject = json.loads(subject_path.read_text(encoding="utf-8"))
    subject["execution_limit_policy"]["fingerprint_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="fingerprint"):
        rebuild_effect_lease_authorization(
            subject,
            keyring=granted.authorization.lease_keyring,
            ledger_path=granted.ledger_path,
        )


def test_bounded_mode_uses_existing_values_and_retains_configured_choices(
    armed_switch: KillSwitch,
) -> None:
    policy = ExecutionLimitPolicy(
        mode=MODE_BOUNDED,
        configured=_axes(
            mission_spend=False,
            wall_time=False,
            concurrency=False,
        ),
    )

    granted = _acquire_wave(
        armed_switch,
        attempt_id="bounded-retains-configured",
        limit_policy=policy,
    )

    assert isinstance(granted, WaveOffloadLease)
    assert granted.lease.effect_scope.max_cost_microusd == 250_000
    assert granted.lease.effect_scope.timeout_s == 900
    assert granted.lease.effect_scope.max_concurrency == 3
    assert granted.receipt()["execution_limit_policy"]["policy"] == policy.as_dict()


def test_unbounded_mode_disables_all_three_lease_resource_axes(
    armed_switch: KillSwitch,
) -> None:
    policy = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)

    granted = _acquire_wave(
        armed_switch,
        attempt_id="fully-unbounded-execution",
        limit_policy=policy,
    )

    assert isinstance(granted, WaveOffloadLease)
    assert granted.lease.effect_scope.max_cost_microusd is None
    assert granted.lease.effect_scope.timeout_s is None
    assert granted.lease.effect_scope.max_concurrency is None

    execution = granted.execution_for(0)
    assert execution.max_cost_microusd is None
    assert execution.to_dict()["max_cost_microusd"] is None


def test_bounded_lease_refuses_execution_that_removes_cost_ceiling(
    tmp_path: Path,
) -> None:
    scope = EffectScope(
        read_only=True,
        tools=("python",),
        max_cost_microusd=10,
        max_concurrency=1,
        timeout_s=30,
        kill_switch_ref="limit-policy-kill",
    )
    spec, request, decision, lease, ledger = _grant(
        tmp_path, scope, suffix="bounded-null-cost"
    )
    execution = dataclasses.replace(
        _execution("bounded-null-cost", cost=10),
        max_cost_microusd=None,
    )

    with pytest.raises(EffectLeaseScopeError, match="removed the leased cost ceiling"):
        _begin(
            ledger,
            lease,
            request,
            decision,
            spec,
            execution,
            offset_s=2,
        )


def test_issuer_loads_policy_from_one_environment_snapshot(
    armed_switch: KillSwitch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = ExecutionLimitPolicy(
        mode=MODE_CUSTOM,
        configured=_axes(mission_spend=False),
    )
    monkeypatch.setenv(ENV_EXECUTION_LIMIT_POLICY, policy.to_env_value())

    granted = _acquire_wave(
        armed_switch,
        attempt_id="environment-policy",
    )
    monkeypatch.setenv(
        ENV_EXECUTION_LIMIT_POLICY,
        ExecutionLimitPolicy().to_env_value(),
    )

    assert isinstance(granted, WaveOffloadLease)
    assert granted.limit_policy == policy
    assert granted.lease.effect_scope.max_cost_microusd is None
    assert granted.lease.effect_scope.timeout_s == 900
    assert granted.lease.effect_scope.max_concurrency == 3
    assert granted.receipt()["execution_limit_policy"]["policy"] == policy.as_dict()


def test_policy_identity_changes_issuer_decision_digest_even_when_scope_matches(
    armed_switch: KillSwitch,
) -> None:
    bounded = ExecutionLimitPolicy(mode=MODE_BOUNDED)
    custom_all_enforced = ExecutionLimitPolicy(mode=MODE_CUSTOM)

    first = _acquire_wave(
        armed_switch,
        attempt_id="digest-bounded",
        limit_policy=bounded,
    )
    second = _acquire_wave(
        armed_switch,
        attempt_id="digest-custom",
        limit_policy=custom_all_enforced,
    )

    assert isinstance(first, WaveOffloadLease)
    assert isinstance(second, WaveOffloadLease)
    assert first.lease.effect_scope == second.lease.effect_scope
    assert first.policy_decision.policy_sha256 != second.policy_decision.policy_sha256
    assert first.policy_decision.digest != second.policy_decision.digest


def test_unbounded_resources_do_not_override_write_policy_refusal(
    armed_switch: KillSwitch,
) -> None:
    policy = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)

    denied = _acquire_wave(
        armed_switch,
        attempt_id="unbounded-write-refused",
        limit_policy=policy,
        write_policy_blocked=(".agentenv/agentenv.json",),
    )

    assert isinstance(denied, WaveLeaseDenied)
    assert any("provider.write_policy" in reason for reason in denied.reasons)
    assert denied.receipt()["execution_limit_policy"] == {
        "policy": policy.as_dict(),
        "effective": policy.effective.as_dict(),
        "fingerprint_sha256": policy.fingerprint_sha256,
    }


def test_issuer_rejects_untyped_policy_instead_of_guessing(
    armed_switch: KillSwitch,
) -> None:
    with pytest.raises(TypeError, match="ExecutionLimitPolicy or None"):
        _acquire_wave(
            armed_switch,
            attempt_id="untyped-policy",
            limit_policy={"mode": MODE_UNBOUNDED_EXECUTION},  # type: ignore[arg-type]
        )

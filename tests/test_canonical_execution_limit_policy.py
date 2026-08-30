from __future__ import annotations

import hashlib
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from daedalus import ikarus_supervisor as supervisor_module
from daedalus.ignition import gate1
from daedalus.ikarus_supervisor import (
    MissionSupervisor,
    PlannedItem,
    RoleHarness,
    SupervisorRefused,
    plan_mission,
)
from daedalus.limit_policy import (
    ENV_EXECUTION_LIMIT_POLICY,
    MODE_UNBOUNDED_EXECUTION,
    ExecutionLimitPolicy,
)
from daedalus.schemas import (
    AttemptContract,
    CampaignContract,
    ContractProvenance,
    EvidencePacket,
    MissionContract,
    ResourceBudget,
    ResourceUsage,
)
from daedalus.spine.attempt import (
    AttemptResult,
    GateResult,
    PatchArtifact,
    TaskAttempt,
    TaskSpec,
)
from daedalus.spine.killswitch import KillSwitch
from daedalus.spine.ledger import SpineLedger
from daedalus.spine.receipts import mission_contract_for_candidate


REVISION = "a" * 40
NOW = "2026-08-30T10:00:00Z"
LATER = "2026-08-30T10:01:00Z"


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _locator(value: str) -> str:
    return f"artifact-locator:sha256:{_sha(value)}"


def _provenance(*inputs: str, created_at: str = NOW) -> ContractProvenance:
    return ContractProvenance(
        origin="test.execution-limit-policy",
        source_revision=REVISION,
        created_at=created_at,
        input_digests=tuple(inputs),
        trace_id="trace-caps",
    )


def _unbounded() -> ExecutionLimitPolicy:
    return ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)


def _legacy_mission() -> MissionContract:
    policy_sha = _sha("effect-policy")
    return MissionContract(
        mission_id="mission-legacy",
        objective="Retain the legacy bounded wire shape.",
        source_revision=REVISION,
        work_item_ids=("work-1",),
        success_criteria=("tests pass",),
        policy_sha256=policy_sha,
        budget=ResourceBudget(max_wall_time_s=60),
        provenance=_provenance(policy_sha),
    )


def test_legacy_contract_payload_and_digest_shape_remain_compatible() -> None:
    mission = _legacy_mission()
    body = mission.to_dict()

    assert "execution_limit_policy" not in body
    assert "execution_limit_policy_sha256" not in body
    rebuilt = MissionContract.from_dict(body)
    assert rebuilt == mission
    assert rebuilt.digest == mission.digest


def test_unbounded_budget_keeps_configured_fallbacks_but_has_null_effective_caps() -> None:
    configured = ResourceBudget(
        max_tokens=100,
        max_cost_microusd=200,
        max_wall_time_s=3,
        max_attempts=4,
    )
    effective = configured.effective(_unbounded())

    assert configured == ResourceBudget(
        max_tokens=100,
        max_cost_microusd=200,
        max_wall_time_s=3,
        max_attempts=4,
    )
    assert effective == ResourceBudget()
    assert configured.violations(
        ResourceUsage(
            input_tokens=1_000,
            output_tokens=1_000,
            cost_microusd=1_000,
            wall_time_ms=10_000,
        ),
        execution_limit_policy=_unbounded(),
    ) == ()
    assert len(
        configured.violations(
            ResourceUsage(
                input_tokens=1_000,
                output_tokens=1_000,
                cost_microusd=1_000,
                wall_time_ms=10_000,
            )
        )
    ) == 3


def test_new_mission_binds_exact_policy_snapshot_and_fingerprint() -> None:
    effect_policy_sha = _sha("effect-policy")
    limit_policy = _unbounded()
    mission = MissionContract(
        mission_id="mission-unbounded",
        objective="Run without Daedalus-owned execution resource caps.",
        source_revision=REVISION,
        work_item_ids=("work-1",),
        success_criteria=("evidence retained",),
        policy_sha256=effect_policy_sha,
        budget=ResourceBudget(
            max_tokens=100,
            max_cost_microusd=200,
            max_wall_time_s=3,
            max_attempts=4,
        ),
        provenance=_provenance(
            effect_policy_sha, limit_policy.fingerprint_sha256
        ),
        execution_limit_policy=limit_policy,
        execution_limit_policy_sha256=limit_policy.fingerprint_sha256,
    )

    body = mission.to_dict()
    assert body["execution_limit_policy"] == limit_policy.as_dict()
    assert (
        body["execution_limit_policy_sha256"]
        == limit_policy.fingerprint_sha256
    )
    assert MissionContract.from_dict(body) == mission

    with pytest.raises(ValueError, match="does not match"):
        MissionContract(
            mission_id="mission-tampered",
            objective=mission.objective,
            source_revision=REVISION,
            work_item_ids=("work-1",),
            success_criteria=("evidence retained",),
            policy_sha256=effect_policy_sha,
            budget=mission.budget,
            provenance=_provenance(effect_policy_sha, _sha("tampered")),
            execution_limit_policy=limit_policy,
            execution_limit_policy_sha256=_sha("tampered"),
        )


def test_admission_captures_policy_once_and_attempt_inherits_mission_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    unbounded = _unbounded()
    monkeypatch.setenv(ENV_EXECUTION_LIMIT_POLICY, unbounded.to_env_value())
    mission = mission_contract_for_candidate(
        SimpleNamespace(
            task_id="task-captured",
            instruction="Change src/value.py.",
            reason="the declared gate passes",
        ),
        source_revision=REVISION,
        created_at=NOW,
        budget=ResourceBudget(
            max_tokens=100,
            max_cost_microusd=100,
            max_wall_time_s=60,
            max_attempts=2,
        ),
    )

    # A later settings change cannot rewrite the already admitted mission or
    # the attempt explicitly descended from it.
    monkeypatch.setenv(
        ENV_EXECUTION_LIMIT_POLICY, ExecutionLimitPolicy().to_env_value()
    )
    task = TaskSpec(
        task_id="task-captured",
        instruction="Change src/value.py.",
        base_revision=REVISION,
        target_paths=("src/value.py",),
        gate_paths=("tests/test_value.py",),
    )
    attempt = TaskAttempt(
        task,
        runner=lambda _ctx: {},
        gate=lambda _ctx: None,
        repo_root=tmp_path,
        mission_id=mission.mission_id,
        budget=mission.budget,
        mission_policy_sha256=mission.policy_sha256,
        execution_limit_policy=mission.execution_limit_policy,
    )

    assert mission.execution_limit_policy == unbounded
    assert attempt.execution_limit_policy == unbounded
    assert mission.budget.max_wall_time_s == 60


@pytest.mark.parametrize(
    ("limit_policy", "expected_timeout"),
    [
        (ExecutionLimitPolicy(), 0.01),
        (_unbounded(), None),
    ],
)
def test_task_attempt_gate_uses_effective_wall_time_policy(
    tmp_path,
    limit_policy: ExecutionLimitPolicy,
    expected_timeout: float | None,
) -> None:
    task = TaskSpec(
        task_id="task-effective-gate-timeout",
        instruction="Run the declared command gate.",
        base_revision=REVISION,
        gate_argv=("python", "-c", "print('ok')"),
        gate_timeout_s=0.01,
    )
    sentinel_gate = lambda _ctx: None

    with patch(
        "daedalus.spine.attempt.command_gate",
        return_value=sentinel_gate,
    ) as command:
        attempt = TaskAttempt(
            task,
            runner=lambda _ctx: {},
            repo_root=tmp_path,
            execution_limit_policy=limit_policy,
        )

    assert attempt._gate is sentinel_gate
    assert command.call_args.kwargs["timeout_s"] == expected_timeout


def test_gate1_descends_the_mission_policy_and_removes_every_gate_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    unbounded = _unbounded()
    monkeypatch.setenv(ENV_EXECUTION_LIMIT_POLICY, unbounded.to_env_value())
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))

    timeout_values: list[float | None] = []
    attempt_calls: list[dict] = []
    lease_calls: list[dict] = []
    real_check = gate1.ignition_checks.pytest_check
    real_mission = gate1.ignition_mission
    real_attempt = gate1.TaskAttempt
    real_lease = gate1.acquire_attempt_lease
    switch = KillSwitch(tmp_path / "gate1-switch")
    switch.arm()
    authority_ledger_path = tmp_path / "authority" / "spine.sqlite3"
    authority_ledger = SpineLedger(authority_ledger_path)
    authority_ledger.close()

    # This test measures immutable policy descent, not whatever operational
    # ledger happens to exist in the developer checkout.  Point the existing
    # read-only issuer seam at a real, fresh canonical ledger so the assertion
    # is identical in a clean clone and in a long-lived working tree.
    monkeypatch.setattr(
        "daedalus.spine.picker.resolve_spine_db_path",
        lambda _root: (authority_ledger_path, None),
    )

    def recording_check(*args, **kwargs):
        timeout_values.append(kwargs.get("timeout_s"))
        return real_check(*args, **kwargs)

    def recording_mission(*args, **kwargs):
        mission = real_mission(*args, **kwargs)
        # A setting changed after admission cannot rewrite descendants of the
        # immutable Mission snapshot.
        monkeypatch.setenv(
            ENV_EXECUTION_LIMIT_POLICY,
            ExecutionLimitPolicy().to_env_value(),
        )
        return mission

    def recording_attempt(task, **kwargs):
        attempt_calls.append({"task": task, **kwargs})
        return real_attempt(task, **kwargs)

    def recording_lease(*args, **kwargs):
        # Gate1's public API stays unchanged; the test injects only the
        # authority it owns at the lease seam it already observes.
        kwargs["switch"] = switch
        lease_calls.append(dict(kwargs))
        return real_lease(*args, **kwargs)

    monkeypatch.setattr(gate1.ignition_checks, "pytest_check", recording_check)
    monkeypatch.setattr(gate1, "ignition_mission", recording_mission)
    monkeypatch.setattr(gate1, "TaskAttempt", recording_attempt)
    monkeypatch.setattr(gate1, "acquire_attempt_lease", recording_lease)

    try:
        result = gate1.run_gate1_ignition(
            receipt_root=tmp_path / "receipts",
            collected_at=NOW,
        )
    finally:
        switch.stop("test complete")

    assert result.mission.execution_limit_policy == unbounded
    assert timeout_values and set(timeout_values) == {None}
    assert len(attempt_calls) == 2
    assert len(lease_calls) == 2
    for call in attempt_calls:
        assert call["task"].gate_timeout_s is None
        assert call["budget"] is result.mission.budget
        assert call["mission_policy_sha256"] == result.mission.policy_sha256
        assert call["execution_limit_policy"] is result.mission.execution_limit_policy
    for call in lease_calls:
        assert call["limit_policy"] is result.mission.execution_limit_policy


def test_supervisor_validates_fallback_but_forwards_the_mission_effective_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@example.invalid"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "value.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    unbounded = _unbounded()
    monkeypatch.setenv(ENV_EXECUTION_LIMIT_POLICY, unbounded.to_env_value())
    item = PlannedItem(
        objective="rewrite value.txt",
        role="coder",
        paths=("value.txt",),
    )
    session, mission = plan_mission(
        "supervisor cap snapshot probe",
        repo_root=repo,
        items=(item,),
        base_revision=head,
        budget=ResourceBudget(max_wall_time_s=600),
        success_criteria=("the value is rewritten",),
    )
    monkeypatch.setenv(
        ENV_EXECUTION_LIMIT_POLICY,
        ExecutionLimitPolicy().to_env_value(),
    )
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))

    observed: list[tuple[str, float | None]] = []

    def runner_factory(_item):
        def runner(ctx):
            observed.append(("runner", ctx.task.gate_timeout_s))
            (ctx.worktree / "value.txt").write_text("after\n", encoding="utf-8")
            return {"wrote": "value.txt"}

        return runner

    def gate_factory(_item):
        def gate(ctx):
            observed.append(("gate", ctx.task.gate_timeout_s))
            return GateResult(passed=True, name="unit-gate", command=())

        return gate

    attempt_calls: list[dict] = []
    real_attempt = supervisor_module.TaskAttempt

    def recording_attempt(task, **kwargs):
        attempt_calls.append({"task": task, **kwargs})
        return real_attempt(task, **kwargs)

    monkeypatch.setattr(supervisor_module, "TaskAttempt", recording_attempt)
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=tmp_path / "run",
        roles={
            "coder": RoleHarness(
                role="coder",
                runner_factory=runner_factory,
                gate_factory=gate_factory,
            )
        },
        gate_timeout_s=17.0,
    )

    final = supervisor.run(session, mission, (item,))

    assert final["outcome"] == "landed"
    assert observed == [("runner", None), ("gate", None)]
    assert len(attempt_calls) == 1
    call = attempt_calls[0]
    assert call["task"].gate_timeout_s is None
    assert call["budget"] == mission.budget
    assert call["mission_policy_sha256"] == mission.policy_sha256
    assert call["execution_limit_policy"] == unbounded
    with pytest.raises(SupervisorRefused, match="positive and finite"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=tmp_path / "invalid-timeout-run",
            roles=supervisor.roles,
            gate_timeout_s=0,
        ).run(session, mission, (item,))


def test_attempt_evidence_uses_captured_policy_without_erasing_usage() -> None:
    limit_policy = _unbounded()
    task = TaskSpec(
        task_id="task-caps",
        instruction="Change src/value.py.",
        base_revision=REVISION,
        target_paths=("src/value.py",),
        gate_paths=("tests/test_value.py",),
    )
    runtime_sha = _sha("runtime")
    decision_sha = _sha("policy-decision")
    attempt = AttemptContract.from_task_spec(
        task,
        attempt_id="attempt-caps",
        mission_id="mission-caps",
        runtime_manifest_sha256=runtime_sha,
        policy_decision_sha256=decision_sha,
        budget=ResourceBudget(
            max_tokens=10,
            max_cost_microusd=10,
            max_wall_time_s=1,
            max_attempts=1,
        ),
        provenance=_provenance(
            task.digest,
            runtime_sha,
            decision_sha,
            limit_policy.fingerprint_sha256,
        ),
        execution_limit_policy=limit_policy,
        execution_limit_policy_sha256=limit_policy.fingerprint_sha256,
    )
    diff = b"diff --git a/src/value.py b/src/value.py\n"
    artifact = PatchArtifact(
        task_id=task.task_id,
        branch="daedalus-attempt-caps",
        base_revision=REVISION,
        diff_bytes=diff,
        diff_sha256=_sha(diff),
        changed_paths=("src/value.py",),
        created_ts=NOW,
    )
    result = AttemptResult(
        state="clean",
        task_id=task.task_id,
        started_ts=NOW,
        finished_ts=LATER,
        duration_s=60.0,
        effect_key="daedalus-attempt-caps",
        branch="daedalus-attempt-caps",
        base_revision=REVISION,
        artifact=artifact,
        artifact_locator={
            "uri": f"sha256:{artifact.diff_sha256}",
            "locator_uri": _locator("candidate"),
        },
        gates=GateResult(
            passed=True,
            name="pytest",
            command=("pytest",),
            returncode=0,
            output="1 passed",
            duration_s=60.0,
        ),
    )
    usage = ResourceUsage(
        input_tokens=100,
        output_tokens=100,
        cost_microusd=100,
        wall_time_ms=60_000,
    )
    evidence_locator = _locator("gate-output")
    provenance = EvidencePacket.attempt_provenance(
        result,
        attempt=attempt,
        evidence_locator=evidence_locator,
        origin="test.execution-limit-policy",
        created_at=LATER,
    )
    packet = EvidencePacket.from_attempt_result(
        result,
        attempt=attempt,
        packet_id="packet-caps",
        usage=usage,
        provenance=provenance,
        evidence_locator=evidence_locator,
        evaluator_assurance="deterministic",
    )

    assert packet.evaluation_status == "passed"
    assert packet.usage == usage
    assert packet.items[0].details["budget_violations"] == ()
    assert packet.attempt_contract_sha256 == attempt.digest
    assert packet.execution_limit_policy == limit_policy
    assert (
        packet.execution_limit_policy_sha256
        == limit_policy.fingerprint_sha256
    )
    assert (
        packet.items[0].details["execution_limit_policy_sha256"]
        == limit_policy.fingerprint_sha256
    )
    assert limit_policy.fingerprint_sha256 in packet.provenance.input_digests
    assert limit_policy.fingerprint_sha256 in attempt.provenance.input_digests


def test_campaign_policy_does_not_relax_write_authority() -> None:
    limit_policy = _unbounded()
    evaluator = _sha("evaluator")
    inputs = (
        _sha("spec"),
        evaluator,
        _sha("task"),
        _sha("baseline"),
        _sha("generator"),
        _sha("model"),
        limit_policy.fingerprint_sha256,
    )
    common = {
        "campaign_id": "campaign-caps",
        "source_revision": REVISION,
        "experiment_spec_sha256": inputs[0],
        "evaluator_sha256": evaluator,
        "task_sha256s": (inputs[2],),
        "baseline_sha256s": (inputs[3],),
        "seeds": (1,),
        "metrics": ("success-rate",),
        "operator_axis": "representation",
        "frozen_components": {
            "generator": inputs[4],
            "model": inputs[5],
            "evaluator": evaluator,
        },
        "budget": ResourceBudget(max_wall_time_s=1),
        "expires_at": LATER,
        "provenance": _provenance(*inputs),
        "execution_limit_policy": limit_policy,
        "execution_limit_policy_sha256": limit_policy.fingerprint_sha256,
    }
    campaign = CampaignContract(**common, writable_paths=("candidates",))

    assert campaign.execution_limit_policy == limit_policy
    assert CampaignContract.from_dict(campaign.to_dict()) == campaign
    with pytest.raises(ValueError, match="bounded writable scope"):
        CampaignContract(**common, writable_paths=())

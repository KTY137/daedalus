"""G1-IKARUS-02 acceptance matrix: variable, fail-closed runtime roles."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.ikarus_runtime_role import (  # noqa: E402
    FIXTURE_EXECUTION_MODE,
    SOURCE_ONLY_EXECUTION_MODE,
    RuntimeRoleBinding,
    RuntimeRoleRegistry,
    RuntimeRoleRegistryError,
)
from daedalus.ikarus_supervisor import (  # noqa: E402
    MissionSupervisor,
    PlannedItem,
    RoleHarness,
    SupervisorRefused,
    plan_mission,
    verify_state_ledger,
)
from daedalus.schemas import MissionContract, ResourceBudget  # noqa: E402
from daedalus.spine.attempt import GateResult  # noqa: E402


HERMES_COMMIT = "fcbd1076a93841fa88855acce810e342a5b78101"


@pytest.fixture
def target_repo(tmp_path):
    repo = tmp_path / "target"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init")
    git("config", "user.name", "runtime-port-test")
    git("config", "user.email", "runtime-port@example.invalid")
    (repo / "work.txt").write_text("base\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "seed")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, head


def _gate_factory(_item):
    def gate(_ctx):
        return GateResult(passed=True, name="runtime-port-gate", command=())

    return gate


def _runner_factory(marker: str, seen: list[dict] | None = None):
    def factory(item):
        def runner(ctx):
            metadata = dict(ctx.task.metadata)
            if seen is not None:
                seen.append(metadata)
            for relative in item.paths:
                target = Path(ctx.worktree) / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(marker + "\n", encoding="utf-8")
            return {"runtime_marker": marker, "task_metadata": metadata}

        return runner

    return factory


def _fixture_binding(
    runtime_id: str,
    *,
    version: str = "1.0.0",
) -> RuntimeRoleBinding:
    return RuntimeRoleBinding(
        role="coder",
        runtime_id=runtime_id,
        adapter_id="fixture.runtime-port",
        adapter_version=version,
        source_revision=f"fixture-source-{version}",
        origin=f"fixture://{runtime_id}/{version}",
        execution_mode=FIXTURE_EXECUTION_MODE,
    )


def _fixture_harness(
    binding: RuntimeRoleBinding,
    *,
    marker: str | None = None,
    seen: list[dict] | None = None,
) -> tuple[str, RoleHarness]:
    return (
        binding.harness_key,
        RoleHarness(
            role=binding.role,
            runner_factory=_runner_factory(marker or binding.runtime_id, seen),
            gate_factory=_gate_factory,
        ),
    )


def _source_only_binding(runtime_id: str = "hermes_agent") -> RuntimeRoleBinding:
    return RuntimeRoleBinding(
        role="coder",
        runtime_id=runtime_id,
        adapter_id="source.adapter",
        adapter_version="v2026.8.19",
        source_revision=HERMES_COMMIT,
        origin="https://github.com/NousResearch/hermes-agent",
        execution_mode=SOURCE_ONLY_EXECUTION_MODE,
        refusal_reason=(
            "design provenance only; broker, containment and live conformance "
            "have not been admitted"
        ),
    )


def _item(runtime_id: str) -> PlannedItem:
    return PlannedItem(
        objective="rewrite the target through the selected runtime",
        role="coder",
        paths=("work.txt",),
        runtime_id=runtime_id,
    )


def _plan(repo: Path, head: str, item: PlannedItem, registry=None):
    return plan_mission(
        "runtime role port probe",
        repo_root=repo,
        items=(item,),
        base_revision=head,
        budget=ResourceBudget(max_wall_time_s=300),
        success_criteria=("the selected fixture produces a gated patch",),
        runtime_roles=registry,
    )


def test_runtime_registry_field_preserves_legacy_positional_constructor():
    sink = []
    supervisor = MissionSupervisor(Path("repo"), Path("run"), {}, 60.0, False, sink)

    assert supervisor.gate_timeout_s == 60.0
    assert supervisor.fail_fast is False
    assert supervisor.results is sink
    assert supervisor.runtime_roles is None


def test_runtime_and_adapter_version_are_part_of_plan_identity(target_repo):
    repo, head = target_repo
    v1 = _fixture_binding("fixture.runtime-a", version="1")
    v1_again = _fixture_binding("fixture.runtime-a", version="1")
    v2 = _fixture_binding("fixture.runtime-a", version="2")
    other = _fixture_binding("fixture.runtime-b", version="1")

    registry_v1 = RuntimeRoleRegistry((v1,))
    session_1, mission_1 = _plan(repo, head, _item("fixture.runtime-a"), registry_v1)
    session_1b, mission_1b = _plan(
        repo, head, _item("fixture.runtime-a"), RuntimeRoleRegistry((v1_again,))
    )
    session_2, mission_2 = _plan(
        repo, head, _item("fixture.runtime-a"), RuntimeRoleRegistry((v2,))
    )
    _, mission_other = _plan(
        repo, head, _item("fixture.runtime-b"), RuntimeRoleRegistry((other,))
    )
    gated_item = PlannedItem(
        objective=_item("fixture.runtime-a").objective,
        role="coder",
        paths=("work.txt",),
        gate_paths=("tests/runtime_gate.py",),
        runtime_id="fixture.runtime-a",
    )
    _, mission_gated = _plan(repo, head, gated_item, registry_v1)

    assert v1.digest == v1_again.digest
    assert mission_1.mission_id == mission_1b.mission_id
    assert mission_1.work_item_ids == mission_1b.work_item_ids
    assert mission_2.mission_id != mission_1.mission_id
    assert mission_other.mission_id != mission_1.mission_id
    assert mission_gated.mission_id != mission_1.mission_id
    assert session_1.waves[0].tasks[0].builder.endswith(v1.digest)
    assert session_2.waves[0].tasks[0].builder.endswith(v2.digest)

    # G1-IKARUS-01 compatibility: the legacy in-process identity did not bind
    # gate_paths. This packet tightens the new explicit-runtime path only.
    legacy_plain = PlannedItem(
        objective="legacy gate identity",
        role="coder",
        paths=("work.txt",),
    )
    legacy_gated = PlannedItem(
        objective=legacy_plain.objective,
        role=legacy_plain.role,
        paths=legacy_plain.paths,
        gate_paths=("tests/legacy_gate.py",),
    )
    _, legacy_plain_mission = _plan(repo, head, legacy_plain)
    _, legacy_gated_mission = _plan(repo, head, legacy_gated)
    assert legacy_plain_mission.mission_id == legacy_gated_mission.mission_id


@pytest.mark.parametrize(
    "runtime_id", ("fixture.runtime-a", "fixture.runtime-b")
)
def test_two_injected_runtimes_use_the_same_supervisor_and_receipt_shape(
    runtime_id, target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    seen: list[dict] = []
    binding = _fixture_binding(runtime_id)
    registry = RuntimeRoleRegistry((binding,))
    item = _item(runtime_id)
    session, mission = _plan(repo, head, item, registry)
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=tmp_path / "run",
        roles=dict((_fixture_harness(binding, marker=runtime_id, seen=seen),)),
        runtime_roles=registry,
        gate_timeout_s=60,
    )

    final = supervisor.run(session, mission, (item,))

    assert final["outcome"] == "landed"
    row = final["items"][0]
    assert row["runtime_id"] == runtime_id
    assert row["runtime_binding_sha256"] == binding.digest
    assert row["attempt_receipt_sha256"]
    assert row["evidence_packet_sha256"]
    assert set(row) == {
        "work_item_id",
        "objective",
        "role",
        "runtime_id",
        "runtime_binding_sha256",
        "paths",
        "status",
        "attempt_id",
        "attempt_receipt_sha256",
        "evidence_packet_sha256",
        "detail",
    }
    assert len(seen) == 1
    assert seen[0]["runtime_id"] == runtime_id
    assert seen[0]["runtime_binding_sha256"] == binding.digest
    assert seen[0]["runtime_adapter_version"] == binding.adapter_version
    assert seen[0]["runtime_source_revision"] == binding.source_revision
    assert seen[0]["runtime_origin"] == binding.origin
    contracts = supervisor.results[0].contract_set()
    assert contracts.attempt is not None
    assert contracts.attempt.base_revision == head
    assert contracts.attempt.policy_decision_sha256 == contracts.policy.digest


def test_unknown_runtime_never_falls_back_to_the_legacy_role(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    called: list[str] = []

    def legacy_runner(item):
        called.append(item.objective)
        return _runner_factory("legacy")(item)

    legacy = RoleHarness(
        role="coder", runner_factory=legacy_runner, gate_factory=_gate_factory
    )
    registry = RuntimeRoleRegistry(())
    item = _item("missing-runtime")
    session, mission = _plan(repo, head, item, registry)
    run_dir = tmp_path / "run"
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=run_dir,
        roles={"coder": legacy},
        runtime_roles=registry,
    )

    with pytest.raises(SupervisorRefused, match="missing-runtime"):
        supervisor.run(session, mission, (item,))

    assert called == []
    assert not (run_dir / "spine.sqlite3").exists()
    assert not (run_dir / "artifacts").exists()
    row = verify_state_ledger(run_dir / "ledger")[-1]["items"][0]
    assert row["status"] == "refused"
    assert row["runtime_id"] == "missing-runtime"
    assert row["runtime_binding_sha256"] is None
    assert "not registered" in row["detail"]


def test_source_only_upstream_is_provenance_not_execution(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _source_only_binding()
    registry = RuntimeRoleRegistry((binding,))
    item = _item(binding.runtime_id)
    session, mission = _plan(repo, head, item, registry)
    run_dir = tmp_path / "run"

    with pytest.raises(SupervisorRefused, match="source-only"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=run_dir,
            roles={},
            runtime_roles=registry,
        ).run(session, mission, (item,))

    assert not (run_dir / "spine.sqlite3").exists()
    row = verify_state_ledger(run_dir / "ledger")[-1]["items"][0]
    assert row["status"] == "refused"
    assert row["runtime_binding_sha256"] == binding.digest
    assert HERMES_COMMIT == binding.source_revision
    assert "live conformance" in row["detail"]


def test_duplicate_unversioned_and_live_claims_are_rejected():
    row = _fixture_binding("fixture.runtime-a")
    with pytest.raises(RuntimeRoleRegistryError, match="duplicate"):
        RuntimeRoleRegistry((row, row))

    with pytest.raises(RuntimeRoleRegistryError, match="adapter_version"):
        RuntimeRoleBinding(
            role="coder",
            runtime_id="fixture.runtime-a",
            adapter_id="fixture.runtime-port",
            adapter_version="",
            source_revision="fixture-source",
            origin="fixture://runtime-a",
            execution_mode=FIXTURE_EXECUTION_MODE,
        )

    # This packet cannot turn a declaration into production authority.
    with pytest.raises(RuntimeRoleRegistryError, match="execution_mode"):
        RuntimeRoleBinding(
            role="coder",
            runtime_id="fixture.runtime-a",
            adapter_id="fixture.runtime-port",
            adapter_version="1",
            source_revision="fixture-source",
            origin="fixture://runtime-a",
            execution_mode="brokered",
        )

    with pytest.raises(RuntimeRoleRegistryError, match="execution_mode"):
        RuntimeRoleBinding(
            role="coder",
            runtime_id="fixture.runtime-a",
            adapter_id="fixture.runtime-port",
            adapter_version="1",
            source_revision="fixture-source",
            origin="fixture://runtime-a",
            execution_mode=[],  # type: ignore[arg-type]
        )

    with pytest.raises(RuntimeRoleRegistryError, match="empty string"):
        RuntimeRoleBinding(
            role="coder",
            runtime_id="fixture.runtime-a",
            adapter_id="fixture.runtime-port",
            adapter_version="1",
            source_revision="fixture-source",
            origin="fixture://runtime-a",
            execution_mode=FIXTURE_EXECUTION_MODE,
            refusal_reason=0,  # type: ignore[arg-type]
        )

    with pytest.raises(RuntimeRoleRegistryError, match="synthetic 'fixture.'"):
        RuntimeRoleBinding(
            role="coder",
            runtime_id="hermes_agent",
            adapter_id="fixture.runtime-port",
            adapter_version="1",
            source_revision="fixture-source",
            origin="fixture://mislabelled-live-runtime",
            execution_mode=FIXTURE_EXECUTION_MODE,
        )


def test_binding_drift_between_plan_and_dispatch_refuses_before_attempt(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    planned = _fixture_binding("fixture.runtime-a", version="1")
    current = _fixture_binding("fixture.runtime-a", version="2")
    item = _item("fixture.runtime-a")
    session, mission = _plan(
        repo, head, item, RuntimeRoleRegistry((planned,))
    )
    run_dir = tmp_path / "run"

    with pytest.raises(SupervisorRefused, match="plan identity drift"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=run_dir,
            roles=dict((_fixture_harness(current),)),
            runtime_roles=RuntimeRoleRegistry((current,)),
        ).run(session, mission, (item,))

    assert not run_dir.exists()


def test_binding_is_data_only_and_requires_the_existing_harness_key(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _fixture_binding("fixture.runtime-a")
    assert not hasattr(binding, "runner_factory")
    assert not hasattr(binding, "gate_factory")

    item = _item(binding.runtime_id)
    registry = RuntimeRoleRegistry((binding,))
    session, mission = _plan(repo, head, item, registry)
    run_dir = tmp_path / "run"

    # A role-only harness is deliberately insufficient: an explicit runtime
    # must resolve through the full descriptor digest key.
    role_only = RoleHarness(
        role="coder",
        runner_factory=_runner_factory("must-not-run"),
        gate_factory=_gate_factory,
    )
    with pytest.raises(SupervisorRefused, match="exact injected RoleHarness"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=run_dir,
            roles={"coder": role_only},
            runtime_roles=registry,
        ).run(session, mission, (item,))
    assert not (run_dir / "spine.sqlite3").exists()


def test_session_and_mission_cannot_be_cross_paired(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding_a = _fixture_binding("fixture.runtime-a")
    binding_b = _fixture_binding("fixture.runtime-b")
    registry_a = RuntimeRoleRegistry((binding_a,))
    registry_b = RuntimeRoleRegistry((binding_b,))
    item_a = _item("fixture.runtime-a")
    item_b = _item("fixture.runtime-b")
    session_a, _mission_a = _plan(repo, head, item_a, registry_a)
    _session_b, mission_b = _plan(repo, head, item_b, registry_b)
    run_dir = tmp_path / "run"

    with pytest.raises(SupervisorRefused, match="session/mission drift"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=run_dir,
            roles=dict((_fixture_harness(binding_a),)),
            runtime_roles=registry_a,
        ).run(session_a, mission_b, (item_a,))

    assert not run_dir.exists()


def test_work_item_ids_cannot_be_swapped_between_ordinals(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding_a = _fixture_binding("fixture.runtime-a")
    binding_b = _fixture_binding("fixture.runtime-b")
    registry = RuntimeRoleRegistry((binding_a, binding_b))
    items = (_item(binding_a.runtime_id), _item(binding_b.runtime_id))
    session, mission = plan_mission(
        "ordinal identity swap probe",
        repo_root=repo,
        items=items,
        base_revision=head,
        budget=ResourceBudget(max_wall_time_s=300),
        success_criteria=("both fixture patches are gated",),
        runtime_roles=registry,
    )
    first, second = session.waves[0].tasks
    assert first.work_item_id != second.work_item_id
    first.work_item_id, second.work_item_id = (
        second.work_item_id,
        first.work_item_id,
    )
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=tmp_path / "run",
        roles=dict(
            (_fixture_harness(binding_a), _fixture_harness(binding_b))
        ),
        runtime_roles=registry,
    )

    with pytest.raises(SupervisorRefused, match="work item identity drift"):
        supervisor.run(session, mission, items)

    assert supervisor.results == []
    assert not (tmp_path / "run").exists()


def test_item_substance_cannot_change_after_planning(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _fixture_binding("fixture.runtime-a")
    registry = RuntimeRoleRegistry((binding,))
    planned_item = _item(binding.runtime_id)
    changed_item = PlannedItem(
        objective="a different instruction under the old work item",
        role=planned_item.role,
        paths=planned_item.paths,
        runtime_id=planned_item.runtime_id,
    )
    session, mission = _plan(repo, head, planned_item, registry)
    run_dir = tmp_path / "run"

    with pytest.raises(SupervisorRefused, match="plan identity drift"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=run_dir,
            roles=dict((_fixture_harness(binding),)),
            runtime_roles=registry,
        ).run(session, mission, (changed_item,))

    assert not run_dir.exists()


def test_preflight_snapshot_survives_binding_mutation_between_items(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding_a = _fixture_binding("fixture.runtime-a", version="1")
    binding_b = _fixture_binding("fixture.runtime-b", version="1")
    original_b_digest = binding_b.digest
    seen_b: list[dict] = []
    observed_b: list[dict] = []

    def mutating_factory(item):
        base = _runner_factory("runtime-a")(item)

        def runner(ctx):
            object.__setattr__(binding_b, "adapter_version", "MUTATED")
            session.waves[0].tasks[1].work_item_id = "injected-after-preflight"
            object.__setattr__(
                harness_b,
                "runner_factory",
                _runner_factory("substituted-after-preflight"),
            )
            supervisor.gate_timeout_s = 9999
            supervisor.repo_root = tmp_path / "other-repository"
            supervisor.run_dir = tmp_path / "other-run"
            return base(ctx)

        return runner

    harness_a = RoleHarness(
        role="coder",
        runner_factory=mutating_factory,
        gate_factory=_gate_factory,
    )
    def observed_b_factory(item):
        base = _runner_factory("runtime-b", seen_b)(item)

        def runner(ctx):
            observed_b.append(
                {
                    "task_id": ctx.task.task_id,
                    "timeout": ctx.task.gate_timeout_s,
                    "worktree": str(ctx.worktree),
                }
            )
            return base(ctx)

        return runner

    harness_b = RoleHarness(
        role="coder",
        runner_factory=observed_b_factory,
        gate_factory=_gate_factory,
    )
    registry = RuntimeRoleRegistry((binding_a, binding_b))
    items = (_item(binding_a.runtime_id), _item(binding_b.runtime_id))
    session, mission = plan_mission(
        "two-item runtime snapshot probe",
        repo_root=repo,
        items=items,
        base_revision=head,
        budget=ResourceBudget(max_wall_time_s=300),
        success_criteria=("both fixture patches are gated",),
        runtime_roles=registry,
    )
    roles = {
        binding_a.harness_key: harness_a,
        binding_b.harness_key: harness_b,
    }
    original_run_dir = tmp_path / "run"
    original_second_id = session.waves[0].tasks[1].work_item_id
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=original_run_dir,
        roles=roles,
        runtime_roles=registry,
        gate_timeout_s=60,
    )

    final = supervisor.run(session, mission, items)

    assert final["outcome"] == "landed"
    assert binding_b.digest != original_b_digest  # adversarial mutation happened
    assert len(seen_b) == 1
    assert seen_b[0]["runtime_binding_sha256"] == original_b_digest
    assert seen_b[0]["runtime_adapter_version"] == "1"
    assert final["items"][1]["runtime_binding_sha256"] == original_b_digest
    assert final["items"][1]["work_item_id"] == original_second_id
    assert len(observed_b) == 1
    assert observed_b == [
        {
            "task_id": original_second_id,
            "timeout": 60.0,
            "worktree": observed_b[0]["worktree"],
        }
    ]
    assert Path(observed_b[0]["worktree"]).is_relative_to(tmp_path / "worktrees")
    assert supervisor.results[1].contract_set().attempt.task_id == original_second_id
    assert (original_run_dir / "spine.sqlite3").exists()
    assert not (tmp_path / "other-run").exists()


def test_mission_snapshot_survives_effectful_role_lookup(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _fixture_binding("fixture.runtime-a")
    registry = RuntimeRoleRegistry((binding,))
    item = _item(binding.runtime_id)
    session, mission = _plan(repo, head, item, registry)
    original_body = mission.to_dict()
    original_digest = mission.digest
    original_objective = mission.objective
    run_dir = tmp_path / "run"

    class MutatingRoles(dict):
        mutated = False

        def get(self, key, default=None):
            if not self.mutated:
                object.__setattr__(mission, "objective", "MUTATED BY LOOKUP")
                object.__setattr__(mission, "source_revision", "f" * 40)
                self.mutated = True
            return super().get(key, default)

    roles = MutatingRoles(dict((_fixture_harness(binding),)))
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=run_dir,
        roles=roles,
        runtime_roles=registry,
    )

    final = supervisor.run(session, mission, (item,))

    assert roles.mutated is True
    assert final["outcome"] == "landed"
    assert final["mission_sha256"] == original_digest
    assert final["objective"] == original_objective
    assert final["source_revision"] == head
    retained_body = json.loads((run_dir / "mission.json").read_text(encoding="utf-8"))
    assert retained_body == original_body
    assert MissionContract.from_dict(retained_body).digest == original_digest
    assert supervisor.results[0].contract_set().attempt.base_revision == head


def test_runner_cannot_forge_terminal_ledger_status(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _fixture_binding("fixture.runtime-a")
    registry = RuntimeRoleRegistry((binding,))
    item = _item(binding.runtime_id)
    session, mission = _plan(repo, head, item, registry)
    task = session.waves[0].tasks[0]

    def mutating_factory(planned_item):
        base_runner = _runner_factory("runtime-a")(planned_item)

        def runner(ctx):
            task.mark = lambda *_args, **_kwargs: setattr(
                task, "status", "dispatched"
            )
            task.status = "attacker-controlled"
            return base_runner(ctx)

        return runner

    harness = RoleHarness(
        role=binding.role,
        runner_factory=mutating_factory,
        gate_factory=_gate_factory,
    )
    final = MissionSupervisor(
        repo_root=repo,
        run_dir=tmp_path / "run",
        roles={binding.harness_key: harness},
        runtime_roles=registry,
    ).run(session, mission, (item,))

    assert final["outcome"] == "landed"
    assert final["items"][0]["status"] == "landed"
    assert final["items"][0]["attempt_receipt_sha256"]
    assert task.status == "landed"


def test_callbacks_cannot_mutate_authoritative_task_spec(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _fixture_binding("fixture.runtime-a")
    registry = RuntimeRoleRegistry((binding,))
    item = _item(binding.runtime_id)
    session, mission = _plan(repo, head, item, registry)
    observed: dict[str, str] = {}

    def mutate_task(task, phase):
        observed[f"{phase}_before"] = task.digest
        evil_metadata = dict(task.metadata)
        evil_metadata["runtime_binding_sha256"] = "0" * 64
        object.__setattr__(task, "metadata", MappingProxyType(evil_metadata))
        observed[f"{phase}_after"] = task.digest

    def runner_factory(planned_item):
        base_runner = _runner_factory("runtime-a")(planned_item)

        def runner(ctx):
            mutate_task(ctx.task, "runner")
            return base_runner(ctx)

        return runner

    def gate_factory(_planned_item):
        def gate(ctx):
            mutate_task(ctx.task, "gate")
            return GateResult(passed=True, name="isolated-task-spec", command=())

        return gate

    harness = RoleHarness(
        role=binding.role,
        runner_factory=runner_factory,
        gate_factory=gate_factory,
    )
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=tmp_path / "run",
        roles={binding.harness_key: harness},
        runtime_roles=registry,
    )

    final = supervisor.run(session, mission, (item,))
    attempt = supervisor.results[0].contract_set().attempt

    assert final["outcome"] == "landed"
    assert observed["runner_before"] == observed["gate_before"]
    assert observed["runner_before"] != observed["runner_after"]
    assert observed["gate_before"] != observed["gate_after"]
    assert attempt.task_sha256 == observed["runner_before"]
    assert final["items"][0]["runtime_binding_sha256"] == binding.digest


def test_stale_mission_contract_cannot_be_reused(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _fixture_binding("fixture.runtime-a")
    registry = RuntimeRoleRegistry((binding,))
    item = _item(binding.runtime_id)
    session, mission = _plan(repo, head, item, registry)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "mission.json").write_text(
        '{"stale":true}\n', encoding="utf-8"
    )

    with pytest.raises(SupervisorRefused, match="mission.json"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=run_dir,
            roles=dict((_fixture_harness(binding),)),
            runtime_roles=registry,
        ).run(session, mission, (item,))

    assert not (run_dir / "ledger").exists()
    assert not (run_dir / "spine.sqlite3").exists()


def test_factory_code_starts_only_inside_the_attempt_boundary(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _fixture_binding("fixture.runtime-a")
    registry = RuntimeRoleRegistry((binding,))
    item = _item(binding.runtime_id)
    session, mission = _plan(repo, head, item, registry)
    run_dir = tmp_path / "run"
    marker = tmp_path / "factory-effect.txt"
    observed_boundary: list[bool] = []

    def effectful_factory(_item):
        observed_boundary.append((run_dir / "spine.sqlite3").exists())
        marker.write_text("factory ran\n", encoding="utf-8")
        raise RuntimeError("factory fails after the attempt starts")

    harness = RoleHarness(
        role="coder",
        runner_factory=effectful_factory,
        gate_factory=_gate_factory,
    )
    assert not marker.exists()

    final = MissionSupervisor(
        repo_root=repo,
        run_dir=run_dir,
        roles={binding.harness_key: harness},
        runtime_roles=registry,
    ).run(session, mission, (item,))

    assert final["outcome"] == "bounced"
    assert marker.read_text(encoding="utf-8") == "factory ran\n"
    assert observed_boundary == [True]
    assert (run_dir / "spine.sqlite3").exists()


def test_escaping_path_is_a_refused_plan_not_a_dispatched_attempt(
    target_repo, tmp_path, monkeypatch
):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    binding = _fixture_binding("fixture.runtime-a")
    registry = RuntimeRoleRegistry((binding,))
    item = PlannedItem(
        objective="try an invalid escaping target",
        role="coder",
        paths=("../escape.txt",),
        runtime_id=binding.runtime_id,
    )
    session, mission = _plan(repo, head, item, registry)
    run_dir = tmp_path / "run"

    with pytest.raises(SupervisorRefused, match="task declaration refused"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=run_dir,
            roles=dict((_fixture_harness(binding),)),
            runtime_roles=registry,
        ).run(session, mission, (item,))

    assert not (run_dir / "spine.sqlite3").exists()
    assert not (run_dir / "artifacts").exists()
    final = verify_state_ledger(run_dir / "ledger")[-1]
    assert final["outcome"] == "refused"
    assert final["items"][0]["status"] == "refused"
    assert "root-escaping" in final["items"][0]["detail"]


def test_registry_copies_descriptor_primitives_at_construction():
    binding = _fixture_binding("fixture.runtime-a", version="1")
    original_digest = binding.digest
    registry = RuntimeRoleRegistry((binding,))
    public_snapshot = registry.bindings[0]

    object.__setattr__(binding, "role", "other-role")
    object.__setattr__(binding, "runtime_id", "fixture.mutated")
    object.__setattr__(binding, "adapter_version", "MUTATED")
    object.__setattr__(public_snapshot, "adapter_version", "ALSO-MUTATED")

    retained = registry.snapshot("coder", "fixture.runtime-a")
    assert retained is not None
    assert retained.role == "coder"
    assert retained.runtime_id == "fixture.runtime-a"
    assert retained.adapter_version == "1"
    assert retained.digest == original_digest
    assert registry.snapshot("other-role", "fixture.mutated") is None


def test_registry_refuses_tampered_private_record_digest():
    binding = _fixture_binding("fixture.runtime-a", version="1")
    registry = RuntimeRoleRegistry((binding,))
    key = (binding.role, binding.runtime_id)
    tampered_record = list(registry._by_key[key])
    tampered_record[4] = "MUTATED"
    object.__setattr__(
        registry,
        "_by_key",
        MappingProxyType({key: tuple(tampered_record)}),
    )

    with pytest.raises(RuntimeRoleRegistryError, match="digest"):
        registry.snapshot(*key)


def test_fake_or_stateful_runtime_registry_is_rejected(target_repo):
    repo, head = target_repo
    item = _item("fixture.runtime-a")
    binding = _fixture_binding(item.runtime_id)

    class StatefulRegistry:
        def __init__(self):
            self.calls = 0

        def snapshot(self, _role, _runtime_id):
            self.calls += 1
            return RuntimeRoleRegistry((binding,)).snapshot(
                binding.role, binding.runtime_id
            )

    fake = StatefulRegistry()
    with pytest.raises(SupervisorRefused, match="exact immutable"):
        _plan(repo, head, item, fake)  # type: ignore[arg-type]
    assert fake.calls == 0


@pytest.mark.parametrize("timeout", (float("nan"), float("inf"), 0.0))
def test_invalid_supervisor_timeout_refuses_before_state(
    timeout, target_repo, tmp_path
):
    repo, head = target_repo
    binding = _fixture_binding("fixture.runtime-a")
    registry = RuntimeRoleRegistry((binding,))
    item = _item(binding.runtime_id)
    session, mission = _plan(repo, head, item, registry)
    run_dir = tmp_path / "run"

    with pytest.raises(SupervisorRefused, match="positive and finite"):
        MissionSupervisor(
            repo_root=repo,
            run_dir=run_dir,
            roles=dict((_fixture_harness(binding),)),
            runtime_roles=registry,
            gate_timeout_s=timeout,
        ).run(session, mission, (item,))

    assert not run_dir.exists()


def test_port_has_no_provider_import_process_spawn_or_vendor_branch():
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "daedalus" / "ikarus_runtime_role.py",
        root / "daedalus" / "ikarus_supervisor.py",
    )
    vendor_tokens = {"claude", "codex", "hermes"}
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not any("providers" in name for name in imported)
        assert not any("subprocess" in name for name in imported)
        assert not any("adapters" in name for name in imported)

        # Provider names may appear in provenance prose, never as dispatch
        # predicates. This detects the forbidden if runtime == vendor shape.
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            literals = {
                value.value.lower()
                for value in ast.walk(node.test)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            }
            assert not any(
                token in literal for token in vendor_tokens for literal in literals
            )

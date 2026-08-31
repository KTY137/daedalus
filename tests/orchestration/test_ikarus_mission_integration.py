"""G1-IKARUS-15: canonical wave execution with disposable projections."""
from __future__ import annotations

import ast
import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

import daedalus.orchestration.missions.service as mission_service
from daedalus.build import BuildSession, BuildTask, Wave
from daedalus.build_exec import BuildRunReport, EffectBounds, WaveExecutor, WaveResult
from daedalus.ikarus_effect_bridge import (
    IkarusEffectBridgeRefused,
    build_oneshot_effect_execution_request,
    build_oneshot_effect_lease_request,
)
from daedalus.ikarus_oneshot import OneShotRuntimeRefused
from daedalus.ikarus_supervisor import (
    MissionSupervisor,
    SupervisorRefused,
    verify_state_ledger,
)
from daedalus.limit_policy import ExecutionLimitPolicy
from daedalus.orchestration.missions.service import run_mission
from daedalus.orchestration.missions.supervisor_projection import (
    begin_supervisor_projection,
    finish_supervisor_projection,
)
from daedalus.spine.effect_boundary import Effect


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "daedalus/orchestration/missions/service.py"
PROJECTION = ROOT / "daedalus/orchestration/missions/supervisor_projection.py"
ONE_SHOT = ROOT / "daedalus/orchestration/missions/one_shot.py"
EFFECT_FIXTURE = ROOT / "tests/test_ikarus_effect_bridge.py"
REVISION = "a" * 40


def _session(repo_root: Path) -> BuildSession:
    return BuildSession(
        feature="execute one admitted documentation task",
        repo_root=str(repo_root),
        project=None,
        waves=[
            Wave(
                index=0,
                tasks=[
                    BuildTask(
                        objective="inspect docs/a.md",
                        agent="docs-dev",
                        category="docs",
                        lane="local_only",
                        tier="none",
                        builder="ollama",
                        frontier=False,
                        paths=["docs/a.md"],
                    )
                ],
            )
        ],
        slug="ikarus-15-probe",
        created="",
        max_workers=1,
        mission_id="mission-ikarus-15-probe",
    )


def _executor(session: BuildSession) -> WaveExecutor:
    return WaveExecutor(
        effect_bounds=EffectBounds(
            mission_id=session.mission_id,
            source_revision=REVISION,
            max_spend_usd=0.10,
            timeout_s=60,
            limit_policy=ExecutionLimitPolicy(),
            trace_id=session.mission_id,
        )
    )


def _landed_report(session: BuildSession) -> BuildRunReport:
    task = session.tasks()[0]
    row = {"status": "offloaded", "result": {"note": "fixture completed"}}
    task.mark("landed", row)
    return BuildRunReport(
        feature=session.feature,
        slug=session.slug,
        repo_root=session.repo_root,
        dry_run=False,
        mission_id=session.mission_id,
        waves=[
            WaveResult(
                index=0,
                mode="sequential",
                dry_run=False,
                write_tasks=0,
                advisory_tasks=1,
                landed_tasks=1,
                bounced_tasks=0,
                forced_sequential_reason=None,
                path_conflicts=[],
                results=[row],
                spend_envelope={"cap_usd": 0.1, "spent_usd": 0.0},
                mission_id=session.mission_id,
            )
        ],
    )


def _execute_once(
    executor: WaveExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> list[BuildSession]:
    calls: list[BuildSession] = []

    def execute(session: BuildSession, **_kwargs: object) -> BuildRunReport:
        calls.append(session)
        return _landed_report(session)

    monkeypatch.setattr(executor, "run", execute)
    return calls


def _load_effect_fixture():
    name = "daedalus_test_ikarus_15_effect_fixture"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EFFECT_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _one_shot_bundle(
    session: BuildSession,
    tmp_path: Path,
    *,
    entrypoint_id: str = "provider.hermes-oneshot",
):
    fixture = _load_effect_fixture()
    request, evidence, tools = fixture._subjects(tmp_path)
    effect_request = build_oneshot_effect_lease_request(
        request,
        evidence,
        tools,
        request_id="ikarus-15-effect-request",
        mission_id=session.mission_id,
        attempt_id=session.work_item_ids()[0],
        entrypoint_id=entrypoint_id,
        idempotency_namespace="ikarus-15-effect-namespace",
        kill_switch_ref="tests.ikarus-15-kill-switch",
        kill_switch_generation=1,
        requested_effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        created_at=fixture.fixture.NOW,
        writable_paths=("workspace/out.txt",),
        egress_endpoints=("https://api.example.test/v1",),
        secret_refs=("provider-key",),
    )
    execution = build_oneshot_effect_execution_request(
        request,
        evidence,
        tools,
        effect_request,
        execution_id="ikarus-15-execution",
        idempotency_key="ikarus-15-execution-key",
    )
    return request, evidence, tools, effect_request, execution


def test_run_mission_executes_one_wave_and_projects_before_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    executor = _executor(session)
    calls = _execute_once(executor, monkeypatch)
    supervisor = MissionSupervisor(
        repo_root=tmp_path,
        run_dir=tmp_path / "projection",
        roles={},
    )

    mission, report = run_mission(
        session,
        source_revision=REVISION,
        executor=executor,
        dry_run=False,
        resume=False,
        update_architecture=False,
        persist_session=False,
        supervisor=supervisor,
    )

    assert calls == [session]
    assert report.mission_id == mission.mission_id == session.mission_id
    assert supervisor.results == []
    assert supervisor.projection_errors == []
    revisions = verify_state_ledger(supervisor.run_dir / "ledger")
    assert [revision["outcome"] for revision in revisions] == [None, "landed"]
    assert revisions[-1]["items"][0]["status"] == "landed"
    assert revisions[-1]["items"][0]["attempt_id"] is None


def test_supervisor_projection_replay_is_idempotent_and_never_runs_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    executor = _executor(session)
    calls = _execute_once(executor, monkeypatch)
    run_dir = tmp_path / "projection"
    supervisor = MissionSupervisor(repo_root=tmp_path, run_dir=run_dir, roles={})
    mission, report = run_mission(
        session,
        source_revision=REVISION,
        executor=executor,
        dry_run=False,
        supervisor=supervisor,
    )
    before = verify_state_ledger(run_dir / "ledger")

    restarted = MissionSupervisor(repo_root=tmp_path, run_dir=run_dir, roles={})
    replayed_mission = dataclasses.replace(
        mission,
        provenance=dataclasses.replace(
            mission.provenance,
            created_at="2026-08-31T23:59:59+00:00",
        ),
    )
    assert replayed_mission.digest != mission.digest
    begin_supervisor_projection(restarted, session, replayed_mission)
    finish_supervisor_projection(restarted, session, replayed_mission, report)
    after = verify_state_ledger(run_dir / "ledger")

    assert calls == [session]
    assert len(after) == len(before) == 2
    assert after[-1]["revision_sha256"] == before[-1]["revision_sha256"]
    assert restarted.results == []

    changed_contract = dataclasses.replace(
        replayed_mission,
        success_criteria=("a different acceptance claim",),
    )
    with pytest.raises(SupervisorRefused, match="another mission"):
        begin_supervisor_projection(restarted, session, changed_contract)
    assert len(verify_state_ledger(run_dir / "ledger")) == 2


def test_projection_failure_after_execution_cannot_replace_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    executor = _executor(session)
    calls = _execute_once(executor, monkeypatch)
    supervisor = MissionSupervisor(
        repo_root=tmp_path,
        run_dir=tmp_path / "projection",
        roles={},
    )
    monkeypatch.setattr(
        mission_service,
        "finish_supervisor_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("projection disk unavailable")
        ),
    )

    mission, report = run_mission(
        session,
        source_revision=REVISION,
        executor=executor,
        dry_run=False,
        supervisor=supervisor,
    )

    assert calls == [session]
    assert report.mission_id == mission.mission_id
    assert supervisor.projection_errors == [
        "after execution: OSError: projection disk unavailable"
    ]


def test_hermes_one_shot_is_exactly_validated_then_refused_before_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    executor = _executor(session)
    monkeypatch.setattr(
        executor,
        "run",
        lambda *_args, **_kwargs: pytest.fail("refused one-shot reached WaveExecutor"),
    )
    bundle = _one_shot_bundle(session, tmp_path)

    with pytest.raises(OneShotRuntimeRefused, match="not registered"):
        run_mission(
            session,
            source_revision=REVISION,
            executor=executor,
            dry_run=False,
            one_shot_effects={session.work_item_ids()[0]: bundle},
        )


@pytest.mark.parametrize(
    "entrypoint_id",
    ("provider.codex", "provider.ollama_native"),
)
def test_inventory_only_runtimes_stay_refused_before_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint_id: str,
) -> None:
    session = _session(tmp_path)
    executor = _executor(session)
    monkeypatch.setattr(
        executor,
        "run",
        lambda *_args, **_kwargs: pytest.fail("inventory-only row reached WaveExecutor"),
    )
    bundle = _one_shot_bundle(session, tmp_path, entrypoint_id=entrypoint_id)

    with pytest.raises(OneShotRuntimeRefused, match="inventory_only, not central"):
        run_mission(
            session,
            source_revision=REVISION,
            executor=executor,
            dry_run=False,
            one_shot_effects={session.work_item_ids()[0]: bundle},
        )


def test_tampered_one_shot_subject_refuses_before_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    executor = _executor(session)
    monkeypatch.setattr(
        executor,
        "run",
        lambda *_args, **_kwargs: pytest.fail("tampered one-shot reached WaveExecutor"),
    )
    request, evidence, tools, effect_request, execution = _one_shot_bundle(
        session, tmp_path
    )
    tampered = dataclasses.replace(execution, tools=())

    with pytest.raises(
        IkarusEffectBridgeRefused,
        match="exact narrowed one-shot projection",
    ):
        run_mission(
            session,
            source_revision=REVISION,
            executor=executor,
            dry_run=False,
            one_shot_effects={
                session.work_item_ids()[0]: (
                    request,
                    evidence,
                    tools,
                    effect_request,
                    tampered,
                )
            },
        )


def test_composition_defines_no_second_scheduler_attempt_or_provider_call() -> None:
    service_tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    service = next(
        node
        for node in ast.walk(service_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "run_mission"
    )
    run_calls = [
        node
        for node in ast.walk(service)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
    ]
    supervisor_run_calls = [
        node
        for node in ast.walk(service)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "supervisor"
        and node.func.attr == "run"
    ]
    assert len(run_calls) == 1
    assert supervisor_run_calls == []

    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in (SERVICE, PROJECTION, ONE_SHOT)
    )
    assert "TaskAttempt(" not in combined
    assert "broker." not in combined
    assert "provider.call" not in combined

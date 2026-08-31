from __future__ import annotations

import ast
from pathlib import Path

import pytest

import daedalus.orchestration as orchestration
import daedalus.orchestration.missions as missions
import daedalus.orchestration.missions.service as mission_service
from daedalus.build import BuildSession, BuildTask, Wave, WorkItemIdentityError
from daedalus.build_exec import BuildRunReport, EffectBounds, WaveExecutor
from daedalus.limit_policy import ExecutionLimitPolicy
from daedalus.orchestration.missions.service import run_mission
from daedalus.schemas import MissionContract


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "daedalus" / "orchestration" / "missions" / "service.py"
CORE = ROOT / "daedalus" / "core.py"
CLI = ROOT / "daedalus" / "cli.py"
BUILD_EXEC = ROOT / "daedalus" / "build_exec.py"
WEB = ROOT / "daedalus" / "web_api.py"
FILE_BRIDGE = ROOT / "daedalus" / "file_bridge.py"

REVISION = "a" * 40
CREATED_AT = "2026-08-31T12:00:00+00:00"


def _session(repo_root: Path) -> BuildSession:
    task = BuildTask(
        objective="inspect docs/a.md",
        agent="docs-dev",
        category="docs",
        lane="local_only",
        tier="none",
        builder="ollama",
        frontier=False,
        paths=["docs/a.md"],
    )
    return BuildSession(
        feature="inspect one document",
        repo_root=str(repo_root),
        project=None,
        waves=[Wave(index=0, tasks=[task])],
        slug="orchestration-probe",
        created="",
        max_workers=1,
        mission_id="mission-orchestration-probe",
    )


def _executor(session: BuildSession) -> WaveExecutor:
    return WaveExecutor(
        effect_bounds=EffectBounds(
            mission_id=session.mission_id,
            source_revision=REVISION,
            max_spend_usd=0.25,
            timeout_s=90,
            limit_policy=ExecutionLimitPolicy(),
            trace_id="trace-orchestration-probe",
        )
    )


def _report(session: BuildSession, *, dry_run: bool) -> BuildRunReport:
    return BuildRunReport(
        feature=session.feature,
        slug=session.slug,
        repo_root=session.repo_root,
        dry_run=dry_run,
        mission_id=session.mission_id,
    )


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(path: Path, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _name_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == name
    ]


def _attribute_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == name
    ]


def test_public_imports_are_the_same_run_mission_object() -> None:
    assert orchestration.run_mission is missions.run_mission is run_mission


def test_service_builds_the_canonical_mission_and_delegates_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(tmp_path)
    executor = _executor(session)
    observed: dict[str, object] = {}

    def execute(bound_session: BuildSession, **kwargs: object) -> BuildRunReport:
        observed["session"] = bound_session
        observed["kwargs"] = kwargs
        return _report(bound_session, dry_run=bool(kwargs["dry_run"]))

    monkeypatch.setattr(executor, "run", execute)
    monkeypatch.setattr(mission_service, "_created_at", lambda: CREATED_AT)
    mission, report = run_mission(
        session,
        source_revision=REVISION,
        executor=executor,
        dry_run=False,
        resume=False,
        update_architecture=False,
        persist_session=False,
    )

    assert type(mission) is MissionContract
    assert mission.mission_id == session.mission_id == report.mission_id
    assert set(mission.work_item_ids) == set(session.work_item_ids())
    assert mission.budget.max_cost_microusd == 250_000
    assert mission.budget.max_wall_time_s == 90
    assert mission.execution_limit_policy == executor.limit_policy
    assert mission.provenance.trace_id == "trace-orchestration-probe"
    assert observed["session"] is session
    assert observed["kwargs"] == {
        "repo_root": None,
        "dry_run": False,
        "parallel_advisory": True,
        "resume": False,
        "stop_on_bounce": False,
        "checkpoint_every_wave": False,
        "runs_dir": None,
        "update_architecture": False,
        "persist_session": False,
    }


def test_plan_drift_refuses_before_executor_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(tmp_path)
    executor = _executor(session)
    session.tasks()[0].objective = "changed after WorkItem identity settled"
    monkeypatch.setattr(
        executor,
        "run",
        lambda *_args, **_kwargs: pytest.fail("plan drift reached executor.run"),
    )

    with pytest.raises(WorkItemIdentityError, match="plan changed"):
        run_mission(session, source_revision=REVISION, executor=executor)


def test_effect_binding_drift_refuses_before_executor_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(tmp_path)
    executor = WaveExecutor(
        effect_bounds=EffectBounds(
            mission_id="mission-another-run",
            source_revision=REVISION,
            limit_policy=ExecutionLimitPolicy(),
        )
    )
    monkeypatch.setattr(
        executor,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "mismatched EffectBounds reached executor.run"
        ),
    )

    with pytest.raises(ValueError, match="mission_id"):
        run_mission(session, source_revision=REVISION, executor=executor)


def test_service_defines_no_parallel_contract_scheduler_or_store() -> None:
    tree = _tree(SERVICE)
    assert [node.name for node in tree.body if isinstance(node, ast.ClassDef)] == []
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "MissionContract" in imported_names
    assert "BuildRunReport" in imported_names
    assert "WaveExecutor" in imported_names
    assert not {
        "KairosScheduler",
        "TaskAttempt",
        "AttemptContract",
        "EvidencePacket",
        "EffectLease",
        "StateLedger",
        "EventStore",
    } & imported_names

    service = _function(SERVICE, "run_mission")
    assert len(_attribute_calls(service, "run")) == 1
    assert _attribute_calls(service, "run_wave") == []
    assert _attribute_calls(service, "dispatch") == []
    assert _attribute_calls(service, "spawn") == []


def test_migrated_surfaces_delegate_without_a_second_execution_path() -> None:
    core = _function(CORE, "_try_ikarus")
    assert len(_name_calls(core, "run_mission")) == 1
    assert _attribute_calls(core, "run_wave") == []
    assert _attribute_calls(core, "dispatch") == []

    build_cli = _function(BUILD_EXEC, "main")
    assert len(_name_calls(build_cli, "run_mission")) == 1
    assert _attribute_calls(build_cli, "run") == []
    assert _attribute_calls(build_cli, "run_wave") == []

    spawn_cli = _function(CLI, "_spawn")
    assert len(_name_calls(spawn_cli, "run_mission")) == 1
    spawn_calls = _attribute_calls(spawn_cli, "spawn")
    assert len(spawn_calls) == 1
    dry_run = next(
        keyword.value
        for keyword in spawn_calls[0].keywords
        if keyword.arg == "dry_run"
    )
    assert isinstance(dry_run, ast.Constant) and dry_run.value is True
    assert _attribute_calls(spawn_cli, "dispatch") == []
    assert _attribute_calls(spawn_cli, "run_wave") == []

    web_post = _function(WEB, "_handle_post")
    assert len(_attribute_calls(web_post, "queue_task")) == 1
    bridge = _function(FILE_BRIDGE, "_process_request_claimed")
    assert len(_name_calls(bridge, "process_bridge_payload")) == 1
    for surface in (web_post, bridge):
        assert _attribute_calls(surface, "dispatch") == []
        assert _attribute_calls(surface, "run_wave") == []
        assert _attribute_calls(surface, "spawn") == []

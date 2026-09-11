from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest

from daedalus import budget
from daedalus.council.vendors import CodexAdapter, RunResult
from daedalus.orchestration.langgraph_adapter import LangGraphUnavailable
from daedalus.spine.killswitch import LoopHalted
from experiments.opus_fleet_watchdog import core


class PassSwitch:
    def __init__(self) -> None:
        self.checkpoints = 0

    def checkpoint(self) -> None:
        self.checkpoints += 1

    @contextmanager
    def watch(self):
        yield self


class StopSwitch(PassSwitch):
    def checkpoint(self) -> None:
        self.checkpoints += 1
        raise LoopHalted("test stop")


def no_budget(*_args, **_kwargs):
    return nullcontext()


def idle_sessions():
    return {"ok": True, "active_sessions": 0, "sources": ["test"], "reason": ""}


def _config(
    tmp_path: Path,
    *,
    campaign_id: str = "campaign-a",
    max_agents: int = 3,
    max_parallel: int = 2,
    context_paths: list[str] | None = None,
    max_spend_usd: float = 100.0,
) -> Path:
    payload = {
        "campaign_id": campaign_id,
        "live": True,
        "projects": [
            {
                "project": "demo",
                "objective": "Review tensor integration",
                "context_paths": context_paths or ["selected.txt"],
                "enabled": True,
            }
        ],
        "roles": ["math", "integration", "tests"],
        "max_agents": max_agents,
        "max_parallel": max_parallel,
        "timeout_s": 5,
        "token_ceiling": 10_000,
        "max_calls": max_agents + 1,
        "max_spend_usd": max_spend_usd,
        "codex_model": "codex-test-model",
        "max_evidence_bytes": 100_000,
    }
    path = tmp_path / f"{campaign_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _planner(projects, roles, *, capacity):
    assert projects == [{"name": "demo", "objective": "Review tensor integration"}]
    return {
        "slots": [
            {
                "ordinal": index + 1,
                "slot_id": f"slot-{index + 1:02d}",
                "project": "demo",
                "objective": "Review tensor integration",
                "role": roles[index % len(roles)],
                "probe": index == 0,
            }
            for index in range(capacity)
        ]
    }


@pytest.fixture
def registered_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "selected.txt").write_text("SELECTED-CONTEXT", encoding="utf-8")
    (repo / "not-selected.txt").write_text("MUST-NOT-LEAVE", encoding="utf-8")
    monkeypatch.setattr(core, "list_projects", lambda: ["demo"])
    monkeypatch.setattr(
        core,
        "resolve_repo_root",
        lambda *, project=None, repo_root=None: str(repo),
    )
    return repo


def _success_factory(events: list | None = None, runner_hook=None):
    def runner(argv, **kwargs):
        provider = "claude" if "claude" in Path(argv[0]).name.lower() else "codex"
        if events is not None:
            events.append(("start", provider, kwargs["stdin_text"]))
        if runner_hook is not None:
            runner_hook(provider, "start")
        if provider == "claude":
            stdout = json.dumps(
                {
                    "is_error": False,
                    "result": "CLAIM: selected evidence was reviewed\nCHECK: python -m pytest -q",
                }
            )
        else:
            stdout = "CLAIM: fallback evidence was reviewed\nCHECK: python -m pytest -q"
        if runner_hook is not None:
            runner_hook(provider, "end")
        if events is not None:
            events.append(("end", provider, ""))
        return RunResult(returncode=0, stdout=stdout)

    def factory(provider, config, repo_root):
        if provider == "claude":
            return core.StructuredClaudeAdapter(
                model="opus",
                repo_root=repo_root,
                max_prompt_tokens=config.token_ceiling,
                runner=runner,
            )
        return CodexAdapter(
            model=config.codex_model,
            repo_root=repo_root,
            max_prompt_tokens=config.token_ceiling,
            runner=runner,
        )

    return factory


def _run(config: Path, tmp_path: Path, **kwargs):
    return core.run_campaign(
        config,
        planner=_planner,
        runs_root=tmp_path / "runs",
        budget_guard_factory=no_budget,
        kill_switch=kwargs.pop("kill_switch", PassSwitch()),
        session_probe=kwargs.pop("session_probe", idle_sessions),
        **kwargs,
    )


def test_real_langgraph_plan_is_global_and_fair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    roots = {}
    for name in ("alpha", "beta"):
        root = tmp_path / name
        root.mkdir()
        (root / "context.txt").write_text(name, encoding="utf-8")
        roots[name] = root
    monkeypatch.setattr(core, "list_projects", lambda: ["alpha", "beta"])
    monkeypatch.setattr(
        core,
        "resolve_repo_root",
        lambda *, project=None, repo_root=None: str(roots[project]),
    )
    payload = {
        "campaign_id": "fair",
        "live": True,
        "projects": [
            {
                "project": name,
                "objective": f"review {name}",
                "context_paths": ["context.txt"],
            }
            for name in ("alpha", "beta")
        ],
        "roles": ["r1", "r2"],
        "max_agents": 4,
        "max_parallel": 2,
        "timeout_s": 5,
        "token_ceiling": 1000,
        "max_calls": 5,
        "max_spend_usd": 20,
        "codex_model": "codex-test",
    }
    config = tmp_path / "fair.json"
    config.write_text(json.dumps(payload), encoding="utf-8")

    try:
        plan = core.dry_plan(config, runs_root=tmp_path / "runs")
    except LangGraphUnavailable:
        pytest.skip("optional orchestration dependency is not installed")

    assert plan["global_slots"] == 4
    assert [slot["project"] for slot in plan["slots"]] == [
        "alpha",
        "beta",
        "alpha",
        "beta",
    ]
    assert [slot["probe"] for slot in plan["slots"]] == [True, False, False, False]
    assert not (tmp_path / "runs").exists(), "dry_plan must not write"


@pytest.mark.parametrize(
    "body,expected",
    [
        ('{"is_error":true,"api_error_status":429,"result":"x"}', "codex"),
        ('{"is_error":true,"api_error_status":503,"result":"x"}', "codex"),
        ('{"is_error":true,"api_error_status":529,"result":"x"}', "codex"),
        ('{"is_error":true,"api_error_status":401,"result":"x"}', None),
        ('{"is_error":true,"api_error_status":"429","result":"x"}', None),
        ('{"is_error":true,"result":"429 session limit"}', None),
        ('{"is_error":false,"api_error_status":429,"result":"x"}', None),
        ('{"is_error":true,"api_error_status":429,"api_error_status":503}', None),
        ("429 session limit", None),
        ('prefix {"is_error":true,"api_error_status":429}', None),
    ],
)
def test_fallback_classifier_uses_only_exact_structured_wrapper(body, expected):
    assert core.fallback_provider(core.parse_claude_json_wrapper(body)) == expected


@pytest.mark.parametrize("status", [429, 503, 529])
@pytest.mark.parametrize("returncode", [0, 1])
def test_typed_probe_error_uses_fresh_codex_councils(
    status: int, returncode: int, tmp_path: Path, registered_project: Path
):
    config = _config(
        tmp_path, campaign_id=f"fallback-{status}-rc{returncode}", max_agents=3
    )
    calls = []

    def runner(argv, **_kwargs):
        provider = "claude" if "claude" in Path(argv[0]).name.lower() else "codex"
        calls.append(provider)
        if provider == "claude":
            return RunResult(
                returncode=returncode,
                stdout=json.dumps(
                    {"is_error": True, "api_error_status": status, "result": "limited"}
                ),
            )
        return RunResult(
            returncode=0,
            stdout="CLAIM: codex reviewed evidence\nCHECK: python -m pytest -q",
        )

    def factory(provider, cfg, repo_root):
        if provider == "claude":
            return core.StructuredClaudeAdapter(
                model="opus", repo_root=repo_root, runner=runner
            )
        return CodexAdapter(model=cfg.codex_model, repo_root=repo_root, runner=runner)

    state = _run(config, tmp_path, adapter_factory=factory)

    assert state["provider_decision"] == "codex"
    assert state["status"] == "complete"
    assert calls[0] == "claude"
    assert calls.count("claude") == 1
    assert calls.count("codex") == 3
    assert state["calls_claimed"] == 4
    probe_attempts = state["slots"][0]["attempts"]
    assert [attempt["provider"] for attempt in probe_attempts] == ["claude", "codex"]
    assert probe_attempts[0]["api_error_status"] == status
    assert probe_attempts[0]["store_path"] != probe_attempts[1]["store_path"]
    for attempt in [a for slot in state["slots"] for a in slot["attempts"]]:
        assert Path(attempt["store_path"]).is_file()
        assert Path(attempt["store_path"]).parent.name == (
            f"mission-fallback-{status}-rc{returncode}"
        )


@pytest.mark.parametrize(
    "result",
    [
        RunResult(returncode=0, stdout="429 session limit"),
        RunResult(returncode=0, stdout='{"is_error":true,"result":"429"}'),
        RunResult(
            returncode=0,
            stdout='{"is_error":true,"api_error_status":"429","result":"x"}',
        ),
        RunResult(returncode=1, stderr="not authenticated; 429"),
        RunResult(
            returncode=1,
            stdout='{"is_error":true,"api_error_status":429}',
            stderr="not authenticated",
        ),
        RunResult(returncode=0, stdout='{"is_error":true,"api_error_status":401}'),
    ],
)
def test_untyped_timeout_auth_or_malformed_probe_never_uses_codex(
    result: RunResult, tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id=f"no-fallback-{abs(hash(repr(result)))}")
    calls = []

    def runner(argv, **_kwargs):
        provider = "claude" if "claude" in Path(argv[0]).name.lower() else "codex"
        calls.append(provider)
        return result

    def factory(provider, cfg, repo_root):
        if provider == "claude":
            return core.StructuredClaudeAdapter(model="opus", repo_root=repo_root, runner=runner)
        return CodexAdapter(model=cfg.codex_model, repo_root=repo_root, runner=runner)

    state = _run(config, tmp_path, adapter_factory=factory)

    assert calls == ["claude"]
    assert state["provider_decision"] == "stopped"
    assert state["calls_claimed"] == 1
    assert all(slot["status"] in {"failed", "suppressed"} for slot in state["slots"])


def test_probe_is_synchronous_then_parallelism_is_bounded(
    tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id="parallel", max_agents=6, max_parallel=2)
    events = []
    guard = threading.Lock()
    active = 0
    maximum = 0

    def hook(_provider, phase):
        nonlocal active, maximum
        with guard:
            if phase == "start":
                active += 1
                maximum = max(maximum, active)
            else:
                active -= 1
        if phase == "start":
            time.sleep(0.04)

    state = _run(
        config,
        tmp_path,
        adapter_factory=_success_factory(events, runner_hook=hook),
    )

    assert state["status"] == "complete"
    assert maximum <= 2
    assert events[0][0:2] == ("start", "claude")
    assert events[1][0:2] == ("end", "claude")
    assert sum(1 for event in events if event[0] == "start") == 6


def test_only_selected_context_reaches_adapter(
    tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id="selected-only", max_agents=1, max_parallel=1)
    events = []

    state = _run(config, tmp_path, adapter_factory=_success_factory(events))

    prompt = events[0][2]
    assert "SELECTED-CONTEXT" in prompt
    assert "MUST-NOT-LEAVE" not in prompt
    assert state["status"] == "complete"


def test_secret_floor_refuses_selected_dotenv_before_runner(
    tmp_path: Path, registered_project: Path
):
    (registered_project / ".env").write_text("API_KEY=sk-secret-value", encoding="utf-8")
    config = _config(
        tmp_path,
        campaign_id="secret-floor",
        max_agents=1,
        max_parallel=1,
        context_paths=[".env"],
    )
    events = []

    state = _run(config, tmp_path, adapter_factory=_success_factory(events))

    assert events == []
    assert state["provider_decision"] == "stopped"
    assert state["slots"][0]["status"] == "refused"
    assert state["slots"][0]["reason"] == "secret_floor"
    transcript = Path(state["slots"][0]["attempts"][0]["store_path"])
    assert transcript.is_file()
    assert "sk-secret-value" not in transcript.read_text(encoding="utf-8")


def test_context_paths_cannot_escape_registered_root(
    tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, context_paths=["../outside.txt"])

    with pytest.raises(core.ConfigError, match="relative"):
        core.load_config(config)


def test_config_rejects_more_than_twenty_agents_and_missing_fallback_call(
    tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path)
    data = json.loads(config.read_text(encoding="utf-8"))
    data["max_agents"] = 21
    data["max_calls"] = 21
    config.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(core.ConfigError, match="max_agents"):
        core.load_config(config)

    data["max_agents"] = 20
    data["max_calls"] = 20
    config.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(core.ConfigError, match="extra call"):
        core.load_config(config)


def test_twenty_slot_fallback_never_exceeds_twenty_one_calls(
    tmp_path: Path, registered_project: Path
):
    config = _config(
        tmp_path,
        campaign_id="twenty",
        max_agents=20,
        max_parallel=4,
    )
    calls = []

    def runner(argv, **_kwargs):
        provider = "claude" if "claude" in Path(argv[0]).name.lower() else "codex"
        calls.append(provider)
        if provider == "claude":
            return RunResult(
                returncode=0,
                stdout='{"is_error":true,"api_error_status":429,"result":"limited"}',
            )
        return RunResult(returncode=0, stdout="CLAIM: x\nCHECK: python -m pytest -q")

    def factory(provider, cfg, repo_root):
        if provider == "claude":
            return core.StructuredClaudeAdapter(model="opus", repo_root=repo_root, runner=runner)
        return CodexAdapter(model=cfg.codex_model, repo_root=repo_root, runner=runner)

    state = _run(config, tmp_path, adapter_factory=factory)

    assert state["status"] == "complete"
    assert state["calls_claimed"] == 21
    assert len(calls) == 21


def test_stale_in_flight_becomes_unknown_and_is_never_retried(
    tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id="crash", max_agents=3)

    def crash(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated process death")

    with pytest.raises(KeyboardInterrupt):
        _run(
            config,
            tmp_path,
            adapter_factory=_success_factory(),
            convene_fn=crash,
        )

    calls = []
    state = _run(
        config,
        tmp_path,
        adapter_factory=_success_factory(calls),
    )

    assert calls == []
    assert state["status"] == "degraded"
    assert state["slots"][0]["status"] == "unknown"
    assert state["slots"][0]["attempts"][0]["status"] == "unknown"
    assert all(slot["status"] == "suppressed" for slot in state["slots"][1:])


@pytest.mark.parametrize("outcome", ["claude_success", "codex_failure"])
def test_probe_result_and_provider_decision_are_one_atomic_write(
    outcome: str,
    tmp_path: Path,
    registered_project: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = _config(
        tmp_path,
        campaign_id=f"atomic-probe-{outcome}",
        max_agents=2,
        max_parallel=1,
    )
    calls = []

    def runner(argv, **_kwargs):
        provider = "claude" if "claude" in Path(argv[0]).name.lower() else "codex"
        calls.append(provider)
        if provider == "claude" and outcome == "codex_failure":
            return RunResult(
                returncode=1,
                stdout='{"is_error":true,"api_error_status":429}',
            )
        if provider == "codex":
            return RunResult(returncode=1, stderr="transport failed")
        return RunResult(
            returncode=0,
            stdout=json.dumps({"is_error": False, "result": "CLAIM: x\nCHECK: x"}),
        )

    def factory(provider, cfg, repo_root):
        if provider == "claude":
            return core.StructuredClaudeAdapter(
                model="opus", repo_root=repo_root, runner=runner
            )
        return CodexAdapter(
            model=cfg.codex_model, repo_root=repo_root, runner=runner
        )

    real_write = core.write_text_atomic

    def crash_on_probe_transition(path, text, **kwargs):
        payload = json.loads(text)
        probe = payload.get("slots", [{}])[0]
        is_target = (
            outcome == "claude_success"
            and probe.get("status") == "completed"
            and payload.get("provider_decision") == "claude"
        ) or (
            outcome == "codex_failure"
            and probe.get("status") == "failed"
            and payload.get("provider_decision") == "stopped"
            and payload.get("reason") == "codex_probe_failed"
        )
        if is_target:
            raise KeyboardInterrupt("crash at sole atomic probe-state replace")
        return real_write(path, text, **kwargs)

    monkeypatch.setattr(core, "write_text_atomic", crash_on_probe_transition)
    with pytest.raises(KeyboardInterrupt):
        _run(config, tmp_path, adapter_factory=factory)
    calls_before_resume = list(calls)

    monkeypatch.setattr(core, "write_text_atomic", real_write)
    resumed = _run(config, tmp_path, adapter_factory=factory)

    assert calls == calls_before_resume, "unknown probe outcome must never re-dispatch"
    assert resumed["status"] == "degraded"
    assert resumed["provider_decision"] == "stopped"
    assert resumed["slots"][0]["status"] == "unknown"
    assert all(slot["status"] == "suppressed" for slot in resumed["slots"][1:])


def test_terminal_campaign_is_one_shot(
    tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id="once", max_agents=2)
    events = []
    factory = _success_factory(events)

    first = _run(config, tmp_path, adapter_factory=factory)
    count = len(events)
    second = _run(config, tmp_path, adapter_factory=factory)

    assert first["status"] == second["status"] == "complete"
    assert len(events) == count


def test_active_session_waits_durably_then_idle_tick_runs(
    tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id="wait-active", max_agents=2)
    events = []
    factory = _success_factory(events)

    waiting = _run(
        config,
        tmp_path,
        adapter_factory=factory,
        session_probe=lambda: {
            "ok": True,
            "active_sessions": 2,
            "sources": ["claude-agents", "codex-process"],
            "reason": "",
        },
    )
    assert waiting["status"] == "waiting"
    assert waiting["calls_claimed"] == 0
    assert events == []
    assert waiting["session_checks"][-1]["active_sessions"] == 2
    assert waiting["evidence_frozen_at"] == ""
    assert all(slot["evidence_digest"] == "" for slot in waiting["slots"])

    (registered_project / "selected.txt").write_text(
        "CONTEXT-AFTER-ACTIVE-SESSION", encoding="utf-8"
    )

    complete = _run(config, tmp_path, adapter_factory=factory)
    assert complete["status"] == "complete"
    assert complete["session_checks"][-1]["active_sessions"] == 0
    assert complete["evidence_frozen_at"]
    assert "CONTEXT-AFTER-ACTIVE-SESSION" in events[0][2]
    assert "SELECTED-CONTEXT" not in events[0][2]


@pytest.mark.parametrize(
    "second",
    [
        {"ok": True, "active_sessions": 1, "sources": ["codex-process"], "reason": ""},
        {"ok": False, "active_sessions": 0, "sources": [], "reason": "probe_error"},
    ],
)
def test_second_session_gate_waits_with_provider_decision_and_pending_slots(
    second, tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id=f"fanout-wait-{second['ok']}", max_agents=3)
    observations = iter([idle_sessions(), second])
    events = []
    factory = _success_factory(events)

    waiting = _run(
        config,
        tmp_path,
        adapter_factory=factory,
        session_probe=lambda: next(observations),
    )

    assert waiting["status"] == "waiting"
    assert waiting["provider_decision"] == "claude"
    assert waiting["calls_claimed"] == 1
    assert waiting["slots"][0]["status"] == "completed"
    assert all(slot["status"] == "pending" for slot in waiting["slots"][1:])
    assert sum(1 for event in events if event[0] == "start") == 1

    complete = _run(config, tmp_path, adapter_factory=factory)
    assert complete["status"] == "complete"
    assert complete["calls_claimed"] == 3
    assert sum(1 for event in events if event[0] == "start") == 3
    assert sum(
        1
        for slot in complete["slots"]
        for attempt in slot["attempts"]
        if attempt["provider"] == "claude"
    ) == 3, "resume must retain the provider decision, not run another probe"


@pytest.mark.parametrize(
    "probe",
    [
        None,
        lambda: (_ for _ in ()).throw(RuntimeError("probe failed")),
        lambda: {"ok": True, "active_sessions": "zero"},
        lambda: core.SessionProbeResult(True, -1, ("forged",), ""),
    ],
)
def test_missing_raising_or_malformed_session_probe_fails_closed(
    probe, tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id=f"probe-error-{abs(hash(repr(probe)))}")
    events = []
    state = core.run_campaign(
        config,
        planner=_planner,
        runs_root=tmp_path / "runs",
        budget_guard_factory=no_budget,
        kill_switch=PassSwitch(),
        session_probe=probe,
        adapter_factory=_success_factory(events),
    )
    assert state["status"] == "waiting"
    assert state["calls_claimed"] == 0
    assert events == []
    assert state["session_checks"][-1]["ok"] is False


def test_kill_switch_is_watched_and_checked_before_any_dispatch(
    tmp_path: Path, registered_project: Path
):
    config = _config(tmp_path, campaign_id="killed")
    events = []
    switch = StopSwitch()

    state = _run(
        config,
        tmp_path,
        adapter_factory=_success_factory(events),
        kill_switch=switch,
    )

    assert events == []
    assert state["calls_claimed"] == 0
    assert state["provider_decision"] == "stopped"
    assert switch.checkpoints >= 1


def test_kill_trip_between_caller_checkpoint_and_seat_prevents_runner(
    tmp_path: Path, registered_project: Path
):
    config = _config(
        tmp_path, campaign_id="seat-kill-race", max_agents=1, max_parallel=1
    )
    seat_entered = threading.Event()
    release_seat = threading.Event()
    tripped = threading.Event()
    events = []

    class SeatBarrierSwitch(PassSwitch):
        def checkpoint(self) -> None:
            self.checkpoints += 1
            if threading.current_thread().name.startswith("council-"):
                seat_entered.set()
                assert release_seat.wait(30)
            if tripped.is_set():
                raise LoopHalted("tripped after caller checkpoint")

    switch = SeatBarrierSwitch()
    result = {}
    failures = []

    def execute():
        try:
            result.update(
                _run(
                    config,
                    tmp_path,
                    adapter_factory=_success_factory(events),
                    kill_switch=switch,
                )
            )
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    if not seat_entered.wait(20):
        thread.join(1)
        pytest.fail(f"seat was not reached; worker failures={failures!r}")
    tripped.set()
    release_seat.set()
    thread.join(10)

    assert not failures
    assert events == [], "a latched switch must win before the vendor runner"
    assert result["calls_claimed"] == 1
    assert result["provider_decision"] == "stopped"
    assert result["slots"][0]["attempts"][0]["status"] == (
        "cancelled_before_dispatch"
    )


def test_campaign_local_spend_ceiling_refuses_before_adapter(
    tmp_path: Path, registered_project: Path
):
    config = _config(
        tmp_path,
        campaign_id="budget",
        max_agents=1,
        max_parallel=1,
        max_spend_usd=0.01,
    )
    created = []
    starts = []
    safe_factory = _success_factory(starts)

    def factory(*args):
        created.append(args)
        return safe_factory(args[0], args[1], args[2])

    state = core.run_campaign(
        config,
        planner=_planner,
        runs_root=tmp_path / "runs",
        kill_switch=PassSwitch(),
        session_probe=idle_sessions,
        adapter_factory=factory,
    )

    assert len(created) == 1, "constructing a tool-less adapter is not dispatch"
    assert starts == [], "spend refusal must happen before the adapter runner"
    assert state["slots"][0]["status"] == "budget_refused"
    assert state["calls_claimed"] == 1


def test_budget_reservation_shares_the_vendor_thread_with_process_guard(
    tmp_path: Path,
    registered_project: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The explicit campaign charge suppresses the process guard in-seat.

    Council starts ``adapter.ask`` on its own thread.  If the explicit guard
    sits outside ``convene``, its thread-local marker is absent at the vendor
    spawn and the shared process guard charges a second ledger.
    """

    config = _config(
        tmp_path,
        campaign_id="one-budget-charge",
        max_agents=1,
        max_parallel=1,
    )
    shared_ledger = tmp_path / "shared-budget.json"
    monkeypatch.setenv(budget.ENV_LEDGER, str(shared_ledger))
    monkeypatch.setenv(budget.ENV_CEILING, "100")
    monkeypatch.setenv(budget.ENV_MAX_CALLS, "10")
    monkeypatch.setenv(budget.ENV_PERIOD, "total")
    budget.reset_default_ledger()
    budget.uninstall_process_guard()
    starts = []

    def fake_spawn(argv, **_kwargs):
        starts.append(tuple(argv))
        return object()

    monkeypatch.setattr(subprocess, "run", fake_spawn)
    uninstall = budget.install_process_guard()

    def runner(_argv, **_kwargs):
        # This is the syscall-like boundary the process guard classifies.
        subprocess.run(["claude", "-p"])
        return RunResult(
            returncode=0,
            stdout=json.dumps(
                {"is_error": False, "result": "CLAIM: x\nCHECK: pytest -q"}
            ),
        )

    def factory(_provider, cfg, repo_root):
        return core.StructuredClaudeAdapter(
            model="opus", repo_root=repo_root, runner=runner
        )

    try:
        state = core.run_campaign(
            config,
            planner=_planner,
            runs_root=tmp_path / "runs",
            kill_switch=PassSwitch(),
            session_probe=idle_sessions,
            adapter_factory=factory,
        )
    finally:
        uninstall()
        budget.reset_default_ledger()

    campaign_ledger = budget.Ledger(
        tmp_path / "runs" / "mission-one-budget-charge" / "budget.json",
        ceiling_usd=100,
        max_calls=2,
        period="total",
    ).state()
    assert state["status"] == "complete"
    assert len(starts) == 1
    assert campaign_ledger.calls == 1
    assert not shared_ledger.exists(), "process guard double-charged the shared ledger"


def test_global_os_lock_prevents_two_campaign_ids_from_overlapping(
    tmp_path: Path, registered_project: Path
):
    first_config = _config(tmp_path, campaign_id="lock-a", max_agents=1, max_parallel=1)
    second_config = _config(tmp_path, campaign_id="lock-b", max_agents=1, max_parallel=1)
    entered = threading.Event()
    release = threading.Event()
    failures = []

    def blocking_convene(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return core.council_convene(*args, **kwargs)

    def first_run():
        try:
            _run(
                first_config,
                tmp_path,
                adapter_factory=_success_factory(),
                convene_fn=blocking_convene,
            )
        except BaseException as exc:  # surfaced in the assertion below
            failures.append(exc)

    thread = threading.Thread(target=first_run)
    thread.start()
    assert entered.wait(5)
    try:
        with pytest.raises(core.CampaignBusy):
            _run(second_config, tmp_path, adapter_factory=_success_factory())
    finally:
        release.set()
        thread.join(10)
    assert not failures


def test_global_lock_outlives_effect_timeout_until_seat_returns(
    tmp_path: Path, registered_project: Path
):
    first_config = _config(
        tmp_path, campaign_id="timeout-lock-a", max_agents=1, max_parallel=1
    )
    second_config = _config(
        tmp_path, campaign_id="timeout-lock-b", max_agents=1, max_parallel=1
    )
    payload = json.loads(first_config.read_text(encoding="utf-8"))
    payload["timeout_s"] = 1
    first_config.write_text(json.dumps(payload), encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    failures = []

    def slow_runner(_argv, **kwargs):
        assert kwargs["timeout_s"] == 1
        started.set()
        assert release.wait(10)
        finished.set()
        return RunResult(
            returncode=0,
            stdout=json.dumps({"is_error": False, "result": "CLAIM: x\nCHECK: x"}),
        )

    def slow_factory(_provider, cfg, repo_root):
        return core.StructuredClaudeAdapter(
            model="opus", repo_root=repo_root, runner=slow_runner
        )

    def first_run():
        try:
            _run(first_config, tmp_path, adapter_factory=slow_factory)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=first_run)
    thread.start()
    assert started.wait(5)
    # Past the actual one-second provider deadline, but inside the explicit
    # ManagedProcess cancellation margin retained by Council.
    assert core.COUNCIL_CANCELLATION_MARGIN_S >= (
        2 * (core.DEFAULT_GRACE_S + 10) + 1
    )
    # Cross the old timeout+grace+1 outer cap. The seat is deliberately still
    # returning from its simulated cancellation path, so the fleet lock must
    # remain held. The bound assertion above separately pins both canonical
    # cancel ladders (grace + hard-kill wait + close's retry).
    time.sleep(5.2)
    try:
        assert not finished.is_set()
        with pytest.raises(core.CampaignBusy):
            _run(
                second_config,
                tmp_path,
                adapter_factory=_success_factory(),
            )
    finally:
        release.set()
        thread.join(10)
    assert not failures
    assert finished.is_set()


def test_windows_codex_adapter_pins_exe_and_both_profiles_have_no_write_tools(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(core.os, "name", "nt")
    monkeypatch.setattr(core.shutil, "which", lambda name: r"C:\native\codex.exe")
    codex = core.ExecutableCodexAdapter(model="codex-test", runner=lambda *a, **k: None)
    claude = core.StructuredClaudeAdapter(model="opus", runner=lambda *a, **k: None)

    codex_argv = codex.argv("codex-test")
    claude_argv = claude.argv("opus")
    assert codex_argv[0] == r"C:\native\codex.exe"
    assert "read-only" in codex_argv
    stdin_index = codex_argv.index("-")
    for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral"):
        assert flag in codex_argv
        assert codex_argv.index(flag) < stdin_index
    assert "workspace-write" not in " ".join(codex_argv)
    assert any(arg.startswith("--disallowed-tools=") for arg in claude_argv)
    tools_index = claude_argv.index("--tools")
    assert claude_argv[tools_index + 1] == "", "Claude tools must be a closed empty set"
    assert "--safe-mode" in claude_argv
    assert "--disable-slash-commands" in claude_argv
    assert "--no-session-persistence" in claude_argv
    assert not any(arg.startswith("--allowed-tools") for arg in claude_argv)
    assert "--model" in claude_argv and "opus" in claude_argv
    assert "dontAsk" not in " ".join(claude_argv)

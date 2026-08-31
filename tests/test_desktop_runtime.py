from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from daedalus import budget as budget_kernel
from daedalus import desktop_runtime as desktop_runtime_module
from daedalus import file_bridge
from daedalus import projects
from daedalus import sensitivity
from daedalus.limit_policy import (
    ExecutionLimitPolicy,
    LIMIT_AXES,
    LimitAxes,
    MODE_CUSTOM,
    MODE_UNBOUNDED_EXECUTION,
)
from daedalus.desktop_runtime import (
    IDE_DOCKER_CONTAINER,
    IDE_DOCKER_IMAGE,
    IDE_DOCKER_OWNER_LABEL,
    IDE_DOCKER_OWNER_VALUE,
    IDE_DOCKER_PROJECT_LABEL,
    IDE_DOCKER_WORKSPACE,
    REMOTE_OK_VAR,
    TRUSTED_HOSTS_VAR,
    TUNNEL_FORWARD_VAR,
    TUNNEL_TARGET_VAR,
    DesktopRuntimeError,
    DesktopRuntimeManager,
    install_web_integration,
    install_tunnel_egress_policy,
    normalize_config,
)

ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_ENV = (
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
    REMOTE_OK_VAR,
    TRUSTED_HOSTS_VAR,
    TUNNEL_FORWARD_VAR,
    TUNNEL_TARGET_VAR,
    budget_kernel.ENV_CEILING,
    budget_kernel.ENV_PERIOD_CEILING_ENABLED,
    budget_kernel.ENV_EXECUTION_LIMIT_POLICY,
    budget_kernel.ENV_MAX_CALLS,
    budget_kernel.ENV_LEDGER,
)


@pytest.fixture(autouse=True)
def restore_runtime_env(tmp_path):
    before = {key: os.environ.get(key) for key in _RUNTIME_ENV}
    os.environ[budget_kernel.ENV_LEDGER] = str(tmp_path / "desktop-budget.json")
    os.environ.pop(budget_kernel.ENV_CEILING, None)
    os.environ.pop(budget_kernel.ENV_PERIOD_CEILING_ENABLED, None)
    os.environ.pop(budget_kernel.ENV_EXECUTION_LIMIT_POLICY, None)
    os.environ.pop(budget_kernel.ENV_MAX_CALLS, None)
    budget_kernel.reset_default_ledger()
    yield
    budget_kernel.reset_default_ledger()
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def remote_config(**patch):
    remote = {
        "host": "192.168.50.20",
        "user": "kaya",
        "port": 22,
        "identity_file": "",
        "host_key_fingerprint": "SHA256:" + "A" * 43,
        "local_port": 11435,
        "remote_port": 11434,
        "start_method": "none",
        "trust_remote_host": False,
    }
    remote.update(patch)
    return {
        "bridge": {"auto_start": True},
        "ollama": {
            "mode": "remote_ssh",
            "auto_start": False,
            "model": "qwen2.5-coder:7b",
            "local_host": "http://127.0.0.1:11434",
            "remote": remote,
        },
    }


def budget_settings(
    manager: DesktopRuntimeManager,
    *,
    enabled: bool,
    ceiling_usd: float,
    confirm_widening: bool | None = None,
):
    config = json.loads(json.dumps(manager.config))
    config["bridge"]["auto_start"] = False
    config["ide"]["auto_start"] = False
    config["ollama"]["auto_start"] = False
    config["budget"] = {
        "period_ceiling_usd": ceiling_usd,
        "max_calls": manager.config["budget"]["max_calls"],
    }
    configured = ExecutionLimitPolicy.from_dict(
        manager.config["caps"]
    ).configured.as_dict()
    configured["period_usd"] = enabled
    config["caps"] = ExecutionLimitPolicy(
        mode=MODE_CUSTOM,
        configured=LimitAxes.from_dict(configured),
    ).as_dict()
    if confirm_widening is not None:
        config["caps"]["confirm_widening"] = confirm_widening
    return config


def cap_settings(
    manager: DesktopRuntimeManager,
    *,
    mode: str | None = None,
    axes: dict[str, bool] | None = None,
    ceiling_usd: float | None = None,
    max_calls: int | None = None,
    confirm_widening: bool | None = None,
):
    config = json.loads(json.dumps(manager.config))
    config["bridge"]["auto_start"] = False
    config["ide"]["auto_start"] = False
    config["ollama"]["auto_start"] = False
    policy = ExecutionLimitPolicy.from_dict(manager.config["caps"])
    configured = policy.configured.as_dict()
    configured.update(axes or {})
    config["caps"] = ExecutionLimitPolicy(
        mode=mode or policy.mode,
        configured=LimitAxes.from_dict(configured),
    ).as_dict()
    if confirm_widening is not None:
        config["caps"]["confirm_widening"] = confirm_widening
    config["budget"] = {
        "period_ceiling_usd": (
            manager.config["budget"]["period_ceiling_usd"]
            if ceiling_usd is None else ceiling_usd
        ),
        "max_calls": (
            manager.config["budget"]["max_calls"]
            if max_calls is None else max_calls
        ),
    }
    return config


def quiet_status(manager: DesktopRuntimeManager, monkeypatch) -> None:
    monkeypatch.setattr(manager, "_probe", lambda timeout=1.5: (False, "offline"))
    monkeypatch.setattr(
        manager,
        "_ide_status",
        lambda project=None: {"reachable": False, "last_error": "offline"},
    )


def test_ollama_child_environment_removes_only_frozen_runtime_paths(tmp_path):
    frozen = tmp_path / "backend" / "_internal"
    nested = frozen / "runtime-bin"
    sibling = tmp_path / "backend" / "_internal-tools"
    external = tmp_path / "tools"
    original_path = os.pathsep.join(
        (str(frozen), str(nested), str(sibling), str(external), "")
    )
    source = {"PATH": original_path, "PRESERVE": "yes"}

    child = desktop_runtime_module._ollama_child_environment(source, frozen)

    assert child["PATH"].split(os.pathsep) == [str(sibling), str(external), ""]
    assert child["PRESERVE"] == "yes"
    assert source["PATH"] == original_path


def test_frozen_ollama_spawn_resets_then_restores_dll_directory(
    tmp_path, monkeypatch
):
    frozen = (tmp_path / "backend" / "_internal").resolve()
    events = []

    class FakeManagedProcess:
        def __init__(self, argv, **kwargs):
            events.append(("spawn", list(argv), kwargs))

    monkeypatch.setattr(desktop_runtime_module, "ManagedProcess", FakeManagedProcess)
    monkeypatch.setattr(
        desktop_runtime_module,
        "_set_windows_dll_directory",
        lambda path: events.append(("dll", path)),
    )

    managed = desktop_runtime_module._spawn_ollama_process(
        [r"C:\Ollama\ollama.exe", "serve"],
        cwd=tmp_path,
        env={"PATH": "safe"},
        stdout=None,
        stderr=None,
        frozen_root=frozen,
    )

    assert isinstance(managed, FakeManagedProcess)
    assert [event[0] for event in events] == ["dll", "spawn", "dll"]
    assert events[0] == ("dll", None)
    assert events[2] == ("dll", str(frozen))


def test_frozen_ollama_spawn_restores_dll_directory_after_spawn_error(
    tmp_path, monkeypatch
):
    frozen = (tmp_path / "backend" / "_internal").resolve()
    events = []

    class FailingManagedProcess:
        def __init__(self, argv, **kwargs):
            events.append(("spawn", list(argv)))
            raise OSError("spawn failed")

    monkeypatch.setattr(desktop_runtime_module, "ManagedProcess", FailingManagedProcess)
    monkeypatch.setattr(
        desktop_runtime_module,
        "_set_windows_dll_directory",
        lambda path: events.append(("dll", path)),
    )

    with pytest.raises(OSError, match="spawn failed"):
        desktop_runtime_module._spawn_ollama_process(
            [r"C:\Ollama\ollama.exe", "serve"],
            cwd=tmp_path,
            env={"PATH": "safe"},
            stdout=None,
            stderr=None,
            frozen_root=frozen,
        )

    assert events == [
        ("dll", None),
        ("spawn", [r"C:\Ollama\ollama.exe", "serve"]),
        ("dll", str(frozen)),
    ]


def test_frozen_ollama_spawn_closes_child_when_dll_restore_fails(
    tmp_path, monkeypatch
):
    frozen = (tmp_path / "backend" / "_internal").resolve()
    events = []

    class FakeManagedProcess:
        def __init__(self, argv, **kwargs):
            events.append(("spawn", list(argv)))

        def close(self, *, grace_s):
            events.append(("close", grace_s))

    def set_dll_directory(path):
        events.append(("dll", path))
        if path is not None:
            raise OSError("restore failed")

    monkeypatch.setattr(desktop_runtime_module, "ManagedProcess", FakeManagedProcess)
    monkeypatch.setattr(
        desktop_runtime_module, "_set_windows_dll_directory", set_dll_directory
    )

    with pytest.raises(OSError, match="restore failed"):
        desktop_runtime_module._spawn_ollama_process(
            [r"C:\Ollama\ollama.exe", "serve"],
            cwd=tmp_path,
            env={"PATH": "safe"},
            stdout=None,
            stderr=None,
            frozen_root=frozen,
        )

    assert events == [
        ("dll", None),
        ("spawn", [r"C:\Ollama\ollama.exe", "serve"]),
        ("dll", str(frozen)),
        ("close", 0.0),
    ]


def test_defaults_autostart_bridge_and_local_ollama():
    cfg = normalize_config({})
    assert cfg["bridge"]["auto_start"] is True
    assert cfg["budget"] == {
        "period_ceiling_usd": budget_kernel.DEFAULT_CEILING_USD,
        "max_calls": budget_kernel.DEFAULT_MAX_CALLS,
    }
    assert cfg["caps"] == ExecutionLimitPolicy().as_dict()
    assert cfg["ide"] == {
        "mode": "docker" if os.name == "nt" else "native",
        "auto_start": False,
        "endpoint": "http://127.0.0.1:3000",
        "executable": "",
        "docker_image": IDE_DOCKER_IMAGE,
    }
    assert cfg["ollama"]["auto_start"] is True
    assert cfg["ollama"]["mode"] == "local"


def test_bridge_pid_liveness_distinguishes_current_from_exited_process():
    child = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child.wait(timeout=5.0)

    assert desktop_runtime_module._pid_is_alive(os.getpid()) is True
    assert desktop_runtime_module._pid_is_alive(child.pid) is False
    assert desktop_runtime_module._pid_is_alive(None) is False
    assert desktop_runtime_module._pid_is_alive(0x8000_0000) is False
    assert desktop_runtime_module._pid_is_alive(0xFFFF_FFFF) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows process exit-code semantics")
def test_bridge_pid_liveness_does_not_confuse_exit_259_with_still_running():
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(259)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert child.wait(timeout=5.0) == 259

    # Popen deliberately retains a process handle here, so OpenProcess can
    # still find the terminated process.  WaitForSingleObject must classify
    # it as signalled rather than trusting the ambiguous STILL_ACTIVE value.
    assert desktop_runtime_module._pid_is_alive(child.pid) is False


def test_bridge_watcher_lock_is_atomic_and_released(tmp_path):
    lock_path = tmp_path / "bridge_watcher.lock"

    with file_bridge._BridgeWatcherLock(lock_path):
        with pytest.raises(file_bridge.WatcherOwnershipBusy):
            with file_bridge._BridgeWatcherLock(lock_path):
                pytest.fail("a second owner acquired the same OS lock")

    with file_bridge._BridgeWatcherLock(lock_path):
        pass


def test_persistent_bridge_lock_is_untracked_runtime_state():
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", "runs/bridge_watcher.lock"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_two_desktop_managers_racing_create_exactly_one_bridge_owner(
    tmp_path, monkeypatch
):
    lock_path = tmp_path / "bridge_watcher.lock"
    heartbeat: dict[str, object] = {}
    heartbeat_lock = threading.Lock()

    def heartbeat_status():
        with heartbeat_lock:
            return dict(heartbeat) if heartbeat else {"state": "none"}

    def claimed_watch(
        default_repo_root,
        interval_s,
        project=None,
        *,
        owner_token=None,
        process_identity=None,
        stop_event=None,
    ):
        with file_bridge._BridgeWatcherLock(lock_path):
            with heartbeat_lock:
                heartbeat.update(
                    {
                        "state": "alive",
                        "pid": os.getpid(),
                        "owner_token": owner_token,
                        "process_identity": process_identity,
                    }
                )
            stop_event.wait(5.0)

    monkeypatch.setattr(file_bridge, "heartbeat_status", heartbeat_status)
    monkeypatch.setattr(file_bridge, "watch", claimed_watch)
    managers = [DesktopRuntimeManager(tmp_path), DesktopRuntimeManager(tmp_path)]
    callers_ready = threading.Barrier(2)
    results: list[dict[str, object] | None] = [None, None]

    def start(index):
        callers_ready.wait(timeout=5.0)
        results[index] = managers[index].ensure_bridge()

    callers = [threading.Thread(target=start, args=(index,)) for index in range(2)]
    try:
        for caller in callers:
            caller.start()
        for caller in callers:
            caller.join(timeout=5.0)

        assert not any(caller.is_alive() for caller in callers)
        assert sum(bool(result and result["managed"]) for result in results) == 1
        assert (
            sum(
                bool(manager._bridge and manager._bridge.is_alive())
                for manager in managers
            )
            == 1
        )
    finally:
        for manager in managers:
            manager.close()
        for manager in managers:
            if manager._bridge:
                manager._bridge.join(timeout=2.0)


def test_bridge_start_post_takes_over_a_dead_persisted_heartbeat(
    tmp_path, monkeypatch
):
    manager = DesktopRuntimeManager(tmp_path)
    started = threading.Event()
    release = threading.Event()
    starts: list[int] = []
    old_pid = os.getpid() + 100_000
    owner: dict[str, str] = {}

    def heartbeat_status():
        if started.is_set():
            return {
                "state": "alive",
                "pid": os.getpid(),
                "project": "daedalus",
                "repo_root": str(tmp_path),
                "age_s": 0.0,
                "owner_token": owner["token"],
                "process_identity": owner["identity"],
            }
        return {
            "state": "alive",
            "pid": old_pid,
            "project": "daedalus",
            "repo_root": str(tmp_path),
            "age_s": 1.0,
        }

    def watch_bridge(
        default_repo_root,
        interval_s,
        project=None,
        *,
        owner_token=None,
        process_identity=None,
        stop_event=None,
    ):
        starts.append(threading.get_ident())
        owner["token"] = owner_token
        owner["identity"] = process_identity
        started.set()
        release.wait(5.0)

    monkeypatch.setattr(file_bridge, "heartbeat_status", heartbeat_status)
    monkeypatch.setattr(file_bridge, "watch", watch_bridge)

    class BaseHandler:
        path = ""

        def _send_json(self, payload, status=200):
            self.sent = (payload, status)

        def _handle_post(self):
            self.fell_through = True

    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        _read_body=lambda handler: {},
        core=SimpleNamespace(envelope=lambda project, **payload: payload),
    )
    install_web_integration(web_api, manager)

    try:
        request = web_api.DaedalusHandler()
        request.path = "/api/desktop/services/bridge/start"
        request._handle_post()

        service, status = request.sent
        assert status == 200
        assert service["service"]["managed"] is True
        assert service["service"]["state"] == "alive"
        assert service["service"]["pid"] == os.getpid()
        assert starts and len(starts) == 1

        first_thread = manager._bridge
        repeated = manager.ensure_bridge()
        assert repeated["managed"] is True
        assert manager._bridge is first_thread
        assert len(starts) == 1
    finally:
        release.set()
        manager.close()
        if manager._bridge:
            manager._bridge.join(timeout=2.0)


def test_live_external_bridge_owner_is_not_duplicated(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    external_pid = os.getpid() + 100_000
    starts: list[str] = []
    monkeypatch.setattr(
        file_bridge,
        "heartbeat_status",
        lambda: {
            "state": "alive",
            "pid": external_pid,
            "project": "other-owner",
            "repo_root": str(tmp_path),
            "age_s": 0.1,
            "owner_token": "external-owner-token",
            "process_identity": "external-process-identity",
        },
    )

    def occupied_watch(*args, **kwargs):
        starts.append(kwargs["owner_token"])
        raise file_bridge.WatcherOwnershipBusy("synthetic external owner")

    monkeypatch.setattr(file_bridge, "watch", occupied_watch)

    try:
        status = manager.ensure_bridge()
        assert status["managed"] is False
        assert status["pid"] == external_pid
        assert manager._bridge is not None and not manager._bridge.is_alive()
        assert len(starts) == 1
        assert "external owner" in status["last_error"]
    finally:
        manager.close()


def test_bridge_owner_token_and_process_identity_prevent_pid_reuse_adoption(
    tmp_path,
):
    manager = DesktopRuntimeManager(tmp_path)
    release = threading.Event()
    manager._bridge_owner_token = "new-owner-token"
    manager._bridge_process_identity = "new-process-identity"
    manager._bridge = threading.Thread(target=lambda: release.wait(2.0), daemon=True)
    manager._bridge.start()
    try:
        reused_pid_status = {
            "state": "alive",
            "pid": os.getpid(),
            "owner_token": "old-owner-token",
            "process_identity": "old-process-identity",
        }
        assert manager._bridge_status_is_managed(reused_pid_status) is False
        assert manager._bridge_status_is_managed(
            {
                **reused_pid_status,
                "owner_token": "new-owner-token",
                "process_identity": "new-process-identity",
            }
        ) is True
    finally:
        release.set()
        manager.close()
        manager._bridge.join(timeout=2.0)


def test_bridge_start_failure_never_reports_managed(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    monkeypatch.setattr(
        file_bridge,
        "heartbeat_status",
        lambda: {"state": "none", "detail": "no heartbeat"},
    )
    monkeypatch.setattr(
        file_bridge,
        "watch",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PermissionError("synthetic boundary refusal")
        ),
    )
    try:
        status = manager.ensure_bridge()
        assert status["managed"] is False
        assert status["state"] == "none"
        assert "synthetic boundary refusal" in status["last_error"]
        assert manager._bridge is not None and not manager._bridge.is_alive()
    finally:
        manager.close()


@pytest.mark.parametrize(
    "settings",
    [
        {"period_ceiling_enabled": 1, "period_ceiling_usd": 5.0},
        {"period_ceiling_enabled": "false", "period_ceiling_usd": 5.0},
        {"period_ceiling_enabled": True, "period_ceiling_usd": True},
        {"period_ceiling_enabled": True, "period_ceiling_usd": "5"},
        {"period_ceiling_enabled": True, "period_ceiling_usd": 0},
        {"period_ceiling_enabled": True, "period_ceiling_usd": -1},
        {"period_ceiling_enabled": True, "period_ceiling_usd": float("nan")},
        {"period_ceiling_enabled": True, "period_ceiling_usd": float("inf")},
        {"period_ceiling_usd": 5.0, "max_calls": True},
        {"period_ceiling_usd": 5.0, "max_calls": 0},
        {"period_ceiling_usd": 5.0, "max_calls": 1.5},
        {"period_ceiling_usd": 5.0, "max_calls": "40"},
        {
            "period_ceiling_enabled": True,
            "period_ceiling_usd": 5.0,
            "api_key": "must-not-be-stored",
        },
    ],
)
def test_budget_settings_are_strict_and_never_accept_secrets(settings):
    with pytest.raises(ValueError, match="budget"):
        normalize_config({"budget": settings})


def test_missing_desktop_budget_migrates_the_existing_environment(
        tmp_path, monkeypatch):
    monkeypatch.setenv(budget_kernel.ENV_CEILING, "12.5")
    monkeypatch.setenv(budget_kernel.ENV_PERIOD_CEILING_ENABLED, "false")

    manager = DesktopRuntimeManager(tmp_path)
    try:
        assert manager.config["budget"] == {
            "period_ceiling_usd": 12.5,
            "max_calls": budget_kernel.DEFAULT_MAX_CALLS,
        }
        assert manager.config["caps"]["mode"] == MODE_CUSTOM
        assert manager.config["caps"]["configured"]["period_usd"] is False
        assert budget_kernel.ledger().state().effective_period_ceiling_usd is None
    finally:
        manager.close()


def test_disabling_the_period_ceiling_requires_transient_confirmation_and_keeps_ledger(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    budget_kernel.ledger().reserve(
        budget_kernel.Estimate("deepseek", "m", 1.0, 1, "priced"),
        label="existing spend",
    ).settle()
    before = budget_kernel.ledger().state()
    config_path = tmp_path / "config" / "connections.json"

    try:
        with pytest.raises(ValueError, match="confirm_widening"):
            manager.save_settings(
                budget_settings(manager, enabled=False, ceiling_usd=5.0)
            )
        assert not config_path.exists()
        assert budget_kernel.ledger().state().period_ceiling_enabled is True

        snapshot = manager.save_settings(
            budget_settings(
                manager,
                enabled=False,
                ceiling_usd=5.0,
                confirm_widening=True,
            )
        )
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert "confirm_widening" not in saved["caps"]
        assert "confirm_widening" not in snapshot["config"]["caps"]
        assert snapshot["budget"]["effective_period_ceiling_usd"] is None
        assert snapshot["budget"]["remaining_period_usd"] is None
        assert snapshot["budget"]["call_ceiling_enforced"] is True

        after = budget_kernel.ledger().state()
        assert after.spent_usd == before.spent_usd
        assert after.calls == before.calls
        assert after.period_key == before.period_key
        budget_kernel.ledger().reserve(
            budget_kernel.Estimate("deepseek", "m", 10.0, 1, "priced"),
            label="uncapped paid call",
        ).settle()
        assert budget_kernel.ledger().state().spent_usd == pytest.approx(11.0)
    finally:
        manager.close()


def test_uncapping_or_increasing_the_configured_amount_requires_confirmation(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    try:
        manager.save_settings(
            budget_settings(
                manager,
                enabled=False,
                ceiling_usd=5.0,
                confirm_widening=True,
            )
        )
        with pytest.raises(ValueError, match="confirm_widening"):
            manager.save_settings(
                budget_settings(manager, enabled=False, ceiling_usd=50.0)
            )
        manager.save_settings(
            budget_settings(
                manager,
                enabled=False,
                ceiling_usd=50.0,
                confirm_widening=True,
            )
        )
        # Returning from uncapped to the already-confirmed finite fallback is
        # a narrowing and needs no second confirmation.
        manager.save_settings(
            budget_settings(manager, enabled=True, ceiling_usd=50.0)
        )

        with pytest.raises(ValueError, match="confirm_widening"):
            manager.save_settings(
                budget_settings(manager, enabled=True, ceiling_usd=51.0)
            )
        manager.save_settings(
            budget_settings(
                manager,
                enabled=True,
                ceiling_usd=51.0,
                confirm_widening=True,
            )
        )
        manager.save_settings(
            budget_settings(manager, enabled=True, ceiling_usd=4.0)
        )
    finally:
        manager.close()


def test_budget_snapshot_reports_ledger_error_without_bricking_settings(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    ledger_path = Path(os.environ[budget_kernel.ENV_LEDGER])
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("{not-json", encoding="utf-8")

    try:
        snapshot = manager.snapshot()
        assert snapshot["config"]["budget"]["period_ceiling_usd"] == 5.0
        assert snapshot["budget"]["available"] is False
        assert snapshot["budget_error"]
        assert snapshot["budget"]["remaining_period_usd"] is None
        with pytest.raises(budget_kernel.BudgetUnavailable):
            budget_kernel.ledger().reserve(
                budget_kernel.Estimate("deepseek", "m", 0.01, 1, "priced"),
                label="corrupt balance remains refused",
            )
    finally:
        manager.close()


def test_desktop_settings_route_requires_transient_budget_widening_confirmation(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)

    class BaseHandler:
        path = ""
        body = None

        def _send_json(self, payload, status=200):
            self.sent = (payload, status)

        def _handle_get(self):
            self.fell_through = True

        def _handle_put(self):
            self.fell_through = True

    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        _read_body=lambda handler: handler.body,
        core=SimpleNamespace(envelope=lambda project, **payload: payload),
        runtime_registry=SimpleNamespace(reset_status_cache=lambda: None),
    )
    install_web_integration(web_api, manager)

    try:
        rejected = web_api.DaedalusHandler()
        rejected.path = "/api/desktop/settings"
        rejected.body = budget_settings(
            manager, enabled=False, ceiling_usd=5.0
        )
        rejected._handle_put()
        assert rejected.sent[1] == 400
        assert "confirm_widening" in rejected.sent[0]["error"]
        assert budget_kernel.ledger().state().period_ceiling_enabled is True

        accepted = web_api.DaedalusHandler()
        accepted.path = "/api/desktop/settings"
        accepted.body = budget_settings(
            manager,
            enabled=False,
            ceiling_usd=5.0,
            confirm_widening=True,
        )
        accepted._handle_put()
        assert accepted.sent[1] == 200
        returned = accepted.sent[0]["desktop"]
        assert returned["budget"]["effective_period_ceiling_usd"] is None
        assert "confirm_widening" not in returned["config"]["caps"]

        fetched = web_api.DaedalusHandler()
        fetched.path = "/api/desktop/settings"
        fetched._handle_get()
        assert fetched.sent[1] == 200
        assert "confirm_widening" not in (
            fetched.sent[0]["desktop"]["config"]["caps"]
        )
    finally:
        manager.close()


@pytest.mark.parametrize("axis", LIMIT_AXES)
def test_every_effective_cap_disable_requires_backend_confirmation(
        axis, tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    try:
        proposed = cap_settings(
            manager,
            mode=MODE_CUSTOM,
            axes={axis: False},
        )
        with pytest.raises(ValueError, match=axis):
            manager.save_settings(proposed)

        proposed["caps"]["confirm_widening"] = True
        snapshot = manager.save_settings(proposed)
        assert snapshot["caps"]["effective"][axis] is False
        assert "confirm_widening" not in snapshot["config"]["caps"]
    finally:
        manager.close()


def test_unbounded_execution_keeps_fallbacks_but_nulls_live_budget_limits(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    try:
        snapshot = manager.save_settings(
            cap_settings(
                manager,
                mode=MODE_UNBOUNDED_EXECUTION,
                confirm_widening=True,
            )
        )
        assert snapshot["config"]["budget"] == {
            "period_ceiling_usd": budget_kernel.DEFAULT_CEILING_USD,
            "max_calls": budget_kernel.DEFAULT_MAX_CALLS,
        }
        assert set(snapshot["caps"]["effective"].values()) == {False}
        assert snapshot["budget"]["effective_period_ceiling_usd"] is None
        assert snapshot["budget"]["remaining_period_usd"] is None
        assert snapshot["budget"]["effective_max_calls"] is None
        assert snapshot["budget"]["remaining_billable_calls"] is None
        assert snapshot["budget"]["explicit_envelope_ceiling_enforced"] is False

        reloaded = DesktopRuntimeManager(tmp_path)
        try:
            assert reloaded.config == manager.config
            assert set(
                budget_kernel.ledger().state().effective_limit_axes.values()
            ) == {False}
        finally:
            reloaded.close()
    finally:
        manager.close()


@pytest.mark.parametrize(
    "patch, affected",
    [
        ({"ceiling_usd": 6.0}, "period_ceiling_usd"),
        ({"max_calls": 41}, "max_calls"),
    ],
)
def test_every_budget_fallback_increase_requires_confirmation(
        patch, affected, tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    try:
        with pytest.raises(ValueError, match=affected):
            manager.save_settings(cap_settings(manager, **patch))
        manager.save_settings(
            cap_settings(manager, confirm_widening=True, **patch)
        )
        assert "confirm_widening" not in json.loads(
            manager.config_path.read_text(encoding="utf-8")
        )["caps"]
    finally:
        manager.close()


def test_mode_label_without_effective_widening_needs_no_confirmation(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    try:
        snapshot = manager.save_settings(
            cap_settings(manager, mode=MODE_CUSTOM)
        )
        assert snapshot["caps"]["mode"] == MODE_CUSTOM
        assert set(snapshot["caps"]["effective"].values()) == {True}
    finally:
        manager.close()


def test_revision9_file_migrates_only_period_axis_and_reloads_canonically(
        tmp_path, monkeypatch):
    path = tmp_path / "config" / "connections.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "budget": {
                    "period_ceiling_enabled": False,
                    "period_ceiling_usd": 9.0,
                }
            }
        ),
        encoding="utf-8",
    )
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    try:
        assert manager.config["caps"]["mode"] == MODE_CUSTOM
        effective = ExecutionLimitPolicy.from_dict(
            manager.config["caps"]
        ).effective.as_dict()
        assert effective["period_usd"] is False
        assert all(effective[axis] for axis in LIMIT_AXES if axis != "period_usd")
        assert manager.config["budget"] == {
            "period_ceiling_usd": 9.0,
            "max_calls": budget_kernel.DEFAULT_MAX_CALLS,
        }

        manager.save_settings(manager.config)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert "period_ceiling_enabled" not in persisted["budget"]
        assert persisted["caps"] == manager.config["caps"]
    finally:
        manager.close()


def test_invalid_policy_environment_is_fail_closed_but_explicitly_repairable(
        tmp_path, monkeypatch):
    monkeypatch.setenv(budget_kernel.ENV_EXECUTION_LIMIT_POLICY, "{invalid")
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    try:
        assert manager.snapshot()["budget"]["available"] is False
        with pytest.raises(budget_kernel.BudgetUnavailable):
            budget_kernel.ledger().state()
        with pytest.raises(ValueError, match="budget and caps"):
            manager.save_settings({"bridge": {"auto_start": False}})

        repaired = manager.save_settings(cap_settings(manager))
        assert repaired["budget"]["available"] is True
        assert ExecutionLimitPolicy.from_env_value(
            os.environ[budget_kernel.ENV_EXECUTION_LIMIT_POLICY]
        ) == ExecutionLimitPolicy()
    finally:
        manager.close()


def test_legacy_and_canonical_confirmation_must_not_conflict(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    try:
        conflicting = cap_settings(
            manager,
            mode=MODE_CUSTOM,
            axes={"period_usd": False},
            confirm_widening=True,
        )
        conflicting["budget"]["confirm_widening"] = False
        with pytest.raises(ValueError, match="conflicts"):
            manager.save_settings(conflicting)

        legacy = cap_settings(
            manager,
            mode=MODE_CUSTOM,
            axes={"period_usd": False},
        )
        legacy["budget"]["confirm_widening"] = True
        saved = manager.save_settings(legacy)
        assert saved["caps"]["effective"]["period_usd"] is False
        assert "confirm_widening" not in saved["config"]["budget"]
    finally:
        manager.close()


def test_settings_do_not_accept_password_or_private_key_bytes():
    cfg = normalize_config(
        remote_config(password="do-not-store", private_key="-----BEGIN PRIVATE KEY-----")
    )
    remote = cfg["ollama"]["remote"]
    assert "password" not in remote
    assert "private_key" not in remote
    assert set(remote) == {
        "host",
        "user",
        "port",
        "identity_file",
        "host_key_fingerprint",
        "local_port",
        "remote_port",
        "start_method",
        "trust_remote_host",
    }


def test_remote_mode_rejects_option_injection_and_dns_trust():
    with pytest.raises(ValueError):
        normalize_config(remote_config(host="-oProxyCommand=evil"))
    with pytest.raises(ValueError):
        normalize_config(remote_config(host="bench.example", trust_remote_host=True))


def test_remote_environment_keeps_transport_and_physical_target_separate(tmp_path, monkeypatch):
    monkeypatch.delenv(TRUSTED_HOSTS_VAR, raising=False)
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config(remote_config())
    manager.apply_environment()
    try:
        assert os.environ["OLLAMA_HOST"] == "http://127.0.0.1:11435"
        assert os.environ[TUNNEL_FORWARD_VAR] == "http://127.0.0.1:11435"
        assert os.environ[TUNNEL_TARGET_VAR] == "http://192.168.50.20:11434"
        assert os.environ[REMOTE_OK_VAR] == "http://127.0.0.1:11435"
    finally:
        manager.close()


def test_tunnel_forward_is_egress_even_though_socket_is_loopback(monkeypatch):
    install_tunnel_egress_policy()
    monkeypatch.delenv(TRUSTED_HOSTS_VAR, raising=False)
    monkeypatch.setenv(TUNNEL_FORWARD_VAR, "http://127.0.0.1:11435")
    monkeypatch.setenv(TUNNEL_TARGET_VAR, "http://192.168.50.20:11434")

    assert sensitivity.is_loopback_host("http://127.0.0.1:11435") is True
    assert sensitivity.lane_for_host("http://127.0.0.1:11435") == "untrusted"
    assert sensitivity.lane_for_host("http://127.0.0.1:11434") == "trusted"


def test_explicit_numeric_remote_trust_survives_tunnel(monkeypatch):
    install_tunnel_egress_policy()
    monkeypatch.setenv(TRUSTED_HOSTS_VAR, "192.168.50.20")
    monkeypatch.setenv(TUNNEL_FORWARD_VAR, "http://127.0.0.1:11435")
    monkeypatch.setenv(TUNNEL_TARGET_VAR, "http://192.168.50.20:11434")
    assert sensitivity.lane_for_host("http://127.0.0.1:11435") == "trusted"


def test_ssh_is_strict_key_only(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config(remote_config(host_key_fingerprint=""))
    manager.apply_environment()
    monkeypatch.setattr("daedalus.desktop_runtime.shutil.which", lambda name: f"/bin/{name}")
    try:
        args = manager._ssh()
    finally:
        manager.close()
    joined = " ".join(args)
    assert "BatchMode=yes" in joined
    assert "PasswordAuthentication=no" in joined
    assert "KbdInteractiveAuthentication=no" in joined
    assert "StrictHostKeyChecking=yes" in joined
    assert "UserKnownHostsFile=" in joined


def test_corrupt_settings_fall_back_without_bricking_desktop(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "connections.json").write_text("{not-json", encoding="utf-8")

    manager = DesktopRuntimeManager(tmp_path)
    try:
        assert manager.config["ollama"]["mode"] == "local"
        assert "cannot read" in manager._config_error
    finally:
        manager.close()


def test_local_endpoint_must_be_numeric_loopback_and_clean_url():
    with pytest.raises(ValueError):
        normalize_config({"ollama": {"local_host": "http://localhost:11434"}})
    with pytest.raises(ValueError):
        normalize_config({"ollama": {"local_host": "http://0.0.0.0:11434"}})
    with pytest.raises(ValueError):
        normalize_config({"ollama": {"local_host": "http://user@127.0.0.1:11434"}})
    with pytest.raises(ValueError):
        normalize_config({"ollama": {"local_host": "http://127.0.0.1:11434?x=1"}})


def test_ipv6_loopback_keeps_required_brackets():
    cfg = normalize_config({"ollama": {"local_host": "http://[::1]:11434"}})
    assert cfg["ollama"]["local_host"] == "http://[::1]:11434"


def test_local_ollama_uses_resolved_executable_managed_process_and_neutral_cwd(
    tmp_path, monkeypatch
):
    manager = DesktopRuntimeManager(tmp_path)
    executable = (tmp_path / "installed" / "ollama.exe").resolve()
    probes = iter(((False, "offline"), (True, "")))
    calls = []

    class FakeManagedProcess:
        def __init__(self, argv, **kwargs):
            self._returncode = None
            self.closed = False
            calls.append((list(argv), kwargs, self))

        def poll(self):
            return self._returncode

        def close(self, *, grace_s):
            self.closed = True

    monkeypatch.setattr(manager, "_probe", lambda timeout=1.5: next(probes))
    monkeypatch.setattr(
        desktop_runtime_module.runtime_registry,
        "resolve_runtime_command",
        lambda runtime_id: str(executable) if runtime_id == "ollama_cli" else None,
    )
    monkeypatch.setattr(desktop_runtime_module, "ManagedProcess", FakeManagedProcess)
    monkeypatch.setattr(
        desktop_runtime_module, "_frozen_windows_runtime_root", lambda: None
    )

    try:
        result = manager.ensure_local_ollama()
        expected_cwd = tmp_path.resolve() / "runs" / "services" / "ollama"
        argv, kwargs, managed = calls[0]
        assert argv == [str(executable), "serve"]
        assert Path(argv[0]).is_absolute()
        assert kwargs["cwd"] == expected_cwd
        assert expected_cwd.is_dir()
        assert kwargs["env"] is not os.environ
        assert manager._ollama is managed
        assert isinstance(manager._ollama, FakeManagedProcess)
        assert result == {
            "mode": "local",
            "running": True,
            "reachable": True,
            "detail": "",
        }
    finally:
        manager.close()

    assert managed.closed is True


def test_reachable_preexisting_ollama_is_not_owned_or_stopped(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    monkeypatch.setattr(manager, "_probe", lambda timeout=1.5: (True, ""))
    monkeypatch.setattr(
        desktop_runtime_module.runtime_registry,
        "resolve_runtime_command",
        lambda runtime_id: pytest.fail("reachable Ollama must not resolve a new child"),
    )
    monkeypatch.setattr(
        desktop_runtime_module,
        "_spawn_ollama_process",
        lambda *args, **kwargs: pytest.fail("reachable Ollama must not be spawned"),
    )

    try:
        result = manager.ensure_local_ollama()
        assert result["reachable"] is True
        assert manager._ollama is None
        manager.stop_ollama()
        assert manager._ollama is None
    finally:
        manager.close()


def test_stop_ollama_releases_managed_process_after_parent_exit(tmp_path):
    manager = DesktopRuntimeManager(tmp_path)
    calls = []

    class ExitedManagedProcess:
        def poll(self):
            return 0

        def close(self, *, grace_s):
            calls.append(grace_s)

    manager._ollama = ExitedManagedProcess()
    try:
        manager.stop_ollama()
        assert calls == [2.0]
        assert manager._ollama is None
    finally:
        manager.close()


def test_local_host_route_change_stops_owned_ollama(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    stopped = []
    proposed = json.loads(json.dumps(manager.config))
    proposed["bridge"]["auto_start"] = False
    proposed["ide"]["auto_start"] = False
    proposed["ollama"]["auto_start"] = False
    proposed["ollama"]["local_host"] = "http://127.0.0.1:11436"
    monkeypatch.setattr(manager, "stop_ollama", lambda: stopped.append(True))

    try:
        manager.save_settings(proposed)
        assert stopped == [True]
    finally:
        manager.close()


def test_manager_close_uses_owned_ollama_stop_path(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    calls = []
    monkeypatch.setattr(manager, "stop_ide", lambda **kwargs: None)
    monkeypatch.setattr(manager, "stop_ollama", lambda: calls.append("ollama"))

    manager.close()

    assert calls == ["ollama"]


def test_web_ollama_stop_route_stops_owned_local_process():
    class BaseHandler:
        path = ""

        def _send_json(self, payload, status=200):
            self.sent = (payload, status)

        def _handle_post(self):
            self.fell_through = True

    class Manager:
        def __init__(self):
            self.stopped = False

        def stop_ollama(self):
            self.stopped = True

        def snapshot(self):
            return {"services": {"ollama": {"reachable": False}}}

    manager = Manager()
    cache_resets = []
    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        core=SimpleNamespace(envelope=lambda project, **payload: payload),
        runtime_registry=SimpleNamespace(
            reset_status_cache=lambda: cache_resets.append(True)
        ),
    )
    install_web_integration(web_api, manager)
    request = web_api.DaedalusHandler()
    request.path = "/api/desktop/services/ollama/stop"

    request._handle_post()

    assert manager.stopped is True
    assert cache_resets == [True]
    assert request.sent == ({"service": {"reachable": False}}, 200)


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://localhost:3000",
        "http://0.0.0.0:3000",
        "https://127.0.0.1:3000",
        "http://user@127.0.0.1:3000",
        "http://127.0.0.1:3000/workspace",
        "http://127.0.0.1:3000?token=nope",
    ),
)
def test_ide_endpoint_is_plain_numeric_loopback(endpoint):
    with pytest.raises(ValueError, match=r"ide\.endpoint"):
        normalize_config({"ide": {"endpoint": endpoint}})


def test_ide_executable_rejects_control_characters():
    with pytest.raises(ValueError, match=r"ide\.executable"):
        normalize_config({"ide": {"executable": "openvscode-server\n--host=evil"}})


def test_ide_discovery_prefers_configured_file_then_path(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    configured = tmp_path / "tools" / "openvscode-server"
    configured.parent.mkdir()
    configured.write_text("", encoding="utf-8")
    try:
        manager.config = normalize_config(
            {"ide": {"mode": "native", "executable": str(configured), "auto_start": False}}
        )
        monkeypatch.setattr(
            "daedalus.desktop_runtime.shutil.which",
            lambda command: pytest.fail("PATH must not be used for an explicit executable"),
        )
        assert manager._discover_ide_executable() == str(configured.resolve())

        manager.config = normalize_config({"ide": {"mode": "native", "executable": ""}})
        monkeypatch.setattr(
            "daedalus.desktop_runtime.shutil.which",
            lambda command: "/opt/openvscode-server" if command == "openvscode-server" else None,
        )
        assert manager._discover_ide_executable() == "/opt/openvscode-server"
    finally:
        manager.close()


def test_ide_discovery_does_not_download_missing_server(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    monkeypatch.setattr("daedalus.desktop_runtime.shutil.which", lambda command: None)
    try:
        with pytest.raises(DesktopRuntimeError, match="runtime downloads are disabled"):
            manager._discover_ide_executable()
    finally:
        manager.close()


def test_ide_start_is_loopback_only_and_project_never_enters_command(tmp_path, monkeypatch):
    class Process:
        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    executable = tmp_path / "openvscode-server"
    executable.write_text("", encoding="utf-8")
    project = tmp_path / "--project with spaces"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config(
        {
            "ide": {
                "mode": "native",
                "endpoint": "http://127.0.0.1:3000",
                "executable": str(executable),
            }
        }
    )
    probes = iter(((False, "offline"), (True, ""), (True, "")))
    monkeypatch.setattr(manager, "_probe_ide", lambda timeout=1.5: next(probes))
    launched = {}
    proc = Process()

    def popen(args, **kwargs):
        launched["args"] = args
        launched["kwargs"] = kwargs
        return proc

    monkeypatch.setattr("daedalus.desktop_runtime.subprocess.Popen", popen)
    try:
        status = manager.ensure_ide(project)
        assert launched["args"] == [
            str(executable.resolve()),
            "--host",
            "127.0.0.1",
            "--port",
            "3000",
            "--without-connection-token",
        ]
        assert str(project) not in launched["args"]
        assert parse_qs(urlsplit(status["ui_url"]).query) == {
            "folder": [str(project.resolve())]
        }
        assert status["reachable"] is True
        assert status["managed"] is True
        manager.stop_ide()
        assert proc.terminated is True
        assert manager._ide is None
    finally:
        manager.close()


def test_ide_project_must_be_an_existing_folder(tmp_path):
    manager = DesktopRuntimeManager(tmp_path)
    try:
        with pytest.raises(DesktopRuntimeError, match="folder does not exist"):
            manager._ide_ui_url(tmp_path / "missing")
        with pytest.raises(DesktopRuntimeError, match="local folder path"):
            manager._ide_ui_url(["--host", "0.0.0.0"])
    finally:
        manager.close()


def test_snapshot_reports_ide_probe_and_close_stops_managed_process(tmp_path, monkeypatch):
    class Process:
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "native"}})
    proc = Process()
    manager._ide = proc
    monkeypatch.setattr(manager, "_probe", lambda timeout=1.5: (False, "ollama offline"))
    monkeypatch.setattr(manager, "_probe_ide", lambda timeout=1.5: (True, ""))
    monkeypatch.setattr(
        "daedalus.desktop_runtime.shutil.which",
        lambda command: r"C:\tools\openvscode-server.cmd"
        if command == "openvscode-server"
        else None,
    )

    snapshot = manager.snapshot()
    assert snapshot["services"]["ide"] == {
        "endpoint": "http://127.0.0.1:3000",
        "ui_url": "http://127.0.0.1:3000/",
        "installed": True,
        "available": True,
        "executable": r"C:\tools\openvscode-server.cmd",
        "reachable": True,
        "last_error": "",
        "detail": "",
        "managed": True,
        "process_running": True,
        "configured_executable": "",
        "runtime_downloads": False,
    }

    manager.close()
    assert proc.terminated is True
    assert manager._ide is None


def test_ide_status_reports_missing_binary_without_start_or_download(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "native"}})
    monkeypatch.setattr(manager, "_probe_ide", lambda timeout=1.5: (False, "offline"))
    monkeypatch.setattr("daedalus.desktop_runtime.shutil.which", lambda command: None)
    monkeypatch.setattr(
        "daedalus.desktop_runtime.subprocess.Popen",
        lambda *args, **kwargs: pytest.fail("status must not start a process"),
    )
    try:
        status = manager._ide_status()
        assert status["installed"] is False
        assert status["available"] is False
        assert status["executable"] == ""
        assert "not on PATH" in status["detail"]
        assert "runtime downloads are disabled" in status["last_error"]
        assert status["runtime_downloads"] is False
    finally:
        manager.close()


def test_ide_status_reports_configured_executable_while_service_is_offline(
    tmp_path, monkeypatch
):
    executable = tmp_path / "tools" / "openvscode-server"
    executable.parent.mkdir()
    executable.write_text("", encoding="utf-8")
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config(
        {"ide": {"mode": "native", "executable": str(executable)}}
    )
    monkeypatch.setattr(manager, "_probe_ide", lambda timeout=1.5: (False, "offline"))
    try:
        status = manager._ide_status()
        assert status["installed"] is True
        assert status["available"] is True
        assert status["executable"] == str(executable.resolve())
        assert status["reachable"] is False
        assert status["last_error"] == "offline"
        assert status["detail"] == ""
    finally:
        manager.close()


def test_docker_ide_config_is_strictly_allowlisted_and_pinned():
    cfg = normalize_config(
        {
            "ide": {
                "mode": "docker",
                "docker_image": "gitpod/openvscode-server@sha256:" + "a" * 64,
            }
        }
    )
    assert cfg["ide"]["docker_image"].endswith("a" * 64)

    for ide in (
        {"mode": "compose"},
        {"mode": "docker", "endpoint": "http://127.0.0.1:3001"},
        {"mode": "docker", "docker_image": "alpine:latest"},
        {"mode": "docker", "docker_image": "gitpod/openvscode-server:latest"},
        {"mode": "docker", "command": "calc.exe"},
        {"mode": "docker", "executable": r"C:\evil.exe"},
    ):
        with pytest.raises(ValueError):
            normalize_config({"ide": ide})


def _owned_docker_container(manager, project, *, running=True, owned=True):
    labels = {
        IDE_DOCKER_PROJECT_LABEL: manager._docker_project_hash(project.resolve()),
    }
    if owned:
        labels[IDE_DOCKER_OWNER_LABEL] = IDE_DOCKER_OWNER_VALUE
    return {
        "Id": "f" * 64,
        "Config": {
            "Image": manager.config["ide"]["docker_image"],
            "Labels": labels,
        },
        "State": {"Running": running},
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(project.resolve()),
                "Destination": IDE_DOCKER_WORKSPACE,
                "RW": True,
            }
        ],
        "HostConfig": {
            "PortBindings": {
                "3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3000"}]
            }
        },
    }


def test_docker_exec_is_argument_only_and_never_uses_shell(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    launched = {}
    monkeypatch.setattr(
        "daedalus.desktop_runtime.shutil.which",
        lambda command: r"C:\Program Files\Docker\docker.exe" if command == "docker" else None,
    )

    def run(args, **kwargs):
        launched["args"] = args
        launched["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr("daedalus.desktop_runtime.subprocess.run", run)
    result = manager._docker_exec(["image", "inspect", IDE_DOCKER_IMAGE])
    assert result.returncode == 0
    assert launched["args"] == [
        r"C:\Program Files\Docker\docker.exe",
        "image",
        "inspect",
        IDE_DOCKER_IMAGE,
    ]
    assert launched["kwargs"]["shell"] is False
    manager.close()


def test_docker_ide_mounts_canonical_project_and_owns_exact_lifecycle(
    tmp_path, monkeypatch
):
    project = tmp_path / "project with spaces"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    created = False
    calls = []

    def docker_exec(args, **kwargs):
        nonlocal created
        calls.append(list(args))
        if args[:2] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        if args[:2] == ["container", "inspect"]:
            if not created:
                return SimpleNamespace(
                    returncode=1, stdout="", stderr="Error: No such container"
                )
            payload = [_owned_docker_container(manager, project)]
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        if args and args[0] == "run":
            created = True
            return SimpleNamespace(returncode=0, stdout="container-id", stderr="")
        if args[:3] == ["container", "rm", "--force"]:
            created = False
            return SimpleNamespace(returncode=0, stdout=IDE_DOCKER_CONTAINER, stderr="")
        raise AssertionError(f"unexpected Docker command: {args!r}")

    probes = iter(((False, "offline"), (True, ""), (True, "")))
    # The fake Docker boundary is complete only when discovery is fake too.
    # Windows and Linux runners happen to carry a Docker CLI, while the macOS
    # bundle runner does not; relying on the host executable made the status
    # half of this otherwise hermetic lifecycle test platform-dependent.
    monkeypatch.setattr(manager, "_discover_docker_executable", lambda: "docker")
    monkeypatch.setattr(manager, "_docker_exec", docker_exec)
    monkeypatch.setattr(manager, "_probe_ide", lambda timeout=1.5: next(probes))
    monkeypatch.setattr(
        "daedalus.desktop_runtime.subprocess.Popen",
        lambda *args, **kwargs: pytest.fail("Docker mode must not use Popen"),
    )

    status = manager.ensure_ide(project / ".")
    run = next(args for args in calls if args and args[0] == "run")
    mount = run[run.index("--mount") + 1]
    assert mount == (
        f"type=bind,source={project.resolve()},target={IDE_DOCKER_WORKSPACE}"
    )
    assert run[run.index("--publish") + 1] == "127.0.0.1:3000:3000"
    assert run[run.index("--pull") + 1] == "never"
    assert run[run.index("--name") + 1] == IDE_DOCKER_CONTAINER
    assert run[-5:] == [
        IDE_DOCKER_IMAGE,
        "--port",
        "3000",
        "--default-folder",
        IDE_DOCKER_WORKSPACE,
    ]
    assert all(args[0] not in {"pull", "build"} for args in calls)
    assert parse_qs(urlsplit(status["ui_url"]).query) == {
        "folder": [IDE_DOCKER_WORKSPACE]
    }
    assert status["reachable"] is True
    assert status["managed"] is True
    assert status["executable"] == "docker"

    manager.stop_ide()
    assert ["container", "rm", "--force", "f" * 64] in calls
    assert created is False
    manager.close()


def test_docker_ide_refuses_foreign_container_and_missing_local_image(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    foreign = _owned_docker_container(manager, project, owned=False)
    monkeypatch.setattr(manager, "_docker_image_error", lambda: "")
    monkeypatch.setattr(manager, "_docker_inspect_container", lambda: foreign)
    monkeypatch.setattr(
        manager,
        "_docker_exec",
        lambda *args, **kwargs: pytest.fail("foreign container must never be mutated"),
    )
    with pytest.raises(DesktopRuntimeError, match="already in use"):
        manager.ensure_ide(project)
    manager.stop_ide()

    monkeypatch.setattr(
        manager,
        "_docker_image_error",
        lambda: "image is not available locally; runtime pull/build is disabled",
    )
    with pytest.raises(DesktopRuntimeError, match="runtime pull/build is disabled"):
        manager.ensure_ide(project)
    manager.close()


def test_docker_ide_status_honestly_reports_missing_docker(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    monkeypatch.setattr(manager, "_probe_ide", lambda timeout=1.5: (False, "offline"))
    monkeypatch.setattr("daedalus.desktop_runtime.shutil.which", lambda command: None)
    status = manager._ide_status()
    assert status["installed"] is False
    assert status["available"] is False
    assert status["managed"] is False
    assert status["reachable"] is False
    assert "Docker is not installed" in status["last_error"]
    assert status["runtime_downloads"] is False
    manager.close()


def test_docker_status_does_not_adopt_lifecycle_ownership(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    container = _owned_docker_container(manager, project)
    monkeypatch.setattr(manager, "_probe_ide", lambda timeout=1.5: (True, ""))
    monkeypatch.setattr(manager, "_docker_image_error", lambda: "")
    monkeypatch.setattr(manager, "_discover_docker_executable", lambda: "docker")
    monkeypatch.setattr(manager, "_docker_inspect_container", lambda *args, **kwargs: container)

    status = manager._docker_ide_status(project)

    assert status["reachable"] is True
    assert status["detail"] == ""
    assert manager._ide_docker_managed_id is None


def test_ensure_docker_ide_recovers_matching_orphan_before_adopting_it(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    container = _owned_docker_container(manager, project)
    calls = []
    monkeypatch.setattr(manager, "_probe_ide", lambda timeout=1.5: (True, ""))
    monkeypatch.setattr(manager, "_docker_image_error", lambda: "")
    monkeypatch.setattr(manager, "_discover_docker_executable", lambda: "docker")
    monkeypatch.setattr(
        manager,
        "_docker_inspect_container",
        lambda reference=IDE_DOCKER_CONTAINER, **kwargs: container,
    )

    def docker_exec(args, **kwargs):
        calls.append(list(args))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(manager, "_docker_exec", docker_exec)
    status = manager.ensure_ide(project)

    assert status["reachable"] is True
    assert manager._ide_docker_managed_id == "f" * 64
    assert not any(args and args[0] in {"run", "start"} for args in calls)
    manager.close(strict=True)
    assert ["container", "rm", "--force", "f" * 64] in calls


def test_docker_match_requires_exact_canonical_mount_source(tmp_path):
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    container = _owned_docker_container(manager, project)
    container["Mounts"][0]["Source"] = str(other.resolve())

    assert manager._docker_container_matches(container, project.resolve()) is False


def test_strict_docker_cleanup_propagates_failure_and_uses_inspected_id(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    container = _owned_docker_container(manager, project)
    manager._ide_docker_managed_id = "f" * 64
    calls = []

    monkeypatch.setattr(
        manager,
        "_docker_inspect_container",
        lambda reference=IDE_DOCKER_CONTAINER, **kwargs: container,
    )

    def docker_exec(args, **kwargs):
        calls.append(list(args))
        return SimpleNamespace(returncode=1, stdout="", stderr="removal failed")

    monkeypatch.setattr(manager, "_docker_exec", docker_exec)
    with pytest.raises(DesktopRuntimeError, match="cannot remove"):
        manager.stop_ide(strict=True)
    assert calls == [["container", "rm", "--force", "f" * 64]]
    assert manager._ide_docker_managed_id == "f" * 64


def test_strict_docker_cleanup_refuses_replacement_container_id(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    replacement = _owned_docker_container(manager, project)
    replacement["Id"] = "e" * 64
    manager._ide_docker_managed_id = "f" * 64
    monkeypatch.setattr(
        manager,
        "_docker_inspect_container",
        lambda reference=IDE_DOCKER_CONTAINER, **kwargs: replacement,
    )
    monkeypatch.setattr(
        manager,
        "_docker_exec",
        lambda *args, **kwargs: pytest.fail("replacement container must not be removed"),
    )

    with pytest.raises(DesktopRuntimeError, match="identity changed"):
        manager.stop_ide(strict=True)


def test_web_integration_resolves_registered_ide_name_before_manager(
    tmp_path, monkeypatch
):
    registry = tmp_path / "projects"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(projects, "PROJECT_DIR", registry)
    projects.register_project(repo, "demo")

    class BaseHandler:
        path = ""
        body = None

        def _send_json(self, payload, status=200):
            self.sent = (payload, status)

        def _handle_post(self):
            self.fell_through = True

    class Manager:
        def __init__(self):
            self.started = []
            self.stopped = False
            self.closed = False
            self.close_error = False

        def ensure_ide(self, project=None):
            self.started.append(project)
            return {"ui_url": "http://127.0.0.1:3000/"}

        def stop_ide(self, **kwargs):
            self.stopped = True

        def close(self, **kwargs):
            self.closed = True
            if self.close_error:
                raise DesktopRuntimeError("cleanup failed")

        def snapshot(self):
            return {"services": {"ide": {"reachable": False}}}

    manager = Manager()
    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        _read_body=lambda handler: handler.body,
        core=SimpleNamespace(envelope=lambda project, **payload: payload),
    )
    install_web_integration(web_api, manager)

    start = web_api.DaedalusHandler()
    start.path = "/api/desktop/services/ide/start"
    start.body = {"project": "demo"}
    start._handle_post()
    assert manager.started == [str(repo.resolve())]
    assert start.sent == ({"service": {"ui_url": "http://127.0.0.1:3000/"}}, 200)

    for unregistered in (str(repo), "../demo", "missing", "", None, {"name": "demo"}):
        rejected = web_api.DaedalusHandler()
        rejected.path = "/api/desktop/services/ide/start"
        rejected.body = {"project": unregistered}
        rejected._handle_post()
        assert rejected.sent[1] == 400
        assert rejected.sent[0]["ok"] is False
        assert manager.started == [str(repo.resolve())]

    (registry / "broken.json").write_text("{not-json", encoding="utf-8")
    unavailable = web_api.DaedalusHandler()
    unavailable.path = "/api/desktop/services/ide/start"
    unavailable.body = {"project": "broken"}
    unavailable._handle_post()
    assert unavailable.sent[1] == 503
    assert manager.started == [str(repo.resolve())]

    stop = web_api.DaedalusHandler()
    stop.path = "/api/desktop/services/ide/stop"
    stop._handle_post()
    assert manager.stopped is True
    assert stop.sent == ({"service": {"reachable": False}}, 200)

    for supplied in ("", "b" * 64):
        rejected = web_api.DaedalusHandler()
        rejected.path = "/api/desktop/shutdown"
        rejected.server = SimpleNamespace(daedalus_desktop_startup_nonce="a" * 64)
        rejected.headers = (
            {"X-Daedalus-Desktop-Nonce": supplied} if supplied else {}
        )
        rejected._handle_post()
        assert manager.closed is False
        assert rejected.sent == (
            {"ok": False, "error": "desktop parent nonce required"},
            403,
        )

    shutdown = web_api.DaedalusHandler()
    shutdown.path = "/api/desktop/shutdown"
    shutdown.server = SimpleNamespace(daedalus_desktop_startup_nonce="a" * 64)
    shutdown.headers = {"X-Daedalus-Desktop-Nonce": "a" * 64}
    shutdown._handle_post()
    assert manager.closed is True
    assert shutdown.sent == ({"service": {"closed": True}}, 200)

    manager.close_error = True
    failed = web_api.DaedalusHandler()
    failed.path = "/api/desktop/shutdown"
    failed.server = SimpleNamespace(daedalus_desktop_startup_nonce="a" * 64)
    failed.headers = {"X-Daedalus-Desktop-Nonce": "a" * 64}
    failed._handle_post()
    assert failed.sent == ({"ok": False, "error": "cleanup failed"}, 400)

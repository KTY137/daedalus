from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from daedalus import budget as budget_kernel
from daedalus import desktop_runtime as desktop_runtime_module
from daedalus import file_bridge
from daedalus.foundation import projects
from daedalus import sensitivity
from daedalus.interfaces.desktop import effects as desktop_effects
from daedalus.spine.killswitch import ENV_SWITCH_PATH, KillSwitch
from daedalus.limit_policy import (
    ExecutionLimitPolicy,
    LIMIT_AXES,
    LimitAxes,
    MODE_CUSTOM,
    MODE_UNBOUNDED_EXECUTION,
)
from daedalus.desktop_runtime import (
    IDE_DOCKER_IMAGE,
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
    ENV_SWITCH_PATH,
)


@pytest.fixture(autouse=True)
def restore_runtime_env(tmp_path):
    before = {key: os.environ.get(key) for key in _RUNTIME_ENV}
    os.environ[budget_kernel.ENV_LEDGER] = str(tmp_path / "desktop-budget.json")
    permit = tmp_path / "operator-armed-desktop-switch"
    KillSwitch(permit).arm(note="desktop test operator")
    os.environ[ENV_SWITCH_PATH] = str(permit)
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
    monkeypatch.setattr(
        manager,
        "_ide_status",
        lambda project=None, **kwargs: {
            "reachable": False,
            "last_error": "offline",
        },
    )


def test_desktop_runtime_has_no_managed_ollama_environment_builder():
    assert not hasattr(desktop_runtime_module, "_ollama_child_environment")


def test_desktop_runtime_has_no_managed_process_constructor():
    assert not hasattr(desktop_runtime_module, "ManagedProcess")


def test_desktop_runtime_has_no_dll_spawn_shim():
    assert not hasattr(desktop_runtime_module, "_set_windows_dll_directory")


def test_desktop_runtime_has_no_ollama_spawn_function():
    assert not hasattr(desktop_runtime_module, "_spawn_ollama_process")


def test_defaults_disable_all_managed_desktop_autostart():
    cfg = normalize_config({})
    assert cfg["bridge"]["auto_start"] is False
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
    assert cfg["ollama"]["auto_start"] is False
    assert cfg["ollama"]["mode"] == "local"

    migrated = normalize_config(
        {
            "bridge": {"auto_start": True},
            "ollama": {"auto_start": True},
            "ide": {"auto_start": True},
        }
    )
    assert migrated["bridge"]["auto_start"] is False
    assert migrated["ollama"]["auto_start"] is False
    assert migrated["ide"]["auto_start"] is False


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


def test_repeated_bridge_start_requests_refuse_without_starting_a_thread(
    tmp_path, monkeypatch
):
    manager = DesktopRuntimeManager(tmp_path)
    starts: list[object] = []
    monkeypatch.setattr(
        file_bridge,
        "watch",
        lambda *args, **kwargs: starts.append((args, kwargs)),
    )
    try:
        for _ in range(2):
            with pytest.raises(
                desktop_effects.DesktopEffectRefused,
                match="Managed bridge start is unavailable",
            ):
                manager.ensure_bridge()
        assert starts == []
        assert not hasattr(manager, "_bridge")
    finally:
        manager.close()


def test_bridge_start_post_returns_structured_refusal_without_watcher(
    tmp_path, monkeypatch
):
    manager = DesktopRuntimeManager(tmp_path)
    starts: list[object] = []
    monkeypatch.setattr(
        file_bridge,
        "watch",
        lambda *args, **kwargs: starts.append((args, kwargs)),
    )

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
        runtime_registry=SimpleNamespace(reset_status_cache=lambda: None),
    )
    install_web_integration(web_api, manager)

    try:
        request = web_api.DaedalusHandler()
        request.path = "/api/desktop/services/bridge/start"
        request._handle_post()

        refusal, status = request.sent
        assert status == 409
        assert refusal["ok"] is False
        assert refusal["error_code"] == "desktop_feature_unavailable"
        assert refusal["committed"] is False
        assert "Managed bridge start is unavailable" in refusal["error"]
        assert starts == []
        assert not hasattr(manager, "_bridge")
    finally:
        manager.close()


def test_live_external_bridge_status_is_observed_but_never_adopted(
    tmp_path, monkeypatch
):
    manager = DesktopRuntimeManager(tmp_path)
    external_pid = os.getpid() + 100_000
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
    try:
        status = manager.snapshot()["services"]["bridge"]
        assert status["managed"] is False
        assert status["pid"] == external_pid
        assert status["managed_start_available"] is False
        assert not hasattr(manager, "_bridge")
    finally:
        manager.close()


def test_bridge_heartbeat_identity_is_never_adopted_as_owned(
    tmp_path,
):
    manager = DesktopRuntimeManager(tmp_path)
    manager._bridge_owner_token = "new-owner-token"
    manager._bridge_process_identity = "new-process-identity"
    manager._bridge = SimpleNamespace(is_alive=lambda: True)
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
        ) is False
    finally:
        manager._bridge = None
        manager.close()


def test_bridge_start_refusal_never_reports_managed(tmp_path, monkeypatch):
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
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Managed bridge start is unavailable",
        ):
            manager.ensure_bridge()
        status = manager.snapshot()["services"]["bridge"]
        assert status["managed"] is False
        assert status["state"] == "none"
        assert status["managed_start_available"] is False
        assert not hasattr(manager, "_bridge")
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


def test_legacy_bridge_autostart_is_persisted_as_disabled_without_start(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    proposed = json.loads(json.dumps(manager.config))
    proposed["bridge"]["auto_start"] = True
    proposed["ollama"]["model"] = "owner-selected-model"
    monkeypatch.setattr(
        manager._effect_owner,
        "start_bridge",
        lambda: pytest.fail("settings must not start the bridge"),
    )
    try:
        snapshot = manager.save_settings(proposed)
        persisted = json.loads(manager.config_path.read_text(encoding="utf-8"))

        assert persisted["ollama"]["model"] == "owner-selected-model"
        assert persisted["bridge"]["auto_start"] is False
        assert os.environ["OLLAMA_MODEL"] == "owner-selected-model"
        assert snapshot["config"]["ollama"]["model"] == "owner-selected-model"
        assert "startup_error" not in snapshot
    finally:
        manager.close()


def test_bootstrap_never_calls_managed_start_ports(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    starts: list[str] = []
    for name in ("start_bridge", "start_ollama", "start_ide"):
        monkeypatch.setattr(
            manager._effect_owner,
            name,
            lambda *args, _name=name, **kwargs: starts.append(_name),
        )
    try:
        snapshot = manager.bootstrap()
        assert starts == []
        assert snapshot["config"]["bridge"]["auto_start"] is False
        assert snapshot["config"]["ollama"]["auto_start"] is False
        assert snapshot["config"]["ide"]["auto_start"] is False
    finally:
        manager.close()


def test_legacy_service_autostarts_are_normalized_without_readiness_calls(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    proposed = json.loads(json.dumps(manager.config))
    proposed["bridge"]["auto_start"] = True
    proposed["ollama"]["auto_start"] = True
    proposed["ide"]["auto_start"] = True
    proposed["ollama"]["model"] = "persisted-before-readiness"
    starts: list[str] = []
    for name in ("start_bridge", "start_ollama", "start_ide"):
        monkeypatch.setattr(
            manager._effect_owner,
            name,
            lambda *args, _name=name, **kwargs: starts.append(_name),
        )
    try:
        snapshot = manager.save_settings(proposed)

        saved = json.loads(manager.config_path.read_text(encoding="utf-8"))
        assert saved["ollama"]["model"] == "persisted-before-readiness"
        assert saved["bridge"]["auto_start"] is False
        assert saved["ollama"]["auto_start"] is False
        assert saved["ide"]["auto_start"] is False
        assert starts == []
        assert "startup_error" not in snapshot
    finally:
        manager.close()


def test_source_web_cli_wires_settings_get_put_and_closes_manager(
        tmp_path, monkeypatch):
    from daedalus.interfaces.cli import entry as cli_entry
    from daedalus.interfaces.http import web_api

    manager_type = DesktopRuntimeManager
    observed = {"responses": [], "lifecycle": []}
    install_integration = desktop_runtime_module.install_web_integration
    monkeypatch.chdir(tmp_path)

    def manager_factory(root):
        observed["lifecycle"].append("manager")
        observed["root"] = root
        manager = manager_type(root)
        quiet_status(manager, monkeypatch)
        close = manager.close

        def bootstrap():
            observed["lifecycle"].append("bootstrap")

        def close_manager():
            observed["lifecycle"].append("close")
            close()

        manager.bootstrap = bootstrap
        manager.close = close_manager
        observed["manager"] = manager
        return manager

    def install(module, manager):
        observed["lifecycle"].append("settings_integration")
        install_integration(module, manager)

    def fake_run(
        host,
        port,
        *,
        allow_remote_clients=False,
        on_bound=None,
        authority_root=None,
    ):
        observed["lifecycle"].append("bound")
        observed["bind"] = (host, port, allow_remote_clients)
        observed["server_authority_root"] = authority_root
        assert on_bound is not None
        on_bound()
        observed["lifecycle"].append("serve")
        get = object.__new__(web_api.DaedalusHandler)
        get.path = "/api/desktop/settings"
        get._send_json = lambda payload, status=200: observed["responses"].append(
            ("GET", status, payload)
        )
        get._handle_get()

        manager = observed["manager"]
        proposed = json.loads(json.dumps(manager.config))
        proposed["bridge"]["auto_start"] = False
        proposed["ollama"]["auto_start"] = False
        proposed["ide"]["auto_start"] = False
        proposed["ollama"]["model"] = "source-web-model"
        put = object.__new__(web_api.DaedalusHandler)
        put.path = "/api/desktop/settings"
        put.body = proposed
        put._send_json = lambda payload, status=200: observed["responses"].append(
            ("PUT", status, payload)
        )
        put._handle_put()
        raise RuntimeError("server stopped")

    def fake_main(argv, *, on_bound=None, authority_root=None):
        observed["lifecycle"].append("main")
        observed["argv"] = argv
        observed["main_authority_root"] = authority_root
        web_api.run(
            "127.0.0.1",
            9876,
            allow_remote_clients=False,
            on_bound=on_bound,
            authority_root=authority_root,
        )

    original_handler = web_api.DaedalusHandler
    monkeypatch.setattr(web_api, "DaedalusHandler", original_handler)
    monkeypatch.setattr(web_api, "run", fake_run)
    monkeypatch.setattr(web_api, "_read_body", lambda handler: handler.body)
    monkeypatch.setattr(web_api, "main", fake_main)
    monkeypatch.setattr(
        desktop_runtime_module,
        "DesktopRuntimeManager",
        manager_factory,
    )
    monkeypatch.setattr(
        desktop_runtime_module,
        "install_tunnel_egress_policy",
        lambda: observed["lifecycle"].append("tunnel_policy"),
    )
    monkeypatch.setattr(
        desktop_runtime_module,
        "install_web_integration",
        install,
    )

    with pytest.raises(RuntimeError, match="server stopped"):
        cli_entry._web(["--port", "9876"])

    manager = observed["manager"]
    assert observed["root"] == tmp_path.resolve()
    assert observed["main_authority_root"] == tmp_path.resolve()
    assert observed["server_authority_root"] == tmp_path.resolve()
    assert observed["argv"] == ["--port", "9876"]
    assert observed["lifecycle"] == [
        "manager",
        "tunnel_policy",
        "settings_integration",
        "main",
        "bound",
        "bootstrap",
        "serve",
        "close",
    ]
    assert observed["bind"] == ("127.0.0.1", 9876, False)
    assert [(method, status) for method, status, _ in observed["responses"]] == [
        ("GET", 200),
        ("PUT", 200),
    ]
    assert observed["responses"][0][2]["desktop"]["config_path"] == str(
        tmp_path.resolve() / "config" / "connections.json"
    )
    assert observed["responses"][1][2]["desktop"]["config"]["ollama"][
        "model"
    ] == "source-web-model"
    assert json.loads(manager.config_path.read_text(encoding="utf-8"))[
        "ollama"
    ]["model"] == "source-web-model"
    assert manager._closed is True
    assert web_api.DaedalusHandler is original_handler
    assert web_api.run is fake_run


def test_source_web_cli_closes_and_restores_handler_when_bootstrap_fails(
        tmp_path, monkeypatch):
    from daedalus.interfaces.cli import entry as cli_entry
    from daedalus.interfaces.http import web_api

    lifecycle = []
    original_handler = web_api.DaedalusHandler
    monkeypatch.chdir(tmp_path)

    class Manager:
        def bootstrap(self):
            lifecycle.append("bootstrap")
            raise DesktopRuntimeError("autostart failed")

        def close(self):
            lifecycle.append("close")

    def install(module, manager):
        lifecycle.append("settings_integration")

        class ManagedHandler(original_handler):
            pass

        module.DaedalusHandler = ManagedHandler

    def fake_run(*args, on_bound=None, **kwargs):
        lifecycle.append("bound")
        assert on_bound is not None
        on_bound()
        pytest.fail("serve must not follow a bootstrap failure")

    def fake_main(argv, *, on_bound=None, authority_root=None):
        lifecycle.append("main")
        assert authority_root == tmp_path.resolve()
        web_api.run(
            "127.0.0.1",
            8765,
            on_bound=on_bound,
            authority_root=authority_root,
        )

    monkeypatch.setattr(web_api, "DaedalusHandler", original_handler)
    monkeypatch.setattr(web_api, "run", fake_run)
    monkeypatch.setattr(web_api, "main", fake_main)
    monkeypatch.setattr(
        desktop_runtime_module,
        "DesktopRuntimeManager",
        lambda root: Manager(),
    )
    monkeypatch.setattr(
        desktop_runtime_module,
        "install_tunnel_egress_policy",
        lambda: lifecycle.append("tunnel_policy"),
    )
    monkeypatch.setattr(
        desktop_runtime_module,
        "install_web_integration",
        install,
    )

    with pytest.raises(DesktopRuntimeError, match="autostart failed"):
        cli_entry._web([])

    assert lifecycle == [
        "tunnel_policy",
        "settings_integration",
        "main",
        "bound",
        "bootstrap",
        "close",
    ]
    assert web_api.DaedalusHandler is original_handler
    assert web_api.run is fake_run


def test_source_web_cli_refused_bind_never_bootstraps_services(monkeypatch):
    from daedalus.interfaces.cli import entry as cli_entry
    from daedalus.interfaces.http import web_api

    lifecycle = []

    class Manager:
        def bootstrap(self):
            lifecycle.append("bootstrap")

        def close(self):
            lifecycle.append("close")

    def manager_factory(root):
        lifecycle.append("manager")
        return Manager()

    monkeypatch.delenv(web_api.ALLOW_REMOTE_ENV, raising=False)
    monkeypatch.delenv(web_api.AUTH_TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        desktop_runtime_module,
        "DesktopRuntimeManager",
        manager_factory,
    )
    monkeypatch.setattr(
        desktop_runtime_module,
        "install_tunnel_egress_policy",
        lambda: lifecycle.append("tunnel_policy"),
    )
    monkeypatch.setattr(
        desktop_runtime_module,
        "install_web_integration",
        lambda module, manager: lifecycle.append("settings_integration"),
    )

    with pytest.raises(SystemExit) as stopped:
        cli_entry._web(["--host", "0.0.0.0"])

    assert stopped.value.code == 2
    assert lifecycle == [
        "manager",
        "tunnel_policy",
        "settings_integration",
        "close",
    ]


def test_packaged_sidecar_bootstraps_after_bound_and_closes_on_failure(
        tmp_path, monkeypatch):
    from daedalus import budget
    from daedalus.foundation import env as foundation_env
    from daedalus.interfaces.desktop import sidecar as sidecar_owner
    from daedalus.interfaces.http import web_api
    from daedalus.spine import effect_boundary
    from scripts import daedalus_desktop_sidecar as sidecar

    lifecycle = []
    process_guard_decision = object()

    class Manager:
        def __init__(self, root):
            lifecycle.append(("manager", root))

        def bootstrap(self):
            lifecycle.append("bootstrap")

        def close(self):
            lifecycle.append("close")

    def fake_main(argv, *, on_bound=None):
        lifecycle.append(("main", argv))
        lifecycle.append("bound")
        assert on_bound is not None
        on_bound()
        raise RuntimeError("server stopped")

    def fake_prepare_runtime():
        lifecycle.append("prepare_runtime")
        return tmp_path

    monkeypatch.setattr(
        budget,
        "process_guard_boundary_decision",
        lambda: lifecycle.append("process_guard") or process_guard_decision,
    )
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda entrypoint_id, effects, decisions: lifecycle.append(
            ("begin", entrypoint_id, effects, tuple(decisions))
        ),
    )
    monkeypatch.setattr(sidecar_owner, "prepare_runtime", fake_prepare_runtime)
    monkeypatch.setattr(
        sidecar_owner.os,
        "chdir",
        lambda root: lifecycle.append(("chdir", root)),
    )
    monkeypatch.setattr(
        foundation_env,
        "load_env",
        lambda path: lifecycle.append(("load_env", path)),
    )
    monkeypatch.setattr(desktop_runtime_module, "DesktopRuntimeManager", Manager)
    monkeypatch.setattr(
        desktop_runtime_module,
        "install_tunnel_egress_policy",
        lambda: lifecycle.append("tunnel_policy"),
    )
    monkeypatch.setattr(
        desktop_runtime_module,
        "install_web_integration",
        lambda module, manager: lifecycle.append("settings_integration"),
    )
    monkeypatch.setattr(web_api, "main", fake_main)

    with pytest.raises(RuntimeError, match="server stopped"):
        sidecar.main(["--port", "9876"])

    assert lifecycle == [
        "process_guard",
        (
            "begin",
            "cli.desktop_sidecar",
            effect_boundary.REGISTRY_BY_ID["cli.desktop_sidecar"].effects,
            (process_guard_decision,),
        ),
        "prepare_runtime",
        ("chdir", tmp_path),
        ("load_env", tmp_path / ".env"),
        ("manager", tmp_path),
        "tunnel_policy",
        "settings_integration",
        ("main", ["--port", "9876"]),
        "bound",
        "bootstrap",
        "close",
    ]


def test_packaged_sidecar_refusal_precedes_runtime_mutation(monkeypatch):
    from daedalus import budget
    from daedalus.interfaces.desktop import sidecar as sidecar_owner
    from daedalus.spine import effect_boundary
    from scripts import daedalus_desktop_sidecar as sidecar

    lifecycle = []
    decision = object()
    monkeypatch.setattr(
        budget,
        "process_guard_boundary_decision",
        lambda: lifecycle.append("process_guard") or decision,
    )

    def refuse(*args):
        lifecycle.append(("begin", args))
        raise RuntimeError("desktop bootstrap refused")

    monkeypatch.setattr(effect_boundary, "begin_effect", refuse)
    monkeypatch.setattr(
        sidecar_owner,
        "prepare_runtime",
        lambda: lifecycle.append("prepare_runtime"),
    )

    with pytest.raises(RuntimeError, match="desktop bootstrap refused"):
        sidecar.main([])

    assert lifecycle == [
        "process_guard",
        (
            "begin",
            (
                "cli.desktop_sidecar",
                effect_boundary.REGISTRY_BY_ID["cli.desktop_sidecar"].effects,
                (decision,),
            ),
        ),
    ]


def test_web_api_occupied_port_never_calls_bound_lifecycle(monkeypatch):
    from daedalus.interfaces.http import web_api

    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    port = occupied.getsockname()[1]
    lifecycle = []
    monkeypatch.setattr(web_api, "load_env", lambda: None)
    try:
        with pytest.raises(OSError):
            web_api.run(
                "127.0.0.1",
                port,
                on_bound=lambda: lifecycle.append("bootstrap"),
            )
    finally:
        occupied.close()

    assert lifecycle == []


def test_web_api_closes_bound_socket_when_lifecycle_callback_fails(monkeypatch):
    from daedalus.interfaces.http import web_api

    lifecycle = []

    class BoundServer:
        daedalus_auth_token = ""
        daedalus_desktop_startup_nonce = ""

        def __init__(self, address, handler):
            lifecycle.append(("bound", address, handler))

        def serve_forever(self):
            lifecycle.append("serve")

        def server_close(self):
            lifecycle.append("server_close")

    def fail_bootstrap():
        lifecycle.append("bootstrap")
        raise DesktopRuntimeError("autostart failed")

    monkeypatch.setattr(web_api, "ThreadingHTTPServer", BoundServer)
    monkeypatch.setattr(web_api, "load_env", lambda: None)

    with pytest.raises(DesktopRuntimeError, match="autostart failed"):
        web_api.run("127.0.0.1", 8765, on_bound=fail_bootstrap)

    assert lifecycle == [
        ("bound", ("127.0.0.1", 8765), web_api.DaedalusHandler),
        "bootstrap",
        "server_close",
    ]


def test_concurrent_settings_puts_serialize_through_confirming_snapshot(
        tmp_path, monkeypatch):
    from daedalus.interfaces.http import web_api

    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    original_handler = web_api.DaedalusHandler
    first_at_snapshot = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_saved = threading.Event()
    responses = {}
    errors = []
    real_authorize = manager._effect_owner._authorize_settings

    def observed_authorize(request, prepared):
        result = real_authorize(request, prepared)
        if prepared["ollama"]["model"] == "second-model":
            second_saved.set()
        return result

    def controlled_snapshot():
        if manager.config["ollama"]["model"] == "first-model":
            first_at_snapshot.set()
            if not release_first.wait(timeout=3):
                raise AssertionError("timed out waiting to release first PUT")
        return {"config": json.loads(json.dumps(manager.config))}

    monkeypatch.setattr(
        manager._effect_owner,
        "_authorize_settings",
        observed_authorize,
    )
    monkeypatch.setattr(
        manager._effect_owner,
        "_detached_snapshot",
        controlled_snapshot,
    )
    monkeypatch.setattr(web_api, "_read_body", lambda handler: handler.body)
    install_web_integration(web_api, manager)

    def put(label, model):
        if label == "second":
            second_started.set()
        try:
            proposed = json.loads(json.dumps(manager.config))
            proposed["bridge"]["auto_start"] = False
            proposed["ollama"]["auto_start"] = False
            proposed["ide"]["auto_start"] = False
            proposed["ollama"]["model"] = model
            handler = object.__new__(web_api.DaedalusHandler)
            handler.path = "/api/desktop/settings"
            handler.body = proposed
            handler._send_json = lambda payload, status=200: responses.setdefault(
                label, (status, payload)
            )
            handler._handle_put()
        except BaseException as exc:  # surfaced after joining the worker
            errors.append(exc)

    first = threading.Thread(target=put, args=("first", "first-model"))
    second = threading.Thread(target=put, args=("second", "second-model"))
    try:
        first.start()
        assert first_at_snapshot.wait(timeout=3)
        second.start()
        assert second_started.wait(timeout=3)
        assert not second_saved.wait(timeout=0.2)
        release_first.set()
        first.join(timeout=3)
        second.join(timeout=3)

        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []
        assert responses["first"][0] == 200
        assert responses["second"][0] == 200
        assert responses["first"][1]["desktop"]["config"]["ollama"][
            "model"
        ] == "first-model"
        assert responses["second"][1]["desktop"]["config"]["ollama"][
            "model"
        ] == "second-model"
    finally:
        release_first.set()
        first.join(timeout=3)
        if second.ident is not None:
            second.join(timeout=3)
        web_api.DaedalusHandler = original_handler
        manager.close()


@pytest.mark.parametrize("section_update", [False, True])
def test_effect_admission_uses_prospective_local_route_for_settings_payloads(
        section_update):
    manager = SimpleNamespace(config=normalize_config(remote_config()))
    local_ollama = json.loads(json.dumps(normalize_config({})["ollama"]))
    local_ollama["local_host"] = "http://127.0.0.1:11436"
    payload = {"ollama": local_ollama}
    if section_update:
        payload = {"section_updates": payload}

    assert desktop_effects._prospective_mode(manager, payload) == "local"
    assert desktop_effects._prospective_endpoints(manager, payload) == (
        "http://127.0.0.1:11436",
        manager.config["ide"]["endpoint"],
    )


def test_effect_admission_refuses_remote_section_update_before_operation(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    remote_ollama = normalize_config(remote_config())["ollama"]
    operation_called = False

    def operation(*args, **kwargs):
        nonlocal operation_called
        operation_called = True

    monkeypatch.setattr(desktop_effects, "acquire_effect_lease", operation)
    try:
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Remote SSH is unavailable",
        ):
            manager.save_settings(
                {"section_updates": {"ollama": remote_ollama}}
            )
    finally:
        manager.close()

    assert operation_called is False


def test_desktop_settings_route_atomically_merges_stale_owner_section_updates(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    baseline = json.loads(json.dumps(manager.config))
    baseline["bridge"]["auto_start"] = False
    baseline["ollama"]["auto_start"] = False
    baseline["ide"]["auto_start"] = False
    manager.save_settings(baseline)

    stale_connection = json.loads(json.dumps(manager.config))
    stale_caps = json.loads(json.dumps(manager.config))
    stale_connection["ollama"]["model"] = "connection-client-model"
    assert stale_caps["budget"]["max_calls"] > 1
    stale_caps["budget"]["max_calls"] -= 1
    stale_caps["caps"]["mode"] = MODE_CUSTOM
    payloads = {
        "connection": {
            "section_updates": {
                "bridge": stale_connection["bridge"],
                "ollama": stale_connection["ollama"],
            }
        },
        "caps": {
            "section_updates": {
                "budget": stale_caps["budget"],
                "caps": stale_caps["caps"],
            }
        },
    }

    class BaseHandler:
        path = ""
        body = None

        def _handle_put(self):
            self.fell_through = True

    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        _read_body=lambda handler: handler.body,
        core=SimpleNamespace(envelope=lambda project, **payload: payload),
        runtime_registry=SimpleNamespace(reset_status_cache=lambda: None),
    )
    install_web_integration(web_api, manager)

    first_at_snapshot = threading.Event()
    release_first = threading.Event()
    caps_started = threading.Event()
    caps_saved = threading.Event()
    responses = {}
    errors = []
    real_authorize = manager._effect_owner._authorize_settings
    real_snapshot = manager._effect_owner._detached_snapshot

    def observed_authorize(request, prepared):
        result = real_authorize(request, prepared)
        if (
            prepared["budget"]["max_calls"]
            == stale_caps["budget"]["max_calls"]
        ):
            caps_saved.set()
        return result

    def controlled_snapshot():
        snap = real_snapshot()
        if manager.config["ollama"]["model"] == "connection-client-model":
            first_at_snapshot.set()
            if not release_first.wait(timeout=3):
                raise AssertionError("timed out waiting to release connection PUT")
        return snap

    monkeypatch.setattr(
        manager._effect_owner,
        "_authorize_settings",
        observed_authorize,
    )
    monkeypatch.setattr(
        manager._effect_owner,
        "_detached_snapshot",
        controlled_snapshot,
    )

    def put(label):
        if label == "caps":
            caps_started.set()
        try:
            handler = web_api.DaedalusHandler()
            handler.path = "/api/desktop/settings"
            handler.body = payloads[label]
            handler._send_json = lambda payload, status=200: responses.setdefault(
                label, (status, payload)
            )
            handler._handle_put()
        except BaseException as exc:  # surfaced after joining the worker
            errors.append(exc)

    connection = threading.Thread(target=put, args=("connection",))
    caps = threading.Thread(target=put, args=("caps",))
    try:
        connection.start()
        assert first_at_snapshot.wait(timeout=3)
        caps.start()
        assert caps_started.wait(timeout=3)
        assert not caps_saved.wait(timeout=0.2)
        release_first.set()
        connection.join(timeout=3)
        caps.join(timeout=3)

        assert not connection.is_alive()
        assert not caps.is_alive()
        assert errors == []
        assert responses["connection"][0] == 200
        assert responses["caps"][0] == 200
        assert responses["connection"][1]["desktop"][
            "settings_update_contract"
        ] == "section_updates_v1"
        assert responses["caps"][1]["desktop"][
            "settings_update_contract"
        ] == "section_updates_v1"
        final = responses["caps"][1]["desktop"]["config"]
        assert final["ollama"]["model"] == "connection-client-model"
        assert final["budget"]["max_calls"] == stale_caps["budget"]["max_calls"]
        assert final["caps"]["mode"] == MODE_CUSTOM
        assert json.loads(
            manager.config_path.read_text(encoding="utf-8")
        ) == final
    finally:
        release_first.set()
        connection.join(timeout=3)
        if caps.ident is not None:
            caps.join(timeout=3)
        manager.close()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"section_updates": []}, "section_updates must be a JSON object"),
        ({"section_updates": {}}, "section_updates must contain at least one"),
        (
            {"section_updates": {"ide": {"auto_start": False}}},
            "unsupported settings section_updates: ide",
        ),
        (
            {
                "section_updates": {
                    "ide": {"endpoint": "http://example.com:3000"}
                }
            },
            "unsupported settings section_updates: ide",
        ),
        (
            {"section_updates": {"bridge": False}},
            "section_updates.bridge must be a JSON object",
        ),
        (
            {"section_updates": {"bridge": {}, "caps": {}}},
            "section_updates must target only one settings owner",
        ),
        (
            {
                "section_updates": {
                    "ollama": {"mode": "remote_ssh"},
                    "caps": {},
                }
            },
            "section_updates must target only one settings owner",
        ),
        (
            {"section_updates": {"bridge": {}}, "bridge": {}},
            "section_updates cannot be combined",
        ),
    ],
)
def test_invalid_section_update_route_leaves_settings_byte_identical(
        payload, message, tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    baseline = json.loads(json.dumps(manager.config))
    baseline["bridge"]["auto_start"] = False
    baseline["ollama"]["auto_start"] = False
    baseline["ide"]["auto_start"] = False
    manager.save_settings(baseline)
    before_config = json.loads(json.dumps(manager.config))
    before_bytes = manager.config_path.read_bytes()

    class BaseHandler:
        path = ""
        body = None

        def _send_json(self, response, status=200):
            self.sent = (status, response)

        def _handle_put(self):
            self.fell_through = True

    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        _read_body=lambda handler: handler.body,
        core=SimpleNamespace(envelope=lambda project, **response: response),
        runtime_registry=SimpleNamespace(reset_status_cache=lambda: None),
    )
    install_web_integration(web_api, manager)

    try:
        handler = web_api.DaedalusHandler()
        handler.path = "/api/desktop/settings"
        handler.body = payload
        handler._handle_put()

        assert handler.sent[0] == 400
        assert message in handler.sent[1]["error"]
        assert manager.config == before_config
        assert manager.config_path.read_bytes() == before_bytes
    finally:
        manager.close()


def test_caps_section_update_reuses_canonical_widening_consent_and_persistence(
        tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    quiet_status(manager, monkeypatch)
    baseline = json.loads(json.dumps(manager.config))
    baseline["bridge"]["auto_start"] = False
    baseline["ollama"]["auto_start"] = False
    baseline["ide"]["auto_start"] = False
    manager.save_settings(baseline)
    before_bytes = manager.config_path.read_bytes()
    budget = json.loads(json.dumps(manager.config["budget"]))
    caps = json.loads(json.dumps(manager.config["caps"]))
    budget["period_ceiling_usd"] += 1.0

    class BaseHandler:
        path = ""
        body = None

        def _send_json(self, response, status=200):
            self.sent = (status, response)

        def _handle_put(self):
            self.fell_through = True

    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        _read_body=lambda handler: handler.body,
        core=SimpleNamespace(envelope=lambda project, **response: response),
        runtime_registry=SimpleNamespace(reset_status_cache=lambda: None),
    )
    install_web_integration(web_api, manager)

    try:
        rejected = web_api.DaedalusHandler()
        rejected.path = "/api/desktop/settings"
        rejected.body = {
            "section_updates": {"budget": budget, "caps": caps}
        }
        rejected._handle_put()
        assert rejected.sent[0] == 400
        assert "confirm_widening" in rejected.sent[1]["error"]
        assert manager.config_path.read_bytes() == before_bytes

        caps["confirm_widening"] = True
        accepted = web_api.DaedalusHandler()
        accepted.path = "/api/desktop/settings"
        accepted.body = {
            "section_updates": {"budget": budget, "caps": caps}
        }
        accepted._handle_put()
        assert accepted.sent[0] == 200
        saved = json.loads(manager.config_path.read_text(encoding="utf-8"))
        assert saved["budget"] == budget
        assert "confirm_widening" not in saved["caps"]
        assert accepted.sent[1]["desktop"]["config"] == saved
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
        assert returned["settings_update_contract"] == "section_updates_v1"
        assert returned["budget"]["effective_period_ceiling_usd"] is None
        assert "confirm_widening" not in returned["config"]["caps"]

        fetched = web_api.DaedalusHandler()
        fetched.path = "/api/desktop/settings"
        fetched._handle_get()
        assert fetched.sent[1] == 200
        assert fetched.sent[0]["desktop"]["settings_update_contract"] == (
            "section_updates_v1"
        )
        assert "settings_update_contract" not in manager.snapshot()
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
    with pytest.raises(ValueError, match="password, private_key"):
        normalize_config(
            remote_config(
                password="do-not-store",
                private_key="-----BEGIN PRIVATE KEY-----",
            )
        )


def test_remote_mode_rejects_option_injection_and_dns_trust():
    with pytest.raises(ValueError):
        normalize_config(remote_config(host="-oProxyCommand=evil"))
    with pytest.raises(ValueError):
        normalize_config(remote_config(host="bench.example", trust_remote_host=True))


def test_persisted_remote_environment_projects_no_ssh_consent_or_peer_trust(
    tmp_path, monkeypatch
):
    monkeypatch.delenv(TRUSTED_HOSTS_VAR, raising=False)
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config(remote_config())
    manager._effect_owner._apply_environment_from(
        manager.config,
        budget_policy_error="",
    )
    try:
        assert os.environ["OLLAMA_HOST"] == "http://127.0.0.1:11434"
        assert TUNNEL_FORWARD_VAR not in os.environ
        assert TUNNEL_TARGET_VAR not in os.environ
        assert REMOTE_OK_VAR not in os.environ
        assert "192.168.50.20" not in os.environ.get(TRUSTED_HOSTS_VAR, "")
    finally:
        manager.close()


def test_removed_tunnel_policy_does_not_reclassify_loopback(monkeypatch):
    install_tunnel_egress_policy()
    monkeypatch.delenv(TRUSTED_HOSTS_VAR, raising=False)
    monkeypatch.setenv(TUNNEL_FORWARD_VAR, "http://127.0.0.1:11435")
    monkeypatch.setenv(TUNNEL_TARGET_VAR, "http://192.168.50.20:11434")

    assert sensitivity.is_loopback_host("http://127.0.0.1:11435") is True
    assert sensitivity.lane_for_host("http://127.0.0.1:11435") == "trusted"
    assert sensitivity.lane_for_host("http://127.0.0.1:11434") == "trusted"


def test_explicit_numeric_remote_trust_survives_tunnel(monkeypatch):
    install_tunnel_egress_policy()
    monkeypatch.setenv(TRUSTED_HOSTS_VAR, "192.168.50.20")
    monkeypatch.setenv(TUNNEL_FORWARD_VAR, "http://127.0.0.1:11435")
    monkeypatch.setenv(TUNNEL_TARGET_VAR, "http://192.168.50.20:11434")
    assert sensitivity.lane_for_host("http://127.0.0.1:11435") == "trusted"


def test_remote_ssh_refuses_without_transport_or_key_access(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config(remote_config(host_key_fingerprint=""))
    try:
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Remote SSH is unavailable",
        ):
            manager.ensure_remote_ollama()
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Remote SSH is unavailable",
        ):
            manager.ensure_ollama()
        assert not hasattr(manager, "_ssh")
        assert not hasattr(manager, "_tunnel")
    finally:
        manager.close()


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


def test_local_ollama_adoption_probes_exact_configured_endpoint_without_child(
    tmp_path, monkeypatch
):
    manager = DesktopRuntimeManager(tmp_path)
    endpoint = "http://127.0.0.1:11436"
    manager.config = normalize_config({"ollama": {"local_host": endpoint}})
    probes: list[tuple[float, str | None]] = []

    def probe(timeout=1.5, *, endpoint=None, switch=None):
        assert switch is not None
        probes.append((timeout, endpoint))
        return True, ""

    monkeypatch.setattr(manager, "_probe", probe)

    try:
        result = manager._adopt_local_ollama_owned(
            endpoint,
            switch=SimpleNamespace(checkpoint=lambda: None),
        )
        assert probes == [(1.5, endpoint)]
        assert not hasattr(manager, "_ollama")
        assert result == {
            "mode": "local",
            "running": True,
            "reachable": True,
            "detail": "",
        }
    finally:
        manager.close()


def test_reachable_preexisting_ollama_is_not_owned_or_stopped(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    endpoint = manager.config["ollama"]["local_host"]
    monkeypatch.setattr(
        manager,
        "_probe",
        lambda timeout=1.5, *, endpoint=None, switch=None: (True, ""),
    )

    try:
        result = manager._adopt_local_ollama_owned(
            endpoint,
            switch=SimpleNamespace(checkpoint=lambda: None),
        )
        assert result["reachable"] is True
        assert not hasattr(manager, "_ollama")
    finally:
        manager.close()


def test_stop_ollama_refuses_external_or_adopted_process_authority(tmp_path):
    manager = DesktopRuntimeManager(tmp_path)
    try:
        with pytest.raises(
            desktop_effects.DesktopFeatureUnavailable,
            match="does not own or terminate",
        ):
            manager.stop_ollama()
        assert not hasattr(manager, "_ollama")
    finally:
        manager.close()


def test_local_host_route_change_invalidates_observation_without_stop(tmp_path):
    manager = DesktopRuntimeManager(tmp_path)
    manager._ollama_observation = {
        "observed": True,
        "endpoint": manager.config["ollama"]["local_host"],
        "observed_at": "now",
        "reachable": True,
        "last_error": "",
    }
    proposed = json.loads(json.dumps(manager.config))
    proposed["bridge"]["auto_start"] = False
    proposed["ide"]["auto_start"] = False
    proposed["ollama"]["auto_start"] = False
    proposed["ollama"]["local_host"] = "http://127.0.0.1:11436"
    try:
        manager.save_settings(proposed)
        assert manager._ollama_observation == {
            "observed": False,
            "endpoint": "http://127.0.0.1:11436",
            "observed_at": None,
            "reachable": False,
            "last_error": "not probed for the configured endpoint",
        }
    finally:
        manager.close()


def test_manager_close_is_effect_free_and_has_no_stop_ports(tmp_path):
    manager = DesktopRuntimeManager(tmp_path)
    manager.close()
    assert manager._closed is True
    assert not hasattr(manager, "_stop_ollama_owned")
    assert not hasattr(manager, "_stop_ide_owned")


def test_web_ollama_stop_route_uses_effect_owner_cleanup():
    class BaseHandler:
        path = ""

        def _send_json(self, payload, status=200):
            self.sent = (payload, status)

        def _handle_post(self):
            self.fell_through = True

    class Manager:
        def __init__(self):
            self.stopped = False
            self._effect_owner = SimpleNamespace(stop_ollama=self.stop_ollama)

        def stop_ollama(self):
            self.stopped = True
            raise desktop_effects.DesktopFeatureUnavailable(
                "external process is not owned"
            )

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
    assert cache_resets == []
    assert request.sent[1] == 409
    assert request.sent[0]["error_code"] == "desktop_feature_unavailable"
    assert request.sent[0]["committed"] is False


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


def test_ide_status_does_not_discover_configured_file_or_path(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    configured = tmp_path / "tools" / "openvscode-server"
    configured.parent.mkdir()
    configured.write_text("", encoding="utf-8")
    try:
        manager.config = normalize_config(
            {"ide": {"mode": "native", "executable": str(configured), "auto_start": False}}
        )
        status = manager._ide_status()
        assert status["observed"] is False
        assert status["installed"] is False
        assert status["available"] is False
        assert status["executable"] == ""
        assert status["configured_executable"] == str(configured)
        assert not hasattr(manager, "_discover_ide_executable")
    finally:
        manager.close()


def test_ide_has_no_discovery_or_download_port(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    try:
        assert not hasattr(manager, "_discover_ide_executable")
        assert not hasattr(manager, "_discover_docker_executable")
        assert manager._ide_status()["runtime_downloads"] is False
    finally:
        manager.close()


def test_ide_start_refuses_before_process_or_project_command_use(tmp_path, monkeypatch):
    project = tmp_path / "--project with spaces"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    try:
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Managed IDE start is unavailable",
        ):
            manager.ensure_ide(project)
        assert not hasattr(manager, "_ide")
    finally:
        manager.close()


def test_unavailable_ide_url_never_resolves_or_inspects_project(tmp_path):
    manager = DesktopRuntimeManager(tmp_path)
    try:
        expected = manager.config["ide"]["endpoint"] + "/"
        assert manager._ide_ui_url(tmp_path / "missing") == expected
        assert manager._ide_ui_url(["--host", "0.0.0.0"]) == expected
    finally:
        manager.close()


def test_snapshot_is_detached_unprobed_and_creates_no_budget_lock(
    tmp_path, monkeypatch
):
    manager = DesktopRuntimeManager(tmp_path)
    ledger = Path(os.environ[budget_kernel.ENV_LEDGER])
    lock = ledger.with_name(ledger.name + ".lock")
    monkeypatch.setattr(
        manager,
        "_probe",
        lambda *args, **kwargs: pytest.fail("snapshot must not probe Ollama"),
    )
    try:
        assert not lock.exists()
        snapshot = manager.snapshot()
        assert not lock.exists()
        assert snapshot["services"]["ide"]["observed"] is False
        assert snapshot["services"]["ide"]["reachable"] is False
        assert snapshot["services"]["ollama"]["observed"] is False
        snapshot["config"]["ollama"]["model"] = "detached-change"
        assert manager.config["ollama"]["model"] != "detached-change"
    finally:
        manager.close()


def test_ide_status_reports_missing_binary_without_start_or_download(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "native"}})
    try:
        status = manager._ide_status()
        assert status["installed"] is False
        assert status["available"] is False
        assert status["executable"] == ""
        assert status["observed"] is False
        assert "not probed" in status["last_error"]
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
    try:
        status = manager._ide_status()
        assert status["installed"] is False
        assert status["available"] is False
        assert status["executable"] == ""
        assert status["configured_executable"] == str(executable)
        assert status["observed"] is False
        assert status["reachable"] is False
        assert "not probed" in status["last_error"]
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


def test_docker_exec_boundary_is_absent_in_v016(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    try:
        assert not hasattr(manager, "_docker_exec")
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Managed IDE start is unavailable",
        ):
            manager.ensure_ide(tmp_path)
    finally:
        manager.close()


def test_docker_ide_start_refuses_without_container_or_process_effect(
    tmp_path, monkeypatch
):
    project = tmp_path / "project with spaces"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    try:
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Managed IDE start is unavailable",
        ):
            manager.ensure_ide(project / ".")
        assert not hasattr(manager, "_ide")
        assert not hasattr(manager, "_docker_exec")
    finally:
        manager.close()


def test_docker_ide_refusal_does_not_inspect_or_mutate_host_containers(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    try:
        assert not hasattr(manager, "_docker_inspect_container")
        assert not hasattr(manager, "_docker_image_error")
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Managed IDE start is unavailable",
        ):
            manager.ensure_ide(project)
    finally:
        manager.close()


def test_docker_ide_status_is_unprobed_and_unavailable(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    status = manager._ide_status()
    assert status["installed"] is False
    assert status["available"] is False
    assert status["managed"] is False
    assert status["observed"] is False
    assert status["reachable"] is False
    assert "not probed" in status["last_error"]
    assert status["runtime_downloads"] is False
    manager.close()


def test_docker_status_does_not_adopt_lifecycle_ownership(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    try:
        status = manager._ide_status(project)
        assert status["reachable"] is False
        assert status["managed"] is False
        assert status["observed"] is False
        assert not hasattr(manager, "_ide_docker_managed_id")
    finally:
        manager.close()


def test_ensure_docker_ide_never_adopts_matching_orphan(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    try:
        with pytest.raises(
            desktop_effects.DesktopEffectRefused,
            match="Managed IDE start is unavailable",
        ):
            manager.ensure_ide(project)
        assert not hasattr(manager, "_ide")
    finally:
        manager.close(strict=True)


def test_docker_container_match_authority_is_absent(tmp_path):
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    try:
        assert not hasattr(manager, "_docker_container_matches")
        assert not hasattr(manager, "_docker_project_hash")
    finally:
        manager.close()


def test_strict_ide_cleanup_does_not_inspect_or_remove_docker(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    try:
        with pytest.raises(desktop_effects.DesktopFeatureUnavailable):
            manager.stop_ide(strict=True)
        assert not hasattr(manager, "_docker_inspect_container")
        assert not hasattr(manager, "_remove_owned_docker_ide")
    finally:
        manager.close()


def test_strict_ide_cleanup_has_no_container_identity_state(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config({"ide": {"mode": "docker"}})
    try:
        assert not hasattr(manager, "_ide_docker_managed_id")
        with pytest.raises(desktop_effects.DesktopFeatureUnavailable):
            manager.stop_ide(strict=True)
        assert not hasattr(manager, "_ide")
    finally:
        manager.close()


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
            self._effect_owner = SimpleNamespace(
                start_ide=self.ensure_ide,
                stop_ide=self.stop_ide,
            )

        def ensure_ide(self, project=None):
            self.started.append(project)
            raise desktop_effects.DesktopFeatureUnavailable(
                "Managed IDE start is unavailable"
            )

        def stop_ide(self, **kwargs):
            self.stopped = True
            raise desktop_effects.DesktopFeatureUnavailable(
                "external IDE is not owned"
            )

        def close(self, **kwargs):
            self.closed = True
            if self.close_error:
                raise DesktopRuntimeError("cleanup failed")

        def snapshot(self):
            return {"services": {"ide": {"reachable": False}}}

    manager = Manager()
    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        _read_body=lambda handler: pytest.fail(
            "unavailable IDE must be refused before body parsing"
        ),
        core=SimpleNamespace(envelope=lambda project, **payload: payload),
    )
    install_web_integration(web_api, manager)

    start = web_api.DaedalusHandler()
    start.path = "/api/desktop/services/ide/start"
    start.body = {"project": "demo"}
    start._handle_post()
    assert manager.started == [None]
    assert start.sent[1] == 409
    assert start.sent[0]["error_code"] == "desktop_feature_unavailable"
    assert start.sent[0]["committed"] is False

    stop = web_api.DaedalusHandler()
    stop.path = "/api/desktop/services/ide/stop"
    stop._handle_post()
    assert manager.stopped is True
    assert stop.sent[1] == 409
    assert stop.sent[0]["error_code"] == "desktop_feature_unavailable"

    for supplied in ("", "b" * 64):
        rejected = web_api.DaedalusHandler()
        rejected.path = "/api/desktop/shutdown"
        rejected.server = SimpleNamespace(daedalus_desktop_startup_nonce="a" * 64)
        rejected.headers = (
            {"X-Daedalus-Desktop-Nonce": supplied} if supplied else {}
        )
        rejected._handle_post()
        assert manager.closed is False
        assert rejected.sent[1] == 403
        assert rejected.sent[0] == {
            "ok": False,
            "error": "desktop parent nonce required",
            "error_code": "desktop_policy_denied",
            "committed": False,
        }

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
    assert failed.sent == (
        {
            "ok": False,
            "error": "cleanup failed",
            "error_code": "desktop_effect_authorization_unavailable",
            "committed": False,
        },
        503,
    )

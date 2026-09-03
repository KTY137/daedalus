"""Architecture and ordering contract for G1-IFACE-DESKTOP-03."""
from __future__ import annotations

import ast
import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import pytest

from daedalus import desktop_runtime
from daedalus.interfaces.desktop import settings
from daedalus.spine.effect_boundary import registry_sha256
from tools import index_work_packets


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "desktop_runtime.py"
OWNER = ROOT / "daedalus" / "interfaces" / "desktop" / "settings.py"
PACKET_PATH = "docs/work-packets/G1-IFACE-DESKTOP-03_SETTINGS_OWNER.md"
REGISTRY_SHA256 = "44222aa9f9269eb1c9d9f5cf118786cbb1a1d602f6f3ca77aeb00d4f599214c9"
SETTINGS_LITERAL_COUNT = 145
SETTINGS_LITERAL_SHA256 = (
    "9cd1426a7902482cd2fc8593eb0c42b69a7a986b72c8de1e97994a704e64251d"
)
SETTINGS_FUNCTIONS = (
    "read_budget_environment",
    "load",
    "save",
    "save_settings",
    "apply_environment",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def _manager_methods(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    manager = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DesktopRuntimeManager"
    )
    return {
        node.name: node
        for node in manager.body
        if isinstance(node, ast.FunctionDef)
    }


def _calls(node: ast.AST, owner: str, name: str) -> Iterable[ast.Call]:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == owner
            and child.func.attr == name
        ):
            yield child


def _literal_digest(path: Path, names: Iterable[str]) -> tuple[int, str]:
    functions = _functions(_tree(path))
    values: list[list[object]] = []
    for name in names:
        function = functions[name]
        doc_node = (
            function.body[0]
            if function.body
            and isinstance(function.body[0], ast.Expr)
            and isinstance(function.body[0].value, ast.Constant)
            and isinstance(function.body[0].value.value, str)
            else None
        )
        for node in ast.walk(function):
            if not (
                isinstance(node, ast.Constant)
                and isinstance(
                    node.value,
                    (str, bytes, int, float, bool, type(None)),
                )
            ):
                continue
            if doc_node is not None and node is doc_node.value:
                continue
            value: object = (
                node.value.hex() if isinstance(node.value, bytes) else node.value
            )
            values.append([type(node.value).__name__, value])
    values.sort(key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=True))
    encoded = json.dumps(
        values,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    ).encode("utf-8")
    return len(values), hashlib.sha256(encoded).hexdigest()


def _bare_manager() -> desktop_runtime.DesktopRuntimeManager:
    manager = object.__new__(desktop_runtime.DesktopRuntimeManager)
    manager._lock = threading.RLock()
    manager.config = desktop_runtime.normalize_config({})
    manager._config_error = ""
    manager._budget_policy_error = ""
    return manager


def _copy_config(manager: desktop_runtime.DesktopRuntimeManager) -> dict[str, Any]:
    return json.loads(json.dumps(manager.config))


def test_settings_owner_retains_exact_frozen_contract_literals() -> None:
    assert _literal_digest(OWNER, SETTINGS_FUNCTIONS) == (
        SETTINGS_LITERAL_COUNT,
        SETTINGS_LITERAL_SHA256,
    )


def test_facade_methods_are_bounded_per_call_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    methods = _manager_methods(_tree(FACADE))
    delegates = {
        "_read_budget_environment": "read_budget_environment",
        "_load": "load",
        "_save": "save",
        "save_settings": "save_settings",
        "apply_environment": "apply_environment",
    }
    for facade_name, owner_name in delegates.items():
        method = methods[facade_name]
        assert list(_calls(method, "desktop_settings", owner_name))
        assert method.end_lineno - method.lineno < 24

    observed: dict[str, tuple[tuple[object, ...], dict[str, object]]] = {}
    results = {
        "read_budget_environment": ({"budget": True}, {"caps": True}, ""),
        "load": {"loaded": True},
        "save": None,
        "save_settings": {"saved": True},
        "apply_environment": None,
    }

    def replacement(name: str):
        def call(*args: object, **kwargs: object) -> object:
            observed[name] = (args, kwargs)
            return results[name]

        return call

    for name in SETTINGS_FUNCTIONS:
        monkeypatch.setattr(settings, name, replacement(name))

    normalize_port = object()
    defaults_port = object()
    numeric_host_port = object()
    budget_port = object()
    json_port = object()
    environment_port = object()
    os_port = SimpleNamespace(environ=environment_port)
    policy_port = object()
    axes_port = object()
    store_policy_port = object()

    class PatchedDesktopError(RuntimeError):
        pass

    monkeypatch.setattr(desktop_runtime, "normalize_config", normalize_port)
    monkeypatch.setattr(desktop_runtime, "_defaults", defaults_port)
    monkeypatch.setattr(desktop_runtime, "_numeric_host", numeric_host_port)
    monkeypatch.setattr(desktop_runtime, "budget_kernel", budget_port)
    monkeypatch.setattr(desktop_runtime, "json", json_port)
    monkeypatch.setattr(desktop_runtime, "os", os_port)
    monkeypatch.setattr(desktop_runtime, "ExecutionLimitPolicy", policy_port)
    monkeypatch.setattr(desktop_runtime, "LimitAxes", axes_port)
    monkeypatch.setattr(desktop_runtime, "MODE_CUSTOM", "patched-custom")
    monkeypatch.setattr(
        desktop_runtime,
        "store_limit_policy_in_env",
        store_policy_port,
    )
    monkeypatch.setattr(desktop_runtime, "DesktopRuntimeError", PatchedDesktopError)

    manager = object.__new__(desktop_runtime.DesktopRuntimeManager)
    assert desktop_runtime.DesktopRuntimeManager._read_budget_environment() == (
        {"budget": True},
        {"caps": True},
        "",
    )
    assert manager._load() == {"loaded": True}
    manager._save()
    assert manager.save_settings({"incoming": True}) == {"saved": True}
    manager.apply_environment()

    assert observed["read_budget_environment"][1] == {
        "budget_kernel": budget_port,
        "default_config": desktop_runtime.DEFAULT_CONFIG,
        "json_module": json_port,
    }
    assert observed["load"][1] == {
        "json_module": json_port,
        "defaults": defaults_port,
        "normalize_config": normalize_port,
    }
    assert observed["save"][1] == {
        "json_module": json_port,
        "os_module": os_port,
        "error_type": PatchedDesktopError,
    }
    assert observed["save_settings"][1] == {
        "json_module": json_port,
        "normalize_config": normalize_port,
        "execution_limit_policy": policy_port,
        "limit_axes": axes_port,
        "mode_custom": "patched-custom",
        "error_type": PatchedDesktopError,
    }
    assert observed["apply_environment"][1] == {
        "environ": environment_port,
        "budget_kernel": budget_port,
        "env_execution_limit_policy": desktop_runtime.ENV_EXECUTION_LIMIT_POLICY,
        "execution_limit_policy": policy_port,
        "store_limit_policy_in_env": store_policy_port,
        "numeric_host": numeric_host_port,
        "tunnel_forward_var": desktop_runtime.TUNNEL_FORWARD_VAR,
        "tunnel_target_var": desktop_runtime.TUNNEL_TARGET_VAR,
        "remote_ok_var": desktop_runtime.REMOTE_OK_VAR,
        "trusted_hosts_var": desktop_runtime.TRUSTED_HOSTS_VAR,
    }


def test_settings_owner_has_no_process_server_or_effect_entry_authority() -> None:
    tree = _tree(OWNER)
    functions = _functions(tree)
    assert set(functions) == set(SETTINGS_FUNCTIONS)
    assert list(_calls(functions["save"], "os_module", "replace"))
    assert not list(_calls(functions["save"], "os_module", "rename"))
    assert not any(isinstance(node, ast.ClassDef) for node in tree.body)
    banned_imports = {
        "atexit",
        "daedalus.desktop_runtime",
        "http.server",
        "socket",
        "subprocess",
        "threading",
        "urllib.request",
    }
    banned_calls = {
        "ManagedProcess",
        "Popen",
        "Thread",
        "ThreadingHTTPServer",
        "begin_effect",
        "serve_forever",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {alias.name for alias in node.names} & banned_imports
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") not in banned_imports
            assert node.level == 0
        elif isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert name not in banned_calls


def test_widening_refusal_precedes_every_injected_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _bare_manager()
    proposed = _copy_config(manager)
    proposed["budget"]["period_ceiling_usd"] += 1.0
    effects: list[str] = []

    def record(name: str):
        return lambda *args, **kwargs: effects.append(name)

    for name in (
        "stop_ollama",
        "stop_ide",
        "_save",
        "apply_environment",
        "ensure_bridge",
        "ensure_ollama",
        "ensure_ide",
        "snapshot",
    ):
        monkeypatch.setattr(manager, name, record(name))

    with pytest.raises(ValueError, match="confirm_widening"):
        manager.save_settings(proposed)
    assert effects == []


def test_save_failure_restores_config_after_ordered_route_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _bare_manager()
    previous = manager.config
    proposed = _copy_config(manager)
    proposed["bridge"]["auto_start"] = False
    proposed["ollama"]["auto_start"] = False
    proposed["ide"]["auto_start"] = False
    proposed["ollama"]["local_host"] = "http://127.0.0.1:11436"
    proposed["ide"]["docker_image"] = "daedalus/openvscode-server:1.109.6"
    calls: list[str] = []

    monkeypatch.setattr(
        manager,
        "stop_ollama",
        lambda: calls.append("stop_ollama"),
    )
    monkeypatch.setattr(
        manager,
        "stop_ide",
        lambda: calls.append("stop_ide"),
    )

    def refuse_save() -> None:
        calls.append("save")
        raise desktop_runtime.DesktopRuntimeError("write refused")

    monkeypatch.setattr(manager, "_save", refuse_save)
    monkeypatch.setattr(
        manager,
        "apply_environment",
        lambda: calls.append("environment"),
    )

    with pytest.raises(desktop_runtime.DesktopRuntimeError, match="write refused"):
        manager.save_settings(proposed)
    assert calls == ["stop_ollama", "stop_ide", "save"]
    assert manager.config is previous


def test_success_orders_save_environment_autostart_and_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _bare_manager()
    proposed = _copy_config(manager)
    proposed["bridge"]["auto_start"] = True
    proposed["ollama"]["auto_start"] = True
    proposed["ide"]["auto_start"] = True
    calls: list[str] = []

    monkeypatch.setattr(manager, "_save", lambda: calls.append("save"))
    monkeypatch.setattr(
        manager,
        "apply_environment",
        lambda: calls.append("environment"),
    )
    monkeypatch.setattr(
        manager,
        "ensure_bridge",
        lambda: calls.append("bridge"),
    )
    monkeypatch.setattr(
        manager,
        "ensure_ollama",
        lambda: calls.append("ollama"),
    )
    monkeypatch.setattr(
        manager,
        "ensure_ide",
        lambda: calls.append("ide"),
    )
    monkeypatch.setattr(
        manager,
        "snapshot",
        lambda: calls.append("snapshot") or {"snapshot": True},
    )

    assert manager.save_settings(proposed) == {"snapshot": True}
    assert calls == ["save", "environment", "bridge", "ollama", "ide", "snapshot"]


def test_registry_and_work_packet_contract_are_stable() -> None:
    assert registry_sha256() == REGISTRY_SHA256
    artifact = index_work_packets._artifact(ROOT, PACKET_PATH, set())
    assert artifact["declared_packet_id"] == "G1-IFACE-DESKTOP-03"
    assert artifact["artifact_role"] == "primary"
    assert artifact["metadata"] == {
        "active_gate": 1,
        "classification": "ALIGNED",
        "owner": "repository owner",
        "base_revision": "0ce7414a3c22e3357816e08a76ed0b1478f3e41d",
        "dependencies": (
            "G1-IFACE-DESKTOP-02 at "
            "0ce7414a3c22e3357816e08a76ed0b1478f3e41d"
        ),
    }
    assert artifact["sections"] == list(index_work_packets.REQUIRED_SECTIONS)

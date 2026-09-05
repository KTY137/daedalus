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
from daedalus.interfaces.desktop import effects as desktop_effects
from daedalus.interfaces.desktop import settings
from daedalus.spine.effect_boundary import registry_sha256
from tools import index_work_packets


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "desktop_runtime.py"
OWNER = ROOT / "daedalus" / "interfaces" / "desktop" / "settings.py"
EFFECT_OWNER = ROOT / "daedalus" / "interfaces" / "desktop" / "effects.py"
PACKET_PATH = "docs/work-packets/G1-IFACE-DESKTOP-03_SETTINGS_OWNER.md"
REGISTRY_SHA256 = "7a8fc9442be4d1fff8f576fa951036788ef146c779c5c1145bce21f471f3c605"
SETTINGS_LITERAL_COUNT = 83
SETTINGS_LITERAL_SHA256 = (
    "01e109e1237b08acd198bce283c93165df65ff2dfe00a1635e2e30d75ee9b3b1"
)
SETTINGS_FUNCTIONS = (
    "read_budget_environment",
    "load",
    "prepare_settings",
    "environment_projection",
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
    return _class_methods(tree, "DesktopRuntimeManager")


def _class_methods(
    tree: ast.Module,
    class_name: str,
) -> dict[str, ast.FunctionDef]:
    manager = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
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


def _bare_manager(root: Path) -> desktop_runtime.DesktopRuntimeManager:
    manager = object.__new__(desktop_runtime.DesktopRuntimeManager)
    manager.root = root.resolve()
    manager.config_path = manager.root / "config" / "connections.json"
    manager.log_path = manager.root / "runs" / "desktop_runtime.log"
    manager._lock = threading.RLock()
    manager.config = desktop_runtime.normalize_config({})
    manager._config_error = ""
    manager._budget_policy_error = ""
    manager._base_trusted = ""
    manager._ollama_observation = {}
    manager._closed = False
    manager._bridge_stop = threading.Event()
    manager._ide = None
    manager._ide_log = None
    manager._ollama = None
    manager._ollama_log = None
    manager._tunnel = None
    manager._tunnel_log = None
    manager._effect_owner = desktop_effects.DesktopEffectOwner(
        manager,
        error_type=desktop_runtime.DesktopRuntimeError,
    )
    return manager


def _copy_config(manager: desktop_runtime.DesktopRuntimeManager) -> dict[str, Any]:
    return json.loads(json.dumps(manager.config))


def _stub_authorization(
    owner: desktop_effects.DesktopEffectOwner,
    monkeypatch: pytest.MonkeyPatch,
    events: list[str] | None = None,
) -> None:
    observed = events if events is not None else []
    granted = object()
    monkeypatch.setattr(
        owner,
        "_ensure_switch",
        lambda: SimpleNamespace(checkpoint=lambda: None),
    )
    monkeypatch.setattr(desktop_effects, "_source_revision", lambda: "a" * 40)
    monkeypatch.setattr(
        desktop_effects,
        "acquire_effect_lease",
        lambda *args, **kwargs: granted,
    )
    monkeypatch.setattr(
        owner,
        "_begin_authorized",
        lambda *args: ("execution", "started"),
    )
    monkeypatch.setattr(
        owner,
        "_complete_authorized",
        lambda *args: observed.append("receipt_completed"),
    )

    def fail(*args: object) -> bool:
        observed.append("receipt_failed")
        return True

    monkeypatch.setattr(owner, "_fail_authorized", fail)


def test_settings_owner_retains_exact_frozen_contract_literals() -> None:
    assert _literal_digest(OWNER, SETTINGS_FUNCTIONS) == (
        SETTINGS_LITERAL_COUNT,
        SETTINGS_LITERAL_SHA256,
    )


def test_facade_methods_are_bounded_per_call_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    methods = _manager_methods(_tree(FACADE))
    preparation_delegates = {
        "_read_budget_environment": "read_budget_environment",
        "_load": "load",
    }
    for facade_name, owner_name in preparation_delegates.items():
        method = methods[facade_name]
        assert list(_calls(method, "desktop_settings", owner_name))
        assert method.end_lineno - method.lineno < 24
    for facade_name, owner_name in {"save_settings": "save_settings"}.items():
        method = methods[facade_name]
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == owner_name
            for node in ast.walk(method)
        )
        assert not any(
            list(_calls(method, "desktop_settings", preparation_name))
            for preparation_name in SETTINGS_FUNCTIONS
        )
        assert method.end_lineno - method.lineno < 24
    effect_methods = _class_methods(_tree(EFFECT_OWNER), "DesktopEffectOwner")
    assert "apply_environment" not in methods
    assert "apply_environment" not in effect_methods
    assert list(
        _calls(
            effect_methods["_apply_environment_from"],
            "desktop_settings",
            "environment_projection",
        )
    )

    observed: dict[str, tuple[tuple[object, ...], dict[str, object]]] = {}
    results = {
        "read_budget_environment": ({"budget": True}, {"caps": True}, ""),
        "load": {"loaded": True},
    }

    def replacement(name: str):
        def call(*args: object, **kwargs: object) -> object:
            observed[name] = (args, kwargs)
            return results[name]

        return call

    for name in ("read_budget_environment", "load"):
        monkeypatch.setattr(settings, name, replacement(name))

    normalize_port = object()
    defaults_port = object()
    budget_port = object()
    json_port = object()

    monkeypatch.setattr(
        desktop_runtime,
        "_normalize_loaded_config",
        normalize_port,
    )
    monkeypatch.setattr(desktop_runtime, "_defaults", defaults_port)
    monkeypatch.setattr(desktop_runtime, "budget_kernel", budget_port)
    monkeypatch.setattr(desktop_runtime, "json", json_port)

    class EffectOwner:
        def save_settings(self, raw: object) -> object:
            observed["effect_save_settings"] = ((raw,), {})
            return {"saved": True}

    manager = object.__new__(desktop_runtime.DesktopRuntimeManager)
    effect_owner = EffectOwner()
    manager._require_effect_owner = lambda: effect_owner
    assert desktop_runtime.DesktopRuntimeManager._read_budget_environment() == (
        {"budget": True},
        {"caps": True},
        "",
    )
    assert manager._load() == {"loaded": True}
    assert manager.save_settings({"incoming": True}) == {"saved": True}

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
    assert observed["effect_save_settings"] == (({"incoming": True},), {})


def test_settings_owner_has_no_process_server_or_effect_entry_authority() -> None:
    tree = _tree(OWNER)
    functions = _functions(tree)
    assert set(functions) == set(SETTINGS_FUNCTIONS)
    assert not any(isinstance(node, ast.ClassDef) for node in tree.body)
    banned_imports = {
        "atexit",
        "daedalus.desktop_runtime",
        "http.server",
        "os",
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
        "fsync",
        "mkdir",
        "open",
        "putenv",
        "rename",
        "replace",
        "serve_forever",
        "unlink",
        "write",
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
    tmp_path: Path,
) -> None:
    manager = _bare_manager(tmp_path)
    proposed = _copy_config(manager)
    proposed["budget"]["period_ceiling_usd"] += 1.0
    effects: list[str] = []

    monkeypatch.setattr(
        manager._effect_owner,
        "_authorize_settings",
        lambda *args, **kwargs: effects.append("authorize"),
    )

    with pytest.raises(
        desktop_effects.DesktopValidationError,
        match="confirm_widening",
    ):
        manager.save_settings(proposed)
    assert effects == []


def test_settings_effect_owner_is_initialized_and_has_the_only_save_path(
    tmp_path: Path,
) -> None:
    manager = _bare_manager(tmp_path)
    manager_methods = _manager_methods(_tree(FACADE))
    effect_methods = _class_methods(_tree(EFFECT_OWNER), "DesktopEffectOwner")

    assert isinstance(manager._effect_owner, desktop_effects.DesktopEffectOwner)
    assert "_save" not in manager_methods
    assert not hasattr(manager, "_save")
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_authorize_settings"
        for node in ast.walk(effect_methods["save_settings"])
    )


def test_settings_authorization_uses_only_exact_repo_relative_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _bare_manager(tmp_path)
    owner = manager._effect_owner
    nonce = "f" * 32
    prepared = _copy_config(manager)
    expected = (
        "config",
        "config/connections.json",
        f"config/.connections.json.{desktop_effects.os.getpid()}.{nonce}.tmp",
    )
    captured: dict[str, object] = {}
    granted = object()

    monkeypatch.setattr(
        desktop_effects.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=nonce),
    )
    monkeypatch.setattr(
        owner,
        "_ensure_switch",
        lambda: SimpleNamespace(checkpoint=lambda: None),
    )
    monkeypatch.setattr(desktop_effects, "_source_revision", lambda: "a" * 40)

    def acquire(root: Path, **kwargs: object) -> object:
        captured["root"] = root
        captured.update(kwargs)
        return granted

    monkeypatch.setattr(desktop_effects, "acquire_effect_lease", acquire)

    def stop_before_publication(*args: object) -> None:
        raise RuntimeError("stop before publication")

    monkeypatch.setattr(
        owner,
        "_begin_authorized",
        stop_before_publication,
    )

    with pytest.raises(
        desktop_effects.DesktopEffectUnavailable,
        match="settings authorization unavailable.*stop before publication",
    ):
        owner._authorize_settings(prepared, prepared)
    assert captured["root"] == tmp_path.resolve()
    assert captured["writable_paths"] == expected
    assert captured["write_policy"].write_allow == expected
    assert all(not Path(path).is_absolute() for path in expected)
    assert not manager.config_path.exists()


def test_save_failure_restores_config_without_stopping_serving_routes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _bare_manager(tmp_path)
    owner = manager._effect_owner
    previous = manager.config
    proposed = _copy_config(manager)
    proposed["bridge"]["auto_start"] = False
    proposed["ollama"]["auto_start"] = False
    proposed["ide"]["auto_start"] = False
    proposed["ollama"]["local_host"] = "http://127.0.0.1:11436"
    proposed["ide"]["docker_image"] = "daedalus/openvscode-server:1.109.6"
    calls: list[str] = []

    _stub_authorization(owner, monkeypatch, calls)
    monkeypatch.setattr(owner, "stop_ollama", lambda: calls.append("stop_ollama"))
    monkeypatch.setattr(owner, "stop_ide", lambda **kwargs: calls.append("stop_ide"))

    def refuse_write(*args: object, **kwargs: object) -> None:
        calls.append("write")
        raise OSError("write refused")

    monkeypatch.setattr(desktop_effects, "REPLACE_RETRY_S", 0.0)
    if desktop_effects.os.name == "nt":
        # Windows publishes through the write-through MoveFileExW seam.  A
        # plain os.replace fault is deliberately irrelevant there because it
        # cannot establish the durability claimed by a successful receipt.
        monkeypatch.setattr(
            desktop_effects,
            "_move_file_ex_windows_write_through",
            refuse_write,
        )
    else:
        monkeypatch.setattr(desktop_effects.os, "replace", refuse_write)
    with pytest.raises(
        desktop_effects.DesktopEffectUnavailable,
        match="settings persistence failed.*write refused",
    ):
        manager.save_settings(proposed)
    assert calls == ["write", "receipt_failed"]
    assert manager.config is previous
    assert not manager.config_path.exists()


def test_effect_owner_orders_receipt_environment_without_autostart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _bare_manager(tmp_path)
    owner = manager._effect_owner
    proposed = _copy_config(manager)
    proposed["bridge"]["auto_start"] = True
    proposed["ollama"]["auto_start"] = True
    proposed["ide"]["auto_start"] = True
    proposed["ollama"]["local_host"] = "http://127.0.0.1:11436"
    proposed["ide"]["docker_image"] = "daedalus/openvscode-server:1.109.6"
    calls: list[str] = []

    _stub_authorization(owner, monkeypatch, calls)
    monkeypatch.setattr(
        owner,
        "_apply_environment_from",
        lambda *_args, **_kwargs: calls.append("environment"),
    )
    monkeypatch.setattr(
        owner,
        "start_bridge",
        lambda: calls.append("bridge") or {"running": True, "managed": True},
    )
    monkeypatch.setattr(
        owner,
        "start_ollama",
        lambda: calls.append("ollama") or {"reachable": True},
    )
    monkeypatch.setattr(
        owner,
        "start_ide",
        lambda: calls.append("ide") or {"reachable": True},
    )
    monkeypatch.setattr(
        owner,
        "_detached_snapshot",
        lambda: calls.append("snapshot") or {"snapshot": True},
    )

    assert manager.save_settings(proposed) == {"snapshot": True}
    assert calls == [
        "receipt_completed",
        "environment",
        "snapshot",
    ]
    assert manager.config["bridge"]["auto_start"] is False
    assert manager.config["ollama"]["auto_start"] is False
    assert manager.config["ide"]["auto_start"] is False
    assert json.loads(manager.config_path.read_text(encoding="utf-8")) == manager.config


def test_post_commit_adoption_failures_are_returned_without_rolling_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _bare_manager(tmp_path)
    owner = manager._effect_owner
    previous = manager.config
    proposed = _copy_config(manager)
    proposed["bridge"]["auto_start"] = False
    proposed["ollama"]["auto_start"] = False
    proposed["ide"]["auto_start"] = False
    proposed["ollama"]["local_host"] = "http://127.0.0.1:11436"
    proposed["ide"]["docker_image"] = "daedalus/openvscode-server:1.109.6"
    calls: list[str] = []

    _stub_authorization(owner, monkeypatch, calls)

    def fail_environment(*_args: object, **_kwargs: object) -> None:
        calls.append("environment")
        raise OSError("environment projection refused")

    monkeypatch.setattr(owner, "_apply_environment_from", fail_environment)
    monkeypatch.setattr(
        owner,
        "_detached_snapshot",
        lambda: calls.append("snapshot") or {"config": manager.config},
    )

    result = manager.save_settings(proposed)

    assert manager.config is not previous
    assert manager.config["ollama"]["local_host"] == "http://127.0.0.1:11436"
    assert result["startup_error"] == (
        "environment adoption: OSError: environment projection refused"
    )
    assert calls == [
        "receipt_completed",
        "environment",
        "snapshot",
    ]
    assert json.loads(manager.config_path.read_text(encoding="utf-8")) == manager.config


@pytest.mark.parametrize("new_mode", ["native", "docker"])
def test_unavailable_ide_cleanup_never_touches_an_unowned_handle(
    tmp_path: Path,
    new_mode: str,
) -> None:
    manager = _bare_manager(tmp_path)
    manager.config["ide"]["mode"] = new_mode
    class FakeProcess:
        terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, *, timeout: float) -> None:
            assert timeout == 2
            assert self.terminated

        def kill(self) -> None:
            raise AssertionError("graceful owned IDE stop should succeed")

    process = FakeProcess()
    manager._ide = process
    with pytest.raises(
        desktop_effects.DesktopFeatureUnavailable,
        match="IDE stop is unavailable",
    ):
        manager.stop_ide(strict=True)
    assert process.terminated is False
    assert manager._ide is process
    assert not hasattr(manager._effect_owner, "_begin_cleanup")
    assert not hasattr(manager, "_docker_inspect_container")


def test_effect_registry_contract_is_stable() -> None:
    assert registry_sha256() == REGISTRY_SHA256


def test_work_packet_contract_is_stable() -> None:
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

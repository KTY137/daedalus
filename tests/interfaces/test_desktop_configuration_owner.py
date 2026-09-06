"""Architecture contract for the G1-IFACE-DESKTOP-02 configuration owner."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest

from daedalus import desktop_runtime
from daedalus.interfaces.desktop import configuration
from daedalus.spine.effect_boundary import registry_sha256
from tools import index_work_packets


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "desktop_runtime.py"
OWNER = ROOT / "daedalus" / "interfaces" / "desktop" / "configuration.py"
PACKET_PATH = "docs/work-packets/G1-IFACE-DESKTOP-02_CONFIGURATION_OWNER.md"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def _manager(tree: ast.Module) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DesktopRuntimeManager"
    )


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


def test_configuration_owner_defaults_disable_managed_desktop_start() -> None:
    first = configuration.defaults()
    second = configuration.defaults()
    for config in (first, second, configuration.DEFAULT_CONFIG):
        assert config["bridge"]["auto_start"] is False
        assert config["ollama"]["auto_start"] is False
        assert config["ide"]["auto_start"] is False

    first["ollama"]["remote"]["port"] = 1
    assert second["ollama"]["remote"]["port"] == 22
    assert configuration.DEFAULT_CONFIG["ollama"]["remote"]["port"] == 22


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {
            "bridge": {"auto_start": True},
            "ollama": {"auto_start": True},
            "ide": {"auto_start": True},
        },
    ],
)
def test_normalization_migrates_missing_and_legacy_autostart_to_false(raw: object) -> None:
    config = configuration.normalize_config(raw)
    assert config["bridge"]["auto_start"] is False
    assert config["ollama"]["auto_start"] is False
    assert config["ide"]["auto_start"] is False


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"unexpected": {}},
        {"bridge": []},
        {"bridge": {"unexpected": True}},
        {"bridge": {"auto_start": 1}},
        {"ollama": []},
        {"ollama": {"unexpected": True}},
        {"ollama": {"remote": []}},
        {"ollama": {"remote": {"password": "secret"}}},
        {"ollama": {"remote": {"port": "22"}}},
        {"ollama": {"remote": {"port": True}}},
        {"ollama": {"remote": {"identity_file": "x" * 4097}}},
        {
            "ollama": {
                "remote": {"host_key_fingerprint": "SHA256:" + "a" * 42}
            }
        },
    ],
)
def test_normalization_rejects_non_exact_types_keys_and_bounded_identity(
    raw: object,
) -> None:
    with pytest.raises(ValueError):
        configuration.normalize_config(raw)


def test_local_mode_remote_block_allows_only_clear_or_exact_legacy_repair() -> None:
    legacy = dict(configuration.defaults()["ollama"]["remote"])
    legacy.update(
        {
            "host": "192.0.2.10",
            "user": "operator",
            "identity_file": "C:/keys/operator_ed25519",
            "host_key_fingerprint": "SHA256:" + "a" * 43,
        }
    )

    loaded = configuration.normalize_config(
        {"ollama": {"mode": "local", "remote": legacy}},
        allow_legacy_remote=True,
    )
    repaired = configuration.normalize_config(
        {"ollama": {"mode": "local", "remote": legacy}},
        current_remote=loaded["ollama"]["remote"],
    )
    assert repaired["ollama"]["remote"] == loaded["ollama"]["remote"]

    modified = dict(legacy)
    modified["remote_port"] += 1
    with pytest.raises(ValueError, match="cannot be modified while ollama.mode is local"):
        configuration.normalize_config(
            {"ollama": {"mode": "local", "remote": modified}},
            current_remote=loaded["ollama"]["remote"],
        )

    cleared = configuration.normalize_config(
        {"ollama": {"mode": "local", "remote": {}}},
        current_remote=loaded["ollama"]["remote"],
    )
    assert cleared["ollama"]["remote"] == configuration.defaults()["ollama"][
        "remote"
    ]


def test_facade_resolves_configuration_owner_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert desktop_runtime.DEFAULT_CONFIG is configuration.DEFAULT_CONFIG
    assert (
        desktop_runtime.IDE_DOCKER_IMAGE
        == configuration.DEFAULT_IDE_DOCKER_IMAGE
    )

    observed: list[tuple[object, object, object]] = []
    sentinel = {"owner": "configuration"}

    def replacement(
        raw: object,
        *,
        budget_defaults: object = None,
        caps_defaults: object = None,
    ) -> dict[str, str]:
        observed.append((raw, budget_defaults, caps_defaults))
        return sentinel

    monkeypatch.setattr(configuration, "normalize_config", replacement)
    assert desktop_runtime.normalize_config(
        {"bridge": {}},
        budget_defaults={"max_calls": 2},
        caps_defaults={"mode": "bounded"},
    ) is sentinel
    assert observed == [
        (
            {"bridge": {}},
            {"max_calls": 2},
            {"mode": "bounded"},
        )
    ]


def test_facade_private_compatibility_helpers_are_bounded_delegates() -> None:
    functions = _functions(_tree(FACADE))
    delegates = {
        "_defaults": "defaults",
        "_port": "port",
        "_loopback_endpoint": "loopback_endpoint",
        "_ide_endpoint": "ide_endpoint",
        "_numeric_host": "numeric_host",
        "normalize_config": "normalize_config",
    }
    for facade_name, owner_name in delegates.items():
        function = functions[facade_name]
        assert list(_calls(function, "desktop_configuration", owner_name))
        assert function.end_lineno - function.lineno < 12


def test_manager_load_still_resolves_configuration_patch_points() -> None:
    manager = _manager(_tree(FACADE))
    methods = {
        node.name: node
        for node in manager.body
        if isinstance(node, ast.FunctionDef)
    }
    load_names = {
        node.id
        for node in ast.walk(methods["_load"])
        if isinstance(node, ast.Name)
    }
    assert {"_normalize_loaded_config", "_defaults"} <= load_names


def test_configuration_owner_cannot_mint_runtime_or_effect_authority() -> None:
    tree = _tree(OWNER)
    banned_imports = {
        "atexit",
        "http.server",
        "socket",
        "subprocess",
        "threading",
        "urllib.request",
        "daedalus.desktop_runtime",
    }
    banned_definitions = {
        "DesktopRuntimeManager",
        "install_tunnel_egress_policy",
        "install_web_integration",
        "main",
        "run",
    }
    banned_calls = {
        "ManagedProcess",
        "Popen",
        "Thread",
        "ThreadingHTTPServer",
        "begin_effect",
        "open",
        "serve_forever",
    }
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }
    assert not definitions & banned_definitions
    relative_imports = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level
    }
    assert relative_imports == {
        "kernel.policy.ledger",
        "kernel.policy.limits",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {alias.name for alias in node.names} & banned_imports
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") not in banned_imports
            assert node.module != "desktop_runtime"
        elif isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert name not in banned_calls


def test_facade_contains_no_managed_start_or_remote_transport_implementation() -> None:
    tree = _tree(FACADE)
    functions = _functions(tree)
    manager_methods = {
        node.name: node
        for node in _manager(tree).body
        if isinstance(node, ast.FunctionDef)
    }
    assert not {
        "_ollama_child_environment",
        "_set_windows_dll_directory",
        "_spawn_ollama_process",
    } & functions.keys()
    assert not {
        "_watch_bridge",
        "_discover_ide_executable",
        "_docker_exec",
        "_ensure_docker_ide",
        "_pin_host_key",
        "_ssh",
        "_start_remote_service",
    } & manager_methods.keys()
    assert {
        "ensure_bridge",
        "ensure_ide",
        "ensure_local_ollama",
        "ensure_remote_ollama",
    } <= manager_methods.keys()
    assert len(registry_sha256()) == 64


def test_work_packet_satisfies_the_post_index_contract() -> None:
    artifact = index_work_packets._artifact(ROOT, PACKET_PATH, set())
    assert artifact["declared_packet_id"] == "G1-IFACE-DESKTOP-02"
    assert artifact["artifact_role"] == "primary"
    assert artifact["metadata"] == {
        "active_gate": 1,
        "classification": "ALIGNED",
        "owner": "repository owner",
        "base_revision": "b0d22beb0897690816fe699608274bcc4943b1e3",
        "dependencies": (
            "G1-IFACE-DESKTOP-01 at "
            "bacd9e6e69d58de6aebde4847e6afd6101b2ca72"
        ),
    }
    assert artifact["sections"] == list(index_work_packets.REQUIRED_SECTIONS)

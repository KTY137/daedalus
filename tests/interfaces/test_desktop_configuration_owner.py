"""Architecture contract for the G1-IFACE-DESKTOP-02 configuration owner."""
from __future__ import annotations

import ast
import hashlib
import json
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
REGISTRY_SHA256 = "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
CONFIG_LITERAL_COUNT = 222
CONFIG_LITERAL_SHA256 = (
    "3c71d59a60d3860619c7c89d16b0d6f3461560ca4bb8efbbb03040a9a9b37ad7"
)
CONFIG_CONSTANT_SHA256 = (
    "7d72e29939fdebcc1ea401de1928f79028abcc4b929a1be128d6b8eea6432c3e"
)
PROCESS_MANAGER_AST_SHA256 = (
    "0d20d6880be9d539b68a2ed4854c085680e9e8e50dda6c6becd892a805e4f489"
)
PROCESS_AST_SHA256 = (
    "122098f5f6b8f5b9e018c45e064e4ec420d3820d7dbbf08a16a074fc70846a96"
)
CONFIG_FUNCTIONS = (
    "defaults",
    "port",
    "loopback_endpoint",
    "ide_endpoint",
    "numeric_host",
    "normalize_config",
)
PROCESS_FUNCTIONS = (
    "_frozen_windows_runtime_root",
    "_path_is_within",
    "_ollama_child_environment",
    "_set_windows_dll_directory",
    "_spawn_ollama_process",
    "_pid_is_alive",
    "install_tunnel_egress_policy",
    "install_web_integration",
)
SETTINGS_METHODS = frozenset(
    {
        "_read_budget_environment",
        "_load",
        "_save",
        "save_settings",
        "apply_environment",
    }
)
PROCESS_MANAGER_METHODS = (
    "__init__",
    "_log",
    "_creationflags",
    "_child_log",
    "bootstrap",
    "_watch_bridge",
    "_bridge_status_is_managed",
    "ensure_bridge",
    "_probe_ide",
    "_discover_ide_executable",
    "_discover_docker_executable",
    "_docker_exec",
    "_docker_error",
    "_docker_image_error",
    "_docker_inspect_container",
    "_docker_container_id",
    "_docker_container_owned",
    "_docker_project_hash",
    "_docker_mount_source_matches",
    "_docker_container_matches",
    "_canonical_ide_project",
    "_ide_ui_url",
    "_ide_status",
    "ensure_ide",
    "_docker_ide_status",
    "_remove_owned_docker_ide",
    "_ensure_docker_ide",
    "stop_ide",
    "_probe",
    "ensure_ollama",
    "ensure_local_ollama",
    "_remote",
    "_pin_host_key",
    "_ssh",
    "_target",
    "_start_remote_service",
    "ensure_remote_ollama",
    "stop_ollama_transport",
    "stop_ollama",
    "close",
    "_budget_status",
    "snapshot",
)


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


def _canonical_ast(value: object) -> object:
    if isinstance(value, ast.AST):
        return [
            type(value).__name__,
            [
                [name, _canonical_ast(child)]
                for name, child in ast.iter_fields(value)
                if name != "type_params"
            ],
        ]
    if isinstance(value, list):
        return [_canonical_ast(child) for child in value]
    return value


def _ast_sha256(nodes: Iterable[ast.AST]) -> str:
    encoded = repr([_canonical_ast(node) for node in nodes]).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_configuration_owner_has_exact_frozen_validation_literals() -> None:
    assert _literal_digest(OWNER, CONFIG_FUNCTIONS) == (
        CONFIG_LITERAL_COUNT,
        CONFIG_LITERAL_SHA256,
    )
    constants = {
        "default_config": configuration.DEFAULT_CONFIG,
        "default_ide_docker_image": configuration.DEFAULT_IDE_DOCKER_IMAGE,
        "host_pattern": configuration._HOST_RE.pattern,
        "user_pattern": configuration._USER_RE.pattern,
        "fingerprint_pattern": configuration._FP_RE.pattern,
        "ide_docker_image_pattern": configuration._IDE_DOCKER_IMAGE_RE.pattern,
    }
    encoded = json.dumps(
        constants,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    ).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == CONFIG_CONSTANT_SHA256

    first = configuration.defaults()
    second = configuration.defaults()
    first["ollama"]["remote"]["port"] = 1
    assert second["ollama"]["remote"]["port"] == 22
    assert configuration.DEFAULT_CONFIG["ollama"]["remote"]["port"] == 22


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


def test_manager_still_resolves_facade_configuration_patch_points() -> None:
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
    environment_names = {
        node.id
        for node in ast.walk(methods["apply_environment"])
        if isinstance(node, ast.Name)
    }
    assert {"normalize_config", "_defaults"} <= load_names
    assert "_numeric_host" in environment_names


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


def test_process_methods_and_effect_facade_ast_match_the_frozen_parent() -> None:
    tree = _tree(FACADE)
    functions = _functions(tree)
    manager_methods = {
        node.name: node
        for node in _manager(tree).body
        if isinstance(node, ast.FunctionDef)
    }
    assert tuple(
        name for name in manager_methods if name not in SETTINGS_METHODS
    ) == PROCESS_MANAGER_METHODS
    assert _ast_sha256(
        manager_methods[name] for name in PROCESS_MANAGER_METHODS
    ) == PROCESS_MANAGER_AST_SHA256
    assert _ast_sha256(functions[name] for name in PROCESS_FUNCTIONS) == (
        PROCESS_AST_SHA256
    )
    assert registry_sha256() == REGISTRY_SHA256


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

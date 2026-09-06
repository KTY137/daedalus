"""Architecture contract for the G1-IFACE-DESKTOP-01 strangler seam."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import pytest

from daedalus import desktop_runtime
from daedalus.interfaces import desktop
from daedalus.interfaces.desktop import http, lifecycle, projection
from daedalus.spine.effect_boundary import ENTRYPOINTS
from tools import index_work_packets


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "desktop_runtime.py"
DESKTOP_ROOT = ROOT / "daedalus" / "interfaces" / "desktop"
IMPLEMENTATIONS = {
    "http": DESKTOP_ROOT / "http.py",
    "lifecycle": DESKTOP_ROOT / "lifecycle.py",
    "projection": DESKTOP_ROOT / "projection.py",
}
SIDECAR = ROOT / "scripts" / "daedalus_desktop_sidecar.py"
SIDECAR_OWNER = DESKTOP_ROOT / "sidecar.py"
PACKET_PATH = (
    "docs/work-packets/G1-IFACE-DESKTOP-01_DESKTOP_RUNTIME_STRANGLER.md"
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


def test_registered_http_and_desktop_effect_targets_are_exact() -> None:
    rows = {
        row.id: row.target
        for row in ENTRYPOINTS
        if row.target.startswith("daedalus.interfaces.http.web_api")
    }
    assert rows == {
        "web.server": "daedalus.interfaces.http.web_api:run",
        "web.mutations": "daedalus.interfaces.http.web_api:DaedalusHandler.do_POST",
        "cli.web_api": "daedalus.interfaces.http.web_api:main",
        "web.mutations_put": "daedalus.interfaces.http.web_api:DaedalusHandler.do_PUT",
    }
    desktop_rows = {
        row.id: row.target for row in ENTRYPOINTS if row.id.startswith("python.desktop_")
    }
    assert desktop_rows == {
        "python.desktop_switch": (
            "daedalus.interfaces.desktop.effects:DesktopEffectOwner._ensure_switch"
        ),
        "python.desktop_settings_persist": (
            "daedalus.interfaces.desktop.effects:DesktopEffectOwner.save_settings"
        ),
        "python.desktop_ollama_adopt": (
            "daedalus.interfaces.desktop.effects:DesktopEffectOwner.start_ollama"
        ),
    }


def test_sidecar_keeps_the_desktop_runtime_facade_imports() -> None:
    imports = [
        node
        for node in ast.walk(_tree(SIDECAR_OWNER))
        if isinstance(node, ast.ImportFrom)
        and node.module == "daedalus.desktop_runtime"
    ]
    assert len(imports) == 1
    assert {alias.name for alias in imports[0].names} == {
        "DesktopRuntimeManager",
        "install_tunnel_egress_policy",
        "install_web_integration",
    }

    launcher_imports = [
        node
        for node in ast.walk(_tree(SIDECAR))
        if isinstance(node, ast.ImportFrom)
        and node.module == "daedalus.interfaces.desktop.sidecar"
    ]
    assert len(launcher_imports) == 1
    assert "main" in {alias.name for alias in launcher_imports[0].names}
    assert "begin_effect" not in SIDECAR.read_text(encoding="utf-8")


def test_facade_retains_only_configuration_dispatch_and_owned_cleanup() -> None:
    tree = _tree(FACADE)
    functions = _functions(tree)
    methods = _manager_methods(tree)
    assert {
        "install_tunnel_egress_policy",
        "install_web_integration",
        "normalize_config",
    } <= functions.keys()
    assert "_spawn_ollama_process" not in functions
    assert {
        "ensure_bridge",
        "ensure_ide",
        "ensure_local_ollama",
        "ensure_remote_ollama",
        "stop_ide",
        "stop_ollama",
    } <= methods.keys()
    assert not {
        "_watch_bridge",
        "_ensure_docker_ide",
        "_docker_exec",
        "_ssh",
        "_start_remote_service",
    } & methods.keys()


def test_facade_projection_and_lifecycle_methods_are_bounded_delegates() -> None:
    methods = _manager_methods(_tree(FACADE))
    delegates = {
        "_bridge_status_is_managed": (
            "desktop_projection",
            "bridge_status_is_managed",
        ),
        "_ide_status": ("desktop_projection", "ide_status"),
        "_budget_status": ("desktop_projection", "budget_status"),
        "snapshot": ("desktop_projection", "snapshot"),
    }
    for method_name, (owner, target) in delegates.items():
        method = methods[method_name]
        assert list(_calls(method, owner, target)), method_name
        assert method.end_lineno - method.lineno < 14, method_name

    for method_name, target in {
        "bootstrap": "bootstrap",
        "close": "close",
        "ensure_bridge": "start_bridge",
        "ensure_ollama": "start_ollama",
    }.items():
        method = methods[method_name]
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == target
            for node in ast.walk(method)
        ), method_name

    installer = _functions(_tree(FACADE))["install_web_integration"]
    assert list(_calls(installer, "desktop_http", "install_web_integration"))
    assert installer.end_lineno - installer.lineno < 18


def test_implementation_owners_do_not_mint_process_http_or_effect_authority() -> None:
    banned_calls = {
        "ManagedProcess",
        "Popen",
        "Thread",
        "ThreadingHTTPServer",
        "begin_effect",
        "serve_forever",
    }
    banned_definitions = {"DesktopRuntimeManager", "main", "run"}
    for label, path in IMPLEMENTATIONS.items():
        tree = _tree(path)
        definitions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        assert not definitions & banned_definitions, label
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "daedalus.desktop_runtime", label
            elif isinstance(node, ast.Import):
                assert all(
                    alias.name != "daedalus.desktop_runtime" for alias in node.names
                ), label
            elif isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                assert name not in banned_calls, (label, name)


def test_http_routes_dispatch_effects_only_through_manager_owner_facades() -> None:
    source = IMPLEMENTATIONS["http"].read_text(encoding="utf-8")
    for operation in (
        "ensure_bridge",
        "ensure_ollama",
        "stop_ollama",
        "ensure_ide",
        "stop_ide",
    ):
        assert f"manager.{operation}(" in source
    assert "manager._effect_owner" not in source
    assert "except DesktopEffectRefused as exc:" in source
    assert '"error_code": error.error_code' in source
    assert '"committed": error.committed' in source


def test_hierarchical_exports_follow_exact_facade_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "DesktopRuntimeError",
        "DesktopRuntimeManager",
        "install_tunnel_egress_policy",
        "install_web_integration",
        "normalize_config",
    ):
        assert getattr(desktop, name) is getattr(desktop_runtime, name)

    replacement = object()
    monkeypatch.setattr(desktop_runtime, "normalize_config", replacement)
    assert desktop.normalize_config is replacement


def test_facade_http_refuses_unavailable_ide_before_project_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    resolved: list[object] = []
    compared: list[tuple[str, str]] = []

    monkeypatch.setattr(
        desktop_runtime,
        "resolve_registered_project_root",
        lambda value: resolved.append(value) or "C:/registered/project",
    )
    monkeypatch.setattr(
        desktop_runtime,
        "hmac",
        SimpleNamespace(
            compare_digest=lambda supplied, expected: (
                compared.append((supplied, expected)) or supplied == expected
            )
        ),
    )

    class BaseHandler:
        path = ""
        body: object = None
        headers: dict[str, str] = {}
        server: object = SimpleNamespace(daedalus_desktop_startup_nonce="nonce")

        def _send_json(self, payload: object, status: int = 200) -> None:
            self.sent = (payload, status)

        def _handle_post(self) -> None:
            self.fell_through = True

    class Manager:
        def __init__(self) -> None:
            self.root = tmp_path
            self.projects: list[object] = []
            self.closed = False

        def ensure_ide(self, project: object = None) -> dict[str, object]:
            self.projects.append(project)
            return {"reachable": True}

        def close(self, **kwargs: object) -> None:
            self.closed = True

    manager = Manager()
    web_api = SimpleNamespace(
        DaedalusHandler=BaseHandler,
        _read_body=lambda handler: handler.body,
        core=SimpleNamespace(envelope=lambda project, **payload: payload),
    )
    desktop_runtime.install_web_integration(web_api, manager)

    start = web_api.DaedalusHandler()
    start.path = "/api/desktop/services/ide/start"
    start.body = {"project": "registered-name"}
    start._handle_post()
    assert resolved == []
    assert manager.projects == [None]

    shutdown = web_api.DaedalusHandler()
    shutdown.path = "/api/desktop/shutdown"
    shutdown.headers = {"X-Daedalus-Desktop-Nonce": "nonce"}
    shutdown._handle_post()
    assert compared == [("nonce", "nonce")]
    assert manager.closed is True


def test_only_documented_runtime_string_import_points_back_to_facade() -> None:
    tree = _tree(DESKTOP_ROOT / "__init__.py")
    imports = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "import_module"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert imports == ["daedalus.desktop_runtime"]

    assert http.install_web_integration.__module__ == (
        "daedalus.interfaces.desktop.http"
    )
    assert lifecycle.bootstrap.__module__ == (
        "daedalus.interfaces.desktop.lifecycle"
    )
    assert projection.snapshot.__module__ == (
        "daedalus.interfaces.desktop.projection"
    )


def test_work_packet_satisfies_the_post_index_contract() -> None:
    artifact = index_work_packets._artifact(ROOT, PACKET_PATH, set())
    assert artifact["declared_packet_id"] == "G1-IFACE-DESKTOP-01"
    assert artifact["artifact_role"] == "primary"
    assert artifact["metadata"] == {
        "active_gate": 1,
        "classification": "ALIGNED",
        "owner": "repository owner",
        "base_revision": "e9cf58a9e97db93d8f2627b52a59e2d58808db4b",
        "dependencies": (
            "G1-IDE-13 at fc4fdbfcf623e5659e349e2c81f709cd9afa3bea; "
            "G1-IFACE-HTTP-01 at e2f5e34714cad292963b6bb9e8b8fb11a09ad12d; "
            "G1-WP-INDEX-01 at b2e74d601ab1af274cf670c58be53645c1001114"
        ),
    }
    assert artifact["sections"] == list(index_work_packets.REQUIRED_SECTIONS)

"""Architecture contract for the G1-IFACE-DESKTOP-01 strangler seam."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import pytest

from daedalus import desktop_runtime
from daedalus.interfaces import desktop
from daedalus.interfaces.desktop import http, lifecycle, projection
from daedalus.spine.effect_boundary import ENTRYPOINTS, registry_sha256
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
PACKET_PATH = (
    "docs/work-packets/G1-IFACE-DESKTOP-01_DESKTOP_RUNTIME_STRANGLER.md"
)
REGISTRY_SHA256 = "1afe32ac18cb6cb755a1bf9a3f5aa47834c3716298e8914c0cc6c983633aef3d"
HTTP_LITERAL_COUNT = 69
HTTP_LITERAL_SHA256 = (
    "184e31150480c230aac851e1160871f1f6c0bd1204ffd249d44fefecc96cfb62"
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


def _literal_digest(path: Path, name: str) -> tuple[int, str]:
    function = _functions(_tree(path))[name]
    doc_node = (
        function.body[0]
        if function.body
        and isinstance(function.body[0], ast.Expr)
        and isinstance(function.body[0].value, ast.Constant)
        and isinstance(function.body[0].value.value, str)
        else None
    )
    values: list[list[object]] = []
    for node in ast.walk(function):
        if not (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (str, bytes, int, float, bool, type(None)))
        ):
            continue
        if doc_node is not None and node is doc_node.value:
            continue
        value: object = node.value.hex() if isinstance(node.value, bytes) else node.value
        values.append([type(node.value).__name__, value])
    values.sort(key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=True))
    encoded = json.dumps(
        values,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    ).encode("utf-8")
    return len(values), hashlib.sha256(encoded).hexdigest()


def test_registered_effect_targets_and_digest_are_unchanged() -> None:
    assert registry_sha256() == REGISTRY_SHA256
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


def test_sidecar_keeps_the_desktop_runtime_facade_imports() -> None:
    imports = [
        node
        for node in ast.walk(_tree(SIDECAR))
        if isinstance(node, ast.ImportFrom)
        and node.module == "daedalus.desktop_runtime"
    ]
    assert len(imports) == 1
    assert {alias.name for alias in imports[0].names} == {
        "DesktopRuntimeManager",
        "install_tunnel_egress_policy",
        "install_web_integration",
    }


def test_facade_retains_process_and_configuration_authority() -> None:
    tree = _tree(FACADE)
    functions = _functions(tree)
    methods = _manager_methods(tree)
    assert {
        "_spawn_ollama_process",
        "install_tunnel_egress_policy",
        "install_web_integration",
        "normalize_config",
    } <= functions.keys()
    assert {
        "ensure_bridge",
        "ensure_ide",
        "_ensure_docker_ide",
        "ensure_local_ollama",
        "ensure_remote_ollama",
        "stop_ide",
        "stop_ollama",
    } <= methods.keys()


def test_facade_projection_and_lifecycle_methods_are_bounded_delegates() -> None:
    methods = _manager_methods(_tree(FACADE))
    delegates = {
        "bootstrap": ("desktop_lifecycle", "bootstrap"),
        "close": ("desktop_lifecycle", "close"),
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


def test_http_routes_json_and_nonce_literals_match_the_frozen_parent() -> None:
    assert _literal_digest(
        IMPLEMENTATIONS["http"], "install_web_integration"
    ) == (HTTP_LITERAL_COUNT, HTTP_LITERAL_SHA256)


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


def test_facade_injects_legacy_monkeypatch_ports_into_http_owner(
    monkeypatch: pytest.MonkeyPatch,
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
    assert resolved == ["registered-name"]
    assert manager.projects == ["C:/registered/project"]

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

"""Architecture contract for the staged Gate-1 HTTP strangler seam."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pytest

from daedalus.interfaces.http import web_api
from daedalus.interfaces import http
from daedalus.interfaces.http.router import parse_request_target
from daedalus.spine.effect_boundary import ENTRYPOINTS, registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "interfaces" / "http" / "web_api.py"
HTTP_ROOT = ROOT / "daedalus" / "interfaces" / "http"
IMPLEMENTATIONS = {
    "read": HTTP_ROOT / "read.py",
    "effects": HTTP_ROOT / "effects.py",
    "sse": HTTP_ROOT / "sse.py",
    "router": HTTP_ROOT / "router.py",
}
REGISTRY_SHA256 = "615372b006399f851eb5f707ccc21ccdb347dec2e717e0911c6ac36549164752"
WIRE_LITERAL_CONTRACTS = {
    "read": (
        ("handle_get",),
        542,
        "20e596b71d368f4f06127cbc6847763922f8b8a3d2915d10a983368158085f5e",
    ),
    "effects": (
        ("handle_put", "handle_post"),
        392,
        "4ee4c3c7138a27759c0c8decce6cf2c81b53b8ca56e8b49c4abd84ec6d83dd61",
    ),
    "sse": (
        (
            "snapshot_events",
            "event_changes",
            "encode_event",
            "_open_stream",
            "_write_frame",
            "_send_event",
            "_send_keep_alive",
            "stream_events",
            "handle_events",
            "handle_ikarus_stream",
            "handle_task_events",
            "handle_conversation_request_events",
        ),
        174,
        "e4a3de4ae47c3d648d2ffb690288002079b3c6588c63f9ddad2c0d1bb74e44c7",
    ),
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def _handler_methods(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    handler = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DaedalusHandler"
    )
    return {
        node.name: node
        for node in handler.body
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


def _literal_digest(path: Path, names: tuple[str, ...]) -> tuple[int, str]:
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
                    node.value, (str, bytes, int, float, bool, type(None))
                )
            ):
                continue
            if doc_node is not None and node is doc_node.value:
                continue
            value: object = (
                node.value.hex() if isinstance(node.value, bytes) else node.value
            )
            values.append([type(node.value).__name__, value])
    values.sort(
        key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=True)
    )
    encoded = json.dumps(
        values,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    ).encode("utf-8")
    return len(values), hashlib.sha256(encoded).hexdigest()


def test_registered_http_targets_and_digest_are_unchanged() -> None:
    assert registry_sha256() == REGISTRY_SHA256
    rows = {
        row.id: row
        for row in ENTRYPOINTS
        if row.target.startswith("daedalus.interfaces.http.web_api")
    }
    assert {key: row.target for key, row in rows.items()} == {
        "web.server": "daedalus.interfaces.http.web_api:run",
        "web.mutations": "daedalus.interfaces.http.web_api:DaedalusHandler.do_POST",
        "cli.web_api": "daedalus.interfaces.http.web_api:main",
        "web.mutations_put": "daedalus.interfaces.http.web_api:DaedalusHandler.do_PUT",
    }


def test_effect_anchors_remain_real_facade_definitions() -> None:
    tree = _tree(FACADE)
    functions = _functions(tree)
    methods = _handler_methods(tree)
    assert {"run", "main"} <= functions.keys()
    assert {"do_POST", "do_PUT"} <= methods.keys()
    assert sum(
        1
        for node in ast.walk(methods["do_POST"])
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "begin_effect")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "begin_effect"
            )
        )
    ) == 1
    assert sum(
        1
        for node in ast.walk(methods["do_PUT"])
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "begin_effect")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "begin_effect"
            )
        )
    ) == 1


def test_facade_handlers_are_bounded_delegation_seams() -> None:
    methods = _handler_methods(_tree(FACADE))
    delegates = {
        "_handle_events": ("http_sse", "handle_events"),
        "_handle_ikarus_stream": ("http_sse", "handle_ikarus_stream"),
        "_handle_task_events": ("http_sse", "handle_task_events"),
        "_handle_conversation_request_events": (
            "http_sse",
            "handle_conversation_request_events",
        ),
        "_handle_get": ("http_read", "handle_get"),
        "_handle_put": ("http_effects", "handle_put"),
        "_handle_post": ("http_effects", "handle_post"),
    }
    for method_name, (owner, target) in delegates.items():
        method = methods[method_name]
        assert list(_calls(method, owner, target)), method_name
        assert method.end_lineno - method.lineno < 32, method_name


def test_implementation_layers_do_not_mint_http_or_effect_authority() -> None:
    banned_calls = {"ThreadingHTTPServer", "begin_effect", "serve_forever"}
    banned_definitions = {
        "DaedalusHandler",
        "NonLoopbackBindRefused",
        "main",
        "run",
    }
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
                assert node.module != "daedalus.interfaces.http.web_api", label
            elif isinstance(node, ast.Import):
                assert all(
                    alias.name != "daedalus.interfaces.http.web_api" for alias in node.names
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


@pytest.mark.parametrize(
    ("label", "names", "count", "expected"),
    [
        (label, names, count, expected)
        for label, (names, count, expected) in WIRE_LITERAL_CONTRACTS.items()
    ],
)
def test_routes_json_and_sse_wire_literals_match_packet_contract(
    label: str,
    names: tuple[str, ...],
    count: int,
    expected: str,
) -> None:
    assert _literal_digest(IMPLEMENTATIONS[label], names) == (count, expected)


def test_compatibility_exports_are_the_exact_legacy_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "DaedalusHandler",
        "NonLoopbackBindRefused",
        "run",
        "main",
        "_resolve_bind",
        "_read_body",
        "_json_safe",
    ):
        assert getattr(http, name) is getattr(web_api, name)

    replacement = object()
    monkeypatch.setattr(web_api, "_read_body", replacement)
    assert http._read_body is replacement

    replacement_handler = type("ReplacementHandler", (), {})
    monkeypatch.setattr(web_api, "DaedalusHandler", replacement_handler)
    assert http.DaedalusHandler is replacement_handler


def test_only_documented_runtime_string_import_points_back_to_facade() -> None:
    tree = _tree(HTTP_ROOT / "__init__.py")
    imports = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "import_module"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert imports == ["daedalus.interfaces.http.web_api"]


def test_router_preserves_raw_segment_boundaries_and_query_shape() -> None:
    target = parse_request_target(
        "/api/projects/a%2Fb/team?project=alpha&project=beta"
    )
    assert target.path == "/api/projects/a%2Fb/team"
    assert target.query == {"project": ["alpha", "beta"]}

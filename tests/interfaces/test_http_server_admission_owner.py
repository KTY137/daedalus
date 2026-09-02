from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from daedalus.interfaces.http import web_api
from daedalus.interfaces.http import server
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]


def _function(module: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_legacy_bind_contracts_resolve_to_the_canonical_owner() -> None:
    assert web_api.NonLoopbackBindRefused is server.NonLoopbackBindRefused
    assert web_api.ALLOW_REMOTE_ENV == server.ALLOW_REMOTE_ENV
    assert web_api.AUTH_TOKEN_ENV == server.AUTH_TOKEN_ENV
    assert web_api.DESKTOP_STARTUP_NONCE_ENV == server.DESKTOP_STARTUP_NONCE_ENV
    assert web_api.MIN_AUTH_TOKEN_CHARS == server.MIN_AUTH_TOKEN_CHARS
    assert web_api._resolve_bind("127.0.0.1", False) == server.resolve_bind(
        "127.0.0.1", False
    )


def test_legacy_bind_functions_are_thin_delegating_seams() -> None:
    tree = ast.parse((ROOT / "daedalus/interfaces/http/web_api.py").read_text(encoding="utf-8"))
    expected = {
        "_desktop_startup_nonce": "http_server.desktop_startup_nonce",
        "_refusal": "http_server.refusal",
        "_resolve_bind": "http_server.resolve_bind",
    }
    for name, target in expected.items():
        function = _function(tree, name)
        calls = [
            ast.unparse(node.func)
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
        ]
        assert calls == [target]


def test_admission_owner_has_no_server_or_effect_authority() -> None:
    source = (ROOT / "daedalus/interfaces/http/server.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    from_imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "daedalus.interfaces.http.web_api" not in imports | from_imports
    assert "http.server" not in imports | from_imports
    assert "ThreadingHTTPServer" not in source
    assert "BaseHTTPRequestHandler" not in source
    assert "begin_effect" not in source
    assert "serve_forever" not in source


def test_cold_owner_import_does_not_load_facade_or_runtime_effect_layers() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import json,sys;"
                f"sys.path.insert(0,{str(ROOT)!r});"
                "import daedalus.interfaces.http.server;"
                "print(json.dumps(sorted(n for n in sys.modules if "
                "n == 'daedalus.interfaces.http.web_api' or n == 'daedalus.file_bridge' "
                "or n.startswith('daedalus.providers'))))"
            ),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(probe.stdout) == []


def test_http_admission_move_keeps_effect_registry_digest() -> None:
    assert registry_sha256() == (
        "1afe32ac18cb6cb755a1bf9a3f5aa47834c3716298e8914c0cc6c983633aef3d"
    )

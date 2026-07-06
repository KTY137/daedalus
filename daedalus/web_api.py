"""Local HTTP API and static webapp host for Daedalus Agent OS."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import agents_registry, categories, control_plane, core, drafts, hierarchy, ikarus_chat, runtime_registry
from .bootstrap_prompt import claude_bootstrap_prompt
from .env import env_status, load_env
from .projects import list_projects, resolve_repo_root

ROOT = Path(__file__).resolve().parents[1]
WEB_DIST = ROOT / "apps" / "web" / "dist"


def _json_safe(payload: Any) -> bytes:
    return json.dumps(payload, default=str).encode("utf-8")


def _project_list() -> dict[str, Any]:
    rows = []
    for name in list_projects():
        try:
            from .projects import load_project

            data = load_project(name)
        except ValueError:
            data = {}
        rows.append({"name": name, "repo_root": data.get("repo_root", ""), "team": data.get("team") or {}})
    return core.envelope(None, projects=rows)


def _provider_status() -> dict[str, Any]:
    return core.envelope(None, providers=core.provider_health(None).get("providers", []))


def _read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw else {}


class DaedalusHandler(BaseHTTPRequestHandler):
    server_version = "DaedalusAgentOS/0.1"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_PUT(self) -> None:
        try:
            self._handle_put()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self) -> None:
        try:
            self._handle_post()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        data = _json_safe(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, path: str) -> None:
        target = WEB_DIST / path.lstrip("/")
        if path in ("", "/"):
            target = WEB_DIST / "index.html"
        if not target.exists() or not target.is_file():
            target = WEB_DIST / "index.html"
        if not target.exists():
            body = b"<h1>Daedalus Agent OS</h1><p>Run npm install && npm run build in apps/web.</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path
        if path == "/api/dashboard":
            self._send_json(core.get_dashboard((qs.get("project") or [None])[0]))
        elif path == "/api/projects":
            self._send_json(_project_list())
        elif path.startswith("/api/projects/") and path.endswith("/hierarchy"):
            project = unquote(path.split("/")[3])
            self._send_json(hierarchy.hierarchy(project))
        elif path.startswith("/api/projects/") and path.endswith("/control-plane"):
            project = unquote(path.split("/")[3])
            self._send_json(control_plane.unified_profiles(project))
        elif path.startswith("/api/projects/") and path.endswith("/bootstrap/claude"):
            project = unquote(path.split("/")[3])
            bootstrap = claude_bootstrap_prompt(project)
            self._send_json(core.envelope(project, prompt=bootstrap["prompt"]))
        elif path == "/api/providers/status":
            self._send_json(_provider_status())
        elif path == "/api/runtimes/status":
            self._send_json(core.envelope(None, **runtime_registry.all_status()))
        elif path == "/api/env/status":
            self._send_json(core.envelope(None, env=env_status()))
        elif path == "/api/capabilities":
            self._send_json(hierarchy.capabilities())
        elif path == "/api/drafts":
            rows = drafts.list_drafts()
            pending = [d for d in rows if d.get("status") == "pending"]
            self._send_json(core.envelope(None, drafts=rows, pending_count=len(pending)))
        elif path.startswith("/api/drafts/"):
            draft_id = unquote(path.split("/", 3)[3])
            d = drafts.get_draft(draft_id)
            self._send_json(core.envelope(None, draft=d) if d else
                            {"ok": False, "error": f"unknown draft {draft_id}"}, status=200 if d else 404)
        elif path.startswith("/api/"):
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
        else:
            self._send_static(path)

    def _handle_put(self) -> None:
        path = urlparse(self.path).path
        body = _read_body(self)
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "team":
            self._send_json(hierarchy.save_team(parts[2], body))
            return
        if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "autonomy":
            self._send_json(control_plane.save_autonomy(parts[2], body))
            return
        if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "agents":
            repo_root = resolve_repo_root(None, parts[2])
            self._send_json(core.envelope(parts[2], path=str(agents_registry.update_role(parts[4], body, repo_root))))
            return
        if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "categories":
            repo_root = resolve_repo_root(None, parts[2])
            self._send_json(core.envelope(parts[2], path=str(categories.update(parts[4], body, repo_root))))
            return
        self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)

    def _handle_post(self) -> None:
        path = urlparse(self.path).path
        body = _read_body(self)
        if path == "/api/queue":
            project = str(body.get("project") or "")
            objective = str(body.get("objective") or "").strip()
            if not project or not objective:
                self._send_json({"ok": False, "error": "project and objective are required"}, status=400)
                return
            self._send_json(core.queue_task(
                project,
                objective,
                lane=str(body.get("lane") or "local_only"),
                source=str(body.get("source") or "webapp"),
                strategy=str(body.get("strategy") or "single"),
                paths=[str(p) for p in body.get("paths") or []],
            ))
            return
        if path == "/api/ikarus/chat":
            project = str(body.get("project") or "")
            message = str(body.get("message") or "").strip()
            if not project or not message:
                self._send_json({"ok": False, "error": "project and message are required"}, status=400)
                return
            self._send_json(ikarus_chat.chat(project, message, apply=bool(body.get("apply"))))
            return
        if path.startswith("/api/drafts/") and (path.endswith("/apply") or path.endswith("/dismiss")):
            parts = [unquote(p) for p in path.strip("/").split("/")]
            draft_id, verb = parts[2], parts[3]
            if verb == "apply":
                packet = drafts.apply_payload(draft_id)
                self._send_json(core.envelope(None, applied=packet) if packet else
                                {"ok": False, "error": f"unknown draft {draft_id}"},
                                status=200 if packet else 404)
            else:
                d = drafts.set_status(draft_id, "dismissed")
                self._send_json(core.envelope(None, draft=d) if d else
                                {"ok": False, "error": f"unknown draft {draft_id}"},
                                status=200 if d else 404)
            return
        if path.startswith("/api/runtimes/") and path.endswith("/test"):
            parts = [unquote(p) for p in path.strip("/").split("/")]
            if len(parts) == 4:
                self._send_json(core.envelope(None, test=runtime_registry.test_runtime(parts[2])))
                return
        self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("DAEDALUS_WEB_DEBUG"):
            super().log_message(fmt, *args)


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    load_env()
    httpd = ThreadingHTTPServer((host, port), DaedalusHandler)
    print(f"Daedalus Agent OS listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local Daedalus Agent OS web API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    run(args.host, args.port)


if __name__ == "__main__":
    main()

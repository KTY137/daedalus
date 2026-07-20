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
from .file_bridge import stream_state
from . import ikarus_os
from .structcore.index import cached_index
from .structcore.report import structure_summary
from .structcore.slice import semantic_slice

ROOT = Path(__file__).resolve().parents[1]
WEB_DIST = ROOT / "apps" / "web" / "dist"


def _project_center(project: str | None) -> list[str]:
    """The project's declared source roots, from ``projects/<name>.json``.

    ``center`` says which subtree actually IS the project; everything else in
    the repo is shell (vendored trees, spec copies) -- indexed and resolvable
    as an import target, but withheld from metrics and not expanded through by
    the slicer. Absent/malformed -> empty, i.e. the whole repo is the center,
    which is the historical behaviour.
    """
    if not project:
        return []
    try:
        from .projects import load_project

        raw = load_project(project).get("center") or []
    except (ValueError, OSError):
        return []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x) for x in raw if str(x).strip()]


def _project_ignore(project: str | None) -> list[str]:
    """The project's ignore patterns, from ``projects/<name>.json``.

    Symmetry with ``center``: a project already declares its source root here,
    so it must be able to carve exceptions here too rather than being forced to
    add a ``.daedalusignore`` to a repo it may not own. Supports the ``@tests``
    preset -- see ``ignore.IGNORE_PRESETS``.
    """
    if not project:
        return []
    try:
        from .projects import load_project

        raw = load_project(project).get("ignore") or []
    except (ValueError, OSError):
        return []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x) for x in raw if str(x).strip()]


def _structure_index(project: str, refresh: bool = False) -> dict:
    """Shared structural index for a project (cached process-wide by repo root
    AND scope -- see ``cached_index``)."""
    return cached_index(resolve_repo_root(None, project), refresh=refresh,
                        center=_project_center(project),
                        ignore=_project_ignore(project))


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

    def _handle_events(self, project: str | None) -> None:
        """Server-Sent Events: cheap live push of bus state (queue/reports/watcher)
        so the cockpit stops polling the heavy dashboard. Reads only the file bus;
        self-recycles after 5 min (EventSource auto-reconnects)."""
        import time as _t
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except OSError:
            return

        def emit(event: str, data: Any) -> None:
            msg = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
            self.wfile.write(msg.encode("utf-8"))
            self.wfile.flush()

        try:
            last = stream_state(project)
            emit("hello", last)
            start = _t.time()
            last_ka = start
            while _t.time() - start < 300:
                _t.sleep(1.0)
                cur = stream_state(project)
                if cur.get("reports_total", 0) > last.get("reports_total", 0):
                    emit("report", cur.get("latest_report") or {})
                if cur.get("queue_depth") != last.get("queue_depth"):
                    emit("queue", {"queue_depth": cur.get("queue_depth", 0)})
                if (cur.get("watcher_state") != last.get("watcher_state")
                        or cur.get("in_flight") != last.get("in_flight")):
                    emit("heartbeat", {"watcher_state": cur.get("watcher_state"),
                                       "in_flight": cur.get("in_flight")})
                last = cur
                if _t.time() - last_ka >= 15:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    last_ka = _t.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        except Exception:
            return

    def _handle_ikarus_stream(self, qs: dict) -> None:
        """Server-Sent Events: one Ikarus chat turn, streamed token-by-token so
        the cockpit renders text as it is produced instead of blocking on the
        whole reply (the CLI cold start + full inference used to land at once).

        GET because EventSource only speaks GET. Same framing as /api/events,
        but this is a ONE-SHOT stream, not an open-ended feed, so it differs in
        one deliberate way: it sends ``Connection: close`` and drops the socket
        after ``final``. Without that the keep-alive socket lingers and the
        client hangs waiting for a turn that already ended.

        CLIENT CONTRACT: an EventSource AUTO-RECONNECTS when the server closes,
        which here would re-run the whole chat turn (and re-spend). The consumer
        MUST call ``es.close()`` when it receives ``final`` (or ``error``).

        Additive — POST /api/ikarus/ask is unchanged and still the right call
        for non-streaming clients.
        """
        project = (qs.get("project") or [""])[0]
        message = (qs.get("message") or [""])[0].strip()
        if not project or not message:
            self._send_json({"ok": False, "error": "project and message are required"}, status=400)
            return
        provider = (qs.get("provider") or [""])[0] or None
        model = (qs.get("model") or [""])[0] or None
        effort = (qs.get("effort") or [""])[0] or None

        self.close_connection = True  # one-shot: do not hold the socket open
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except OSError:
            return

        def emit(event: str, data: Any) -> None:
            msg = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
            self.wfile.write(msg.encode("utf-8"))
            self.wfile.flush()

        try:
            for event, payload in ikarus_os.ask_stream(
                project, message, provider=provider, model=model, effort=effort
            ):
                emit(event, payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return  # client navigated away mid-stream
        except Exception as exc:
            # Fail closed into a well-formed chat envelope: the UI shows a reply,
            # never a broken stream.
            try:
                emit("final", core.envelope(project, intent="error",
                                            assistant=f"I hit a snag: {exc}",
                                            provider_used="deterministic"))
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

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
        elif path == "/api/events":
            self._handle_events((qs.get("project") or [None])[0])
        elif path == "/api/ikarus/stream":
            self._handle_ikarus_stream(qs)
        elif path == "/api/structure":
            project = (qs.get("project") or [None])[0]
            if not project:
                self._send_json({"ok": False, "error": "project is required"}, status=400)
                return
            refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
            idx = _structure_index(project, refresh)
            self._send_json(core.envelope(project, structure=structure_summary(idx)))
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
        if path == "/api/ikarus/ask":
            project = str(body.get("project") or "")
            message = str(body.get("message") or "").strip()
            if not project or not message:
                self._send_json({"ok": False, "error": "project and message are required"}, status=400)
                return
            provider = body.get("provider")
            model = body.get("model")
            effort = body.get("effort")
            self._send_json(ikarus_os.ask(
                project, message,
                provider=str(provider) if provider else None,
                model=str(model) if model else None,
                effort=str(effort) if effort else None,
            ))
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
        if path == "/api/distill":
            project = str(body.get("project") or "")
            target = str(body.get("target") or "").strip()
            if not project or not target:
                self._send_json({"ok": False, "error": "project and target are required"}, status=400)
                return
            repo_root = resolve_repo_root(None, project)
            idx = _structure_index(project)
            try:
                res = semantic_slice(repo_root, target, idx=idx)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=404)
                return
            res["slice_text"] = res["slice_text"][:20000]
            self._send_json(core.envelope(project, distill=res))
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

"""Der Raum — a local web GUI for the shared cross-vendor chatroom.

    python runs/council/room_server.py [--port 8765]

Stdlib only. Binds 127.0.0.1 exclusively: this process launches real vendor
CLIs on the user's machine, so it must never be reachable from the network.

room.py stays the engine — this file is a thin transport over it:

    GET  /            -> room_ui.html
    GET  /api/room    -> {turns, raw, hash}   (?since=<hash> -> {unchanged:true})
    POST /api/say     -> {who, text}          appends a human turn
    POST /api/ask     -> {vendor, model?, extra?, attach?} -> job id, runs in a
                         background thread (a vendor call takes minutes)
    GET  /api/jobs    -> in-flight + recent jobs, with honest elapsed seconds
    GET  /api/status  -> per-vendor availability WITHOUT invoking any model

Vendor calls are serialized behind one lock so two agents can never interleave
their appends into room.md; the second call reports state=queued until it runs.
A vendor crash becomes a job in state=error *and* an appended room turn — a
silent failure in a chatroom is worse than a loud one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import room  # noqa: E402  (room.py is the engine; it lives next door)

UI_FILE = HERE / "room_ui.html"
REPO_ROOT = room.ROOM.parents[2].resolve()

DEFAULT_MODELS = {"ollama": "qwen2.5-coder:14b", "codex": "", "agy": ""}
MAX_BODY = 1 << 20          # 1 MiB of JSON is already absurd for a chat turn
JOB_HISTORY = 40            # finished jobs kept for the UI
STATUS_TTL = 5.0            # seconds; keeps a 1s UI poll off the bench
PROBE_TIMEOUT = 2.5         # seconds for the ollama /api/version probe

# --------------------------------------------------------------------------
# transcript parsing (pure; room.py is left untouched)
# --------------------------------------------------------------------------

# "### Claude  ·  Anthropic · Fable 5  ·  11:42:53"
# The tag itself contains a "·" with single spaces, so both name and tag are
# lazy and the anchored clock forces the backtracker to the right split.
_HEAD_RE = re.compile(
    r"^###[^\S\n]+(?P<name>.+?)[^\S\n]+·[^\S\n]+(?P<tag>.+?)"
    r"[^\S\n]+·[^\S\n]+(?P<time>\d{1,2}:\d{2}(?::\d{2})?)[^\S\n]*$"
)
_NAME_TO_KEY = {name.lower(): key for key, (name, _tag) in room.SPEAKERS.items()}


def parse_turns(raw: str) -> list[dict]:
    """Split the room markdown into turns.

    A "---" line only starts a new turn when the next non-blank line is a
    speaker heading, and never while inside a fenced code block — agent
    output contains horizontal rules and fences of its own.
    """
    lines = raw.split("\n")
    turns: list[dict] = []
    cur: dict | None = None
    buf: list[str] = []
    in_fence = False
    i = 0

    def flush() -> None:
        if cur is not None:
            cur["text"] = "\n".join(buf).strip()

    while i < len(lines):
        line = lines[i]
        if not in_fence and line.strip() == "---":
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            m = _HEAD_RE.match(lines[j]) if j < len(lines) else None
            if m:
                flush()
                name = m.group("name").strip()
                cur = {
                    "index": len(turns),
                    "who": _NAME_TO_KEY.get(name.lower(), name.lower()),
                    "name": name,
                    "tag": m.group("tag").strip(),
                    "time": m.group("time"),
                    "text": "",
                }
                turns.append(cur)
                buf = []
                i = j + 1
                continue
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if cur is not None:
            buf.append(line)
        i += 1

    flush()
    return turns


def room_payload() -> dict:
    raw = room.transcript()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return {
        "hash": digest,
        "raw": raw,
        "turns": parse_turns(raw),
        "speakers": {k: {"name": n, "tag": t} for k, (n, t) in room.SPEAKERS.items()},
    }


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_jobs_order: list[str] = []
_jobs_lock = threading.Lock()
_vendor_lock = threading.Lock()   # only one vendor call at a time
_say_lock = threading.Lock()      # only one appender to room.md at a time
_job_seq = 0


def _say(who: str, text: str) -> None:
    with _say_lock:
        room.say(who, text)


def _job_view(job: dict) -> dict:
    now = time.time()
    started = job.get("started_at")
    ended = job.get("ended_at")
    if job["state"] == "queued":
        elapsed = 0.0
    elif started is None:
        elapsed = 0.0
    else:
        elapsed = (ended or now) - started
    return {
        "id": job["id"],
        "vendor": job["vendor"],
        "name": room.SPEAKERS.get(job["vendor"], (job["vendor"], ""))[0],
        "model": job.get("model") or "",
        "state": job["state"],
        "created_at": job["created_at"],
        "started_at": started,
        "duration_s": round(elapsed, 1),
        "waited_s": round((started or now) - job["created_at"], 1),
        "error": job.get("error"),
        "chars": job.get("chars"),
    }


def _update(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)


def _new_job(vendor: str, model: str) -> dict:
    global _job_seq
    with _jobs_lock:
        _job_seq += 1
        job = {
            "id": f"j{_job_seq}",
            "vendor": vendor,
            "model": model,
            "state": "queued",
            "created_at": time.time(),
            "started_at": None,
            "ended_at": None,
            "error": None,
            "chars": None,
        }
        _jobs[job["id"]] = job
        _jobs_order.append(job["id"])
        # drop the oldest *finished* jobs once history is long
        if len(_jobs_order) > JOB_HISTORY:
            for old in list(_jobs_order):
                if len(_jobs_order) <= JOB_HISTORY:
                    break
                if _jobs[old]["state"] in ("done", "error"):
                    _jobs_order.remove(old)
                    _jobs.pop(old, None)
        return job


def _error_detail(exc: BaseException) -> str:
    """First line plus whatever the vendor actually said on stderr."""
    parts = [f"{type(exc).__name__}: {exc}"]
    for attr in ("stderr", "output"):
        blob = getattr(exc, attr, None)
        if isinstance(blob, (bytes, bytearray)):
            blob = blob.decode("utf-8", "replace")
        if isinstance(blob, str) and blob.strip():
            parts.append(f"{attr} tail:\n{blob.strip()[-1500:]}")
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", "replace")
            if body.strip():
                parts.append(f"response body:\n{body.strip()[-1000:]}")
        except Exception:
            pass
    tb = traceback.format_exc(limit=4).strip()
    if tb and tb != "NoneType: None":
        parts.append(f"traceback:\n{tb[-1200:]}")
    return "\n\n".join(parts)[:4000]


def _run_job(job_id: str, vendor: str, model: str, extra: str,
             attach: list[str], timeout: int) -> None:
    with _vendor_lock:
        _update(job_id, state="running", started_at=time.time())
        t0 = time.time()
        try:
            if vendor == "codex":
                reply = room.ask_codex(extra=extra, timeout=timeout, attach=attach)
            elif vendor == "ollama":
                reply = room.ask_ollama(model=model or DEFAULT_MODELS["ollama"],
                                        extra=extra, timeout=timeout, attach=attach)
            elif vendor == "agy":
                reply = room.ask_agy(model=model, extra=extra, timeout=timeout,
                                     attach=attach)
            else:
                raise ValueError(f"unknown vendor {vendor!r}")
            if not (reply or "").strip():
                raise RuntimeError("vendor returned an empty reply")
        except BaseException as exc:  # noqa: BLE001 — nothing may escape silently
            detail = _error_detail(exc)
            _update(job_id, state="error", ended_at=time.time(), error=detail)
            try:
                _say(vendor, "**call failed** — this turn is the failure, not a "
                             f"reply (job {job_id}, after {time.time() - t0:.0f}s)."
                             f"\n\n```\n{detail[:1800]}\n```")
            except Exception:
                pass
            return
        try:
            _say(vendor, reply)
        except Exception as exc:  # writing the reply failed: still be loud
            _update(job_id, state="error", ended_at=time.time(),
                    error=_error_detail(exc))
            return
        _update(job_id, state="done", ended_at=time.time(), chars=len(reply))


# --------------------------------------------------------------------------
# status — never invokes a model
# --------------------------------------------------------------------------

_status_cache: dict = {"t": 0.0, "data": None}


def _cli(name: str) -> tuple[bool, str]:
    try:
        return True, room._exe(name)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _get_json(url: str, timeout: float = PROBE_TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def build_status() -> dict:
    vendors = []

    # claude — speaks through the CLI session driving this repo, not invoked here
    vendors.append({
        "key": "claude", "name": "Claude", "tag": room.SPEAKERS["claude"][1],
        "available": True, "invokable": False,
        "detail": "speaks via the Claude Code session, not from this server",
    })

    ok, detail = _cli("codex")
    vendors.append({
        "key": "codex", "name": "Codex", "tag": room.SPEAKERS["codex"][1],
        "available": ok, "invokable": True,
        "detail": detail if ok else f"codex CLI not on PATH ({detail})",
    })

    ollama = {
        "key": "ollama", "name": "Ollama", "tag": room.SPEAKERS["ollama"][1],
        "available": False, "invokable": True, "host": room.BENCH,
        "models": [], "detail": "",
    }
    try:
        version = _get_json(f"{room.BENCH}/api/version").get("version", "?")
        ollama["available"] = True
        ollama["detail"] = f"ollama {version} at {room.BENCH}"
        try:
            tags = _get_json(f"{room.BENCH}/api/tags")
            ollama["models"] = sorted(
                m.get("name", "") for m in tags.get("models", []) if m.get("name")
            )
        except Exception:
            pass  # model list is a convenience; its absence is not a failure
    except Exception as exc:  # noqa: BLE001
        ollama["detail"] = f"no answer from {room.BENCH}/api/version ({exc})"
    vendors.append(ollama)

    ssh_ok, ssh_detail = _cli("ssh")
    vendors.append({
        "key": "agy", "name": "Antigravity", "tag": room.SPEAKERS["agy"][1],
        "available": False, "invokable": True,
        "detail": ("needs interactive sign-in — the agy CLI is installed on the "
                   f"remote bench ({room.BENCH_SSH}) but no signed-in session "
                   "exists yet"
                   + ("" if ssh_ok else f"; also: ssh not on PATH ({ssh_detail})")),
    })

    return {"vendors": vendors, "room_file": str(room.ROOM),
            "repo_root": str(REPO_ROOT), "checked_at": time.time()}


def cached_status() -> dict:
    now = time.time()
    if _status_cache["data"] is None or now - _status_cache["t"] > STATUS_TTL:
        _status_cache["data"] = build_status()
        _status_cache["t"] = now
    return _status_cache["data"]


# --------------------------------------------------------------------------
# request handling
# --------------------------------------------------------------------------

class BadRequest(Exception):
    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.code = code


def clean_attach(items) -> list[str]:
    """Repo-relative, inside the repo, and actually a file. Nothing else."""
    if items is None:
        return []
    if isinstance(items, str):
        items = [chunk for chunk in re.split(r"[,\n]", items)]
    if not isinstance(items, list):
        raise BadRequest("attach must be a list of repo-relative paths")
    out = []
    for entry in items:
        rel = str(entry).strip().strip('"').replace("\\", "/")
        if not rel:
            continue
        try:
            resolved = (REPO_ROOT / rel).resolve()
            resolved.relative_to(REPO_ROOT)
        except (ValueError, OSError):
            raise BadRequest(f"attachment escapes the repo: {rel}")
        if not resolved.is_file():
            raise BadRequest(f"no such file in repo: {rel}")
        out.append(resolved.relative_to(REPO_ROOT).as_posix())
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DerRaum/1.0"

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt, *args):  # noqa: A003
        path = getattr(self, "path", "")
        if path.startswith(("/api/room", "/api/jobs", "/api/status")):
            return  # 1s polling would drown the console
        sys.stderr.write("[room-server] %s %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, message: str, code: int = 400, **extra) -> None:
        payload = {"error": message, "status": code}
        payload.update(extra)
        self._json(payload, code)

    def _guard(self) -> bool:
        """Loopback only, and refuse DNS-rebinding Host headers."""
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self._error("this server serves loopback only", 403)
            return False
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host and host not in ("127.0.0.1", "localhost", "::1"):
            self._error(f"unexpected Host header {host!r}", 403)
            return False
        return True

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise BadRequest("empty request body")
        if length > MAX_BODY:
            raise BadRequest("request body too large", 413)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BadRequest(f"body is not valid JSON: {exc}")

    # -- routes ------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        if not self._guard():
            return
        try:
            path, _, query = self.path.partition("?")
            params = {}
            for pair in query.split("&"):
                if "=" in pair:
                    key, _, val = pair.partition("=")
                    params[key] = urllib.parse.unquote_plus(val)

            if path in ("/", "/index.html"):
                if not UI_FILE.exists():
                    return self._error(f"missing UI file {UI_FILE}", 500)
                self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            elif path == "/api/room":
                payload = room_payload()
                since = params.get("since")
                if since and since == payload["hash"]:
                    return self._json({"unchanged": True, "hash": payload["hash"]})
                self._json(payload)
            elif path == "/api/jobs":
                with _jobs_lock:
                    jobs = [_job_view(_jobs[i]) for i in _jobs_order if i in _jobs]
                self._json({"jobs": jobs,
                            "active": sum(1 for j in jobs
                                          if j["state"] in ("queued", "running"))})
            elif path == "/api/status":
                self._json(cached_status())
            else:
                self._error(f"no route for GET {path}", 404)
        except BadRequest as exc:
            self._error(str(exc), exc.code)
        except Exception as exc:  # noqa: BLE001 — never emit an HTML traceback
            self._error(f"{type(exc).__name__}: {exc}", 500,
                        traceback=traceback.format_exc(limit=3)[-1200:])

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        if not self._guard():
            return
        try:
            path = self.path.partition("?")[0]
            if path == "/api/say":
                data = self._body()
                who = str(data.get("who") or "kaya").strip().lower()
                text = str(data.get("text") or "")
                if who not in room.SPEAKERS:
                    raise BadRequest(f"unknown speaker {who!r}; "
                                     f"known: {sorted(room.SPEAKERS)}")
                if not text.strip():
                    raise BadRequest("refusing to append an empty turn")
                _say(who, text)
                payload = room_payload()
                self._json({"ok": True, "hash": payload["hash"],
                            "turns": payload["turns"], "raw": payload["raw"]})

            elif path == "/api/ask":
                data = self._body()
                vendor = str(data.get("vendor") or "").strip().lower()
                if vendor not in ("codex", "ollama", "agy"):
                    raise BadRequest("vendor must be one of codex, ollama, agy")
                model = str(data.get("model") or DEFAULT_MODELS[vendor]).strip()
                extra = str(data.get("extra") or "")
                attach = clean_attach(data.get("attach"))
                try:
                    timeout = int(data.get("timeout") or 900)
                except (TypeError, ValueError):
                    raise BadRequest("timeout must be an integer number of seconds")
                timeout = max(5, min(timeout, 3600))

                job = _new_job(vendor, model)
                threading.Thread(
                    target=_run_job,
                    args=(job["id"], vendor, model, extra, attach, timeout),
                    name=f"ask-{vendor}-{job['id']}",
                    daemon=True,
                ).start()
                self._json({"ok": True, "job": _job_view(job),
                            "attach": attach}, 202)
            else:
                self._error(f"no route for POST {path}", 404)
        except BadRequest as exc:
            self._error(str(exc), exc.code)
        except Exception as exc:  # noqa: BLE001
            self._error(f"{type(exc).__name__}: {exc}", 500,
                        traceback=traceback.format_exc(limit=3)[-1200:])


class RoomServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A browser polling once a second drops keep-alive sockets constantly.

        Those teardowns are not errors; printing a 20-line traceback for each
        would bury the console output that actually matters.
        """
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError, TimeoutError)):
            return
        sys.stderr.write(f"[room-server] error serving {client_address}: "
                         f"{traceback.format_exc(limit=4)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Local web GUI for Der Raum.")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    try:
        httpd = RoomServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(f"[room-server] cannot bind 127.0.0.1:{args.port} — {exc}",
              file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{args.port}/"
    print(f"[room-server] Der Raum  ->  {url}")
    print(f"[room-server] room file  : {room.ROOM}")
    print(f"[room-server] ollama host: {room.BENCH}")
    print("[room-server] loopback only. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[room-server] stopping")
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    # The server drives the same room engine, so it spawns the same paid vendor
    # CLIs -- and it is a THIRD entry point that never passes through
    # daedalus/cli.py, where the spend ceiling is installed. A long-lived HTTP
    # server is the worst place to be uncapped: nobody is watching the terminal.
    from daedalus.budget import install_process_guard

    install_process_guard()
    sys.exit(main())

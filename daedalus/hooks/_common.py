"""Shared plumbing for the hooks package: payload, repository root, session
state, ledger, budget. Pure stdlib; every function is safe to call with bad
input and fails toward "do nothing" rather than toward an exception.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HOOKS_DIR_REL = "runs/hooks"
LEDGER_NAME = "ledger.jsonl"
LEDGER_MAX_BYTES = 1_000_000
#: Per-turn injection budget in characters. The harness cap is 10,000 (then it
#: spills to a file); the attention budget is what matters, and 1,500 is already
#: generous for lines the model must read before the prompt.
TURN_BUDGET_CHARS = 1_500
LOCK_TIMEOUT_S = 5.0
LOCK_STALE_S = 30.0
#: Poll interval while waiting for the lock; jittered so eight waiters do not
#: wake in lockstep (measured 2026-08-23: 20 ms fixed polling starved one of
#: eight processes for > 2 s).
LOCK_POLL_S = 0.005
GIT_TIMEOUT_S = 5.0

_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class HookResult:
    """What a handler wants to say. ``text`` is plain stdout (context for
    SessionStart/UserPromptSubmit); ``payload`` is a JSON object for events
    that speak JSON (PreToolUse, PostToolUse, SubagentStart)."""

    text: str = ""
    payload: dict | None = None
    note: str = ""

    @property
    def chars(self) -> int:
        if self.payload is not None:
            return len(json.dumps(self.payload))
        return len(self.text)


# --------------------------------------------------------------------------
# payload and roots
# --------------------------------------------------------------------------


def payload_is_usable(payload: dict) -> bool:
    """A hook payload the dispatcher may act on: a dict that names the event
    and a cwd. Anything else (empty stdin, malformed JSON, a list) means "not
    a harness call" and the dispatcher does nothing -- no output, no state."""
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("hook_event_name"), str)
        and isinstance(payload.get("cwd"), str)
    )


def read_payload(stream=None) -> dict:
    stream = stream if stream is not None else sys.stdin
    try:
        raw = stream.read()
    except Exception:  # noqa: BLE001 - stdin may be closed or binary
        return {}
    try:
        data = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def git(root: Path, *args: str, timeout: float = GIT_TIMEOUT_S) -> str:
    """stdout of a git command, or "" on any failure. Never raises."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def repo_root(payload: dict, env: dict | None = None) -> Path:
    """The repository the session works in: the git toplevel of the payload's
    ``cwd``; then ``CLAUDE_PROJECT_DIR``; then the cwd itself. Never this
    file's location — that is how the archived tree got into live sessions."""
    env = os.environ if env is None else env
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    candidates = [c for c in (cwd, env.get("CLAUDE_PROJECT_DIR", "")) if c]
    for cand in candidates:
        top = git(Path(cand), "rev-parse", "--show-toplevel")
        if top:
            return Path(top).resolve()
    for cand in candidates:
        if Path(cand).is_dir():
            return Path(cand).resolve()
    return Path.cwd().resolve()


def safe_session_id(raw: Any) -> str:
    """A session id that is safe to use as a file-name component. Anything that
    is not a plain token becomes "unknown" rather than a path."""
    if isinstance(raw, str) and _SESSION_ID.match(raw):
        return raw
    return "unknown"


def hooks_dir(root: Path) -> Path:
    return root / HOOKS_DIR_REL


def display_name(root: Path) -> str:
    return root.name or str(root)


# --------------------------------------------------------------------------
# locked, atomic session state
# --------------------------------------------------------------------------


class _Lock:
    """``O_CREAT|O_EXCL`` lock file with a stale breaker. Windows-safe."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> "_Lock":
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("ascii"))
                return self
            except (FileExistsError, PermissionError):
                # PermissionError: Windows reports a lock file that another
                # process is unlinking (delete pending) as access denied, not
                # as "exists". Both mean busy.
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_S:
                        # Break a stale lock by RENAMING it first: the rename is
                        # atomic, so of two breakers only one succeeds and the
                        # other sees the lock gone rather than unlinking a
                        # lock a third process has just re-acquired.
                        stale = self.path.with_name(f"{self.path.name}.stale.{os.getpid()}")
                        os.replace(self.path, stale)
                        try:
                            os.unlink(stale)
                        except OSError:
                            pass
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"lock {self.path} busy")
                time.sleep(LOCK_POLL_S * (1 + random.random()))

    def __exit__(self, *exc) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        try:
            self.path.unlink()
        except OSError:
            pass


def state_path(root: Path, sid: str) -> Path:
    return hooks_dir(root) / f"state-{sid}.json"


def load_state(root: Path, sid: str) -> dict:
    try:
        data = json.loads(state_path(root, sid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows: the target is momentarily open by a reader.
            if attempt == 19:
                raise
            time.sleep(0.005)


def update_state(root: Path, sid: str, fn: Callable[[dict], None]) -> dict:
    """Locked read-modify-write. ``fn`` mutates the dict in place. Returns the
    state after the write; on lock timeout the mutation is applied to an
    in-memory copy only (the turn still gets its answer) and the lost write is
    noted in the returned dict under ``_lost_write``."""
    path = state_path(root, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _Lock(path.with_name(path.name + ".lock")):
            state = load_state(root, sid)
            fn(state)
            _write_atomic(path, json.dumps(state, sort_keys=True))
            return state
    except TimeoutError:
        state = load_state(root, sid)
        fn(state)
        state["_lost_write"] = True
        return state


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------


def ledger_append(root: Path, row: dict) -> None:
    """One JSON line per hook invocation; rotated once past the cap. Errors
    are swallowed: a ledger that cannot be written must not cost a turn."""
    try:
        d = hooks_dir(root)
        d.mkdir(parents=True, exist_ok=True)
        path = d / LEDGER_NAME
        try:
            if path.stat().st_size > LEDGER_MAX_BYTES:
                os.replace(path, path.with_suffix(".jsonl.1"))
        except OSError:
            pass
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# budget
# --------------------------------------------------------------------------


def trim_to_budget(lines: list[str], cap: int = TURN_BUDGET_CHARS) -> tuple[str, bool]:
    """Join ``lines`` (given in priority order, most important first) and drop
    from the END until the result fits. Returns (text, trimmed)."""
    kept = list(lines)
    trimmed = False
    while kept and len("\n".join(kept)) > cap:
        kept.pop()
        trimmed = True
    return "\n".join(kept), trimmed


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Timing:
    started: float = field(default_factory=time.perf_counter)

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

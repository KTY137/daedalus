"""Watcher ownership and liveness behind the File Bridge effect facade.

The registered ``file_bridge.watch`` effect start remains in the legacy
facade.  This module owns the OS claim, heartbeat projection, and polling loop
through explicit path, clock, publication, dispatch, and exception ports.
"""
from __future__ import annotations

import errno
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, ContextManager


HeartbeatPort = Callable[..., None]
NowEpochPort = Callable[[], float]
NowIsoPort = Callable[[], str]
PoisonPort = Callable[[Path, BaseException], Any]
ProcessRequestPort = Callable[[Path, str | None], Path]
RestartHintPort = Callable[[dict[str, Any] | None], str]
SleepPort = Callable[[float], None]
WatcherLockPort = Callable[[Path], ContextManager[Any]]
WriteTextPort = Callable[[Path, str], None]


class WatcherOwnershipBusy(RuntimeError):
    """Raised when another process already owns the bridge watch loop."""


class _BridgeWatcherLock:
    """One fail-closed OS lock for a bridge ownership scope."""

    def __init__(
        self,
        path: Path,
        *,
        blocking: bool = False,
        label: str = "bridge watcher ownership",
    ) -> None:
        self.path = Path(path)
        self.blocking = bool(blocking)
        self.label = str(label)
        self._fh: Any = None

    def __enter__(self) -> "_BridgeWatcherLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a+b")
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        contention_errnos = {
                            errno.EACCES,
                            errno.EAGAIN,
                            errno.EINTR,
                            errno.EDEADLK,
                        }
                        if not self.blocking or exc.errno not in contention_errnos:
                            raise
                        time.sleep(0.05)
            else:
                import fcntl

                mode = fcntl.LOCK_EX
                if not self.blocking:
                    mode |= fcntl.LOCK_NB
                fcntl.flock(self._fh.fileno(), mode)
        except OSError as exc:
            if self._fh is not None:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None
            raise WatcherOwnershipBusy(
                f"{self.label} is unavailable at {self.path}: {exc}"
            ) from exc
        return self

    def __exit__(self, *exc: Any) -> bool:
        if self._fh is None:
            return False
        try:
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None
        return False


def current_process_identity(
    *,
    pid: int,
    recorded_pid: int,
    nonce: str,
    new_nonce: Callable[[], str],
) -> tuple[str, int, str]:
    """Return the process identity plus refreshed facade state after a fork."""

    if pid != recorded_pid:
        recorded_pid = pid
        nonce = new_nonce()
    return f"{pid}:{nonce}", recorded_pid, nonce


def watcher_lock_path(heartbeat_path: Path) -> Path:
    return heartbeat_path.with_name("bridge_watcher.lock")


def write_heartbeat(
    *,
    heartbeat_path: Path,
    project: str | None,
    repo_root: str | None,
    interval_s: float | None,
    current: dict[str, Any] | None,
    force: bool,
    owner_token: str | None,
    process_identity: str | None,
    last_idle_beat: float,
    idle_beat_every_s: float,
    now_epoch: NowEpochPort,
    now_iso: NowIsoPort,
    pid: int,
    write_text: WriteTextPort,
) -> float:
    """Best-effort heartbeat publish; return the next throttle timestamp."""

    now = now_epoch()
    if not force and current is None and now - last_idle_beat < idle_beat_every_s:
        return last_idle_beat
    payload = {
        "ts": now_iso(),
        "epoch": now,
        "pid": pid,
        "project": project,
        "repo_root": repo_root,
        "interval_s": interval_s,
        "current": current,
        "owner_token": owner_token,
        "process_identity": process_identity,
    }
    try:
        write_text(heartbeat_path, json.dumps(payload, indent=2))
        if current is None:
            return now
    except OSError:
        pass
    return last_idle_beat


def restart_hint(heartbeat: dict[str, Any] | None = None) -> str:
    """Return the exact one-liner to start the watcher from its context."""

    heartbeat = heartbeat or {}
    if heartbeat.get("project"):
        return (
            "python -m daedalus.file_bridge watch --project "
            f"{heartbeat['project']}"
        )
    if heartbeat.get("repo_root"):
        return (
            'python -m daedalus.file_bridge watch --repo-root '
            f'"{heartbeat["repo_root"]}"'
        )
    return "python -m daedalus.file_bridge watch --project <project>"


def heartbeat_status(
    *,
    heartbeat_path: Path,
    now: float,
    stale_after_s: float,
    busy_budget_s: float,
    restart: RestartHintPort,
) -> dict[str, Any]:
    """Classify a heartbeat as none, alive, busy, wedged, or stale."""

    try:
        heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {
            "state": "none",
            "restart": restart(None),
            "detail": (
                "no heartbeat recorded (watcher not running, or "
                "started before the heartbeat feature landed)"
            ),
        }
    age = max(0.0, now - float(heartbeat.get("epoch") or 0.0))
    out = {
        "age_s": round(age, 1),
        "pid": heartbeat.get("pid"),
        "project": heartbeat.get("project"),
        "repo_root": heartbeat.get("repo_root"),
        "current": heartbeat.get("current"),
        "owner_token": heartbeat.get("owner_token"),
        "process_identity": heartbeat.get("process_identity"),
        "restart": restart(heartbeat),
    }
    current = heartbeat.get("current")
    if current:
        busy_for = max(0.0, now - float(current.get("started_epoch") or 0.0))
        out["busy_for_s"] = round(busy_for, 1)
        out["state"] = "busy" if busy_for <= busy_budget_s else "wedged"
        return out
    out["state"] = "alive" if age <= stale_after_s else "stale"
    return out


def watch_loop(
    *,
    outbox: Path,
    inbox: Path,
    watcher_lock_path: Path,
    default_repo_root: str | None,
    interval_s: float,
    project: str | None,
    owner_token: str,
    process_identity: str,
    stop_event: Any | None,
    heartbeat: HeartbeatPort,
    watcher_lock: WatcherLockPort,
    process_request: ProcessRequestPort,
    handle_poison: PoisonPort,
    pending_exceptions: tuple[tuple[type[BaseException], str], ...],
    now_epoch: NowEpochPort,
    now_iso: NowIsoPort,
    sleep: SleepPort,
) -> None:
    """Run the admitted polling loop under one OS-held watcher claim."""

    def beat(current: dict[str, Any] | None = None, force: bool = False) -> None:
        heartbeat(
            project=project,
            repo_root=default_repo_root,
            interval_s=interval_s,
            current=current,
            force=force,
            owner_token=owner_token,
            process_identity=process_identity,
        )

    with watcher_lock(watcher_lock_path):
        outbox.mkdir(parents=True, exist_ok=True)
        inbox.mkdir(parents=True, exist_ok=True)
        beat(force=True)
        print("AGENT_BRIDGE_START", flush=True)
        print(f"Watching {outbox}", flush=True)
        print("AGENT_BRIDGE_READY", flush=True)

        while not (stop_event is not None and stop_event.is_set()):
            beat()
            for path in sorted(outbox.glob("*.json")):
                print(f"Processing {path.name}", flush=True)
                beat(
                    current={
                        "file": path.name,
                        "started_epoch": now_epoch(),
                        "started_ts": now_iso(),
                    },
                    force=True,
                )
                try:
                    result = process_request(path, default_repo_root)
                    print(f"Wrote {result}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    pending_label = next(
                        (
                            label
                            for exception_type, label in pending_exceptions
                            if isinstance(exc, exception_type)
                        ),
                        None,
                    )
                    if pending_label is not None:
                        print(f"{pending_label} {path.name}: {exc}", flush=True)
                    else:
                        handle_poison(path, exc)
                beat(force=True)
            if stop_event is not None:
                if stop_event.wait(interval_s):
                    break
            else:
                sleep(interval_s)

"""Declared working windows and durable shift context for autonomous agents.

The high-level :class:`Shift` API exposes a human-readable goal/deadline context.
The lower-level :class:`ShiftManager` and :class:`WorkingWindow` contracts retain
the deterministic persistence and boundary primitives used by the original
DeepSeek laboratory tests.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Mapping

SHIFT_VERSION = "1"
SHIFT_REL_PATH = "runs/shift.json"


def _now() -> datetime:
    """Read the wall clock afresh; the value is deliberately never cached."""
    return datetime.now().astimezone()


def _parse_until(value: str, *, now: datetime | None = None) -> datetime | None:
    """Accept ``HH:MM``, ``+90m``, ``+2h`` or a full ISO timestamp."""
    now = now or _now()
    v = (value or "").strip()
    if not v:
        return None
    if v.startswith("+"):
        unit = v[-1].lower()
        try:
            amount = float(v[1:-1])
        except ValueError:
            return None
        if unit == "m":
            return now + timedelta(minutes=amount)
        if unit == "h":
            return now + timedelta(hours=amount)
        return None
    if len(v) <= 5 and ":" in v:
        try:
            hh, mm = (int(part) for part in v.split(":", 1))
            candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        except (TypeError, ValueError):
            return None
        return candidate if candidate > now else candidate + timedelta(days=1)
    try:
        parsed = datetime.fromisoformat(v)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


@dataclass
class Shift:
    goal: str = ""
    started: str = ""
    until: str = ""
    done_means: str = ""
    notes: list[Any] = field(default_factory=list)
    version: str = SHIFT_VERSION

    def remaining(self) -> timedelta | None:
        end = _parse_until(self.until) if self.until else None
        if end is None:
            try:
                end = datetime.fromisoformat(self.until).astimezone()
            except (ValueError, TypeError):
                return None
        return end - _now()

    @property
    def expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining.total_seconds() <= 0

    def elapsed(self) -> timedelta | None:
        try:
            return _now() - datetime.fromisoformat(self.started).astimezone()
        except (ValueError, TypeError):
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "started": self.started,
            "until": self.until,
            "done_means": self.done_means,
            "notes": list(self.notes),
            "version": self.version,
        }

    def render(self) -> str:
        """Render one compact, console-safe context line."""
        now = _now().strftime("%H:%M")
        if not self.goal:
            return f"[{now}] no shift declared"
        parts = [f"[{now}]"]
        remaining = self.remaining()
        if remaining is None:
            parts.append("no end declared")
        elif remaining.total_seconds() <= 0:
            parts.append(f"SHIFT ENDED {_hm(-remaining)} ago (was {self.until})")
        else:
            parts.append(f"{_hm(remaining)} left (until {self.until})")
        elapsed = self.elapsed()
        if elapsed is not None:
            parts.append(f"{_hm(elapsed)} worked")
        parts.append(f"goal: {self.goal}")
        if self.done_means:
            parts.append(f"done = {self.done_means}")
        return "  |  ".join(parts)


def _hm(value: timedelta) -> str:
    total = int(abs(value.total_seconds()))
    hours, minutes = divmod(total // 60, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Publish JSON atomically and remove a temporary file after any failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


class StateCorruptError(ValueError):
    """Raised when a persisted manager state exists but is not admissible JSON."""


@dataclass(frozen=True)
class WorkingWindow:
    """A half-open daily window ``[start_time, end_time)``.

    A start later than the end denotes a window crossing midnight. Equal
    boundaries denote an empty window, avoiding an implicit 24-hour grant.
    """

    start_time: clock_time
    end_time: clock_time

    def __post_init__(self) -> None:
        if not isinstance(self.start_time, clock_time) or not isinstance(
            self.end_time, clock_time
        ):
            raise TypeError("working-window boundaries must be datetime.time values")
        if (self.start_time.tzinfo is None) != (self.end_time.tzinfo is None):
            raise ValueError("working-window boundaries must use matching timezone awareness")

    def contains(self, moment: datetime) -> bool:
        if not isinstance(moment, datetime):
            raise TypeError("moment must be a datetime")
        current = moment.timetz() if self.start_time.tzinfo is not None else moment.time()
        if self.start_time == self.end_time:
            return False
        if self.start_time < self.end_time:
            return self.start_time <= current < self.end_time
        return current >= self.start_time or current < self.end_time


class ShiftManager:
    """Deterministic atomic JSON persistence for generic shift state.

    The lock path is deliberately separate from the replaced state file. A
    transient lock marker is removed when this instance created it; a pre-existing
    marker is tolerated so an independently held lock handle cannot block atomic
    replacement of the state file itself.
    """

    @staticmethod
    def _state_path(state_path: str | os.PathLike[str]) -> Path:
        if not isinstance(state_path, (str, os.PathLike)):
            raise TypeError("state_path must be path-like")
        return Path(state_path)

    def publish(
        self,
        data: Mapping[str, Any],
        state_path: str | os.PathLike[str],
    ) -> None:
        if not isinstance(data, Mapping):
            raise TypeError("state must be a mapping")
        path = self._state_path(state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = Path(str(path) + ".lock")
        created_lock = not lock_path.exists()

        # Opening a directory here raises OSError before any state mutation. A
        # normal pre-existing/open lock file remains compatible with replacement
        # because it is not the file passed to os.replace().
        try:
            with lock_path.open("a", encoding="utf-8"):
                pass
        except OSError:
            raise

        import time as _time

        tmp = path.with_name(
            f".{path.name}.{os.getpid()}.{_time.monotonic_ns()}.tmp"
        )
        try:
            encoded = json.dumps(
                dict(data),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
            with tmp.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        finally:
            if created_lock:
                try:
                    lock_path.unlink()
                except OSError:
                    pass

    def load(self, state_path: str | os.PathLike[str]) -> dict[str, Any]:
        path = self._state_path(state_path)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError:
            raise
        if not text.strip():
            raise StateCorruptError(f"shift state is empty: {path}")
        try:
            value = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise StateCorruptError(f"shift state is not valid JSON: {path}") from exc
        if not isinstance(value, dict):
            raise StateCorruptError("shift state root must be an object")
        if "version" in value and type(value["version"]) is not int:
            raise StateCorruptError("shift state version must be an integer")
        return value


class _ShiftLock:
    """Exclusive, bounded, best-effort lock for read-modify-write checkpoints."""

    def __init__(self, path: Path, timeout_s: float = 2.0) -> None:
        self.path = Path(str(path) + ".lock")
        self.timeout_s = timeout_s
        self._fd: int | None = None

    def __enter__(self) -> bool:
        import time

        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fd = os.open(
                    str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR
                )
                return True
            except FileExistsError:
                if time.monotonic() >= deadline:
                    try:
                        if time.time() - self.path.stat().st_mtime > self.timeout_s:
                            self.path.unlink()
                            continue
                    except OSError:
                        pass
                    return False
                time.sleep(0.05)
            except OSError:
                return False

    def __exit__(self, *exc: Any) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
        try:
            self.path.unlink()
        except OSError:
            pass
        return None


def _path(repo_root: str | os.PathLike[str] | None = None) -> Path:
    root = Path(repo_root or os.environ.get("DAEDALUS_REPO_ROOT") or ".")
    return root / SHIFT_REL_PATH


def load(repo_root: str | os.PathLike[str] | None = None) -> Shift:
    """Return the declared shift, or an empty shift when none is present."""
    path = _path(repo_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Shift()
    if not isinstance(raw, dict):
        return Shift()
    return Shift(
        goal=str(raw.get("goal") or ""),
        started=str(raw.get("started") or ""),
        until=str(raw.get("until") or ""),
        done_means=str(raw.get("done_means") or ""),
        notes=list(raw.get("notes") or []),
    )


def start(
    goal: str,
    until: str = "",
    done_means: str = "",
    repo_root: str | os.PathLike[str] | None = None,
) -> Shift:
    shift = Shift(
        goal=goal,
        started=_now().isoformat(timespec="seconds"),
        until=until,
        done_means=done_means,
    )
    _write_atomic(_path(repo_root), shift.to_dict())
    return shift


def note(
    text: str,
    repo_root: str | os.PathLike[str] | None = None,
) -> Shift:
    """Append a durable checkpoint under a bounded read-modify-write lock."""
    path = _path(repo_root)
    with _ShiftLock(path) as acquired:
        shift = load(repo_root)
        shift.notes.append(
            {
                "at": _now().strftime("%H:%M"),
                "text": text,
                "locked": bool(acquired),
            }
        )
        _write_atomic(path, shift.to_dict())
    return shift


def end(repo_root: str | os.PathLike[str] | None = None) -> None:
    try:
        _path(repo_root).unlink()
    except OSError:
        pass


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    if not argv or argv[0] in ("status", "-s"):
        print(load().render())
        return 0
    command = argv[0]
    if command == "start":
        goal = argv[1] if len(argv) > 1 else ""
        until = argv[2] if len(argv) > 2 else ""
        done = argv[3] if len(argv) > 3 else ""
        print(start(goal, until, done).render())
        return 0
    if command == "note":
        print(note(" ".join(argv[1:])).render())
        return 0
    if command == "end":
        end()
        print("shift ended")
        return 0
    print(
        "usage: python -m daedalus.shift "
        "[status|start GOAL UNTIL [DONE]|note TEXT|end]"
    )
    return 2


__all__ = [
    "SHIFT_REL_PATH",
    "SHIFT_VERSION",
    "Shift",
    "ShiftManager",
    "StateCorruptError",
    "WorkingWindow",
    "end",
    "load",
    "note",
    "start",
]


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(main(sys.argv[1:]))

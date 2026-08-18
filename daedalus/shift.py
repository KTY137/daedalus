"""shift.py — a declared working window, so an agent cannot lose the clock.

WHY THIS EXISTS
---------------
On 2026-07-30 an agent (me) was told to work until 10:00, read a clock once at
the start, estimated elapsed time from its own sense of progress, and announced
"it is 10 o'clock" at 03:10. Nothing in the loop had told it otherwise, because
nothing in the loop ever mentions the time. An agent has no wall clock: it sees
the conversation, and a conversation has no duration.

The fix is not "try harder to track time". It is to make the current time and
the declared deadline part of the CONTEXT on every turn, so the failure mode
becomes impossible rather than unlikely. ``hook.py`` beside this module does
that for Claude Code; ``Shift`` is the object both that hook and an autonomous
Ikarus loop read.

WHAT A SHIFT IS
---------------
Four facts, and no cleverness: what is being worked on, when it started, when it
must stop, and what "done" would mean. The last one matters most — a deadline
without a goal produces an agent that stops on time having done nothing in
particular.

DESIGN RULES
------------
* **A shift is DECLARED, never inferred.** Nothing here guesses that work has
  begun. An absent shift reports "no shift declared", which is a real answer.
* **The clock is the operating system's**, read fresh on every call. A cached
  timestamp is exactly the bug this module exists to prevent.
* **Expiry is reported, never enforced.** This module does not stop anything; it
  makes the truth visible and leaves the decision where it belongs. A guard that
  silently killed work would be a worse failure than a late finish.
* stdlib only, no daemon, no background process. The state is one small JSON
  file, so it survives a restart and can be read by anything.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .atomic import write_text_atomic

SHIFT_VERSION = "1"
SHIFT_REL_PATH = "runs/shift.json"


def _now() -> datetime:
    """The wall clock, read fresh. Never cached, never passed in."""
    return datetime.now().astimezone()


def _parse_until(value: str, *, now: datetime | None = None) -> datetime | None:
    """Accept ``HH:MM``, ``+90m``, ``+2h`` or a full ISO timestamp.

    ``HH:MM`` means the NEXT occurrence of that time, so "until 10:00" declared
    at 03:10 means this morning, and the same words at 11:00 mean tomorrow. That
    is what a person means and it is worth the four lines.
    """
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
            hh, mm = (int(x) for x in v.split(":", 1))
        except ValueError:
            return None
        cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return cand if cand > now else cand + timedelta(days=1)
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
    notes: list = field(default_factory=list)
    version: str = SHIFT_VERSION

    # ── derived, always against a FRESH clock ─────────────────────────────
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
        rem = self.remaining()
        return rem is not None and rem.total_seconds() <= 0

    def elapsed(self) -> timedelta | None:
        try:
            return _now() - datetime.fromisoformat(self.started).astimezone()
        except (ValueError, TypeError):
            return None

    def to_dict(self) -> dict:
        return {"goal": self.goal, "started": self.started, "until": self.until,
                "done_means": self.done_means, "notes": list(self.notes),
                "version": self.version}

    def render(self) -> str:
        """One line for a human, and for a prompt. Time first, always."""
        now = _now().strftime("%H:%M")
        if not self.goal:
            return f"[{now}] no shift declared"
        bits = [f"[{now}]"]
        rem = self.remaining()
        if rem is None:
            bits.append("no end declared")
        elif rem.total_seconds() <= 0:
            over = -rem
            bits.append(f"SHIFT ENDED {_hm(over)} ago (was {self.until})")
        else:
            bits.append(f"{_hm(rem)} left (until {self.until})")
        el = self.elapsed()
        if el is not None:
            bits.append(f"{_hm(el)} worked")
        bits.append(f"goal: {self.goal}")
        if self.done_means:
            bits.append(f"done = {self.done_means}")
        return "  |  ".join(bits)   # ASCII: this line lands in a cp1252 console


def _hm(td: timedelta) -> str:
    total = int(abs(td.total_seconds()))
    h, m = divmod(total // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"



# --------------------------------------------------------------------------- #
# Concurrency: several processes touch this file at once                        #
# --------------------------------------------------------------------------- #
# A ticker polls it, a prompt hook reads it on every turn, and the agent appends
# checkpoints -- concurrently, by construction. ``Path.write_text`` truncates
# and then writes, so a reader landing in between sees an EMPTY file, and
# ``load`` would report "no shift declared" while a shift was running: silently
# wrong, which is worse than loudly broken.
#
# Two mechanisms, matching what this repo already does elsewhere
# (``file_bridge._write_json_atomic`` and ``budget._BudgetLock``):
#   * publish via a temp file plus ``os.replace``, which is atomic on POSIX and
#     Windows, so a reader sees the old content or the new one and never a torn
#     one; readers therefore need no lock at all;
#   * take a separate LOCK FILE for read-modify-write (``note``), because
#     atomicity alone still loses one of two concurrent appends. The lock file
#     is separate from the data file deliberately: on Windows you cannot replace
#     a file another handle holds open.


def _write_atomic(path: Path, payload: dict) -> None:
    """Publish the shift file. Delegates to ``daedalus.atomic``.

    The comment block above says the replace "is atomic on POSIX and Windows".
    That is true of the syscall and NOT true of this call: on win32 the ticker
    reads this exact file on a timer, holds it open without FILE_SHARE_DELETE,
    and the replace then fails with ERROR_ACCESS_DENIED. ``daedalus.atomic``
    carries the bounded retry that was measured against that case.
    """
    write_text_atomic(path, json.dumps(payload, indent=1))


class _ShiftLock:
    """Exclusive, best-effort, and it never blocks the caller forever.

    A shift note is bookkeeping: losing one to a timeout is a small harm, and
    hanging an agent's turn on a stale lock is a large one. So the timeout is
    short and expiry is REPORTED by returning False rather than raising --
    unlike ``budget._BudgetLock``, where an unobtainable lock must refuse
    because money is involved.
    """

    def __init__(self, path: Path, timeout_s: float = 2.0) -> None:
        self.path = Path(str(path) + ".lock")
        self.timeout_s = timeout_s
        self._fd = None

    def __enter__(self) -> bool:
        import time
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return True
            except FileExistsError:
                if time.monotonic() >= deadline:
                    # A lock older than the timeout is assumed abandoned: the
                    # holder crashed. Steal it rather than deadlock a hook.
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

    def __exit__(self, *exc) -> None:
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


# --------------------------------------------------------------------------- #
def _path(repo_root=None) -> Path:
    root = Path(repo_root or os.environ.get("DAEDALUS_REPO_ROOT") or ".")
    return root / SHIFT_REL_PATH


def load(repo_root=None) -> Shift:
    """The declared shift, or an empty one. A missing file is not an error —
    it means nobody declared a shift, which is a legitimate state."""
    p = _path(repo_root)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Shift()
    return Shift(goal=str(raw.get("goal") or ""),
                 started=str(raw.get("started") or ""),
                 until=str(raw.get("until") or ""),
                 done_means=str(raw.get("done_means") or ""),
                 notes=list(raw.get("notes") or []))


def start(goal: str, until: str = "", done_means: str = "", repo_root=None) -> Shift:
    s = Shift(goal=goal, started=_now().isoformat(timespec="seconds"),
              until=until, done_means=done_means)
    _write_atomic(_path(repo_root), s.to_dict())
    return s


def note(text: str, repo_root=None) -> Shift:
    """Append a checkpoint. What survives a restart is what was written down."""
    p = _path(repo_root)
    with _ShiftLock(p) as got:
        # Read INSIDE the lock: reading first would let two appends race and
        # drop one, which is the whole reason a lock exists here.
        s = load(repo_root)
        s.notes.append({"at": _now().strftime("%H:%M"), "text": text,
                        "locked": bool(got)})
        _write_atomic(p, s.to_dict())
    return s


def end(repo_root=None) -> None:
    try:
        _path(repo_root).unlink()
    except OSError:
        pass


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    if not argv or argv[0] in ("status", "-s"):
        print(load().render())
        return 0
    cmd = argv[0]
    if cmd in ("start", "note", "end"):
        # Read-only status stays fail-open above; every state write starts
        # at the central boundary.
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "cli.shift",
            REGISTRY_BY_ID["cli.shift"].effects,
            (process_guard_boundary_decision(),),
        )
    if cmd == "start":
        goal = argv[1] if len(argv) > 1 else ""
        until = argv[2] if len(argv) > 2 else ""
        done = argv[3] if len(argv) > 3 else ""
        print(start(goal, until, done).render())
        return 0
    if cmd == "note":
        print(note(" ".join(argv[1:])).render())
        return 0
    if cmd == "end":
        end()
        print("shift ended")
        return 0
    print("usage: python -m daedalus.shift [status|start GOAL UNTIL [DONE]|note TEXT|end]")
    return 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv[1:]))

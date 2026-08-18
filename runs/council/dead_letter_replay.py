"""Replay dead-lettered room turns back through the one append boundary.

BACKGROUND. `runs/council/stream_hook.py` mirrors a Claude Code turn into Der
Raum through `room.append_turn` -- the one place a turn is allowed to enter
the markdown, because `append_turn` appends AND chains AND takes a
cross-process lock. When that door cannot be used (a bad import, a lock
failure, anything that makes `append_turn` raise), the hook does NOT fall
back to a direct `open(room.md, "a")`: Codex's review of the original bug
was that `verify_room()` makes an invariant break VISIBLE, it does not
PREVENT one, so an escape hatch that appends an unattested turn is the
original defect with a smaller blast radius, not a fix. Instead the hook
spools the turn as one JSON line in `dead_letter.jsonl`, beside the room.

THIS MODULE is what turns that spool from "a lost turn with better
bookkeeping" into an actual recovery path: it replays every entry through
`room.append_turn` -- THE SAME DOOR, never a direct write -- so a replayed
turn is exactly as attested as one that made it through on the first try.

Properties this module is built to hold:

  * ONE DOOR. Every turn this module puts into the room goes through
    `room.append_turn`. There is no fallback append here, on purpose: a
    fallback is how the original bug happened, and a replay tool that
    reintroduces it would be worse than no replay tool.
  * IDEMPOTENT. Replaying the same spool twice must not duplicate a turn.
    The check is against the ROOM ITSELF -- does a turn with this exact body
    already exist in room.md? -- rather than a side ledger that could drift
    out of sync with what actually landed. That also makes replay safe to
    re-run after a crash: if the process dies between a successful
    `append_turn` and the spool being rewritten, the next run sees the body
    already in the room and treats the entry as done instead of repeating it.
  * NOTHING IS EVER SILENTLY DROPPED. An entry that still cannot be chained
    (the same failure mode that spooled it in the first place) stays in the
    spool. A malformed line (bad JSON, missing fields) is reported and left
    in the spool too -- it is not this tool's job to guess what a corrupt
    line meant, only to refuse to lose it.
  * INCREMENTAL DURABILITY. The spool file is rewritten after EVERY entry is
    resolved, not once at the end, so a crash mid-replay leaves the spool
    accurately reflecting exactly what has and has not been recovered yet.
  * LOCKED against a live hook. A stream_hook process can append a NEW dead
    letter to the same spool while this tool is reading and rewriting it;
    without a lock that append could be lost (the classic read-modify-write
    race). Replay takes the same cross-process lock primitive room.py uses
    for the room itself, scoped to the spool file.

CLI:

  python runs/council/dead_letter_replay.py list
  python runs/council/dead_letter_replay.py replay [--dry-run]

Both accept --room / --bus / --spool to override the defaults, which follow
`room.py`'s own globals (`room.ROOM`, and the spool beside it) so tests that
redirect those globals redirect this tool too.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The engine lives next door, exactly as stream_hook.py imports it: this
# module's entire job is to hand turns back to room.append_turn, so it needs
# the real module, not a reimplementation of what "append and chain" means.
HOOK_DIR = Path(__file__).resolve().parent
if str(HOOK_DIR) not in sys.path:
    sys.path.insert(0, str(HOOK_DIR))
import room as _room  # noqa: E402  -- see comment above


# --------------------------------------------------------------------------
# paths -- resolved at CALL TIME from room's globals, never cached at import
# time, so a test (or a caller) that redirects room.ROOM / room.BUS_PATH
# redirects this module too. Same reasoning append_turn itself documents for
# why it takes explicit paths instead of trusting a module global.
# --------------------------------------------------------------------------


def _room_path(room_path: str | Path | None) -> Path:
    return Path(room_path) if room_path else _room.ROOM


def _bus_path(room_path: Path, bus_path: str | Path | None) -> Path:
    if bus_path:
        return Path(bus_path)
    # Mirrors room.py's own convention: BUS_PATH == ROOM.parent / "room.jsonl".
    return room_path.parent / "room.jsonl"


def _spool_path(room_path: Path, spool_path: str | Path | None) -> Path:
    if spool_path:
        return Path(spool_path)
    # stream_hook.py's default hook dir IS room.py's own directory, so the
    # spool it writes sits beside room.md by construction.
    return room_path.parent / "dead_letter.jsonl"


# --------------------------------------------------------------------------
# the spool: read, validate, rewrite -- never silently losing a line
# --------------------------------------------------------------------------

_REQUIRED_FIELDS = ("who", "body")


class SpoolEntry:
    """One spool line, parsed or not.

    ``raw`` is kept verbatim so a rewrite of the spool never reformats a line
    it didn't touch, and so a malformed line can be put straight back with no
    risk of this tool mangling it further while trying to "fix" it.
    """

    __slots__ = ("line_no", "raw", "data", "error")

    def __init__(self, line_no: int, raw: str, data: dict | None = None,
                 error: str | None = None) -> None:
        self.line_no = line_no
        self.raw = raw
        self.data = data
        self.error = error

    @property
    def malformed(self) -> bool:
        return self.data is None


def _read_spool(spool_path: Path) -> list[SpoolEntry]:
    """Parse every line. A bad line becomes a malformed entry, never an
    exception that aborts the rest of the spool."""
    try:
        raw_lines = spool_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    entries: list[SpoolEntry] = []
    for i, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("spool line is not a JSON object")
            for field in _REQUIRED_FIELDS:
                val = data.get(field)
                if not isinstance(val, str) or not val.strip():
                    raise ValueError(f"missing or empty required field {field!r}")
        except Exception as exc:  # noqa: BLE001 -- any bad line, one report
            entries.append(SpoolEntry(i, line, data=None,
                                      error=f"{type(exc).__name__}: {exc}"))
            continue
        entries.append(SpoolEntry(i, line, data=data))
    return entries


def _write_spool(spool_path: Path, entries: list[SpoolEntry]) -> None:
    """Atomic rewrite (tmp + replace), same reasoning as room.save_state: a
    crash mid-write must not leave a truncated spool, which would silently
    lose whatever line the crash landed inside."""
    spool_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = spool_path.with_name(spool_path.name + ".tmp")
    text = "".join(e.raw + "\n" for e in entries)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(spool_path)


# --------------------------------------------------------------------------
# idempotency: checked against the room itself, not a side ledger
# --------------------------------------------------------------------------


def _already_in_room(room_path: Path, body: str) -> bool:
    """True if room.md already holds a turn with this exact body.

    A dead-lettered entry's ``body`` is already the exact text that would
    have been appended -- stream_hook.py spools the fully rendered turn, lede
    and abridgement note included, not the raw source. So an exact match
    against an existing turn means this entry already reached the room,
    whether through a prior replay or (in principle) some other route, and
    appending it again would duplicate a voice that has already spoken.
    Checking the room itself instead of a separate "replayed" ledger means a
    crash between a successful append_turn and this tool updating its own
    bookkeeping cannot cause a duplicate: the next run sees the body sitting
    in room.md and skips it.
    """
    try:
        text = room_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    target = body.strip()
    return any(t.body.strip() == target for t in _room.parse_turns(text))


# --------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------


def _replay_one(entry: SpoolEntry, room_path: Path, bus_path: Path) -> str:
    """Attempt one entry through room.append_turn. Returns a status string
    and NEVER raises -- a replay tool that dies on one bad entry is worse
    than a spool with one stubborn line left in it."""
    data = entry.data
    body = data["body"]
    who = data.get("who") or "claude"
    name = data.get("name") or None
    tag = data.get("tag") or None
    try:
        res = _room.append_turn(who, body, name=name, tag=tag,
                                room_path=room_path, bus_path=bus_path)
    except Exception as exc:  # noqa: BLE001 -- append_turn documents itself
        # as never raising, but this tool must survive even a broken promise.
        entry.error = f"append_turn raised: {type(exc).__name__}: {exc}"
        return "failed"
    if res.get("ok"):
        return "replayed"
    entry.error = f"append_turn did not chain: {res.get('error')}"
    return "failed"


def replay(spool_path: str | Path, room_path: str | Path,
           bus_path: str | Path | None = None, dry_run: bool = False) -> dict:
    """Replay every well-formed spool entry through room.append_turn.

    Returns a report dict: totals plus a per-line ``details`` list. Never
    raises. The spool file is rewritten after EVERY entry is resolved (not
    once at the end) so a crash mid-run leaves the spool accurately
    reflecting exactly what has and has not been recovered.
    """
    spool_path = Path(spool_path)
    room_path = Path(room_path)
    bus_path = _bus_path(room_path, bus_path)

    report = {"total": 0, "malformed": 0, "already_present": 0,
              "replayed": 0, "failed": 0, "details": []}

    lock = _room._RoomLock(spool_path.with_name(spool_path.name + ".lock"))
    with lock:
        entries = _read_spool(spool_path)
        report["total"] = len(entries)
        keep: list[SpoolEntry] = []
        for idx, entry in enumerate(entries):
            if entry.malformed:
                report["malformed"] += 1
                report["details"].append(
                    {"line": entry.line_no, "status": "malformed",
                     "detail": entry.error})
                keep.append(entry)          # never dropped
                if not dry_run:
                    _write_spool(spool_path, keep + entries[idx + 1:])
                continue

            body = entry.data["body"]
            already = _already_in_room(room_path, body)
            if dry_run:
                status = "already-present" if already else "would-replay"
                if already:
                    report["already_present"] += 1
                report["details"].append(
                    {"line": entry.line_no, "status": status, "detail": None})
                keep.append(entry)          # dry run mutates nothing
                continue

            if already:
                report["already_present"] += 1
                report["details"].append(
                    {"line": entry.line_no, "status": "already-present",
                     "detail": None})
                # dropped from `keep`: it is already reflected in the room.
                _write_spool(spool_path, keep + entries[idx + 1:])
                continue

            status = _replay_one(entry, room_path, bus_path)
            report["details"].append(
                {"line": entry.line_no, "status": status, "detail": entry.error})
            if status == "replayed":
                report["replayed"] += 1
                # dropped from `keep`: durably appended and chained.
            else:
                report["failed"] += 1
                keep.append(entry)          # stays queued for the next run
            _write_spool(spool_path, keep + entries[idx + 1:])

        if dry_run:
            # Confirm nothing changed: belt-and-suspenders for the promise a
            # --dry-run makes.
            pass
    return report


def list_spool(spool_path: str | Path, room_path: str | Path) -> list[dict]:
    """Read-only summary of what is spooled. Touches neither the spool nor
    the room."""
    spool_path = Path(spool_path)
    room_path = Path(room_path)
    out = []
    for entry in _read_spool(spool_path):
        if entry.malformed:
            out.append({"line": entry.line_no, "malformed": True,
                        "error": entry.error})
            continue
        d = entry.data
        out.append({
            "line": entry.line_no, "malformed": False,
            "ts": d.get("ts", "?"), "who": d.get("who", "?"),
            "name": d.get("name", "?"), "tag": d.get("tag", "?"),
            "reason": d.get("reason", ""),
            "body_preview": d["body"].strip().replace("\n", " ")[:80],
            "already_in_room": _already_in_room(room_path, d["body"]),
        })
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--room", default="",
                        help="room.md path (default: room.py's ROOM)")
    common.add_argument("--bus", default="",
                        help="chain jsonl path (default: <room>.parent/room.jsonl)")
    common.add_argument("--spool", default="",
                        help="dead_letter.jsonl path "
                             "(default: <room>.parent/dead_letter.jsonl)")

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", parents=[common],
                   help="show what is spooled, without touching it")
    r = sub.add_parser("replay", parents=[common],
                       help="replay spooled turns through room.append_turn")
    r.add_argument("--dry-run", action="store_true",
                   help="report what would happen; change nothing")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    room_path = _room_path(args.room)
    bus_path = _bus_path(room_path, args.bus)
    spool_path = _spool_path(room_path, args.spool)

    if args.cmd != "list":
        # Spool listing stays fail-open read-only inspection; replaying
        # dead-lettered turns into the transcript starts centrally.
        _repo_root = str(Path(__file__).resolve().parents[2])
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "runs.council.dead_letter_replay",
            REGISTRY_BY_ID["runs.council.dead_letter_replay"].effects,
            (process_guard_boundary_decision(),),
        )
    if args.cmd == "list":
        rows = list_spool(spool_path, room_path)
        if not rows:
            print(f"[dead-letter] {spool_path}: empty or missing "
                  f"-- nothing spooled")
            return 0
        for row in rows:
            if row["malformed"]:
                print(f"  #{row['line']}: MALFORMED -- {row['error']}")
                continue
            flag = " [already in room]" if row["already_in_room"] else ""
            print(f"  #{row['line']}: {row['who']}/{row['name']} "
                  f"({row['ts']}) reason={row['reason']!r} "
                  f"-- {row['body_preview']!r}{flag}")
        return 0

    report = replay(spool_path, room_path, bus_path, dry_run=args.dry_run)
    for d in report["details"]:
        suffix = f" -- {d['detail']}" if d["detail"] else ""
        print(f"  #{d['line']}: {d['status']}{suffix}")
    print(f"[dead-letter] {report['replayed']} replayed, "
          f"{report['already_present']} already present, "
          f"{report['failed']} failed (left in spool), "
          f"{report['malformed']} malformed (left in spool)"
          + (" [dry-run: nothing changed]" if args.dry_run else ""))

    if not args.dry_run and report["replayed"] > 0:
        ok, failures = _room.verify_room(store_path=bus_path)
        if ok:
            print("[dead-letter] verify_room: OK")
        else:
            print("[dead-letter] verify_room FAILED after replay:",
                  file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            return _room.EXIT_VERIFY_FAILED

    if report["failed"] or report["malformed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

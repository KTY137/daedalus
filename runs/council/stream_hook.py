"""Mirror this Claude Code session into Der Raum, live — distilled, not dumped.

Claude Code fires hooks around a turn. This script is that hook: it reads the
hook payload on stdin and appends the human's prompt or Claude's reply to the
shared room file, so the other vendors' agents see the conversation as it
happens instead of being told about it afterwards.

Wire it in settings.json:

  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command",
       "command": "python <repo>/runs/council/stream_hook.py user"}]}],
    "Stop":            [{"hooks": [{"type": "command",
       "command": "python <repo>/runs/council/stream_hook.py assistant"}]}]
  }

WHAT LANDS IN THE ROOM is a LEDE, not the turn. A turn written for the human
runs to thousands of characters, and every later speaker in the room pays to
re-read all of it — the room stops being a conversation and becomes somebody
else's status report. So the mirror follows this repo's own doctrine, the one
``daedalus/offload.py`` applies to code context: DISTILLED BY DEFAULT, EVIDENCE
ON DEMAND, AND THE DISTILLATION IS NEVER SILENT.

  * the lede is the opening of the turn, cut at a paragraph or sentence
    boundary — never mid-word;
  * the full text is written to a per-turn sidecar under ``session/<date>/``,
    which any agent can pull in with ``room.py ask ... --attach``;
  * when anything was omitted, the room says so, names the omitted size, and
    names the path — ``_[abridged: N of M chars omitted · full: <path>]_``.
    NOTHING omitted means NO line: silence means "you have it all". A model
    that does not know it is reading an abridged view will reason confidently
    about the gap, so the gap is always labelled.

The compression is MECHANICAL — boundary search over the string. There is no
model here and there cannot be: this runs synchronously around every turn.

Design constraints that matter:
- NEVER fail the turn. A hook that raises blocks the session, so every error
  path exits 0 silently. A broken mirror must not break the conversation.
- Skip empty and duplicate turns: Stop can fire more than once around
  sub-agent activity, and a room full of repeats is worse than no mirror.
- Silent toward the session, TALKATIVE TOWARD THE DISK. Because the hook may
  never speak up, a silent failure was indistinguishable from "never ran".
  Every invocation appends one line to ``.stream_hook.log`` saying what it
  decided and why. That log is capped and rotated; it cannot grow unbounded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The real repo, resolved from the script's own location and NEVER from the
# test override below: it is only used to render provenance paths relative to
# the checkout, and a relative path that resolves against the wrong root is
# worse than an absolute one.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Redirects every path this hook touches. Exists for tests, which must not
# append to the live room; production leaves it unset.
HOOK_DIR_ENV = "DAEDALUS_STREAM_HOOK_DIR"

# Lede window, tuned by reading real turns in room.md: a preferred cut lands in
# [LEDE_MIN, LEDE_MAX], which is where the opening paragraph or the first two
# or three sentences of an actual turn end. A turn at or under LEDE_MAX is
# mirrored whole — abridging it would cost a provenance line to save nothing.
LEDE_MIN = 400
LEDE_MAX = 600

# The transcript log is bounded at two generations of this size, no more.
LOG_MAX_BYTES = 256 * 1024

SEEN_KEEP = 40


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------


def _hook_dir() -> Path:
    override = os.environ.get(HOOK_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent


def _room_path() -> Path:
    return _hook_dir() / "room.md"


def _seen_path() -> Path:
    return _hook_dir() / ".stream_seen"


def _log_path() -> Path:
    return _hook_dir() / ".stream_hook.log"


def _session_root() -> Path:
    return _hook_dir() / "session"


def _display_path(path: Path) -> str:
    """Repo-relative POSIX path when the file is in the checkout, absolute when
    it is not. The room quotes this at other agents, who then hand it to
    ``--attach``: it has to resolve for THEM, from the repo root."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


# --------------------------------------------------------------------------
# the append-only decision log
# --------------------------------------------------------------------------


def _record(role: str, decision: str, chars_in: int = 0, chars_kept: int = 0,
            sidecar: str = "-", note: str = "") -> None:
    """One line per invocation. Never raises: the log is a debugging aid, and
    an aid that can break the session is not one."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.stat().st_size >= LOG_MAX_BYTES:
                # One generation of history, then gone. Bounded at 2x the cap.
                path.replace(path.with_name(path.name + ".1"))
        except OSError:
            pass
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fields = [stamp, role or "-", decision,
                  f"in={chars_in}", f"kept={chars_kept}",
                  f"sidecar={sidecar or '-'}"]
        if note:
            flat = re.sub(r"[\t\r\n]+", " ", note)[:200]
            fields.append(f"note={flat}")
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\t".join(fields) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------
# filters that already work — do not weaken
# --------------------------------------------------------------------------


def _dedupe(text: str) -> bool:
    """True if this exact text was already mirrored (keeps the last 40)."""
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
    seen_path = _seen_path()
    try:
        seen = seen_path.read_text(encoding="utf-8").split()
    except OSError:
        seen = []
    if digest in seen:
        return True
    seen.append(digest)
    try:
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text("\n".join(seen[-SEEN_KEEP:]), encoding="utf-8")
    except OSError:
        pass
    return False


# Harness plumbing that is NOT conversation. Mirroring these creates a
# feedback loop: the monitor notices a new turn -> its notification arrives as
# a turn -> the hook mirrors it -> the monitor notices a new turn. Observed
# live, and it does not stop on its own.
_PLUMBING = (
    "<task-notification>",
    "<system-reminder>",
    "[SYSTEM NOTIFICATION",
    "Monitor event:",
    "<ide_opened_file>",
    "<ide_selection>",
)


def _is_plumbing(text: str) -> bool:
    head = text[:600]
    return any(marker in head for marker in _PLUMBING)


# --------------------------------------------------------------------------
# the lede — mechanical compression, no model, no network
# --------------------------------------------------------------------------

_PARA = re.compile(r"\n[ \t]*\n")
# A sentence ends at .!? followed by whitespace or end of string. A period
# glued to the next character is not a sentence end -- that is what keeps
# `daedalus/spine/attempt.py:295` and `1.5` from being cut in half.
_SENTENCE = re.compile(r"[.!?][\"'’”)\]`]*(?=\s|$)")
# Periods that end a token without ending a sentence.
_ABBREV = {"e.g.", "i.e.", "etc.", "cf.", "vs.", "al.", "fig.", "no.",
           "resp.", "approx.", "eq.", "sec.", "ref."}


def _is_abbrev(window: str, end: int) -> bool:
    token = window[:end].split()[-1] if window[:end].split() else ""
    token = token.lstrip("([{\"'`").lower()
    if token in _ABBREV:
        return True
    # A single letter plus a period is an initial, not a sentence.
    return len(token) == 2 and token[0].isalpha() and token[1] == "."


def _pick(cuts: list[int], lo: int, hi: int) -> int:
    """The LATEST candidate inside the window, or 0 for none. Latest, because a
    lede should carry as much of the opening as the window allows."""
    ok = [c for c in cuts if lo <= c <= hi]
    return max(ok) if ok else 0


def _word_cut(window: str) -> int:
    """Last whitespace in the window. The floor under every other rule: a lede
    may be blunt, but it may never end mid-word."""
    idx = max(window.rfind(" "), window.rfind("\n"), window.rfind("\t"))
    return idx if idx > 0 else len(window)


def _lede(text: str) -> tuple[str, int]:
    """``(lede, cut)`` where ``lede == text[:cut]`` exactly.

    Boundary preference, strongest first: a paragraph break inside the window,
    a sentence end inside the window, then the latest boundary of either kind
    below the window, then a word boundary. Only a single token longer than
    the whole window can force a hard cut, and prose does not contain one.
    """
    if len(text) <= LEDE_MAX:
        return text, len(text)
    window = text[:LEDE_MAX]
    paras = [m.start() for m in _PARA.finditer(window)]
    sents = [m.end() for m in _SENTENCE.finditer(window)
             if not _is_abbrev(window, m.end())]
    cut = (_pick(paras, LEDE_MIN, LEDE_MAX)
           or _pick(sents, LEDE_MIN, LEDE_MAX)
           or _pick(paras + sents, 1, LEDE_MAX)
           or _word_cut(window))
    # Pull the cut back over trailing whitespace so that len(lede) and the
    # omitted count are exact complements of len(text). The provenance line
    # quotes those numbers; they have to add up.
    cut = len(text[:cut].rstrip())
    if cut <= 0:
        cut = min(LEDE_MAX, len(text))
    return text[:cut], cut


def _balance_fences(lede: str) -> str:
    """Close a code fence the cut left open.

    Scaffolding, not content: an unterminated ``` swallows every following
    turn header into a code block in the GUI, which is a rendering bug the
    reader would blame on the room rather than on the mirror.
    """
    opens = sum(1 for line in lede.splitlines() if line.lstrip().startswith("```"))
    return lede + "\n```" if opens % 2 else lede


# --------------------------------------------------------------------------
# sidecars — evidence on demand
# --------------------------------------------------------------------------

_SIDECAR_RE = re.compile(r"t(\d+)$")


def _next_index(root: Path) -> int:
    """Derived from disk, never from memory: the hook is a fresh process every
    single turn, so an in-memory counter would restart at 1 and overwrite
    yesterday's evidence. Globally monotonic across day directories, so a
    turn id quoted in the room means one file forever."""
    highest = 0
    try:
        for path in root.glob("*/t*.md"):
            m = _SIDECAR_RE.match(path.stem)
            if m:
                highest = max(highest, int(m.group(1)))
    except OSError:
        pass
    return highest + 1


def _sidecar(name: str, tag: str, text: str) -> tuple[Path | None, str]:
    """Write the full turn. Returns ``(path, error)``; one of them is empty."""
    try:
        root = _session_root()
        now = datetime.now(timezone.utc)
        day = root / now.strftime("%Y-%m-%d")
        day.mkdir(parents=True, exist_ok=True)
        base = _next_index(root)
        stamp = now.strftime("%Y-%m-%d %H:%M:%SZ")
        for bump in range(64):
            n = base + bump
            path = day / f"t{n:04d}.md"
            try:
                # "x": exclusive create. Two hooks racing must not land on the
                # same id and silently lose one turn's evidence.
                with path.open("x", encoding="utf-8") as fh:
                    fh.write(f"_t{n:04d}  ·  {name}  ·  {tag}  ·  "
                             f"{stamp}  ·  {len(text):,} chars_\n\n"
                             f"{text}\n")
                return path, ""
            except FileExistsError:
                continue
        return None, "no free sidecar id after 64 tries"
    except Exception as exc:  # noqa: BLE001 -- the turn outranks its evidence
        return None, f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# the mirror
# --------------------------------------------------------------------------


def _append(name: str, tag: str, text: str, role: str = "-") -> None:
    text = (text or "").strip()
    if not text:
        _record(role, "skipped-empty")
        return
    if _is_plumbing(text):
        _record(role, "skipped-plumbing", len(text))
        return
    if _dedupe(text):
        _record(role, "skipped-dupe", len(text))
        return

    lede, cut = _lede(text)
    omitted = len(text) - cut
    body = _balance_fences(lede)
    shown = "-"
    note = ""
    if omitted > 0:
        path, err = _sidecar(name, tag, text)
        if path is not None:
            shown = _display_path(path)
            body += (f"\n\n_[abridged: {omitted:,} of {len(text):,} chars "
                     f"omitted · full: {shown}]_")
        else:
            # Still abridged, and still not silent about it: naming a sidecar
            # that does not exist would be worse than naming the failure.
            note = err
            body += (f"\n\n_[abridged: {omitted:,} of {len(text):,} chars "
                     f"omitted · full text UNAVAILABLE: {err}]_")

    # THROUGH THE ROOM'S ONE APPEND BOUNDARY, never straight into the markdown.
    #
    # This used to be its own `room.open("a")`, which is how the room ended up
    # holding turns the hash chain does not attest: `verify` reported turns 30-32
    # as "inside the attested range but MISSING from the chain", and the cause
    # was simply that there were two writers and only `say()` knew about the
    # mirror. `append_turn` appends AND chains AND takes a cross-process lock,
    # which matters here more than anywhere: this hook runs in a separate
    # process for every Claude Code session on the machine.
    written = False
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import room as _room  # noqa: WPS433 -- the engine lives next door

        # The hook decides WHICH room (its dir is redirectable, and the tests
        # rely on that), so it passes the target EXPLICITLY. An earlier version
        # assigned room.ROOM instead and that global outlived the call: the next
        # caller in the same process wrote wherever this one had aimed, and a
        # test turn ended up in the real transcript.
        target = _room_path()
        _room.append_turn("claude", body, name=name, tag=tag,
                          room_path=target,
                          bus_path=target.parent / "room.jsonl")
        written = True
    except Exception as exc:                    # noqa: BLE001
        # A hook that raises breaks the session it is mirroring. Falling back to
        # a direct append keeps the human's turn, and `verify` will name the
        # resulting gap rather than the room silently losing it.
        note = (note + " | " if note else "") + f"append_turn unavailable: {exc}"
    if not written:
        # DEAD LETTER, never the canonical markdown.
        #
        # The obvious fallback -- append directly and let `verify` report the
        # gap -- was the wrong shape, and the reason is worth keeping: `verify`
        # makes an invariant break VISIBLE, it does not PREVENT one. An escape
        # hatch that writes an unattested turn into the artifact is the original
        # bug with a smaller blast radius, not a fix. So a turn that cannot go
        # through `append_turn` is spooled beside the room and replayed later
        # through that same door, and the room never holds a turn the chain
        # does not know about.
        spool = _hook_dir() / "dead_letter.jsonl"
        try:
            spool.parent.mkdir(parents=True, exist_ok=True)
            record = json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "who": "claude", "name": name, "tag": tag, "body": body,
                "reason": note,
            }, ensure_ascii=False)
            # One line, one write: a partial line in a spool is a turn nobody
            # can replay.
            with spool.open("a", encoding="utf-8") as fh:
                fh.write(record + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception as exc:                # noqa: BLE001
            note = (note + " | " if note else "") + f"dead-letter failed: {exc}"
    # "mirrored" means the turn REACHED THE ROOM. A dead-lettered turn did not,
    # and logging it as mirrored would make the logbook agree with a thing that
    # did not happen -- in the module whose whole subject is turns that were
    # believed written and were not.
    _record(role, "mirrored" if written else "error",
            len(text), len(body), shown, note)


def _extract(payload: dict, role: str) -> str:
    """Pull the turn text out of whatever shape the hook payload has."""
    if role == "user":
        for key in ("prompt", "user_prompt", "message", "text"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return ""
    # assistant: prefer an explicit field, else the last assistant message
    for key in ("response", "assistant_response", "last_message", "text"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    msgs = payload.get("messages")
    if isinstance(msgs, list):
        for msg in reversed(msgs):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    if any(parts):
                        return "\n".join(p for p in parts if p)
    return ""


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    role = argv[1] if len(argv) > 1 else "user"
    try:
        raw = sys.stdin.read()
    except Exception as exc:  # noqa: BLE001
        _record(role, "error", note=f"stdin unreadable: {type(exc).__name__}")
        return 0
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception as exc:  # noqa: BLE001
        _record(role, "error", len(raw or ""), note=f"payload not JSON: {exc}")
        return 0
    text = ""
    try:
        text = _extract(payload, role)
        if role == "user":
            _append("Kaya", "human · live", text, role)
        else:
            _append("Claude", "Anthropic · Fable 5 · live", text, role)
    except Exception as exc:  # noqa: BLE001 -- the session outranks the mirror
        _record(role, "error", len(text or ""),
                note=f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

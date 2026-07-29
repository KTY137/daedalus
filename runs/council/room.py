"""Der Raum — a shared chatroom for agents from different vendors.

One append-only markdown file. Everybody reads the room before they speak,
everybody's turn lands in the same place, and a human can watch it live in an
editor.

  python runs/council/room.py show
  python runs/council/room.py say <who> <text-file>
  python runs/council/room.py ask codex   [--prompt-file F]
  python runs/council/room.py ask ollama  [--model qwen2.5-coder:14b]
  python runs/council/room.py ask agy     [--model ...]        # needs sign-in
  python runs/council/room.py verify
  python runs/council/room.py who

The room file is plain markdown on purpose: no parsing ceremony, a human opens
it and reads a conversation. Three things are wired to daedalus rather than
re-invented here, because this repo already has them tested:

  1. ATTACHMENTS ARE DISTILLED, not inlined whole (``structcore.semantic_slice``
     + ``structcore.parse.extract_units``). ``--raw`` restores literal bytes.
  2. EVERY TURN IS MIRRORED into ``daedalus.council.bus``, an append-only
     hash-chained JSONL beside the markdown. ``room.py verify`` walks the chain
     and names the failing position. The markdown stays the human artifact; the
     chain is the thing you can check it against.
  3. A PER-SPEAKER UNREAD CURSOR replaces re-sending the whole room every turn.

Nothing here is silent. A withheld file, a trimmed slice, an omitted turn and a
held floor are all NAMED in the prompt the speaker actually receives: a model
reasoning about code must know when it is not seeing everything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

def _resolve_room() -> Path:
    """Where this room's transcript lives.

    THIS ENGINE IS CANONICAL, AND PORTABILITY IS WHY IT HAD A RIVAL.

    Until 2026-07-29 there were two room implementations. This one, and an
    unversioned 703-line fork at ``~/.claude/skills/room/room.py`` that the
    `room` SKILL.md pointed every invocation at. On 2026-07-29 BOTH were live:
    `.room/room.md` (47 turns, 10:46) and `runs/council/room.md` (92 turns,
    10:43) were written three minutes apart, by agents who could not see each
    other's transcript.

    The fork existed for exactly one good reason: it was portable. It resolved
    its transcript from $DAEDALUS_ROOM_FILE or ``cwd/.room/room.md``, so the
    skill worked in any repo, while this engine hardcoded its own directory.
    It paid for that with everything else -- no hash chain, no `verify`, no
    cross-process lock, no per-model cursor, and, decisively, NO SECRET FLOOR:
    its ``_attach`` read any path and inlined the bytes verbatim, to a bench at
    100.119.126.9 over a tailnet and over ssh. That is precisely the egress
    hole commit df5a7c2 closed HERE, whose own message warns that "a fix that
    lives in one of two implementations is not a closed class."

    So the fork's one advantage moves here, and the rival loses its reason to
    exist. THE DEFAULT IS UNCHANGED -- an unset variable still resolves to
    runs/council/room.md, because a live transcript must not move under the
    agents currently writing to it.
    """
    env = os.environ.get("DAEDALUS_ROOM_FILE", "").strip()
    if env:
        return Path(env).expanduser().absolute()
    return Path(__file__).resolve().parent / "room.md"


ROOM = _resolve_room()
BENCH = os.environ.get("DAEDALUS_RTX_OLLAMA_HOST", "http://100.119.126.9:11434")
BENCH_SSH = "Administrator@100.119.126.9"

# The repo this room talks about; attachment paths resolve against it.
# ANCHORED TO THIS FILE, never to ROOM: the transcript is now movable
# ($DAEDALUS_ROOM_FILE) and deriving the repo from it would make a room opened
# in /tmp resolve every attachment path against /tmp.
REPO_ROOT = Path(__file__).resolve().parents[2]

# The hash-chained mirror of the markdown, and the council id it is filed under.
BUS_ID = "room"
BUS_PATH = ROOM.parent / f"{BUS_ID}.jsonl"

# Above this many chars a file's FOCUS body is distilled to a signature-level
# skeleton instead of being inlined whole. Below it the body is cheap enough
# that sending it beats describing it -- a 2k file plus its neighbourhood costs
# MORE than the file, and a "distillation" that grows the prompt is a lie.
FOCUS_CHAR_CAP = 6000

# A distilled view may cost at most 1/DISTILL_RATIO of the body it replaces
# (floored at MIN_DISTILL_CHARS so a file just over the cap still gets some
# reach). Without this the slicer happily expands the neighbourhood to fill
# whatever budget it is handed, and the "distilled" attach comes out BIGGER
# than the raw one -- measured, not hypothetical.
DISTILL_RATIO = 3
MIN_DISTILL_CHARS = 1500

# Exit codes: a caller (and the GUI) must be able to tell "not addressed" from
# "the vendor broke".
EXIT_NOT_ADDRESSED = 3
EXIT_VERIFY_FAILED = 4
EXIT_VENDOR_FAILED = 5

SPEAKERS = {
    # Two distinct Claudes can appear here, and conflating them would be a lie:
    #   "claude" -- the live Claude Code session driving this work. It has the
    #     whole day's context and is woken by a room monitor, not by this server.
    #   "fable"  -- a FRESH headless instance. No memory of the session, reads
    #     only the transcript. That is the point: an unattached opinion.
    "claude": ("Claude", "Anthropic · Fable 5 · live session"),
    "fable": ("Fable", "Anthropic · Fable 5 · fresh instance"),
    "codex": ("Codex", "OpenAI · codex CLI"),
    # NOT "local": this speaker runs on the RTX bench, a different machine.
    # Bytes sent here cross the tailnet, so it is an egress lane. Only
    # 127.0.0.1 would be local, and the label must never blur that.
    "ollama": ("Ollama", "RTX bench (off-machine) · qwen2.5-coder"),
    "agy": ("Antigravity", "Google · agy CLI"),
    "opus": ("Opus", "Anthropic · Opus 4.6"),
    "kaya": ("Kaya", "human"),
}

# Independence is a property of WEIGHTS, not of endpoints (bus.py's rule). This
# is DECLARED config, never inferred from a display tag at write time: the three
# Anthropic heads must be visible as ONE class in the chained record, or a room
# of clones reads as a room of independent voices.
CLASSES = {
    "claude": {"vendor": "anthropic", "family": "claude"},
    "fable": {"vendor": "anthropic", "family": "claude"},
    "opus": {"vendor": "anthropic", "family": "claude"},
    "codex": {"vendor": "openai", "family": "gpt"},
    "ollama": {"vendor": "alibaba", "family": "qwen2.5-coder"},
    "agy": {"vendor": "google", "family": "gemini"},
    "kaya": {"vendor": "human", "family": "human"},
}

HOUSE_RULES = """\
You are in a shared room with agents from other vendors. Below is the room;
anyone may read it and anyone may reply.

House rules:
- Disagree when you disagree. Different vendors have different blind spots and
  that is the entire point of this room. Agreement that costs you nothing is
  worth nothing here.
- Address people by name when you answer them.
- Cite file:line when you make a claim about code. A claim without evidence is
  an opinion, and this room runs on evidence.
- If you could not verify something, say so instead of guessing. Attachments
  may be DISTILLED views rather than whole files; what is missing is named.
- Be brief. This is a conversation, not a report.
"""


class VendorError(RuntimeError):
    """A vendor call failed. This is NOT a turn.

    An error string appended to the room reads, to every later speaker, as
    something the vendor SAID. Observed: an agy OAuth timeout landed as a
    turn whose body was the full authorization redirect, scopes and state
    parameter included -- authentication internals, in a file every agent
    reads before it speaks. A failure belongs beside the room, not in it.
    """


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _ensure() -> None:
    ROOM.parent.mkdir(parents=True, exist_ok=True)
    if not ROOM.exists():
        ROOM.write_text(
            "# Der Raum\n\n"
            "A shared room for agents from different vendors. Append-only.\n\n",
            encoding="utf-8",
        )


def transcript() -> str:
    _ensure()
    return ROOM.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# turns — the unit the cursor counts and the bus mirrors
# --------------------------------------------------------------------------

DOT = "\u00b7"
_TURN_RE = re.compile(
    r"^###\s+(?P<name>.+?)\s+" + DOT + r"\s+(?P<tag>.+?)\s+" + DOT
    + r"\s+(?P<time>\d{2}:\d{2}:\d{2})\s*$"
)


class Turn:
    __slots__ = ("index", "name", "tag", "time", "body")

    def __init__(self, index: int, name: str, tag: str, time_: str, body: str):
        self.index, self.name, self.tag, self.time, self.body = (
            index, name, tag, time_, body,
        )

    def render(self) -> str:
        return (f"### {self.name}  {DOT}  {self.tag}  {DOT}  {self.time}\n\n"
                f"{self.body}\n")


def parse_turns(text: str) -> list[Turn]:
    """Split the room into turns.

    Anchored on the header line ONLY, never on the ``---`` rule: a model that
    writes a horizontal rule or a YAML fence inside its own turn must not be
    able to split its turn in two and desynchronise every cursor and every
    chained position.
    """
    lines = text.splitlines()
    starts: list[tuple[int, re.Match]] = []
    for i, line in enumerate(lines):
        m = _TURN_RE.match(line)
        if m:
            starts.append((i, m))
    turns: list[Turn] = []
    for n, (i, m) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip()
        # drop the trailing separator rule that belongs to the NEXT turn
        if body.endswith("---"):
            body = body[:-3].rstrip()
        turns.append(Turn(n, m.group("name"), m.group("tag"),
                          m.group("time"), body))
    return turns


# --------------------------------------------------------------------------
# state: per-speaker unread cursor + persisted floor
#
# Without a cursor every speaker is re-sent the whole transcript before every
# turn, so a room of N turns costs O(N^2) tokens. The cursor makes a turn cost
# roughly what actually happened since that speaker last looked.
# --------------------------------------------------------------------------

_EMPTY_STATE = {"version": 1, "cursors": {}, "floor": None}


def state_file() -> Path:
    return ROOM.parent / "cursors.json"


def load_state() -> dict:
    """Read cursors + floor. ANY damage degrades to 'nobody has seen anything',
    which re-sends the whole room. That direction is the safe one: the failure
    mode of a corrupt cursor must be an expensive turn, never a blind one."""
    path = state_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(_EMPTY_STATE, cursors={})
    except (OSError, ValueError) as exc:
        print(f"[room] cursor file unreadable ({exc}); sending full transcript",
              file=sys.stderr)
        return dict(_EMPTY_STATE, cursors={})
    if not isinstance(raw, dict):
        print("[room] cursor file is not an object; sending full transcript",
              file=sys.stderr)
        return dict(_EMPTY_STATE, cursors={})
    cursors = raw.get("cursors")
    if not isinstance(cursors, dict):
        cursors = {}
    clean = {k: v for k, v in cursors.items() if isinstance(v, int) and v >= 0}
    floor = raw.get("floor")
    if not isinstance(floor, str) or not floor:
        floor = None
    return {"version": 1, "cursors": clean, "floor": floor}


def save_state(state: dict) -> None:
    """Atomic: a crash mid-write must not leave a truncated cursor file (which
    would then be unreadable, which would then resend everything forever)."""
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def cursor_key(who: str, model: str | None = None) -> str:
    """A cursor belongs to (speaker, model), not to the speaker alone.

    The speaker slot is a ROLE; different weights can occupy it. Observed: the
    ``ollama`` slot ran qwen2.5-coder, advancing its cursor to 34; devstral then
    took the same slot, inherited that cursor, and was sent ZERO turns while the
    caller had explicitly asked for the transcript. It answered generically,
    from nothing, and nothing in the output said so. A model that has never
    seen the room must not be told it is caught up.
    """
    return who if not model else f"{who}::{model}"


def seen_count(who: str, total: int, state: dict | None = None,
               model: str | None = None) -> int:
    st = state if state is not None else load_state()
    n = st["cursors"].get(cursor_key(who, model), 0)
    # A cursor past the end means the room was truncated, rotated or replaced.
    # Rewind to zero and re-send everything rather than skip real turns.
    if n > total:
        return 0
    return max(0, n)


def set_cursor(who: str, n: int, model: str | None = None) -> None:
    st = load_state()
    st["cursors"][cursor_key(who, model)] = int(n)
    save_state(st)


def set_floor(who: str | None) -> None:
    st = load_state()
    st["floor"] = who
    save_state(st)


def is_addressed(who: str, state: dict | None = None) -> bool:
    """Deterministic floor rule: an OPEN room addresses everyone, a held floor
    addresses exactly its holder. No model judgement anywhere in this."""
    st = state if state is not None else load_state()
    floor = st.get("floor")
    return floor is None or floor == who


# --------------------------------------------------------------------------
# egress: the secret floor, then distillation
# --------------------------------------------------------------------------


def _floor(path: str, text: str) -> str | None:
    """Secret floor, per file, both channels. Returns a rule name or None.

    The floor has two INDEPENDENT channels: path markers checked against the
    path, value-shaped regexes checked against the text. Driving them together
    with an empty path kills the path tier, so a file NAMED .env or id_rsa
    would sail through on content alone. A hit means REFUSE -- there is no
    redact-and-send here.
    """
    try:
        from daedalus.sensitivity import secret_floor_rule
    except Exception:
        # Fail CLOSED: no floor available means nothing gets attached.
        return "secret floor unavailable"
    return secret_floor_rule(path, text or "")


def _skeleton(rel: str, text: str) -> tuple[str, int]:
    """Signature-level digest of a file: one line per unit, every body dropped.

    Built with ``structcore.parse.extract_units`` -- the same parser the slicer
    uses -- so "what counts as a unit" has one answer in this repo, not two.
    Returns ``(skeleton_text, n_units)``; ``n_units == 0`` means nothing was
    extractable and the caller must not pretend it distilled anything.
    """
    try:
        from daedalus.structcore import spec_for
        from daedalus.structcore.parse import extract_units
    except Exception:
        return "", 0
    spec = spec_for(rel)
    units = extract_units(rel, text, spec) if spec else []
    if not units:
        return "", 0
    out = [f"# {rel}  (SKELETON — signatures only, every body omitted)"]
    for u in units:
        first = next((ln.strip() for ln in u.source.splitlines() if ln.strip()),
                     u.name)
        out.append(f"    {first[:120]}   # :{u.line} ({u.loc} loc)")
    return "\n".join(out), len(units)


def _speaker_lane(who: str, host: str | None = None) -> str:
    """The egress lane for the speaker an attachment is being built FOR.

    ``lane="trusted"`` disables the default-deny allow-list in
    ``slice_egress_rule``, leaving only the secret floor. It was hardcoded here,
    so a distilled neighbourhood was built at full trust and then handed to
    whoever spoke next -- including **codex and agy, which are external
    vendors**. The secret floor did run (the attachment path is careful about
    that, on raw bytes, first), but tier 2 never did.

    Trust is a property of where the bytes go, never of the room. ``ollama`` is
    trusted only when its resolved endpoint is this machine, for the same reason
    ``daedalus.sensitivity.lane_for_host`` exists: ``OLLAMA_HOST`` is an
    environment variable.
    """
    name = (who or "").strip().lower()
    if name == "claude":
        return "trusted"
    if name == "ollama":
        # The host this room ACTUALLY dispatches to, which defaults to BENCH --
        # a different machine. Reading OLLAMA_HOST here (as the first version of
        # this function did) would have called bench traffic "trusted", which is
        # precisely the bug this predicate exists to prevent, reintroduced one
        # module over. The caller passes the host it is about to use.
        try:
            from daedalus.sensitivity import lane_for_host
            return lane_for_host(host or BENCH)
        except Exception:
            return "untrusted"
    return "untrusted"          # codex, agy, and anything added later


def _distill_one(rel: str, body: str, share_chars: int,
                 lane: str = "untrusted") -> dict:
    """One file's distilled view plus its provenance.

    THE INVARIANT: a distilled view is NEVER larger than the raw body it
    replaces. A "distillation" that grows the prompt is a lie, and the slicer
    will grow it if you hand it a generous budget -- it fills whatever
    ``max_tokens`` it is given with neighbourhood. So the budget here is
    derived from the FILE, not from the attachment allowance.

    Two branches, deliberately mirroring ``offload._slice_context``'s
    ``include_focus`` split:

      * body <= FOCUS_CHAR_CAP -> send it WHOLE. Below the cap the file is
        cheaper than any description of it, and the model gets complete
        evidence instead of a summary.
      * body >  FOCUS_CHAR_CAP -> a signature skeleton from
        ``structcore.parse.extract_units`` plus a neighbourhood from
        ``semantic_slice(include_focus=False)``, together capped at
        ``1/DISTILL_RATIO`` of the body.

    Fail-OPEN on machinery, fail-CLOSED on content: a broken index degrades to
    the raw body (which the caller has ALREADY run the secret floor over),
    while an egress-gate refusal inside ``semantic_slice`` yields no text at
    all. Every degrade is named in the returned ``note``; nothing is silent.
    """
    info = {"mode": "raw", "note": "", "text": body, "withheld": None,
            "trimmed": 0, "included": 0, "units": 0}
    if len(body) <= FOCUS_CHAR_CAP:
        info["note"] = (f"sent whole: {len(body)} chars is under the "
                        f"{FOCUS_CHAR_CAP}-char distill cap, so the file itself "
                        f"is cheaper than a distilled view of it")
        return info
    try:
        from daedalus.structcore import cached_index, semantic_slice
    except Exception as exc:
        info["note"] = f"raw fallback: daedalus slicer unavailable ({exc})"
        return info

    skeleton, n_units = _skeleton(rel, body)
    if not n_units:
        # Nothing parseable (markdown, JSON, a data file). Distilling it would
        # mean inventing a structure it does not have.
        info["note"] = "raw: no extractable units, nothing to distill"
        return info

    cap = min(max(share_chars, MIN_DISTILL_CHARS),
              max(MIN_DISTILL_CHARS, len(body) // DISTILL_RATIO))
    nbr_tokens = max(128, (cap - len(skeleton)) // 4)
    try:
        idx = cached_index(str(REPO_ROOT))
        res = semantic_slice(str(REPO_ROOT), rel, idx=idx, lane=lane,
                             max_tokens=nbr_tokens, include_focus=False)
    except ValueError:
        # Not in the index (a create target, an unindexed tree). There is no
        # neighbourhood to build, but the skeleton still stands.
        info.update(mode="skeleton", text=skeleton, units=n_units,
                    note=(f"DISTILLED: skeleton only, {n_units} signatures, all "
                          f"bodies omitted ({len(body)} raw chars NOT sent); "
                          f"file is not in the code index so no neighbourhood "
                          f"was built"))
        return info
    except Exception as exc:  # noqa: BLE001 -- context is optional, the turn is not
        info["note"] = f"raw fallback: slice build failed ({exc})"
        return info

    focus_rule = next((w.get("rule") for w in res.get("withheld") or ()
                       if w.get("role") == "focus"), None)
    if focus_rule:
        # The slicer's own gate refused the focus. Nothing is inlined -- not the
        # slice, and not the raw body it would have stood in for.
        info.update(mode="withheld", text="", withheld=focus_rule,
                    note=f"withheld by the egress gate: {focus_rule}")
        return info

    slice_text = (res.get("slice_text") or "").strip()
    trimmed = int(res.get("trimmed_count") or 0)
    withheld_n = int(res.get("withheld_count") or 0)
    included = int(res.get("n_included") or 0)
    parts = [skeleton]
    if slice_text:
        parts.append("\n# ===== NEIGHBOURHOOD (imports, callees, callers) =====")
        parts.append(slice_text)
    text = "\n".join(parts)
    if len(text) >= len(body):
        # The guard, not the intent: if the neighbourhood outgrew the file
        # anyway, send the file. Complete evidence beats an expensive summary.
        info["note"] = (f"raw: the distilled view ({len(text)} chars) was not "
                        f"smaller than the file ({len(body)} chars)")
        return info
    info.update(
        mode="skeleton+neighbourhood", text=text, units=n_units,
        trimmed=trimmed, included=included,
        note=(f"DISTILLED: {n_units} signatures kept, all bodies omitted "
              f"({len(body)} raw chars NOT sent); {included} neighbour unit(s) "
              f"included, {trimmed} trimmed to fit budget, {withheld_n} "
              f"withheld by the egress gate"),
    )
    return info


def _attach(paths: list[str], budget_chars: int = 40000,
            raw: bool = False, lane: str = "untrusted") -> str:
    """Assemble the attachment block for speakers that cannot read the disk.

    Ollama and agy get text only; without this they are asked about code they
    have never seen, and an honest model correctly answers nothing.

    ORDER IS THE SAFETY PROPERTY. Every file passes the secret floor FIRST, on
    its RAW BYTES, before any distillation runs -- a distilled slice is still
    egress, and a slicer that happened to keep a credential-bearing line would
    otherwise ship it. A refusal is visible in the prompt as a NAMED refusal,
    never a silent omission: a speaker must know it was denied evidence rather
    than believing the file was empty.

    ``raw=True`` restores literal whole-file bytes (still floored). Use it when
    you genuinely need the bytes; the default is the distilled view, and the
    block header states which one the speaker is looking at.
    """
    if not paths:
        return ""
    root = REPO_ROOT
    chunks, spent = [], 0
    share = budget_chars // max(1, len(paths))
    distilled_any = False
    for rel in paths:
        p = (root / rel).resolve()
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            chunks.append(f"----- {rel} (unreadable: {exc}) -----")
            continue
        # SECRET FLOOR FIRST, on the raw bytes, before anything is distilled.
        rule = _floor(rel, body)
        if rule:
            chunks.append(
                f"----- {rel} (WITHHELD by the secret floor: {rule}) -----")
            continue
        if raw:
            text, note = body, ""
        else:
            info = _distill_one(rel, body, share, lane=lane)
            if info["mode"] == "withheld":
                chunks.append(
                    f"----- {rel} (WITHHELD by the egress gate: "
                    f"{info['withheld']}) -----")
                continue
            text, note = info["text"], info["note"]
            if info["mode"] in ("skeleton", "skeleton+neighbourhood",
                                "full+neighbourhood"):
                distilled_any = True
        room_left = budget_chars - spent
        if room_left <= 0:
            chunks.append(f"----- {rel} (omitted: attachment budget spent) -----")
            continue
        if len(text) > room_left:
            text = text[:room_left] + f"\n... [truncated at {room_left} chars]"
            note = (note + "; " if note else "") + "truncated by attachment budget"
        spent += len(text)
        header = f"----- {rel} -----" if not note else f"----- {rel}  [{note}] -----"
        chunks.append(f"{header}\n{text}")

    if raw or not distilled_any:
        head = "===== ATTACHED FILES =====\n"
    else:
        head = (
            "===== ATTACHED FILES (DISTILLED VIEWS, NOT WHOLE FILES) =====\n"
            "These are structure-distilled views built by daedalus's semantic\n"
            "slicer, not the literal files. Where a body was replaced by a\n"
            "signature skeleton, or neighbours were trimmed, or a file was\n"
            "withheld, the bracket after the filename says so. YOU ARE NOT\n"
            "SEEING EVERYTHING. If a claim needs a line that is not in front\n"
            "of you, say you could not verify it instead of guessing.\n"
        )
    return "\n\n" + head + "\n\n".join(chunks) + "\n===== END FILES =====\n"


def attach_sizes(paths: list[str], budget_chars: int = 40000) -> dict:
    """``{'raw': n, 'distilled': n, 'saved_pct': f}`` for the same file set.

    Exists so the win is a measured number a caller can print, not a claim.
    """
    raw_n = len(_attach(paths, budget_chars, raw=True))
    dist_n = len(_attach(paths, budget_chars, raw=False))
    saved = round(100 * (1 - dist_n / raw_n), 1) if raw_n else 0.0
    return {"raw": raw_n, "distilled": dist_n, "saved_pct": saved}


# --------------------------------------------------------------------------
# prompt assembly
# --------------------------------------------------------------------------


def _recap(turns: list[Turn]) -> str:
    """Who is in the room. This is what a TRIMMED speaker still needs: it
    replaces the turns it is not being re-sent, so it never loses track of who
    it is talking to."""
    roster: dict[str, tuple[str, int]] = {}
    for t in turns:
        tag, count = roster.get(t.name, (t.tag, 0))
        roster[t.name] = (tag, count + 1)
    who_line = "; ".join(
        f"{n} ({tag}, {c} turn{'s' if c != 1 else ''})"
        for n, (tag, c) in roster.items()
    ) or "(nobody has spoken yet)"
    return ("===== THE ROOM =====\n"
            f"In the room: {who_line}\n"
            f"Turns so far: {len(turns)}\n"
            "===== END ROOM =====\n")


def build_prompt(who: str, extra: str = "", attach: list[str] | None = None,
                 full: bool = False, raw: bool = False,
                 addressed: bool | None = None,
                 solo: bool = False,
                 model: str | None = None,
                 speaker_host: str | None = None) -> tuple[str, int, int]:
    """Assemble what a speaker will actually be sent.

    Returns ``(prompt, total_turns, omitted)``. Pure with respect to the room:
    it reads state but never advances a cursor, so it is safe to call just to
    see what a turn would cost.
    """
    text = transcript()
    turns = parse_turns(text)
    state = load_state()
    name = SPEAKERS.get(who, (who, ""))[0]

    seen = 0 if full else seen_count(who, len(turns), state, model=model)
    shown = turns[seen:]
    if seen > 0:
        head = (f"[{seen} earlier turn{'s' if seen != 1 else ''} omitted — you "
                f"have already seen them. This is not the whole room.]\n\n")
    else:
        head = ""
    body = "\n---\n\n".join(t.render() for t in shown)
    if not shown:
        body = "(no new turns since you last spoke)\n"

    floor = state.get("floor")
    if addressed is None:
        addressed = floor is None or floor == who
    floor_block = ""
    if floor is not None:
        holder = SPEAKERS.get(floor, (floor, ""))[0]
        if addressed:
            floor_block = (
                "===== FLOOR =====\n"
                f"This room is in addressed-only mode and the floor is yours "
                f"({holder}). Only you are expected to answer this round.\n"
                "===== END FLOOR =====\n\n")
        else:
            floor_block = (
                "===== FLOOR =====\n"
                f"This room is in addressed-only mode. The floor is held by "
                f"**{holder}**. You are NOT addressed this round.\n"
                "===== END FLOOR =====\n\n")

    if solo:
        # No transcript. A completion-tuned model continues the strongest
        # pattern it can see, and in a chat log that is its OWN last turn --
        # observed three times, the same 21 characters returned verbatim, once
        # with the full source of the file it had been asked about in front of
        # it. Give this model class a task and material, never a room to echo.
        return (
            "You are a careful reviewer. Answer the task below using ONLY the\n"
            "material provided. If the material does not contain the answer, say\n"
            "exactly what is missing. Do not restate the task. Do not repeat any\n"
            "sentence you were given.\n\n"
            f"TASK:\n{extra}\n"
            f"{_attach(attach or [], raw=raw, lane=_speaker_lane(who, speaker_host))}\n"
            "Your answer:"
        ), len(turns), len(turns)

    prompt = (
        f"{HOUSE_RULES}\n"
        f"{floor_block}"
        f"You are **{name}**. Read the room, then write ONLY your next turn —\n"
        f"no headers, no markdown title, no signature, just what you say.\n"
        f"{extra}\n\n"
        f"{_recap(turns)}\n"
        f"===== ROOM TRANSCRIPT =====\n{head}{body}\n===== END =====\n"
        f"{_attach(attach or [], raw=raw, lane=_speaker_lane(who, speaker_host))}\n"
        f"Your turn, {name}:"
    )
    return prompt, len(turns), seen


def _prompt_for(who: str, extra: str = "", attach: list[str] | None = None,
                full: bool = False, raw: bool = False) -> str:
    """Back-compatible wrapper: the prompt only. The new behaviour rides on the
    defaulted tail so every existing caller is untouched."""
    return build_prompt(who, extra, attach, full, raw)[0]


# --------------------------------------------------------------------------
# the tamper-evident mirror
# --------------------------------------------------------------------------

_ACTOR_SAFE = re.compile(r"[^a-z0-9_-]+")
_MODEL_SAFE = re.compile(r"[^A-Za-z0-9._:+-]+")


def _actor_for(who: str, model: str | None) -> tuple[str, str, str, dict]:
    """``(actor, vendor, model, independence_class)`` for bus.py's ADR-010
    namespace. An unknown model is recorded as the literal ``unknown`` -- never
    omitted, and never guessed from a display tag."""
    vendor = _ACTOR_SAFE.sub("-", (who or "").lower()).strip("-") or "unknown"
    mdl = _MODEL_SAFE.sub("-", (model or "").strip()).strip("-") or "unknown"
    cls = CLASSES.get(who) or {"vendor": vendor, "family": "unknown"}
    return f"council.{vendor}.{mdl}", vendor, mdl, dict(cls)


def mirror_turn(who: str, text: str, model: str | None = None,
                index: int | None = None,
                store_path: str | Path | None = None) -> dict:
    """Chain one room turn into ``daedalus.council.bus``.

    The markdown stays the artifact a human opens; this is the artifact a
    verifier walks. Each room turn is its own single-participant round, so the
    chained ``round`` doubles as the turn's position in the markdown.

    Returns a status dict and NEVER raises. A mirror failure must not lose the
    turn (the markdown already holds it) and must not 500 the GUI -- but it is
    also never swallowed: it is printed loudly and, because the chain is then
    one record short, :func:`verify_room` reports the gap BY POSITION.
    """
    path = Path(store_path) if store_path else BUS_PATH
    try:
        from daedalus.council import bus
    except Exception as exc:
        return {"ok": False, "id": None, "error": f"bus unavailable: {exc}"}
    actor, vendor, mdl, cls = _actor_for(who, model)
    content = text or ""
    turn = {
        "actor": actor, "vendor": vendor, "model": mdl,
        "independence_class": cls, "role": "participant",
        "lane": "untrusted",
        "meta": {"transport": "room.md", "endpoint": "der-raum"},
    }
    if not content.strip():
        # An empty turn is a degrade, not a contribution. bus.py refuses to
        # chain an empty 'spoke' precisely so this cannot render as speech.
        turn.update(status="anomaly", reason="malformed_response",
                    content=content)
    elif len(content) > getattr(bus, "MAX_CONTENT_CHARS", 200_000):
        turn.update(status="anomaly", reason="malformed_response",
                    content=(f"[{len(content)} chars exceeds the bus content "
                             f"ceiling; body not chained verbatim]"))
    else:
        turn.update(status="spoke", content=content)
    try:
        if index is None:
            index = max(0, len(parse_turns(transcript())) - 1)
        tid = bus.append_turn(BUS_ID, int(index), turn, store_path=path)
    except Exception as exc:  # noqa: BLE001 -- the markdown must survive this
        return {"ok": False, "id": None, "error": str(exc)}
    return {"ok": True, "id": tid, "error": None}


def verify_room(store_path: str | Path | None = None) -> tuple[bool, list[str]]:
    """Walk the chain, then check the markdown against it.

    Two independent questions, both answered BY POSITION:

      * IS THE CHAIN INTACT?  ``bus.verify_chain`` recomputes both SHAs per
        line and consults the persisted anchor, so a flipped byte, a deleted
        interior line and a truncated tail are each NAMED with their 1-indexed
        line number.
      * DOES THE MARKDOWN MATCH IT?  Every markdown turn's body is compared to
        the content chained at the same position. A silent rewrite of room.md
        -- the exact thing a plain markdown log cannot detect -- surfaces here
        as a named turn index.

    A ``refused`` record is a LEGITIMATE divergence (the secret floor declined
    to chain that body) and is reported as such rather than as tampering.

    ALIGNMENT IS BY CHAINED POSITION, NOT BY LIST OFFSET. Each record carries
    the markdown turn index it was written for, so a room whose history predates
    the mirror verifies its ATTESTED range instead of failing wholesale on turns
    the chain never claimed to cover. What the chain does NOT cover is not a
    failure -- but it is not silence either: :func:`chain_coverage` reports it
    and the ``verify`` command always prints it.
    """
    path = Path(store_path) if store_path else BUS_PATH
    try:
        from daedalus.council import bus
    except Exception as exc:
        return False, [f"bus unavailable: {exc}"]
    ok, failures = bus.verify_chain(path)
    failures = list(failures)

    records = [r for r in bus.load_transcript(path) if r.get("record") == "turn"]
    turns = parse_turns(transcript())
    seen: dict[int, str] = {}
    for rec in records:
        rnd = rec.get("round")
        if not isinstance(rnd, int) or not (0 <= rnd < len(turns)):
            failures.append(
                f"chained record {rec.get('id')} claims turn position {rnd}, "
                f"which room.md does not have (markdown truncated or rewritten)")
            continue
        if rnd in seen:
            failures.append(
                f"turn {rnd}: chained TWICE ({seen[rnd]} and {rec.get('id')}) "
                f"-- one voice recorded as two")
            continue
        seen[rnd] = rec.get("id")
        t = turns[rnd]
        if rec.get("status") == "refused":
            failures.append(
                f"turn {rnd} ({t.name}): chained as REFUSED by the secret floor "
                f"({rec.get('reason')}) -- room.md holds a body the chain "
                f"deliberately does not attest")
            continue
        if (rec.get("content") or "").strip() != t.body.strip():
            failures.append(
                f"turn {rnd} ({t.name}): room.md body does not match chained "
                f"record {rec.get('id')} (markdown edited after the fact)")
    if seen:
        for i in range(min(seen), max(seen) + 1):
            if i not in seen:
                failures.append(
                    f"turn {i} ({turns[i].name}): inside the attested range but "
                    f"MISSING from the chain (mirror gap)")
        # THE TAIL, which used to be excused wholesale.
        #
        # Turns BEFORE the first chained one genuinely predate the mirror and
        # are correctly not covered. Turns AFTER the last chained one do NOT:
        # the mirror was demonstrably running by then, so an unchained turn
        # there is the same defect as a hole in the middle -- it just happens to
        # sit at the end. Reporting only the interior meant a writer that
        # bypassed `append_turn` was invisible for as long as it was the most
        # recent writer, which is exactly how long it matters.
        for i in range(max(seen) + 1, len(turns)):
            failures.append(
                f"turn {i} ({turns[i].name}): appended AFTER the last chained "
                f"turn but MISSING from the chain (unmirrored tail)")
    return (not failures), failures


def chain_coverage(store_path: str | Path | None = None) -> tuple[int, int]:
    """``(attested_turns, total_turns)``. A young chain over an old room is
    normal; pretending it covers everything would not be."""
    path = Path(store_path) if store_path else BUS_PATH
    try:
        from daedalus.council import bus
    except Exception:
        return 0, len(parse_turns(transcript()))
    records = [r for r in bus.load_transcript(path) if r.get("record") == "turn"]
    turns = parse_turns(transcript())
    rounds = {r.get("round") for r in records
              if isinstance(r.get("round"), int) and 0 <= r["round"] < len(turns)}
    return len(rounds), len(turns)


class _RoomLock:
    """A CROSS-PROCESS lock around append+mirror.

    ``bus._WRITE_LOCK`` is a ``threading.Lock``, which serialises threads inside
    one interpreter and nothing else. The writers here are separate PROCESSES --
    the CLI, the GUI server, and a Claude Code hook that fires for every session
    on the machine -- so a thread lock never applied to the case that actually
    happens. Two processes could interleave an append and a mirror and leave the
    markdown holding a turn the chain does not attest.

    Degrades to a no-op if the lock cannot be taken rather than blocking a turn
    forever: losing serialisation is bad, losing the human's message is worse,
    and ``verify_room`` still reports any gap that results BY POSITION.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None

    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+b")
            if os.name == "nt":
                import msvcrt
                for _ in range(300):            # ~30s, then proceed unlocked
                    try:
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            self._fh = None
        return self

    def __exit__(self, *exc) -> bool:
        if self._fh is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._fh.close()
            except Exception:
                pass
        return False


def append_turn(who: str, text: str, model: str | None = None,
                name: str | None = None, tag: str | None = None,
                room_path: Path | None = None,
                bus_path: Path | None = None) -> dict:
    """THE ONE PLACE A TURN ENTERS THE ROOM. Appends AND mirrors, under a lock.

    Every writer goes through here. That is the whole point: a turn that reaches
    the markdown by any other route is a turn the hash chain does not attest,
    and ``verify_room`` will correctly report it as a gap in a range it claims
    to cover. That is exactly what happened -- `runs/council/stream_hook.py`
    appended directly with its own ``open(..., "a")`` and never mirrored, so the
    room accumulated turns inside the attested range with no chained record.
    The detection was right; there were simply two writers and only one of them
    knew about the chain.

    Returns the mirror status dict. NEVER raises: the markdown already holds the
    turn by the time the mirror runs, and losing it to a bookkeeping error would
    be strictly worse than an un-attested turn that ``verify`` can name.
    """
    # EXPLICIT PATHS, never a module global the caller mutates.
    #
    # The first version had callers assign `room.ROOM` before calling. That
    # leaked across every later call in the same process: a test that redirected
    # the room left the global pointing at its temp dir, and the next caller --
    # or the next TEST -- wrote wherever the previous one had aimed. It appended
    # a pytest turn into the real transcript before anyone noticed, which is the
    # same "two writers, one target" shape this function exists to remove.
    target = Path(room_path) if room_path else ROOM
    bus = Path(bus_path) if bus_path else (
        target.parent / "room.jsonl" if room_path else BUS_PATH)

    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(
            "# Der Raum\n\nA shared room for agents from different vendors. "
            "Append-only.\n\n", encoding="utf-8")
    if name is None or tag is None:
        default_name, default_tag = SPEAKERS.get(who, (who, "unknown"))
        name = name or default_name
        tag = tag or default_tag
    with _RoomLock(target.parent / ".room.lock"):
        with target.open("a", encoding="utf-8") as fh:
            fh.write(f"\n---\n\n### {name}  {DOT}  {tag}  {DOT}  {_now()}\n\n"
                     f"{text.strip()}\n")
        turns = parse_turns(target.read_text(encoding="utf-8"))
        res = mirror_turn(who, text.strip(), model, index=max(0, len(turns) - 1),
                          store_path=bus)
    if not res["ok"]:
        print(f"[room] WARNING: turn NOT chained ({res['error']}); "
              f"room.md is ahead of the mirror", file=sys.stderr)
    return {**res, "turns": len(turns)}


def say(who: str, text: str, model: str | None = None) -> None:
    """Append a turn to the markdown, mirror it into the chain, advance the
    speaker's cursor.

    Cursor advancement lives HERE, not in the ask path, because both the CLI
    and the GUI reach the room through this one function: a speaker that has
    just spoken has, by construction, seen everything before its own turn.
    """
    name, _tag = SPEAKERS.get(who, (who, "unknown"))
    res = append_turn(who, text, model)
    set_cursor(who, res["turns"], model=model)
    print(f"[room] {name} spoke ({len(text)} chars)"
          + (f", chained {res['id']}" if res["ok"] else ", NOT CHAINED"))


# --------------------------------------------------------------------------
# vendors
# --------------------------------------------------------------------------


def _exe(name: str) -> str:
    """Resolve a CLI to something CreateProcess can actually launch.

    npm shims on Windows are .cmd/.ps1; subprocess without a shell cannot
    launch the extensionless variant that shutil.which finds first.
    """
    import shutil

    for candidate in (f"{name}.cmd", f"{name}.exe", name):
        found = shutil.which(candidate)
        if found and Path(found).suffix.lower() in {".cmd", ".exe", ".bat"}:
            return found
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(f"{name} is not on PATH")
    return found


def ask_codex(extra: str = "", timeout: int = 900,
              attach: list[str] | None = None, full: bool = False,
              raw: bool = False) -> str:
    prompt = _prompt_for("codex", extra, attach, full, raw)
    pf = ROOM.parent / ".codex_prompt.txt"
    pf.write_text(prompt, encoding="utf-8")
    # The prompt goes in on stdin: a multi-line argument does not survive the
    # npm .cmd shim on Windows (it arrives truncated at the first newline).
    proc = subprocess.run(
        [_exe("codex"), "exec", "--sandbox", "read-only"],
        input=prompt,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout or ""
    # codex exec prints a preamble and token accounting; the reply is the tail
    marker = "tokens used"
    if marker in out:
        out = out.split(marker)[-1]
        out = "\n".join(out.splitlines()[1:])
    if not out.strip():
        raise VendorError(f"codex returned nothing; stderr: {proc.stderr[-400:]}")
    return out.strip()


def ask_fable(model: str = "", extra: str = "", timeout: int = 900,
              attach: list[str] | None = None, full: bool = False,
              raw: bool = False) -> str:
    """A FRESH Claude instance, unattached to the live session.

    It reads the room and nothing else -- no memory of the conversation that
    produced the work under review. That detachment is the value: it cannot
    defend a position it never took.
    """
    prompt = _prompt_for("fable", extra, attach, full, raw)
    argv = [_exe("claude"), "-p", "--permission-mode", "plan"]
    if model:
        argv += ["--model", model]
    proc = subprocess.run(
        argv, input=prompt, cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "").strip()
    if not out:
        raise VendorError(f"fable returned nothing; stderr: {proc.stderr[-400:]}")
    return out


def ask_opus(model: str = "claude-opus-4-6", extra: str = "",
             timeout: int = 900, attach: list[str] | None = None,
             full: bool = False, raw: bool = False) -> str:
    """A second Anthropic head on a different model.

    Not vendor-independent — same weights family, same lab — but a different
    model with different training, and available while agy is quota-limited.
    Label it honestly in the room so nobody mistakes it for a fourth vendor.
    """
    prompt = _prompt_for("opus", extra, attach, full, raw)
    proc = subprocess.run(
        [_exe("claude"), "-p", "--model", model, "--permission-mode", "plan"],
        input=prompt,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "").strip()
    if not out:
        raise VendorError(f"opus returned nothing; stderr: {proc.stderr[-400:]}")
    return out


def ask_ollama(model: str = "qwen2.5-coder:14b", host: str = BENCH,
               solo: bool = True,
               extra: str = "", timeout: int = 900,
               attach: list[str] | None = None, full: bool = False,
               raw: bool = False) -> str:
    # solo defaults TRUE for this lane: qwen2.5-coder is completion-tuned and
    # anchors on a transcript, echoing its own last turn instead of reasoning.
    # speaker_host: the attachment gate must be decided by the endpoint this
    # call is about to use, not by the name "ollama". BENCH is another machine.
    prompt = build_prompt("ollama", extra, attach, full, raw, solo=solo,
                          speaker_host=host)[0]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_ctx": 16384, "temperature": 0.4},
    }).encode()
    req = urllib.request.Request(
        f"{host}/api/chat", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return (data.get("message", {}).get("content") or "").strip()


def ask_agy(model: str = "", extra: str = "", timeout: int = 900,
            attach: list[str] | None = None, full: bool = False,
            raw: bool = False) -> str:
    prompt = _prompt_for("agy", extra, attach, full, raw)

    # THE PROMPT GOES ON STDIN AND NEVER INTO THE COMMAND STRING.
    #
    # This was:
    #     cmd = f'agy -p "$(type {remote})"'
    #     subprocess.run(["ssh", BENCH_SSH, cmd], ...)
    #
    # `ssh` with a trailing command does not take an argv: it concatenates its
    # arguments and hands the string to the REMOTE login shell, which re-parses
    # it. `$(...)` is command substitution performed THERE, on the contents of a
    # file that holds room prompts -- and room prompts carry diffs. An ordinary
    # patch containing backticks or `$(...)` (a shell script, a test log, a
    # Python f-string) therefore executed on the bench as Administrator, with no
    # adversarial model required. Local argv quoting cannot help: the escaping
    # that matters belongs to a shell we cannot see.
    #
    # `agy -p -` reads the prompt from stdin, so the only thing the remote shell
    # ever parses is the fixed token sequence below, which contains no
    # caller-controlled text. `daedalus/council/vendors.py` documents and tests
    # this same invariant; this module is the second implementation and did not
    # inherit it.
    argv = ["ssh", "-T",                    # no pty: an auth prompt cannot block
            "-o", "BatchMode=yes",          # never wait on a passphrase
            "-o", "StrictHostKeyChecking=yes",
            BENCH_SSH, "--", "agy", "-p", "-"]
    if model:
        # Constrained to a model-id shape so it can never become another token.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", model):
            raise VendorError(f"refusing an unsafe agy model id: {model!r}")
        argv += ["--model", model]
    proc = subprocess.run(argv, input=prompt, capture_output=True,
                          text=True, timeout=timeout, encoding="utf-8",
                          errors="replace")
    out = (proc.stdout or "").strip()
    if not out or "sign in" in (proc.stderr or "").lower():
        raise VendorError(
            f"agy unavailable: {(proc.stderr or 'no output')[-300:]}")
    return out


def who() -> None:
    state = load_state()
    turns = parse_turns(transcript())
    floor = state.get("floor")
    print(f"room: {ROOM}")
    print(f"chain: {BUS_PATH}")
    print(f"cursors: {state_file()}")
    print(f"bench: {BENCH}")
    print(f"turns: {len(turns)}")
    print("floor: " + ("OPEN (anyone may speak)" if not floor
                       else f"{SPEAKERS.get(floor, (floor, ''))[0]} only"))
    for key, (name, tag) in SPEAKERS.items():
        seen = seen_count(key, len(turns), state)
        print(f"  {key:8s} {name:12s} {tag:38s} seen {seen}/{len(turns)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sub.add_parser("who")
    sub.add_parser("verify",
                   help="walk the hash chain and check room.md against it")
    s = sub.add_parser("say")
    s.add_argument("who")
    s.add_argument("textfile")
    c = sub.add_parser("cursor", help="inspect or reset a speaker's cursor")
    c.add_argument("speaker", nargs="?", default="")
    c.add_argument("--reset", action="store_true", help="rewind to 0 (resend all)")
    f = sub.add_parser("floor", help="set or clear addressed-only mode")
    f.add_argument("speaker", nargs="?", default="")
    f.add_argument("--open", action="store_true", help="clear the floor")
    a = sub.add_parser("ask")
    a.add_argument("vendor",
                   choices=["codex", "ollama", "agy", "opus", "fable"])
    a.add_argument("--model", default="")
    a.add_argument("--extra", default="")
    a.add_argument("--timeout", type=int, default=900)
    a.add_argument("--attach", default="",
                   help="comma-separated repo-relative files to distill in")
    a.add_argument("--with-room", action="store_true",
                   help="send the transcript to a local model too (off by "
                        "default: completion-tuned models echo it)")
    a.add_argument("--raw", action="store_true",
                   help="attach literal whole-file bytes instead of distilled views")
    a.add_argument("--full", action="store_true",
                   help="resend the whole transcript, ignoring the cursor")
    a.add_argument("--only", default="",
                   help="put the room in addressed-only mode for this speaker")
    args = ap.parse_args()

    if args.cmd == "show":
        print(transcript())
    elif args.cmd == "who":
        who()
    elif args.cmd == "verify":
        ok, failures = verify_room()
        attested, total = chain_coverage()
        print(f"[room] chain {BUS_PATH.name}: {attested}/{total} turn(s) "
              f"attested" + ("" if attested == total else
                             " (the rest predate the mirror and are NOT covered)"))
        if ok:
            print("[room] chain OK -- every attested turn matches room.md"
                  if attested else
                  "[room] nothing to verify yet -- the chain is empty; turns "
                  "appended from now on will be attested")
            return 0
        print("[room] VERIFY FAILED:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return EXIT_VERIFY_FAILED
    elif args.cmd == "say":
        say(args.who, Path(args.textfile).read_text(encoding="utf-8"))
    elif args.cmd == "cursor":
        if args.reset and args.speaker:
            set_cursor(args.speaker, 0)
            print(f"[room] cursor {args.speaker} -> 0")
        else:
            print(json.dumps(load_state(), indent=2, sort_keys=True))
    elif args.cmd == "floor":
        if args.open or not args.speaker:
            set_floor(None)
            print("[room] floor OPEN -- anyone may speak")
        else:
            set_floor(args.speaker)
            print(f"[room] floor held by {args.speaker} -- only they are invoked")
    elif args.cmd == "ask":
        if args.only:
            set_floor(args.only)
        if not is_addressed(args.vendor):
            # Floor control is enforced HERE, by NOT invoking the model -- not
            # by asking a model to decide whether it should have spoken.
            holder = load_state().get("floor")
            print(f"[room] floor is held by {holder}; {args.vendor} is not "
                  f"addressed -- not invoking.", file=sys.stderr)
            return EXIT_NOT_ADDRESSED
        t0 = time.time()
        att = [x.strip() for x in args.attach.split(",") if x.strip()]
        _, total, seen = build_prompt(args.vendor, args.extra, att,
                                      args.full, args.raw)
        print(f"[room] {args.vendor}: sending {total - seen}/{total} turns"
              f"{' [--full]' if args.full else ''}"
              f"{' [--raw]' if args.raw else ' [distilled]'}")
        try:
            if args.vendor == "codex":
                model = args.model or "unknown"
                reply = ask_codex(args.extra, args.timeout, att, args.full,
                                  args.raw)
            elif args.vendor == "fable":
                model = args.model or "unknown"
                reply = ask_fable(args.model, args.extra, args.timeout, att,
                                  args.full, args.raw)
            elif args.vendor == "opus":
                model = args.model or "claude-opus-4-6"
                reply = ask_opus(model, args.extra, args.timeout, att,
                                 args.full, args.raw)
            elif args.vendor == "ollama":
                model = args.model or "qwen2.5-coder:14b"
                reply = ask_ollama(model, extra=args.extra,
                                   timeout=args.timeout, attach=att,
                                   full=args.full, raw=args.raw,
                                   solo=not args.with_room)
            else:
                model = args.model or "unknown"
                reply = ask_agy(args.model, args.extra, args.timeout, att,
                                args.full, args.raw)
        except VendorError as exc:
            # A failure is reported BESIDE the room, never inside it: an error
            # string appended as a turn reads to every later speaker as
            # something the vendor said, and vendor stderr can carry auth
            # internals that never passed the secret floor.
            print(f"[room] {args.vendor} FAILED: {exc}", file=sys.stderr)
            return EXIT_VENDOR_FAILED
        say(args.vendor, reply, model=model)
        print(f"[room] {args.vendor} replied in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    # `ask` spawns a paid vendor CLI. The spend ceiling is installed per
    # PROCESS in daedalus/cli.py, and the room is its own entry point, so every
    # turn taken here ran outside the cap -- including turns that cost real
    # money. budget.BILLABLE_SITES lists ask_codex/ask_fable as
    # ``explicit: False``, which is the register naming the hole, not blessing
    # it. This module already imports daedalus elsewhere, so the import is not
    # a new dependency; it is the one that was missing.
    from daedalus.budget import install_process_guard

    install_process_guard()
    sys.exit(main())

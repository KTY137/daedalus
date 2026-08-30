# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Handlers for the context-carrying events: SessionStart, UserPromptSubmit,
SubagentStart/Stop, ConfigChange. Each handler is a pure function of
(payload, root, sid) plus the session state it reads and updates, and returns
a :class:`HookResult`. Tool events live in ``tools.py``."""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from ._common import (
    HookResult,
    _Lock,
    clip_block,
    hooks_dir,
    trim_lines,
    update_state,
    with_deadline,
)
from ._tree import (
    UNREADABLE_KEY,
    fingerprint_diff,
    last_sweep,
    source_fingerprint,
    tree_facts,
)

MIN_PARALLEL = 4
#: A subagent entry older than this is pruned from the live set: the harness
#: does not promise a SubagentStop for an agent it killed.
AGENT_STALE_S = 2 * 3600
#: The architecture delta's own budget. A block with no budget of its own
#: competes for the whole turn budget, and the trimmer settles that competition
#: by deletion -- see :func:`_common.clip_block` for the measurement.
ARCH_DELTA_CHARS = 600
#: Wall-clock budgets for the two PYTHON-side dependencies. Every git call is
#: already capped by subprocess timeout; these two were capped by nothing, and
#: a hook has no deadline of its own. [MEASURED 2026-08-25] one turn row reads
#: 139,592 ms and a direct render_delta call exceeded 120 s on this tree.
SHIFT_BUDGET_S = 2.0
ARCH_BUDGET_S = 3.0

CREW_TARGETS = (
    "DeepSeek (advisory, reads daedalus/) -- reviews, adversarial audits, research with paths=[]",
    "haiku delegates: argus (read-only recon), kadmos (mechanical edits), metron (gate runs), mnemosyne (docs)",
    "background Bash -- test suites, receipt runs, index builds",
)

LEGEND = (
    "HOOKS v2: silence = unchanged (ARCH, CREW). CHANGED = source tree differs "
    "from the last recorded test run. Ledger: runs/hooks/ledger.jsonl"
)


def _shift_line(root: Path) -> str:
    def render() -> str:
        try:
            from daedalus import shift as shift_mod

            s = shift_mod.load(root)
            line = s.render()
            if s.goal and s.expired:
                line += "  <- the declared window has passed; report and confirm before continuing"
            return line
        except Exception:  # noqa: BLE001 - the clock must not cost the turn
            return "[clock unavailable]"

    # Two failures, two words. "unavailable" is a clock that raised;
    # "timed out" is a clock that never came back -- and only the second one
    # was costing the user a prompt.
    return with_deadline(render, SHIFT_BUDGET_S, "[clock timed out]")


# --------------------------------------------------------------------------
# SessionStart
# --------------------------------------------------------------------------


def session_start(payload: dict, root: Path, sid: str) -> HookResult:
    facts = tree_facts(root)
    lines = [facts.tree_line()]
    archived = facts.archived_line()
    if archived:
        lines.append(archived)
    lines.append("SHIFT: " + _shift_line(root))
    plan = root / "docs" / "IKARUS_ARIADNE_MASTER_PLAN.md"
    if plan.exists():
        lines.append("PLAN: docs/IKARUS_ARIADNE_MASTER_PLAN.md -- design authority; read it before architecture/kernel work")
    sweep_sha, behind = last_sweep(root)
    if sweep_sha:
        tail = f" ({behind} commits since)" if behind and behind != "0" else ""
        lines.append(f"DOCS: last mnemosyne sweep at {sweep_sha}{tail}")
    lines.append(LEGEND)

    base_fp = source_fingerprint(root)

    def mutate(state: dict) -> None:
        state.setdefault("base_fp", base_fp)
        state["targets_shown"] = False
        state.setdefault("agents", {})
        state["started"] = payload.get("source") or payload.get("start_reason") or "startup"

    update_state(root, sid, mutate)
    text, dropped = trim_lines(lines)
    return HookResult(text=text, note=f"trimmed:{dropped}" if dropped else "")


# --------------------------------------------------------------------------
# UserPromptSubmit
# --------------------------------------------------------------------------


def _live_agents(state: dict) -> dict[str, dict]:
    agents = state.get("agents") or {}
    now = time.time()
    return {
        k: v
        for k, v in agents.items()
        if isinstance(v, dict) and now - float(v.get("started", 0)) < AGENT_STALE_S
    }


def _crew_lines(state: dict) -> tuple[list[str], dict]:
    live = _live_agents(state)
    n = len(live)
    last = state.get("last_crew")
    lines: list[str] = []
    if n < MIN_PARALLEL or n != last:
        types = sorted({str(v.get("type", "?")) for v in live.values()})
        who = f": {', '.join(types)}" if types else ""
        lines.append(f"CREW: {n} subagents live (hook-tracked, min {MIN_PARALLEL}){who}")
        if n < MIN_PARALLEL and not state.get("targets_shown"):
            lines.append("  where work goes (shown once): " + " | ".join(CREW_TARGETS))
    return lines, live


def _changed_line(root: Path, state: dict) -> str:
    current = source_fingerprint(root)
    if UNREADABLE_KEY in current:
        # Returning "" here reads as "nothing changed". A fingerprint built on
        # a git call that failed cannot support that sentence.
        return (
            f"CHANGED: cannot say -- git was unreadable ({current[UNREADABLE_KEY]}); "
            "this is NOT a report that the tree is unchanged"
        )
    test = state.get("last_test")
    if isinstance(test, dict) and isinstance(test.get("fp"), dict):
        stored = {k: v for k, v in test["fp"].items() if k != UNREADABLE_KEY}
        diff = fingerprint_diff(stored, current)
        if not diff:
            return ""
        shown = ", ".join(diff[:4]) + (f", +{len(diff) - 4}" if len(diff) > 4 else "")
        return (
            f"CHANGED since last test run ({test.get('at', '?')}, `{test.get('cmd', '?')}`): "
            f"{len(diff)} source files -- {shown}"
        )
    base = state.get("base_fp")
    if isinstance(base, dict):
        diff = fingerprint_diff({k: v for k, v in base.items() if k != UNREADABLE_KEY}, current)
        if diff:
            shown = ", ".join(diff[:4]) + (f", +{len(diff) - 4}" if len(diff) > 4 else "")
            return (
                f"CHANGED since session start, no test run recorded: "
                f"{len(diff)} source files -- {shown}"
            )
    return ""


def _watchdog_anomalies(root: Path) -> list[str] | None:
    """Anomaly ids from the work watchdog's last valid health pass.

    ``None`` means the evidence is unavailable or invalid; an empty list means
    the watchdog explicitly reported no anomalies. Read-only; the hook never
    runs the watchdog.
    """
    try:
        import json

        data = json.loads((root / "runs" / "watchdog" / "health.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        anomalies = data.get("anomalies")
        if not isinstance(anomalies, list):
            return None
        ids: list[str] = []
        for anomaly in anomalies:
            if not isinstance(anomaly, dict):
                return None
            anomaly_id = anomaly.get("id")
            if not isinstance(anomaly_id, str) or not anomaly_id:
                return None
            ids.append(anomaly_id)
        return sorted(ids)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def user_prompt(payload: dict, root: Path, sid: str) -> HookResult:
    lines: list[str] = [_shift_line(root)]

    def render_arch() -> str:
        try:
            from daedalus import arch_memory

            return arch_memory.render_delta(
                root, shown_path=hooks_dir(root) / f"arch-{sid}.shown", silent_when_unchanged=True
            ) or ""
        except Exception:  # noqa: BLE001
            return ""

    delta = clip_block(
        with_deadline(render_arch, ARCH_BUDGET_S, "[architecture delta timed out]"),
        ARCH_DELTA_CHARS,
    )

    collected: dict = {}

    def mutate(state: dict) -> None:
        crew_lines, live = _crew_lines(state)
        collected["crew"] = crew_lines
        if crew_lines and any(l.startswith("  where work goes") for l in crew_lines):
            state["targets_shown"] = True
        state["last_crew"] = len(live)
        state["agents"] = live
        collected["changed"] = _changed_line(root, state)
        changed_cfg = state.pop("config_changed", None)
        if changed_cfg:
            collected["config"] = "CONFIG changed during this session: " + "; ".join(changed_cfg[-3:])
        # the work watchdog's anomalies, shown when they CHANGE (delta, not wallpaper)
        wd_ids = _watchdog_anomalies(root)
        previous_wd_ids = state.get("last_watchdog")
        if wd_ids is not None and wd_ids != previous_wd_ids:
            state["last_watchdog"] = wd_ids
            if wd_ids:
                collected["watchdog"] = "WATCHDOG: " + "; ".join(wd_ids) + " (runs/watchdog/HEALTH.md)"
            elif isinstance(previous_wd_ids, list) and bool(previous_wd_ids):
                collected["watchdog"] = "WATCHDOG: all clear"
        

    update_state(root, sid, mutate)
    # PRIORITY ORDER, and deliberately not narrative order. `trim_lines` drops
    # from the END, so the last line is the first casualty -- and the last line
    # used to be the watchdog's anomalies, i.e. the most alarming thing this
    # hook has to say was first out. Alarms now precede the crew count, and the
    # architecture delta goes last: it is the largest block and the least
    # urgent, and it is clipped to its own budget above so that even when it
    # survives it cannot crowd the alarms out.
    if collected.get("watchdog"):
        lines.append(collected["watchdog"])
    if collected.get("changed"):
        lines.append(collected["changed"])
    if collected.get("config"):
        lines.append(collected["config"])
    lines += collected.get("crew", [])
    if delta:
        lines.append(delta)
    text, dropped = trim_lines(lines)
    return HookResult(text=text, note=f"trimmed:{dropped}" if dropped else "")


# --------------------------------------------------------------------------
# SubagentStart / SubagentStop
# --------------------------------------------------------------------------


def subagent_start(payload: dict, root: Path, sid: str) -> HookResult:
    agent_id = str(payload.get("agent_id") or "")
    agent_type = str(payload.get("agent_type") or "?")

    def mutate(state: dict) -> None:
        agents = state.setdefault("agents", {})
        if agent_id:
            agents[agent_id] = {"type": agent_type, "started": time.time()}

    update_state(root, sid, mutate)
    facts = tree_facts(root)
    lines = [facts.tree_line()]
    archived = facts.archived_line()
    if archived:
        lines.append(archived)
    if facts.serena_mismatch:
        lines.append("Use Edit/Write/Bash with absolute paths in this tree; Serena read tools only.")
    text, _ = trim_lines(lines, 600)
    return HookResult(
        payload={
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": text,
            }
        },
        note=agent_type,
    )


def subagent_stop(payload: dict, root: Path, sid: str) -> HookResult:
    agent_id = str(payload.get("agent_id") or "")

    def mutate(state: dict) -> None:
        agents = state.setdefault("agents", {})
        agents.pop(agent_id, None)

    update_state(root, sid, mutate)
    return HookResult(note=str(payload.get("agent_type") or ""))


# --------------------------------------------------------------------------
# ConfigChange
# --------------------------------------------------------------------------


def config_change(payload: dict, root: Path, sid: str) -> HookResult:
    # Two field spellings are in circulation for this event (config_source/
    # config_path in one reference, source/file_path in another); accept both.
    source = str(payload.get("config_source") or payload.get("source") or "?")
    path = str(payload.get("config_path") or payload.get("file_path") or "?")

    def mutate(state: dict) -> None:
        state.setdefault("config_changed", []).append(f"{source} ({path})")

    update_state(root, sid, mutate)
    return HookResult(note=f"{source}:{path}")


# --------------------------------------------------------------------------
# PreCompact
# --------------------------------------------------------------------------


#: The heading compaction markers belong under. It is written when the note is
#: created AND checked when it already exists -- see _append_compaction_marker.
COMPACTION_SECTION = "## Kompaktierungen"


def _local_now() -> datetime.datetime:
    """A seam for deterministic marker tests; production uses local time so
    the marker lands in the same daily note the operator sees in the vault."""
    return datetime.datetime.now()


def _one_line(value: object, limit: int) -> str:
    """A bounded Markdown-inline field from a hook payload."""
    text = " ".join(str(value).splitlines()).replace("`", "'").strip()
    return text[:limit]


def _append_compaction_marker(
    note: Path, header: str, line: str, section: str = COMPACTION_SECTION
) -> None:
    """Create a daily note once, or append one marker UNDER ``section``.

    Serialize the create-or-append decision. Exclusive creation alone is not
    sufficient: another process can observe the empty file between ``open(x)``
    and the creator's first write, append its marker, and have that marker
    overwritten by the creator. The package's existing Windows-safe lock keeps
    the frontmatter unique and every marker append-only.

    APPENDING IS NOT ENOUGH ON ITS OWN. The header -- and with it the section
    heading -- used to be written only when this function CREATED the note. It
    is not the only writer of that file: the work watchdog opens the same daily
    note at ~02:29 under its own ``## watchdog`` heading, hours before any
    compaction can happen. [MEASURED 2026-08-25] against the real shape of
    ``vault/Sessions/2026-08-25.md``: every marker landed under ``## watchdog``
    and ``## Kompaktierungen`` was never created at all. A record filed under
    the wrong heading is a record that says something untrue about what it is.
    So a note that exists without the section gains the section.

    Line endings follow the FILE, not this process. The vault's notes are CRLF
    on this machine, and appending with ``newline="\n"`` left a mixed-ending
    file in git on every compaction.
    """
    note.parent.mkdir(parents=True, exist_ok=True)
    lock = note.with_name(f".{note.name}.precompact.lock")
    with _Lock(lock):
        try:
            with note.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(header + line)
            return
        except FileExistsError:
            pass
        raw = note.read_bytes()
        eol = "\r\n" if b"\r\n" in raw else "\n"
        existing = raw.decode("utf-8", errors="replace")
        prefix = ""
        if existing and not existing.endswith(("\n", "\r")):
            prefix = "\n"
        if section not in existing:
            prefix += "\n" + section + "\n\n"
        # Build with "\n" throughout, translate ONCE: translating a prefix that
        # already contains "\r\n" would produce "\r\r\n".
        with note.open("a", encoding="utf-8", newline="") as handle:
            handle.write((prefix + line).replace("\n", eol))


def pre_compact(payload: dict, root: Path, sid: str) -> HookResult:
    """Record compaction through the already-governed hooks dispatcher.

    Claude Code 2.1.x names the event field ``trigger`` (``manual`` or
    ``auto``). ``compaction_trigger`` remains a compatibility fallback for the
    older proposal this replaces. The hook never emits stdout and any diary
    write failure remains fail-open, but the dispatcher still records the
    outcome in ``runs/hooks/ledger.jsonl``.
    """
    vault = root / "vault"
    if not vault.is_dir():
        return HookResult(note="precompact:vault-unavailable")

    now = _local_now()
    raw_trigger = payload.get("trigger") or payload.get("compaction_trigger")
    trigger = raw_trigger if raw_trigger in {"manual", "auto"} else "unknown"
    transcript = _one_line(payload.get("transcript_path") or "", 500)
    session = sid[:8]
    note = vault / "Sessions" / f"{now:%Y-%m-%d}.md"
    line = (
        f"- {now:%H:%M} [compaction:{trigger}] Kontext kompaktiert "
        f"(Session {session}) — Transkript: `{transcript}`\n"
    )
    header = (
        f"---\ntags: [session]\ndate: {now:%Y-%m-%d}\n---\n\n"
        f"# Session {now:%Y-%m-%d}\n\n{COMPACTION_SECTION}\n\n"
    )
    try:
        _append_compaction_marker(note, header, line, COMPACTION_SECTION)
    except OSError as exc:
        return HookResult(note=f"precompact:write-failed:{type(exc).__name__}")
    return HookResult(note=f"precompact:{trigger}")

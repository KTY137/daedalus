"""Local HTTP API and static webapp host for Daedalus Agent OS."""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .kairos import drafts
from . import (
    accelerators,
    agents_registry,
    categories,
    control_plane,
    core,
    hierarchy,
    ikarus_cancellation,
    ikarus_chat,
    runtime_registry,
)
from .bootstrap_prompt import claude_bootstrap_prompt
from .context_plan import plan_context
from .env import env_status, load_env
from .projects import list_projects, resolve_repo_root
from .file_bridge import stream_state
from . import file_bridge
from . import ikarus_os
from .structcore.index import cached_index
from .structcore.churn import co_change_pairs
from .structcore.report import structure_summary
from .structcore.slice import semantic_slice
from .structcore.topology import spectral_partition
from . import memory as memory_mod

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


# --------------------------------------------------------------------------- #
# the self-improvement loop, exposed READ-ONLY                                  #
# --------------------------------------------------------------------------- #
# The loop already has inspectable state -- a ranked queue where every candidate
# carries the measurement it was scored from, and a ledger of what has been
# attempted. None of it was reachable from the cockpit, which meant the one
# surface a human actually watches could not tell them what the loop believes.
#
# Three properties govern everything below, and each has a test:
#
#   1. READ-ONLY. The ledger is opened with ``read_only=True``. The normal
#      constructor creates the parent directory, sets ``journal_mode=WAL`` and
#      runs migrations inside BEGIN IMMEDIATE -- so merely OPENING a ledger to
#      look at it WRITES to it. An HTTP GET must not do that, and SQLite (not a
#      comment) enforces it: ``mode=ro`` fails any write at the engine.
#   2. A DEGRADED SOURCE IS NOT AN EMPTY QUEUE. ``degraded_sources`` rides at the
#      top of every answer here and survives every bound below. "The picker
#      found nothing" and "the picker could not look" are different answers, and
#      a client that cannot tell them apart eventually reads a broken adapter as
#      an idle loop and stops investigating.
#   3. BOUNDED. A candidate carries a whole instruction plus open-ended
#      evidence; one ledger intent carries a gate's 4000-char output tail. That
#      is not a reason to withhold the loop from its own cockpit -- it is a
#      reason to state here exactly how much of it crosses the socket.
LOOP_TEXT_CHARS = 1200        # instruction / reason / any top-level free text
LOOP_VALUE_CHARS = 400        # a scalar nested inside evidence or sources
LOOP_MAP_KEYS = 32            # keys kept from any one nested map
LOOP_LIST_ITEMS = 20          # items kept from any one nested list
LOOP_DEPTH = 4                # how deep the shaper walks before it stops
LOOP_MAX_LIMIT = 50           # rows a caller may ask for
LOOP_RESPONSE_MAX_BYTES = 256 * 1024


def _clip(text: Any, limit: int | None = None) -> str:
    """Truncate VISIBLY.

    A silently shortened instruction reads as a complete one, and a reviewer
    would act on half a sentence without ever knowing there was more.

    ``limit`` defaults to :data:`LOOP_TEXT_CHARS` READ AT CALL TIME, not baked
    into the signature: a bound stated as a module constant that a default
    argument froze at import is a bound nobody can actually re-read -- including
    the test that has to prove the clipping is load-bearing.
    """
    limit = LOOP_TEXT_CHARS if limit is None else limit
    text = str(text)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [+{len(text) - limit} chars truncated]"


def _loop_shape(value: Any, depth: int = 0) -> Any:
    """Bound an arbitrary picker value into something safe to serialise.

    ``evidence`` and ``sources`` are open-ended BY DESIGN -- a source function
    may put any measurement it likes in there -- so this cannot be an allowlist
    of keys without silently dropping the next measurement someone adds. What it
    can do is bound: clip scalars, cap the width of maps and lists, stop at a
    fixed depth, and say where it did so rather than pretending the value ended.
    """
    if isinstance(value, str):
        return _clip(value, LOOP_VALUE_CHARS)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= LOOP_DEPTH:
        return f"[depth limit: {type(value).__name__} not expanded]"
    if isinstance(value, dict):
        items = sorted(((str(k), v) for k, v in value.items()), key=lambda kv: kv[0])
        out = {k: _loop_shape(v, depth + 1) for k, v in items[:LOOP_MAP_KEYS]}
        if len(items) > LOOP_MAP_KEYS:
            out["_truncated"] = f"{len(items) - LOOP_MAP_KEYS} more key(s) omitted"
        return out
    if isinstance(value, (list, tuple)):
        out = [_loop_shape(v, depth + 1) for v in value[:LOOP_LIST_ITEMS]]
        if len(value) > LOOP_LIST_ITEMS:
            out.append(f"[+{len(value) - LOOP_LIST_ITEMS} more item(s) omitted]")
        return out
    return _clip(value, LOOP_VALUE_CHARS)


def _loop_limit(qs: dict, default: int) -> int:
    """Parse and BOUND ``?limit=``; raises ValueError with the caller's message."""
    raw = (qs.get("limit") or [str(default)])[0]
    try:
        limit = int(raw)
    except ValueError:
        raise ValueError("limit must be an integer") from None
    if not 1 <= limit <= LOOP_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {LOOP_MAX_LIMIT}")
    return limit


def _loop_fit(payload: dict[str, Any], section: str, rows_key: str) -> dict[str, Any]:
    """Shrink the answer until it fits, by dropping ROWS from the tail.

    Per-field clipping keeps the typical response small; this is the bound that
    actually holds when it does not. It trims the growable list ONLY -- never
    ``degraded_sources``, ``notes`` or ``sources`` -- because a size cap that
    can delete "a source failed" while keeping "here is more work" turns
    property 2 into a coincidence.
    """
    block = payload[section]
    rows = list(block[rows_key])
    total = len(rows)
    while True:
        block[rows_key] = rows
        block["returned"] = len(rows)
        block["dropped_for_size"] = total - len(rows)
        block["response_bytes"] = len(_json_safe(payload))
        if block["response_bytes"] <= LOOP_RESPONSE_MAX_BYTES or not rows:
            return payload
        rows = rows[:-1]


def _loop_candidate(candidate: Any) -> dict[str, Any]:
    """One queued candidate, WITH the measurement that put it there.

    ``evidence`` is the whole point: a queue whose entries cannot be argued with
    is a queue of opinion. It is bounded, never dropped.
    """
    row = candidate.to_dict()
    return {
        "task_id": str(row.get("task_id") or ""),
        "source": str(row.get("source") or ""),
        "score": row.get("score"),
        "band": row.get("band"),
        "measured_offset": row.get("measured_offset"),
        "reason": _clip(row.get("reason") or ""),
        "instruction": _clip(row.get("instruction") or ""),
        "gate_paths": _loop_shape(row.get("gate_paths") or []),
        "evidence": _loop_shape(row.get("evidence") or {}),
    }


def _loop_repo_root(project: str | None) -> str | None:
    """Where to pick work from. ``None`` means this checkout.

    Deliberately NOT a free-form ``?repo_root=`` parameter: that would hand any
    page loaded in the browser a read primitive over the filesystem. A project
    is a declared, named thing in ``projects/``.
    """
    return resolve_repo_root(None, project) if project else None


def _loop_queue(project: str | None, limit: int) -> dict[str, Any]:
    from .spine import picker

    queue = picker.build_queue(_loop_repo_root(project), limit=limit)
    degraded = list(queue.degraded_sources)
    warnings = []
    if degraded:
        warnings.append(
            f"INCOMPLETE: {', '.join(degraded)} could not be consulted, so this "
            f"queue is not the whole picture -- an empty or short queue here is "
            f"NOT evidence that there is no work.")
    payload = core.envelope(project, warnings=warnings, queue={
        "candidates": [_loop_candidate(c) for c in queue.candidates],
        "n_candidates": len(queue.candidates),
        "limit": limit,
        "sources": _loop_shape(dict(queue.sources)),
        "notes": [_clip(n) for n in queue.notes][:LOOP_LIST_ITEMS],
        "degraded_sources": degraded,
        "incomplete": bool(degraded),
        "opt_in_sources_available": False,
    })
    return _loop_fit(payload, "queue", "candidates")


def _loop_attempt_row(intent: Any) -> dict[str, Any]:
    payload = intent.payload if isinstance(intent.payload, dict) else {}
    meta = payload.get("metadata")
    meta = meta if isinstance(meta, dict) else {}
    result = intent.result if isinstance(intent.result, dict) else {}
    gates = result.get("gates") if isinstance(result.get("gates"), dict) else {}
    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}

    outcome = str(result.get("state") or "") or None
    error = intent.error
    if error:
        try:
            parsed = json.loads(error)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            outcome = outcome or (str(parsed.get("state") or "") or None)
            error = parsed.get("error") or parsed.get("state") or ""
    return {
        "intent_id": intent.id,
        "kind": intent.kind,
        "state": intent.state,
        "created_ts": intent.created_ts,
        "resolved_ts": intent.resolved_ts,
        "effect_key": intent.effect_key,
        "task_id": str(payload.get("task_id") or ""),
        "instruction": _clip(payload.get("instruction") or ""),
        "source": str(meta.get("picker_source") or ""),
        "score": meta.get("picker_score"),
        "reason": _clip(meta.get("picker_reason") or ""),
        "outcome": outcome,
        "gates_passed": gates.get("passed"),
        "changed_paths": (len(artifact.get("changed_paths") or ())
                          if artifact else None),
        "error": _clip(error or "", LOOP_VALUE_CHARS) or None,
    }


def _loop_attempts(kind: str | None, limit: int, task_id: str) -> dict[str, Any]:
    from pathlib import Path as _Path

    from .spine import picker
    from .spine.ledger import SpineLedger, default_db_path

    path = default_db_path()
    rows: list[dict[str, Any]] = []
    error = ""
    exists = _Path(path).exists()
    if exists:
        try:
            ledger = SpineLedger(path, read_only=True)
            try:
                if task_id:
                    intents = ledger.intents_matching_payload(
                        "task_id", [task_id], kind=kind)
                    intents = [
                        i for i in intents
                        if isinstance(i.payload, dict)
                        and str(i.payload.get("task_id") or "") == task_id
                    ][:limit]
                else:
                    intents = ledger.recent_intents(kind, limit=limit)
            finally:
                ledger.close()
            rows = [_loop_attempt_row(i) for i in intents]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    degraded = ["spine_ledger"] if error else []
    warnings = []
    if error:
        warnings.append(
            f"INCOMPLETE: the spine ledger could not be read ({error}), so an "
            f"empty history here is NOT evidence that nothing was attempted.")
    payload = core.envelope(None, warnings=warnings, attempts={
        "intents": rows,
        "limit": limit,
        "kind": kind or "(every kind)",
        "task_id": task_id or None,
        "ledger": {
            "path": str(path),
            "exists": exists,
            "read_only": True,
            "error": error or None,
            "note": ("no ledger yet -- nothing has been attempted in this "
                     "checkout" if not exists else None),
        },
        "degraded_sources": degraded,
        "incomplete": bool(degraded),
        "attempt_intent_kind": picker.ATTEMPT_INTENT_KIND,
    })
    return _loop_fit(payload, "attempts", "intents")


def _loop_architecture(project: str | None) -> dict[str, Any]:
    from pathlib import Path as _Path

    from .spine import picker

    root = _Path(_loop_repo_root(project) or picker.ROOT)
    state = picker.load_map_state(repo_root=root)
    trust = picker.map_state_trustworthy(state, repo_root=root)
    counts = state.get("counts") if isinstance(state.get("counts"), dict) else {}
    measured = {k: len(v) for k, v in sorted(state.items())
                if isinstance(v, list)}
    disagreements = {k: {"recorded": counts.get(k), "measured": n}
                     for k, n in measured.items()
                     if k in counts and counts.get(k) != n}

    degraded = []
    if not state:
        degraded.append("map")
    elif not trust.get("trusted"):
        degraded.append("map")
    warnings = []
    if degraded:
        warnings.append(
            f"INCOMPLETE: the architecture snapshot could not be trusted "
            f"({trust.get('reason') or 'unreadable'}), so these counts describe "
            f"nothing you should act on. Regenerate with `daedalus map`.")
    return core.envelope(project, warnings=warnings, architecture={
        "path": str(root / picker.MAP_STATE_REL_PATH),
        "read": bool(state),
        "schema": state.get("schema"),
        "digest": str(state.get("digest") or ""),
        "note": _clip(state.get("note") or ""),
        "counts": _loop_shape(counts),
        "measured_lengths": measured,
        "count_disagreements": disagreements,
        "trusted": bool(trust.get("trusted")),
        "trust_reason": _clip(trust.get("reason") or ""),
        "trust": _loop_shape(dict(trust)),
        "degraded_sources": degraded,
        "incomplete": bool(degraded),
    })


_TASK_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}\Z")
_TASK_TERMINAL_SOURCES = ("inbox_report", "archive")
_TASK_EVENTS_MAX_S = 1800
_TASK_EVENTS_GRACE_S = 10.0
_TASK_EVENTS_PERIOD_S = 3.0


def _safe_bus_path(base_dir: Path, task_id: str, suffix: str) -> Path | None:
    if not isinstance(task_id, str) or not _TASK_ID_RE.match(task_id):
        return None
    p = base_dir / f"{task_id}{suffix}"
    try:
        p.resolve().relative_to(base_dir.resolve())
    except (ValueError, OSError):
        return None
    return p


def _read_json_or_none(path: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _task_report_fields(report: dict[str, Any]) -> tuple[str | None, str]:
    inner = report.get("report") if isinstance(report.get("report"), dict) else {}
    if inner:
        return inner.get("status"), str(inner.get("summary") or "")
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    for a in (result.get("assignments") or []):
        if not isinstance(a, dict):
            continue
        ar = a.get("result") if isinstance(a.get("result"), dict) else {}
        ar_report = ar.get("report") if isinstance(ar.get("report"), dict) else {}
        if ar_report:
            return ar_report.get("status"), str(ar_report.get("summary") or "")
    return None, str(report.get("error") or "")


def _derive_applied(report: dict[str, Any]) -> tuple[bool | None, str]:
    if not isinstance(report, dict):
        return None, "no report to inspect"
    bridge_status = report.get("bridge_status")
    if bridge_status in ("failed", "quarantined"):
        return False, f"bridge_status={bridge_status}: the run did not complete"
    mutation_blocked = report.get("mutation_blocked")
    if mutation_blocked:
        return False, _clip(str(mutation_blocked), LOOP_VALUE_CHARS)
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    assignments = result.get("assignments") if isinstance(result.get("assignments"), list) else []
    verdicts: list[bool | None] = []
    reasons: list[str] = []
    for a in assignments:
        if not isinstance(a, dict):
            continue
        status = a.get("status")
        ar = a.get("result") if isinstance(a.get("result"), dict) else {}
        owner = str(a.get("owner") or "?")
        if status == "escalated_after_verify_fail":
            verdicts.append(False)
            reasons.append(f"{owner}: verification failed, changes rolled back")
        elif status == "offloaded":
            if ar.get("draft"):
                verdicts.append(False)
                reasons.append(f"{owner}: saved as advisory draft {ar['draft']}, not applied")
            else:
                verdicts.append(True)
                reasons.append(f"{owner}: verified before/after disk diff, kept")
        else:
            verdicts.append(None)
            reasons.append(f"{owner}: status={status!r}, no verify signal")
    if verdicts:
        reason = _clip("; ".join(reasons), LOOP_VALUE_CHARS)
        if any(v is False for v in verdicts):
            return False, reason
        if all(v is True for v in verdicts):
            return True, reason
        return None, reason
    if bridge_status == "done":
        return None, ("no verify/rollback signal in this report -- this lane "
                      "(e.g. the direct Claude path) does not produce one, so "
                      "whether the change actually landed on disk cannot be "
                      "confirmed from here")
    return None, "insufficient information to determine whether anything was applied"


def _task_snapshot(task_id: str) -> dict[str, Any]:
    from . import progress as progress_mod
    from . import progress_sources

    now = time.time()
    prog = progress_sources.snapshot_from_bridge(task_id, now=now)
    if prog is None:
        return {
            "id": task_id, "found": False, "state": "unknown", "source": "none",
            "observed_at": core.now_iso(), "age_s": None,
            "lane": None, "project": None, "objective": None,
            "bridge_status": None, "report_status": None, "summary": None,
            "error": None, "applied": None,
            "applied_reason": ("no task with this id was found on the file bus "
                              "(wrong id, or the archive has since been cleared)"),
            "busy_for_s": None, "stalled": False, "progress": None,
        }

    progress_dict = prog.to_dict()
    report_path = _safe_bus_path(file_bridge.INBOX, task_id, ".report.json")
    report = (_read_json_or_none(report_path)
             if report_path is not None and report_path.exists() else None)

    if report is not None:
        request = report.get("request") if isinstance(report.get("request"), dict) else {}
        bridge_status = report.get("bridge_status")
        report_status, summary = _task_report_fields(report)
        applied, applied_reason = _derive_applied(report)
        return {
            "id": task_id, "found": True,
            "state": bridge_status or ("done" if prog.terminal else "unknown"),
            "source": "inbox_report",
            "observed_at": progress_dict["observed_at"], "age_s": progress_dict["age_s"],
            "lane": report.get("lane") or request.get("lane"),
            "project": request.get("project"),
            "objective": _clip(request.get("objective") or "", 400) or None,
            "bridge_status": bridge_status,
            "report_status": report_status,
            "summary": _clip(summary, LOOP_VALUE_CHARS) or None,
            "error": _clip(str(report.get("error") or ""), LOOP_VALUE_CHARS) or None,
            "applied": applied, "applied_reason": applied_reason,
            "busy_for_s": None, "stalled": prog.stalled, "progress": progress_dict,
        }

    if prog.terminal:
        return {
            "id": task_id, "found": True, "state": "unknown", "source": "archive",
            "observed_at": progress_dict["observed_at"], "age_s": progress_dict["age_s"],
            "lane": None, "project": None, "objective": None,
            "bridge_status": None, "report_status": None,
            "summary": ("the request is archived but its report is missing -- "
                       "state cannot be determined from the file bus"),
            "error": None, "applied": None,
            "applied_reason": "no report found for this id",
            "busy_for_s": None, "stalled": prog.stalled, "progress": progress_dict,
        }

    outbox_path = _safe_bus_path(file_bridge.OUTBOX, task_id, ".json")
    payload = (_read_json_or_none(outbox_path)
              if outbox_path is not None and outbox_path.exists() else None) or {}
    running_here = prog.latest_kind == progress_mod.CLAIMED
    return {
        "id": task_id, "found": True,
        "state": "running" if running_here else "queued",
        "source": "outbox",
        "observed_at": progress_dict["observed_at"], "age_s": progress_dict["age_s"],
        "lane": payload.get("lane"), "project": payload.get("project"),
        "objective": _clip(payload.get("objective") or "", 400) or None,
        "bridge_status": None, "report_status": None, "summary": None,
        "error": None, "applied": None, "applied_reason": "not finished yet",
        "busy_for_s": progress_dict.get("claimed_age_s") if running_here else None,
        "stalled": prog.stalled, "progress": progress_dict,
    }


def _task_artifacts(task_id: str) -> dict[str, Any]:
    snap = _task_snapshot(task_id)
    if not snap["found"]:
        return {"found": False}
    if snap["source"] not in _TASK_TERMINAL_SOURCES:
        return {"found": True, "available": False, "task": snap,
               "reason": "the run has not finished yet"}
    report_path = _safe_bus_path(file_bridge.INBOX, task_id, ".report.json")
    report = _read_json_or_none(report_path) if report_path is not None else None
    if report is None:
        return {"found": True, "available": False, "task": snap,
               "reason": "no readable report exists for this id"}
    inner = report.get("report") if isinstance(report.get("report"), dict) else {}
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    files_changed = [str(p) for p in (inner.get("files_changed") or [])]
    rolled_back: list[str] = []
    wrote: list[str] = []
    draft_ids: list[str] = []
    for a in (result.get("assignments") or []):
        if not isinstance(a, dict):
            continue
        ar = a.get("result") if isinstance(a.get("result"), dict) else {}
        rolled_back.extend(str(p) for p in (ar.get("rolled_back") or []))
        wrote.extend(str(p) for p in (a.get("wrote") or []))
        if ar.get("draft"):
            draft_ids.append(str(ar["draft"]))
        ar_report = ar.get("report") if isinstance(ar.get("report"), dict) else {}
        files_changed.extend(str(p) for p in (ar_report.get("files_changed") or []))
    return {
        "found": True, "available": True, "task": snap,
        "applied": snap["applied"], "applied_reason": snap["applied_reason"],
        "files_changed": _loop_shape(sorted(set(files_changed))),
        "rolled_back": _loop_shape(sorted(set(rolled_back))),
        "wrote": _loop_shape(sorted(set(wrote))),
        "draft_ids": _loop_shape(sorted(set(draft_ids))),
        "tests_run": _loop_shape(inner.get("tests_run") or []),
        "risks": _loop_shape(inner.get("risks") or []),
        "todos": _loop_shape(inner.get("todos") or []),
        "handoff": _loop_shape(inner.get("handoff") or {}),
        "report": _loop_shape(report),
    }


_CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}\Z")


def _dataclass_or_none(value: Any) -> Any:
    from dataclasses import asdict, is_dataclass

    if value is None:
        return None
    return asdict(value) if is_dataclass(value) else value


def _conversation_view(conversation_id: str, limit: int = LOOP_MAX_LIMIT) -> dict[str, Any] | None:
    from . import conversation as conv

    store = conv.default_store()
    if not store.conversation_exists(conversation_id):
        return None
    resumed = store.resume(conversation_id)
    turns = store.turns(conversation_id, limit=limit)

    def _turn_dict(t: Any) -> dict[str, Any]:
        d = _dataclass_or_none(t) or {}
        d["user_message"] = _clip(d.get("user_message") or "")
        d["assistant_text"] = _clip(d.get("assistant_text") or "") or None
        d["envelope"] = _loop_shape(d.get("envelope") or {})
        d["proposed_action"] = _loop_shape(d.get("proposed_action")) if d.get("proposed_action") else None
        return d

    def _dispatch_dict(d: dict[str, Any]) -> dict[str, Any]:
        return {"link": _dataclass_or_none(d.get("link")),
               "latest": _dataclass_or_none(d.get("latest"))}

    return {
        "conversation_id": conversation_id,
        "exists": resumed["exists"],
        "turn_count": resumed["turn_count"],
        "narrative": resumed["narrative"],
        "last_turn": _turn_dict(resumed["last_turn"]) if resumed["last_turn"] else None,
        "turns": [_turn_dict(t) for t in turns],
        "turns_returned": len(turns),
        "dispatches": [_dispatch_dict(d) for d in resumed["dispatches"]],
        "open_dispatches": [_dispatch_dict(d) for d in resumed["open_dispatches"]],
    }


def _dispatch_status_view(task_id: str) -> dict[str, Any] | None:
    from . import conversation as conv

    try:
        status = conv.default_store().dispatch_status(task_id)
    except Exception:
        return None
    if status is None:
        return None
    return {"link": _dataclass_or_none(status["link"]),
           "events": [_dataclass_or_none(e) for e in status["events"]],
           "latest": _dataclass_or_none(status["latest"])}


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

    def _authorized(self) -> bool:
        token = getattr(self.server, "daedalus_auth_token", "") or ""
        if not token:
            return True
        supplied = (self.headers.get("Authorization") or "").strip()
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        return hmac.compare_digest(supplied, token)

    def _deny(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", "Bearer")
        body = _json_safe({"ok": False, "error": "unauthorized: this server is bound to a non-loopback address and requires a bearer token"})
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._authorized():
            self._deny()
            return
        try:
            self._handle_get()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def _bind_decision(self):
        from daedalus.spine.effect_boundary import GuardDecision

        token = getattr(self.server, "daedalus_auth_token", "") or ""
        return GuardDecision(
            "web.authenticated_bind",
            True,
            "loopback bind (no packet leaves the machine)" if not token
            else "non-loopback opt-in bind; bearer token verified",
        )

    def do_PUT(self) -> None:
        if not self._authorized():
            self._deny()
            return
        try:
            from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

            begin_effect("web.mutations_put", REGISTRY_BY_ID["web.mutations_put"].effects, (self._bind_decision(),))
            self._handle_put()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self) -> None:
        if not self._authorized():
            self._deny()
            return
        try:
            from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

            begin_effect("web.mutations", REGISTRY_BY_ID["web.mutations"].effects, (self._bind_decision(),))
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
                    emit("heartbeat", {"watcher_state": cur.get("watcher_state"), "in_flight": cur.get("in_flight")})
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
        project = (qs.get("project") or [""])[0]
        message = (qs.get("message") or [""])[0].strip()
        if not project or not message:
            self._send_json({"ok": False, "error": "project and message are required"}, status=400)
            return
        provider = (qs.get("provider") or [""])[0] or None
        model = (qs.get("model") or [""])[0] or None
        effort = (qs.get("effort") or [""])[0] or None
        conversation_id = (qs.get("conversation_id") or [""])[0] or None
        request_id = ((qs.get("request_id") or [""])[0].strip() or f"ikarus:{secrets.token_hex(16)}")

        registry = ikarus_cancellation.default_registry()
        try:
            registry.validate_request_id(request_id)
        except ikarus_cancellation.CancellationRegistrationError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        try:
            cancellation = registry.open(request_id)
        except ikarus_cancellation.CancellationRegistrationError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=409)
            return

        stream = None
        try:
            unit_id: str | None = None
            try:
                from . import progress as progress_mod
                unit_id = progress_mod.open_unit(source="web_api.ikarus_stream", detail={"project": project, "message_chars": len(message), "request_id": request_id})
            except Exception:
                unit_id = None

            self.close_connection = True
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
                stream = ikarus_os.ask_stream(project, message, provider=provider, model=model, effort=effort, conversation_id=conversation_id, cancellation=cancellation)
                if unit_id:
                    from . import progress_sources
                    stream = progress_sources.watch_stream(unit_id, stream, source="web_api.ikarus_stream")
                for event, payload in stream:
                    if event == "start":
                        payload = {**payload, "request_id": request_id}
                        if unit_id:
                            payload["progress_unit_id"] = unit_id
                    emit(event, payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                cancellation.cancel()
                return
            except Exception as exc:
                try:
                    emit("final", core.envelope(project, intent="error", assistant=f"I hit a snag: {exc}", provider_used="deterministic", cancellation_request_id=request_id))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    cancellation.cancel()
                    return
        finally:
            if stream is not None:
                try:
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                except Exception:
                    pass
            registry.release(cancellation)

    def _handle_task_events(self, task_id: str) -> None:
        if not _TASK_ID_RE.match(task_id):
            self._send_json({"ok": False, "error": "invalid task id"}, status=400)
            return
        self.close_connection = True
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
            start = time.time()
            last_state: str | None = None
            last_stalled = False
            last_emit = 0.0
            while True:
                snap = _task_snapshot(task_id)
                now = time.time()
                if not snap["found"]:
                    if now - start > _TASK_EVENTS_GRACE_S:
                        emit("final", snap)
                        return
                    time.sleep(1.0)
                    continue
                terminal = snap["source"] in _TASK_TERMINAL_SOURCES
                if terminal:
                    emit("final", snap)
                    return
                if now - start > _TASK_EVENTS_MAX_S:
                    emit("final", {**snap, "timed_out": True, "applied_reason": snap["applied_reason"] + f" (subscription open >{_TASK_EVENTS_MAX_S:.0f}s; poll GET /api/queue/<id> to keep checking)"})
                    return
                stalled = bool(snap.get("stalled"))
                if (snap["state"] != last_state or stalled != last_stalled or now - last_emit >= _TASK_EVENTS_PERIOD_S):
                    emit("hello" if last_state is None else "progress", snap)
                    last_emit = now
                last_state = snap["state"]
                last_stalled = stalled
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        except Exception as exc:
            try:
                emit("error", {"ok": False, "error": str(exc)})
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path
        if path == "/api/dashboard":
            self._send_json(core.get_dashboard((qs.get("project") or [None])[0]))
        elif path == "/api/governance":
            self._send_json(core.get_governance((qs.get("project") or [None])[0]))
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
            self._send_json(core.envelope(None, **runtime_registry.all_status(use_cache=True)))
        elif path == "/api/accelerators/status":
            deep = (qs.get("deep") or ["0"])[0] in ("1", "true", "yes")
            probe_remote = ((qs.get("probe_remote") or ["0"])[0] in ("1", "true", "yes"))
            self._send_json(core.envelope(None, accelerators=accelerators.accelerator_status(deep=deep, probe_remote=probe_remote)))
        elif path == "/api/env/status":
            self._send_json(core.envelope(None, env=env_status()))
        elif path == "/api/capabilities":
            self._send_json(hierarchy.capabilities())
        elif path == "/api/catalogue":
            query = (qs.get("q") or [""])[0].strip()
            if len(query) > 2000:
                self._send_json({"ok": False, "error": "q must be at most 2000 characters"}, status=400)
                return
            try:
                limit = int((qs.get("limit") or ["8"])[0])
            except ValueError:
                self._send_json({"ok": False, "error": "limit must be an integer"}, status=400)
                return
            if not 1 <= limit <= 100:
                self._send_json({"ok": False, "error": "limit must be between 1 and 100"}, status=400)
                return
            from . import gui_catalogue
            catalogue = gui_catalogue.load_catalogue()
            payload: dict[str, Any] = {"catalogue": catalogue.to_dict()}
            if query:
                payload["search"] = gui_catalogue.search(catalogue, query, limit=limit, use_latent=False).to_dict()
            self._send_json(core.envelope(None, **payload))
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
        elif path == "/api/topology":
            project = (qs.get("project") or [None])[0]
            if not project:
                self._send_json({"ok": False, "error": "project is required"}, status=400)
                return
            repo_root = resolve_repo_root(None, project)
            refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
            topo = spectral_partition(repo_root, idx=_structure_index(project, refresh))
            self._send_json(core.envelope(project, topology=topo))
        elif path == "/api/context/plan":
            project = (qs.get("project") or [None])[0]
            objective = (qs.get("q") or [""])[0].strip()
            if not project:
                self._send_json({"ok": False, "error": "project is required"}, status=400)
                return
            if not objective:
                self._send_json({"ok": False, "error": "q is required"}, status=400)
                return
            if len(objective) > 4000:
                self._send_json({"ok": False, "error": "q must be at most 4000 characters"}, status=400)
                return
            try:
                max_tokens = int((qs.get("max_tokens") or ["8000"])[0])
            except ValueError:
                self._send_json({"ok": False, "error": "max_tokens must be an integer"}, status=400)
                return
            if not 1 <= max_tokens <= 200_000:
                self._send_json({"ok": False, "error": "max_tokens must be between 1 and 200000"}, status=400)
                return
            refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
            use_latent = (qs.get("latent") or ["0"])[0] in ("1", "true", "yes")
            use_cochange = ((qs.get("cochange") or ["0"])[0] in ("1", "true", "yes"))
            repo_root = resolve_repo_root(None, project)
            result = plan_context(repo_root, objective, idx=_structure_index(project, refresh), project=project, token_budget=max_tokens, use_latent=use_latent, temporal_pairs=(co_change_pairs(repo_root) if use_cochange else ()))
            self._send_json(core.envelope(project, context_plan=result.to_dict()))
        elif path == "/api/latent/search":
            query = (qs.get("q") or [""])[0].strip()
            try:
                limit = int((qs.get("limit") or ["5"])[0])
            except ValueError:
                self._send_json({"ok": False, "error": "limit must be an integer"}, status=400)
                return
            if not 1 <= limit <= 100:
                self._send_json({"ok": False, "error": "limit must be between 1 and 100"}, status=400)
                return
            metric = (qs.get("metric") or ["cosine"])[0]
            if not query:
                self._send_json({"ok": False, "error": "q is required"}, status=400)
                return
            if len(query) > 2000:
                self._send_json({"ok": False, "error": "q must be at most 2000 characters"}, status=400)
                return
            if metric != "cosine":
                self._send_json({"ok": False, "error": "only cosine search is supported"}, status=400)
                return
            try:
                from .memory import VECTOR_DB_PATH
                from .memory.embeddings import EventVectorStore
                store = EventVectorStore(VECTOR_DB_PATH)
                try:
                    results = store.search(query, limit=limit, metric=metric)
                    hits = [{"event": ev.to_dict(), "score": round(score, 4)} for ev, score in results]
                finally:
                    store.close()
                self._send_json(core.envelope(None, results=hits, query=query))
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
        elif path == "/api/events/memory":
            try:
                limit = int((qs.get("limit") or ["50"])[0])
            except ValueError:
                self._send_json({"ok": False, "error": "limit must be an integer"}, status=400)
                return
            if not 1 <= limit <= 1000:
                self._send_json({"ok": False, "error": "limit must be between 1 and 1000"}, status=400)
                return
            events = memory_mod.load_events()[-limit:]
            self._send_json(core.envelope(None, events=events))
        elif path == "/api/loop/queue":
            try:
                limit = _loop_limit(qs, 10)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            project = (qs.get("project") or [None])[0]
            try:
                self._send_json(_loop_queue(project, limit))
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
        elif path == "/api/loop/attempts":
            try:
                limit = _loop_limit(qs, 20)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            from .spine import picker as _picker
            kind = (qs.get("kind") or [_picker.ATTEMPT_INTENT_KIND])[0]
            kind = None if kind == "all" else _clip(kind, 200)
            task_id = _clip((qs.get("task_id") or [""])[0], 200)
            self._send_json(_loop_attempts(kind, limit, task_id))
        elif path == "/api/loop/architecture":
            project = (qs.get("project") or [None])[0]
            try:
                self._send_json(_loop_architecture(project))
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
        elif path == "/api/health":
            try:
                from . import health as _health
                deep = (qs.get("deep") or ["0"])[0] in ("1", "true", "yes")
                remote = (qs.get("probe_remote") or ["0"])[0] in ("1", "true", "yes")
                only = _clip((qs.get("only") or [""])[0], 100) or None
                payload = _health.to_payload(_health.assess(only, deep=deep, probe_remote=remote))
                payload["asked"] = {"deep": deep, "probe_remote": remote, "only": only}
                self._send_json(core.envelope(None, health=payload))
            except Exception as exc:
                self._send_json({"ok": False, "error": f"the health surface itself failed: {type(exc).__name__}: {exc}", "health": None}, status=500)
        elif path == "/api/drafts":
            project = (qs.get("project") or [None])[0]
            root, perr = "", ""
            if project:
                try:
                    from .projects import load_project
                    root = str(load_project(project).get("repo_root") or "")
                except ValueError as exc:
                    perr = str(exc)
            warnings = []
            if project and not root:
                warnings.append(perr or f"unknown project '{project}'; no drafts could be scoped to it")
                rows = []
            else:
                rows = drafts.list_drafts(root or None)
            pending = [d for d in rows if d.get("status") == "pending"]
            self._send_json(core.envelope(project, drafts=rows, pending_count=len(pending), scope=root or None, warnings=warnings))
        elif path.startswith("/api/drafts/"):
            draft_id = unquote(path.split("/", 3)[3])
            d = drafts.get_draft(draft_id)
            self._send_json(core.envelope(None, draft=d) if d else {"ok": False, "error": f"unknown draft {draft_id}"}, status=200 if d else 404)
        elif path.startswith("/api/queue/"):
            parts = [unquote(p) for p in path.strip("/").split("/")]
            if len(parts) not in (3, 4):
                self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
                return
            task_id = parts[2]
            if not _TASK_ID_RE.match(task_id):
                self._send_json({"ok": False, "error": "invalid task id"}, status=400)
                return
            if len(parts) == 3:
                snap = _task_snapshot(task_id)
                if snap["found"]:
                    snap["conversation_dispatch"] = _dispatch_status_view(task_id)
                self._send_json(core.envelope(None, task=snap) if snap["found"] else {"ok": False, "error": f"unknown task id {task_id}", "task": snap}, status=200 if snap["found"] else 404)
                return
            sub = parts[3]
            if sub == "artifacts":
                art = _task_artifacts(task_id)
                if not art.get("found"):
                    self._send_json({"ok": False, "error": f"unknown task id {task_id}"}, status=404)
                    return
                self._send_json(core.envelope(None, artifacts=art))
                return
            if sub == "events":
                self._handle_task_events(task_id)
                return
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
        elif path.startswith("/api/conversations/"):
            parts = [unquote(p) for p in path.strip("/").split("/")]
            if len(parts) != 3:
                self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
                return
            conversation_id = parts[2]
            if not _CONVERSATION_ID_RE.match(conversation_id):
                self._send_json({"ok": False, "error": "invalid conversation id"}, status=400)
                return
            try:
                limit = _loop_limit(qs, LOOP_MAX_LIMIT)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            try:
                view = _conversation_view(conversation_id, limit=limit)
            except Exception as exc:
                self._send_json({"ok": False, "error": f"the conversation store failed: {type(exc).__name__}: {exc}"}, status=500)
                return
            self._send_json(core.envelope(None, conversation=view) if view is not None else {"ok": False, "error": f"unknown conversation id {conversation_id}"}, status=200 if view is not None else 404)
        elif path.startswith("/api/progress/"):
            parts = [unquote(p) for p in path.strip("/").split("/")]
            if len(parts) != 3:
                self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
                return
            unit_id = parts[2]
            if not _CONVERSATION_ID_RE.match(unit_id):
                self._send_json({"ok": False, "error": "invalid unit id"}, status=400)
                return
            try:
                from . import progress_sources
                prog = progress_sources.snapshot_any(unit_id)
                self._send_json(core.envelope(None, progress=prog.to_dict()))
            except Exception as exc:
                self._send_json({"ok": False, "error": f"the progress source failed: {type(exc).__name__}: {exc}"}, status=500)
            return
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
            result = core.queue_task(
                project,
                objective,
                lane=str(body.get("lane") or "local_only"),
                source=str(body.get("source") or "webapp"),
                strategy=str(body.get("strategy") or "single"),
                paths=[str(p) for p in body.get("paths") or []],
            )
            task_id = Path(str(result.get("queued") or "")).stem or None
            result["id"] = task_id
            conversation_id = body.get("conversation_id")
            if task_id and conversation_id:
                turn_id = body.get("turn_id")
                try:
                    from . import conversation as conv

                    link = conv.default_store().link_dispatch(
                        str(conversation_id), task_id,
                        turn_id=(int(turn_id) if turn_id is not None else None),
                        kind="queue_task",
                        detail={
                            "schema": "conversation.dispatch.identity.v1",
                            "project": project,
                            "objective": objective,
                            "lane": str(
                                result.get("lane")
                                or body.get("lane")
                                or "local_only"
                            ),
                        },
                    )
                    result["conversation_link"] = {
                        "conversation_id": link.conversation_id,
                        "turn_id": link.turn_id, "dispatch_ref": link.dispatch_ref,
                        "linked": True}
                except Exception as exc:
                    result["conversation_link"] = {
                        "conversation_id": str(conversation_id), "linked": False,
                        "error": f"{type(exc).__name__}: {exc}"}
            self._send_json(result)
            return
        if path == "/api/conversations":
            from . import conversation as conv
            self._send_json(core.envelope(None, conversation_id=conv.new_conversation_id()))
            return
        if path == "/api/ikarus/cancel":
            request_id = str(body.get("request_id") or "").strip()
            if not request_id:
                self._send_json({"ok": False, "error": "request_id is required"}, status=400)
                return
            try:
                receipt = ikarus_cancellation.default_registry().cancel_and_wait(request_id, timeout_s=0.25)
            except (ikarus_cancellation.CancellationRegistrationError, ValueError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._send_json(core.envelope(None, cancellation=receipt.to_dict()))
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
            conversation_id = body.get("conversation_id")
            self._send_json(ikarus_os.ask(project, message, provider=str(provider) if provider else None, model=str(model) if model else None, effort=str(effort) if effort else None, conversation_id=str(conversation_id) if conversation_id else None))
            return
        if path.startswith("/api/drafts/") and (path.endswith("/apply") or path.endswith("/dismiss")):
            parts = [unquote(p) for p in path.strip("/").split("/")]
            draft_id, verb = parts[2], parts[3]
            if verb == "apply":
                packet = drafts.apply_payload(draft_id)
                self._send_json(core.envelope(None, applied=packet) if packet else {"ok": False, "error": f"unknown draft {draft_id}"}, status=200 if packet else 404)
            else:
                d = drafts.set_status(draft_id, "dismissed")
                self._send_json(core.envelope(None, draft=d) if d else {"ok": False, "error": f"unknown draft {draft_id}"}, status=200 if d else 404)
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


class NonLoopbackBindRefused(RuntimeError):
    pass


ALLOW_REMOTE_ENV = "DAEDALUS_WEB_ALLOW_REMOTE_CLIENTS"
AUTH_TOKEN_ENV = "DAEDALUS_WEB_TOKEN"
MIN_AUTH_TOKEN_CHARS = 32


def _refusal(host: str, why: str, remedy: str) -> str:
    return (
        f"REFUSED: daedalus web will not serve {host!r}.\n\n"
        f"{why}\n\n"
        f"This server has NO AUTHENTICATION on its loopback path, because on loopback the operating system is the boundary. Every endpoint is reachable by anyone who can reach the port: the spine ledger (what the loop has attempted), the picker queue (what it is working on), PUT endpoints that rewrite agent roles, and POST endpoints that queue work and invoke models -- that last one is remote SPEND, not just remote read. ADR-002 rejected a subsystem for being exactly this shape: an independent, unauthenticated network server.\n\n"
        f"The server was NOT started, and it was NOT quietly downgraded to loopback.\n\n{remedy}"
    )


def _resolve_bind(host: str, allow_remote_clients: bool) -> str:
    from .sensitivity import is_loopback_host

    host = str(host or "").strip()
    if is_loopback_host(host):
        return ""

    if not (allow_remote_clients or os.environ.get(ALLOW_REMOTE_ENV, "").strip().lower() in ("1", "true", "yes")):
        named = repr(host) if host else "an empty host (every interface)"
        raise NonLoopbackBindRefused(_refusal(
            host or "",
            f"{named} is not this machine. sensitivity.lane_for_host reports it as UNTRUSTED, which in this project means 'bytes leave this host'.",
            f"  * to serve this machine only:  --host 127.0.0.1  (the default)\n  * 'localhost' is refused ON PURPOSE: it is a NAME, and a name that resolves to loopback when it is checked can resolve elsewhere when it is connected. Use the numeric literal.\n  * to genuinely serve other machines, opt in explicitly AND authenticate:\n        set {AUTH_TOKEN_ENV} to a secret of at least {MIN_AUTH_TOKEN_CHARS} characters\n        pass --allow-remote-clients (or {ALLOW_REMOTE_ENV}=1)\n    every request must then carry 'Authorization: Bearer <token>'."))

    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    if len(token) < MIN_AUTH_TOKEN_CHARS:
        state = "is not set" if not token else f"is only {len(token)} characters long"
        raise NonLoopbackBindRefused(_refusal(host, f"--allow-remote-clients was given, but {AUTH_TOKEN_ENV} {state}. An opt-in is a decision to expose this, not a decision to expose it to ANYONE -- so the escape hatch carries authentication with it and cannot be opened without.", f"  * set {AUTH_TOKEN_ENV} to at least {MIN_AUTH_TOKEN_CHARS} characters and try again."))
    return token


def run(host: str = "127.0.0.1", port: int = 8765, *, allow_remote_clients: bool = False) -> None:
    load_env()
    token = _resolve_bind(host, allow_remote_clients)
    httpd = ThreadingHTTPServer((host, port), DaedalusHandler)
    httpd.daedalus_auth_token = token
    if token:
        print(f"!! Daedalus Agent OS is bound to {host}, which is NOT this machine. Every request requires 'Authorization: Bearer <{AUTH_TOKEN_ENV}>'. Unauthenticated requests get 401.", flush=True)
    print(f"Daedalus Agent OS listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> None:
    import sys

    parser = argparse.ArgumentParser(description="Run the local Daedalus Agent OS web API.")
    parser.add_argument("--host", default="127.0.0.1", help="address to serve. Anything that is not this machine is REFUSED unless --allow-remote-clients is also given.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-remote-clients", action="store_true", help=f"serve machines other than this one. Requires {AUTH_TOKEN_ENV} (>= {MIN_AUTH_TOKEN_CHARS} chars); every request then needs an Authorization: Bearer header.")
    args = parser.parse_args(argv)
    try:
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision, begin_effect

        token = _resolve_bind(args.host, args.allow_remote_clients)
        begin_effect("cli.web_api", REGISTRY_BY_ID["cli.web_api"].effects, (GuardDecision("web.authenticated_bind", True, f"_resolve_bind accepted host={args.host!r} " + ("(loopback, no token)" if not token else "(non-loopback opt-in, token set)")),))
        run(args.host, args.port, allow_remote_clients=args.allow_remote_clients)
    except NonLoopbackBindRefused as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()

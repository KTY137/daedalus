"""Local HTTP API and static webapp host for Daedalus Agent OS."""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import re
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
        # Property 2, in the shape a program can branch on.
        "degraded_sources": degraded,
        "incomplete": bool(degraded),
        # The two opt-in sources are NOT reachable from here on purpose: both
        # cost a whole-repo analysis pass, and a browser tab must not be able to
        # start a multi-minute replay inside the server process. The queue says
        # so itself -- ``sources.eval_gate`` / ``sources.hotspots`` carry the
        # reason they did not run.
        "opt_in_sources_available": False,
    })
    return _loop_fit(payload, "queue", "candidates")


def _loop_attempt_row(intent: Any) -> dict[str, Any]:
    """One ledger intent, projected through a FIXED allowlist.

    Not ``dict(intent.payload)``. The recorded payload carries the primary
    checkout's absolute path, the worktree root, and whatever a caller put in
    ``metadata``; the recorded result carries a gate's command line and the tail
    of its output. None of that is needed to answer "what has the loop tried,
    and how did it end", and an endpoint that returns whatever happens to be in
    a blob is an endpoint whose exposure changes when someone edits a runner.
    """
    payload = intent.payload if isinstance(intent.payload, dict) else {}
    meta = payload.get("metadata")
    meta = meta if isinstance(meta, dict) else {}
    result = intent.result if isinstance(intent.result, dict) else {}
    gates = result.get("gates") if isinstance(result.get("gates"), dict) else {}
    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}

    outcome = str(result.get("state") or "") or None
    error = intent.error
    if error:
        # mark_failed stores canonical_json(result_body), i.e. the whole attempt
        # result as text. Read the two fields worth showing out of it rather
        # than blowing the blob back through the socket.
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
            # READ-ONLY. See property 1 above -- the plain constructor mutates.
            ledger = SpineLedger(path, read_only=True)
            try:
                if task_id:
                    intents = ledger.intents_matching_payload(
                        "task_id", [task_id], kind=kind)
                    # LIKE is a substring test; confirm the row really is the id
                    # asked for and not one that merely contains it.
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
        except Exception as exc:  # unreadable, locked, corrupt, schema mismatch
            error = f"{type(exc).__name__}: {exc}"

    # A ledger that is not there yet and a ledger that will not open are
    # DIFFERENT facts. The first is a fresh checkout that has attempted nothing;
    # the second is a source that failed, and it is reported as one.
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
    """Counts out of the GENERATED, digest-covered architecture snapshot.

    Counts and the digest verdict only. The module lists themselves are not
    served here: the ones that are actionable already arrive as queue candidates
    with their evidence attached, and the rest would be a few hundred paths that
    no reader of a counts endpoint asked for.
    """
    from pathlib import Path as _Path

    from .spine import picker

    root = _Path(_loop_repo_root(project) or picker.ROOT)
    state = picker.load_map_state(repo_root=root)
    # repo_root matters: the trust verdict is integrity AND freshness, and
    # freshness is answered against the HEAD of the repo being asked about.
    trust = picker.map_state_trustworthy(state, repo_root=root)
    counts = state.get("counts") if isinstance(state.get("counts"), dict) else {}
    measured = {k: len(v) for k, v in sorted(state.items())
                if isinstance(v, list)}
    # The snapshot's own counts versus the lengths of the lists in the same
    # file. They should agree; if they do not, the file is telling two stories
    # and that is worth more than either number.
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
        # The whole verdict, not just the boolean. The predicate grew a second
        # question (freshness) after the first was already shipped; a client
        # that only ever saw ``trusted`` would have silently lost the reason.
        "trust": _loop_shape(dict(trust)),
        "degraded_sources": degraded,
        "incomplete": bool(degraded),
    })


# --------------------------------------------------------------------------- #
# task lifecycle: start work, get an id, watch it, collect what it produced    #
# --------------------------------------------------------------------------- #
# POST /api/queue already starts work (core.queue_task -> file_bridge.enqueue).
# What was missing for an assistant to actually DRIVE that -- rather than fire
# a request and never look at it again -- is a way to address ONE piece of
# queued work afterwards. file_bridge already has the id: enqueue() names its
# request file ``{stamp}-{slug}-{uuid8}.json``, and that filename STEM is the
# idempotency key the bridge itself uses to find the eventual report
# (``inbox/{key}.report.json``) and the archived request (``runs/processed/
# {key}.json``). Nothing new is minted below -- ``id`` IS that stem.
#
# THE HONESTY RULE THIS SECTION IS BUILT TO: a status of "done" must mean
# something OBSERVED, not something started, and it must say its own age.
# Concretely:
#
#   * every snapshot carries ``observed_at`` + ``age_s`` -- the mtime of the
#     file actually read, not "now". A caller polling this is reading a
#     photograph, not a live feed, and the payload says so on every response.
#   * ``bridge_status: "done"`` is NOT ``applied: true``. The bridge's "done"
#     means the pipeline finished and produced a report -- it says nothing by
#     itself about whether the change survived on disk. The lanes disagree
#     sharply on that:
#       - local/ikarus (offload()) verifies a before/after disk diff and
#         either keeps the write (``action: "offloaded"``) or ROLLS IT BACK
#         (``action: "escalated_after_verify_fail"``, offload.py ~490-559).
#         Advisory mode writes nothing at all -- it saves a draft instead
#         (kairos/drafts.py) for a human/Claude to apply later.
#       - the codex lane is advisory-only BY CONSTRUCTION and says so on its
#         own report (``mutation_blocked``, core.py ``_codex_report``).
#       - the direct claude lane (claude_bridge.ask_claude) writes with NO
#         verify/rollback wrapper at all, so there is no on-disk signal to
#         confirm from here -- it is reported as unknown, never assumed true.
#     ``_derive_applied`` below reads whichever of these signals a report
#     actually carries and returns ``None`` (not ``True``) when it cannot
#     tell -- the same discipline health.py applies to its own five-state
#     vocabulary, at this layer.
#
# SEAM NOTE, ikarus-progress (the honest-progress-event-model work): the
# state vocabulary here (queued/running/done/failed/quarantined/unknown) and
# the per-event observed_at/age_s stamping are THIS endpoint's own, built
# straight off the file bus (outbox/heartbeat/inbox) because no richer event
# model existed yet when this shipped. If/when one lands, reconcile the
# vocabulary here against it; the endpoint SHAPE (GET /api/queue/<id>/events,
# SSE, one-shot, terminal-closes -- same contract as /api/ikarus/stream)
# should not need to change even if what feeds it does.
#
# SEAM NOTE, ikarus-conversation (the conversation-state work): daedalus/
# conversation.py landed while this section was being written (see the
# "conversation seam" section below, right after _task_artifacts) --
# POST /api/ikarus/ask, GET /api/ikarus/stream, POST /api/queue and
# GET /api/queue/<id> are now wired to it, additively, exactly as that
# module's own ask()/ask_stream() kwarg makes possible: omit
# conversation_id anywhere below and every one of these endpoints behaves
# byte-for-byte as it did before this landed.
#
# SEAM NOTE, progress_sources (the honest-progress-event-model work): also
# landed mid-write. _task_snapshot below now LAYERS ON
# daedalus.progress_sources.snapshot_from_bridge for "is it found" and the
# coarse lifecycle stage, rather than keeping this section's own file-bus
# reader as a second, disagreeing state machine -- see that function's
# docstring for exactly where this section's own reading still adds
# something progress_sources does not yet do (the applied/lane/summary
# decomposition of a landed report).

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}\Z")  # \Z, not $: "$" also matches before a trailing newline
_TASK_TERMINAL_SOURCES = ("inbox_report", "archive")
_TASK_EVENTS_MAX_S = 1800      # give up holding the SSE socket open after 30 min
_TASK_EVENTS_GRACE_S = 10.0    # tolerate the enqueue -> first-poll race before
                               # reporting a fresh id as "not found"
_TASK_EVENTS_PERIOD_S = 3.0    # minimum gap between two non-terminal SSE events


def _safe_bus_path(base_dir: Path, task_id: str, suffix: str) -> Path | None:
    """Resolve a URL-supplied task id to a path under ``base_dir``, or ``None``
    if the id is not a plain filename stem or would resolve outside
    ``base_dir`` (rejects traversal, separators, absolute paths). Same shape
    as ``kairos.drafts._safe_path`` -- reimplemented locally because that one
    is bound to a single directory and this module addresses three (outbox /
    inbox / archive)."""
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
    """(report_status, summary) read across every lane shape the bus carries:
    a top-level agent_report_v1 (claude / codex lanes), or -- for the
    local/ikarus lane, which nests one report per dispatched assignment --
    the first assignment that has one. Best-effort only; NEVER the source of
    truth for whether anything was applied (see _derive_applied)."""
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
    """Whether the work this report describes actually landed on disk, and
    the evidence for saying so. Returns ``None`` (not ``True``) whenever the
    report does not carry enough to tell -- see the section docstring above
    for why the three lanes need three different readings."""
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
    """This task's OBSERVED state, right now -- a photograph, not a promise.

    LAYERED ON :func:`daedalus.progress_sources.snapshot_from_bridge`, this
    repo's shared, cross-source honest-progress model (QUEUED / CLAIMED /
    DONE, Fact-based MEASURED/INHERITED provenance, stall detection) -- used
    here for "is it found" and the coarse lifecycle stage, rather than a
    second file-bus reader kept in parallel. Two disagreeing readers of the
    same outbox/inbox files is the exact bug class ``daedalus.health`` exists
    to catch; this function does not add a second instance of it. Its full
    ``UnitProgress`` rides along under the ``progress`` key.

    On top of that shared model, this function decomposes the raw file-bridge
    report itself once one has landed -- bridge_status / applied / lane /
    summary -- because ``snapshot_from_bridge`` deliberately treats the
    report as opaque past ``bridge_status`` (it does not walk the nested
    per-assignment shape ``offload()`` produces), and the applied-vs-merely-
    finished distinction this whole section exists to make needs that walk.
    The two are complementary, never contradictory: ``progress["applied"]``
    is the shared model's own answer (currently always ``None`` for a landed
    bridge report -- it does not attempt this decomposition), while the
    top-level ``applied``/``applied_reason`` here is this endpoint's more
    specific one, for this one lane.

    ``found=False`` covers both a wrong id and a genuinely unknown one; nothing
    here raises to tell those apart, because a filesystem check cannot.
    """
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
        # progress_sources considers this finished (archived) but no report
        # could be read back -- degraded, not a verdict worth guessing at.
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
    """What a completed task produced, or an honest 'not yet' when it has not
    finished. Never 'found but empty' for a run still in flight -- callers
    must check ``available`` before reading anything else."""
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
        # Bounded full dump for anything the allowlist above missed -- same
        # philosophy as _loop_shape's own docstring: bound, never drop silently.
        "report": _loop_shape(report),
    }


# --------------------------------------------------------------------------- #
# conversation + progress seam                                                #
# --------------------------------------------------------------------------- #
# Both sibling modules landed while the section above was being written.
# ``daedalus/conversation.py`` gives the Ikarus assistant seam (ask/ask_stream)
# a durable multi-turn identity: a conversation_id, an append-only turn log,
# and dispatch attribution (a turn caused work; that work is a caller-supplied
# ref, e.g. a file-bridge task id, that a later report can be found under).
# ``daedalus/progress.py`` + ``progress_sources.py`` give a single unit of work
# (a chat generation, an offload call, a spine attempt) an honest, closed-
# vocabulary event trail -- queued/claimed/generating/.../done, never a
# fabricated percentage, never "running" read as "progressing".
#
# What is wired below, and what is deliberately left for the modules' own
# owners: this file starts conversations, appends turns via ikarus_os's
# opt-in ``conversation_id`` kwarg, links a queued task to the turn that
# proposed it, and reads all of that back. It does NOT call
# ``conversation.record_dispatch_event`` anywhere -- the module's own
# docstring is explicit that the call site for "a report landed" belongs to
# whoever owns that path (file_bridge.py's ``process_request``, not this
# file), and calling it speculatively from inside a GET handler here would
# make this file a second writer racing that eventual real one. So
# GET /api/conversations/<id> can legitimately show a dispatch stuck at
# "dispatched" even after the underlying task is long finished --
# GET /api/queue/<id> (this section's own endpoint, above) is what still
# tells the truth about that, read straight from the file bus every time,
# whether or not any conversation ever linked it.
_CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}\Z")  # \Z, not $: see _TASK_ID_RE


def _dataclass_or_none(value: Any) -> Any:
    """``dataclasses.asdict`` recurses into nested dataclasses on its own, but
    raises on ``None`` -- and conversation.py's reads legitimately return
    ``None`` for "no last turn yet" / "no report yet". One guarded call site
    instead of an ``if x is None else asdict(x)`` at every call site below."""
    from dataclasses import asdict, is_dataclass

    if value is None:
        return None
    return asdict(value) if is_dataclass(value) else value


def _conversation_view(conversation_id: str, limit: int = LOOP_MAX_LIMIT) -> dict[str, Any] | None:
    """Everything GET /api/conversations/<id> serves: the resumable summary
    (``ConversationStore.resume`` -- a narrative built only from closed
    vocabularies, per that module's own docstring, so it cannot claim more
    than the rows prove) plus the bounded raw turn list. ``None`` when the
    conversation has never had a turn appended -- ``append_turn`` is what
    creates the row; there is no separate "create conversation" write to be
    missing."""
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
    """The conversation timeline's OWN record for this dispatch, if any turn
    ever linked it (POST /api/queue's optional ``conversation_id``). ``None``
    when this id was never linked -- most tasks, including everything queued
    before this shipped, and every task queued without a conversation_id.

    NOT a live status feed -- see the section docstring above on why nothing
    here calls ``record_dispatch_event``. For the live ground truth, this
    response's sibling field (``task``, from :func:`_task_snapshot`) always
    reflects the file bus directly, whether or not a conversation link
    exists."""
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
        # Preflight carries no Authorization header by specification, so it is
        # answered unauthenticated. It reveals nothing: the response is three
        # fixed CORS headers and no body.
        self.send_response(204)
        self.end_headers()

    def _authorized(self) -> bool:
        """True unless this server was started with a shared token unmet.

        The token is set by :func:`run` and is EMPTY on a loopback bind, where
        there is nothing to authenticate against because no packet leaves the
        machine. It is non-empty only on the explicit non-loopback opt-in, which
        :func:`_resolve_bind` refuses to grant without one.
        """
        token = getattr(self.server, "daedalus_auth_token", "") or ""
        if not token:
            return True
        supplied = (self.headers.get("Authorization") or "").strip()
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        # Constant time: a token compared with == leaks its prefix to anyone
        # who can time the answer, and this one is the whole boundary.
        return hmac.compare_digest(supplied, token)

    def _deny(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", "Bearer")
        body = _json_safe({"ok": False, "error": "unauthorized: this server is "
                                                 "bound to a non-loopback "
                                                 "address and requires a "
                                                 "bearer token"})
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

    def do_PUT(self) -> None:
        if not self._authorized():
            self._deny()
            return
        try:
            self._handle_put()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self) -> None:
        if not self._authorized():
            self._deny()
            return
        try:
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
        """Server-Sent Events: cheap live push of bus state (queue/reports/watcher)
        so the cockpit stops polling the heavy dashboard. Reads only the file bus;
        self-recycles after 5 min (EventSource auto-reconnects)."""
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
                    emit("heartbeat", {"watcher_state": cur.get("watcher_state"),
                                       "in_flight": cur.get("in_flight")})
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
        """Server-Sent Events: one Ikarus chat turn, streamed token-by-token so
        the cockpit renders text as it is produced instead of blocking on the
        whole reply (the CLI cold start + full inference used to land at once).

        GET because EventSource only speaks GET. Same framing as /api/events,
        but this is a ONE-SHOT stream, not an open-ended feed, so it differs in
        one deliberate way: it sends ``Connection: close`` and drops the socket
        after ``final``. Without that the keep-alive socket lingers and the
        client hangs waiting for a turn that already ended.

        CLIENT CONTRACT: an EventSource AUTO-RECONNECTS when the server closes,
        which here would re-run the whole chat turn (and re-spend). The consumer
        MUST call ``es.close()`` when it receives ``final`` (or ``error``).

        Additive — POST /api/ikarus/ask is unchanged and still the right call
        for non-streaming clients.

        Two more additive, opt-in wires, both able to fail silently into the
        plain unwired stream rather than take the chat down:

          ``conversation_id`` (query param) is passed straight through to
          ``ikarus_os.ask_stream`` -- see daedalus/conversation.py. Omitted,
          this endpoint is byte-for-byte what it was before that module
          landed.

          A ``daedalus.progress`` unit is opened for this turn and the
          stream is tee'd through ``progress_sources.watch_stream`` so a
          SEPARATE caller can poll ``GET /api/progress/<id>`` and see
          claimed/generating/done for THIS generation while it runs -- the
          id rides on the ``start`` event as ``progress_unit_id``. Best-
          effort: if opening a unit fails, the stream runs exactly as it did
          before this existed.
        """
        project = (qs.get("project") or [""])[0]
        message = (qs.get("message") or [""])[0].strip()
        if not project or not message:
            self._send_json({"ok": False, "error": "project and message are required"}, status=400)
            return
        provider = (qs.get("provider") or [""])[0] or None
        model = (qs.get("model") or [""])[0] or None
        effort = (qs.get("effort") or [""])[0] or None
        conversation_id = (qs.get("conversation_id") or [""])[0] or None

        unit_id: str | None = None
        try:
            from . import progress as progress_mod

            unit_id = progress_mod.open_unit(
                source="web_api.ikarus_stream",
                detail={"project": project, "message_chars": len(message)})
        except Exception:
            unit_id = None  # progress tracking is best-effort; the chat is not

        self.close_connection = True  # one-shot: do not hold the socket open
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
            stream = ikarus_os.ask_stream(
                project, message, provider=provider, model=model, effort=effort,
                conversation_id=conversation_id,
            )
            if unit_id:
                from . import progress_sources

                # Transparent tee (see that function's own docstring): every
                # item passes through UNCHANGED, in the same order; recording
                # is a side effect only, and a bug in it cannot alter what
                # this loop sees, only what a separate GET /api/progress/<id>
                # caller can observe about it meanwhile.
                stream = progress_sources.watch_stream(
                    unit_id, stream, source="web_api.ikarus_stream")
            for event, payload in stream:
                if event == "start" and unit_id:
                    payload = {**payload, "progress_unit_id": unit_id}
                emit(event, payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return  # client navigated away mid-stream
        except Exception as exc:
            # Fail closed into a well-formed chat envelope: the UI shows a reply,
            # never a broken stream.
            try:
                emit("final", core.envelope(project, intent="error",
                                            assistant=f"I hit a snag: {exc}",
                                            provider_used="deterministic"))
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    def _handle_task_events(self, task_id: str) -> None:
        """Server-Sent Events: progress of ONE task, addressed by the id
        POST /api/queue handed back. Built from the same file-bridge bus
        GET /api/queue/<id> reads (outbox/heartbeat/inbox) -- this is that
        same snapshot, pushed on a timer instead of pulled once.

        ONE-SHOT, like /api/ikarus/stream: closes once the task reaches a
        terminal state (a report exists, or the id is archived with no
        report) or after ``_TASK_EVENTS_MAX_S``, and says which in the
        'final' event's own fields. An EventSource client MUST call
        ``es.close()`` on 'final' -- auto-reconnect would just reopen onto an
        already-finished task and replay the same 'final' forever.

        A fresh id that is not found YET (the enqueue -> first-poll race) is
        tolerated for ``_TASK_EVENTS_GRACE_S`` before being reported as
        final/not-found -- see ``_task_snapshot``'s docstring on why "not
        found" cannot be told apart from "wrong id" by a filesystem check
        alone.
        """
        if not _TASK_ID_RE.match(task_id):
            self._send_json({"ok": False, "error": "invalid task id"}, status=400)
            return
        self.close_connection = True  # one-shot: do not hold the socket open
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
                    emit("final", {**snap, "timed_out": True,
                                   "applied_reason": snap["applied_reason"] +
                                   f" (subscription open >{_TASK_EVENTS_MAX_S:.0f}s; "
                                   "poll GET /api/queue/<id> to keep checking)"})
                    return
                stalled = bool(snap.get("stalled"))
                if (snap["state"] != last_state or stalled != last_stalled
                        or now - last_emit >= _TASK_EVENTS_PERIOD_S):
                    emit("hello" if last_state is None else "progress", snap)
                    last_emit = now
                last_state = snap["state"]
                last_stalled = stalled
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return  # client navigated away mid-stream
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
            # "May this system promote anything right now, and why not?"
            # Byte-identical to dashboard["governance"] -- same function, no
            # second opinion. tests/test_ui_governance.py pins that equality.
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
            self._send_json(core.envelope(None, **runtime_registry.all_status()))
        elif path == "/api/accelerators/status":
            deep = (qs.get("deep") or ["0"])[0] in ("1", "true", "yes")
            probe_remote = (
                (qs.get("probe_remote") or ["0"])[0] in ("1", "true", "yes")
            )
            self._send_json(
                core.envelope(
                    None,
                    accelerators=accelerators.accelerator_status(
                        deep=deep,
                        probe_remote=probe_remote,
                    ),
                )
            )
        elif path == "/api/env/status":
            self._send_json(core.envelope(None, env=env_status()))
        elif path == "/api/capabilities":
            self._send_json(hierarchy.capabilities())
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
            # Reuse the same center/ignore-scoped index as /api/structure.
            topo = spectral_partition(repo_root, idx=_structure_index(project, refresh))
            self._send_json(core.envelope(project, topology=topo))
        elif path == "/api/context/plan":
            project = (qs.get("project") or [None])[0]
            objective = (qs.get("q") or [""])[0].strip()
            if not project:
                self._send_json(
                    {"ok": False, "error": "project is required"},
                    status=400,
                )
                return
            if not objective:
                self._send_json(
                    {"ok": False, "error": "q is required"},
                    status=400,
                )
                return
            if len(objective) > 4000:
                self._send_json(
                    {"ok": False, "error": "q must be at most 4000 characters"},
                    status=400,
                )
                return
            try:
                max_tokens = int((qs.get("max_tokens") or ["8000"])[0])
            except ValueError:
                self._send_json(
                    {"ok": False, "error": "max_tokens must be an integer"},
                    status=400,
                )
                return
            if not 1 <= max_tokens <= 200_000:
                self._send_json(
                    {
                        "ok": False,
                        "error": "max_tokens must be between 1 and 200000",
                    },
                    status=400,
                )
                return
            refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
            use_latent = (qs.get("latent") or ["0"])[0] in ("1", "true", "yes")
            use_cochange = (
                (qs.get("cochange") or ["0"])[0] in ("1", "true", "yes")
            )
            repo_root = resolve_repo_root(None, project)
            result = plan_context(
                repo_root,
                objective,
                idx=_structure_index(project, refresh),
                project=project,
                token_budget=max_tokens,
                use_latent=use_latent,
                temporal_pairs=(
                    co_change_pairs(repo_root) if use_cochange else ()
                ),
            )
            self._send_json(
                core.envelope(project, context_plan=result.to_dict())
            )
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
                self._send_json(
                    {"ok": False, "error": "only cosine search is supported"},
                    status=400,
                )
                return
            try:
                from .memory import VECTOR_DB_PATH
                from .memory.embeddings import EventVectorStore

                store = EventVectorStore(VECTOR_DB_PATH)
                try:
                    results = store.search(query, limit=limit, metric=metric)
                    hits = [
                        {"event": ev.to_dict(), "score": round(score, 4)}
                        for ev, score in results
                    ]
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
            except ValueError as exc:  # unknown / malformed project
                self._send_json({"ok": False, "error": str(exc)}, status=400)
        elif path == "/api/loop/attempts":
            try:
                limit = _loop_limit(qs, 20)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            from .spine import picker as _picker

            kind = (qs.get("kind") or [_picker.ATTEMPT_INTENT_KIND])[0]
            # "every kind" has to be asked for by name; defaulting to it would
            # widen what this endpoint returns every time a new intent kind is
            # recorded anywhere in the system.
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
            # The health surface has fourteen probes and a five-state vocabulary
            # that deliberately cannot collapse into green, plus a MEASURED /
            # INHERITED / ASSUMED tag on every fact. None of it was reachable
            # from the UI, so the browser was re-deriving a weaker version of
            # the same judgement from other payloads. One endpoint, and the
            # provenance travels with the verdict.
            #
            # `deep` and `probe_remote` are OFF unless asked for: the first
            # calls the latent route (~7s cold) and the second embeds against a
            # host that is not this machine. A browser tab must not be able to
            # start either by accident, and the response says which were skipped
            # rather than letting `present` read as `working`.
            try:
                from . import health as _health

                deep = (qs.get("deep") or ["0"])[0] in ("1", "true", "yes")
                remote = (qs.get("probe_remote") or ["0"])[0] in ("1", "true", "yes")
                only = _clip((qs.get("only") or [""])[0], 100) or None
                payload = _health.to_payload(
                    _health.assess(only, deep=deep, probe_remote=remote))
                payload["asked"] = {"deep": deep, "probe_remote": remote,
                                    "only": only}
                self._send_json(core.envelope(None, health=payload))
            except Exception as exc:                 # noqa: BLE001
                # A health surface that 500s tells the operator nothing about
                # the system and everything about itself -- so say which.
                self._send_json(
                    {"ok": False,
                     "error": f"the health surface itself failed: "
                              f"{type(exc).__name__}: {exc}",
                     "health": None}, status=500)
        elif path == "/api/drafts":
            rows = drafts.list_drafts()
            pending = [d for d in rows if d.get("status") == "pending"]
            self._send_json(core.envelope(None, drafts=rows, pending_count=len(pending)))
        elif path.startswith("/api/drafts/"):
            draft_id = unquote(path.split("/", 3)[3])
            d = drafts.get_draft(draft_id)
            self._send_json(core.envelope(None, draft=d) if d else
                            {"ok": False, "error": f"unknown draft {draft_id}"}, status=200 if d else 404)
        elif path.startswith("/api/queue/"):
            # /api/queue/<id>              GET  -> one snapshot (see _task_snapshot)
            # /api/queue/<id>/artifacts    GET  -> what a finished run produced
            # /api/queue/<id>/events       GET  -> SSE progress, one-shot
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
                    # Read-only, additive: what a conversation turn recorded
                    # about this dispatch, if any ever linked it. None is the
                    # normal case for anything queued without a
                    # conversation_id. See the "conversation + progress
                    # seam" section for why this can lag the `task` block
                    # above, which stays the live ground truth regardless.
                    snap["conversation_dispatch"] = _dispatch_status_view(task_id)
                self._send_json(
                    core.envelope(None, task=snap) if snap["found"] else
                    {"ok": False, "error": f"unknown task id {task_id}", "task": snap},
                    status=200 if snap["found"] else 404)
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
            # GET /api/conversations/<id>[?limit=] -> resumable summary +
            # bounded turn list (see _conversation_view).
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
                self._send_json(
                    {"ok": False,
                     "error": f"the conversation store failed: {type(exc).__name__}: {exc}"},
                    status=500)
                return
            self._send_json(
                core.envelope(None, conversation=view) if view is not None else
                {"ok": False, "error": f"unknown conversation id {conversation_id}"},
                status=200 if view is not None else 404)
        elif path.startswith("/api/progress/"):
            # GET /api/progress/<unit_id> -> daedalus.progress_sources
            # .snapshot_any: this endpoint's own event log first, then the
            # spine ledger, then the file bridge -- whichever recognises the
            # id. Always 200: `found` inside the payload carries the honest
            # "nobody has heard of this id" answer, matching how
            # snapshot_any itself is designed to be read (see its docstring).
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
                self._send_json(
                    {"ok": False,
                     "error": f"the progress source failed: {type(exc).__name__}: {exc}"},
                    status=500)
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
            # `queued` is a filesystem path -- an implementation detail. `id`
            # is that same request's filename stem: the exact key file_bridge
            # itself uses to find the eventual report, and the only id
            # GET /api/queue/<id> (and its /artifacts, /events siblings)
            # accept. Purely additive: `queued` is unchanged, so existing
            # callers see no difference.
            task_id = Path(str(result.get("queued") or "")).stem or None
            result["id"] = task_id
            # Optional: attribute this dispatch to the conversation turn that
            # proposed it (daedalus.conversation.ConversationStore
            # .link_dispatch). Additive and best-effort, same fail-open
            # posture as ikarus_os._persist_turn: a caller that never sends
            # conversation_id sees nothing here, and a link failure (unknown
            # conversation, unknown turn_id) is REPORTED on the response, not
            # allowed to fail an enqueue that has already, actually happened.
            conversation_id = body.get("conversation_id")
            if task_id and conversation_id:
                turn_id = body.get("turn_id")
                try:
                    from . import conversation as conv

                    link = conv.default_store().link_dispatch(
                        str(conversation_id), task_id,
                        turn_id=(int(turn_id) if turn_id is not None else None),
                        kind="queue_task")
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
            # Mint only -- see daedalus.conversation.new_conversation_id: pure
            # id generation, no store write. The row is created lazily by the
            # FIRST append_turn (via POST /api/ikarus/ask's conversation_id),
            # so this never leaves a conversation-shaped id with no turns
            # behind it that GET /api/conversations/<id> would 404 on forever.
            from . import conversation as conv

            self._send_json(core.envelope(None, conversation_id=conv.new_conversation_id()))
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
            self._send_json(ikarus_os.ask(
                project, message,
                provider=str(provider) if provider else None,
                model=str(model) if model else None,
                effort=str(effort) if effort else None,
                conversation_id=str(conversation_id) if conversation_id else None,
            ))
            return
        if path.startswith("/api/drafts/") and (path.endswith("/apply") or path.endswith("/dismiss")):
            parts = [unquote(p) for p in path.strip("/").split("/")]
            draft_id, verb = parts[2], parts[3]
            if verb == "apply":
                packet = drafts.apply_payload(draft_id)
                self._send_json(core.envelope(None, applied=packet) if packet else
                                {"ok": False, "error": f"unknown draft {draft_id}"},
                                status=200 if packet else 404)
            else:
                d = drafts.set_status(draft_id, "dismissed")
                self._send_json(core.envelope(None, draft=d) if d else
                                {"ok": False, "error": f"unknown draft {draft_id}"},
                                status=200 if d else 404)
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
    """``run()`` was asked to serve an address that is not this machine.

    Raised INSTEAD of starting the server. Not a warning, and deliberately not a
    silent downgrade to loopback either: the operator asked for something and
    has to be told it was refused, or they will believe a phone on the LAN can
    reach a cockpit that is not there.
    """


# The opt-in, spelled out. ``--host`` alone is NOT the opt-in: it reads as a
# routine bind parameter, and the whole failure mode here is that a flag which
# looks routine turns an unauthenticated local tool into a network service.
ALLOW_REMOTE_ENV = "DAEDALUS_WEB_ALLOW_REMOTE_CLIENTS"
AUTH_TOKEN_ENV = "DAEDALUS_WEB_TOKEN"
MIN_AUTH_TOKEN_CHARS = 32


def _refusal(host: str, why: str, remedy: str) -> str:
    return (
        f"REFUSED: daedalus web will not serve {host!r}.\n\n"
        f"{why}\n\n"
        f"This server has NO AUTHENTICATION on its loopback path, because on "
        f"loopback the operating system is the boundary. Every endpoint is "
        f"reachable by anyone who can reach the port: the spine ledger (what "
        f"the loop has attempted), the picker queue (what it is working on), "
        f"PUT endpoints that rewrite agent roles, and POST endpoints that "
        f"queue work and invoke models -- that last one is remote SPEND, not "
        f"just remote read. ADR-002 rejected a subsystem for being exactly "
        f"this shape: an independent, unauthenticated network server.\n\n"
        f"The server was NOT started, and it was NOT quietly downgraded to "
        f"loopback.\n\n{remedy}"
    )


def _resolve_bind(host: str, allow_remote_clients: bool) -> str:
    """Decide whether this bind may happen, and with what authentication.

    Returns the shared token every request must then carry -- ``""`` on a
    loopback bind, where there is nothing to authenticate against because no
    packet leaves the machine. Raises :class:`NonLoopbackBindRefused` otherwise.

    THE PREDICATE IS NOT REDEFINED HERE. ``sensitivity.lane_for_host`` is the
    single implementation of "is this host this machine"; the repo held five
    divergent copies of that question inside one day and they disagreed about
    ``[::1]``. A sixth one in the web server -- the one place where being wrong
    means an open port rather than a slightly wrong lane -- would be the worst
    possible place to keep the habit alive.
    """
    # is_loopback_host, NOT lane_for_host. Both live in sensitivity.py and they
    # answered the same thing until DAEDALUS_TRUSTED_HOSTS existed: an operator
    # can now DECLARE a private-tunnel host trusted so repository content may be
    # sent there for inference. That is consent about egress. It is not a claim
    # that packets to that address stay on this machine -- and this function is
    # asking exactly that, because returning "" here yields an empty auth token
    # and _authorized() treats empty as always-authorized.
    #
    # Reading the egress answer here would have meant: declaring a bench for
    # INFERENCE silently publishes the control plane -- spine ledger, the PUTs
    # that rewrite agent roles, the POSTs that queue work and invoke models --
    # unauthenticated to everything that can reach that tailnet. Found in review
    # after the widening shipped, with the declaration already live in .env.
    from .sensitivity import is_loopback_host

    host = str(host or "").strip()
    if is_loopback_host(host):
        return ""

    if not (allow_remote_clients
            or os.environ.get(ALLOW_REMOTE_ENV, "").strip().lower()
            in ("1", "true", "yes")):
        named = repr(host) if host else "an empty host (every interface)"
        raise NonLoopbackBindRefused(_refusal(
            host or "",
            f"{named} is not this machine. sensitivity.lane_for_host reports "
            f"it as UNTRUSTED, which in this project means 'bytes leave this "
            f"host'.",
            f"  * to serve this machine only:  --host 127.0.0.1  (the default)\n"
            f"  * 'localhost' is refused ON PURPOSE: it is a NAME, and a name "
            f"that resolves to loopback when it is checked can resolve "
            f"elsewhere when it is connected. Use the numeric literal.\n"
            f"  * to genuinely serve other machines, opt in explicitly AND "
            f"authenticate:\n"
            f"        set {AUTH_TOKEN_ENV} to a secret of at least "
            f"{MIN_AUTH_TOKEN_CHARS} characters\n"
            f"        pass --allow-remote-clients (or {ALLOW_REMOTE_ENV}=1)\n"
            f"    every request must then carry "
            f"'Authorization: Bearer <token>'."))

    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    if len(token) < MIN_AUTH_TOKEN_CHARS:
        state = ("is not set" if not token
                 else f"is only {len(token)} characters long")
        raise NonLoopbackBindRefused(_refusal(
            host,
            f"--allow-remote-clients was given, but {AUTH_TOKEN_ENV} {state}. "
            f"An opt-in is a decision to expose this, not a decision to expose "
            f"it to ANYONE -- so the escape hatch carries authentication with "
            f"it and cannot be opened without.",
            f"  * set {AUTH_TOKEN_ENV} to at least {MIN_AUTH_TOKEN_CHARS} "
            f"characters and try again."))
    return token


def run(host: str = "127.0.0.1", port: int = 8765, *,
        allow_remote_clients: bool = False) -> None:
    load_env()  # before the guard: the token may legitimately live in .env
    token = _resolve_bind(host, allow_remote_clients)
    httpd = ThreadingHTTPServer((host, port), DaedalusHandler)
    # Read per request by DaedalusHandler._authorized. Empty on the loopback
    # path, which is every path anybody normally takes.
    httpd.daedalus_auth_token = token
    if token:
        print(f"!! Daedalus Agent OS is bound to {host}, which is NOT this "
              f"machine. Every request requires 'Authorization: Bearer "
              f"<{AUTH_TOKEN_ENV}>'. Unauthenticated requests get 401.",
              flush=True)
    print(f"Daedalus Agent OS listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> None:
    import sys

    parser = argparse.ArgumentParser(description="Run the local Daedalus Agent OS web API.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to serve. Anything that is not this "
                             "machine is REFUSED unless "
                             "--allow-remote-clients is also given.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-remote-clients", action="store_true",
                        help=f"serve machines other than this one. Requires "
                             f"{AUTH_TOKEN_ENV} (>= {MIN_AUTH_TOKEN_CHARS} "
                             f"chars); every request then needs an "
                             f"Authorization: Bearer header.")
    args = parser.parse_args(argv)
    try:
        run(args.host, args.port,
            allow_remote_clients=args.allow_remote_clients)
    except NonLoopbackBindRefused as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()

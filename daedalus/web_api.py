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

from .interfaces.http import effects as http_effects
from .interfaces.http import read as http_read
from .interfaces.http import server as http_server
from .interfaces.http import sse as http_sse

from .kairos import drafts
from . import accelerators, core
from .orchestration import agents_registry, categories, control_plane, conversation_requests, editor_context, hierarchy, ikarus_chat, runtime_registry
from .bootstrap_prompt import claude_bootstrap_prompt
from .orchestration.context_plan import plan_context
from .env import env_status, load_env
from .projects import (
    ProjectRegistrationError,
    ProjectRegistryUnavailable,
    ProjectRowNotFound,
    ProjectRowUpdateError,
    list_projects,
    register_project,
    resolve_repo_root,
)
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
        repo_root = str(data.get("repo_root") or "")
        try:
            reachable = bool(repo_root) and Path(repo_root).is_dir()
        except OSError:
            reachable = False
        rows.append({
            "name": name,
            "repo_root": repo_root,
            "team": data.get("team") or {},
            # Registered is not the same fact as present on THIS machine.
            # Additive so older clients ignore it and newer clients can avoid
            # silently selecting a checkout that cannot be read.
            "reachable": reachable,
        })
    return core.envelope(None, projects=rows)


def _provider_status() -> dict[str, Any]:
    return core.envelope(None, providers=core.provider_health(None).get("providers", []))


def _host_capabilities(
        host_mode: str = "browser", desktop: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Measured host affordances, separate from workflow authority.

    The plain web server cannot start or claim a desktop editor.  The managed
    desktop handler passes its observational service snapshot here; no probe is
    inferred from whether an iframe happened to render.
    """
    ide = ((desktop or {}).get("services") or {}).get("ide") or {}
    managed = host_mode == "desktop"
    return {
        "host_mode": host_mode,
        "can_manage_openvscode": bool(managed and ide.get("available") is True),
        "can_open_external_editor": bool(
            managed and ide.get("reachable") is True and ide.get("ui_url")),
        # Navigation requires a live, nonce-bound adapter session.  Supporting
        # the route is not itself evidence that such a session exists.
        "can_send_editor_commands": False,
        "editor_commands_require_session": True,
        "measured_at": core.now_iso(),
    }


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
#       - the canonical queue currently refuses a direct claude lane before
#         invocation because its caller does not yet own the required broker
#         authority. Historical direct-lane reports carry no verify/rollback
#         signal and therefore remain unknown rather than assumed true.
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
        status = str(a.get("status") or ar_report.get("status") or "").strip()
        summary = str(ar_report.get("summary") or a.get("reason") or "").strip()
        if status == "gated_held":
            held = "candidate passed its gate and is held; not applied to the primary checkout"
            summary = f"{held}: {summary}" if summary else held
        if status or summary:
            return status or None, summary
    return None, str(report.get("error") or "")


def _derive_applied(report: dict[str, Any]) -> tuple[bool | None, str]:
    """Whether the work this report describes actually landed on disk, and
    the evidence for saying so. Returns ``None`` (not ``True``) whenever the
    report does not carry enough to tell -- see the section docstring above
    for why the three lanes need three different readings."""
    applied, reason = file_bridge.report_application_truth(report)
    return applied, _clip(reason, LOOP_VALUE_CHARS)


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
            "requested_lane": None, "actual_providers": [],
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
        requested_lane = report.get("requested_lane") or request.get("lane")
        actual_providers = (
            list(report.get("actual_providers") or [])
            if isinstance(report.get("actual_providers"), list) else []
        )
        return {
            "id": task_id, "found": True,
            "state": bridge_status or ("done" if prog.terminal else "unknown"),
            "source": "inbox_report",
            "observed_at": progress_dict["observed_at"], "age_s": progress_dict["age_s"],
            "lane": report.get("lane") or requested_lane,
            "requested_lane": requested_lane,
            "actual_providers": actual_providers,
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
            "requested_lane": None, "actual_providers": [],
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
        "requested_lane": payload.get("lane"), "actual_providers": [],
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
# ``daedalus/orchestration/conversation.py`` gives the Ikarus assistant seam (ask/ask_stream)
# a durable multi-turn identity: a conversation_id, an append-only turn log,
# and dispatch attribution (a turn caused work; that work is a caller-supplied
# ref, e.g. a file-bridge task id, that a later report can be found under).
# It owns no store of its own: it is a facade, and every row it writes is a
# typed intent (``conversation.turn`` / ``conversation.dispatch`` /
# ``conversation.dispatch.report``) on the single canonical event spine,
# ``daedalus/spine/ledger.py``. Nothing in this file may read an orchestration
# decision back out of it -- the live truth for a queued task is the file bus
# (``_task_snapshot``), and the conversation rows are attribution and narrative.
# ``daedalus/progress.py`` + ``progress_sources.py`` give a single unit of work
# (a chat generation, an offload call, a spine attempt) an honest, closed-
# vocabulary event trail -- queued/claimed/generating/.../done, never a
# fabricated percentage, never "running" read as "progressing".
#
# What is wired below, and what remains owned by the report path: this file
# starts conversations, appends turns via ikarus_os's opt-in
# ``conversation_id`` kwarg, links a queued task to the turn that proposed it,
# and reads all of that back. It does NOT project outcomes from a GET handler.
# ``file_bridge.process_request`` owns that write: after the fixed, terminal
# report is durable, it calls ``conversation.record_dispatch_event`` with the
# queue request key as both dispatch ref and stable source-event identity. The
# canonical spine's partial unique index makes crash/restart replay return the
# same fact rather than append a duplicate; no browser state or second journal
# becomes authoritative. A projection failure does not retract or relabel the
# terminal bridge report and never re-runs the provider. On the normal report
# path it leaves only cleanup unfinalized so the watcher retries idempotently;
# the narrow post-link reconciliation below returns the same archived request
# to the canonical outbox for projection-only retry when necessary, and reports
# pending/error separately without rewriting a successful link as false. Thus
# this read can briefly show ``dispatched`` while projection is pending, while
# GET /api/queue/<id> remains the live task truth read directly from the file
# bus in every case.
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
    from .orchestration import conversation as conv

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


def _conversation_list_view(project: str, limit: int = 20) -> list[dict[str, Any]]:
    """Everything GET /api/conversations?project= serves: this project's
    conversations from the canonical spine, newest first, every free-text
    field clipped by the same bound the turn view uses. Read-only; minting a
    conversation stays on the POST route and creation stays on the first
    turn."""
    from .orchestration import conversation as conv

    rows = conv.default_store().list_conversations(project, limit=limit)
    for row in rows:
        row["first_message"] = _clip(row.get("first_message") or "")
        row["last_message"] = _clip(row.get("last_message") or "")
    return rows


def _dispatch_status_view(task_id: str) -> dict[str, Any] | None:
    """The conversation timeline's OWN record for this dispatch, if any turn
    ever linked it (POST /api/queue's optional ``conversation_id``). ``None``
    when this id was never linked -- most tasks, including everything queued
    before this shipped, and every task queued without a conversation_id.

    NOT a live status feed -- see the section comment above: terminal outcomes
    are projected exactly once by ``file_bridge.process_request``, never by
    this read handler. For the live ground truth, this response's sibling field
    (``task``, from :func:`_task_snapshot`) always reflects the file bus
    directly, whether or not a conversation link exists and even while a
    conversation projection retry is pending."""
    from .orchestration import conversation as conv

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
    """Compatibility seam for callers patching the historical body reader."""

    return http_effects.read_body(handler)




class DaedalusHandler(BaseHTTPRequestHandler):
    server_version = "DaedalusAgentOS/0.1"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Daedalus-Editor-Token, Last-Event-ID",
        )
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

    def _bind_decision(self):
        """The web.authenticated_bind decision this request just passed."""
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

            begin_effect(
                "web.mutations_put",
                REGISTRY_BY_ID["web.mutations_put"].effects,
                (self._bind_decision(),),
            )
            self._handle_put()
        except ProjectRowNotFound as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=404)
        except ProjectRowUpdateError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except ProjectRegistryUnavailable as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=503)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self) -> None:
        if not self._authorized():
            self._deny()
            return
        try:
            from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

            begin_effect(
                "web.mutations",
                REGISTRY_BY_ID["web.mutations"].effects,
                (self._bind_decision(),),
            )
            self._handle_post()
        except editor_context.UnknownEditorSession as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=404)
        except editor_context.EditorContextError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
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
        return http_sse.handle_events(self, project, stream_state=stream_state)

    def _handle_ikarus_stream(self, qs: dict) -> None:
        return http_sse.handle_ikarus_stream(self, qs)

    def _handle_task_events(self, task_id: str) -> None:
        return http_sse.handle_task_events(
            self,
            task_id,
            task_snapshot=_task_snapshot,
            task_id_re=_TASK_ID_RE,
            terminal_sources=_TASK_TERMINAL_SOURCES,
        )

    def _handle_conversation_request_events(
            self, conversation_id: str, request_id: int, qs: dict) -> None:
        return http_sse.handle_conversation_request_events(
            self, conversation_id, request_id, qs)

    def _handle_get(self) -> None:
        return http_read.handle_get(
            self,
            ports=http_read.ReadPorts(
                clip=_clip,
                conversation_view=_conversation_view,
                conversation_list_view=_conversation_list_view,
                dispatch_status_view=_dispatch_status_view,
                host_capabilities=_host_capabilities,
                loop_architecture=_loop_architecture,
                loop_attempts=_loop_attempts,
                loop_limit=_loop_limit,
                loop_queue=_loop_queue,
                project_list=_project_list,
                provider_status=_provider_status,
                structure_index=_structure_index,
                task_artifacts=_task_artifacts,
                task_snapshot=_task_snapshot,
                resolve_repo_root=resolve_repo_root,
                conversation_id_re=_CONVERSATION_ID_RE,
                task_id_re=_TASK_ID_RE,
                loop_max_limit=LOOP_MAX_LIMIT,
            ),
        )

    def _handle_put(self) -> None:
        return http_effects.handle_put(
            self,
            ports=http_effects.EffectPorts(
                read_body=_read_body,
                structure_index=_structure_index,
                resolve_repo_root=resolve_repo_root,
                register_project=register_project,
            ),
        )

    def _handle_post(self) -> None:
        return http_effects.handle_post(
            self,
            ports=http_effects.EffectPorts(
                read_body=_read_body,
                structure_index=_structure_index,
                resolve_repo_root=resolve_repo_root,
                register_project=register_project,
            ),
        )

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("DAEDALUS_WEB_DEBUG"):
            super().log_message(fmt, *args)


NonLoopbackBindRefused = http_server.NonLoopbackBindRefused
ALLOW_REMOTE_ENV = http_server.ALLOW_REMOTE_ENV
AUTH_TOKEN_ENV = http_server.AUTH_TOKEN_ENV
DESKTOP_STARTUP_NONCE_ENV = http_server.DESKTOP_STARTUP_NONCE_ENV
MIN_AUTH_TOKEN_CHARS = http_server.MIN_AUTH_TOKEN_CHARS


def _desktop_startup_nonce() -> str:
    """Compatibility seam for callers of the historical nonce validator."""

    return http_server.desktop_startup_nonce()


def _refusal(host: str, why: str, remedy: str) -> str:
    return http_server.refusal(host, why, remedy)


def _resolve_bind(host: str, allow_remote_clients: bool) -> str:
    """Compatibility seam for the canonical HTTP bind admission owner."""

    return http_server.resolve_bind(host, allow_remote_clients)


def run(host: str = "127.0.0.1", port: int = 8765, *,
        allow_remote_clients: bool = False) -> None:
    load_env()  # before the guard: the token may legitimately live in .env
    token = _resolve_bind(host, allow_remote_clients)
    httpd = ThreadingHTTPServer((host, port), DaedalusHandler)
    # Read per request by DaedalusHandler._authorized. Empty on the loopback
    # path, which is every path anybody normally takes.
    httpd.daedalus_auth_token = token
    httpd.daedalus_desktop_startup_nonce = _desktop_startup_nonce()
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
        from daedalus.spine.effect_boundary import (
            REGISTRY_BY_ID,
            GuardDecision,
            begin_effect,
        )

        token = _resolve_bind(args.host, args.allow_remote_clients)
        begin_effect(
            "cli.web_api",
            REGISTRY_BY_ID["cli.web_api"].effects,
            (
                GuardDecision(
                    "web.authenticated_bind",
                    True,
                    f"_resolve_bind accepted host={args.host!r} "
                    + ("(loopback, no token)" if not token
                       else "(non-loopback opt-in, token set)"),
                ),
            ),
        )
        run(args.host, args.port,
            allow_remote_clients=args.allow_remote_clients)
    except NonLoopbackBindRefused as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()

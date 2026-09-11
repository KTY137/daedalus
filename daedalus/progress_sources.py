"""progress_sources.py -- adapters from signals this repo ALREADY produces
onto :mod:`daedalus.progress`'s event vocabulary.

Nothing in this file is a second source of truth. Every function here either
(a) turns bytes or a return value a caller already holds into
:class:`~daedalus.progress.ProgressEvent` records, or (b) performs a
READ-ONLY poll of a store this repo already keeps durably. This module never
edits, wraps the internals of, or monkeypatches the modules it reads --
:mod:`daedalus.orchestration.ikarus.shell`, :mod:`daedalus.offload`, :mod:`daedalus.spine.attempt`
and :mod:`daedalus.spine.ledger` are all owned elsewhere and are used here
exactly as their own public functions already behave.

SIGNALS USED, AND WHY EACH IS TRUSTED
--------------------------------------------------------------------------
* ``daedalus.orchestration.ikarus.shell.ask_stream`` / ``_claude_stream``: every non-empty
  "delta" is a byte physically read from a live child process's stdout (see
  ``_claude_stream``'s ``for line in proc.stdout:`` loop) -- it cannot be
  produced by a hung or dead process. Trusted for GENERATING.
* ``daedalus.offload.offload()``'s ``result["wrote"]``: a before/after
  content-hash diff of the real filesystem
  (``offload._repo_snapshot``/``_scoped_snapshot``, SHA-256 per file).
  Trusted for DISK_CHANGED/NO_CHANGE, and the ONLY thing this module accepts
  for that -- ``result["report"]["files_changed"]`` (the worker's own claim)
  is never read by any function below, on purpose.
* ``daedalus.spine.attempt.AttemptResult.artifact``: a ``PatchArtifact``
  captured by a hardened ``git diff`` inside an isolated worktree, and
  ``attempt.py`` structurally cannot apply it to the primary checkout (three
  enforced properties -- see that module's docstring). Trusted for
  PATCH_PRODUCED, and ONLY EVER that: this file has no code path that turns
  an AttemptResult into DISK_CHANGED.
* ``daedalus.spine.ledger.SpineLedger``: an intent is committed BEFORE the
  effect it describes, so an open (unresolved) intent read via
  ``open_intents()`` is real, durable, cross-process proof that a unit was
  claimed, with a true age (``created_ts``) rather than a guess. Opened
  ``read_only=True`` everywhere in this file, matching ``daedalus.health``'s
  own discipline: asking the question must never be the thing that creates
  the file being asked about.
* ``daedalus.file_bridge.heartbeat_status()`` / the outbox-inbox-archive
  filenames: an already-measured busy/wedged classification and an
  already-durable queued/reported/archived lifecycle, reused rather than
  re-derived.

SIGNALS REFUSED, ON PURPOSE
--------------------------------------------------------------------------
* ``report["files_changed"]`` or any other field a worker/model
  SELF-REPORTS about what it did. This is the exact fake-offload failure
  named in this project's own history (a model narrated an edit it never
  made, and a harness read the narration as a finished report) -- see
  ``daedalus/orchestration/verifier.py``'s comment on that same field. No function in this
  file reads it, and :func:`daedalus.progress.record_disk_change` refuses a
  ``basis`` that is not a mechanical diff even if a caller tried to smuggle
  one through.
* "the subprocess/thread is still alive" as evidence of PROGRESS. Recorded
  as HEARTBEAT, a deliberately weaker, separate fact: proof against a crash,
  never proof of forward motion. A hung model and a working one are
  identical on this signal alone -- see :func:`track_call`.
* A cached verdict re-served as current truth. Every snapshot function here
  stamps ``observed_at``/recomputes every age at call time; nothing in this
  file memoises a result across calls (the direct fix for the bench health
  check that was true when read and false a second later).

WHAT THIS FILE DOES NOT COVER (a stated gap, not a silent one): plain
``offload()``/``KairosScheduler.dispatch()`` calls made OUTSIDE
``daedalus.spine.attempt`` are single blocking calls with no internal
progress hook, and this module does not edit ``offload.py`` to add one. Wrap
such a call with :func:`track_call` and you get CLAIMED, an optional
HEARTBEAT trail proving the calling thread is alive, and then everything
``record_offload_result`` can prove once the call returns -- and nothing
finer-grained in between, because nothing finer-grained is observable there.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from . import progress as P
from .health import INHERITED, inherited, measured

__all__ = [
    "watch_stream", "record_offload_result", "record_attempt_result", "track_call",
    "snapshot_from_ledger", "open_attempts", "snapshot_from_bridge", "snapshot_any",
]


# --------------------------------------------------------------------------- #
# 1 -- the chat stream: daedalus.orchestration.ikarus.shell.ask_stream / _claude_stream         #
# --------------------------------------------------------------------------- #
def watch_stream(unit_id: str, event_payload_iter: Iterable[tuple[str, Any]], *,
                 source: str = "ikarus_os.ask_stream",
                 log: "P.ProgressLog | None" = None) -> Iterator[tuple[str, Any]]:
    """Wrap the ``(event, payload)`` iterator :func:`daedalus.orchestration.ikarus.shell.ask_stream`
    yields. A transparent tee: every item is yielded UNCHANGED, in the same
    order, with recording as a side effect only -- a caller drops this around
    an existing ``for event, payload in ask_stream(...):`` loop with no other
    change.

    EVENT MAPPING, AND WHY:

      ("start", {...})    -> CLAIMED. ``ask_stream`` yields this immediately
                             after choosing a runtime, BEFORE the child
                             process is confirmed to have produced anything
                             -- it is a dispatch fact, not evidence of
                             generation. Conflating the two ("running" read
                             as "progressing") is exactly what this module
                             exists to avoid.
      ("delta", {"text"}) -> GENERATING, iff the text is non-empty. Each one
                             is a byte physically read from the child's
                             stdout (see ``_claude_stream``) -- MEASURED, not
                             inferred.
      ("final", envelope)  -> DONE. ``succeeded`` is True whenever a reply
                             string exists. ``applied`` is always False: a
                             chat reply is text, and an ``enqueue`` intent
                             that may ride inside the envelope's ``action``
                             field is a PROPOSAL gated on a confirmation that
                             has not happened yet (see
                             ``daedalus.orchestration.ikarus.shell._enqueue``) -- a caller that
                             later confirms it should open a SEPARATE unit
                             for that effect and record its own
                             DISK_CHANGED/NO_CHANGE there.

    LIMITATION, STATED PLAINLY: this proves TEXT generation, never TOOL
    invocation. ``_claude_stream`` filters the Claude CLI's stream-json
    frames down to ``content_block_delta``/``text_delta`` only (verified
    against CLI 2.1.201); a turn that calls a tool with no interstitial text
    yields zero deltas here and is, on this signal alone, indistinguishable
    from a stalled process. Call :func:`daedalus.progress.snapshot` on this
    unit_id and read ``.stalled`` to see that ambiguity surfaced rather than
    hidden -- this module does not invent a tool-call signal ``_claude_stream``
    does not expose.
    """
    log = log or P.default_log()
    deltas_seen = 0
    for event, payload in event_payload_iter:
        try:
            if event == "start":
                P.claim_unit(unit_id, source=source, detail=dict(payload or {}), log=log)
            elif event == "delta":
                text = (payload or {}).get("text") or ""
                if text:
                    deltas_seen += 1
                    P.record_generating(
                        unit_id, nbytes=len(text.encode("utf-8", "replace")),
                        source=source, detail={"deltas_seen": deltas_seen}, log=log)
            elif event == "final":
                envelope = payload or {}
                streamed = deltas_seen > 0
                P.record_done(
                    unit_id, succeeded=bool(envelope.get("assistant")), applied=False,
                    source=source,
                    reason=("streamed reply" if streamed else
                           "no deltas observed before 'final' -- completed via the "
                           "non-streaming fallback, or produced only blocks this "
                           "adapter cannot see (tool_use/thinking)"),
                    detail={"provider_used": envelope.get("provider_used"),
                           "intent": envelope.get("intent"), "deltas_seen": deltas_seen},
                    log=log)
        except Exception:                        # noqa: BLE001 -- see module docstring:
            # a bug in recording must never break the caller's real stream. The
            # caller still gets every event/payload it would have gotten
            # without this wrapper; only OUR bookkeeping is at risk here.
            pass
        yield event, payload


# --------------------------------------------------------------------------- #
# 2 -- daedalus.offload.offload()'s result dict                               #
# --------------------------------------------------------------------------- #
def record_offload_result(unit_id: str, result: dict, *, source: str = "offload.offload",
                          log: "P.ProgressLog | None" = None) -> None:
    """Decompose one ALREADY-RETURNED ``offload()`` result into the events it
    proves.

    ``offload()`` is one blocking call with no internal hook this module may
    reach into without editing it (out of scope for this module -- offload.py
    is owned elsewhere) -- so everything below lands at once, timestamped at
    the moment the call returned. Between :func:`track_call`'s CLAIMED and
    this, a caller polling ``progress.snapshot()`` sees only CLAIMED (and
    HEARTBEAT, if enabled) -- which is the truth: ``offload()`` offers no
    finer-grained signal, and nothing here fabricates one.

    GROUND TRUTH USED: ``result["wrote"]`` -- offload's own before/after
    content-hash diff. ``result["report"]["files_changed"]`` (the worker's
    self-report) is never read by this function.
    """
    log = log or P.default_log()
    action = result.get("action")

    if action == "would_offload":
        P.record_done(unit_id, succeeded=None, applied=False, source=source,
                      reason="dry run only (live=False); nothing was executed",
                      detail={"action": action}, log=log)
        return
    if action in ("escalate_to_claude", "senior"):
        P.record_done(unit_id, succeeded=None, applied=False, source=source,
                      reason=result.get("note") or
                      "routed away from the free bench; nothing ran here",
                      detail={"action": action}, log=log)
        return

    report = result.get("report") or {}
    P.record_tool_ran(unit_id, name=f"{result.get('provider', '?')} worker",
                      ok=bool(report), source=source,
                      detail={"objective": result.get("objective"),
                             "owner": result.get("owner"),
                             "mode": result.get("mode")}, log=log)

    verify = result.get("verify")
    if verify is not None:
        P.record_gate_verdict(unit_id, name="offload.verify", passed=bool(verify.get("ok")),
                              source=source, detail={"checks": verify.get("checks")}, log=log)

    wrote = result.get("wrote")
    mode = result.get("mode")
    if wrote is not None:
        detail = {"mode": mode}
        if not wrote and mode == "advisory":
            # Advisory legitimately writes nothing -- a draft, not a no-op.
            # Kept in the detail so a renderer does not read NO_CHANGE here
            # as a failed write attempt.
            detail["note"] = "advisory draft: no disk write is expected"
        P.record_disk_change(unit_id, changed_paths=wrote, basis="content_hash_diff",
                             source=source, detail=detail, log=log)

    succeeded = action == "offloaded"
    applied = bool(wrote) if wrote is not None else None
    done_detail: dict[str, Any] = {"action": action}
    if result.get("rolled_back"):
        done_detail["rolled_back"] = result["rolled_back"]
        # Rolled back means the paths are NOT still on disk even though
        # `wrote` may still list them -- offload.py keeps `wrote`
        # ground-truthful only for paths it could NOT revert
        # (`dirty_unreverted`). Correct `applied` down rather than trust
        # `wrote` alone once a rollback happened.
        applied = bool(result.get("dirty_unreverted"))
    if result.get("dirty_unreverted"):
        done_detail["dirty_unreverted"] = result["dirty_unreverted"]
        done_detail["note"] = ("write could not be fully reverted -- a live hazard, "
                               "not a clean failure")
    P.record_done(unit_id, succeeded=succeeded, applied=applied, source=source,
                 reason=str(action or "no action recorded"), detail=done_detail, log=log)


# --------------------------------------------------------------------------- #
# 3 -- daedalus.spine.attempt.AttemptResult (TaskAttempt.run())               #
# --------------------------------------------------------------------------- #
def record_attempt_result(unit_id: str, result: Any, *,
                          source: str = "spine.attempt.TaskAttempt",
                          log: "P.ProgressLog | None" = None) -> None:
    """Decompose one :class:`daedalus.spine.attempt.AttemptResult`.

    NEVER emits DISK_CHANGED: ``attempt.py`` is structurally incapable of
    writing the primary checkout (three enforced properties -- see its
    module docstring), so any artifact it produces is PATCH_PRODUCED at
    most, explicitly marked unapplied.
    """
    log = log or P.default_log()
    if result.runner_detail is not None:
        P.record_tool_ran(unit_id, name="runner", ok=(result.state != "runner_failed"),
                          source=source, detail={"state": result.state}, log=log)
    if result.gates is not None:
        P.record_gate_verdict(
            unit_id, name=result.gates.name, passed=result.gates.passed, source=source,
            detail={"returncode": result.gates.returncode,
                   "duration_s": result.gates.duration_s,
                   "timed_out": result.gates.timed_out,
                   "cancelled": result.gates.cancelled}, log=log)
    if result.artifact is not None and not result.artifact.is_empty:
        P.record_patch_produced(
            unit_id, diff_sha256=result.artifact.diff_sha256,
            changed_paths=list(result.artifact.changed_paths),
            byte_length=result.artifact.byte_length, branch=result.branch, source=source,
            detail={"base_revision": result.base_revision}, log=log)
    P.record_done(
        unit_id, succeeded=result.ok, applied=False, source=source,
        reason=result.error or result.state,
        detail={"state": result.state, "effect_key": result.effect_key,
               "intent_id": result.intent_id}, log=log)


# --------------------------------------------------------------------------- #
# 4 -- generic blocking-call wrapper, for anything with no finer-grained hook  #
# --------------------------------------------------------------------------- #
def track_call(unit_id: str, fn: Callable[..., Any], *args: Any, source: str,
               heartbeat_interval_s: float | None = 15.0,
               log: "P.ProgressLog | None" = None, **kwargs: Any) -> Any:
    """Claim, call ``fn`` (blocking), decompose the result if it is a
    recognisable shape, then mark done. Re-raises whatever ``fn`` raises,
    after recording a failed DONE.

    Optionally emits HEARTBEAT from a background thread while ``fn`` runs --
    proof the calling thread has not died, nothing more.

    THE HONEST GAP THIS DOES NOT CLOSE: between CLAIMED and the moment ``fn``
    returns, nothing here can prove FORWARD PROGRESS inside ``fn`` -- only
    that the thread asking is still alive. Neither ``offload()`` nor
    ``KairosScheduler.dispatch()`` expose a finer-grained hook, and this
    function does not guess one into existence.
    """
    log = log or P.default_log()
    P.claim_unit(unit_id, source=source,
                 detail={"fn": getattr(fn, "__name__", str(fn))}, log=log)

    stop: threading.Event | None = None
    thread: threading.Thread | None = None
    if heartbeat_interval_s and heartbeat_interval_s > 0:
        stop = threading.Event()

        def _beat() -> None:
            n = 0
            while not stop.wait(heartbeat_interval_s):
                n += 1
                try:
                    P.heartbeat(unit_id, source=source, detail={"beat": n}, log=log)
                except Exception:                # noqa: BLE001 -- a heartbeat must never crash the worker
                    pass

        thread = threading.Thread(target=_beat, daemon=True,
                                  name=f"progress-heartbeat-{unit_id}")
        thread.start()

    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        if stop is not None:
            stop.set()
        P.record_done(unit_id, succeeded=False, applied=None, source=source,
                      reason=f"{type(exc).__name__}: {exc}", log=log)
        raise
    finally:
        if stop is not None:
            stop.set()

    if isinstance(result, dict) and "action" in result and "eligible" in result:
        record_offload_result(unit_id, result, source=f"{source}->offload", log=log)
    else:
        try:
            from .spine.attempt import AttemptResult
        except Exception:                        # noqa: BLE001
            AttemptResult = ()                    # type: ignore[assignment]
        if AttemptResult and isinstance(result, AttemptResult):
            record_attempt_result(unit_id, result, source=f"{source}->attempt", log=log)
        else:
            P.record_done(unit_id, succeeded=None, applied=None, source=source,
                          reason="fn returned an unrecognised shape; recorded "
                                "completion only, no further decomposition",
                          detail={"result_type": type(result).__name__}, log=log)
    return result


# --------------------------------------------------------------------------- #
# 5 -- the spine ledger, polled READ-ONLY                                     #
# --------------------------------------------------------------------------- #
def _ledger_unit_progress(intent: Any, *, now: float) -> "P.UnitProgress":
    from .spine.ledger import STATE_COMPLETED

    created = P.parse_iso(intent.created_ts)
    claimed_age = max(0.0, now - created)
    terminal = intent.is_open is False
    succeeded = (intent.state == STATE_COMPLETED) if terminal else None
    payload = intent.payload if isinstance(intent.payload, dict) else {}

    facts = [
        measured("ledger state", intent.state),
        P.Fact(label="claim age", value=f"{intent.state} for {P.format_age(claimed_age)}",
              provenance=INHERITED,
              source=f"spine ledger intent #{intent.id} ({intent.kind})", age_s=claimed_age),
    ]
    if payload.get("instruction"):
        facts.append(measured("instruction", str(payload["instruction"])[:160]))
    if intent.error:
        facts.append(measured("ledger error", str(intent.error)[:200]))

    latest_kind = P.DONE if terminal else P.CLAIMED
    narrative = [{"kind": "claimed", "ts": intent.created_ts, "source": "spine.ledger",
                 "detail": {"payload_sha": intent.payload_sha, "kind": intent.kind}}]
    if terminal:
        narrative.append({"kind": "done", "ts": intent.resolved_ts, "source": "spine.ledger",
                          "detail": {"effect_id": intent.effect_id, "error": intent.error}})

    return P.UnitProgress(
        unit_id=str(intent.effect_key or intent.id), observed_at=P.now_iso(), found=True,
        events_seen=len(narrative), kinds_seen=(latest_kind,), latest_kind=latest_kind,
        latest_source="spine.ledger", latest_ts=(intent.resolved_ts or intent.created_ts),
        age_s=(0.0 if terminal else claimed_age), claimed_ts=intent.created_ts,
        claimed_age_s=claimed_age, terminal=terminal, succeeded=succeeded,
        applied=(False if terminal else None), stalled=False,
        fraction_hint="single ledger intent: no total is knowable here; see "
                      "daedalus.progress.batch_snapshot for a declared set of units",
        facts=tuple(facts), narrative=tuple(narrative))


def snapshot_from_ledger(effect_key_or_id: str | int, *,
                         ledger_path: str | Path | None = None) -> "P.UnitProgress | None":
    """Read-only poll of the spine ledger for ONE unit, by ``effect_key``
    (the repo's own recommended handle -- "a token you can go and look for
    afterwards") or by raw intent id.

    Opens ``SpineLedger(read_only=True)`` -- same discipline as
    ``daedalus.health``: merely asking must never write. Returns ``None`` on
    a miss (never raises for "nothing matches"); a genuinely broken ledger
    path/file still raises, matching ``SpineLedger``'s own posture.
    """
    from .spine.ledger import SpineLedger, default_db_path

    path = Path(ledger_path) if ledger_path else default_db_path()
    if not path.exists():
        return None
    ledger = SpineLedger(path, read_only=True)
    try:
        now = time.time()
        intent = None
        try:
            iid = int(effect_key_or_id)
        except (TypeError, ValueError):
            iid = None
        if iid is not None:
            intent = ledger.get(iid)
        if intent is None:
            matches = ledger.resolve_by_effect(str(effect_key_or_id))
            intent = matches[-1] if matches else None  # most recent attempt under this key
        if intent is None:
            return None
        return _ledger_unit_progress(intent, now=now)
    finally:
        ledger.close()


def open_attempts(*, kind: str = "attempt.candidate",
                  ledger_path: str | Path | None = None) -> list["P.UnitProgress"]:
    """Every currently-OPEN (claimed, unresolved) ledger intent, right now,
    from any process.

    This is the concrete, already-wired answer to "how many siblings are in
    flight" for every concurrent write this repo dispatches through
    :class:`daedalus.spine.attempt.TaskAttempt` -- including
    ``daedalus.kairos.gated_writes.gate_candidates``, which fans N of these
    out at once. No code elsewhere had to change for this to be true: the
    ledger already commits the claim before the effect (see
    ``spine/ledger.py``'s module docstring, "INTENT BEFORE EFFECT").
    """
    from .spine.ledger import SpineLedger, default_db_path

    path = Path(ledger_path) if ledger_path else default_db_path()
    if not path.exists():
        return []
    ledger = SpineLedger(path, read_only=True)
    try:
        now = time.time()
        return [_ledger_unit_progress(i, now=now) for i in ledger.open_intents(kind=kind)]
    finally:
        ledger.close()


# --------------------------------------------------------------------------- #
# 6 -- the file bridge outbox/inbox/archive lifecycle, polled READ-ONLY       #
# --------------------------------------------------------------------------- #
def _bridge_progress(key: str, latest_kind: str, age_s: float | None, succeeded: bool | None,
                     applied: bool | None, note: str, *,
                     source_path: Path | None = None) -> "P.UnitProgress":
    facts = [measured("bridge state", latest_kind)]
    if source_path is not None:
        facts.append(inherited("source file", str(source_path), source_path))
    else:
        facts.append(P.Fact(label="note", value=note, provenance=INHERITED,
                            source=f"file_bridge heartbeat (key {key})",
                            age_s=(age_s if age_s is not None else 0.0)))
    return P.UnitProgress(
        unit_id=key, observed_at=P.now_iso(), found=True, events_seen=1,
        kinds_seen=(latest_kind,), latest_kind=latest_kind, latest_source="file_bridge",
        latest_ts=None, age_s=age_s, claimed_ts=None, claimed_age_s=age_s,
        terminal=(latest_kind == P.DONE), succeeded=succeeded, applied=applied, stalled=False,
        fraction_hint="single bridge task: no total is knowable here; see "
                      "daedalus.progress.batch_snapshot for a declared set of units",
        facts=tuple(facts),
        narrative=({"kind": latest_kind, "ts": None, "source": "file_bridge",
                   "detail": {"note": note}},))


def _report_verdict(report_path: "Path") -> tuple[bool | None, object]:
    """``(succeeded, raw_status)`` for a bridge report, or ``(None, None)``.

    ONE rule, called from both the archived branch and the report branch, so
    an archived task and a not-yet-archived one can never disagree about the
    same report. They did: the archive branch used to hardcode success.

    ``succeeded`` is tri-state on purpose. A report with no status at all is
    ``None`` -- unproven -- never ``False``, because "the watcher wrote no
    status" and "the watcher wrote a failure" are different facts.
    """
    import json as _json

    try:
        report = _json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        report = {}
    status = report.get("bridge_status") or report.get("status")
    succeeded = (str(status).lower() in ("done", "ok", "success")) if status else None
    return succeeded, status


def snapshot_from_bridge(key: str, *, now: float | None = None) -> "P.UnitProgress | None":
    """Read-only poll of one :mod:`daedalus.file_bridge`-dispatched task,
    keyed by the outbox filename stem :func:`daedalus.file_bridge.enqueue`
    returns (its own de-facto idempotency key). Reads real, already-durable
    facts and nothing else:

      outbox/{key}.json           -> still queued, watcher has not claimed it
      (heartbeat "current" == key) -> claimed; busy or wedged per the
                                      watcher's own classification
      inbox/{key}.report.json     -> the watcher finished and wrote a report
      runs/processed/{key}.json   -> archived (terminal, acknowledged)
      quarantined                 -> the watcher gave up (see
                                      ``file_bridge.quarantined_requests()``)

    Returns ``None`` when the key matches nothing in any of the four places
    (never guesses).
    """
    from . import file_bridge as fb

    now = now if now is not None else time.time()

    archive_path = fb.ARCHIVE / f"{key}.json"
    report_path = fb.INBOX / f"{key}.report.json"

    if archive_path.exists():
        age = max(0.0, now - archive_path.stat().st_mtime)
        # THE ARCHIVE HOLDS THE REQUEST, NOT THE OUTCOME.
        #
        # ``runs/processed/{key}.json`` is the enqueued REQUEST -- objective,
        # lane, paths, model -- and carries no status field of any kind.
        # "Archived" means the watcher acknowledged the task and filed it,
        # which it does for FAILURES exactly as it does for successes.
        #
        # This branch used to return ``succeeded=True, applied=True`` from that
        # file. It was this module's own forbidden collapse, named in
        # ``progress.py``'s docstring -- "finished is not succeeded, and
        # succeeded is not applied" -- and it was invisible, because this
        # branch runs BEFORE the report branch below and masks it. A task whose
        # report said ``bridge_status=failed`` flipped to a green "succeeded"
        # the moment the watcher filed it, while the task-level view kept
        # reporting the failure honestly. Two projections of one run,
        # disagreeing, with the optimistic one winning.
        #
        # Measured 2026-09-03 on a real dispatch: state=failed, error="the
        # trusted local bench did not accept the task", progress.succeeded=true.
        #
        # The verdict now comes from the report, by the same rule the report
        # branch uses. With no report retained there is no evidence either way,
        # so the answer is None -- unproven -- never True.
        if report_path.exists():
            succeeded, status = _report_verdict(report_path)
            note = f"archived (acknowledged); report says bridge_status={status!r}"
        else:
            succeeded, note = None, ("archived (acknowledged); no report was retained, "
                                     "so the outcome is unproven")
        # ``applied`` stays None for the reason it does in the report branch:
        # nothing here is evidence that anything reached the disk.
        return _bridge_progress(key, P.DONE, age, succeeded, None, note,
                                source_path=archive_path)

    try:
        quarantined = {q.get("name") for q in fb.quarantined_requests()}
    except Exception:                            # noqa: BLE001 -- a quarantine-list failure must not hide the other checks
        quarantined = set()
    if f"{key}.json" in quarantined:
        return _bridge_progress(key, P.DONE, None, False, False,
                                "quarantined: the watcher gave up on it")

    if report_path.exists():
        age = max(0.0, now - report_path.stat().st_mtime)
        succeeded, status = _report_verdict(report_path)
        return _bridge_progress(key, P.DONE, age, succeeded, None,
                                f"report landed, bridge_status={status!r}",
                                source_path=report_path)

    try:
        hb = fb.heartbeat_status(now=now)
    except Exception:                            # noqa: BLE001
        hb = {}
    current = hb.get("current") or {}
    if key in str(current.get("file") or ""):
        state = hb.get("state")
        return _bridge_progress(key, P.CLAIMED, hb.get("busy_for_s"), None, None,
                                f"watcher state={state}, {hb.get('busy_for_s')}s into this task")

    outbox_path = fb.OUTBOX / f"{key}.json"
    if outbox_path.exists():
        age = max(0.0, now - outbox_path.stat().st_mtime)
        return _bridge_progress(key, P.QUEUED, age, None, None,
                                "queued; not yet claimed by the watcher",
                                source_path=outbox_path)

    return None


# --------------------------------------------------------------------------- #
# 7 -- one entry point across every source this module knows about            #
# --------------------------------------------------------------------------- #
def snapshot_any(unit_id: str, *, log: "P.ProgressLog | None" = None,
                 ledger_path: str | Path | None = None,
                 now: float | None = None) -> "P.UnitProgress":
    """Try, in order: this module's own event log, the spine ledger (by
    effect_key/intent id), the file bridge (by outbox/inbox key). Returns
    the FIRST source that recognises the id.

    Never guesses across sources, and never prefers a stale one over a live
    one: if the log has events for this id, that IS the answer -- a caller
    that already knows an id is ledger- or bridge-backed should call
    :func:`snapshot_from_ledger`/:func:`snapshot_from_bridge` directly rather
    than relying on this fallback order.
    """
    log = log or P.default_log()
    own = P.snapshot(unit_id, log=log, now=now)
    if own.found:
        return own
    from_ledger = snapshot_from_ledger(unit_id, ledger_path=ledger_path)
    if from_ledger is not None:
        return from_ledger
    from_bridge = snapshot_from_bridge(unit_id, now=now)
    if from_bridge is not None:
        return from_bridge
    return own  # found=False -- the honest "nobody has heard of this id" answer

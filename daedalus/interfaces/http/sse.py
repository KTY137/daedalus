"""Server-sent-event delivery behind the legacy HTTP facade."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Collection, Pattern

from ... import core
from ...orchestration.ikarus import shell as ikarus_os
from ...orchestration import conversation_requests

SsePort = Callable[..., Any]
ClockPort = Callable[[], float]
SleepPort = Callable[[float], None]

EVENT_STREAM_MAX_S = 300
EVENT_STREAM_PERIOD_S = 1.0
EVENT_STREAM_KEEP_ALIVE_S = 15
TASK_EVENTS_MAX_S = 1800
TASK_EVENTS_GRACE_S = 10.0
TASK_EVENTS_PERIOD_S = 3.0


class _ClientDisconnected(Exception):
    """Internal control flow for a client that closed an SSE connection."""


def snapshot_events(project: str | None, *, stream_state: SsePort) -> dict[str, Any]:
    """Read one project-scoped bridge snapshot through the injected port."""

    return stream_state(project)


def event_changes(
        previous: dict[str, Any],
        current: dict[str, Any],
) -> tuple[tuple[str, Any], ...]:
    """Translate a pair of snapshots into the additive live-event contract."""

    changes: list[tuple[str, Any]] = []
    if current.get("reports_total", 0) > previous.get("reports_total", 0):
        changes.append(("report", current.get("latest_report") or {}))
    if current.get("queue_depth") != previous.get("queue_depth"):
        changes.append(("queue", {"queue_depth": current.get("queue_depth", 0)}))
    if (
        current.get("watcher_state") != previous.get("watcher_state")
        or current.get("in_flight") != previous.get("in_flight")
    ):
        changes.append(
            (
                "heartbeat",
                {
                    "watcher_state": current.get("watcher_state"),
                    "in_flight": current.get("in_flight"),
                },
            )
        )
    return tuple(changes)


def encode_event(event: str, data: Any, sequence: int | None = None) -> bytes:
    """Encode one event with the legacy JSON and SSE framing."""

    prefix = f"id: {sequence}\n" if sequence is not None else ""
    frame = prefix + f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
    return frame.encode("utf-8")


def _open_stream(handler: Any, *, connection: str) -> bool:
    """Write the common SSE headers, returning false after a socket close."""

    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", connection)
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()
    except OSError:
        return False
    return True


def _write_frame(handler: Any, frame: bytes) -> None:
    """Write one frame or turn a transport close into local control flow."""

    try:
        handler.wfile.write(frame)
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError) as exc:
        raise _ClientDisconnected from exc


def _send_event(
        handler: Any,
        event: str,
        data: Any,
        sequence: int | None = None,
) -> None:
    _write_frame(handler, encode_event(event, data, sequence))


def _send_keep_alive(handler: Any) -> None:
    _write_frame(handler, b": keep-alive\n\n")


def stream_events(
        handler: Any,
        project: str | None,
        *,
        stream_state: SsePort,
        clock: ClockPort,
        sleep: SleepPort,
        max_s: float = EVENT_STREAM_MAX_S,
        period_s: float = EVENT_STREAM_PERIOD_S,
        keep_alive_s: float = EVENT_STREAM_KEEP_ALIVE_S,
) -> None:
    """Run the bounded dashboard stream over project-scoped snapshots."""

    previous = snapshot_events(project, stream_state=stream_state)
    _send_event(handler, "hello", previous)
    start = clock()
    last_keep_alive = start
    while clock() - start < max_s:
        sleep(period_s)
        current = snapshot_events(project, stream_state=stream_state)
        for event, payload in event_changes(previous, current):
            _send_event(handler, event, payload)
        previous = current
        if clock() - last_keep_alive >= keep_alive_s:
            _send_keep_alive(handler)
            last_keep_alive = clock()


def handle_events(handler: Any, project: str | None, *, stream_state: SsePort) -> None:
    """Server-Sent Events: cheap live push of bus state (queue/reports/watcher)
    so the cockpit stops polling the heavy dashboard. Reads only the file bus;
    self-recycles after 5 min (EventSource auto-reconnects)."""
    self = handler
    if not _open_stream(self, connection="keep-alive"):
        return
    try:
        stream_events(
            self,
            project,
            stream_state=stream_state,
            clock=time.time,
            sleep=time.sleep,
        )
    except _ClientDisconnected:
        return
    except Exception:
        return


def handle_ikarus_stream(handler: Any, qs: dict[str, list[str]]) -> None:
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
      ``ikarus_os.ask_stream`` -- see daedalus/orchestration/conversation.py. Omitted,
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
    self = handler
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
        from ... import progress as progress_mod

        unit_id = progress_mod.open_unit(
            source="web_api.ikarus_stream",
            detail={"project": project, "message_chars": len(message)})
    except Exception:
        unit_id = None  # progress tracking is best-effort; the chat is not

    self.close_connection = True  # one-shot: do not hold the socket open
    if not _open_stream(self, connection="close"):
        return

    try:
        stream = ikarus_os.ask_stream(
            project, message, provider=provider, model=model, effort=effort,
            conversation_id=conversation_id,
        )
        if unit_id:
            from ... import progress_sources

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
            _send_event(self, event, payload)
    except _ClientDisconnected:
        return  # client navigated away mid-stream
    except Exception as exc:
        # Fail closed into a well-formed chat envelope: the UI shows a reply,
        # never a broken stream.
        try:
            _send_event(
                self,
                "final",
                core.envelope(
                    project,
                    intent="error",
                    assistant=f"I hit a snag: {exc}",
                    provider_used="deterministic",
                    delivery_mode="stream",
                    stream_interrupted=True,
                ),
            )
        except _ClientDisconnected:
            return


def handle_task_events(
        handler: Any,
        task_id: str,
        *,
        task_snapshot: SsePort,
        task_id_re: Pattern[str],
        terminal_sources: Collection[str],
) -> None:
    """Server-Sent Events: progress of ONE task, addressed by the id
    POST /api/queue handed back. Built from the same file-bridge bus
    GET /api/queue/<id> reads (outbox/heartbeat/inbox) -- this is that
    same snapshot, pushed on a timer instead of pulled once.

    ONE-SHOT, like /api/ikarus/stream: closes once the task reaches a
    terminal state (a report exists, or the id is archived with no
    report) or after ``TASK_EVENTS_MAX_S``, and says which in the
    'final' event's own fields. An EventSource client MUST call
    ``es.close()`` on 'final' -- auto-reconnect would just reopen onto an
    already-finished task and replay the same 'final' forever.

    A fresh id that is not found YET (the enqueue -> first-poll race) is
    tolerated for ``TASK_EVENTS_GRACE_S`` before being reported as
    final/not-found -- see ``_task_snapshot``'s docstring on why "not
    found" cannot be told apart from "wrong id" by a filesystem check
    alone.
    """
    self = handler
    _task_snapshot = task_snapshot
    _TASK_ID_RE = task_id_re
    _TASK_TERMINAL_SOURCES = terminal_sources
    if not _TASK_ID_RE.match(task_id):
        self._send_json({"ok": False, "error": "invalid task id"}, status=400)
        return
    self.close_connection = True  # one-shot: do not hold the socket open
    if not _open_stream(self, connection="close"):
        return

    try:
        start = time.time()
        last_state: str | None = None
        last_stalled = False
        last_emit = 0.0
        while True:
            snap = _task_snapshot(task_id)
            now = time.time()
            if not snap["found"]:
                if now - start > TASK_EVENTS_GRACE_S:
                    _send_event(self, "final", snap)
                    return
                time.sleep(1.0)
                continue
            terminal = snap["source"] in _TASK_TERMINAL_SOURCES
            if terminal:
                _send_event(self, "final", snap)
                return
            if now - start > TASK_EVENTS_MAX_S:
                _send_event(
                    self,
                    "final",
                    {
                        **snap,
                        "timed_out": True,
                        "applied_reason": snap["applied_reason"]
                        + f" (subscription open >{TASK_EVENTS_MAX_S:.0f}s; "
                        "poll GET /api/queue/<id> to keep checking)",
                    },
                )
                return
            stalled = bool(snap.get("stalled"))
            if (snap["state"] != last_state or stalled != last_stalled
                    or now - last_emit >= TASK_EVENTS_PERIOD_S):
                _send_event(
                    self,
                    "hello" if last_state is None else "progress",
                    snap,
                )
                last_emit = now
            last_state = snap["state"]
            last_stalled = stalled
            time.sleep(1.0)
    except _ClientDisconnected:
        return  # client navigated away mid-stream
    except Exception as exc:
        try:
            _send_event(self, "error", {"ok": False, "error": str(exc)})
        except _ClientDisconnected:
            return


def handle_conversation_request_events(
        handler: Any,
        conversation_id: str,
        request_id: int,
        qs: dict[str, list[str]],
) -> None:
    """Observe one existing generation request without ever starting it.

    Reopening this endpoint is safe: creation lives exclusively on the POST
    route and the canonical request id is already fixed. ``Last-Event-ID``
    resumes the process-local frame sequence when it is available; after a
    restart the durable terminal/unknown projection is returned instead of
    replaying provider work.
    """
    self = handler
    manager = conversation_requests.default_manager()
    try:
        status = manager.status(request_id)
    except conversation_requests.UnknownConversationRequest as exc:
        self._send_json({"ok": False, "error": str(exc)}, status=404)
        return
    if status["conversation_id"] != conversation_id:
        self._send_json({"ok": False, "error": "turn request belongs to another conversation"}, status=404)
        return
    raw_after = (qs.get("after") or [self.headers.get("Last-Event-ID", "0")])[0]
    try:
        after = max(0, int(raw_after or 0))
    except (TypeError, ValueError):
        self._send_json({"ok": False, "error": "after must be an integer"}, status=400)
        return

    self.close_connection = True
    if not _open_stream(self, connection="close"):
        return

    try:
        while True:
            projection = manager.events(request_id, after=after, wait_s=15.0)
            rows = projection["events"]
            for row in rows:
                sequence = int(row["sequence"])
                after = max(after, sequence)
                _send_event(self, str(row["event"]), row["data"], sequence)
            if projection["terminal"]:
                if not rows:
                    _send_event(self, "state", projection["status"])
                return
            if not rows:
                _send_event(
                    self,
                    "heartbeat",
                    {
                        "request_id": request_id,
                        "state": projection["status"]["state"],
                    },
                )
    except _ClientDisconnected:
        return

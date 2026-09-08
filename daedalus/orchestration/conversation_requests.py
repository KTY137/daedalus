"""Idempotent, observable Ikarus generation requests on the canonical spine.

Creating a request records an open intent *before* provider work starts.  A
client observes that intent through a separate read path; reconnecting can
therefore never repeat the provider call.  Final chat turns continue to be
persisted by :mod:`daedalus.orchestration.ikarus.shell` through :mod:`daedalus.orchestration.conversation`.

The process-local runtime below is only a live stream projection.  After a
server restart an unresolved request is reported as ``unknown`` and is never
automatically replayed.  The canonical spine remains the sole durable state.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .ikarus import shell as ikarus_os
from . import conversation, editor_context
from ..spine.ledger import STATE_COMPLETED, STATE_FAILED, STATE_INTENDED, Intent


KIND_GENERATION = conversation.KIND_GENERATION
KIND_CANCELLATION = "conversation.generation.cancel"
_REQUEST_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")


class ConversationRequestError(RuntimeError):
    pass


class UnknownConversationRequest(ConversationRequestError):
    pass


class ConflictingConversationRequest(ConversationRequestError):
    pass


class ConflictingConversationProject(ConflictingConversationRequest):
    """The durable conversation id belongs to another/invalid project."""


@dataclass
class _Runtime:
    request_id: int
    cancel: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)
    events: list[dict[str, Any]] = field(default_factory=list)
    terminal: bool = False
    worker: threading.Thread | None = None
    cancel_intent_ids: list[int] = field(default_factory=list)
    stream: Any = None
    cancel_supported: bool | None = None


@dataclass(frozen=True)
class _RuntimeSnapshot:
    """One condition-locked view of the process-local stream projection."""

    live: bool = False
    cancel_set: bool = False
    cancel_intent_ids: frozenset[int] = frozenset()

    def owns(self, cancellation_id: int) -> bool:
        return (
            self.live
            and self.cancel_set
            and int(cancellation_id) in self.cancel_intent_ids
        )


def _client_key(conversation_id: str, client_request_id: str) -> str:
    return f"{conversation_id}:{client_request_id}"


def _check_client_id(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 160 or any(ch not in _REQUEST_ID_CHARS for ch in text):
        raise ConversationRequestError(
            f"{label} must be 1-160 URL-safe identifier characters")
    return text


def _lane_for_context(provider: str | None) -> str:
    """Resolve the same voice choice as Ikarus, biased fail-closed."""
    try:
        selection = ikarus_os._voice_client().resolve(provider)  # noqa: SLF001
        selected = str(selection.provider or "").lower()
        if selected in ikarus_os._DEEPSEEK or selected in ikarus_os._CODEX:  # noqa: SLF001
            return "untrusted"
        if selected in ikarus_os._OLLAMA_HTTP or selected in ikarus_os._OLLAMA_CLI:  # noqa: SLF001
            return ikarus_os._local_lane()  # noqa: SLF001
        return "trusted"
    except Exception:
        return "untrusted"


class ConversationRequestManager:
    def __init__(
        self,
        store: conversation.ConversationStore | None = None,
        *,
        stream_factory: Callable[..., Iterable[tuple[str, dict[str, Any]]]] | None = None,
    ) -> None:
        self.store = store or conversation.default_store()
        self.spine = self.store.spine
        self.stream_factory = stream_factory or ikarus_os.ask_stream
        self._lock = threading.Lock()
        self._runtime: dict[int, _Runtime] = {}
        self._install_uniqueness_guards()

    def _install_uniqueness_guards(self) -> None:
        try:
            with self.spine._txn() as connection:  # canonical writer transaction
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_conversation_generation_client_key "
                    "ON intents(effect_key) "
                    f"WHERE kind = '{KIND_GENERATION}'")
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_conversation_generation_cancel_key "
                    "ON intents(effect_key) "
                    f"WHERE kind = '{KIND_CANCELLATION}'")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_conversation_generation_cancel_request "
                    "ON intents(json_extract(payload, '$.request_id'), id DESC) "
                    f"WHERE kind = '{KIND_CANCELLATION}'")
        except (sqlite3.DatabaseError, AttributeError) as exc:
            raise ConversationRequestError(
                "the canonical spine cannot enforce generation identities: "
                f"{type(exc).__name__}: {exc}") from exc

    def _intent(self, request_id: object) -> Intent:
        if type(request_id) is not int or request_id <= 0:
            raise UnknownConversationRequest(str(request_id))
        intent = self.spine.get(request_id)
        if intent is None or intent.kind != KIND_GENERATION:
            raise UnknownConversationRequest(str(request_id))
        return intent

    def _runtime_for(self, request_id: int) -> _Runtime | None:
        with self._lock:
            return self._runtime.get(request_id)

    @staticmethod
    def _runtime_snapshot_locked(runtime: _Runtime | None) -> _RuntimeSnapshot:
        """Capture ``runtime`` while its condition is held by the caller."""
        if runtime is None:
            return _RuntimeSnapshot()
        worker = runtime.worker
        return _RuntimeSnapshot(
            live=bool(
                worker is not None
                and worker.is_alive()
                and not runtime.terminal
            ),
            cancel_set=runtime.cancel.is_set(),
            cancel_intent_ids=frozenset(runtime.cancel_intent_ids),
        )

    def _durable_snapshot(self, request_id: int) -> tuple[Intent, list[Intent]]:
        """Read one generation and its cancellations at one durable point.

        The canonical ledger does not expose a compound read facade.  Use its
        existing re-entrant read lock and connection here, just as this manager
        already uses the ledger transaction seam to install its identity
        indexes.  Both SELECTs and hydration therefore observe one SQLite
        snapshot, and this helper never writes or resolves an intent.
        """
        with self.spine._lock:  # canonical connection/read lock
            connection = self.spine._conn
            connection.execute("BEGIN")
            try:
                row = connection.execute(
                    "SELECT * FROM intents WHERE id = ?", (int(request_id),)
                ).fetchone()
                if row is None:
                    raise UnknownConversationRequest(str(request_id))
                generation = self.spine._hydrate(row)
                if generation.kind != KIND_GENERATION:
                    raise UnknownConversationRequest(str(request_id))
                cancellation_rows = connection.execute(
                    "SELECT * FROM intents "
                    "WHERE kind = ? "
                    "AND json_extract(payload, '$.request_id') = ? "
                    "ORDER BY id DESC",
                    (KIND_CANCELLATION, int(request_id)),
                ).fetchall()
                cancellations = []
                for cancel_row in cancellation_rows:
                    cancellation = self.spine._hydrate(cancel_row)
                    if (
                        int(cancellation.payload.get("request_id") or 0)
                        == int(request_id)
                    ):
                        cancellations.append(cancellation)
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        return generation, cancellations

    def _existing_by_key(self, key: str) -> Intent | None:
        rows = self.spine.intents_by_effect_key(key, kind=KIND_GENERATION, limit=1)
        return rows[0] if rows else None

    def create(
        self, *, conversation_id: object, client_request_id: object,
        project: object, message: object, provider: object = None,
        model: object = None, effort: object = None,
        context_refs: object = None,
    ) -> tuple[dict[str, Any], bool]:
        cid = str(conversation_id or "").strip()
        conversation.conversation_effect_key(cid)  # exact shared validation
        client_id = _check_client_id(client_request_id, "client_request_id")
        project_name = str(project or "").strip()
        prompt = str(message or "").strip()
        if not project_name or not prompt:
            raise ConversationRequestError("project and message are required")
        raw_refs = context_refs or []
        if not isinstance(raw_refs, list) or any(not isinstance(item, str) for item in raw_refs):
            raise ConversationRequestError("context_refs must be a list of strings")
        if len(raw_refs) > 20:
            raise ConversationRequestError("context_refs exceeds the 20-item limit")
        payload = {
            "conversation_id": cid,
            "client_request_id": client_id,
            "project": project_name,
            "message": prompt,
            "provider": str(provider) if provider else None,
            "model": str(model) if model else None,
            "effort": str(effort) if effort else None,
            "context_refs": list(dict.fromkeys(raw_refs)),
        }
        key = _client_key(cid, client_id)
        try:
            intent = self.spine.record_intent(
                KIND_GENERATION, payload, effect_key=key)
            created = True
        except sqlite3.IntegrityError as exc:
            if conversation.is_project_binding_conflict(exc):
                raise ConflictingConversationProject(
                    f"conversation {cid!r} is already bound to another project "
                    "or has a quarantined project history") from exc
            intent = self._existing_by_key(key)
            if intent is None or intent.payload != payload:
                raise ConflictingConversationRequest(
                    "client_request_id is already bound to different turn input") from exc
            created = False

        if created:
            runtime = _Runtime(intent.id)
            worker = threading.Thread(
                target=self._run, args=(intent.id,),
                name=f"ikarus-turn-{intent.id}", daemon=True)
            runtime.worker = worker
            with self._lock:
                self._runtime[intent.id] = runtime
            worker.start()
        return self.status(intent.id), created

    def _append_event(self, runtime: _Runtime, event: str,
                      payload: dict[str, Any]) -> None:
        with runtime.condition:
            runtime.events.append({
                "sequence": len(runtime.events) + 1,
                "event": event,
                "data": payload,
            })
            runtime.condition.notify_all()

    def _resolve_cancellations(self, runtime: _Runtime, status: str) -> None:
        with runtime.condition:
            intent_ids = list(runtime.cancel_intent_ids)
        for intent_id in intent_ids:
            try:
                current = self.spine.get(intent_id)
                if current is not None and current.state == STATE_INTENDED:
                    self.spine.mark_completed(
                        intent_id, effect_id=str(runtime.request_id),
                        result={"status": status, **self._subprocess_evidence(runtime)})
            except Exception:
                # The generation outcome remains authoritative even if this
                # informational cancellation projection cannot be closed.
                continue

    def _complete_cancellation(self, intent: Intent, status: str) -> Intent:
        """Resolve one cancellation once, absorbing only a proven race."""
        if intent.state != STATE_INTENDED:
            return intent
        try:
            return self.spine.mark_completed(
                intent.id,
                effect_id=str(intent.payload.get("request_id") or ""),
                result={"status": status},
            )
        except Exception:
            current = self.spine.get(intent.id)
            if current is None or current.state == STATE_INTENDED:
                raise
            return current

    @staticmethod
    def _stored_cancellation_status(intent: Intent) -> str | None:
        if intent.state != STATE_COMPLETED or not isinstance(intent.result, dict):
            return None
        status = str(intent.result.get("status") or "")
        if status in {
            "requested", "confirmed", "already_terminal", "not_supported",
            "unknown",
        }:
            return status
        return "unknown"

    @classmethod
    def _has_confirmed_cancellation(cls, cancellations: list[Intent]) -> bool:
        return any(
            cls._stored_cancellation_status(cancellation) == "confirmed"
            for cancellation in cancellations
        )

    @classmethod
    def _project_cancellation(
        cls,
        cancellation: Intent,
        generation: Intent,
        runtime: _RuntimeSnapshot,
        *,
        has_confirmed: bool,
    ) -> dict[str, Any]:
        """Project one cancellation without mutating the canonical ledger."""
        stored = cls._stored_cancellation_status(cancellation)
        if stored is not None and stored != "requested":
            status = stored
        elif generation.state == STATE_COMPLETED:
            status = "already_terminal"
        elif generation.state == STATE_FAILED and generation.error != "cancelled_by_user":
            status = "already_terminal"
        elif cancellation.state == STATE_INTENDED and runtime.owns(cancellation.id):
            # A durable cancellation is only still "requested" while this
            # process has a live worker that registered and can act on it.
            status = "requested"
        elif generation.state == STATE_FAILED and has_confirmed:
            # A different, durably confirmed cancellation already stopped the
            # generation; this later/open request arrived too late.
            status = "already_terminal"
        else:
            # An unresolved generation after restart, or cancelled_by_user
            # without a durable confirmation, cannot be reconstructed.
            status = "unknown"
        return cls._cancel_projection(cancellation, status=status)

    @staticmethod
    def _request_stream_cancel(stream: Any) -> str:
        """Call one advertised cancel seam and normalize its support result.

        Legacy/injected cancellable iterators returned ``None``. That remains
        a supported request. The canonical Ikarus stream returns an explicit
        local outcome so a final-vs-cancel race is never guessed.
        """
        cancel_method = getattr(stream, "cancel", None)
        if not callable(cancel_method):
            return "not_supported"
        outcome = cancel_method()
        if outcome is None:
            return "requested"
        text = str(outcome)
        if text in {
            "requested", "confirmed", "already_terminal", "not_supported", "unknown"
        }:
            return text
        return "unknown"

    @staticmethod
    def _stream_cancellation_status(stream: Any) -> str | None:
        outcome = getattr(stream, "cancellation_status", None)
        if outcome in {"requested", "confirmed", "already_terminal"}:
            return str(outcome)
        return None

    @staticmethod
    def _subprocess_evidence(runtime: _Runtime) -> dict[str, Any]:
        # Only the canonical stream can issue exact-owned-child evidence.
        if type(runtime.stream) is not ikarus_os._CancellableAskStream:
            return {}
        receipt = runtime.stream.subprocess_stop_receipt
        if receipt is None:
            return {}
        return {"subprocess": {**receipt, "request_id": runtime.request_id},
                "provider_process_terminated": receipt["process_exited"]}

    def _finish_cancelled(self, runtime: _Runtime, request_id: int) -> str:
        """Durably expose local cancellation without guessing a terminal race."""
        current = self.spine.get(request_id)
        if current is not None and current.state == STATE_INTENDED:
            try:
                current = self.spine.mark_failed(request_id, "cancelled_by_user")
            except Exception:
                # Another process may have resolved the canonical intent after
                # our read. Only absorb that race when the durable reread proves
                # it; real storage failures while still open must remain errors.
                current = self.spine.get(request_id)
                if current is None or current.state == STATE_INTENDED:
                    raise
        if (
            current is None
            or current.state != STATE_FAILED
            or current.error != "cancelled_by_user"
        ):
            runtime.cancel.clear()
            outcome = (
                "already_terminal"
                if current is not None
                and current.state in {STATE_COMPLETED, STATE_FAILED}
                else "unknown"
            )
            self._resolve_cancellations(runtime, outcome)
            return outcome
        self._append_event(runtime, "cancelled", {
            "status": "confirmed",
            "scope": "local_generation_delivery_persistence",
            "provider_process_terminated": None,
            "request_id": request_id,
            **self._subprocess_evidence(runtime),
        })
        self._resolve_cancellations(runtime, "confirmed")
        return "confirmed"

    def _request_snapshot(
        self, request_id: int
    ) -> tuple[Intent, list[Intent], _Runtime | None, _RuntimeSnapshot]:
        """Capture runtime ownership and durable state without a torn view.

        Local final delivery takes ``runtime.condition`` before resolving the
        generation. Cancellation failure is recorded just before taking that
        condition. Capturing liveness first and the compound ledger snapshot
        second while holding the condition therefore admits a linearization
        point on either side of both local transitions.
        """
        runtime = self._runtime_for(request_id)
        if runtime is None:
            generation, cancellations = self._durable_snapshot(request_id)
            return generation, cancellations, None, _RuntimeSnapshot()
        with runtime.condition:
            runtime_snapshot = self._runtime_snapshot_locked(runtime)
            generation, cancellations = self._durable_snapshot(request_id)
        return generation, cancellations, runtime, runtime_snapshot

    def _run(self, request_id: int) -> None:
        runtime = self._runtime_for(request_id)
        if runtime is None:
            return
        intent = self._intent(request_id)
        payload = intent.payload
        stream = None
        try:
            context_receipt: dict[str, Any] | None = None
            context_text = ""
            refs = payload.get("context_refs") or []
            if refs:
                capsule = editor_context.materialize_capsule(
                    refs, project=payload["project"],
                    lane=_lane_for_context(payload.get("provider")))
                context_text = str(capsule.pop("text", ""))
                context_receipt = capsule
            stream = self.stream_factory(
                payload["project"], payload["message"],
                provider=payload.get("provider"), model=payload.get("model"),
                effort=payload.get("effort"),
                conversation_id=payload["conversation_id"],
                additional_context=context_text,
                context_receipt=context_receipt,
            )
            cancel_method = getattr(stream, "cancel", None)
            with runtime.condition:
                runtime.stream = stream
                runtime.cancel_supported = callable(cancel_method)
                cancellation_waiting = runtime.cancel.is_set()
            if cancellation_waiting:
                if callable(cancel_method):
                    outcome = self._request_stream_cancel(stream)
                    if outcome == "already_terminal":
                        runtime.cancel.clear()
                        self._resolve_cancellations(runtime, "already_terminal")
                    elif outcome in {"not_supported", "unknown"}:
                        runtime.cancel.clear()
                        self._resolve_cancellations(runtime, outcome)
                else:
                    runtime.cancel.clear()
                    self._resolve_cancellations(runtime, "not_supported")
                    self._append_event(runtime, "cancellation", {
                        "status": "not_supported", "request_id": request_id})
            saw_final = False
            for event, data in stream:
                if event == "final":
                    # ask_stream persists the exact turn before yielding final.
                    # If cancellation raced with this frame, the provider effect
                    # is already terminal and must not be relabelled cancelled.
                    saw_final = True
                    self._append_event(runtime, event, dict(data))
                    self.spine.mark_completed(
                        request_id,
                        effect_id=str(data.get("turn_id") or request_id),
                        result=dict(data),
                    )
                    self._resolve_cancellations(runtime, "already_terminal")
                    break
                if runtime.cancel.is_set():
                    if self._stream_cancellation_status(stream) == "already_terminal":
                        runtime.cancel.clear()
                        self._resolve_cancellations(runtime, "already_terminal")
                        self._append_event(runtime, event, dict(data))
                        continue
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                    self._finish_cancelled(runtime, request_id)
                    break
                self._append_event(runtime, event, dict(data))
            else:
                if not saw_final:
                    if runtime.cancel.is_set():
                        if self._stream_cancellation_status(stream) == "already_terminal":
                            runtime.cancel.clear()
                            self.spine.mark_failed(
                                request_id, "stream ended without final"
                            )
                            self._append_event(runtime, "error", {
                                "error": "stream ended without final"})
                            self._resolve_cancellations(
                                runtime, "already_terminal"
                            )
                        else:
                            self._finish_cancelled(runtime, request_id)
                    else:
                        self.spine.mark_failed(request_id, "stream ended without final")
                        self._append_event(runtime, "error", {
                            "error": "stream ended without final"})
                        self._resolve_cancellations(runtime, "unknown")
        except Exception as exc:
            cancel_race = self._stream_cancellation_status(stream)
            if runtime.cancel.is_set() and cancel_race != "already_terminal":
                self._finish_cancelled(runtime, request_id)
            else:
                cancellation_resolution = "unknown"
                if runtime.cancel.is_set():
                    runtime.cancel.clear()
                    cancellation_resolution = "already_terminal"
                current = self.spine.get(request_id)
                if current is not None and current.state == STATE_INTENDED:
                    self.spine.mark_failed(request_id, str(exc))
                self._append_event(runtime, "error", {"error": str(exc)})
                self._resolve_cancellations(runtime, cancellation_resolution)
        finally:
            with runtime.condition:
                runtime.stream = None
                runtime.terminal = True
                runtime.condition.notify_all()

    def status(self, request_id: object) -> dict[str, Any]:
        if type(request_id) is not int or request_id <= 0:
            raise UnknownConversationRequest(str(request_id))
        intent, cancellations, _runtime, runtime_snapshot = (
            self._request_snapshot(request_id)
        )
        has_confirmed = self._has_confirmed_cancellation(cancellations)
        active_requested = any(
            cancellation_intent.state == STATE_INTENDED
            and runtime_snapshot.owns(cancellation_intent.id)
            for cancellation_intent in cancellations
        )
        cancellation = (
            self._project_cancellation(
                cancellations[0],
                intent,
                runtime_snapshot,
                has_confirmed=has_confirmed,
            )
            if cancellations
            else None
        )
        state = "unknown"
        final = None
        error = None
        if intent.state == STATE_COMPLETED:
            state = "final"
            final = intent.result if isinstance(intent.result, dict) else None
        elif intent.state == STATE_FAILED:
            error = intent.error
            # The durable generation is authoritative.  A crash can land after
            # this failure is committed but before the informational cancel
            # row is confirmed; that makes the cancel projection unknown, not
            # the already-terminal generation.
            state = "cancelled" if error == "cancelled_by_user" else "error"
        elif has_confirmed:
            # Canonical writers confirm only after cancelling the generation.
            # If durable evidence ever contradicts that order, expose neither
            # a live nor a requested generation from the torn/corrupt pair.
            state = "unknown"
        elif active_requested:
            state = "cancel_requested"
        elif runtime_snapshot.live:
            state = "streaming"
        return {
            "request_id": intent.id,
            "conversation_id": intent.payload["conversation_id"],
            "client_request_id": intent.payload["client_request_id"],
            "project": intent.payload["project"],
            "state": state,
            "created_at": intent.created_ts,
            "resolved_at": intent.resolved_ts,
            "turn_id": (final or {}).get("turn_id"),
            "final": final,
            "error": error,
            "cancellation": cancellation,
        }

    def events(self, request_id: object, *, after: int = 0,
               wait_s: float = 0.0) -> dict[str, Any]:
        intent = self._intent(request_id)
        runtime = self._runtime_for(intent.id)
        if runtime is None:
            status = self.status(intent.id)
            terminal = status["state"] in {"final", "error", "cancelled", "unknown"}
            events = ([{"sequence": 1, "event": "final", "data": status["final"]}]
                      if status["final"] else [])
            return {"events": events, "terminal": terminal, "status": status}
        threshold = max(0, int(after))
        with runtime.condition:
            rows = [dict(row) for row in runtime.events
                    if int(row["sequence"]) > threshold]
            if not rows and not runtime.terminal and wait_s > 0:
                runtime.condition.wait(timeout=min(float(wait_s), 25.0))
                rows = [dict(row) for row in runtime.events
                        if int(row["sequence"]) > threshold]
            terminal = runtime.terminal
        return {"events": rows, "terminal": terminal,
                "status": self.status(intent.id)}

    def _reconcile_existing_cancellation(
        self,
        request_id: int,
        existing: Intent,
    ) -> dict[str, Any]:
        """Resolve an old/open cancellation on an effectful POST only.

        A GET merely projects an unresolved row. A repeated POST is allowed to
        close it because it is itself the effectful reconciliation request.
        It never upgrades ``cancelled_by_user`` to confirmed: only the live
        responsible worker can write that proof. Existing durable confirmation
        remains authoritative.
        """
        generation, cancellations, _runtime, runtime_snapshot = (
            self._request_snapshot(request_id)
        )
        cancellation = next(
            (row for row in cancellations if row.id == existing.id), existing
        )
        has_confirmed = self._has_confirmed_cancellation(cancellations)
        if cancellation.state != STATE_INTENDED:
            return self._project_cancellation(
                cancellation,
                generation,
                runtime_snapshot,
                has_confirmed=has_confirmed,
            )

        if generation.state == STATE_COMPLETED:
            resolution = "already_terminal"
        elif generation.state == STATE_FAILED and generation.error != "cancelled_by_user":
            resolution = "already_terminal"
        elif runtime_snapshot.owns(cancellation.id):
            return self._project_cancellation(
                cancellation,
                generation,
                runtime_snapshot,
                has_confirmed=has_confirmed,
            )
        elif generation.state == STATE_FAILED and has_confirmed:
            resolution = "already_terminal"
        else:
            resolution = "unknown"

        resolved = self._complete_cancellation(cancellation, resolution)
        return self._project_cancellation(
            resolved,
            generation,
            runtime_snapshot,
            has_confirmed=has_confirmed,
        )

    def cancel(self, request_id: object, *, client_cancel_id: object) -> dict[str, Any]:
        if type(request_id) is not int or request_id <= 0:
            raise UnknownConversationRequest(str(request_id))
        cancel_id = _check_client_id(client_cancel_id, "client_cancel_id")
        key = f"generation:{request_id}:cancel:{cancel_id}"
        existing_rows = self.spine.intents_by_effect_key(
            key, kind=KIND_CANCELLATION, limit=1)
        if existing_rows:
            return self._reconcile_existing_cancellation(
                request_id, existing_rows[0]
            )

        payload = {"request_id": request_id, "client_cancel_id": cancel_id}
        runtime = self._runtime_for(request_id)
        support: bool | None = None
        active_stream: Any = None
        immediate_status: str | None = None
        recorded: Intent | None = None
        try:
            if runtime is None:
                generation, _cancellations = self._durable_snapshot(request_id)
                immediate_status = (
                    "already_terminal"
                    if generation.state in {STATE_COMPLETED, STATE_FAILED}
                    else "unknown"
                )
                recorded = self.spine.record_fact(
                    KIND_CANCELLATION,
                    payload,
                    effect_key=key,
                    effect_id=str(request_id),
                    result={"status": immediate_status},
                )
            else:
                # Publish the open intent and register its process-local owner
                # under one condition lock. A duplicate POST cannot observe a
                # durable row in the gap before the worker owns it.
                with runtime.condition:
                    runtime_snapshot = self._runtime_snapshot_locked(runtime)
                    generation, _cancellations = self._durable_snapshot(request_id)
                    if generation.state in {STATE_COMPLETED, STATE_FAILED}:
                        immediate_status = "already_terminal"
                    elif not runtime_snapshot.live:
                        immediate_status = "unknown"
                    elif runtime.cancel_supported is False:
                        immediate_status = "not_supported"

                    if immediate_status is not None:
                        recorded = self.spine.record_fact(
                            KIND_CANCELLATION,
                            payload,
                            effect_key=key,
                            effect_id=str(request_id),
                            result={"status": immediate_status},
                        )
                    else:
                        recorded = self.spine.record_intent(
                            KIND_CANCELLATION,
                            payload,
                            effect_key=key,
                        )
                        runtime.cancel_intent_ids.append(recorded.id)
                        support = runtime.cancel_supported
                        active_stream = runtime.stream
                        runtime.cancel.set()
        except sqlite3.IntegrityError:
            rows = self.spine.intents_by_effect_key(
                key, kind=KIND_CANCELLATION, limit=1)
            if not rows:
                raise
            return self._reconcile_existing_cancellation(request_id, rows[0])

        assert recorded is not None
        if immediate_status is not None:
            generation, cancellations = self._durable_snapshot(request_id)
            return self._project_cancellation(
                recorded,
                generation,
                _RuntimeSnapshot(),
                has_confirmed=self._has_confirmed_cancellation(cancellations),
            )

        if support is True:
            try:
                outcome = self._request_stream_cancel(active_stream)
            except Exception:
                runtime.cancel.clear()
                self._resolve_cancellations(runtime, "unknown")
            else:
                if outcome in {"already_terminal", "unknown", "not_supported"}:
                    runtime.cancel.clear()
                    self._resolve_cancellations(runtime, outcome)
                # ``confirmed`` from the stream is deliberately left open
                # until the worker records cancelled_by_user. This keeps the
                # durable generation authoritative and prevents a confirmed
                # cancellation from being projected beside streaming work.

        # Close the completion race: the worker may have reached final between
        # the first state read and registration of this cancellation intent.
        current, _cancellations = self._durable_snapshot(request_id)
        if current is not None and current.state == STATE_COMPLETED:
            self._resolve_cancellations(runtime, "already_terminal")
        elif (
            current is not None
            and current.state == STATE_FAILED
            and current.error != "cancelled_by_user"
        ):
            self._resolve_cancellations(runtime, "already_terminal")
        # Seeing cancelled_by_user is not itself proof that this cancellation
        # caused the stop. Only the responsible worker's _finish_cancelled path
        # may durably confirm the registered cancellation intents.
        latest, cancellations, _runtime, runtime_snapshot = (
            self._request_snapshot(request_id)
        )
        refreshed = next(
            (row for row in cancellations if row.id == recorded.id), recorded
        )
        return self._project_cancellation(
            refreshed,
            latest,
            runtime_snapshot,
            has_confirmed=self._has_confirmed_cancellation(cancellations),
        )

    @staticmethod
    def _cancel_projection(
        intent: Intent, *, status: str | None = None
    ) -> dict[str, Any]:
        result = intent.result if isinstance(intent.result, dict) else {}
        return {
            "cancellation_id": intent.id,
            "request_id": int(intent.payload["request_id"]),
            "client_cancel_id": intent.payload["client_cancel_id"],
            "status": status or result.get("status") or "requested",
            "created_at": intent.created_ts,
            "resolved_at": intent.resolved_ts,
            **({"subprocess": result["subprocess"],
                "provider_process_terminated": result.get("provider_process_terminated")}
               if isinstance(result.get("subprocess"), dict) else {}),
        }


_MANAGERS: dict[str, ConversationRequestManager] = {}
_MANAGERS_LOCK = threading.Lock()


def default_manager() -> ConversationRequestManager:
    path = str(conversation.default_db_path())
    with _MANAGERS_LOCK:
        manager = _MANAGERS.get(path)
        if manager is None:
            manager = ConversationRequestManager(conversation.default_store())
            _MANAGERS[path] = manager
        return manager


def new_client_request_id() -> str:
    return "turn_" + uuid.uuid4().hex


__all__ = [
    "ConflictingConversationRequest", "ConflictingConversationProject",
    "ConversationRequestError",
    "ConversationRequestManager", "KIND_CANCELLATION", "KIND_GENERATION",
    "UnknownConversationRequest", "default_manager", "new_client_request_id",
]

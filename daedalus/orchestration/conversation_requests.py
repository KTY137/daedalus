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


KIND_GENERATION = "conversation.generation"
KIND_CANCELLATION = "conversation.generation.cancel"
_REQUEST_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")


class ConversationRequestError(RuntimeError):
    pass


class UnknownConversationRequest(ConversationRequestError):
    pass


class ConflictingConversationRequest(ConversationRequestError):
    pass


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
                        result={"status": status})
            except Exception:
                # The generation outcome remains authoritative even if this
                # informational cancellation projection cannot be closed.
                continue

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
                    cancel_method()
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
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                    self.spine.mark_failed(request_id, "cancelled_by_user")
                    self._append_event(runtime, "cancelled", {
                        "status": "confirmed", "request_id": request_id})
                    self._resolve_cancellations(runtime, "confirmed")
                    break
                self._append_event(runtime, event, dict(data))
            else:
                if not saw_final:
                    if runtime.cancel.is_set():
                        self.spine.mark_failed(request_id, "cancelled_by_user")
                        self._append_event(runtime, "cancelled", {
                            "status": "confirmed", "request_id": request_id})
                        self._resolve_cancellations(runtime, "confirmed")
                    else:
                        self.spine.mark_failed(request_id, "stream ended without final")
                        self._append_event(runtime, "error", {
                            "error": "stream ended without final"})
                        self._resolve_cancellations(runtime, "unknown")
        except Exception as exc:
            current = self.spine.get(request_id)
            if current is not None and current.state == STATE_INTENDED:
                self.spine.mark_failed(request_id, str(exc))
            self._append_event(runtime, "error", {"error": str(exc)})
            self._resolve_cancellations(runtime, "unknown")
        finally:
            with runtime.condition:
                runtime.stream = None
                runtime.terminal = True
                runtime.condition.notify_all()

    def status(self, request_id: object) -> dict[str, Any]:
        intent = self._intent(request_id)
        runtime = self._runtime_for(intent.id)
        state = "unknown"
        final = None
        error = None
        if intent.state == STATE_COMPLETED:
            state = "final"
            final = intent.result if isinstance(intent.result, dict) else None
        elif intent.state == STATE_FAILED:
            error = intent.error
            state = "cancelled" if error == "cancelled_by_user" else "error"
        elif runtime is not None and runtime.worker is not None:
            state = "cancel_requested" if runtime.cancel.is_set() else (
                "streaming" if runtime.worker.is_alive() else "unknown")
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
            "cancellation": self._cancellation_status(intent.id),
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

    def cancel(self, request_id: object, *, client_cancel_id: object) -> dict[str, Any]:
        intent = self._intent(request_id)
        cancel_id = _check_client_id(client_cancel_id, "client_cancel_id")
        key = f"generation:{intent.id}:cancel:{cancel_id}"
        existing_rows = self.spine.intents_by_effect_key(
            key, kind=KIND_CANCELLATION, limit=1)
        if existing_rows:
            return self._cancel_projection(existing_rows[0])

        runtime = self._runtime_for(intent.id)
        if intent.state in {STATE_COMPLETED, STATE_FAILED}:
            recorded = self.spine.record_fact(
                KIND_CANCELLATION,
                {"request_id": intent.id, "client_cancel_id": cancel_id},
                effect_key=key, effect_id=str(intent.id),
                result={"status": "already_terminal"})
            return self._cancel_projection(recorded)
        if runtime is None or runtime.worker is None or not runtime.worker.is_alive():
            recorded = self.spine.record_fact(
                KIND_CANCELLATION,
                {"request_id": intent.id, "client_cancel_id": cancel_id},
                effect_key=key, effect_id=str(intent.id),
                result={"status": "unknown"})
            return self._cancel_projection(recorded)
        with runtime.condition:
            known_support = runtime.cancel_supported
        if known_support is False:
            recorded = self.spine.record_fact(
                KIND_CANCELLATION,
                {"request_id": intent.id, "client_cancel_id": cancel_id},
                effect_key=key, effect_id=str(intent.id),
                result={"status": "not_supported"})
            return self._cancel_projection(recorded)
        try:
            recorded = self.spine.record_intent(
                KIND_CANCELLATION,
                {"request_id": intent.id, "client_cancel_id": cancel_id},
                effect_key=key)
        except sqlite3.IntegrityError:
            rows = self.spine.intents_by_effect_key(
                key, kind=KIND_CANCELLATION, limit=1)
            if not rows:
                raise
            return self._cancel_projection(rows[0])
        with runtime.condition:
            runtime.cancel_intent_ids.append(recorded.id)
            support = runtime.cancel_supported
            active_stream = runtime.stream
            if support is not False:
                runtime.cancel.set()
        if support is False:
            self._resolve_cancellations(runtime, "not_supported")
        elif support is True:
            cancel_method = getattr(active_stream, "cancel", None)
            try:
                cancel_method()
            except Exception:
                runtime.cancel.clear()
                self._resolve_cancellations(runtime, "unknown")

        # Close the completion race: the worker may have reached final between
        # the first state read and registration of this cancellation intent.
        current = self.spine.get(intent.id)
        if current is not None and current.state in {STATE_COMPLETED, STATE_FAILED}:
            self._resolve_cancellations(runtime, "already_terminal")
        return self._cancel_projection(recorded)

    @staticmethod
    def _cancel_projection(intent: Intent) -> dict[str, Any]:
        result = intent.result if isinstance(intent.result, dict) else {}
        return {
            "cancellation_id": intent.id,
            "request_id": int(intent.payload["request_id"]),
            "client_cancel_id": intent.payload["client_cancel_id"],
            "status": result.get("status") or "requested",
            "created_at": intent.created_ts,
            "resolved_at": intent.resolved_ts,
        }

    def _cancellation_status(self, request_id: int) -> dict[str, Any] | None:
        for intent in self.spine.recent_intents(KIND_CANCELLATION):
            if int(intent.payload.get("request_id") or 0) == request_id:
                return self._cancel_projection(intent)
        return None


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
    "ConflictingConversationRequest", "ConversationRequestError",
    "ConversationRequestManager", "KIND_CANCELLATION", "KIND_GENERATION",
    "UnknownConversationRequest", "default_manager", "new_client_request_id",
]

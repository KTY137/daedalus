"""Loss-aware, provider-neutral runtime callback projection for Ikarus.

This is a deliberately small adaptation of a Hermes/ACP motif: callbacks from
parallel tool calls need explicit correlation, and cancellation must not make
unfinished plan entries disappear. It is not an agent loop, event store, tool
registry, provider, scheduler, or policy authority.

Adapters bind a runtime ``call_id`` to an exact declared ``plan_entry_id`` at
start. Terminal callbacks are resolved only through that call id; tool names
are never a fallback identity. The projector stores only SHA-256 observation
digests, not arbitrary provider output, and freezes all unfinished entries as
``cancelled`` when the run is cancelled.

ALIGNED: replay and decoding remain pure projections over the existing
callback contract. A digest detects inconsistency, not authenticity; callers
must resolve trusted kernel evidence and re-admit effects after a restart.
No replay method executes a tool or turns callback success into task proof.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Sequence


RUNTIME_EVENT_PROJECTION_SCHEMA = "daedalus-ikarus-runtime-event-projection/1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ROW_STATUSES = frozenset({"planned", "running", "succeeded", "failed", "cancelled"})
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
EVENT_KINDS = frozenset(
    {"tool_started", "tool_succeeded", "tool_failed", "run_cancelled"}
)


class RuntimeEventProjectionError(ValueError):
    """A callback cannot be projected without ambiguous or invalid state."""


def _id(value: Any, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise RuntimeEventProjectionError(f"{name} must match {_ID_RE.pattern!r}")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise RuntimeEventProjectionError(f"{name} must be lowercase SHA-256")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class RuntimeToolPlanEntry:
    """One logical tool call declared before callbacks begin."""

    plan_entry_id: str
    tool_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_entry_id", _id(self.plan_entry_id, "plan_entry_id"))
        object.__setattr__(self, "tool_name", _id(self.tool_name, "tool_name"))


@dataclass(frozen=True)
class RuntimeToolEvent:
    """One normalized callback observation in projector receipt order."""

    sequence: int
    kind: str
    plan_entry_id: str | None = None
    call_id: str | None = None
    tool_name: str | None = None
    observation_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise RuntimeEventProjectionError("event sequence must be non-negative int")
        if type(self.kind) is not str or self.kind not in EVENT_KINDS:
            raise RuntimeEventProjectionError("unsupported runtime event kind")
        if self.kind == "run_cancelled":
            if any(
                value is not None
                for value in (self.plan_entry_id, self.call_id, self.tool_name)
            ):
                raise RuntimeEventProjectionError(
                    "run cancellation cannot impersonate one tool call"
                )
            object.__setattr__(
                self,
                "observation_sha256",
                _sha(self.observation_sha256, "observation_sha256"),
            )
            return

        object.__setattr__(self, "plan_entry_id", _id(self.plan_entry_id, "plan_entry_id"))
        object.__setattr__(self, "call_id", _id(self.call_id, "call_id"))
        object.__setattr__(self, "tool_name", _id(self.tool_name, "tool_name"))
        if self.kind == "tool_started":
            if self.observation_sha256 is not None:
                raise RuntimeEventProjectionError(
                    "tool start cannot carry terminal observation evidence"
                )
        else:
            object.__setattr__(
                self,
                "observation_sha256",
                _sha(self.observation_sha256, "observation_sha256"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "plan_entry_id": self.plan_entry_id,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "observation_sha256": self.observation_sha256,
        }


@dataclass(frozen=True)
class RuntimeToolProjectionRow:
    """Current state of one declared plan entry."""

    plan_entry_id: str
    tool_name: str
    status: str
    call_id: str | None = None
    terminal_observation_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_entry_id", _id(self.plan_entry_id, "plan_entry_id"))
        object.__setattr__(self, "tool_name", _id(self.tool_name, "tool_name"))
        if type(self.status) is not str or self.status not in ROW_STATUSES:
            raise RuntimeEventProjectionError("unsupported projection row status")
        if self.call_id is not None:
            object.__setattr__(self, "call_id", _id(self.call_id, "call_id"))

        terminal = self.terminal_observation_sha256
        if self.status == "planned" and (self.call_id is not None or terminal is not None):
            raise RuntimeEventProjectionError("planned row cannot carry runtime identity")
        if self.status == "running" and (self.call_id is None or terminal is not None):
            raise RuntimeEventProjectionError("running row requires only call_id")
        if self.status in {"succeeded", "failed"}:
            if self.call_id is None:
                raise RuntimeEventProjectionError("completed row requires call_id")
            object.__setattr__(
                self,
                "terminal_observation_sha256",
                _sha(terminal, "terminal_observation_sha256"),
            )
        if self.status == "cancelled" and terminal is not None:
            raise RuntimeEventProjectionError(
                "cancelled row cannot fabricate terminal tool evidence"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_entry_id": self.plan_entry_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "call_id": self.call_id,
            "terminal_observation_sha256": self.terminal_observation_sha256,
        }


@dataclass(frozen=True)
class RuntimeEventProjection:
    """Immutable value snapshot; it is a projection, never event-store authority."""

    rows: tuple[RuntimeToolProjectionRow, ...]
    events: tuple[RuntimeToolEvent, ...]
    cancelled: bool

    def __post_init__(self) -> None:
        if type(self.cancelled) is not bool:
            raise RuntimeEventProjectionError("cancelled must be bool")
        # A frozen dataclass is not immutable when it retains caller-owned lists.
        # Only ordered, materialized sequences belong in a value snapshot.
        for name in ("rows", "events"):
            values = getattr(self, name)
            if type(values) not in (tuple, list):
                raise RuntimeEventProjectionError(f"{name} must be a tuple or list")
            object.__setattr__(self, name, tuple(values))
        if not self.rows:
            raise RuntimeEventProjectionError("projection cannot have an empty plan")
        if any(type(row) is not RuntimeToolProjectionRow for row in self.rows):
            raise RuntimeEventProjectionError("projection rows must use exact row type")
        if any(type(event) is not RuntimeToolEvent for event in self.events):
            raise RuntimeEventProjectionError("events must use exact event type")
        if tuple(event.sequence for event in self.events) != tuple(range(len(self.events))):
            raise RuntimeEventProjectionError("event sequence must be contiguous")
        plan_ids = tuple(row.plan_entry_id for row in self.rows)
        call_ids = tuple(row.call_id for row in self.rows if row.call_id is not None)
        if len(set(plan_ids)) != len(plan_ids):
            raise RuntimeEventProjectionError("duplicate plan_entry_id in projection")
        if len(set(call_ids)) != len(call_ids):
            raise RuntimeEventProjectionError("duplicate call_id in projection")

        cancellation_events = [e for e in self.events if e.kind == "run_cancelled"]
        if self.cancelled:
            if len(cancellation_events) != 1 or self.events[-1].kind != "run_cancelled":
                raise RuntimeEventProjectionError(
                    "cancelled projection requires one final run_cancelled event"
                )
            if any(row.status not in TERMINAL_STATUSES for row in self.rows):
                raise RuntimeEventProjectionError(
                    "cancelled projection must terminalize every plan row"
                )
        elif cancellation_events or any(row.status == "cancelled" for row in self.rows):
            raise RuntimeEventProjectionError(
                "cancelled rows/events require cancelled projection state"
            )

        # Shape-valid rows can still lie about the history. Use the live
        # transition rules rather than introducing a second state machine.
        plan = tuple(RuntimeToolPlanEntry(row.plan_entry_id, row.tool_name)
                     for row in self.rows)
        replayed = RuntimeEventProjector.from_events(plan, self.events)
        expected = tuple(replayed._rows[entry.plan_entry_id] for entry in plan)
        if self.rows != expected or self.cancelled != replayed._cancelled:
            raise RuntimeEventProjectionError("projection rows do not match event history")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RuntimeEventProjection:
        """Decode the existing /1 wire shape; reject inconsistent snapshots.

        This validates an already parsed object, not raw JSON or authenticity.
        A caller reading JSON must reject duplicate keys at its parsing boundary.
        For recovery, also bind the externally declared plan with
        ``RuntimeEventProjector.from_projection``. Neither method verifies the
        referenced observation artifacts or grants permission to repeat an effect.
        """
        fields = {"schema", "cancelled", "rows", "events", "projection_sha256"}
        if type(payload) is not dict or set(payload) != fields:
            raise RuntimeEventProjectionError("projection payload has missing or unknown fields")
        if (type(payload["schema"]) is not str
                or payload["schema"] != RUNTIME_EVENT_PROJECTION_SCHEMA):
            raise RuntimeEventProjectionError("unsupported projection schema")
        supplied_digest = _sha(payload["projection_sha256"], "projection_sha256")
        row_fields = {"plan_entry_id", "tool_name", "status", "call_id",
                      "terminal_observation_sha256"}
        event_fields = {"sequence", "kind", "plan_entry_id", "call_id", "tool_name",
                        "observation_sha256"}
        decoded = {}
        for name, keys, value_type in (
            ("rows", row_fields, RuntimeToolProjectionRow),
            ("events", event_fields, RuntimeToolEvent),
        ):
            values = payload[name]
            if type(values) is not list:
                raise RuntimeEventProjectionError(f"{name} payload must be a list")
            result = []
            for value in values:
                if type(value) is not dict or set(value) != keys:
                    raise RuntimeEventProjectionError(f"{name} item has missing or unknown fields")
                result.append(value_type(**value))
            decoded[name] = tuple(result)
        projection = cls(decoded["rows"], decoded["events"], payload["cancelled"])
        if projection.digest != supplied_digest:
            raise RuntimeEventProjectionError("projection digest does not match payload")
        return projection

    def _body(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_EVENT_PROJECTION_SCHEMA,
            "cancelled": self.cancelled,
            "rows": [row.to_dict() for row in self.rows],
            "events": [event.to_dict() for event in self.events],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self._body()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        body = self._body()
        body["projection_sha256"] = self.digest
        return body


class RuntimeEventProjector:
    """Per-run, thread-safe projector with no I/O or ambient authority."""

    def __init__(self, plan: Sequence[RuntimeToolPlanEntry]) -> None:
        if isinstance(plan, (str, bytes)):
            raise RuntimeEventProjectionError("tool plan must be a sequence")
        try:
            supplied = tuple(plan)
        except TypeError as exc:
            raise RuntimeEventProjectionError("tool plan must be iterable") from exc
        if not supplied:
            raise RuntimeEventProjectionError("tool plan cannot be empty")
        if any(type(entry) is not RuntimeToolPlanEntry for entry in supplied):
            raise RuntimeEventProjectionError("tool plan requires exact plan-entry values")

        self._plan = tuple(
            RuntimeToolPlanEntry(entry.plan_entry_id, entry.tool_name)
            for entry in supplied
        )
        ids = tuple(entry.plan_entry_id for entry in self._plan)
        if len(set(ids)) != len(ids):
            raise RuntimeEventProjectionError("duplicate plan_entry_id in tool plan")
        self._rows = {
            entry.plan_entry_id: RuntimeToolProjectionRow(
                entry.plan_entry_id, entry.tool_name, "planned"
            )
            for entry in self._plan
        }
        self._call_to_plan: dict[str, str] = {}
        self._events: list[RuntimeToolEvent] = []
        self._cancelled = False
        self._lock = threading.Lock()

    @classmethod
    def from_events(
        cls,
        plan: Sequence[RuntimeToolPlanEntry],
        events: Sequence[RuntimeToolEvent],
    ) -> RuntimeEventProjector:
        """Reconstruct callback state, not execution, from an ordered history.

        Receipt order is significant: no sorting, duplicate suppression, guessed
        tool identity, or retry. A running entry stays running/unknown until a
        trusted adapter reconciles it. This method never calls ``snapshot``;
        snapshot validation uses it and must not recurse.
        """
        if type(plan) not in (tuple, list):
            raise RuntimeEventProjectionError("replay plan must be a tuple or list")
        if type(events) not in (tuple, list):
            raise RuntimeEventProjectionError("events must be a tuple or list")
        supplied = tuple(events)
        if any(type(event) is not RuntimeToolEvent for event in supplied):
            raise RuntimeEventProjectionError("events must use exact event type")
        if any(event.sequence != index for index, event in enumerate(supplied)):
            raise RuntimeEventProjectionError("event sequence must be contiguous")
        projector = cls(plan)
        # A declared entry starts at most once and has at most one terminal
        # callback; at most one cancellation may follow. This is a contract
        # cardinality check, not an execution-resource limit or new policy.
        if len(supplied) > 2 * len(projector._plan) + 1:
            raise RuntimeEventProjectionError("event count exceeds the declared plan")
        for event in supplied:
            if event.kind == "tool_started":
                reproduced = projector.start(
                    plan_entry_id=event.plan_entry_id,
                    call_id=event.call_id,
                    tool_name=event.tool_name,
                )
            elif event.kind in {"tool_succeeded", "tool_failed"}:
                reproduced = projector.finish(
                    call_id=event.call_id,
                    tool_name=event.tool_name,
                    outcome=event.kind.removeprefix("tool_"),
                    observation_sha256=event.observation_sha256,
                )
            elif event.kind == "run_cancelled":
                reproduced = projector.cancel(reason_sha256=event.observation_sha256)
            else:
                raise RuntimeEventProjectionError("unsupported runtime event kind")
            # finish() resolves plan identity by call id. Compare the WHOLE
            # event to reject a forged terminal plan_entry_id too.
            if reproduced != event:
                raise RuntimeEventProjectionError("event does not match its bound callback")
        return projector

    @classmethod
    def from_projection(
        cls,
        plan: Sequence[RuntimeToolPlanEntry],
        projection: RuntimeEventProjection,
    ) -> RuntimeEventProjector:
        """Restore only against the exact external plan, including its order.

        Never infer the recovery plan from the snapshot itself: an otherwise
        consistent snapshot may have omitted an unstarted task. Canonical
        Mission/Attempt/revision and evidence admission remain the caller's job.
        """
        if type(projection) is not RuntimeEventProjection:
            raise RuntimeEventProjectionError("projection must use exact projection type")
        projector = cls.from_events(plan, projection.events)
        expected = tuple(projector._rows[entry.plan_entry_id] for entry in projector._plan)
        if projection.rows != expected or projection.cancelled != projector._cancelled:
            raise RuntimeEventProjectionError("projection does not match the declared plan")
        return projector

    def _open(self) -> None:
        if self._cancelled:
            raise RuntimeEventProjectionError("projection is closed by cancellation")

    def start(
        self, *, plan_entry_id: str, call_id: str, tool_name: str
    ) -> RuntimeToolEvent:
        """Bind a runtime call to one exact planned entry."""

        plan_entry_id = _id(plan_entry_id, "plan_entry_id")
        call_id = _id(call_id, "call_id")
        tool_name = _id(tool_name, "tool_name")
        with self._lock:
            self._open()
            row = self._rows.get(plan_entry_id)
            if row is None:
                raise RuntimeEventProjectionError(f"unknown plan entry {plan_entry_id!r}")
            if row.status != "planned":
                raise RuntimeEventProjectionError("plan entry already started or terminal")
            if row.tool_name != tool_name:
                raise RuntimeEventProjectionError(
                    "tool name does not match declared plan entry"
                )
            if call_id in self._call_to_plan:
                raise RuntimeEventProjectionError(f"call_id {call_id!r} already bound")

            replacement = RuntimeToolProjectionRow(
                row.plan_entry_id, row.tool_name, "running", call_id
            )
            event = RuntimeToolEvent(
                len(self._events), "tool_started", row.plan_entry_id, call_id, row.tool_name
            )
            self._rows[row.plan_entry_id] = replacement
            self._call_to_plan[call_id] = row.plan_entry_id
            self._events.append(event)
            return event

    def finish(
        self,
        *,
        call_id: str,
        tool_name: str,
        outcome: str,
        observation_sha256: str,
    ) -> RuntimeToolEvent:
        """Terminalize by exact call id; never infer identity from tool name."""

        call_id = _id(call_id, "call_id")
        tool_name = _id(tool_name, "tool_name")
        observation_sha256 = _sha(observation_sha256, "observation_sha256")
        if type(outcome) is not str or outcome not in {"succeeded", "failed"}:
            raise RuntimeEventProjectionError("outcome must be 'succeeded' or 'failed'")

        with self._lock:
            self._open()
            plan_entry_id = self._call_to_plan.get(call_id)
            if plan_entry_id is None:
                raise RuntimeEventProjectionError(f"call_id {call_id!r} was never started")
            row = self._rows[plan_entry_id]
            if row.status != "running" or row.call_id != call_id:
                raise RuntimeEventProjectionError("call is not in running state")
            if row.tool_name != tool_name:
                raise RuntimeEventProjectionError(
                    "terminal tool name does not match bound call"
                )

            replacement = RuntimeToolProjectionRow(
                row.plan_entry_id,
                row.tool_name,
                outcome,
                call_id,
                observation_sha256,
            )
            event = RuntimeToolEvent(
                len(self._events),
                f"tool_{outcome}",
                row.plan_entry_id,
                call_id,
                row.tool_name,
                observation_sha256,
            )
            self._rows[row.plan_entry_id] = replacement
            self._events.append(event)
            return event

    def cancel(self, *, reason_sha256: str) -> RuntimeToolEvent:
        """Freeze every unfinished entry as cancelled without dropping it."""

        reason_sha256 = _sha(reason_sha256, "reason_sha256")
        with self._lock:
            self._open()
            replacements = {
                entry.plan_entry_id: (
                    self._rows[entry.plan_entry_id]
                    if self._rows[entry.plan_entry_id].status in TERMINAL_STATUSES
                    else RuntimeToolProjectionRow(
                        entry.plan_entry_id,
                        entry.tool_name,
                        "cancelled",
                        self._rows[entry.plan_entry_id].call_id,
                    )
                )
                for entry in self._plan
            }
            event = RuntimeToolEvent(
                len(self._events),
                "run_cancelled",
                observation_sha256=reason_sha256,
            )
            self._rows.update(replacements)
            self._events.append(event)
            self._cancelled = True
            return event

    def snapshot(self) -> RuntimeEventProjection:
        """Return an immutable snapshot in declared plan order."""

        with self._lock:
            return RuntimeEventProjection(
                rows=tuple(self._rows[e.plan_entry_id] for e in self._plan),
                events=tuple(self._events),
                cancelled=self._cancelled,
            )


__all__ = [
    "RUNTIME_EVENT_PROJECTION_SCHEMA",
    "RuntimeEventProjection",
    "RuntimeEventProjectionError",
    "RuntimeEventProjector",
    "RuntimeToolEvent",
    "RuntimeToolPlanEntry",
    "RuntimeToolProjectionRow",
]

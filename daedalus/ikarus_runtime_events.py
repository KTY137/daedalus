# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
        if self.kind not in EVENT_KINDS:
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
        if self.status not in ROW_STATUSES:
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
        if outcome not in {"succeeded", "failed"}:
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

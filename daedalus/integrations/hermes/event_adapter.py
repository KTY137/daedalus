"""Loss-aware event normalization for Hermes worker observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Mapping


class HermesEventError(ValueError):
    pass


@dataclass(frozen=True)
class HermesRuntimeEvent:
    sequence: int
    kind: str
    request_id: str
    task_id: str
    call_id: str = ""
    name: str = ""
    digest: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class HermesEventLedger:
    def __init__(self) -> None:
        self._events: list[HermesRuntimeEvent] = []
        self._open_calls: dict[str, str] = {}
        self._terminal = False

    @property
    def events(self) -> tuple[HermesRuntimeEvent, ...]:
        return tuple(self._events)

    def append_message(self, message: Mapping[str, object]) -> HermesRuntimeEvent:
        sequence = int(message["sequence"])
        if sequence != len(self._events):
            raise HermesEventError("Hermes event sequence is not contiguous")
        kind = str(message["type"])
        if self._terminal:
            raise HermesEventError("event arrived after terminal Hermes event")
        call_id = str(message.get("call_id", ""))
        name = str(message.get("name", ""))
        if kind == "tool_call":
            if call_id in self._open_calls:
                raise HermesEventError("duplicate Hermes tool call id")
            self._open_calls[call_id] = name
        elif kind == "tool_result":
            if self._open_calls.get(call_id) != name:
                raise HermesEventError("Hermes tool result does not match an open call")
            del self._open_calls[call_id]
        elif kind in {"final", "failure"}:
            if self._open_calls:
                raise HermesEventError("Hermes terminated while tool calls remained open")
            self._terminal = True
        encoded = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        event = HermesRuntimeEvent(
            sequence=sequence,
            kind=kind,
            request_id=str(message["request_id"]),
            task_id=str(message["task_id"]),
            call_id=call_id,
            name=name,
            digest=sha256(encoded).hexdigest(),
        )
        self._events.append(event)
        return event

    @property
    def terminal(self) -> bool:
        return self._terminal

    @property
    def digest(self) -> str:
        encoded = json.dumps([event.to_dict() for event in self._events], sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()

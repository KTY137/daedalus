from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Union, Any, Dict

@dataclass
class AgentCapabilities:
    streaming: bool = False
    resume: bool = False
    hidden_state_access: bool = False

@dataclass
class SessionStarted:
    session_id: str


@dataclass
class SessionEnded:
    session_id: str
    exit_code: int
    stderr: str = ""

@dataclass
class TextDelta:
    text: str

@dataclass
class ToolRequested:
    tool_name: str
    arguments: Dict[str, Any]
    call_id: str

@dataclass
class ToolCompleted:
    call_id: str
    result: Any
    is_error: bool = False

@dataclass
class FileRead:
    path: str
    content: str

@dataclass
class CommandOutput:
    command: str
    output: str
    exit_code: int

@dataclass
class AgentMessage:
    content: str
    role: str = "assistant"

AgentEvent = Union[
    SessionStarted,
    SessionEnded,
    TextDelta,
    ToolRequested,
    ToolCompleted,
    FileRead,
    CommandOutput,
    AgentMessage
]


_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


@dataclass(frozen=True)
class TransportRecord:
    """Lossless envelope exchanged between a runtime shell and downstream sinks.

    Embeddings are derived from this record; they never replace its original
    payload or provenance.
    """

    record_id: str
    session_id: str
    runtime: str
    direction: str
    sequence: int
    event_type: str
    timestamp: str
    content: str
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransportRecord":
        return cls(
            record_id=str(data["record_id"]),
            session_id=str(data["session_id"]),
            runtime=str(data["runtime"]),
            direction=str(data["direction"]),
            sequence=int(data["sequence"]),
            event_type=str(data["event_type"]),
            timestamp=str(data["timestamp"]),
            content=str(data.get("content") or ""),
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def embedding_text(self) -> str:
        """Stable text projection used by an optional embedding index."""
        return (
            f"[{self.runtime}/{self.direction}/{self.event_type}] "
            f"{self.content}"
        ).strip()


def event_to_transport_record(
    event: AgentEvent,
    *,
    session_id: str,
    runtime: str,
    direction: str,
    sequence: int,
    metadata: Dict[str, Any] | None = None,
) -> TransportRecord:
    """Wrap one typed event without discarding its provider-neutral payload."""
    if direction not in {"input", "output", "system"}:
        raise ValueError("direction must be input, output, or system")
    payload = asdict(event)
    event_type = _CAMEL_BOUNDARY.sub("_", type(event).__name__).lower()

    if isinstance(event, (TextDelta, AgentMessage)):
        content = event.text if isinstance(event, TextDelta) else event.content
    elif isinstance(event, ToolRequested):
        content = f"{event.tool_name} {json.dumps(event.arguments, default=str)}"
    elif isinstance(event, ToolCompleted):
        content = json.dumps(event.result, default=str)
    elif isinstance(event, FileRead):
        content = f"{event.path}\n{event.content}"
    elif isinstance(event, CommandOutput):
        content = f"{event.command}\n{event.output}"
    elif isinstance(event, SessionEnded):
        content = f"exit_code={event.exit_code}\n{event.stderr}".strip()
    else:
        content = json.dumps(payload, default=str)

    return TransportRecord(
        record_id=f"{session_id}:{direction}:{sequence:08d}",
        session_id=session_id,
        runtime=runtime,
        direction=direction,
        sequence=sequence,
        event_type=event_type,
        timestamp=datetime.now(timezone.utc).isoformat(),
        content=str(content),
        payload=payload,
        metadata=dict(metadata or {}),
    )

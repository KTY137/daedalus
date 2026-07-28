"""
Daedalus Adapters — universal interface for CLI agent runtimes.

Usage:
    from daedalus.adapters import SubprocessAdapter, RUNTIME_PROFILES

    # Pre-built profiles
    adapter = SubprocessAdapter.claude(repo_root="/my/repo")
    adapter = SubprocessAdapter.codex(repo_root="/my/repo")
    adapter = SubprocessAdapter.from_name("claude", repo_root="/my/repo")

    # Custom runtime
    from daedalus.adapters.subprocess_adapter import RuntimeConfig
    adapter = SubprocessAdapter(config=RuntimeConfig(command="my-agent"))
"""

from .base import AgentAdapter
from .events import (
    AgentCapabilities,
    AgentEvent,
    SessionEnded,
    TransportRecord,
    event_to_transport_record,
)
from .subprocess_adapter import SubprocessAdapter, RuntimeConfig, RUNTIME_PROFILES
from .transport import (
    CompositeTransportSink,
    InMemoryTransportSink,
    JsonlTransportSink,
    TransportSink,
)

__all__ = [
    "AgentAdapter",
    "AgentCapabilities",
    "AgentEvent",
    "SessionEnded",
    "TransportRecord",
    "event_to_transport_record",
    "TransportSink",
    "CompositeTransportSink",
    "InMemoryTransportSink",
    "JsonlTransportSink",
    "SubprocessAdapter",
    "RuntimeConfig",
    "RUNTIME_PROFILES",
]

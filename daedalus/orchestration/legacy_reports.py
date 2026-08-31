"""Legacy task and run projections owned by orchestration.

These records remain wire-compatible exports of :mod:`daedalus.schemas`, but
they are not kernel contracts and do not participate in kernel contract
parsing, evidence identity, or promotion. Provider report contracts are
runtime-owned and reexported here only for import compatibility.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from daedalus.runtimes.contracts.provider_report import (
    REPORT_KEYS,
    AgentReport,
    validate_report,
)


@dataclass
class AgentTask:
    task_id: str
    agent: str
    objective: str
    repo_root: str
    paths: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)

    def brief(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "repo_root": self.repo_root,
            "objective": self.objective,
            "paths": self.paths,
            "context": self.context,
            "constraints": self.constraints,
            "return": "agent_report_v1 JSON only",
        }


@dataclass
class RunState:
    run_id: str
    objective: str
    repo_root: str
    active_agent: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    paths: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    open_todos: list[str] = field(default_factory=list)
    test_results: list[str] = field(default_factory=list)
    risk_level: str = "unknown"

    def add_event(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "payload": payload,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

__all__ = ["AgentReport", "AgentTask", "REPORT_KEYS", "RunState", "validate_report"]

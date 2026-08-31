"""Legacy agent task/report projections owned by orchestration.

These records remain wire-compatible exports of :mod:`daedalus.schemas`, but
they are not kernel contracts and do not participate in kernel contract
parsing, evidence identity, or promotion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


REPORT_KEYS = {
    "status",
    "summary",
    "files_changed",
    "tests_run",
    "risks",
    "todos",
    "handoff",
}


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
class AgentReport:
    status: str
    summary: str
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)
    handoff: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def validate_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = REPORT_KEYS - set(report)
    extra = set(report) - REPORT_KEYS
    if missing:
        errors.append(f"missing keys: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"extra keys: {', '.join(sorted(extra))}")
    if report.get("status") not in {"done", "blocked", "needs_review", "failed"}:
        errors.append("status must be one of: done, blocked, needs_review, failed")
    summary = report.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 600:
        errors.append("summary must be a non-empty string no longer than 600 characters")
    for key in ("files_changed", "tests_run", "risks", "todos"):
        if key in report and not isinstance(report[key], list):
            errors.append(f"{key} must be a list")
    if "handoff" in report and not isinstance(report["handoff"], dict):
        errors.append("handoff must be an object")
    return errors


__all__ = ["AgentReport", "AgentTask", "REPORT_KEYS", "RunState", "validate_report"]

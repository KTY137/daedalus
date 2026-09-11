"""Canonical report contract returned by provider runtimes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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


__all__ = ["AgentReport", "REPORT_KEYS", "validate_report"]

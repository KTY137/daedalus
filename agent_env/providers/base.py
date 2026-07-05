from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderCapabilities:
    """What a provider is *allowed* and *able* to do. These are structural
    guarantees enforced by the harness, not promises the model must keep."""

    name: str
    can_write: bool         # may mutate the repo (apply edits / run tools)
    local: bool             # runs on this machine; no network egress at all
    trusted_with_ip: bool   # approved to receive proprietary/sensitive source
    agentic: bool           # can read the repo itself vs. needs inlined context


class Provider(abc.ABC):
    """Common interface for every model backend. All providers return the same
    validated ``agent_report_v1`` dict so everything downstream is uniform."""

    caps: ProviderCapabilities

    @abc.abstractmethod
    def available(self) -> bool:
        """True if this provider can be reached right now (key set / server up)."""

    @abc.abstractmethod
    def run(
        self,
        *,
        objective: str,
        repo_root: str,
        paths: list[str],
        agent: dict[str, Any],
        model: str | None = None,
        timeout_s: int = 300,
        policy: Any | None = None,
    ) -> dict[str, Any]:
        """Execute the task and return {"provider", "agent", "report"}."""

    # -- shared helpers ---------------------------------------------------

    def _enforce_read_only(self, report: dict[str, Any]) -> dict[str, Any]:
        """A read-only provider can neither edit files nor run tests. Any change
        it proposes is advisory: it is moved into ``handoff.suggestions`` and the
        mutating fields are forced empty so nothing can be auto-applied."""
        if self.caps.can_write:
            return report
        proposed = report.get("files_changed") or []
        handoff = report.get("handoff") or {}
        if proposed:
            handoff = {**handoff, "suggested_files": proposed}
        report["handoff"] = handoff
        report["files_changed"] = []
        report["tests_run"] = []
        if report.get("status") == "done":
            # A model that cannot write cannot legitimately be "done" applying a
            # change; downgrade to advisory review.
            report["status"] = "needs_review"
        return report

from __future__ import annotations

import shutil
from typing import Any

from ..claude_bridge import ask_claude
from .base import Provider, ProviderCapabilities


class ClaudeCLIProvider(Provider):
    """Primary lane: the agentic, write-capable, trusted Claude CLI."""

    caps = ProviderCapabilities(
        name="claude_cli",
        can_write=True,
        local=False,
        trusted_with_ip=True,
        agentic=True,
    )

    def available(self) -> bool:
        return shutil.which("claude") is not None

    def run(
        self,
        *,
        objective: str,
        repo_root: str,
        paths: list[str],
        agent: dict[str, Any],
        model: str | None = None,
        timeout_s: int = 300,
        policy: Any | None = None,  # unused: Claude is agentic + trusted
    ) -> dict[str, Any]:
        result = ask_claude(
            objective=objective,
            repo_root=repo_root,
            paths=paths,
            model=model or agent.get("model_tier", "sonnet"),
            timeout_s=timeout_s,
        )
        return {
            "provider": self.caps.name,
            "agent": result["agent"],
            "report": result["report"],
        }

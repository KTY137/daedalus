from __future__ import annotations

from typing import Any


DEFAULT_POLICY: dict[str, Any] = {
    "claude": "optional",
    "codex": "primary",
    "on_claude_blocked": "continue_with_codex_and_record_retry_todo",
    "on_codex_unavailable": "claude_reads_memory_and_repo_status",
    "review_gate": "prefer_claude_review_for_risky_changes_but_do_not_block_low_risk_fixes",
}


def fallback_decision(
    claude_status: str | None,
    risk_level: str = "normal",
    user_requires_claude: bool = False,
) -> dict[str, Any]:
    """Decide whether work can continue when Claude is missing or blocked."""
    if claude_status in {"done", "needs_review"}:
        return {
            "mode": "collaborative",
            "continue": True,
            "reason": "Claude produced a usable report.",
            "todo": None,
        }

    if user_requires_claude:
        return {
            "mode": "blocked",
            "continue": False,
            "reason": "User explicitly required Claude participation.",
            "todo": "Retry when Claude is available.",
        }

    if risk_level in {"safety", "high"}:
        return {
            "mode": "codex_cautious",
            "continue": True,
            "reason": "Claude unavailable; Codex may continue only with extra tests/review notes.",
            "todo": "Run Claude review before final merge if available.",
        }

    return {
        "mode": "codex_solo",
        "continue": True,
        "reason": "Claude unavailable; work may continue with local tests and memory logging.",
        "todo": "Retry Claude second opinion later if useful.",
    }

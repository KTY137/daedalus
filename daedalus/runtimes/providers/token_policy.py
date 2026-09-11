"""Runtime-owned prompt and token-shaping policy for provider calls."""

from __future__ import annotations

from daedalus.kernel.policy.limits import (
    ExecutionLimitPolicy,
    load_from_env as load_limit_policy,
)


MAX_SUMMARY_CHARS = 600
MAX_TODO_CHARS = 180
MAX_PATHS_PER_REQUEST = 12
DEFAULT_MODEL = "sonnet"
HIGH_RISK_MODEL = "opus"
CHEAP_MODEL = "haiku"

STATIC_PROMPT_PREFIX = """Daedalus Bridge Protocol v1.

Minimize tokens:
- Use the supplied paths instead of exploring the whole repo.
- Read only files needed for this task.
- Return compact structured JSON only.
- No conversational intro, praise, or markdown.
- No full code dumps unless explicitly requested.
- Prefer file:line references and short summaries.
- Do not include chain-of-thought; include only conclusions and evidence.
"""


def trim_paths(
    paths: list[str],
    limit: int = MAX_PATHS_PER_REQUEST,
    *,
    limit_policy: ExecutionLimitPolicy | None = None,
) -> list[str]:
    """Deduplicate request paths and apply the captured work-scope policy."""

    policy = limit_policy or load_limit_policy()
    if not isinstance(policy, ExecutionLimitPolicy):
        raise TypeError("limit_policy must be an ExecutionLimitPolicy")
    unique = list(dict.fromkeys(paths))
    return unique[:limit] if policy.enforces("work_scope") else unique


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


__all__ = [
    "CHEAP_MODEL",
    "DEFAULT_MODEL",
    "HIGH_RISK_MODEL",
    "MAX_PATHS_PER_REQUEST",
    "MAX_SUMMARY_CHARS",
    "MAX_TODO_CHARS",
    "STATIC_PROMPT_PREFIX",
    "ExecutionLimitPolicy",
    "load_limit_policy",
    "trim_paths",
    "trim_text",
]

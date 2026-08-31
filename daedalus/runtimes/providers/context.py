"""Provider context preparation behind injected sensitivity and graph ports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from daedalus.kernel.policy.limits import ExecutionLimitPolicy

from .execution_policy import bounded_execution_limit_policy


ReadContextPort = Callable[..., tuple[str, list[str]]]
RenderBriefPort = Callable[..., str]
GraphBriefPort = Callable[..., Any]


def read_provider_context(
    paths: list[str],
    repo_root: str,
    *,
    max_chars: int,
    allow_sensitive: bool,
    sensitivity_policy: Any | None,
    execution_limit_policy: ExecutionLimitPolicy | None,
    read_inlined_context: ReadContextPort,
) -> tuple[str, list[str]]:
    """Read context through the injected canonical sensitivity port."""

    resolved = bounded_execution_limit_policy(execution_limit_policy)
    capacity = max_chars
    if not resolved.enforces("tokens"):
        root = Path(repo_root)
        capacity = 1
        for raw in paths:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                data = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            capacity += len(f"\n===== FILE: {raw} =====\n") + len(data)
    return read_inlined_context(
        paths,
        repo_root,
        capacity,
        allow_sensitive=allow_sensitive,
        policy=sensitivity_policy,
    )


def render_provider_brief(
    repo_root: str,
    paths: list[str],
    *,
    bounded_chars: int,
    execution_limit_policy: ExecutionLimitPolicy | None,
    render_brief: RenderBriefPort,
    graph_brief: GraphBriefPort,
) -> str:
    """Render bounded or complete graph context through injected read ports."""

    resolved = bounded_execution_limit_policy(execution_limit_policy)
    if resolved.enforces("tokens"):
        return render_brief(
            repo_root, paths, hops=1, budget_chars=bounded_chars
        )
    capacity = max(1, bounded_chars)
    try:
        while True:
            result = graph_brief(
                repo_root, paths, hops=1, budget_chars=capacity
            )
            if not result.truncated:
                return result.text
            capacity *= 2
    except Exception:  # noqa: BLE001 -- optional context, never an admission gate
        return ""


__all__ = [
    "GraphBriefPort",
    "ReadContextPort",
    "RenderBriefPort",
    "read_provider_context",
    "render_provider_brief",
]

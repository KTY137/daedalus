"""Compatibility and context facade for runtime-owned provider helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..kernel.policy.ledger import BudgetRefused, Reservation, reserve
from ..kernel.policy.limits import (
    ExecutionLimitPolicy,
    LimitPolicyError,
    load_from_env,
)
from ..kernel.policy.pricing import BudgetError
from ..lanes import graph_brief, render_brief
from ..runtimes.contracts.provider_report import REPORT_KEYS, validate_report
from ..runtimes.providers.budget_admission import (
    budget_refusal_report,
    reserve_or_report,
)
from ..runtimes.providers.execution_policy import (
    admit_execution_limit_policy,
    attempt_numbers,
    bounded_execution_limit_policy,
    provider_http_timeout,
)
from ..runtimes.providers.reporting import (
    _INVALID_ESCAPE_RE,
    _loads_or_repair,
    blocked_report,
    build_prompt,
    coerce_report,
    extract_json,
    report_instructions,
)
from ..runtimes.providers.token_policy import (
    MAX_SUMMARY_CHARS,
    STATIC_PROMPT_PREFIX,
)


# Total inlined-context budget for non-agentic providers (chars). Keeps prompts
# small per the token-efficiency rules; sensitive files are excluded upstream.
MAX_CONTEXT_CHARS = 24_000


def read_provider_context(
    paths: list[str],
    repo_root: str,
    *,
    max_chars: int,
    allow_sensitive: bool,
    sensitivity_policy: Any | None,
    execution_limit_policy: ExecutionLimitPolicy | None,
) -> tuple[str, list[str]]:
    """Read provider context while retaining the canonical sensitivity gate.

    With token limits disabled, the capacity passed to
    :func:`read_inlined_context` is derived from the complete readable inputs;
    it is not an arbitrary numeric substitute for infinity.  The canonical
    secret/egress checks still decide which of those inputs may be returned.
    """

    from ..sensitivity import read_inlined_context

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
) -> str:
    """Render the normal bounded brief or the complete graph brief.

    The unlimited branch grows an explicit working capacity until the graph
    builder reports that it omitted nothing.  It therefore has a terminating
    completeness condition rather than a fake numerical "unlimited" value.
    """

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

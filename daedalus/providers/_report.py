"""Compatibility and context facade for runtime-owned provider helpers."""

from __future__ import annotations

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
from ..runtimes.providers.context import (
    read_provider_context as _read_provider_context,
    render_provider_brief as _render_provider_brief,
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
    """Inject the current sensitivity port into the runtime context owner."""
    from ..sensitivity import read_inlined_context

    return _read_provider_context(
        paths,
        repo_root,
        max_chars=max_chars,
        allow_sensitive=allow_sensitive,
        sensitivity_policy=sensitivity_policy,
        execution_limit_policy=execution_limit_policy,
        read_inlined_context=read_inlined_context,
    )


def render_provider_brief(
    repo_root: str,
    paths: list[str],
    *,
    bounded_chars: int,
    execution_limit_policy: ExecutionLimitPolicy | None,
) -> str:
    """Inject the current graph ports into the runtime context owner."""

    return _render_provider_brief(
        repo_root,
        paths,
        bounded_chars=bounded_chars,
        execution_limit_policy=execution_limit_policy,
        render_brief=render_brief,
        graph_brief=graph_brief,
    )

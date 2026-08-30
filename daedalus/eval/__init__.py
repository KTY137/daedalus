"""daedalus.eval -- private, evidence-conscious distillation evaluation.

Tier 1 and the deterministic A/B/C retrieval comparison live in
``daedalus.eval.harness``. Tier 2 is opt-in and now uses explicit semantic
validators plus structured provider receipts from ``daedalus.eval.tier2`` so
transport failures, truncated outputs, and missing validators cannot masquerade
as ordinary wrong model answers.

This remains a private directional eval, not SWE-bench.
"""
from __future__ import annotations

from .tasks import TASKS, resolve_task_repo
from . import harness as harness
from . import report as report
from . import tier2 as tier2

run_tier1 = harness.run_tier1


def run_tier2(
    tasks: list[dict] | None = None,
    provider: str | None = None,
    cap_tokens: int = 120_000,
) -> dict:
    """Package-level delegate to the live canonical Tier-2 implementation."""

    return tier2.run_tier2(tasks, provider, cap_tokens)

__all__ = ["TASKS", "resolve_task_repo", "run_tier1", "run_tier2"]

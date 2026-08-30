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

# Backward-compatible strangler seam. Existing code imports
# ``daedalus.eval.harness.run_tier2`` and tests call ``harness._score`` directly.
# Keep those names working while tier2.py becomes the single owner of live-model
# scoring and provider-integrity semantics.
harness._score = tier2._score
harness._ask = tier2._ask
harness.run_tier2 = tier2.run_tier2
report.render_tier2 = tier2.render_tier2

run_tier1 = harness.run_tier1
run_tier2 = tier2.run_tier2

__all__ = ["TASKS", "resolve_task_repo", "run_tier1", "run_tier2"]

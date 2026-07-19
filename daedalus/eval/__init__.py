"""daedalus.eval -- a small, private eval harness for the distillation thesis.

The claim under test: a *distilled semantic slice* (the focus symbol/file plus
its dependency + caller neighborhood) carries enough context to act on a target
at a fraction of the tokens of a naive whole-repo concatenation (Repomix /
Gitingest style). "Distillation beats concatenation."

This is a **private, directional** eval, NOT SWE-bench. Two tiers:

  * Tier 1 (deterministic, no LLM -- the rigorous core): for each labelled task
    measure slice **recall** (did the distilled slice actually contain the
    symbols a competent answer needs?) and **compression** (how much smaller than
    the whole repo?). Recall is *necessary, not sufficient* -- it proves the
    slice didn't drop load-bearing context.

  * Tier 2 (opt-in, needs a runtime): ask the same question against the distilled
    slice (A) and against the whole-repo concat (B) via a model, and compare
    task-success and tokens. The win is A ~= B success at a fraction of B's
    tokens. Gated: skipped cleanly when no provider is available.

Isolated package: imports structcore's stable public API; never mutates it.
"""
from __future__ import annotations

from .tasks import TASKS, resolve_task_repo
from .harness import run_tier1, run_tier2

__all__ = ["TASKS", "resolve_task_repo", "run_tier1", "run_tier2"]

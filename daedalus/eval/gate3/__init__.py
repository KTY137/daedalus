"""Gate-3 baseline harness (packet G3-BASE-01) -- EXPERIMENT, Gate-3 prework.

The active delivery gate is **1**. This package builds the measurement
instrument Gate 3 will require; it does not open, enter, or satisfy Gate 3, and
no value it produces is Gate-3 baseline evidence until an owner seals the
harness (plan §11, Gate 3: "Only after that baseline harness is sealed").

It EXTENDS ``daedalus.eval``; it does not fork it. BM25, per-provenance-tier
aggregation, the tokenizer, the regression ratchet and the budget-equality
primitive already live in ``daedalus.eval.harness`` and are reused from there.

Layout:
  contracts.py -- the six freeze obligations + RunManifest (the seal)
  protocols.py -- Task, SealedEvaluator, Arm, run_trial
  arms/        -- the eleven required baselines, one module each
  measures.py  -- the nine required measures
"""
from __future__ import annotations

from .contracts import (
    PLANES,
    ArmBudget,
    EvaluatorVersion,
    FreezeError,
    FrozenTaskSet,
    RunEnvironment,
    RunManifest,
    SeedPolicy,
    TrialResult,
    canonical_digest,
    partition_trials,
    require_equal_budgets,
)
from .protocols import Arm, ArmOutcome, SealedEvaluator, Task, run_arm_over_tasks, run_trial

__all__ = [
    "PLANES",
    "Arm",
    "ArmBudget",
    "ArmOutcome",
    "EvaluatorVersion",
    "FreezeError",
    "FrozenTaskSet",
    "RunEnvironment",
    "RunManifest",
    "SealedEvaluator",
    "SeedPolicy",
    "Task",
    "TrialResult",
    "canonical_digest",
    "partition_trials",
    "require_equal_budgets",
    "run_arm_over_tasks",
    "run_trial",
]

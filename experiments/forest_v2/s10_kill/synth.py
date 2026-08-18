"""Synthetic result sets for the self-test.

The evaluator's own correctness has the same problem as the thing it grades:
you cannot check a kill detector against real data whose answer you do not
know.  So the self-test builds runs whose ground truth is constructed --
"here the treatment really is better by 0.15", "here the control really is
identical" -- and asks whether the verdicts come out the way the plan says
they should.

Every score is *drawn at runtime* from a seeded PRNG.  Nothing in this file
is a fixture table of magic numbers, and the seeds are ordinary integers.

Scores are paired by construction: each case gets one latent difficulty, and
every arm is that difficulty plus its own effect plus noise.  That mirrors
the real structure (arms are correlated across cases) and is what makes the
paired bootstrap the right interval.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence

from . import SCHEMA_ID


@dataclass(frozen=True)
class ArmSpec:
    """One arm's ground truth: how much better than the latent base it is."""

    role: str
    effect: float = 0.0
    variant: str = "raw"
    budget_tokens: float = 4096.0
    cost_units: float = 1.0
    #: per-case-group effect overrides, e.g. {"held_out": 0.0}
    group_effects: Mapping[str, float] = field(default_factory=dict)

    @property
    def arm_id(self) -> str:
        return f"{self.role}/{self.variant}"


def make_run(
    run_id: str,
    specs: Sequence[ArmSpec],
    *,
    n_cases: int = 40,
    seed: int = 1,
    noise: float = 0.02,
    seeds: int = 8,
    with_groups: bool = False,
    primary_metric: str = "recall@10",
) -> Dict[str, object]:
    """Build a wire-form result set with known ground truth."""
    rng = random.Random(seed)
    cases = [f"case{i:04d}" for i in range(n_cases)]
    # One latent difficulty per case, shared by every arm.
    base = {c: rng.uniform(0.15, 0.75) for c in cases}

    groups: Dict[str, List[str]] = {}
    membership: Dict[str, str] = {}
    if with_groups:
        half = max(1, n_cases // 2)
        groups = {"in_domain": cases[:half], "held_out": cases[half:]}
        for name, members in groups.items():
            for c in members:
                membership[c] = name

    arms = []
    for spec in specs:
        scores: Dict[str, float] = {}
        for c in cases:
            effect = spec.effect
            group = membership.get(c)
            if group is not None and group in spec.group_effects:
                effect = spec.group_effects[group]
            val = base[c] + effect + rng.gauss(0.0, noise)
            scores[c] = min(1.0, max(0.0, val))
        arms.append(
            {
                "arm_id": spec.arm_id,
                "role": spec.role,
                "variant": spec.variant,
                "budget_tokens": spec.budget_tokens,
                "cost_units": spec.cost_units,
                "scores": {primary_metric: scores},
            }
        )

    return {
        "schema": SCHEMA_ID,
        "run_id": run_id,
        "source": "synthetic ground truth (experiments/forest_v2/s10_kill/synth.py)",
        "seeds": seeds,
        "primary_metric": primary_metric,
        "cases": cases,
        "case_groups": groups,
        "arms": arms,
    }


# ------------------------------------------------------------- scenarios

WIN = 0.15      # an effect far larger than the practical margin
SMALL = 0.004   # a real but practically irrelevant effect (inside the margin)


def scenario_surviving_prior(seed: int = 11) -> Dict[str, object]:
    """Every decidable criterion should pass: the prior survives this run."""
    return make_run(
        "synthetic-surviving-prior",
        [
            ArmSpec("full", WIN, cost_units=1.4),
            ArmSpec("code_only", 0.0, cost_units=1.0),
            ArmSpec("bm25", 0.01, cost_units=1.0),
            ArmSpec("rewired", 0.02),
            ArmSpec("separate_indices", 0.03),
            ArmSpec("ablate:code", 0.02),
            ArmSpec("ablate:type", 0.05),
            ArmSpec("ablate:data", 0.06),
            ArmSpec("ablate:knowledge", 0.04),
            ArmSpec("graph_priority", WIN),
            ArmSpec("random_priority", 0.0),
            ArmSpec("evaluator_only", 0.02),
            ArmSpec("token_matched", 0.03),
            ArmSpec("full", WIN - 0.01, variant="scrubbed"),
            ArmSpec("code_only", 0.0, variant="scrubbed"),
            ArmSpec("bm25", 0.01, variant="scrubbed"),
        ],
        seed=seed,
        with_groups=True,
    )


def scenario_rewire_kill(seed: int = 22) -> Dict[str, object]:
    """The rewired control matches the full graph: section 14.2 must fire."""
    return make_run(
        "synthetic-rewire-kill",
        [
            ArmSpec("full", WIN),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.01),
            ArmSpec("rewired", WIN),  # identical ground truth to full
        ],
        seed=seed,
        noise=0.01,
    )


def scenario_no_gain(seed: int = 33) -> Dict[str, object]:
    """The full representation does not beat cheap retrieval: 14.1 must fire."""
    return make_run(
        "synthetic-no-gain",
        [
            ArmSpec("full", 0.0),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0),
        ],
        seed=seed,
        noise=0.01,
    )


def scenario_underpowered(seed: int = 44) -> Dict[str, object]:
    """A real effect, far too few noisy cases: nothing may be decided."""
    return make_run(
        "synthetic-underpowered",
        [
            ArmSpec("full", WIN),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0),
        ],
        n_cases=5,
        seed=seed,
        noise=0.25,
        seeds=1,
    )


def scenario_budget_bought_win(seed: int = 55) -> Dict[str, object]:
    """A win purchased with 2.5x the tokens: must not be reported as a win."""
    return make_run(
        "synthetic-budget-bought-win",
        [
            ArmSpec("full", WIN, budget_tokens=10240.0),
            ArmSpec("code_only", 0.0, budget_tokens=4096.0),
            ArmSpec("bm25", 0.0, budget_tokens=4096.0),
        ],
        seed=seed,
    )


def scenario_leakage_kill(seed: int = 66) -> Dict[str, object]:
    """The gain exists on raw queries and vanishes when scrubbed: 14.7 fires."""
    return make_run(
        "synthetic-leakage-kill",
        [
            ArmSpec("full", WIN),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0),
            ArmSpec("full", 0.0, variant="scrubbed"),
            ArmSpec("code_only", 0.0, variant="scrubbed"),
            ArmSpec("bm25", 0.0, variant="scrubbed"),
        ],
        seed=seed,
        noise=0.01,
    )


def scenario_cost_kill(seed: int = 77) -> Dict[str, object]:
    """Eight times the cost for no quality: 14.9 fires."""
    return make_run(
        "synthetic-cost-kill",
        [
            ArmSpec("full", 0.0, cost_units=8.0),
            ArmSpec("code_only", 0.0, cost_units=1.0),
            ArmSpec("bm25", 0.0, cost_units=1.0),
        ],
        seed=seed,
        noise=0.01,
    )


def scenario_held_out_kill(seed: int = 88) -> Dict[str, object]:
    """A gain that does not transfer to the held-out group: 14.12 fires."""
    return make_run(
        "synthetic-held-out-kill",
        [
            ArmSpec("full", WIN, group_effects={"held_out": 0.0}),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0),
        ],
        seed=seed,
        noise=0.01,
        n_cases=60,
        with_groups=True,
    )


def scenario_tiny_win(seed: int = 99) -> Dict[str, object]:
    """A statistically real win smaller than the practical margin."""
    return make_run(
        "synthetic-tiny-win",
        [
            ArmSpec("full", SMALL),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0),
        ],
        seed=seed,
        noise=0.005,
        n_cases=80,
    )


SCENARIOS = {
    "surviving_prior": scenario_surviving_prior,
    "rewire_kill": scenario_rewire_kill,
    "no_gain": scenario_no_gain,
    "underpowered": scenario_underpowered,
    "budget_bought_win": scenario_budget_bought_win,
    "leakage_kill": scenario_leakage_kill,
    "cost_kill": scenario_cost_kill,
    "held_out_kill": scenario_held_out_kill,
    "tiny_win": scenario_tiny_win,
}


def build(name: str, seed: Optional[int] = None) -> Dict[str, object]:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}; have {sorted(SCENARIOS)}")
    fn = SCENARIOS[name]
    return fn(seed) if seed is not None else fn()

"""Legacy provider-routing cost estimator.

This module answers one deliberately narrow question: given representative token
counts, a declared provider posture, and a price table, what would the routing
shape cost *if those assumptions held*?

It is not a benchmark authority. The task rows below are representative rather
than revision-frozen, the token counts are estimates, and the price table is not
verified at execution time. Results from :func:`run` are therefore planning
estimates and are mechanically labelled ineligible for comparative evidence.

Historically this module also had a ``--live`` path that called ``offload``
directly and printed "MEASURED" savings. That formed a second evaluation loop
beside :mod:`daedalus.eval` without frozen tasks/evaluators, equal budgets,
model/hardware identity, repeated seeds, retained failures, or uncertainty. The
Master Plan requires those properties before comparative claims, so live
measurement is retired here rather than expanded into another benchmark
subsystem. Real evaluation belongs to the canonical eval/evidence line.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from ..provider_router import select_provider
from ..router import route_task

ESTIMATE_SCHEMA = "daedalus.benchmark.cost-estimate/2"
ESTIMATE_CLASSIFICATION = "planning_estimate"

LIVE_BENCHMARK_RETIREMENT = (
    "live provider benchmarking is retired from daedalus.orchestration.benchmark: this "
    "legacy task/price model is not a frozen, equal-budget evaluator. Use the "
    "canonical daedalus.eval evidence path for measured comparisons."
)


class LiveBenchmarkRetired(RuntimeError):
    """Raised when a caller tries to use the retired parallel live evaluator."""


# USD per 1M tokens, (input, output). These are an explicit planning snapshot,
# not runtime-verified prices and not benchmark evidence.
PRICES: dict[str, tuple[float, float]] = {
    "claude_opus": (5.00, 25.00),
    "claude_sonnet": (3.00, 15.00),
    "deepseek": (0.14, 0.28),
    "ollama": (0.00, 0.00),
}

# When a free lane drafts advisory output, estimate a small Claude review/apply
# overhead rather than pretending advisory work costs no frontier tokens.
APPLY_IN, APPLY_OUT = 400, 250

# Representative routing posture only. It is included verbatim in every result
# so the estimate cannot masquerade as an observation of the live environment.
POSTURE = {"claude_cli": True, "ollama": True, "deepseek": False}


@dataclass(frozen=True)
class Task:
    name: str
    objective: str
    paths: tuple[str, ...]
    ctx_tokens: int
    out_tokens: int


# Historical representative workload retained for cost-planning continuity.
# It is intentionally NOT promoted into the canonical evaluation corpus.
TASKS: tuple[Task, ...] = (
    Task("gui docstrings", "Draft docstrings for the motor status panel",
         ("TCT_app/gui/motor_panel.py",), 3200, 800),
    Task("readme wording", "Update the README setup section wording",
         ("README.md",), 1500, 600),
    Task("scan-format note", "Draft an HDF5 layout note for SCAN_DATA_FORMAT.md",
         ("TCT_app/SCAN_DATA_FORMAT.md",), 2600, 700),
    Task("sim-backend docstrings", "Draft docstrings for the simulated motor backend",
         ("TCT_app/devices/motor_grbl_simulated.py",), 2000, 600),
    Task("theme review", "Review the gui theme change for accessibility",
         ("TCT_app/gui/style.py",), 2500, 800),
    Task("plot-helper refactor", "Refactor the scan-plot helper in the gui",
         ("TCT_app/gui/scan_panel.py",), 3400, 900),
    Task("laser-norm comment", "Summarize laser_normalization for an explanatory comment",
         ("TCT_app/analysis/laser_normalization.py",), 3000, 650),
    Task("state-machine review", "Review the scan state machine for race conditions",
         ("TCT_app/controller/state_machine.py",), 6000, 1200),
    Task("hv driver refactor", "Refactor the ISEG HV ramp driver",
         ("TCT_app/devices/bias_supply_iseg.py",), 5000, 1500),
)


def _cost(price_key: str, tin: int, tout: int) -> float:
    pin, pout = PRICES[price_key]
    return (tin * pin + tout * pout) / 1_000_000


def _claude_key(agent: dict[str, Any]) -> str:
    return "claude_opus" if agent.get("model_tier") == "opus" else "claude_sonnet"


def _assumptions() -> dict[str, Any]:
    """Return every non-observed input that the estimate depends on."""
    return {
        "task_set": "legacy_representative_tct_slice",
        "task_set_revision_frozen": False,
        "token_counts_measured": False,
        "prices_verified_at_runtime": False,
        "prices_usd_per_million_tokens": {
            name: {"input": price[0], "output": price[1]}
            for name, price in sorted(PRICES.items())
        },
        "posture_observed_at_runtime": False,
        "posture": dict(POSTURE),
        "advisory_apply_tokens": {"input": APPLY_IN, "output": APPLY_OUT},
    }


def run(json_out: bool = False) -> dict[str, Any]:
    """Compute the legacy routing cost estimate without calling a provider."""
    rows: list[dict[str, Any]] = []
    routed_total = base_opus = base_sonnet = 0.0
    for task in TASKS:
        agent = route_task(task.objective, list(task.paths))
        decision = select_provider(agent, task.objective, list(task.paths), POSTURE)
        ckey = _claude_key(agent)

        if decision.provider == "claude_cli":
            routed = _cost(ckey, task.ctx_tokens, task.out_tokens)
        else:
            routed = _cost(decision.provider, task.ctx_tokens, task.out_tokens)
            if decision.mode == "advisory":
                routed += _cost("claude_sonnet", APPLY_IN, APPLY_OUT)

        opus = _cost("claude_opus", task.ctx_tokens, task.out_tokens)
        sonnet = _cost("claude_sonnet", task.ctx_tokens, task.out_tokens)
        routed_total += routed
        base_opus += opus
        base_sonnet += sonnet

        rows.append({
            "task": task.name,
            "agent": agent["name"],
            "provider": decision.provider,
            "persona": decision.persona,
            "mode": decision.mode,
            "sensitive": decision.sensitive,
            "risk": decision.risk,
            "estimated_tokens": task.ctx_tokens + task.out_tokens,
            "estimated_routed_usd": round(routed, 6),
            "estimated_all_opus_usd": round(opus, 6),
        })

    summary = {
        "estimated_routed_total_usd": round(routed_total, 4),
        "estimated_all_opus_usd": round(base_opus, 4),
        "estimated_all_sonnet_usd": round(base_sonnet, 4),
        "estimated_savings_vs_opus_pct": (
            round(100 * (1 - routed_total / base_opus), 1) if base_opus else 0
        ),
        "estimated_savings_vs_sonnet_pct": (
            round(100 * (1 - routed_total / base_sonnet), 1) if base_sonnet else 0
        ),
    }
    result = {
        "schema": ESTIMATE_SCHEMA,
        "classification": ESTIMATE_CLASSIFICATION,
        "comparative_evidence_eligible": False,
        "rows": rows,
        "summary": summary,
        "assumptions": _assumptions(),
    }
    if not json_out:
        _print_table(rows, summary)
    return result


def run_live(repo_root: str, project: str | None = None, limit: int | None = None,
             run_tests: bool = False, json_out: bool = False) -> dict[str, Any]:
    """Compatibility refusal for the former parallel live measurement path.

    Keep the function long enough for callers to receive an explicit refusal
    instead of an import error. Remove it once repository callers and docs no
    longer reference ``benchmark.run_live``/``benchmark --live``.
    """
    del repo_root, project, limit, run_tests, json_out
    raise LiveBenchmarkRetired(LIVE_BENCHMARK_RETIREMENT)


def _print_table(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    print("COST ESTIMATE ONLY -- NOT COMPARATIVE EVIDENCE")
    print(f"{'task':<21}{'agent':<17}{'provider/persona':<22}{'risk':<6}"
          f"{'mode':<10}{'est.$':>10}{'allOpus$':>10}")
    print("-" * 96)
    for row in rows:
        provider = f"{row['provider']}/{row['persona']}"
        print(f"{row['task']:<21}{row['agent']:<17}{provider:<22}"
              f"{row['risk']:<6}{row['mode']:<10}"
              f"{row['estimated_routed_usd']:>10.5f}"
              f"{row['estimated_all_opus_usd']:>10.5f}")
    print("-" * 96)
    print(f"estimated routed total: ${summary['estimated_routed_total_usd']:.4f}")
    print(f"estimated all-Opus:     ${summary['estimated_all_opus_usd']:.4f}   "
          f"-> estimate {summary['estimated_savings_vs_opus_pct']}%")
    print(f"estimated all-Sonnet:   ${summary['estimated_all_sonnet_usd']:.4f}   "
          f"-> estimate {summary['estimated_savings_vs_sonnet_pct']}%")
    print("\nRepresentative tasks/tokens and unverified price snapshot; no model was called.")


def main() -> None:
    # Retain the existing registered CLI boundary. Retiring the live path is a
    # narrowing of capability, not permission to create an unregistered door.
    from ..budget import process_guard_boundary_decision
    from ..spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.benchmark",
        REGISTRY_BY_ID["cli.benchmark"].effects,
        (process_guard_boundary_decision(),),
    )

    parser = argparse.ArgumentParser(
        description="Legacy provider-routing cost estimate (not benchmark evidence)."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help="retired: measured comparisons must use the canonical eval/evidence path",
    )
    # Kept only so existing invocations fail for the intended reason instead of
    # first failing argument parsing. None of these can cause an effect here.
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args()

    if args.live:
        parser.error(LIVE_BENCHMARK_RETIREMENT)

    result = run(json_out=args.json)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

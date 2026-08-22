"""Token / cost benchmark for provider routing.

Answers the question behind the whole design: how much do we save by offloading
low-security work to cheap (DeepSeek) or free (Ollama) lanes instead of running
everything on Claude?

It is a *dry* estimate — it does not call any model, so running it costs zero
tokens. Token sizes per task are representative estimates (a real integration
should re-measure with count_tokens). Prices are cents-accurate as of the dates
noted below and are the single knob to re-verify.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass

from .provider_router import select_provider
from .router import route_task

# USD per 1M tokens, (input, output). Re-verify at integration time.
#   Claude:   platform.claude.com pricing (cached 2026-06-24 via claude-api skill)
#   DeepSeek: api-docs.deepseek.com/quick_start/pricing (deepseek-v4-flash, cache-miss)
#   Ollama:   local, no metered cost
PRICES: dict[str, tuple[float, float]] = {
    "claude_opus": (5.00, 25.00),      # claude-opus-4-8
    "claude_sonnet": (3.00, 15.00),    # claude-sonnet-5 (intro $2/$10 to 2026-08-31)
    "deepseek": (0.14, 0.28),          # deepseek-v4-flash, cache-miss input
    "ollama": (0.00, 0.00),            # local
}

# When a free lane drafts advisory output, Claude still reviews + applies a small
# diff. Model that overhead so the savings are honest, not inflated.
APPLY_IN, APPLY_OUT = 400, 250

# The real default posture: local bench on, DeepSeek dormant (no key). This is
# what you actually pay. (Turning DeepSeek on shifts non-sensitive drafting to a
# cheaper cloud lane but keeps the same shape.)
POSTURE = {"claude_cli": True, "ollama": True, "deepseek": False}


@dataclass
class Task:
    name: str
    objective: str
    paths: list[str]
    ctx_tokens: int   # inlined context + prompt
    out_tokens: int   # generated report/draft


# Representative slice of crew work. Paths are repo-relative; the guard classifies
# them exactly as it would at runtime.
TASKS: list[Task] = [
    Task("gui docstrings", "Draft docstrings for the motor status panel",
         ["TCT_app/gui/motor_panel.py"], 3200, 800),
    Task("readme wording", "Update the README setup section wording",
         ["README.md"], 1500, 600),
    Task("scan-format note", "Draft an HDF5 layout note for SCAN_DATA_FORMAT.md",
         ["TCT_app/SCAN_DATA_FORMAT.md"], 2600, 700),
    Task("sim-backend docstrings", "Draft docstrings for the simulated motor backend",
         ["TCT_app/devices/motor_grbl_simulated.py"], 2000, 600),
    Task("theme review", "Review the gui theme change for accessibility",
         ["TCT_app/gui/style.py"], 2500, 800),
    Task("plot-helper refactor", "Refactor the scan-plot helper in the gui",
         ["TCT_app/gui/scan_panel.py"], 3400, 900),
    Task("laser-norm comment", "Summarize laser_normalization for an explanatory comment",
         ["TCT_app/analysis/laser_normalization.py"], 3000, 650),
    Task("state-machine review", "Review the scan state machine for race conditions",
         ["TCT_app/controller/state_machine.py"], 6000, 1200),
    Task("hv driver refactor", "Refactor the ISEG HV ramp driver",
         ["TCT_app/devices/bias_supply_iseg.py"], 5000, 1500),
]


def _cost(price_key: str, tin: int, tout: int) -> float:
    pin, pout = PRICES[price_key]
    return (tin * pin + tout * pout) / 1_000_000


def _claude_key(agent: dict) -> str:
    return "claude_opus" if agent.get("model_tier") == "opus" else "claude_sonnet"


def run(json_out: bool = False) -> dict:
    rows = []
    routed_total = base_opus = base_sonnet = 0.0
    for task in TASKS:
        agent = route_task(task.objective, task.paths)
        decision = select_provider(agent, task.objective, task.paths, POSTURE)
        ckey = _claude_key(agent)

        if decision.provider == "claude_cli":
            routed = _cost(ckey, task.ctx_tokens, task.out_tokens)
        else:
            routed = _cost(decision.provider, task.ctx_tokens, task.out_tokens)
            if decision.mode == "advisory":
                routed += _cost("claude_sonnet", APPLY_IN, APPLY_OUT)  # Claude applies

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
            "tokens": task.ctx_tokens + task.out_tokens,
            "routed_usd": round(routed, 6),
            "all_opus_usd": round(opus, 6),
        })

    summary = {
        "routed_total_usd": round(routed_total, 4),
        "all_opus_usd": round(base_opus, 4),
        "all_sonnet_usd": round(base_sonnet, 4),
        "savings_vs_opus_pct": round(100 * (1 - routed_total / base_opus), 1) if base_opus else 0,
        "savings_vs_sonnet_pct": round(100 * (1 - routed_total / base_sonnet), 1) if base_sonnet else 0,
    }
    result = {"rows": rows, "summary": summary}
    if json_out:
        return result

    _print_table(rows, summary)
    return result


def _print_table(rows: list[dict], summary: dict) -> None:
    print(f"{'task':<21}{'agent':<17}{'provider/persona':<22}{'risk':<6}{'mode':<10}{'routed$':>10}{'allOpus$':>10}")
    print("-" * 96)
    for r in rows:
        pp = f"{r['provider']}/{r['persona']}"
        print(f"{r['task']:<21}{r['agent']:<17}{pp:<22}{r['risk']:<6}{r['mode']:<10}"
              f"{r['routed_usd']:>10.5f}{r['all_opus_usd']:>10.5f}")
    print("-" * 96)
    s = summary
    print(f"routed total:     ${s['routed_total_usd']:.4f}")
    print(f"all-Opus baseline:${s['all_opus_usd']:.4f}   "
          f"-> routing saves {s['savings_vs_opus_pct']}%")
    print(f"all-Sonnet base:  ${s['all_sonnet_usd']:.4f}   "
          f"-> routing saves {s['savings_vs_sonnet_pct']}%")
    print("\n(dry estimate; token sizes representative, prices per PRICES dict -- re-verify.)")


# --------------------------------------------------------------------------
# LIVE benchmark: actually run each task through the offload cascade and measure
# the REAL accept/escalate mix. This is the honest number the dry run can't give:
# the dry run assumes every eligible task succeeds; here we find out how often the
# local model clears the verifier gate (accept = zero Claude tokens) vs falls back
# to Claude (we paid local time AND still owe Claude the full task).
# --------------------------------------------------------------------------

def _routed_cost_live(task: "Task", res: dict, ckey: str) -> float:
    """Actual $ this task cost given what really happened on the bench."""
    action = res.get("action", "")
    mode = res.get("mode", "")
    if action == "offloaded":
        if mode == "advisory":
            # local drafted for free; Claude still reviews + applies a small diff
            return _cost("claude_sonnet", APPLY_IN, APPLY_OUT)
        return 0.0  # ran + wrote locally, verified -> no Claude tokens at all
    # escalate_to_claude / escalated_after_verify_fail / senior -> Claude does the whole task
    return _cost(ckey, task.ctx_tokens, task.out_tokens)


def run_live(repo_root: str, project: str | None = None, limit: int | None = None,
             run_tests: bool = False, json_out: bool = False) -> dict:
    from . import metrics
    from .offload import offload

    tasks = TASKS[:limit] if limit else TASKS
    rows = []
    routed_total = base_opus = base_sonnet = 0.0
    t_start = time.time()
    for task in tasks:
        agent = route_task(task.objective, task.paths)
        ckey = _claude_key(agent)
        t0 = time.time()
        res = offload(task.objective, repo_root, task.paths, live=True,
                      run_tests=run_tests, project=project)
        dt = time.time() - t0

        routed = _routed_cost_live(task, res, ckey)
        opus = _cost("claude_opus", task.ctx_tokens, task.out_tokens)
        sonnet = _cost("claude_sonnet", task.ctx_tokens, task.out_tokens)
        routed_total += routed
        base_opus += opus
        base_sonnet += sonnet

        rows.append({
            "task": task.name, "agent": agent["name"],
            "provider": res.get("provider"), "mode": res.get("mode"),
            "action": res.get("action"), "risk": res.get("risk"),
            "seconds": round(dt, 1), "routed_usd": round(routed, 6),
            "all_opus_usd": round(opus, 6),
            "verify": (res.get("verify") or {}).get("ok"),
            "note": res.get("note", ""),
        })

    wall = round(time.time() - t_start, 1)
    m = metrics.summary()
    summary = {
        "tasks_run": len(rows),
        "wall_seconds": wall,
        "routed_total_usd": round(routed_total, 4),
        "all_opus_usd": round(base_opus, 4),
        "all_sonnet_usd": round(base_sonnet, 4),
        "measured_savings_vs_opus_pct": round(100 * (1 - routed_total / base_opus), 1) if base_opus else 0,
        "measured_savings_vs_sonnet_pct": round(100 * (1 - routed_total / base_sonnet), 1) if base_sonnet else 0,
        "metrics": m,
    }
    result = {"rows": rows, "summary": summary}
    if json_out:
        return result
    _print_live(rows, summary)
    return result


def _print_live(rows: list[dict], summary: dict) -> None:
    print(f"{'task':<21}{'provider':<12}{'mode':<10}{'action':<28}{'sec':>6}{'routed$':>10}")
    print("-" * 96)
    for r in rows:
        print(f"{r['task']:<21}{str(r['provider']):<12}{str(r['mode']):<10}"
              f"{str(r['action']):<28}{r['seconds']:>6.0f}{r['routed_usd']:>10.5f}")
    print("-" * 96)
    s = summary
    print(f"tasks: {s['tasks_run']}   wall: {s['wall_seconds']}s")
    print(f"routed total:      ${s['routed_total_usd']:.4f}")
    print(f"all-Opus baseline: ${s['all_opus_usd']:.4f}   -> MEASURED saves {s['measured_savings_vs_opus_pct']}%")
    print(f"all-Sonnet base:   ${s['all_sonnet_usd']:.4f}   -> MEASURED saves {s['measured_savings_vs_sonnet_pct']}%")
    mm = s["metrics"]
    print(f"\nreal fallback rate: {mm['fallback_rate']:.0%}  "
          f"(offloaded {mm['offloaded']}/{mm['offloadable']}; alarm={mm['alarm']})")


def main() -> None:
    # THE BOUNDARY COMES FIRST -- above parse_args, the c67fd116 shape, so
    # both doors pass it: `daedalus benchmark` and `python -m
    # daedalus.benchmark`. Above --live on purpose. A cost benchmark is the
    # door most likely to be run casually and least likely to be assumed
    # expensive, and with --live every task goes through offload(live=True) to
    # a real provider.
    from .budget import process_guard_boundary_decision
    from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.benchmark",
        REGISTRY_BY_ID["cli.benchmark"].effects,
        (process_guard_boundary_decision(),),
    )

    parser = argparse.ArgumentParser(description="Provider-routing token/cost benchmark.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--live", action="store_true",
                        help="actually run each task through the offload cascade + measure")
    parser.add_argument("--repo-root", help="target repo (required with --live)")
    parser.add_argument("--project", help="project name -> loads safety policy (enables live writes)")
    parser.add_argument("--limit", type=int, help="only run the first N tasks (live)")
    parser.add_argument("--run-tests", action="store_true", help="force the project test suite in the gate")
    args = parser.parse_args()

    if args.live:
        if not args.repo_root:
            parser.error("--live requires --repo-root")
        result = run_live(args.repo_root, project=args.project, limit=args.limit,
                          run_tests=args.run_tests, json_out=args.json)
    else:
        result = run(json_out=args.json)
    if args.json:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

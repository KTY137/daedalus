"""G3-ORIGIN-EFFECT-01 -- does repository identity move retrieval scores?

Executes exactly the design frozen in
``docs/G3_ORIGIN_EFFECT_PREREGISTRATION_20260909.md`` (commit 9a8e6a24) plus
its two pre-measurement amendments. Read the pre-registration first; this file
is the instrument, not the argument.

Design, restated only so the code can be checked against it:
  contrast    mean(score | code, agent_env, n=6)
              - mean(score | code, sunny_garden, n=4)
  arms        bm25, code_only_graph, embeddings, separate_indices
              (the four deterministic, dependency-free ones)
  budgets     max_tokens in {1000, 4000, 16000}; primary reading 4000
  CI          stratified percentile bootstrap, 10000 resamples, seed 20260818
  margin      +-0.02

WHY ``run_arm_over_tasks`` AND NOT ``run_comparison``: the task set here is
single-plane by construction, and ``FrozenTaskSet.require_cross_plane()``
correctly refuses a single-plane set for a cross-plane comparison. This is not
a cross-plane comparison, so it uses the API that does not demand one. That is
the difference between using a guard as intended and routing around it -- the
guard is not weakened, disabled, or monkeypatched anywhere in this file.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

from daedalus.eval.gate3.contracts import ArmBudget, require_equal_budgets
from daedalus.eval.gate3.evaluator import make_recall_evaluator
from daedalus.eval.gate3.protocols import Task, run_arm_over_tasks
from daedalus.eval.gate3.taskset import classify_task_plane, filter_primary_tasks
from daedalus.eval.harness import all_tasks
from daedalus.eval.tasks import resolve_task_repo

RESAMPLES = 10_000
SEED = 20260818
MARGIN = 0.02
LADDER = (1000, 4000, 16000)
PRIMARY_RUNG = 4000
LEFT_REPO = "agent_env"
RIGHT_REPO = "sunny_garden"


def _arms():
    from daedalus.eval.gate3.arms import (bm25, code_only_graph, embeddings,
                                          separate_indices)
    out = []
    for mod in (bm25, code_only_graph, embeddings, separate_indices):
        factory = None
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and hasattr(obj, "name") and hasattr(obj, "run"):
                factory = obj
        if factory is None:
            raise SystemExit(f"no Arm class found in {mod.__name__}")
        out.append(factory())
    return out


def _split():
    primary = filter_primary_tasks(all_tasks())
    primary = primary[0] if isinstance(primary, tuple) else primary
    groups: dict[str, list[dict]] = {LEFT_REPO: [], RIGHT_REPO: []}
    for t in primary:
        if classify_task_plane(t) != "code":
            continue
        if t.get("repo") in groups:
            groups[t["repo"]].append(t)
    return groups


def _as_task(t: dict, label_plane: str | None = None) -> Task:
    """``label_plane`` defaults to the task's OWN classified plane.

    It used to be hardcoded to "code". That was true for this experiment --
    every task in the frozen contrast is code-plane -- and it was false the
    moment the helper was reused for a non-code probe, which is exactly what
    happened on 2026-09-09: ``separate_indices`` was handed data/knowledge
    tasks labelled "code", dutifully searched its code index, scored 0.00, and
    was written up as broken. It was not broken; the probe was. Deriving the
    default from the task removes the chance to be wrong by reuse.
    """
    return Task(task_id=t["id"], repo_root=resolve_task_repo(t["repo"]),
                question=t.get("question", ""), target=t.get("target", ""),
                label_plane=label_plane or classify_task_plane(t))


def _bootstrap_ci(left: list[float], right: list[float]):
    """Stratified percentile bootstrap on mean(left) - mean(right)."""
    rng = random.Random(SEED)
    deltas = []
    nl, nr = len(left), len(right)
    for _ in range(RESAMPLES):
        a = statistics.fmean(left[rng.randrange(nl)] for _ in range(nl))
        b = statistics.fmean(right[rng.randrange(nr)] for _ in range(nr))
        deltas.append(a - b)
    deltas.sort()
    lo = deltas[int(0.025 * RESAMPLES)]
    hi = deltas[min(int(0.975 * RESAMPLES), RESAMPLES - 1)]
    return lo, hi


def _read_arm(left: list[float], right: list[float]) -> tuple[str, float, float, float]:
    """Reading table §5. First match wins; order is the frozen order."""
    allv = left + right
    delta = statistics.fmean(left) - statistics.fmean(right)
    lo, hi = _bootstrap_ci(left, right)

    # row 1: DEGENERATE
    if (len(set(allv)) == 1) or all(v == 0.0 for v in allv) or all(v == 1.0 for v in allv):
        return "DEGENERATE", delta, lo, hi
    # row 2: entirely outside the margin
    if lo > MARGIN or hi < -MARGIN:
        return "REPO_IDENTITY_MATTERS", delta, lo, hi
    # row 3: entirely inside
    if -MARGIN <= lo and hi <= MARGIN:
        return "NEGLIGIBLE", delta, lo, hi
    # row 4
    return "UNINFORMATIVE", delta, lo, hi


def _aggregate(readings: dict[str, str]) -> str:
    """Reading table §6."""
    vals = set(readings.values())
    if vals == {"DEGENERATE"}:
        return "INSTRUMENT_VACUOUS"
    if "REPO_IDENTITY_MATTERS" in vals:
        return "REPO_IDENTITY_MATTERS_AT_ALL"
    nondegen = {v for v in vals if v != "DEGENERATE"}
    if nondegen == {"NEGLIGIBLE"}:
        return "REPO_IDENTITY_BOUNDED_SMALL"
    return "UNBOUNDED"


def main() -> int:
    groups = _split()
    if len(groups[LEFT_REPO]) != 6 or len(groups[RIGHT_REPO]) != 4:
        raise SystemExit(
            "corpus moved since the pre-registration: expected 6 %s / 4 %s "
            "code tasks, got %d / %d. Re-freeze before measuring."
            % (LEFT_REPO, RIGHT_REPO, len(groups[LEFT_REPO]), len(groups[RIGHT_REPO])))

    labels = {t["id"]: t["must_include"]
              for g in groups.values() for t in g if t.get("must_include")}
    tasks = {k: [_as_task(t) for t in v] for k, v in groups.items()}
    arms = _arms()

    failures: list[dict] = []
    report: dict = {"schema": "g3-origin-effect/1", "resamples": RESAMPLES,
                    "seed": SEED, "margin": MARGIN, "primary_rung": PRIMARY_RUNG,
                    "n": {k: len(v) for k, v in groups.items()}, "rungs": {}}

    for rung in LADDER:
        budgets = {a.name: ArmBudget(max_tokens=rung) for a in arms}
        require_equal_budgets(budgets)
        rung_rows: dict = {}
        for arm in arms:
            scores: dict[str, list[float]] = {}
            for repo, tlist in tasks.items():
                ev = make_recall_evaluator({t.task_id: labels[t.task_id]
                                            for t in tlist})
                trials = run_arm_over_tasks(arm, tlist, budgets[arm.name], ev, [0])
                # NEVER coerce a failed trial to 0.0. An arm that errored, or
                # returned no score, has not been measured -- silently reading
                # it as "scored zero" manufactures a confident result out of a
                # broken instrument, which is exactly how a run gets reported
                # as a finding when it should be reported as blocked.
                for tr in trials:
                    if tr.error is not None or tr.score is None:
                        failures.append({
                            "rung": rung, "arm": arm.name, "repo": repo,
                            "task": tr.task_id, "score": tr.score,
                            "error": tr.error,
                            "budget_exceeded": tr.budget_exceeded,
                        })
                scores[repo] = [float(tr.score) for tr in trials
                                if tr.error is None and tr.score is not None]
                if len(scores[repo]) != len(tlist):
                    continue
            reading, delta, lo, hi = _read_arm(scores[LEFT_REPO], scores[RIGHT_REPO])
            rung_rows[arm.name] = {
                "reading": reading, "delta": delta, "ci95": [lo, hi],
                "mean_left": statistics.fmean(scores[LEFT_REPO]),
                "mean_right": statistics.fmean(scores[RIGHT_REPO]),
                "scores": scores,
            }
            print("  rung=%-6d %-18s delta=%+.4f  CI95=[%+.4f, %+.4f]  %s"
                  % (rung, arm.name, delta, lo, hi, reading))
        report["rungs"][str(rung)] = {
            "arms": rung_rows,
            "aggregate": _aggregate({k: v["reading"] for k, v in rung_rows.items()}),
        }
        print("  rung=%-6d AGGREGATE: %s\n" % (rung, report["rungs"][str(rung)]["aggregate"]))

    report["failures"] = failures
    if failures:
        # A trial that errored was not measured. Reading a table over the
        # survivors would silently redefine the contrast as "whichever tasks
        # happened to work", which is not the frozen design.
        report["primary_verdict"] = "BLOCKED_TRIALS_FAILED"
        print("\nBLOCKED: %d trial(s) failed; no verdict is read." % len(failures))
        for f in failures[:20]:
            print("   rung=%-6s %-18s %-14s %-28s score=%s err=%s"
                  % (f["rung"], f["arm"], f["repo"], f["task"], f["score"],
                     (f["error"] or "")[:70]))
        out = Path("runs/g3_origin_effect/report.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print("wrote", out)
        return 2

    verdicts = {r: report["rungs"][r]["aggregate"] for r in report["rungs"]}
    report["primary_verdict"] = verdicts[str(PRIMARY_RUNG)]
    report["rungs_agree"] = len(set(verdicts.values())) == 1
    print("PRIMARY (rung %d): %s" % (PRIMARY_RUNG, report["primary_verdict"]))
    print("rungs agree: %s  -> %s" % (report["rungs_agree"], verdicts))

    out = Path("runs/g3_origin_effect/report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

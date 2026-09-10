"""Is a task answerable, and does it discriminate? A retained instrument.

WHY THIS FILE EXISTS. On 2026-09-10 I promoted 35 tasks into the Gate-3 primary
tier and justified it with "bm25 means 0.209 and separate_indices 0.500 ... two
arms separated by 0.29". An independent pass could not reproduce that from any
routing (it measured 0.243 and 0.265, separation 0.022) and there was nothing to
check it against: no script, no receipt, no seed. The only record of the pair
was a sentence in a docstring. ``AGENTS.md`` calls an unverifiable claim a
release-blocking defect, and it was sitting in the sentence that justified the
promotion.

So this is deliberately an instrument and not a one-off: it declares its arms,
its budgets and its task selection, writes a receipt with the numbers AND the
inputs that produced them, and refuses to summarise anything if a trial FAILED.

A FAILURE IS NOT A REFUSAL, and the first run of this file got that wrong. It
blocked on 24 cells where ``code_only_graph`` declined data and knowledge tasks
-- which is the measurement that code-only baseline exists to provide. Blocking
there would have made this instrument permanently unable to report on a
non-code corpus. The distinction now comes from the arm's OWN
``retrieved_planes`` declaration: a refusal on a plane it never claimed is
information; a refusal on a plane it did claim is a defect and still blocks.
Not from the arm's name, and not from a hardcoded list.

ONE SEED, AND THE ASYMMETRY THAT MAKES IT SOUND HERE. Stochastic arms run at
``SEED`` only, which plan §14 would call too few if the question were "how much
does this arm score". It is not that question. DISCRIMINATIVE is a POSITIVE
finding: differing scores were observed, and more seeds cannot un-observe them.
CONSTANT is the claim that needs more seeds, because another seed might move
it. So a run in which every task reads DISCRIMINATIVE is sound at one seed, and
a run reporting CONSTANT must be re-read at several before it is believed.

WHAT IT MEASURES, in the vocabulary the corpus needs:

  ANSWERABLE     some (arm, budget) cell scores > 0. Somebody can do it.
  DISCRIMINATIVE the task's scores are not identical across every cell. It can
                 tell two arms, or two budgets, apart.
  CONSTANT       every cell returns the same score. The task carries no
                 information about any arm, whatever that constant is -- 1.0 is
                 exactly as useless as 0.0, and a constant 1.0 is the more
                 dangerous of the two because it inflates a mean while looking
                 like success.

A task can be answerable and still constant (everything answers it perfectly).
Those are different properties and this reports both, because conflating them
is how four fixture rows sat in a scored tier for months.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import statistics
import sys
from collections import Counter

from daedalus.eval.gate3.contracts import ArmBudget
from daedalus.eval.gate3.coverage import retrieved_planes
from daedalus.eval.gate3.evaluator import make_recall_evaluator
from daedalus.eval.gate3.protocols import Task
from daedalus.eval.gate3.taskset import classify_task_plane
from daedalus.eval.harness import all_tasks
from daedalus.eval.mint import load_minted_tasks, promotion_witness
from daedalus.eval.tasks import resolve_task_repo

#: Declared here rather than passed in, so two runs of this file are comparable
#: by construction. Changing either is a change to the instrument and moves the
#: recorded ``instrument_digest``.
BUDGETS = (500, 2000, 4000, 16000)
SEED = 0


def _arms():
    """Every arm that runs locally without a provider, deterministic first.

    ``single_llm_loop`` is excluded: it needs a live model and returns an error
    offline, which would make every run of this instrument report a blocked
    cell for reasons that have nothing to do with the task.
    """
    from daedalus.eval.gate3.arms import (best_of_n, bm25, code_only_graph,
                                          embeddings, local_mutation,
                                          random_search, separate_indices)
    out = []
    for mod in (best_of_n, bm25, code_only_graph, embeddings, local_mutation,
                random_search, separate_indices):
        cls = next(getattr(mod, n) for n in dir(mod)
                   if isinstance(getattr(mod, n), type)
                   and hasattr(getattr(mod, n), "run")
                   and hasattr(getattr(mod, n), "name"))
        out.append(cls())
    return out


def _instrument_digest() -> str:
    """Hash this file plus the declared knobs, so a receipt names the exact
    instrument that produced it. A number without this is the defect above."""
    h = hashlib.sha256()
    h.update(pathlib.Path(__file__).read_bytes())
    h.update(repr((BUDGETS, SEED)).encode())
    return h.hexdigest()[:16]


def _select(which: str) -> list[dict]:
    if which == "minted-clean":
        return [t for t in load_minted_tasks()
                if promotion_witness({**t, "confirmations": 0}) == "noise_audit"]
    if which == "minted-all":
        return list(load_minted_tasks())
    if which == "primary":
        return [t for t in all_tasks() if t.get("tier") == "primary"]
    raise SystemExit(f"unknown selection {which!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--select", default="minted-clean",
                    choices=["minted-clean", "minted-all", "primary"])
    ap.add_argument("--out", default="runs/g3_task_answerability/report.json")
    args = ap.parse_args()

    tasks = _select(args.select)
    if not tasks:
        raise SystemExit(f"selection {args.select!r} is empty; nothing to measure")
    arms = _arms()

    cells: list[dict] = []
    failures: list[dict] = []
    refusals: list[dict] = []
    for task in tasks:
        plane = classify_task_plane(task)
        root = resolve_task_repo(task["repo"])
        question = task.get("question") or f"what changed in {task.get('target')}"
        for arm in arms:
            for budget in BUDGETS:
                gt = Task(task_id=task["id"], repo_root=root, question=question,
                          target=task.get("target", ""), label_plane=plane)
                ev = make_recall_evaluator({gt.task_id: task["must_include"]})()
                out = arm.run(gt, ArmBudget(max_tokens=budget), ev, SEED)
                if out.error is not None or out.score is None:
                    # AN EXPECTED REFUSAL IS NOT A FAILED RUN. ``code_only_graph``
                    # is code-only on purpose, and it erroring on a data or
                    # knowledge task is the measurement that baseline exists to
                    # provide -- blocking the whole instrument on it would mean
                    # this file could never report on a non-code corpus at all.
                    #
                    # The distinction is taken from the arm's OWN declaration
                    # rather than from its name or a hardcoded list: if it does
                    # not claim to retrieve this plane, a refusal here is
                    # information; if it DOES claim to, the refusal is a defect
                    # and must still block.
                    expected = plane not in retrieved_planes(arm)
                    row = {"task": task["id"], "arm": arm.name,
                           "budget": budget, "plane": plane,
                           "error": out.error}
                    (refusals if expected else failures).append(row)
                    continue
                cells.append({"task": task["id"], "plane": plane,
                              "repo": task["repo"], "arm": arm.name,
                              "budget": budget, "score": float(out.score)})

    report = {
        "schema": "g3-task-answerability/1",
        "instrument_digest": _instrument_digest(),
        "selection": args.select,
        "budgets": list(BUDGETS),
        "seed": SEED,
        "arms": sorted(a.name for a in arms),
        "n_tasks": len(tasks),
        "cells": cells,
        "failures": failures,
        "expected_refusals": refusals,
    }

    per_task: dict[str, list[float]] = {}
    for c in cells:
        per_task.setdefault(c["task"], []).append(c["score"])

    verdicts = {}
    for tid, scores in per_task.items():
        uniq = set(scores)
        if len(uniq) == 1:
            verdicts[tid] = "CONSTANT_%s" % ("1" if scores[0] == 1.0
                                             else "0" if scores[0] == 0.0
                                             else "MID")
        elif max(scores) == 0.0:
            verdicts[tid] = "UNANSWERABLE"
        else:
            verdicts[tid] = "DISCRIMINATIVE"
    report["task_verdicts"] = verdicts

    print("instrument %s  selection=%s  tasks=%d  arms=%d  budgets=%s"
          % (report["instrument_digest"], args.select, len(tasks), len(arms),
             list(BUDGETS)))
    if refusals:
        by = Counter((r["arm"], r["plane"]) for r in refusals)
        print("expected refusals (arm does not declare the task's plane): %d"
              % len(refusals))
        for (arm_name, pl), n in sorted(by.items()):
            print("   %-18s %-10s %d" % (arm_name, pl, n))
    if failures:
        # Never summarise over survivors: that silently redefines the
        # population as "whichever cells happened to work".
        report["summary_status"] = "BLOCKED_TRIALS_FAILED"
        print("BLOCKED: %d errored cell(s); no summary is produced." % len(failures))
        for f in failures[:10]:
            print("   ", f)
    else:
        report["summary_status"] = "ok"
        print("\nper-task verdicts: %s" % dict(Counter(verdicts.values())))
        print("\n%-38s %-10s %-16s %6s %6s %s"
              % ("task", "plane", "verdict", "min", "max", "distinct"))
        for tid in sorted(per_task):
            s = per_task[tid]
            plane = next(c["plane"] for c in cells if c["task"] == tid)
            print("%-38s %-10s %-16s %6.3f %6.3f %d"
                  % (tid[:38], plane, verdicts[tid], min(s), max(s), len(set(s))))
        print("\nper-arm mean over all tasks and budgets:")
        by_arm: dict[str, list[float]] = {}
        for c in cells:
            by_arm.setdefault(c["arm"], []).append(c["score"])
        for arm in sorted(by_arm):
            v = by_arm[arm]
            print("   %-18s mean=%.3f  distinct=%d  n=%d"
                  % (arm, statistics.fmean(v), len(set(v)), len(v)))

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("\nwrote", out_path)
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())

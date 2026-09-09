"""G3-ARM-PLANE-01 -- before/after for the two arms that never look.

Executes the design frozen in
``docs/G3_ARM_PLANE_REPAIR_PREREGISTRATION_20260910.md``. Measures WITHOUT
editing either arm: the arms' own ``_repo_chunks`` call is wrapped so the
universe it returns changes, and nothing in ``run()`` is touched. The repair
ships only if the frozen reading table says it should.

Two patch points, not one: ``bm25`` calls ``harness._repo_chunks`` through the
module, but ``embeddings`` did ``from daedalus.eval.harness import
_repo_chunks`` at import time and holds its own reference. Patching only
``harness`` would leave embeddings measuring the OLD universe while the report
claimed it measured the new one -- a silent half-measurement.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from daedalus.eval import harness
from daedalus.eval.gate3.arms import bm25 as bm25_mod
from daedalus.eval.gate3.arms import embeddings as emb_mod
from daedalus.eval.gate3.contracts import ArmBudget
from daedalus.eval.gate3.evaluator import make_recall_evaluator
from daedalus.eval.gate3.protocols import Task
from daedalus.eval.gate3.taskset import classify_task_plane, filter_primary_tasks
from daedalus.eval.harness import all_tasks
from daedalus.eval.tasks import resolve_task_repo

LADDER = (1000, 4000, 16000)
ALL_PLANES = ("code", "data", "knowledge")   # _repo_chunks refuses `type`
_ORIG = harness._repo_chunks


# (root, planes) -> chunks. The universe is a pure function of those two, and
# rebuilding it per trial costs ~4s on this repository -- 252 trials spent
# longer walking the tree than measuring anything. Caching changes no result;
# the first run without it timed out at 10 minutes.
_UNIVERSE: dict[tuple, list] = {}


def _universe(root, planes):
    key = (str(root), planes)
    if key not in _UNIVERSE:
        _UNIVERSE[key] = _ORIG(root) if planes is None else _ORIG(root, planes=planes)
    return _UNIVERSE[key]


def _install(mode: str, plane_of):
    """Wrap the universe the arms retrieve over. ``mode`` is the variant."""
    def wrapped(root, *a, **kw):
        if "planes" in kw or a:
            return _ORIG(root, *a, **kw)
        if mode == "before":
            return _universe(root, None)
        if mode == "A":
            return _universe(root, ALL_PLANES)
        if mode == "B":
            p = plane_of()
            want = ("code",) if p in (None, "code") else ("code", p)
            return _universe(root, want)
        raise AssertionError(mode)
    harness._repo_chunks = wrapped
    bm25_mod.harness._repo_chunks = wrapped
    emb_mod._repo_chunks = wrapped


def _restore():
    harness._repo_chunks = _ORIG
    bm25_mod.harness._repo_chunks = _ORIG
    emb_mod._repo_chunks = _ORIG


def main() -> int:
    primary = filter_primary_tasks(all_tasks())
    primary = primary[0] if isinstance(primary, tuple) else primary
    rows = []
    for t in primary:
        rows.append((t, classify_task_plane(t)))
    assert len(rows) == 14, f"expected 14 primary tasks, got {len(rows)}"

    arms = {"bm25": bm25_mod.BM25Arm(), "embeddings": emb_mod.EmbeddingsArm()}
    current = {"plane": None}
    report: dict = {"schema": "g3-arm-plane/1", "ladder": list(LADDER),
                    "all_planes": list(ALL_PLANES), "cells": []}

    for mode in ("before", "A", "B"):
        _install(mode, lambda: current["plane"])
        try:
            for rung in LADDER:
                for arm_name, arm in arms.items():
                    for task, plane in rows:
                        current["plane"] = plane
                        gt = Task(task_id=task["id"],
                                  repo_root=resolve_task_repo(task["repo"]),
                                  question=task.get("question", ""),
                                  target=task.get("target", ""),
                                  label_plane=plane)
                        ev = make_recall_evaluator({gt.task_id: task["must_include"]})()
                        out = arm.run(gt, ArmBudget(max_tokens=rung), ev, 0)
                        report["cells"].append({
                            "mode": mode, "rung": rung, "arm": arm_name,
                            "task": task["id"], "repo": task["repo"],
                            "plane": plane,
                            "score": None if out.score is None else float(out.score),
                            "error": out.error,
                        })
        finally:
            _restore()

    errors = [c for c in report["cells"] if c["error"] or c["score"] is None]
    report["errors"] = errors

    def cell(mode, rung, arm, task):
        for c in report["cells"]:
            if (c["mode"], c["rung"], c["arm"], c["task"]) == (mode, rung, arm, task):
                return c
        raise KeyError((mode, rung, arm, task))

    if errors:
        report["verdict"] = {a: "BLOCKED" for a in arms}
        print("BLOCKED: %d errored cell(s); no verdict is read." % len(errors))
        for e in errors[:10]:
            print("   ", e)
    else:
        verdict = {}
        for arm_name in arms:
            noncode_rose = code_fell = hint_rose = False
            for rung in LADDER:
                for task, plane in rows:
                    b = cell("before", rung, arm_name, task["id"])["score"]
                    a = cell("A", rung, arm_name, task["id"])["score"]
                    h = cell("B", rung, arm_name, task["id"])["score"]
                    if plane == "code":
                        if a < b:
                            code_fell = True
                    else:
                        if a > b:
                            noncode_rose = True
                        if h > b:
                            hint_rose = True
            if noncode_rose and not code_fell:
                verdict[arm_name] = "REPAIRED_CLEAN"
            elif noncode_rose:
                verdict[arm_name] = "REPAIRED_WITH_REGRESSION"
            elif hint_rose:
                verdict[arm_name] = "NEEDS_THE_HINT"
            else:
                verdict[arm_name] = "CAUSAL_STORY_INCOMPLETE"
        report["verdict"] = verdict

    # per-arm x per-plane x per-rung, never a single mean over the tier
    print("\n%-11s %-6s %-10s %8s %8s %8s" % ("arm", "rung", "plane", "before", "A(all)", "B(hint)"))
    for arm_name in arms:
        for rung in LADDER:
            for plane in ("code", "data", "knowledge"):
                ids = [t["id"] for t, p in rows if p == plane]
                if not ids:
                    continue
                def m(mode):
                    vals = [cell(mode, rung, arm_name, i)["score"] for i in ids]
                    vals = [v for v in vals if v is not None]
                    return statistics.fmean(vals) if vals else float("nan")
                print("%-11s %-6d %-10s %8.3f %8.3f %8.3f"
                      % (arm_name, rung, plane, m("before"), m("A"), m("B")))
    print("\nVERDICT:", report.get("verdict"))

    # the sunny_garden control (A2): it has no non-code files, so A must not move it
    moved = [t["id"] for t, p in rows if t["repo"] == "sunny_garden"
             for rung in LADDER for a in arms
             if cell("before", rung, a, t["id"])["score"] != cell("A", rung, a, t["id"])["score"]]
    print("A2 control -- sunny_garden tasks moved by variant A:", sorted(set(moved)) or "NONE")

    out = Path("runs/g3_arm_plane/report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

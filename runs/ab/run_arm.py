"""Run ONE arm of the pre-registered A/B and write a mechanical receipt.

Both arms get: the same SPEC.md, the same model, the same base repo state
(PnP_App @ f894b3f in an isolated git worktree), and the same tools.

The ONLY difference is process:

  A (crew only)      the spec, a repo, and the model's own judgment.
  B (full Daedalus)  the spec plus a DSS-distilled, token-BUDGETED context
                     bundle produced by `daedalus context` (so it does not have
                     to go looking), and a harness that runs the gate after each
                     pass and feeds a failure back for a bounded number of
                     repair rounds -- counted as rework.

Nothing here reads the hidden conformance suite; scoring happens afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = (HERE / "SPEC.md").read_text(encoding="utf-8")
AB_ROOT = Path(r"C:\Users\nukei\Desktop\ab_run")
MODEL = "sonnet"
GATE = ["npm", "--prefix", "design/visual-lab", "run", "build"]


def run_gate(arm_dir: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(GATE, cwd=arm_dir, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=900,
                              shell=True)
    except subprocess.SubprocessError as e:
        return False, f"gate could not run: {e}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out[-4000:]


def call_claude(prompt: str, cwd: Path) -> dict:
    """One `claude -p` turn. Returns the CLI's own JSON receipt."""
    env = dict(os.environ)
    # Keep this run out of the session mirror: a hook that mirrors every Claude
    # Code session into the shared room would otherwise inject the experiment's
    # own turns back into the room the judges read.
    env["DAEDALUS_ROOM_FILE"] = str(HERE / "receipts" / "_arm_room_sink.md")
    started = time.time()
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", MODEL,
         "--dangerously-skip-permissions"],
        input=prompt, cwd=cwd, capture_output=True, encoding="utf-8",
        errors="replace", timeout=3600, env=env, shell=True)
    wall = time.time() - started
    try:
        receipt = json.loads(proc.stdout)
    except Exception:
        receipt = {"parse_error": True, "stdout": (proc.stdout or "")[-2000:],
                   "stderr": (proc.stderr or "")[-2000:]}
    receipt["_wall_seconds"] = round(wall, 2)
    return receipt


def distilled_context(objective: str) -> tuple[str, dict]:
    """Arm B's advantage: what `daedalus context` says is worth reading."""
    sys.path.insert(0, str(HERE.parents[1]))
    from daedalus.context_plan import plan_context  # type: ignore

    repo_root = Path(r"C:\Users\nukei\Desktop\PnP_App")
    plan = plan_context(repo_root, objective, project="pnp_app").to_dict()
    cp = (plan.get("dss") or {}).get("context_plan") or {}
    selected = cp.get("selected") or []
    repo = Path(r"C:\Users\nukei\Desktop\PnP_App")
    chunks = []
    for item in selected:
        rel = item.get("node_id")
        try:
            body = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunks.append(f"----- {rel} -----\n{body}")
    return "\n\n".join(chunks), {
        "token_budget": cp.get("token_budget"),
        "tokens_used": cp.get("tokens_used"),
        "selected": [s.get("node_id") for s in selected],
        "omitted": [s.get("node_id") for s in (cp.get("omitted") or [])],
        "receipt_sha256": ((plan.get("dss") or {}).get("receipt") or {}).get("receipt_sha256"),
    }


PROMPT_A = """{spec}

---

You are working in the repository at {root}.

Implement the task above. You have full access to the repository: read whatever
you need, including `design/06-giga-product-architecture.md`.

The gate is `npm --prefix design/visual-lab run build`. Run it yourself and make
sure it passes before you finish.

Write the code. Do not ask questions -- make the judgment calls yourself and
state them in comments where they matter.
"""

PROMPT_B_FIRST = """{spec}

---

You are working in the repository at {root}.

CONTEXT HAS BEEN DISTILLED FOR YOU. A context planner selected the files below
as the ones that matter for this objective, within a {budget}-token budget
({used} tokens used). You may still read the repository -- including
`design/06-giga-product-architecture.md` -- but you should not need to go
looking for the shape of the existing code:

{context}

---

The gate is `npm --prefix design/visual-lab run build`. It will be run for you
after this pass, and any failure will be handed back to you for repair, so you
do not have to run it yourself.

Write the code. Do not ask questions -- make the judgment calls yourself and
state them in comments where they matter.
"""

PROMPT_B_REPAIR = """The gate failed on your last pass. This is repair round {round}.

Gate command: npm --prefix design/visual-lab run build
Gate output (tail):

{gate_output}

Fix the cause. Do not weaken the spec to make the gate pass, and do not delete
required exports. Reply when the code is corrected.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["A", "B"])
    ap.add_argument("--max-repairs", type=int, default=2)
    args = ap.parse_args()

    arm_dir = AB_ROOT / f"arm{args.arm}"
    receipt: dict = {"arm": args.arm, "model": MODEL, "repo": str(arm_dir),
                     "turns": [], "rework": 0, "human_interventions": 0}

    objective = ("Implement the Chronicle core navigation model: scope, "
                 "ObjectRef, ViewRecipe, visibility and deep links as "
                 "TypeScript modules in design/visual-lab/src/core")

    started = time.time()
    if args.arm == "A":
        prompt = PROMPT_A.format(spec=SPEC, root=arm_dir)
    else:
        ctx, meta = distilled_context(objective)
        receipt["distilled_context"] = meta
        prompt = PROMPT_B_FIRST.format(spec=SPEC, root=arm_dir, context=ctx,
                                       budget=meta.get("token_budget"),
                                       used=meta.get("tokens_used"))
    receipt["prompt_chars"] = len(prompt)

    turn = call_claude(prompt, arm_dir)
    receipt["turns"].append(turn)

    passed, gate_out = run_gate(arm_dir)
    receipt["gate_after_first_pass"] = passed

    # Arm B's harness repairs; Arm A was told to run its own gate and stop.
    if args.arm == "B":
        rounds = 0
        while not passed and rounds < args.max_repairs:
            rounds += 1
            receipt["rework"] = rounds
            turn = call_claude(
                PROMPT_B_REPAIR.format(round=rounds, gate_output=gate_out),
                arm_dir)
            receipt["turns"].append(turn)
            passed, gate_out = run_gate(arm_dir)

    receipt["gate_passed"] = passed
    receipt["gate_output_tail"] = gate_out[-1500:]
    receipt["wall_seconds_total"] = round(time.time() - started, 2)

    tot_in = tot_out = tot_cache_r = tot_cache_c = 0
    cost = 0.0
    for t in receipt["turns"]:
        u = t.get("usage") or {}
        tot_in += int(u.get("input_tokens") or 0)
        tot_out += int(u.get("output_tokens") or 0)
        tot_cache_r += int(u.get("cache_read_input_tokens") or 0)
        tot_cache_c += int(u.get("cache_creation_input_tokens") or 0)
        cost += float(t.get("total_cost_usd") or 0.0)
    receipt["totals"] = {
        "input_tokens": tot_in, "output_tokens": tot_out,
        "cache_read_input_tokens": tot_cache_r,
        "cache_creation_input_tokens": tot_cache_c,
        "billable_tokens": tot_in + tot_out + tot_cache_c,
        "usd": round(cost, 4),
        "turns": len(receipt["turns"]),
    }

    out = HERE / "receipts" / f"arm{args.arm}.json"
    out.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"arm": args.arm, "gate_passed": passed,
                      **receipt["totals"],
                      "wall_seconds": receipt["wall_seconds_total"],
                      "rework": receipt["rework"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

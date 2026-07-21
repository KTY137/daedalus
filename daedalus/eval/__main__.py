"""CLI entrypoint: ``python -m daedalus.eval [--tier2] [--arms] [--project NAME]
[--gate | --update-baseline | --mint-commit SHA | --confirm-mint TASK_ID]``.

Tier 1 always runs (deterministic, no LLM). --arms adds the deterministic A/B/C
retrieval comparison (also no LLM). Tier 2 runs only with --tier2 AND a
reachable provider; otherwise it is skipped with a clear message.

--gate is an ADVISORY local regression check against baseline.json -- see
``daedalus.eval.harness.run_gate``. It is never wired into anything automatic;
run it by hand before shipping a slice-heuristic change. --update-baseline is
the only thing that writes baseline.json, and only when explicitly passed.

--mint-commit/--confirm-mint are the ONLY entry points that persist a task to
the mint store (``daedalus.eval.mint.DEFAULT_MINT_STORE_PATH``); every other
flag above only READS it via ``harness.all_tasks()``. This is the human-invoked
half of the mint -> quarantine -> confirm -> primary flywheel -- there is no
automatic caller (offload.py does not invoke this today; see mint.py's module
docstring).

Output is ASCII-only for a raw Windows console.
"""
from __future__ import annotations

import argparse
import sys

from . import harness
from .harness import all_tasks, run_tier1, run_tier2, run_arms
from .mint import add_minted_task, confirm_minted_task, mint_from_commit
from .report import render, render_gate
from .tasks import AGENT_ENV_ROOT, task_project_label


def _select(project: str | None) -> list[dict]:
    tasks = all_tasks()
    if not project:
        return tasks
    selected = [t for t in tasks if task_project_label(t) == project]
    if not selected:
        buckets = sorted({task_project_label(t) for t in tasks})
        raise SystemExit(f"no tasks for project {project!r}. Known: {', '.join(buckets)}")
    return selected


def _print_ascii(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:  # pragma: no cover - defensive
        sys.stdout.buffer.write(text.encode("ascii", "replace"))
        sys.stdout.buffer.write(b"\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m daedalus.eval",
        description="Private directional eval: distillation vs concatenation vs "
                    "retrieval. Tier 1 and --arms are deterministic (no LLM); "
                    "Tier 2 is opt-in; --gate is an advisory local regression check.")
    ap.add_argument("--tier2", action="store_true",
                    help="also run the LLM A-vs-B comparison (needs a provider).")
    ap.add_argument("--arms", action="store_true",
                    help="also run the deterministic A/B/C comparison (semantic "
                         "slice vs whole-repo concat vs BM25 retrieval) -- no LLM.")
    ap.add_argument("--project", default=None,
                    help="filter tasks to one project bucket (agent_env | sunny_garden).")
    ap.add_argument("--provider", default=None,
                    help="force a Tier-2 provider label (default: autodetect Ollama).")
    ap.add_argument("--gate", action="store_true",
                    help="ADVISORY: replay tasks against baseline.json and report "
                         "per-task recall regressions on the primary tier. Exits "
                         "non-zero on a regression; never blocks anything automatic.")
    ap.add_argument("--update-baseline", action="store_true",
                    help="EXPLICIT ONLY: overwrite baseline.json with current "
                         "recall. Never happens automatically.")
    ap.add_argument("--baseline-path", default=None,
                    help="override the baseline.json path (default: "
                         "daedalus/eval/baseline.json).")
    ap.add_argument("--mint-commit", default=None, metavar="SHA",
                    help="EXPLICIT ONLY: mint a quarantined, independent_diff "
                         "task from git commit SHA in --repo (default: this "
                         "agent_env checkout) and persist it to the mint store "
                         "so it joins every subsequent run via all_tasks().")
    ap.add_argument("--confirm-mint", default=None, metavar="TASK_ID",
                    help="EXPLICIT ONLY: record one independent confirmation "
                         "for a quarantined minted task, promoting it to "
                         "primary at daedalus.eval.mint.MINT_CONFIRM_THRESHOLD.")
    ap.add_argument("--repo", default=None,
                    help="repo root for --mint-commit (default: this agent_env "
                         "checkout).")
    ap.add_argument("--mint-store-path", default=None,
                    help="override the mint store path (default: "
                         "daedalus/eval/minted_tasks.json).")
    args = ap.parse_args(argv)

    if args.mint_commit:
        repo = args.repo or AGENT_ENV_ROOT
        minted = mint_from_commit(repo, args.mint_commit)
        if not minted:
            print(f"nothing minted from {args.mint_commit!r} in {repo!r} "
                  "(unresolvable ref, or the diff had no unit-level change).")
            return 1
        for t in minted:
            path = add_minted_task(t, path=args.mint_store_path)
        print(f"minted {len(minted)} quarantined task(s) -> {path}:")
        for t in minted:
            print(f"  {t['id']}  target={t['target']}  must_include={t['must_include']}")
        return 0

    if args.confirm_mint:
        confirmed = confirm_minted_task(args.confirm_mint, path=args.mint_store_path)
        if confirmed is None:
            print(f"no minted task with id {args.confirm_mint!r} in the store.")
            return 1
        print(f"{confirmed['id']}: confirmations={confirmed['confirmations']} "
              f"tier={confirmed['tier']}")
        return 0

    tasks = _select(args.project)

    if args.update_baseline:
        path = harness.write_baseline(tasks, path=args.baseline_path)
        print(f"baseline updated (explicit --update-baseline): {path}")
        return 0

    if args.gate:
        gate = harness.run_gate(tasks, baseline_path=args.baseline_path)
        _print_ascii(render_gate(gate))
        return 0 if gate["passed"] else 1

    tier1 = run_tier1(tasks)
    arms = run_arms(tasks) if args.arms else None
    tier2 = run_tier2(tasks, provider=args.provider) if args.tier2 else None

    text = render(tier1, tier2=tier2, arms=arms)
    _print_ascii(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

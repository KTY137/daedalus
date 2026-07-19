"""CLI entrypoint: ``python -m daedalus.eval [--tier2] [--project NAME]``.

Tier 1 always runs (deterministic, no LLM). Tier 2 runs only with --tier2 AND a
reachable provider; otherwise it is skipped with a clear message. Output is
ASCII-only for a raw Windows console.
"""
from __future__ import annotations

import argparse
import sys

from .harness import run_tier1, run_tier2
from .report import render
from .tasks import TASKS, task_project_label


def _select(project: str | None) -> list[dict]:
    if not project:
        return TASKS
    tasks = [t for t in TASKS if task_project_label(t) == project]
    if not tasks:
        buckets = sorted({task_project_label(t) for t in TASKS})
        raise SystemExit(f"no tasks for project {project!r}. Known: {', '.join(buckets)}")
    return tasks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m daedalus.eval",
        description="Private directional eval: distillation vs concatenation. "
                    "Tier 1 is deterministic (no LLM); Tier 2 is opt-in.")
    ap.add_argument("--tier2", action="store_true",
                    help="also run the LLM A-vs-B comparison (needs a provider).")
    ap.add_argument("--project", default=None,
                    help="filter tasks to one project bucket (agent_env | sunny_garden).")
    ap.add_argument("--provider", default=None,
                    help="force a Tier-2 provider label (default: autodetect Ollama).")
    args = ap.parse_args(argv)

    tasks = _select(args.project)
    tier1 = run_tier1(tasks)
    tier2 = run_tier2(tasks, provider=args.provider) if args.tier2 else None

    # ASCII-safe print even on a cp1252 console.
    text = render(tier1, tier2)
    try:
        print(text)
    except UnicodeEncodeError:  # pragma: no cover - defensive
        sys.stdout.buffer.write(text.encode("ascii", "replace"))
        sys.stdout.buffer.write(b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

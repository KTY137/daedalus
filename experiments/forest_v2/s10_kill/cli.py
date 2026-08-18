"""Read-only entry point: evaluate a result set and print the report.

    python -m experiments.forest_v2.s10_kill.cli --demo surviving_prior
    python -m experiments.forest_v2.s10_kill.cli results.json --json

This module reads and prints.  It opens no network connection, spawns no
subprocess, and **writes no file** -- deliberately, so this directory keeps
the read-only property the forest_v2 README's boundary note depends on
(an effectful entrypoint under ``experiments/`` would have to be registered
in the canonical effect registry first).  Redirect stdout if you want the
report on disk; the decision to write is then the caller's, made outside
this experiment.

The exit code reports whether the *evaluation ran*, never what it found:
0 = evaluated, 2 = the input was not a result set this evaluator will
grade.  A KILL verdict does not change the exit code, because a nonzero
exit is how tooling gates things, and this evaluator gates nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional, Sequence

from . import SCHEMA_ID
from .criteria import EvalConfig, evaluate
from .report import build, render, to_json
from .schema import ResultSet, SchemaError
from .stats import DEFAULT_CONFIDENCE, DEFAULT_MARGIN, DEFAULT_RESAMPLES
from .synth import SCENARIOS, build as build_scenario


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="s10_kill",
        description=(
            "Evaluate master plan section 14 kill criteria over a frozen result "
            "set. Advisory only: promotes nothing, gates nothing."
        ),
    )
    p.add_argument("path", nargs="?", help=f"result set JSON ({SCHEMA_ID})")
    p.add_argument("--demo", choices=sorted(SCENARIOS), help="evaluate a synthetic run")
    p.add_argument("--demo-seed", type=int, default=None, help="seed for --demo")
    p.add_argument("--list-demos", action="store_true", help="list synthetic scenarios")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                   help="practical equivalence margin (default %(default)s)")
    p.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE,
                   help="bootstrap confidence (default %(default)s)")
    p.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES,
                   help="bootstrap resamples (default %(default)s)")
    p.add_argument("--seed", type=int, default=EvalConfig().seed,
                   help="bootstrap seed (default %(default)s)")
    p.add_argument("--min-cases", type=int, default=EvalConfig().min_cases,
                   help="withhold verdicts below this many paired cases "
                        "(default %(default)s)")
    p.add_argument("--dump-input", action="store_true",
                   help="print the (synthetic) input result set instead of evaluating")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)

    if args.list_demos:
        for name in sorted(SCENARIOS):
            doc = (SCENARIOS[name].__doc__ or "").strip().splitlines()[0]
            print(f"{name:22s} {doc}")
        return 0

    if not args.path and not args.demo:
        print("give a result set path or --demo <scenario>", file=sys.stderr)
        return 2

    try:
        if args.demo:
            obj = build_scenario(args.demo, args.demo_seed)
            if args.dump_input:
                print(json.dumps(obj, indent=2, sort_keys=True))
                return 0
            rs = ResultSet.from_obj(obj)
        else:
            rs = ResultSet.load(args.path)
    except SchemaError as exc:
        print(f"input rejected: {exc}", file=sys.stderr)
        return 2

    cfg = EvalConfig(
        margin=args.margin,
        confidence=args.confidence,
        resamples=args.resamples,
        seed=args.seed,
        min_cases=args.min_cases,
    )
    rep = build(rs, evaluate(rs, cfg), cfg)
    print(json.dumps(to_json(rep), indent=2, sort_keys=True) if args.as_json else render(rep))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

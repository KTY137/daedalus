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
from . import measured_inputs
from .criteria import EvalConfig, evaluate
from .report import build, render, to_json
from .measured_inputs import MEASURED_RUNS, build as build_measured
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
    p.add_argument("--measured", choices=sorted(MEASURED_RUNS),
                   help="evaluate a run rebuilt from a real published measurement")
    p.add_argument("--demo-seed", type=int, default=None, help="seed for --demo")
    p.add_argument("--list-demos", action="store_true", help="list synthetic scenarios")
    p.add_argument(
        "--plane-census", action="store_true",
        help="print gold labels per plane across every query set in the program, "
             "and the planes that are never a retrieval target anywhere",
    )
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
            print(f"{name:22s} {doc}   [synthetic]")
        for name in sorted(MEASURED_RUNS):
            doc = (MEASURED_RUNS[name].__doc__ or "").strip().splitlines()[0]
            print(f"{name:22s} {doc}   [MEASURED, rebuilt from published counts]")
        return 0

    if args.plane_census:
        census = measured_inputs.program_plane_census()
        docs, gold = census["documents"], census["gold_labels"]
        print("Gold labels per plane, across every query set this program has")
        print(f"{'plane':12s} {'documents':>10s} {'gold labels':>12s}")
        for plane in sorted(docs):
            print(f"{plane:12s} {docs[plane]:>10d} {gold.get(plane, 0):>12d}")
        for name in ("frozen600", "noncode138", "extended738"):
            mix = census[name]
            print(f"  {name:12s} " + ", ".join(f"{p}={n}" for p, n in mix.items()))
        never = measured_inputs.planes_never_a_retrieval_target()
        print()
        print(
            "planes that can never be a retrieval target anywhere in the program: "
            + (", ".join(never) if never else "(none)")
        )
        if never:
            print(
                "  a plane with documents in the corpus and no gold label in any "
                "query set is a plane no measurement here can say anything about; "
                "every criterion that names it is UNDECIDABLE by construction"
            )
        return 0

    if not args.path and not args.demo and not args.measured:
        print(
            "give a result set path, --demo <scenario> or --measured <run>",
            file=sys.stderr,
        )
        return 2

    try:
        if args.demo or args.measured:
            obj = (
                build_measured(args.measured) if args.measured
                else build_scenario(args.demo, args.demo_seed)
            )
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

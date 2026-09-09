"""Is the Type plane empty because this repository has no types, or because the plane rule cannot see them?

`docs/GATE2_CROSS_PLANE_SUPPLY_CEILING_20260909.md` records that criterion 14.4
(`plane_has_no_marginal_contribution`) is NOT_EVALUABLE because the Type plane
carries 0 gold labels, and calls that a labelling problem rather than a
sample-size one. This probe measures which.

The frozen rule maps planes by file suffix (`taskset.py::PLANE_BY_SUFFIX`), and
its own comment says the consequence out loud:

    the Type plane has no file-level representative at all, so a corpus can
    look "three-plane" here while touching two.

That is true of the RULE. It is not obviously true of the repository. Plan §5
defines the Type plane as "declared/inferred types, constraints, contracts,
interfaces", and this tree tracks 90 `*.schema.json` files -- JSON Schema, i.e.
declared contracts -- which the suffix rule sends to `data` along with every
config and fixture.

So the probe applies ONE refinement and nothing else: a path whose name ends
`.schema.json` is Type, not Data. Everything else is untouched.

This probe CHANGES NOTHING. It does not rewrite the frozen task set, whose
digest is load-bearing, and it does not re-run any retriever. It answers one
question: if the rule could see schemas, how much Type-plane gold would exist,
and how many commits would become genuinely cross-plane that are not today?

Reading the result honestly:

* A large number does NOT mean the four-plane prior is supported. It means one
  ablation becomes runnable that is not runnable now.
* A small number is the more interesting outcome: it would mean the Type plane
  is empty here on the merits, and the write-up's "labelling problem" framing
  is wrong and must be corrected.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from experiments.forest_v2.s09_eval import taskset as frozen

REPO = Path(__file__).resolve().parents[3]
ANCHOR = "d849c2a94d66ffb1bf892de924995645395bf2a6"
WINDOW = 1200

TWIN_PLANES = ("code", "type", "data", "knowledge")


def refined_plane_of(path: str) -> str:
    """The frozen rule plus exactly one refinement: schemas are Type.

    Deliberately narrow. ``*.schema.json`` is an explicit, self-describing
    naming convention already used consistently in this tree (41 files under
    configs/schemas, 41 under daedalus/resources/schemas), so it needs no
    content sniffing and cannot silently capture an ordinary config file.
    """
    if path.lower().endswith(".schema.json"):
        return "type"
    return frozen.plane_of(path)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--anchor", default=ANCHOR)
    parser.add_argument("--window", type=int, default=WINDOW)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    commits = _git(
        "log", "--format=%H", f"-n{args.window}", args.anchor
    ).split()

    frozen_combos: Counter[str] = Counter()
    refined_combos: Counter[str] = Counter()
    gained_type = 0
    became_cross_plane = 0
    four_plane = 0
    type_gold_paths = 0
    examples: list[dict] = []

    for sha in commits:
        paths = [
            line
            for line in _git(
                "show", "--name-only", "--format=", sha
            ).splitlines()
            if line.strip()
        ]
        if not paths:
            continue
        f_planes = tuple(
            sorted({frozen.plane_of(p) for p in paths} & set(TWIN_PLANES))
        )
        r_planes = tuple(
            sorted({refined_plane_of(p) for p in paths} & set(TWIN_PLANES))
        )
        if not f_planes and not r_planes:
            continue
        frozen_combos["+".join(f_planes) or "(none)"] += 1
        refined_combos["+".join(r_planes) or "(none)"] += 1

        n_type = sum(1 for p in paths if refined_plane_of(p) == "type")
        type_gold_paths += n_type
        if "type" in r_planes:
            gained_type += 1
            if len(f_planes) < 2 <= len(r_planes):
                became_cross_plane += 1
            if len(r_planes) == 4:
                four_plane += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "commit": sha[:12],
                        "frozen_planes": f_planes,
                        "refined_planes": r_planes,
                        "type_paths": [
                            p for p in paths if refined_plane_of(p) == "type"
                        ][:3],
                    }
                )

    result = {
        "anchor": args.anchor,
        "window": args.window,
        "commits_walked": len(commits),
        "commits_with_type_gold": gained_type,
        "commits_that_become_cross_plane": became_cross_plane,
        "commits_spanning_all_four_planes": four_plane,
        "type_gold_paths_total": type_gold_paths,
        "frozen_plane_combinations": dict(frozen_combos.most_common()),
        "refined_plane_combinations": dict(refined_combos.most_common()),
        "examples": examples,
    }

    if args.as_json:
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0

    print("=" * 74)
    print("Type-plane supply under ONE refinement: *.schema.json is Type")
    print("=" * 74)
    print(f"anchor {args.anchor[:12]}   window {args.window}   "
          f"commits walked {len(commits)}")
    print()
    print(f"  commits carrying Type gold          : {gained_type:>5}")
    print(f"  ... that are single-plane TODAY     : {became_cross_plane:>5}")
    print(f"  commits spanning all FOUR planes    : {four_plane:>5}")
    print(f"  Type gold paths in total            : {type_gold_paths:>5}")
    print()
    print("  frozen plane combinations (top 8):")
    for combo, n in list(frozen_combos.most_common(8)):
        print(f"    {combo:<28} {n:>5}")
    print("  refined plane combinations (top 8):")
    for combo, n in list(refined_combos.most_common(8)):
        print(f"    {combo:<28} {n:>5}")
    if examples:
        print()
        print("  examples:")
        for ex in examples:
            print(f"    {ex['commit']}  {'+'.join(ex['frozen_planes'])}"
                  f"  ->  {'+'.join(ex['refined_planes'])}")
            for p in ex["type_paths"]:
                print(f"        {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

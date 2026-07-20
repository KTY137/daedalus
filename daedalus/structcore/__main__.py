"""CLI:  python -m daedalus.structcore <repo> [--json out.json]

Prints a derived, multi-language structural summary for distillation targeting.
Works stdlib-only; installs of ``tree-sitter-language-pack`` and ``lizard``
sharpen it (shown in the backend line).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .index import build_index


def print_summary(idx: dict) -> None:
    b = idx["backend"]
    langs = idx["languages"]
    print(f"\n=== STRUCTCORE -- {idx['n_files']} files across {len(langs)} languages ===")
    print(f"backend: tree-sitter={'on' if b['tree_sitter'] else 'OFF (stdlib+window only)'} "
          f"| lizard={'on' if b['lizard'] else 'off'}")

    # State the exclusion out loud. A smaller report with no explanation looks
    # like a cleaner codebase, which is the failure mode worth avoiding.
    ign = idx.get("ignored") or {}
    if ign.get("count"):
        why = []
        if ign.get("center"):
            why.append("center=" + ",".join(ign["center"][:4]))
        if ign.get("ignore_patterns"):
            why.append("ignore=" + ",".join(ign["ignore_patterns"][:4]))
        print(f"scope:   {ign['count']} of {ign['n_files_scanned']} files are SHELL, withheld "
              f"from metrics [{' '.join(why)}]")
        print("         (shell stays resolvable as an import target; it is not expanded through)")
    print("\nLANGUAGES (by loc):")
    for lang, s in langs.items():
        print(f"  {s['loc']:7}  {s['files']:4} files  {lang}")

    if idx["fan_in"]:
        print("\nTOP FAN-IN (most depended-on internal modules):")
        for mod, n in list(idx["fan_in"].items())[:10]:
            print(f"  {n:3}  {mod}")

    print("\nHOTSPOTS (distillation targets -- complexity x churn rank):")
    for h in idx["hotspots"][:10]:
        cc = f" cc_max={h['cc_max']}" if h.get("cc_max") else ""
        churn = f", churn={h['churn']}" if h.get("churn") else ""
        print(f"  {h['score']:6}  {h['module']}  ({h['loc']} loc, "
              f"{h['long_functions']} long fns, {h['guard_count']} guards{cc}{churn})")

    dup = idx["duplication"]
    units = dup["unit_clusters"]
    print(f"\nEXACT CLONE CLUSTERS (Type-1, precise, {len(units)} found):")
    for c in units[:12]:
        sites = ", ".join(f"{s['module']}:{s['line']}" for s in c["sites"][:5])
        more = "" if len(c["sites"]) <= 5 else f" +{len(c['sites']) - 5}"
        fence = "  [!] SAFETY-FENCED" if c.get("safety") else ""
        print(f"  x{c['count']}  (~{c['loc']} loc)  {c['language']}:{c['name']}  "
              f"[{sites}{more}]{fence}")

    renamed = dup.get("renamed_clusters", [])
    print(f"\nRENAMED CLONE CLUSTERS (Type-2, {len(renamed)} found):")
    for c in renamed[:10]:
        names = ", ".join(c.get("names", [c["name"]])[:5])
        fence = "  [!] SAFETY-FENCED" if c.get("safety") else ""
        print(f"  x{c['count']}  (~{c['loc']} loc)  {c['language']}:{{{names}}}{fence}")

    near = dup.get("near_clusters", [])
    print(f"\nNEAR-MISS CLONE CLUSTERS (Type-3, advisory, {len(near)} found):")
    for c in near[:10]:
        names = ", ".join(c.get("names", [c["name"]])[:5])
        fence = "  [!] SAFETY-FENCED" if c.get("safety") else ""
        print(f"  ~{c.get('similarity')} sim  x{c['count']}  (~{c['loc']} loc)  "
              f"{c['language']}:{{{names}}}{fence}")

    wins = dup["window_clusters"]
    print(f"\nWINDOW CLONE CLUSTERS (universal, {len(wins)} file-sets share runs):")
    for c in wins[:10]:
        fence = "  [!] SAFETY-FENCED" if c.get("safety") else ""
        print(f"  {c['shared_runs']:4} runs  {' , '.join(c['files'][:4])}{fence}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="daedalus.structcore",
                                 description="Derived multi-language structural index.")
    ap.add_argument("repo", nargs="?", default=".", help="repo root to index")
    ap.add_argument("--json", type=str, default=None, help="write full index to this JSON path")
    ap.add_argument("--max-files", type=int, default=20000)
    ap.add_argument("--center", action="append", default=None, metavar="PATH",
                    help="repo-relative source root that IS the project (repeatable). "
                         "Everything outside it is shell: still resolvable as an import "
                         "target, but withheld from metrics. Default: the whole repo.")
    ap.add_argument("--ignore", action="append", default=None, metavar="PATTERN",
                    help="extra ignore pattern (repeatable). Composes on top of "
                         ".daedalusignore. '@tests' expands to the test-file preset.")
    args = ap.parse_args(argv)

    idx = build_index(args.repo, max_files=args.max_files, center=args.center,
                      ignore=args.ignore)
    if args.json:
        Path(args.json).write_text(json.dumps(idx, indent=1), encoding="utf-8")
        print(f"wrote {args.json}")
    print_summary(idx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

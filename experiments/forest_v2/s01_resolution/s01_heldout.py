"""EXPERIMENT (forest_v2 / slice s01): the held-out corpus run.

Read-only.  Pure stdlib.  Prints exactly one JSON object; no writes, no
network, no subprocess, no model calls.

Why this file exists: the slice's headline was measured on the repository it
was written against, which is the corpus its author looked at while writing the
resolver.  The plan's kill criteria list *"benefits disappear on held-out
repositories"* (section 14 in the revision checked out on this branch, section
13 in revision 1 -- cite it by name), so the claim has to be re-run somewhere
the author never tuned anything.  The corpus is the CPython standard library of the
interpreter running this script -- a tree with a different import culture,
different class-per-module density, and no relationship to this project.

It **fired**.  On 2026-08-18, CPython 3.10.11, 21 packages, 201 modules, 18,683
call sites: B0 32.58 %, B1 35.85 %, s01 29.73 % -- the resolver is *below* every
baseline arm on the metric the retracted headline used.  See ``README.md``,
"Retraction".

Usage::

    python experiments/forest_v2/s01_resolution/s01_heldout.py [--corpus DIR]
"""
from __future__ import annotations

import ast
import json
import sys
import sysconfig
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _extra in (_HERE, _HERE.parent):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import probe_cross_module_resolution as probe  # noqa: E402
from s01_index import build_index  # noqa: E402
from s01_measure import BASELINE_ARMS, DEFAULT_ARM, _baseline_site  # noqa: E402
from s01_resolver import resolve_module  # noqa: E402

#: Stdlib packages used as the held-out corpus.  Chosen once, before the run,
#: as "every package directory in Lib/ that is library code rather than tooling
#: or data": no ``idlelib``/``turtledemo``/``distutils``/``ensurepip``/``msilib``
#: (tools), no ``encodings``/``pydoc_data`` (generated tables), no ``lib2to3``
#: (deprecated), no ``tkinter`` (thin binding over a C extension).
PACKAGES = (
    "asyncio", "collections", "concurrent", "ctypes", "curses", "dbm", "email",
    "html", "http", "importlib", "json", "logging", "multiprocessing",
    "sqlite3", "unittest", "urllib", "venv", "wsgiref", "xml", "xmlrpc",
    "zoneinfo",
)

#: Test trees are excluded: they are not library code and would let a package's
#: own test helpers inflate every arm at once.
EXCLUDED_PATH_PARTS = ("/test/", "/tests/", "/idle_test/")

REPO_BUCKETS = ("same_module_resolvable", "cross_module_repo")


def held_out(corpus: Path, packages: tuple[str, ...] = PACKAGES) -> dict:
    index = build_index(corpus, packages)
    for name in [
        n
        for n, m in index.modules.items()
        if any(part in "/" + m.rel for part in EXCLUDED_PATH_PARTS)
    ]:
        module = index.modules.pop(name)
        index.by_rel.pop(module.rel, None)
    index._attr_cache.clear()

    module_symbols = {
        name: probe._collect_symbols(info.tree) for name, info in index.modules.items()
    }
    arm_repo = Counter()
    arm_contradictions = Counter()
    arm_same_module = Counter()
    status = Counter()
    per_package: dict[str, Counter] = {}
    calls = 0

    for module in index.modules.values():
        package = module.rel.split("/")[0]
        counter = per_package.setdefault(package, Counter())
        counter["modules"] += 1
        by_id = {id(node): res for node, res in resolve_module(index, module)}
        bindings = probe._bindings(module.tree, module.name)
        arm_names = {arm: build(module.tree) for arm, build in BASELINE_ARMS.items()}

        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            res = by_id.get(id(node))
            if res is None:
                continue
            calls += 1
            counter["calls"] += 1
            status[res.status] += 1
            if res.status == "verified":
                counter["s01_verified"] += 1
            name = probe._call_name(node.func)
            for arm, names in arm_names.items():
                bucket = _baseline_site(name, names, bindings, module_symbols)
                if bucket in REPO_BUCKETS:
                    arm_repo[arm] += 1
                    counter[f"{arm}_repo"] += 1
                if bucket == "same_module_resolvable":
                    arm_same_module[arm] += 1
                    if res.status == "verified" and res.target_module != module.name:
                        arm_contradictions[arm] += 1
                    elif res.status == "external":
                        arm_contradictions[arm] += 1

    verified = status["verified"]
    denominator = calls or 1

    def pct(value: int) -> float:
        return round(100.0 * value / denominator, 2)

    arms = {}
    for arm in BASELINE_ARMS:
        arms[arm] = {
            "repo_claimed": arm_repo[arm],
            "repo_claimed_pct": pct(arm_repo[arm]),
            "s01_lift_pp": round(pct(verified) - pct(arm_repo[arm]), 2),
            "same_module_claims": arm_same_module[arm],
            "contradicted_by_s01": arm_contradictions[arm],
            "contradiction_rate_pct": round(
                100.0 * arm_contradictions[arm] / (arm_same_module[arm] or 1), 2
            ),
        }

    packages_report = {}
    favourable = Counter()
    for package, counter in sorted(per_package.items()):
        total = counter["calls"] or 1
        entry = {
            "modules": counter["modules"],
            "call_sites": counter["calls"],
            "s01_verified_pct": round(100.0 * counter["s01_verified"] / total, 2),
        }
        for arm in BASELINE_ARMS:
            lift = round(
                100.0 * counter["s01_verified"] / total
                - 100.0 * counter[f"{arm}_repo"] / total,
                2,
            )
            entry[f"{arm}_repo_pct"] = round(100.0 * counter[f"{arm}_repo"] / total, 2)
            entry[f"s01_lift_vs_{arm}_pp"] = lift
            if lift > 0:
                favourable[arm] += 1
        packages_report[package] = entry

    return {
        "schema": "forest-v2-s01-heldout/1",
        "read_only": True,
        "corpus": corpus.as_posix(),
        "python": sys.version.split()[0],
        "packages": list(packages),
        "modules": len(index.modules),
        "call_sites": calls,
        "default_arm": DEFAULT_ARM,
        "s01": {
            "verified": verified,
            "verified_pct": pct(verified),
            "external": status["external"],
            "unresolved": status["unresolved"],
        },
        "arms": arms,
        "favourable_packages": {
            arm: f"{favourable[arm]} of {len(per_package)}" for arm in BASELINE_ARMS
        },
        "per_package": packages_report,
        "kill_criterion": {
            "plan_section": "13/14 -- benefits disappear on held-out repositories",
            "fired": arms[DEFAULT_ARM]["s01_lift_pp"] <= 0,
        },
    }


def main(argv: list[str]) -> int:
    corpus = Path(sysconfig.get_paths()["stdlib"])
    rest = list(argv)
    while rest:
        item = rest.pop(0)
        if item == "--corpus" and rest:
            corpus = Path(rest.pop(0))
    print(json.dumps(held_out(corpus), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

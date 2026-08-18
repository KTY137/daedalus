"""EXPERIMENT slice s02, continuation 3: the same metrics on corpora that are
not this repository.

Why this exists
---------------
The slice's original headline was measured on one corpus that happens to be
92.89% annotated, and the marginal contribution of the resolver machinery over
an annotation-only control came out at 0.119 pp there.  That number says
something about ``daedalus``, not about type-plane construction.  Whether the
machinery buys anything is a property of the corpus, so it has to be measured
on corpora with different annotation postures.

Frozen sub-spec (declared before the run)
-----------------------------------------
* Same frame as the rest of the slice: read-only AST, stdlib only, no imports
  of the analysed code, no writes, no network, no subprocess, one JSON object.
* Corpora are declared in ``CORPORA`` below and every declared corpus is
  reported, present or absent.  Nothing is dropped after its numbers are seen.
  The third-party set was chosen for spread of *typing posture* -- two
  ``py.typed`` distributions, one re-export-heavy pair, two largely
  unannotated ones -- before any of them was measured.
* Every corpus carries a content pin.  Third-party corpora are whatever this
  interpreter has installed; the pin, not a version string, is what makes a
  re-run comparable.
* Expiry: same as the slice (2026-09-15).  Re-measure before reuse.

What to read out of it
----------------------
``annotation_only_pct``     the control: how much is syntactically complete.
``marginal_pp``             what the whole binding + symbol-table machinery
                            adds over that control.  It is subtractive by
                            construction and this is its ceiling too.
``type_name_resolution_pct`` decoupled from coverage: of the type names that
                            ARE written, how many attribute at all.
``verified_share_of_internal_pct``  of the names attributed to the corpus
                            itself, how many were verified against a symbol
                            table rather than merely named.  This is the one
                            that moves between corpora, and the one
                            ``corpus_alias`` shows to be optimistic.
"""
from __future__ import annotations

import argparse
import json
import sys
import sysconfig
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import type_plane as tp  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
STDLIB = Path(sysconfig.get_paths()["stdlib"])
SITE = Path(sysconfig.get_paths()["purelib"])
USER_SITE = Path(sysconfig.get_paths()["purelib"])
try:  # the Windows Store layout keeps user installs elsewhere
    import site as _site

    _user = Path(_site.getusersitepackages())
    if _user.is_dir():
        USER_SITE = _user
except Exception:  # pragma: no cover - defensive only
    pass


def stdlib_packages() -> tuple[str, ...]:
    """Every pure-python stdlib package directory, no exclusions.

    Enumerated rather than listed on purpose: a hand-picked subset of the
    standard library is a subset someone chose, and the choice would be
    unfalsifiable.
    """
    if not STDLIB.is_dir():
        return ()
    return tuple(
        sorted(
            p.name
            for p in STDLIB.iterdir()
            if p.is_dir() and (p / "__init__.py").is_file()
        )
    )


CORPORA: tuple[dict[str, Any], ...] = (
    {
        "name": "kernel",
        "note": "this repository's kernel package -- the original headline",
        "root": REPO_ROOT,
        "packages": ("daedalus",),
    },
    {
        "name": "fixture_alias",
        "note": "the hand-answered fixture from continuation 2",
        "root": HERE / "corpus_alias",
        "packages": ("xpkg",),
    },
    {
        "name": "stdlib",
        "note": "every pure-python stdlib package of this interpreter",
        "root": STDLIB,
        "packages": None,  # filled from stdlib_packages()
    },
    {
        "name": "third_party_typed",
        "note": "py.typed distributions, annotation-heavy",
        "root": USER_SITE,
        "packages": ("fastapi", "anyio"),
    },
    {
        "name": "third_party_reexport",
        "note": "the canonical re-export pair: attrs re-exports attr",
        "root": USER_SITE,
        "packages": ("attr", "attrs"),
    },
    {
        "name": "third_party_untyped",
        "note": "no py.typed, largely unannotated",
        "root": USER_SITE,
        "packages": ("bs4", "click"),
    },
)


def measure(spec: dict[str, Any]) -> dict[str, Any]:
    root: Path = spec["root"]
    packages = spec["packages"]
    if packages is None:
        packages = stdlib_packages()
    present = [p for p in packages if (root / p).is_dir()]
    if not present:
        return {
            "name": spec["name"],
            "note": spec["note"],
            "present": False,
            "reason": f"no package of {list(packages)} under {root.as_posix()}",
        }

    started = time.perf_counter()
    report = tp.build_type_plane(root, tuple(present))
    elapsed = round(time.perf_counter() - started, 2)

    totals = report["totals"]
    sites = report["type_name_sites_by_bucket"]
    internal = sites.get("repo", 0) + sites.get("repo_unverified", 0)

    def pct(num: int, den: int) -> float:
        return round(100.0 * num / (den or 1), 2)

    return {
        "name": spec["name"],
        "note": spec["note"],
        "present": True,
        "root": root.as_posix(),
        "packages": list(present),
        "packages_missing": [p for p in packages if p not in present],
        "corpus_pin": report["corpus_pin"],
        "files_parsed": totals["files_parsed"],
        "files_unparseable": totals["files_unparseable"],
        "functions": report["functions_total"],
        "wall_seconds": elapsed,
        "annotation_only_pct": report["controls"]["annotation_only"]["pct"],
        "full_resolver_pct": report["controls"]["full_resolver"]["pct"],
        "marginal_functions": report["controls"]["marginal_vs_annotation_only"][
            "functions"
        ],
        "marginal_pp": report["controls"]["marginal_vs_annotation_only"]["pp"],
        "type_name_sites": totals["type_name_sites"],
        "type_name_resolution_pct": report["rates"]["type_name_resolution_pct"],
        "sig_present_annotations_resolve_pct": report["rates"][
            "sig_present_annotations_resolve_pct"
        ],
        "internal_name_sites": internal,
        "internal_verified": sites.get("repo", 0),
        "internal_named_only": sites.get("repo_unverified", 0),
        "verified_share_of_internal_pct": pct(sites.get("repo", 0), internal),
        "type_name_sites_by_bucket": sites,
    }


def run() -> dict[str, Any]:
    measured = [measure(spec) for spec in CORPORA]
    present = [m for m in measured if m["present"]]
    return {
        "schema": "forest-v2-type-plane-corpora/1",
        "read_only": True,
        "python": sys.version.split()[0],
        "stdlib_root": STDLIB.as_posix(),
        "site_root": USER_SITE.as_posix(),
        "corpora_declared": len(CORPORA),
        "corpora_measured": len(present),
        "annotation_only_pct_range": (
            [
                min(m["annotation_only_pct"] for m in present),
                max(m["annotation_only_pct"] for m in present),
            ]
            if present
            else []
        ),
        "corpora": measured,
    }


def table(report: dict[str, Any]) -> str:
    header = (
        f"{'corpus':22s} {'funcs':>7s} {'annot%':>8s} {'resolv%':>8s} "
        f"{'marg pp':>8s} {'names':>7s} {'name res%':>10s} {'verif int%':>11s}"
    )
    lines = [header, "-" * len(header)]
    for m in report["corpora"]:
        if not m["present"]:
            lines.append(f"{m['name']:22s} {'--- absent: ' + m['reason']}")
            continue
        lines.append(
            f"{m['name']:22s} {m['functions']:7d} {m['annotation_only_pct']:8.2f} "
            f"{m['full_resolver_pct']:8.2f} {m['marginal_pp']:8.3f} "
            f"{m['type_name_sites']:7d} {m['type_name_resolution_pct']:10.2f} "
            f"{m['verified_share_of_internal_pct']:11.2f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="s02 type plane across corpora")
    parser.add_argument("--table", action="store_true", help="human table instead of JSON")
    args = parser.parse_args(argv)
    report = run()
    print(table(report) if args.table else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

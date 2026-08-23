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

Continuation 4 (2026-08-18): the kernel row stopped being a moving target
------------------------------------------------------------------------
The kernel row used to be measured against the working tree and then pinned
exactly.  Two unrelated kernel commits added one function, ``functions``
became 4204, and a check that had nothing to do with those commits went red
and stopped a port.  The guard was correct; the pin was not, because a
reproducible number needs a fixed input and the working tree is not one.

So the kernel is measured twice now and the two rows have different jobs:

``kernel_at_pin``   the tree at ``revision_corpus.PINNED_REVISION``, read out
                    of git history.  These are the numbers the write-up
                    publishes and they are pinned exactly -- forever, because
                    the input can no longer move.
``kernel``          the live working tree.  Its counts are **reported**, not
                    asserted.  What is asserted about it is the qualitative
                    finding (see ``drift_vs_pin`` and the checks): a count
                    that moves with every commit is an observation, not an
                    assertion.

``drift_vs_pin`` in the report says whether the live tree still is the pinned
tree and, when it is not, exactly which values moved and by how much.  A moved
tree now produces a reported difference instead of a red check.

Frozen sub-spec (declared before the run)
-----------------------------------------
* Same frame as the rest of the slice: read-only AST, stdlib only, no imports
  of the analysed code, no writes, one JSON object.  Continuation 4 declares
  one exception to "no subprocess": ``revision_corpus`` shells read-only git
  plumbing behind a verb allowlist, because history is the only place a past
  tree still exists.  It writes only into a temporary directory it creates and
  removes, never into the repository.
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

import revision_corpus as rc  # noqa: E402
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
        "name": "kernel_at_pin",
        "note": (
            "the kernel package at the revision the published numbers were "
            "measured against -- frozen input, so these are pinned exactly"
        ),
        "root": REPO_ROOT,
        "packages": ("daedalus",),
        "revision": rc.PINNED_REVISION,
    },
    {
        "name": "kernel",
        "note": (
            "the same package in the live working tree -- reported, never "
            "pinned; see drift_vs_pin"
        ),
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

    revision = spec.get("revision")
    if revision:
        # Frozen input: the tree as it was at ``revision``, not as it is now.
        # An unreachable anchor is reported as absent with a reason -- like
        # any other missing corpus -- because it is a different failure from a
        # moved tree and the checks distinguish the two.
        started = time.perf_counter()
        try:
            report = rc.measure_at_revision(tuple(packages), revision, root)
        except rc.RevisionUnavailable as exc:
            return {
                "name": spec["name"],
                "note": spec["note"],
                "present": False,
                "pinned_revision": revision,
                "reason": f"pinned revision {revision[:12]} unreadable: {exc}",
            }
        elapsed = round(time.perf_counter() - started, 2)
        return _summarise(spec, report, list(packages), elapsed)

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
    return _summarise(spec, report, list(packages), elapsed)


def _summarise(
    spec: dict[str, Any],
    report: dict[str, Any],
    requested: list[str],
    elapsed: float,
) -> dict[str, Any]:
    """One row of the comparison, whatever the input tree came from."""
    present = list(report["packages"])
    totals = report["totals"]
    sites = report["type_name_sites_by_bucket"]
    internal = sites.get("repo", 0) + sites.get("repo_unverified", 0)

    def pct(num: int, den: int) -> float:
        return round(100.0 * num / (den or 1), 2)

    return {
        "name": spec["name"],
        "note": spec["note"],
        "present": True,
        "root": report["root"],
        "revision": report.get("revision"),
        "revision_is_pinned": bool(report.get("revision_is_pinned")),
        "packages": present,
        "packages_missing": [p for p in requested if p not in present],
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


#: The values that move whenever the kernel package gains or loses a function.
#: They are published against the pin and *reported* against the live tree.
#: Anything not listed here is either qualitative or an arithmetic identity,
#: and those are asserted on both rows.
DRIFTING_FIELDS: tuple[str, ...] = (
    "functions",
    "annotation_only_pct",
    "full_resolver_pct",
    "marginal_pp",
    "files_parsed",
)


def drift(pinned: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """How far the live working tree has moved from the published measurement.

    This is the replacement for pinning the live tree.  It answers "are the
    write-up's kernel numbers still the numbers you would measure today", and
    when the answer is no it says which ones moved -- as data, on stdout, not
    as a failing check.  Only a moved *anchor* is a failure; a moved tree is
    news.
    """
    if not pinned.get("present"):
        return {
            "comparable": False,
            "reason": pinned.get("reason", "the pinned row was not measured"),
        }
    if not live.get("present"):
        return {
            "comparable": False,
            "reason": live.get("reason", "the live row was not measured"),
        }
    pin_digest = pinned["corpus_pin"]["sha256"]
    live_digest = live["corpus_pin"]["sha256"]
    fields: dict[str, Any] = {}
    for key in DRIFTING_FIELDS:
        before, after = pinned.get(key), live.get(key)
        if before != after:
            entry = {"pinned": before, "live": after}
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                entry["delta"] = round(after - before, 4)
            fields[key] = entry
    return {
        "comparable": True,
        "pinned_revision": pinned.get("revision"),
        "pinned_digest": pin_digest,
        "live_digest": live_digest,
        "tree_unchanged": pin_digest == live_digest,
        "drifted": fields,
        "note": (
            "the published kernel numbers are the pinned row; the live row is "
            "an observation of today's tree and is never pinned"
        ),
    }


def run() -> dict[str, Any]:
    measured = [measure(spec) for spec in CORPORA]
    present = [m for m in measured if m["present"]]
    by_name = {m["name"]: m for m in measured}
    return {
        "schema": "forest-v2-type-plane-corpora/2",
        "drift_vs_pin": drift(by_name["kernel_at_pin"], by_name["kernel"]),
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
    lines.append("")
    lines.append(_drift_lines(report["drift_vs_pin"]))
    return "\n".join(lines)


def _drift_lines(block: dict[str, Any]) -> str:
    if not block.get("comparable"):
        return f"drift vs pin: NOT COMPARABLE -- {block.get('reason')}"
    rev = (block.get("pinned_revision") or "?")[:12]
    if block["tree_unchanged"]:
        return (
            f"drift vs pin ({rev}): none -- the live tree is the pinned tree "
            f"(digest {block['pinned_digest'][:12]})"
        )
    out = [
        f"drift vs pin ({rev}): the live tree has MOVED",
        f"  pinned digest {block['pinned_digest'][:12]}  "
        f"live digest {block['live_digest'][:12]}",
    ]
    if not block["drifted"]:
        out.append("  no reported value changed; the movement is elsewhere in the tree")
    for key, entry in sorted(block["drifted"].items()):
        delta = entry.get("delta")
        suffix = f"  ({delta:+})" if isinstance(delta, (int, float)) else ""
        out.append(f"  {key:24s} pinned {entry['pinned']}  ->  live {entry['live']}{suffix}")
    out.append("  the write-up publishes the pinned row; this is an observation.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="s02 type plane across corpora")
    parser.add_argument("--table", action="store_true", help="human table instead of JSON")
    args = parser.parse_args(argv)
    report = run()
    print(table(report) if args.table else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""EXPERIMENT slice s02, continuation 2: does the resolver get names RIGHT?

The coverage probe in ``type_plane.py`` answers "was every name in this
signature attributable".  It cannot answer "was the attribution correct",
because on the kernel package there is nothing to compare against: the
extractor's own output is the only account of the truth.

This module supplies the missing comparison.  It runs the SAME machinery
(``type_plane.Resolver``, ``import_bindings``, ``top_level_symbols``) over a
small fixture corpus in ``corpus_alias/`` whose every annotation site has a
hand-computed answer recorded in ``ground_truth.json``, and reports where the
resolver agrees, over-claims, and misses.

Why a fixture corpus and not the kernel package: the kernel is 92.89%
annotated, uses almost no re-export chains, and has zero wildcard imports, so
the two failure modes that matter -- multi-hop re-export and scope shadowing --
do not occur there in measurable quantity.  A corpus where the resolver cannot
fail is not evidence that the resolver works.

Verdict vocabulary
------------------
``hit``          bucket and canonical name both match the hand answer.
``miss``         the hand answer names a real definition in the corpus; the
                 resolver did not verify it (``repo_unverified``,
                 ``unresolved``, ...).  A recall failure.
``overclaim``    the resolver returned a VERIFIED ``repo`` attribution whose
                 canonical name is not the definition the annotation means.
                 A precision failure, and the dangerous one: downstream
                 consumers cannot tell it from a hit.
``abstain_ok``   the hand answer is "no definition exists"; the resolver said
                 ``unresolved``.  Correct.
``abstain_bad``  the hand answer is "no definition exists"; the resolver
                 attributed something anyway.

Read-only, stdlib-only, no writes, no network, no subprocess, one JSON object
on stdout -- the frozen frame of the slice is unchanged.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, Iterable

sys_path_marker = Path(__file__).resolve().parent
if str(sys_path_marker) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(sys_path_marker))

import type_plane as tp  # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parent / "corpus_alias"
GROUND_TRUTH = Path(__file__).resolve().parent / "ground_truth.json"
CORPUS_PACKAGES = ("xpkg",)


# --------------------------------------------------------------------------
# per-site resolution, through the production resolver
# --------------------------------------------------------------------------
def _annotation_exprs(tree: ast.Module) -> list[tuple[ast.expr, str]]:
    """Every expression used in a type position, with its context label."""
    out: list[tuple[ast.expr, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in (
                list(args.posonlyargs)
                + list(args.args)
                + list(args.kwonlyargs)
                + [a for a in (args.vararg, args.kwarg) if a is not None]
            ):
                if arg.annotation is not None:
                    out.append((arg.annotation, "param"))
            if node.returns is not None:
                out.append((node.returns, "return"))
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                out.append((base, "base"))
        elif isinstance(node, ast.AnnAssign):
            out.append((node.annotation, "field"))
    return out


def _leaf_names(expr: ast.expr) -> list[tuple[str, int]]:
    """Dotted name leaves of an annotation expression, with line numbers."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        try:
            inner = ast.parse(expr.value, mode="eval").body
        except SyntaxError:
            return []
        # a forward ref carries no line of its own; use the string's line
        return [(name, expr.lineno) for name, _ in _leaf_names(inner)]
    if isinstance(expr, (ast.Name, ast.Attribute)):
        dotted = tp.dotted_of(expr)
        return [(dotted, expr.lineno)] if dotted else []
    out: list[tuple[str, int]] = []
    for child in ast.iter_child_nodes(expr):
        if isinstance(child, ast.expr):
            out.extend(_leaf_names(child))
    return out


def resolve_sites(
    root: Path = CORPUS_DIR, packages: Iterable[str] = CORPUS_PACKAGES
) -> list[dict[str, Any]]:
    packages = tuple(packages)
    paths = list(tp.iter_py_files(root, packages))
    parsed = []
    module_symbols: dict[str, set[str]] = {}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module, is_package = tp.module_name_of(root, path)
        parsed.append((path, module, is_package, tree))
        module_symbols[module] = tp.top_level_symbols(tree)

    resolver = tp.Resolver(
        module_symbols=module_symbols,
        module_names=set(module_symbols),
        repo_roots=frozenset(packages),
    )

    sites: list[dict[str, Any]] = []
    for path, module, is_package, tree in parsed:
        rel = path.relative_to(root).as_posix()
        bindings = tp.import_bindings(tree, module, is_package)
        local = module_symbols[module]
        for expr, context in _annotation_exprs(tree):
            for written, line in _leaf_names(expr):
                bucket, canonical = resolver.resolve(written, module, local, bindings)
                sites.append(
                    {
                        "file": rel,
                        "line": line,
                        "written": written,
                        "context": context,
                        "bucket": bucket,
                        "canonical": canonical,
                    }
                )
    sites.sort(key=lambda s: (s["file"], s["line"], s["written"], s["context"]))
    return sites


# --------------------------------------------------------------------------
# grading against the hand-computed answers
# --------------------------------------------------------------------------
def load_truth(path: Path = GROUND_TRUTH) -> dict[tuple[str, int, str], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    truth: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in payload["sites"]:
        truth[(row["file"], row["line"], row["written"])] = row
    return truth


def verdict_for(site: dict[str, Any], row: dict[str, Any]) -> str:
    if row["truth_bucket"] == "none":
        return "abstain_ok" if site["bucket"] in tp.UNRESOLVED_BUCKETS else "abstain_bad"
    if site["bucket"] == row["truth_bucket"] and site["canonical"] == row["truth_canonical"]:
        return "hit"
    if site["bucket"] == "repo":
        # a VERIFIED claim that names the wrong definition
        return "overclaim"
    return "miss"


def grade(
    root: Path = CORPUS_DIR,
    packages: Iterable[str] = CORPUS_PACKAGES,
    truth_path: Path = GROUND_TRUTH,
) -> dict[str, Any]:
    sites = resolve_sites(root, packages)
    truth = load_truth(truth_path)
    graded: list[dict[str, Any]] = []
    unlisted: list[dict[str, Any]] = []
    for site in sites:
        key = (site["file"], site["line"], site["written"])
        row = truth.get(key)
        if row is None:
            unlisted.append(site)
            continue
        entry = dict(site)
        entry["case"] = row["case"]
        entry["truth_bucket"] = row["truth_bucket"]
        entry["truth_canonical"] = row["truth_canonical"]
        entry["verdict"] = verdict_for(site, row)
        graded.append(entry)

    missing_from_run = [
        {"file": f, "line": ln, "written": w}
        for (f, ln, w) in sorted(truth)
        if (f, ln, w) not in {(s["file"], s["line"], s["written"]) for s in sites}
    ]

    counts: dict[str, int] = {}
    for entry in graded:
        counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1

    by_case: dict[str, dict[str, int]] = {}
    for entry in graded:
        bucket = by_case.setdefault(entry["case"], {})
        bucket[entry["verdict"]] = bucket.get(entry["verdict"], 0) + 1

    # Precision is asked of the VERIFIED bucket only: ``repo`` is the one
    # attribution this slice ever called an existence proof, so it is the one
    # that has to be right.  Builtin hits are trivial and are reported apart
    # so they cannot pad either rate.
    verified_claims = [e for e in graded if e["bucket"] == "repo"]
    verified_correct = [e for e in verified_claims if e["verdict"] == "hit"]
    corpus_truth = [e for e in graded if e["truth_bucket"] == "repo"]
    corpus_recalled = [e for e in corpus_truth if e["verdict"] == "hit"]
    trivial = [e for e in graded if e["truth_bucket"] == "builtin"]

    def pct(num: int, den: int) -> float:
        return round(100.0 * num / (den or 1), 2)

    return {
        "schema": "forest-v2-type-plane-accuracy/1",
        "read_only": True,
        "corpus": root.as_posix(),
        "corpus_pin": tp.corpus_pin(
            [
                (p.relative_to(root).as_posix(), p.read_bytes())
                for p in tp.iter_py_files(root, tuple(packages))
            ]
        ),
        "ground_truth_pin": tp.corpus_pin(
            [(truth_path.name, truth_path.read_bytes())]
        ),
        "sites_graded": len(graded),
        "sites_unlisted_in_ground_truth": unlisted,
        "ground_truth_rows_not_produced": missing_from_run,
        "verdicts": dict(sorted(counts.items())),
        "verdicts_by_case": {k: dict(sorted(v.items())) for k, v in sorted(by_case.items())},
        "metrics": {
            "verified_claims": len(verified_claims),
            "verified_correct": len(verified_correct),
            "verified_precision_pct": pct(len(verified_correct), len(verified_claims)),
            "corpus_internal_names": len(corpus_truth),
            "corpus_internal_recalled": len(corpus_recalled),
            "verified_recall_pct": pct(len(corpus_recalled), len(corpus_truth)),
            "overclaims": counts.get("overclaim", 0),
            "misses": counts.get("miss", 0),
            "abstentions_correct": counts.get("abstain_ok", 0),
            "abstentions_wrong": counts.get("abstain_bad", 0),
            "trivial_builtin_sites_excluded_from_both_rates": len(trivial),
        },
        "failures": [e for e in graded if e["verdict"] in {"miss", "overclaim", "abstain_bad"}],
        "_graded": graded,
    }


def summary(report: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if not k.startswith("_")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="s02 resolver accuracy on a pinned corpus")
    parser.add_argument("--sites", action="store_true", help="dump every graded site")
    args = parser.parse_args(argv)
    report = grade()
    payload = summary(report)
    if args.sites:
        payload["sites"] = report["_graded"]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

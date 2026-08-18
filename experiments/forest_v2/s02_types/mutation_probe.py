"""EXPERIMENT slice s02: do the checks actually notice when the resolver lies?

A metric is only evidence if something breaks when the thing it measures
breaks.  This probe damages the resolver in named ways and reports which of
the slice's guards fire.  A mutant nothing notices is a metric that is not
measuring what its name says.

The guards here are the SAME functions the check suite asserts on, so there is
one definition of "the reported numbers still hold" rather than two that can
drift apart.

Read-only, stdlib-only, in-process (no subprocess), one JSON object on stdout.
Mutations are applied to in-memory module attributes and undone in a
``finally``; nothing on disk is touched.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import resolver_accuracy as ra  # noqa: E402
import type_plane as tp  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus_alias"


# --------------------------------------------------------------------------
# guards: the reported numbers, restated as executable predicates
# --------------------------------------------------------------------------
def guard_accuracy_headline() -> None:
    m = ra.grade()["metrics"]
    assert m["verified_precision_pct"] == 87.5, m["verified_precision_pct"]
    assert m["verified_recall_pct"] == 58.33, m["verified_recall_pct"]
    assert m["verified_correct"] == 14, m["verified_correct"]
    assert m["verified_claims"] == 16, m["verified_claims"]


def guard_failure_classes() -> None:
    by_case = ra.grade()["verdicts_by_case"]
    assert by_case["aliased_import"] == {"hit": 2}, by_case.get("aliased_import")
    assert by_case["relative_import"] == {"hit": 2}, by_case.get("relative_import")
    assert by_case["module_attribute"] == {"hit": 2}, by_case.get("module_attribute")
    assert by_case["same_module"] == {"hit": 2}, by_case.get("same_module")
    assert by_case["type_checking_guard"] == {"hit": 1}, by_case.get("type_checking_guard")
    assert by_case["reexport_two_hop"] == {"miss": 2}, by_case.get("reexport_two_hop")
    assert by_case["star_import"] == {"miss": 2}, by_case.get("star_import")
    assert by_case["closure_shadowing"] == {"overclaim": 1}, by_case.get("closure_shadowing")
    assert by_case["dangling_name"] == {"abstain_ok": 1}, by_case.get("dangling_name")


def guard_no_silent_overclaim() -> None:
    """Every wrong VERIFIED attribution must be labelled an overclaim."""
    report = ra.grade()
    for entry in report["_graded"]:
        if entry["bucket"] == "repo" and entry["truth_bucket"] == "repo":
            same = entry["canonical"] == entry["truth_canonical"]
            assert entry["verdict"] == ("hit" if same else "overclaim"), entry
    assert report["metrics"]["overclaims"] == 2, report["metrics"]["overclaims"]


def guard_corpus_coverage_rates() -> None:
    report = tp.build_type_plane(CORPUS, ("xpkg",))
    rates = report["rates"]
    assert rates["sig_annotated_pct"] == 73.68, rates["sig_annotated_pct"]
    assert rates["sig_resolved_pct"] == 57.89, rates["sig_resolved_pct"]
    assert rates["type_name_resolution_pct"] == 86.67, rates["type_name_resolution_pct"]
    assert report["controls"]["marginal_vs_annotation_only"]["functions"] == 3


def guard_marginal_is_bounded_by_the_control() -> None:
    report = tp.build_type_plane(CORPUS, ("xpkg",))
    totals = report["totals"]
    assert totals["sig_resolved"] <= totals["sig_annotated"]
    assert (
        report["controls"]["marginal_vs_annotation_only"]["functions"]
        == totals["sig_annotated"] - totals["sig_resolved"]
    )


def guard_falsifier_can_fire() -> None:
    """The decoupled rate must be able to reach 0 on a fully annotated corpus."""
    report = tp.build_type_plane(CORPUS, ("xpkg",))
    assert report["rates"]["type_name_resolution_pct"] < 100.0
    assert report["totals"]["type_name_sites_resolved"] < report["totals"]["type_name_sites"]


def guard_retracted_control_stays_weak() -> None:
    """The retracted control must stay degenerate where it has nothing to find.

    No signature in the fixture corpus is spelled in builtins alone, so the
    builtins-only resolver must score exactly zero there.  A control that
    starts scoring is a control that stopped measuring what it is named for.
    """
    report = tp.build_type_plane(CORPUS, ("xpkg",))
    assert report["totals"]["sig_resolved_builtins_only"] == 0, report["totals"][
        "sig_resolved_builtins_only"
    ]
    assert report["controls"]["builtins_only"]["status"].startswith("RETRACTED")


def guard_retracted_control_composition() -> None:
    """The retracted control must keep reporting how empty its hits are."""
    kernel = tp.build_type_plane(Path(__file__).resolve().parents[3], ("daedalus",))
    control = kernel["controls"]["builtins_only"]
    assert control["status"].startswith("RETRACTED")
    assert control["resolved"] == 1562, control["resolved"]
    assert kernel["totals"]["sig_resolved_builtins_only_zero_param"] == 823
    assert control["zero_param_share_of_hits"] == 52.69


GUARDS: dict[str, Callable[[], None]] = {
    "accuracy_headline": guard_accuracy_headline,
    "failure_classes": guard_failure_classes,
    "no_silent_overclaim": guard_no_silent_overclaim,
    "corpus_coverage_rates": guard_corpus_coverage_rates,
    "marginal_bounded_by_control": guard_marginal_is_bounded_by_the_control,
    "falsifier_can_fire": guard_falsifier_can_fire,
    "retracted_control_stays_weak": guard_retracted_control_stays_weak,
    "retracted_control_composition": guard_retracted_control_composition,
}

# The kernel-wide guard costs ~7 s; the probe skips it unless asked.
FAST_GUARDS = tuple(k for k in GUARDS if k != "retracted_control_composition")


# --------------------------------------------------------------------------
# mutations
# --------------------------------------------------------------------------
@contextmanager
def _patch(target: Any, name: str, value: Any) -> Iterator[None]:
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


@contextmanager
def mut_bindings_ignore_asname() -> Iterator[None]:
    """``import X as Y`` binds the original spelling instead of the alias."""
    original = tp.import_bindings

    def patched(tree: ast.Module, module: str, is_package: bool) -> dict[str, str]:
        out = {}
        for key, value in original(tree, module, is_package).items():
            out[value.rsplit(".", 1)[-1]] = value
        return out

    with _patch(tp, "import_bindings", patched):
        yield


@contextmanager
def mut_symbols_drop_classes() -> Iterator[None]:
    """The symbol table forgets classes, so no repo attribution verifies."""
    original = tp.top_level_symbols

    def patched(tree: ast.Module) -> set[str]:
        classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
        return original(tree) - classes

    with _patch(tp, "top_level_symbols", patched):
        yield


@contextmanager
def mut_relative_base_off_by_one() -> Iterator[None]:
    """``from ..x import y`` climbs one package too few."""
    original = tp._relative_base

    def patched(module: str, is_package: bool, level: int) -> str:
        return original(module, is_package, max(1, level - 1))

    with _patch(tp, "_relative_base", patched):
        yield


@contextmanager
def mut_resolve_claims_everything() -> Iterator[None]:
    """The resolver claims a verified repo attribution for every name."""

    def patched(self, dotted, module, local_names, bindings):  # type: ignore[no-untyped-def]
        return "repo", f"{module}.{dotted}"

    with _patch(tp.Resolver, "resolve", patched):
        yield


@contextmanager
def mut_emit_counts_everything_resolved() -> Iterator[None]:
    """Occurrence accounting marks every site resolved regardless of bucket."""
    original = tp.TypeExprWalker._emit

    def patched(self, bucket, name, seen, line):  # type: ignore[no-untyped-def]
        out = original(self, bucket, name, seen, line)
        if bucket in tp.UNRESOLVED_BUCKETS:
            self.totals["type_name_sites_resolved"] += 1
        return out

    with _patch(tp.TypeExprWalker, "_emit", patched):
        yield


@contextmanager
def mut_builtins_control_accepts_everything() -> Iterator[None]:
    """The retracted control stops being weak, hiding what it measures."""
    with _patch(tp, "builtins_only_bucket", lambda dotted: "builtin"):
        yield


MUTANTS: dict[str, Callable[[], Any]] = {
    "bindings_ignore_asname": mut_bindings_ignore_asname,
    "symbols_drop_classes": mut_symbols_drop_classes,
    "relative_base_off_by_one": mut_relative_base_off_by_one,
    "resolve_claims_everything": mut_resolve_claims_everything,
    "emit_counts_everything_resolved": mut_emit_counts_everything_resolved,
    "builtins_control_accepts_everything": mut_builtins_control_accepts_everything,
}


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------
def run_guards(names: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in names:
        try:
            GUARDS[name]()
        except AssertionError as exc:
            out[name] = f"FAILED: {exc}" if str(exc) else "FAILED"
        except Exception as exc:  # a mutant that crashes a guard also kills it
            out[name] = f"ERROR: {type(exc).__name__}: {exc}"
        else:
            out[name] = "passed"
    return out


def probe(guard_names: tuple[str, ...] = tuple(GUARDS)) -> dict[str, Any]:
    baseline = run_guards(guard_names)
    results: dict[str, Any] = {}
    for name, mutation in MUTANTS.items():
        with mutation():
            results[name] = run_guards(guard_names)
    killed = {
        name: sorted(g for g, v in res.items() if v != "passed")
        for name, res in results.items()
    }
    survivors = sorted(name for name, g in killed.items() if not g)
    return {
        "schema": "forest-v2-type-plane-mutation/1",
        "read_only": True,
        "guards": list(guard_names),
        "baseline": baseline,
        "baseline_clean": all(v == "passed" for v in baseline.values()),
        "killed_by": killed,
        "mutants": len(MUTANTS),
        "mutants_killed": sum(1 for g in killed.values() if g),
        "survivors": survivors,
        "detail": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="s02 mutation probe")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="skip the kernel-wide guard (~7 s per run, 7 runs)",
    )
    parser.add_argument("--detail", action="store_true", help="print per-guard results")
    args = parser.parse_args(argv)
    report = probe(FAST_GUARDS if args.fast else tuple(GUARDS))
    if not args.detail:
        report.pop("detail")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not report["survivors"] and report["baseline_clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

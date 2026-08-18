"""Checks for the resolver-accuracy grading and the mutation probe.

Run directly::

    python -m pytest experiments/forest_v2/s02_types/test_resolver_accuracy.py

Every number asserted here was computed by hand from ``corpus_alias/`` before
the resolver was run over it; ``ground_truth.json`` records the derivation per
site.  The corpus is pinned by content digest so a silent fixture edit cannot
move a reported rate.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mutation_probe as mp  # noqa: E402
import resolver_accuracy as ra  # noqa: E402
import type_plane as tp  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus_alias"

# Frozen at the revision that produced the reported numbers.  Content-exact:
# ``corpus_pin`` normalises line endings before hashing, because this
# repository rewrites them on checkout and a pin that moves with the platform
# pins nothing.
CORPUS_SHA = "cc5d42c2455187c49c452feabe988ccd74118d80446de6aea91cc721d3579327"
TRUTH_SHA = "dafb3d51007c167fcf1414d278e60557ea700b6711b40bc0bc2ee494e27ff80d"


# --------------------------------------------------------------------------
# the corpus and its answers are pinned
# --------------------------------------------------------------------------
def test_corpus_and_ground_truth_are_pinned() -> None:
    report = ra.grade()
    assert report["corpus_pin"] == {"files": 18, "sha256": CORPUS_SHA}
    assert report["ground_truth_pin"] == {"files": 1, "sha256": TRUTH_SHA}


def test_ground_truth_covers_the_corpus_exactly() -> None:
    """No site graded without an answer, no answer without a site."""
    report = ra.grade()
    assert report["sites_unlisted_in_ground_truth"] == []
    assert report["ground_truth_rows_not_produced"] == []
    assert report["sites_graded"] == 30


# --------------------------------------------------------------------------
# the headline accuracy numbers
# --------------------------------------------------------------------------
def test_verified_precision_and_recall_are_the_hand_computed_figures() -> None:
    m = ra.grade()["metrics"]
    # 16 sites were claimed as VERIFIED repo attributions; 14 name the right
    # definition, 2 name the wrong one.
    assert m["verified_claims"] == 16
    assert m["verified_correct"] == 14
    assert m["verified_precision_pct"] == 87.5
    # 24 annotation names have a definition inside the corpus; 14 are recalled.
    assert m["corpus_internal_names"] == 24
    assert m["corpus_internal_recalled"] == 14
    assert m["verified_recall_pct"] == 58.33
    assert m["overclaims"] == 2
    assert m["misses"] == 8
    assert m["abstentions_correct"] == 1
    assert m["abstentions_wrong"] == 0
    assert m["trivial_builtin_sites_excluded_from_both_rates"] == 5


def test_every_case_lands_where_it_was_predicted_to() -> None:
    by_case = ra.grade()["verdicts_by_case"]
    assert by_case == {
        "aliased_import": {"hit": 2},
        "aliased_module": {"hit": 2},
        "builtin": {"hit": 5},
        "class_scope_alias": {"miss": 1},
        "closure_shadowing": {"overclaim": 1},
        "dangling_name": {"abstain_ok": 1},
        "direct_import": {"hit": 3},
        "module_attribute": {"hit": 2},
        "reexport_two_hop": {"miss": 2},
        "reexport_two_hop_aliased": {"miss": 2},
        "reexport_via_package_init": {"miss": 1},
        "relative_import": {"hit": 2},
        "same_module": {"hit": 2},
        "star_import": {"miss": 2},
        "try_except_import": {"overclaim": 1},
        "type_checking_guard": {"hit": 1},
    }


def test_overclaims_are_verified_claims_not_hedged_ones() -> None:
    """The dangerous failure: bucket says ``repo``, the name is wrong."""
    failures = ra.grade()["failures"]
    overclaims = [f for f in failures if f["verdict"] == "overclaim"]
    assert len(overclaims) == 2
    for entry in overclaims:
        assert entry["bucket"] == "repo"
        assert entry["canonical"] != entry["truth_canonical"]
    cases = sorted(e["case"] for e in overclaims)
    assert cases == ["closure_shadowing", "try_except_import"]


def test_misses_are_hedged_or_absent_never_silently_verified() -> None:
    misses = [f for f in ra.grade()["failures"] if f["verdict"] == "miss"]
    assert len(misses) == 8
    for entry in misses:
        assert entry["bucket"] in {"repo_unverified", "unresolved"}


# --------------------------------------------------------------------------
# coverage is not correctness
# --------------------------------------------------------------------------
def test_coverage_rate_overstates_correctness_on_the_same_corpus() -> None:
    """The point of the whole continuation, stated as an inequality.

    ``type_name_resolution_pct`` counts a site as resolved when a bucket was
    assigned.  Accuracy asks whether the bucket names the right definition.
    On one and the same 30 sites the two answers are far apart.
    """
    coverage = tp.build_type_plane(CORPUS, ("xpkg",))
    accuracy = ra.grade()
    assert coverage["totals"]["type_name_sites"] == accuracy["sites_graded"] == 30
    assert coverage["rates"]["type_name_resolution_pct"] == 86.67
    assert accuracy["metrics"]["verified_recall_pct"] == 58.33
    assert (
        coverage["rates"]["type_name_resolution_pct"]
        > accuracy["metrics"]["verified_recall_pct"] + 25
    )


def test_the_fixture_corpus_is_not_a_well_annotated_one() -> None:
    """The corpus must not repeat the kernel's 92.89% annotation degree."""
    coverage = tp.build_type_plane(CORPUS, ("xpkg",))
    assert coverage["rates"]["sig_annotated_pct"] == 73.68
    assert coverage["totals"]["sig_no_annotation"] == 3
    # and the marginal contribution of the machinery is visible here, unlike
    # on the kernel package where it is 0.119 pp
    assert coverage["controls"]["marginal_vs_annotation_only"]["pp"] == 15.7895


# --------------------------------------------------------------------------
# the mutation probe
# --------------------------------------------------------------------------
def test_guards_pass_unmutated() -> None:
    results = mp.run_guards(mp.FAST_GUARDS)
    assert set(results.values()) == {"passed"}, results


def test_every_mutant_is_killed_by_at_least_one_guard() -> None:
    report = mp.probe(mp.FAST_GUARDS)
    assert report["baseline_clean"] is True
    assert report["survivors"] == [], report["killed_by"]
    assert report["mutants_killed"] == report["mutants"] == 6


def test_a_lying_resolver_is_caught_by_the_precision_guard() -> None:
    """The single most important mutant: claim everything is verified."""
    with mp.mut_resolve_claims_everything():
        results = mp.run_guards(("no_silent_overclaim", "accuracy_headline"))
    assert results["no_silent_overclaim"] != "passed"
    assert results["accuracy_headline"] != "passed"


def test_padding_the_decoupled_metric_is_caught() -> None:
    """If the falsifier metric could be inflated, it would stop being one."""
    with mp.mut_emit_counts_everything_resolved():
        results = mp.run_guards(("falsifier_can_fire",))
    assert results["falsifier_can_fire"] != "passed"

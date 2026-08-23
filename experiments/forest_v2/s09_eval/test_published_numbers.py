"""Pin every published number to the artifact it came from.

The suite used to assert rules against synthetic fixtures and nothing else.
Not one test read ``results/raw.json`` or the census fields of
``taskset.json``, which means the suite would have stayed green if every
number in the README were wrong.  They were not wrong -- an independent pass
reconstructed the whole table from git history -- but that was the auditor's
work, not the suite's, and an unpinned number drifts the moment somebody
edits prose.

These tests are deliberately dumb: they read the artifacts and compare
against the figures quoted in the README.  If a number here goes red, either
the artifact was regenerated and the README is now lying, or the README was
edited and the artifact disagrees.  Both are the failure this file exists to
catch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import taskset  # noqa: E402
from s09_eval.tokens import path_tokens, word_tokens  # noqa: E402

HERE = Path(__file__).resolve().parent
RAW = HERE / "results" / "raw.json"
TASKSET = HERE / "taskset.json"


@pytest.fixture(scope="module")
def raw():
    return json.loads(RAW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def record():
    return json.loads(TASKSET.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def frozen():
    return taskset.load(TASKSET)


def _agg(raw, retriever, variant):
    for row in raw["aggregates"]:
        if row["retriever"] == retriever and row["variant"] == variant:
            return row
    raise AssertionError(f"no aggregate for {retriever}/{variant}")


# ------------------------------------------------- the artifact is the table
def test_results_were_measured_on_the_frozen_task_set(raw, record):
    """A results file scored against a drifted corpus is worthless."""
    assert raw["schema"] == "forest_v2.s09.results/1"
    assert raw["taskset_digest"] == record["digest"]
    assert raw["taskset_anchor"] == record["anchor_commit"]
    assert raw["cases"] == len(record["cases"]) == 20


@pytest.mark.parametrize(
    "retriever,variant,mrr,hits20,hit_cases",
    [
        ("recency_prior", "raw", 0.2239, 19, 16),
        ("bm25_content_only", "raw", 0.1565, 11, 9),
        ("bm25", "raw", 0.1410, 8, 7),
        ("path_lexical", "raw", 0.1245, 13, 12),
        ("random_uniform", "raw", 0.0038, 1, 1),
        ("recency_prior", "scrubbed", 0.2239, 19, 16),
        ("bm25_content_only", "scrubbed", 0.1258, 7, 6),
        ("bm25", "scrubbed", 0.1168, 7, 6),
        ("random_uniform", "scrubbed", 0.0038, 1, 1),
        ("path_lexical", "scrubbed", 0.0000, 0, 0),
    ],
)
def test_published_table_row_matches_the_artifact(
    raw, retriever, variant, mrr, hits20, hit_cases
):
    """Every row of the README's RAW table, read back out of raw.json."""
    row = _agg(raw, retriever, variant)
    assert row["mrr"] == pytest.approx(mrr, abs=5e-5)
    assert row["hits_at"]["20"] == hits20
    assert row["cases_with_any_hit"] == hit_cases
    assert row["gold_total"] == 35


def test_the_bar_for_s07_and_s08_is_the_query_blind_prior(raw):
    """The headline claim: the leader reads no query at all."""
    best_raw = max(
        (r for r in raw["aggregates"] if r["variant"] == "raw"),
        key=lambda r: r["mrr"],
    )
    assert best_raw["retriever"] == "recency_prior"
    assert best_raw["mrr"] == pytest.approx(0.2239, abs=5e-5)
    assert best_raw["macro_recall_at"]["20"] == pytest.approx(0.7625, abs=5e-5)


def test_per_case_rows_average_to_the_published_mrr(raw):
    """The aggregate is not an independently typed number."""
    for retriever, variant in [
        ("recency_prior", "raw"),
        ("bm25", "scrubbed"),
        ("path_lexical", "raw"),
    ]:
        rows = [
            r for r in raw["per_case"]
            if r["retriever"] == retriever and r["variant"] == variant
        ]
        assert len(rows) == 20
        mean = sum(r["reciprocal_rank"] for r in rows) / len(rows)
        assert mean == pytest.approx(_agg(raw, retriever, variant)["mrr"], abs=1e-3)


# ------------------------------------------------------------------------ F5
def test_paired_comparisons_are_uniquely_keyed(raw):
    """The published contract used to collide, and it misled a real consumer.

    ``paired_comparisons`` concatenates every variant into one flat array.
    Without ``variant`` on each entry, ``(subject, reference)`` appears twice
    and a consumer keying on it silently reads the scrubbed number while
    believing it read the raw one.  Position is no substitute: each variant
    block is independently re-sorted by ``-delta.point``.
    """
    entries = raw["paired_comparisons"]
    assert entries, "no paired comparisons were published"
    assert all(e.get("variant") for e in entries), "an entry carries no variant"
    keys = [(e["subject"], e["reference"], e["variant"]) for e in entries]
    assert len(set(keys)) == len(keys), f"colliding keys in {keys}"
    assert raw["paired_comparisons_key"] == ["subject", "reference", "variant"]
    assert {e["variant"] for e in entries} == {"raw", "scrubbed"}


def test_the_only_separated_raw_comparison_is_the_random_floor(raw):
    """Claim 2 of the README, pinned: n=20 separates nothing else."""
    separated = {
        e["subject"]
        for e in raw["paired_comparisons"]
        if e["variant"] == "raw" and e["interval_excludes_zero"]
    }
    assert separated == {"random_uniform"}


def test_scrubbing_separates_two_arms_as_losses(raw):
    losses = {
        e["subject"]: e["delta_mean"]["point"]
        for e in raw["paired_comparisons"]
        if e["variant"] == "scrubbed" and e["interval_excludes_zero"]
    }
    assert set(losses) == {"random_uniform", "bm25", "path_lexical"}
    assert all(point < 0 for point in losses.values())
    assert losses["bm25"] == pytest.approx(-0.1071, abs=5e-5)


# ------------------------------------------------------------------------ F2
def test_the_multi_file_quota_is_a_choice_not_a_ceiling(record):
    """The retracted claim, pinned so it cannot come back as prose."""
    census = record["selection_census"]
    assert census["admissible_multi_file"] == 18
    assert census["multi_file_quota"] == 8
    assert census["multi_file_used"] == 8
    assert census["multi_file_admissible_unused"] == 10
    assert census["admissible_multi_file"] > census["multi_file_quota"], (
        "supply no longer exceeds the quota -- the 'supply-capped' wording "
        "would become true and this test should be rewritten, not deleted"
    )
    assert record["strata_actual"] == {"multi_file": 8, "single_file": 12}


# ------------------------------------------------------------------------ F3
def test_the_rejection_denominator_is_recorded(record):
    """15 silent rejections used to increment no counter anywhere."""
    acceptance = record["acceptance"]
    assert acceptance["commits_considered"] == 35
    assert acceptance["commits_accepted"] == 20
    assert acceptance["commits_rejected"] == 15
    assert acceptance["acceptance_rate"] == pytest.approx(0.5714, abs=5e-5)
    assert len(acceptance["rejected_commits"]) == 15
    assert all(not r["accepted"] for r in acceptance["rejected_commits"])


def test_the_rejected_population_is_file_creating_commits(record):
    """The bias matters more than the count: creators are removed wholesale."""
    rejected = record["acceptance"]["rejected_commits"]
    assert record["acceptance"]["rejection_reasons"] == {
        "all_changed_files_created_by_this_commit": 15
    }
    multi = [r for r in rejected if r["stratum"] == "multi_file"]
    assert len(multi) == 2
    for commit in multi:
        assert len(commit["changed"]) == 5
        suffixes = {Path(p).suffix for p in commit["changed"]}
        assert {".yml", ".md", ".py"} <= suffixes, (
            "the rejected multi-file commits are the cross-plane-shaped ones; "
            f"got {sorted(suffixes)}"
        )


# ------------------------------------------------------------------------ F4
def test_the_corpus_cannot_exercise_the_hypothesis_it_grades(record):
    """Declared, not discovered later by whoever reads a null result."""
    comp = record["plane_composition"]
    assert comp["gold_paths_total"] == 35
    assert comp["gold_by_suffix"][".py"] == 32
    assert sum(comp["gold_by_suffix"].values()) == 35
    assert comp["gold_by_plane"] == {"code": 32, "data": 2, "knowledge": 1}
    assert comp["cases_spanning_more_than_one_plane"] == 3
    assert comp["cases_touching_the_knowledge_plane"] == 1
    assert comp["cases_matching_the_gate1_python_markdown_csv_shape"] == 0, (
        "the Gate-1 flagship scenario still has no representative in this corpus"
    )
    assert comp["type_plane_representatives"] == 0
    assert "warning" in comp and "kill" in comp["warning"]


def test_python_share_of_gold_is_declared_as_a_limitation(record):
    comp = record["plane_composition"]
    share = comp["gold_by_suffix"][".py"] / comp["gold_paths_total"]
    assert share == pytest.approx(0.914, abs=1e-3)


# ------------------------------------------- the mislabelled dropped field
def test_dropped_paths_are_split_into_created_and_ineligible(record, frozen):
    """``gold_created_dropped`` over-attributes to creation; the total is right."""
    _, cases = frozen
    breakdown = record["dropped_breakdown"]
    assert breakdown["created_by_commit"] == 3
    assert breakdown["existed_but_ineligible"] == 2
    total_dropped = sum(len(c.gold_created_dropped) for c in cases)
    assert total_dropped == 5
    assert (
        breakdown["created_by_commit"] + breakdown["existed_but_ineligible"]
        == total_dropped
    ), "the breakdown and the per-case field disagree about the total"
    assert sum(len(c.gold) for c in cases) == 35


# ------------------------------------------------------------------------ F1
def test_the_full_scrub_makes_gold_structurally_unscorable_for_path_matching(frozen):
    """Why ``path_lexical`` 0.000 is arithmetic and not a measurement.

    ``scrub`` bans ``path_tokens(gold)``; ``PathLexical`` scores exactly
    ``|word_tokens(query) & path_tokens(candidate)|`` and drops zero-scoring
    candidates.  For gold that intersection is empty by definition of the
    scrub, on every corpus and in every repository.
    """
    _, cases = frozen
    scorable = 0
    disjoint_cases = 0
    gold_total = 0
    for case in cases:
        q = set(word_tokens(case.query("scrubbed")))
        overlaps = [len(q & path_tokens(g)) for g in case.gold]
        gold_total += len(overlaps)
        scorable += sum(1 for o in overlaps if o)
        disjoint_cases += all(o == 0 for o in overlaps)
    assert gold_total == 35
    assert scorable == 0, "the 0.000 would stop being arithmetic; re-read the README"
    assert disjoint_cases == 20


def test_the_raw_query_can_reach_gold_through_path_tokens(frozen):
    """The contrast that makes the previous test meaningful."""
    _, cases = frozen
    scorable = sum(
        1
        for case in cases
        for g in case.gold
        if set(word_tokens(case.query("raw"))) & path_tokens(g)
    )
    assert scorable == 26


def test_the_echo_is_entirely_a_basename_echo(frozen):
    """The measurement the full scrub could not make.

    Removing only the gold *basename* leaves directory tokens in the query,
    so a path retriever keeps every chance the corpus ever gave it -- and
    scorable gold still falls 26/35 -> 0/35.  These commit messages never
    name a directory of the file they touch; the whole path signal was the
    filename.
    """
    _, cases = frozen
    scorable = sum(
        1
        for case in cases
        for g in case.gold
        if set(word_tokens(case.query("scrubbed_basename"))) & path_tokens(g)
    )
    assert scorable == 0


def test_the_basename_scrub_is_indistinguishable_from_the_full_scrub_here(frozen):
    """The requested measurement, executed, returning "there is nothing to measure".

    The audit asked for a scrub that removes only the basename so the
    filename echo could be isolated from the general path signal.  It was
    built and run.  On this corpus it produces byte-identical queries to the
    full scrub on all 20 cases, because no commit message ever names a
    directory of the file it touches -- so the weaker scrub removes exactly
    the same tokens as the stronger one.

    Consequence, and it is the honest one: this corpus cannot separate
    "filename echo" from "path signal", because it contains no path signal
    other than the filename.  ``path_lexical``'s 0.000 stays arithmetic in
    both variants.
    """
    _, cases = frozen
    for case in cases:
        assert case.query("scrubbed_basename") == case.query("scrubbed")
        assert (
            taskset.scrub_basename(case.query_raw, case.gold)[1]
            == taskset.scrub(case.query_raw, case.gold)[1]
        )


def test_no_commit_message_names_a_directory_of_its_gold_file(frozen):
    """Why the two scrubs coincide -- the underlying property, measured.

    Every one of the 35 gold paths has at least one directory token, and not
    one of them appears in the commit message that changed it.
    """
    _, cases = frozen
    with_dirs = 0
    named = 0
    for case in cases:
        q = set(word_tokens(case.query_raw))
        for gold in case.gold:
            dirs = path_tokens(gold) - path_tokens(gold.rsplit("/", 1)[-1])
            with_dirs += bool(dirs)
            named += bool(q & dirs)
    assert with_dirs == 35
    assert named == 0

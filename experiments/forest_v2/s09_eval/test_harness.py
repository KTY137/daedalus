"""Tests for the runner's budget-equality and anti-cheating rules.

These use a synthetic universe rather than the repository, so they assert
the rules themselves instead of re-measuring the corpus.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import harness, retrievers  # noqa: E402
from s09_eval.contract import Budget, Candidate, ContractViolation  # noqa: E402
from s09_eval.taskset import Case  # noqa: E402
from s09_eval.tokens import TokenCache  # noqa: E402

BUDGET = Budget(cutoffs=(1, 5))
UNIVERSE = [
    Candidate(path="pkg/target.py", blob="b1", size=20, raw=b"the declared sink lives here"),
    Candidate(path="pkg/other.py", blob="b2", size=20, raw=b"unrelated body text"),
    Candidate(path="pkg/third.py", blob="b3", size=20, raw=b"more unrelated text"),
]

CASE = Case(
    case_id="c00",
    commit="deadbeef",
    parent="cafebabe",
    committed_at=0,
    query_raw="fix the declared sink",
    query_scrubbed="fix the declared",
    gold=("pkg/target.py",),
    gold_created_dropped=(),
    leak_tokens=("sink",),
    universe_size=3,
)


def _provider(case):
    return list(UNIVERSE)


def _run(suite, variants=("raw",), cases=(CASE,)):
    return harness.run(
        Path("."), list(cases), suite, BUDGET, variants, TokenCache(),
        universe_provider=_provider,
    )


class _Cheat:
    """Returns a path that is not in the universe."""

    name = "cheat_invented_path"

    def rank(self, query, universe):
        return ["pkg/does_not_exist.py"]


class _Duplicator:
    """Returns the same path repeatedly to buy extra draws."""

    name = "cheat_duplicate"

    def rank(self, query, universe):
        return ["pkg/target.py"] * 5


class _Spy:
    """Records exactly what it was handed."""

    name = "spy"

    def __init__(self):
        self.seen = []

    def rank(self, query, universe):
        self.seen.append((query, [c.path for c in universe], [c.text() for c in universe]))
        return [c.path for c in universe]


def test_an_invented_path_aborts_the_run_instead_of_scoring():
    with pytest.raises(ContractViolation, match="not in the universe"):
        _run([_Cheat()])


def test_a_duplicated_path_aborts_the_run():
    with pytest.raises(ContractViolation, match="duplicate"):
        _run([_Duplicator()])


def test_every_retriever_sees_the_identical_universe_and_bytes():
    first, second = _Spy(), _Spy()
    second.name = "spy2"
    _run([first, second])
    assert first.seen[0][1] == second.seen[0][1]
    assert first.seen[0][2] == second.seen[0][2]


def test_retrievers_never_receive_the_gold_set():
    spy = _Spy()
    _run([spy])
    query = spy.seen[0][0]
    assert not hasattr(query, "gold")
    assert "target" not in query.text or "sink" in query.text  # query text only
    assert query.revision == CASE.parent


def test_both_variants_are_scored_separately():
    aggregates, per_case, _, _ = _run([retrievers.PathLexical()], variants=("raw", "scrubbed"))
    variants = {a.variant for a in aggregates}
    assert variants == {"raw", "scrubbed"}
    assert {row["variant"] for row in per_case} == {"raw", "scrubbed"}


def test_a_gold_path_outside_the_universe_is_a_loud_failure():
    """Silent zero-recall would look like a bad retriever, not a broken run."""
    broken = Case(**{**CASE.__dict__, "gold": ("pkg/vanished.py",)})
    with pytest.raises(RuntimeError, match="gold not inside the rebuilt universe"):
        _run([retrievers.PathLexical()], cases=(broken,))


def test_cost_accounting_charges_indexing_once_not_per_retriever():
    _, _, cost, _ = _run([retrievers.Bm25(TokenCache()), retrievers.PathLexical()])
    assert cost["token_cache_misses"] == len(UNIVERSE)
    assert set(cost["rank_seconds"]) == {"bm25", "path_lexical"}
    assert cost["shared_index_seconds"] >= 0.0


def test_scores_land_in_the_aggregate():
    aggregates, per_case, _, _ = _run([retrievers.Bm25(TokenCache())])
    agg = aggregates[0]
    assert agg.cases == 1 and agg.gold_total == 1
    assert agg.hits_at[5] == 1  # "declared sink" body match finds the target
    assert per_case[0]["case_id"] == "c00"


def _delta(subject: str, variant: str):
    from s09_eval import stats

    return stats.paired_delta(
        subject, "ref", [0.5, 0.4], [0.1, 0.2], resamples=20, variant=variant
    )


def test_comparison_payload_emits_a_usable_key():
    rows = harness.comparison_payload([_delta("a", "raw"), _delta("a", "scrubbed")])
    keys = {(r["subject"], r["reference"], r["variant"]) for r in rows}
    assert len(keys) == 2
    assert all(r["variant"] for r in rows)


def test_comparison_payload_refuses_an_entry_without_a_variant():
    """Fail closed rather than publish an array a consumer can misread."""
    with pytest.raises(ValueError) as excinfo:
        harness.comparison_payload([_delta("a", "")])
    assert "no variant" in str(excinfo.value)


def test_comparison_payload_refuses_colliding_keys():
    with pytest.raises(ValueError) as excinfo:
        harness.comparison_payload([_delta("a", "raw"), _delta("a", "raw")])
    assert "colliding" in str(excinfo.value)

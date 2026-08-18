"""Tests for the adapter contract, especially its two structural guarantees."""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval.contract import (  # noqa: E402
    Budget,
    Candidate,
    ContractViolation,
    QueryView,
    load_retriever,
    validate_ranking,
)


def _universe(*paths: str):
    return [Candidate(path=p, blob="0" * 40, size=10, raw=b"body") for p in paths]


def test_query_view_carries_no_answer_key():
    """A retriever must not be able to reach the gold set through its input."""
    names = {f.name for f in fields(QueryView)}
    assert names == {"case_id", "text", "variant", "revision"}
    assert not any("gold" in n for n in names)

    candidate_names = {f.name for f in fields(Candidate)}
    assert not any("gold" in n or "label" in n for n in candidate_names)


def test_content_budget_truncates_so_nobody_buys_accuracy_with_bytes():
    cand = Candidate(path="a.py", blob="x" * 40, size=100, raw=b"abcdefghij", content_budget=4)
    assert cand.text() == "abcd"


def test_validate_ranking_truncates_at_max_k():
    universe = _universe("a.py", "b.py", "c.py")
    out = validate_ranking("t", ["a.py", "b.py", "c.py"], universe, max_k=2)
    assert out == ["a.py", "b.py"]


def test_validate_ranking_rejects_a_path_outside_the_universe():
    with pytest.raises(ContractViolation, match="not in the universe"):
        validate_ranking("t", ["ghost.py"], _universe("a.py"), max_k=5)


def test_validate_ranking_rejects_duplicates():
    with pytest.raises(ContractViolation, match="duplicate"):
        validate_ranking("t", ["a.py", "a.py"], _universe("a.py", "b.py"), max_k=5)


def test_short_rankings_are_allowed_and_simply_score_worse():
    assert validate_ranking("t", [], _universe("a.py"), max_k=5) == []


def test_budget_eligibility_rule():
    budget = Budget(max_file_bytes=100)
    assert budget.eligible("a/b.py", 50)
    assert not budget.eligible("a/b.py", 500), "oversized file must fall out"
    assert not budget.eligible("a/b.png", 50), "binary suffix must fall out"
    assert not budget.eligible("a/b.py", 0), "empty file must fall out"


def test_load_retriever_rejects_a_malformed_spec():
    with pytest.raises(ContractViolation, match="module:attribute"):
        load_retriever("no_colon_here")


def test_load_retriever_rejects_an_object_without_the_contract():
    with pytest.raises(ContractViolation, match="does not satisfy"):
        load_retriever("json:dumps")


class _Conforming:
    """Stand-in for an s07/s08 retriever, so this test needs no other slice."""

    name = "conforming"

    def rank(self, query, universe):
        return [c.path for c in universe]


def test_load_retriever_accepts_a_conforming_object():
    retriever = load_retriever(f"{__name__}:_Conforming")
    assert retriever.name == "conforming"
    assert retriever.rank(QueryView("c00", "q", "raw"), _universe("a.py")) == ["a.py"]

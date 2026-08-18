"""EXPERIMENT s06 checks: the negative path, and a mutation probe per new guard.

Two jobs, deliberately in one file because they answer the same objection.

**Part 1 — the counters are measurements.**  ``records_rejected`` and
``contract_violations`` used to be structural zeros: no malformed input ever
reached them, so they could not have moved.  Each check here drives one
condition through ``node_cards.tally`` — the function the corpus run uses —
and asserts the counter moves.

**Part 2 — the guards are load-bearing.**  A check that passes because the
input is clean proves nothing about the guard.  So each new guard is *removed
from its own source* (its condition rewritten to ``if False:``), the module is
recompiled, and the check asserts the violation goes unnoticed in the mutant.
A guard whose removal changes nothing is decoration; every guard below is
shown not to be.

Run:  python -m pytest experiments/forest_v2/s06_cards/test_negative_paths.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import negative_fixtures as nf  # noqa: E402
import node_cards as nc  # noqa: E402

SOURCE = (HERE / "node_cards.py").read_text(encoding="utf-8")


def mutate(condition: str) -> SimpleNamespace:
    """Recompile node_cards with one guard's condition forced false."""
    assert SOURCE.count(condition) == 1, f"mutation target is not unique: {condition!r}"
    head, sep, tail = condition.partition("if ")
    assert sep, condition
    dead = f"{head}if False:  # MUTATED"
    namespace: dict = {}
    exec(compile(SOURCE.replace(condition, dead), "node_cards<mutant>", "exec"), namespace)
    return SimpleNamespace(**namespace)


# ===========================================================================
# Part 1 -- each condition moves its counter, through the production tally
# ===========================================================================


@pytest.mark.parametrize("fixture", nf.FIXTURES, ids=lambda f: f.id)
def test_every_fixture_moves_the_counter_it_claims(fixture):
    result = nf.run_fixture(fixture)
    assert result["moved"], (
        f"{fixture.id}: {fixture.counter} stayed at {result['broken_input']} "
        "-- the counter is still a structural zero"
    )


def test_a_malformed_record_is_rejected_not_carded():
    result = nf.run_fixture(nf.FIXTURES[0])
    assert result["counter"] == "records_rejected"
    assert result["clean_input"] == 0
    assert result["broken_input"] == 4  # empty, missing, bad plane, bad range


def test_a_duplicate_node_id_is_counted_as_a_collision():
    result = nf.run_fixture(nf.FIXTURES[1])
    assert result["counter"] == "duplicate_node_ids"
    assert result["clean_input"] == 0 and result["broken_input"] == 1


def test_a_budget_overrun_is_counted_and_is_a_violation():
    result = nf.run_fixture(nf.FIXTURES[2])
    assert result["counter"] == "content_over_budget"
    assert result["broken_input"] == 1
    assert result["contract_violations"] == 2  # content and neighborhood
    assert any("over budget" in r for r in result["violation_reasons"])


def test_a_card_missing_its_plane_is_a_counted_violation():
    result = nf.run_fixture(nf.FIXTURES[3])
    assert result["counter"] == "contract_violations"
    assert result["clean_input"] == 0 and result["broken_input"] == 1
    assert "card missing field: plane" in result["violation_reasons"]


def test_a_card_missing_its_revision_is_a_counted_violation():
    result = nf.run_fixture(nf.FIXTURES[4])
    assert result["broken_input"] == 1
    assert "empty revision (a card must be revision-bound)" in result["violation_reasons"]


def test_a_dangling_provenance_ref_is_counted_and_is_a_violation():
    result = nf.run_fixture(nf.FIXTURES[5])
    assert result["counter"] == "provenance_refs_dangling"
    assert result["clean_input"] == 0 and result["broken_input"] == 1
    assert result["contract_violations"] == 1


def test_clean_input_leaves_every_counter_at_zero():
    """The other half: the counters must not fire on well-formed cards either."""
    clean = nf._clean_baseline("git:abc")
    for counter in (
        "records_rejected",
        "contract_violations",
        "duplicate_node_ids",
        "content_over_budget",
        "neighborhood_over_budget",
        "provenance_refs_dangling",
    ):
        assert clean[counter] == 0, counter


def test_counter_liveness_reports_every_fixture_moving():
    report = nf.counter_liveness()
    assert report["all_moved"] is True
    assert set(report["fixtures"]) == {f.id for f in nf.FIXTURES}


def test_the_fixtures_run_through_the_same_tally_the_probe_uses():
    """Guard against the fixtures drifting onto a private checker."""
    import inspect

    source = inspect.getsource(nf.run_fixture)
    assert "tally(" in source
    assert nf.tally is nc.tally


# ===========================================================================
# Part 2 -- mutation probes: remove the guard, the violation goes unnoticed
# ===========================================================================


def _card_with(**tamper) -> tuple[dict, nc.ProvenanceBook]:
    book = nc.ProvenanceBook()
    ref = book.add(nf.FIXTURE_PROVENANCE)
    card = nc.build_card(nf._record(), revision="git:abc", provenance=ref)
    for key, value in tamper.items():
        card[key] = value
    nf._readdress(card)
    return card, book


def test_mutation_provenance_ref_format_guard():
    card, _ = _card_with(provenance="s01 (not available at build time)")
    assert any("not a sha256 ref" in p for p in nc.validate_card(card))

    mutant = mutate("elif not _REF_RE.match(ref):")
    assert mutant.validate_card(card) == [], "removing the format guard changed nothing"


def test_mutation_provenance_resolution_guard():
    """Removing this guard silences its message -- but a backstop still fires.

    Recorded rather than smoothed over: the dangling ref is caught twice, once
    by the resolution check and once by the content-address check downstream
    of it (``provenance_ref(None) != ref``).  So this guard is load-bearing
    for the *diagnosis* and not for the *rejection*.  Claiming a single
    load-bearing guard here would have been the easier sentence and the wrong
    one.
    """
    card, book = _card_with(provenance="sha256:" + "0" * 64)
    assert any("does not resolve" in p for p in nc.validate_card(card, book))

    mutant = mutate("if block is None:")
    mutant_book = mutant.ProvenanceBook(book.as_dict())
    problems = mutant.validate_card(card, mutant_book)
    assert not any("does not resolve" in p for p in problems)
    assert problems, "no guard at all caught a dangling ref"
    assert any("content-address" in p for p in problems)


def test_mutation_provenance_content_address_guard():
    book = nc.ProvenanceBook()
    ref = book.add(nf.FIXTURE_PROVENANCE)
    card = nc.build_card(nf._record(), revision="git:abc", provenance=ref)
    liar = nc.ProvenanceBook({ref: {"source": "a different origin entirely"}})
    assert any("content-address" in p for p in nc.validate_card(card, liar))

    mutant = mutate("elif provenance_ref(block) != ref:")
    assert mutant.validate_card(card, mutant.ProvenanceBook(liar.as_dict())) == []


def test_mutation_content_budget_guard():
    book = nc.ProvenanceBook()
    ref = book.add(nf.FIXTURE_PROVENANCE)
    card = nc.build_card(
        nf._record(text="x" * 400), revision="git:abc", provenance=ref, content_budget=20
    )
    card["content"]["text"] = "x" * 400
    nf._readdress(card)
    assert any("content over budget" in p for p in nc.validate_card(card, book))

    mutant = mutate('if len(content.get("text", "")) > budget:')
    assert mutant.validate_card(card, mutant.ProvenanceBook(book.as_dict())) == []


def test_mutation_content_truncation_flag_guard():
    book = nc.ProvenanceBook()
    ref = book.add(nf.FIXTURE_PROVENANCE)
    card = nc.build_card(
        nf._record(text="x" * 400), revision="git:abc", provenance=ref, content_budget=20
    )
    card["content"]["truncated"] = False
    nf._readdress(card)
    assert any("truncated flag disagrees" in p for p in nc.validate_card(card, book))

    mutant = mutate(
        'if bool(content.get("truncated")) != (int(content.get("text_chars", 0)) > budget):'
    )
    assert mutant.validate_card(card, mutant.ProvenanceBook(book.as_dict())) == []


def test_mutation_neighborhood_budget_guard():
    edges = [
        {
            "relation": "calls",
            "direction": "out",
            "node_id": f"code://m.py#function:m.g{i}",
            "kind": "function",
            "name": f"g{i}",
        }
        for i in range(5)
    ]
    book = nc.ProvenanceBook()
    ref = book.add(nf.FIXTURE_PROVENANCE)
    card = nc.build_card(
        nf._record(neighbors=edges), revision="git:abc", provenance=ref, neighbor_budget=2
    )
    card["neighborhood"]["edges"] = edges
    nf._readdress(card)
    assert any("neighborhood over budget" in p for p in nc.validate_card(card, book))

    mutant = mutate('if len(hood.get("edges", ())) > hood_budget:')
    assert mutant.validate_card(card, mutant.ProvenanceBook(book.as_dict())) == []


def test_mutation_neighborhood_truncation_flag_guard():
    book = nc.ProvenanceBook()
    ref = book.add(nf.FIXTURE_PROVENANCE)
    card = nc.build_card(nf._record(), revision="git:abc", provenance=ref)
    card["neighborhood"]["truncated"] = True  # claims a drop that never happened
    nf._readdress(card)
    assert any("truncated flag disagrees" in p for p in nc.validate_card(card, book))

    mutant = mutate(
        'if bool(hood.get("truncated")) != (int(hood.get("edge_total", 0)) > hood_budget):'
    )
    assert mutant.validate_card(card, mutant.ProvenanceBook(book.as_dict())) == []


def test_mutation_empty_provenance_block_guard():
    with pytest.raises(ValueError):
        nc.ProvenanceBook().add({})

    mutant = mutate("if not block:")
    mutant.ProvenanceBook().add({})  # the mutant accepts what the guard refuses


def test_the_mutation_harness_would_notice_a_missing_target():
    """The probe must fail loudly if a guard is renamed out from under it."""
    with pytest.raises(AssertionError, match="not unique"):
        mutate("if this_condition_does_not_exist:")

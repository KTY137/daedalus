"""EXPERIMENT s06: the negative path — fixtures that make the zero counters move.

Why this module exists
----------------------
The first version of the slice reported ``records_rejected = 0`` and
``contract_violations = 0`` and presented them as results.  They were not
results.  The probe fed only well-formed records into ``build_card``, and
``build_card`` raises before a malformed record can become a card — so neither
counter *could* have been anything but zero.  A counter that cannot move is
not a measurement; it is a restatement of the code's control flow.

What fixes it is not a better assertion but a second input.  Each fixture here
constructs input that violates exactly one condition, runs it through
``node_cards.tally`` — **the same function the corpus run uses**, not a
parallel checker written to agree with it — and reports the counter before and
after.  A zero over the real corpus then carries information, because the same
counter has been shown to be non-zero over input that deserves it.

The five conditions, each with its own check
--------------------------------------------
1. ``malformed_record``      -- a record that breaks the input contract
2. ``duplicate_node_id``     -- two records that collapse to one identity
3. ``budget_overrun``        -- content/neighborhood past their declared bound
4. ``missing_plane``         -- a card that lost a mandatory field
5. ``missing_revision``      -- a card that is not revision-bound
6. ``dangling_provenance``   -- a ref that resolves to nothing

Condition 6 guards the compression this slice introduced: provenance is now
carried by reference, and a reference into nothing would be strictly worse
than the literal it replaced.

Read-only, pure stdlib, no repository imports, no writes, no network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from node_cards import (
    ProvenanceBook,
    build_card,
    sha256_of,
    tally,
)

#: A provenance block the fixtures share.  Its ref is registered in each
#: fixture's own book, except where the fixture is specifically about a ref
#: that does not resolve.
FIXTURE_PROVENANCE = {
    "source": "negative_fixtures",
    "extractor": "experiments.forest_v2.s06_cards.negative_fixtures",
    "extractor_version": "1",
    "input_contract": "forest-v2-node-record/1",
    "read_only": True,
    "promotes": "nothing",
}


def _record(qualname: str = "m.f", **overrides) -> dict:
    record = {
        "plane": "code",
        "kind": "function",
        "path": "m.py",
        "qualname": qualname,
        "start_line": 1,
        "end_line": 3,
        "text": "def f():\n    return 1\n",
    }
    record.update(overrides)
    return record


def _readdress(card: dict) -> dict:
    """Recompute ``card_id`` after tampering.

    Without this every fixture would also trip the ``card_id`` guard, and a
    check that fires for two reasons proves neither.  Re-addressing isolates
    the tamper to the one condition under test.
    """
    body = {k: v for k, v in card.items() if k != "card_id"}
    card["card_id"] = sha256_of(body)
    return card


@dataclass(frozen=True)
class Fixture:
    """One negative condition, and the counter it must move."""

    id: str
    condition: str
    counter: str
    build: Callable[[str], tuple[list[dict], int, ProvenanceBook]]


# ---------------------------------------------------------------------------
# 1. a malformed record must be rejected, not silently carded
# ---------------------------------------------------------------------------
def _f_malformed(revision: str):
    book = ProvenanceBook()
    ref = book.add(FIXTURE_PROVENANCE)
    broken = [
        _record(qualname=""),                      # empty mandatory field
        {k: v for k, v in _record().items() if k != "start_line"},  # missing field
        _record(plane="astrology"),                # not one of the four planes
        _record(start_line=9, end_line=2),         # range runs backwards
    ]
    cards, rejected = [], 0
    for record in broken:
        try:
            cards.append(build_card(record, revision=revision, provenance=ref))
        except ValueError:
            rejected += 1
    return cards, rejected, book


# ---------------------------------------------------------------------------
# 2. two records that collapse to one node_id must be visible as a collision
# ---------------------------------------------------------------------------
def _f_duplicate(revision: str):
    book = ProvenanceBook()
    ref = book.add(FIXTURE_PROVENANCE)
    # Same plane/path/kind/qualname, different lines: node_id carries no line
    # numbers by design, so these two ARE one identity.
    cards = [
        build_card(_record(start_line=1, end_line=3), revision=revision, provenance=ref),
        build_card(
            _record(start_line=40, end_line=44), revision=revision, provenance=ref
        ),
    ]
    return cards, 0, book


# ---------------------------------------------------------------------------
# 3. a budget is a bound; a card past it is a violation, not a curiosity
# ---------------------------------------------------------------------------
def _f_budget(revision: str):
    book = ProvenanceBook()
    ref = book.add(FIXTURE_PROVENANCE)
    neighbors = [
        {
            "relation": "calls",
            "direction": "out",
            "node_id": f"code://m.py#function:m.g{i}",
            "kind": "function",
            "name": f"g{i}",
        }
        for i in range(6)
    ]
    over_content = build_card(
        _record(text="x" * 500),
        revision=revision,
        provenance=ref,
        content_budget=50,
    )
    over_content["content"]["text"] = "x" * 500  # past the budget it declares
    _readdress(over_content)

    over_hood = build_card(
        _record(qualname="m.h", neighbors=neighbors),
        revision=revision,
        provenance=ref,
        neighbor_budget=2,
    )
    over_hood["neighborhood"]["edges"] = neighbors  # 6 edges under a bound of 2
    _readdress(over_hood)
    return [over_content, over_hood], 0, book


# ---------------------------------------------------------------------------
# 4. a card that lost a mandatory field is not a card
# ---------------------------------------------------------------------------
def _f_missing_plane(revision: str):
    book = ProvenanceBook()
    ref = book.add(FIXTURE_PROVENANCE)
    card = build_card(_record(), revision=revision, provenance=ref)
    del card["plane"]
    _readdress(card)
    return [card], 0, book


# ---------------------------------------------------------------------------
# 5. a card that is not revision-bound breaks §5 atomicity
# ---------------------------------------------------------------------------
def _f_missing_revision(revision: str):
    book = ProvenanceBook()
    ref = book.add(FIXTURE_PROVENANCE)
    card = build_card(_record(), revision=revision, provenance=ref)
    card["revision"] = ""
    _readdress(card)
    return [card], 0, book


# ---------------------------------------------------------------------------
# 6. provenance by reference is only honest while the reference resolves
# ---------------------------------------------------------------------------
def _f_dangling_provenance(revision: str):
    book = ProvenanceBook()
    ref = book.add(FIXTURE_PROVENANCE)
    card = build_card(_record(), revision=revision, provenance=ref)
    # A well-formed ref that this build never registered.
    card["provenance"] = "sha256:" + "0" * 64
    _readdress(card)
    return [card], 0, book


FIXTURES: tuple[Fixture, ...] = (
    Fixture(
        "malformed_record",
        "record breaks forest-v2-node-record/1 (empty, missing, bad plane, bad range)",
        "records_rejected",
        _f_malformed,
    ),
    Fixture(
        "duplicate_node_id",
        "two records collapse to one node_id",
        "duplicate_node_ids",
        _f_duplicate,
    ),
    Fixture(
        "budget_overrun",
        "content and neighborhood exceed the budget they declare",
        "content_over_budget",
        _f_budget,
    ),
    Fixture(
        "missing_plane",
        "card lost a mandatory field (plane)",
        "contract_violations",
        _f_missing_plane,
    ),
    Fixture(
        "missing_revision",
        "card is not revision-bound",
        "contract_violations",
        _f_missing_revision,
    ),
    Fixture(
        "dangling_provenance",
        "provenance ref does not resolve in this build",
        "provenance_refs_dangling",
        _f_dangling_provenance,
    ),
)


def _clean_baseline(revision: str) -> dict:
    """A well-formed card, through the same tally.  Every counter must be 0."""
    book = ProvenanceBook()
    ref = book.add(FIXTURE_PROVENANCE)
    card = build_card(_record(), revision=revision, provenance=ref)
    return tally([card], rejected=0, provenance_book=book)


def run_fixture(fixture: Fixture, *, revision: str = "sha256:fixture") -> dict:
    """Run one negative fixture through the production tally and report the move."""
    clean = _clean_baseline(revision)
    cards, rejected, book = fixture.build(revision)
    counts = tally(cards, rejected=rejected, provenance_book=book)
    reasons = counts.pop("_violation_reasons")
    counts.pop("_by_plane")
    counts.pop("_by_kind")
    before = int(clean.get(fixture.counter, 0))
    after = int(counts.get(fixture.counter, 0))
    return {
        "condition": fixture.condition,
        "counter": fixture.counter,
        "clean_input": before,
        "broken_input": after,
        "moved": after > before,
        "contract_violations": counts["contract_violations"],
        "violation_reasons": sorted(reasons),
    }


def counter_liveness(*, revision: str = "sha256:fixture") -> dict:
    """Evidence that each counter CAN move, reported next to the corpus zeros.

    ``all_moved`` is the claim a reader should check first: if it is false,
    some counter in the corpus report is still a structural zero and must not
    be read as a measurement.
    """
    results = {f.id: run_fixture(f, revision=revision) for f in FIXTURES}
    return {
        "note": (
            "each fixture runs through node_cards.tally, the same function the "
            "corpus run uses; a counter listed here has been shown to move"
        ),
        "all_moved": all(r["moved"] for r in results.values()),
        "fixtures": results,
    }

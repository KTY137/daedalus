"""EXPERIMENT s06 tests: the Node Card contract must hold, not merely run.

Run directly:  python -m pytest experiments/forest_v2/s06_cards/test_node_cards.py
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import node_cards as nc  # noqa: E402


def make_record(**overrides) -> dict:
    record = {
        "plane": "code",
        "kind": "function",
        "path": "pkg/mod.py",
        "qualname": "pkg.mod.do_thing",
        "start_line": 10,
        "end_line": 20,
        "signature": "(value: int) -> int",
        "doc": "Do the thing.\n\nLonger prose that is not the summary.",
        "text": "def do_thing(value):\n    return value + 1\n",
        "source_sha256": nc.sha256_text("file body"),
        "neighbors": [
            {
                "relation": "contained_by",
                "direction": "in",
                "node_id": "code://pkg/mod.py#module:pkg.mod",
                "kind": "module",
                "name": "pkg.mod",
            }
        ],
    }
    record.update(overrides)
    return record


PROVENANCE = {"source": "test", "extractor": "s06.test", "extractor_version": "1"}
BOOK = nc.ProvenanceBook()
PROVENANCE_REF = BOOK.add(PROVENANCE)


def build(record: dict, **kwargs) -> dict:
    return nc.build_card(record, revision="git:abc123", provenance=PROVENANCE, **kwargs)


# --- the seven §6 fields ---------------------------------------------------


def test_card_carries_every_field_section_six_demands():
    card = build(make_record())
    assert nc.validate_card(card) == []
    assert card["node_id"]
    assert card["revision"] == "git:abc123"
    assert card["plane"] == "code"
    assert card["locator"]["path"] == "pkg/mod.py"
    assert card["locator"]["start_line"] == 10
    assert card["content"]["text"].startswith("def do_thing")
    assert card["neighborhood"]["edges"][0]["relation"] == "contained_by"
    # Provenance is present as a resolvable content address, not as a blob.
    assert card["provenance"] == PROVENANCE_REF
    assert BOOK.resolve(card)["extractor"] == "s06.test"


def test_card_id_addresses_the_body():
    card = build(make_record())
    body = {k: v for k, v in card.items() if k != "card_id"}
    assert card["card_id"] == nc.sha256_of(body)


def test_tampering_with_any_field_is_caught_by_validate():
    card = build(make_record())
    card["locator"]["start_line"] = 999
    assert "card_id does not address the card body" in nc.validate_card(card)


# --- the two identities ----------------------------------------------------


def test_node_id_survives_a_line_shift_but_card_id_does_not():
    """The whole point of splitting identity from content address."""
    original = build(make_record())
    moved = build(make_record(start_line=110, end_line=120))
    assert original["node_id"] == moved["node_id"]
    assert original["card_id"] != moved["card_id"]


def test_node_id_excludes_line_numbers():
    assert "10" not in nc.node_id(make_record())


def test_same_qualname_twice_in_one_file_stays_distinguishable():
    first = nc.node_id(make_record())
    second = nc.node_id(make_record(ordinal=1))
    assert first != second


def test_card_is_deterministic_across_rebuilds():
    assert build(make_record())["card_id"] == build(make_record())["card_id"]


def test_no_wall_clock_leaks_into_a_card():
    """A timestamped card could never be compared across revisions."""
    card = build(make_record())
    text = json.dumps(card)
    for stamp in ("2026-", "timestamp", "generated_at", "ingested_at"):
        assert stamp not in text


# --- compact content -------------------------------------------------------


def test_content_is_truncated_to_budget_but_the_full_digest_survives():
    body = secrets.token_hex(64)  # 128 chars, generated at runtime, never a literal
    card = build(make_record(text=body), content_budget=32)
    assert card["content"]["text"] == body[:32]
    assert card["content"]["truncated"] is True
    assert card["content"]["text_chars"] == 128
    assert card["content"]["text_sha256"] == nc.sha256_text(body)


def test_untruncated_content_is_flagged_honestly():
    card = build(make_record(text="short"), content_budget=1000)
    assert card["content"]["truncated"] is False


def test_doc_is_reduced_to_its_first_paragraph():
    card = build(make_record())
    assert card["content"]["doc"] == "Do the thing."


# --- local neighbourhood ---------------------------------------------------


def test_neighborhood_is_bounded_and_reports_what_it_dropped():
    neighbors = [
        {
            "relation": "contains",
            "direction": "out",
            "node_id": f"code://pkg/mod.py#function:f{index}",
            "kind": "function",
            "name": f"f{index}",
        }
        for index in range(20)
    ]
    card = build(make_record(neighbors=neighbors), neighbor_budget=5)
    assert len(card["neighborhood"]["edges"]) == 5
    assert card["neighborhood"]["edge_total"] == 20
    assert card["neighborhood"]["truncated"] is True


def test_neighborhood_order_is_deterministic_regardless_of_input_order():
    neighbors = [
        {"relation": "contains", "direction": "out", "node_id": f"n{i}",
         "kind": "function", "name": f"f{i}"}
        for i in range(6)
    ]
    forward = build(make_record(neighbors=neighbors))
    backward = build(make_record(neighbors=list(reversed(neighbors))))
    assert forward["card_id"] == backward["card_id"]


def test_duplicate_edges_collapse():
    edge = {"relation": "imports", "direction": "out", "node_id": "code://module:json",
            "kind": "module", "name": "json"}
    card = build(make_record(neighbors=[edge, dict(edge)]))
    assert card["neighborhood"]["edge_total"] == 1


# --- contract enforcement --------------------------------------------------


def test_a_record_without_a_plane_is_refused():
    with pytest.raises(ValueError):
        build(make_record(plane=None))


def test_a_fifth_plane_is_refused():
    with pytest.raises(ValueError) as excinfo:
        build(make_record(plane="ast"))
    assert "plane" in str(excinfo.value)


def test_an_unbound_revision_is_a_contract_violation():
    card = nc.build_card(make_record(), revision="", provenance=PROVENANCE)
    assert "empty revision (a card must be revision-bound)" in nc.validate_card(card)


def test_a_card_without_provenance_is_refused_at_build_time():
    with pytest.raises(ValueError, match="provenance"):
        nc.build_card(make_record(), revision="git:abc", provenance={})


def test_an_empty_provenance_on_an_existing_card_is_a_contract_violation():
    card = build(make_record())
    card["provenance"] = ""
    card["card_id"] = nc.sha256_of({k: v for k, v in card.items() if k != "card_id"})
    assert "empty provenance" in nc.validate_card(card)


# --- plane genericity ------------------------------------------------------


def test_a_knowledge_record_builds_through_the_same_builder():
    card = build(
        make_record(
            plane="knowledge",
            kind="section",
            path="doc/note.md",
            qualname="note/Findings",
            text="# Findings\n\nSomething measured.\n",
            neighbors=[],
        )
    )
    assert nc.validate_card(card) == []
    assert card["plane"] == "knowledge"
    assert card["node_id"].startswith("knowledge://")


# --- size measurement ------------------------------------------------------


def test_size_stats_are_raw_counts_over_canonical_bytes():
    cards = [build(make_record(text="x" * n, start_line=n, end_line=n)) for n in (1, 50, 500)]
    stats = nc.size_stats(cards)
    assert stats["cards"] == 3
    assert stats["bytes_min"] <= stats["bytes_p50"] <= stats["bytes_max"]
    assert stats["bytes_total"] == sum(nc.card_size_bytes(c) for c in cards)


def test_size_stats_on_no_cards_says_zero_not_crash():
    assert nc.size_stats([]) == {"cards": 0}


def test_jsonl_round_trips():
    cards = [build(make_record()), build(make_record(ordinal=1))]
    lines = nc.to_jsonl(cards).splitlines()
    assert [json.loads(line)["card_id"] for line in lines] == [c["card_id"] for c in cards]


# --- provenance carried by reference ---------------------------------------


def test_the_card_carries_a_ref_not_the_block():
    card = build(make_record())
    assert isinstance(card["provenance"], str)
    assert card["provenance"].startswith("sha256:")
    assert len(card["provenance"]) == len("sha256:") + 64


def test_two_cards_sharing_an_origin_share_one_block():
    book = nc.ProvenanceBook()
    ref = book.add(PROVENANCE)
    a = nc.build_card(make_record(), revision="r", provenance=ref)
    b = nc.build_card(make_record(qualname="pkg.mod.other"), revision="r", provenance=ref)
    assert a["provenance"] == b["provenance"]
    assert len(book) == 1


def test_the_ref_is_the_content_address_of_the_block():
    ref = nc.provenance_ref(PROVENANCE)
    assert ref == nc.sha256_of(PROVENANCE)
    assert nc.provenance_ref({**PROVENANCE, "extractor_version": "2"}) != ref


def test_the_ref_costs_a_constant_and_only_pays_off_above_break_even():
    """The honest version of "provenance by reference is cheaper".

    It is not always cheaper.  A ref is a fixed 73 canonical bytes; a block
    smaller than that is cheaper inlined.  The claim this slice may make is
    the narrow one: the ref cost does not grow with the origin description,
    and the block s06 actually carries is far past break-even.
    """
    card = build(make_record())
    ref_size = nc.card_size_bytes(card)

    tiny = {"s": "t"}
    real = {
        "source": "standin_ast_extractor",
        "extractor": "experiments.forest_v2.s06_cards.standin_source",
        "extractor_version": "1",
        "input_contract": "forest-v2-node-record/1",
        "plane": "code",
        "read_only": True,
        "promotes": "nothing",
    }

    # A ref is the same size whatever it points at.
    assert nc.card_size_bytes(
        dict(card, provenance=nc.provenance_ref(tiny))
    ) == nc.card_size_bytes(dict(card, provenance=nc.provenance_ref(real)))

    # Below break-even the ref LOSES.  Saying otherwise would be the same
    # kind of overclaim this slice is here to remove.
    assert nc.card_size_bytes(dict(card, provenance=tiny)) < ref_size
    # The block s06 really carries is well above it.
    assert nc.card_size_bytes(dict(card, provenance=real)) > ref_size


def test_break_even_is_where_the_measured_claim_comes_from():
    card = build(make_record())
    ref_size = nc.card_size_bytes(card)
    # A ref serialises as 73 bytes: 'sha256:' + 64 hex + two quotes.
    assert len(nc.canonical_bytes(card["provenance"])) == 73
    filler = {"k": "x" * 200}
    saved = nc.card_size_bytes(dict(card, provenance=filler)) - ref_size
    assert saved > 0


def test_a_ref_that_does_not_resolve_is_a_contract_violation():
    book = nc.ProvenanceBook()
    book.add(PROVENANCE)
    card = build(make_record())
    card["provenance"] = "sha256:" + "0" * 64
    card["card_id"] = nc.sha256_of({k: v for k, v in card.items() if k != "card_id"})
    problems = nc.validate_card(card, book)
    assert any("does not resolve" in p for p in problems)
    # ...and without a book to check against, the same card looks fine, which
    # is exactly why the probe always passes its book.
    assert nc.validate_card(card) == []


def test_a_block_that_does_not_address_its_ref_is_caught():
    book = nc.ProvenanceBook()
    ref = book.add(PROVENANCE)
    card = build(make_record())
    tampered = nc.ProvenanceBook({ref: {"source": "someone else's origin"}})
    problems = nc.validate_card(card, tampered)
    assert any("content-address" in p for p in problems)


def test_a_provenance_ref_that_is_not_a_sha256_is_refused():
    card = build(make_record())
    card["provenance"] = "s01 (not available at build time)"
    card["card_id"] = nc.sha256_of({k: v for k, v in card.items() if k != "card_id"})
    assert any("not a sha256 ref" in p for p in nc.validate_card(card))


def test_an_empty_block_cannot_be_registered():
    with pytest.raises(ValueError, match="empty provenance block"):
        nc.ProvenanceBook().add({})


# --- budgets are bounds, and a bound that is exceeded is a violation --------


def test_content_past_its_declared_budget_is_a_violation():
    card = build(make_record(text="x" * 40), content_budget=10)
    assert nc.validate_card(card) == []
    card["content"]["text"] = "x" * 40
    card["card_id"] = nc.sha256_of({k: v for k, v in card.items() if k != "card_id"})
    assert any("content over budget" in p for p in nc.validate_card(card))


def test_a_neighborhood_past_its_declared_budget_is_a_violation():
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
    card = build(make_record(neighbors=edges), neighbor_budget=2)
    assert nc.validate_card(card) == []
    card["neighborhood"]["edges"] = edges
    card["card_id"] = nc.sha256_of({k: v for k, v in card.items() if k != "card_id"})
    assert any("neighborhood over budget" in p for p in nc.validate_card(card))


def test_a_lying_truncation_flag_is_caught():
    card = build(make_record(text="x" * 40), content_budget=10)
    card["content"]["truncated"] = False
    card["card_id"] = nc.sha256_of({k: v for k, v in card.items() if k != "card_id"})
    assert any("truncated flag disagrees" in p for p in nc.validate_card(card))

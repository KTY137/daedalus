"""The picker's GENERATED source: candidates derived from `daedalus map`.

Why this source exists. The picker's only effective input used to be
``docs/FEATURE_INVENTORY.json``, which is hand-written -- nothing in the repo
generates it -- and which was measured thirty commits stale while driving the
two highest bands. ``docs/architecture-state.json`` describes the same property
("built, but nothing reaches it") and cannot rot the same way: it is generated,
covered by its own digest, and gated by ``daedalus map --check``.

Two properties carry this file:

TRUST IS VERIFIED, NOT ASSUMED. ``daedalus.mapping.drift`` states the rule --
any verb that INHERITS lists from a snapshot rather than rescanning must check
the digest first, or a hand-edit the drift gate would have caught silently
becomes the thing the loop picks work from. Fixtures here are stamped with the
REAL ``_digest``, so these tests exercise the same contract the product does
rather than a mocked stand-in.

ISLANDS AND SHIMS ARE NOT THE SAME FINDING. They look alike in a count and need
opposite remedies: an island is capability nobody can reach and usually wants
wiring; a shim is indirection nobody uses and wants removing. Handing a fixer
the wrong verb is the failure this separation prevents.
"""
from __future__ import annotations

import json

import pytest

import daedalus.spine.picker as picker
from daedalus.spine.picker import (
    BAND_SPAN,
    SOURCE_BANDS,
    build_queue,
    load_map_state,
    map_candidates,
    map_state_trustworthy,
)


def _real_head() -> str:
    """The HEAD the product's own freshness check will compare against.

    Read through the picker's reader rather than a second git call, so a
    fixture can never disagree with the code under test about what HEAD is."""
    return picker._head_sha(picker.ROOT) or "0" * 40


def _stamped(**overrides) -> dict:
    """A snapshot carrying a genuinely valid digest, per the real algorithm.

    Stamped FRESH by default. The revision lives inside the digest on purpose:
    if it sat outside, anyone could rewrite the recorded head to make a stale
    snapshot look current, and the freshness gate would be decorative."""
    from daedalus.mapping.drift import _digest

    doc = {
        "schema": 3,
        "repo_state": {"head": _real_head(), "branch": "t", "dirty": False},
        "counts": {"modules": 3, "islands": 1, "shims": 1},
        "ignore": {},
        "modules": ["pkg/a.py", "pkg/b.py", "pkg/c.py"],
        "islands": ["pkg/a.py"],
        "unknown": [],
        "shims": ["pkg/b.py"],
        "test_only": ["pkg/a.py"],
        "dark_switches": [],
        "doc_drift": [],
        "unparsable": [],
        "index_extra_edges": [],
        "acceptances": [],
        "note": "GENERATED",
    }
    doc.update(overrides)
    doc["digest"] = _digest(doc)
    return doc


def _write_map(tmp_path, doc):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "architecture-state.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


@pytest.fixture
def no_eval(monkeypatch):
    monkeypatch.setattr(picker, "_load_baseline", lambda: ({}, None))
    return monkeypatch


# --------------------------------------------------------------------------- #
# trust                                                                        #
# --------------------------------------------------------------------------- #
def test_a_valid_snapshot_is_trusted():
    assert map_state_trustworthy(_stamped())["trusted"] is True


def test_a_hand_edited_snapshot_is_refused():
    # The exact failure the digest exists to catch: somebody deletes an
    # inconvenient island from the generated file by hand.
    doc = _stamped()
    doc["islands"] = []                      # edited AFTER the digest was written
    got = map_state_trustworthy(doc)
    assert got["trusted"] is False
    assert "hand-edited" in got["reason"]


def test_editing_acceptances_does_not_break_trust():
    # acceptances is the one part a human is SUPPOSED to write, so it is
    # deliberately outside the digest. If this ever fails, the picker would be
    # refusing snapshots for the one edit the workflow requires.
    doc = _stamped()
    doc["acceptances"] = [{"id": "island:pkg/a.py", "why": "kept on purpose"}]
    assert map_state_trustworthy(doc)["trusted"] is True


def test_an_absent_snapshot_is_not_an_error():
    assert map_state_trustworthy({})["trusted"] is True
    assert map_candidates({}) == ((), ())


# --------------------------------------------------------------------------- #
# freshness -- the half that was missing, and what its absence cost            #
# --------------------------------------------------------------------------- #
def test_a_STALE_snapshot_is_refused_even_though_its_digest_verifies():
    """The bug this file's own docstring used to assert was impossible.

    That docstring said the generated snapshot "cannot rot the same way" as the
    hand-written inventory, because it is covered by a digest. A digest proves
    nobody TAMPERED with the file. It says nothing about which tree was scanned,
    and a snapshot generated thirty commits ago verifies its digest perfectly.

    Measured consequence: an agent executed the loop's top recommendation, which
    asserted daedalus/compaction.py was an unreachable island. On the live tree
    it was not an island -- the picker had suppressed the stale inventory (which
    has a freshness gate) while trusting the stale map (which had none).
    """
    doc = _stamped(repo_state={"head": "dead" * 10, "branch": "t", "dirty": False})
    got = map_state_trustworthy(doc)
    assert got["trusted"] is False
    assert got["integrity"] is True, "integrity is fine; it is freshness that failed"
    assert "was written against" in got["reason"]


def test_a_snapshot_that_records_no_head_is_refused_not_assumed_fresh():
    """Fail CLOSED. Today's generator records no repo_state at all, so this is
    the live verdict on the real file -- and "I cannot check" must never be
    reported as "checked and fine"."""
    doc = _stamped()
    doc.pop("repo_state")
    from daedalus.mapping.drift import _digest
    doc["digest"] = _digest(doc)          # a HONESTLY re-stamped snapshot
    got = map_state_trustworthy(doc)
    assert got["trusted"] is False
    assert "records no repo_state.head" in got["reason"]


def test_integrity_and_freshness_are_reported_separately():
    """A caller must be able to tell a hand-edit from a stale scan: one means
    somebody edited a generated file, the other means run `daedalus map`."""
    edited = _stamped()
    edited["islands"] = []
    assert map_state_trustworthy(edited)["integrity"] is False

    stale = _stamped(repo_state={"head": "beef" * 10, "branch": "t", "dirty": False})
    assert map_state_trustworthy(stale)["integrity"] is True
    assert map_state_trustworthy(stale)["freshness"]["fresh"] is False


@pytest.mark.xfail(strict=True, reason=(
    "repo_state is NOT yet covered by daedalus.mapping.drift._digest, so a "
    "forged head is undetectable by integrity. Owned by the mapping layer, not "
    "by the picker. strict=True on purpose: the day _MECHANICAL_KEYS grows to "
    "include repo_state this test PASSES, the suite goes RED, and somebody has "
    "to come here and delete this marker deliberately."))
def test_a_forged_head_is_caught_as_a_hand_edit():
    """The attack the freshness gate does not stop on its own.

    A wrong head is caught by freshness (see the stale test above). The
    dangerous edit is the opposite one: take a genuinely stale snapshot and
    rewrite its recorded head to the CURRENT revision. Freshness then says
    "matches HEAD" and the lists are still thirty commits old. Only the digest
    can catch that, and only if it covers repo_state.
    """
    doc = _stamped()
    doc["repo_state"] = {"head": _real_head(), "branch": "t", "dirty": False}
    doc["islands"] = ["pkg/a.py", "pkg/forged.py"]   # the stale half, edited
    from daedalus.mapping.drift import _digest
    doc["digest"] = _digest(doc)      # re-stamped: covers the lists...
    doc["repo_state"] = {"head": _real_head(), "branch": "t", "dirty": False}
    got = map_state_trustworthy(doc)
    assert got.get("integrity") is False, (
        "repo_state sits outside the digest -- a forged head passes unnoticed")


def test_a_dirty_tree_does_not_suppress_the_map():
    """This repo is almost always dirty mid-session. Refusing to rank work
    whenever an editor has unsaved changes would make the loop unusable for
    exactly the person using it."""
    doc = _stamped(repo_state={"head": _real_head(), "branch": "t", "dirty": True})
    assert map_state_trustworthy(doc)["trusted"] is True


def test_an_unreadable_snapshot_degrades_to_empty(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture-state.json").write_text("{not json", encoding="utf-8")
    assert load_map_state(repo_root=tmp_path) == {}


# --------------------------------------------------------------------------- #
# candidates                                                                   #
# --------------------------------------------------------------------------- #
def test_islands_and_shims_are_separate_sources_with_separate_remedies():
    cands, _ = map_candidates(_stamped())
    by_source = {c.source: c for c in cands}
    assert set(by_source) == {"map_island", "map_shim"}

    island = by_source["map_island"].instruction
    shim = by_source["map_shim"].instruction
    assert "wire it into a real caller" in island
    assert "do not 'wire it in'" in shim, "a shim was handed the island's verb"
    assert "remove the shim" in shim


def test_an_island_imported_only_by_tests_outranks_one_with_no_importer():
    tested, _ = map_candidates(_stamped())
    lonely_doc = _stamped(test_only=[])
    lonely, _ = map_candidates(lonely_doc)
    a = next(c for c in tested if c.source == "map_island")
    b = next(c for c in lonely if c.source == "map_island")
    # Behaviour that is already pinned is cheaper and safer to move.
    assert a.offset > b.offset
    assert a.evidence["imported_only_by_tests"] is True
    assert b.evidence["imported_only_by_tests"] is False


def test_every_map_candidate_carries_its_generated_provenance():
    cands, _ = map_candidates(_stamped())
    for c in cands:
        assert "architecture-state.json" in c.evidence["measurement"]
        assert c.evidence["snapshot_digest"].startswith("sha256:")
        assert c.evidence["module"]
        assert c.evidence["classification"] in ("island", "shim")


def test_unclassifiable_modules_are_reported_but_never_ranked():
    # "the engine could not classify this" is a finding about the MAP. Ranking
    # it would send a fixer to change code because a scanner was confused.
    cands, notes = map_candidates(_stamped(unknown=["pkg/c.py"]))
    assert all("pkg/c.py" not in c.task_id for c in cands)
    assert any("could not classify" in n for n in notes)


def test_task_ids_are_stable_across_runs():
    a, _ = map_candidates(_stamped())
    b, _ = map_candidates(_stamped())
    assert [c.task_id for c in a] == [c.task_id for c in b]


# --------------------------------------------------------------------------- #
# how it sits in the queue                                                     #
# --------------------------------------------------------------------------- #
def test_the_generated_source_outranks_the_hand_written_one():
    # The whole argument for this source: when two sources describe the same
    # property, the one that cannot silently rot is the one to work from.
    assert SOURCE_BANDS["map_island"] > SOURCE_BANDS["inventory_island"]
    assert SOURCE_BANDS["map_shim"] > SOURCE_BANDS["inventory_island"]


def test_adding_map_bands_did_not_break_the_non_crossing_invariant():
    bands = sorted(SOURCE_BANDS.values())
    smallest_gap = min(b - a for a, b in zip(bands, bands[1:]))
    assert BAND_SPAN < smallest_gap, (
        "a measurement can now cross a band boundary; the stated priority is "
        "no longer stated")


def test_a_hand_edited_snapshot_is_withheld_from_the_queue_loudly(tmp_path, no_eval):
    doc = _stamped()
    doc["islands"] = []
    _write_map(tmp_path, doc)
    q = build_queue(tmp_path, limit=None)
    assert q.sources["map"]["suppressed"] is True
    assert q.sources["map"]["candidates"] == 0
    assert any("MAP SUPPRESSED" in n for n in q.notes)
    assert "map" in q.degraded_sources


def test_a_valid_snapshot_fills_the_queue(tmp_path, no_eval):
    _write_map(tmp_path, _stamped())
    q = build_queue(tmp_path, limit=None)
    assert q.sources["map"]["suppressed"] is False
    assert q.sources["map"]["candidates"] == 2
    assert "map" not in q.degraded_sources
    assert q.candidates[0].source == "map_island"


def test_the_real_repo_snapshot_is_JUDGED_and_ACTED_ON_consistently():
    """Against the ACTUAL committed snapshot -- the configuration the product
    runs in. A fixture-only test here would prove nothing about this repo.

    This used to assert `trusted is True` unconditionally, which quietly
    encoded the assumption that the real snapshot is always usable. It was not:
    today's generator records no `repo_state`, so the honest verdict is NOT
    trusted, and asserting otherwise would have forced someone to weaken the
    freshness gate to keep a test green.

    What must hold either way is the INVARIANT, so that is what is asserted:
    the verdict is computed, and the queue obeys it. Trusted -> the map's work
    items are offered. Not trusted -> they are withheld AND the reason is said
    out loud, because a suppressed source that stays silent is indistinguishable
    from a source with no work in it.
    """
    state = load_map_state()
    if not state:
        pytest.skip("no committed architecture-state.json")
    trust = map_state_trustworthy(state)
    cands, _ = map_candidates(state)
    assert {c.source for c in cands} <= {"map_island", "map_shim"}

    if trust["trusted"]:
        assert cands, "the generated map produced no work items for this repo"
        return

    # Withheld -- prove the picker actually withholds, and says why.
    assert trust["reason"], "a refusal with no reason is unactionable"
    queue = build_queue(limit=50)
    src = queue.sources["map"]
    assert src["suppressed"] is True
    assert src["candidates"] == 0
    assert not any(c.source.startswith("map_") for c in queue.candidates), (
        "the map was judged untrustworthy but its candidates were ranked anyway")
    assert any("MAP SUPPRESSED" in n for n in queue.notes), (
        "the map was withheld silently -- indistinguishable from having no work")

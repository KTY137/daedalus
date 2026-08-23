"""Checks for the cross-corpus probe.

Run directly::

    python -m pytest experiments/forest_v2/s02_types/test_external_corpora.py

Three kinds of assertion live here, deliberately kept apart:

* corpora with a **frozen input** are pinned exactly -- the hand-written
  fixture, and (since continuation 4) the kernel package read out of git at
  ``revision_corpus.PINNED_REVISION``.  These may be pinned because nothing
  can move them.  If one fails, the resolver changed or the anchor was
  repointed, and the write-up is stale.
* the **live working tree** is asserted only on the finding it carries --
  ``marginal_functions``, ``internal_named_only``, the verified share, the
  subtractive ordering.  Its counts and percentages are *reported* through
  ``drift_vs_pin`` rather than pinned.  The earlier version of this module
  pinned the live tree exactly and said so in this docstring; on 2026-08-18
  two unrelated kernel commits added one function, ``functions == 4203`` went
  red, and a port stopped on a check about a tree nobody in that port had
  touched.  The guard was right about the drift and wrong about what to do
  with it: a count that moves with every commit is an observation.
* the external corpora are asserted only on properties that do not depend on
  which versions this machine happens to have installed.  Their exact figures
  belong in the write-up stamped with the interpreter and the content pin,
  not in a check that would go red on someone else's box.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_external_corpora as pec  # noqa: E402
import revision_corpus as rc  # noqa: E402

_REPORT: dict | None = None


def report() -> dict:
    """The probe walks ~800 files; run it once for the whole module."""
    global _REPORT
    if _REPORT is None:
        _REPORT = pec.run()
    return _REPORT


def row(name: str) -> dict:
    for entry in report()["corpora"]:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"corpus {name!r} missing from the report entirely")


# --------------------------------------------------------------------------
# nothing is dropped after its numbers are seen
# --------------------------------------------------------------------------
def test_every_declared_corpus_is_reported() -> None:
    names = [entry["name"] for entry in report()["corpora"]]
    assert names == [spec["name"] for spec in pec.CORPORA]
    assert report()["corpora_declared"] == len(pec.CORPORA)


def test_absent_corpora_say_why_instead_of_vanishing() -> None:
    for entry in report()["corpora"]:
        if not entry["present"]:
            assert entry["reason"]


# --------------------------------------------------------------------------
# the published kernel numbers are pinned to a revision, not to today's tree
# --------------------------------------------------------------------------
def test_the_pinned_revision_is_readable_at_all() -> None:
    """A lost anchor is a real failure, and a different one from a moved tree.

    This is the only kernel check that may go red because of history rather
    than content, and it says so in its name.  Everything below assumes the
    anchor resolved.
    """
    entry = row("kernel_at_pin")
    assert entry["present"] is True, entry.get("reason")
    assert entry["revision"] == rc.PINNED_REVISION
    assert entry["revision_is_pinned"] is True


def test_the_pinned_tree_is_the_tree_the_write_up_measured() -> None:
    """Content digest, not just a commit name.

    A revision pins a repository; the digest pins what was actually parsed.
    Checking both means a checkout that rewrote the files cannot pass as the
    published corpus on the strength of a matching sha.
    """
    entry = row("kernel_at_pin")
    assert entry["corpus_pin"]["sha256"] == rc.PINNED_KERNEL_DIGEST
    assert entry["corpus_pin"]["files"] == rc.PINNED_KERNEL_FILES
    assert entry["files_parsed"] == rc.PINNED_KERNEL_FILES
    assert entry["files_unparseable"] == 0


def test_pinned_kernel_row_is_the_retracted_headline_restated() -> None:
    """The published kernel numbers, against a frozen input.

    These may be pinned exactly because the input can no longer move.  If this
    fails, either the resolver changed behaviour or the anchor was repointed --
    both of which mean the write-up is stale, which is what a pin is for.
    """
    entry = row("kernel_at_pin")
    assert entry["functions"] == 4203
    assert entry["annotation_only_pct"] == 92.89  # the control
    assert entry["full_resolver_pct"] == 92.77
    assert entry["marginal_functions"] == 5
    assert entry["marginal_pp"] == 0.119
    # every corpus-internal name is verified here -- which is exactly why this
    # corpus cannot show what the machinery is worth
    assert entry["internal_named_only"] == 0
    assert entry["verified_share_of_internal_pct"] == 100.0


# --------------------------------------------------------------------------
# the live tree is checked for the finding, and reports its counts
# --------------------------------------------------------------------------
def test_live_kernel_row_still_carries_the_finding() -> None:
    """What survives a moved tree: the retraction, not the digits.

    The finding is that on this repository the whole binding + symbol-table
    machinery changes the verdict on a handful of functions and that every
    corpus-internal name already verifies -- which is why the kernel package
    cannot grade the resolver.  Those are the assertions.  ``functions`` and
    the three percentages are not: they move with every kernel commit and are
    reported by ``drift_vs_pin`` instead.
    """
    entry = row("kernel")
    assert entry["present"] is True
    assert entry["revision_is_pinned"] is False
    assert entry["marginal_functions"] == 5
    assert entry["internal_named_only"] == 0
    assert entry["verified_share_of_internal_pct"] == 100.0
    # subtractive by construction, and still a rounding error against the control
    assert entry["full_resolver_pct"] <= entry["annotation_only_pct"]
    assert entry["marginal_pp"] < 1.0


def test_a_moved_tree_is_reported_rather_than_asserted() -> None:
    """The drift block exists, is comparable, and names what moved.

    This is the check that replaces pinning the live tree.  It must stay green
    whether or not the tree moved -- but it must go red if the report stops
    carrying the comparison, because then a moved tree would once again be
    invisible instead of merely reported.
    """
    block = report()["drift_vs_pin"]
    assert block["comparable"] is True, block.get("reason")
    assert block["pinned_revision"] == rc.PINNED_REVISION
    assert block["pinned_digest"] == rc.PINNED_KERNEL_DIGEST
    assert set(block) >= {"tree_unchanged", "drifted", "live_digest"}

    # Named here, not read out of ``pec.DRIFTING_FIELDS``: a check that derives
    # its expectation from the constant it is checking cannot notice that
    # constant shrinking.  It did not -- a mutant that dropped ``functions``
    # from the reporter survived this check in its first form, on the very
    # tree where ``functions`` had moved.  These four are the kernel values the
    # write-up publishes; the reporter must watch all of them.
    published = {"functions", "annotation_only_pct", "full_resolver_pct", "marginal_pp"}
    assert published <= set(pec.DRIFTING_FIELDS)

    pinned, live = row("kernel_at_pin"), row("kernel")
    same = pinned["corpus_pin"]["sha256"] == live["corpus_pin"]["sha256"]
    assert block["tree_unchanged"] is same
    # a moved tree names every published value that moved; an unmoved one, none
    moved = {key for key in published if pinned.get(key) != live.get(key)}
    assert moved <= set(block["drifted"])
    assert set(block["drifted"]) <= set(pec.DRIFTING_FIELDS)
    if same:
        assert not block["drifted"]
    for key, entry in block["drifted"].items():
        assert entry["pinned"] == pinned.get(key)
        assert entry["live"] == live.get(key)


def test_fixture_row_shows_what_the_kernel_row_cannot() -> None:
    entry = row("fixture_alias")
    assert entry["annotation_only_pct"] == 73.68
    assert entry["marginal_pp"] == 15.7895
    assert entry["internal_named_only"] == 5
    assert entry["verified_share_of_internal_pct"] == 76.19
    # two orders of magnitude apart from the kernel's 0.119 pp
    assert entry["marginal_pp"] > row("kernel")["marginal_pp"] * 100


# --------------------------------------------------------------------------
# machine-independent properties of the whole comparison
# --------------------------------------------------------------------------
def test_reported_rates_are_arithmetically_consistent() -> None:
    for entry in report()["corpora"]:
        if not entry["present"]:
            continue
        expected = round(
            100.0 * entry["marginal_functions"] / (entry["functions"] or 1), 4
        )
        assert entry["marginal_pp"] == expected, entry["name"]
        internal = entry["internal_verified"] + entry["internal_named_only"]
        assert internal == entry["internal_name_sites"], entry["name"]
        assert entry["verified_share_of_internal_pct"] == round(
            100.0 * entry["internal_verified"] / (internal or 1), 2
        ), entry["name"]


def test_the_marginal_contribution_never_exceeds_its_ceiling() -> None:
    """Subtractive by construction: the resolver cannot beat its own control."""
    for entry in report()["corpora"]:
        if entry["present"]:
            assert entry["full_resolver_pct"] <= entry["annotation_only_pct"], entry["name"]


def test_the_corpus_set_actually_spans_annotation_postures() -> None:
    """A comparison over corpora that all look alike would prove nothing."""
    present = [e for e in report()["corpora"] if e["present"]]
    assert len(present) >= 4
    low = [e for e in present if e["annotation_only_pct"] < 10]
    high = [e for e in present if e["annotation_only_pct"] > 90]
    assert low, "no barely-annotated corpus in the set"
    assert high, "no heavily-annotated corpus in the set"


def test_stdlib_decouples_coverage_from_resolvability() -> None:
    """The external case the kernel package could never make.

    Version-independent claim only: some real, large, externally authored
    corpus is annotated in the low single digits while nearly every type name
    it does write attributes fine.  The exact figures are in the write-up with
    the interpreter version and the content pin next to them.
    """
    entry = row("stdlib")
    if not entry["present"]:  # pragma: no cover - stdlib is always there
        return
    assert entry["files_parsed"] > 100
    assert entry["annotation_only_pct"] < 5.0
    assert entry["type_name_resolution_pct"] > 90.0
    # and the verification gap the kernel package hides at 0
    assert entry["internal_named_only"] > 0

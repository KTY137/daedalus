"""Checks for the cross-corpus probe.

Run directly::

    python -m pytest experiments/forest_v2/s02_types/test_external_corpora.py

Two kinds of assertion live here, deliberately kept apart:

* the two in-repository corpora are pinned exactly -- if one of these fails,
  the tree moved and every number in the slice's write-up is stale;
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
# the in-repository corpora are pinned
# --------------------------------------------------------------------------
def test_kernel_row_is_the_retracted_headline_restated() -> None:
    """If this fails the kernel package moved; re-measure the write-up."""
    entry = row("kernel")
    assert entry["present"] is True
    # Re-measured on frozen G1-EVAL-CORPUS-01 source with the repository-venv
    # CPython 3.12.13; the probe ran twice and all fields except
    # corpora[*].wall_seconds/root matched. Both complete raw runs are retained
    # under runs/g1-eval-corpus-01 and archived in
    # docs/evidence/G1-EVAL-CORPUS-01. The corpus grew because the packaged
    # four-plane eval fixture (daedalus/eval/fixtures/fourfold_wiki_app/, five
    # Python files) is under daedalus/ and this probe censuses the package tree,
    # exactly as the older fixtures/sunny_garden files are already counted.
    # Prior measured rows remain in the README; this moving corpus census is
    # NOT a resolver superiority claim -- the resolver did not change.
    #
    # RE-PINNED 2026-09-08 (review fixes on the same packet): the file COUNT is
    # unchanged at 490 and every resolver number below is byte-identical; only
    # the content digest moved, because the review fix to
    # daedalus/eval/harness.py::_plane_unindexed_reason edited a file inside
    # the censused package tree. Two fresh probe runs
    # (runs/g1-eval-corpus-01/s02-fixer-{c,d}.json) matched on everything except
    # corpora[*].wall_seconds/root; non-timing canonical SHA256
    # eaf4808c4207d67b50f8b30556ad77af9a24a8172c98eca5804c7d422ada2eeb.
    # Superseded digest: 966aff67...aac1fc57a (frozen source, before the fix).
    assert entry["corpus_pin"] == {
        "files": 490,
        "sha256": "9861df4379037a00b0951191a986717c8b3dc5a6c692af0a2da4a6c00e645e45",
    }
    assert entry["functions"] == 6801
    assert entry["annotation_only_pct"] == 94.35  # the control, unmoved
    assert entry["full_resolver_pct"] == 94.24
    assert entry["marginal_functions"] == 8
    assert entry["marginal_pp"] == 0.1176
    # Preserve the repo-unverified bucket and all earlier negative/retracted rows.
    assert entry["type_name_sites"] == 45296
    assert entry["internal_named_only"] == 425
    assert entry["verified_share_of_internal_pct"] == 90.52



def test_fixture_row_shows_what_the_kernel_row_cannot() -> None:
    entry = row("fixture_alias")
    assert entry["annotation_only_pct"] == 73.68
    assert entry["marginal_pp"] == 15.7895
    assert entry["internal_named_only"] == 5
    assert entry["verified_share_of_internal_pct"] == 76.19
    # two orders of magnitude apart from the current kernel's 0.1176 pp
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

    Cross-install claim only: some real, large, externally authored corpus is
    annotated in the low single digits while a large majority of the type
    names it does write attribute fine.  The exact figures are in the write-up
    with the interpreter version and the content pin next to them.
    """
    entry = row("stdlib")
    if not entry["present"]:  # pragma: no cover - stdlib is always there
        return
    assert entry["files_parsed"] > 100
    assert entry["annotation_only_pct"] < 5.0
    # Corpus membership is intentionally install-dependent.  This Windows
    # Python 3.10.11 includes the large ``test`` package and measures 88.77%
    # at pin 09ab2d80efe3...; the project venv's Python 3.13.5 measures 90.57%
    # at a different pin.  The guard protects the cross-install separation,
    # not one corpus snapshot's 90% boundary.
    assert entry["type_name_resolution_pct"] > 80.0
    # and the verification gap the kernel package hides at 0
    assert entry["internal_named_only"] > 0

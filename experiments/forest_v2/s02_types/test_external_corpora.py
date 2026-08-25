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

import re
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
FOREST_ROOT = HERE.parent
REPO_ROOT = FOREST_ROOT.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(FOREST_ROOT))

import probe_external_corpora as pec  # noqa: E402
from _historical_tree_fixture import materialize_historical_tree  # noqa: E402
from s09_eval import gitio  # noqa: E402

_REPORT: dict | None = None
S02_SOURCE_REVISION = "deabb5182e94eeb939611aa835f72ca8234e84c8"
S02_DAEDALUS_TREE = "aacb26ef791f0b0c96a0a840e24c6ba63c32bab8"


@pytest.fixture(scope="module")
def historical_kernel(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Rebuild the published kernel row from exactly its measured source."""
    assert gitio.rev_parse(REPO_ROOT, f"{S02_SOURCE_REVISION}:daedalus") == (
        S02_DAEDALUS_TREE
    )
    tree = materialize_historical_tree(
        REPO_ROOT,
        S02_SOURCE_REVISION,
        tmp_path_factory.mktemp("forest_s02_history") / "source",
        prefixes=("daedalus",),
    )
    assert tree.blob_count == 291
    kernel = next(spec for spec in pec.CORPORA if spec["name"] == "kernel")
    return pec.measure({**kernel, "root": tree.root})


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
def test_kernel_row_is_the_retracted_headline_restated(
    historical_kernel: dict,
) -> None:
    """The published row replays against its exact historical source tree."""
    entry = historical_kernel
    assert entry["present"] is True
    assert entry["functions"] == 4203
    assert entry["annotation_only_pct"] == 92.89  # the control
    assert entry["full_resolver_pct"] == 92.77
    assert entry["marginal_functions"] == 5
    assert entry["marginal_pp"] == 0.119
    # every corpus-internal name is verified here -- which is exactly why this
    # corpus cannot show what the machinery is worth
    assert entry["internal_named_only"] == 0
    assert entry["verified_share_of_internal_pct"] == 100.0


def test_fixture_row_shows_what_the_kernel_row_cannot(
    historical_kernel: dict,
) -> None:
    entry = row("fixture_alias")
    assert entry["annotation_only_pct"] == 73.68
    assert entry["marginal_pp"] == 15.7895
    assert entry["internal_named_only"] == 5
    assert entry["verified_share_of_internal_pct"] == 76.19
    # two orders of magnitude apart from the kernel's 0.119 pp
    assert entry["marginal_pp"] > historical_kernel["marginal_pp"] * 100


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


def test_stdlib_row_is_descriptive_content_pinned_evidence() -> None:
    """Validate the row contract without universalising one stdlib build.

    CPython distributions with the same language version can ship materially
    different library trees. Semantic thresholds therefore belong to a named
    content pin, not to this cross-run contract test.
    """
    entry = row("stdlib")
    if not entry["present"]:  # pragma: no cover - stdlib is always there
        return
    pin = entry["corpus_pin"]
    assert pin["files"] == entry["files_parsed"] + entry["files_unparseable"]
    assert pin["files"] > 0
    assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
    assert entry["functions"] > 0
    assert entry["type_name_sites"] > 0
    assert sum(entry["type_name_sites_by_bucket"].values()) == entry["type_name_sites"]
    for rate in (
        "annotation_only_pct",
        "full_resolver_pct",
        "type_name_resolution_pct",
        "sig_present_annotations_resolve_pct",
        "verified_share_of_internal_pct",
    ):
        assert 0.0 <= entry[rate] <= 100.0, rate

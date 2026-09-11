"""Pin the stratified result, because it corrects a conclusion twice in one day.

Fast: asserts over the retained probe output under
``docs/evidence/gate2-stratified-20260909/``.

The load-bearing facts these protect:

* the pooled mean (+0.0118) is the average of two LARGE opposite-signed effects
  (+0.1147 cross-plane, -0.1871 control), not a small effect;
* the control result already excludes zero at n=30 -- fusion is significantly
  worse where there is nothing to fuse, and no plan criterion currently asks;
* fusion does NOT beat plain BM25 on cross-plane cases, which is why a decisive
  14.1 would probably still be negative.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

EVIDENCE = (
    Path(__file__).resolve().parents[3]
    / "docs" / "evidence" / "gate2-stratified-20260909"
)
RESULT = json.loads((EVIDENCE / "run1.json").read_text(encoding="utf-8"))
ACCEPTANCE = json.loads((EVIDENCE / "acceptance.json").read_text(encoding="utf-8"))


def _row(reference_prefix: str) -> dict:
    for row in RESULT["comparisons"]:
        if row["reference"].startswith(reference_prefix):
            return row
    raise AssertionError(f"no comparison against {reference_prefix}")


def test_both_retained_runs_are_byte_identical():
    digests = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(EVIDENCE.glob("run*.json"))
    }
    assert len(digests) == 2
    assert len(set(digests.values())) == 1
    assert digests == ACCEPTANCE["sha256"]


def test_the_strata_are_the_ones_the_census_declared():
    assert RESULT["n_total"] == 88
    assert RESULT["n_cross_plane"] == 58
    assert RESULT["n_control_single_plane"] == 30


def test_the_pooled_mean_hides_two_large_opposite_effects():
    """The whole correction in one assertion."""
    strata = _row("code_only_bm25")["strata"]
    pooled = strata["pooled"]["point"]
    cross = strata["cross_plane"]["point"]
    control = strata["control_single_plane"]["point"]

    assert abs(pooled) < 0.02, pooled
    assert cross > 0.10, cross
    assert control < -0.15, control
    # and each stratum's effect is an order of magnitude above the pooled one
    assert abs(cross) > 8 * abs(pooled)
    assert abs(control) > 8 * abs(pooled)


def test_fusion_is_significantly_WORSE_where_there_is_nothing_to_fuse():
    """Already decisive at n=30, and no plan criterion asks it."""
    for prefix in ("code_only_bm25", "separate_indices_bm25"):
        control = _row(prefix)["strata"]["control_single_plane"]
        assert control["excludes_zero"] is True, prefix
        assert control["ci95_high"] < 0, control
        assert control["losses"] >= 3 * control["wins"], control


def test_fusion_does_not_beat_plain_bm25_on_cross_plane_cases():
    """Why a decisive 14.1 would probably still be negative: the criterion is
    'beats code_only AND bm25', and BM25 is the comparison it loses."""
    cross = _row("bm25/raw")["strata"]["cross_plane"]
    assert cross["point"] < 0, cross
    assert cross["losses"] > cross["wins"], cross


def test_the_cross_plane_interval_still_includes_zero():
    """Guards against reading the correction as a KEEP. It is not one."""
    cross = _row("code_only_bm25")["strata"]["cross_plane"]
    assert cross["excludes_zero"] is False
    assert cross["ci95_low"] < 0 < cross["ci95_high"]

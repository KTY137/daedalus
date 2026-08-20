"""Slice 5 (watchdog mission): commuting squares — second-order holonomy.

Pre-registered expectations (TDD, written before the implementation):

A commuting square takes two CERTIFIED-DISJOINT invertible operators
forward and returns in SWAPPED order: word = [A, B, A^-1, B^-1] (the
natural unwind would be B^-1;A^-1 — swapping makes it a genuine
commutator). The control word is the sequential pair of roundtrips
[A, A^-1, B, B^-1], which contains the same four edits WITHOUT
interleaving. Second-order holonomy is the difference between square and
control endpoints: zero iff they end tree-identical.

First-order classification (against baseline, scheme as in loops.py)
depends only on where the scale roundtrip's numeric format loss lands
(pre-registered per fixture, measured in the campaign):
- values without trailing zeros in the scaled column and off-output:
  trivial (sensorlab, pumplab pressure squares);
- format loss in a column NOT printed by the pipeline: tree
  (chemlab reagent_b);
- format loss in a printed column: behavior with k_value 0.0
  (textlab score — label/format holonomy, value-equivalent).
Second-order holonomy is expected ZERO for all certified-disjoint pairs:
the commutator adds nothing beyond the component roundtrips.
"""
from pathlib import Path

import assay
import loops

ROOT = Path(__file__).resolve().parents[1]


def test_commuting_square_words():
    squares = loops.commuting_squares("textlab")
    assert len(squares) >= 1
    name, square, control = squares[0]
    assert len(square) == 4 and len(control) == 4
    # forward A;B, back in swapped order A^-1;B^-1
    assert square[0].name == control[0].name  # A
    assert square[1].name == control[2].name  # B
    assert square[2].name == control[1].name  # A^-1
    assert square[3].name == control[3].name  # B^-1
    # the two forward operators are certified disjoint
    import operators
    assert not operators.conflict(square[0], square[1])


def test_run_squares_textlab_behavior_channel(tmp_path):
    analysis = loops.run_squares(
        ROOT / "fixtures" / "textlab", tmp_path / "out", "textlab")
    sq = analysis["squares"][0]
    assert sq["composable"] is True
    assert sq["classification"] == "behavior"
    assert sq["k_value"] == 0.0
    assert sq["digest_equal"] is False
    assert sq["second_order"] == "zero"
    assert assay.verify_chain(
        tmp_path / "out" / "receipts.jsonl",
        expected_head=analysis["receipt_head"],
        expected_count=analysis["receipt_count"]) is True


def test_run_squares_sensorlab_tree_channel(tmp_path):
    # Correction to the initial pre-registration (recorded in SPEC): the
    # original prediction was "trivial", overlooking that sensorlab's
    # pressure column contains 101.0 — the roundtrip drops the trailing
    # zero ("101.0" -> "101"), so the tree differs while pressure stays
    # off-output: measured class is "tree", second order still zero.
    analysis = loops.run_squares(
        ROOT / "fixtures" / "sensorlab", tmp_path / "out", "sensorlab")
    sq = analysis["squares"][0]
    assert sq["composable"] is True
    assert sq["classification"] == "tree"
    assert sq["second_order"] == "zero"

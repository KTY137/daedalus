"""Slice 6 (watchdog mission): descent prototype — one check assay per
cover instead of all pairs.

Pre-registered expectations (TDD, written before the implementation):

Given a PARTITION of the schema fields (the cover), each operator is
assigned to the cell its declared footprint touches. Operators touching
several cells, the layout resource, wildcards or concept resources are
DESCENT OBSTRUCTIONS — recorded with a reason, never silently dropped.

For local operators the descent check replaces pairwise cross-cell
K-assays: ONE gluing assay per cover — the composite word applied
cell-by-cell versus the same operators interleaved round-robin across
cells. Tree-equal endpoints => the cover descends: all cross-cell pairs
of local ops are certified commuting by ONE measurement.

Balance accounting (the H-DESC economics): runs_used = baseline + one run
per non-empty cell + two gluing orders; runs_saved = 2 * (number of
cross-cell local pairs) that the pairwise matrix would have needed.

Expected on chemlab (scale/clip/tighten live in three distinct cells,
by construction of slice 2): descent holds (glue orders tree-identical),
obstructions = rename (layout write), add (layout read), regen
(field:* wildcard); saved pairs = 3 -> 6 pairwise runs replaced by the
descent check. The verdict must AGREE with the measured chemlab matrix
(runs/chemlab-20260821: every cross-cell pair commuted tree-identically).
"""
from pathlib import Path

import assay
import descent
import operators

ROOT = Path(__file__).resolve().parents[1]

CHEM_PARTITION = [
    ["reagent_a"],
    ["reagent_b"],
    ["catalyst"],
    ["sample_id"],
    ["temperature"],
]


def test_op_cell_assignment():
    ops = operators.standard_ops("chemlab")
    local, obstructions = descent.assign_ops(ops, CHEM_PARTITION)
    assert set(local) == {"scale", "clip", "tighten"}
    assert local["scale"] == 1 and local["clip"] == 2 and local["tighten"] == 3
    reasons = {name: reason for name, reason in obstructions}
    assert set(reasons) == {"rename", "add", "regen"}
    assert "layout" in reasons["rename"]
    assert "layout" in reasons["add"]
    assert "field:*" in reasons["regen"]


def test_run_descent_chemlab(tmp_path):
    ops = operators.standard_ops("chemlab")
    analysis = descent.run_descent(
        ROOT / "fixtures" / "chemlab", ops, CHEM_PARTITION, tmp_path / "out")
    assert analysis["descent_holds"] is True
    assert analysis["glue"]["tree_equal"] is True
    assert sorted(n for n, _ in analysis["obstructions"]) == ["add", "regen", "rename"]
    # economics: 3 cross-cell local pairs -> 6 pairwise runs replaced by
    # baseline + 3 cell runs + 2 glue runs
    assert analysis["balance"]["cross_cell_pairs"] == 3
    assert analysis["balance"]["pairwise_runs_replaced"] == 6
    assert analysis["balance"]["descent_runs_used"] == 1 + 3 + 2
    assert assay.verify_chain(
        tmp_path / "out" / "receipts.jsonl",
        expected_head=analysis["receipt_head"],
        expected_count=analysis["receipt_count"]) is True

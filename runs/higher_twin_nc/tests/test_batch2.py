"""Batch-2 tests: adversarial fixes + H-ANOM ground truth + loops + cryptic.

Pins the semantics demanded by the Momus/refuter round:
- receipts are fail-closed against accidental append,
- verify_chain keeps its bool contract and supports an external anchor,
- the evaluator rejects ragged CSV rows,
- measured footprints (files changed per op) land in the word result,
- the liar/honest operator pair gives the anomaly detector ground truth,
- K gains a continuous value-distance component,
- loop assays measure holonomy with positive and negative controls,
- the cryptic-variance pilot runs with its L=0 self test.
"""
import json
import shutil
from pathlib import Path

import pytest

import assay
import cryptic
import evaluate
import loops
import operators

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sensorlab"


def test_matrix_refuses_existing_receipts(tmp_path):
    (tmp_path / "receipts.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        assay.run_matrix(FIXTURE, operators.standard_ops(), tmp_path)


def test_verify_chain_returns_false_on_garbage(tmp_path):
    bad = tmp_path / "garbage.jsonl"
    bad.write_text("not json at all\n", encoding="utf-8")
    assert assay.verify_chain(bad) is False
    no_sha = tmp_path / "nosha.jsonl"
    no_sha.write_text('{"seq": 0, "prev": null}\n', encoding="utf-8")
    assert assay.verify_chain(no_sha) is False


def test_verify_chain_detects_truncation_with_anchor(tmp_path):
    path = tmp_path / "chain.jsonl"
    chain = assay.ReceiptChain(path)
    for i in range(3):
        chain.append({"record": "test", "i": i})
    assert assay.verify_chain(path, expected_head=chain.prev, expected_count=3) is True
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:2]), encoding="utf-8")
    assert assay.verify_chain(path, expected_head=chain.prev, expected_count=3) is False
    # documented limit: without an anchor, a valid prefix still verifies
    assert assay.verify_chain(path) is True


def test_schema_rejects_ragged_rows(tmp_path):
    tree = tmp_path / "tree"
    shutil.copytree(FIXTURE, tree)
    csv_path = tree / "data" / "events.csv"
    lines = csv_path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    lines[3] = ",".join(lines[3].split(",")[:2])
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    assert evaluate.evaluate_tree(tree)["schema_ok"] is False


def test_run_word_records_measured_footprint(tmp_path):
    ops = operators.standard_ops()
    res = assay.run_word(FIXTURE, [ops["scale"]], tmp_path / "w")
    assert res["composable"]
    applied = res["ops_applied"]
    assert len(applied) == 1
    assert applied[0]["files_changed"] == [
        "data/events.csv", "docs/fields.md", "schema.json",
    ]


def test_sham_measured_footprint_exposes_declaration_gap(tmp_path):
    res = assay.run_word(FIXTURE, [operators.sham()], tmp_path / "w")
    assert res["ops_applied"][0]["files_changed"] == ["calib.py"]
    assert operators.sham().writes == frozenset()


def test_liar_operator_triggers_anomaly(tmp_path):
    ops = {
        "liar": operators.normalize_by_pressure(honest=False),
        "scalep": operators.scale_values("pressure", 10.0, "daPa"),
    }
    res = assay.run_matrix(FIXTURE, ops, tmp_path)
    (pair,) = res["pairs"]
    assert pair["footprint_conflict"] is False
    assert pair["ab_composable"] and pair["ba_composable"]
    assert pair["behavior_equal"] is False
    assert pair["anomaly"] is True


def test_honest_twin_predicts_conflict_no_anomaly(tmp_path):
    ops = {
        "honest": operators.normalize_by_pressure(honest=True),
        "scalep": operators.scale_values("pressure", 10.0, "daPa"),
    }
    res = assay.run_matrix(FIXTURE, ops, tmp_path)
    (pair,) = res["pairs"]
    assert pair["footprint_conflict"] is True
    assert pair["anomaly"] is False


def test_anomaly_includes_asym_composability(tmp_path):
    probe = operators.Op(
        name="needs_humidity",
        reads=frozenset({"field:dew"}),
        writes=frozenset({"field:dew"}),
        pre=lambda tree: None if "humidity" in operators._schema_names(tree)
        else "field 'humidity' missing (undeclared read)",
        run=lambda tree: None,
    )
    ops = {"add": operators.add_field("humidity", "50.0", "number", "%"), "probe": probe}
    res = assay.run_matrix(FIXTURE, ops, tmp_path)
    (pair,) = res["pairs"]
    assert pair["footprint_conflict"] is False
    assert pair["classification"] == "noncomposable-asym"
    assert pair["anomaly"] is True


def test_k_value_separates_numeric_from_label_effects(tmp_path):
    ops = operators.standard_ops()
    scale_clip = assay.run_word(FIXTURE, [ops["scale"], ops["clip"]], tmp_path / "ab")
    clip_scale = assay.run_word(FIXTURE, [ops["clip"], ops["scale"]], tmp_path / "ba")
    k = assay.value_distance(scale_clip["Y"]["values"], clip_scale["Y"]["values"])
    assert k is not None and k > 0
    add_tighten = assay.run_word(FIXTURE, [ops["add"], ops["tighten"]], tmp_path / "cd")
    tighten_add = assay.run_word(FIXTURE, [ops["tighten"], ops["add"]], tmp_path / "dc")
    assert assay.value_distance(add_tighten["Y"]["values"], tighten_add["Y"]["values"]) == 0.0


def test_pairwise_certificates_inherit_to_depth3(tmp_path):
    ops = operators.standard_ops()
    triple = [ops["scale"], ops["tighten"], ops["add"]]
    for a, b in [(0, 1), (0, 2), (1, 2)]:
        assert operators.conflict(triple[a], triple[b]) is False
    shas = set()
    orders = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]
    for i, order in enumerate(orders):
        word = [triple[j] for j in order]
        res = assay.run_word(FIXTURE, word, tmp_path / f"p{i}")
        assert res["composable"], res["fail_reason"]
        shas.add(res["tree_sha"])
    assert len(shas) == 1


def test_rename_loop_is_trivial(tmp_path):
    res = loops.run_loops(FIXTURE, tmp_path)
    by_name = {l["name"]: l for l in res["loops"]}
    assert by_name["rename_roundtrip"]["classification"] == "trivial"


def test_scale_loop_has_format_holonomy_but_value_equivalence(tmp_path):
    res = loops.run_loops(FIXTURE, tmp_path)
    by_name = {l["name"]: l for l in res["loops"]}
    loop = by_name["scale_roundtrip"]
    assert loop["classification"] == "behavior"
    assert loop["k_value"] == 0.0


def test_cryptic_pilot_l0_selftest_and_neutrality(tmp_path):
    res = cryptic.run_pilot(FIXTURE, tmp_path)
    assert res["l0_ok"] is True
    lengths = sorted(w["L"] for w in res["walks"])
    assert lengths == [0, 2, 4]
    for walk in res["walks"]:
        assert walk["neutral_certified"] is True
        assert 0.0 <= walk["flip_rate"] <= 1.0

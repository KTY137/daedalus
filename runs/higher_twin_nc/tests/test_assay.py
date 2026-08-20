"""Tests for the higher-twin-nc-v1 intervention assay (A/B/AB/BA/Sham).

These tests pin the measurement semantics:
- Sham is a behavioral null (tree changes, behavior does not).
- Word execution is deterministic.
- Composability is asymmetric where preconditions are order-sensitive.
- Data-plane value transforms genuinely fail to commute behaviorally.
- Footprint-disjoint pairs must commute on trees (soundness of the
  commutation certificate) and anomalies flag hidden couplings.
- Receipts are hash-chained and verifiable.
"""
import shutil
from pathlib import Path

import pytest

import assay
import evaluate
import operators

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sensorlab"


def test_baseline_evaluates_clean(tmp_path):
    tree = tmp_path / "tree"
    shutil.copytree(FIXTURE, tree)
    y = evaluate.evaluate_tree(tree)
    assert y["parse_ok"] is True
    assert y["schema_ok"] is True
    assert y["docs_ok"] is True
    assert y["checks_total"] > 0
    assert y["checks_passed"] == y["checks_total"]
    assert len(y["digest"]) == 64


def test_sham_is_behavioral_null(tmp_path):
    base = assay.run_word(FIXTURE, [], tmp_path / "base")
    sham = assay.run_word(FIXTURE, [operators.sham()], tmp_path / "sham")
    assert base["composable"] and sham["composable"]
    assert sham["tree_sha"] != base["tree_sha"]
    assert sham["Y"] == base["Y"]


def test_word_run_is_deterministic(tmp_path):
    ops = operators.standard_ops()
    r1 = assay.run_word(FIXTURE, [ops["rename"]], tmp_path / "r1")
    r2 = assay.run_word(FIXTURE, [ops["rename"]], tmp_path / "r2")
    assert r1["composable"] and r2["composable"]
    assert r1["tree_sha"] == r2["tree_sha"]
    assert r1["Y"] == r2["Y"]


def test_rename_then_scale_is_noncomposable_but_reverse_composes(tmp_path):
    ops = operators.standard_ops()
    ab = assay.run_word(FIXTURE, [ops["rename"], ops["scale"]], tmp_path / "ab")
    ba = assay.run_word(FIXTURE, [ops["scale"], ops["rename"]], tmp_path / "ba")
    assert ab["composable"] is False
    assert "voltage" in ab["fail_reason"]
    assert ba["composable"] is True


def test_scale_and_clip_do_not_commute_behaviorally(tmp_path):
    ops = operators.standard_ops()
    ab = assay.run_word(FIXTURE, [ops["scale"], ops["clip"]], tmp_path / "ab")
    ba = assay.run_word(FIXTURE, [ops["clip"], ops["scale"]], tmp_path / "ba")
    assert ab["composable"] and ba["composable"]
    assert ab["Y"]["digest"] != ba["Y"]["digest"]


def test_add_and_tighten_commute_to_identical_trees(tmp_path):
    ops = operators.standard_ops()
    ab = assay.run_word(FIXTURE, [ops["add"], ops["tighten"]], tmp_path / "ab")
    ba = assay.run_word(FIXTURE, [ops["tighten"], ops["add"]], tmp_path / "ba")
    assert ab["composable"] and ba["composable"]
    assert ab["tree_sha"] == ba["tree_sha"]


def test_regen_docs_is_idempotent_on_pristine_tree(tmp_path):
    ops = operators.standard_ops()
    base = assay.run_word(FIXTURE, [], tmp_path / "base")
    regen = assay.run_word(FIXTURE, [ops["regen"]], tmp_path / "regen")
    assert regen["tree_sha"] == base["tree_sha"]


def test_footprint_conflict_is_bernstein():
    ops = operators.standard_ops()
    assert operators.conflict(ops["scale"], ops["clip"]) is True
    assert operators.conflict(ops["scale"], ops["tighten"]) is False
    assert operators.conflict(ops["rename"], ops["regen"]) is True
    assert operators.conflict(operators.sham(), ops["scale"]) is False


@pytest.fixture(scope="module")
def matrix(tmp_path_factory):
    out = tmp_path_factory.mktemp("matrix")
    return out, assay.run_matrix(FIXTURE, operators.standard_ops(), out)


def test_matrix_covers_all_pairs(matrix):
    _out, res = matrix
    assert len(res["pairs"]) == 15
    assert all(p["classification"] for p in res["pairs"])


def test_matrix_certificate_soundness(matrix):
    _out, res = matrix
    for pair in res["pairs"]:
        if not pair["footprint_conflict"] and pair["ab_composable"] and pair["ba_composable"]:
            assert pair["tree_equal"], f"certificate violated: {pair['pair']}"


def test_matrix_has_no_anomalies_on_clean_fixture(matrix):
    _out, res = matrix
    assert [p["pair"] for p in res["pairs"] if p["anomaly"]] == []


def test_matrix_receipts_chain_verifies(matrix):
    out, _res = matrix
    receipts = out / "receipts.jsonl"
    assert receipts.exists()
    assert assay.verify_chain(receipts) is True

"""Slice 2 (watchdog mission): fixture 3 `chemlab` — specificity fixture.

Pre-registered expectations (written BEFORE the fixture existed — TDD):

1. chemlab is purely additive-commutative: calibrated is a documented sum
   of independent field terms (reagent_a, reagent_b, catalyst) plus OFFSET.
   Every read of the pipeline is documented; there is NO hidden coupling.
   `temperature` is read by nothing (inert control).
2. The chemlab profile targets pairwise DISTINCT fields, so the standard
   matrix should produce the strongest possible null table: every pair
   composable in both orders, every pair tree-identical commuting, k = 0
   everywhere, zero anomalies, and more certified-disjoint pairs than the
   earlier fixtures (9 of 15).
3. This is the anomaly detector's specificity side: a fixture without
   coupling must not generate a single anomaly anywhere.
"""
import shutil
from pathlib import Path

import assay
import evaluate
import operators

ROOT = Path(__file__).resolve().parents[1]
CHEMLAB = ROOT / "fixtures" / "chemlab"


def _copy(tmp_path, name="tree"):
    tree = tmp_path / name
    shutil.copytree(CHEMLAB, tree, ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def test_chemlab_layout_and_baseline(tmp_path):
    for rel in ("README.md", "schema.json", "calib.py", "checks.py",
                "data/events.csv", "docs/fields.md"):
        assert (CHEMLAB / rel).is_file(), rel
    schema = operators._load_schema(CHEMLAB)
    assert [f["name"] for f in schema["fields"]] == [
        "sample_id", "reagent_a", "reagent_b", "catalyst", "temperature"]
    y = evaluate.evaluate_tree(_copy(tmp_path))
    assert y["parse_ok"] and y["schema_ok"] and y["docs_ok"]
    assert y["checks_total"] > 0 and y["checks_passed"] == y["checks_total"]
    assert len(y["values"]) == 12 and y["digest"]


def test_chemlab_docs_regen_is_idempotent():
    schema = operators._load_schema(CHEMLAB)
    docs = (CHEMLAB / "docs" / "fields.md").read_text(encoding="utf-8")
    assert operators.render_docs(schema) == docs


def test_chemlab_contract_is_complete(tmp_path):
    """No hidden coupling: every documented read is real, the inert field
    is really inert."""
    base = evaluate.evaluate_tree(_copy(tmp_path, "base"))
    b_tree = _copy(tmp_path, "b")
    operators.scale_values("reagent_b", 2.0, "mL").apply(b_tree)
    assert evaluate.evaluate_tree(b_tree)["values"] != base["values"], \
        "reagent_b is a documented read and must feed calibration"
    t_tree = _copy(tmp_path, "t")
    operators.scale_values("temperature", 10.0, "dC").apply(t_tree)
    assert evaluate.evaluate_tree(t_tree)["values"] == base["values"], \
        "temperature must be inert (no hidden coupling)"


def test_standard_ops_chemlab_profile(tmp_path):
    ops = operators.standard_ops("chemlab")
    assert ops["rename"].name == "rename_reagent_a_to_acid_a"
    assert ops["scale"].name == "scale_reagent_b_x1000"
    assert ops["clip"].name == "clip_catalyst_at25"
    assert ops["add"].name == "add_solvent"
    assert ops["tighten"].name == "tighten_sample_id_to_integer"
    for key, op in ops.items():
        tree = _copy(tmp_path, key)
        assert op.precondition(tree) is None, key
        op.apply(tree)
        y = evaluate.evaluate_tree(tree)
        assert y["parse_ok"] and y["schema_ok"] and y["docs_ok"], key
        assert y["checks_passed"] == y["checks_total"], key


def test_chemlab_null_table(tmp_path):
    """Distinct-field ops on an additive fixture: everything commutes."""
    ops = operators.standard_ops("chemlab")
    sub = {k: ops[k] for k in ("rename", "scale", "clip", "add")}
    analysis = assay.run_matrix(CHEMLAB, sub, tmp_path / "out")
    assert analysis["runs"] == 18
    assert analysis["sham"]["Y"] == analysis["baseline"]["Y"]
    for p in analysis["pairs"]:
        label = "+".join(p["pair"])
        assert p["ab_composable"] and p["ba_composable"], label
        assert p["tree_equal"] is True, label
        assert p["k_value"] == 0.0, label
        assert p["anomaly"] is False, label
        assert p["harness_alert"] is False, label
    # distinct-field targeting: only layout couples rename+add; scale+clip,
    # scale+add, clip+add, rename+scale, rename+clip are certified disjoint
    certified = {tuple(p["pair"]) for p in analysis["pairs"]
                 if p["certificate_predicted"]}
    assert certified == {("rename", "scale"), ("rename", "clip"),
                         ("scale", "clip"), ("scale", "add"), ("clip", "add")}
    assert assay.verify_analysis(tmp_path / "out") is True

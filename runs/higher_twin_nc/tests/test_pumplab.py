"""Slice 1 (watchdog mission): fixture 2 `pumplab` + profile-generic operators.

Pre-registered expectations (written BEFORE the fixture/ops existed — TDD):

1. pumplab has the same file structure as sensorlab, 5 schema fields, and a
   REAL hidden coupling in fixture code: `calib.py` reads the `pressure`
   column into the flow calibration (pressure correction). The documented
   contract (README, checks) presents calibration as a function of
   `flow_rate` alone.
2. `standard_ops(profile)` parameterizes the six standard operators by field
   names; the no-arg default stays the sensorlab pilot set (back-compat).
3. Non-circular H-ANOM validation: `retune_offset` is a realistic
   maintenance operator (re-baseline OFFSET from live pipeline output) whose
   INNOCENT declaration follows the documented contract (only the calibrated
   field's slice). The coupling lives in fixture code, not in the operator's
   self-report, so a detected anomaly validates coupling detection rather
   than declaration-diff mechanics:
   - retune + scale_pressure: declared disjoint, but order changes OFFSET
     -> ANOMALY expected (trees differ, Y differs, k_value > 0).
   - retune + scale_temperature: declared disjoint, temperature is NOT read
     by the pipeline -> commutes tree-identically, NO anomaly (specificity).
   - scale_pressure + scale_temperature: column-local edits commute
     tree-identically even though one column feeds the hidden coupling.
"""
import shutil
from pathlib import Path

import assay
import evaluate
import operators

ROOT = Path(__file__).resolve().parents[1]
PUMPLAB = ROOT / "fixtures" / "pumplab"


def _copy(tmp_path, name="tree"):
    tree = tmp_path / name
    shutil.copytree(PUMPLAB, tree, ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def test_pumplab_layout_and_baseline(tmp_path):
    for rel in ("README.md", "schema.json", "calib.py", "checks.py",
                "data/events.csv", "docs/fields.md"):
        assert (PUMPLAB / rel).is_file(), rel
    schema = operators._load_schema(PUMPLAB)
    assert len(schema["fields"]) == 5
    assert [f["name"] for f in schema["fields"]] == [
        "sample_id", "flow_rate", "pressure", "temperature", "rpm"]
    y = evaluate.evaluate_tree(_copy(tmp_path))
    assert y["parse_ok"] and y["schema_ok"] and y["docs_ok"]
    assert y["checks_total"] > 0 and y["checks_passed"] == y["checks_total"]
    assert len(y["values"]) == 12 and y["digest"]


def test_pumplab_docs_regen_is_idempotent():
    schema = operators._load_schema(PUMPLAB)
    docs = (PUMPLAB / "docs" / "fields.md").read_text(encoding="utf-8")
    assert operators.render_docs(schema) == docs


def test_coupling_ground_truth(tmp_path):
    """The hidden coupling is real: pressure feeds calibration, temperature
    does not. This is measured on the fixture itself, independent of any
    operator declaration."""
    base = evaluate.evaluate_tree(_copy(tmp_path, "base"))
    p_tree = _copy(tmp_path, "p")
    operators.scale_values("pressure", 1.25, "kPa").apply(p_tree)
    y_p = evaluate.evaluate_tree(p_tree)
    assert y_p["values"] != base["values"], "pressure must feed calibration"
    t_tree = _copy(tmp_path, "t")
    operators.scale_values("temperature", 10.0, "dC").apply(t_tree)
    y_t = evaluate.evaluate_tree(t_tree)
    assert y_t["values"] == base["values"], "temperature must NOT feed calibration"


def test_standard_ops_default_profile_unchanged():
    ops = operators.standard_ops()
    assert list(ops) == ["rename", "scale", "clip", "add", "tighten", "regen"]
    assert ops["rename"].name == "rename_voltage_to_bias_voltage"
    assert ops["scale"].name == "scale_voltage_x1000"
    assert ops["tighten"].name == "tighten_sample_id_to_integer"


def test_standard_ops_pumplab_profile(tmp_path):
    ops = operators.standard_ops("pumplab")
    assert list(ops) == ["rename", "scale", "clip", "add", "tighten", "regen"]
    assert ops["rename"].name == "rename_flow_rate_to_mass_flow"
    assert ops["scale"].name == "scale_flow_rate_x2"
    assert ops["clip"].name == "clip_flow_rate_at6"
    assert ops["add"].name == "add_viscosity"
    assert ops["tighten"].name == "tighten_pressure_to_integer"
    # every single op is composable on the pumplab tree
    for key, op in ops.items():
        tree = _copy(tmp_path, key)
        assert op.precondition(tree) is None, key
        op.apply(tree)
        y = evaluate.evaluate_tree(tree)
        assert y["parse_ok"] and y["schema_ok"] and y["docs_ok"], key
        assert y["checks_passed"] == y["checks_total"], key


def test_retune_offset_innocent_and_deterministic(tmp_path):
    op = operators.retune_offset("flow_rate", target=10.0)
    # innocent declaration: only the documented slice, disjoint from pressure
    assert op.reads == frozenset({"field:flow_rate"})
    assert op.writes == frozenset({"field:flow_rate"})
    assert not operators.conflict(op, operators.scale_values("pressure", 1.25, "kPa"))
    a = _copy(tmp_path, "a")
    assert op.precondition(a) is None
    before = (a / "calib.py").read_text(encoding="utf-8")
    op.apply(a)
    after = (a / "calib.py").read_text(encoding="utf-8")
    assert before != after and "OFFSET = " in after
    # deterministic: same base tree -> byte-identical result
    b = _copy(tmp_path, "b")
    op.apply(b)
    assert (b / "calib.py").read_bytes() == (a / "calib.py").read_bytes()
    # the retuned tree really has mean calibrated == target
    y = evaluate.evaluate_tree(a)
    assert y["checks_passed"] == y["checks_total"]
    mean = sum(y["values"]) / len(y["values"])
    assert abs(mean - 10.0) < 1e-4


def test_retune_detects_fixture_code_coupling(tmp_path):
    ops = {
        "retune": operators.retune_offset("flow_rate", target=10.0),
        "scalep": operators.scale_values("pressure", 1.25, "kPa"),
        "scalet": operators.scale_values("temperature", 10.0, "dC"),
    }
    analysis = assay.run_matrix(PUMPLAB, ops, tmp_path / "out")
    pairs = {tuple(p["pair"]): p for p in analysis["pairs"]}
    hit = pairs[("retune", "scalep")]
    assert hit["certificate_predicted"] is True
    assert hit["anomaly"] is True
    assert hit["tree_equal"] is False
    assert hit["k_value"] is not None and hit["k_value"] > 0
    spec = pairs[("retune", "scalet")]
    assert spec["certificate_predicted"] is True
    assert spec["anomaly"] is False
    assert spec["tree_equal"] is True
    ctrl = pairs[("scalep", "scalet")]
    assert ctrl["anomaly"] is False and ctrl["tree_equal"] is True
    assert assay.verify_analysis(tmp_path / "out") is True

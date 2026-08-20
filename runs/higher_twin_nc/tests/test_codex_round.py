"""Fixes demanded by the Codex falsifier round (council-20260820T173055Z).

Each test pins one accepted finding; the council bus is the provenance.
"""
import json
import shutil
from pathlib import Path

import pytest

import assay
import cryptic
import evaluate
import operators

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sensorlab"


def _copy_fixture(tmp_path, name="tree"):
    tree = tmp_path / name
    shutil.copytree(FIXTURE, tree, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return tree


def test_checks_crash_with_stale_line_yields_zero(tmp_path):
    tree = _copy_fixture(tmp_path)
    (tree / "checks.py").write_text(
        'print("CHECKS 9/1")\nraise SystemExit(7)\n',
        encoding="utf-8", newline="\n",
    )
    y = evaluate.evaluate_tree(tree)
    assert (y["checks_passed"], y["checks_total"]) == (0, 0)


def test_nonzero_exit_digest_includes_stdout(tmp_path):
    a = _copy_fixture(tmp_path, "a")
    b = _copy_fixture(tmp_path, "b")
    (a / "calib.py").write_text('print("alpha")\nraise SystemExit(3)\n', encoding="utf-8", newline="\n")
    (b / "calib.py").write_text('print("beta")\nraise SystemExit(3)\n', encoding="utf-8", newline="\n")
    ya, yb = evaluate.evaluate_tree(a), evaluate.evaluate_tree(b)
    assert ya["digest"] != yb["digest"]


def test_nonfinite_values_are_json_safe_and_stable(tmp_path):
    tree = _copy_fixture(tmp_path)
    (tree / "calib.py").write_text(
        'print("sample_id voltage calibrated")\nprint("1.0 2.0 nan")\n',
        encoding="utf-8", newline="\n",
    )
    y1 = evaluate.evaluate_tree(tree)
    y2 = evaluate.evaluate_tree(tree)
    json.dumps(y1)  # must not raise / must not smuggle NaN into JSON
    assert y1 == y2


def test_duplicate_csv_header_rejected(tmp_path):
    tree = _copy_fixture(tmp_path)
    csv_path = tree / "data" / "events.csv"
    lines = csv_path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    lines[0] = "sample_id,voltage,voltage"
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    assert evaluate.evaluate_tree(tree)["schema_ok"] is False


def test_hash_tree_sees_empty_directories(tmp_path):
    a = _copy_fixture(tmp_path, "a")
    b = _copy_fixture(tmp_path, "b")
    (b / "emptydir").mkdir()
    assert assay.hash_tree(a) != assay.hash_tree(b)


def test_digest_independent_of_workdir_label(tmp_path):
    src = _copy_fixture(tmp_path, "src")
    with open(src / "calib.py", "a", encoding="utf-8", newline="\n") as fh:
        fh.write("import pathlib\nprint(pathlib.Path.cwd().name)\n")
    r1 = assay.run_word(src, [], tmp_path / "label_one")
    r2 = assay.run_word(src, [], tmp_path / "label_two")
    assert r1["Y"]["digest"] == r2["Y"]["digest"]


def test_mutating_precondition_is_recorded(tmp_path):
    def bad_pre(tree):
        path = tree / "calib.py"
        path.write_text(path.read_text(encoding="utf-8") + "# side effect\n",
                        encoding="utf-8", newline="\n")
        return "refusing after mutation"

    op = operators.Op(
        name="mutating_pre", reads=frozenset(), writes=frozenset(),
        pre=bad_pre, run=lambda tree: None,
    )
    res = assay.run_word(FIXTURE, [op], tmp_path / "w")
    assert res["composable"] is False
    assert res["precondition_mutations"] == ["calib.py"]


def test_exception_after_mutation_records_footprint(tmp_path):
    def boom(tree):
        path = tree / "schema.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8", newline="\n")
        raise RuntimeError("boom")

    op = operators.Op(
        name="mutate_then_raise", reads=frozenset(), writes=frozenset(),
        pre=lambda tree: None, run=boom,
    )
    res = assay.run_word(FIXTURE, [op], tmp_path / "w")
    assert res["composable"] is False
    assert res["ops_applied"][-1]["failed"] is True
    assert res["ops_applied"][-1]["files_changed"] == ["schema.json"]


def test_tree_equal_pair_is_harness_alert_not_anomaly(tmp_path):
    noop_a = operators.Op(name="noop_a", reads=frozenset({"field:x"}),
                          writes=frozenset({"field:x"}),
                          pre=lambda t: None, run=lambda t: None)
    noop_b = operators.Op(name="noop_b", reads=frozenset({"field:y"}),
                          writes=frozenset({"field:y"}),
                          pre=lambda t: None, run=lambda t: None)
    res = assay.run_matrix(FIXTURE, {"a": noop_a, "b": noop_b}, tmp_path)
    (pair,) = res["pairs"]
    assert pair["tree_equal"] is True
    assert pair["anomaly"] is False
    assert pair["harness_alert"] is False


def test_evaluate_timeout_is_deterministic_failure(tmp_path, monkeypatch):
    tree = _copy_fixture(tmp_path)
    (tree / "calib.py").write_text(
        "import time\ntime.sleep(5)\nprint('late')\n",
        encoding="utf-8", newline="\n",
    )
    monkeypatch.setattr(evaluate, "TIMEOUT_S", 1)
    y = evaluate.evaluate_tree(tree)
    assert y["digest"].startswith("TIMEOUT")


def test_matrix_chain_starts_with_provenance_and_ends_with_analysis(tmp_path):
    noop = operators.Op(name="noop", reads=frozenset(), writes=frozenset(),
                        pre=lambda t: None, run=lambda t: None)
    assay.run_matrix(FIXTURE, {"a": noop}, tmp_path)
    records = [json.loads(line) for line in
               (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["record"] == "provenance"
    assert len(records[0]["code_sha"]) == 64
    assert records[-1]["record"] == "analysis"
    assert assay.verify_analysis(tmp_path) is True


def test_tampered_kmatrix_fails_analysis_verification(tmp_path):
    noop = operators.Op(name="noop", reads=frozenset(), writes=frozenset(),
                        pre=lambda t: None, run=lambda t: None)
    assay.run_matrix(FIXTURE, {"a": noop}, tmp_path)
    kmatrix_path = tmp_path / "kmatrix.json"
    data = json.loads(kmatrix_path.read_text(encoding="utf-8"))
    data["runs"] = 999
    kmatrix_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    assert assay.verify_analysis(tmp_path) is False


def test_neutral_edit_refuses_missing_target(tmp_path):
    tree = _copy_fixture(tmp_path)
    (tree / "calib.py").write_text("print('no imports here')\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        cryptic.n3_import_reorder(tree)

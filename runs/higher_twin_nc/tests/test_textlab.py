"""Slice 3 (watchdog mission): fixture 4 `textlab` — footprint completeness
stressor.

Pre-registered expectations (written BEFORE fixture/ops existed — TDD):

textlab is knowledge-heavy: the interesting operators edit `docs/fields.md`.
Two new operator families extend the footprint vocabulary's blind spots on
purpose:

- `annotate_field(name, note)`: inserts a note line into one field's doc
  section; declared rw on that field slice (sound: sections are disjoint
  regions).
- `add_appendix(topic, text)`: appends a non-field knowledge section at the
  file tail; declared write on `concept:<topic>` — a resource OUTSIDE the
  field vocabulary. The `field:*` wildcard of regen_docs does NOT intersect
  `concept:*`.

Predicted certificate UNSOUNDNESS (the stressor — measured, not assumed):
1. appendix + appendix: declared disjoint (different concepts), but both
   append to the same file tail -> order changes bytes: tree_equal False,
   behavior_equal True, classification "commute-behavior", anomaly False.
2. appendix + regen_docs: declared disjoint (wildcard misses concept:*),
   but regen regenerates the file from schema and DROPS appendices ->
   tree_equal False, behavior_equal True.
Adjudication per H-CERT rule: the measured footprint (files_changed shows
both ops wrote the same file) deviates from the declaration -> counts as
misdeclaration / vocabulary incompleteness, not as an H-CERT kill.

Predicted soundness where declarations are honest:
3. annotate(score) + appendix: disjoint regions -> commute-tree.
4. annotate(score) + annotate(weight): different sections -> commute-tree.
5. annotate + regen: declared CONFLICT (wildcard) and truly noncommuting
   (regen wipes notes) -> true positive of the footprint rule.
No behavioral order effect anywhere: 0 anomalies, 0 harness alerts.
"""
import shutil
from pathlib import Path

import assay
import evaluate
import operators

ROOT = Path(__file__).resolve().parents[1]
TEXTLAB = ROOT / "fixtures" / "textlab"


def _copy(tmp_path, name="tree"):
    tree = tmp_path / name
    shutil.copytree(TEXTLAB, tree, ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def test_textlab_layout_and_baseline(tmp_path):
    for rel in ("README.md", "schema.json", "calib.py", "checks.py",
                "data/events.csv", "docs/fields.md"):
        assert (TEXTLAB / rel).is_file(), rel
    schema = operators._load_schema(TEXTLAB)
    assert [f["name"] for f in schema["fields"]] == ["sample_id", "score", "weight"]
    y = evaluate.evaluate_tree(_copy(tmp_path))
    assert y["parse_ok"] and y["schema_ok"] and y["docs_ok"]
    assert y["checks_total"] > 0 and y["checks_passed"] == y["checks_total"]
    assert len(y["values"]) == 12 and y["digest"]
    docs = (TEXTLAB / "docs" / "fields.md").read_text(encoding="utf-8")
    assert operators.render_docs(schema) == docs


def test_annotate_field_is_section_scoped(tmp_path):
    tree = _copy(tmp_path)
    op = operators.annotate_field("score", "reviewed 2026-08-21")
    assert op.reads == frozenset({"field:score"})
    assert op.writes == frozenset({"field:score"})
    assert op.precondition(tree) is None
    op.apply(tree)
    text = (tree / "docs" / "fields.md").read_text(encoding="utf-8")
    assert "Note: reviewed 2026-08-21." in text
    # the note lands inside the score section, not at the file tail
    score_at = text.index("## `score`")
    weight_at = text.index("## `weight`")
    assert score_at < text.index("Note: reviewed 2026-08-21.") < weight_at
    assert evaluate.evaluate_tree(tree)["docs_ok"] is True


def test_add_appendix_appends_concept_section(tmp_path):
    tree = _copy(tmp_path)
    op = operators.add_appendix("units", "All units are SI-derived.")
    assert op.writes == frozenset({"concept:units"})
    assert op.precondition(tree) is None
    op.apply(tree)
    text = (tree / "docs" / "fields.md").read_text(encoding="utf-8")
    assert text.rstrip().endswith("All units are SI-derived.")
    assert "## Appendix: units" in text
    assert evaluate.evaluate_tree(tree)["docs_ok"] is True
    # idempotence guard: the same appendix cannot be added twice
    assert op.precondition(tree) is not None
    # the wildcard does not reach concept resources
    assert not operators.conflict(op, operators.regen_docs())


def test_textlab_footprint_stress_matrix(tmp_path):
    ops = {
        "ann_s": operators.annotate_field("score", "reviewed"),
        "app_u": operators.add_appendix("units", "All units are SI-derived."),
        "app_h": operators.add_appendix("history", "Schema v1 from legacy lab notes."),
        "regen": operators.regen_docs(),
    }
    analysis = assay.run_matrix(TEXTLAB, ops, tmp_path / "out")
    assert analysis["runs"] == 18
    pairs = {tuple(p["pair"]): p for p in analysis["pairs"]}

    def violated(p):
        return (p["certificate_predicted"] and not p["tree_equal"]
                and p["behavior_equal"] and p["classification"] == "commute-behavior")

    # measured unsoundness: tail appends and wildcard-escaping concepts
    assert violated(pairs[("app_u", "app_h")])
    assert violated(pairs[("app_u", "regen")])
    assert violated(pairs[("app_h", "regen")])
    # honest declarations stay sound
    held = pairs[("ann_s", "app_u")]
    assert held["certificate_predicted"] and held["tree_equal"]
    held2 = pairs[("ann_s", "app_h")]
    assert held2["certificate_predicted"] and held2["tree_equal"]
    # true positive: wildcard conflict, really noncommuting (notes wiped)
    tp = pairs[("ann_s", "regen")]
    assert tp["footprint_conflict"] and not tp["tree_equal"] and tp["behavior_equal"]
    # no behavioral order effects at all
    for p in analysis["pairs"]:
        assert p["ab_composable"] and p["ba_composable"], p["pair"]
        assert p["anomaly"] is False, p["pair"]
        assert p["harness_alert"] is False, p["pair"]
        assert p["behavior_equal"] is True, p["pair"]
    assert assay.verify_analysis(tmp_path / "out") is True

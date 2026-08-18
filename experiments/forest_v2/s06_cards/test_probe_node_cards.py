"""EXPERIMENT s06 tests: the stand-in extractor and the probe, on a synthetic tree.

Every assertion here runs against a tree this file builds, so the numbers are
checkable without depending on the repository's current shape.

Run directly:  python -m pytest experiments/forest_v2/s06_cards/test_probe_node_cards.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import node_cards as nc  # noqa: E402
import probe_node_cards as probe_mod  # noqa: E402
import standin_source as src  # noqa: E402

CODE = '''"""Module doc."""
import json


def top_level(value):
    """Top level."""
    return value


class Widget(Base):
    """A widget."""

    def method_a(self):
        return 1

    def method_b(self):
        return 2
'''

NOTE = """# Title

Intro prose with a [link](other.md).

## First section

Body of the first section.

### Nested

Deeper body.

## Second section

More body.
"""


def build_tree(root: Path) -> Path:
    package = root / "daedalus"
    package.mkdir(parents=True)
    (package / "widget.py").write_text(CODE, encoding="utf-8")
    knowledge = root / "docs"
    knowledge.mkdir(parents=True)
    (knowledge / "note.md").write_text(NOTE, encoding="utf-8")
    return root


# --- code plane extraction -------------------------------------------------


def test_code_records_cover_module_class_function_and_method(tmp_path):
    build_tree(tmp_path)
    records = src.code_records(tmp_path, tmp_path / "daedalus" / "widget.py")
    kinds = sorted(r["kind"] for r in records)
    assert kinds == ["class", "function", "method", "method", "module"]
    quals = {r["qualname"] for r in records}
    assert "daedalus.widget.Widget.method_a" in quals
    assert "daedalus.widget" in quals


def test_module_record_links_children_and_imports(tmp_path):
    build_tree(tmp_path)
    records = src.code_records(tmp_path, tmp_path / "daedalus" / "widget.py")
    module = next(r for r in records if r["kind"] == "module")
    relations = {n["relation"] for n in module["neighbors"]}
    assert {"contains", "imports"} <= relations
    assert any(n["name"] == "json" for n in module["neighbors"])


def test_class_record_records_its_base(tmp_path):
    build_tree(tmp_path)
    records = src.code_records(tmp_path, tmp_path / "daedalus" / "widget.py")
    widget = next(r for r in records if r["kind"] == "class")
    bases = [n["name"] for n in widget["neighbors"] if n["relation"] == "derives_from"]
    assert bases == ["Base"]


def test_locator_lines_bracket_the_real_source(tmp_path):
    build_tree(tmp_path)
    records = src.code_records(tmp_path, tmp_path / "daedalus" / "widget.py")
    method = next(r for r in records if r["qualname"].endswith("method_a"))
    assert method["text"].strip().startswith("def method_a")
    assert method["start_line"] < method["end_line"]


def test_an_unparseable_file_is_skipped_not_fatal(tmp_path):
    package = tmp_path / "daedalus"
    package.mkdir(parents=True)
    broken = package / "broken.py"
    broken.write_text("def (\n", encoding="utf-8")
    assert src.code_records(tmp_path, broken) == []


# --- knowledge plane extraction --------------------------------------------


def test_knowledge_records_nest_section_qualnames(tmp_path):
    build_tree(tmp_path)
    records = src.knowledge_records(tmp_path, tmp_path / "docs" / "note.md")
    quals = {r["qualname"] for r in records}
    assert "note/Title/First section/Nested" in quals
    assert any(r["kind"] == "document" for r in records)


def test_knowledge_sections_carry_their_links(tmp_path):
    build_tree(tmp_path)
    records = src.knowledge_records(tmp_path, tmp_path / "docs" / "note.md")
    title = next(r for r in records if r["qualname"] == "note/Title")
    links = [n["name"] for n in title["neighbors"] if n["relation"] == "links_to"]
    assert links == ["other.md"]


# --- probe -----------------------------------------------------------------


def test_probe_builds_valid_cards_for_both_planes(tmp_path):
    build_tree(tmp_path)
    report = probe_mod.probe(tmp_path)
    assert report["totals"]["contract_violations"] == 0
    assert report["totals"]["records_rejected"] == 0
    assert report["cards_by_plane"]["code"] == 5
    assert report["cards_by_plane"]["knowledge"] == 5  # 4 headings + document


def test_probe_reports_unique_node_ids(tmp_path):
    build_tree(tmp_path)
    totals = probe_mod.probe(tmp_path)["totals"]
    assert totals["duplicate_node_ids"] == 0
    assert totals["distinct_node_ids"] == totals["cards"]


def test_probe_is_deterministic(tmp_path):
    build_tree(tmp_path)
    assert probe_mod.probe(tmp_path) == probe_mod.probe(tmp_path)


def test_a_smaller_content_budget_makes_smaller_cards(tmp_path):
    build_tree(tmp_path)
    wide = probe_mod.probe(tmp_path, content_budget=4000)
    narrow = probe_mod.probe(tmp_path, content_budget=64)
    assert narrow["size_all_planes"]["bytes_total"] < wide["size_all_planes"]["bytes_total"]
    assert narrow["totals"]["content_truncated"] >= wide["totals"]["content_truncated"]


def test_envelope_bytes_is_the_measured_metadata_floor(tmp_path):
    build_tree(tmp_path)
    report = probe_mod.probe(tmp_path)
    assert 0 < report["totals"]["envelope_bytes"] <= report["size_all_planes"]["bytes_min"]


def test_probe_reports_an_unresolvable_revision_as_unknown(tmp_path):
    build_tree(tmp_path)
    assert probe_mod.probe(tmp_path)["revision"] == "unknown"


def test_cards_from_the_probe_pass_the_card_validator(tmp_path):
    build_tree(tmp_path)
    revision = src.resolve_revision(tmp_path)
    provenance = {"source": "standin_ast_extractor", "extractor_version": "1"}
    for record in src.iter_records(tmp_path):
        card = nc.build_card(record, revision=revision or "unknown", provenance=provenance)
        assert nc.validate_card(card) == []


def test_main_prints_one_json_object(tmp_path, capsys):
    build_tree(tmp_path)
    assert probe_mod.main([str(tmp_path)]) == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "forest-v2-node-card-probe/1"
    assert payload["read_only"] is True

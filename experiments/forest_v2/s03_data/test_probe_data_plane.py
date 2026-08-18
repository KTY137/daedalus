"""Tests for the s03 data-plane extraction probe.

Run directly:  python -m pytest experiments/forest_v2/s03_data/ -q

Every fixture here is synthetic and inline.  No repository fixture is
mutated, nothing is written, and the one repository-level test asserts
structural invariants only (never a frozen count), so the tests do not rot
when the tree moves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_data_plane as dp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


# --- DDL parsing ------------------------------------------------------------
def test_split_top_level_keeps_nested_parens_together():
    body = "a INTEGER, b VARCHAR(10) NOT NULL, CHECK(x = 1 AND y IN (1, 2)), c TEXT"
    parts = dp._split_top_level(body)
    assert parts == [
        "a INTEGER",
        "b VARCHAR(10) NOT NULL",
        "CHECK(x = 1 AND y IN (1, 2))",
        "c TEXT",
    ]


def test_declared_type_stops_at_constraint_keywords():
    assert dp._declared_type("TEXT PRIMARY KEY") == "TEXT"
    assert dp._declared_type("TEXT NOT NULL PRIMARY KEY") == "TEXT"
    assert dp._declared_type("INTEGER PRIMARY KEY AUTOINCREMENT") == "INTEGER"
    assert dp._declared_type("VARCHAR(10) NOT NULL") == "VARCHAR(10)"
    assert dp._declared_type("UNSIGNED BIG INT") == "UNSIGNED BIG INT"
    assert dp._declared_type("PRIMARY KEY") is None
    assert dp._declared_type("") is None


IMPLICIT_CONCAT_SOURCE = '''
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS intents ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " kind TEXT NOT NULL,"
    " payload TEXT)",
)
'''


def test_implicit_concatenation_is_folded_and_columns_recovered():
    nodes, edges, indexes = dp.extract_sqlite(IMPLICIT_CONCAT_SOURCE, "pkg/mod.py")
    assert len(nodes) == 1
    node = nodes[0]
    assert node.name == "intents"
    assert node.kind == "sqlite.table"
    assert node.complete is True
    assert [f.name for f in node.fields] == ["id", "kind", "payload"]
    assert [f.declared_type for f in node.fields] == ["INTEGER", "TEXT", "TEXT"]
    assert "primary_key" in node.fields[0].flags
    assert "not_null" in node.fields[1].flags
    assert node.fields[2].flags == ()
    assert edges == [] and indexes == 0


def test_field_locators_point_at_the_declaring_line():
    nodes, _, _ = dp.extract_sqlite(IMPLICIT_CONCAT_SOURCE, "pkg/mod.py")
    lines = IMPLICIT_CONCAT_SOURCE.splitlines()
    for item in nodes[0].fields:
        assert item.locator.startswith("pkg/mod.py#L")
        lineno = int(item.locator.rsplit("#L", 1)[1])
        assert item.name in lines[lineno - 1]


def test_naive_one_line_baseline_misses_what_ast_folding_recovers():
    seen, complete = dp.naive_sqlite_baseline(IMPLICIT_CONCAT_SOURCE)
    nodes, _, _ = dp.extract_sqlite(IMPLICIT_CONCAT_SOURCE, "pkg/mod.py")
    assert seen == 1  # the regex sees the statement head
    assert complete == 0  # but never a complete body on one raw line
    assert len(nodes[0].fields) == 3  # AST folding recovers all of it


def test_docstring_mention_is_not_a_table():
    source = '''
def migrate():
    """When the table is absent this is a no-op and ``CREATE TABLE`` runs."""
    return None
'''
    nodes, _, _ = dp.extract_sqlite(source, "pkg/mod.py")
    assert nodes == []


def test_foreign_key_and_references_produce_edges():
    source = '''
SQL = """
CREATE TABLE intent_events (
    id INTEGER PRIMARY KEY,
    intent_id INTEGER NOT NULL REFERENCES intents(id),
    state TEXT NOT NULL,
    FOREIGN KEY (state) REFERENCES states(name)
)
"""
'''
    nodes, edges, _ = dp.extract_sqlite(source, "pkg/mod.py")
    assert [f.name for f in nodes[0].fields] == ["id", "intent_id", "state"]
    assert "references" in nodes[0].fields[1].flags
    targets = sorted(edge.dst for edge in edges)
    assert targets == ["intents.id", "states.name"]
    assert all(edge.kind == "sqlite.foreign_key" for edge in edges)


def test_temp_table_and_index_statements_are_seen():
    source = 'SQL = "CREATE TEMP TABLE IF NOT EXISTS live (key TEXT PRIMARY KEY)"\n'
    nodes, _, _ = dp.extract_sqlite(source, "pkg/mod.py")
    assert nodes[0].name == "live"
    source_with_index = (
        'SQL = "CREATE TABLE t (a TEXT); CREATE UNIQUE INDEX ix ON t(a)"\n'
    )
    _, _, indexes = dp.extract_sqlite(source_with_index, "pkg/mod.py")
    assert indexes == 1


def test_fstring_ddl_is_marked_incomplete():
    source = 'SQL = f"CREATE TABLE {name} (a TEXT)"\n'
    nodes, _, _ = dp.extract_sqlite(source, "pkg/mod.py")
    assert nodes == [] or "f_string_partial" in nodes[0].notes


def test_predicate_fragment_without_body_is_flagged_not_invented():
    source = 'PREDICATE = "CREATE TABLE IF NOT EXISTS provider_bindings"\n'
    nodes, _, _ = dp.extract_sqlite(source, "pkg/mod.py")
    assert len(nodes) == 1
    assert nodes[0].complete is False
    assert nodes[0].fields == []
    assert "no_balanced_body" in nodes[0].notes


# --- JSON Schema ------------------------------------------------------------
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Sample",
    "type": "object",
    "required": ["id"],
    "properties": {
        "id": {"$ref": "#/$defs/identifier"},
        "count": {"type": "integer"},
        "either": {"type": ["string", "null"]},
        "undeclared": {"description": "no type here"},
    },
    "$defs": {
        "identifier": {"type": "string", "pattern": "^[a-z]+$"},
        "nested": {
            "type": "object",
            "required": ["inner"],
            "properties": {"inner": {"type": "boolean"}},
        },
    },
}


def test_json_schema_root_and_defs_become_nodes():
    nodes, edges = dp.extract_json_schema(SCHEMA, "configs/schemas/x.schema.json")
    kinds = [node.kind for node in nodes]
    assert kinds == ["json.schema", "json.schema.def", "json.schema.def"]
    root = nodes[0]
    assert root.name == "Sample"
    assert root.locator == "configs/schemas/x.schema.json#/"
    names = {item.name: item for item in root.fields}
    assert names["id"].flags == ("required",)
    assert names["count"].flags == ("optional",)
    assert names["count"].declared_type == "integer"
    assert names["either"].declared_type == "string|null"
    assert names["undeclared"].declared_type is None
    assert names["id"].declared_type == "$ref:#/$defs/identifier"
    assert names["count"].locator == (
        "configs/schemas/x.schema.json#/properties/count"
    )
    scalar_def, record_def = nodes[1], nodes[2]
    assert scalar_def.fields == []  # a scalar type declaration, not a record
    assert [item.name for item in record_def.fields] == ["inner"]
    assert record_def.locator == "configs/schemas/x.schema.json#/$defs/nested"
    assert record_def.fields[0].locator.endswith("#/$defs/nested/properties/inner")
    assert [edge.dst for edge in edges] == ["#/$defs/identifier"]
    assert edges[0].kind == "json.ref"


def test_non_schema_document_yields_no_nodes():
    nodes, edges = dp.extract_json_schema({"a": 1, "b": [2]}, "daedalus/eval/x.json")
    assert nodes == [] and edges == []
    assert dp._is_schema([1, 2, 3]) is False


# --- CSV --------------------------------------------------------------------
def test_csv_header_becomes_fields_with_inferred_types():
    text = "id,voltage,label,blank\n1,125.0,alpha,\n2,126.5,beta,\n"
    nodes = dp.extract_csv(text, "tests/fixtures/x/data/events.csv")
    node = nodes[0]
    assert node.kind == "csv.table"
    assert node.locator == "tests/fixtures/x/data/events.csv#L1"
    assert [item.name for item in node.fields] == ["id", "voltage", "label", "blank"]
    assert [item.declared_type for item in node.fields] == [
        "integer",
        "number",
        "string",
        None,
    ]
    assert node.fields[0].type_source == "inferred"
    assert node.fields[3].type_source == "none"
    assert node.fields[1].locator.endswith("#L1C2")
    assert node.notes == ("sampled_rows=2",)


def test_empty_csv_yields_no_node():
    assert dp.extract_csv("", "x.csv") == []


# --- binding and consistency ------------------------------------------------
def _csv_node(text: str) -> dp.DataNode:
    return dp.extract_csv(text, "data/events.csv")[0]


def test_binding_verifies_only_subset_with_compatible_types():
    schema_nodes, _ = dp.extract_json_schema(
        {
            "$schema": "s",
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}, "voltage": {"type": "number"}},
        },
        "schemas/event.schema.json",
    )
    good = dp.bind_csv_to_schema([_csv_node("id,voltage\na,1.5\n")], schema_nodes)
    assert len(good) == 1 and good[0]["verified"] is True
    assert good[0]["overlap"] == 2 and good[0]["header_is_subset"] is True

    mismatch = dp.bind_csv_to_schema([_csv_node("id,voltage\na,b\n")], schema_nodes)
    assert mismatch[0]["verified"] is False
    assert mismatch[0]["type_mismatches"] == ["voltage: csv=string schema=number"]

    extra = dp.bind_csv_to_schema([_csv_node("id,voltage,extra\na,1.5,x\n")], schema_nodes)
    assert extra[0]["header_is_subset"] is False
    assert extra[0]["verified"] is False

    assert dp.bind_csv_to_schema([_csv_node("other\n1\n")], schema_nodes) == []


def test_duplicate_declarations_separate_names_types_and_flags():
    first, _, _ = dp.extract_sqlite(
        'SQL = "CREATE TABLE t (a TEXT PRIMARY KEY, b TEXT NOT NULL)"\n', "one.py"
    )
    second, _, _ = dp.extract_sqlite(
        'SQL = "CREATE TABLE t (a TEXT NOT NULL PRIMARY KEY, b TEXT NOT NULL)"\n',
        "two.py",
    )
    third, _, _ = dp.extract_sqlite(
        'SQL = "CREATE TABLE t (a INTEGER PRIMARY KEY, c TEXT)"\n', "three.py"
    )
    flags_only = dp.duplicate_declarations(first + second)
    assert len(flags_only) == 1
    assert flags_only[0]["column_names_agree"] is True
    assert flags_only[0]["column_types_agree"] is True
    assert flags_only[0]["column_flags_agree"] is False
    assert flags_only[0]["declarations"] == ["one.py#L1", "two.py#L1"]

    diverged = dp.duplicate_declarations(first + third)
    assert diverged[0]["column_names_agree"] is False
    assert dp.duplicate_declarations(first) == []


def test_incomplete_declarations_are_excluded_from_duplicate_analysis():
    fragment, _, _ = dp.extract_sqlite('P = "CREATE TABLE IF NOT EXISTS t"\n', "p.py")
    real, _, _ = dp.extract_sqlite('S = "CREATE TABLE t (a TEXT)"\n', "r.py")
    assert dp.duplicate_declarations(fragment + real) == []


# --- revision binding -------------------------------------------------------
def test_git_revision_reads_head_ref_without_subprocess(tmp_path):
    git_dir = tmp_path / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    digest = "0" * 39 + "1"
    (git_dir / "refs" / "heads" / "main").write_text(digest + "\n", encoding="utf-8")
    assert dp.git_revision(tmp_path) == digest


def test_git_revision_returns_none_without_a_git_dir(tmp_path):
    assert dp.git_revision(tmp_path) is None


# --- repository-level invariants (no frozen counts) -------------------------
def test_probe_over_this_repository_is_structurally_sound():
    result = dp.probe(REPO_ROOT)
    assert result["nodes"]["total"] > 0
    assert result["fields"]["unanchored"] == 0
    assert result["files"]["python_unparseable"] == 0
    assert result["files"]["json_unparseable"] == 0
    assert (
        result["fields"]["declared_type"]
        + result["fields"]["inferred_type"]
        + result["fields"]["no_type"]
        == result["fields"]["total"]
    )
    assert (
        result["nodes"]["sqlite_table"]
        + result["nodes"]["json_schema"]
        + result["nodes"]["json_schema_def"]
        + result["nodes"]["csv_table"]
        == result["nodes"]["total"]
    )
    json.dumps(result)  # the output contract stays serialisable


def test_node_records_carry_a_locator_for_every_field():
    for record in dp.node_records(REPO_ROOT):
        assert "#" in record["locator"]
        for item in record["fields"]:
            assert "#" in item["locator"]

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
    assert node.notes == ("rows_read=2", "exhaustive")


def test_empty_csv_yields_no_node():
    assert dp.extract_csv("", "x.csv") == []


def test_csv_reads_every_row_by_default_and_marks_sampling_when_asked():
    text = "id\n" + "".join(f"{n}\n" for n in range(200))
    node = dp.extract_csv(text, "x.csv")[0]
    assert node.meta["rows_read"] == 200
    assert node.meta["exhaustive"] is True
    sampled = dp.extract_csv(text, "x.csv", sample_rows=50)[0]
    assert sampled.meta["rows_read"] == 50
    assert sampled.meta["exhaustive"] is False


def test_column_observation_counts_empty_cells_as_non_numeric():
    # The DESCRIPTIVE label skips empty cells; the verifier's evidence does not.
    # An empty CELL (",,") -- distinct from a blank ROW, which is dropped.
    node = dp.extract_csv("n,other\n1,a\n,b\n2,c\n", "x.csv")[0]
    assert node.fields[0].declared_type == "integer"  # description
    observation = node.meta["columns"]["0"]
    assert observation["values_seen"] == 3
    assert observation["empty_cells"] == 1
    assert observation["all_integer"] is False  # evidence
    assert observation["all_string"] is True


def test_ragged_and_blank_rows_are_recorded():
    node = dp.extract_csv("a,b\n1,2\n3\n\n4,5\n", "x.csv")[0]
    assert node.meta["ragged_rows"] == 1
    assert node.meta["blank_rows"] == 1
    assert node.meta["rows_read"] == 3


# --- fail-closed intra-data binding -----------------------------------------
def _schema(properties: dict, required: list[str]) -> list[dp.DataNode]:
    nodes, _ = dp.extract_json_schema(
        {
            "$schema": "s",
            "type": "object",
            "required": required,
            "properties": properties,
        },
        "schemas/event.schema.json",
    )
    return nodes


EVENT_SCHEMA = _schema(
    {"id": {"type": "string"}, "voltage": {"type": "number"}}, ["id", "voltage"]
)


def _bind(text: str, schema_nodes=None, **kwargs) -> dict:
    proposals = dp.propose_intra_data_bindings(
        [dp.extract_csv(text, "data/events.csv", **kwargs)[0]],
        EVENT_SCHEMA if schema_nodes is None else schema_nodes,
    )
    assert len(proposals) == 1
    return proposals[0]


def test_a_clean_binding_verifies_and_still_is_not_a_trusted_edge():
    record = _bind("id,voltage\na,1.5\nb,2\n")
    assert record["status"] == dp.VERIFIED
    assert record["rejections"] == [] and record["indeterminacies"] == []
    assert record["rows_checked"] == 2 and record["exhaustive_rows"] is True
    # The whole point of the fix: a passing check is NOT a cross-plane edge.
    assert record["record_type"] == "intra_data_proposal"
    assert record["planes"] == ["data", "data"]
    assert record["trusted_cross_plane_edge"] is False
    assert record["sec6_verifier_record"] is None
    assert set(record["sec6_inputs_missing"]) == {
        "revision_compatibility",
        "task_relevance",
        "score",
        "expiry_or_retest",
    }


def test_missing_required_field_is_rejected():
    # The old check never looked at `required` at all.
    schema = _schema(
        {"id": {"type": "string"}, "voltage": {"type": "number"}}, ["id", "voltage"]
    )
    record = _bind("id\na\n", schema)
    assert record["status"] == dp.REJECTED
    assert record["rejections"] == ["required_field_missing:voltage"]


def test_column_the_schema_does_not_declare_is_rejected():
    record = _bind("id,voltage,extra\na,1.5,x\n")
    assert record["status"] == dp.REJECTED
    assert "csv_column_not_in_schema:extra" in record["rejections"]


def test_value_contradicting_the_declared_type_is_rejected():
    record = _bind("id,voltage\na,b\n")
    assert record["status"] == dp.REJECTED
    assert record["rejections"] == ["type_mismatch:voltage:values_not_number"]


def test_one_bad_row_late_in_the_file_is_still_caught():
    # The old code sampled 50 rows; row 120 was invisible to it.
    rows = "".join(f"id{n},1.0\n" for n in range(119)) + "idX,not-a-number\n"
    record = _bind("id,voltage\n" + rows)
    assert record["rows_checked"] == 120
    assert record["status"] == dp.REJECTED
    assert record["rejections"] == ["type_mismatch:voltage:values_not_number"]
    # and proof the old 50-row window would have missed it
    sampled = dp.extract_csv("id,voltage\n" + rows, "data/events.csv", sample_rows=50)[0]
    assert sampled.meta["columns"]["1"]["all_number"] is True


def test_union_type_is_indeterminate_never_verified():
    schema = _schema(
        {"id": {"type": "string"}, "voltage": {"type": ["number", "null"]}},
        ["id", "voltage"],
    )
    record = _bind("id,voltage\na,1.5\n", schema)
    assert record["status"] == dp.INDETERMINATE
    assert record["indeterminacies"] == ["schema_type_union:voltage"]


def test_ref_is_indeterminate_never_verified():
    schema = _schema(
        {"id": {"$ref": "#/$defs/identifier"}, "voltage": {"type": "number"}},
        ["id", "voltage"],
    )
    record = _bind("id,voltage\na,1.5\n", schema)
    assert record["status"] == dp.INDETERMINATE
    assert record["indeterminacies"] == ["schema_type_ref:id"]


def test_untyped_property_is_indeterminate_never_verified():
    schema = _schema(
        {"id": {"description": "no type"}, "voltage": {"type": "number"}},
        ["id", "voltage"],
    )
    record = _bind("id,voltage\na,1.5\n", schema)
    assert record["status"] == dp.INDETERMINATE
    assert record["indeterminacies"] == ["schema_type_untyped:id"]


def test_bare_enum_property_is_indeterminate_never_verified():
    # This is the exact hole the old table walked through: `enum` was not in
    # the admissibility map, `.get()` returned None, and "no mismatch" was
    # read as "verified".
    schema = _schema(
        {"id": {"type": "string"}, "voltage": {"enum": ["low", "high"]}},
        ["id", "voltage"],
    )
    record = _bind("id,voltage\na,low\n", schema)
    assert record["status"] == dp.INDETERMINATE
    assert record["indeterminacies"] == ["schema_type_enum:voltage"]


def test_unsupported_non_scalar_type_is_indeterminate():
    schema = _schema(
        {"id": {"type": "string"}, "voltage": {"type": "object"}}, ["id", "voltage"]
    )
    record = _bind("id,voltage\na,1.5\n", schema)
    assert record["status"] == dp.INDETERMINATE
    assert record["indeterminacies"] == ["schema_type_unsupported:voltage"]


def test_sampled_rows_can_never_verify():
    rows = "".join(f"id{n},1.0\n" for n in range(200))
    record = _bind("id,voltage\n" + rows, sample_rows=50)
    assert record["status"] == dp.INDETERMINATE
    assert "csv_types_sampled_not_exhaustive" in record["indeterminacies"]
    assert record["exhaustive_rows"] is False


def test_duplicate_header_name_is_indeterminate():
    schema = _schema(
        {"id": {"type": "string"}, "voltage": {"type": "number"}}, ["id", "voltage"]
    )
    record = _bind("id,voltage,id\na,1.5,b\n", schema)
    assert record["status"] == dp.INDETERMINATE
    assert "csv_header_not_unique:id" in record["indeterminacies"]


def test_blank_header_name_is_indeterminate():
    schema = _schema(
        {"id": {"type": "string"}, "voltage": {"type": "number"}, "": {"type": "string"}},
        ["id", "voltage"],
    )
    record = _bind("id,voltage,\na,1.5,x\n", schema)
    assert record["status"] == dp.INDETERMINATE
    assert "csv_header_blank_name" in record["indeterminacies"]


def test_header_only_file_is_indeterminate_not_verified():
    record = _bind("id,voltage\n")
    assert record["status"] == dp.INDETERMINATE
    assert "csv_has_no_data_rows" in record["indeterminacies"]


def test_ragged_rows_are_indeterminate():
    record = _bind("id,voltage\na,1.5\nb\n")
    assert record["status"] == dp.INDETERMINATE
    assert "csv_rows_ragged:1" in record["indeterminacies"]


def test_column_without_observed_values_is_indeterminate():
    schema = _schema(
        {"id": {"type": "string"}, "voltage": {"type": "number"}}, ["id", "voltage"]
    )
    record = _bind("id,voltage\na,\n", schema)
    # "" is not a number: an empty cell cannot verify a numeric property.
    assert record["status"] == dp.REJECTED
    assert record["rejections"] == ["type_mismatch:voltage:values_not_number"]


def test_boolean_only_accepts_true_false_literals():
    schema = _schema({"flag": {"type": "boolean"}}, ["flag"])
    assert _bind("flag\ntrue\nFALSE\n", schema)["status"] == dp.VERIFIED
    # The old map said boolean admits any string; 0/1 must not pass.
    assert _bind("flag\n1\n0\n", schema)["status"] == dp.REJECTED
    assert _bind("flag\nyes\n", schema)["status"] == dp.REJECTED


def test_a_rejection_always_outranks_an_indeterminacy():
    schema = _schema(
        {"id": {"type": "string"}, "voltage": {"enum": ["low"]}}, ["id", "voltage"]
    )
    record = _bind("id,voltage,extra\na,low,x\n", schema)
    assert record["status"] == dp.REJECTED
    assert record["rejections"] and record["indeterminacies"]


def test_no_field_overlap_produces_no_proposal():
    assert (
        dp.propose_intra_data_bindings(
            [dp.extract_csv("other\n1\n", "data/events.csv")[0]], EVENT_SCHEMA
        )
        == []
    )


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


# --- accounting: the funnel must add up -------------------------------------
def test_python_accounting_adds_up_and_parses_every_scanned_file(tmp_path):
    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "good.py").write_text(
        'SQL = "CREATE TABLE t (a TEXT)"\n', encoding="utf-8"
    )
    (root / "src" / "plain.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "mentions.py").write_text(
        "# CREATE TABLE only in a comment\nVALUE = 2\n", encoding="utf-8"
    )
    (root / "src" / "broken.py").write_text("def (\n", encoding="utf-8")
    scope = dp.Scope(ddl_roots=("src",), json_roots=(), csv_roots=())
    found = dp.collect(root, scope)
    py = found.python
    assert py["scanned"] == 4
    # The whole point: every scanned file reaches the parser.
    assert py["parsed"] + py["unparseable"] + py["unreadable"] == py["scanned"]
    assert py["unparseable"] == 1
    assert found.unparseable_python == ["src/broken.py"]
    assert py["parsed_with_ddl"] + py["parsed_without_ddl"] == py["parsed"]
    # Classification is by parse, not by grep: a comment is not a declaration.
    assert py["parsed_with_ddl"] == 1
    assert py["parsed_without_ddl"] == 2


def test_a_prefilter_can_no_longer_hide_an_unparseable_file(tmp_path):
    """Regression for the reported denominator artifact.

    The earlier probe skipped any file without the literal text CREATE TABLE
    BEFORE parsing, so a syntactically invalid file was silently absent from
    the "unparseable" count while still being counted as "scanned".
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "broken.py").write_text("def (\n", encoding="utf-8")
    scope = dp.Scope(ddl_roots=("src",), json_roots=(), csv_roots=())
    py = dp.collect(tmp_path, scope).python
    assert py["scanned"] == 1 and py["unparseable"] == 1 and py["parsed"] == 0


def test_json_and_csv_accounting_add_up(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "a.schema.json").write_text(
        '{"properties": {"x": {"type": "string"}}}', encoding="utf-8"
    )
    (tmp_path / "d" / "plain.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "d" / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "d" / "rows.csv").write_text("x\n1\n", encoding="utf-8")
    (tmp_path / "d" / "empty.csv").write_text("", encoding="utf-8")
    scope = dp.Scope(ddl_roots=(), json_roots=("d",), csv_roots=("d",))
    found = dp.collect(tmp_path, scope)
    js = found.json
    assert js["scanned"] == 3
    assert js["parsed"] + js["unparseable"] + js["unreadable"] == js["scanned"]
    assert js["unparseable"] == 1 and found.unparseable_json == ["d/broken.json"]
    assert js["schema_documents"] + js["non_schema_documents"] == js["parsed"]
    cs = found.csv
    assert cs["scanned"] == 2
    assert cs["parsed"] + cs["empty"] + cs["unreadable"] == cs["scanned"]
    assert cs["empty"] == 1


def test_census_accounts_for_every_file_of_a_candidate_suffix(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "d" / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (tmp_path / "elsewhere" / "b.csv").write_text("x\n1\n", encoding="utf-8")
    (tmp_path / "runs" / "c.csv").write_text("x\n1\n", encoding="utf-8")
    scope = dp.Scope(ddl_roots=(), json_roots=(), csv_roots=("d",))
    bucket = dp.census(tmp_path, scope)["by_suffix"][".csv"]
    assert bucket["in_tree"] == 3
    assert bucket["accounted"] == bucket["in_tree"]  # nothing falls off the table
    assert bucket["in_scope"] == 1
    assert bucket["excluded_documented"] == 1  # runs/
    assert bucket["excluded_outside_frozen_roots"] == 1


def test_binding_stage_denominator_is_all_candidate_pairs(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "a.schema.json").write_text(
        '{"required": ["x"], "properties": {"x": {"type": "integer"}}}',
        encoding="utf-8",
    )
    (tmp_path / "d" / "b.schema.json").write_text(
        '{"required": ["y"], "properties": {"y": {"type": "integer"}}}',
        encoding="utf-8",
    )
    (tmp_path / "d" / "t.csv").write_text("x\n1\n", encoding="utf-8")
    scope = dp.Scope(ddl_roots=(), json_roots=("d",), csv_roots=("d",))
    binding = dp.probe(tmp_path, scope)["accounting"]["binding"]
    assert binding["candidate_pairs"] == 2  # 1 csv x 2 schemas, not just the hits
    assert binding["excluded_no_field_overlap"] == 1
    assert binding["proposals"] == 1
    assert (
        binding["verified"] + binding["rejected"] + binding["indeterminate"]
        == binding["proposals"]
    )


# --- the pinned corpus ------------------------------------------------------
# The repository table is revision-bound and moves when the tree moves, which
# is exactly how the earlier numbers drifted away from what the code did.
# `corpus/` is a committed, frozen tree, so THESE numbers are a contract: they
# can only change when someone changes the corpus or the extractor, and then
# this test says so out loud.
CORPUS = Path(__file__).resolve().parent / "corpus"
CORPUS_SCOPE = dp.Scope(
    ddl_roots=("src",),
    json_roots=("schemas",),
    csv_roots=("data",),
    documented_exclusions=("excluded",),
)

PINNED_ACCOUNTING = {
    "python": {
        "scanned": 9,
        "unreadable": 0,
        "unparseable": 1,
        "parsed": 8,
        "parsed_with_ddl": 6,
        "parsed_without_ddl": 2,
    },
    "json": {
        "scanned": 6,
        "unreadable": 0,
        "unparseable": 1,
        "parsed": 5,
        "schema_documents": 4,
        "non_schema_documents": 1,
    },
    "csv": {"scanned": 7, "unreadable": 0, "empty": 1, "parsed": 6},
    "binding": {
        "candidate_pairs": 30,
        "excluded_no_field_overlap": 6,
        "excluded_schema_without_properties": 6,
        "proposals": 24,
        "verified": 1,
        "rejected": 10,
        "indeterminate": 13,
    },
}

PINNED_NODES = {
    "total": 19,
    "sqlite_table": 7,
    "sqlite_table_incomplete": 3,
    "json_schema": 4,
    "json_schema_def": 2,
    "csv_table": 6,
    "json_schema_def_scalar": 1,
    "with_zero_fields": 3,
}

PINNED_FIELDS = {
    "total": 42,
    "sqlite": 10,
    "json_schema": 13,
    "csv": 19,
    "declared_type": 23,
    "inferred_type": 19,
    "no_type": 0,
    "line_anchored": 29,
    "pointer_anchored": 13,
    "unanchored": 0,
}

PINNED_EDGES = {
    "total": 2,
    "sqlite_foreign_key": 1,
    "json_ref": 1,
    "json_ref_internal": 1,
    "sqlite_index_statements": 0,
}

PINNED_CENSUS = {
    ".py": {"in_tree": 9, "in_scope": 9, "excluded_documented": 0},
    ".json": {"in_tree": 7, "in_scope": 6, "excluded_documented": 1},
    ".csv": {"in_tree": 8, "in_scope": 7, "excluded_documented": 1},
}


def _corpus() -> dict:
    return dp.probe(CORPUS, CORPUS_SCOPE)


def test_pinned_corpus_accounting_table():
    accounting = _corpus()["accounting"]
    assert accounting == PINNED_ACCOUNTING


def test_pinned_corpus_node_field_and_edge_table():
    result = _corpus()
    assert result["nodes"] == PINNED_NODES
    assert result["fields"] == PINNED_FIELDS
    assert result["edges"] == PINNED_EDGES
    assert result["naive_ddl_baseline"] == {
        "statements_on_raw_lines": 7,
        "complete_body_on_one_line": 0,
        "ast_folded_tables": 7,
    }


def test_pinned_corpus_census_accounts_for_every_candidate_file():
    census = _corpus()["census"]["by_suffix"]
    for suffix, expected in PINNED_CENSUS.items():
        bucket = census[suffix]
        assert bucket["accounted"] == bucket["in_tree"], suffix
        for key, value in expected.items():
            assert bucket[key] == value, (suffix, key)


def test_pinned_corpus_binding_outcomes_per_pair():
    detail = {
        (
            Path(item["csv"].split("#")[0]).name,
            Path(item["schema"].split("#")[0]).name,
        ): item["status"]
        for item in _corpus()["intra_data_bindings"]["detail"]
    }
    # Exactly one binding in the whole corpus survives every check.
    assert detail[("good.csv", "article.schema.json")] == dp.VERIFIED
    assert sum(1 for status in detail.values() if status == dp.VERIFIED) == 1
    # The same clean CSV is indeterminate against the three schemas whose
    # property types this probe cannot decide.
    assert detail[("good.csv", "enum_votes.schema.json")] == dp.INDETERMINATE
    assert detail[("good.csv", "union_votes.schema.json")] == dp.INDETERMINATE
    assert detail[("good.csv", "ref_id.schema.json")] == dp.INDETERMINATE
    # Structural failures reject against every schema.
    for schema in (
        "article.schema.json",
        "enum_votes.schema.json",
        "union_votes.schema.json",
        "ref_id.schema.json",
    ):
        assert detail[("extra_column.csv", schema)] == dp.REJECTED
        assert detail[("missing_required.csv", schema)] == dp.REJECTED
        assert detail[("ragged.csv", schema)] == dp.INDETERMINATE
        assert detail[("duplicate_header.csv", schema)] == dp.INDETERMINATE
    # A contradicted value rejects only where the type was decidable at all.
    assert detail[("bad_type.csv", "article.schema.json")] == dp.REJECTED
    assert detail[("bad_type.csv", "ref_id.schema.json")] == dp.REJECTED
    assert detail[("bad_type.csv", "enum_votes.schema.json")] == dp.INDETERMINATE
    assert detail[("bad_type.csv", "union_votes.schema.json")] == dp.INDETERMINATE


def test_pinned_corpus_sqlite_nodes():
    nodes = dp.collect(CORPUS, CORPUS_SCOPE).sqlite_nodes
    shape = sorted(
        (node.name, node.complete, len(node.fields), node.notes) for node in nodes
    )
    assert shape == [
        ("article", True, 3, ()),
        ("article_tag", True, 2, ()),
        # prose in a docstring: a known false positive, kept visible and
        # explicitly shapeless rather than filtered away
        ("ghost_table", False, 0, ("no_balanced_body",)),
        # f-string: one node, not two -- ast.walk yields the literal segments
        # of a JoinedStr a second time on their own
        ("live_", False, 1, ("f_string_partial",)),
        ("session", False, 0, ("no_balanced_body",)),
        ("session", True, 2, ()),
        ("session", True, 2, ()),
    ]


def test_one_fstring_declaration_yields_exactly_one_node():
    source = 'SQL = f"CREATE TABLE live_{suffix} (key TEXT PRIMARY KEY)"\n'
    nodes, _, _ = dp.extract_sqlite(source, "pkg/mod.py")
    assert len(nodes) == 1
    assert nodes[0].name == "live_"
    assert nodes[0].notes == ("f_string_partial",)
    assert nodes[0].complete is False


def test_pinned_corpus_finds_the_constraint_divergence():
    groups = _corpus()["duplicate_table_declarations"]
    assert len(groups) == 1
    group = groups[0]
    assert group["table"] == "session"
    assert group["column_names_agree"] is True
    assert group["column_types_agree"] is True
    assert group["column_flags_agree"] is False
    assert group["declarations"] == ["src/duplicate_a.py#L10", "src/duplicate_b.py#L4"]


# --- repository-level invariants (no frozen counts) -------------------------
def test_probe_over_this_repository_is_structurally_sound():
    result = dp.probe(REPO_ROOT)
    assert result["nodes"]["total"] > 0
    assert result["fields"]["unanchored"] == 0
    python = result["accounting"]["python"]
    assert python["parsed"] + python["unparseable"] + python["unreadable"] == (
        python["scanned"]
    )
    assert python["unparseable"] == 0
    assert result["accounting"]["json"]["unparseable"] == 0
    assert result["intra_data_bindings"]["trusted_cross_plane_edges"] == 0
    for suffix, bucket in result["census"]["by_suffix"].items():
        assert bucket["accounted"] == bucket["in_tree"], suffix
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

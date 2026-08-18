"""EXPERIMENT s03 -- Forest v2 pre-study, data plane extraction baseline.

Classification: EXPERIMENT (master plan section 10, Gate 2 prework:
"data/schema extraction").  Read-only.  No production promotion, no
production import may reference this module.

What it does: walks a frozen set of repository roots and lifts three kinds of
*declared* data artifacts into plain data nodes with a provenance locator:

  sqlite.table   -- CREATE TABLE statements embedded in Python string
                    constants (AST-folded, so implicit concatenation is seen)
  json.schema    -- JSON Schema documents and their ``$defs`` sub-schemas
  csv.table      -- CSV headers (fields declared by the header row only)

Every node carries ``locator`` = "<repo-relative path>#<anchor>" and every
field carries its own locator, so a later Forest build can bind a data node
back to the exact source line or JSON Pointer that declared it.

It also proposes CSV-table -> JSON-schema bindings.  Those are INTRA-DATA-PLANE
PROPOSALS: both endpoints are data-plane nodes, and the plan section 6 verifier
record is incomplete here (no revision compatibility, no task relevance, no
score, no expiry/retest), so nothing this module emits is a trusted cross-plane
edge.  Verification is fail-closed: whatever the probe cannot decide comes back
``indeterminate``, never ``verified``.

Constraints held on purpose: stdlib only, no repository imports, no writes,
no network, no subprocess.  ``main`` prints one JSON object to stdout, which
keeps this directory free of an effectful entrypoint (see the boundary note
in ``experiments/forest_v2/README.md``).
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path

# --- frozen scope -----------------------------------------------------------
# DDL is only mined where the slice says it lives.  JSON/CSV roots are the
# declared-shape carriers.  Everything excluded is excluded loudly (the probe
# reports the size of the excluded population so nothing is quietly hidden).
DDL_ROOTS = ("daedalus",)
JSON_ROOTS = ("configs", "tests/fixtures", "examples", "daedalus")
CSV_ROOTS = ("tests/fixtures", "examples")
EXCLUDED_DIRS = (".git", ".claude", "node_modules", "__pycache__", ".venv")
# Declared, not silently dropped: receipt instances under runs/ are data
# *instances* of the schemas in configs/, not declarations of shape.
DOCUMENTED_EXCLUSIONS = ("runs", ".claude/skills")
# Directories skipped by the tree census as "not source at all".  Counting the
# contents of .git would be noise, not honesty.
CENSUS_PRUNED_DIRS = (".git", "node_modules", "__pycache__", ".venv")


@dataclass(frozen=True)
class Scope:
    """The frozen scope, as a value -- so a corpus can pin numbers exactly."""

    ddl_roots: tuple[str, ...] = DDL_ROOTS
    json_roots: tuple[str, ...] = JSON_ROOTS
    csv_roots: tuple[str, ...] = CSV_ROOTS
    documented_exclusions: tuple[str, ...] = DOCUMENTED_EXCLUSIONS

_CREATE_TABLE = re.compile(
    r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*|\"[^\"]+\"|`[^`]+`|\[[^\]]+\])",
    re.IGNORECASE,
)
_CREATE_INDEX = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+", re.IGNORECASE)
_REFERENCES = re.compile(
    r"REFERENCES\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_FOREIGN_KEY = re.compile(r"^\s*FOREIGN\s+KEY", re.IGNORECASE)
_TABLE_CONSTRAINT = re.compile(
    r"^\s*(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|CONSTRAINT)\b", re.IGNORECASE
)
# A column type may be several words ("UNSIGNED BIG INT") and may carry
# arguments ("VARCHAR(10)"), so it is consumed token-wise and stopped at the
# first constraint keyword -- a greedy "words and spaces" regex would swallow
# "NOT NULL PRIMARY KEY" into the declared type.
_TYPE_STOP_WORDS = frozenset(
    {
        "PRIMARY",
        "NOT",
        "NULL",
        "UNIQUE",
        "DEFAULT",
        "REFERENCES",
        "CHECK",
        "COLLATE",
        "GENERATED",
        "AS",
        "CONSTRAINT",
        "AUTOINCREMENT",
        "ON",
        "DEFERRABLE",
        "KEY",
        "ASC",
        "DESC",
        "CONFLICT",
    }
)
_TYPE_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\s*\([^)]*\))?$")
# The cheap alternative this baseline is measured against: one regex, one raw
# source line, a complete parenthesised body.
_NAIVE_ONE_LINE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\((.+)\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Field:
    name: str
    declared_type: str | None
    type_source: str  # "declared" | "inferred" | "none"
    flags: tuple[str, ...]
    locator: str


@dataclass
class DataNode:
    node_id: str
    kind: str
    name: str
    locator: str
    fields: list[Field] = dc_field(default_factory=list)
    complete: bool = True
    notes: tuple[str, ...] = ()
    # Evidence the verifier needs but a field list cannot carry: how many rows
    # were actually read, whether that was the whole file, and the per-column
    # observation summary.  A verifier that only sees a summarised type label
    # cannot tell an exhaustive check from a sample.
    meta: dict = dc_field(default_factory=dict)


@dataclass(frozen=True)
class DataEdge:
    kind: str
    src: str
    dst: str
    evidence: str


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def _iter_files(root: Path, roots: tuple[str, ...], suffix: str) -> list[Path]:
    seen: dict[str, Path] = {}
    for name in roots:
        base = root / name
        if not base.exists():
            continue
        for path in sorted(base.rglob(f"*{suffix}")):
            if path.is_file() and not _excluded(path):
                seen.setdefault(_rel(root, path), path)
    return [seen[key] for key in sorted(seen)]


# --- sqlite DDL -------------------------------------------------------------
def _split_top_level(body: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return [part.strip() for part in parts if part.strip()]


def _balanced_body(text: str, open_index: int) -> tuple[str | None, int]:
    """Return the content of the parenthesis group starting at ``open_index``."""
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index], index
    return None, len(text)


def _unquote(name: str) -> str:
    return name.strip().strip('"').strip("`").strip("[]")


def _field_line(source_lines: list[str], span: range, column: str) -> int | None:
    pattern = re.compile(r"[\s\"'`\[(,]" + re.escape(column) + r"[\s\"'`\]),]")
    for lineno in span:
        line = source_lines[lineno - 1]
        if pattern.search(" " + line + " "):
            return lineno
    return None


def _declared_type(rest: str) -> str | None:
    """Leading type words of a column definition, stopped at the constraints."""
    words: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*\s*\([^)]*\)|[^\s,]+", rest):
        token = token.strip()
        head = re.split(r"[\s(]", token, maxsplit=1)[0].upper()
        if head in _TYPE_STOP_WORDS or not _TYPE_WORD.match(token):
            break
        words.append(re.sub(r"\s+", "", token))
    return " ".join(words) if words else None


def _parse_columns(
    body: str, rel_path: str, table: str, source_lines: list[str], span: range
) -> tuple[list[Field], list[DataEdge]]:
    fields: list[Field] = []
    edges: list[DataEdge] = []
    for part in _split_top_level(body):
        if _TABLE_CONSTRAINT.match(part):
            if _FOREIGN_KEY.match(part):
                ref = _REFERENCES.search(part)
                if ref:
                    edges.append(
                        DataEdge(
                            "sqlite.foreign_key",
                            f"{rel_path}::{table}",
                            f"{ref.group(1)}.{ref.group(2)}",
                            part.strip()[:120],
                        )
                    )
            continue
        tokens = part.split(None, 1)
        if not tokens:
            continue
        name = _unquote(tokens[0])
        if not name or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            continue
        rest = tokens[1] if len(tokens) > 1 else ""
        declared = _declared_type(rest)
        flags = []
        upper = rest.upper()
        if "PRIMARY KEY" in upper:
            flags.append("primary_key")
        if "NOT NULL" in upper:
            flags.append("not_null")
        if "UNIQUE" in upper:
            flags.append("unique")
        if "DEFAULT" in upper:
            flags.append("default")
        ref = _REFERENCES.search(rest)
        if ref:
            flags.append("references")
            edges.append(
                DataEdge(
                    "sqlite.foreign_key",
                    f"{rel_path}::{table}.{name}",
                    f"{ref.group(1)}.{ref.group(2)}",
                    part.strip()[:120],
                )
            )
        line = _field_line(source_lines, span, name)
        anchor = f"L{line}" if line else f"L{span.start}"
        fields.append(
            Field(
                name=name,
                declared_type=declared,
                type_source="declared" if declared else "none",
                flags=tuple(flags),
                locator=f"{rel_path}#{anchor}",
            )
        )
    return fields, edges


def _sql_strings(tree: ast.Module) -> list[tuple[str, int, int, bool]]:
    """(text, lineno, end_lineno, is_complete) for every DDL-bearing literal.

    An f-string's literal segments are ``ast.Constant`` nodes in their own
    right, so a plain ``ast.walk`` yields them BOTH as part of the JoinedStr
    and again individually -- one f-string DDL then counts as two tables, the
    second of them a truncated phantom.  The segments are collected first and
    skipped, so each literal is accounted for exactly once.
    """
    inside_fstring: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in ast.walk(node):
                if isinstance(part, ast.Constant):
                    inside_fstring.add(id(part))
    found: list[tuple[str, int, int, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in inside_fstring:
                continue
            if _CREATE_TABLE.search(node.value):
                found.append(
                    (node.value, node.lineno, node.end_lineno or node.lineno, True)
                )
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                value.value
                for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
            if _CREATE_TABLE.search(text):
                found.append(
                    (text, node.lineno, node.end_lineno or node.lineno, False)
                )
    return found


def extract_sqlite(source: str, rel_path: str) -> tuple[list[DataNode], list[DataEdge], int]:
    """Return (table nodes, edges, index statement count) for one Python file."""
    return extract_sqlite_from_tree(ast.parse(source), source, rel_path)


def extract_sqlite_from_tree(
    tree: ast.Module, source: str, rel_path: str
) -> tuple[list[DataNode], list[DataEdge], int]:
    """Same, for a caller that already parsed the file.

    The accounting walk parses EVERY candidate file so the unparseable count
    has an honest denominator; it must not pay for a second parse here.
    """
    source_lines = source.splitlines()
    nodes: list[DataNode] = []
    edges: list[DataEdge] = []
    indexes = 0
    for text, lineno, end_lineno, literal_complete in _sql_strings(tree):
        indexes += len(_CREATE_INDEX.findall(text))
        span = range(lineno, min(end_lineno, len(source_lines)) + 1)
        for match in _CREATE_TABLE.finditer(text):
            table = _unquote(match.group(1))
            open_index = text.find("(", match.end())
            body, _ = (
                _balanced_body(text, open_index) if open_index != -1 else (None, 0)
            )
            node = DataNode(
                node_id=f"{rel_path}::{table}",
                kind="sqlite.table",
                name=table,
                locator=f"{rel_path}#L{lineno}",
                complete=literal_complete and body is not None,
            )
            if body is not None:
                columns, table_edges = _parse_columns(
                    body, rel_path, table, source_lines, span
                )
                node.fields = columns
                edges.extend(table_edges)
            else:
                node.notes = ("no_balanced_body",)
            if not literal_complete:
                node.notes = node.notes + ("f_string_partial",)
            nodes.append(node)
    return nodes, edges, indexes


def naive_sqlite_baseline(source: str) -> tuple[int, int]:
    """(statements seen, statements whose body is complete on one raw line)."""
    seen = 0
    complete = 0
    for line in source.splitlines():
        for _ in _CREATE_TABLE.finditer(line):
            seen += 1
        if _NAIVE_ONE_LINE.search(line):
            complete += 1
    return seen, complete


# --- JSON Schema ------------------------------------------------------------
_SCHEMA_KEYS = {"$schema", "properties", "$defs", "definitions", "required"}


def _is_schema(document: object) -> bool:
    return isinstance(document, dict) and bool(_SCHEMA_KEYS & set(document))


def _schema_fields(schema: dict, rel_path: str, pointer: str) -> list[Field]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    fields: list[Field] = []
    for name, spec in properties.items():
        declared = None
        source = "none"
        if isinstance(spec, dict):
            if isinstance(spec.get("type"), str):
                declared, source = spec["type"], "declared"
            elif isinstance(spec.get("type"), list):
                declared, source = "|".join(map(str, spec["type"])), "declared"
            elif isinstance(spec.get("$ref"), str):
                declared, source = f"$ref:{spec['$ref']}", "declared"
            elif "const" in spec:
                declared, source = "const", "declared"
            elif "enum" in spec:
                declared, source = "enum", "declared"
        flags = ("required",) if name in required_names else ("optional",)
        fields.append(
            Field(
                name=str(name),
                declared_type=declared,
                type_source=source,
                flags=flags,
                locator=f"{rel_path}#/{pointer}/properties/{name}".replace("#//", "#/"),
            )
        )
    return fields


def extract_json_schema(
    document: object, rel_path: str
) -> tuple[list[DataNode], list[DataEdge]]:
    nodes: list[DataNode] = []
    edges: list[DataEdge] = []
    if not _is_schema(document):
        return nodes, edges
    assert isinstance(document, dict)
    root_name = str(document.get("title") or Path(rel_path).name)
    root = DataNode(
        node_id=f"{rel_path}::$",
        kind="json.schema",
        name=root_name,
        locator=f"{rel_path}#/",
        fields=_schema_fields(document, rel_path, ""),
    )
    nodes.append(root)
    for container in ("$defs", "definitions"):
        defs = document.get(container)
        if not isinstance(defs, dict):
            continue
        for name, sub in defs.items():
            if not isinstance(sub, dict):
                continue
            pointer = f"{container}/{name}"
            nodes.append(
                DataNode(
                    node_id=f"{rel_path}::{pointer}",
                    kind="json.schema.def",
                    name=str(name),
                    locator=f"{rel_path}#/{pointer}",
                    fields=_schema_fields(sub, rel_path, pointer),
                )
            )
    for node in nodes:
        for item in node.fields:
            if item.declared_type and item.declared_type.startswith("$ref:"):
                target = item.declared_type[len("$ref:") :]
                edges.append(
                    DataEdge(
                        "json.ref",
                        f"{node.node_id}.{item.name}",
                        target if target.startswith("#") else target,
                        item.locator,
                    )
                )
    return nodes, edges


# --- CSV --------------------------------------------------------------------
# A CSV cell is text.  "true"/"false" is the only spelling of a JSON boolean
# this probe will accept; 0/1/yes/no are deliberately NOT booleans here,
# because guessing an encoding is exactly the kind of unverifiable heuristic
# this slice is supposed to avoid.
_BOOLEAN_LITERALS = frozenset({"true", "false"})


def _is_integer(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _infer(values: list[str]) -> str | None:
    """Descriptive label for the reported column type.

    Deliberately skips empty cells so the *description* stays readable.  This
    is NOT what the verifier uses -- see ``_column_observation``.
    """
    kept = [value for value in values if value != ""]
    if not kept:
        return None
    if all(_is_integer(value) for value in kept):
        return "integer"
    if all(_is_number(value) for value in kept):
        return "number"
    return "string"


def _column_observation(values: list[str]) -> dict:
    """Exhaustive per-column evidence over EVERY value that was read.

    Unlike ``_infer`` this counts empty cells: "" is not an integer, not a
    number and not a boolean, so a column carrying one is admissible for a
    string property only.  ``values_seen == 0`` means there is no evidence at
    all, which the verifier must treat as indeterminate rather than as a pass.
    """

    def _every(predicate) -> bool:
        return bool(values) and all(predicate(value) for value in values)

    return {
        "values_seen": len(values),
        "empty_cells": sum(1 for value in values if value == ""),
        "all_integer": _every(_is_integer),
        "all_number": _every(_is_number),
        "all_boolean": _every(lambda value: value.strip().lower() in _BOOLEAN_LITERALS),
        "all_string": bool(values),
    }


def extract_csv(text: str, rel_path: str, sample_rows: int | None = None) -> list[DataNode]:
    """Header fields plus exhaustive per-column evidence.

    ``sample_rows=None`` (the default) reads EVERY row.  Sampling remains
    possible for a caller that wants it, but a sampled node is stamped
    ``exhaustive=False`` and the verifier refuses to verify anything from it:
    a type claim derived from part of a file is a hypothesis, not evidence.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    rows: list[list[str]] = []
    blank_rows = 0
    truncated = False
    for index, row in enumerate(reader):
        if sample_rows is not None and len(rows) >= sample_rows:
            truncated = True
            break
        if not row:
            blank_rows += 1
            continue
        rows.append(row)
    ragged_rows = sum(1 for row in rows if len(row) != len(header))

    fields: list[Field] = []
    observations: dict[str, dict] = {}
    for column, raw_name in enumerate(header):
        name = raw_name.strip()
        column_values = [row[column] for row in rows if len(row) > column]
        inferred = _infer(column_values)
        # Keyed by column index, not by name: a duplicated header name must
        # not silently overwrite another column's evidence.
        observations[str(column)] = dict(
            _column_observation(column_values), name=name
        )
        fields.append(
            Field(
                name=name,
                declared_type=inferred,
                type_source="inferred" if inferred else "none",
                flags=(f"column_{column}",),
                locator=f"{rel_path}#L1C{column + 1}",
            )
        )
    return [
        DataNode(
            node_id=f"{rel_path}::header",
            kind="csv.table",
            name=Path(rel_path).stem,
            locator=f"{rel_path}#L1",
            fields=fields,
            notes=(
                f"rows_read={len(rows)}",
                "exhaustive" if not truncated else "sampled",
            ),
            meta={
                "rows_read": len(rows),
                "blank_rows": blank_rows,
                "ragged_rows": ragged_rows,
                "exhaustive": not truncated,
                "columns": observations,
            },
        )
    ]


# --- intra-plane consistency ------------------------------------------------
def duplicate_declarations(sqlite_nodes: list[DataNode]) -> list[dict]:
    """Same table name declared in more than one place -- do they agree?

    A data plane that only counts tables misses the interesting part: two
    modules declaring the same physical table with different column sets or
    different constraints is a schema-drift hazard the code plane cannot see.
    """
    by_name: dict[str, list[DataNode]] = {}
    for node in sqlite_nodes:
        if not node.complete or not node.fields:
            continue
        by_name.setdefault(node.name, []).append(node)
    groups: list[dict] = []
    for name, nodes in sorted(by_name.items()):
        if len(nodes) < 2:
            continue
        name_sets = {tuple(item.name for item in node.fields) for node in nodes}
        typed = {
            tuple((item.name, item.declared_type) for item in node.fields)
            for node in nodes
        }
        full = {
            tuple(
                (item.name, item.declared_type, tuple(sorted(item.flags)))
                for item in node.fields
            )
            for node in nodes
        }
        groups.append(
            {
                "table": name,
                "declarations": [node.locator for node in nodes],
                "column_names_agree": len(name_sets) == 1,
                "column_types_agree": len(typed) == 1,
                "column_flags_agree": len(full) == 1,
            }
        )
    return groups


# --- intra-data-plane proposals (NOT trusted cross-plane edges) -------------
# Plan section 6: "A verifier checks source evidence, revision compatibility,
# type/rule constraints, and task relevance before an edge becomes trusted.
# Unverified similarities remain proposals and expire or are retested", and a
# proposal carries "score and rationale".
#
# This probe can supply two of those six inputs.  It therefore emits
# INTRA-DATA-PLANE PROPOSALS -- a CSV table bound to a JSON schema, both of
# them nodes of the SAME (data) plane -- and it never emits a trusted
# cross-plane edge.  A CSV-to-schema agreement is a subset-and-type check
# inside one plane; calling it cross-plane would be a category error.
SEC6_VERIFIER_INPUTS = (
    "source_evidence",
    "revision_compatibility",
    "type_rule_constraints",
    "task_relevance",
    "score",
    "expiry_or_retest",
)
# Present: every endpoint carries a file/line/pointer locator, and the type and
# required-field rules below are actually evaluated.
# Absent, with reasons:
#   revision_compatibility -- the probe reads the WORKING TREE while
#       git_revision() reports HEAD; a dirty tree makes the two disagree and
#       nothing here proves the two endpoints came from one revision.
#   task_relevance         -- there is no mission or task in scope to be
#       relevant to.
#   score                  -- the outcome is a boolean check, not a calibrated
#       score, and inventing one would be decoration.
#   expiry_or_retest       -- records carry no expiry and no retest policy.
SEC6_INPUTS_PRESENT = ("source_evidence", "type_rule_constraints")
SEC6_INPUTS_MISSING = tuple(
    name for name in SEC6_VERIFIER_INPUTS if name not in SEC6_INPUTS_PRESENT
)

# The only JSON Schema types whose CSV encoding this probe claims to decide.
SUPPORTED_SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean"})

VERIFIED = "verified"
REJECTED = "rejected"
INDETERMINATE = "indeterminate"


def _supported_scalar(declared: str | None) -> tuple[bool, str]:
    """(is a decidable scalar, reason it is not)."""
    if declared is None:
        return False, "untyped"
    if declared.startswith("$ref:"):
        return False, "ref"
    if "|" in declared:
        return False, "union"
    if declared in ("const", "enum"):
        return False, declared
    if declared not in SUPPORTED_SCALAR_TYPES:
        return False, "unsupported"
    return True, ""


def _admissible(declared: str, observation: dict) -> bool:
    """Does EVERY observed value satisfy the declared scalar type?"""
    if declared == "string":
        return observation["all_string"]
    if declared == "integer":
        return observation["all_integer"]
    if declared == "number":
        return observation["all_number"]
    if declared == "boolean":
        return observation["all_boolean"]
    return False


def propose_intra_data_bindings(
    csv_nodes: list[DataNode], schema_nodes: list[DataNode]
) -> list[dict]:
    """Propose CSV-table -> JSON-schema bindings and check them fail-closed.

    Three outcomes, never two:

    ``rejected``      a check the probe CAN run says no (a column the schema
                      does not declare, a required property the header omits,
                      a value that contradicts the declared type).
    ``indeterminate`` the probe cannot decide -- a union type, a ``$ref``, an
                      untyped or non-scalar property, a duplicated or blank
                      header name, ragged rows, a column with no observed
                      values, or types derived from a sample rather than the
                      whole file.
    ``verified``      every check passed AND every check was actually runnable.

    "verified" here means "this intra-data-plane proposal survived every check
    this probe can run".  It does NOT mean a trusted edge: the section 6
    verifier record is incomplete by construction (SEC6_INPUTS_MISSING), which
    every emitted record states about itself.
    """
    proposals: list[dict] = []
    for csv_node in csv_nodes:
        csv_names = [item.name for item in csv_node.fields]
        if not csv_names:
            continue
        meta = csv_node.meta or {}
        columns = meta.get("columns", {})
        duplicates = sorted({name for name in csv_names if csv_names.count(name) > 1})
        header_is_unique = not duplicates and "" not in csv_names
        by_name = {
            entry["name"]: entry
            for entry in columns.values()
            if isinstance(entry, dict) and "name" in entry
        }

        for schema_node in schema_nodes:
            schema_types = {
                item.name: item.declared_type for item in schema_node.fields
            }
            if not schema_types:
                continue
            required_names = sorted(
                item.name for item in schema_node.fields if "required" in item.flags
            )
            overlap = [name for name in csv_names if name in schema_types]
            if not overlap:
                continue

            rejections: list[str] = []
            indeterminacies: list[str] = []

            # --- header hygiene: an ambiguous header cannot be verified -----
            if duplicates:
                indeterminacies.append(
                    "csv_header_not_unique:" + ",".join(duplicates)
                )
            if "" in csv_names:
                indeterminacies.append("csv_header_blank_name")
            if not meta.get("exhaustive", False):
                indeterminacies.append("csv_types_sampled_not_exhaustive")
            if meta.get("ragged_rows"):
                indeterminacies.append(
                    f"csv_rows_ragged:{meta['ragged_rows']}"
                )
            if not meta.get("rows_read", 0):
                indeterminacies.append("csv_has_no_data_rows")

            # --- structural checks: definite negatives ----------------------
            for name in csv_names:
                if name not in schema_types:
                    rejections.append(f"csv_column_not_in_schema:{name}")
            for name in required_names:
                if name not in csv_names:
                    rejections.append(f"required_field_missing:{name}")

            # --- type/rule constraints over every row -----------------------
            if header_is_unique:
                for name in overlap:
                    declared = schema_types[name]
                    supported, why = _supported_scalar(declared)
                    if not supported:
                        indeterminacies.append(f"schema_type_{why}:{name}")
                        continue
                    observation = by_name.get(name)
                    if observation is None:
                        indeterminacies.append(f"csv_column_not_observed:{name}")
                    elif not observation["values_seen"]:
                        indeterminacies.append(f"csv_column_without_values:{name}")
                    elif not _admissible(declared, observation):
                        rejections.append(
                            f"type_mismatch:{name}:values_not_{declared}"
                        )

            if rejections:
                status = REJECTED
            elif indeterminacies:
                status = INDETERMINATE
            else:
                status = VERIFIED

            proposals.append(
                {
                    "record_type": "intra_data_proposal",
                    "planes": ["data", "data"],
                    "trusted_cross_plane_edge": False,
                    "csv": csv_node.locator,
                    "schema": schema_node.locator,
                    "overlap": len(overlap),
                    "csv_fields": len(csv_names),
                    "schema_fields": len(schema_types),
                    "required_fields": required_names,
                    "rows_checked": meta.get("rows_read", 0),
                    "exhaustive_rows": bool(meta.get("exhaustive", False)),
                    "status": status,
                    "rejections": rejections,
                    "indeterminacies": indeterminacies,
                    "sec6_verifier_record": None,
                    "sec6_inputs_present": list(SEC6_INPUTS_PRESENT),
                    "sec6_inputs_missing": list(SEC6_INPUTS_MISSING),
                }
            )
    return proposals


# --- revision binding (file reads only, no subprocess) ----------------------
def git_revision(root: Path) -> str | None:
    git_path = root / ".git"
    try:
        if git_path.is_file():
            pointer = git_path.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git_dir = Path(pointer.split(":", 1)[1].strip())
            if not git_dir.is_absolute():
                git_dir = (root / git_dir).resolve()
        else:
            git_dir = git_path
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(":", 1)[1].strip()
        ref_file = git_dir / ref
        if ref_file.exists():
            return ref_file.read_text(encoding="utf-8").strip()
        common = git_dir / "commondir"
        if common.exists():
            base = (git_dir / common.read_text(encoding="utf-8").strip()).resolve()
            packed = base / "packed-refs"
            if (base / ref).exists():
                return (base / ref).read_text(encoding="utf-8").strip()
            if packed.exists():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + ref):
                        return line.split(" ", 1)[0]
    except OSError:
        return None
    return None


# --- collection with an honest denominator ----------------------------------
@dataclass
class Extraction:
    """Nodes, edges, and the accounting that produced them.

    One walk feeds both ``probe`` and ``node_records``, so a count can never
    describe a different population than the node list it is published with.
    """

    sqlite_nodes: list[DataNode] = dc_field(default_factory=list)
    schema_nodes: list[DataNode] = dc_field(default_factory=list)
    csv_nodes: list[DataNode] = dc_field(default_factory=list)
    edges: list[DataEdge] = dc_field(default_factory=list)
    indexes: int = 0
    naive_seen: int = 0
    naive_complete: int = 0
    python: dict = dc_field(default_factory=dict)
    json: dict = dc_field(default_factory=dict)
    csv: dict = dc_field(default_factory=dict)
    unparseable_python: list[str] = dc_field(default_factory=list)
    unreadable_python: list[str] = dc_field(default_factory=list)
    unparseable_json: list[str] = dc_field(default_factory=list)
    unreadable_json: list[str] = dc_field(default_factory=list)
    unreadable_csv: list[str] = dc_field(default_factory=list)

    @property
    def all_nodes(self) -> list[DataNode]:
        return self.sqlite_nodes + self.schema_nodes + self.csv_nodes


def collect(root: Path, scope: Scope = Scope()) -> Extraction:
    """Walk the frozen scope once, counting every candidate file.

    The denominator rule: a file that enters the scope is counted, and every
    exit from the funnel is counted with its reason.  There is no content
    prefilter, because a prefilter that runs BEFORE the parser removes files
    from the denominator of "unparseable" and makes that number meaningless --
    the earlier version reported "285 scanned / 0 unparseable" while handing
    only 10 files to the parser.
    """
    out = Extraction()

    python_files = _iter_files(root, scope.ddl_roots, ".py")
    out.python = {
        "scanned": len(python_files),
        "unreadable": 0,
        "unparseable": 0,
        "parsed": 0,
        "parsed_with_ddl": 0,
        "parsed_without_ddl": 0,
    }
    for path in python_files:
        rel_path = _rel(root, path)
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            out.python["unreadable"] += 1
            out.unreadable_python.append(rel_path)
            continue
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            # Every candidate file reaches the parser, so "unparseable" is a
            # fraction of "scanned" and not of a pre-filtered remnant.
            out.python["unparseable"] += 1
            out.unparseable_python.append(rel_path)
            continue
        out.python["parsed"] += 1
        # Classification by PARSE, not by grep: a file that only mentions
        # CREATE TABLE in a comment carries no declaration.
        if not _sql_strings(tree):
            out.python["parsed_without_ddl"] += 1
            continue
        out.python["parsed_with_ddl"] += 1
        nodes, file_edges, file_indexes = extract_sqlite_from_tree(
            tree, source, rel_path
        )
        out.sqlite_nodes.extend(nodes)
        out.edges.extend(file_edges)
        out.indexes += file_indexes
        seen, complete = naive_sqlite_baseline(source)
        out.naive_seen += seen
        out.naive_complete += complete

    json_files = _iter_files(root, scope.json_roots, ".json")
    out.json = {
        "scanned": len(json_files),
        "unreadable": 0,
        "unparseable": 0,
        "parsed": 0,
        "schema_documents": 0,
        "non_schema_documents": 0,
    }
    for path in json_files:
        rel_path = _rel(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            out.json["unreadable"] += 1
            out.unreadable_json.append(rel_path)
            continue
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            out.json["unparseable"] += 1
            out.unparseable_json.append(rel_path)
            continue
        out.json["parsed"] += 1
        if not _is_schema(document):
            out.json["non_schema_documents"] += 1
            continue
        out.json["schema_documents"] += 1
        nodes, file_edges = extract_json_schema(document, rel_path)
        out.schema_nodes.extend(nodes)
        out.edges.extend(file_edges)

    csv_files = _iter_files(root, scope.csv_roots, ".csv")
    out.csv = {"scanned": len(csv_files), "unreadable": 0, "empty": 0, "parsed": 0}
    for path in csv_files:
        rel_path = _rel(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            out.csv["unreadable"] += 1
            out.unreadable_csv.append(rel_path)
            continue
        nodes = extract_csv(text, rel_path)
        if not nodes:
            out.csv["empty"] += 1
            continue
        out.csv["parsed"] += 1
        out.csv_nodes.extend(nodes)
    return out


def census(root: Path, scope: Scope = Scope()) -> dict:
    """Every file of each candidate suffix in the tree, bucketed by why it is
    or is not in scope.

    This is the outer denominator: the frozen scope is a choice, and a reader
    is entitled to see how large the population is that the choice excludes.
    """
    suffixes = {
        ".py": scope.ddl_roots,
        ".json": scope.json_roots,
        ".csv": scope.csv_roots,
    }
    in_scope = {
        suffix: {_rel(root, path) for path in _iter_files(root, roots, suffix)}
        for suffix, roots in suffixes.items()
    }
    buckets = {
        suffix: {
            "in_tree": 0,
            "in_scope": len(in_scope[suffix]),
            "excluded_documented": 0,
            "excluded_by_dir_filter": 0,
            "excluded_outside_frozen_roots": 0,
        }
        for suffix in suffixes
    }
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in CENSUS_PRUNED_DIRS]
        base = Path(current)
        for filename in filenames:
            suffix = Path(filename).suffix.lower()
            if suffix not in buckets:
                continue
            rel_path = _rel(root, base / filename)
            bucket = buckets[suffix]
            bucket["in_tree"] += 1
            if rel_path in in_scope[suffix]:
                continue
            if any(
                rel_path == name or rel_path.startswith(name + "/")
                for name in scope.documented_exclusions
            ):
                bucket["excluded_documented"] += 1
            elif _excluded(base / filename):
                bucket["excluded_by_dir_filter"] += 1
            else:
                bucket["excluded_outside_frozen_roots"] += 1
    for suffix, bucket in buckets.items():
        bucket["accounted"] = (
            bucket["in_scope"]
            + bucket["excluded_documented"]
            + bucket["excluded_by_dir_filter"]
            + bucket["excluded_outside_frozen_roots"]
        )
    return {"pruned_dirs": list(CENSUS_PRUNED_DIRS), "by_suffix": buckets}


# --- probe ------------------------------------------------------------------
def probe(root: Path, scope: Scope = Scope()) -> dict:
    found = collect(root, scope)
    sqlite_nodes = found.sqlite_nodes
    schema_nodes = found.schema_nodes
    csv_nodes = found.csv_nodes
    edges = found.edges
    indexes = found.indexes
    naive_seen = found.naive_seen
    naive_complete = found.naive_complete

    all_nodes = found.all_nodes
    field_total = sum(len(node.fields) for node in all_nodes)
    typed_fields = sum(
        1 for node in all_nodes for item in node.fields if item.type_source == "declared"
    )
    excluded_counts = {}
    for name in scope.documented_exclusions:
        base = root / name
        excluded_counts[name] = (
            sum(1 for path in base.rglob("*") if path.is_file()) if base.exists() else 0
        )

    proposals = propose_intra_data_bindings(csv_nodes, schema_nodes)

    return {
        "probe": "s03_data.data_plane_extraction",
        "revision": git_revision(root),
        "scope": {
            "ddl_roots": list(scope.ddl_roots),
            "json_roots": list(scope.json_roots),
            "csv_roots": list(scope.csv_roots),
            "documented_exclusions": excluded_counts,
        },
        # Replaces the old "files" block.  That block paired "python_scanned"
        # with "python_unparseable" although the two counted different
        # populations -- a content prefilter removed 275 of 285 files before
        # anything was parsed.  Each stage below is a funnel whose exits are
        # all named, so the parts add up to the population above them.
        "accounting": {
            "python": found.python,
            "json": found.json,
            "csv": found.csv,
            "binding": {
                "candidate_pairs": len(csv_nodes)
                * sum(1 for node in schema_nodes if node.fields),
                "excluded_no_field_overlap": (
                    len(csv_nodes) * sum(1 for node in schema_nodes if node.fields)
                    - len(proposals)
                ),
                "excluded_schema_without_properties": (
                    len(csv_nodes)
                    * sum(1 for node in schema_nodes if not node.fields)
                ),
                "proposals": len(proposals),
                "verified": sum(1 for item in proposals if item["status"] == VERIFIED),
                "rejected": sum(1 for item in proposals if item["status"] == REJECTED),
                "indeterminate": sum(
                    1 for item in proposals if item["status"] == INDETERMINATE
                ),
            },
        },
        # The outer denominator: how big is the population the frozen scope
        # leaves out, and for which stated reason.
        "census": census(root, scope),
        "nodes": {
            "total": len(all_nodes),
            "sqlite_table": len(sqlite_nodes),
            "sqlite_table_incomplete": sum(
                1 for node in sqlite_nodes if not node.complete
            ),
            "json_schema": sum(1 for node in schema_nodes if node.kind == "json.schema"),
            "json_schema_def": sum(
                1 for node in schema_nodes if node.kind == "json.schema.def"
            ),
            "csv_table": len(csv_nodes),
            # Honest accounting: a $defs entry that declares a scalar type
            # (string/pattern/enum) legitimately has no fields.  It is a type
            # declaration, not a record shape, and is counted as such.
            "json_schema_def_scalar": sum(
                1
                for node in schema_nodes
                if node.kind == "json.schema.def" and not node.fields
            ),
            "with_zero_fields": sum(1 for node in all_nodes if not node.fields),
        },
        "fields": {
            "total": field_total,
            "sqlite": sum(len(node.fields) for node in sqlite_nodes),
            "json_schema": sum(len(node.fields) for node in schema_nodes),
            "csv": sum(len(node.fields) for node in csv_nodes),
            "declared_type": typed_fields,
            "inferred_type": sum(
                1
                for node in all_nodes
                for item in node.fields
                if item.type_source == "inferred"
            ),
            "no_type": sum(
                1
                for node in all_nodes
                for item in node.fields
                if item.type_source == "none"
            ),
            "line_anchored": sum(
                1
                for node in all_nodes
                for item in node.fields
                if re.search(r"#L\d+", item.locator)
            ),
            "pointer_anchored": sum(
                1
                for node in all_nodes
                for item in node.fields
                if "#/" in item.locator
            ),
            "unanchored": sum(
                1
                for node in all_nodes
                for item in node.fields
                if "#" not in item.locator
            ),
        },
        "edges": {
            "total": len(edges),
            "sqlite_foreign_key": sum(
                1 for edge in edges if edge.kind == "sqlite.foreign_key"
            ),
            "json_ref": sum(1 for edge in edges if edge.kind == "json.ref"),
            "json_ref_internal": sum(
                1 for edge in edges if edge.kind == "json.ref" and edge.dst.startswith("#")
            ),
            "sqlite_index_statements": indexes,
        },
        "naive_ddl_baseline": {
            "statements_on_raw_lines": naive_seen,
            "complete_body_on_one_line": naive_complete,
            "ast_folded_tables": len(sqlite_nodes),
        },
        "duplicate_table_declarations": duplicate_declarations(sqlite_nodes),
        # NOT "cross_plane_candidates".  Both endpoints are data-plane nodes
        # and the section 6 verifier record is incomplete, so these are
        # intra-data-plane proposals and nothing may promote them to edges.
        "intra_data_bindings": {
            "trusted_cross_plane_edges": 0,
            "sec6_inputs_present": list(SEC6_INPUTS_PRESENT),
            "sec6_inputs_missing": list(SEC6_INPUTS_MISSING),
            "proposals": len(proposals),
            "verified": sum(1 for item in proposals if item["status"] == VERIFIED),
            "rejected": sum(1 for item in proposals if item["status"] == REJECTED),
            "indeterminate": sum(
                1 for item in proposals if item["status"] == INDETERMINATE
            ),
            "detail": proposals,
        },
        "unparseable_python": found.unparseable_python,
        "unreadable_python": found.unreadable_python,
        "unparseable_json": found.unparseable_json,
        "unreadable_json": found.unreadable_json,
        "unreadable_csv": found.unreadable_csv,
    }


def node_records(root: Path, scope: Scope = Scope()) -> list[dict]:
    """Full node dump -- the artifact contract a Gate 2 builder would consume.

    Same walk as ``probe``, so the dump and the counts can never disagree.
    """
    records = collect(root, scope).all_nodes
    return [
        {
            "node_id": node.node_id,
            "kind": node.kind,
            "name": node.name,
            "locator": node.locator,
            "complete": node.complete,
            "notes": list(node.notes),
            "meta": node.meta,
            "fields": [
                {
                    "name": item.name,
                    "declared_type": item.declared_type,
                    "type_source": item.type_source,
                    "flags": list(item.flags),
                    "locator": item.locator,
                }
                for item in node.fields
            ],
        }
        for node in records
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[3]),
        help="repository root to scan (default: this checkout)",
    )
    parser.add_argument(
        "--nodes", action="store_true", help="print the full node list instead"
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    payload = node_records(root) if args.nodes else probe(root)
    json.dump(payload, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

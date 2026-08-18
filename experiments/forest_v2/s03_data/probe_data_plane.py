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
    """(text, lineno, end_lineno, is_complete) for every DDL-bearing literal."""
    found: list[tuple[str, int, int, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
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
    tree = ast.parse(source)
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
def _infer(values: list[str]) -> str | None:
    kept = [value for value in values if value != ""]
    if not kept:
        return None
    try:
        for value in kept:
            int(value)
        return "integer"
    except ValueError:
        pass
    try:
        for value in kept:
            float(value)
        return "number"
    except ValueError:
        pass
    return "string"


def extract_csv(text: str, rel_path: str, sample_rows: int = 50) -> list[DataNode]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    samples: list[list[str]] = []
    for index, row in enumerate(reader):
        if index >= sample_rows:
            break
        samples.append(row)
    fields: list[Field] = []
    for column, name in enumerate(header):
        column_values = [row[column] for row in samples if len(row) > column]
        inferred = _infer(column_values)
        fields.append(
            Field(
                name=name.strip(),
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
            notes=(f"sampled_rows={len(samples)}",),
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


# --- cross-plane candidate check -------------------------------------------
_JSON_TO_CSV_TYPE = {
    "integer": {"integer"},
    "number": {"integer", "number"},
    "string": {"string", "integer", "number"},
    "boolean": {"string"},
}


def bind_csv_to_schema(
    csv_nodes: list[DataNode], schema_nodes: list[DataNode]
) -> list[dict]:
    """Propose data<->data bindings and verify them against declared types.

    A proposal is only ``verified`` when the CSV header is a subset of the
    schema's property names AND every inferred column type is admissible for
    the declared property type.  Unverified proposals stay proposals -- that
    is the section 6 rule applied to the cheapest possible hypothesis source.
    """
    proposals: list[dict] = []
    for csv_node in csv_nodes:
        csv_names = [item.name for item in csv_node.fields]
        if not csv_names:
            continue
        for schema_node in schema_nodes:
            schema_types = {
                item.name: item.declared_type for item in schema_node.fields
            }
            if not schema_types:
                continue
            overlap = [name for name in csv_names if name in schema_types]
            if not overlap:
                continue
            subset = len(overlap) == len(csv_names)
            mismatches = []
            for item in csv_node.fields:
                declared = schema_types.get(item.name)
                if declared is None or item.declared_type is None:
                    continue
                allowed = _JSON_TO_CSV_TYPE.get(declared)
                if allowed is not None and item.declared_type not in allowed:
                    mismatches.append(
                        f"{item.name}: csv={item.declared_type} schema={declared}"
                    )
            proposals.append(
                {
                    "csv": csv_node.locator,
                    "schema": schema_node.locator,
                    "overlap": len(overlap),
                    "csv_fields": len(csv_names),
                    "header_is_subset": subset,
                    "type_mismatches": mismatches,
                    "verified": subset and not mismatches,
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


# --- probe ------------------------------------------------------------------
def probe(root: Path) -> dict:
    sqlite_nodes: list[DataNode] = []
    schema_nodes: list[DataNode] = []
    csv_nodes: list[DataNode] = []
    edges: list[DataEdge] = []
    indexes = 0
    unparseable: list[str] = []
    naive_seen = 0
    naive_complete = 0

    python_files = _iter_files(root, DDL_ROOTS, ".py")
    ddl_files = 0
    for path in python_files:
        source = path.read_text(encoding="utf-8", errors="replace")
        if "CREATE TABLE" not in source.upper():
            continue
        ddl_files += 1
        rel_path = _rel(root, path)
        try:
            nodes, file_edges, file_indexes = extract_sqlite(source, rel_path)
        except SyntaxError:
            unparseable.append(rel_path)
            continue
        sqlite_nodes.extend(nodes)
        edges.extend(file_edges)
        indexes += file_indexes
        seen, complete = naive_sqlite_baseline(source)
        naive_seen += seen
        naive_complete += complete

    json_files = _iter_files(root, JSON_ROOTS, ".json")
    json_documents = 0
    json_unparseable: list[str] = []
    for path in json_files:
        rel_path = _rel(root, path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            json_unparseable.append(rel_path)
            continue
        if not _is_schema(document):
            json_documents += 1
            continue
        nodes, file_edges = extract_json_schema(document, rel_path)
        schema_nodes.extend(nodes)
        edges.extend(file_edges)

    csv_files = _iter_files(root, CSV_ROOTS, ".csv")
    for path in csv_files:
        rel_path = _rel(root, path)
        csv_nodes.extend(
            extract_csv(path.read_text(encoding="utf-8", errors="replace"), rel_path)
        )

    all_nodes = sqlite_nodes + schema_nodes + csv_nodes
    field_total = sum(len(node.fields) for node in all_nodes)
    typed_fields = sum(
        1 for node in all_nodes for item in node.fields if item.type_source == "declared"
    )
    excluded_counts = {}
    for name in DOCUMENTED_EXCLUSIONS:
        base = root / name
        excluded_counts[name] = (
            sum(1 for path in base.rglob("*") if path.is_file()) if base.exists() else 0
        )

    proposals = bind_csv_to_schema(csv_nodes, schema_nodes)

    return {
        "probe": "s03_data.data_plane_extraction",
        "revision": git_revision(root),
        "scope": {
            "ddl_roots": list(DDL_ROOTS),
            "json_roots": list(JSON_ROOTS),
            "csv_roots": list(CSV_ROOTS),
            "documented_exclusions": excluded_counts,
        },
        "files": {
            "python_scanned": len(python_files),
            "python_with_ddl": ddl_files,
            "python_unparseable": len(unparseable),
            "json_scanned": len(json_files),
            "json_schema_documents": len(
                {node.locator.split("#")[0] for node in schema_nodes}
            ),
            "json_plain_documents": json_documents,
            "json_unparseable": len(json_unparseable),
            "csv_scanned": len(csv_files),
        },
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
        "cross_plane_candidates": {
            "proposals": len(proposals),
            "verified": sum(1 for item in proposals if item["verified"]),
            "detail": proposals,
        },
        "unparseable_python": unparseable,
        "unparseable_json": json_unparseable,
    }


def node_records(root: Path) -> list[dict]:
    """Full node dump -- the artifact contract a Gate 2 builder would consume."""
    records: list[dict] = []
    for path in _iter_files(root, DDL_ROOTS, ".py"):
        source = path.read_text(encoding="utf-8", errors="replace")
        if "CREATE TABLE" not in source.upper():
            continue
        try:
            nodes, _, _ = extract_sqlite(source, _rel(root, path))
        except SyntaxError:
            continue
        records.extend(nodes)
    for path in _iter_files(root, JSON_ROOTS, ".json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        nodes, _ = extract_json_schema(document, _rel(root, path))
        records.extend(nodes)
    for path in _iter_files(root, CSV_ROOTS, ".csv"):
        records.extend(
            extract_csv(
                path.read_text(encoding="utf-8", errors="replace"), _rel(root, path)
            )
        )
    return [
        {
            "node_id": node.node_id,
            "kind": node.kind,
            "name": node.name,
            "locator": node.locator,
            "complete": node.complete,
            "notes": list(node.notes),
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

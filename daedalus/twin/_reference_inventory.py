"""Deterministic AST, data-schema, and Markdown inventories."""
from __future__ import annotations

import ast
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping
from urllib.parse import unquote, urlsplit

from ..structcore.forest import ForestEdge, ForestNode
from ._reference_common import ReferenceCompileError, decode_text

_MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


@dataclass
class Inventory:
    nodes: list[ForestNode]
    edges: list[ForestEdge]
    plane_nodes: dict[str, set[str]]
    dataclass_fields: dict[str, set[tuple[str, str]]]
    csv_fields: dict[str, set[str]]
    schema_fields: dict[str, set[str]]
    wiki_links: dict[str, set[str]]


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _python(path: str, text: str):
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise ReferenceCompileError(f"Python parse failed for {path}: {exc}") from exc
    code = [ForestNode(f"code:file:{path}", "source_file", {"path": path})]
    types: list[ForestNode] = []
    edges: list[ForestEdge] = []
    fields: set[tuple[str, str]] = set()
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbol = f"code:symbol:{path}#{item.name}"
            code.append(ForestNode(symbol, "symbol", {"path": path, "name": item.name}))
            edges.append(ForestEdge(f"code:file:{path}", symbol, "declares_symbol", True, evidence=(path,)))
        if not isinstance(item, ast.ClassDef):
            continue
        if "dataclass" not in {_decorator_name(d) for d in item.decorator_list}:
            continue
        type_id = f"type:{path}#{item.name}"
        types.append(ForestNode(type_id, "type", {"path": path, "name": item.name}))
        for member in item.body:
            if not isinstance(member, ast.AnnAssign) or not isinstance(member.target, ast.Name):
                continue
            name = member.target.id
            field_id = f"type:field:{path}#{item.name}.{name}"
            types.append(ForestNode(field_id, "field", {"path": path, "type": item.name, "name": name}))
            edges.append(ForestEdge(type_id, field_id, "has_field", True, evidence=(path,)))
            fields.add((item.name, name))
    return code, types, edges, fields


def _csv(path: str, text: str):
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ReferenceCompileError(f"CSV file is empty: {path}") from exc
    columns = tuple(column.strip() for column in header)
    if not columns or any(not column for column in columns) or len(set(columns)) != len(columns):
        raise ReferenceCompileError(f"CSV header is invalid: {path}")
    table = f"data:table:{path}"
    nodes = [ForestNode(table, "data_table", {"path": path})]
    edges = []
    for column in columns:
        field = f"data:field:{path}#{column}"
        nodes.append(ForestNode(field, "data_field", {"path": path, "name": column}))
        edges.append(ForestEdge(table, field, "has_column", True, evidence=(path,)))
    return nodes, edges, set(columns)


def _schema(path: str, text: str):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReferenceCompileError(f"JSON parse failed for {path}: {exc}") from exc
    properties = payload.get("properties") if isinstance(payload, Mapping) else None
    if payload.get("type") != "object" or not isinstance(properties, Mapping) or not properties:
        raise ReferenceCompileError(f"JSON Schema must be a non-empty object schema: {path}")
    schema = f"data:schema:{path}"
    nodes = [ForestNode(schema, "data_schema", {"path": path})]
    edges = []
    for name in sorted(properties):
        if not isinstance(name, str) or not name:
            raise ReferenceCompileError(f"JSON Schema property name is invalid: {path}")
        field = f"data:schema-field:{path}#{name}"
        nodes.append(ForestNode(field, "data_schema_field", {"path": path, "name": name}))
        edges.append(ForestEdge(schema, field, "has_property", True, evidence=(path,)))
    return nodes, edges, set(properties)


def normalized_link(wiki_file: str, raw_target: str) -> str:
    target = raw_target.strip().split()[0].strip("<>")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return "external"
    if not parsed.path:
        return "fragment"
    decoded = unquote(parsed.path)
    if "\\" in decoded:
        raise ReferenceCompileError(f"Markdown link must use POSIX paths: {wiki_file} -> {target}")
    parts: list[str] = []
    for part in PurePosixPath(wiki_file).parent.joinpath(decoded).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ReferenceCompileError(f"Markdown link escapes project: {wiki_file} -> {target}")
            parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts).as_posix()


def _markdown(path: str, text: str):
    source = f"knowledge:doc:{path}"
    links: set[str] = set()
    edges: list[ForestEdge] = []
    for raw in _MD_LINK_RE.findall(text):
        target = normalized_link(path, raw)
        if target in {"external", "fragment"}:
            continue
        links.add(target)
        if target.endswith(".md"):
            edges.append(ForestEdge(source, f"knowledge:doc:{target}", "links_to", True, evidence=(path,)))
    return ForestNode(source, "document", {"path": path}), links, edges


def build_inventory(
    root: Path,
    *,
    code_files: tuple[str, ...],
    data_files: tuple[str, ...],
    knowledge_files: tuple[str, ...],
    file_bytes: Mapping[str, bytes],
) -> Inventory:
    inv = Inventory([], [], {p: set() for p in ("code", "type", "data", "knowledge")}, {}, {}, {}, {})
    for path in code_files:
        code, types, edges, fields = _python(path, decode_text(file_bytes[path], path))
        inv.dataclass_fields[path] = fields
        inv.nodes.extend(code + types)
        inv.edges.extend(edges)
        inv.plane_nodes["code"].update(n.id for n in code)
        inv.plane_nodes["type"].update(n.id for n in types)
    if not inv.plane_nodes["type"]:
        raise ReferenceCompileError("reference project must expose at least one dataclass-backed type")
    for path in data_files:
        text = decode_text(file_bytes[path], path)
        if path.endswith(".csv"):
            nodes, edges, fields = _csv(path, text)
            inv.csv_fields[path] = fields
        else:
            nodes, edges, fields = _schema(path, text)
            inv.schema_fields[path] = fields
        inv.nodes.extend(nodes)
        inv.edges.extend(edges)
        inv.plane_nodes["data"].update(n.id for n in nodes)
    declared = set(code_files + data_files + knowledge_files)
    for path in knowledge_files:
        node, links, edges = _markdown(path, decode_text(file_bytes[path], path))
        inv.nodes.append(node)
        inv.edges.extend(edges)
        inv.wiki_links[path] = links
        inv.plane_nodes["knowledge"].add(node.id)
        for target in sorted(links):
            if target not in declared and not (root / target).is_file():
                raise ReferenceCompileError(f"broken local Markdown link: {path} -> {target}")
    if len({n.id for n in inv.nodes}) != len(inv.nodes):
        raise ReferenceCompileError("compiled node identities are not unique")
    return inv

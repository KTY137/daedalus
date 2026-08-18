"""EXPERIMENT s08 — build four single-plane document sets and a code-only graph.

Scope is deliberately narrow and *declared*, because an undeclared corpus makes
every retrieval number unfalsifiable:

* **code** — ``*.py`` under the same three packages the earlier forest_v2
  probes used (``daedalus``, ``tools``, ``runs``).  One document per module.
* **type** — derived from those same modules: declared parameter/return
  annotations, annotated assignments, and class bases.  The tree carries no
  ``.pyi``, so this plane is an honest *proxy* built from source annotations,
  not an independent artifact class.
* **data** — schema-shaped files (``.json``, ``.csv``, ``.toml``, ``.yaml``)
  under ``daedalus``, ``docs`` and the repository root.  Content is reduced to
  *shape*: JSON key paths, CSV headers, YAML/TOML keys — never values.  Two
  reasons: the Data plane is about schemas/fields/formats, and a values-free
  index cannot accidentally carry a secret into an experiment artifact.
  ``runs/**/*.json`` (3329 receipt files) is EXCLUDED: those are evidence
  artifacts, not the Data plane.
* **knowledge** — ``*.md`` under ``docs``, ``runs`` and the repository root.

Pure stdlib.  Read-only: this module opens files and never writes one.
"""
from __future__ import annotations

import ast
import csv
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from s08_api import Document

CODE_ROOTS: tuple[str, ...] = ("daedalus", "tools", "runs")
KNOWLEDGE_ROOTS: tuple[str, ...] = ("docs", "runs")
DATA_ROOTS: tuple[str, ...] = ("daedalus", "docs")
DATA_SUFFIXES: frozenset[str] = frozenset({".json", ".csv", ".toml", ".yaml", ".yml"})
SKIP_DIR_PARTS: frozenset[str] = frozenset(
    {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
)
MAX_FILE_BYTES = 256 * 1024
MAX_DOC_CHARS = 200_000
MAX_JSON_KEYPATHS = 400
MAX_CSV_ROWS = 3

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")
_YAML_KEY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*:")

STOPWORDS: frozenset[str] = frozenset(
    """a an and are as at be but by for from has have if in into is it its of on or
    that the their then there these this to was were will with not none true false
    self cls return def class import if else elif try except finally raise pass
    """.split()
)


def split_identifier(word: str) -> list[str]:
    """``load_env`` -> ``[load, env]``; ``DeepSeekProvider`` -> ``[deep, seek, provider]``."""
    parts: list[str] = []
    for chunk in word.split("_"):
        if not chunk:
            continue
        parts.extend(m.group(0).lower() for m in _CAMEL.finditer(chunk))
    return [p for p in parts if p]


def tokenize(text: str) -> list[str]:
    """Identifier-aware tokenizer: the whole identifier AND its parts are kept."""
    tokens: list[str] = []
    for match in _IDENT.finditer(text):
        word = match.group(0)
        low = word.lower()
        if len(low) > 1 and low not in STOPWORDS:
            tokens.append(low)
        parts = split_identifier(word)
        if len(parts) > 1:
            tokens.extend(p for p in parts if len(p) > 1 and p not in STOPWORDS)
    return tokens


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_PARTS for part in path.parts)


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_DOC_CHARS]
    except OSError:
        return None


def module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


# --------------------------------------------------------------------------- code


@dataclass
class ModuleFacts:
    """What the code plane knows about one module, without executing it."""

    module: str
    locator: str
    symbols: tuple[str, ...]
    imports: tuple[str, ...]  # repo-internal module names, import edges
    calls: dict[str, int]  # repo-internal module name -> resolved call-site count
    annotations: tuple[str, ...]
    docstrings: tuple[tuple[str, str], ...]  # (symbol, first docstring sentence)


class _ModuleVisitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.symbols: list[str] = []
        self.bindings: dict[str, str] = {}  # local name -> module it came from
        self.module_aliases: dict[str, str] = {}  # alias -> module
        self.raw_imports: list[str] = []
        self.call_names: list[str] = []
        self.annotations: list[str] = []
        self.docstrings: list[tuple[str, str]] = []
        self._depth = 0

    # imports ------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.raw_imports.append(alias.name)
            self.module_aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:  # relative import
            parent = self.module.split(".")[: -node.level] if self.module else []
            base = ".".join([*parent, base]) if base else ".".join(parent)
        if base:
            self.raw_imports.append(base)
        for alias in node.names:
            self.bindings[alias.asname or alias.name] = base
        self.generic_visit(node)

    # definitions --------------------------------------------------------
    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self._depth == 0:
            self.symbols.append(node.name)
        for arg in [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]:
            if arg.annotation is not None:
                self.annotations.append(ast.unparse(arg.annotation))
        if node.returns is not None:
            self.annotations.append(ast.unparse(node.returns))
        doc = ast.get_docstring(node)
        if doc:
            self.docstrings.append((node.name, doc))
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_FunctionDef = _function  # type: ignore[assignment]
    visit_AsyncFunctionDef = _function  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self._depth == 0:
            self.symbols.append(node.name)
        for base in node.bases:
            self.annotations.append(ast.unparse(base))
        doc = ast.get_docstring(node)
        if doc:
            self.docstrings.append((node.name, doc))
        self._depth += 1
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.symbols.append(f"{node.name}.{child.name}")
        self.generic_visit(node)
        self._depth -= 1

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.annotations.append(ast.unparse(node.annotation))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name:
            self.call_names.append(name)
        self.generic_visit(node)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _first_sentence(text: str) -> str:
    line = " ".join(text.strip().split())
    for stop in (". ", "! ", "? "):
        idx = line.find(stop)
        if idx > 0:
            return line[: idx + 1]
    return line[:200]


def parse_module(root: Path, path: Path) -> tuple[ModuleFacts, str, "_ModuleVisitor"] | None:
    """AST-parse one module once.  Returns (facts, source, visitor) or None.

    The visitor is handed back so the graph pass can reuse the import bindings
    instead of re-parsing the whole tree a second time.
    """
    source = _read_text(path)
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    mod = module_name(root, path)
    visitor = _ModuleVisitor(mod)
    visitor.visit(tree)
    facts = ModuleFacts(
        module=mod,
        locator=path.relative_to(root).as_posix(),
        symbols=tuple(visitor.symbols),
        imports=tuple(visitor.raw_imports),
        calls={},
        annotations=tuple(visitor.annotations),
        docstrings=tuple((s, _first_sentence(d)) for s, d in visitor.docstrings),
    )
    return facts, source, visitor


# --------------------------------------------------------------------------- data


def _json_keypaths(text: str) -> list[str]:
    """Reduce a JSON document to its key paths.  Values are never indexed."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return []
    paths: list[str] = []

    def walk(node: object, prefix: str) -> None:
        if len(paths) >= MAX_JSON_KEYPATHS:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                paths.append(path)
                walk(value, path)
        elif isinstance(node, list) and node:
            walk(node[0], f"{prefix}[]")

    walk(data, "")
    return paths[:MAX_JSON_KEYPATHS]


def _csv_shape(text: str) -> list[str]:
    """Header plus a few rows: the Data plane's format signal, bounded."""
    try:
        reader = csv.reader(io.StringIO(text))
        rows = [row for _, row in zip(range(MAX_CSV_ROWS + 1), reader)]
    except (csv.Error, ValueError):
        return []
    return [" ".join(cell for cell in row if cell) for row in rows]


def _keyish_lines(text: str) -> list[str]:
    return [m.group(1) for line in text.splitlines() if (m := _YAML_KEY.match(line))]


def data_document_text(path: Path, text: str) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "\n".join(_json_keypaths(text))
    if suffix == ".csv":
        return "\n".join(_csv_shape(text))
    return "\n".join(_keyish_lines(text))


# --------------------------------------------------------------------------- corpus


@dataclass
class Corpus:
    """Four single-plane document sets plus the code-only graph over the code plane."""

    root: Path
    docs: dict[str, Document] = field(default_factory=dict)
    by_plane: dict[str, list[Document]] = field(default_factory=lambda: defaultdict(list))
    modules: dict[str, ModuleFacts] = field(default_factory=dict)  # module name -> facts
    doc_id_by_module: dict[str, str] = field(default_factory=dict)
    edges: dict[tuple[str, str], float] = field(default_factory=dict)  # undirected, module pair
    stats: dict[str, object] = field(default_factory=dict)

    def add(self, doc: Document) -> None:
        self.docs[doc.doc_id] = doc
        self.by_plane[doc.plane].append(doc)

    _adjacency: dict[str, list[tuple[str, float]]] | None = None

    def adjacency(self) -> dict[str, list[tuple[str, float]]]:
        """Undirected adjacency, built once from the edge set."""
        if self._adjacency is None:
            adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
            for (a, b), w in self.edges.items():
                adj[a].append((b, w))
                adj[b].append((a, w))
            self._adjacency = dict(adj)
        return self._adjacency

    def neighbours(self, module: str) -> list[tuple[str, float]]:
        return self.adjacency().get(module, [])


def _iter_files(root: Path, sub: str, suffixes: frozenset[str]) -> list[Path]:
    base = root / sub
    if not base.is_dir():
        return []
    return sorted(
        p
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in suffixes and not _is_skipped(p)
    )


def build_corpus(root: Path) -> Corpus:
    """Read the tree once and produce every plane plus the code graph."""
    root = Path(root)
    corpus = Corpus(root=root)
    skipped_unparseable = 0
    oversize = 0

    # --- code plane + module facts
    code_files: list[Path] = []
    visitors: dict[str, _ModuleVisitor] = {}
    for sub in CODE_ROOTS:
        code_files.extend(_iter_files(root, sub, frozenset({".py"})))
    for path in code_files:
        parsed = parse_module(root, path)
        if parsed is None:
            if _read_text(path) is None:
                oversize += 1
            else:
                skipped_unparseable += 1
            continue
        facts, source, visitor = parsed
        visitors[facts.module] = visitor
        locator = facts.locator
        doc = Document(
            doc_id=f"code:{locator}",
            plane="code",
            locator=locator,
            text=source,
            symbols=facts.symbols,
            tokens=tuple(tokenize(source)),
        )
        corpus.add(doc)
        corpus.modules[facts.module] = facts
        corpus.doc_id_by_module[facts.module] = doc.doc_id

    # --- code graph: import edges + call edges resolved through import bindings
    _build_graph(corpus, visitors)

    # --- type plane (derived proxy)
    empty_type = 0
    for module, facts in corpus.modules.items():
        text = "\n".join(facts.annotations)
        if not text.strip():
            empty_type += 1
            continue
        locator = facts.locator
        corpus.add(
            Document(
                doc_id=f"type:{locator}",
                plane="type",
                locator=locator,
                text=text,
                symbols=facts.symbols,
                tokens=tuple(tokenize(text)),
            )
        )

    # --- data plane
    data_files: list[Path] = []
    for sub in DATA_ROOTS:
        data_files.extend(_iter_files(root, sub, DATA_SUFFIXES))
    data_files.extend(
        sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in DATA_SUFFIXES)
    )
    empty_data = 0
    for path in data_files:
        text = _read_text(path)
        if text is None:
            oversize += 1
            continue
        shaped = data_document_text(path, text)
        if not shaped.strip():
            empty_data += 1
            continue
        locator = path.relative_to(root).as_posix()
        corpus.add(
            Document(
                doc_id=f"data:{locator}",
                plane="data",
                locator=locator,
                text=shaped,
                tokens=tuple(tokenize(shaped)),
            )
        )

    # --- knowledge plane
    knowledge_files: list[Path] = []
    for sub in KNOWLEDGE_ROOTS:
        knowledge_files.extend(_iter_files(root, sub, frozenset({".md"})))
    knowledge_files.extend(sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".md"))
    for path in knowledge_files:
        text = _read_text(path)
        if text is None:
            oversize += 1
            continue
        locator = path.relative_to(root).as_posix()
        corpus.add(
            Document(
                doc_id=f"knowledge:{locator}",
                plane="knowledge",
                locator=locator,
                text=text,
                tokens=tuple(tokenize(text)),
            )
        )

    corpus.stats = {
        "docs_total": len(corpus.docs),
        "docs_per_plane": {p: len(corpus.by_plane.get(p, [])) for p in ("code", "type", "data", "knowledge")},
        "modules": len(corpus.modules),
        "graph_edges": len(corpus.edges),
        "code_files_seen": len(code_files),
        "unparseable_code_files": skipped_unparseable,
        "oversize_files_skipped": oversize,
        "modules_without_annotations": empty_type,
        "data_files_without_shape": empty_data,
        "tokens_total": sum(len(d.tokens) for d in corpus.docs.values()),
    }
    return corpus


def _resolve_repo_module(name: str, corpus: Corpus) -> str | None:
    """Longest-prefix match of a dotted name against the repo's own module set."""
    parts = name.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = ".".join(parts[:cut])
        if candidate in corpus.modules:
            return candidate
    return None


def _build_graph(corpus: Corpus, visitors: dict[str, "_ModuleVisitor"]) -> None:
    """Undirected weighted graph: import edges (1.0) + resolved call edges (0.5 each, capped).

    Edge weights are frozen a priori (import 1.0, call 0.5 per site up to 10);
    they were not tuned against the evaluation.
    """
    for mod, visitor in visitors.items():
        call_targets: dict[str, int] = defaultdict(int)
        for raw in visitor.raw_imports:
            target = _resolve_repo_module(raw, corpus)
            if target and target != mod:
                _add_edge(corpus, mod, target, 1.0)
        for call in visitor.call_names:
            head = call.split(".")[0]
            origin = visitor.bindings.get(head) or visitor.module_aliases.get(head)
            if not origin:
                continue
            target = _resolve_repo_module(origin, corpus)
            if target and target != mod:
                call_targets[target] += 1
        for target, count in call_targets.items():
            _add_edge(corpus, mod, target, min(count, 10) * 0.5)
        corpus.modules[mod].calls = dict(call_targets)


def _add_edge(corpus: Corpus, a: str, b: str, weight: float) -> None:
    key = (a, b) if a < b else (b, a)
    corpus.edges[key] = corpus.edges.get(key, 0.0) + weight

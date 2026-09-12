"""Grey Matter: the latent atlas Ikarus thinks with.

A regenerable index over ingested repositories (Masterplan Â§5/Â§6/Â§9.1):

* **Node Cards** -- one card per module, class, function, type, schema, table,
  document section. Each carries plane (code/type/data/knowledge), repository,
  revision, locator, compact content and provenance.
* **Embeddings** -- deterministic hashed token features (no third-party
  dependency, reproducible across hosts). ``embed()`` is the single door, so a
  learned backend can replace it behind the same contract later.
* **Relation tensor** -- the sparse planeÃ—planeÃ—relation count projection of
  a repository's intra- and cross-plane edges. It is a *projection* of the
  card graph, never candidate identity.
* **Binding proposals** -- cross-plane similarities above a threshold are
  recorded as *proposals* with score; a literal-evidence verifier marks the
  ones the source itself supports. Unverified proposals stay proposals.

Everything is SQLite in one file; the store is a projection and may be
deleted and rebuilt from the corpus at any time.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import struct
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

PLANES = ("code", "type", "data", "knowledge")
DIMENSION = 256
SKIP_DIRS = frozenset({".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", ".mypy_cache",
                       ".pytest_cache", ".ruff_cache", "target", ".next", ".nuxt", "coverage", ".tox", "runs",
                       ".daedalus_worktrees", ".idea", ".vscode", "vendor", "site-packages"})
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 20_000
MAX_CARD_TEXT = 1200
PROPOSAL_THRESHOLD = 0.55
SCHEMA_VERSION = "grey-matter/1"

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", re.M)
_JS_CLASS = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)(?:\s+extends\s+([A-Za-z_$][\w$.]*))?", re.M)
_JS_CONST_FN = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", re.M)
_JS_IMPORT = re.compile(r"^\s*import\s+(?:[^'\"]+\s+from\s+)?['\"]([^'\"]+)['\"]", re.M)
_JS_REQUIRE = re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)")
_TS_TYPE = re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.M)
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_SQL_TABLE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?[`\"\[]?([A-Za-z_][\w.]*)", re.I)
_SQL_COLUMN = re.compile(r"^\s*[`\"\[]?([A-Za-z_]\w*)[`\"\]]?\s+[A-Za-z]+", re.M)
_CODE_SUFFIXES = {".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
                  ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript"}
_DATA_SUFFIXES = {".json", ".csv", ".sql", ".yaml", ".yml", ".toml"}
_KNOWLEDGE_SUFFIXES = {".md", ".rst", ".txt"}


@dataclass(frozen=True)
class NodeCard:
    card_id: str
    repo_id: str
    plane: str
    kind: str
    name: str
    locator: str
    text: str
    revision: str
    neighborhood: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"card_id": self.card_id, "repo_id": self.repo_id, "plane": self.plane, "kind": self.kind,
                "name": self.name, "locator": self.locator, "text": self.text, "revision": self.revision,
                "neighborhood": list(self.neighborhood)}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    evidence: str


# --------------------------------------------------------------------------- #
# Embedding                                                                    #
# --------------------------------------------------------------------------- #
def tokens(text: str) -> list[str]:
    out: list[str] = []
    for ident in _IDENT.findall(text or ""):
        parts = [p for p in re.split(r"_+", ident) if p]
        for part in parts:
            for sub in _CAMEL.split(part):
                sub = sub.lower()
                if len(sub) > 1:
                    out.append(sub)
    return out


def embed(text: str, dimension: int = DIMENSION) -> list[float]:
    """Deterministic hashed unigram+bigram features, L2-normalised."""
    vector = [0.0] * dimension
    toks = tokens(text)
    features = list(toks) + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    if not features:
        return vector
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def _pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


# --------------------------------------------------------------------------- #
# Extraction                                                                   #
# --------------------------------------------------------------------------- #
def _card_id(repo_id: str, locator: str, plane: str, name: str, kind: str = "") -> str:
    return hashlib.sha256(f"{repo_id}\n{plane}\n{locator}\n{kind}\n{name}".encode("utf-8")).hexdigest()[:24]


def _clip(text: str, limit: int = MAX_CARD_TEXT) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " â€¦"


def iter_files(root: Path) -> Iterator[Path]:
    count = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith(".") and entry.name not in {".github"}:
                    continue
                stack.append(entry)
                continue
            if not entry.is_file():
                continue
            try:
                if entry.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            count += 1
            if count > MAX_FILES:
                return
            yield entry


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _python_cards(repo_id: str, rel: str, source: str, revision: str) -> tuple[list[NodeCard], list[Edge]]:
    cards: list[NodeCard] = []
    edges: list[Edge] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # foreign corpus code may carry invalid escapes; not our defect
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return cards, edges
    module_name = rel[:-3].replace("/", ".").replace("\\", ".")
    module_doc = ast.get_docstring(tree) or ""
    module_card = NodeCard(_card_id(repo_id, rel, "code", module_name, "module"), repo_id, "code", "module", module_name, rel,
                           _clip(f"module {module_name}\n{module_doc}"), revision)
    cards.append(module_card)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if name:
                    edges.append(Edge(module_card.card_id, f"module:{name}", "imports", f"{rel}:{node.lineno}"))
    type_names: dict[str, list[str]] = {}

    def annotation_names(annotation: ast.AST | None) -> list[str]:
        if annotation is None:
            return []
        return [n.id for n in ast.walk(annotation) if isinstance(n, ast.Name)]

    for node in tree.body if isinstance(tree, ast.Module) else []:
        for item in ([node] + (node.body if isinstance(node, ast.ClassDef) else [])):
            if isinstance(item, ast.ClassDef):
                bases = [ast.unparse(b) for b in item.bases]
                doc = ast.get_docstring(item) or ""
                fields = [ast.unparse(s.target) + ": " + ast.unparse(s.annotation) for s in item.body
                          if isinstance(s, ast.AnnAssign)]
                is_type = any(d for d in bases if d in {"TypedDict", "Protocol", "Enum", "NamedTuple"}) or \
                    any(isinstance(d, ast.Name) and d.id == "dataclass" or isinstance(d, ast.Call) and
                        getattr(d.func, "id", "") == "dataclass" for d in item.decorator_list)
                plane = "type" if is_type else "code"
                text = f"class {item.name}({', '.join(bases)})\n{doc}\n" + "\n".join(fields)
                card = NodeCard(_card_id(repo_id, rel, plane, item.name), repo_id, plane,
                                "dataclass" if is_type else "class", item.name, f"{rel}:{item.lineno}",
                                _clip(text), revision, (module_card.card_id,))
                cards.append(card)
                edges.append(Edge(module_card.card_id, card.card_id, "declares", f"{rel}:{item.lineno}"))
                for base in bases:
                    edges.append(Edge(card.card_id, f"type:{base}", "extends", f"{rel}:{item.lineno}"))
                if is_type:
                    type_names.setdefault(item.name, []).append(card.card_id)
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = (ast.get_docstring(item) or "").splitlines()
                signature = f"def {item.name}({ast.unparse(item.args)})"
                if item.returns is not None:
                    signature += " -> " + ast.unparse(item.returns)
                owner = node.name + "." if isinstance(node, ast.ClassDef) and item is not node else ""
                name = owner + item.name
                card = NodeCard(_card_id(repo_id, rel, "code", name), repo_id, "code", "function", name,
                                f"{rel}:{item.lineno}", _clip(signature + "\n" + (doc[0] if doc else "")),
                                revision, (module_card.card_id,))
                cards.append(card)
                edges.append(Edge(module_card.card_id, card.card_id, "declares", f"{rel}:{item.lineno}"))
                annotated = set()
                for arg in list(item.args.args) + list(item.args.kwonlyargs):
                    annotated.update(annotation_names(arg.annotation))
                annotated.update(annotation_names(item.returns))
                for type_name in sorted(annotated):
                    if type_name[:1].isupper():
                        edges.append(Edge(card.card_id, f"type:{type_name}", "annotated_with", f"{rel}:{item.lineno}"))
    return cards, edges


def _js_cards(repo_id: str, rel: str, source: str, revision: str, language: str) -> tuple[list[NodeCard], list[Edge]]:
    cards: list[NodeCard] = []
    edges: list[Edge] = []
    module_name = re.sub(r"\.(m|c)?[jt]sx?$", "", rel).replace("\\", "/")
    first_comment = ""
    match = re.match(r"\s*(?:/\*\*?(.*?)\*/|//(.*))", source, re.S)
    if match:
        first_comment = (match.group(1) or match.group(2) or "").strip()[:300]
    module_card = NodeCard(_card_id(repo_id, rel, "code", module_name, "module"), repo_id, "code", "module", module_name, rel,
                           _clip(f"{language} module {module_name}\n{first_comment}"), revision)
    cards.append(module_card)
    for target in _JS_IMPORT.findall(source) + _JS_REQUIRE.findall(source):
        edges.append(Edge(module_card.card_id, f"module:{target}", "imports", rel))
    for regex, kind in ((_JS_FUNC, "function"), (_JS_CONST_FN, "function")):
        for found in regex.finditer(source):
            name = found.group(1)
            line = source.count("\n", 0, found.start()) + 1
            card = NodeCard(_card_id(repo_id, rel, "code", name), repo_id, "code", kind, name, f"{rel}:{line}",
                            _clip(found.group(0).strip()), revision, (module_card.card_id,))
            cards.append(card)
            edges.append(Edge(module_card.card_id, card.card_id, "declares", f"{rel}:{line}"))
    for found in _JS_CLASS.finditer(source):
        name = found.group(1)
        line = source.count("\n", 0, found.start()) + 1
        card = NodeCard(_card_id(repo_id, rel, "code", name), repo_id, "code", "class", name, f"{rel}:{line}",
                        _clip(found.group(0).strip()), revision, (module_card.card_id,))
        cards.append(card)
        edges.append(Edge(module_card.card_id, card.card_id, "declares", f"{rel}:{line}"))
        if found.group(2):
            edges.append(Edge(card.card_id, f"type:{found.group(2)}", "extends", f"{rel}:{line}"))
    if language == "typescript":
        for found in _TS_TYPE.finditer(source):
            name = found.group(1)
            line = source.count("\n", 0, found.start()) + 1
            end = source.find("\n\n", found.start())
            body = source[found.start(): end if end > 0 else found.start() + 600]
            card = NodeCard(_card_id(repo_id, rel, "type", name), repo_id, "type", "type", name, f"{rel}:{line}",
                            _clip(body), revision, (module_card.card_id,))
            cards.append(card)
            edges.append(Edge(module_card.card_id, card.card_id, "declares", f"{rel}:{line}"))
    return cards, edges


def _data_cards(repo_id: str, rel: str, source: str, revision: str) -> tuple[list[NodeCard], list[Edge]]:
    cards: list[NodeCard] = []
    edges: list[Edge] = []
    suffix = Path(rel).suffix.lower()
    name = Path(rel).name
    if suffix == ".json":
        try:
            payload = json.loads(source)
        except ValueError:
            return cards, edges
        keys = sorted(payload.keys())[:60] if isinstance(payload, dict) else []
        shape = f"json object keys: {', '.join(keys)}" if keys else f"json {type(payload).__name__}"
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            shape += "; row keys: " + ", ".join(sorted(payload[0].keys())[:40])
        cards.append(NodeCard(_card_id(repo_id, rel, "data", name), repo_id, "data", "json", name, rel, _clip(shape), revision))
    elif suffix == ".csv":
        try:
            header = next(csv.reader(io.StringIO(source)))
        except (StopIteration, csv.Error):
            return cards, edges
        cards.append(NodeCard(_card_id(repo_id, rel, "data", name), repo_id, "data", "csv", name, rel,
                              _clip("csv columns: " + ", ".join(h.strip() for h in header[:80])), revision))
    elif suffix == ".sql":
        for found in _SQL_TABLE.finditer(source):
            table = found.group(1)
            block_end = source.find(";", found.end())
            block = source[found.end(): block_end if block_end > 0 else found.end() + 800]
            columns = _SQL_COLUMN.findall(block)[:60]
            card = NodeCard(_card_id(repo_id, rel, "data", table), repo_id, "data", "table", table, rel,
                            _clip(f"table {table} columns: {', '.join(columns)}"), revision)
            cards.append(card)
    elif suffix in {".yaml", ".yml", ".toml"}:
        keys = re.findall(r"^([A-Za-z_][\w.-]*)\s*[:=]", source, re.M)[:60]
        if keys:
            cards.append(NodeCard(_card_id(repo_id, rel, "data", name), repo_id, "data", suffix[1:], name, rel,
                                  _clip(f"{suffix[1:]} keys: {', '.join(dict.fromkeys(keys))}"), revision))
    return cards, edges


def _knowledge_cards(repo_id: str, rel: str, source: str, revision: str) -> tuple[list[NodeCard], list[Edge]]:
    cards: list[NodeCard] = []
    edges: list[Edge] = []
    heading = Path(rel).stem
    buffer: list[str] = []
    start = 1

    def flush(end_line: int) -> None:
        body = "\n".join(buffer).strip()
        if not body and not heading:
            return
        card = NodeCard(_card_id(repo_id, rel, "knowledge", f"{heading}@{start}"), repo_id, "knowledge", "section",
                        heading, f"{rel}:{start}", _clip(f"{heading}\n{body}"), revision)
        cards.append(card)
        for _label, link in _MD_LINK.findall(body):
            if not link.startswith(("http://", "https://", "#", "mailto:")):
                edges.append(Edge(card.card_id, f"path:{link.split('#')[0]}", "references", f"{rel}:{start}"))
        for ident in set(re.findall(r"`([A-Za-z_][\w.]*)`", body)):
            edges.append(Edge(card.card_id, f"symbol:{ident}", "mentions", f"{rel}:{start}"))

    for number, line in enumerate(source.splitlines(), 1):
        found = _MD_HEADING.match(line)
        if found and rel.lower().endswith((".md", ".rst")):
            flush(number)
            heading = found.group(2).strip()
            buffer = []
            start = number
            continue
        buffer.append(line)
        if len(buffer) > 400:
            flush(number)
            buffer = []
            start = number + 1
    flush(0)
    return cards[:400], edges


def extract_cards(root: Path, repo_id: str, revision: str) -> tuple[list[NodeCard], list[Edge]]:
    cards: list[NodeCard] = []
    edges: list[Edge] = []
    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        source = None
        if suffix in _CODE_SUFFIXES or suffix in _DATA_SUFFIXES or suffix in _KNOWLEDGE_SUFFIXES:
            source = _read(path)
        if source is None:
            continue
        if suffix == ".py":
            more_cards, more_edges = _python_cards(repo_id, rel, source, revision)
        elif suffix in _CODE_SUFFIXES:
            more_cards, more_edges = _js_cards(repo_id, rel, source, revision, _CODE_SUFFIXES[suffix])
        elif suffix in _DATA_SUFFIXES:
            more_cards, more_edges = _data_cards(repo_id, rel, source, revision)
        else:
            more_cards, more_edges = _knowledge_cards(repo_id, rel, source, revision)
        cards.extend(more_cards)
        edges.extend(more_edges)
    return cards, edges


# --------------------------------------------------------------------------- #
# Store                                                                        #
# --------------------------------------------------------------------------- #
_DDL = """
CREATE TABLE IF NOT EXISTS repos (
    repo_id TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT NOT NULL, revision TEXT NOT NULL,
    origin TEXT, license TEXT, ingested_at REAL NOT NULL, card_count INTEGER NOT NULL, edge_count INTEGER NOT NULL,
    provenance TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards (
    card_id TEXT PRIMARY KEY, repo_id TEXT NOT NULL, plane TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
    locator TEXT NOT NULL, text TEXT NOT NULL, revision TEXT NOT NULL, neighborhood TEXT NOT NULL, vector BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS cards_repo ON cards(repo_id);
CREATE INDEX IF NOT EXISTS cards_name ON cards(name);
CREATE TABLE IF NOT EXISTS edges (
    repo_id TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL, evidence TEXT NOT NULL,
    source_plane TEXT NOT NULL, target_plane TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS edges_repo ON edges(repo_id);
CREATE TABLE IF NOT EXISTS proposals (
    repo_id TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL, score REAL NOT NULL,
    verified INTEGER NOT NULL, rationale TEXT NOT NULL, PRIMARY KEY (repo_id, source, target, relation));
"""


def _plane_of_ref(reference: str) -> str:
    prefix = reference.split(":", 1)[0]
    return {"module": "code", "type": "type", "path": "knowledge", "symbol": "code"}.get(prefix, "unknown")


def _git_revision(root: Path) -> str:
    head = root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unversioned"
    if text.startswith("ref:"):
        ref = root / ".git" / text[4:].strip()
        try:
            return ref.read_text(encoding="utf-8").strip()[:40]
        except OSError:
            packed = root / ".git" / "packed-refs"
            try:
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + text[4:].strip()):
                        return line.split(" ", 1)[0][:40]
            except OSError:
                pass
            return "unversioned"
    return text[:40]


def _license_of(root: Path) -> str | None:
    markers = (("mit license", "MIT"), ("the mit licence", "MIT"), ("permission is hereby granted, free of charge", "MIT"),
               ("apache license", "Apache-2.0"), ("gnu general public license", "GPL"), ("gnu lesser general public", "LGPL"),
               ("mozilla public", "MPL-2.0"), ("bsd 3-clause", "BSD-3-Clause"), ("bsd 2-clause", "BSD-2-Clause"),
               ("redistribution and use in source and binary forms", "BSD"), ("unlicense", "Unlicense"), ("isc license", "ISC"))
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst", "LICENCE", "LICENCE.md", "COPYING", "LICENSE-MIT",
                 "license", "license.md", "license.txt"):
        path = root / name
        if path.is_file():
            head = (_read(path) or "")[:1500].lower()
            for marker, spdx in markers:
                if marker in head:
                    return spdx
            return "declared-unrecognised"
    for manifest, pattern in (("package.json", r'"license"\s*:\s*"([^"]+)"'), ("pyproject.toml", r'license\s*=\s*["{]\s*(?:text\s*=\s*)?"?([A-Za-z0-9.+-]+)')):
        text = _read(root / manifest) or ""
        found = re.search(pattern, text)
        if found:
            return found.group(1)
    return None


class GreyMatter:
    """The atlas store. One SQLite file, fully regenerable."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=30)
        self.db.executescript(_DDL)

    def close(self) -> None:
        self.db.close()

    # -- ingestion ----------------------------------------------------------
    def ingest_repo(self, root: Path, *, name: str | None = None, origin: str | None = None,
                    provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        root = Path(root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"repository root is not a directory: {root}")
        revision = _git_revision(root)
        repo_name = name or root.name
        repo_id = hashlib.sha256(f"{origin or root}\n{revision}".encode("utf-8")).hexdigest()[:20]
        started = time.time()
        cards, edges = extract_cards(root, repo_id, revision)
        by_name: dict[str, list[NodeCard]] = {}
        for card in cards:
            by_name.setdefault(card.name, []).append(card)
            by_name.setdefault(card.name.rsplit(".", 1)[-1], []).append(card)
        planes = {card.card_id: card.plane for card in cards}
        with self.db:
            self.db.execute("DELETE FROM cards WHERE repo_id=?", (repo_id,))
            self.db.execute("DELETE FROM edges WHERE repo_id=?", (repo_id,))
            self.db.execute("DELETE FROM proposals WHERE repo_id=?", (repo_id,))
            self.db.executemany(
                "INSERT OR REPLACE INTO cards VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(c.card_id, c.repo_id, c.plane, c.kind, c.name, c.locator, c.text, c.revision,
                  json.dumps(list(c.neighborhood)), _pack(embed(f"{c.plane} {c.kind} {c.name} {c.text}")))
                 for c in cards])
            rows = []
            for edge in edges:
                target_plane = planes.get(edge.target) or _plane_of_ref(edge.target)
                rows.append((repo_id, edge.source, edge.target, edge.relation, edge.evidence,
                             planes.get(edge.source, "unknown"), target_plane))
            self.db.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?)", rows)
            record = {"schema": SCHEMA_VERSION, "root": str(root), "origin": origin, "revision": revision,
                      "license": _license_of(root), "extraction": "greymatter.extract_cards/1",
                      "embedding": f"hashed-blake2b/{DIMENSION}", "temporal_cutoff": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      **(provenance or {})}
            self.db.execute("INSERT OR REPLACE INTO repos VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (repo_id, repo_name, str(root), revision, origin, record["license"], time.time(),
                             len(cards), len(rows), json.dumps(record, sort_keys=True)))
        proposals = self.propose_bindings(repo_id)
        return {"repo_id": repo_id, "name": repo_name, "revision": revision, "license": record["license"],
                "cards": len(cards), "edges": len(rows), "proposals": proposals["proposed"],
                "verified_bindings": proposals["verified"], "planes": self.plane_counts(repo_id),
                "seconds": round(time.time() - started, 3), "origin": origin}

    # -- projections ----------------------------------------------------------
    def plane_counts(self, repo_id: str | None = None) -> dict[str, int]:
        query = "SELECT plane, COUNT(*) FROM cards" + (" WHERE repo_id=?" if repo_id else "") + " GROUP BY plane"
        rows = self.db.execute(query, (repo_id,) if repo_id else ()).fetchall()
        counts = {plane: 0 for plane in PLANES}
        counts.update({plane: count for plane, count in rows})
        return counts

    def relation_tensor(self, repo_id: str) -> dict[str, Any]:
        """Sparse planeÃ—planeÃ—relation counts: the kitchen's tensor projection."""
        rows = self.db.execute(
            "SELECT source_plane, target_plane, relation, COUNT(*) FROM edges WHERE repo_id=? "
            "GROUP BY source_plane, target_plane, relation ORDER BY 1,2,3", (repo_id,)).fetchall()
        relations = sorted({row[2] for row in rows})
        entries = [{"coordinates": {"source_plane": s, "target_plane": t, "relation": r}, "value": int(n)}
                   for s, t, r, n in rows]
        cross = sum(e["value"] for e in entries if e["coordinates"]["source_plane"] != e["coordinates"]["target_plane"]
                    and e["coordinates"]["target_plane"] != "unknown")
        payload = {"schema": "daedalus-kitchen-relation-tensor/1", "repo_id": repo_id,
                   "axes": [{"name": "source_plane", "labels": list(PLANES) + ["unknown"]},
                            {"name": "target_plane", "labels": list(PLANES) + ["unknown"]},
                            {"name": "relation", "labels": relations}],
                   "entries": entries, "total": sum(e["value"] for e in entries), "cross_plane": cross,
                   "status": "projection", "note": "derived from the card graph; never candidate identity"}
        payload["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return payload

    def propose_bindings(self, repo_id: str, threshold: float = PROPOSAL_THRESHOLD, limit: int = 3000) -> dict[str, int]:
        """Cross-plane similarity proposals; the literal verifier promotes a few."""
        rows = self.db.execute("SELECT card_id, plane, name, text, vector FROM cards WHERE repo_id=?", (repo_id,)).fetchall()
        by_plane: dict[str, list[tuple[str, str, str, list[float]]]] = {}
        for card_id, plane, name, text, blob in rows:
            by_plane.setdefault(plane, []).append((card_id, name, text, _unpack(blob)))
        proposals: list[tuple[str, str, str, str, float, int, str]] = []
        seen: set[tuple[str, str, str]] = set()
        # Pass 1 -- literal evidence: a knowledge card that names a code/type
        # symbol in backticks binds to it, verified by the source itself.
        by_short: dict[str, list[tuple[str, str]]] = {}
        for plane in ("code", "type", "data"):
            for card_id, name, _text, _vec in by_plane.get(plane, []):
                by_short.setdefault(name.rsplit(".", 1)[-1], []).append((card_id, plane))
        mention_rows = self.db.execute("SELECT source, target FROM edges WHERE repo_id=? AND relation='mentions'", (repo_id,)).fetchall()
        for source, target in mention_rows[: limit // 2]:
            short = target.split(":", 1)[1].rsplit(".", 1)[-1]
            for card_id, plane in by_short.get(short, [])[:3]:
                relation = {"code": "documents", "type": "documents", "data": "describes"}[plane]
                key = (source, card_id, relation)
                if key in seen:
                    continue
                seen.add(key)
                proposals.append((repo_id, source, card_id, relation, 1.0, 1, f"literal mention of `{short}` in knowledge card"))
        # Pass 2 -- latent similarity: proposals, unverified unless the text
        # literally names the counterpart.
        pairs = (("knowledge", "code", "documents"), ("type", "code", "types"), ("data", "code", "persists"),
                 ("knowledge", "data", "describes"))
        for left_plane, right_plane, relation in pairs:
            left = by_plane.get(left_plane, [])[:600]
            right = by_plane.get(right_plane, [])[:1500]
            for l_id, l_name, l_text, l_vec in left:
                best: list[tuple[float, str, str, str]] = []
                for r_id, r_name, r_text, r_vec in right:
                    score = cosine(l_vec, r_vec)
                    if score >= threshold:
                        best.append((score, r_id, r_name, r_text))
                best.sort(reverse=True)
                for score, r_id, r_name, _r_text in best[:3]:
                    key = (l_id, r_id, relation)
                    if key in seen:
                        continue
                    seen.add(key)
                    short = r_name.rsplit(".", 1)[-1]
                    literal = len(short) > 2 and re.search(r"\b" + re.escape(short) + r"\b", l_text) is not None
                    rationale = (f"literal mention of `{short}` in {left_plane} card" if literal
                                 else f"cosine {score:.2f} between {left_plane} and {right_plane} cards; unverified")
                    proposals.append((repo_id, l_id, r_id, relation, round(score, 4), int(literal), rationale))
                if len(proposals) >= limit:
                    break
        with self.db:
            self.db.execute("DELETE FROM proposals WHERE repo_id=?", (repo_id,))
            self.db.executemany("INSERT OR REPLACE INTO proposals VALUES (?,?,?,?,?,?,?)", proposals[:limit])
        verified = sum(1 for p in proposals[:limit] if p[5])
        return {"proposed": len(proposals[:limit]), "verified": verified}

    # -- retrieval --------------------------------------------------------------
    def search(self, query: str, *, k: int = 8, plane: str | None = None, repo_id: str | None = None) -> list[dict[str, Any]]:
        vector = embed(query)
        if not any(vector):
            return []
        clauses, params = [], []
        if plane:
            clauses.append("plane=?")
            params.append(plane)
        if repo_id:
            clauses.append("repo_id=?")
            params.append(repo_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        query_terms = set(tokens(query))
        scored: list[tuple[float, tuple]] = []
        for row in self.db.execute(f"SELECT card_id, repo_id, plane, kind, name, locator, text, revision, vector FROM cards{where}", params):
            score = cosine(vector, _unpack(row[8]))
            overlap = len(query_terms & set(tokens(row[4]))) * 0.15
            scored.append((score + overlap, row[:8]))
        scored.sort(key=lambda item: item[0], reverse=True)
        repos = {r[0]: r[1] for r in self.db.execute("SELECT repo_id, name FROM repos")}
        return [{"score": round(score, 4), "card_id": r[0], "repo_id": r[1], "repo": repos.get(r[1], r[1]),
                 "plane": r[2], "kind": r[3], "name": r[4], "locator": r[5], "text": r[6], "revision": r[7]}
                for score, r in scored[:k]]

    def repos(self) -> list[dict[str, Any]]:
        return [{"repo_id": r[0], "name": r[1], "root": r[2], "revision": r[3], "origin": r[4], "license": r[5],
                 "ingested_at": r[6], "cards": r[7], "edges": r[8], "provenance": json.loads(r[9])}
                for r in self.db.execute("SELECT * FROM repos ORDER BY ingested_at DESC")]

    def stats(self) -> dict[str, Any]:
        repos = self.repos()
        proposals, verified = self.db.execute("SELECT COUNT(*), COALESCE(SUM(verified),0) FROM proposals").fetchone()
        return {"schema": SCHEMA_VERSION, "path": str(self.path), "repos": len(repos), "cards": sum(r["cards"] for r in repos),
                "edges": sum(r["edges"] for r in repos), "planes": self.plane_counts(), "proposals": int(proposals or 0),
                "verified_bindings": int(verified or 0), "embedding": f"hashed-blake2b/{DIMENSION}"}

    def motif_context(self, query: str, *, k: int = 8) -> str:
        """Rendered retrieval for a builder prompt: references, never copies."""
        hits = self.search(query, k=k)
        if not hits:
            return ""
        lines = ["Corpus motifs (Grey Matter retrieval; reference only, respect each repository's license):"]
        for hit in hits:
            lines.append(f"- [{hit['plane']}/{hit['kind']}] {hit['name']} @ {hit['repo']}:{hit['locator']} "
                         f"(score {hit['score']}) -- {hit['text'][:220].replace(chr(10), ' ')}")
        return "\n".join(lines)


__all__ = ["GreyMatter", "NodeCard", "Edge", "embed", "cosine", "tokens", "extract_cards", "PLANES", "DIMENSION"]

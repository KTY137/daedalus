"""EXPERIMENT s05: minimal reference plane extractors (placeholders for s01-s04).

These are deliberately the CHEAPEST extractors that satisfy
``forest-v2-plane-extraction/1``.  They exist so the snapshot builder can be
measured against the real repository tree instead of synthetic fixtures, and
so the contract has at least one working producer per plane before s01-s04
land.  When those slices ship, they replace these functions; the snapshot
builder must not change.

Explicitly NOT claimed: extraction quality.  The code plane sees top-level
definitions only, the type plane sees syntactic annotation text (no inference),
the data plane sees file-level field lists (no lineage), the knowledge plane
sees headings (no concept resolution).  Every number these produce is a
property of a placeholder, never evidence about Gate-2 extraction.

Determinism rules every extractor here obeys, because the digest depends on
them: sorted file walk, posix relative locators, no mtime, no absolute path,
no wall clock, no set iteration leaking into output order.
"""
from __future__ import annotations

import ast
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

try:  # flat experiment directory: sibling import without a package
    from snapshot import CONTRACT
except ImportError:  # pragma: no cover - depends on caller's sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from snapshot import CONTRACT

CODE_ROOTS = ("daedalus",)
DATA_ROOTS = ("configs", "catalogue", "examples")
KNOWLEDGE_ROOTS = ("docs",)

_SKIP_DIRS = frozenset({"__pycache__", ".git", "node_modules", ".venv", "venv", ".mypy_cache"})
#: bound on how many list elements the data extractor unions keys over
_LIST_SAMPLE = 200


def _walk(root: Path, subdirs: Iterable[str], suffixes: tuple[str, ...]) -> list[Path]:
    """Deterministically sorted file list under ``root``/``subdir``."""
    found: list[Path] = []
    for sub in subdirs:
        base = root / sub
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                if name.endswith(suffixes):
                    found.append(Path(dirpath) / name)
    return sorted(found, key=lambda p: p.as_posix())


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _document(plane: str, revision: str, producer: str, nodes: list, edges: list) -> dict[str, Any]:
    return {
        "schema": CONTRACT,
        "plane": plane,
        "revision": revision,
        "producer": producer,
        "nodes": nodes,
        "edges": edges,
    }


def _node(node_id: str, kind: str, path: str, start: int, end: int, **attrs: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "locator": {"path": path, "start_line": start, "end_line": end},
        "attrs": attrs,
    }


def _edge(src: str, dst: str, kind: str) -> dict[str, Any]:
    return {"src": src, "dst": dst, "kind": kind, "attrs": {}}


def _parse_python(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except SyntaxError:
        return None


def _span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", 0) or 0
    end = getattr(node, "end_lineno", None) or start
    return start, end


# --------------------------------------------------------------------------
# code plane
# --------------------------------------------------------------------------


def extract_code(root: Path, revision: str, roots: Iterable[str] = CODE_ROOTS) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for path in _walk(root, roots, (".py",)):
        rel = _rel(root, path)
        tree = _parse_python(path)
        module_id = f"code:module:{rel}"
        nodes.append(_node(module_id, "module", rel, 0, 0, parsed=tree is not None))
        if tree is None:
            continue
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "function"
            elif isinstance(item, ast.ClassDef):
                kind = "class"
            else:
                continue
            start, end = _span(item)
            node_id = f"code:{kind}:{rel}:{item.name}"
            nodes.append(_node(node_id, kind, rel, start, end, name=item.name))
            edges.append(_edge(node_id, module_id, "defined_in"))
    nodes = _dedupe(nodes)
    return _document("code", revision, "s05_snapshot.reference_planes.extract_code", nodes, edges)


def _dedupe(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first node per id; a redefinition is not a second node."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for node in nodes:
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        out.append(node)
    return out


# --------------------------------------------------------------------------
# type plane
# --------------------------------------------------------------------------


def _annotation_text(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - unparse is total on parsed trees
        return None


def extract_type(root: Path, revision: str, roots: Iterable[str] = CODE_ROOTS) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    annotation_ids: set[str] = set()
    for path in _walk(root, roots, (".py",)):
        rel = _rel(root, path)
        tree = _parse_python(path)
        if tree is None:
            continue
        for item in tree.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start, end = _span(item)
            args = item.args
            positional = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
            annotated = [(a.arg, _annotation_text(a.annotation)) for a in positional]
            annotated = [(name, text) for name, text in annotated if text is not None]
            returns = _annotation_text(item.returns)
            if not annotated and returns is None:
                continue
            sig_id = f"type:signature:{rel}:{item.name}"
            nodes.append(
                _node(
                    sig_id,
                    "signature",
                    rel,
                    start,
                    end,
                    name=item.name,
                    params=len(positional),
                    annotated_params=len(annotated),
                    returns=returns,
                )
            )
            claims = [(name, text) for name, text in annotated]
            if returns is not None:
                claims.append(("->", returns))
            for slot, text in claims:
                ann_id = f"type:annotation:{text}"
                if ann_id not in annotation_ids:
                    annotation_ids.add(ann_id)
                    nodes.append(_node(ann_id, "annotation", rel, 0, 0, text=text))
                edges.append(_edge(ann_id, sig_id, f"annotates:{slot}"))
    return _document("type", revision, "s05_snapshot.reference_planes.extract_type", _dedupe(nodes), edges)


# --------------------------------------------------------------------------
# data plane
# --------------------------------------------------------------------------


def _json_fields(path: Path) -> tuple[list[str], bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return [], False
    if isinstance(payload, dict):
        return sorted(str(k) for k in payload), False
    if isinstance(payload, list):
        fields: set[str] = set()
        sample = payload[:_LIST_SAMPLE]
        for element in sample:
            if isinstance(element, dict):
                fields.update(str(k) for k in element)
        return sorted(fields), len(payload) > len(sample)
    return [], False


def _csv_fields(path: Path) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.reader(handle):
                return [c.strip() for c in row if c.strip()]
    except OSError:  # pragma: no cover - unreadable file
        return []
    return []


def extract_data(root: Path, revision: str, roots: Iterable[str] = DATA_ROOTS) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for path in _walk(root, roots, (".json", ".csv")):
        rel = _rel(root, path)
        if path.suffix == ".csv":
            fields, truncated = _csv_fields(path), False
            fmt = "csv"
        else:
            fields, truncated = _json_fields(path)
            fmt = "json"
        file_id = f"data:file:{rel}"
        nodes.append(
            _node(file_id, "dataset", rel, 0, 0, format=fmt, fields=len(fields), truncated=truncated)
        )
        for field in fields:
            field_id = f"data:field:{rel}:{field}"
            nodes.append(_node(field_id, "field", rel, 0, 0, name=field))
            edges.append(_edge(field_id, file_id, "field_of"))
    return _document("data", revision, "s05_snapshot.reference_planes.extract_data", _dedupe(nodes), edges)


# --------------------------------------------------------------------------
# knowledge plane
# --------------------------------------------------------------------------


def extract_knowledge(root: Path, revision: str, roots: Iterable[str] = KNOWLEDGE_ROOTS) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for path in _walk(root, roots, (".md",)):
        rel = _rel(root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        doc_id = f"knowledge:document:{rel}"
        nodes.append(_node(doc_id, "document", rel, 0, len(lines), lines=len(lines)))
        fenced = False
        stack: list[tuple[int, str]] = []
        counts: dict[str, int] = {}
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("```"):
                fenced = not fenced
                continue
            if fenced or not stripped.startswith("#"):
                continue
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            if not title or level > 6:
                continue
            slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")
            base = f"knowledge:heading:{rel}:{level}:{slug or 'untitled'}"
            counts[base] = counts.get(base, 0) + 1
            heading_id = base if counts[base] == 1 else f"{base}#{counts[base]}"
            nodes.append(_node(heading_id, "heading", rel, number, number, level=level, title=title))
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else doc_id
            edges.append(_edge(heading_id, parent, "under"))
            stack.append((level, heading_id))
    return _document(
        "knowledge", revision, "s05_snapshot.reference_planes.extract_knowledge", _dedupe(nodes), edges
    )


# --------------------------------------------------------------------------
# revision binding
# --------------------------------------------------------------------------


def read_git_revision(root: Path) -> str | None:
    """Resolve HEAD to a commit id by reading git's files.  No subprocess.

    Handles a plain ``.git`` directory, a worktree ``.git`` file with
    ``gitdir:``, a detached HEAD, a symbolic ref resolved in the gitdir or in
    the ``commondir``, and ``packed-refs``.  Returns ``None`` when the tree is
    not a git checkout -- the caller then supplies its own revision id.
    """
    dot_git = root / ".git"
    if dot_git.is_file():
        try:
            line = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not line.startswith("gitdir:"):
            return None
        gitdir = Path(line.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = (root / gitdir).resolve()
    elif dot_git.is_dir():
        gitdir = dot_git
    else:
        return None

    head_file = gitdir / "HEAD"
    if not head_file.is_file():
        return None
    try:
        head = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head.startswith("ref:"):
        return head or None
    ref = head.split(":", 1)[1].strip()

    search = [gitdir]
    common = gitdir / "commondir"
    if common.is_file():
        try:
            target = Path(common.read_text(encoding="utf-8").strip())
        except OSError:
            target = None
        if target is not None:
            search.append(target if target.is_absolute() else (gitdir / target).resolve())
    for base in search:
        candidate = base / ref
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8").strip() or None
            except OSError:
                return None
        packed = base / "packed-refs"
        if packed.is_file():
            try:
                content = packed.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for entry in content.splitlines():
                if entry.startswith("#") or not entry.strip():
                    continue
                parts = entry.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    return None


EXTRACTORS = {
    "code": extract_code,
    "type": extract_type,
    "data": extract_data,
    "knowledge": extract_knowledge,
}


def extract_all(root: Path, revision: str) -> list[dict[str, Any]]:
    """Run the four placeholder extractors against one revision of ``root``."""
    return [EXTRACTORS[plane](root, revision) for plane in ("code", "type", "data", "knowledge")]

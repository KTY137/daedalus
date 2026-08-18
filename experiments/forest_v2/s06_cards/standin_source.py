"""EXPERIMENT s06: a stand-in node source, so the card contract is measurable today.

Slice s01 is the intended producer of node records.  Its output did not exist
in this worktree when s06 was built (base ``d849c2a9``), so this module emits
records in the SAME contract (``forest-v2-node-record/1``) straight from the
tree, using stdlib AST for the code plane and a heading walk for the knowledge
plane.  It is a *stand-in*, not a competitor: when s01's stream lands, feed it
through ``s01_adapter.py`` and the builder, probe and tests do not change.

Two planes are emitted on purpose.  A card contract that only ever saw Python
would silently become a code-plane format, and §5 explicitly forbids a fifth
AST plane growing out of one.  Emitting knowledge-plane sections through the
identical builder is the cheapest available falsification of "these cards are
secretly code-only".

Read-only, pure stdlib, no repository imports, no writes, no network, no
subprocess.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Iterator

CODE_PACKAGES = ("daedalus", "tools", "runs")
KNOWLEDGE_DIRS = ("docs",)

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)|\[\[([^\]|#]+)")


def file_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _segment(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[max(0, start - 1) : end])


def _signature(node: ast.AST) -> str:
    try:
        return "(" + ast.unparse(node.args) + ")"  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - unparse is best effort only
        return "(...)"


def _code_node_id(plane_path: str, kind: str, qualname: str) -> str:
    return f"code://{plane_path}#{kind}:{qualname}"


def code_records(root: Path, path: Path) -> list[dict]:
    """Node records for one Python file: module, classes, functions, methods."""
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return []

    rel = _rel(root, path)
    lines = text.splitlines(keepends=True)
    digest = file_digest(text)
    module = module_name(root, path) or rel
    records: list[dict] = []

    module_children: list[dict] = []
    imports: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    {
                        "relation": "imports",
                        "direction": "out",
                        "node_id": f"code://module:{alias.name}",
                        "kind": "module",
                        "name": alias.name,
                    }
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(
                {
                    "relation": "imports",
                    "direction": "out",
                    "node_id": f"code://module:{node.module}",
                    "kind": "module",
                    "name": node.module,
                }
            )

    module_nid = _code_node_id(rel, "module", module)

    def emit(node, kind: str, qualname: str, parent_nid: str, parent_kind: str,
             parent_name: str) -> dict:
        neighbors = [
            {
                "relation": "contained_by",
                "direction": "in",
                "node_id": parent_nid,
                "kind": parent_kind,
                "name": parent_name,
            }
        ]
        record = {
            "plane": "code",
            "kind": kind,
            "path": rel,
            "qualname": qualname,
            "start_line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno) or node.lineno,
            "signature": _signature(node) if kind != "class" else "",
            "doc": ast.get_docstring(node) or "",
            "text": _segment(lines, node.lineno, getattr(node, "end_lineno", node.lineno)),
            "source_sha256": digest,
            "neighbors": neighbors,
        }
        return record

    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = f"{module}.{top.name}"
            records.append(
                emit(top, "function", qual, module_nid, "module", module)
            )
            module_children.append(
                {
                    "relation": "contains",
                    "direction": "out",
                    "node_id": _code_node_id(rel, "function", qual),
                    "kind": "function",
                    "name": top.name,
                }
            )
        elif isinstance(top, ast.ClassDef):
            qual = f"{module}.{top.name}"
            class_nid = _code_node_id(rel, "class", qual)
            class_record = emit(top, "class", qual, module_nid, "module", module)
            for base in top.bases:
                try:
                    base_name = ast.unparse(base)
                except Exception:  # pragma: no cover
                    continue
                class_record["neighbors"].append(
                    {
                        "relation": "derives_from",
                        "direction": "out",
                        "node_id": f"code://symbol:{base_name}",
                        "kind": "class",
                        "name": base_name,
                    }
                )
            for inner in top.body:
                if not isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                mqual = f"{qual}.{inner.name}"
                records.append(
                    emit(inner, "method", mqual, class_nid, "class", top.name)
                )
                class_record["neighbors"].append(
                    {
                        "relation": "contains",
                        "direction": "out",
                        "node_id": _code_node_id(rel, "method", mqual),
                        "kind": "method",
                        "name": inner.name,
                    }
                )
            records.append(class_record)
            module_children.append(
                {
                    "relation": "contains",
                    "direction": "out",
                    "node_id": class_nid,
                    "kind": "class",
                    "name": top.name,
                }
            )

    records.append(
        {
            "plane": "code",
            "kind": "module",
            "path": rel,
            "qualname": module,
            "start_line": 1,
            "end_line": max(1, len(lines)),
            "signature": "",
            "doc": ast.get_docstring(tree) or "",
            "text": text,
            "source_sha256": digest,
            "neighbors": module_children + imports,
        }
    )
    return records


def knowledge_records(root: Path, path: Path) -> list[dict]:
    """Node records for one Markdown file: one card per heading section."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []

    rel = _rel(root, path)
    lines = text.splitlines(keepends=True)
    digest = file_digest(text)
    doc_name = path.stem

    heads: list[tuple[int, int, str]] = []  # (level, line_no, title)
    for index, line in enumerate(lines, start=1):
        match = _HEADING.match(line.rstrip("\n"))
        if match:
            heads.append((len(match.group(1)), index, match.group(2).strip()))

    doc_nid = f"knowledge://{rel}#document:{doc_name}"
    records: list[dict] = []
    seen: dict[str, int] = {}
    stack: list[tuple[int, str]] = []  # (level, qualname)
    children: list[dict] = []

    for position, (level, start, title) in enumerate(heads):
        end = heads[position + 1][1] - 1 if position + 1 < len(heads) else len(lines)
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_qual = stack[-1][1] if stack else doc_name
        parent_kind = "section" if stack else "document"
        qual = f"{parent_qual}/{title}"
        stack.append((level, qual))

        ordinal = seen.get(qual, 0)
        seen[qual] = ordinal + 1

        body = _segment(lines, start, end)
        links = []
        for target, wiki in _MD_LINK.findall(body):
            name = target or wiki
            if name:
                links.append(
                    {
                        "relation": "links_to",
                        "direction": "out",
                        "node_id": f"knowledge://link:{name}",
                        "kind": "link",
                        "name": name,
                    }
                )
        parent_nid = (
            f"knowledge://{rel}#section:{parent_qual}" if stack[:-1] else doc_nid
        )
        records.append(
            {
                "plane": "knowledge",
                "kind": "section",
                "path": rel,
                "qualname": qual,
                "ordinal": ordinal,
                "start_line": start,
                "end_line": max(start, end),
                "signature": "#" * level,
                "doc": title,
                "text": body,
                "source_sha256": digest,
                "neighbors": [
                    {
                        "relation": "contained_by",
                        "direction": "in",
                        "node_id": parent_nid,
                        "kind": parent_kind,
                        "name": parent_qual,
                    }
                ]
                + links,
            }
        )
        if level <= 2:
            children.append(
                {
                    "relation": "contains",
                    "direction": "out",
                    "node_id": f"knowledge://{rel}#section:{qual}",
                    "kind": "section",
                    "name": title,
                }
            )

    records.append(
        {
            "plane": "knowledge",
            "kind": "document",
            "path": rel,
            "qualname": doc_name,
            "start_line": 1,
            "end_line": max(1, len(lines)),
            "signature": "",
            "doc": heads[0][2] if heads else "",
            "text": text,
            "source_sha256": digest,
            "neighbors": children,
        }
    )
    return records


def iter_records(root: Path) -> Iterator[dict]:
    """Every node record the stand-in extractor can produce for one tree."""
    for package in CODE_PACKAGES:
        directory = root / package
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            yield from code_records(root, path)
    for name in KNOWLEDGE_DIRS:
        directory = root / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            yield from knowledge_records(root, path)


def resolve_revision(root: Path) -> str:
    """Read HEAD without a subprocess.  Returns 'unknown' when unresolvable.

    A card must be revision-bound (§5 atomic revisions); reporting 'unknown'
    loudly is honest, silently stamping a wrong revision is not.
    """
    git = root / ".git"
    try:
        if git.is_file():
            pointer = git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return "unknown"
            gitdir = Path(pointer.split(":", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = (root / gitdir).resolve()
        elif git.is_dir():
            gitdir = git
        else:
            return "unknown"

        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            common = gitdir
            if not (common / ref).exists() and (gitdir / "commondir").exists():
                shared = (gitdir / "commondir").read_text(encoding="utf-8").strip()
                candidate = Path(shared)
                common = candidate if candidate.is_absolute() else (gitdir / shared)
            ref_file = common / ref
            if ref_file.exists():
                return "git:" + ref_file.read_text(encoding="utf-8").strip()
            packed = common / "packed-refs"
            if packed.exists():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + ref):
                        return "git:" + line.split(" ", 1)[0].strip()
            return "unknown"
        return "git:" + head
    except (OSError, UnicodeError, IndexError):
        return "unknown"

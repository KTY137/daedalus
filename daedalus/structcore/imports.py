"""imports.py — all-language import extraction + internal resolution.

Movement I.5 / Move 2. Python keeps its precise ``parse.python_imports`` path
(relative-import resolution intact); THIS module handles every OTHER language so
``index.py`` can build a dependency graph + fan-in beyond Python.

Two honest tiers:

  * ``extract_imports`` — find the import edges. With tree-sitter installed it
    walks the grammar's ``import_types`` nodes (precise node boundaries); without
    it, a per-language regex fallback keeps the edges flowing at lower precision.
    Each edge is ``(raw, kind)`` where ``kind`` is 'internal' (a resolution
    candidate — a repo-local module) or 'external' (a library / stdlib import).
  * ``resolve_internal`` — map an internal ``raw`` to an actual repo file by
    path/suffix match against the known file set. This is **best-effort** for
    non-Python languages: module->file conventions (Rust ``mod.rs``, Java source
    roots, Go packages-as-directories, C++ inline namespaces) are only
    approximated without a real build graph. Unresolved edges are simply dropped
    (no false edge), never guessed.

The ``kind`` distinction is syntactic where a language marks it (C ``"x"`` vs
``<x>``, Rust ``crate::``/``self::``/``super::``, JS relative ``./x``, QML quoted
dir imports); for the dotted-name languages that give NO syntactic internal/
external signal (Java, Kotlin, C#, PHP, Go) every import is treated as an
internal *candidate* and the file-set match is the real arbiter.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from .languages import LanguageSpec

# Languages whose imports are dotted names with no syntactic internal/external
# marker -> treat as internal candidates; resolution against real files decides.
_CANDIDATE_LANGS = {"java", "kotlin", "csharp", "go", "php"}

_JS_EXTS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".d.ts",
            "/index.ts", "/index.tsx", "/index.js", "/index.jsx")


# --------------------------------------------------------------------------- #
# Extraction                                                                    #
# --------------------------------------------------------------------------- #
def extract_imports(rel: str, text: str, spec: LanguageSpec | None,
                    tree_sitter_available: bool) -> list[tuple[str, str]]:
    """Return ``[(raw, kind), ...]`` for a non-Python file. Python returns [] —
    it is resolved precisely by ``parse.python_imports`` in ``index.py``."""
    if spec is None or spec.name == "python":
        return []
    node_texts: list[str] = []
    if tree_sitter_available and spec.ts_grammar and spec.import_types:
        node_texts = _ts_import_nodes(text, spec)
    if not node_texts:  # degrade cleanly: no tree-sitter / grammar missing
        node_texts = _regex_import_nodes(text, spec)

    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for nt in node_texts:
        for raw, kind in _parse_import(spec.name, nt):
            if raw and (raw, kind) not in seen:
                seen.add((raw, kind))
                out.append((raw, kind))
    return out


def _ts_import_nodes(text: str, spec: LanguageSpec) -> list[str]:
    """Raw source text of every ``import_types`` node (precise boundaries)."""
    from .parse import _parser_for  # reuse the cached, degrade-safe loader

    parser = _parser_for(spec.ts_grammar)
    if parser is None:
        return []
    data = text.encode("utf-8", errors="replace")
    try:
        tree = parser.parse(data)
    except Exception:
        return []
    wanted = set(spec.import_types)
    found: list[str] = []

    # Iterative pre-order walk. A recursive one blows Python's recursion limit
    # on deeply nested real-world ASTs (long chained/generated expressions) —
    # push children reversed so they pop back in source order.
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in wanted:
            found.append(data[node.start_byte:node.end_byte].decode("utf-8", "replace"))
        stack.extend(reversed(node.children))
    return found


# Per-language fallback line patterns (no tree-sitter). Best-effort by design.
_REGEX_FALLBACK: dict[str, re.Pattern] = {
    "c": re.compile(r'#\s*include\s*(?:"[^"]+"|<[^>]+>)'),
    "cpp": re.compile(r'#\s*include\s*(?:"[^"]+"|<[^>]+>)'),
    "java": re.compile(r'import\s+(?:static\s+)?[\w.]+\s*;'),
    "kotlin": re.compile(r'import\s+[\w.*]+'),
    "rust": re.compile(r'use\s+[^;]+;'),
    "go": re.compile(r'import\s+(?:"[^"]+"|\([^)]*\))', re.S),
    "javascript": re.compile(r'''(?:import|export)[^\n;]*?['"][^'"]+['"]'''),
    "typescript": re.compile(r'''(?:import|export)[^\n;]*?['"][^'"]+['"]'''),
    "csharp": re.compile(r'using\s+[^;]+;'),
    "php": re.compile(r'use\s+[\w\\]+(?:\s+as\s+\w+)?\s*;'),
    "qml": re.compile(r'import\s+[^\n]+'),
}


def _regex_import_nodes(text: str, spec: LanguageSpec) -> list[str]:
    pat = _REGEX_FALLBACK.get(spec.name)
    return pat.findall(text) if pat else []


# --------------------------------------------------------------------------- #
# Per-language node -> (raw, kind)                                              #
# --------------------------------------------------------------------------- #
_STR = re.compile(r"""['"]([^'"]+)['"]""")


def _parse_import(lang: str, node_text: str) -> list[tuple[str, str]]:
    t = node_text.strip()
    if lang in ("c", "cpp"):
        m = re.search(r'#\s*include\s*(?:"([^"]+)"|<([^>]+)>)', t)
        if not m:
            return []
        return [(m.group(1), "internal")] if m.group(1) else [(m.group(2), "external")]

    if lang in ("javascript", "typescript"):
        strings = _STR.findall(t)
        if not strings:
            return []
        spec_path = strings[-1]  # module specifier is the last string literal
        kind = "internal" if spec_path.startswith((".", "/")) else "external"
        return [(spec_path, kind)]

    if lang == "qml":
        strings = _STR.findall(t)
        if strings:  # import "dir" [as X]  -> a repo-local component dir
            return [(strings[0], "internal")]
        m = re.search(r"import\s+([\w.]+)", t)  # import QtQuick 2.0 -> external
        return [(m.group(1), "external")] if m else []

    if lang == "rust":
        body = t[3:] if t.startswith("use") else t
        body = body.rstrip(";").strip()
        path = re.split(r"::\s*[{*]", body, 1)[0].strip()  # drop group / glob tail
        head = re.match(r"([A-Za-z_]\w*)", path)
        first = head.group(1) if head else ""
        kind = "internal" if first in ("crate", "self", "super") else "external"
        return [(path, kind)]

    if lang in ("java", "kotlin"):
        body = re.sub(r"^\s*import\s+(?:static\s+)?", "", t).rstrip(";").strip()
        body = body.rstrip(".*").rstrip(".")  # `import a.b.*` -> package a.b
        return [(body, "internal")] if body else []

    if lang == "go":
        return [(s, "internal") for s in _STR.findall(t)]

    if lang == "php":
        body = re.sub(r"^\s*use\s+(?:function\s+|const\s+)?", "", t)
        body = re.sub(r"\s+as\s+\w+", "", body).rstrip(";").strip()
        return [(body, "internal")] if body else []

    if lang == "csharp":
        body = re.sub(r"^\s*using\s+(?:static\s+)?", "", t).rstrip(";").strip()
        body = re.sub(r"^\w+\s*=\s*", "", body)  # `using X = A.B;` -> A.B
        return [(body, "internal")] if body else []

    return []


# --------------------------------------------------------------------------- #
# Internal resolution (best-effort, non-Python)                                 #
# --------------------------------------------------------------------------- #
def resolve_internal(raw: str, spec_name: str, src_rel: str, known: set[str],
                     by_basename: dict[str, list[str]],
                     by_dir_tail: dict[str, list[str]]) -> str | None:
    """Map an internal ``raw`` import to a repo file (posix rel), or None.

    ``known`` — every rel path; ``by_basename`` — filename -> rels;
    ``by_dir_tail`` — last-dir-segment -> rels (for package/dir imports). Match
    is by suffix / directory containment; the first, most specific hit wins."""
    for cand in _candidate_paths(raw, spec_name, src_rel):
        hit = _match_file(cand, known, by_basename)
        if hit and hit != src_rel:
            return hit
    for seg in _candidate_dirs(raw, spec_name, src_rel):
        hit = _match_dir(seg, by_dir_tail, spec_name)
        if hit and hit != src_rel:
            return hit
    return None


def _candidate_paths(raw: str, lang: str, src_rel: str) -> list[str]:
    """Ordered candidate FILE paths (posix, extension included) to match."""
    src_dir = str(PurePosixPath(src_rel).parent)

    def rel_to(base_dir: str, sub: str) -> str:
        joined = PurePosixPath(base_dir) / sub if base_dir != "." else PurePosixPath(sub)
        # normalize .. and . manually (PurePosixPath keeps '..')
        parts: list[str] = []
        for part in joined.parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part not in (".", ""):
                parts.append(part)
        return "/".join(parts)

    if lang in ("c", "cpp"):
        return [raw, rel_to(src_dir, raw)]

    if lang in ("javascript", "typescript"):
        base = rel_to(src_dir, raw)
        return [base + ext for ext in _JS_EXTS]

    if lang in ("java", "kotlin"):
        ext = ".java" if lang == "java" else ".kt"
        base = raw.replace(".", "/")
        cands = [base + ext]
        if "/" in base:  # static member import: a.b.C.m -> a/b/C
            cands.append(base.rsplit("/", 1)[0] + ext)
        return cands

    if lang == "rust":
        body = raw
        base_dir = ""
        if body.startswith("crate::"):
            body = body[len("crate::"):]
        elif body.startswith("self::"):
            body, base_dir = body[len("self::"):], src_dir
        elif body.startswith("super::"):
            body, base_dir = body[len("super::"):], str(PurePosixPath(src_dir).parent)
        p = body.replace("::", "/")
        stem = rel_to(base_dir, p) if base_dir else p
        parent = stem.rsplit("/", 1)[0] if "/" in stem else ""
        cands = [stem + ".rs", stem + "/mod.rs"]
        if parent:
            cands.append(parent + ".rs")  # `use crate::foo::Bar` (Bar is in foo.rs)
        return cands

    if lang == "php":
        base = raw.replace("\\", "/")
        cands = [base + ".php"]
        if "/" in base:
            cands.append(base.rsplit("/", 1)[0] + ".php")
        return cands

    if lang == "csharp":
        base = raw.replace(".", "/")
        return [base + ".cs", (base.rsplit("/", 1)[-1] if "/" in base else base) + ".cs"]

    return []


def _candidate_dirs(raw: str, lang: str, src_rel: str) -> list[str]:
    """Last directory segment(s) for package/dir-style imports (Go, QML)."""
    if lang == "go":
        return [raw.rstrip("/").rsplit("/", 1)[-1]] if raw else []
    if lang == "qml":
        return [raw.rstrip("/").rsplit("/", 1)[-1].lstrip("./")] if raw else []
    return []


def _match_file(cand: str, known: set[str],
                by_basename: dict[str, list[str]]) -> str | None:
    if not cand:
        return None
    if cand in known:
        return cand
    bn = cand.rsplit("/", 1)[-1]
    suffix = "/" + cand
    best: str | None = None
    for rel in by_basename.get(bn, ()):
        if rel == cand or rel.endswith(suffix):
            if best is None or len(rel) < len(best):
                best = rel  # prefer the shallowest (closest to root) match
    return best


def _match_dir(seg: str, by_dir_tail: dict[str, list[str]], lang: str) -> str | None:
    if not seg:
        return None
    want_ext = ".go" if lang == "go" else ".qml"
    for rel in by_dir_tail.get(seg, ()):
        if rel.endswith(want_ext):
            return rel
    return None

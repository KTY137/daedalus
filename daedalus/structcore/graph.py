"""graph.py — a pragmatic symbol-reference graph (call-graph approximation).

Compiler-precise, cross-file symbol resolution is SCIP / tree-sitter-stack-graphs
territory: months of per-language work. This is the honest v1 — a NAME-based
reference graph over the units the parser already extracted: for a unit, which
*other known unit names* appear as identifier tokens in its body.

Movement I.5 / Move 4 sharpens it with import/scope awareness. A raw name match
picks up EVERY unit that happens to share a name (a ``run`` in ten unrelated
files). Given a ``SymbolResolver`` (a per-file symbol table + the Move-2 import
edges), resolution instead prefers, in order:

  1. a unit defined in the SAME file as the reference,
  2. a unit in a module the file actually IMPORTS,
  3. the global-name fallback (the old behavior) only when 1+2 find nothing.

This drops false call edges -> tighter distill slices + a truer call graph.
Python is precise (its import graph is precise); other languages are best-effort
(their import resolution is best-effort). Full scope/shadowing is deliberately
NOT attempted here — that is SCIP / stack-graphs, deferred, not faked.

Backward-compatible: ``callees``/``callers`` take an OPTIONAL ``resolver`` that
defaults to None (the pure name-match), so existing callers (``slice.py``) are
unaffected.
"""
from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field

from .parse import CodeUnit

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# common cross-language noise words that are never useful reference targets
_STOP = set(keyword.kwlist) | {
    "self", "cls", "true", "false", "null", "none", "return", "if", "else",
    "for", "while", "in", "of", "let", "const", "var", "function", "def", "int",
    "str", "float", "bool", "list", "dict", "set", "new", "this", "void",
}


def identifiers(source: str) -> set[str]:
    """Identifier tokens in a chunk of source, minus obvious stop-words."""
    return {t for t in _IDENT.findall(source) if t.lower() not in _STOP and len(t) > 2}


def name_index(units: list[CodeUnit]) -> dict[str, list[CodeUnit]]:
    idx: dict[str, list[CodeUnit]] = {}
    for u in units:
        idx.setdefault(u.name, []).append(u)
    return idx


# --------------------------------------------------------------------------- #
# Import/scope-aware resolution context (Move 4)                                #
# --------------------------------------------------------------------------- #
@dataclass
class SymbolResolver:
    """A per-file symbol table + import edges, used to resolve a referenced name
    to the unit most likely meant. Build with ``build_resolver``; it is derived
    (never hand-kept) and cheap.

    * ``defs_by_file`` — file rel -> {unit name: unit} (the names that file
      defines; first definition wins on a same-file name collision).
    * ``imports_by_file`` — file rel -> set of internal files it imports (Python
      precise via ``python_imports``; other languages best-effort via Move 2).
    """
    defs_by_file: dict[str, dict[str, CodeUnit]] = field(default_factory=dict)
    imports_by_file: dict[str, set[str]] = field(default_factory=dict)

    def resolve(self, name: str, from_file: str) -> CodeUnit | None:
        """Best unit for ``name`` referenced from ``from_file``: same-file def,
        else a def in an imported file, else None (caller does global fallback)."""
        local = self.defs_by_file.get(from_file, {})
        if name in local:
            return local[name]
        for imp in self.imports_by_file.get(from_file, ()):  # pragma: no branch
            defs = self.defs_by_file.get(imp)
            if defs and name in defs:
                return defs[name]
        return None

    def imports(self, from_file: str, target_file: str) -> bool:
        return target_file in self.imports_by_file.get(from_file, ())


def build_resolver(units: list[CodeUnit],
                   imports_by_file: dict[str, set[str]]) -> SymbolResolver:
    defs_by_file: dict[str, dict[str, CodeUnit]] = {}
    for u in units:
        bucket = defs_by_file.setdefault(u.module, {})
        bucket.setdefault(u.name, u)  # first definition wins
    return SymbolResolver(defs_by_file=defs_by_file,
                          imports_by_file={k: set(v) for k, v in imports_by_file.items()})


def _dedup(units: list[CodeUnit]) -> list[CodeUnit]:
    seen: set[tuple] = set()
    out: list[CodeUnit] = []
    for u in units:
        key = (u.module, u.name, u.line)
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


# --------------------------------------------------------------------------- #
# Call-edge approximation                                                       #
# --------------------------------------------------------------------------- #
def callees(focus: CodeUnit, candidates: list[CodeUnit],
            resolver: SymbolResolver | None = None) -> list[CodeUnit]:
    """Units among ``candidates`` (and, with a resolver, same-file/imported defs)
    that ``focus`` most likely calls — names appearing in its body. Approximate.

    Without ``resolver``: pure name match over ``candidates`` (v1 behavior).
    With ``resolver``: each referenced name is resolved local->imported first;
    only names the resolver can't place fall back to a candidate name match."""
    used = identifiers(focus.source)
    if resolver is None:
        return [u for u in candidates if u.name in used and u.name != focus.name]

    by_name: dict[str, list[CodeUnit]] = {}
    for u in candidates:
        by_name.setdefault(u.name, []).append(u)

    hits: list[CodeUnit] = []
    for name in used:
        if name == focus.name:
            continue
        resolved = resolver.resolve(name, focus.module)
        if resolved is not None and resolved.name != focus.name:
            hits.append(resolved)
        elif name in by_name:  # unresolved but present in the neighborhood
            hits.extend(u for u in by_name[name] if u.name != focus.name)
    return _dedup(hits)


def callers(focus: CodeUnit, candidates: list[CodeUnit],
            resolver: SymbolResolver | None = None) -> list[CodeUnit]:
    """Units whose body references ``focus``'s name — who most likely calls it.

    Without ``resolver``: pure name match (v1 behavior). With ``resolver``: a
    referencing unit counts only if it is in ``focus``'s file or in a file that
    IMPORTS ``focus``'s file (dropping false edges to same-named symbols in
    unrelated modules); if the resolver has no import info for that file, it
    falls back to the name match so no real caller is lost."""
    referencing = [u for u in candidates
                   if u.name != focus.name and focus.name in identifiers(u.source)]
    if resolver is None:
        return referencing

    out: list[CodeUnit] = []
    for u in referencing:
        if u.module == focus.module or resolver.imports(u.module, focus.module):
            out.append(u)
        elif u.module not in resolver.imports_by_file:  # no import info -> keep
            out.append(u)
    return _dedup(out)

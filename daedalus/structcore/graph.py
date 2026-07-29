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
import posixpath
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
    imports_by_file: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # SORTED TUPLES, not sets. ``resolve`` returns the FIRST import that
        # defines a name, so when two imported modules both define it, WHICH
        # unit is returned is decided by iteration order -- and over a set of
        # rel-path strings that order is a function of PYTHONHASHSEED. The
        # chosen unit reaches the CALLEES block of ``slice_text``, so the
        # distilled slice was not byte-identical across processes (measured:
        # 3 distinct slice hashes over 5 seeds on a 6-module fixture).
        # Normalising HERE rather than in ``build_resolver`` means every
        # construction path is deterministic, including hand-built resolvers.
        # Same candidates, now a total order; ties break on rel path.
        self.imports_by_file = {
            k: tuple(sorted(v)) for k, v in self.imports_by_file.items()}

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
    # ``SymbolResolver.__post_init__`` normalises these to sorted tuples.
    return SymbolResolver(defs_by_file=defs_by_file,
                          imports_by_file=dict(imports_by_file))


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
    # SORTED, not raw set order. ``identifiers`` returns a set, and this loop's
    # order survives into ``hits`` -> the CALLEES block of slice_text and the
    # ``included`` list, so iterating it directly made the distilled slice
    # depend on PYTHONHASHSEED: the same target emitted the same callees in a
    # different order on every process. Same hits, now a total order.
    for name in sorted(used):
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


# --------------------------------------------------------------------------- #
# Safety-class reachability (blast radius over the import graph)                #
# --------------------------------------------------------------------------- #
# The safety fence in ``sensitivity.change_risk`` matches fenced fragments
# against the LITERAL edited path only. That answers "is this file dangerous?"
# and never "does this file feed something dangerous?" -- so a leaf helper that
# a hardware interlock transitively imports scores low-risk and becomes writable
# by the local 7B bench. The index already carries the answer
# (``import_edges_reverse``: rel -> rels that import it); these helpers ask it.
#
# Pure and index-level on purpose: no ``daedalus.sensitivity`` import, so the
# fenced fragments arrive as a parameter and structcore keeps its light import
# graph (the router owns the policy, this file owns the traversal).

# A leaf that 5000 modules transitively depend on is either a pathological graph
# or a blast radius so large that escalating is right anyway, so the cap is not
# a correctness compromise -- but the caller MUST treat ``truncated`` as "could
# not prove safe", never as "safe". Bounded work is what keeps a router that
# runs on every task from hanging on a cyclic or degenerate import graph.
REACH_VISIT_CAP = 5000


def _fence_norm(rel: str) -> str:
    """Path normalised for fence matching: forward slashes, lower-cased, and
    ROOT-ANCHORED with a leading '/'.

    The leading slash is deliberate and is NOT what ``sensitivity._norm`` does.
    The generic fence ships fragments like ``/controller`` and ``/safety``, which
    a repo-relative rel (``controller/hv_interlock.py``) cannot contain -- so
    anchoring here catches top-level fenced trees that a bare substring test
    misses. It can only ever match MORE than the literal check, which is the
    direction this whole module is allowed to err in.
    """
    return "/" + rel.replace("\\", "/").lower().lstrip("/")


def fenced_fragment(rel: str, fenced_paths) -> str | None:
    """The first fenced fragment matching ``rel``, or None. Fragment order comes
    from the policy tuple (a total order), so the reported reason is stable."""
    norm = _fence_norm(rel)
    for frag in fenced_paths or ():
        f = str(frag).replace("\\", "/").lower()
        if f and f in norm:
            return frag
    return None


def canonical_node(idx: dict, rel: str) -> str | None:
    """The index node ``rel`` names, or None if the graph has never seen it.

    Spelling is a BYPASS CLASS, not a cosmetic detail: the fence is keyed on
    graph membership, so ``Utils/Clamp.py`` (Windows hands back either case),
    ``./utils/clamp.py`` and ``utils/../utils/clamp.py`` all used to miss the
    node and read as "no known dependents" -- i.e. as safe. Resolve the spelling
    before deciding, never after.
    """
    norm = posixpath.normpath(rel.replace("\\", "/")).lstrip("/")
    nodes = _graph_nodes(idx)
    if norm in nodes:
        return norm
    lowered = {n.lower(): n for n in sorted(nodes)}
    return lowered.get(norm.lower())


def _graph_nodes(idx: dict) -> set[str]:
    """Nodes of the DEPENDENCY graph. Code only.

    Documents are excluded deliberately, and this is a safety decision rather
    than a tidiness one. Everything downstream of this set is a fence question:
    ``fenced_reachability`` (does editing this file reach safety-critical code?)
    and ``fenced_dominance``, whose ``fraction`` is the share of NON-fenced
    modules that feed a fenced one -- and which ``provider_router`` reads to
    decide whether to stand the reachability escalation down.

    A document has no import edges by construction, so every one of them would
    land in the denominator and none in the numerator: turning documents on
    would DILUTE the fence's dominance fraction with files that cannot reach
    anything, making a guardrail less likely to fire for a bookkeeping reason.
    A safety number must move only when safety moves.
    """
    from .markdown import code_modules

    nodes = set(code_modules(idx))
    nodes.update(idx.get("import_edges") or ())
    for srcs in (idx.get("import_edges_reverse") or {}).values():
        nodes.update(srcs)
    return nodes


def fenced_reachability(idx: dict, rel: str, fenced_paths,
                        visit_cap: int = REACH_VISIT_CAP) -> dict:
    """Shortest dependency chain from ``rel`` to a fenced module.

    BFS over ``idx["import_edges_reverse"]`` (rel -> rels that import it), i.e.
    outward through everything that would be affected by editing ``rel``.

    ``hops`` 0 means the edited path is itself fenced -- exactly what today's
    literal check already catches. ``hops`` >= 1 is the case the literal check
    cannot see: a leaf that a fenced module transitively depends on.

    Determinism is load-bearing (two processes must block the same edit with the
    same explanation): the frontier and every neighbour list are iterated
    sorted, first parent wins, and among fenced nodes found at the minimal hop
    level the lexicographically smallest is reported.

    Non-Python import edges are best-effort, so this OVER-reports. That is
    intended: a spurious escalation costs a Claude call, a missed one lets a 7B
    model write code a hardware interlock depends on. Do not "tighten" this.
    """
    rev: dict = idx.get("import_edges_reverse") or {}
    node = canonical_node(idx, rel)
    result = {
        "reaches": False,
        "hops": None,
        "via": None,
        "fenced_node": None,
        "fragment": None,
        "chain": [],
        "visited": 0,
        "truncated": False,
        # A path the index never saw has no KNOWN dependents. Reported so the
        # caller can decide what to do about an unknown rather than silently
        # reading absence-of-edges as absence-of-risk.
        "known": node is not None,
    }
    # Traverse from the CANONICAL spelling when there is one; an unknown path
    # is still walked as given so a fenced-looking path is never let through
    # merely for being absent from the graph.
    rel = node or rel

    frontier = [rel]
    seen = {rel}                      # doubles as the cycle guard
    parent: dict[str, str] = {}
    hops = 0
    while frontier:
        hit = sorted(n for n in frontier if fenced_fragment(n, fenced_paths))
        if hit:
            node = hit[0]
            chain = [node]
            while chain[-1] in parent:
                chain.append(parent[chain[-1]])
            chain.reverse()
            result.update({
                "reaches": True,
                "hops": hops,
                "via": " -> ".join(chain),
                "fenced_node": node,
                "fragment": fenced_fragment(node, fenced_paths),
                "chain": chain,
                "visited": len(seen),
            })
            return result
        nxt: list[str] = []
        for node in sorted(frontier):
            for nb in sorted(rev.get(node, ())):
                if nb in seen:
                    continue
                if len(seen) >= visit_cap:
                    result["visited"] = len(seen)
                    result["truncated"] = True
                    return result
                seen.add(nb)
                parent[nb] = node
                nxt.append(nb)
        frontier = nxt
        hops += 1
    result["visited"] = len(seen)
    return result


def fenced_dominance(idx: dict, fenced_paths) -> dict:
    """How much of the repo the fence already covers by reachability.

    Returns ``{"fraction", "escalated", "candidates", "fenced_nodes"}`` where
    ``fraction`` is, of the modules that are NOT themselves fenced, the share
    that transitively feeds a fenced module -- i.e. exactly the share of edits
    that ``fenced_reachability`` would newly escalate.

    DENOMINATOR CHOICE (deliberate): already-fenced modules are excluded. They
    are high-risk under the literal check today, so reachability changes nothing
    about them; counting them would measure "how safety-critical is this repo"
    instead of "how much NEW escalation does this feature add", and a repo that
    is 90% fenced would then trip the guardrail on the strength of files the
    feature never touches. What we want to bound is the delta.

    Computed as ONE multi-source BFS over the forward edges from the fenced set
    (a module reaches a fenced node in the reverse graph exactly when it is
    reachable from a fenced node in the forward graph), not V separate BFS runs
    -- the router calls this on every task and O(V*E) on a 7k-file repo is not
    something a fence may cost.
    """
    fwd: dict = idx.get("import_edges") or {}
    nodes = _graph_nodes(idx)
    fenced = {n for n in nodes if fenced_fragment(n, fenced_paths)}

    seen = set(fenced)
    frontier = sorted(fenced)
    while frontier:
        nxt = []
        for node in frontier:
            for tgt in sorted(fwd.get(node, ())):
                if tgt not in seen:
                    seen.add(tgt)
                    nxt.append(tgt)
        frontier = sorted(nxt)

    candidates = sorted(nodes - fenced)
    escalated = [n for n in candidates if n in seen]
    return {
        # No non-fenced candidates -> 0.0, which keeps the guard ON. A guardrail
        # that fails toward "disable the fence" is the wrong failure.
        "fraction": round(len(escalated) / len(candidates), 4) if candidates else 0.0,
        "escalated": len(escalated),
        "candidates": len(candidates),
        "fenced_nodes": len(fenced),
    }

# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The threefold graph, as a paragraph a model can read.

MEASURED 2026-07-30, and the whole reason this module exists: **the agents never
see the graph.** No provider module references ``structcore``, ``build_index``,
``typegraph`` or ``forest``. The entire context a write lane gets is
``read_inlined_context`` -- raw file bytes and nothing else. So a model asked to
write ``tests/test_shift.py`` had no way to know that the class is ``Shift`` and
not ``ShiftManager``, that linting lives at ``daedalus.gui.lint`` and not
``daedalus.linting``, or that the vault is ``daedalus.wiki.vault`` and not
``daedalus.wiki_vault``. It guessed, plausibly, three times, and a syntax gate
passed all three.

All three of those hallucinations are answered by ~6.5k characters of text that
the index can already produce. That is the cheapest open improvement measured
that night, and it was the same defect class as everything else: the graph was
built, the graph was measured, and the graph was never connected to the consumer.

Three layers, which is why it is a brief and not a manifest:

1. **symbols** -- what exists, per file. Answers "does this name exist".
2. **imports** -- who reaches whom, INCLUDING the edges that live inside
   function bodies. Answers "what will I break" and "where does this belong".
   Function-body edges are marked ``*``: 202 of 526 internal edges in this repo
   are only visible there, so a brief built from top-level imports alone would
   present ~60% of the graph as the whole of it.
3. **documents** -- which page claims to describe this file. Answers "what has
   someone already promised about this code", which is the layer that turns a
   docstring lie into a visible contradiction rather than a discovery.

Layers 2 and 3 degrade cleanly: the type and document layers of the index are
behind flags, and when they are off those sections are omitted rather than
faked. What is never omitted silently is a TRUNCATION -- if the budget cuts the
brief, the brief says what it dropped. A brief that quietly stops listing files
reads exactly like a brief that says those files do not exist, which is the
hallucination this module was written to prevent.

This is a DERIVED artefact. It is regenerated, never edited, and a model must not
cite it as evidence about behaviour -- it describes shape, not semantics.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "DEFAULT_BUDGET_CHARS",
    "GraphBrief",
    "graph_brief",
    "render_brief",
    "file_symbols",
]

#: Default character budget for a whole brief. Sized from measurement, not
#: taste: the full symbol layer for the ``daedalus/`` package is 6,479
#: characters, so a 1-hop brief around a handful of files fits comfortably and
#: the budget only bites on a genuinely wide change.
DEFAULT_BUDGET_CHARS = 12_000

#: Marks an edge that exists ONLY inside a function body. See the module
#: docstring: this is the 38% of the import graph that naive tooling misses.
DEEP_EDGE_MARK = "*"

#: Path prefixes that are ARTEFACTS, not the project, and must never appear in a
#: brief. Both entries are measured, not defensive:
#:
#: * ``runs/`` -- the first brief built for ``daedalus/shift.py`` listed
#:   ``runs/eval/deepseek_lab/wrecked/shift.py`` as a graph neighbour and printed
#:   its symbols. That file is the DESTROYED artefact kept as evidence: a test
#:   module that overwrote the real one. Showing it to a model asked to edit
#:   ``shift.py`` teaches it precisely the substitution the write gate now
#:   refuses -- the brief would have been arguing for the bug.
#: * ``build/`` -- holds 142 stale copies of the package. Every naive sweep
#:   double-counts them, and a brief that lists a symbol twice from two versions
#:   of one file is worse than one that omits it.
ARTEFACT_ROOTS: tuple[str, ...] = ("runs/", "build/", "dist/", ".captures/")

#: Characters reserved for the header, which is composed after the layers are
#: budgeted. Generous on purpose: overshooting the reserve wastes a few hundred
#: characters, while under-reserving silently pushes the brief over the budget a
#: caller sized its prompt against.
_HEADER_RESERVE = 700


def _is_artefact(rel: str) -> bool:
    return rel.startswith(ARTEFACT_ROOTS)


@dataclass(frozen=True)
class GraphBrief:
    """A rendered brief plus the facts it was rendered from."""

    text: str
    #: The files the brief was requested for.
    targets: tuple[str, ...]
    #: Files pulled in as graph neighbours of the targets.
    neighbours: tuple[str, ...]
    #: Layer name -> number of items rendered.
    counts: Mapping[str, int]
    #: Layer name -> number of items dropped by the budget.
    dropped: Mapping[str, int]
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def truncated(self) -> bool:
        return any(self.dropped.values())


# --------------------------------------------------------------------------
# layer 1 -- symbols
# --------------------------------------------------------------------------

def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = node.args
    names = [p.arg for p in (*a.posonlyargs, *a.args)]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        names.append("*")
    names += [p.arg for p in a.kwonlyargs]
    if a.kwarg:
        names.append("**" + a.kwarg.arg)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(names)})"


def file_symbols(path: Path, *, include_private: bool = True) -> list[str]:
    """Top-level API of one Python file, as declaration lines.

    Signatures rather than bare names, because the measured failure was not only
    "the module does not exist" but "the module does not define that": a name
    without its shape still lets a caller invent the arguments.

    Methods are included one level down for classes, since ``Shift.tick()`` is
    the kind of thing a caller needs and the class name alone does not give it.
    Deeper nesting is deliberately not listed -- it is not API.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError, RecursionError):
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if include_private or not node.name.startswith("_"):
                out.append(_sig(node))
        elif isinstance(node, ast.ClassDef):
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            head = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
            out.append(head)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("__") and sub.name != "__init__":
                        continue
                    if not include_private and sub.name.startswith("_"):
                        continue
                    out.append("    " + _sig(sub))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    out.append(f"{t.id} = ...")
    return out


# --------------------------------------------------------------------------
# layer 2 -- imports, including the ones inside function bodies
# --------------------------------------------------------------------------

def _deep_only_modules(path: Path) -> frozenset[str]:
    """Dotted module names this file imports ONLY inside a function body.

    Computed here rather than read from the index because the index publishes a
    flat edge list with no depth: it correctly INCLUDES function-body edges (12
    edges for ``offload.py`` against 7 top-level import statements -- verified),
    it just cannot say which ones they are. One extra AST pass over a handful of
    neighbour files buys the distinction.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError, RecursionError):
        return frozenset()
    top: set[str] = set()
    deep: set[str] = set()
    body = set(map(id, tree.body))

    def _names(node: ast.Import | ast.ImportFrom) -> list[str]:
        if isinstance(node, ast.ImportFrom):
            return [node.module] if node.module and not node.level else []
        return [a.name for a in node.names]

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            top.update(_names(node))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in body:
            deep.update(_names(node))
    return frozenset(deep - top)


def _tail_matches(dotted_set: Iterable[str], rel: str) -> bool:
    """Does any dotted name in the set plausibly denote ``rel``?

    Suffix matching on the dotted path, because a function-body import may be
    written ``from .kairos import drafts`` or ``import daedalus.kairos.drafts``
    and both denote ``daedalus/kairos/drafts.py``. Over-matching here only ever
    adds a ``*`` mark to an edge that is genuinely present, so a wrong guess
    mislabels a true edge rather than inventing one.
    """
    stem = rel[:-3] if rel.endswith(".py") else rel
    parts = stem.replace("\\", "/").split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return False
    tail_1 = parts[-1]
    tail_2 = ".".join(parts[-2:]) if len(parts) > 1 else tail_1
    for dotted in dotted_set:
        segs = dotted.split(".")
        if segs[-1] == tail_1 or dotted.endswith(tail_2):
            return True
    return False


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def _neighbourhood(
    targets: Sequence[str],
    edges: Mapping[str, list[str]],
    reverse: Mapping[str, list[str]],
    hops: int,
) -> list[str]:
    seen = set(targets)
    frontier = set(targets)
    for _ in range(max(0, hops)):
        nxt: set[str] = set()
        for rel in frontier:
            nxt.update(edges.get(rel) or ())
            nxt.update(reverse.get(rel) or ())
        nxt = {r for r in nxt if not _is_artefact(r)} - seen
        if not nxt:
            break
        seen |= nxt
        frontier = nxt
    return sorted(seen - set(targets))


def graph_brief(
    repo_root: str | Path,
    targets: Sequence[str],
    *,
    hops: int = 1,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    index: Mapping[str, Any] | None = None,
    include_docs: bool = True,
) -> GraphBrief:
    """Build the brief for ``targets`` and their ``hops``-hop neighbourhood.

    ``index`` may be supplied to avoid a rebuild; otherwise the process-wide
    cached index is used, which is single-flight, so two hundred concurrent lanes
    warm it once rather than each starting a full scan. That property is the
    difference between this being free and this being the reason a fan-out melts
    the box.

    Never raises for a missing or unreadable index: a lane that cannot get a
    brief must still be able to run with none. A brief is context, not a gate.
    """
    root = Path(repo_root).resolve()
    rels = tuple(dict.fromkeys(str(t).replace("\\", "/") for t in targets))

    if index is None:
        try:
            from ..structcore.index import cached_index
            index = cached_index(root)
        except Exception:                       # noqa: BLE001 -- context, not a gate
            index = {}

    edges: Mapping[str, list[str]] = index.get("import_edges") or {}
    reverse: Mapping[str, list[str]] = index.get("import_edges_reverse") or {}
    neighbours = tuple(_neighbourhood(rels, edges, reverse, hops))

    counts: dict[str, int] = {}
    dropped: dict[str, int] = {}
    rendered: dict[str, str] = {}
    # The header is written last but must not escape the budget, so its space is
    # reserved up front. A brief that overshoots by exactly the size of its own
    # preamble is the kind of off-by-a-section that only shows up as a truncated
    # prompt at the far end.
    spent = _HEADER_RESERVE

    def _emit(title: str, note: str, lines: Sequence[str], layer: str) -> None:
        """Render a layer if it fits. Called in PRIORITY order, not display order.

        Priority matters because the layers are wildly different sizes: the
        1-hop symbol layer around ``offload.py`` alone is 495 lines, and emitting
        it first consumed the entire budget and dropped the import layer -- the
        smallest and most valuable of the three, and the only one that answers
        "what will I break". Small high-value layers are rendered first and
        DISPLAYED in reading order.
        """
        nonlocal spent
        if not lines:
            return
        head = f"--- {title} ---\n{note}\n" if note else f"--- {title} ---\n"
        kept: list[str] = []
        for line in lines:
            if spent + len(head) + len(line) + 1 > budget_chars:
                break
            kept.append(line)
            spent += len(line) + 1
        if not kept:
            dropped[layer] = len(lines)
            return
        spent += len(head)
        counts[layer] = len(kept)
        if len(kept) < len(lines):
            dropped[layer] = len(lines) - len(kept)
        rendered[layer] = head + "\n".join(kept)

    # ---- layer: imports (rendered FIRST -- smallest, highest value) --------
    imp_lines: list[str] = []
    for rel in rels:
        out = [d for d in (edges.get(rel) or []) if not _is_artefact(d)]
        if out:
            deep = _deep_only_modules(root / rel)
            marked = [
                dep + (DEEP_EDGE_MARK if deep and _tail_matches(deep, dep) else "")
                for dep in out
            ]
            imp_lines.append(f"{rel} -> {', '.join(marked)}")
        # Artefact importers are filtered HERE as well as in the neighbourhood.
        # Measured: the first brief for ``shift.py`` had no artefact neighbour
        # left and still printed "<- imported by
        # runs/eval/deepseek_lab/wrecked/shift.py", because a reverse edge is
        # read straight off the index and never passed through the walk.
        inc = [s for s in (reverse.get(rel) or []) if not _is_artefact(s)]
        if inc:
            imp_lines.append(f"{rel} <- imported by {', '.join(inc)}")
    _emit("IMPORTS",
          f"'->' imports, '<-' is imported by. '{DEEP_EDGE_MARK}' marks an edge "
          "that exists only inside a function body -- a change there still "
          "breaks the importer.",
          imp_lines, "imports")

    # ---- layer: symbols ---------------------------------------------------
    sym_lines: list[str] = []
    for rel in rels:
        path = root / rel
        if rel.endswith(".py") and path.is_file():
            syms = file_symbols(path)
            if syms:
                sym_lines.append(rel)
                sym_lines.extend("  " + s for s in syms)
    for rel in neighbours:
        path = root / rel
        if not rel.endswith(".py") or not path.is_file():
            continue
        # PUBLIC API ONLY for a neighbour. What a caller may use from another
        # module is its public surface; its private helpers are not callable and
        # listing them cost 495 lines around ``offload.py`` -- enough to consume
        # the whole budget on names nobody is allowed to reference.
        syms = file_symbols(path, include_private=False)
        if syms:
            sym_lines.append(f"{rel}  (public API only)")
            sym_lines.extend("  " + s for s in syms)
    _emit("SYMBOLS THAT EXIST",
          "If a name is not listed under its file, it does not exist in that "
          "file. Do not import it.",
          sym_lines, "symbols")

    # ---- layer: documents -------------------------------------------------
    if include_docs:
        doc_lines: list[str] = []
        # ``document_links_reverse`` is keyed BY THE CODE FILE, which is the
        # lookup wanted here -- a scan of the forward map would be O(all pages)
        # per lane. Both keys are absent unless the document layer is enabled, so
        # this section vanishes rather than lying when it is off.
        rev: Mapping[str, list[str]] = index.get("document_links_reverse") or {}
        for rel in rels:
            pages = rev.get(rel) or ()
            if pages:
                doc_lines.append(f"{rel} <- documented by {', '.join(sorted(pages))}")
        # Wikilinks from a page INTO code are a separate relation with its own
        # layer, and are only forward-keyed.
        wiki: Mapping[str, list[str]] = index.get("wiki_code_links") or {}
        items = wiki.items() if isinstance(wiki, Mapping) else ()
        for page, described in sorted(items):
            hits = sorted(set(described or ()) & set(rels))
            if hits:
                doc_lines.append(f"{page} wiki-links {', '.join(hits)}")
        _emit("DOCUMENTS",
              "A page that describes one of these files. Its claims are a "
              "PROMISE, not evidence -- where the code disagrees, the document "
              "is the bug.",
              doc_lines, "documents")

    header = [
        "=== STRUCTURAL BRIEF (derived from the index; regenerated, never "
        "hand-edited) ===",
        f"targets: {', '.join(rels)}",
        f"neighbourhood: {len(neighbours)} file(s) at {hops} hop(s); "
        f"index covers {index.get('n_files', 0)} file(s)",
        "This describes SHAPE, not behaviour. Never cite it as evidence about "
        "what code does.",
    ]
    if dropped:
        header.append(
            "BUDGET: truncated -- "
            + ", ".join(f"{n} {layer} line(s) omitted"
                        for layer, n in sorted(dropped.items()))
            + ". Absence below is NOT evidence of absence in the repo.")
    # DISPLAY order, independent of the priority order the layers were rendered
    # in: symbols first because "what exists" is what a writer needs before
    # anything else, then who reaches whom, then what has been promised.
    sections = [rendered[k] for k in ("symbols", "imports", "documents")
                if k in rendered]
    if not sections:
        header.append("No structural facts available for these files.")

    text = "\n".join(header) + "\n\n" + "\n\n".join(sections) + "\n"
    return GraphBrief(
        text=text,
        targets=rels,
        neighbours=neighbours,
        counts=counts,
        dropped=dropped,
        provenance={
            "scope_key": index.get("scope_key"),
            "n_files": index.get("n_files", 0),
            "hops": hops,
            "budget_chars": budget_chars,
        },
    )


def render_brief(
    repo_root: str | Path,
    targets: Sequence[str],
    **kwargs: Any,
) -> str:
    """:func:`graph_brief` as text, or "" if there is nothing to say.

    The convenience a provider calls: it must never raise into a lane, so a
    failure to describe the graph degrades to no description.
    """
    try:
        return graph_brief(repo_root, targets, **kwargs).text
    except Exception:                           # noqa: BLE001 -- context, not a gate
        return ""

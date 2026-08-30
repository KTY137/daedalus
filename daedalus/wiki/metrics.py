# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Structural quality of a wiki, measured on the graph the wiki produces.

A page can be well written, current and true about the tree and still buy the
project nothing: if what it says connects to nothing else, it dies in the first
structural filter anyone applies to the graph. This module measures exactly
that -- the share of documentation->source edges that survive a k-core of the
fourfold graph -- because it is the one wiki property a model writing prose
cannot talk its way past. ``verify`` decides whether a page is *true*; this
module decides whether it is *load bearing*.

Definition
----------
Extract triples from the tree (code and type plane from Python, knowledge plane
from Markdown), prune to the k-core -- drop every node below degree ``k``,
repeat until nothing moves -- and report

    crossplane_survival_rate = surviving doc->source edges / all doc->source edges

Only ``documents`` and ``documents_file`` count as cross-plane here. Both are
authored: a wiki page mentions a symbol, or links a file. Intra-code and
code->type edges are the repository's own structure and would swamp the number
the wiki is actually responsible for.

Two modelling rules below are measured lessons, not taste. Measured 2026-08-25
on project_tct (411 py / 383 md), all four numbers from the same corpus:

1. A Markdown link to a source file becomes an edge onto the *code* node
   (``documents_file`` -> ``code:module:<path>``). The first draft minted a
   parallel ``knowledge:file:<path>`` node per linked file, so the most
   deliberate cross-plane statement a wiki author can make -- linking the file
   -- connected the planes not at all. Putting it on the code node moved the
   rate 31.5% -> 38.3%, and all 168 of those edges survived the 3-core.
2. A backticked span becomes ONE ``knowledge:concept:<span>`` node for the whole
   tree, never one mention node per page. Per-page mention nodes have degree 2
   by construction (one in, one out), so every cross-plane edge died in a 3-core
   whatever the corpus looked like: measured 0%. Per concept, the same corpus
   measured 26%. That 0 was a property of the instrument, not of the wiki --
   which is why the rule is written down here instead of being rediscovered.

What the instrument cannot see
------------------------------
``wiki_health`` always returns ``could_not_measure``: unparsable files, files
skipped for size, unreadable files, truncated link lists, nested Git checkouts
left out of the walk, and the planes and languages this extractor does not read
at all -- each with the count of files it stepped over, so the size of the blind
spot is visible next to the number.
An empty list means the instrument saw everything it knows how to see; it never
means the tree is clean. When there are no cross-plane edges at all, the rate
is ``None`` plus an entry here -- a measured 0.0 (edges exist, none survive) is
a finding, "nothing to measure" is not, and the two must not print the same.

Read-only: no network, no model, no writes. Stdlib only.

    python -c "from daedalus.wiki.metrics import wiki_health; import json; \\
               print(json.dumps(wiki_health('.'), indent=2))"
    python -m daedalus.wiki.metrics <root> [k]
"""

from __future__ import annotations

import ast
import collections
import json
import os
import pathlib
import posixpath
import re
import sys

METRICS_VERSION = 1

# Close to ``verify`` and ``plan``, deliberately not identical: ``plan`` also
# skips ``docs`` because it partitions SOURCE into topics, and this module must
# not -- the wiki under ``docs/`` is half of what it measures. The artefact
# trees come from ``plan`` for its measured reason: without them a walker reads
# generated output as project structure (it made every run directory a topic,
# 602 of them on this repository). Each tree walker in this package keeps its
# own copy on purpose -- they are standalone entrypoints.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "site-packages",
             ".mypy_cache", ".pytest_cache", "reference", "lab_assets",
             "runs", "artifacts", "artifacts_claude", "artifacts_codex",
             "scratchpad", "build", "dist", "htmlcov", ".tox", "spikes"}

MAX_BYTES = 400_000          # a file larger than this is reported, not parsed
MAX_LINKS_PER_PAGE = 80      # bounds one pathological generated page

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)")
MD_CODE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{2,60})`")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

#: Relations that cross from the knowledge plane into source. The rate is about
#: these and nothing else.
CROSS_PLANE_RELATIONS = ("documents", "documents_file")

#: Present in real trees, invisible to this extractor. Counted, not parsed.
UNREAD_SUFFIXES = {
    "data plane (csv/json/yaml/sql)": {".csv", ".json", ".yaml", ".yml", ".sql"},
    "non-Python source": {".ts", ".tsx", ".js", ".jsx", ".qml", ".rs", ".go",
                          ".java", ".c", ".h", ".cpp", ".ps1", ".sh"},
    "notebooks": {".ipynb"},
}

Triple = tuple[str, str, str]


def _nested_checkout(directory: pathlib.Path) -> bool:
    """Is this subdirectory its own Git checkout?

    A marker rule, not a name list: a clone carries a ``.git`` DIRECTORY, a
    worktree a ``.git`` FILE, and either way the tree below belongs to another
    repository and is not this project's structure. Same shape as ``plan``'s
    ``_venv_roots``, which knows a venv by ``pyvenv.cfg`` rather than by its
    name. Measured on agent_env: worktree copies under ``.claude/worktrees``
    supplied 1144 of 2303 Python files, so the walk read this repository
    several times over and called the result its health. (Ruling 2026-08-25.)
    """
    return (directory / ".git").exists()


def _walk(root: pathlib.Path) -> tuple[dict[str, list[pathlib.Path]], list[str]]:
    """One pruned pass over the tree by suffix, plus the checkouts left out.

    ``rglob`` would descend into ``.venv`` before filtering; on a real tree that
    is the whole cost. Names are sorted so two runs on the same tree produce the
    same graph -- first definition wins when a symbol name repeats. ``root``
    itself is never marker-tested: it is allowed to be a checkout, that is the
    point of it.
    """
    found: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
    nested: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = pathlib.Path(dirpath)
        keep = []
        for name in sorted(dirnames):
            if name in SKIP_DIRS:
                continue
            if _nested_checkout(here / name):
                nested.append((here / name).relative_to(root).as_posix())
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            found[pathlib.PurePath(name).suffix.lower()].append(here / name)
    return found, nested


def _read(path: pathlib.Path, blind: collections.Counter, kind: str) -> str | None:
    """Text of a file, or ``None`` -- and then the reason is booked as blind."""
    try:
        if path.stat().st_size > MAX_BYTES:
            blind[f"{kind} file(s) skipped: larger than {MAX_BYTES} bytes"] += 1
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        blind[f"{kind} file(s) unreadable"] += 1
        return None


def _register(defined: dict[str, str], ambiguous: set[str], name: str, node: str) -> None:
    """Bind a bare name to its first definition, and book every collision.

    A documentation mention names a symbol, not a location: ``run`` in backticks
    cannot be told apart from ``run`` in thirty modules. First definition wins so
    the graph stays deterministic -- but the guess is published, not hidden, as
    ``documents_on_ambiguous_names``. Measured on project_tct: 293 of 1499
    documents edges rest on it, and forcing those down to the unambiguous
    survival rate would move the headline by at most ~1.1 points.
    """
    if defined.setdefault(name, node) != node:
        ambiguous.add(name)


def _python_plane(py_files: list[pathlib.Path], root: pathlib.Path,
                  triples: set[Triple], defined: dict[str, str],
                  ambiguous: set[str], blind: collections.Counter) -> None:
    """Code plane and type plane. Fills ``defined``: bare name -> node id."""
    for path in py_files:
        text = _read(path, blind, "python")
        if text is None:
            continue
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            blind["python file(s) unparsable (SyntaxError)"] += 1
            continue
        module = f"code:module:{rel}"
        # A method is ONE node. Walking the tree flat would emit it twice --
        # ``code:func:<rel>#Class.method`` as the tail of ``has_method`` and
        # ``code:func:<rel>#method`` as the tail of ``defines_func`` -- which
        # splits its degree over two nodes and hands the concept edge the
        # weaker half. Same failure mode as the per-page mention node.
        owner = {item: node.name
                 for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
                 for item in node.body
                 if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                triples.add((module, "imports_from", f"code:module:{node.module}"))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    triples.add((module, "imports", f"code:module:{alias.name}"))
            elif isinstance(node, ast.ClassDef):
                cls = f"code:class:{rel}#{node.name}"
                triples.add((module, "defines_class", cls))
                _register(defined, ambiguous, node.name, cls)
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        triples.add((cls, "inherits", f"code:symbol:{base.id}"))
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        triples.add((cls, "has_method",
                                     f"code:func:{rel}#{node.name}.{item.name}"))
                    elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field = f"type:field:{rel}#{node.name}.{item.target.id}"
                        triples.add((cls, "has_field", field))
                        if isinstance(item.annotation, ast.Name):
                            triples.add((field, "has_type", f"type:name:{item.annotation.id}"))
                        _register(defined, ambiguous, item.target.id, field)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                holder = owner.get(node)
                fn = (f"code:func:{rel}#{holder}.{node.name}" if holder
                      else f"code:func:{rel}#{node.name}")
                if holder is None:      # a method is already tied to its class
                    triples.add((module, "defines_func", fn))
                _register(defined, ambiguous, node.name, fn)
                for arg in node.args.args:
                    if isinstance(arg.annotation, ast.Name):
                        triples.add((fn, "param_type", f"type:name:{arg.annotation.id}"))
                if isinstance(node.returns, ast.Name):
                    triples.add((fn, "returns_type", f"type:name:{node.returns.id}"))


def _knowledge_plane(md_files: list[pathlib.Path], root: pathlib.Path,
                     py_rel: set[str], triples: set[Triple], defined: dict[str, str],
                     blind: collections.Counter) -> None:
    """Knowledge plane, and the two cross-plane relations. See rules 1 and 2."""
    for path in md_files:
        text = _read(path, blind, "markdown")
        if text is None:
            continue
        rel = path.relative_to(root).as_posix()
        doc = f"knowledge:doc:{rel}"
        here = posixpath.dirname(rel)
        links = MD_LINK.findall(text)
        if len(links) > MAX_LINKS_PER_PAGE:
            blind[f"markdown page(s) truncated: only the first "
                  f"{MAX_LINKS_PER_PAGE} links read"] += 1
            # the windowless count beside the window: pages alone do not say
            # how many statements were lost
            blind[f"markdown link(s) not read: page link list truncated at "
                  f"{MAX_LINKS_PER_PAGE}"] += len(links) - MAX_LINKS_PER_PAGE
        for target in links[:MAX_LINKS_PER_PAGE]:
            raw = target.split("#")[0].split("?")[0].replace("\\", "/").strip()
            if not raw or raw.startswith("<"):
                continue
            # Resolved as a string, never through the filesystem. ``Path.resolve``
            # on a protocol-relative or UNC-shaped target (``//host/share``, which
            # Markdown badge links produce) makes Windows go ask the network:
            # measured, one 11 KB README cost 331 s of DNS timeouts. A read-only
            # metric must not open an egress path because of a string in a doc.
            if raw.startswith("/") or SCHEME.match(raw):
                blind["markdown link(s) not modelled: a URL or an absolute "
                      "path, so it names nothing in this tree"] += 1
                continue
            rel_target = posixpath.normpath(posixpath.join(here, raw))
            if rel_target.startswith("..") or rel_target == ".":
                blind["markdown link(s) not modelled: target resolves outside the tree"] += 1
                continue
            # RULE 1: the code node itself, never a parallel knowledge:file node.
            if rel_target in py_rel:
                triples.add((doc, "documents_file", f"code:module:{rel_target}"))
            else:
                triples.add((doc, "links_to", f"knowledge:file:{rel_target}"))
        for span in sorted(set(MD_CODE.findall(text))):
            # RULE 2: one node per concept for the whole tree, not per page.
            concept = f"knowledge:concept:{span}"
            triples.add((doc, "mentions", concept))
            if span in defined:
                triples.add((concept, "documents", defined[span]))


def _extract(root: pathlib.Path) -> tuple[list[Triple], list[str], set[str]]:
    """``extract_graph``, what the walk could not see, and the ambiguous names."""
    blind: collections.Counter = collections.Counter()
    triples: set[Triple] = set()
    defined: dict[str, str] = {}
    ambiguous: set[str] = set()
    if not root.is_dir():
        # a mistyped path walks nothing and would otherwise print exactly what a
        # real but empty tree prints -- the instrument has to say which it saw
        return [], [f"root is not a directory: {root.as_posix()} -- nothing was "
                    f"walked, so this is not a measurement of an empty tree"], ambiguous
    files, nested = _walk(root)

    py_files = files.get(".py", [])
    md_files = files.get(".md", [])
    py_rel = {p.relative_to(root).as_posix() for p in py_files}
    _python_plane(py_files, root, triples, defined, ambiguous, blind)
    _knowledge_plane(md_files, root, py_rel, triples, defined, blind)

    could_not_measure = [f"{count} {reason}" for reason, count in sorted(blind.items())]
    for label, suffixes in sorted(UNREAD_SUFFIXES.items()):
        count = sum(len(files.get(s, ())) for s in suffixes)
        if count:
            could_not_measure.append(
                f"{count} file(s) in tree not extracted at all -- {label}")
    if nested:
        shown = ", ".join(nested[:3]) + (", ..." if len(nested) > 3 else "")
        could_not_measure.append(
            f"{len(nested)} nested git checkout(s) not walked -- own .git marker, "
            f"so another repository, not this project's structure: {shown}")
    if not py_files:
        could_not_measure.append("no Python file found: the code plane is empty, "
                                 "so no cross-plane edge can exist by construction")
    if not md_files:
        could_not_measure.append("no Markdown file found: the knowledge plane is empty, "
                                 "so no cross-plane edge can exist by construction")
    return sorted(triples), could_not_measure, ambiguous


def extract_graph(root: pathlib.Path) -> list[Triple]:
    """Sorted ``(head, relation, tail)`` triples of the fourfold graph under ``root``.

    Nodes are ``<plane>:<kind>:<locator>``. Planes here are ``code``, ``type``
    and ``knowledge``; the data plane is not read (see ``could_not_measure`` on
    ``wiki_health``). Deterministic: same tree, same list.

    Use ``wiki_health`` when you need the blind-spot list as well -- this
    function drops it, and a triple list alone cannot tell you what is missing.
    """
    return _extract(pathlib.Path(root).resolve())[0]


def k_core(triples: list[Triple], k: int) -> tuple[list[Triple], set[str]]:
    """The load-bearing core: drop every node below degree ``k``, until fixed.

    Degree counts incident triples, so a node needs ``k`` distinct statements
    about it to stay. Returns the surviving triples and the surviving nodes.

    Peeled with a work list rather than by re-scanning all triples per round.
    The obvious rescan version is O(E) per round and the round count is itself
    O(E) in the worst case; on project_tct (36k triples) that did not finish in
    180s, while this returns in well under a second. Same fixed point.
    """
    incident: dict[str, list[int]] = collections.defaultdict(list)
    for index, (head, _, tail) in enumerate(triples):
        incident[head].append(index)
        incident[tail].append(index)
    degree = {node: len(idx) for node, idx in incident.items()}
    alive = [True] * len(triples)
    dropped: set[str] = set()
    pending = [node for node, deg in degree.items() if deg < k]
    while pending:
        node = pending.pop()
        if node in dropped:
            continue
        dropped.add(node)
        for index in incident[node]:
            if not alive[index]:
                continue
            alive[index] = False
            head, _, tail = triples[index]
            for other in (head, tail):
                if other in dropped:
                    continue
                degree[other] -= 1
                if degree[other] < k:
                    pending.append(other)
    keep = {node for node in degree if node not in dropped}
    return [t for t, ok in zip(triples, alive) if ok], keep


def _ambiguous_edges(triples: list[Triple], ambiguous: set[str]) -> int:
    """``documents`` edges whose concept name has several definitions in the tree."""
    prefix = "knowledge:concept:"
    return sum(1 for head, rel, _ in triples
               if rel == "documents" and head.startswith(prefix)
               and head[len(prefix):] in ambiguous)


def _planes(nodes) -> dict[str, int]:
    """Node count per plane, key-sorted so the output is byte-stable."""
    counted = collections.Counter(node.split(":", 1)[0] for node in nodes)
    return dict(sorted(counted.items()))


def wiki_health(root: pathlib.Path, k: int = 3) -> dict:
    """Structural health of the wiki under ``root``, as a JSON-ready dict.

    The headline is ``crossplane_survival_rate``: of every doc->source edge the
    documentation asserts, the share still standing in the ``k``-core. Measured
    range on project_tct across wiki states: 0.0 (mention-per-page modelling,
    an instrument artefact), 0.26 (concepts, wiki before), 0.315 and 0.383
    (wiki after, links onto code nodes). This module on the same tree, same
    day: 0.3947 -- it differs from 0.383 because it drops the data plane and
    keeps one node per method instead of two, both of which raise degree
    around the documented symbol.

    ``None`` for that rate means there was nothing to divide by, and
    ``could_not_measure`` says so. It is not a zero.
    """
    root = pathlib.Path(root).resolve()
    triples, could_not_measure, ambiguous = _extract(root)

    degree: collections.Counter = collections.Counter()
    for head, _, tail in triples:
        degree[head] += 1
        degree[tail] += 1
    entities = len(degree)

    core, kept = k_core(triples, k)
    full_rel = collections.Counter(r for _, r, _ in triples)
    core_rel = collections.Counter(r for _, r, _ in core)
    crossplane_edges = sum(full_rel.get(r, 0) for r in CROSS_PLANE_RELATIONS)
    crossplane_core = sum(core_rel.get(r, 0) for r in CROSS_PLANE_RELATIONS)
    on_guess = [_ambiguous_edges(triples, ambiguous), _ambiguous_edges(core, ambiguous)]
    if crossplane_edges:
        rate: float | None = round(crossplane_core / crossplane_edges, 4)
    else:
        rate = None
        could_not_measure.append(
            "crossplane_survival_rate: no doc->source edge exists, so the rate is "
            "undefined -- this is not a measured 0.0")
    if not entities:
        could_not_measure.append("graph is empty: no triple could be extracted from this tree")

    return {
        "metrics_version": METRICS_VERSION,
        "root": root.as_posix(),
        "k": k,
        "entities": entities,
        "triples": len(triples),
        "avg_degree": round(2 * len(triples) / entities, 3) if entities else 0.0,
        # nodes named exactly once: no structure around them, they die first
        "seen_once_share": (round(sum(1 for d in degree.values() if d == 1) / entities, 4)
                            if entities else 0.0),
        "core_entities": len(kept),
        "core_triples": len(core),
        "core_share": round(len(kept) / entities, 4) if entities else 0.0,
        # sorted, not Counter order: ``kept`` is a set, and set iteration order
        # of strings changes per process, which would make two runs on the same
        # tree produce different JSON for the same measurement
        "planes": _planes(degree),
        "core_planes": _planes(kept),
        "crossplane_relations": list(CROSS_PLANE_RELATIONS),
        "crossplane_edges": crossplane_edges,
        "crossplane_core": crossplane_core,
        "crossplane_by_relation": {r: [full_rel.get(r, 0), core_rel.get(r, 0)]
                                   for r in CROSS_PLANE_RELATIONS},
        "crossplane_survival_rate": rate,
        # [all, surviving] documents edges whose backticked name has more than
        # one definition in the tree, so the edge points at the first of several
        # candidates: the share of the headline that rests on that guess
        "documents_on_ambiguous_names": on_guess,
        "could_not_measure": could_not_measure,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = pathlib.Path(args[0]) if args else pathlib.Path.cwd()
    if not root.is_dir():
        print(f"not a directory: {root.resolve().as_posix()}", file=sys.stderr)
        return 2
    k = int(args[1]) if len(args) > 1 else 3
    print(json.dumps(wiki_health(root, k), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

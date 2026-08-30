# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Spectral structure metrics over the reachability graph.

The question this module answers is ONE question: *does our declared package
structure match our actual structure?* Four numbers answer it from four sides,
and each one is defined so that a reader can act on it without asking a
mathematician what it means.

RELATIONSHIP TO ``daedalus/structcore/topology.py`` -- READ THIS FIRST
----------------------------------------------------------------------
A spectral module already exists and this one does NOT replace or fork it.

  * ``structcore.topology.spectral_partition`` produces ONE PRODUCT: a two-way
    visualization cut of the *structcore index* graph, served to the web UI at
    ``/api/topology``. Its output is a partition -- a picture.
  * This module produces NO partition and serves no UI. It produces MEASUREMENTS
    ABOUT A PARTITION WE ALREADY DECLARED (the package layout on disk), over the
    *reachability* graph from :func:`daedalus.mapping.reach.analyse` -- the same
    graph ``docs/architecture-state.json`` is built from, which is branch-aware
    and deliberately refuses the ``if False:`` and swallowed-``ImportError``
    edges the structcore index carries (see ``reach.analyse``'s docstring).

Different graph, different output, different consumer. The Fiedler vector shows
up in both because both need the second Laplacian eigenvector; in neither case
is an eigensolver hand-rolled -- both call networkx/scipy. If you are adding a
fifth spectral thing, extend one of these two rather than opening a third.

NO GRAPH IS BUILT HERE. There is exactly one import-graph extractor on the
mapping side and it is ``reach.analyse``. :func:`graph_from_reach` is an
adapter over its output, not a second walker.

THIS IS EVIDENCE, NEVER A GATE
------------------------------
Nothing here returns an exit code, blocks a lane, moves a picker band, or
decides anything. Every value is a measurement attached to a candidate a human
or the picker already had for other reasons. A structure metric that can block
is a structure metric that will be gamed; these are trend lines and arguments,
not thresholds. There is no threshold constant in this file on purpose.

Undirected on purpose: Laplacian spectral theory as used here (Fiedler vector,
algebraic connectivity, modularity, conductance) is defined for undirected
graphs. ``A imports B`` is projected to an undirected edge, which loses
direction and keeps adjacency. That trade is stated in every report dict as
``graph_type`` so no reader mistakes a cut for a dependency direction.
"""

from __future__ import annotations

import math
import random
from typing import Any, Iterable, Mapping, Sequence

# "which package does this file declare itself in" is ONE question and
# inventory.py already answers it. Importing beats restating a rule that must
# stay identical across the two modules or the numbers stop being comparable.
from .inventory import _area_of as declared_package

try:  # mirrors structcore.topology's guard, deliberately: same extra, same word
    import networkx as nx

    HAVE_MATH = True
except ImportError:  # pragma: no cover - exercised by the unavailable-path test
    HAVE_MATH = False

__all__ = [
    "HAVE_MATH",
    "MATH_EXTRA_HINT",
    "analyse",
    "conductance_report",
    "declared_partition",
    "declared_package",
    "eigengap_report",
    "fiedler_report",
    "graph_from_reach",
    "graph_from_edges",
    "modularity_report",
    "spectral_evidence",
]

MATH_EXTRA_HINT = "install the 'math' extra (numpy, scipy, networkx)"

# Random-partition trials for the modularity baseline. Enough that the mean is
# not noise, small enough that the whole report stays sub-second on this repo.
DEFAULT_TRIALS = 50
DEFAULT_SEED = 20260729

# How many eigenvalues to consider when guessing a cluster count. Beyond this
# the "largest gap" heuristic is reading tea leaves in the tail of the spectrum.
DEFAULT_K_MAX = 12


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


# --------------------------------------------------------------------------
# graph adapters -- NOT extractors
# --------------------------------------------------------------------------

def graph_from_edges(edges: Mapping[str, Iterable[str]],
                     *, nodes: Iterable[str] | None = None) -> "nx.Graph":
    """Undirected projection of a ``{source: [targets]}`` mapping.

    Exists so a synthetic graph with known ground truth can be measured by the
    exact code path the repo graph goes through. A metric validated on a
    different code path than the one that ships is not validated.
    """
    graph = nx.Graph()
    if nodes is not None:
        graph.add_nodes_from(sorted(nodes))
    for source in sorted(edges):
        graph.add_node(source)
        for target in sorted(edges[source]):
            if target == source:
                continue  # a self-import is not a structural edge
            graph.add_edge(source, target)
    return graph


def graph_from_reach(report: Any, *,
                     scope_prefixes: Sequence[str] | None = None) -> "nx.Graph":
    """Undirected projection of a :class:`daedalus.mapping.reach.ReachReport`.

    Every node is a repo-relative ``.py`` path, exactly as
    ``docs/architecture-state.json`` names them, so a number reported here can
    be pasted next to an island or shim from the same snapshot.

    ``scope_prefixes`` restricts the graph to modules under those path prefixes.
    Default None means MEASURE EVERYTHING -- no hidden filtering, because a
    metric with an invisible exclusion list is a metric nobody can check.

    It exists because the whole-repo reading is dominated by a partition
    artifact: ``tests/`` is ~half the modules, and test files import the code
    under test and never each other, so the test package scores leak_rate 1.0
    with zero internal edges. That is CORRECT and MEANINGLESS -- it is what a
    test suite is supposed to look like, not a finding. Pass
    ``scope_prefixes=("daedalus/",)`` to measure the shipped package's own
    structure. Report which one you took; the two are not comparable.
    """
    modules = list(getattr(report, "modules", ()) or ())
    if scope_prefixes:
        wanted = tuple(scope_prefixes)
        modules = [m for m in modules if str(m.module).startswith(wanted)]
    names = [m.module for m in modules]
    edges = {m.module: tuple(m.imports or ()) for m in modules}
    known = set(names)
    # reach may record an import of something outside the scanned tree; those
    # are real facts but not nodes of this graph, and inventing nodes for them
    # would inflate every denominator below.
    trimmed = {src: [t for t in tgts if t in known] for src, tgts in edges.items()}
    return graph_from_edges(trimmed, nodes=names)


def declared_partition(modules: Iterable[str]) -> dict[str, list[str]]:
    """The structure we CLAIM: every module grouped by its directory package.

    This is the partition the metrics below judge. It is read off the tree, not
    proposed by any algorithm -- the whole point is to score a human decision.
    """
    groups: dict[str, list[str]] = {}
    for module in modules:
        groups.setdefault(declared_package(module), []).append(module)
    return {pkg: sorted(mods) for pkg, mods in sorted(groups.items())}


def _communities(partition: Mapping[str, Sequence[str]],
                 graph: "nx.Graph") -> list[set[str]]:
    """Partition as a list of node sets covering exactly ``graph``'s nodes."""
    seen: set[str] = set()
    out: list[set[str]] = []
    for members in partition.values():
        block = {m for m in members if m in graph}
        block -= seen
        if block:
            out.append(block)
            seen |= block
    missing = set(graph.nodes) - seen
    if missing:  # any node the caller's partition forgot forms its own block
        out.append(missing)
    return out


def _giant(graph: "nx.Graph") -> "nx.Graph":
    """The largest connected component, as a subgraph view copy."""
    components = list(nx.connected_components(graph))
    if not components:
        return graph
    biggest = max(components, key=lambda c: (len(c), sorted(c)[0]))
    return graph.subgraph(biggest).copy()


# --------------------------------------------------------------------------
# 1. Fiedler vector / algebraic connectivity -- where is the natural seam?
# --------------------------------------------------------------------------

def fiedler_report(graph: "nx.Graph", partition: Mapping[str, Sequence[str]]
                   | None = None, *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """Where the graph wants to be cut, and whether our walls agree with it.

    ``algebraic_connectivity`` (the second-smallest Laplacian eigenvalue) is how
    hard the graph resists being split. ``boundary_agreement`` per package is the
    fraction of that package's modules landing on the SAME side of the Fiedler
    split -- 1.0 means the package sits wholly inside one natural half.

    WHAT TO DO WITH THE NUMBER
      * agreement ~1.0  -- a REAL SEAM. The package boundary is also where the
        graph would tear. Safe to extract, to own separately, to distil against.
      * agreement ~0.5  -- a FALSE WALL. The package name spans two natural
        halves; the directory is a filing decision, not a structural one.
        Splitting work along it will keep producing cross-cutting changes.
      * algebraic_connectivity near 0 -- the graph is nearly disconnected
        already; the "cut" is barely a cut and the seam is close to free.
      * algebraic_connectivity high -- densely tied; any two-way split will cost
        real edges and "just extract a module" is not going to be cheap.

    Reported on the largest connected component when the graph is disconnected:
    a disconnected graph has algebraic connectivity exactly 0 and no unique
    Fiedler vector, and fabricating one would be the numerology this module
    exists to prevent. Both the global 0.0 and the component value are returned,
    labelled, so neither can be quoted as the other.
    """
    if not HAVE_MATH:
        return _unavailable(MATH_EXTRA_HINT)
    if graph.number_of_nodes() < 2:
        return _unavailable("a graph with fewer than 2 nodes has no Fiedler vector")

    components = list(nx.connected_components(graph))
    connected = len(components) == 1
    scope = graph if connected else _giant(graph)
    if scope.number_of_nodes() < 2:
        return _unavailable(
            "every connected component is a single node; there is no seam to find")

    try:
        vector = nx.fiedler_vector(scope, normalized=True, method="lanczos",
                                   seed=seed)
    except Exception as exc:  # eigensolver refusal is a finding, not a crash
        return _unavailable(f"eigensolver failed: {exc}")

    order = sorted(scope.nodes)
    values = {node: float(vector[i]) for i, node in enumerate(order)}
    # The sign of an eigenvector is arbitrary. Pin it so two runs over an
    # unchanged tree produce the same dict -- provenance requires it.
    if sum(values.values()) < 0 or (
            math.isclose(sum(values.values()), 0.0, abs_tol=1e-12)
            and values[order[0]] < 0):
        values = {node: -v for node, v in values.items()}

    positive = {node for node, v in values.items() if v >= 0}
    negative = set(values) - positive
    cut_edges = int(nx.cut_size(scope, positive, negative)) if negative else 0
    lambda2 = round(float(nx.algebraic_connectivity(
        scope, normalized=True, method="lanczos", seed=seed)), 6)

    agreement: dict[str, dict[str, Any]] = {}
    if partition:
        for pkg, members in partition.items():
            inside = [m for m in members if m in values]
            if not inside:
                continue
            pos = sum(1 for m in inside if m in positive)
            frac = max(pos, len(inside) - pos) / len(inside)
            agreement[pkg] = {
                "modules": len(inside),
                "boundary_agreement": round(frac, 4),
                # Stated verbatim so a reader never has to recall the scale.
                "reads_as": ("real seam" if frac >= 0.9 else
                             "mostly aligned" if frac >= 0.7 else "false wall"),
            }

    return {
        "available": True,
        "graph_type": "undirected projection of directed import edges",
        "connected": connected,
        "connected_components": len(components),
        "scope": "whole graph" if connected else "largest connected component",
        "scope_nodes": scope.number_of_nodes(),
        # A disconnected graph's algebraic connectivity is exactly 0 -- that is
        # the true global answer, and the component value is a DIFFERENT number
        # about a DIFFERENT graph. Both are labelled so neither can be quoted
        # as the other.
        "algebraic_connectivity_global": lambda2 if connected else 0.0,
        "algebraic_connectivity_scope": lambda2,
        "cut_edges": cut_edges,
        "side_sizes": [len(positive), len(negative)],
        "fiedler_values": {n: round(v, 8) for n, v in sorted(values.items())},
        "boundary_agreement": dict(sorted(agreement.items())),
    }


# --------------------------------------------------------------------------
# 2. Newman modularity -- declared structure vs. a coin flip
# --------------------------------------------------------------------------

def modularity_report(graph: "nx.Graph", partition: Mapping[str, Sequence[str]],
                      *, trials: int = DEFAULT_TRIALS,
                      seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """How much better our packages group the graph than a random grouping.

    ``declared`` is Newman modularity Q of the on-disk package partition.
    ``random_mean`` is Q of partitions with the SAME block sizes and shuffled
    membership -- the null hypothesis, measured rather than assumed.
    ``lift`` is ``declared - random_mean``.

    WHAT TO DO WITH THE NUMBER
      * Q >= 0.3 with clear lift -- the package layout is real structure.
        Trend it; a drop between two commits means a change blurred a boundary.
      * Q ~ 0.1-0.3 -- weak. The layout groups something, but plenty of coupling
        crosses it. Worth a look at the worst conductance packages below.
      * lift <= 0 -- the declared layout is NO BETTER than shuffling the files.
        The directory tree is filing, not architecture, and any claim that
        "module X is a separate concern" is currently unsupported by the graph.
      * Q < 0 -- worse than random: blocks are internally sparser than chance.

    Q is not comparable across different graphs -- only across snapshots of THIS
    graph. That is why the raw counts travel with it in the returned dict.
    """
    if not HAVE_MATH:
        return _unavailable(MATH_EXTRA_HINT)
    if graph.number_of_edges() == 0:
        return _unavailable("a graph with no edges has undefined modularity")

    blocks = _communities(partition, graph)
    if len(blocks) < 2:
        return _unavailable("modularity needs at least 2 non-empty blocks")

    declared = float(nx.community.modularity(graph, blocks))

    nodes = sorted(graph.nodes)
    sizes = [len(b) for b in blocks]
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(max(1, trials)):
        shuffled = list(nodes)
        rng.shuffle(shuffled)
        cut, random_blocks = 0, []
        for size in sizes:
            random_blocks.append(set(shuffled[cut:cut + size]))
            cut += size
        random_blocks = [b for b in random_blocks if b]
        samples.append(float(nx.community.modularity(graph, random_blocks)))

    random_mean = sum(samples) / len(samples)
    random_max = max(samples)
    return {
        "available": True,
        "declared": round(declared, 6),
        "random_mean": round(random_mean, 6),
        "random_max": round(random_max, 6),
        "lift": round(declared - random_mean, 6),
        "beats_random": bool(declared > random_max),
        "trials": len(samples),
        "seed": seed,
        "blocks": len(blocks),
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "reads_as": ("real structure" if declared >= 0.3 else
                     "weak structure" if declared >= 0.1 else
                     "filing, not architecture"),
    }


# --------------------------------------------------------------------------
# 3. Conductance per declared module -- who leaks
# --------------------------------------------------------------------------

def conductance_report(graph: "nx.Graph", partition: Mapping[str, Sequence[str]]
                       ) -> dict[str, Any]:
    """Per package: what fraction of its own edge volume leaves it.

    ``leak_rate`` is ``cut(S) / vol(S)`` -- of all the edge-endpoints this
    package has, the share that point outside it. Normalised for size, so a
    3-file package and a 60-file package compare directly, which raw cut counts
    do not. RANK BY THIS ONE.

    ``conductance_symmetric`` is textbook conductance, ``cut(S) / min(vol(S),
    vol(rest))``. It is reported for cross-reference and it is NOT the ranking
    key, because the ``min`` makes it symmetric: with a two-block partition it
    hands the tight 10-clique and the 2-file shim the SAME number, and a reader
    would conclude the core is a pass-through. That is exactly the kind of
    number-shaped falsehood this module exists to avoid, so both are printed
    with their formulas rather than one being quietly picked.

    WHAT TO DO WITH THE NUMBER (leak_rate)
      * ~0.0-0.2 -- a tight package. Most of its edges are internal. This is
        what a real module looks like; leave it alone.
      * ~0.2-0.5 -- ordinary coupling for a working package. Not a finding.
      * >0.8 -- nearly every edge crosses the boundary. The package is a
        PASS-THROUGH: a directory of files that talk to everything except each
        other. Candidate for dissolving into its callers, or for being renamed
        to what it actually is. Cross-check against the shim list before acting.
      * 1.0 with a small module count -- the classic shim/island shape: nothing
        internal at all.

    Sorted worst-first, because the only reason to read this list is to find the
    top of it. Packages that are the whole graph, or that have zero volume, are
    reported with ``leak_rate: None`` rather than a fabricated number.
    """
    if not HAVE_MATH:
        return _unavailable(MATH_EXTRA_HINT)
    if graph.number_of_edges() == 0:
        return _unavailable("a graph with no edges has undefined conductance")

    rows: list[dict[str, Any]] = []
    all_nodes = set(graph.nodes)
    for pkg, members in partition.items():
        inside = {m for m in members if m in graph}
        outside = all_nodes - inside
        if not inside:
            continue
        volume = int(nx.volume(graph, inside))
        outside_volume = int(nx.volume(graph, outside)) if outside else 0
        if not outside or volume == 0:
            rows.append({"package": pkg, "modules": len(inside),
                         "internal_edges": graph.subgraph(inside).number_of_edges(),
                         "cut_edges": 0, "volume": volume,
                         "leak_rate": None, "conductance_symmetric": None,
                         "reads_as": ("the package is the whole graph"
                                      if not outside else "no edges at all")})
            continue
        cut = int(nx.cut_size(graph, inside, outside))
        leak = cut / volume
        # Guarded rather than delegated: nx.conductance divides by
        # min(vol(S), vol(rest)) and raises ZeroDivisionError when the rest of
        # the graph is all isolated nodes. A crash is not a measurement.
        floor = min(volume, outside_volume)
        symmetric = round(cut / floor, 6) if floor else None
        rows.append({
            "package": pkg,
            "modules": len(inside),
            "internal_edges": graph.subgraph(inside).number_of_edges(),
            "cut_edges": cut,
            "volume": volume,
            "leak_rate": round(leak, 6),
            "conductance_symmetric": symmetric,
            "reads_as": ("pass-through" if leak > 0.8 else
                         "leaky" if leak > 0.5 else
                         "ordinary" if leak > 0.2 else "tight"),
        })

    rows.sort(key=lambda r: (-(r["leak_rate"] if r["leak_rate"] is not None
                               else -1.0), r["package"]))
    return {"available": True, "packages": len(rows), "rows": rows}


# --------------------------------------------------------------------------
# 4. Eigengap -- how many clusters we actually are
# --------------------------------------------------------------------------

def eigengap_report(graph: "nx.Graph", *, k_max: int = DEFAULT_K_MAX,
                    declared_blocks: int | None = None) -> dict[str, Any]:
    """How many natural clusters the spectrum says the graph has.

    The normalized Laplacian's eigenvalues are sorted ascending; the largest gap
    between consecutive eigenvalues at position ``k`` says "there are k
    clusters" (the eigengap heuristic). Zero eigenvalues count connected
    components exactly, so a disconnected graph's answer is dominated by them --
    the component-free reading over the largest component is reported alongside.

    WHAT TO DO WITH THE NUMBER
      * ``clusters`` close to ``declared_packages`` -- the tree's granularity
        matches the graph's. Nothing to do.
      * ``clusters`` MUCH smaller (say 3 vs 20 packages) -- we have declared far
        more boundaries than the graph supports. Most package walls are
        cosmetic; consolidation will not lose structure that exists.
      * ``clusters`` MUCH larger -- there is structure inside our packages that
        we have not named. A package is doing several jobs; look for the split.
      * ``gap`` small and flat across k -- no honest answer. A weak, evenly
        connected graph has no natural cluster count and this metric should be
        ignored rather than rounded into a claim. ``confident`` says so.

    ``confident`` is the honest brake: it is False when the winning gap is not
    meaningfully larger than the runner-up, i.e. when the heuristic is guessing.
    """
    if not HAVE_MATH:
        return _unavailable(MATH_EXTRA_HINT)
    n = graph.number_of_nodes()
    if n < 3:
        return _unavailable("a graph with fewer than 3 nodes has no cluster count")
    if graph.number_of_edges() == 0:
        return _unavailable("a graph with no edges has no cluster structure")

    def _spectrum(g: "nx.Graph") -> list[float]:
        return sorted(float(v) for v in nx.normalized_laplacian_spectrum(g))

    def _pick(values: list[float], limit: int) -> tuple[int, float, float]:
        top = min(limit, len(values) - 1)
        gaps = [(values[k] - values[k - 1], k) for k in range(1, top + 1)]
        if not gaps:
            return 1, 0.0, 0.0
        gaps.sort(key=lambda item: (-item[0], item[1]))
        best_gap, best_k = gaps[0]
        runner = gaps[1][0] if len(gaps) > 1 else 0.0
        return best_k, best_gap, runner

    values = _spectrum(graph)
    components = nx.number_connected_components(graph)
    if components > 1:
        # The multiplicity of eigenvalue 0 IS the number of connected
        # components -- exactly, as a theorem. So on a disconnected graph the
        # first `components` eigenvalues are all 0 and every gap between them
        # is float noise; picking the largest of them returned a k derived from
        # rounding error. The honest answer is the component count, and the
        # interesting one is the giant component's, reported separately.
        k, gap, runner = components, 0.0, 0.0
        confident = True
        reason = ("the graph is disconnected; the cluster count is the "
                  "connected-component count by theorem, not by heuristic")
    else:
        k, gap, runner = _pick(values, k_max)
        confident = bool(gap > 1.5 * runner and gap > 0.02)
        reason = ("largest eigengap in the normalized Laplacian spectrum"
                  if confident else
                  "no dominant eigengap; this graph has no honest cluster count")

    scope_k: int | None = None
    scope_gap: float | None = None
    scope_confident: bool | None = None
    if components > 1:
        giant = _giant(graph)
        if giant.number_of_nodes() >= 3 and giant.number_of_edges() > 0:
            gvalues = _spectrum(giant)
            scope_k, scope_gap, scope_runner = _pick(gvalues, k_max)
            scope_confident = bool(scope_gap > 1.5 * scope_runner and scope_gap > 0.02)

    out = {
        "available": True,
        "clusters": int(k),
        "gap": round(gap, 6),
        "runner_up_gap": round(runner, 6),
        # A winning gap barely ahead of the next one is a coin flip wearing a
        # number's clothes. Say so instead of reporting k as a fact.
        "confident": confident,
        "basis": reason,
        "connected_components": int(components),
        "eigenvalues": [round(v, 6) for v in values[:k_max + 1]],
        "k_max": k_max,
        "nodes": n,
    }
    if declared_blocks is not None:
        out["declared_packages"] = int(declared_blocks)
        out["reads_as"] = (
            "granularity matches" if abs(k - declared_blocks) <= max(
                1, declared_blocks // 4) else
            "we declare more boundaries than the graph supports"
            if declared_blocks > k else
            "there is unnamed structure inside our packages")
    if scope_k is not None:
        out["giant_component"] = {
            "clusters": int(scope_k),
            "gap": round(float(scope_gap or 0.0), 6),
            "confident": bool(scope_confident),
        }
    return out


# --------------------------------------------------------------------------
# the whole reading
# --------------------------------------------------------------------------

def analyse(repo_root: Any = None, *, report: Any = None,
            graph: "nx.Graph | None" = None,
            partition: Mapping[str, Sequence[str]] | None = None,
            scope_prefixes: Sequence[str] | None = None,
            trials: int = DEFAULT_TRIALS, seed: int = DEFAULT_SEED,
            k_max: int = DEFAULT_K_MAX) -> dict[str, Any]:
    """All four metrics over one graph.

    Supply exactly one graph source: ``graph`` (already built), ``report`` (a
    :class:`~daedalus.mapping.reach.ReachReport`), or ``repo_root`` (in which
    case ``reach.analyse`` is called -- a WHOLE-REPO PASS, MEASURED at ~11s on
    this tree, which is why no hot path calls this without being asked to).

    ``scope_prefixes`` is echoed into the result as ``scope`` so a reading can
    never be quoted without saying what it was taken over. See
    :func:`graph_from_reach` for why you probably want ``("daedalus/",)``.
    """
    if not HAVE_MATH:
        return {"available": False, "reason": MATH_EXTRA_HINT}

    source = "graph"
    if graph is None:
        if report is None:
            if repo_root is None:
                return {"available": False,
                        "reason": "no graph, report or repo_root supplied"}
            from . import reach  # local: the 10s pass must be opt-in, not on import
            report = reach.analyse(repo_root)
            source = "reach.analyse(repo_root)"
        else:
            source = "reach.ReachReport"
        graph = graph_from_reach(report, scope_prefixes=scope_prefixes)
    elif scope_prefixes:
        return {"available": False,
                "reason": "scope_prefixes applies to a reach report, not a "
                          "pre-built graph; filter the graph before passing it"}

    if partition is None:
        partition = declared_partition(sorted(graph.nodes))

    return {
        "available": True,
        "graph_source": source,
        # Travels with every reading so a number can never be quoted without
        # what it was measured over.
        "scope": list(scope_prefixes) if scope_prefixes else "whole repo",
        "graph_type": "undirected projection of directed import edges",
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "declared_packages": len(partition),
        # Carried so :func:`spectral_evidence` can answer for EVERY module,
        # including the disconnected ones -- islands are exactly the modules the
        # picker asks about, and they are exactly the ones absent from the
        # Fiedler scope. An enrichment that goes blank where it is needed is
        # worse than none.
        "partition": {pkg: list(mods) for pkg, mods in partition.items()},
        "fiedler": fiedler_report(graph, partition, seed=seed),
        "modularity": modularity_report(graph, partition, trials=trials,
                                        seed=seed),
        "conductance": conductance_report(graph, partition),
        "eigengap": eigengap_report(graph, k_max=k_max,
                                    declared_blocks=len(partition)),
    }


def spectral_evidence(reading: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten a full :func:`analyse` reading into per-module evidence rows.

    The picker enriches an EXISTING candidate's evidence with these; it never
    creates a candidate from them and never lets them move a band. A module that
    is not in the graph gets no row, so a caller that looks one up gets nothing
    rather than a zero that reads like a measurement.

    ``spectral_fiedler_value`` is None for a module outside the Fiedler scope
    (an island, or any node off the largest component). None means NOT MEASURED
    -- never 0.0, which would read as "sits on the seam".
    """
    if not reading.get("available"):
        return {}
    fiedler = reading.get("fiedler") or {}
    values = fiedler.get("fiedler_values") or {}
    agreement = fiedler.get("boundary_agreement") or {}
    cond_rows = {row["package"]: row
                 for row in ((reading.get("conductance") or {}).get("rows") or [])}
    modularity = reading.get("modularity") or {}
    partition = reading.get("partition") or {}
    modules = {m for members in partition.values() for m in members} or set(values)

    out: dict[str, dict[str, Any]] = {}
    for module in sorted(modules):
        pkg = declared_package(module)
        row = cond_rows.get(pkg) or {}
        agree = agreement.get(pkg) or {}
        out[module] = {
            "spectral_package": pkg,
            "spectral_package_leak_rate": row.get("leak_rate"),
            "spectral_package_reads_as": row.get("reads_as"),
            "spectral_boundary_agreement": agree.get("boundary_agreement"),
            "spectral_boundary_reads_as": agree.get("reads_as"),
            "spectral_fiedler_value": values.get(module),
            "spectral_declared_modularity": modularity.get("declared"),
            "spectral_modularity_beats_random": modularity.get("beats_random"),
        }
    return out

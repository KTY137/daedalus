"""code_only_graph.py -- Gate-3 baseline (g): code-plane-only structural graph
retrieval (plan §11 Gate 3, C7).

WHY THIS ARM MATTERS (plan §14 kill criteria): "the full representation does
not beat code-only or BM25 retrieval" and "a plane has no marginal
contribution in ablation" are both measured AGAINST this arm. If a four-plane
Twin cannot beat a strong code-only graph baseline at an equal budget, that
kill criterion fires. A weak code-only arm would manufacture a false win for
the four-plane hypothesis -- exactly the defect this packet's docstrings
(``contracts.py``, ``bm25.py``) already name against the s08 four-separate-
indices slice (``docs/GATE2_FOREST_V2_TRIAGE.md:109-131``: a headline that was
an artifact of a starved measurement, not a real result). This arm must
therefore be genuinely strong, not a strawman.

WHAT "CODE-PLANE ONLY" MEANS HERE, STATED EXPLICITLY: this arm receives NO
type-plane, data-plane or knowledge-plane input (plan §5's four planes). The
corpus walk uses ``daedalus.structcore.languages.spec_for``, which returns a
``LanguageSpec`` only for programming-language source files -- markdown
(``.md``/``.markdown``/``.mdx``) is a separate ``DocumentSpec`` family, data
files (``.csv``, ``.json``, schemas) have no spec at all, and neither is ever
walked into this arm's units or graph. This exclusion is the definition of the
control, not an incidental filter: if a future change lets a document or data
file leak into this module's corpus, that silently converts the code-only
control into something else and invalidates any kill-criterion measurement
that used it.

STRUCTURAL RELATIONS -- what "graph" means for this arm, and the reuse behind
each edge type (packet §2, "extend, never duplicate": no second AST parser, no
second import resolver):

  * IMPORTS   -- ``daedalus.structcore.index.cached_index(..., documents=False,
                 types=False, wiki=False, effect_free=True)["import_edges"]``.
                 Reuses the existing precise-Python / best-effort-other-language
                 import resolution wholesale; this module adds no import parser
                 of its own. ``documents=False``/``types=False``/``wiki=False``
                 keep the index itself code-plane-only (its own docstring: those
                 layers are opt-in and additive). ``effect_free=True`` skips
                 ``git_churn``'s subprocess call -- this arm is offline by
                 construction (rule 5e/E6), not merely by accident of a repo
                 lacking git history.
  * CALLS     -- ``daedalus.structcore.graph.callees`` with a
                 ``daedalus.structcore.graph.SymbolResolver`` built by
                 ``build_resolver`` over this arm's own extracted units and the
                 same ``import_edges``. This is the repository's existing
                 import/scope-aware call-graph approximation (Movement I.5 /
                 Move 4); no second call-graph heuristic is introduced.
  * CONTAINMENT -- every unit in the same file as the focus target is treated
                 as immediately proximate (module-local rank 0), matching the
                 intuitive meaning of "this is defined right next to what I'm
                 looking at".
  * INHERITANCE -- a Python-syntax ``class Name(Base, ...):`` regex over each
                 file's own text. STATED LIMITATION: ``structcore.parse``
                 extracts function/method units only (no ``ClassDef`` units;
                 see ``parse.extract_units``'s docstring), so there is no
                 existing class-level extraction to reuse here, and building a
                 second full class extractor for every supported language is
                 out of this packet's scope. This baseline's inheritance edges
                 are therefore Python-only and best-effort, exactly the kind of
                 declared, non-hidden limitation packet C11 requires of the
                 AlphaEvolve proxy -- stated once, here, not discovered later.

GRANULARITY (a deliberate, documented choice): proximity is computed at
FILE/MODULE granularity (import, inheritance, and module-projected call
edges), because imports and inheritance are file-level relations in this
repository's own extraction. Within the target's own file, EVERY unit --
including the exact focus symbol -- sorts ahead of every other file by
construction (containment); the exact focus symbol always sorts first within
its file. This is a stated granularity choice, not a claim of function-level
BFS precision beyond what ``structcore.graph`` already provides.

BUDGET (packet rule R1): this arm receives ``budget.max_tokens`` as its full,
undivided retrieval budget. There are no internal components to split, so
``ArmBudget.split()`` is never called.

CORPUS UNIVERSE: every code-plane file under ``task.repo_root``, minus the
same build/VCS ignore list ``daedalus.eval.harness`` already applies
(``harness._IGNORE_DIRS``, reused directly rather than re-declared, so this
arm's ignore rules cannot silently drift from every other arm's).

DETERMINISM: ``stochastic = False``. Every collection this module walks is
either a sorted list already (the file walk, ``sorted(dirnames)``/
``sorted(filenames)``) or is explicitly sorted before iteration in the BFS and
in the final ranking key, so no step here depends on dict/set iteration order
and therefore not on ``PYTHONHASHSEED``. ``structcore.graph.callees`` already
carries this same discipline (see its own module docstring) for the call edges
this arm reuses.

SCORING: exactly one capability, ``evaluator.score(candidate, task)`` (plan §4
invariant 3). ``success`` uses this packet's existing convention (``bm25.py``,
``best_of_n.py``): the evaluator's own perfect-recall ceiling, 1.0.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from daedalus.eval import harness
from daedalus.structcore.graph import SymbolResolver, build_resolver, callees
from daedalus.structcore.index import cached_index
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import CodeUnit, extract_units

from ..contracts import ArmBudget, FreezeError
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: This packet's existing recall convention (``bm25.py``, ``best_of_n.py``):
#: a score of 1.0 means the gold labels were fully satisfied.
_SUCCESS_THRESHOLD = 1.0

#: ``callees`` is O(units) per unit (it rebuilds a name index and scans every
#: candidate's identifiers), so computing module-level call edges over ALL
#: units is O(units^2). Fine for the eval task repositories this packet
#: targets; a stated, honest ceiling above which this arm still runs -- it
#: just reports the call-edge layer as skipped rather than silently paying an
#: unbounded quadratic cost or (worse) hanging the run.
_MAX_UNITS_FOR_CALL_GRAPH = 4000

# Python-only, deliberately (see module docstring's INHERITANCE section).
_CLASS_RE = re.compile(r"^[ \t]*class\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*:", re.MULTILINE)
_BASE_IGNORE = {"object", "", "metaclass=type"}


def _collect_units_and_texts(root: str) -> tuple[list[CodeUnit], dict[str, str]]:
    """Every code-plane unit under ``root``, plus the full text of each file
    that produced them (needed for the inheritance regex pass). One synthetic
    whole-file unit (``name=""``) stands in for a file with nothing
    extractable -- the same fallback ``daedalus.eval.harness._repo_chunks``
    uses for the BM25 arm's corpus, kept here rather than imported because
    that function returns ``(label, text)`` tuples and this arm needs real
    ``CodeUnit`` objects (module/name/source) for ``structcore.graph``.
    """
    units: list[CodeUnit] = []
    texts: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in harness._IGNORE_DIRS and not d.startswith(".")
        )
        for fn in sorted(filenames):
            spec = spec_for(fn)
            if spec is None:
                continue  # CODE PLANE ONLY: no LanguageSpec => not this arm's corpus
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            rel = os.path.relpath(p, root).replace("\\", "/")
            texts[rel] = text
            extracted = extract_units(rel, text, spec)
            if extracted:
                units.extend(extracted)
            else:
                lines = text.count("\n") + 1
                units.append(CodeUnit(
                    language=spec.name, module=rel, name="", line=1,
                    end_line=lines, loc=lines, source=text,
                ))
    return units, texts


def _label(u: CodeUnit) -> str:
    return f"{u.module}::{u.name}" if u.name else u.module


def _symmetric(edges: Mapping[str, Sequence[str]]) -> dict[str, set[str]]:
    """A directed rel->[rels] edge map, made undirected. Proximity is a
    symmetric notion here (an import target is exactly as "close" to its
    importer as the importer is to it) -- unlike ``structcore.graph``'s own
    safety-fence BFS, which deliberately stays directed (blast radius only
    flows one way). Different question, different edge shape."""
    out: dict[str, set[str]] = {}
    for src, targets in edges.items():
        for tgt in targets:
            out.setdefault(src, set()).add(tgt)
            out.setdefault(tgt, set()).add(src)
    return out


def _inheritance_module_edges(texts: Mapping[str, str]) -> dict[str, set[str]]:
    """Module-level inheritance edges from Python ``class X(Base, ...):``
    syntax. See the module docstring's INHERITANCE section for why this is
    Python-only and file-granular rather than a second class-level parser."""
    class_owners: dict[str, list[str]] = {}
    class_decls: dict[str, list[tuple[str, ...]]] = {}
    for rel, text in texts.items():
        for m in _CLASS_RE.finditer(text):
            cls_name, bases_raw = m.group(1), m.group(2)
            class_owners.setdefault(cls_name, []).append(rel)
            bases = tuple(
                b.strip().rsplit(".", 1)[-1]
                for b in bases_raw.split(",")
                if b.strip() and b.strip() not in _BASE_IGNORE
            )
            if bases:
                class_decls.setdefault(rel, []).append(bases)

    edges: dict[str, set[str]] = {}
    for rel, decls in class_decls.items():
        for bases in decls:
            for base in bases:
                owners = sorted(o for o in class_owners.get(base, ()) if o != rel)
                if not owners:
                    continue
                target = owners[0]
                edges.setdefault(rel, set()).add(target)
                edges.setdefault(target, set()).add(rel)
    return edges


def _call_module_edges(units: list[CodeUnit],
                       resolver: SymbolResolver) -> dict[str, set[str]]:
    """Module-level projection of the unit-level call graph: an edge between
    two files whenever a unit in one resolves a call into the other (see
    ``structcore.graph.callees``). Skipped above ``_MAX_UNITS_FOR_CALL_GRAPH``
    -- see that constant's docstring."""
    edges: dict[str, set[str]] = {}
    for u in units:
        for callee in callees(u, units, resolver):
            if callee.module != u.module:
                edges.setdefault(u.module, set()).add(callee.module)
                edges.setdefault(callee.module, set()).add(u.module)
    return edges


def _merge_edges(*edge_maps: Mapping[str, set[str]]) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for edges in edge_maps:
        for src, targets in edges.items():
            merged.setdefault(src, set()).update(targets)
    return merged


def _module_distances(start_modules: Sequence[str],
                      graph_adj: Mapping[str, set[str]]) -> dict[str, int]:
    """Multi-source BFS, sorted frontiers throughout (mirrors the determinism
    discipline of ``structcore.graph.fenced_reachability``): the same start
    set and the same edges always produce the same distances, independent of
    dict/set iteration order."""
    dist: dict[str, int] = {m: 0 for m in sorted(set(start_modules))}
    frontier = sorted(dist)
    while frontier:
        nxt: list[str] = []
        for node in frontier:
            for nb in sorted(graph_adj.get(node, ())):
                if nb not in dist:
                    dist[nb] = dist[node] + 1
                    nxt.append(nb)
        frontier = sorted(nxt)
    return dist


def _rank_key(u: CodeUnit, target_module: str, target_name: str | None,
             module_dist: Mapping[str, int], fallback_dist: int) -> tuple[int, str]:
    label = _label(u)
    if u.module == target_module:
        if target_name is not None and u.name == target_name:
            return (-1, label)  # the exact focus symbol: always first
        return (0, label)       # containment: any sibling in the focus file
    return (module_dist.get(u.module, fallback_dist), label)


def _assemble(units_sorted: list[CodeUnit], budget_tokens: float) -> dict:
    """Greedy top-ranked-first assembly up to ``budget_tokens``, same shape as
    ``daedalus.eval.harness._bm25_context``: chunks are taken whole, the
    single best-ranked chunk is always included even alone over budget, and
    ``truncated`` is reported rather than silently clipping a later chunk."""
    picked: list[CodeUnit] = []
    total = 0
    truncated = False
    for u in units_sorted:
        block = f"# ===== {_label(u)} =====\n{u.source}\n"
        t = harness.count_tokens(block)
        if picked and total + t > budget_tokens:
            truncated = True
            break
        picked.append(u)
        total += t
    combined = "".join(f"# ===== {_label(u)} =====\n{u.source}\n" for u in picked)
    return {
        "text": combined,
        "n_units_total": len(units_sorted),
        "n_units_used": len(picked),
        "truncated": truncated,
        "tokens": harness.count_tokens(combined),
    }


@dataclass
class CodeOnlyGraphArm:
    """Gate-3 baseline (g): code-plane-only structural graph retrieval, full
    budget, no LLM. See the module docstring for the edge types, the
    granularity choice, and why this arm must be strong rather than a
    strawman.
    """

    name: str = "code_only_graph"
    stochastic: bool = False

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        del seed  # deterministic arm; accepted only to satisfy the Arm protocol
        try:
            units, texts = _collect_units_and_texts(task.repo_root)
        except OSError as exc:
            return ArmOutcome(error=f"OSError reading {task.repo_root!r}: {exc}")

        if not units:
            return ArmOutcome(
                error=f"no code-plane units found under {task.repo_root!r}")

        raw_target = (task.target or "").replace("\\", "/")
        if "::" in raw_target:
            target_module, target_name = raw_target.split("::", 1)
        else:
            target_module, target_name = raw_target, None

        focus_units = [u for u in units if u.module == target_module]
        if not focus_units:
            return ArmOutcome(
                error=f"target module {target_module!r} not found in "
                      "code-plane graph")

        try:
            idx = cached_index(task.repo_root, documents=False, types=False,
                               wiki=False, effect_free=True)
        except FreezeError:
            raise
        except Exception as exc:  # ordinary failure -> an errored outcome
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}")

        import_edges_raw: dict[str, list[str]] = idx.get("import_edges") or {}
        resolver = build_resolver(
            units, {m: set(t) for m, t in import_edges_raw.items()})

        import_module_edges = _symmetric(import_edges_raw)
        inheritance_edges = _inheritance_module_edges(texts)
        call_edges_skipped = len(units) > _MAX_UNITS_FOR_CALL_GRAPH
        call_edges = ({} if call_edges_skipped
                     else _call_module_edges(units, resolver))

        module_graph = _merge_edges(import_module_edges, inheritance_edges, call_edges)
        start_modules = sorted({u.module for u in focus_units})
        module_dist = _module_distances(start_modules, module_graph)
        fallback_dist = max(module_dist.values(), default=0) + 1

        ranked = sorted(
            units,
            key=lambda u: _rank_key(u, target_module, target_name, module_dist,
                                    fallback_dist),
        )

        budget_tokens = (budget.max_tokens if budget.max_tokens is not None
                        else math.inf)
        assembled = _assemble(ranked, budget_tokens)
        candidate = assembled["text"]

        try:
            score = evaluator.score(candidate, task)
        except FreezeError:
            raise
        except Exception as exc:
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}")

        return ArmOutcome(
            candidate=candidate,
            score=score,
            success=score >= _SUCCESS_THRESHOLD,
            tokens_used=assembled["tokens"],
            notes={
                "n_units_total": assembled["n_units_total"],
                "n_units_used": assembled["n_units_used"],
                "truncated": assembled["truncated"],
                "target_module": target_module,
                "target_name": target_name,
                "call_edges_skipped": call_edges_skipped,
            },
        )

"""Result sets rebuilt from measurements that actually exist on disk.

``synth`` builds runs whose ground truth is constructed, which tests the
evaluator and nothing else.  This module does the opposite and asks the
question the slice is for: *given the measurements this project has today,
can any kill criterion fire at all, or is the evaluator structurally unable
to say KILL?*

Provenance of everything below: slice s08 (`experiments/forest_v2/
s08_graph_baselines/`), branch ``grind/f2-s08`` @ ``3a785930``, its RAW
section "All 600 queries, cutoff 10" and the gross rescue/loss table beside
it.  600 queries, one gold document each, so ``recall@10`` per query is 1 or
0 and the published 2x2 tables *are* the paired data -- the reconstruction
below reproduces both marginals and the pairing exactly, and invents no
score.  What it cannot reproduce is a pairing s08 never published: where a
2x2 table is missing, the joint is filled deterministically and the affected
comparison is not consumed by any criterion.  Those gaps are named per run.

Two honest limits travel with every verdict derived from this input:

* **s08's query set carries code gold labels only.**  Every gold document is
  a code document by construction, so the type, data and knowledge indices
  score zero by arithmetic rather than by measurement.  Any cross-plane
  question -- above all 14.3, fusion versus separate indices -- is
  *instrumented* by this data, not decided by it.  s08 says so itself.
* **One run, one machine, no repeated trials.**  ``seeds`` is 1, and the
  evaluator attaches its low-seed warning to every verdict it reaches.

The runs are named after what s08 measured, not after what one might wish it
had measured.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from . import SCHEMA_ID

S08_COMMIT = "3a785930"
S08_QUERIES = 600
S08_SOURCE = (
    "slice s08 graph baselines, branch grind/f2-s08 @ 3a785930, RAW table "
    "'All 600 queries, cutoff 10' + gross rescue/loss table [MEASURED]"
)

#: The caveat that must travel with any verdict computed from this input.
S08_CAVEAT = (
    "every gold label in the s08 query set is a code document by construction, "
    "so the type/data/knowledge indices cannot score; cross-plane questions are "
    "instrumented by this run, not decided by it"
)


@dataclass(frozen=True)
class Contingency:
    """A published paired 2x2: hits of A and B over the same queries."""

    a: str
    b: str
    both: int
    only_a: int
    only_b: int
    neither: int

    @property
    def n(self) -> int:
        return self.both + self.only_a + self.only_b + self.neither

    @property
    def hits_a(self) -> int:
        return self.both + self.only_a

    @property
    def hits_b(self) -> int:
        return self.both + self.only_b


#: Verbatim from the s08 README's "Gross rescue/loss at k=10" table.
S08_PAIRS: Tuple[Contingency, ...] = (
    Contingency("bm25_code_only", "graph_code_only", 482, 9, 15, 94),
    Contingency("graph_rewired", "graph_code_only", 484, 7, 13, 96),
    Contingency("four_plane_no_fusion", "bm25_single_index", 415, 17, 23, 145),
    Contingency("four_plane_no_fusion", "bm25_code_only", 432, 0, 59, 109),
)


def pair(a: str, b: str) -> Contingency:
    for c in S08_PAIRS:
        if (c.a, c.b) == (a, b):
            return c
        if (c.a, c.b) == (b, a):
            return Contingency(b, a, c.both, c.only_b, c.only_a, c.neither)
    raise KeyError(f"s08 published no paired table for {a!r} vs {b!r}")


def _cases(n: int) -> List[str]:
    return [f"q{i:04d}" for i in range(n)]


def _anchor_vector(hits: int, n: int) -> List[int]:
    """The reference arm: the first ``hits`` cases are hits."""
    return [1 if i < hits else 0 for i in range(n)]


def _paired_to_anchor(anchor: Sequence[int], table: Contingency) -> List[int]:
    """Rebuild an arm paired against the anchor, from a published 2x2.

    ``table`` must be oriented (other, anchor).  Inside each stratum of the
    anchor the assignment is front-filled, which is deterministic and
    irrelevant: a paired comparison against the anchor only depends on the
    strata counts, which the table fixes exactly.
    """
    want_with = table.both        # other=1 where anchor=1
    want_without = table.only_a   # other=1 where anchor=0
    out: List[int] = []
    seen_hit = seen_miss = 0
    for value in anchor:
        if value:
            out.append(1 if seen_hit < want_with else 0)
            seen_hit += 1
        else:
            out.append(1 if seen_miss < want_without else 0)
            seen_miss += 1
    if sum(out) != table.hits_a:
        raise ValueError(f"reconstruction lost hits for {table.a!r}")
    return out


def _arm(arm_id: str, role: str, scores: Sequence[int], cases: Sequence[str],
         metric: str, note: str) -> Dict[str, object]:
    return {
        "arm_id": arm_id,
        "role": role,
        "variant": "raw",
        "note": note,
        "scores": {metric: {c: float(v) for c, v in zip(cases, scores)}},
    }


def _run(run_id: str, arms: Sequence[Mapping[str, object]], cases: Sequence[str],
         metric: str) -> Dict[str, object]:
    return {
        "schema": SCHEMA_ID,
        "run_id": run_id,
        "source": S08_SOURCE,
        "seeds": 1,
        "primary_metric": metric,
        "cases": list(cases),
        "case_groups": {},
        "arms": list(arms),
    }


# ------------------------------------------------------------------- runs


def s08_graph_structure() -> Dict[str, object]:
    """Does the code graph beat its own degree-preserving rewiring? (14.2)

    ``full`` here is s08's ``graph_code_only``: the representation whose
    structure is under test.  It is a **code** graph, not the four-plane
    Twin, so a verdict from this run is about graph structure at module
    granularity and must not be read as a verdict on the Twin.

    Unidentified pairing: s08 published no 2x2 for rewired vs bm25_code_only.
    No criterion in this run compares those two -- 14.1 needs a distinct BM25
    arm this run does not have, and refuses instead of guessing.
    """
    metric = "recall@10"
    cases = _cases(S08_QUERIES)
    graph = _anchor_vector(pair("bm25_code_only", "graph_code_only").hits_b, len(cases))
    code_only = _paired_to_anchor(graph, pair("bm25_code_only", "graph_code_only"))
    rewired = _paired_to_anchor(graph, pair("graph_rewired", "graph_code_only"))
    return _run(
        f"s08-graph-structure@{S08_COMMIT}",
        [
            _arm("graph_code_only/raw", "full", graph, cases, metric,
                 "s08 graph retriever, alpha=0.5, 2 hops -- a CODE graph, not the "
                 "four-plane Twin"),
            _arm("graph_rewired/raw", "rewired", rewired, cases, metric,
                 "degree-preserving rewiring of the same graph, s08's own control"),
            _arm("bm25_code_only/raw", "code_only", code_only, cases, metric,
                 "lexical code-only baseline"),
        ],
        cases,
        metric,
    )


def s08_plane_routing() -> Dict[str, object]:
    """Four independent indices against the lexical baseline (14.3 territory).

    s08 measured the *cost of not routing*: a round-robin over four separate
    single-plane indices, strictly dominated by the code-only index (0 queries
    rescued, 59 lost).  It never built a cross-plane **fusion** retriever, so
    the criterion as the plan words it -- "four independent indices perform
    equivalently to cross-plane fusion" -- has no treatment arm to compare
    against.  This run exists to show the evaluator refusing that comparison
    rather than substituting the nearest available arm for the missing one.
    """
    metric = "recall@10"
    cases = _cases(S08_QUERIES)
    no_fusion = _anchor_vector(
        pair("four_plane_no_fusion", "bm25_code_only").hits_a, len(cases)
    )
    code_only = _paired_to_anchor(
        no_fusion, pair("bm25_code_only", "four_plane_no_fusion")
    )
    single_index = _paired_to_anchor(
        no_fusion, pair("bm25_single_index", "four_plane_no_fusion")
    )
    return _run(
        f"s08-plane-routing@{S08_COMMIT}",
        [
            _arm("four_plane_no_fusion/raw", "separate_indices", no_fusion, cases,
                 metric, "round-robin over four independent single-plane BM25 indices"),
            _arm("bm25_code_only/raw", "code_only", code_only, cases, metric,
                 "lexical code-only baseline"),
            _arm("bm25_single_index/raw", "bm25", single_index, cases, metric,
                 "one BM25 index over all four planes' documents"),
        ],
        cases,
        metric,
    )


MEASURED_RUNS = {
    "s08_graph_structure": s08_graph_structure,
    "s08_plane_routing": s08_plane_routing,
}


def build(name: str) -> Dict[str, object]:
    try:
        return MEASURED_RUNS[name]()
    except KeyError:
        raise KeyError(
            f"unknown measured run {name!r}; have {sorted(MEASURED_RUNS)}"
        ) from None

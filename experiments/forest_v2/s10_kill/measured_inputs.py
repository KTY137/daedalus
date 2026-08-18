"""Result sets rebuilt from measurements that actually exist on disk.

``synth`` builds runs whose ground truth is constructed, which tests the
evaluator and nothing else.  This module does the opposite and asks the
question the slice is for: *given the measurements this project has today,
can any kill criterion fire at all, or is the evaluator structurally unable
to say KILL?*

Provenance of everything below: slice s08 (`experiments/forest_v2/
s08_graph_baselines/`), branch ``grind/f2-s08`` @ ``a0c8fabd`` -- the
**corrected** run.  s08's first reported run was retracted on 2026-08-18 for
two defects that both biased towards the four-plane hypothesis, so the
retracted tables are not reused here; where a table survived the retraction
unchanged, that is stated at the run.  One gold document per query, so
``recall@10`` per query is 1 or 0 and the published 2x2 tables *are* the
paired data -- the reconstruction reproduces both marginals and the pairing
exactly, and invents no score.  What it cannot reproduce is a pairing s08
never published: where a 2x2 is missing, the joint is filled
deterministically and the affected comparison is not consumed by any
criterion.  Those gaps are named per run.

Three honest limits travel with every verdict derived from this input:

* **The comparator the criterion names does not exist in s08.**  There is no
  cross-plane *fusion* retriever, so 14.3 cannot be decided here at all;
  s08's own verdict is "NOT DECIDABLE AS STATED".  The nearest measurable
  system is ONE joint BM25 index over all four planes' documents, and a joint
  index is **not** fusion.  Labelling it ``fusion`` to get a verdict out
  would be substituting the comparator -- the same defect s08 had to retract,
  reborn one level up in the instrument that is supposed to detect it.  The
  arms here are therefore labelled ``bm25`` (one joint index), never
  ``fusion``, and the evaluator refuses 14.3 on every one of these runs.
* **s08's frozen query set carries code gold labels only.**  Every gold
  document is a code document by construction, so a cross-plane method can
  only lose slots to planes guaranteed not to hold the answer, and a
  code-only index cannot be beaten.  The criterion is structurally
  unfalsifiable there, *in the direction that favours the hypothesis*.  The
  138 added non-code-gold queries fix the plane mix but not the leakage, and
  the type plane still has zero gold labels (289 documents, 27.9% of the
  corpus).
* **One run, one machine, no repeated trials.**  ``seeds`` is 1, and the
  evaluator attaches its low-seed warning to every verdict it reaches.

The runs are named after what s08 measured, not after what one might wish it
had measured.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from . import SCHEMA_ID

S08_COMMIT = "a0c8fabd"
S08_QUERIES = 600
S08_SOURCE = (
    "slice s08 graph baselines, branch grind/f2-s08 @ a0c8fabd (the corrected "
    "run; the first one was retracted), RAW hits table + gross rescue/loss "
    "table [MEASURED]"
)

#: The caveat that must travel with any verdict computed from this input.
S08_CAVEAT = (
    "every gold label in the s08 frozen query set is a code document by "
    "construction, so the type/data/knowledge indices cannot score; cross-plane "
    "questions are instrumented by this run, not decided by it"
)

#: s08 has no cross-plane fusion retriever.  Stated once, cited by every run
#: that touches the plane-routing question.
NO_FUSION_ARM_EXISTS = (
    "s08 contains no cross-plane fusion retriever, so criterion 14.3 has no "
    "treatment arm; the joint single index is a different, weaker comparator "
    "and is labelled as one"
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


#: Verbatim from the corrected s08 README's "Gross rescue/loss at k=10"
#: table.  Both graph rows survived the retraction unchanged.
#:
#: Deliberately absent: ``four_plane_no_fusion`` vs ``bm25_code_only``
#: (432/0/59/109).  s08 withdrew it -- the round-robin arm was starved by slot
#: allocation, and the comparator was a third system again -- so reusing it
#: here would republish a retracted measurement.
S08_PAIRS: Tuple[Contingency, ...] = (
    Contingency("bm25_code_only", "graph_code_only", 482, 9, 15, 94),
    Contingency("graph_rewired", "graph_code_only", 484, 7, 13, 96),
)

#: The corrected plane-routing comparison, per query set and per no-fusion
#: instantiation.  A is always ``bm25_single_index_all_planes`` -- ONE joint
#: BM25 index over all four planes' documents, which is *not* fusion.
#:
#: The two no-fusion arms disagree by design and neither is "the" one:
#: ``four_plane_no_fusion`` splits one budget of k slots round-robin across
#: four planes, ``union_no_fusion`` takes per-plane top-k and concatenates.
#: Both are run, so the answer cannot be selected by picking an arm.
S08_ROUTING: Dict[Tuple[str, str], Contingency] = {
    ("frozen600", "four_plane_no_fusion"):
        Contingency("bm25_single_index", "four_plane_no_fusion", 415, 23, 17, 145),
    ("frozen600", "union_no_fusion"):
        Contingency("bm25_single_index", "union_no_fusion", 438, 0, 53, 109),
    ("noncode138", "four_plane_no_fusion"):
        Contingency("bm25_single_index", "four_plane_no_fusion", 28, 21, 4, 85),
    ("noncode138", "union_no_fusion"):
        Contingency("bm25_single_index", "union_no_fusion", 1, 48, 0, 89),
    ("extended738", "four_plane_no_fusion"):
        Contingency("bm25_single_index", "four_plane_no_fusion", 443, 44, 21, 230),
    ("extended738", "union_no_fusion"):
        Contingency("bm25_single_index", "union_no_fusion", 439, 48, 53, 198),
}

#: What each query set is, and why its answer cannot simply be pooled.
QUERY_SETS = {
    "frozen600": (
        "the 600 frozen queries, seed 20260818 -- every gold label is a CODE "
        "document, so a code-only index cannot be beaten and the criterion is "
        "unfalsifiable here in the direction that favours the hypothesis"
    ),
    "noncode138": (
        "the 138 added queries whose gold label is NOT a code document, seed "
        "20260819 -- fixes the plane mix, does not fix the leakage, and the "
        "type plane still carries zero gold labels"
    ),
    "extended738": (
        "frozen 600 + non-code 138; a pooled set whose plane mix is an "
        "artefact of how many of each were generated, not of any population"
    ),
}

#: Plane order is a hidden prior worth almost the whole result: s08 measured
#: union_no_fusion at 491/600 code-FIRST and 4/600 code-LAST.  Any no-fusion
#: number is meaningless without it.
S08_PLANE_ORDER = "code-first (s08 measured 491/600 code-first vs 4/600 code-last)"


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
         metric: str, notes: str) -> Dict[str, object]:
    # The field is "notes": the schema reads that name, and an arm whose
    # provenance is dropped on the floor is exactly how a role label ends up
    # standing in for a system nobody measured.
    return {
        "arm_id": arm_id,
        "role": role,
        "variant": "raw",
        "notes": notes,
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
                 "four-plane Twin; both rows of this run survived s08's retraction "
                 "unchanged"),
            _arm("graph_rewired/raw", "rewired", rewired, cases, metric,
                 "degree-preserving rewiring of the same graph, s08's own control"),
            _arm("bm25_code_only/raw", "code_only", code_only, cases, metric,
                 "lexical code-only baseline"),
        ],
        cases,
        metric,
    )


def s08_plane_routing(query_set: str, no_fusion_arm: str) -> Dict[str, object]:
    """Four independent indices against ONE JOINT INDEX -- not against fusion.

    The plan's 14.3 asks whether four independent indices perform equivalently
    to *cross-plane fusion*.  s08 built no fusion retriever, so that criterion
    has no treatment arm and cannot be decided from this data at any sample
    size; s08's own verdict is "NOT DECIDABLE AS STATED".

    What exists instead is one joint BM25 index over all four planes'
    documents.  A joint index shares an IDF space; it does not compare or
    combine per-plane scores.  It is a weaker, different question, and the arm
    is labelled ``bm25`` accordingly.  Labelling it ``fusion`` would produce a
    verdict for 14.3 out of a comparison nobody ran -- which is the defect s08
    had to retract, committed one level up by the instrument built to catch
    it.  These runs exist to show the evaluator refusing.
    """
    table = S08_ROUTING[(query_set, no_fusion_arm)]
    metric = "recall@10"
    cases = _cases(table.n)
    separate = _anchor_vector(table.hits_b, len(cases))
    joint = _paired_to_anchor(separate, table)
    return _run(
        f"s08-routing-{query_set}-{no_fusion_arm}@{S08_COMMIT}",
        [
            _arm(
                f"{no_fusion_arm}/raw", "separate_indices", separate, cases, metric,
                f"four independent single-plane BM25 indices, {no_fusion_arm} "
                f"instantiation, plane order {S08_PLANE_ORDER}; "
                f"budget at cutoff 10: 10 documents for four_plane_no_fusion, up "
                f"to 40 for union_no_fusion (s08 measured a truncated union at "
                f"identical numbers, so the extra documents buy nothing here)",
            ),
            _arm(
                "bm25_single_index_all_planes/raw", "bm25", joint, cases, metric,
                "ONE joint BM25 index over all 1037 documents of all four planes "
                "-- a shared IDF space, NOT cross-plane fusion; no fusion "
                "retriever exists in s08",
            ),
        ],
        cases,
        metric,
    )


def _routing_run(query_set: str, arm: str):
    def make() -> Dict[str, object]:
        return s08_plane_routing(query_set, arm)

    make.__doc__ = (
        f"Four independent indices ({arm}) vs one joint index, {query_set}. "
        f"14.3 is REFUSED: no fusion arm exists. {QUERY_SETS[query_set]}"
    )
    return make


MEASURED_RUNS = {
    "s08_graph_structure": s08_graph_structure,
    **{
        f"s08_routing_{qs}_{arm}": _routing_run(qs, arm)
        for qs, arm in sorted(S08_ROUTING)
    },
}


def build(name: str) -> Dict[str, object]:
    try:
        return MEASURED_RUNS[name]()
    except KeyError:
        raise KeyError(
            f"unknown measured run {name!r}; have {sorted(MEASURED_RUNS)}"
        ) from None

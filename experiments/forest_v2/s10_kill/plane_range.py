"""The dynamic-range precondition: can this comparison move at all?

A comparison metric is only evidence when the data it is computed on could
have come out the other way.  Three defects measured in this program are the
same defect in different coordinates:

* s08's frozen 600 gold labels are **all code documents**.  A cross-plane
  method can only spend slots on planes guaranteed not to hold the answer, so
  a code-only index cannot be beaten.  The comparison had no room to move in
  the refuting direction.
* s08's graph has **992 edges, 0 of which cross a plane** (endpoint plane
  counts: ``{code: 1984}``).  Criterion 14.2 is about *cross-plane* edges; the
  rewiring control randomises an intra-code import/call graph.  The object the
  criterion names is not in the input.
* s02's annotation ceiling sat at 100%: a control already at the top of the
  scale cannot lose.

The rule this module implements, stated once:

    Before any comparison metric is reported, emit the cross-tab of
    gold-label plane x plane each arm can actually return.  Refuse the metric
    -- ``UNDECIDABLE``, never a number -- whenever the gold labels contain
    **zero** instances in any plane that distinguishes the two arms, or
    whenever an arm sits at a structural 0% or 100% ceiling on the corpus
    used.

``UNDECIDABLE`` is deliberately not ``INCONCLUSIVE`` and not
``NOT_EVALUABLE``:

======================  ==================================================
``INCONCLUSIVE``        the data could have decided this and did not
                        (too few cases, too wide an interval) -- more of
                        the same data would help
``UNDECIDABLE``         the data could **never** decide this, at any sample
                        size, because the distinguishing observation does
                        not occur in it -- more of the same data changes
                        nothing and only shrinks the interval
``NOT_EVALUABLE``       this run did not ship the arm, or the input format
                        cannot carry the evidence at all
======================  ==================================================

Conflating the first two is how this class of error hides: s08 measured that
padding the query set from 600 to 738 left the discordant counts *identical*
while n grew 23%, which tightens every interval from no new observation.  At
the observed discordance rate a large enough pad flips 14.2 from
``INCONCLUSIVE`` to "equivalent", i.e. fires a KILL, purely by adding queries
that contain no information.  A rule that only counts cases cannot see that;
a rule that asks whether the distinguishing observation is present can.

Index scope is read as declared -- with one exception.  ``returns_planes`` is
a structural property of an index.  The identity of a **fusion** arm is not: a
role label is exactly what this module exists to refuse, so ``fusion_arm``
demands an attested mechanism *and* measured evidence that the arm returned
documents from more than one plane.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .schema import FUSION_MECHANISM, PLANES, Arm, ResultSet


@dataclass(frozen=True)
class Refusal:
    """Why a metric may not be reported, and the evidence for the refusal."""

    reason: str
    detail: Tuple[str, ...] = ()

    def text(self) -> str:
        return self.reason + ("  [" + "; ".join(self.detail) + "]" if self.detail else "")


class RangeRefused(Exception):
    """Raised instead of returning a number whose dynamic range is zero.

    Raised from ``criteria._compare_arms`` so that no criterion can report a
    comparison without passing the precondition: the gate sits in the one
    function every comparison goes through, not in each caller's good
    manners.
    """

    def __init__(self, refusal: Refusal, label: str = "") -> None:
        super().__init__(refusal.reason)
        self.refusal = refusal
        self.label = label


# ------------------------------------------------------------- cross-tab


@dataclass(frozen=True)
class CrossTabRow:
    plane: str
    documents: Optional[int]
    gold_labels: int
    #: arm_id -> (can this arm ever return this plane?, documents it did return)
    per_arm: Mapping[str, Tuple[Optional[bool], Optional[int]]]


@dataclass(frozen=True)
class CrossTab:
    rows: Tuple[CrossTabRow, ...]
    arm_ids: Tuple[str, ...]
    cases: int
    gold_planes_declared: bool

    @property
    def unlabelled(self) -> int:
        """Cases whose gold plane the run did not declare."""
        return self.cases - sum(r.gold_labels for r in self.rows)

    def never_targeted(self) -> Tuple[str, ...]:
        """Planes that hold documents but never hold a gold label."""
        return tuple(
            r.plane for r in self.rows
            if r.gold_labels == 0 and (r.documents is None or r.documents > 0)
        )


def gold_counts(rs: ResultSet, cases: Sequence[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {p: 0 for p in PLANES}
    for case in cases:
        plane = rs.gold_planes.get(case)
        if plane is not None:
            counts[plane] = counts.get(plane, 0) + 1
    return counts


def crosstab(rs: ResultSet, cases: Optional[Sequence[str]] = None) -> CrossTab:
    """Gold-label plane x plane each arm can actually return."""
    cases = tuple(cases) if cases is not None else rs.cases
    counts = gold_counts(rs, cases)
    docs = rs.corpus.documents_per_plane if rs.corpus else {}
    arm_ids = tuple(a.arm_id for a in rs.arms)
    rows: List[CrossTabRow] = []
    for plane in PLANES:
        per_arm: Dict[str, Tuple[Optional[bool], Optional[int]]] = {}
        for arm in rs.arms:
            can = None if arm.returns_planes is None else (plane in arm.returns_planes)
            got = (
                None if arm.returned_plane_counts is None
                else int(arm.returned_plane_counts.get(plane, 0))
            )
            per_arm[arm.arm_id] = (can, got)
        rows.append(
            CrossTabRow(
                plane=plane,
                documents=docs.get(plane) if docs else None,
                gold_labels=counts.get(plane, 0),
                per_arm=per_arm,
            )
        )
    return CrossTab(tuple(rows), arm_ids, len(cases), bool(rs.gold_planes))


def render_crosstab(ct: CrossTab) -> List[str]:
    """Plain ASCII.  Printed before any number, whatever the verdicts are."""
    out = [
        "GOLD-LABEL PLANE x PLANE EACH ARM CAN RETURN",
        "(a comparison can only move where a gold label and both arms' reach overlap)",
        "",
    ]
    if not ct.gold_planes_declared:
        out.append(
            "  the run declares no gold-label planes: the dynamic range of every"
        )
        out.append(
            "  comparison in it is unknown, so no comparison metric is reported"
        )
        return out
    out.append(
        f"  {'plane':10s} {'docs':>6s} {'gold':>6s}   arms "
        f"(Y = in index scope, . = out of scope, ? = undeclared)"
    )
    out.append("  " + "-" * 74)
    for row in ct.rows:
        docs = "-" if row.documents is None else str(row.documents)
        cells = []
        for arm_id in ct.arm_ids:
            can, got = row.per_arm[arm_id]
            mark = "?" if can is None else ("Y" if can else ".")
            if got is not None:
                mark += f"({got})"
            cells.append(f"{arm_id}={mark}")
        flag = "   <-- never a retrieval target" if row.gold_labels == 0 else ""
        out.append(
            f"  {row.plane:10s} {docs:>6s} {row.gold_labels:>6d}   "
            + ", ".join(cells)
            + flag
        )
    if ct.unlabelled:
        out.append(f"  {ct.unlabelled} of {ct.cases} cases carry no declared gold plane")
    never = ct.never_targeted()
    if never:
        out.append(
            "  planes that are never a retrieval target in this run: " + ", ".join(never)
        )
    return out


# ------------------------------------------------------------- the gate


def range_refusal(
    rs: ResultSet, treat: Arm, base: Arm, cases: Sequence[str]
) -> Optional[Refusal]:
    """``None`` when the comparison may be reported, a ``Refusal`` otherwise."""
    cases = tuple(cases)
    if not rs.gold_planes:
        return Refusal(
            "the run declares no gold-label planes, so the dynamic range of this "
            "comparison cannot be established; a number computed here could not be "
            "shown capable of coming out the other way",
            ("gold_planes: absent",),
        )
    missing_scope = [a.arm_id for a in (treat, base) if a.returns_planes is None]
    if missing_scope:
        return Refusal(
            "the run does not declare which planes these arms can return, so the "
            "planes that distinguish them are unknown: " + ", ".join(missing_scope),
            ("returns_planes: absent",),
        )
    counts = gold_counts(rs, cases)
    live = {p for p, n in counts.items() if n > 0}

    # 1. the planes that distinguish the arms carry no gold label at all
    t_scope, b_scope = set(treat.returns_planes or ()), set(base.returns_planes or ())
    distinguishing = t_scope.symmetric_difference(b_scope)
    if distinguishing and not (distinguishing & live):
        detail = tuple(f"{p}: {counts.get(p, 0)} gold" for p in sorted(distinguishing))
        return Refusal(
            f"the only planes that distinguish {treat.arm_id} from {base.arm_id} "
            f"({', '.join(sorted(distinguishing))}) carry zero gold labels across all "
            f"{len(cases)} cases; the comparison cannot move in the direction that "
            f"would refute the hypothesis, at any sample size",
            detail,
        )

    # 2. structural ceiling: an arm that cannot reach any plane holding an answer
    for arm in (treat, base):
        scope = set(arm.returns_planes or ())
        if live and not (scope & live):
            return Refusal(
                f"{arm.arm_id} cannot return any plane that holds a gold label "
                f"(scope {sorted(scope)}, gold planes {sorted(live)}); its score is 0 "
                f"by construction, which is a structural floor, not a measurement",
                tuple(f"{p}: {counts[p]} gold" for p in sorted(live)),
            )

    # 3. observed ceiling: a constant arm pinned at the floor or at the top
    for arm in (treat, base):
        vals = [arm.scores[c] for c in cases]
        lo, hi = min(vals), max(vals)
        if lo == hi and lo in (0.0, 1.0):
            return Refusal(
                f"{arm.arm_id} scores a constant {lo:.1f} on all {len(cases)} cases: it "
                f"sits at a structural {'0' if lo == 0.0 else '100'}% ceiling on this "
                f"corpus and has no room to move",
                (f"{arm.arm_id}: min={lo}, max={hi}",),
            )
    return None


# ------------------------------------------------------- fusion identity


def fusion_arm(rs: ResultSet, variant: str) -> Tuple[Optional[Arm], Optional[Refusal]]:
    """The one arm that is *demonstrably* a cross-plane fusion retriever.

    Never falls back to another role.  The deleted fallback here read
    ``rs.find("fusion") or rs.find("full")``, which let a run with no fusion
    arm at all be graded as though it had one -- measured: relabelling one
    string in a real s08 result set produced ``14.3 verdict=KILL``, with no
    warning anywhere in the report, for a comparison nobody ran.
    """
    arm = rs.find("fusion", variant)
    if arm is None:
        return None, Refusal(
            "no arm in this run is a cross-plane fusion retriever, and there is no "
            "fallback to another role: criterion 14.3 names fusion as its treatment, "
            "so without one it has a single arm and cannot be decided at any sample "
            "size",
            ("role 'fusion': absent",),
        )
    att = arm.retriever
    if att is None:
        return None, Refusal(
            f"{arm.arm_id} is labelled 'fusion' but carries no retriever attestation; "
            f"a role label is a string, not a retriever",
            ("retriever: absent",),
        )
    if att.mechanism != FUSION_MECHANISM:
        return None, Refusal(
            f"{arm.arm_id} is labelled 'fusion' but attests mechanism "
            f"{att.mechanism!r}, which does not compare or combine scores across "
            f"planes; {FUSION_MECHANISM!r} is what 14.3 names",
            (f"mechanism: {att.mechanism}",),
        )
    if len(att.combines_planes) < 2:
        return None, Refusal(
            f"{arm.arm_id} attests fusion over {len(att.combines_planes)} plane(s) "
            f"({', '.join(att.combines_planes) or 'none'}); fusion needs at least two",
            (f"combines_planes: {list(att.combines_planes)}",),
        )
    got = arm.returned_plane_counts
    if got is None:
        return None, Refusal(
            f"{arm.arm_id} attests fusion but the run carries no measured per-plane "
            f"return counts for it, so nothing shows it ever returned a document from "
            f"more than one plane",
            ("returned_plane_counts: absent",),
        )
    reached = sorted(p for p, n in got.items() if n > 0)
    if len(reached) < 2:
        return None, Refusal(
            f"{arm.arm_id} attests fusion but returned documents from {len(reached)} "
            f"plane(s) ({', '.join(reached) or 'none'}); a fusion arm that never "
            f"returns a second plane is a single-plane retriever",
            (f"returned planes: {reached}",),
        )
    return arm, None


# ------------------------------------------------ the object 14.2 names


def cross_plane_edge_refusal(rs: ResultSet) -> Optional[Refusal]:
    """14.2 names cross-plane edges.  Count them; refuse when there are none."""
    corpus = rs.corpus
    if corpus is None or corpus.total_edges is None:
        return Refusal(
            "the run declares no graph census, so the number of cross-plane edges in "
            "the graph under test is unknown; 14.2 is about cross-plane edges and "
            "cannot be evaluated without counting them",
            ("corpus.graph: absent",),
        )
    if corpus.cross_plane_edges is None:
        return Refusal(
            "the run's graph census does not count cross-plane edges",
            (f"total_edges: {corpus.total_edges}",),
        )
    if corpus.cross_plane_edges == 0:
        endpoints = ", ".join(
            f"{p}: {n}" for p, n in sorted(corpus.endpoint_plane_counts.items())
        )
        return Refusal(
            f"the graph under test has {corpus.total_edges} edges and 0 of them cross "
            f"a plane boundary; a rewiring control randomises an intra-plane graph, so "
            f"whatever this comparison measures it is not 'cross-plane edges perform "
            f"equivalently'",
            (f"endpoint plane counts: {endpoints or 'none'}",),
        )
    return None


def planes_never_targeted(rs: ResultSet) -> Tuple[str, ...]:
    return crosstab(rs).never_targeted()

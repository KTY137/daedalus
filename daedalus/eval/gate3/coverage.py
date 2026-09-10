"""coverage.py -- can the arms actually retrieve the planes they are scored on?

``FrozenTaskSet.require_cross_plane`` (contracts.py) refuses a task set whose
gold labels all sit in one plane. It is the s08 defect made mechanical, and it
is the right check. It is also only half of the condition, and the missing half
cost a measurement on 2026-09-09:

  * ``_repo_chunks(fixture, planes=("knowledge",))`` returns 15 chunks and
    ``planes=("data",)`` returns 2 -- the documents are there and the harness
    retrieves them on request.
  * ``arms/bm25.py`` and ``arms/embeddings.py`` call ``_repo_chunks(root)``
    with no ``planes`` argument, so they get the code-only DEFAULT universe.
  * Scored against gold labels living in a CSV, a JSON schema and Markdown
    pages, both returned 0.00 on every non-code task at every budget.

``require_cross_plane`` passed on that task set, because the LABELS spanned
three planes. It cannot see the arms at all -- a ``FrozenTaskSet`` knows nothing
about who will run over it. So a comparison in which half the tasks were
unanswerable by construction was admitted, and its zeros were indistinguishable
from zeros earned by looking and failing.

That distinction is the whole point of this module. A 0.00 from an arm that
searched the right corpus and missed is EVIDENCE. A 0.00 from an arm that never
looked at the corpus containing the answer is ARITHMETIC. Reported side by side
in the same column, the second one is worse than useless, because it looks
exactly like the first.

WHAT THIS DOES NOT DO. It does not refuse a single-plane baseline.
``code_only_graph`` retrieves only code ON PURPOSE -- being beaten on knowledge
tasks is the measurement that baseline exists to provide, and refusing it would
delete the control. What is refused is a task set carrying a plane that NO arm
in the comparison can retrieve: a question the whole panel is structurally
unable to answer, which is precisely the s08 shape.

It also does not verify that a declaration is true. ``retrieved_planes`` is an
arm's own claim about itself, and an arm that lies understates nothing and
overstates its coverage. That is the same trust model as ``Arm.stochastic``,
whose docstring says the acceptance matrix tests the behaviour directly rather
than trusting the flag; ``tests/eval/gate3/test_coverage.py`` does the same here
by checking declarations against what the arms actually retrieve.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .contracts import PLANES, FreezeError

#: An arm that does not declare ``retrieved_planes`` is assumed to retrieve
#: code only. That is the historical behaviour of every arm written before this
#: module existed (``_repo_chunks``'s default is ``planes=("code",)``), so the
#: assumption is conservative in the direction that matters: it under-claims
#: coverage rather than inventing it.
DEFAULT_RETRIEVED_PLANES: tuple[str, ...] = ("code",)


def retrieved_planes(arm: object) -> tuple[str, ...]:
    """What this arm claims it can retrieve. See ``DEFAULT_RETRIEVED_PLANES``."""
    declared = getattr(arm, "retrieved_planes", None)
    if declared is None:
        return DEFAULT_RETRIEVED_PLANES
    planes = tuple(declared)
    unknown = [p for p in planes if p not in PLANES]
    if unknown:
        raise FreezeError(
            f"arm {getattr(arm, 'name', arm)!r} declares unknown plane(s) "
            f"{unknown!r}; known planes are {list(PLANES)}")
    if not planes:
        raise FreezeError(
            f"arm {getattr(arm, 'name', arm)!r} declares an EMPTY "
            "retrieved_planes. An arm that retrieves nothing cannot be scored; "
            "omit the attribute to accept the code-only default, or name the "
            "planes it reaches.")
    return planes


@dataclass(frozen=True)
class CoverageReport:
    """Which planes each arm can reach, and which the task set needs.

    ``uncovered`` is the refusal condition. ``partial`` is not a refusal -- it
    names the (arm, plane) pairs where a 0.00 will be arithmetic rather than
    evidence, so a reader of the results table can tell the two apart.
    """

    planes_needed: tuple[str, ...]
    by_arm: Mapping[str, tuple[str, ...]]
    uncovered: tuple[str, ...]
    partial: tuple[tuple[str, str], ...]

    @property
    def ok(self) -> bool:
        return not self.uncovered

    def describe(self) -> str:
        lines = [f"planes needed by the task set: {list(self.planes_needed)}"]
        for arm in sorted(self.by_arm):
            reach = self.by_arm[arm]
            missing = [p for p in self.planes_needed if p not in reach]
            note = f"  MISSING {missing}" if missing else ""
            lines.append(f"  {arm}: retrieves {list(reach)}{note}")
        if self.uncovered:
            lines.append(f"NO ARM RETRIEVES: {list(self.uncovered)}")
        return "\n".join(lines)


def plane_coverage(arms: Sequence[object],
                   planes_needed: Iterable[str]) -> CoverageReport:
    """Build the report. Pure; refuses nothing on its own."""
    needed = tuple(p for p in PLANES if p in set(planes_needed))
    by_arm = {getattr(a, "name", repr(a)): retrieved_planes(a) for a in arms}
    covered = {p for reach in by_arm.values() for p in reach}
    uncovered = tuple(p for p in needed if p not in covered)
    partial = tuple((arm, p) for arm in sorted(by_arm)
                    for p in needed if p not in by_arm[arm])
    return CoverageReport(planes_needed=needed, by_arm=by_arm,
                          uncovered=uncovered, partial=partial)


def require_plane_coverage(arms: Sequence[object],
                           planes_needed: Iterable[str]) -> CoverageReport:
    """Refuse a comparison containing a plane no arm can retrieve.

    Raises ``FreezeError`` BEFORE any trial runs, for the same reason
    ``require_cross_plane`` does: a structurally impossible comparison must not
    be run and then reported as a finding.

    Returns the report when admissible, so the caller can record ``partial``
    alongside its results instead of discarding it.
    """
    report = plane_coverage(arms, planes_needed)
    if not report.ok:
        raise FreezeError(
            "this comparison is structurally unanswerable: no arm retrieves "
            f"{list(report.uncovered)}, yet the task set has gold labels "
            "there. Every score on those tasks would be 0.00 by arithmetic "
            "rather than by measurement, and would be indistinguishable in the "
            "results table from a genuine miss.\n" + report.describe())
    return report

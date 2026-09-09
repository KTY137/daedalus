"""Plane coverage: the half of the s08 condition ``require_cross_plane`` misses.

The measured defect these tests pin (2026-09-09, see
docs/G3_ARMS_NEVER_LOOKED_AT_THE_NON_CODE_PLANES_20260909.md): ``bm25`` and
``embeddings`` call ``harness._repo_chunks(root)`` with no ``planes`` argument,
get the code-only default universe, and score 0.00 on every non-code task --
while ``require_cross_plane()`` PASSES, because it inspects gold labels and
cannot see arms at all.
"""
from __future__ import annotations

import pytest

from daedalus.eval.gate3.contracts import FreezeError
from daedalus.eval.gate3.coverage import (DEFAULT_RETRIEVED_PLANES,
                                          plane_coverage, require_plane_coverage,
                                          retrieved_planes)


class _Arm:
    def __init__(self, name, planes=None):
        self.name = name
        if planes is not None:
            self.retrieved_planes = planes


# --------------------------------------------------------------------------- #
# declaration handling                                                         #
# --------------------------------------------------------------------------- #

def test_undeclared_arm_is_assumed_code_only():
    """Conservative in the direction that matters: under-claim, never invent.

    Every arm written before this module retrieved the ``_repo_chunks``
    code-only default, so silence means code.
    """
    assert retrieved_planes(_Arm("x")) == DEFAULT_RETRIEVED_PLANES == ("code",)


def test_unknown_plane_is_refused_not_ignored():
    with pytest.raises(FreezeError, match="unknown plane"):
        retrieved_planes(_Arm("x", ("code", "vibes")))


def test_empty_declaration_is_refused():
    """An empty tuple is not 'no opinion' -- it is a claim to retrieve nothing,
    which cannot be scored. Omitting the attribute is how you say 'default'."""
    with pytest.raises(FreezeError, match="EMPTY"):
        retrieved_planes(_Arm("x", ()))


# --------------------------------------------------------------------------- #
# the refusal                                                                  #
# --------------------------------------------------------------------------- #

def test_refuses_a_plane_no_arm_can_reach():
    """The exact 2026-09-09 shape: labels in knowledge, every arm code-only."""
    arms = [_Arm("bm25"), _Arm("embeddings")]
    with pytest.raises(FreezeError, match="structurally unanswerable"):
        require_plane_coverage(arms, ("code", "knowledge"))


def test_refusal_names_the_plane_and_the_arms():
    """A refusal a reader cannot act on just moves the confusion."""
    with pytest.raises(FreezeError) as exc:
        require_plane_coverage([_Arm("bm25")], ("code", "data"))
    msg = str(exc.value)
    assert "data" in msg and "bm25" in msg and "retrieves ['code']" in msg


def test_admits_when_one_arm_covers_the_plane():
    """Coverage is a property of the PANEL, not of every member."""
    arms = [_Arm("code_only_graph"), _Arm("fourfold", ("code", "data", "knowledge"))]
    report = require_plane_coverage(arms, ("code", "knowledge"))
    assert report.ok


def test_a_single_plane_baseline_is_not_refused():
    """``code_only_graph`` is code-only ON PURPOSE -- losing on knowledge tasks
    is the measurement it exists to provide. Refusing it would delete the
    control, which is the opposite of what this guard is for."""
    arms = [_Arm("code_only_graph"), _Arm("wide", ("code", "knowledge"))]
    report = require_plane_coverage(arms, ("code", "knowledge"))
    assert report.ok
    assert ("code_only_graph", "knowledge") in report.partial


def test_partial_is_reported_not_refused():
    """The distinction the whole module exists for: which (arm, plane) cells
    will produce a 0.00 by arithmetic rather than by measurement."""
    arms = [_Arm("narrow"), _Arm("wide", ("code", "data", "knowledge"))]
    report = plane_coverage(arms, ("code", "data", "knowledge"))
    assert report.ok
    assert ("narrow", "data") in report.partial
    assert ("narrow", "knowledge") in report.partial
    assert not any(a == "wide" for a, _ in report.partial)


def test_planes_needed_is_ordered_canonically():
    """Order comes from PLANES so two reports of the same set compare equal."""
    a = plane_coverage([_Arm("w", ("code", "data", "knowledge", "type"))],
                       ("knowledge", "code", "data"))
    b = plane_coverage([_Arm("w", ("code", "data", "knowledge", "type"))],
                       ("data", "knowledge", "code"))
    assert a.planes_needed == b.planes_needed == ("code", "data", "knowledge")


# --------------------------------------------------------------------------- #
# declarations checked against behaviour, not trusted                          #
# --------------------------------------------------------------------------- #

def _returned_planes(candidate: str) -> set[str]:
    """Classify the documents an arm actually returned.

    Arms emit ``# ===== <repo-relative path> =====`` headers before each chunk
    (``harness._bm25_context`` and the separate-indices concatenation both do).
    Classifying those paths is what makes this a behavioural check rather than
    an attribute read.
    """
    import re

    from daedalus.eval.gate3.arms.separate_indices import classify_plane

    planes = set()
    for rel in re.findall(r"^# =====\s*(.+?)\s*=====\s*$", candidate or "",
                          flags=re.MULTILINE):
        plane = classify_plane(rel.split("::", 1)[0])
        if plane:
            planes.add(plane)
    return planes


def test_real_arm_declarations_match_what_they_retrieve():
    """An arm that declares a plane it cannot reach re-opens the exact hole
    this module closes, and does it while LOOKING covered.

    ``Arm.stochastic``'s docstring says the acceptance matrix tests the
    behaviour rather than trusting the flag. This does the same: it RUNS each
    arm, once per declared plane, and checks that the documents it actually
    returned include one from that plane.

    The previous version of this test read the attribute and asserted things
    about the FIXTURE instead. An adversarial pass showed it survived the one
    mutation it existed to catch -- giving ``bm25`` a declaration of
    ``("code", "data", "knowledge")``, which the measurements refute, left all
    ten tests green. Its docstring described a behavioural check it did not
    perform, and ``coverage.py`` cited it as the reason its trust model was
    acceptable.
    """
    from daedalus.eval.gate3.arms import bm25, embeddings, separate_indices
    from daedalus.eval.gate3.contracts import ArmBudget
    from daedalus.eval.gate3.evaluator import make_recall_evaluator
    from daedalus.eval.gate3.protocols import Task
    from daedalus.eval.harness import _repo_chunks
    from daedalus.eval.tasks import resolve_task_repo

    root = resolve_task_repo("fourfold_wiki_app")
    available = {p: len(_repo_chunks(root, planes=(p,)))
                 for p in ("code", "data", "knowledge")}
    # Precondition, asserted rather than assumed: a fixture without non-code
    # documents would make every check below unfalsifiable.
    assert available["code"] and available["data"] and available["knowledge"], (
        f"fixture cannot evidence the planes under test: {available}")

    budget = ArmBudget(max_tokens=16000)
    for mod in (bm25, embeddings, separate_indices):
        arm = next(getattr(mod, n) for n in dir(mod)
                   if isinstance(getattr(mod, n), type)
                   and hasattr(getattr(mod, n), "run")
                   and hasattr(getattr(mod, n), "name"))()
        declared = retrieved_planes(arm)
        for plane in declared:
            assert available.get(plane, 0) > 0, (
                f"{arm.name} declares plane {plane!r}, which the fixture holds "
                "no documents for -- the declaration cannot be checked against "
                "behaviour, so it must not be asserted"
            )
            task = Task(task_id=f"coverage-{arm.name}-{plane}", repo_root=root,
                        question="article schema fields and storage decisions",
                        target="", label_plane=plane)
            # make_recall_evaluator returns a FACTORY; arm.run wants a live
            # SealedEvaluator. Calling it is not a detail -- passing the factory
            # makes the arm fail with an AttributeError it reports as an
            # ordinary error, which this test would then read as "retrieved
            # nothing" rather than "was never run".
            ev = make_recall_evaluator({task.task_id: ["schema"]})()
            outcome = arm.run(task, budget, ev, 0)
            assert getattr(outcome, "error", None) is None, (
                f"{arm.name} errored on plane {plane!r}: {outcome.error}"
            )
            got = _returned_planes(getattr(outcome, "candidate", "") or "")
            assert plane in got, (
                f"{arm.name} declares it retrieves {plane!r}, but running it "
                f"with label_plane={plane!r} returned documents from {sorted(got)} "
                "only. A declaration the arm's own behaviour does not support is "
                "worse than no declaration: gate3.coverage would admit a "
                "comparison on the strength of it."
            )

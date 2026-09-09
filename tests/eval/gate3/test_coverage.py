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

def test_real_arm_declarations_match_what_they_retrieve():
    """``Arm.stochastic``'s docstring says the acceptance matrix tests the
    behaviour rather than trusting the flag. Same here: an arm that declares a
    plane it cannot actually reach would re-open the exact hole this module
    closes, and would do it while LOOKING covered.

    Runs each arm over the four-plane fixture and checks that a declared plane
    yields at least one retrieved document from it.
    """
    from daedalus.eval.gate3.arms import bm25, embeddings, separate_indices
    from daedalus.eval.harness import _repo_chunks
    from daedalus.eval.tasks import resolve_task_repo

    root = resolve_task_repo("fourfold_wiki_app")
    available = {p: len(_repo_chunks(root, planes=(p,)))
                 for p in ("code", "data", "knowledge")}
    # Precondition: the fixture must actually hold non-code documents, or this
    # test would pass vacuously and prove nothing.
    assert available["knowledge"] > 0 and available["data"] > 0, available

    for mod in (bm25, embeddings, separate_indices):
        arm = next(getattr(mod, n) for n in dir(mod)
                   if isinstance(getattr(mod, n), type)
                   and hasattr(getattr(mod, n), "run")
                   and hasattr(getattr(mod, n), "name"))()
        declared = retrieved_planes(arm)
        assert "code" in declared, (
            f"{arm.name} does not declare code; every arm here retrieves it"
        )
        for plane in declared:
            assert available.get(plane, 0) > 0, (
                f"{arm.name} declares plane {plane!r}, which the fixture has no "
                "documents for -- the declaration cannot be checked, so it must "
                "not be asserted"
            )

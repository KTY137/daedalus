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

def _returned_planes(root: str, candidate: str) -> set[str]:
    """Classify the documents an arm actually returned, by CONTENT.

    The first version parsed ``# ===== <path> =====`` headers. That works for
    the arms that concatenate ranked chunks and silently fails for the ones
    that return a single document's raw text -- ``best_of_n`` came back with
    ``# Architecture`` (a knowledge document, i.e. it WAS looking) and scored
    an empty plane set, a false negative in the check itself.

    Matching content against the fixture's own files works for every candidate
    shape, because the arm has to return the bytes either way.
    """
    import os
    import pathlib

    from daedalus.eval.gate3.arms.separate_indices import classify_plane

    planes = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            plane = classify_plane(rel)
            if not plane or plane in planes:
                continue
            try:
                text = pathlib.Path(full).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # a distinctive run of the file's own body, long enough not to
            # collide across files and short enough to survive truncation
            body = [ln for ln in text.splitlines() if len(ln.strip()) > 25]
            if body and any(ln.strip() in candidate for ln in body[:5]):
                planes.add(plane)
    return planes


#: ``single_llm_loop`` calls a model. With no provider reachable it returns an
#: error rather than a candidate, so its declaration cannot be checked offline.
#: Named here rather than skipped silently: an arm whose declaration nothing
#: verifies is exactly the state this test exists to prevent, and pinning the
#: list means adding a second such arm has to be a deliberate act.
PROVIDER_DEPENDENT_ARMS = {"single_llm_loop"}


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
    from daedalus.eval.gate3.arms import (best_of_n, bm25, embeddings,
                                         local_mutation, random_search,
                                         separate_indices, single_llm_loop)
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
    unverified = set()

    # One plane-targeted probe per plane. Each carries a question and a gold
    # label that genuinely live in that plane of the fixture, so an arm whose
    # universe includes the plane has a real reason to return a document from
    # it.
    PROBES = {
        "code": ("how does search_articles filter articles", ["search_articles"]),
        "data": ("article schema required fields and patterns", ["$schema"]),
        "knowledge": ("why was CSV storage accepted", ["Accepted"]),
    }

    for mod in (best_of_n, bm25, embeddings, local_mutation, random_search,
                separate_indices, single_llm_loop):
        arm = next(getattr(mod, n) for n in dir(mod)
                   if isinstance(getattr(mod, n), type)
                   and hasattr(getattr(mod, n), "run")
                   and hasattr(getattr(mod, n), "name"))()
        declared = retrieved_planes(arm)
        seen: set[str] = set()
        errored = False
        for plane in declared:
            assert available.get(plane, 0) > 0, (
                f"{arm.name} declares plane {plane!r}, which the fixture holds "
                "no documents for -- the declaration cannot be checked against "
                "behaviour, so it must not be asserted"
            )
            question, labels = PROBES[plane]
            task = Task(task_id=f"coverage-{arm.name}-{plane}", repo_root=root,
                        question=question, target="", label_plane=plane)
            ev = make_recall_evaluator({task.task_id: labels})()
            outcome = arm.run(task, budget, ev, 0)
            if getattr(outcome, "error", None):
                assert arm.name in PROVIDER_DEPENDENT_ARMS, (
                    f"{arm.name} errored on plane {plane!r}: {outcome.error}"
                )
                unverified.add(arm.name)
                errored = True
                continue
            seen |= _returned_planes(root, getattr(outcome, "candidate", "") or "")
        if errored:
            continue
        # WHAT IS ACTUALLY OBSERVABLE FROM OUTSIDE, and the limit of this check.
        #
        # The defect being guarded against is a code-ONLY retrieval universe.
        # That is falsifiable black-box: an arm whose universe is code-only can
        # NEVER return a non-code document, whatever the query.
        #
        # Which SPECIFIC non-code plane comes back is not, because selection is
        # not universe. ``best_of_n`` returns exactly one document per run -- it
        # answered the data probe with a knowledge document that scored better,
        # which is the arm working correctly. Demanding plane X from probe X
        # failed a healthy arm for doing its job, and two earlier versions of
        # this assertion did exactly that.
        #
        # So: an arm declaring any non-code plane must demonstrably return a
        # non-code document. That still kills the mutation this test exists for
        # -- a code-only bm25 declaring ("code","data","knowledge") cannot
        # produce one -- while not asserting more than the evidence supports.
        if set(declared) - {"code"}:
            assert seen - {"code"}, (
                f"{arm.name} declares {list(declared)} but across plane-targeted "
                f"probes returned only {sorted(seen) or 'nothing classifiable'}. "
                "A code-only universe can never return a non-code document, so "
                "this declaration is not supported by the arm's own behaviour: "
                "gate3.coverage would admit a comparison on the strength of it."
            )

    assert unverified <= PROVIDER_DEPENDENT_ARMS, (
        f"these arms could not be verified and are not declared as "
        f"provider-dependent: {sorted(unverified - PROVIDER_DEPENDENT_ARMS)}"
    )

# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""``python.attempt``'s registry anchor must dominate the attempt it starts.

THE DEFECT, MEASURED AT 684b7503. ``TaskAttempt.run`` held its central
``begin_effect`` inside a ``try:`` whose ``else:`` branch carried the whole
attempt::

    try:
        self._boundary_receipt = begin_effect(...)
    except ...:
        result = finish(...)
    else:
        result = self._run_with_ledger(...)

``scripts/declare_write_surfaces.py:_anchor_regions`` counts the statements that
FOLLOW the statement holding the call, so the attempt -- being inside that same
statement -- was never among them. The door scored ``dominated_statements 1,
declared 0``. The runtime ordering was correct, the four contracts ran and the
receipt was real; the anchor still provably preceded nothing, which is a
boundary in name only.

WHY THIS IS A SEPARATE FILE. ``tests/gates/test_write_surface_lease_dominance.py``
measures the PRODUCER against synthetic doors, and it is owned by the lane that
wrote the lease-dominance guard. These two measure a REAL registry row against
the REAL file it anchors, which is the case every synthetic fixture is blind to:
a door can be centrally wired, run its contracts and return a receipt, and still
be unable to classify a single surface no matter what it does.

WHAT THEY DO NOT CLAIM. Dominating the attempt is not the same as the attempt
happening inside a leased execution -- that is the separate ``leased_positions``
region, and at this revision ``python.attempt`` has none, because
``TaskAttempt.run`` takes no Effect Lease yet. These tests pin the anchor, not
the lease.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_generator():
    """The declaration generator itself, so these tests use its own dominance
    rule rather than a second copy of it that could drift from the producer."""

    path = REPO_ROOT / "scripts" / "declare_write_surfaces.py"
    spec = importlib.util.spec_from_file_location(
        "declare_write_surfaces_anchor_probe", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["declare_write_surfaces_anchor_probe"] = module
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()



def _anchor_function(door_id: str):
    """The AST of the function one CENTRAL row anchors, resolved through the
    registry rather than named here.  Moving the anchor to another symbol
    therefore fails these tests instead of silently measuring the old one."""

    from daedalus.spine.effect_boundary import REGISTRY_BY_ID

    row = REGISTRY_BY_ID[door_id]
    anchor = next(a for a in row.anchors if a.call == "begin_effect")
    module, _, symbol = anchor.target.partition(":")
    rel_path = GEN._module_rel_path(REPO_ROOT, module)
    assert rel_path is not None, f"{door_id} anchors a module that is not a file"
    tree = ast.parse((REPO_ROOT / rel_path).read_bytes(), filename=rel_path)
    func = GEN._find_symbol(tree, tuple(symbol.split(".")) if symbol else ())
    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    return func


def _dominated_method_calls(func) -> set[str]:
    dominated, _shape = GEN._anchor_regions(func, GEN._is_begin_effect)
    return {
        node.func.attr
        for statement in dominated
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_the_attempt_anchor_dominates_the_attempt_it_starts():
    """MEASURED at 684b7503, and the reason this test exists.

    ``TaskAttempt.run`` held its ``begin_effect`` inside a ``try:`` whose
    ``else:`` branch carried the whole attempt::

        try:
            self._boundary_receipt = begin_effect(...)
        except ...:
            result = finish(...)
        else:
            result = self._run_with_ledger(...)

    ``_anchor_regions`` counts the statements that FOLLOW the statement holding
    the call, so the attempt -- being inside that same statement -- was not
    among them.  The door scored ``dominated_statements 1, declared 0``: the
    runtime order was correct and the anchor provably preceded nothing, which
    is a boundary in name only.  Both handlers return now, and the work is a
    sibling statement below.

    Put the ``else:`` back and this goes red.
    """

    called = _dominated_method_calls(_anchor_function("python.attempt"))
    assert "_run_with_ledger" in called, (
        "the statement that carries the attempt is not below the begin_effect "
        "holder, so the anchor dominates nothing the attempt does"
    )
    # DELIBERATELY NOT a second hard-coded method name. This line used to read
    # `assert "_reap" in called`, and it went red the moment `run`'s exit was
    # routed through `_released` to remove a duplicated anchor -- a correct
    # change failing a test that had pinned the spelling of the exit rather
    # than the fact. What must be true is that the attempt is not the LAST
    # thing the region does, so the exit is dominated too; which method the
    # exit is spelled as is not this test's business.
    assert len(called - {"_run_with_ledger"}) >= 1, (
        f"the anchor dominates only the attempt call itself ({sorted(called)}); "
        "the exit path is outside the region"
    )


def test_the_attempt_anchor_region_is_not_a_single_trailing_statement():
    """The weaker, blunter half of the same fact, kept separate on purpose.

    A future refactor could satisfy the test above by burying
    ``_run_with_ledger`` in a one-line trailing ``return`` while putting the
    real work back inside the holder.  This pins the count instead of the name,
    so the two fail for different edits.
    """

    dominated, shape = GEN._anchor_regions(
        _anchor_function("python.attempt"), GEN._is_begin_effect
    )
    assert shape == "statement"
    assert len(dominated) >= 2, (
        f"python.attempt's anchor dominates {len(dominated)} statement(s); at "
        "684b7503 it dominated exactly 1 and the door declared 0 surfaces"
    )

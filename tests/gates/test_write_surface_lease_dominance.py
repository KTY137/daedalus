# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""A door that HELD a lease is not the same claim as a write that was UNDER one.

THE DEFECT THIS GUARD EXISTS FOR. ``authenticated_doors`` proves that a
registry row really granted, started and terminalised an Effect Lease at this
revision. The dominance analysis proves that every path to a write surface
crosses that row's ``begin_effect`` anchor. Neither of those, nor both, proves
that the write itself happened inside a leased execution -- and the two claims
come apart exactly where ``python.offload`` showed they do: at merge 21f21f2a
its only write, ``worker.run``, sat in ``_offload_impl``, which the un-leased
``live=False`` planning path also called.

That case was caught by accident. The private-callee fixpoint refuses a helper
the un-leased path also names, so ``_offload_impl`` never entered the dominated
region. A surface sitting DIRECTLY in an ``if authorization is not None:``
region would not be refused by anything: the receipt anchor dominates it, the
door authenticates, and the row comes out ``cleared:central`` on the strength
of some other invocation's lease.

So the region is computed from the lease consumption itself.
``<authorization>.begin_effect(execution)`` is an attribute call and the free
``begin_effect(entrypoint_id, effects, decisions)`` receipt function is not,
which is the mechanical difference these tests pin. A surface outside the
leased region stays a blocker with the reason named.

WHAT CHANGED IN THE TREE UNDER IT. ``_offload_impl`` no longer executes
anything: it plans, refuses, and returns a description of the dispatch, and the
provider run moved into a module-private executor named exactly once in
``daedalus/offload.py`` -- from the statement in ``offload`` that follows
``authorization.begin_effect(...)``. ``test_the_offload_door_lease_dominates_
its_bench_write`` is the measurement of that on the real tree.

AND IT IS A TRIPWIRE OVER A KNOWN WEAKNESS, not a proof of one. The analysis
resolves references by name only -- it cannot follow an attribute call or read
a method body -- so it admits a helper on the strictly-stronger evidence it can
actually collect: that the helper's token appears in no other Python source.
That is fail-closed, and it also means a comment or a test that merely MENTIONS
the executor drops this door back to zero dominated surfaces with no behavioural
change at all. The test below exists so that regression is red instead of
silent; the repair belongs upstream, in the analysis (see "KNOWN FRAGILITY OF
LEVEL 2" in ``scripts/declare_write_surfaces.py``), not in everyone remembering
not to type a word.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

from daedalus.gates.repository_write_classification import (
    GuardDisposition,
    TargetDisposition,
)
from daedalus.kernel import offload_lease as ol
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "0" * 40
MECHANISM = "gated_writes.run_write_wave: one TaskAttempt worktree per write task"


def _load_generator():
    path = REPO_ROOT / "scripts" / "declare_write_surfaces.py"
    spec = importlib.util.spec_from_file_location("declare_write_surfaces", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["declare_write_surfaces"] = module
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()

#: A synthetic ``daedalus/offload.py``. The registry's ``python.offload`` row
#: anchors ``daedalus.offload:offload`` at a ``begin_effect`` call, so a root
#: holding this file resolves that door for real -- no fake registry, no fake
#: anchor. Three writes, and the whole test is which of them is leased:
#:
#: * ``open(receipted, "w")`` sits AFTER the free ``begin_effect(...)`` receipt
#:   and BEFORE the lease is consumed. The anchor dominates it; the lease does
#:   not. This is the shape the old producer would have classified
#:   ``cleared:central`` on the strength of a lease that had not been taken
#:   yet, and it is why the guard is a separate region rather than a stricter
#:   anchor predicate.
#: * ``open(leased, "w")`` sits after ``authorization.begin_effect(...)`` in
#:   the anchor function itself -- lease-dominated, and the positive control.
#: * ``_shared_write`` is called from the leased branch AND from
#:   ``plan_offload``, which holds nothing -- the dual-caller case.
DUAL_CALLER_MODULE = '''"""Synthetic offload door for the lease-dominance test."""
from pathlib import Path


def _shared_write(target):
    """Reachable from a leased caller and from an un-leased one."""
    with open(target, "w") as handle:
        handle.write("shared")


def plan_offload(target):
    """The un-leased path. It holds no authorization and never asks for one."""
    return _shared_write(target)


def offload(authorization, execution, receipted, leased, shared):
    from daedalus.spine.effect_boundary import begin_effect

    begin_effect("python.offload", (), ())
    with open(receipted, "w") as handle:
        handle.write("receipted")
    start = authorization.begin_effect(execution)
    with open(leased, "w") as handle:
        handle.write("leased")
    _shared_write(shared)
    return start
'''

#: THE ``finally`` CASE. The lease is consumed INSIDE a ``try``, and a write
#: sits in that ``try``'s ``finally``. The finaliser runs whether or not
#: ``begin_effect`` ever returned, so its write is not under the lease -- and
#: ``_anchor_regions`` seeds only the statements AFTER the holder, so it is not
#: in the leased region either. The write below the ``try`` is, which is what
#: makes this a discrimination rather than a blanket refusal.
FINALLY_MODULE = '''"""Synthetic offload door whose finaliser writes."""


def offload(authorization, execution, deferred, leased):
    from daedalus.spine.effect_boundary import begin_effect

    begin_effect("python.offload", (), ())
    try:
        start = authorization.begin_effect(execution)
    finally:
        with open(deferred, "w") as handle:
            handle.write("deferred")
    with open(leased, "w") as handle:
        handle.write("leased")
    return start
'''

#: THE CALLBACK CASE. The write helper is called from the leased region, and it
#: is ALSO named at module level, where un-leased code can dispatch through the
#: table and invoke it without ever holding an authorization. One un-dominated
#: reference is enough for the fixpoint to refuse the helper, which is the
#: property that makes "named nowhere else" a usable rule rather than a wish.
CALLBACK_MODULE = '''"""Synthetic offload door that hands its writer out."""


def _deferred_write(target):
    with open(target, "w") as handle:
        handle.write("callback")


#: Un-leased code reaches the writer through this table.
HOOKS = (_deferred_write,)


def offload(authorization, execution, target, leased):
    from daedalus.spine.effect_boundary import begin_effect

    begin_effect("python.offload", (), ())
    start = authorization.begin_effect(execution)
    with open(leased, "w") as handle:
        handle.write("leased")
    _deferred_write(target)
    return start
'''

ISSUER_STUB = '"""Stub issuer module, present only so its bytes can be hashed."""\n'


@pytest.fixture
def control(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    switch = KillSwitch(repo_root=str(REPO_ROOT))
    switch.arm(note="lease dominance test")
    return switch


@pytest.fixture
def synthetic_root(tmp_path):
    root = tmp_path / "tree"
    (root / "daedalus" / "kernel").mkdir(parents=True)
    (root / "daedalus" / "offload.py").write_text(
        DUAL_CALLER_MODULE, encoding="utf-8"
    )
    (root / "daedalus" / "kernel" / "offload_lease.py").write_text(
        ISSUER_STUB, encoding="utf-8"
    )
    return root


def _authenticated_door(switch):
    """One real granted -> begun -> finished ``python.offload`` execution."""

    lease = ol.acquire_wave_offload_lease(
        str(REPO_ROOT),
        source_revision=REVISION,
        mission_id="lease-dominance",
        attempt_id="a-1",
        positions=1,
        lanes=("ollama",),
        max_spend_usd=0.25,
        timeout_s=900,
        writable_paths=("docs/x.md",),
        contained=True,
        containment_evidence=MECHANISM,
        switch=switch,
    )
    assert lease.granted, getattr(lease, "reasons", None)
    execution = lease.execution_for(0, ("docs/x.md",))
    start = lease.authorization.begin_effect(execution)
    lease.authorization.finish_effect(start.receipt, outcome="COMPLETED")
    records, refusals = ol.harvest_effect_lease_terminal_records(
        ol.write_evidence_root(str(REPO_ROOT), REVISION),
        control_root_path=ol.control_root(str(REPO_ROOT)),
        keyring=ol.issuer_keyring(str(REPO_ROOT)),
    )
    assert refusals == () and len(records) == 1
    return lease


def _derive(root, switch):
    return GEN.derive(
        Path(root),
        REVISION,
        evidence_root=ol.write_evidence_root(str(REPO_ROOT), REVISION),
        control_root_path=ol.control_root(str(REPO_ROOT)),
        issued_at="2026-08-23T12:00:00.000000+00:00",
    )


# --------------------------------------------------------------------------- #
# the two regions are different, and the difference is mechanical              #
# --------------------------------------------------------------------------- #
def test_the_free_receipt_call_is_not_a_lease_consumption(synthetic_root):
    door = next(
        d
        for d in GEN.resolve_central_doors(synthetic_root)[0]
        if d.door_id == "python.offload"
    )
    dominance = GEN._dominance(
        synthetic_root, door, GEN.NameIndex.build(synthetic_root)
    )
    # The anchor region is seeded from the FIRST begin_effect in the function,
    # which is the free receipt call -- so it covers everything below it.
    assert dominance.positions
    # The leased region is seeded from the attribute call one line down, so it
    # is strictly smaller and it does not contain the receipt call itself.
    assert dominance.leased_positions
    assert dominance.leased_positions < dominance.positions
    assert dominance.leased_refusal == ""


def test_a_door_that_consumes_no_lease_has_an_empty_leased_region(tmp_path):
    """The fail-closed default, and the state of every door in this tree but
    ``python.offload``."""

    root = tmp_path / "unleased"
    (root / "daedalus").mkdir(parents=True)
    (root / "daedalus" / "offload.py").write_text(
        '''from pathlib import Path


def offload(target):
    from daedalus.spine.effect_boundary import begin_effect

    begin_effect("python.offload", (), ())
    with open(target, "w") as handle:
        handle.write("unleased")
''',
        encoding="utf-8",
    )
    door = next(
        d
        for d in GEN.resolve_central_doors(root)[0]
        if d.door_id == "python.offload"
    )
    dominance = GEN._dominance(root, door, GEN.NameIndex.build(root))
    assert dominance.positions
    assert dominance.leased_positions == frozenset()
    assert "no <authorization>.begin_effect" in dominance.leased_refusal


def test_a_write_in_the_finally_of_the_lease_holder_is_not_leased(tmp_path):
    """ADVERSARIAL: a finaliser is not a leased caller.

    ``finally`` runs on the path where ``begin_effect`` raised, refused, or was
    never reached, so a write there is exactly the un-attributable case. The
    anchor region still covers it -- the free receipt call is above the whole
    ``try`` -- and the leased region must not."""

    root = tmp_path / "finally"
    (root / "daedalus").mkdir(parents=True)
    (root / "daedalus" / "offload.py").write_text(FINALLY_MODULE, encoding="utf-8")
    door = next(
        d for d in GEN.resolve_central_doors(root)[0] if d.door_id == "python.offload"
    )
    dominance = GEN._dominance(root, door, GEN.NameIndex.build(root))

    deferred = _line(FINALLY_MODULE, 'with open(deferred, "w")')
    leased = _line(FINALLY_MODULE, 'with open(leased, "w")')
    anchored = {line for line, _column in dominance.positions}
    under_lease = {line for line, _column in dominance.leased_positions}

    assert deferred in anchored, "the receipt anchor covers the whole try"
    assert deferred not in under_lease
    # The positive control in the same fixture: a guard that refuses both
    # writes proves nothing about the finaliser.
    assert leased in under_lease


def test_a_writer_handed_out_at_module_level_is_not_leased(tmp_path):
    """ADVERSARIAL: a callback is not a leased caller either.

    ``_deferred_write`` is invoked from the leased region, so a naive callee
    walk would admit it. It is also named in a module-level table that
    un-leased code can dispatch through, and one un-dominated reference is
    enough to refuse it."""

    root = tmp_path / "callback"
    (root / "daedalus").mkdir(parents=True)
    (root / "daedalus" / "offload.py").write_text(CALLBACK_MODULE, encoding="utf-8")
    door = next(
        d for d in GEN.resolve_central_doors(root)[0] if d.door_id == "python.offload"
    )
    dominance = GEN._dominance(root, door, GEN.NameIndex.build(root))

    callback = _line(CALLBACK_MODULE, 'with open(target, "w")')
    leased = _line(CALLBACK_MODULE, 'with open(leased, "w")')
    under_lease = {line for line, _column in dominance.leased_positions}

    assert callback not in under_lease
    assert "_deferred_write" not in dominance.private_callees
    assert leased in under_lease


def test_the_offload_door_lease_dominates_its_bench_write():
    """THE MEASUREMENT, on the real tree, and the reason this lane existed.

    ``python.offload`` authenticated with zero refusals at merge 21f21f2a and
    dominated no blocking write surface, because ``worker.run`` sat in
    ``_offload_impl`` -- reachable from the leased entrypoint and from the
    un-leased ``live=False`` planning path. The provider run now lives behind a
    caller that cannot be reached without a lease, so the surface is attributed.

    The negative control is in the same file and matters as much: the snapshot
    helper's ``subprocess.run`` is reachable from ``_repo_snapshot``, which
    other modules import and call, so it stays un-attributed. A rule that
    admitted both would be admitting by file membership again.
    """

    from daedalus.gates.repository_write_inventory_v2 import (
        scan_repository_write_surfaces_v2,
    )

    doors, _skipped = GEN.resolve_central_doors(REPO_ROOT)
    door = next(d for d in doors if d.door_id == "python.offload")
    dominance = GEN._dominance(REPO_ROOT, door, GEN.NameIndex.build(REPO_ROOT))
    assert dominance.leased_refusal == ""

    inventory = scan_repository_write_surfaces_v2(
        REPO_ROOT, source_revision=REVISION
    )
    surfaces = [
        surface
        for surface in inventory.surfaces
        if surface.path == "daedalus/offload.py" and surface.blocking
    ]
    bench = [surface for surface in surfaces if surface.callee == "worker.run"]
    assert len(bench) == 1, [s.callee for s in surfaces]
    position = (bench[0].line, bench[0].column)
    assert position in dominance.positions
    assert position in dominance.leased_positions, (
        "the bench run is no longer attributed to python.offload's lease -- "
        "either a second caller reached the executor, or its name appeared in "
        "another Python source and the private-callee fixpoint refused it"
    )

    snapshot = [
        surface for surface in surfaces if surface.callee == "subprocess.run"
    ]
    assert len(snapshot) == 1
    assert (snapshot[0].line, snapshot[0].column) not in dominance.leased_positions


# THE FULL DERIVATION OVER THE REAL TREE IS NOT A TEST HERE, and the omission
# is deliberate rather than an oversight. ``derive`` runs the v2 scanner, which
# composes generation 2 from a base scan taken twice and refuses with "base
# inventory changed while composing generation 2" when a single byte of the
# checkout moves between them. This repository is worked by several sessions at
# once, so that refusal fires on other people's edits, not on this door. The
# end-to-end derivation is asserted on synthetic roots above, and measured on
# two isolated ``git archive`` snapshots of the SAME revision out of band --
# one plain, one carrying this change -- each given one real grant -> begin ->
# finish for ``python.offload``:
#
#   [MEASURED 2026-08-24, snapshot pair pinned to b07e1309; 435 surfaces in
#    both arms, so this is an A/B and not two different trees]
#     before: declared 0, lease_dominated 0, private_callees ()
#             admitted_surfaces: []
#             evidence_refusals: ["door python.offload: authenticated, and its
#                                  anchor dominates no blocking write surface;
#                                  its leased region holds none either"]
#             in-process census: blocked:...inventory_only 31, unclassified 404
#     after:  declared 1, lease_dominated 1, lease_refusal ""
#             private_callees ('_auto_mint', <the executor>)
#             admitted_surfaces: ["daedalus/offload.py:651:10"]  (worker.run)
#             evidence_refusals: []
#             in-process census: cleared:central 1,
#                                blocked:...inventory_only 31, unclassified 403
#
# The reporter's own failure count does not move (435 both ways) and that is
# not a disappointment: a ``central`` row carries a NonRuntimeConformityAdmission
# that has no wire shape, so the declaration FILE the reporter reads can never
# hold one. What moves in the report is the verdict histogram --
# blocked 31/unclassified 404 becomes blocked 32/unclassified 403 -- because the
# surface stopped being one nobody had looked at. The next owed stage is named
# rather than papered over: the six verifiers refuse the admitted row at
# GuardImplementationManifestError, because nothing in this tree signs a guard
# implementation manifest.
#
# Only ``daedalus/`` is scanned for surfaces, so nothing in tests/ can move
# these numbers -- which is why editing this comment does not invalidate it.


def test_the_real_gate_door_consumes_no_lease(tmp_path):
    """THE MEASUREMENT, on the real tree: ``python.command_gate`` is the only
    door here that declares a blocking write surface and has an in-process
    caller that could hold its lease, and its anchor consumes none. The writes
    live in the closure the factory returns, so even a lease taken inside that
    closure would sit below the anchor's region, not inside it."""

    doors, _skipped = GEN.resolve_central_doors(REPO_ROOT)
    gate = next(d for d in doors if d.door_id == "python.command_gate")
    dominance = GEN._dominance(REPO_ROOT, gate, GEN.NameIndex.build(REPO_ROOT))
    assert dominance.positions  # the anchor dominates its 2 surfaces
    assert dominance.leased_positions == frozenset()
    assert "no <authorization>.begin_effect" in dominance.leased_refusal


# --------------------------------------------------------------------------- #
# the guard, end to end, on an authenticated door                              #
# --------------------------------------------------------------------------- #
def test_a_lease_dominated_surface_is_central(control, synthetic_root):
    """The positive control: without this passing, the test below proves
    nothing, because a guard that refuses everything is not a guard."""

    _authenticated_door(control)
    derivation = _derive(synthetic_root, control)
    assert "python.offload" in derivation.authenticated_doors
    central = [
        row for row in derivation.rows if row.guard == GuardDisposition.CENTRAL
    ]
    assert central, [row.notes for row in derivation.rows]
    assert all(row.target is TargetDisposition.CHECKOUT_EXTERNAL for row in central)
    # Every central row sits below the lease consumption and above the end of
    # the anchor function -- i.e. inside the leased region, not merely inside
    # the module.
    consumption = _line(DUAL_CALLER_MODULE, "start = authorization.begin_effect")
    shared = _line(DUAL_CALLER_MODULE, "def _shared_write")
    for row in central:
        assert row.surface.line > consumption, row.surface
        assert row.surface.line > shared, row.surface
    assert {row.surface.callee for row in central} <= {"open", "handle.write"}


def test_a_write_between_the_receipt_and_the_lease_is_not_central(control, synthetic_root):
    """THE CASE THE OLD PRODUCER WOULD HAVE CLEARED.

    ``open(receipted, "w")`` is dominated by the registry receipt anchor and by
    nothing else: at the moment it runs, no lease has been started for this
    execution. A door that authenticates on some other invocation's terminal
    receipt says nothing about it, so it stays a blocker.
    """

    _authenticated_door(control)
    derivation = _derive(synthetic_root, control)
    receipted = _line(DUAL_CALLER_MODULE, 'with open(receipted, "w")')
    consumption = _line(DUAL_CALLER_MODULE, "start = authorization.begin_effect")
    assert receipted < consumption

    by_line = {row.surface.line: row for row in derivation.rows}
    row = by_line[receipted]
    assert row.guard is GuardDisposition.INVENTORY_ONLY
    assert row.target is TargetDisposition.UNKNOWN
    assert row.guard_contracts == ()
    # And the lease-dominated write one statement further down IS central, so
    # the difference is the lease and nothing else.
    leased = _line(DUAL_CALLER_MODULE, 'with open(leased, "w")')
    assert by_line[leased].guard is GuardDisposition.CENTRAL


def test_the_dual_caller_write_never_becomes_central(control, synthetic_root):
    """THE ADVERSARIAL CASE. ``_shared_write`` performs a write, is called from
    the leased branch of the anchor, and is ALSO called from ``plan_offload``,
    which holds no authorization. It must not authenticate, and it does not."""

    _authenticated_door(control)
    derivation = _derive(synthetic_root, control)
    for row in derivation.rows:
        if row.guard is GuardDisposition.CENTRAL:
            # The one central row is the leased write inside the anchor. The
            # dual-caller write is at a strictly larger line number and is not
            # among them.
            assert "_shared_write" not in row.notes
    unleased = [
        row for row in derivation.rows if row.guard is GuardDisposition.INVENTORY_ONLY
    ]
    # Every surface the anchor dominates but the lease does not stays a blocker
    # with the target unresolved.
    assert all(row.target is TargetDisposition.UNKNOWN for row in unleased)


def test_an_authenticated_door_that_classifies_nothing_says_so(control, tmp_path):
    """THE STATE OF THIS TREE, and it used to be a silent zero.

    ``python.offload`` authenticates with no refusals and its anchor dominates
    no blocking write surface, because its writes sit in ``_offload_impl``,
    which the un-leased ``live=False`` path also calls. Before this line the
    derivation reported ``evidence_refusals: []`` for exactly that -- an empty
    list that reads as "nothing to report" rather than as the measurement.
    """

    root = tmp_path / "no-surface"
    (root / "daedalus" / "kernel").mkdir(parents=True)
    (root / "daedalus" / "offload.py").write_text(
        '''def offload(authorization, execution):
    from daedalus.spine.effect_boundary import begin_effect

    begin_effect("python.offload", (), ())
    start = authorization.begin_effect(execution)
    return start
''',
        encoding="utf-8",
    )
    (root / "daedalus" / "kernel" / "offload_lease.py").write_text(
        ISSUER_STUB, encoding="utf-8"
    )
    _authenticated_door(control)
    derivation = _derive(root, control)
    assert derivation.authenticated_doors == ("python.offload",)
    assert derivation.rows == ()
    assert derivation.evidence_refusals == (
        "door python.offload: authenticated, and its anchor dominates no "
        "blocking write surface; its leased region holds none either",
    )


def test_the_guard_names_every_surface_it_costs_a_door(control, synthetic_root):
    """A silent zero would read as "there was nothing to classify"."""

    _authenticated_door(control)
    derivation = _derive(synthetic_root, control)
    if any(
        row.guard is GuardDisposition.INVENTORY_ONLY for row in derivation.rows
    ):
        assert any(
            "not lease-dominated" in reason
            for reason in derivation.evidence_refusals
        ), derivation.evidence_refusals


def _line(text: str, needle: str) -> int:
    """1-based line of ``needle`` in ``text``. Derived, never a magic number:
    editing the fixture module must not silently move what these tests pin."""

    for index, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return index
    raise AssertionError(f"{needle!r} is not in the fixture module")


def _positions(derivation, disposition):
    return {
        (row.surface.line, row.surface.column)
        for row in derivation.rows
        if row.guard is disposition
    }


# --------------------------------------------------------------------------- #
# the index is an instrument, and both ways it lied are pinned here            #
# --------------------------------------------------------------------------- #
def test_a_nested_checkout_does_not_disable_private_callee_attribution(tmp_path):
    """A repository inside the repository is not "a bigger superset".

    ``NameIndex`` is a deliberate over-count -- a name in a comment or a string
    counts -- and the class argues that the failure direction is safe because
    over-counting can only EXCLUDE a helper, never admit one. True, and not the
    whole story: a nested checkout is a copy of every module in the tree, so
    every module-private helper appears outside its own file at once and NO
    door can ever admit a private callee again. The instrument then reports
    zero attributed surfaces and looks exactly like a tree that has none.

    MEASURED 2026-08-26: a git worktree under ``.claude/worktrees/`` (excluded
    via ``.git/info/exclude``, so ``git status`` shows nothing) put 1173 files
    into the index and took the offload door's dominated positions from 573 to
    94. The fixture below is that situation in four files.
    """
    module = "".join(
        line + chr(10)
        for line in ("def _helper():", "    return 1", "", "",
                     "def door():", "    return _helper()")
    )
    (tmp_path / "a.py").write_text(module, encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    # A worktree marks itself with a `.git` FILE, a clone with a directory.
    # Both are pruned, and the fixture uses the shape that actually bit.
    (nested / ".git").write_text("gitdir: /elsewhere" + chr(10),
                                 encoding="utf-8")
    (nested / "a.py").write_text(
        "def _helper():" + chr(10) + "    return 1" + chr(10),
        encoding="utf-8",
    )

    index = GEN.NameIndex.build(tmp_path)

    assert "nested/a.py" not in index._per_file, sorted(index._per_file)
    assert "_helper" not in index.outside("a.py"), (
        "the nested checkout's copy of the module leaked its private helper "
        "into the outside set, which silently disables attribution repo-wide"
    )


def test_the_generator_never_names_a_door_private_helper():
    """The instrument must not appear in its own measurement.

    ``NameIndex`` reads RAW TEXT, so an identifier written into a docstring or
    a comment counts as a mention from that file. The generator is a file in
    the tree like any other: spelling a door module's private helper anywhere
    in it puts that name in every other file's ``outside`` set and refuses the
    helper for the door that owns it.

    This is not hypothetical. The commit that taught ``NameIndex.build`` to
    prune nested checkouts documented the fix by naming the exact helper it had
    just restored, and thereby broke it again -- the repair and its own defeat
    in one file. The probe costs one read and would have caught it immediately.

    A collision with one of the generator's OWN private helpers fails here too,
    and that is correct rather than a false positive: the consequence on disk
    is identical, and renaming one of the two is the fix.
    """
    generator = (REPO_ROOT / "scripts" / "declare_write_surfaces.py").read_text(
        encoding="utf-8", errors="replace"
    )
    mentioned = frozenset(GEN._IDENTIFIER.findall(generator))
    doors, _skipped = GEN.resolve_central_doors(REPO_ROOT)
    offenders: list[str] = []
    for door in doors:
        module_path = REPO_ROOT / door.rel_path
        if not module_path.is_file():
            continue
        tree = ast.parse(module_path.read_text(encoding="utf-8", errors="replace"))
        for statement in tree.body:
            if not isinstance(
                statement, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            name = statement.name
            if not name.startswith("_") or name.startswith("__"):
                continue
            if name in mentioned:
                offenders.append(f"{door.door_id}:{door.rel_path}:{name}")
    assert not offenders, (
        "the generator names these door-module private helpers, which "
        "removes them from every door's admissible set:" + chr(10)
        + (chr(10) + "  ").join(sorted(set(offenders)))
    )

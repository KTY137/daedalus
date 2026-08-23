"""A door that HELD a lease is not the same claim as a write that was UNDER one.

THE DEFECT THIS GUARD EXISTS FOR. ``authenticated_doors`` proves that a
registry row really granted, started and terminalised an Effect Lease at this
revision. The dominance analysis proves that every path to a write surface
crosses that row's ``begin_effect`` anchor. Neither of those, nor both, proves
that the write itself happened inside a leased execution -- and the two claims
come apart exactly where ``python.offload`` already showed they do: its writes
live in ``_offload_impl``, which the un-leased ``live=False`` planning path
also calls.

That case is caught today by accident. The private-callee fixpoint refuses a
helper the un-leased path also names, so ``_offload_impl`` never enters the
dominated region. A surface sitting DIRECTLY in an ``if authorization is not
None:`` region would not be refused by anything: the receipt anchor dominates
it, the door authenticates, and the row comes out ``cleared:central`` on the
strength of some other invocation's lease.

So the region is computed from the lease consumption itself.
``<authorization>.begin_effect(execution)`` is an attribute call and the free
``begin_effect(entrypoint_id, effects, decisions)`` receipt function is not,
which is the mechanical difference these tests pin. A surface outside the
leased region stays a blocker with the reason named.
"""
from __future__ import annotations

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

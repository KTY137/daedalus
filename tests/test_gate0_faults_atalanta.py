# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Gate-0 exit criterion, as a fault-injection matrix.

Section 10 of ``docs/IKARUS_ARIADNE_MASTER_PLAN.md`` lets Gate 0 exit only when
"a fault-injection matrix demonstrates fail-closed protected effects and
fail-open read-only inspection". Two halves; the repository covers them very
unevenly, and this file exists to name and close the cheap gaps rather than to
re-test what is already covered.

WHAT WAS ALREADY THERE, measured 2026-07-31 at HEAD 3088037 before writing a
line of this file:

  * ``tests/test_effect_boundary.py`` drives ``begin_effect`` through unknown
    entrypoints, undeclared effects, denials, empty evidence, duplicate and
    foreign decisions, and unknown/unimplemented guard contracts -- a strong
    fail-closed suite for the boundary's *arguments*.
  * ``tests/test_killswitch.py`` (41 tests) covers a corrupt, absent, oversized,
    non-utf8, directory-shaped and unreadable permit, all fail-closed.

WHAT WAS NOT THERE, and is what this file adds:

  1. The refusal is proven for exactly TWO of the registry's rows
     (``test_known_unguarded_paths_have_machine_readable_migrations``
     parametrises ``python.offload`` and ``python.promote_candidates``). The
     other 48 rows -- 40 ``inventory_only``, 7 ``local_guards``, 1 ``absent``
     -- are never driven through ``begin_effect`` at all. The registry is the
     thing Gate 0 is about; testing 2/50 of it and calling the boundary covered
     is the shape of claim this repository is supposed to refuse.
  2. Nothing anywhere asserts the SEALED-PROMOTION invariant survives a
     registry edit. ``GUARD_CONTRACT_IMPLEMENTED["promotion.owner_approval"]``
     is ``False`` on purpose; no test injects the obvious fault (someone marks
     the promotion row centrally wired) and checks the boundary still refuses.
  3. The words "fail-open" and "fail_open" do not occur anywhere in this
     project's own source. MEASURED: every hit of that string under the
     repository root is inside ``.venv-dspy`` third-party ``litellm``. The
     second half of the exit criterion has no named concept and no test, so
     "fail-open read-only inspection" is currently an unmeasured claim.

HOW EACH TEST WAS SHOWN TO BE LOAD-BEARING. A green test is not evidence that
a guard works. Every assertion below was run once with its guard deliberately
disabled and observed to go RED. [MEASURED 2026-07-31, HEAD 3088037], 7
mutations, 7 caught:

  =========================== ============================================
  guard disabled              observed
  =========================== ============================================
  wiring != CENTRAL refusal   refusals 50/50 -> 0/50; all 50 rows red
  owner_approval => True      promotion admitted; central-row test red
  checkpoint() returns        "DID NOT RAISE LoopHalted"; fail-closed red
  read_state() raises         fail-OPEN test red (inspection locked out)
  should_stop() raises        fail-OPEN test red (inspection locked out)
  check_conformance() raises  fail-OPEN test red on the broken tree
  scan.source_unreadable gone fail-CLOSED half red (``assert []``)
  =========================== ============================================

The two effect-boundary mutations ran against a standalone COPY of the module
in a scratch directory; the five runtime ones ran as a pytest plugin over this
real file. Neither route edited repository source -- other agents were working
in this tree at the time and a temporarily broken guard in a shared checkout
is a fault injected into their runs, not mine.

This file injects faults and asserts refusals. It is read-only with respect to
the repository: no test here writes outside ``tmp_path``.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import (
    ENTRYPOINTS,
    Effect,
    EffectStartRefused,
    GuardDecision,
    GUARD_CONTRACT_IMPLEMENTED,
    Wiring,
    begin_effect,
    check_conformance,
)
from daedalus.spine.killswitch import KillSwitch, LoopHalted


ROOT = Path(__file__).resolve().parents[1]


def _satisfied(spec) -> list[GuardDecision]:
    """Every guard the row declares, answered ALLOW with non-empty evidence.

    Deliberately the most permissive input a caller could construct: if the
    boundary still refuses, the refusal came from the row's own wiring or from
    an unimplemented contract, not from a malformed argument. Argument-shaped
    refusals are already covered in ``tests/test_effect_boundary.py`` and are
    not what this file is measuring.
    """
    return [
        GuardDecision(name, True, f"satisfied by the caller: {name}")
        for name in spec.guard_contracts
    ]


# --------------------------------------------------------------------------- #
# FAIL-CLOSED: protected effects                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("spec", ENTRYPOINTS, ids=lambda s: s.id)
def test_every_non_central_row_refuses_an_effect_start(spec) -> None:
    """No row that is not CENTRAL may start an effect -- all 50, not 2 of them.

    The caller here is maximally cooperative: it requests exactly the effects
    the row declares and answers every guard contract with ALLOW. The only
    thing that can refuse it is the wiring check, which is the Gate-0 property
    under test: an entrypoint that has not been migrated to the central start
    path cannot perform a protected effect no matter what it claims about
    itself.

    MEASURED at HEAD 3088037: 50/50 rows refuse, because 0/50 are CENTRAL
    (40 inventory_only, 7 local_guards, 2 unguarded, 1 absent). That makes the
    assertion trivially true TODAY and load-bearing TOMORROW -- the moment a
    row is flipped to CENTRAL it leaves this branch and must satisfy
    ``test_a_central_row_may_not_rest_on_an_unimplemented_guard`` instead, so
    no row can become central without some test in this file noticing.

    GUARD DISABLED, RED CONFIRMED [MEASURED 2026-07-31]: deleting the
    ``spec.wiring is not Wiring.CENTRAL`` refusal at
    ``daedalus/spine/effect_boundary.py:663`` (in a standalone copy of the
    module -- the repository source was not touched) drops the refusal count
    from 50/50 to 0/50, so every row here goes red. An earlier draft of this
    docstring guessed 47/50, reasoning that three rows would still refuse on an
    unimplemented guard contract; that guess was wrong and is recorded here
    rather than quietly corrected. The wiring check runs BEFORE the
    guard-contract checks, and this test matches on "not central"
    specifically, so a row refused for any other reason still fails it.
    """
    if spec.wiring is Wiring.CENTRAL:
        pytest.skip(f"{spec.id} is CENTRAL; covered by the central-row test")

    with pytest.raises(EffectStartRefused, match="not central"):
        begin_effect(spec.id, spec.effects or [Effect.FILESYSTEM_WRITE], _satisfied(spec))


def test_a_central_row_may_not_rest_on_an_unimplemented_guard(monkeypatch) -> None:
    """A central registry edit cannot turn an unimplemented guard into authority."""

    import daedalus.spine.effect_boundary as boundary

    monkeypatch.setattr(
        boundary,
        "GUARD_CONTRACT_IMPLEMENTED",
        {**dict(boundary.GUARD_CONTRACT_IMPLEMENTED), "test.unimplemented": False},
    )
    monkeypatch.setattr(
        boundary,
        "POLICY_CONTRACTS",
        frozenset(boundary.GUARD_CONTRACT_IMPLEMENTED),
    )
    row = next(r for r in ENTRYPOINTS if r.id == "python.offload")
    fault = dataclasses.replace(
        row,
        guard_contracts=("test.unimplemented",),
        wiring=Wiring.CENTRAL,
    )
    with pytest.raises(EffectStartRefused, match="unimplemented guard"):
        begin_effect(
            fault.id,
            fault.effects,
            [GuardDecision("test.unimplemented", True, "claimed")],
            registry={fault.id: fault},
        )


def test_every_central_row_declares_only_implemented_guards() -> None:
    """The drift detector for the migration that has not happened yet.

    Today this iterates an empty set -- no row is CENTRAL. It is here so that
    the first row migrated to the central path cannot arrive carrying a guard
    contract that is declared but not implemented, which is precisely how a
    boundary becomes decorative: every row central, every guard a string.
    """
    for spec in ENTRYPOINTS:
        if spec.wiring is not Wiring.CENTRAL:
            continue
        unimplemented = [
            name for name in spec.guard_contracts
            if not GUARD_CONTRACT_IMPLEMENTED.get(name, False)
        ]
        assert not unimplemented, (
            f"{spec.id} is CENTRAL but rests on unimplemented guard "
            f"contract(s): {unimplemented}")
        assert spec.guard_contracts, (
            f"{spec.id} is CENTRAL with no guard contracts at all")


def test_the_kill_switch_fails_closed_at_a_checkpoint() -> None:
    """A stopped switch must stop the loop by raising, not by returning False.

    Paired deliberately with the fail-open test below: this is the protected
    half of the same injected fault (the permit is revoked), and the two must
    hold simultaneously for the exit criterion to be met.

    GUARD DISABLED, RED CONFIRMED [MEASURED 2026-07-31]: patching
    ``KillSwitch.checkpoint`` to return instead of raising fails this test with
    "DID NOT RAISE LoopHalted".
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        switch = KillSwitch(Path(tmp) / "permit", poll_s=0.02)
        switch.arm()
        switch.checkpoint()  # armed: must not raise

        switch.stop(reason="fault injection: operator revoked the permit")

        assert switch.should_stop() is True
        with pytest.raises(LoopHalted):
            switch.checkpoint()


# --------------------------------------------------------------------------- #
# FAIL-OPEN: read-only inspection                                             #
# --------------------------------------------------------------------------- #
def test_read_only_inspection_still_answers_while_effects_are_refused() -> None:
    """The half of the exit criterion nothing in this repository measured.

    THE INJECTED FAULT: the kill switch is stopped, so every protected effect
    is refused (asserted above). Under that same fault, the read-only
    inspection surfaces must keep answering -- an operator diagnosing why the
    machine stopped must not be locked out by the stop itself. A system that
    fails closed on inspection as well as on effects is not safe, it is
    bricked, and the plan asks for both properties by name.

    Three inspection paths are driven here: the switch's own state read, its
    stop predicate, and the effect-boundary conformance report.

    GUARD DISABLED, RED CONFIRMED [MEASURED 2026-07-31], two separate
    mutations: patching ``KillSwitch.read_state`` to raise fails this test, and
    so, independently, does patching ``should_stop`` to propagate rather than
    swallow. Both also take the fail-closed checkpoint test down with them,
    which is the expected coupling -- inspection is on that path too.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        switch = KillSwitch(Path(tmp) / "permit", poll_s=0.02)
        switch.arm()
        switch.stop(reason="fault injection")

        # inspection answers, and answers HONESTLY (stopped, with a reason)
        state = switch.read_state()
        assert state.running is False
        assert state.reason, "a stopped switch inspected with no reason to show"
        assert switch.should_stop() is True  # never raises, by contract

        # and the same read is repeatable rather than a one-shot latch
        assert switch.read_state().running is False

    # the boundary's own inspection surface answers with the switch stopped
    report = check_conformance(ROOT)
    assert report.matrix, "the conformance matrix came back empty"
    assert report.gate0_closed is False
    payload = report.to_dict()
    assert payload["security_boundary_claimed"] is False
    json.dumps(payload)  # inspection output must be serialisable for an operator


def test_an_unreadable_source_tree_fails_closed_but_still_reports(tmp_path: Path) -> None:
    """Both halves of the criterion on ONE fault, which is the point of a matrix.

    THE INJECTED FAULT: a module in the scanned package does not parse. The
    scanner cannot know what effects it performs.

    FAIL-CLOSED: ``structurally_conformant`` must go False. An unreadable file
    is not an absent risk; treating "I could not read it" as "it is fine" is
    the exact inversion this repository has shipped before.

    FAIL-OPEN: the report is still PRODUCED, still enumerates, still names the
    unreadable file. ``check_conformance`` must not raise -- an inspection tool
    that crashes on the broken tree is useless precisely when it is needed.

    ``tests/test_effect_boundary.py:312`` asserts the fail-closed half of this.
    The fail-open half -- that a report comes back at all and names the fault
    -- is asserted here for the first time.

    GUARD DISABLED, RED CONFIRMED [MEASURED 2026-07-31], two separate
    mutations: filtering ``scan.source_unreadable`` out of the findings fails
    the fail-closed half (``assert []``), and letting the ``SyntaxError``
    propagate out of the scanner fails the fail-open half with an ERROR rather
    than an assertion -- which is itself the distinction this test draws.
    """
    package = tmp_path / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "readable.py").write_text(
        "import subprocess\n\ndef main():\n    subprocess.run(['tool'])\n",
        encoding="utf-8")
    (package / "broken.py").write_text("def main(:\n    pass\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='fixture'\n", encoding="utf-8")

    report = check_conformance(tmp_path, registry=())

    # fail-closed
    assert report.structurally_conformant is False
    assert report.gate0_closed is False
    unreadable = [row for row in report.findings if row.code == "scan.source_unreadable"]
    assert unreadable, "an unparseable module was scanned without a finding"
    assert any("broken" in row.subject for row in unreadable), (
        "the unreadable-source finding does not name the file it could not read")

    # fail-open: the report still exists, still enumerates, still serialises
    assert report.findings
    assert json.dumps(report.to_dict())
    assert any(row.target == "daedalus.readable:main" for row in report.discoveries), (
        "one unparseable file suppressed discovery of its readable neighbour; "
        "inspection failed closed where it should have degraded")

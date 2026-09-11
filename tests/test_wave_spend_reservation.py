"""The leased spend ceiling, made of money instead of of declarations.

FINDING F7 (measured 2026-08-22, agent_env_g0 HEAD 898ac110). A wave's Effect
Lease published ``max_cost_microusd`` -- 250000 for ``--max-spend-usd 0.25`` --
and NOTHING subtracted from it. ``daedalus/kernel/effects.py:304-307`` compared
the execution's declaration against the lease's declaration; ``grep -rn
max_cost_microusd daedalus/`` found no other enforcement site at all. The only
real ceiling a live wave ran under was ``daedalus.budget``'s period ceiling
(``DAEDALUS_BUDGET_USD``, default $5.00/day), which is a different number from
a different operator gesture. A wave leased a quarter could spend four dollars
without one refusal.

The fix is a BUDGET RESERVATION, not a second ledger: when the wave's lease is
granted, ``WaveExecutor._open_spend_envelope`` opens a spend envelope on the
one existing ledger for exactly the leased ceiling, and every reservation made
inside it -- explicit or interposed by ``install_process_guard`` -- draws that
envelope down and is refused at ITS number, with the lease named in the
refusal. The unused hold is released when the wave ends and the realized spend
is written into the receipt beside the ceiling.

Each test below fails if one link is removed:

* drop the envelope             -> ``test_granted_lease_reserves_its_ceiling``
* enforce only the day's cap    -> ``test_spend_past_the_leased_ceiling_*``
* let the interposer through    -> ``test_the_process_guard_refuses_*``
* never close the envelope      -> ``test_wave_end_releases_the_hold_*``
* dispatch anyway when the money cannot be held
                                -> ``test_a_wave_that_cannot_hold_its_ceiling_*``

NOT ONE BILLABLE CALL IS MADE HERE. ``_offload_impl`` is patched out, and the
process-guard test interposes over a spy, never over a real ``subprocess.run``
-- exactly as ``tests/test_budget.py`` does.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

import daedalus.budget as B
from daedalus.build import BuildTask, Wave
from daedalus.build_exec import EffectBounds, WaveExecutor
from daedalus.kairos.scheduler import Assignment, KairosScheduler
from daedalus.kernel.offload_lease import control_root
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = str(Path(__file__).resolve().parents[1])
REVISION = "b" * 40

#: The wave is leased this much. The period ceiling below is TWENTY TIMES it on
#: purpose: every refusal in this file must be the LEASE's refusal, never the
#: day's, and a test that cannot tell them apart proves nothing.
LEASE_USD = 0.25
PERIOD_CEILING_USD = 5.00


@pytest.fixture
def env(tmp_path, monkeypatch):
    """An armed permit, a temp lease ledger, and a temp BUDGET ledger."""
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    monkeypatch.setenv("DAEDALUS_BUDGET_LEDGER", str(tmp_path / "budget.json"))
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", f"{PERIOD_CEILING_USD:.2f}")
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "40")
    monkeypatch.delenv(B.ENV_EXECUTION_LIMIT_POLICY, raising=False)
    monkeypatch.delenv(B.ENV_ENVELOPE, raising=False)
    B.reset_default_ledger()
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="test")
    assert control_root(REPO_ROOT) == tmp_path
    yield sw
    B.reset_default_ledger()


def _assignment(mode: str = "advisory", paths=("docs/x.md",)) -> Assignment:
    return Assignment(objective="review the docref", paths=list(paths),
                      owner="Clio", lane="ollama", worker="Lucia", mode=mode,
                      accepted=True, reason="test routing")


def _wave(n: int = 1) -> Wave:
    return Wave(index=0, tasks=[
        BuildTask(objective=f"task {i}", agent="Clio", category="docs",
                  lane="ollama", tier="cheap", builder="ollama",
                  frontier=False, paths=[f"docs/x{i}.md"])
        for i in range(n)])


def _executor(sw: KillSwitch, *, max_spend_usd: float = LEASE_USD) -> WaveExecutor:
    return WaveExecutor(
        availability={"ollama": True},
        effect_bounds=EffectBounds(
            mission_id="spend-test", source_revision=REVISION,
            max_spend_usd=max_spend_usd, timeout_s=900.0,
            trace_id="tr-test", switch=sw))


def _estimate(usd: float) -> B.Estimate:
    return B.Estimate(vendor="deepseek", model="chat", usd=usd, calls=1,
                      basis="priced")


def _run_live_wave(sw, *, during, tasks: int = 1):
    """Run one live advisory wave, calling ``during()`` inside the dispatch.

    ``during`` runs where a provider would: after the lease is granted and the
    envelope opened, before the wave ends. That window is the whole subject of
    this file -- outside it there is no leased ceiling to test.
    """
    seen: list = []

    def _impl(*a, **kw):
        seen.append(during())
        return {"action": "offloaded", "wrote": []}

    wave = _wave(tasks)
    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment() for _ in range(tasks)]):
        with mock.patch("daedalus.offload._offload_impl", side_effect=_impl):
            result = _executor(sw).run_wave(
                KairosScheduler(availability={"ollama": True}), wave,
                REPO_ROOT, dry_run=False, parallel=False)
    return result, seen


# --------------------------------------------------------------------------- #
# the reservation                                                              #
# --------------------------------------------------------------------------- #
def test_granted_lease_reserves_its_ceiling_on_the_budget_ledger(env):
    result, seen = _run_live_wave(env, during=lambda: B.ledger().state())
    inside = seen[0]
    # ONE envelope, holding EXACTLY the leased ceiling -- the same number the
    # lease receipt publishes as max_cost_microusd, in dollars.
    assert len(inside.envelopes) == 1, inside.as_dict()
    envelope = inside.envelopes[0]
    assert envelope["cap_usd"] == pytest.approx(LEASE_USD)
    assert envelope["lease_id"] == result.results[0]["effect_lease"]["lease_id"]
    # It is HELD, not merely recorded: the period ledger's own committed total
    # went up by the leased ceiling the moment the capability was issued.
    assert inside.envelope_hold_usd == pytest.approx(LEASE_USD)
    assert inside.committed_usd == pytest.approx(LEASE_USD)
    assert inside.remaining_usd == pytest.approx(PERIOD_CEILING_USD - LEASE_USD)


def test_exact_effect_replay_skips_a_second_hold_with_orphan_envelope(env):
    """A crash may leave the provider terminal in the Effect Ledger while its
    spend envelope is still open.  The restart must consult that ledger before
    attempting another hold: otherwise an unrelated hold can budget-refuse the
    replay, or a roomy period can hold the same lease twice.

    Provider work is mocked below ``offload``; no process or network starts.
    """
    issued_at = datetime.now(timezone.utc)
    bounds = EffectBounds(
        mission_id="file-bridge-replay-test",
        source_revision=REVISION,
        max_spend_usd=LEASE_USD,
        timeout_s=900.0,
        trace_id="tr-file-bridge-replay",
        switch=env,
        attempt_id="file-bridge-replay-attempt",
        lease_id="file-bridge-replay-lease",
        issued_at=issued_at,
    )

    def run_once():
        return WaveExecutor(
            availability={"ollama": True}, effect_bounds=bounds
        ).run_wave(
            KairosScheduler(availability={"ollama": True}),
            _wave(1),
            REPO_ROOT,
            dry_run=False,
            parallel=False,
        )

    orphan = other = None
    try:
        with mock.patch.object(
            KairosScheduler, "accept", return_value=[_assignment()]
        ), mock.patch(
            "daedalus.offload._offload_impl",
            return_value={"action": "offloaded", "wrote": []},
        ) as provider:
            first = run_once()
            lease_id = first.results[0]["effect_lease"]["lease_id"]
            assert lease_id == bounds.lease_id

            # Model a hard process death before SpendEnvelope.__exit__: the exact
            # lease's hold is still present. A competing admitted hold leaves less
            # than LEASE_USD free, so opening a third envelope would be refused.
            orphan = B.ledger().open_envelope(
                LEASE_USD, label="interrupted wave", lease_id=lease_id
            )
            other = B.ledger().open_envelope(
                4.60, label="other admitted work", lease_id="other-lease"
            )
            before = B.ledger().state()
            assert before.remaining_usd < LEASE_USD
            assert len(before.envelopes) == 2

            replay = run_once()

        assert provider.call_count == 1
        assert replay.results[0]["status"] == "effect_replay"
        assert replay.spend_envelope is None
        after = B.ledger().state()
        assert len(after.envelopes) == 2, "replay opened a duplicate spend hold"
        assert {row["id"] for row in after.envelopes} == {orphan.id, other.id}
    finally:
        if orphan is not None:
            orphan.close("test cleanup")
        if other is not None:
            other.close("test cleanup")


def test_pre_effect_crash_reuses_its_exact_spend_hold(env):
    """A restart rejoins the hold published before ``begin_effect``.

    The injected death happens in ``SpendEnvelope.__enter__``: the ledger has
    durably admitted the money, but scheduler dispatch (and therefore the
    Effect execution start) has not happened.  A competing hold makes a second
    reservation for this lease impossible, so the retry can succeed only by
    reusing the first envelope.  Provider work remains mocked below offload.
    """
    class PreEffectCrash(BaseException):
        pass

    bounds = EffectBounds(
        mission_id="file-bridge-pre-effect-replay-test",
        source_revision=REVISION,
        max_spend_usd=LEASE_USD,
        timeout_s=900.0,
        trace_id="tr-file-bridge-pre-effect-replay",
        switch=env,
        attempt_id="file-bridge-pre-effect-attempt",
        lease_id="file-bridge-pre-effect-lease",
        issued_at=datetime.now(timezone.utc),
    )

    def run_once():
        return WaveExecutor(
            availability={"ollama": True}, effect_bounds=bounds
        ).run_wave(
            KairosScheduler(availability={"ollama": True}),
            _wave(1),
            REPO_ROOT,
            dry_run=False,
            parallel=False,
        )

    real_enter = B.SpendEnvelope.__enter__
    injected = False
    orphan = other = None

    def crash_once(spend_envelope):
        nonlocal injected, orphan
        if not injected:
            injected = True
            orphan = spend_envelope
            raise PreEffectCrash("died after hold, before Effect start")
        return real_enter(spend_envelope)

    try:
        with mock.patch.object(
            KairosScheduler, "accept", return_value=[_assignment()]
        ), mock.patch(
            "daedalus.offload._offload_impl",
            return_value={"action": "offloaded", "wrote": []},
        ) as provider, mock.patch.object(
            B.SpendEnvelope, "__enter__", new=crash_once
        ):
            with pytest.raises(PreEffectCrash, match="before Effect start"):
                run_once()

            assert provider.call_count == 0
            before = B.ledger().state()
            assert len(before.envelopes) == 1
            assert before.envelopes[0]["id"] == orphan.id
            assert before.envelopes[0]["lease_id"] == bounds.lease_id

            other = B.ledger().open_envelope(
                4.60, label="other admitted work", lease_id="other-lease"
            )
            assert B.ledger().state().remaining_usd < LEASE_USD

            retry = run_once()

        assert provider.call_count == 1
        assert retry.mode == "sequential"
        assert retry.results[0]["status"] == "offloaded"
        assert retry.spend_envelope["id"] == orphan.id
        after = B.ledger().state()
        assert {row["id"] for row in after.envelopes} == {other.id}

        budget_doc = B.ledger()._load()
        opens = [
            row for row in budget_doc["entries"]
            if row.get("kind") == "envelope_open"
            and row.get("lease_id") == bounds.lease_id
        ]
        reuses = [
            row for row in budget_doc["entries"]
            if row.get("kind") == "envelope_reuse"
            and row.get("lease_id") == bounds.lease_id
        ]
        assert len(opens) == 1, "retry double-held the stable lease"
        assert len(reuses) == 1
    finally:
        if orphan is not None and orphan.state() is not None:
            orphan.close("test cleanup")
        if other is not None and other.state() is not None:
            other.close("test cleanup")


def test_spend_past_the_leased_ceiling_is_refused_while_the_day_has_room(env):
    def _overspend():
        with pytest.raises(B.BudgetRefused) as excinfo:
            B.ledger().reserve(_estimate(LEASE_USD + 0.01), label="one call too many")
        return excinfo.value

    result, seen = _run_live_wave(env, during=_overspend)
    refusal = seen[0]
    # THE LEASE REFUSED IT, NOT THE DAY. This distinction is the finding: the
    # period ceiling still had $4.75 of room at this instant.
    assert refusal.envelope is not None
    assert refusal.envelope["lease_id"] == result.results[0]["effect_lease"]["lease_id"]
    assert refusal.envelope["cap_usd"] == pytest.approx(LEASE_USD)
    assert refusal.ceiling_usd == pytest.approx(PERIOD_CEILING_USD)
    assert "leased spend ceiling" in refusal.reason
    # And the message names the lease, so a receipt of the refusal is joinable
    # to the capability that made it.
    assert refusal.envelope["lease_id"] in str(refusal)


def test_spend_inside_the_leased_ceiling_still_goes_through(env):
    """The ALLOW half. A ceiling that refuses everything passes every refusal
    test above and breaks the product."""
    def _spend():
        res = B.ledger().reserve(_estimate(0.10), label="a call that fits")
        res.settle()
        return B.ledger().state()

    _, seen = _run_live_wave(env, during=_spend)
    inside = seen[0]
    assert inside.spent_usd == pytest.approx(0.10)
    assert inside.envelopes[0]["drawn_usd"] == pytest.approx(0.10)
    assert inside.envelopes[0]["remaining_usd"] == pytest.approx(LEASE_USD - 0.10)
    # The draw did not ALSO add to the period commitment: the hold shrank by
    # exactly what was drawn. Double-counting here would refuse legitimate work
    # at the day's ceiling long before the day's money was gone.
    assert inside.committed_usd == pytest.approx(LEASE_USD)


def test_the_process_guard_refuses_an_interposed_vendor_call_at_the_lease(env):
    """The interposer is the net under the explicit reservations -- the only
    thing between an un-edited call site and the ceiling -- and it must read
    the LEASE's number while a wave is running.

    MEASURED, and it is why this test is possible at all: acquiring the wave's
    lease installs the guard itself (``kernel/offload_lease.py`` runs
    ``budget.process_guard_boundary_decision`` as the ``budget.process_guard``
    contract), so the interposer under test here is the production one.
    """
    spy = mock.Mock(return_value="ok")

    def _through_the_guard():
        # The wave already installed it. Re-arm it over a spy so the refusal is
        # measured without a real vendor binary anywhere near this test --
        # uninstall first, because install_process_guard is idempotent and
        # would otherwise leave the spy unguarded.
        assert B._INSTALLED, "the wave's own lease must install the spend guard"
        B.uninstall_process_guard()
        try:
            with mock.patch.object(subprocess, "run", spy):
                uninstall = B.install_process_guard()
                try:
                    # Priced as one worst-case Anthropic CLI call ($3.00,
                    # basis=worst_case): far above a $0.25 lease and still
                    # under the $5.00 day.
                    with pytest.raises(B.BudgetRefused) as excinfo:
                        subprocess.run(["claude", "-p", "do the thing"])
                    return excinfo.value
                finally:
                    uninstall()
        finally:
            B.install_process_guard()      # leave the wave as it was found

    result, seen = _run_live_wave(env, during=_through_the_guard)
    refusal = seen[0]
    assert refusal.envelope is not None
    assert refusal.envelope["lease_id"] == result.results[0]["effect_lease"]["lease_id"]
    assert refusal.ceiling_usd == pytest.approx(PERIOD_CEILING_USD)
    # REFUSED BEFORE THE SPAWN. The point of interposing at all.
    assert spy.call_count == 0


# --------------------------------------------------------------------------- #
# the release, and the receipt                                                 #
# --------------------------------------------------------------------------- #
def test_wave_end_releases_the_hold_and_reports_the_realized_spend(env):
    def _spend():
        B.ledger().reserve(_estimate(0.10), label="one call").settle()
        return None

    result, _ = _run_live_wave(env, during=_spend)
    after = B.ledger().state()
    # NOTHING STILL HELD. An envelope that outlives its wave holds the day's
    # money hostage against work that is already over.
    assert after.envelopes == ()
    assert after.envelope_hold_usd == 0.0
    assert after.reserved_usd == 0.0
    # The money that was really spent stays spent.
    assert after.spent_usd == pytest.approx(0.10)
    # AUTHORISED AND REALIZED, SIDE BY SIDE, in the wave's own receipt.
    envelope = result.spend_envelope
    assert envelope["cap_usd"] == pytest.approx(LEASE_USD)
    assert envelope["spent_usd"] == pytest.approx(0.10)
    stamped = result.results[0]["effect_lease"]
    assert stamped["max_cost_microusd"] == int(LEASE_USD * 1_000_000)
    assert stamped["spend_envelope"]["spent_usd"] == pytest.approx(0.10)
    assert stamped["spend_envelope"]["lease_id"] == stamped["lease_id"]


def test_the_hold_is_released_even_when_the_wave_raises(env):
    def _boom(*a, **kw):
        raise RuntimeError("the provider exploded")

    wave = _wave(1)
    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment()]):
        with mock.patch("daedalus.offload._offload_impl", side_effect=_boom):
            with pytest.raises(RuntimeError):
                _executor(env).run_wave(
                    KairosScheduler(availability={"ollama": True}), wave,
                    REPO_ROOT, dry_run=False, parallel=False)
    assert B.ledger().state().envelopes == ()


# --------------------------------------------------------------------------- #
# fail closed                                                                  #
# --------------------------------------------------------------------------- #
def test_a_wave_that_cannot_hold_its_ceiling_does_not_dispatch(env, monkeypatch):
    """The period ceiling is nearly exhausted, so the leased ceiling cannot be
    pre-authorised. A capability nobody can pay for does not get spent
    against: the wave is refused BEFORE any attempt is started."""
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "0.10")
    B.reset_default_ledger()
    impl = mock.Mock(return_value={"action": "offloaded", "wrote": []})
    wave = _wave(1)
    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment()]):
        with mock.patch("daedalus.offload._offload_impl", impl):
            result = _executor(env).run_wave(
                KairosScheduler(availability={"ollama": True}), wave,
                REPO_ROOT, dry_run=False, parallel=False)
    assert result.mode == "spend_denied"
    assert result.landed_tasks == 0 and result.bounced_tasks == 1
    assert result.results[0]["status"] == "spend_envelope_denied"
    assert "pre-authorise" in result.results[0]["reason"]
    # NOT ONE ATTEMPT STARTED, and no envelope left behind.
    assert impl.call_count == 0
    assert B.ledger().state().envelopes == ()
    assert all(t.status == "bounced" for t in wave.tasks)


def test_a_dry_run_reserves_nothing(env):
    """A dry run cannot spend by construction, so it must not hold money
    either -- a hold is a change, and the dry run's contract is that it makes
    none."""
    wave = _wave(1)
    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment()]):
        result = _executor(env).run_wave(
            KairosScheduler(availability={"ollama": True}), wave,
            REPO_ROOT, dry_run=True, parallel=False)
    assert result.spend_envelope is None
    assert B.ledger().state().envelopes == ()

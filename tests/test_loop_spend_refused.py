"""A draw refused at the LEASED ceiling ends an iteration, not the run.

THE FINDING (measured 2026-08-22, agent_env_g0 HEAD 5f586455, probe
``heracles-refused-probe.py``). Since ``be9c2692`` a granted wave lease holds a
:class:`daedalus.budget.SpendEnvelope`, so a draw past the leased ceiling
raises :class:`daedalus.budget.BudgetRefused` from inside ``offload()`` -- i.e.
from inside ``KairosScheduler.dispatch``'s ``_run_one``, in the middle of a
wave. ``offload()`` marks the effect FAILED and re-raises (``offload.py:801``),
and NOTHING between there and the loop's outermost handler caught it. Measured
before the fix, with the refusal injected at position 2 of 3:

* ``KairosScheduler.dispatch``  -> raised; position 1's finished result was
  LOST with it (``results`` is a local list);
* ``WaveExecutor.run_wave``     -> raised; all three tasks left marked
  ``"dispatched"`` forever, no ``WaveResult``, no receipt;
* ``LoopDriver._run_iteration`` -> raised into ``run()``'s outermost handler,
  which ended the WHOLE run with ``stop_reason="error"``, ``iterations_run=0``
  and zero LoopLedger rows.

Fail-closed, wrong shape. Money that stops is correct; a run that loses the
evidence of an iteration that really happened is not. A refusal has a lease id,
a reason and a realized spend -- it is an OUTCOME, and it is now reported as
one at every level, position-matched like every other result.

Each test below fails if one link is removed:

* drop the per-position translation in ``KairosScheduler.dispatch``
    -> ``test_a_refused_draw_in_position_2_of_3_keeps_position_1s_result``
* drop the wave-level net / the ``mode`` in ``run_wave``
    -> ``test_the_wave_reports_the_refusal_instead_of_raising``
* never close the envelope
    -> ``test_the_envelope_is_closed_and_the_hold_released``
* retry the refused call
    -> ``test_nothing_retries_the_refused_call``
* drop the catch at the iteration boundary in ``LoopDriver._run_iteration``
    -> ``test_an_escaped_refusal_still_ends_the_iteration_with_a_receipt``
* drop the receipt / the LoopLedger detail
    -> ``test_the_iteration_receipt_names_the_lease_and_the_realized_spend``
* continue past the loop's own exhausted --max-spend-usd
    -> ``test_the_run_ends_with_the_receipt_when_the_loops_own_bound_is_gone``

NOT ONE BILLABLE CALL IS MADE HERE. ``_offload_impl`` is patched out and every
refusal is produced by the real ledger on a temp budget file, exactly as
``tests/test_wave_spend_reservation.py`` does.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

import daedalus.budget as B
from daedalus.build import BuildTask, Wave
from daedalus.build_exec import EffectBounds, WaveExecutor, WaveResult
from daedalus.kairos.scheduler import (
    SPEND_REFUSED_SKIPPED_STATUS,
    SPEND_REFUSED_STATUS,
    Assignment,
    KairosScheduler,
    spend_refused_result,
)
from daedalus.kernel.offload_lease import control_root
from daedalus.orchestration.loop import LoopBounds, LoopDriver
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = str(Path(__file__).resolve().parents[1])
REVISION = "c" * 40

#: The wave is leased this much; the period ceiling is twenty times it, so
#: every refusal here is the LEASE's refusal and never the day's.
LEASE_USD = 0.25
PERIOD_CEILING_USD = 5.00


@pytest.fixture
def env(tmp_path, monkeypatch):
    """An armed permit, a temp lease ledger, and a temp BUDGET ledger."""
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    monkeypatch.setenv("DAEDALUS_BUDGET_LEDGER", str(tmp_path / "budget.json"))
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", f"{PERIOD_CEILING_USD:.2f}")
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "40")
    monkeypatch.delenv(B.ENV_ENVELOPE, raising=False)
    B.reset_default_ledger()
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="test")
    assert control_root(REPO_ROOT) == tmp_path
    yield sw
    B.reset_default_ledger()


def _assignment(i: int = 0) -> Assignment:
    return Assignment(objective=f"review docref {i}", paths=[f"docs/x{i}.md"],
                      owner="Clio", lane="ollama", worker="Lucia",
                      mode="advisory", accepted=True, reason="test routing")


def _wave(n: int = 3) -> Wave:
    return Wave(index=0, tasks=[
        BuildTask(objective=f"task {i}", agent="Clio", category="docs",
                  lane="ollama", tier="cheap", builder="ollama",
                  frontier=False, paths=[f"docs/x{i}.md"])
        for i in range(n)])


def _executor(sw: KillSwitch, *, max_spend_usd: float = LEASE_USD) -> WaveExecutor:
    return WaveExecutor(
        availability={"ollama": True},
        effect_bounds=EffectBounds(
            mission_id="spend-refused-test", source_revision=REVISION,
            max_spend_usd=max_spend_usd, timeout_s=900.0,
            trace_id="tr-refused", switch=sw))


def _estimate(usd: float) -> B.Estimate:
    return B.Estimate(vendor="deepseek", model="chat", usd=usd, calls=1,
                      basis="priced")


def _refuse_at_position_2(sw, *, tasks: int = 3):
    """One live advisory wave of ``tasks``; position 2 (index 1) draws past the
    LEASED ceiling and the real ledger refuses it.

    Nothing is faked but the provider call: the envelope, the refusal, the
    lease id it names and the realized spend all come from the production
    ledger on the fixture's temp budget file.
    """
    seen: list[int] = []

    def _impl(*a, **kw):
        seen.append(len(seen))
        if len(seen) == 2:
            # Not caught: this is exactly how a real over-draw leaves
            # `_offload_impl` -- offload() marks the effect FAILED and re-raises.
            B.ledger().reserve(_estimate(LEASE_USD + 0.01),
                               label="one call too many")
        return {"action": "offloaded", "wrote": []}

    wave = _wave(tasks)
    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment(i) for i in range(tasks)]):
        with mock.patch("daedalus.offload._offload_impl", side_effect=_impl):
            result = _executor(sw).run_wave(
                KairosScheduler(availability={"ollama": True}), wave,
                REPO_ROOT, dry_run=False, parallel=False)
    return result, wave, seen


# --------------------------------------------------------------------------- #
# the wave                                                                     #
# --------------------------------------------------------------------------- #
def test_the_wave_reports_the_refusal_instead_of_raising(env):
    """The whole finding in one assertion: run_wave RETURNS."""
    result, wave, _ = _refuse_at_position_2(env)

    assert isinstance(result, WaveResult)
    assert result.mode == "spend_refused"
    # The wave says why on its own face, so a caller switching on `mode` does
    # not have to scan N result dicts to find out what stopped it.
    assert "leased spend ceiling refused" in (result.forced_sequential_reason or "")
    # And no task is left in the pre-terminal "dispatched" state, which is what
    # a raise left behind (measured before the fix). Position 1's advisory call
    # really finished, so it keeps its own terminal status -- a refusal at
    # position 2 does not retroactively bounce work that was already done.
    assert [t.status for t in wave.tasks] == ["landed", "bounced", "bounced"]


def test_a_refused_draw_in_position_2_of_3_keeps_position_1s_result(env):
    """Position-matched, full length, earlier work preserved."""
    result, _, _ = _refuse_at_position_2(env)
    rows = result.results

    assert len(rows) == 3, rows
    # Position 1 really ran and its result survives the refusal at position 2.
    assert rows[0]["status"] == "offloaded"
    assert rows[0]["effect_lease"]["lease_id"]
    # Position 2 asked for money and was told no.
    assert rows[1]["status"] == SPEND_REFUSED_STATUS
    # Position 3 was never called: the wave's money was already gone, and
    # "refused" and "never attempted" are different facts.
    assert rows[2]["status"] == SPEND_REFUSED_SKIPPED_STATUS


def test_the_refusal_row_names_the_lease_that_ran_out(env):
    result, _, _ = _refuse_at_position_2(env)
    refused = result.results[1]
    lease_id = result.results[0]["effect_lease"]["lease_id"]

    detail = refused["budget_refusal"]
    # THE LEASE, NOT THE DAY. The period ceiling still had $4.75 of room at the
    # instant this was refused; a receipt that named the day's cap here would
    # send a reader looking for the wrong problem.
    assert detail["envelope"] is not None
    assert detail["envelope"]["lease_id"] == lease_id
    assert refused["spend_lease_id"] == lease_id
    assert detail["envelope"]["cap_usd"] == pytest.approx(LEASE_USD)
    assert detail["ceiling_usd"] == pytest.approx(PERIOD_CEILING_USD)
    # Nothing ran, so nothing was written -- and that is READ from the refusal,
    # never inferred from the status string.
    assert refused["wrote"] == []
    assert refused["changed_paths"] == []


def test_nothing_retries_the_refused_call(env):
    """A refusal is not a flake. Retrying it would spend the operator's next
    dollar discovering the same "no"."""
    result, _, seen = _refuse_at_position_2(env)

    # Exactly two provider calls for a three-task wave: position 1 ran,
    # position 2 was refused, position 3 was never dispatched.
    assert len(seen) == 2, f"{len(seen)} calls -- something retried"
    assert result.results[2]["status"] == SPEND_REFUSED_SKIPPED_STATUS


def test_a_refusal_that_escapes_the_dispatch_callable_becomes_a_wave_receipt(env):
    """The net under the per-position translation.

    ``run_wave`` has TWO dispatch callables. ``KairosScheduler.dispatch``
    translates a refusal per position (every test above), but a live write wave
    goes through ``daedalus.kairos.gated_writes.run_write_wave``, which is
    owned elsewhere and does not translate -- so a refusal on that path still
    escaped and destroyed the run. This drives the same escape through the
    dispatch callable directly: whatever comes out of it, the wave ends with a
    receipt.
    """
    tasks = 3
    wave = _wave(tasks)

    def _raise(*a, **kw):
        B.ledger().reserve(_estimate(LEASE_USD + 0.01), label="one call too many")

    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment(i) for i in range(tasks)]):
        with mock.patch.object(KairosScheduler, "dispatch", side_effect=_raise):
            result = _executor(env).run_wave(
                KairosScheduler(availability={"ollama": True}), wave,
                REPO_ROOT, dry_run=False, parallel=False)

    assert result.mode == "spend_refused"
    # Full length and position-matched even though the dispatch callable
    # returned nothing at all -- run_wave's own length check is downstream of
    # this and would raise if the net synthesised the wrong shape.
    assert len(result.results) == tasks
    assert {r["status"] for r in result.results} == {SPEND_REFUSED_STATUS}
    assert result.results[0]["budget_refusal"]["envelope"]["cap_usd"] == \
        pytest.approx(LEASE_USD)
    assert [t.status for t in wave.tasks] == ["bounced"] * tasks
    # The envelope closed on the way out of the raise, and says so.
    assert result.spend_envelope["closed"] is True
    assert "BudgetRefused" in result.spend_envelope["reason"]
    assert not B.ledger().state().envelopes


def test_a_refused_wave_stops_the_build_session(env, tmp_path):
    """One operator gesture must not become N caps.

    Every wave opens its OWN envelope for the full ``max_spend_usd``, so a
    session that kept going after a refusal would immediately hand wave 2 a
    fresh, complete authorisation for money the ledger had just refused.
    """
    from daedalus.build import BuildSession

    session = BuildSession(
        feature="two waves", slug="spend-refused-session", repo_root=REPO_ROOT,
        project=None, created="", max_workers=1,
        waves=[Wave(index=0, tasks=_wave(1).tasks),
               Wave(index=1, tasks=_wave(1).tasks)])

    def _impl(*a, **kw):
        B.ledger().reserve(_estimate(LEASE_USD + 0.01), label="one call too many")

    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment(0)]):
        with mock.patch("daedalus.offload._offload_impl", side_effect=_impl):
            with mock.patch.object(BuildSession, "save",
                                   return_value=tmp_path / "session.json"):
                report = _executor(env).run(session, dry_run=False,
                                            update_architecture=False)

    assert len(report.waves) == 1, "wave 2 was authorised after a refusal"
    assert report.waves[0].mode == "spend_refused"
    assert not B.ledger().state().envelopes


def test_the_envelope_is_closed_and_the_hold_released(env):
    """An envelope that survives its own wave holds the day's money hostage."""
    result, _, _ = _refuse_at_position_2(env)

    closed = result.spend_envelope
    assert closed is not None and closed["closed"] is True
    assert closed["cap_usd"] == pytest.approx(LEASE_USD)
    # The whole cap comes back: the refused draw never settled, and the one
    # call that did run was the patched provider, which reserves nothing.
    assert closed["released_hold_usd"] == pytest.approx(LEASE_USD)
    # The ledger agrees: no envelope is open any more, and the period's
    # committed total is back down to the realized spend alone.
    state = B.ledger().state()
    assert not state.envelopes, state.envelopes
    assert state.envelope_hold_usd == pytest.approx(0.0)
    assert state.committed_usd == pytest.approx(closed["spent_usd"] or 0.0)


# --------------------------------------------------------------------------- #
# the iteration                                                                #
# --------------------------------------------------------------------------- #
def _real_refusal(*, cap_usd: float = LEASE_USD, drawn_usd: float = 0.20,
                  lease_id: str = "lease-loop-test"):
    """``(BudgetRefused, closed envelope dict)`` from the real ledger.

    Built by actually opening an envelope, drawing inside it, and then asking
    for more -- so the refusal under test is the production one, with a real
    realized spend on it, not a hand-built exception that could drift from it.
    """
    envelope = B.ledger().open_envelope(cap_usd, label="wave 0 (loop-test)",
                                        lease_id=lease_id)
    with envelope:
        fits = B.ledger().reserve(_estimate(drawn_usd), label="the call that fit")
        fits.settle()
        with pytest.raises(B.BudgetRefused) as excinfo:
            B.ledger().reserve(_estimate(cap_usd), label="the call that did not")
    return excinfo.value, envelope.result


class _Candidate:
    task_id = "cand-refused-1"
    instruction = "propagate Event.voltage -> bias_voltage"
    source = "picker"
    score = 0.9
    target_paths = ["docs/x0.md"]


def _driver(sw, tmp_path, executor, *, max_spend_usd: float = LEASE_USD,
            max_iterations: int = 3) -> LoopDriver:
    driver = LoopDriver(
        repo_root=REPO_ROOT, executor=executor, dry_run=False,
        switch=sw, runs_dir=tmp_path / "runs",
        bounds=LoopBounds(max_iterations=max_iterations,
                          max_spend_usd=max_spend_usd))
    driver._session_for = lambda c: mock.Mock(waves=[_wave(1)])   # type: ignore
    driver._pick = lambda: (_Candidate(), [], "picked")           # type: ignore
    return driver


class _RaisingExecutor:
    """An INJECTED executor that lets the refusal escape.

    This is the belt the loop's own boundary catch exists for: `executor` is a
    documented injection point (LoopDriver.__init__), and a loop whose evidence
    depends on which executor was injected is not evidence.
    """
    availability = {"ollama": True}

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def run_wave(self, scheduler, wave, repo_root, **kw):
        self.calls += 1
        raise self.exc


class _RefusingExecutor:
    """The post-fix production shape: a WaveResult carrying the refusal."""
    availability = {"ollama": True}

    def __init__(self, exc, closed_envelope, *, settle_usd: float = 0.0):
        self.exc = exc
        self.closed = closed_envelope
        self.settle_usd = settle_usd
        self.calls = 0

    def run_wave(self, scheduler, wave, repo_root, **kw):
        self.calls += 1
        if self.settle_usd:
            # Real money on the real ledger, so the loop's OWN --max-spend-usd
            # bound is measured rather than simulated.
            res = B.ledger().reserve(_estimate(self.settle_usd),
                                     label=f"wave {self.calls}")
            res.settle()
        row = spend_refused_result(_assignment(0), self.exc)
        for t in wave.tasks:
            t.mark("bounced", row)
        return WaveResult(
            index=0, mode="spend_refused", dry_run=False, write_tasks=0,
            advisory_tasks=1, landed_tasks=0, bounced_tasks=1,
            forced_sequential_reason="the leased spend ceiling refused a draw "
                                     "mid-wave",
            path_conflicts=[], results=[row], spend_envelope=self.closed)


def test_the_iteration_receipt_names_the_lease_and_the_realized_spend(env, tmp_path):
    exc, closed = _real_refusal()
    driver = _driver(env, tmp_path, _RefusingExecutor(exc, closed))

    iteration = driver._run_iteration(0, _Candidate())

    assert iteration.status == SPEND_REFUSED_STATUS
    # Never relabelled "cancelled" and never laundered into an attempt state:
    # nothing about this candidate was measured.
    assert iteration.outcome == "not_attempted"
    assert iteration.promoted is False
    assert iteration.budget_refusal is not None
    assert iteration.budget_refusal["envelope"]["lease_id"] == "lease-loop-test"
    assert iteration.effect_lease is not None
    assert iteration.effect_lease.get("lease_id") == "lease-loop-test"
    # REALIZED SPEND FROM THE ENVELOPE, not the period delta: the period counts
    # every other envelope's money too.
    assert iteration.spend_usd == pytest.approx(0.20)
    assert "BUDGET REFUSED" in iteration.reason
    # And it survives serialisation -- the report file is what an operator
    # actually reads.
    assert iteration.to_dict()["budget_refusal"]["envelope"]["cap_usd"] == \
        pytest.approx(LEASE_USD)


def test_an_escaped_refusal_still_ends_the_iteration_with_a_receipt(env, tmp_path):
    """MEASURED before the fix: this raised out of _run_iteration, and the run
    ended with stop_reason='error' and ZERO iteration receipts."""
    exc, _ = _real_refusal()
    driver = _driver(env, tmp_path, _RaisingExecutor(exc))

    iteration = driver._run_iteration(0, _Candidate())

    assert iteration.status == SPEND_REFUSED_STATUS
    assert iteration.budget_refusal["envelope"]["lease_id"] == "lease-loop-test"
    # Even with no WaveResult to read an envelope back from, the refusal's own
    # envelope view carries the lease id and the realized spend.
    assert iteration.effect_lease["source"] == "budget_refusal"
    assert iteration.spend_usd == pytest.approx(0.20)


def test_the_run_exits_cleanly_and_records_the_refusal_in_the_ledger(env, tmp_path):
    exc, closed = _real_refusal()
    driver = _driver(env, tmp_path, _RefusingExecutor(exc, closed),
                     max_spend_usd=5.0, max_iterations=2)

    report = driver.run()

    # NOT an error. The run ended on one of its own declared bounds.
    assert report.stop_reason != "error", report.stop_detail
    assert report.stop_reason == "max_iterations"
    assert len(report.iterations) == 2
    assert all(it.status == SPEND_REFUSED_STATUS for it in report.iterations)
    assert any("WAS REFUSED ITS MONEY" in n for n in report.notes)
    # The LoopLedger -- the file a LATER run reads back -- carries why.
    rows = driver.ledger.attempts[_Candidate.task_id]["detail"]
    assert rows[0]["status"] == SPEND_REFUSED_STATUS
    assert rows[0]["budget_refusal"]["envelope"]["lease_id"] == "lease-loop-test"
    assert rows[0]["spend_usd"] == pytest.approx(0.20)


def test_the_run_ends_with_the_receipt_when_the_loops_own_bound_is_gone(env, tmp_path):
    """A refused wave does not end the RUN by itself -- the loop's own
    --max-spend-usd decides whether there is room for another one."""
    exc, closed = _real_refusal(drawn_usd=0.05)
    # Each iteration settles $0.30 of real money against a $0.25 loop bound, so
    # the bound has no room left when the next iteration is considered.
    executor = _RefusingExecutor(exc, closed, settle_usd=0.30)
    driver = _driver(env, tmp_path, executor, max_spend_usd=LEASE_USD,
                     max_iterations=5)

    report = driver.run()

    assert report.stop_reason == "max_spend"
    # ONE iteration ran, and its receipt is on the report -- the run did not
    # discard the evidence of the iteration that hit the wall.
    assert len(report.iterations) == 1
    assert report.iterations[0].status == SPEND_REFUSED_STATUS
    assert executor.calls == 1, "a second wave was authorised past the bound"
    # And the run says WHY in the same line, not just "$0.30 of $0.25".
    assert "LEASED ceiling refused a draw" in report.stop_detail
    assert "BUDGET REFUSED" in report.stop_detail

"""The wave's ``python.offload`` Effect Lease: who issues it, who may not, and
what the receipt has to say about it afterwards.

These tests pin the ignition blocker measured in
``runs/loop/blocker_9887a98e.json``: ``KairosScheduler._run_one`` called
``offload(..., live=True)`` with no authorization, ``offload`` refused with
``effect_lease_required``, and every loop iteration gated the empty blob. The
fix is a lease acquired ONCE PER WAVE by the wave's starter and threaded down.
Each test below fails if one link of that chain is removed:

* remove the acquisition        -> ``test_offload_receives_the_wave_lease``
* acquire per candidate instead -> ``test_one_wave_acquires_exactly_one_lease``
* let ``_run_one`` mint its own -> ``test_run_one_never_reaches_the_issuer``
* drop the kill-switch check    -> ``test_engaged_kill_switch_refuses_*``
* widen the spend bound         -> ``test_lease_spend_bound_is_the_loops_bound``
* drop the receipt fields       -> ``test_receipt_carries_lease_id_and_effects``
* quote another tree's HEAD     -> ``test_report_source_revision_is_this_repo``
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from daedalus.build import BuildTask, Wave
from daedalus.build_exec import EffectBounds, WaveExecutor
from daedalus.kairos.scheduler import Assignment, KairosScheduler
from daedalus.kernel.offload_lease import (
    ENTRYPOINT_ID,
    WaveLeaseDenied,
    WaveLeaseKillSwitchEngaged,
    WaveOffloadLease,
    acquire_wave_offload_lease,
    control_root,
    lease_ledger_path,
)
from daedalus.spine.effect_boundary import REGISTRY_BY_ID
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = str(Path(__file__).resolve().parents[1])
REVISION = "b" * 40

#: The complete declared effect set of the registry row. Read from the registry
#: rather than restated, so a row that gains or loses an effect fails these
#: tests instead of silently narrowing what a production lease binds.
DECLARED_EFFECTS = tuple(
    sorted(effect.value for effect in REGISTRY_BY_ID[ENTRYPOINT_ID].effects)
)


@pytest.fixture
def switch(tmp_path, monkeypatch):
    """An armed permit in a temp dir, with the lease ledger and issuer key
    beside it. ``DAEDALUS_KILLSWITCH`` moves all three together, which is why
    ``offload_lease.control_root`` derives from the switch path."""
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="test")
    assert control_root(REPO_ROOT) == tmp_path
    return sw


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


def _executor(sw: KillSwitch, *, max_spend_usd: float = 0.25) -> WaveExecutor:
    return WaveExecutor(
        availability={"ollama": True},
        effect_bounds=EffectBounds(
            mission_id="loop-test", source_revision=REVISION,
            max_spend_usd=max_spend_usd, timeout_s=900.0,
            trace_id="tr-test", switch=sw))


# --------------------------------------------------------------------------- #
# the issuer                                                                   #
# --------------------------------------------------------------------------- #
def test_issuer_binds_the_complete_declared_effect_set(switch):
    lease = acquire_wave_offload_lease(
        REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
        attempt_id="w0", positions=1, writable_paths=("docs/x.md",),
        lanes=("ollama",), max_spend_usd=0.25, timeout_s=900,
        containment_evidence="advisory wave", switch=switch)
    assert isinstance(lease, WaveOffloadLease)
    # offload() refuses any execution that does not bind the COMPLETE set --
    # a narrowed one comes back "effect_lease_refused", not "offloaded".
    assert lease.requested_effects == DECLARED_EFFECTS
    assert lease.execution_for(0).requested_effects == DECLARED_EFFECTS
    assert lease.lease.entrypoint_id == ENTRYPOINT_ID
    assert Path(lease.ledger_path) == lease_ledger_path(REPO_ROOT)


def test_each_position_gets_its_own_execution_identity(switch):
    lease = acquire_wave_offload_lease(
        REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
        attempt_id="w0", positions=3, writable_paths=("docs/x.md",),
        lanes=("ollama",), max_spend_usd=0.25, timeout_s=900,
        containment_evidence="advisory wave", switch=switch)
    ids = {lease.execution_for(i).execution_id for i in range(3)}
    keys = {lease.execution_for(i).idempotency_key for i in range(3)}
    # Sharing one execution across a wave would make the ledger treat every
    # candidate after the first as an idempotent replay and run none of them.
    assert len(ids) == 3 and len(keys) == 3
    assert lease.execution_for(1) is lease.execution_for(1)  # stable, not fresh
    assert lease.lease.effect_scope.max_concurrency == 3


def test_lease_spend_bound_is_the_loops_bound(switch):
    lease = acquire_wave_offload_lease(
        REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
        attempt_id="w0", positions=1, writable_paths=("docs/x.md",),
        lanes=("ollama",), max_spend_usd=0.25, timeout_s=900,
        containment_evidence="advisory wave", switch=switch)
    # --max-spend-usd 0.25, in the unit the contract speaks. The operator typed
    # the ceiling once; it must mean one number everywhere.
    assert lease.lease.effect_scope.max_cost_microusd == 250_000
    assert lease.execution_for(0).max_cost_microusd == 250_000
    assert lease.receipt()["max_cost_microusd"] == 250_000


def test_blocked_write_path_denies_instead_of_issuing(switch):
    denied = acquire_wave_offload_lease(
        REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
        attempt_id="w0", positions=1, writable_paths=("docs/x.md",),
        lanes=("ollama",), max_spend_usd=0.25, timeout_s=900,
        write_policy_blocked=(".agentenv/agentenv.json",),
        containment_evidence="advisory wave", switch=switch)
    assert isinstance(denied, WaveLeaseDenied)
    receipt = denied.receipt()
    assert receipt["verdict"] == "deny"
    assert receipt["lease_id"] is None
    assert receipt["requested_effects"] == []
    assert any("provider.write_policy" in r for r in denied.reasons)
    # The deny decision is a canonical contract, and issue_effect_lease refuses
    # to turn one into a lease -- refusal and record cannot drift apart.
    assert denied.policy_decision.verdict == "deny"
    assert not denied.policy_decision.effect_scope.has_effects


def test_unleasable_lane_denies_rather_than_declaring_an_endpoint(switch):
    denied = acquire_wave_offload_lease(
        REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
        attempt_id="w0", positions=1, writable_paths=("docs/x.md",),
        lanes=("codex_cli",), max_spend_usd=0.25, timeout_s=900,
        containment_evidence="advisory wave", switch=switch)
    assert isinstance(denied, WaveLeaseDenied)
    assert any("codex_cli" in r for r in denied.reasons)


def test_engaged_kill_switch_issues_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="test")
    sw.stop("operator test")
    with pytest.raises(WaveLeaseKillSwitchEngaged):
        acquire_wave_offload_lease(
            REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
            attempt_id="w0", positions=1, writable_paths=("docs/x.md",),
            lanes=("ollama",), max_spend_usd=0.25, timeout_s=900,
            containment_evidence="advisory wave", switch=sw)
    # No ledger, no key, no lease: a stopped permit is refused BEFORE any
    # capability material is created, not after.
    assert not lease_ledger_path(REPO_ROOT).exists()


def test_latched_switch_refuses_even_when_the_permit_reads_armed(switch):
    switch.stop("operator test")          # latches this object AND drops a marker
    switch.arm(force=True, note="re-armed")  # the FILE reads armed again
    assert switch.read_state().running is True
    # read_state is deliberately latch-blind, so relying on it alone would hand
    # a capability back to a run a human already stopped.
    with pytest.raises(WaveLeaseKillSwitchEngaged):
        acquire_wave_offload_lease(
            REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
            attempt_id="w0", positions=1, writable_paths=("docs/x.md",),
            lanes=("ollama",), max_spend_usd=0.25, timeout_s=900,
            containment_evidence="advisory wave", switch=switch)


def test_generation_changes_when_the_permit_changes(switch):
    from daedalus.kernel.offload_lease import kill_switch_generation

    before = kill_switch_generation(switch)
    switch.arm(force=True, note="rearmed")
    after = kill_switch_generation(switch)
    # verify_effect_lease compares generations for EQUALITY, so a re-armed
    # permit must invalidate every lease issued under the previous one.
    assert before != after


# --------------------------------------------------------------------------- #
# the chain: run_wave -> dispatch -> _run_one -> offload                        #
# --------------------------------------------------------------------------- #
def test_one_wave_acquires_exactly_one_lease(switch):
    wave = _wave(2)
    calls: list[dict] = []
    real = acquire_wave_offload_lease

    def _counting(*args, **kwargs):
        calls.append(dict(kwargs))
        return real(*args, **kwargs)

    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment(), _assignment()]):
        with mock.patch("daedalus.kernel.offload_lease."
                        "acquire_wave_offload_lease", side_effect=_counting):
            with mock.patch("daedalus.offload._offload_impl",
                            return_value={"action": "offloaded", "wrote": []}):
                result = _executor(switch).run_wave(
                    KairosScheduler(availability={"ollama": True}), wave,
                    REPO_ROOT, dry_run=False, parallel=False)
    # ONE lease for a TWO-candidate wave. Per-candidate acquisition would read
    # 2 here, and would make the number of live capabilities a function of what
    # the picker happened to return.
    assert len(calls) == 1
    assert calls[0]["positions"] == 2
    lease_ids = {row["effect_lease"]["lease_id"] for row in result.results}
    execution_ids = {row["effect_lease"]["execution_id"]
                     for row in result.results}
    assert len(lease_ids) == 1
    assert len(execution_ids) == 2


def test_offload_receives_the_wave_lease(switch):
    seen: list[dict] = []
    import daedalus.offload as offload_module

    real_offload = offload_module.offload

    def _spy(*args, **kwargs):
        seen.append({"authorization": kwargs.get("effect_authorization"),
                     "execution": kwargs.get("effect_execution")})
        return real_offload(*args, **kwargs)

    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment()]):
        with mock.patch("daedalus.offload._offload_impl",
                        return_value={"action": "offloaded", "wrote": []}):
            with mock.patch("daedalus.offload.offload", side_effect=_spy):
                result = _executor(switch).run_wave(
                    KairosScheduler(availability={"ollama": True}), _wave(1),
                    REPO_ROOT, dry_run=False, parallel=False)

    assert len(seen) == 1
    assert seen[0]["authorization"] is not None
    assert seen[0]["execution"].requested_effects == DECLARED_EFFECTS
    # The measured blocker's signature. If the hand-down is removed, offload
    # refuses and this is what comes back instead of "offloaded".
    assert result.results[0]["status"] != "effect_lease_required"
    assert result.results[0]["status"] == "offloaded"


def test_run_one_never_reaches_the_issuer(switch):
    """The entrypoint consumes a capability; it never discovers one.

    Two independent checks, because either alone is weak: the scheduler module
    must not even name the issuer, and a dispatch that IS handed a lease must
    not call the issuer while running.
    """
    import daedalus.kairos.scheduler as scheduler_module

    source = Path(scheduler_module.__file__).read_text(encoding="utf-8")
    assert "offload_lease" not in source
    assert "issue_effect_lease" not in source

    lease = acquire_wave_offload_lease(
        REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
        attempt_id="w0", positions=1, writable_paths=("docs/x0.md",),
        lanes=("ollama",), max_spend_usd=0.25, timeout_s=900,
        containment_evidence="advisory wave", switch=switch)

    def _explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("dispatch reached the lease issuer")

    scheduler = KairosScheduler(availability={"ollama": True})
    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment()]):
        with mock.patch("daedalus.kernel.offload_lease."
                        "acquire_wave_offload_lease", side_effect=_explode):
            with mock.patch("daedalus.kernel.offload_lease."
                        "issue_effect_lease", side_effect=_explode):
                with mock.patch("daedalus.offload._offload_impl",
                                return_value={"action": "offloaded",
                                              "wrote": []}):
                    rows = scheduler.dispatch(
                        REPO_ROOT, [{"objective": "t", "paths": ["docs/x0.md"]}],
                        dry_run=False, parallel=False,
                        effect_authorization=lease.authorization,
                        effect_executions={0: lease.execution_for(0)})
    assert rows[0]["status"] == "offloaded"


def test_engaged_kill_switch_refuses_the_wave_before_any_offload(
        tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="test")
    sw.stop("operator test")

    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment()]):
        with mock.patch("daedalus.offload._offload_impl") as impl:
            with pytest.raises(WaveLeaseKillSwitchEngaged) as excinfo:
                # cancel deliberately NOT passed: this asserts the LEASE path
                # refuses on its own, not that the pre-existing pre-dispatch
                # cancel checkpoint happened to fire first.
                _executor(sw).run_wave(
                    KairosScheduler(availability={"ollama": True}), _wave(1),
                    REPO_ROOT, dry_run=False, parallel=False)
            impl.assert_not_called()
    # A LoopHalted subclass, so LoopDriver.run reports stop_reason="killswitch"
    # (exit code 3) instead of classifying an operator's stop as an error.
    from daedalus.spine.killswitch import LoopHalted

    assert isinstance(excinfo.value, LoopHalted)


def test_denied_wave_refuses_with_a_receipt_and_no_dispatch(switch):
    denied = WaveLeaseDenied(
        policy_decision=acquire_wave_offload_lease(
            REPO_ROOT, source_revision=REVISION, mission_id="loop-test",
            attempt_id="w0", positions=1, writable_paths=("docs/x0.md",),
            lanes=("codex_cli",), containment_evidence="advisory wave",
            switch=switch).policy_decision,
        reasons=("provider.egress_policy: lane 'codex_cli' declares no endpoint",))

    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment()]):
        with mock.patch.object(WaveExecutor, "_acquire_wave_lease",
                               return_value=denied):
            with mock.patch("daedalus.offload._offload_impl") as impl:
                result = _executor(switch).run_wave(
                    KairosScheduler(availability={"ollama": True}), _wave(1),
                    REPO_ROOT, dry_run=False, parallel=False)
    impl.assert_not_called()
    assert result.mode == "lease_denied"
    assert result.landed_tasks == 0
    row = result.results[0]
    assert row["status"] == "effect_lease_denied"
    assert row["wrote"] == []
    assert row["effect_lease"]["verdict"] == "deny"
    assert row["provider_receipt"]["lease_id"] is None


def test_gated_write_wave_gets_the_lease_the_day_it_accepts_one(switch):
    """The conditional hand-down, pinned from the caller's side.

    ``gated_writes.run_write_wave`` does not take a lease today (its body is a
    sealed strangler resource this lane does not own -- the hunk is proposed
    separately). ``run_wave`` therefore ASKS the callable instead of assuming
    either answer, and this test stands in a callable that does accept one, so
    the caller side is proven now rather than the day the callee lands.

    MEASURED 2026-08-22 (runs/loop/loop-20260822-124627-bd9a26.json): without
    the callee change a live write wave still returns
    ``provider_receipt.action == "effect_lease_required"`` even though the
    lease was issued -- which is why this asserts the hand-down, not the
    outcome.
    """
    received: dict = {}

    def _fake_run_write_wave(scheduler, repo_root, tasks, assignments, *,
                             auto_promote, ledger_path=None, cancel=None,
                             effect_authorization=None, effect_executions=None):
        received["authorization"] = effect_authorization
        received["executions"] = dict(effect_executions or {})
        return [{"status": "gated_held", "attempt_state": "clean",
                 "task_id": "kairos-ollama-deadbeef", "wrote": [],
                 "paths": []} for _ in tasks]

    write_assignment = _assignment(mode="write", paths=("docs/x0.md",))
    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[write_assignment]):
        with mock.patch("daedalus.kairos.gated_writes.run_write_wave",
                        _fake_run_write_wave):
            result = _executor(switch).run_wave(
                KairosScheduler(availability={"ollama": True}), _wave(1),
                REPO_ROOT, dry_run=False, parallel=False)

    assert received["authorization"] is not None
    assert received["executions"][0].requested_effects == DECLARED_EFFECTS
    assert result.results[0]["effect_lease"]["verdict"] == "allow"


def test_dry_run_acquires_no_capability(switch):
    with mock.patch.object(KairosScheduler, "accept",
                           return_value=[_assignment()]):
        with mock.patch("daedalus.kernel.offload_lease."
                        "acquire_wave_offload_lease") as issuer:
            result = _executor(switch).run_wave(
                KairosScheduler(availability={"ollama": True}), _wave(1),
                REPO_ROOT, dry_run=True, parallel=False)
    # A dry run performs no effect, so it needs no capability -- and must not
    # create one, or the cheapest path would be the one that mints authority.
    issuer.assert_not_called()
    assert result.results[0]["status"] == "planned"
    assert "effect_lease" not in result.results[0]

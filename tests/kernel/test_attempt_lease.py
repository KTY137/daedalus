"""The second door becomes leasable: ``python.attempt`` through the issuer.

The measured Gate-0 wall (B5 handoff, 2026-08-23): exactly one registry row --
``python.offload`` -- could hold a lease, and it declares zero write surfaces.
``issuable_row`` named two reasons for refusing ``python.attempt``: the issuer
had no in-process implementation of ``containment.worktree`` and
``spine.intent_ledger``, and the row named no ``provider.write_policy`` for the
write scope to be drawn from. These tests pin the removal of that wall and,
just as deliberately, what still refuses: an attempt lease exists only for an
attempt whose INTENDED row is already durable.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from daedalus.kernel.offload_lease import (          # noqa: E402
    ATTEMPT_ENTRYPOINT_ID,
    WaveLeaseDenied,
    WaveOffloadLease,
    acquire_attempt_lease,
    issuable_row,
)
from daedalus.sensitivity import Policy              # noqa: E402
from daedalus.spine.killswitch import KillSwitch, control_root  # noqa: E402
from daedalus.spine.ledger import SpineLedger        # noqa: E402

REVISION = "b" * 40
DOCS_POLICY = Policy(write_allow=("docs/",))


@pytest.fixture
def repo(tmp_path):
    """A real git repo with its own spine ledger and a fresh control root.

    Isolation by repo identity (the test_loop pattern): a temp repo hashes to
    a control-root digest nothing was ever written under. The control root the
    issuer creates is removed on cleanup.
    """
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo_path, check=True,
                       capture_output=True)

    git("init")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.invalid")
    (repo_path / "docs").mkdir()
    (repo_path / "docs" / "x.md").write_text("x\n", encoding="utf-8")
    git("add", "docs/x.md")
    git("commit", "-m", "seed")
    yield repo_path
    import shutil
    shutil.rmtree(control_root(repo_path), ignore_errors=True)


@pytest.fixture
def armed_switch(repo):
    sw = KillSwitch(repo_root=repo)
    sw.arm(force=True)
    yield sw
    sw.stop("test teardown")


def _intend(repo: Path, effect_key: str) -> SpineLedger:
    led = SpineLedger(repo / "runs" / "spine" / "spine.sqlite3")
    led.record_intent("attempt.worktree", {"why": "test"}, effect_key=effect_key)
    return led


def _acquire(repo, **overrides):
    kwargs = dict(
        source_revision=REVISION,
        mission_id="m-test",
        attempt_id="a-test",
        effect_key="daedalus-attempt-test-branch",
        writable_paths=("docs/x.md",),
        write_policy=DOCS_POLICY,
        contained=True,
        containment_evidence="TaskAttempt worktree, test",
    )
    kwargs.update(overrides)
    return acquire_attempt_lease(repo, **kwargs)


# --------------------------------------------------------------------------- #
# the wall is gone -- and the row still cannot be chosen by the caller         #
# --------------------------------------------------------------------------- #
def test_the_attempt_row_is_issuable_by_the_registry_not_by_assertion():
    spec, reasons = issuable_row(ATTEMPT_ENTRYPOINT_ID)
    assert reasons == ()
    assert spec is not None and spec.id == ATTEMPT_ENTRYPOINT_ID


def test_the_wrapper_pins_the_row_and_demands_the_effect_key(repo):
    with pytest.raises(TypeError, match="python.attempt only"):
        acquire_attempt_lease(repo, entrypoint_id="python.offload")
    with pytest.raises(TypeError, match="effect_key"):
        _acquire(repo, effect_key=None)


# --------------------------------------------------------------------------- #
# the grant, over a real INTENDED row                                          #
# --------------------------------------------------------------------------- #
def test_an_attempt_with_a_durable_intent_is_leased(repo, armed_switch):
    led = _intend(repo, "daedalus-attempt-test-branch")
    try:
        lease = _acquire(repo, switch=armed_switch)
        assert isinstance(lease, WaveOffloadLease), getattr(lease, "reasons", None)
        by_name = {d.contract: d
                   for d in lease.authorization.guard_decisions}
        assert by_name["spine.intent_ledger"].allowed is True
        assert "INTENDED" in by_name["spine.intent_ledger"].evidence
        assert by_name["containment.worktree"].allowed is True
        assert by_name["provider.write_policy"].allowed is True
    finally:
        led.close()


def test_no_ledger_no_lease_but_the_lease_may_precede_the_intent(repo,
                                                                  armed_switch):
    """Two halves of the issuance-time meaning of spine.intent_ledger. Without
    a durable attempt ledger the intent has nowhere to land and the lease is
    refused. With the ledger present and NO prior row for the effect_key, the
    lease is GRANTED: TaskAttempt.run records the intent itself, so in the
    consumes-never-discovers flow the capability legitimately precedes the
    intent (measured circularity 2026-08-24: requiring the row at issuance
    made the attempt door unleasable by construction)."""
    denied = _acquire(repo, switch=armed_switch)
    assert isinstance(denied, WaveLeaseDenied)
    assert any("no attempt ledger exists" in r for r in denied.reasons)

    led = _intend(repo, "some-other-branch")
    try:
        lease = _acquire(repo, switch=armed_switch)
        assert isinstance(lease, WaveOffloadLease)
        by_name = {d.contract: d
                   for d in lease.authorization.guard_decisions}
        assert by_name["spine.intent_ledger"].allowed is True
        assert "precedes the intent" in by_name["spine.intent_ledger"].evidence
    finally:
        led.close()


def test_a_resolved_intent_is_an_effect_that_already_happened(repo, armed_switch):
    led = _intend(repo, "daedalus-attempt-test-branch")
    try:
        intent = led.open_intents()[0]
        led.mark_failed(intent.id, "closed before the lease was asked for")
        denied = _acquire(repo, switch=armed_switch)
        assert isinstance(denied, WaveLeaseDenied)
        assert any("already resolved" in r for r in denied.reasons)
    finally:
        led.close()


# --------------------------------------------------------------------------- #
# the wiring: TaskAttempt consumes the lease it was handed                     #
# --------------------------------------------------------------------------- #
def _writing_runner(rel: str, payload: str = "leased\n"):
    def runner(ctx):
        target = Path(ctx.worktree) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
        return {"wrote": [rel]}
    return runner


def _passing_gate():
    from daedalus.spine.attempt import GateResult

    def gate(ctx):
        return GateResult(passed=True, name="unit-gate", command=())
    return gate


def test_a_leased_attempt_begins_before_the_worktree_and_terminalises(
        repo, armed_switch, tmp_path, monkeypatch):
    """Commit 4's wiring, end to end. The caller acquires (consumes, never
    discovers), run() begins the execution BEFORE `git worktree add -b` writes
    the branch ref, and the terminal outcome lands in the effect ledger and on
    the result -- COMPLETED even though only the gate's verdict, not the
    attempt's success, is the payload."""
    from daedalus.spine.attempt import TaskAttempt, TaskSpec
    from daedalus.kernel.effect_replay import inspect_effect_execution

    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    task = TaskSpec(task_id="leased-attempt", instruction="probe",
                    target_paths=("docs/probe.md",))
    ledger_path = repo / "runs" / "spine" / "spine.sqlite3"
    SpineLedger(ledger_path).close()      # the durable ground exists up front
    attempt = TaskAttempt(task, runner=_writing_runner("docs/probe.md"),
                          gate=_passing_gate(), repo_root=repo,
                          ledger_path=ledger_path)
    lease = _acquire(repo, switch=armed_switch, effect_key=attempt.branch,
                     attempt_id=attempt.branch,
                     writable_paths=("docs/probe.md",))
    assert isinstance(lease, WaveOffloadLease), getattr(lease, "reasons", None)
    attempt._attempt_lease = lease

    result = attempt.run()

    assert result.state == "clean", result.error
    assert result.lease_id == lease.lease_id
    assert result.lease_outcome == "COMPLETED"
    assert result.lease_error is None
    execution = lease.issued_execution(1)
    assert execution is not None
    snapshot = inspect_effect_execution(lease.authorization, execution)
    assert snapshot is not None, "the execution left no durable state"
    assert str(getattr(snapshot, "state", "")).upper() in ("TERMINAL", "COMPLETED", "FINISHED") or getattr(snapshot, "terminal_receipt", None) is not None, (
        f"the execution did not terminalise: {snapshot}")


def test_the_same_lease_cannot_run_a_second_attempt(repo, armed_switch,
                                                    tmp_path, monkeypatch):
    """One lease, one execution identity, one begin. A second attempt handed
    the same lease is refused as lease_refused BEFORE any worktree exists --
    its own state, so the receipt does not claim a worktree failure that
    never happened."""
    from daedalus.kairos.worktree import GitWorktreeManager
    from daedalus.spine.attempt import STATE_LEASE_REFUSED, TaskAttempt, TaskSpec
    from daedalus.spine.receipts import AttemptContractSet

    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    ledger_path = repo / "runs" / "spine" / "spine.sqlite3"
    SpineLedger(ledger_path).close()      # the durable ground exists up front
    task = TaskSpec(task_id="leased-attempt", instruction="probe",
                    target_paths=("docs/probe.md",))
    first = TaskAttempt(task, runner=_writing_runner("docs/probe.md"),
                        gate=_passing_gate(), repo_root=repo,
                        ledger_path=ledger_path)
    lease = _acquire(repo, switch=armed_switch, effect_key=first.branch,
                     attempt_id=first.branch,
                     writable_paths=("docs/probe.md",))
    assert isinstance(lease, WaveOffloadLease)
    first._attempt_lease = lease
    assert first.run().state == "clean"

    runner_calls = []
    worktree_calls = []

    def forbidden_runner(ctx):
        runner_calls.append(ctx)
        raise AssertionError("a refused replay reached the runner")

    def forbidden_worktree(*args, **kwargs):
        worktree_calls.append((args, kwargs))
        raise AssertionError("a refused replay created a worktree")

    monkeypatch.setattr(GitWorktreeManager, "create_worktree", forbidden_worktree)
    second = TaskAttempt(task, runner=forbidden_runner,
                         gate=_passing_gate(), repo_root=repo,
                         ledger_path=ledger_path)
    second._attempt_lease = lease
    result = second.run()
    assert result.state == STATE_LEASE_REFUSED
    assert "refused to begin" in (result.error or "")
    assert result.lease_outcome is None
    assert runner_calls == []
    assert worktree_calls == []
    contracts = AttemptContractSet.from_dict(result.contracts)
    assert contracts.policy is not None
    assert contracts.policy.verdict == "deny"
    assert contracts.policy.effect_scope.read_only is True
    assert contracts.policy.effect_scope.has_effects is False
    assert contracts.policy.effect_scope.writable_paths == ()
    assert contracts.attempt is None
    assert contracts.evidence is None
    assert contracts.receipt is None
    # the second attempt's intent is resolved, not leaked open:
    led = SpineLedger(ledger_path)
    try:
        assert led.open_intents() == []
    finally:
        led.close()

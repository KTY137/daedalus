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


def test_no_intent_no_lease(repo, armed_switch):
    """The guard the issuer runs itself: an attempt nobody intends -- no ledger,
    no row, a resolved row -- is refused with the reason named."""
    denied = _acquire(repo, switch=armed_switch)
    assert isinstance(denied, WaveLeaseDenied)
    assert any("no attempt ledger exists" in r for r in denied.reasons)

    led = _intend(repo, "some-other-branch")
    try:
        denied = _acquire(repo, switch=armed_switch)
        assert isinstance(denied, WaveLeaseDenied)
        assert any("no intent" in r and "effect_key" in r for r in denied.reasons)
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

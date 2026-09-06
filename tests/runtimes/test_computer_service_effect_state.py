"""Pins the post-``external_started`` exception classification in
``ComputerService.execute`` (daedalus/runtimes/computer.py).

``provably_no_effect`` is true ONLY for a ``ComputerRefused`` whose
``effect_state`` is ``None``/``"none"``, or a ``KeyboardInterrupt`` that
carries ``effect_state == "none"`` (the file adapter's own
``ComputerFileInterrupted``). Only then is the started effect finished as
``CANCELLED`` and the state reported ``"blocked"``. Every other exception
after ``external_started`` -- a bare ``KeyboardInterrupt``, an
"uncertain"-tagged interruption or refusal, or an unrelated exception -- must
leave the STARTED receipt untouched (no terminal record at all, so replay
still sees ``STARTED``) and report ``"reconciliation_required"``.

No case here reaches the real file adapter: ``service._dispatch`` is
monkeypatched to raise immediately, so none of these cases performs a host
effect. That is asserted directly (the target directory is never created).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, FILE_TOOLS, policy_path
from daedalus.runtimes import computer as subject
from daedalus.runtimes.computer_files import ComputerFileEffectUncertain, ComputerFileInterrupted
from daedalus.spine import killswitch


@pytest.fixture
def configured(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    authority = tmp_path / "authority"
    authority.mkdir()
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    policy = ComputerPolicy(workspace=workspace, tools=FILE_TOOLS)
    path = policy_path(authority)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=authority, sweep_managed=False)
    assert switch.arm(note="isolated computer effect-state acceptance fixture").running
    service = subject.ComputerService(authority)
    grants = []
    real_acquire = subject.acquire_effect_lease

    def acquire(*args, **kwargs):
        result = real_acquire(*args, **kwargs)
        grants.append(result)
        return result

    monkeypatch.setattr(subject, "acquire_effect_lease", acquire)
    yield service, workspace, grants
    service.close()


def run(service, tool, args, attempt):
    return service.execute(tool, args, mission_id="computer-effect-state-fixture", attempt_id=attempt)


def terminal_states(service) -> list[str]:
    """Every ``terminal_state`` retained under this service's evidence root.

    Empty means no execution was ever finished -- the durable ledger still
    shows the started effect as ``STARTED``, which is the fact under test for
    the ``reconciliation_required`` cases: nothing here rewrites that record
    as ``CANCELLED``.
    """
    directory = service.control / "computer-effect-evidence" / "lease-terminal"
    if not directory.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8"))["terminal_state"] for p in directory.glob("*.json")]


def raiser(exc):
    def _raise(tool, args):
        raise exc
    return _raise


def test_bare_keyboard_interrupt_is_reconciliation_required_with_started_kept(configured, monkeypatch):
    service, workspace, grants = configured
    monkeypatch.setattr(service, "_dispatch", raiser(KeyboardInterrupt()))
    result = run(service, "file.mkdir", {"path": "folder"}, "kbi-bare")
    assert result["state"] == "reconciliation_required", result
    assert result["error_type"] == "KeyboardInterrupt"
    # No terminal record was ever written: the started effect stays STARTED,
    # never rewritten to CANCELLED.
    assert terminal_states(service) == []
    assert not (workspace / "folder").exists()
    assert len(grants) == 1


def test_typed_interrupted_with_effect_state_none_is_blocked_and_cancelled(configured, monkeypatch):
    service, workspace, grants = configured
    monkeypatch.setattr(
        service, "_dispatch",
        raiser(ComputerFileInterrupted("interrupted before any effect", effect_state="none")),
    )
    result = run(service, "file.mkdir", {"path": "folder"}, "kbi-none")
    assert result["state"] == "blocked", result
    assert result["error_type"] == "ComputerFileInterrupted"
    assert terminal_states(service) == ["cancelled"]
    assert not (workspace / "folder").exists()
    assert len(grants) == 1


def test_typed_interrupted_with_effect_state_uncertain_is_reconciliation_required(configured, monkeypatch):
    service, workspace, grants = configured
    monkeypatch.setattr(
        service, "_dispatch",
        raiser(ComputerFileInterrupted(
            "interrupted; final state requires reconciliation",
            effect_state="uncertain", recovery_paths=("folder",),
        )),
    )
    result = run(service, "file.mkdir", {"path": "folder"}, "kbi-uncertain")
    assert result["state"] == "reconciliation_required", result
    assert result["error_type"] == "ComputerFileInterrupted"
    assert terminal_states(service) == []
    assert not (workspace / "folder").exists()
    assert len(grants) == 1


def test_plain_computer_refused_is_blocked(configured, monkeypatch):
    service, workspace, grants = configured
    monkeypatch.setattr(service, "_dispatch", raiser(ComputerRefused("x")))
    result = run(service, "file.mkdir", {"path": "folder"}, "refused-plain")
    assert result["state"] == "blocked", result
    assert result["error_type"] == "ComputerRefused"
    # A plain refusal carries no effect_state at all; the same "no proven
    # effect" rule that types it "blocked" also finishes it CANCELLED.
    assert terminal_states(service) == ["cancelled"]
    assert not (workspace / "folder").exists()
    assert len(grants) == 1


def test_effect_uncertain_refusal_is_reconciliation_required(configured, monkeypatch):
    service, workspace, grants = configured
    monkeypatch.setattr(
        service, "_dispatch",
        raiser(ComputerFileEffectUncertain("x", recovery_paths=("folder",))),
    )
    result = run(service, "file.mkdir", {"path": "folder"}, "refused-uncertain")
    assert result["state"] == "reconciliation_required", result
    assert result["error_type"] == "ComputerFileEffectUncertain"
    assert terminal_states(service) == []
    assert not (workspace / "folder").exists()
    assert len(grants) == 1


def test_unrelated_runtime_error_is_reconciliation_required(configured, monkeypatch):
    service, workspace, grants = configured
    monkeypatch.setattr(service, "_dispatch", raiser(RuntimeError("adapter blew up")))
    result = run(service, "file.mkdir", {"path": "folder"}, "runtime-error")
    assert result["state"] == "reconciliation_required", result
    assert result["error_type"] == "RuntimeError"
    assert terminal_states(service) == []
    assert not (workspace / "folder").exists()
    assert len(grants) == 1


def test_post_dispatch_checkpoint_refusal_is_reconciliation_required(configured, monkeypatch):
    """``check_cancelled()`` runs again right after ``_dispatch`` returns.

    A plain ``ComputerRefused`` there (cancellation requested, deadline
    exceeded, policy digest changed) carries no ``effect_state`` at all --
    exactly like a pre-dispatch refusal -- but the host effect already
    landed (``_dispatch`` already returned a result). The classifier must
    tell the two apart: this is not "provably no effect", so it must report
    ``"reconciliation_required"`` with the STARTED receipt kept, the same as
    any other post-dispatch failure, rather than finishing the effect
    ``CANCELLED`` and reporting ``"blocked"`` as if the mkdir never happened.

    This was G1-IKARUS-25 F1, tracked here as ``xfail(strict=True)`` while
    the fix (a ``dispatched`` flag set after the adapter returns, gating
    ``provably_no_effect``) was landing in a parallel session on this same
    tree. MEASURED 2026-09-05: the fix landed in
    ``daedalus/runtimes/computer.py`` (the ``dispatched`` flag now gates
    ``provably_no_effect``) while this file was being written, so the
    ``xfail`` marker was removed the same session that discovered the landing
    -- an ``xfail(strict=True)`` left in place after its bug is fixed becomes
    a false failure (``XPASS``) instead of a passing regression test.
    """
    service, workspace, grants = configured
    monkeypatch.setattr(service, "_dispatch", lambda tool, args: {"created": True, "path": args["path"]})
    real_check = service.check_cancelled
    calls: list[int] = []

    def check_cancelled():
        calls.append(1)
        if len(calls) >= 3:
            # The pre-admission and pre-dispatch checkpoints (calls 1-2) must
            # pass normally; only the post-dispatch checkpoint (call 3) fires.
            raise ComputerRefused("computer task cancellation requested")
        real_check()

    monkeypatch.setattr(service, "check_cancelled", check_cancelled)
    result = run(service, "file.mkdir", {"path": "folder"}, "post-dispatch-checkpoint")
    assert result["state"] == "reconciliation_required", result
    assert result["error_type"] == "ComputerRefused"
    assert terminal_states(service) == []
    assert not (workspace / "folder").exists()
    assert len(grants) == 1

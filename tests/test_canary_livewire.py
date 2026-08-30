# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The canary's live-wire gate: no vendor lane is called without an explicit opt-in.

WHY THIS FILE EXISTS.  ``daedalus council`` had this hole closed; ``daedalus
canary`` still had it.  The command's own help says every probe is "a small REAL
task ... with a checkable answer", and ``--dry-run`` was the ONLY brake -- an
OPT-OUT, which protects exactly the operator who already knew to type it.

MEASURED BEFORE THE FIX (spawn sentinel, 2026-07-28): a bare
``cli._canary(["--vendors", "anthropic,openai,google", "--quick"])`` launched

    C:\\Users\\nukei\\.local\\bin\\claude.exe -p --output-format ...
    C:\\Users\\nukei\\AppData\\Roaming\\npm\\codex.cmd --ask-for-approval never ...

and appended 3 records to the history file.  Two paid vendor binaries and a disk
write, from an invocation with no flags at all.

HOW THIS FILE TESTS.  By DRIVING THE GATE, never by reading source text -- a test
that greps for a flag name passes on a comment saying the flag does not exist.
The spend is observed where it is real, at the process spawn:
``vendors.ManagedProcess`` is replaced with a sentinel that RECORDS argv and
starts nothing.  So with the gate in place ``spawned == []``, and with the gate
deleted these tests go red -- and verifying that costs nothing, because no vendor
process is ever really started.

The ALLOW side is tested too (``test_live_true_actually_unlocks_dispatch``): a
gate that refused everything would pass every refusal test here while quietly
making the feature dead.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from daedalus import cli
from daedalus.council import canary as C
from daedalus.council import session as S
from daedalus.council import vendors as V


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def spawn_sentinel(monkeypatch):
    """Record every attempt to start a vendor process, and start none.

    ``run_managed`` resolves ``ManagedProcess`` from the vendors module at CALL
    time, so this intercepts the real runner WITHOUT replacing it -- the adapter
    still holds the shipped ``run_managed`` and the gate must therefore still
    classify it as live.  Neutering the runner itself would hand the gate the
    answer it is being tested for.
    """
    attempts: list[list[str]] = []

    def _blocked(argv, **kw):
        attempts.append(list(argv))
        raise OSError("test sentinel: no vendor process may start here")

    monkeypatch.setattr(V, "ManagedProcess", _blocked)
    return attempts


@pytest.fixture
def no_socket(monkeypatch):
    """Fail loudly if anything tries to open a TCP connection.

    The Ollama lane is HTTP, not a subprocess, so the spawn sentinel does not
    cover it.  Without this a regression in the local lane would look green here
    while really talking to the bench across the tailnet.
    """
    import socket

    def _blocked(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("a canary lane opened a socket without --live")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def _reply(content: str = "ok") -> V.VendorReply:
    return V.VendorReply(vendor="fake", actor="canary.fake.fake-1",
                         model="fake-1", status="ok", content=content)


def _fake_lane(vendor: str = "anthropic") -> C.Lane:
    """The shape the offline harness uses: a plain callable, no adapter."""
    return C.Lane(vendor=vendor, model="fake-1", endpoint=f"fake:{vendor}",
                  ask=lambda prompt, timeout_s: _reply())


def _real_lanes(*names: str) -> tuple[C.Lane, ...]:
    return C.default_lanes(list(names) or ["anthropic", "openai", "google"])


# --------------------------------------------------------------------------
# THE CENTRAL TEST: real lanes, no opt-in, nothing reached
# --------------------------------------------------------------------------


def test_run_canary_refuses_real_lanes_without_live(spawn_sentinel, no_socket):
    """The exact call the CLI used to make. It must refuse, and spawn nothing."""
    lanes = _real_lanes("anthropic", "openai", "google")
    # Sanity: these really are the shipped adapters, not stand-ins.
    assert {type(l.adapter).__name__ for l in lanes} == {
        "_CanaryClaude", "_CanaryCodex", "_CanaryAntigravity"}

    with pytest.raises(C.LiveCanaryRefused) as excinfo:
        C.run_canary(lanes, C.probes_for(quick=True), wall_clock_s=5.0)

    # The refusal names the money and the way out, not just "denied".
    message = str(excinfo.value)
    assert "spend real money" in message
    assert "live=True" in message and "--dry-run" in message
    # THE INVARIANT: no vendor process was even attempted.
    assert spawn_sentinel == [], f"a vendor was reached without --live: {spawn_sentinel}"


def test_the_local_lane_is_gated_too(spawn_sentinel, no_socket):
    """`local` is free at the till but it is still egress, and still a call.

    The default Ollama host is the bench on the tailnet, not this machine, so a
    probe sent there HAS left the box.  It is also the one lane the spawn
    sentinel cannot see -- if the gate skipped it, this is the only thing that
    would notice.
    """
    lanes = _real_lanes("local")
    assert len(C.live_egress_lanes(lanes)) == 1
    with pytest.raises(C.LiveCanaryRefused):
        C.run_canary(lanes, C.probes_for(quick=True), wall_clock_s=5.0)


def test_live_true_actually_unlocks_dispatch(spawn_sentinel):
    """The opt-in must be a real switch, not decoration.

    If this passes while the refusal tests also pass, ``live`` is the ONLY thing
    standing between a bare invocation and a bill.  Without this test a gate that
    refused unconditionally would look perfect and the command would be dead.
    """
    lanes = _real_lanes("anthropic", "openai")
    run = C.run_canary(lanes, C.probes_for(quick=True), per_probe_timeout_s=5.0,
                       wall_clock_s=20.0, live=True)

    binaries = {Path(argv[0]).stem.lower() for argv in spawn_sentinel}
    assert binaries == {"claude", "codex"}, (
        f"live=True did not reach the shipped transports: {spawn_sentinel}")
    # The run still completed and reported both lanes honestly.
    assert len(run.results) == 2
    assert {r.vendor for r in run.results} == {"anthropic", "openai"}


def test_run_canary_defaults_live_to_false():
    """A flipped default is the cheapest way to silently reopen this hole."""
    live = inspect.signature(C.run_canary).parameters["live"]
    assert live.default is False
    assert live.kind is inspect.Parameter.KEYWORD_ONLY


def test_refusal_happens_before_anything_is_written(tmp_path, spawn_sentinel, no_socket):
    """Nothing on disk, so there is nothing to clean up after a refusal.

    A refusal that fired after the run had been graded would still be a refusal,
    but a refusal that left a history record claiming lanes were probed would be
    a lie in the file the median comparison is built from.
    """
    history = tmp_path / "history.jsonl"
    with pytest.raises(SystemExit):
        cli._canary(["--vendors", "anthropic,openai", "--history", str(history)])
    assert not history.exists()
    assert spawn_sentinel == []


# --------------------------------------------------------------------------
# the classifier: ONE family, fail-closed, precise enough not to kill the harness
# --------------------------------------------------------------------------


def test_every_default_lane_is_classified_live():
    """All four shipped lanes count as live, including the local one."""
    lanes = C.default_lanes(["anthropic", "openai", "google", "local"])
    assert len(C.live_egress_lanes(lanes)) == 4


def test_the_canary_reuses_the_council_classifier():
    """ONE predicate, not a second family that can drift out of agreement.

    This repo has already spent a night finding five copies of one "is this host
    local" check disagreeing with each other.  Driving the shared function --
    rather than asserting on an import line -- is what makes a re-implementation
    that merely *looks* equivalent fail here.
    """
    assert C.live_egress_seats is S.live_egress_seats
    assert issubclass(C.LiveCanaryRefused, S.LiveCouncilRefused)

    lanes = C.default_lanes(["anthropic", "openai", "google", "local"])
    seats = S.live_egress_seats([l.adapter for l in lanes])
    # Every seat the council would flag is flagged by the canary, verbatim.
    flagged = C.live_egress_lanes(lanes)
    assert len(flagged) == len(seats)
    for seat, line in zip(seats, flagged):
        assert line.endswith(seat)


def test_fake_lanes_need_no_opt_in():
    """The offline harness must never have to ask permission it does not need."""
    lanes = [_fake_lane("anthropic"), _fake_lane("openai")]
    assert C.live_egress_lanes(lanes) == ()
    run = C.run_canary(lanes, C.probes_for(quick=True), wall_clock_s=10.0)
    assert len(run.results) == 2


def test_a_hand_rolled_lane_around_a_real_adapter_is_still_live(no_socket):
    """FAIL-CLOSED: the gate is not satisfied by skipping ``default_lanes``.

    ``Lane(ask=_bind(ClaudeAdapter()))`` has ``adapter=None`` and a bare closure
    for ``ask``.  A gate that only understood the ``adapter`` field would be a
    gate with a documented bypass, so the closure is inspected too.
    """
    adapter = V.ClaudeAdapter()
    sneaky = C.Lane(vendor="anthropic", model="claude", endpoint="cli:claude",
                    ask=C._bind(adapter))
    assert sneaky.adapter is None
    assert len(C.live_egress_lanes([sneaky])) == 1
    with pytest.raises(C.LiveCanaryRefused):
        C.run_canary([sneaky], C.probes_for(quick=True), wall_clock_s=5.0)


def test_a_bound_method_of_a_real_adapter_is_still_live(no_socket):
    """The other way to smuggle an adapter past a field check."""
    adapter = V.CodexAdapter()
    sneaky = C.Lane(vendor="openai", model="codex", endpoint="cli:codex",
                    ask=adapter.ask)
    assert len(C.live_egress_lanes([sneaky])) == 1


def test_a_one_shot_lane_iterator_is_not_drained_by_the_gate():
    """The gate iterates the roster before the scheduler does.

    An iterator would arrive full, be consumed by the check, and reach the rest
    of ``run_canary`` empty -- a canary of no lanes, reported as if it had run.
    """
    run = C.run_canary(iter([_fake_lane("anthropic")]), C.probes_for(quick=True),
                       wall_clock_s=10.0)
    assert len(run.results) == 1


# --------------------------------------------------------------------------
# the CLI: the operator-facing form of the same opt-in
# --------------------------------------------------------------------------


@pytest.fixture
def no_run(monkeypatch):
    """Make any attempt to build lanes or run the canary an outright failure."""
    from daedalus.council import canary as cn

    def _boom(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("the CLI proceeded past the spend gate")

    monkeypatch.setattr(cn, "run_canary", _boom)
    monkeypatch.setattr(cn, "default_lanes", _boom)
    monkeypatch.setattr(cn, "append_history", _boom)


def test_cli_refuses_a_bare_canary_invocation(no_run, capsys):
    """`daedalus canary` used to spawn claude and codex. Now it refuses."""
    with pytest.raises(SystemExit) as excinfo:
        cli._canary([])
    assert excinfo.value.code != 0
    err = capsys.readouterr().err
    assert "--live" in err and "--dry-run" in err


def test_cli_refuses_a_bare_invocation_that_carries_other_flags(no_run, capsys):
    """The gate is on the OPT-IN, not on the argument count.

    `--quick` reads like a safety flag ("just one probe") and is not one: it
    still calls every lane for real, once each.
    """
    with pytest.raises(SystemExit) as excinfo:
        cli._canary(["--quick", "--vendors", "anthropic"])
    assert excinfo.value.code != 0
    assert "--live" in capsys.readouterr().err


def test_cli_refuses_live_and_dry_run_together(no_run, capsys):
    """Ambiguous intent about spending money is refused, not resolved.

    No precedence rule: whichever way it silently resolved, half the operators
    would remember it the other way round.
    """
    with pytest.raises(SystemExit) as excinfo:
        cli._canary(["--live", "--dry-run"])
    assert excinfo.value.code != 0
    assert "contradict" in capsys.readouterr().err


def test_cli_live_flag_authorises_the_spend(monkeypatch, capsys):
    """--live must reach run_canary as live=True -- and nothing else may."""
    from daedalus.council import canary as cn

    seen: dict = {}

    class _Run:
        results = ()
        def summary(self): return {}
        def exit_code(self): return 0

    monkeypatch.setattr(cn, "default_lanes", lambda *a, **kw: (_fake_lane(),))
    monkeypatch.setattr(cn, "load_history", lambda *a, **kw: [])
    monkeypatch.setattr(cn, "append_history", lambda *a, **kw: 0)
    monkeypatch.setattr(cn, "render_table", lambda run: "rendered")
    monkeypatch.setattr(cn, "run_canary",
                        lambda *a, **kw: seen.update(kw) or _Run())
    assert cli._canary(["--live", "--vendors", "anthropic"]) == 0
    assert seen.get("live") is True
    assert "rendered" in capsys.readouterr().out


def test_the_library_gate_still_holds_if_the_cli_gate_is_neutered(
        monkeypatch, spawn_sentinel, no_socket, tmp_path):
    """DEFENCE IN DEPTH: two independent gates, and this drives the second one.

    ``parser.error`` is neutered so execution falls straight through the CLI's
    refusal with ``args.live`` still False -- which is what a future edit that
    loosens or deletes the CLI gate would look like.  ``run_canary`` must then
    refuse on its own.

    This is also the ONLY test that distinguishes ``live=args.live`` from a
    hard-coded ``live=True`` at the call site: with the CLI gate in place the two
    are behaviourally identical, so without this test somebody could pin the
    argument to True and every other test here would stay green.
    """
    import argparse

    monkeypatch.setattr(argparse.ArgumentParser, "error",
                        lambda self, message: None)
    history = tmp_path / "history.jsonl"
    with pytest.raises(C.LiveCanaryRefused):
        cli._canary(["--vendors", "anthropic,openai", "--quick",
                     "--history", str(history)])
    assert spawn_sentinel == [], (
        f"the CLI authorised a spend the operator never asked for: {spawn_sentinel}")
    assert not history.exists()


def test_cli_dry_run_names_the_lanes_live_would_call(capsys):
    """The plan must state the price before the operator types --live."""
    assert cli._canary(["--dry-run", "--quick",
                        "--vendors", "anthropic,openai"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN -- no model was called" in out
    assert "2 real" in out
    assert "_CanaryClaude" in out and "_CanaryCodex" in out


def test_cli_dry_run_calls_nothing(spawn_sentinel, no_socket, tmp_path):
    """`--dry-run` is still a dry run: it names lanes, it does not probe them."""
    history = tmp_path / "history.jsonl"
    assert cli._canary(["--dry-run", "--vendors", "anthropic,openai,google,local",
                        "--history", str(history)]) == 0
    assert spawn_sentinel == []
    assert not history.exists()

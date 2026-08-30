# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The live-wire gate: a real vendor is unreachable without an explicit opt-in.

WHY THIS FILE EXISTS.  ``session.py`` used to state, in its module docstring,
that "the offline replay harness ... is the only thing that runs this".  It was
false: :func:`session.default_participants` builds the real Claude/Codex/agy/
Ollama adapters and ``daedalus council "q"`` handed them straight to
:func:`session.convene`.  A documented lock that nobody implemented is read as a
lock, which is worse than no lock at all.

HOW THIS FILE TESTS.  By DRIVING THE GATE, never by reading source text.  A test
that greps for a flag name passes on a comment saying the flag does not exist.
So the spend is observed at the only place it is real: the process spawn.
``vendors.ManagedProcess`` is replaced with a sentinel that RECORDS the argv and
refuses to start anything, which means

* with the gate in place, ``spawned == []`` and ``LiveCouncilRefused`` is raised;
* with the gate deleted, ``spawned`` is non-empty and these tests go red --
  and, crucially, deleting the gate to verify that costs nothing, because no
  vendor process is ever really started.

The Ollama seat is covered by classification only: its transport hook is bound
at construction, so neutering it would make it indistinguishable from an
injected fake and would test the wrong thing.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from daedalus import cli
from daedalus.council import session as S
from daedalus.council import vendors as V


CLEAN_DIFF = "--- a/x.py\n+++ b/x.py\n@@\n-return 0\n+return 1\n"


def _evidence() -> S.Evidence:
    return S.Evidence(label="patch:x", paths=("x.py",),
                      files=(("PATCH.diff", CLEAN_DIFF),))


def _store(tmp_path: Path) -> Path:
    return tmp_path / "council.jsonl"


@pytest.fixture
def spawn_sentinel(monkeypatch):
    """Record every attempt to start a vendor process, and start none.

    ``run_managed`` resolves ``ManagedProcess`` from the vendors module at CALL
    time, so this intercepts the real runner without replacing it -- the adapter
    still holds the shipped ``run_managed``, so the gate must still classify it
    as live.  Neutering the runner itself would hand the gate the answer.
    """
    attempts: list[list[str]] = []

    def _blocked(argv, **kw):
        attempts.append(list(argv))
        raise OSError("test sentinel: no vendor process may start here")

    monkeypatch.setattr(V, "ManagedProcess", _blocked)
    return attempts


class _OfflineAdapter(V.CouncilAdapter):
    """Transport replaced in THIS module -- the shape the replay harness uses."""

    def __init__(self, vendor="anthropic", model="fake-1", **kw):
        super().__init__(model=model, lane="trusted", **kw)
        self.vendor = vendor
        self.endpoint = f"fake:{vendor}"

    def _dispatch(self, text, *, model, timeout_s):
        return {"status": "ok", "content": "CLAIM: x\nCITE: y\nCHECK: NONE"}


def _never_spawn(*a, **kw):  # pragma: no cover - must never run
    raise AssertionError("an injected runner was expected to stand in for spawn")


# --------------------------------------------------------------------------
# THE CENTRAL TEST: real adapters, no opt-in, nothing reached
# --------------------------------------------------------------------------


def test_convene_refuses_real_vendor_seats_without_live(tmp_path, spawn_sentinel):
    """The exact call the CLI used to make. It must refuse, and spawn nothing."""
    participants = S.default_participants(["anthropic", "openai", "google"])
    # Sanity: these really are the shipped adapters, not stand-ins.
    assert {type(p).__name__ for p in participants} == {
        "ClaudeAdapter", "CodexAdapter", "AntigravityAdapter"}

    with pytest.raises(S.LiveCouncilRefused) as excinfo:
        S.convene("is this safe?", _evidence(), participants, rounds=1,
                  council_id="c-live-refused", store_path=_store(tmp_path))

    # The refusal names the money and the way out, not just "denied".
    message = str(excinfo.value)
    assert "spend real money" in message
    assert "live=True" in message and "--dry-run" in message
    # THE INVARIANT: no vendor process was even attempted.
    assert spawn_sentinel == [], f"a vendor was reached without --live: {spawn_sentinel}"
    # And nothing was chained: a refusal must not leave an open council on disk.
    assert not _store(tmp_path).exists()


def test_live_true_actually_unlocks_dispatch(tmp_path, spawn_sentinel):
    """The opt-in must be a real switch, not decoration.

    If this passes while the previous test also passes, ``live`` is the ONLY
    thing standing between a bare invocation and four paid vendor calls.
    """
    participants = S.default_participants(["anthropic", "openai"])
    record = S.convene("is this safe?", _evidence(), participants, rounds=1,
                       council_id="c-live-allowed", store_path=_store(tmp_path),
                       per_call_timeout_s=5.0, wall_clock_s=20.0, live=True)

    binaries = {argv[0] for argv in spawn_sentinel}
    assert binaries == {"claude", "codex"}, (
        f"live=True did not reach the shipped transports: {spawn_sentinel}")
    # The council still ran to completion and recorded both seats honestly.
    assert record.requested == 2 and record.responded == 0
    assert _store(tmp_path).exists()


def test_convene_defaults_live_to_false():
    """A flipped default is the cheapest way to silently reopen this hole."""
    live = inspect.signature(S.convene).parameters["live"]
    assert live.default is False
    assert live.kind is inspect.Parameter.KEYWORD_ONLY


# --------------------------------------------------------------------------
# the classifier: fail-closed, and precise enough not to break the harness
# --------------------------------------------------------------------------


def test_every_default_participant_is_classified_live():
    """All four shipped seats -- including the Ollama one -- count as live.

    ``local`` is free but it is still egress: the default host is the bench on
    the tailnet, not this machine.
    """
    participants = S.default_participants(["anthropic", "openai", "google", "local"])
    assert len(S.live_egress_seats(participants)) == 4


def test_offline_fakes_need_no_opt_in(tmp_path):
    """The replay harness must never have to ask permission it does not need."""
    fakes = [_OfflineAdapter("anthropic"), _OfflineAdapter("openai", "fake-2")]
    assert S.live_egress_seats(fakes) == ()
    record = S.convene("q", _evidence(), fakes, rounds=1, council_id="c-fakes",
                       store_path=_store(tmp_path))
    assert record.responded == 2


def test_a_one_shot_roster_is_not_drained_by_the_gate(tmp_path):
    """The gate iterates the roster before ``convene`` sorts it.

    An iterator would arrive full, be consumed by the check, and reach the rest
    of ``convene`` empty -- a council of nobody, chained as though it were real.
    """
    record = S.convene("q", _evidence(), iter([_OfflineAdapter("anthropic")]),
                       rounds=1, council_id="c-iter", store_path=_store(tmp_path))
    assert record.requested == 1 and record.responded == 1


def test_injected_runner_counts_as_offline():
    """A shipped CLASS with a substituted transport is not a live seat.

    ``tests/test_council_session.py`` seats a real ``AntigravityAdapter`` with an
    injected runner precisely to exercise the production path offline.  If this
    exemption is ever removed, that harness starts demanding ``live=True`` and
    somebody will grant it.
    """
    agy = V.AntigravityAdapter(signed_in=False, runner=_never_spawn)
    claude = V.ClaudeAdapter(runner=_never_spawn)
    assert S.live_egress_seats([agy, claude]) == ()


def test_unknown_adapter_shapes_are_assumed_live():
    """FAIL-CLOSED: a shipped class whose transport was NOT replaced is live,
    even when it is subclassed into something the gate has never seen."""

    class SneakyClaude(V.ClaudeAdapter):
        """Inherits the shipped ``_dispatch`` and the shipped runner."""

    assert len(S.live_egress_seats([SneakyClaude()])) == 1


def test_rebinding_the_module_default_cannot_disarm_the_gate(monkeypatch):
    """The shipped-transport set is snapshotted at import.

    Otherwise ``monkeypatch.setattr(vendors, "run_managed", fake)`` AFTER the
    adapters exist would make every already-built real adapter look substituted
    while it still holds -- and would still call -- the real runner.
    """
    participants = S.default_participants(["anthropic"])
    monkeypatch.setattr(V, "run_managed", _never_spawn)
    assert len(S.live_egress_seats(participants)) == 1


# --------------------------------------------------------------------------
# the CLI: the operator-facing form of the same opt-in
# --------------------------------------------------------------------------


@pytest.fixture
def no_convene(monkeypatch):
    """Make any attempt to build a roster or convene an outright test failure."""
    def _boom(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("the CLI proceeded past the spend gate")

    monkeypatch.setattr(S, "convene", _boom)
    monkeypatch.setattr(S, "default_participants", _boom)


def test_cli_refuses_a_bare_council_invocation(no_convene, capsys):
    """`daedalus council "q"` used to call four vendors. Now it refuses."""
    with pytest.raises(SystemExit) as excinfo:
        cli._council(["is this patch safe?"])
    assert excinfo.value.code != 0
    err = capsys.readouterr().err
    assert "--live" in err and "--dry-run" in err


def test_cli_refuses_live_and_dry_run_together(no_convene, capsys):
    """Ambiguous intent about spending money is refused, not resolved."""
    with pytest.raises(SystemExit) as excinfo:
        cli._council(["is this patch safe?", "--live", "--dry-run"])
    assert excinfo.value.code != 0
    assert "contradict" in capsys.readouterr().err


def test_cli_live_flag_authorises_the_spend(monkeypatch, capsys):
    """--live must reach convene as live=True -- and nothing else may."""
    seen: dict = {}

    class _Rec:
        def render(self):
            return "rendered"

    monkeypatch.setattr(S, "default_participants", lambda *a, **kw: (_OfflineAdapter(),))
    monkeypatch.setattr(S, "convene", lambda *a, **kw: seen.update(kw) or _Rec())
    cli._council(["is this patch safe?", "--live"])
    assert seen.get("live") is True
    assert "rendered" in capsys.readouterr().out


def test_cli_dry_run_names_the_seats_live_would_call(monkeypatch, capsys):
    """The plan must state the price before the operator types --live."""
    monkeypatch.setattr(V, "available_vendors", lambda **kw: ())
    monkeypatch.setattr(S, "convene", lambda *a, **kw: pytest.fail(
        "--dry-run called convene"))
    cli._council(["is this patch safe?", "--dry-run", "--vendors", "anthropic,openai"])
    out = capsys.readouterr().out
    assert "DRY RUN -- no model was called" in out
    assert "2 real" in out
    assert "ClaudeAdapter" in out and "CodexAdapter" in out

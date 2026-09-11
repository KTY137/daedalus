"""G1-ARIADNE-09: the Ariadne CLI answers each campaign outcome with its own exit code.

The question stage 3 put to Codex and never got answered: what exit codes and
what stdout/stderr contract should ``daedalus ariadne`` give the four typed
campaign outcomes, so that a script and the desktop can branch on them without
parsing prose?

Measured baseline before this packet (2026-09-05, real tmp git repository, real
frozen evaluator, worktree venv on Windows):

- ``python -m daedalus.ariadne`` had no failure handling at all.  A request
  refusal, a revision conflict and a stopped kill switch each escaped as an
  uncaught traceback with exit ``1``; argparse's own usage error used exit ``2``.
- ``daedalus ariadne`` collapsed ``AriadneRequestError``, ``AriadneConflictError``,
  ``LoopHalted``, ``OSError``, ``TypeError`` and ``ValueError`` into exit ``2``
  with a prose line on stderr -- the same code argparse uses for a mistyped flag.
- Both doors exited ``0`` for a settled ``failed`` receipt exactly as for a
  nomination, so a script branching on the exit code read a rejected candidate
  as a success.  G1-ARIADNE-04 deferred this on purpose ("an outcome-based exit
  code is a separate decision"); this is that decision.

Every test here drives a real door: either the argv ``main`` function or a real
child process.  Nothing in ``daedalus/ariadne/campaign.py`` changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.spine.envelope import canonical_json

# The real repository fixture and the deterministic gate double this packet
# reuses verbatim; duplicating them would let the two copies drift apart and
# then the CLI would be measured against a gate the campaign suite no longer has.
from test_ariadne_campaign_v0 import _git_repo, _passing_fake_gate


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------


def _arm(root: Path):
    from daedalus.spine.killswitch import KillSwitch

    switch = KillSwitch(repo_root=root)
    # force=True: a previous test may have stopped this control root's switch.
    assert switch.arm(force=True, note="ariadne cli exit codes").running
    return switch


def _argv(root: Path, head: str, campaign_id: str, **overrides: str) -> list[str]:
    fields = {
        "--repo-root": str(root),
        "--source-revision": head,
        "--campaign-id": campaign_id,
        "--target": "sample.txt",
        "--before": "broken",
        "--after": "fixed",
        "--timeout-s": "5",
    }
    fields.update(overrides)
    return [item for pair in fields.items() for item in pair]


def _module_main(argv: list[str]) -> int:
    """The real ``python -m daedalus.ariadne`` door, called as a function."""
    from daedalus.ariadne.__main__ import main

    return main(argv)


def _subcommand(argv: list[str]) -> int:
    """The real ``daedalus ariadne`` subcommand door, called as a function."""
    from daedalus.interfaces.cli.entry import _ariadne

    return _ariadne(argv)


DOORS = pytest.mark.parametrize("door", [_module_main, _subcommand], ids=["module", "subcommand"])


def _child(argv: list[str], *, door: str = "module") -> subprocess.CompletedProcess:
    """The same door as a real child process, so the exit code is a process code."""
    if door == "module":
        command = [sys.executable, "-m", "daedalus.ariadne", *argv]
    else:
        command = [
            sys.executable, "-c",
            "from daedalus.interfaces.cli.entry import main; main()",
            "ariadne", *argv,
        ]
    return subprocess.run(
        command, capture_output=True, text=True, env=dict(os.environ), timeout=300
    )


def _polluted_fake_gate(module, monkeypatch):
    """A gate double whose output violates the frozen evaluator's one-line JSON contract.

    The exact shape of the measured Windows defect (G1-ARIADNE-03/04): a
    launcher warning ahead of the one canonical JSON line.  It produces a
    settled ``failed`` campaign receipt on the first call.
    """

    class _Contained:
        @staticmethod
        def summary() -> dict[str, object]:
            return {
                "requested": True, "executes_candidate": True, "contained": True,
                "platform": "test", "mechanism": "cli-exit-code-test-double",
                "inherited_handle_count": 0,
            }

    def polluted_command_gate(argv, **_kwargs):
        expected_sha256 = str(argv[-1])
        target = str(argv[-2])

        def evaluate(context):
            payload = (context.worktree / target).read_bytes()
            observed = hashlib.sha256(payload).hexdigest()
            output = "warning: Making stdin inheritable failed\n" + canonical_json({
                "expected_sha256": expected_sha256,
                "observed_sha256": observed,
                "passed": observed == expected_sha256,
            }) + "\n"
            return SimpleNamespace(
                passed=observed == expected_sha256,
                returncode=0 if observed == expected_sha256 else 1,
                output=output,
                output_sha256=hashlib.sha256(output.encode("ascii")).hexdigest(),
                duration_s=0.001, containment=_Contained(),
            )

        return evaluate

    monkeypatch.setattr(module, "command_gate", polluted_command_gate)


# --------------------------------------------------------------------------
# the contract itself
# --------------------------------------------------------------------------


def test_the_exit_codes_are_distinct_and_named() -> None:
    """A contract scripts branch on cannot have two meanings sharing one code."""
    from daedalus.ariadne import __main__ as door

    codes = {
        "EXIT_NOMINATED": door.EXIT_NOMINATED,
        "EXIT_NEGATIVE_RECEIPT": door.EXIT_NEGATIVE_RECEIPT,
        "EXIT_REQUEST_REFUSED": door.EXIT_REQUEST_REFUSED,
        "EXIT_REVISION_CONFLICT": door.EXIT_REVISION_CONFLICT,
        "EXIT_HALTED": door.EXIT_HALTED,
        "EXIT_CAMPAIGN_REFUSED": door.EXIT_CAMPAIGN_REFUSED,
        "EXIT_USAGE": door.EXIT_USAGE,
        "EXIT_INTERNAL": door.EXIT_INTERNAL,
    }
    assert len(set(codes.values())) == len(codes), codes
    assert codes["EXIT_NOMINATED"] == 0
    # The measured baseline defect: argparse's usage error and a refusal both
    # exited 2, so a mistyped flag was indistinguishable from a refused request.
    assert codes["EXIT_USAGE"] != codes["EXIT_REQUEST_REFUSED"]
    assert all(0 <= code <= 125 for code in codes.values()), codes


def test_the_failure_classification_is_exhaustive_and_ordered() -> None:
    """Subclasses must be classified before their base, or every refusal is a 5."""
    from daedalus.ariadne import __main__ as door
    from daedalus.ariadne.campaign import (
        AriadneCampaignError,
        AriadneConflictError,
        AriadneRequestError,
    )
    from daedalus.spine.killswitch import LoopHalted

    assert door.classify_failure(AriadneRequestError("x")) == (door.EXIT_REQUEST_REFUSED, "request")
    assert door.classify_failure(AriadneConflictError("x")) == (door.EXIT_REVISION_CONFLICT, "conflict")
    assert door.classify_failure(LoopHalted("x")) == (door.EXIT_HALTED, "halted")
    assert door.classify_failure(AriadneCampaignError("x")) == (door.EXIT_CAMPAIGN_REFUSED, "campaign")
    assert door.classify_failure(OSError("x")) == (door.EXIT_INTERNAL, "internal")
    assert door.classify_failure(ValueError("x")) == (door.EXIT_INTERNAL, "internal")


@pytest.mark.parametrize(
    "outcome,expected",
    [("nominated", 0), ("rejected", 1), ("failed", 1), ("cancelled", 1), ("something-new", 1)],
)
def test_only_a_nomination_exits_zero(outcome: str, expected: int) -> None:
    """The canonical vocabulary is nominated/rejected/failed/cancelled; an
    unknown outcome is not a success either."""
    from daedalus.ariadne.__main__ import exit_code_for_receipt

    assert exit_code_for_receipt({"outcome": outcome}) == expected


# --------------------------------------------------------------------------
# 0 -- a nominated candidate
# --------------------------------------------------------------------------


@DOORS
def test_a_nomination_exits_zero_with_the_bare_receipt_on_stdout(
    tmp_path, monkeypatch, capsys, door
) -> None:
    import daedalus.ariadne.campaign as module

    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    _passing_fake_gate(module, monkeypatch)
    switch = _arm(root)
    try:
        code = door(_argv(root, head, f"cli-nom-{door.__name__}"))
    finally:
        switch.stop()

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == "", captured.err
    receipt = json.loads(captured.out)
    # The bare canonical document, not an {"ok": ..., "ariadne": ...} wrapper:
    # both doors must hand a script the same bytes.
    assert receipt["contract_type"] == "daedalus.campaign-receipt"
    assert receipt["outcome"] == "nominated"
    assert receipt["campaign_id"] == f"cli-nom-{door.__name__}"


def test_the_json_flag_makes_the_receipt_exactly_one_line(tmp_path, monkeypatch, capsys) -> None:
    """A script reads one line; the default stays indented for a human."""
    import daedalus.ariadne.campaign as module

    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    _passing_fake_gate(module, monkeypatch)
    switch = _arm(root)
    try:
        assert _module_main([*_argv(root, head, "cli-json-compact"), "--json"]) == 0
        compact = capsys.readouterr()
        assert _module_main(_argv(root, head, "cli-json-indented")) == 0
        indented = capsys.readouterr()
    finally:
        switch.stop()

    assert compact.out.count("\n") == 1, "compact output must be one line plus its newline"
    assert indented.out.count("\n") > 1
    assert json.loads(compact.out)["outcome"] == "nominated"
    assert json.loads(indented.out)["outcome"] == "nominated"


# --------------------------------------------------------------------------
# 1 -- a settled receipt that nominates nothing
# --------------------------------------------------------------------------


@DOORS
def test_a_settled_failed_receipt_exits_one_and_still_prints_the_receipt(
    tmp_path, monkeypatch, capsys, door
) -> None:
    """G1-ARIADNE-04 made the first call RETURN the retained failed receipt.
    The baseline then exited 0 for it, exactly as for a nomination."""
    import daedalus.ariadne.campaign as module

    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    _polluted_fake_gate(module, monkeypatch)
    switch = _arm(root)
    try:
        code = door(_argv(root, head, f"cli-failed-{door.__name__}"))
    finally:
        switch.stop()

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == "", captured.err
    receipt = json.loads(captured.out)
    assert receipt["outcome"] == "failed"
    assert receipt["contract_type"] == "daedalus.campaign-receipt"
    assert any("frozen evaluator output is invalid" in b for b in receipt["blockers"]), receipt["blockers"]
    # A negative verdict is still a receipt: the exit code says "not nominated",
    # never "there is nothing to read".
    assert receipt["nomination_receipt_sha256"] is None


# --------------------------------------------------------------------------
# 2 -- the request was refused before any effect
# --------------------------------------------------------------------------


@pytest.mark.parametrize("door_name", ["module", "subcommand"])
def test_a_request_refusal_exits_two_in_a_real_process(tmp_path, monkeypatch, door_name) -> None:
    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    _arm(root).stop()  # the refusal must precede the switch entirely

    done = _child(_argv(root, head, "cli-request", **{"--target": "../escape.txt"}), door=door_name)

    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert done.stderr == "", done.stderr
    error = json.loads(done.stdout)["error"]
    assert error["kind"] == "request"
    assert "target_path is invalid" in error["message"]
    assert not (tmp_path / "control" / "ariadne").exists(), "a refused request leaves no campaign state"


def test_a_missing_repository_root_is_the_same_refusal(tmp_path, monkeypatch) -> None:
    """G1-ARIADNE-07 typed this refusal; the baseline still crashed with a
    ``FileNotFoundError`` traceback and exit 1 at the module door."""
    _git_repo(tmp_path, monkeypatch)

    done = _child(_argv(tmp_path / "absent", "a" * 40, "cli-missing-root"))

    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert done.stderr == "", done.stderr
    error = json.loads(done.stdout)["error"]
    assert error["kind"] == "request"
    assert "repo_root is unavailable or unsafe" in error["message"]


# --------------------------------------------------------------------------
# 3 -- the repository moved
# --------------------------------------------------------------------------


@pytest.mark.parametrize("door_name", ["module", "subcommand"])
def test_a_revision_conflict_exits_three_in_a_real_process(tmp_path, monkeypatch, door_name) -> None:
    root, _git = _git_repo(tmp_path, monkeypatch)

    done = _child(_argv(root, "0" * 40, "cli-conflict"), door=door_name)

    assert done.returncode == 3, (done.returncode, done.stdout, done.stderr)
    assert done.stderr == "", done.stderr
    error = json.loads(done.stdout)["error"]
    assert error["kind"] == "conflict"
    assert "source_revision conflict" in error["message"]


# --------------------------------------------------------------------------
# 4 -- the kill switch
# --------------------------------------------------------------------------


@pytest.mark.parametrize("door_name", ["module", "subcommand"])
def test_a_stopped_kill_switch_exits_four_in_a_real_process(tmp_path, monkeypatch, door_name) -> None:
    """The switch is armed in a tmp control root named by DAEDALUS_KILLSWITCH,
    then stopped, so the child halts on a real latch rather than a stub."""
    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    switch = _arm(root)
    assert not switch.stop("cli exit code measurement").running

    done = _child(_argv(root, head, "cli-halted"), door=door_name)

    assert done.returncode == 4, (done.returncode, done.stdout, done.stderr)
    assert done.stderr == "", done.stderr
    error = json.loads(done.stdout)["error"]
    assert error["kind"] == "halted"
    assert "kill switch engaged" in error["message"]


# --------------------------------------------------------------------------
# 5 -- refused, but neither a request shape nor a conflict
# --------------------------------------------------------------------------


@DOORS
def test_a_bare_campaign_refusal_exits_five(tmp_path, monkeypatch, capsys, door) -> None:
    """``AriadneCampaignError`` is the base of the other two.  Classifying it as
    a request refusal would make the two named classes unobservable."""
    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")

    code = door(_argv(root, head, "not a valid id!"))

    captured = capsys.readouterr()
    assert code == 5
    assert captured.err == "", captured.err
    error = json.loads(captured.out)["error"]
    assert error["kind"] == "campaign"
    assert "campaign_id must be" in error["message"]


# --------------------------------------------------------------------------
# 64 -- the command line, not the campaign
# --------------------------------------------------------------------------


@pytest.mark.parametrize("door_name", ["module", "subcommand"])
def test_a_usage_error_exits_sixty_four_not_two(tmp_path, monkeypatch, door_name) -> None:
    """Baseline: both doors used argparse's exit 2, which the subcommand also
    used for every refusal.  A script could not tell a typo from a refusal."""
    root, _git = _git_repo(tmp_path, monkeypatch)

    done = _child(["--repo-root", str(root)], door=door_name)

    assert done.returncode == 64, (done.returncode, done.stdout, done.stderr)
    assert "the following arguments are required" in done.stderr
    error = json.loads(done.stdout)["error"]
    assert error["kind"] == "usage"
    assert "--source-revision" in error["message"]


def test_help_prints_the_usage_text_and_exits_zero(tmp_path, monkeypatch) -> None:
    _git_repo(tmp_path, monkeypatch)

    done = _child(["--help"])

    assert done.returncode == 0, (done.returncode, done.stderr)
    assert "--source-revision" in done.stdout
    assert done.stderr == ""


# --------------------------------------------------------------------------
# 70 -- a defect in Daedalus, reported as one
# --------------------------------------------------------------------------


@DOORS
def test_a_foreign_exception_exits_seventy_with_its_traceback_on_stderr(
    tmp_path, monkeypatch, capsys, door
) -> None:
    """The baseline subcommand caught ``OSError`` and reported it as the same
    refusal as a bad target path, so an internal defect looked like operator error."""
    from daedalus.ariadne import __main__ as module

    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")

    def boom(**_kwargs):
        raise OSError("the control root vanished")

    monkeypatch.setattr(module, "run_campaign", boom)

    code = door(_argv(root, head, "cli-internal"))

    captured = capsys.readouterr()
    assert code == 70
    error = json.loads(captured.out)["error"]
    assert error["kind"] == "internal"
    assert "the control root vanished" in error["message"]
    # The one deliberate stderr exception: an internal defect keeps its traceback.
    assert "Traceback (most recent call last)" in captured.err
    assert "OSError" in captured.err


# --------------------------------------------------------------------------
# one contract, two doors
# --------------------------------------------------------------------------


def test_both_doors_answer_a_conflict_with_identical_bytes(tmp_path, monkeypatch) -> None:
    """The whole point: a caller may use either door and branch the same way."""
    root, _git = _git_repo(tmp_path, monkeypatch)

    module_door = _child(_argv(root, "0" * 40, "cli-agree-a"), door="module")
    subcommand_door = _child(_argv(root, "0" * 40, "cli-agree-b"), door="subcommand")

    assert module_door.returncode == subcommand_door.returncode == 3
    assert module_door.stdout == subcommand_door.stdout
    assert module_door.stderr == subcommand_door.stderr == ""


def test_every_error_document_is_one_compact_line(tmp_path, monkeypatch) -> None:
    """Errors are machine-read first; a script must never have to buffer to
    find the end of one, whether or not --json was passed."""
    root, _git = _git_repo(tmp_path, monkeypatch)

    done = _child(_argv(root, "0" * 40, "cli-one-line"))

    assert done.stdout.count("\n") == 1, repr(done.stdout)
    assert set(json.loads(done.stdout)) == {"error"}
    assert set(json.loads(done.stdout)["error"]) == {"kind", "message"}

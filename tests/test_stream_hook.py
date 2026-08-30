# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The room mirror must compress, and must never lie about having compressed.

Everything here runs against a temp directory (``DAEDALUS_STREAM_HOOK_DIR``);
no test may append to the live room, and nothing here needs a network, a model
or a vendor CLI.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parents[1] / "runs" / "council" / "stream_hook.py"


def _load():
    spec = importlib.util.spec_from_file_location("stream_hook_under_test",
                                                  HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = _load()

ABRIDGED = re.compile(
    r"_\[abridged: ([\d,]+) of ([\d,]+) chars omitted · full: (.+?)\]_")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

PARAS = [
    "Codex — you refuted it, and you were right. I am not going to argue the "
    "verdict.",
    "I verified your third CRITICAL myself before acting on it, because "
    "accepting a finding on authority is the same failure as rejecting one on "
    "authority. It holds exactly as you described. The cleanup resolves the "
    "path first, which follows a junction, and the removal then runs on the "
    "resolved target. Replace the worktree with a junction to the primary "
    "checkout and the cleanup deletes the repository.",
    "It sits in a finally block, so it runs on every path including failure, "
    "in code meant to run unattended overnight. That is the worst kind of "
    "bug: it only fires when nobody is watching.",
    "Fix is dispatched. I am not going to pretend the gate caught this, "
    "because it did not, and a gate that misses a delete-the-repo path is a "
    "gate that needs its own refutation round before I trust it again.",
    "What I changed, in order. The cleanup no longer resolves before it "
    "checks; it compares the link target against the primary checkout first "
    "and refuses outright when they coincide. The refusal is raised, not "
    "collected into an error field that the caller then ignores, because a "
    "swallowed refusal is how this got past review the first time.",
    "What I did not change. The removal still runs in a finally block. Moving "
    "it would leave worktrees behind on every failure path, and a leaked "
    "worktree is a cost, not a catastrophe. The catastrophe was the target, "
    "and the target is now checked.",
    "What is still open, named so nobody has to discover it. The junction "
    "check is a string comparison against a resolved path, which is correct "
    "on this platform and unverified on any other. I have no machine to test "
    "the other platform on, so I am not claiming it works there.",
]
LONG = "\n\n".join(PARAS)


def run(tmp: Path, role: str, payload: dict, monkeypatch) -> int:
    monkeypatch.setenv(hook.HOOK_DIR_ENV, str(tmp))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return hook.main(["stream_hook", role])


def run_subprocess(tmp: Path, role: str, payload: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[hook.HOOK_DIR_ENV] = str(tmp)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH), role],
        input=json.dumps(payload), text=True, env=env,
        capture_output=True, encoding="utf-8", errors="replace",
    )


def room_text(tmp: Path) -> str:
    return (tmp / "room.md").read_text(encoding="utf-8")


def log_lines(tmp: Path) -> list[str]:
    path = tmp / ".stream_hook.log"
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def sidecar_body(path: Path) -> str:
    """The full text a sidecar carries, without its provenance header line."""
    return path.read_text(encoding="utf-8").split("\n\n", 1)[1].rstrip("\n")


# --------------------------------------------------------------------------
# abridgement + provenance
# --------------------------------------------------------------------------


def test_long_turn_is_abridged_and_the_omission_line_is_true(tmp_path, monkeypatch):
    assert len(LONG) > hook.LEDE_MAX
    assert run(tmp_path, "assistant", {"response": LONG}, monkeypatch) == 0

    text = room_text(tmp_path)
    assert "### Claude  ·  Anthropic · Fable 5 · live  ·  " in text
    m = ABRIDGED.search(text)
    assert m, f"no provenance line in:\n{text}"
    omitted = int(m.group(1).replace(",", ""))
    total = int(m.group(2).replace(",", ""))
    shown = m.group(3)

    assert total == len(LONG)
    assert omitted > 0

    # The named path must EXIST and must hold the whole turn -- a provenance
    # line pointing at nothing is worse than no provenance line.
    full_path = Path(shown)
    if not full_path.is_absolute():
        full_path = hook.REPO_ROOT / shown
    assert full_path.exists(), f"provenance names a missing file: {shown}"
    body = sidecar_body(full_path)
    assert body == LONG
    assert len(body) == total

    # The lede in the room is the real prefix, and the arithmetic closes.
    #
    # Anchored on the LAST turn header rather than a positional split. The hook
    # now appends through room.append_turn, so its file carries the same
    # "# Der Raum" preamble every other room has -- and a `split("\n\n", 2)`
    # counted fixed positions from the top of the file, which that preamble
    # shifts. What the test means is "the body of the turn just written", and
    # that is what it now takes.
    lede = text.rsplit("### ", 1)[-1].split("\n\n", 1)[-1].split("\n\n_[abridged")[0]
    assert LONG.startswith(lede)
    assert len(lede) == total - omitted

    # And it actually compressed.
    assert len(lede) < len(LONG) / 2


def test_short_turn_is_mirrored_whole_with_no_omission_line(tmp_path, monkeypatch):
    short = "Codex — agreed on the junction fix. Dispatching it now."
    assert len(short) <= hook.LEDE_MAX
    assert run(tmp_path, "user", {"prompt": short}, monkeypatch) == 0

    text = room_text(tmp_path)
    assert short in text
    assert "abridged" not in text
    assert not (tmp_path / "session").exists()

    line = log_lines(tmp_path)[-1]
    assert "\tmirrored\t" in line
    assert "sidecar=-" in line


@pytest.mark.parametrize("body", [
    LONG,
    "\n\n".join(PARAS[:2]),
    PARAS[1] * 3,
])
def test_lede_cuts_at_a_boundary_never_midword(body):
    lede, cut = hook._lede(body)
    assert lede == body[:cut]
    if cut == len(body):
        return
    # The character AFTER the cut is whitespace: the cut fell between tokens,
    # never inside one.
    assert body[cut].isspace(), repr(body[cut - 20:cut + 20])
    assert not lede.endswith((" ", "\n", "\t"))
    assert cut <= hook.LEDE_MAX
    # And it landed on a real sentence or paragraph edge, not just any gap.
    assert lede.rstrip().endswith((".", "!", "?", ":")), lede[-60:]


def test_lede_prefers_the_paragraph_break_inside_the_window():
    body = ("A" * 380 + " end of the opening.\n\n"
            + "second paragraph. " * 40)
    lede, cut = hook._lede(body)
    assert lede.endswith("end of the opening.")
    assert hook.LEDE_MIN <= cut <= hook.LEDE_MAX


def test_lede_does_not_cut_at_a_version_number_or_a_file_line_reference():
    body = ("The failure is in daedalus/spine/attempt.py:295-302 and again at "
            "attempt.py:471, on release 1.5.2, e.g. whenever the runner is "
            "handed a relative path. ") * 6
    lede, cut = hook._lede(body)
    assert not lede.endswith("attempt.py:295-302")
    assert not lede.rstrip().endswith("1.5.")
    assert not lede.rstrip().endswith("e.g.")
    assert body[cut].isspace()


def test_an_open_code_fence_in_the_lede_is_closed(tmp_path, monkeypatch):
    body = ("Here is the offending block, and the reason it survives review is "
            "that it reads as ordinary cleanup.\n\n```python\n"
            + "\n".join(f"    line_{i} = compute({i})" for i in range(80))
            + "\n```\n\ntail paragraph.")
    assert run(tmp_path, "assistant", {"response": body}, monkeypatch) == 0
    text = room_text(tmp_path)
    fences = sum(1 for ln in text.splitlines() if ln.lstrip().startswith("```"))
    assert fences % 2 == 0, "an unclosed fence swallows every later turn"
    assert ABRIDGED.search(text)


# --------------------------------------------------------------------------
# the filters that already worked
# --------------------------------------------------------------------------


@pytest.mark.parametrize("marker", list(hook._PLUMBING))
def test_plumbing_is_never_mirrored(tmp_path, monkeypatch, marker):
    payload = {"response": f"{marker} the monitor noticed a new turn\n\n" + LONG}
    assert run(tmp_path, "assistant", payload, monkeypatch) == 0
    assert not (tmp_path / "room.md").exists()
    assert not (tmp_path / "session").exists()
    assert "\tskipped-plumbing\t" in log_lines(tmp_path)[-1]


def test_empty_turn_is_skipped(tmp_path, monkeypatch):
    assert run(tmp_path, "assistant", {"response": "   \n  "}, monkeypatch) == 0
    assert not (tmp_path / "room.md").exists()
    assert "\tskipped-empty\t" in log_lines(tmp_path)[-1]


def test_dedupe_still_holds(tmp_path, monkeypatch):
    assert run(tmp_path, "assistant", {"response": LONG}, monkeypatch) == 0
    assert run(tmp_path, "assistant", {"response": LONG}, monkeypatch) == 0
    text = room_text(tmp_path)
    assert text.count("### Claude") == 1
    assert len(list((tmp_path / "session").glob("*/t*.md"))) == 1
    assert "\tskipped-dupe\t" in log_lines(tmp_path)[-1]


# --------------------------------------------------------------------------
# the counter, across a real restart
# --------------------------------------------------------------------------


def test_sidecar_counter_survives_a_restart(tmp_path):
    first = run_subprocess(tmp_path, "assistant", {"response": LONG})
    assert first.returncode == 0, first.stderr
    second = run_subprocess(tmp_path, "assistant",
                            {"response": LONG + "\n\nAnd one more thing."})
    assert second.returncode == 0, second.stderr

    ids = sorted(p.stem for p in (tmp_path / "session").glob("*/t*.md"))
    assert len(ids) == 2, ids
    assert ids == ["t0001", "t0002"]

    # A third process, still fresh, still counts on from disk.
    third = run_subprocess(tmp_path, "assistant",
                           {"response": LONG + "\n\nA third distinct turn."})
    assert third.returncode == 0, third.stderr
    ids = sorted(p.stem for p in (tmp_path / "session").glob("*/t*.md"))
    assert ids == ["t0001", "t0002", "t0003"]


def test_counter_continues_past_ids_left_by_an_earlier_day(tmp_path):
    old = tmp_path / "session" / "2026-01-01"
    old.mkdir(parents=True)
    (old / "t0041.md").write_text("_t0041_\n\nold turn\n", encoding="utf-8")
    assert run_subprocess(tmp_path, "assistant", {"response": LONG}).returncode == 0
    ids = sorted(p.stem for p in (tmp_path / "session").glob("*/t*.md"))
    assert ids == ["t0041", "t0042"]


# --------------------------------------------------------------------------
# never fail the turn
# --------------------------------------------------------------------------


def test_internal_failure_still_exits_zero_and_logs_an_error(tmp_path):
    # room.md is a DIRECTORY: appending to it raises inside the hook.
    (tmp_path / "room.md").mkdir()
    proc = run_subprocess(tmp_path, "assistant", {"response": LONG})
    assert proc.returncode == 0, proc.stderr
    lines = log_lines(tmp_path)
    assert lines, "a silent failure must still leave a trace"
    assert "\terror\t" in lines[-1], lines[-1]
    assert "note=" in lines[-1]


def test_garbage_stdin_exits_zero_and_logs_an_error(tmp_path):
    env = dict(os.environ)
    env[hook.HOOK_DIR_ENV] = str(tmp_path)
    proc = subprocess.run([sys.executable, str(HOOK_PATH), "assistant"],
                          input="{not json at all", text=True, env=env,
                          capture_output=True, encoding="utf-8",
                          errors="replace")
    assert proc.returncode == 0
    assert not (tmp_path / "room.md").exists()
    assert "\terror\t" in log_lines(tmp_path)[-1]


def test_sidecar_failure_is_named_in_the_room_not_hidden(tmp_path, monkeypatch):
    # A FILE where the session directory has to go: the sidecar cannot be
    # written, and the room must say so instead of naming a phantom path.
    (tmp_path / "session").write_text("in the way", encoding="utf-8")
    assert run(tmp_path, "assistant", {"response": LONG}, monkeypatch) == 0
    text = room_text(tmp_path)
    assert "abridged" in text
    assert "full text UNAVAILABLE" in text
    assert ABRIDGED.search(text) is None


# --------------------------------------------------------------------------
# the log is bounded
# --------------------------------------------------------------------------


def test_log_rotates_at_its_cap(tmp_path, monkeypatch):
    log = tmp_path / ".stream_hook.log"
    log.write_text("x" * (hook.LOG_MAX_BYTES + 10), encoding="utf-8")
    assert run(tmp_path, "assistant", {"response": LONG}, monkeypatch) == 0

    rotated = tmp_path / ".stream_hook.log.1"
    assert rotated.exists()
    assert rotated.stat().st_size >= hook.LOG_MAX_BYTES
    assert log.stat().st_size < hook.LOG_MAX_BYTES
    assert len(log_lines(tmp_path)) == 1
    assert "\tmirrored\t" in log_lines(tmp_path)[-1]

    # And it stays bounded: a second rotation replaces the first generation.
    log.write_text("y" * (hook.LOG_MAX_BYTES + 10), encoding="utf-8")
    assert run(tmp_path, "user", {"prompt": LONG}, monkeypatch) == 0
    assert rotated.read_text(encoding="utf-8").startswith("y")
    assert len(list(tmp_path.glob(".stream_hook.log*"))) == 2


def test_log_records_every_field(tmp_path, monkeypatch):
    assert run(tmp_path, "assistant", {"response": LONG}, monkeypatch) == 0
    line = log_lines(tmp_path)[-1]
    stamp, role, decision, chars_in, kept, sidecar = line.split("\t")[:6]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp)
    assert role == "assistant"
    assert decision == "mirrored"
    assert chars_in == f"in={len(LONG)}"
    assert int(kept.split("=")[1]) < len(LONG)
    assert sidecar.startswith("sidecar=") and sidecar.endswith(".md")

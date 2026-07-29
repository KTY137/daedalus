"""Dead-letter replay: the recovery path for a turn stream_hook.py could not
chain when it happened.

Background: `runs/council/stream_hook.py` appends every turn through
`room.append_turn` -- the ONE place a turn enters Der Raum's markdown, because
that function appends AND chains AND takes a cross-process lock. When that
door cannot be used (a bad import, a lock failure), the hook does not fall
back to a direct write -- it spools the turn as one JSON line in
`dead_letter.jsonl`. Nothing used to replay that spool: a dead letter nobody
ever reads back is just a lost turn with better bookkeeping. This module
(`runs/council/dead_letter_replay.py`) is that replay path, and this file
pins what it must never do wrong.

Every test here runs offline, exactly like test_room_wiring.py: room.py's
globals (ROOM, BUS_PATH) are redirected into a temp dir, so nothing touches
the real transcript, chain or spool.

What is pinned:
  * replay puts a turn into the room ONLY via room.append_turn -- a direct
    write here would reintroduce the exact bug the dead letter survives;
  * replaying the same spool twice does not duplicate a turn (checked with
    the guard both present and, once, actually disabled);
  * an entry that still cannot be chained stays queued in the spool;
  * a malformed spool line is reported and left in the spool, and does not
    abort replay of the good lines around it;
  * after a successful replay, verify_room() is clean;
  * --dry-run changes nothing;
  * the full loop closes end to end: a real stream_hook dead letter can be
    replayed back into an attested room.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[1]
ROOM_DIR = REPO / "runs" / "council"


def _load_room():
    """Import runs/council/room.py under its own name, exactly as
    room_server.py and test_room_wiring.py do."""
    if str(ROOM_DIR) not in sys.path:
        sys.path.insert(0, str(ROOM_DIR))
    spec = importlib.util.spec_from_file_location("room", ROOM_DIR / "room.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["room"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_dlr():
    """Import dead_letter_replay.py. MUST run after _load_room(): the module
    does `import room` at its own top level, and a plain `import` reuses
    whatever is already cached under sys.modules['room'] instead of loading a
    second, independent copy. That is exactly what lets this test's
    redirected room.ROOM / room.BUS_PATH reach the replay module too --
    without it, the replay tool would be talking to a different `room`
    object than the one the tests configured, and every redirect below would
    silently do nothing."""
    spec = importlib.util.spec_from_file_location(
        "dead_letter_replay", ROOM_DIR / "dead_letter_replay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load room, then dlr (which does `import room` at its own top level and so
# needs OUR object to be the one currently cached under sys.modules['room']
# at that instant) -- then put back whatever was there before.
#
# Leaving our object sitting in sys.modules['room'] here would be collection
# -time pollution: pytest imports every test file (running each one's module
# -level code, including this block) BEFORE it runs any test. If this file
# is collected after test_room_wiring.py but its own tests haven't executed
# yet, our module staying cached under 'room' would hijack THAT file's
# OneAppendBoundary tests, whose stream_hook probes also do `import room`
# fresh on every call -- verified by driving the pytest order
# `test_room_wiring.py test_stream_hook.py test_dead_letter_replay.py` and
# watching test_room_wiring's own dead-letter test fail with an unattested
# turn, because it ended up calling OUR unpatched append_turn instead of its
# own patched one. So this substitution is scoped to the two lines below;
# the lasting per-test substitution that OUR OWN tests need lives in
# DeadLetterTestCase.setUp/tearDown instead, which pin and restore it once
# per test rather than once for the whole file.
_prior_sys_room = sys.modules.get("room")
room = _load_room()
dlr = _load_dlr()
if _prior_sys_room is not None:
    sys.modules["room"] = _prior_sys_room
else:
    sys.modules.pop("room", None)


class DeadLetterTestCase(unittest.TestCase):
    """Redirect the room into a temp dir, same pattern as
    test_room_wiring.py's RoomTestCase."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.room_dir = Path(self._tmp.name) / "council"
        self.room_dir.mkdir()
        self._saved = {k: getattr(room, k) for k in ("ROOM", "BUS_PATH")}
        room.ROOM = self.room_dir / "room.md"
        room.BUS_PATH = self.room_dir / "room.jsonl"
        room._ensure()
        self.spool = self.room_dir / "dead_letter.jsonl"

        # Pin sys.modules['room'] to THIS module for the test's duration.
        #
        # test_room_wiring.py loads its own copy of room.py the same way we
        # do (spec_from_file_location + sys.modules['room'] = mod), and
        # pytest imports every test file at collection time before any test
        # runs -- so whichever test file was collected LAST owns the shared
        # sys.modules['room'] slot by the time ANY test body executes. That
        # is invisible to code that reads a module-level `room` name (each
        # file's own binding is fixed at its own collection time and does
        # not move), but stream_hook.py's `_append` does `import room`
        # freshly on EVERY call, deliberately, so a broken import degrades to
        # a dead letter instead of crashing at load time. Combined, that
        # means the hook we drive in TheFullLoopCloses could silently bind to
        # test_room_wiring.py's room object instead of this file's -- and
        # then a monkeypatch on OUR `room.append_turn` would not be the
        # function the hook actually calls, which is exactly the kind of
        # invisible-guard trap the brief warns about. Restored in tearDown so
        # test_room_wiring.py's own tests get their module back afterward.
        self._saved_sys_room = sys.modules.get("room")
        sys.modules["room"] = room

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            setattr(room, k, v)
        if self._saved_sys_room is not None:
            sys.modules["room"] = self._saved_sys_room
        else:
            sys.modules.pop("room", None)
        self._tmp.cleanup()

    def _write_spool_lines(self, records: list[dict]) -> None:
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
        self.spool.write_text(text + "\n" if text else "", encoding="utf-8")

    @staticmethod
    def _dead_letter(who="claude", name="Kaya", tag="human · live",
                     body="a lost turn", reason="append_turn unavailable: boom",
                     ts="2026-07-28T00:00:00+00:00") -> dict:
        return {"ts": ts, "who": who, "name": name, "tag": tag, "body": body,
                "reason": reason}


# --------------------------------------------------------------------------
# 1. basic replay: appended AND chained, verify stays clean
# --------------------------------------------------------------------------
class ReplayLandsTurnsThroughAppendTurn(DeadLetterTestCase):

    def test_replay_appends_through_append_turn_and_verify_is_clean(self):
        # Establish a chained turn FIRST: in an empty room the chain has no
        # entries and verify_room checks nothing, so a broken replay could
        # pass this test by doing nothing at all.
        room.append_turn("claude", "an attested turn, so the chain is running")
        before = len(room.parse_turns(room.transcript()))

        self._write_spool_lines([self._dead_letter(body="the lost turn")])
        report = dlr.replay(self.spool, room.ROOM, room.BUS_PATH)

        self.assertEqual(report["replayed"], 1, report)
        self.assertEqual(report["failed"], 0, report)
        self.assertEqual(report["malformed"], 0, report)

        after = room.parse_turns(room.transcript())
        self.assertEqual(len(after), before + 1)
        self.assertEqual(after[-1].body.strip(), "the lost turn")

        ok, failures = room.verify_room()
        self.assertTrue(ok, failures)

        # nothing left to retry
        self.assertEqual(len(dlr._read_spool(self.spool)), 0)

    def test_replayed_turn_preserves_the_original_speaker_identity(self):
        # The dead letter carries the ORIGINAL name/tag stream_hook computed
        # (e.g. "Kaya"/"human" for a user turn, "Claude"/"...live" for an
        # assistant turn). append_turn's own SPEAKERS fallback would relabel
        # every "claude"-who turn as "Claude" regardless -- so this pins that
        # replay passes name/tag through rather than letting it default.
        room.append_turn("claude", "baseline")
        self._write_spool_lines([self._dead_letter(
            name="Claude", tag="Anthropic · Fable 5 · live",
            body="an assistant turn that could not be chained")])
        dlr.replay(self.spool, room.ROOM, room.BUS_PATH)
        turns = room.parse_turns(room.transcript())
        self.assertEqual(turns[-1].name, "Claude")
        self.assertEqual(turns[-1].tag, "Anthropic · Fable 5 · live")


# --------------------------------------------------------------------------
# 2. idempotency
# --------------------------------------------------------------------------
class ReplayIsIdempotent(DeadLetterTestCase):

    def test_replaying_twice_does_not_duplicate_a_turn(self):
        room.append_turn("claude", "baseline")
        before = len(room.parse_turns(room.transcript()))
        self._write_spool_lines([self._dead_letter(body="only once, please")])

        report1 = dlr.replay(self.spool, room.ROOM, room.BUS_PATH)
        self.assertEqual(report1["replayed"], 1, report1)
        self.assertEqual(len(room.parse_turns(room.transcript())), before + 1)

        # Simulate the crash window this design is built to survive: the
        # append succeeded but the spool still holds (or was handed again)
        # the identical record, e.g. a process killed right after
        # append_turn returned and before the spool was rewritten.
        self._write_spool_lines([self._dead_letter(body="only once, please")])
        report2 = dlr.replay(self.spool, room.ROOM, room.BUS_PATH)

        self.assertEqual(report2["replayed"], 0, report2)
        self.assertEqual(report2["already_present"], 1, report2)
        after = room.parse_turns(room.transcript())
        self.assertEqual(len(after), before + 1,
                         "replaying an already-landed entry duplicated the turn")
        ok, failures = room.verify_room()
        self.assertTrue(ok, failures)


# --------------------------------------------------------------------------
# 3. an entry that still cannot be chained stays queued
# --------------------------------------------------------------------------
class FailedEntriesStayQueued(DeadLetterTestCase):

    def test_an_entry_that_still_cannot_be_chained_stays_in_the_spool(self):
        room.append_turn("claude", "baseline")
        before_text = room.ROOM.read_text(encoding="utf-8")
        self._write_spool_lines([self._dead_letter(body="cannot be chained yet")])

        saved = room.append_turn
        room.append_turn = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("boom again"))
        try:
            report = dlr.replay(self.spool, room.ROOM, room.BUS_PATH)
        finally:
            room.append_turn = saved

        self.assertEqual(report["failed"], 1, report)
        self.assertEqual(report["replayed"], 0, report)
        remaining = dlr._read_spool(self.spool)
        self.assertEqual(len(remaining), 1, "a failed entry was dropped")
        self.assertIn("cannot be chained yet", remaining[0].data["body"])
        # A failed replay attempt must not fall back to writing the markdown
        # directly -- that is the exact bug a dead letter exists to survive,
        # one level deeper. room.md must be byte-identical to before the
        # failed attempt, not just "not longer".
        self.assertEqual(
            room.ROOM.read_text(encoding="utf-8"), before_text,
            "a failed append_turn call left an unattested write in room.md")

        # once the door works again, the next replay recovers it
        report2 = dlr.replay(self.spool, room.ROOM, room.BUS_PATH)
        self.assertEqual(report2["replayed"], 1, report2)
        self.assertEqual(len(dlr._read_spool(self.spool)), 0)


# --------------------------------------------------------------------------
# 4. a malformed line is reported, kept, and does not abort the batch
# --------------------------------------------------------------------------
class MalformedLineDoesNotAbortReplay(DeadLetterTestCase):

    def test_a_malformed_line_is_reported_and_the_good_lines_still_replay(self):
        room.append_turn("claude", "baseline")
        good1 = json.dumps(self._dead_letter(body="first good turn"))
        good2 = json.dumps(self._dead_letter(body="second good turn"))
        self.spool.write_text(
            good1 + "\n{not json at all\n" + good2 + "\n", encoding="utf-8")

        report = dlr.replay(self.spool, room.ROOM, room.BUS_PATH)
        self.assertEqual(report["replayed"], 2, report)
        self.assertEqual(report["malformed"], 1, report)
        self.assertEqual(report["failed"], 0, report)

        remaining_text = self.spool.read_text(encoding="utf-8")
        self.assertIn("{not json at all", remaining_text,
                      "the malformed line was dropped instead of kept")
        remaining = dlr._read_spool(self.spool)
        self.assertEqual(len(remaining), 1)
        self.assertTrue(remaining[0].malformed)

        bodies = {t.body.strip() for t in room.parse_turns(room.transcript())}
        self.assertIn("first good turn", bodies)
        self.assertIn("second good turn", bodies)
        ok, failures = room.verify_room()
        self.assertTrue(ok, failures)


# --------------------------------------------------------------------------
# 5. replay uses ONLY append_turn -- never a direct write
# --------------------------------------------------------------------------
class ReplayNeverBypassesAppendTurn(DeadLetterTestCase):

    def test_replay_touches_room_md_only_through_append_turn(self):
        room.append_turn("claude", "baseline")
        self._write_spool_lines(
            [self._dead_letter(body="should route through append_turn")])
        before_text = room.ROOM.read_text(encoding="utf-8")

        calls = []

        def stub(who, text, model=None, name=None, tag=None,
                 room_path=None, bus_path=None):
            calls.append((who, text, name, tag))
            return {"ok": True, "id": "stub-id", "error": None, "turns": 999}

        saved = room.append_turn
        room.append_turn = stub
        try:
            dlr.replay(self.spool, room.ROOM, room.BUS_PATH)
        finally:
            room.append_turn = saved

        after_text = room.ROOM.read_text(encoding="utf-8")
        self.assertEqual(
            before_text, after_text,
            "replay modified room.md without going through append_turn")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "should route through append_turn")


# --------------------------------------------------------------------------
# 6. --dry-run changes nothing
# --------------------------------------------------------------------------
class DryRunChangesNothing(DeadLetterTestCase):

    def test_dry_run_reports_but_mutates_neither_room_nor_spool(self):
        room.append_turn("claude", "baseline")
        self._write_spool_lines([self._dead_letter(body="not yet, just looking")])
        before_room = room.ROOM.read_text(encoding="utf-8")
        before_spool = self.spool.read_text(encoding="utf-8")

        report = dlr.replay(self.spool, room.ROOM, room.BUS_PATH, dry_run=True)

        self.assertEqual(report["replayed"], 0)
        self.assertEqual(report["details"][0]["status"], "would-replay")
        self.assertEqual(room.ROOM.read_text(encoding="utf-8"), before_room)
        self.assertEqual(self.spool.read_text(encoding="utf-8"), before_spool)

    def test_dry_run_reports_already_present_without_mutating_anything(self):
        room.append_turn("claude", "baseline")
        self._write_spool_lines([self._dead_letter(body="landed already")])
        dlr.replay(self.spool, room.ROOM, room.BUS_PATH)   # real replay first
        self._write_spool_lines([self._dead_letter(body="landed already")])
        before_room = room.ROOM.read_text(encoding="utf-8")
        before_spool = self.spool.read_text(encoding="utf-8")

        report = dlr.replay(self.spool, room.ROOM, room.BUS_PATH, dry_run=True)

        self.assertEqual(report["details"][0]["status"], "already-present")
        self.assertEqual(room.ROOM.read_text(encoding="utf-8"), before_room)
        self.assertEqual(self.spool.read_text(encoding="utf-8"), before_spool)


# --------------------------------------------------------------------------
# 7. CLI
# --------------------------------------------------------------------------
class CLIEntryPoint(DeadLetterTestCase):

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dlr.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_list_reports_without_mutating_the_spool(self):
        self._write_spool_lines([self._dead_letter(body="just list me")])
        before = self.spool.read_text(encoding="utf-8")
        code, out, _ = self._run(
            ["list", "--spool", str(self.spool), "--room", str(room.ROOM)])
        self.assertEqual(code, 0)
        self.assertIn("just list me", out)
        self.assertEqual(self.spool.read_text(encoding="utf-8"), before)

    def test_replay_defaults_follow_the_redirected_room_globals(self):
        # No --room / --spool given: must resolve against room.ROOM, which
        # setUp already redirected into the temp dir. If this resolved
        # against the real repo's room instead, it would find no spool and
        # report nothing -- so the assertion on the turn landing is the
        # thing that actually proves the redirect was honoured.
        room.append_turn("claude", "baseline")
        self._write_spool_lines([self._dead_letter(body="found via defaults")])
        code, out, _ = self._run(["replay"])
        self.assertEqual(code, 0, out)
        self.assertIn("1 replayed", out)
        bodies = {t.body.strip() for t in room.parse_turns(room.transcript())}
        self.assertIn("found via defaults", bodies)

    def test_replay_reports_verify_ok_after_success(self):
        room.append_turn("claude", "baseline")
        self._write_spool_lines([self._dead_letter(body="verify me")])
        code, out, _ = self._run(
            ["replay", "--spool", str(self.spool), "--room", str(room.ROOM),
             "--bus", str(room.BUS_PATH)])
        self.assertEqual(code, 0)
        self.assertIn("verify_room: OK", out)

    def test_replay_exits_nonzero_when_a_failed_entry_remains(self):
        room.append_turn("claude", "baseline")
        self._write_spool_lines([self._dead_letter(body="will fail")])
        saved = room.append_turn
        room.append_turn = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("nope"))
        try:
            code, out, _ = self._run(
                ["replay", "--spool", str(self.spool), "--room", str(room.ROOM),
                 "--bus", str(room.BUS_PATH)])
        finally:
            room.append_turn = saved
        self.assertEqual(code, 1)
        self.assertIn("1 failed", out)


# --------------------------------------------------------------------------
# 8. the full loop: a real stream_hook dead letter, replayed clean
# --------------------------------------------------------------------------
class TheFullLoopCloses(DeadLetterTestCase):
    """The end-to-end path this module exists to complete: a turn
    stream_hook.py could not chain is spooled, then recovered here, and the
    room ends up exactly as attested as if the mirror had never failed."""

    def test_stream_hook_dead_letter_replays_clean_and_is_idempotent(self):
        hook_path = ROOM_DIR / "stream_hook.py"
        spec = importlib.util.spec_from_file_location(
            "stream_hook_dlr_probe", hook_path)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        hook._room_path = lambda: room.ROOM
        hook._hook_dir = lambda: room.ROOM.parent

        # Establish a chained turn FIRST -- same reasoning as test 1: an
        # empty chain would make verify_room check nothing.
        room.append_turn("claude", "an attested turn, so the chain is running")
        before = len(room.parse_turns(room.transcript()))

        saved = room.append_turn
        room.append_turn = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("boom"))
        try:
            hook._append("Kaya", "human · live",
                         "a turn lost to a broken mirror")
        finally:
            room.append_turn = saved

        # the room did not grow: the turn was spooled, not appended
        self.assertEqual(len(room.parse_turns(room.transcript())), before)
        self.assertTrue(self.spool.exists())

        report = dlr.replay(self.spool, room.ROOM, room.BUS_PATH)
        self.assertEqual(report["replayed"], 1, report)
        after = room.parse_turns(room.transcript())
        self.assertEqual(len(after), before + 1)
        self.assertEqual(after[-1].body.strip(), "a turn lost to a broken mirror")

        ok, failures = room.verify_room()
        self.assertTrue(ok, failures)

        # idempotent: the spool is now empty, a second replay is a no-op
        report2 = dlr.replay(self.spool, room.ROOM, room.BUS_PATH)
        self.assertEqual(report2["total"], 0, report2)
        self.assertEqual(len(room.parse_turns(room.transcript())), before + 1)


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The room summariser: idempotent, crash-safe, floor-gated, honest.

Every test here runs OFFLINE with an injected fake summariser and temp dirs.
No model, no network, no vendor CLI, and the real ``runs/council/room.md`` is
never touched.

What is pinned:
  * a missing ``turns/`` directory is a clean no-op, not an error -- shipping
    this module cannot break a session where the hook half is not wired yet;
  * a second pass posts NOTHING new (idempotent);
  * a crash between summarise and mark leaves the turn RE-PROCESSABLE, and the
    retry does not double-post -- the room, not the marker, is the authority;
  * a planted secret is refused by the floor, never reaches the summariser, and
    the room RECORDS the refusal instead of silently skipping it;
  * a direct address to a named agent survives VERBATIM even when the model
    drops it -- the module preserves it, it does not merely hope;
  * every entry is visibly a summary and carries the sidecar pointer;
  * ``--dry-run`` calls the summariser zero times;
  * the output cap is enforced by code, not by the model's self-restraint;
  * the Ollama host must be passed explicitly, and non-loopback is refused.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[1]
ROOM_DIR = REPO / "runs" / "council"


def _load_summarize():
    """Import runs/council/summarize.py under its own name (no package)."""
    if str(ROOM_DIR) not in sys.path:
        sys.path.insert(0, str(ROOM_DIR))
    spec = importlib.util.spec_from_file_location(
        "summarize", ROOM_DIR / "summarize.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["summarize"] = mod
    spec.loader.exec_module(mod)
    return mod


sm = _load_summarize()

# If this string ever appears in what the fake summariser saw, or in the room,
# the floor leaked. It is planted inside a shape the floor recognises.
CANARY = "ZZ-ROOM-SUMMARY-LEAK-CANARY-ZZ"
SECRET_BODY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    f"MIIEowIBAAKCAQEA{CANARY}\n"
    "-----END RSA PRIVATE KEY-----\n"
)


class FakeSummariser:
    """Records every prompt it is handed; returns a canned reply."""

    def __init__(self, reply: str = "DECIDED: the fake decided something."):
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply

    @property
    def calls(self) -> int:
        return len(self.prompts)


def _write_turn(turns: Path, stem: str, text: str, *,
                role: str = "assistant", name: str | None = None) -> Path:
    turns.mkdir(parents=True, exist_ok=True)
    path = turns / f"{stem}.json"
    payload = {
        "id": stem,
        "ts": "2026-07-28T14:55:03Z",
        "role": role,
        "text": text,
    }
    if name:
        payload["name"] = name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class RoomSummariseBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.turns = self.root / "turns"
        self.room = self.root / "room.md"
        self.addCleanup(self._tmp.cleanup)

    def room_text(self) -> str:
        if not self.room.exists():
            return ""
        return self.room.read_text(encoding="utf-8")

    def marker_count(self, turn_id: str) -> int:
        return self.room_text().count(sm.entry_marker(turn_id))


class TestNoOpAndIdempotency(RoomSummariseBase):
    def test_missing_turns_dir_is_a_clean_noop(self):
        """The hook half may not exist yet. That is 'nothing to do', not an error."""
        fake = FakeSummariser()
        report = sm.process_once(
            turns_dir=self.root / "does-not-exist",
            room=self.room, summariser=fake)
        self.assertEqual(report.scanned, 0)
        self.assertEqual(report.posted, 0)
        self.assertEqual(fake.calls, 0)
        self.assertFalse(self.room.exists(), "no room file should be created")

        # ...and through the CLI, which must exit 0.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = sm.main(["--once",
                          "--turns-dir", str(self.root / "does-not-exist"),
                          "--room", str(self.room)])
        self.assertEqual(rc, 0)
        self.assertIn("nothing to summarise", buf.getvalue())

    def test_second_run_posts_nothing_new(self):
        _write_turn(self.turns, "20260728T100000Z-assistant-aaaa",
                    "A long turn about routing lanes. " * 40)
        fake = FakeSummariser()

        first = sm.process_once(turns_dir=self.turns, room=self.room,
                                summariser=fake)
        self.assertEqual(first.posted, 1)
        self.assertEqual(fake.calls, 1)
        after_first = self.room_text()

        second = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake)
        self.assertEqual(second.scanned, 0, "marked turn must not be rescanned")
        self.assertEqual(second.posted, 0)
        self.assertEqual(fake.calls, 1, "no second model call for a done turn")
        self.assertEqual(self.room_text(), after_first,
                         "the room must be byte-identical after a re-run")


class TestCrashSafety(RoomSummariseBase):
    def test_crash_between_summarise_and_mark_is_reprocessable_not_doubled(self):
        """The failure the marker alone cannot survive.

        Post lands, marker does not. The turn must come back on the next pass
        (not lost) and must not produce a second room entry (not doubled).
        """
        turn_id = "20260728T110000Z-assistant-bbbb"
        sidecar = _write_turn(self.turns, turn_id, "Decide the lane model.")
        fake = FakeSummariser("DECIDED: lane model stays as-is.")

        real_mark = sm.mark_done

        def exploding_mark(*_a, **_kw):
            raise OSError("simulated crash before the marker landed")

        sm.mark_done = exploding_mark
        try:
            first = sm.process_once(turns_dir=self.turns, room=self.room,
                                    summariser=fake)
        finally:
            sm.mark_done = real_mark

        self.assertEqual(fake.calls, 1)
        self.assertFalse(sm.marker_path(sidecar).exists(),
                         "the marker must NOT exist after the simulated crash")
        self.assertEqual(self.marker_count(turn_id), 1,
                         "the room entry did land before the crash")
        self.assertEqual(first.posted, 0, "an unmarked post is not a success")

        # The turn is still pending -> not lost.
        self.assertEqual([p.name for p in sm.pending_turns(self.turns)],
                         [sidecar.name])

        second = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=FakeSummariser("DECIDED: second try."))
        self.assertEqual(second.scanned, 1, "the turn was re-processed")
        self.assertEqual(self.marker_count(turn_id), 1,
                         "the room must still hold exactly ONE entry for this turn")
        self.assertNotIn("DECIDED: second try.", self.room_text(),
                         "the retry must not append a second summary")
        self.assertTrue(sm.marker_path(sidecar).exists(),
                        "the retry must finish the job and mark it done")
        self.assertEqual(second.outcomes[0].status, "duplicate")

    def test_summariser_failure_leaves_the_turn_pending(self):
        sidecar = _write_turn(self.turns, "20260728T111500Z-assistant-cccc", "hi")

        def boom(_prompt: str) -> str:
            raise RuntimeError("model unreachable")

        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=boom)
        self.assertEqual(report.posted, 0)
        self.assertEqual(report.outcomes[0].status, "error")
        self.assertFalse(sm.marker_path(sidecar).exists())
        self.assertEqual(self.room_text(), "", "nothing half-written to the room")
        self.assertEqual(len(sm.pending_turns(self.turns)), 1)


class TestSecretFloor(RoomSummariseBase):
    def test_planted_secret_is_refused_and_the_room_says_so(self):
        turn_id = "20260728T120000Z-assistant-dddd"
        sidecar = _write_turn(
            self.turns, turn_id,
            "Here is the deploy key we were talking about:\n" + SECRET_BODY)
        fake = FakeSummariser()

        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake)

        self.assertEqual(fake.calls, 0,
                         "the secret must never reach the summariser")
        self.assertNotIn(CANARY, "".join(fake.prompts))
        self.assertEqual(report.refused, 1)

        room = self.room_text()
        self.assertNotIn(CANARY, room, "the secret must never reach the room")
        self.assertNotIn("BEGIN RSA PRIVATE KEY", room)
        # The refusal is VISIBLE, not a silent skip.
        self.assertIn("summary withheld", room)
        self.assertIn("NOT SUMMARISED", room)
        self.assertIn("secret floor refused", room)
        self.assertIn("private key", room.lower())
        self.assertIn(sidecar.name, room, "the reader is told where the turn is")

        marker = json.loads(sm.marker_path(sidecar).read_text(encoding="utf-8"))
        self.assertEqual(marker["status"], "refused")
        self.assertEqual(marker["channel"], "content")

    def test_floor_channels_are_driven_separately(self):
        """A clean-content turn whose PATH is secret-marked must still refuse.

        Feeding the floor one concatenated blob would kill the path tier; this
        pins that the path channel is fed on its own.
        """
        self.turns.mkdir(parents=True, exist_ok=True)
        sidecar = self.turns / "20260728T121000Z-assistant.env.json"
        sidecar.write_text(json.dumps(
            {"id": "path-marked", "role": "assistant",
             "text": "Entirely innocent prose with no credential in it."}),
            encoding="utf-8")
        fake = FakeSummariser()

        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake)
        self.assertEqual(fake.calls, 0)
        self.assertEqual(report.refused, 1)
        self.assertEqual(report.outcomes[0].detail.split(":")[0], "path")


class TestEntryShape(RoomSummariseBase):
    def test_direct_address_survives_verbatim_even_if_the_model_drops_it(self):
        turn_id = "20260728T130000Z-assistant-eeee"
        address = "Codex: rerun the floor check on offload.py"
        _write_turn(self.turns, turn_id,
                    "Long preamble about the lane model.\n\n"
                    f"{address}\n\nMore prose nobody needs.")
        # The model paraphrases everything away -- the classic small-model failure.
        fake = FakeSummariser("DECIDED: nothing much happened here.")

        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)
        room = self.room_text()
        self.assertIn(address, room,
                      "the module must restore a dropped direct address verbatim")
        # ADDRESSED, not ASKS: the module must not invent an obligation, and a
        # reader must be able to tell a restored line from a model-written one.
        self.assertIn(f"ADDRESSED: {address}", room)

    def test_direct_address_kept_by_the_model_is_not_duplicated(self):
        turn_id = "20260728T131000Z-assistant-ffff"
        address = "Codex: rerun the floor check on offload.py"
        _write_turn(self.turns, turn_id, f"{address}\n\nsome prose")
        fake = FakeSummariser(f"ASKS: {address}")

        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)
        self.assertEqual(self.room_text().count(address), 1)

    def test_an_agent_already_addressed_in_the_models_own_words_is_not_restored(self):
        """Regression from a real claude-haiku-4-5 run.

        The model addressed Codex and Ollama in its own words; a per-utterance
        restore then appended two redundant verbatim lines, one of which was an
        acknowledgement mislabelled as an ASK. Coverage is per AGENT.
        """
        turn_id = "20260728T132000Z-assistant-pppp"
        _write_turn(self.turns, turn_id,
                    "Codex: you refuted it, and you were right.\n\n"
                    "Ollama: stand down from reviewing for now.\n")
        fake = FakeSummariser(
            "ASKS: Codex — which git verb is worse? Answer with evidence.\n"
            "ASKS: Ollama — stand down from reviewing; summarise diffs instead.")

        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)
        room = self.room_text()
        self.assertNotIn("ADDRESSED:", room,
                         "both agents were already addressed by the model")
        self.assertNotIn("you refuted it", room,
                         "an acknowledgement must not be restored as an ask")
        body = [ln for ln in room.splitlines() if ln.startswith(("ASKS:", "ADDRESSED:"))]
        self.assertEqual(len(body), 2)

    def test_an_unspaced_dash_address_still_counts_as_coverage(self):
        """Regression from a second real claude-haiku-4-5 run, verbatim.

        The model wrote "Codex—is there..." with NO space after the dash. The
        detector missed it, decided Codex was uncovered, and re-appended a
        verbatim quote the summary already carried. Both agents here are
        addressed by the model; nothing may be restored.
        """
        turn_id = "20260728T134000Z-assistant-rrrr"
        _write_turn(self.turns, turn_id,
                    'Codex: you refuted it, and you were right.\n\n'
                    'Ollama: you answered "I could not break it." twice.\n')
        fake = FakeSummariser(
            "ASKS: Codex—is there a worse git verb in allowlist than git config?\n"
            "ASKS: Ollama—stand down from reviewing; focus on summarising diffs.")

        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)
        room = self.room_text()
        self.assertNotIn("ADDRESSED:", room)
        self.assertNotIn("you refuted it", room)
        self.assertNotIn("I could not break it", room)

    def test_a_leading_name_with_no_punctuation_counts_as_coverage(self):
        """Third real run, verbatim: "ASKS: Ollama stand down from reviewing".

        No colon, no dash. It is still plainly an address, and restoring the
        source quote on top of it is the redundancy this rule exists to stop.
        """
        turn_id = "20260728T135000Z-assistant-ssss"
        _write_turn(self.turns, turn_id,
                    'Ollama: you answered "I could not break it." twice.\n')
        fake = FakeSummariser(
            "ASKS: Ollama stand down from reviewing; shift to summarising diffs.")

        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)
        room = self.room_text()
        self.assertNotIn("ADDRESSED:", room)
        self.assertNotIn("I could not break it", room)

    def test_an_unspaced_hyphen_inside_a_word_is_not_an_address(self):
        """The dash relaxation must not turn hyphenated prose into an address."""
        self.assertEqual(sm.direct_addresses("the Claude-side fence is fine"), [])
        self.assertEqual(sm.direct_addresses("Codex-style review is cheap"), [])
        self.assertEqual(
            sm.direct_addresses("Codex—rerun the check"),
            ["Codex: rerun the check"])

    def test_a_mere_mention_does_not_suppress_the_verbatim_restore(self):
        """Mentioning Codex is not addressing Codex. The guarantee survives."""
        turn_id = "20260728T133000Z-assistant-qqqq"
        address = "Codex: rerun the floor check on offload.py"
        _write_turn(self.turns, turn_id, f"prose\n\n{address}\n")
        fake = FakeSummariser("DECIDED: accepting Codex's three CRITICALs.")

        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)
        self.assertIn(f"ADDRESSED: {address}", self.room_text())

    def test_entry_is_labelled_a_summary_and_carries_the_sidecar_path(self):
        turn_id = "20260728T140000Z-assistant-gggg"
        sidecar = _write_turn(self.turns, turn_id, "x" * 4321, name="Claude")
        fake = FakeSummariser("DECIDED: shipped the thing.")

        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake,
                        model="test-model")
        room = self.room_text()

        self.assertIn("### Claude (summary)", room)
        self.assertIn("SUMMARY -- not Claude's own words", room)
        self.assertIn("4,321 chars", room, "the reader is told what was cut")
        self.assertIn("test-model", room, "the reader is told who compressed it")
        self.assertIn(sm._sidecar_ref(sidecar), room,
                      "the pointer to the full turn must be present")
        self.assertIn(sm.entry_marker(turn_id), room)
        # It must not be mistakable for the speaker's own words.
        self.assertNotIn("### Claude  ", room)

    def test_output_is_capped_by_code_not_by_the_model(self):
        turn_id = "20260728T141000Z-assistant-hhhh"
        _write_turn(self.turns, turn_id, "no addresses in this turn at all")
        runaway = "\n".join(f"DECIDED: line {i} " + "y" * 400 for i in range(30))
        fake = FakeSummariser(runaway)

        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)
        body = self.room_text().split("chars by")[-1]
        summary_lines = [ln for ln in body.splitlines()
                         if ln.startswith("DECIDED:")]
        self.assertLessEqual(len(summary_lines), sm.MAX_SUMMARY_LINES)
        for line in summary_lines:
            self.assertLessEqual(len(line), sm.MAX_LINE_CHARS + 4)

    def test_off_shape_output_is_flagged_not_hidden(self):
        turn_id = "20260728T142000Z-assistant-iiii"
        sidecar = _write_turn(self.turns, turn_id, "some prose")
        fake = FakeSummariser("The author explains that things are going well.")

        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake)
        self.assertEqual(report.off_shape, 1)
        marker = json.loads(sm.marker_path(sidecar).read_text(encoding="utf-8"))
        self.assertFalse(marker["shape_ok"])

    def test_the_prompt_carries_the_turn_and_the_four_categories(self):
        _write_turn(self.turns, "20260728T143000Z-assistant-jjjj",
                    "We decided to keep local_only fail-closed.")
        fake = FakeSummariser()
        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)

        prompt = fake.prompts[0]
        for label in ("DECIDED:", "CHANGED:", "ASKS:", "CONSTRAINT:"):
            self.assertIn(label, prompt)
        self.assertIn("We decided to keep local_only fail-closed.", prompt)
        self.assertIn("VERBATIM", prompt, "the address rule must be in the prompt")


class TestDryRun(RoomSummariseBase):
    def test_dry_run_calls_the_summariser_zero_times(self):
        turn_id = "20260728T150000Z-assistant-kkkk"
        sidecar = _write_turn(self.turns, turn_id, "some turn text here")
        fake = FakeSummariser()

        lines: list[str] = []
        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake, dry_run=True,
                                 log=lines.append)

        self.assertEqual(fake.calls, 0)
        self.assertEqual(report.posted, 0)
        self.assertEqual(report.scanned, 1)
        self.assertFalse(self.room.exists(), "a dry run writes no room entry")
        self.assertFalse(sm.marker_path(sidecar).exists(),
                         "a dry run marks nothing done")
        self.assertTrue(any("would post" in ln for ln in lines))

    def test_dry_run_through_the_cli_constructs_no_model_client(self):
        _write_turn(self.turns, "20260728T151000Z-assistant-llll", "text")
        called: list[str] = []

        real_factory = sm.cli_summariser
        sm.cli_summariser = lambda *a, **kw: called.append("built") or (
            lambda _p: "")
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = sm.main(["--dry-run",
                              "--turns-dir", str(self.turns),
                              "--room", str(self.room)])
        finally:
            sm.cli_summariser = real_factory

        self.assertEqual(rc, 0)
        self.assertEqual(called, [], "--dry-run must not even build a model client")
        self.assertIn("would post", buf.getvalue())
        self.assertFalse(self.room.exists())

    def test_dry_run_still_reports_a_floor_refusal(self):
        """A dry run that hides a refusal is a dry run that lies."""
        _write_turn(self.turns, "20260728T152000Z-assistant-mmmm",
                    "key:\n" + SECRET_BODY)
        fake = FakeSummariser()
        lines: list[str] = []
        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake,
                        dry_run=True, log=lines.append)
        self.assertEqual(fake.calls, 0)
        blob = "\n".join(lines)
        self.assertIn("REFUSAL", blob)
        self.assertNotIn(CANARY, blob)


class TestFeedbackLoop(RoomSummariseBase):
    """Observed live on the first real run, not hypothetical.

    ``claude -p`` starts a real Claude Code session; that session fires the same
    stream hook; the hook mirrored this module's own 6,183-char summarisation
    prompt into the live room as a turn from "Kaya". Summarising that would
    produce another prompt, which would mirror again.
    """

    def test_a_mirrored_summarisation_prompt_is_skipped_not_summarised(self):
        turn_id = "20260728T170000Z-user-loop"
        sidecar = _write_turn(
            self.turns, turn_id,
            sm.build_prompt(sm.Turn(
                id="inner", path=Path("x.json"), role="assistant",
                name="Claude", tag="t", text="some earlier turn")),
            role="user")
        fake = FakeSummariser()

        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake)
        self.assertEqual(fake.calls, 0, "never summarise our own prompt")
        self.assertEqual(report.skipped, 1)
        self.assertEqual(report.posted, 0)
        self.assertEqual(self.room_text(), "",
                         "plumbing gets no room entry -- that is the noise "
                         "this module exists to delete")
        marker = json.loads(sm.marker_path(sidecar).read_text(encoding="utf-8"))
        self.assertEqual(marker["status"], "skipped")
        self.assertIn("own summarisation prompt", marker["reason"])

    def test_the_sentinel_is_actually_in_every_prompt(self):
        """A loop breaker that is not in the prompt breaks no loop."""
        _write_turn(self.turns, "20260728T171000Z-assistant-s", "hello")
        fake = FakeSummariser()
        sm.process_once(turns_dir=self.turns, room=self.room, summariser=fake)
        self.assertIn(sm.PROMPT_SENTINEL, fake.prompts[0])

    def test_the_child_session_is_pointed_at_a_sink_not_the_live_room(self):
        seen: dict = {}

        class _Proc:
            returncode = 0
            stdout = "DECIDED: ok"
            stderr = ""

        real_run, real_which = sm.subprocess.run, sm.shutil.which
        sm.subprocess.run = lambda cmd, **kw: (seen.update(kw), _Proc())[1]
        sm.shutil.which = lambda name: "claude.exe"
        before = os.environ.get(sm.HOOK_DIR_ENV)
        try:
            sm.cli_summariser("m")("prompt")
        finally:
            sm.subprocess.run, sm.shutil.which = real_run, real_which

        child = seen["env"][sm.HOOK_DIR_ENV]
        self.assertTrue(child, "the child must get a hook-dir redirect")
        self.assertNotEqual(Path(child).resolve(), ROOM_DIR.resolve(),
                            "the child must not mirror into the live room")
        self.assertNotIn(str(REPO), str(Path(child).resolve()),
                         "the sink belongs outside the checkout")
        self.assertIn("PATH", seen["env"], "the child keeps the real environment")
        self.assertEqual(os.environ.get(sm.HOOK_DIR_ENV), before,
                         "this process's own environment is never mutated")


class TestSummariserBackends(unittest.TestCase):
    def test_ollama_host_must_be_explicit_and_loopback(self):
        with self.assertRaises(TypeError):
            sm.ollama_summariser(model="qwen2.5-coder")  # host is required

        with self.assertRaises(ValueError) as ctx:
            sm.ollama_summariser(host="10.0.0.5:11434", model="qwen2.5-coder")
        self.assertIn("off-machine egress", str(ctx.exception))

        # loopback is fine, and building the client touches no network
        client = sm.ollama_summariser(host="127.0.0.1:11434", model="q")
        self.assertTrue(callable(client))
        # ...and an operator who accepts the egress can still do it explicitly
        self.assertTrue(callable(sm.ollama_summariser(
            host="10.0.0.5:11434", model="q", allow_offmachine=True)))

    def test_module_never_reads_or_sets_ollama_host(self):
        """An env var that redirects where turn text goes is nobody's decision."""
        before = os.environ.get("OLLAMA_HOST")
        sm.ollama_summariser(host="127.0.0.1:11434", model="q")
        self.assertEqual(os.environ.get("OLLAMA_HOST"), before)
        source = (ROOM_DIR / "summarize.py").read_text(encoding="utf-8")
        self.assertNotIn('environ.get("OLLAMA_HOST"', source)
        self.assertNotIn('environ["OLLAMA_HOST"]', source)

    def test_cli_summariser_sends_the_prompt_on_stdin_not_argv(self):
        """The npm .cmd shim mangles a multi-line argv element. STDIN or bust."""
        seen: dict = {}

        class _Proc:
            returncode = 0
            stdout = "DECIDED: ok"
            stderr = ""

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["input"] = kwargs.get("input")
            return _Proc()

        real_run, real_which = sm.subprocess.run, sm.shutil.which
        sm.subprocess.run = fake_run
        sm.shutil.which = lambda name: (
            r"C:\Users\x\.local\bin\claude.exe" if name == "claude.exe" else None)
        try:
            out = sm.cli_summariser("claude-haiku-4-5")("line one\nline two")
        finally:
            sm.subprocess.run, sm.shutil.which = real_run, real_which

        self.assertEqual(out, "DECIDED: ok")
        self.assertEqual(seen["input"], "line one\nline two")
        self.assertTrue(seen["cmd"][0].endswith("claude.exe"))
        self.assertEqual(seen["cmd"][1:],
                         ["-p", "--model", "claude-haiku-4-5",
                          "--permission-mode", "plan"])
        for arg in seen["cmd"]:
            self.assertNotIn("\n", arg, "no multi-line argv element, ever")

    def test_model_is_configurable_by_env(self):
        before = os.environ.get(sm.MODEL_ENV)
        os.environ[sm.MODEL_ENV] = "some-cheap-model"
        try:
            seen: dict = {}

            class _Proc:
                returncode = 0
                stdout = "x"
                stderr = ""

            real_run, real_which = sm.subprocess.run, sm.shutil.which
            sm.subprocess.run = lambda cmd, **kw: (seen.update(cmd=cmd), _Proc())[1]
            sm.shutil.which = lambda name: "claude.exe"
            try:
                sm.cli_summariser()("prompt")
            finally:
                sm.subprocess.run, sm.shutil.which = real_run, real_which
            self.assertIn("some-cheap-model", seen["cmd"])
        finally:
            if before is None:
                os.environ.pop(sm.MODEL_ENV, None)
            else:
                os.environ[sm.MODEL_ENV] = before


class TestSidecarContract(RoomSummariseBase):
    def test_unreadable_sidecar_is_isolated_not_fatal(self):
        self.turns.mkdir(parents=True, exist_ok=True)
        (self.turns / "20260728T160000Z-assistant-bad.json").write_text(
            "{not json", encoding="utf-8")
        good = _write_turn(self.turns, "20260728T160100Z-assistant-good", "hello")
        fake = FakeSummariser()

        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake)
        self.assertEqual(report.scanned, 2)
        self.assertEqual(report.posted, 1, "one bad sidecar must not stop the pass")
        self.assertTrue(sm.marker_path(good).exists())

    def test_plain_text_sidecar_is_accepted(self):
        self.turns.mkdir(parents=True, exist_ok=True)
        path = self.turns / "20260728T161000Z-user-plain.txt"
        path.write_text("just some raw turn text", encoding="utf-8")
        fake = FakeSummariser()

        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake)
        self.assertEqual(report.posted, 1)
        self.assertIn("just some raw turn text", fake.prompts[0])
        self.assertIn("### Kaya (summary)", self.room_text(),
                      "role inferred from the filename")

    def test_the_real_hook_sidecar_layout_is_read(self):
        """The shape ``stream_hook.py:_sidecar`` actually writes.

        Nested under ``session/<day>/``, named ``tNNNN.md``, with a provenance
        header whose separator is a TWO-SPACE-padded dot -- while the tag field
        carries single-spaced dots of its own.
        """
        day = self.turns / "2026-07-28"
        day.mkdir(parents=True, exist_ok=True)
        sidecar = day / "t0007.md"
        sidecar.write_text(
            "_t0007  ·  Claude  ·  Anthropic · Fable 5 · live  ·  "
            "2026-07-28 11:57:09Z  ·  4,408 chars_\n\n"
            "Codex: rerun the floor check.\n\nThe body of the turn.\n",
            encoding="utf-8")
        fake = FakeSummariser("DECIDED: something.")

        report = sm.process_once(turns_dir=self.turns, room=self.room,
                                 summariser=fake)
        self.assertEqual(report.posted, 1, "a nested sidecar must be found")

        turn = sm.load_turn(sidecar)
        self.assertEqual(turn.id, "t0007")
        self.assertEqual(turn.name, "Claude")
        self.assertEqual(turn.tag, "Anthropic · Fable 5 · live",
                         "the tag's own dots must survive the header split")
        self.assertEqual(turn.role, "assistant")
        self.assertNotIn("chars_", turn.text,
                         "the provenance header is not part of the turn")
        self.assertTrue(turn.text.startswith("Codex: rerun the floor check."))
        self.assertNotIn("chars_", fake.prompts[0])

        room = self.room_text()
        self.assertIn("### Claude (summary)", room)
        self.assertIn("t0007", room)
        self.assertTrue((day / "t0007.summary.json").exists())

    def test_a_human_turn_is_recognised_from_the_header_tag(self):
        day = self.turns / "2026-07-28"
        day.mkdir(parents=True, exist_ok=True)
        (day / "t0008.md").write_text(
            "_t0008  ·  Kaya  ·  human · live  ·  2026-07-28 11:58:00Z  ·  20 chars_\n\n"
            "was denkst du dazu?\n", encoding="utf-8")

        turn = sm.load_turn(day / "t0008.md")
        self.assertEqual(turn.role, "user")
        self.assertEqual(turn.name, "Kaya")

    def test_markers_are_invisible_to_the_hooks_id_sequence(self):
        """The hook indexes on ``*/t*.md``. A marker must not enter that glob,
        or it would push the next turn's id and orphan the sequence."""
        day = self.turns / "2026-07-28"
        day.mkdir(parents=True, exist_ok=True)
        (day / "t0009.md").write_text(
            "_t0009  ·  Claude  ·  tag  ·  2026-07-28 12:00:00Z  ·  4 chars_\n\nbody\n",
            encoding="utf-8")

        sm.process_once(turns_dir=self.turns, room=self.room,
                        summariser=FakeSummariser())
        self.assertTrue((day / "t0009.summary.json").exists())
        self.assertEqual([p.name for p in self.turns.glob("*/t*.md")],
                         ["t0009.md"])

    def test_turns_are_ordered_by_the_monotonic_index_across_day_dirs(self):
        for day, idx in (("2026-07-28", 9), ("2026-07-29", 10), ("2026-07-28", 8)):
            d = self.turns / day
            d.mkdir(parents=True, exist_ok=True)
            (d / f"t{idx:04d}.md").write_text(
                f"_t{idx:04d}  ·  Claude  ·  tag  ·  2026-07-28 12:00:00Z  ·  4 chars_"
                f"\n\nbody {idx}\n", encoding="utf-8")
        self.assertEqual([p.stem for p in sm.pending_turns(self.turns)],
                         ["t0008", "t0009", "t0010"])

    def test_hook_dir_env_redirects_the_defaults(self):
        before = os.environ.get(sm.HOOK_DIR_ENV)
        os.environ[sm.HOOK_DIR_ENV] = str(self.root)
        try:
            self.assertEqual(sm.default_turns_dir(), self.root / "session")
            self.assertEqual(sm.default_room(), self.root / "room.md")
        finally:
            if before is None:
                os.environ.pop(sm.HOOK_DIR_ENV, None)
            else:
                os.environ[sm.HOOK_DIR_ENV] = before

    def test_markers_are_never_mistaken_for_turns(self):
        sidecar = _write_turn(self.turns, "20260728T162000Z-assistant-nnnn", "hi")
        sm.process_once(turns_dir=self.turns, room=self.room,
                        summariser=FakeSummariser())
        self.assertTrue(sm.marker_path(sidecar).exists())
        self.assertEqual(sm.pending_turns(self.turns), [],
                         "a .summary.json must not be picked up as a turn")


if __name__ == "__main__":
    unittest.main()

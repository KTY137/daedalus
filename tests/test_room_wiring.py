"""The room is wired to daedalus, not to a worse copy of it.

Every test here runs offline: no network, no vendor CLI, no model call. The
room's globals (``ROOM``, ``BUS_PATH``, ``REPO_ROOT``) are redirected into a
temp dir, so nothing touches the real transcript, the real chain or the real
cursors.

What is pinned:
  * the SECRET FLOOR still runs BEFORE distillation, and the withheld bytes
    reach no prompt;
  * the distilled attach is materially smaller than raw AND says so;
  * ``--raw`` still ships literal bytes;
  * every turn is chained, ``verify`` passes, and a flipped byte makes it fail
    BY POSITION;
  * the cursor sends only unseen turns with a VISIBLE omission notice, and a
    corrupt cursor degrades to sending everything;
  * ``--only`` refuses to INVOKE a speaker that is not addressed;
  * room_server.py still imports room.py and every symbol it uses resolves.
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
    room_server.py does (sys.path insert + ``import room``)."""
    if str(ROOM_DIR) not in sys.path:
        sys.path.insert(0, str(ROOM_DIR))
    spec = importlib.util.spec_from_file_location("room", ROOM_DIR / "room.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["room"] = mod
    spec.loader.exec_module(mod)
    return mod


room = _load_room()

# A distinctive value: if this string appears anywhere in a built prompt, the
# floor leaked. It is planted inside a shape the floor recognises.
SECRET_TOKEN = "ZZ-DER-RAUM-LEAK-CANARY-ZZ"
SECRET_BODY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    f"MIIEowIBAAKCAQEA{SECRET_TOKEN}\n"
    "-----END RSA PRIVATE KEY-----\n"
)

# A file comfortably over FOCUS_CHAR_CAP so the skeleton branch is exercised.
_BIG_FN = (
    "def fn_{i}(a, b, c=None):\n"
    '    """Doc for fn_{i}."""\n'
    "    total = a + b\n"
    "    for _ in range(10):\n"
    "        total += len(str(a)) + len(str(b)) + {i}\n"
    "    if c is not None:\n"
    "        total -= len(str(c))\n"
    "    return total\n\n\n"
)
BIG_BODY = ("import helper\n\n\n"
            + "".join(_BIG_FN.format(i=i) for i in range(60)))
HELPER_BODY = "def helper_fn(x):\n    return x * 2\n"


class RoomTestCase(unittest.TestCase):
    """Redirect the room into a temp dir and build a tiny indexable repo."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        (self.repo / "big.py").write_text(BIG_BODY, encoding="utf-8")
        (self.repo / "helper.py").write_text(HELPER_BODY, encoding="utf-8")
        (self.repo / "leaky.py").write_text(SECRET_BODY, encoding="utf-8")
        self.room_dir = base / "council"
        self.room_dir.mkdir()

        self._saved = {k: getattr(room, k)
                       for k in ("ROOM", "BUS_PATH", "REPO_ROOT")}
        room.ROOM = self.room_dir / "room.md"
        room.BUS_PATH = self.room_dir / "room.jsonl"
        room.REPO_ROOT = self.repo
        room._ensure()

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            setattr(room, k, v)
        self._tmp.cleanup()


# --------------------------------------------------------------------------
# 1. the secret floor still runs FIRST, and its bytes reach no prompt
# --------------------------------------------------------------------------
class SecretFloorSurvivesTheSlicer(RoomTestCase):

    def test_planted_secret_is_withheld_and_never_inlined(self):
        block = room._attach(["leaky.py"])
        self.assertIn("WITHHELD by the secret floor", block)
        self.assertNotIn(SECRET_TOKEN, block)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", block)

    def test_secret_bytes_appear_nowhere_in_the_built_prompt(self):
        prompt, _, _ = room.build_prompt(
            "ollama", "what is this?", ["leaky.py", "big.py"])
        self.assertNotIn(SECRET_TOKEN, prompt)
        # The refusal is NAMED, not silent: a speaker must know it was denied
        # evidence rather than believe the file was empty.
        self.assertIn("leaky.py", prompt)
        self.assertIn("WITHHELD by the secret floor", prompt)

    def test_the_floor_runs_before_distillation_not_after(self):
        # Ordering is the safety property, so prove it directly: the distiller
        # is booby-trapped, and a floored file must never reach it. Asserting on
        # the output alone would pass even if the floor ran second.
        saved = room._distill_one

        def trap(*a, **kw):
            raise AssertionError("the distiller was reached before the floor")

        room._distill_one = trap
        try:
            block = room._attach(["leaky.py"])
        finally:
            room._distill_one = saved
        self.assertIn("WITHHELD by the secret floor", block)
        self.assertNotIn(SECRET_TOKEN, block)

    def test_a_large_secret_file_is_floored_before_the_slicer_sees_it(self):
        # Size must not change the answer: a secret in a 20k file is still a
        # secret, and it must not reach the slicer to be "distilled" out.
        big_leak = (SECRET_BODY
                    + "".join(_BIG_FN.format(i=i) for i in range(60)))
        (self.repo / "big_leaky.py").write_text(big_leak, encoding="utf-8")
        self.assertGreater(len(big_leak), room.FOCUS_CHAR_CAP)
        block = room._attach(["big_leaky.py"])
        self.assertIn("WITHHELD by the secret floor", block)
        self.assertNotIn(SECRET_TOKEN, block)
        self.assertNotIn("SKELETON", block)

    def test_floor_unavailable_fails_closed(self):
        # No floor means no attachment. Ever.
        self.assertEqual(room._floor(".env", "anything"),
                         "secret path marker '.env'")


# --------------------------------------------------------------------------
# 2 + 3. distilled is materially smaller and honest; --raw is literal
# --------------------------------------------------------------------------
class DistilledAttach(RoomTestCase):

    def test_distilled_is_materially_smaller_than_raw(self):
        sizes = room.attach_sizes(["big.py"])
        self.assertGreater(sizes["raw"], sizes["distilled"])
        # "Materially" is a number, not an adjective: at least a 50% cut on a
        # file this size, or the wire is not earning its complexity.
        self.assertGreaterEqual(
            sizes["saved_pct"], 50.0,
            f"distillation saved only {sizes['saved_pct']}% "
            f"({sizes['raw']} -> {sizes['distilled']} chars)")

    def test_the_prompt_states_that_the_view_is_distilled(self):
        block = room._attach(["big.py"], lane="trusted")
        self.assertIn("DISTILLED VIEWS, NOT WHOLE FILES", block)
        self.assertIn("YOU ARE NOT", block)
        self.assertIn("SKELETON", block)

    def test_the_prompt_names_what_was_trimmed_or_omitted(self):
        block = room._attach(["big.py"], lane="trusted")
        # the per-file bracket carries the provenance, offload-style
        self.assertIn("signatures kept, all bodies omitted", block)
        self.assertIn("raw chars NOT sent", block)

    def test_distilled_keeps_signatures_but_drops_bodies(self):
        block = room._attach(["big.py"], lane="trusted")
        self.assertIn("def fn_0(a, b, c=None):", block)
        # a body line unique to the implementation must be gone
        self.assertNotIn("total -= len(str(c))", block)

    def test_raw_produces_the_literal_bytes(self):
        block = room._attach(["big.py"], raw=True)
        self.assertIn(BIG_BODY.strip(), block)
        self.assertIn("total -= len(str(c))", block)
        self.assertNotIn("DISTILLED VIEWS", block)

    def test_raw_still_runs_the_secret_floor(self):
        block = room._attach(["leaky.py"], raw=True)
        self.assertNotIn(SECRET_TOKEN, block)
        self.assertIn("WITHHELD by the secret floor", block)

    def test_small_files_are_not_forced_through_the_skeleton(self):
        # Below the cap the body is cheap; describing it would be worse.
        block = room._attach(["helper.py"])
        self.assertIn("def helper_fn(x):", block)
        self.assertIn("return x * 2", block)
        self.assertIn("under the", block)   # the reason is stated, not implied

    def test_no_file_is_ever_inlined_larger_than_its_own_body(self):
        # The invariant the whole feature rests on. A "distillation" that grows
        # the prompt is a lie, and the slicer WILL grow it if handed a generous
        # budget -- _distill_one's cap and guard exist for exactly that.
        for rel in ("big.py", "helper.py"):
            body = (self.repo / rel).read_text(encoding="utf-8")
            info = room._distill_one(rel, body, 40000)
            self.assertLessEqual(
                len(info["text"]), len(body),
                f"{rel}: distilled {len(info['text'])} > raw {len(body)}")

    def test_a_set_containing_a_large_file_shrinks_overall(self):
        for paths in (["big.py"], ["big.py", "helper.py"],
                      ["big.py", "helper.py", "leaky.py"]):
            z = room.attach_sizes(paths)
            self.assertLess(z["distilled"], z["raw"],
                            f"{paths}: {z['raw']} -> {z['distilled']}")

    def test_a_small_file_is_sent_whole_and_the_only_growth_is_provenance(self):
        # Below the cap nothing is shrunk; the block grows only by the bracket
        # that tells the speaker it IS looking at complete evidence.
        body = (self.repo / "helper.py").read_text(encoding="utf-8")
        z = room.attach_sizes(["helper.py"])
        dist = room._attach(["helper.py"])
        self.assertIn(body.strip(), dist)
        self.assertLess(z["distilled"] - z["raw"], 300)

    def test_a_tight_budget_truncates_raw_but_fits_distilled(self):
        # Raw attach spends its budget on the first file and drops the rest;
        # the distilled attach represents every file.
        budget = len(BIG_BODY) // 2
        raw = room._attach(["big.py", "helper.py"], budget, raw=True)
        dist = room._attach(["big.py", "helper.py"], budget)
        self.assertIn("truncated at", raw)
        self.assertNotIn("def helper_fn(x):", raw)
        self.assertIn("def helper_fn(x):", dist)


# --------------------------------------------------------------------------
# 4. the tamper-evident mirror
# --------------------------------------------------------------------------
class ChainedMirror(RoomTestCase):

    def _say(self, who, text, model="test-model"):
        with contextlib.redirect_stdout(io.StringIO()):
            room.say(who, text, model=model)

    def test_every_turn_lands_in_the_bus_and_verify_passes(self):
        self._say("kaya", "first turn")
        self._say("ollama", "second turn")
        self._say("codex", "third turn")
        self.assertTrue(room.BUS_PATH.exists())
        attested, total = room.chain_coverage()
        self.assertEqual((attested, total), (3, 3))
        ok, failures = room.verify_room()
        self.assertTrue(ok, failures)

    def test_a_flipped_byte_makes_verify_fail_and_names_the_position(self):
        self._say("kaya", "alpha")
        self._say("ollama", "bravo")
        lines = room.BUS_PATH.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["content"] = "bravo-TAMPERED"
        lines[1] = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        room.BUS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok, failures = room.verify_room()
        self.assertFalse(ok)
        blob = " | ".join(failures)
        # the chain walk names the 1-indexed LINE ...
        self.assertIn("line 2", blob)
        self.assertIn("body_sha mismatch", blob)
        # ... and the markdown cross-check names the TURN
        self.assertIn("turn 1", blob)

    def test_a_silent_markdown_rewrite_is_detected_by_position(self):
        self._say("kaya", "the original claim")
        self._say("ollama", "a reply")
        text = room.ROOM.read_text(encoding="utf-8")
        room.ROOM.write_text(
            text.replace("the original claim", "a claim never made"),
            encoding="utf-8")
        ok, failures = room.verify_room()
        self.assertFalse(ok)
        self.assertTrue(
            any("turn 0" in f and "does not match chained record" in f
                for f in failures), failures)

    def test_a_truncated_tail_is_detected_against_the_anchor(self):
        self._say("kaya", "one")
        self._say("ollama", "two")
        lines = room.BUS_PATH.read_text(encoding="utf-8").splitlines()
        room.BUS_PATH.write_text(lines[0] + "\n", encoding="utf-8")
        ok, failures = room.verify_room()
        self.assertFalse(ok)
        self.assertTrue(any("truncated" in f for f in failures), failures)

    def test_turns_predating_the_mirror_are_reported_not_failed(self):
        # A room that existed before the chain did: the attested range verifies,
        # and the uncovered turns are counted rather than silently blessed.
        room.ROOM.write_text(
            "# Der Raum\n\n"
            f"\n---\n\n### Kaya  {room.DOT}  human  {room.DOT}  00:00:01\n\n"
            "an older turn\n",
            encoding="utf-8")
        self._say("ollama", "the first chained turn")
        ok, failures = room.verify_room()
        self.assertTrue(ok, failures)
        self.assertEqual(room.chain_coverage(), (1, 2))

    def test_the_chained_actor_carries_vendor_and_model(self):
        self._say("ollama", "hello", model="qwen2.5-coder:7b")
        rec = json.loads(room.BUS_PATH.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(rec["actor"], "council.ollama.qwen2.5-coder:7b")
        self.assertEqual(rec["independence_class"],
                         {"vendor": "alibaba", "family": "qwen2.5-coder"})

    def test_the_three_anthropic_heads_share_one_independence_class(self):
        # A room of clones must be visible as one voice, not three.
        classes = {room.CLASSES[k]["family"]
                   for k in ("claude", "fable", "opus")}
        self.assertEqual(classes, {"claude"})


# --------------------------------------------------------------------------
# 5. the unread cursor
# --------------------------------------------------------------------------
class UnreadCursor(RoomTestCase):

    def _say(self, who, text):
        with contextlib.redirect_stdout(io.StringIO()):
            room.say(who, text)

    def test_only_unseen_turns_are_sent_and_the_gap_is_visible(self):
        self._say("kaya", "TURN-ONE")
        self._say("kaya", "TURN-TWO")
        self._say("ollama", "OLLAMA-SPOKE")   # advances ollama's cursor to 3
        self._say("kaya", "TURN-FOUR")

        prompt, total, seen = room.build_prompt("ollama")
        self.assertEqual((total, seen), (4, 3))
        self.assertIn("TURN-FOUR", prompt)
        self.assertNotIn("TURN-ONE", prompt)
        self.assertNotIn("TURN-TWO", prompt)
        # The trim is NAMED. A speaker must never be quietly given less.
        self.assertIn("3 earlier turns omitted", prompt)
        self.assertIn("This is not the whole room", prompt)

    def test_full_overrides_the_cursor(self):
        self._say("kaya", "TURN-ONE")
        self._say("ollama", "OLLAMA-SPOKE")
        prompt, total, seen = room.build_prompt("ollama", full=True)
        self.assertEqual(seen, 0)
        self.assertIn("TURN-ONE", prompt)
        self.assertNotIn("earlier turns omitted", prompt)

    def test_a_corrupt_cursor_file_degrades_to_sending_everything(self):
        self._say("kaya", "TURN-ONE")
        self._say("ollama", "OLLAMA-SPOKE")
        room.state_file().write_text("{not json at all", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            prompt, total, seen = room.build_prompt("ollama")
        self.assertEqual(seen, 0)
        self.assertIn("TURN-ONE", prompt)
        # loud, not silent
        self.assertIn("sending full transcript", err.getvalue())

    def test_a_missing_cursor_file_sends_everything(self):
        self._say("kaya", "TURN-ONE")
        room.state_file().unlink()
        _, _, seen = room.build_prompt("ollama")
        self.assertEqual(seen, 0)

    def test_a_cursor_past_the_end_rewinds_instead_of_skipping(self):
        self._say("kaya", "TURN-ONE")
        room.set_cursor("ollama", 99)
        _, total, seen = room.build_prompt("ollama")
        self.assertEqual((total, seen), (1, 0))

    def test_the_cursor_write_is_atomic(self):
        # No .tmp left behind, and the file parses after a write.
        self._say("kaya", "TURN-ONE")
        self.assertFalse((room.state_file().with_suffix(".json.tmp")).exists())
        json.loads(room.state_file().read_text(encoding="utf-8"))

    def test_a_horizontal_rule_inside_a_turn_does_not_split_it(self):
        self._say("ollama", "before\n\n---\n\nafter")
        turns = room.parse_turns(room.transcript())
        self.assertEqual(len(turns), 1)
        self.assertIn("before", turns[0].body)
        self.assertIn("after", turns[0].body)


# --------------------------------------------------------------------------
# 6. addressed-only floor control
# --------------------------------------------------------------------------
class AddressedOnlyFloor(RoomTestCase):

    def _run(self, argv):
        calls = []

        def fake(*a, **kw):
            calls.append((a, kw))
            return "a reply that should never happen"

        saved = {k: getattr(room, k) for k in
                 ("ask_ollama", "ask_codex", "ask_opus", "ask_agy", "ask_fable")}
        for k in saved:
            setattr(room, k, fake)
        saved_argv = sys.argv
        sys.argv = ["room.py"] + argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()) as err:
                code = room.main()
            return code, calls, err.getvalue()
        finally:
            sys.argv = saved_argv
            for k, v in saved.items():
                setattr(room, k, v)

    def test_only_refuses_to_invoke_a_non_addressed_speaker(self):
        room.set_floor("codex")
        code, calls, err = self._run(["ask", "ollama"])
        self.assertEqual(code, room.EXIT_NOT_ADDRESSED)
        self.assertEqual(calls, [], "a non-addressed vendor was invoked anyway")
        self.assertIn("not addressed", err)
        # and nothing was appended to the room
        self.assertEqual(room.parse_turns(room.transcript()), [])

    def test_only_sets_the_floor_and_lets_the_addressed_speaker_through(self):
        code, calls, _ = self._run(["ask", "ollama", "--only", "ollama"])
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(room.load_state()["floor"], "ollama")

    def test_the_floor_is_persisted_across_invocations(self):
        self._run(["ask", "ollama", "--only", "ollama"])
        code, calls, _ = self._run(["ask", "codex"])
        self.assertEqual(code, room.EXIT_NOT_ADDRESSED)
        self.assertEqual(calls, [])

    def test_clearing_the_floor_reopens_the_room(self):
        room.set_floor("codex")
        self.assertFalse(room.is_addressed("ollama"))
        room.set_floor(None)
        self.assertTrue(room.is_addressed("ollama"))

    def test_a_held_floor_is_named_in_the_prompt(self):
        room.set_floor("codex")
        prompt, _, _ = room.build_prompt("ollama", addressed=False)
        self.assertIn("addressed-only mode", prompt)
        self.assertIn("You are NOT addressed", prompt)


# --------------------------------------------------------------------------
# 7. the GUI regression guard
# --------------------------------------------------------------------------
class RoomServerStillImports(unittest.TestCase):
    """room_server.py drives a GUI off room.py's helpers. Import it for real and
    resolve every symbol it touches: a renamed helper here is a broken GUI."""

    USED = ["ROOM", "BENCH", "SPEAKERS", "transcript", "say",
            "ask_codex", "ask_ollama", "ask_agy", "_exe"]

    def test_room_server_imports(self):
        if str(ROOM_DIR) not in sys.path:
            sys.path.insert(0, str(ROOM_DIR))
        spec = importlib.util.spec_from_file_location(
            "room_server", ROOM_DIR / "room_server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "room"))

    def test_every_symbol_the_gui_uses_still_resolves(self):
        for name in self.USED:
            self.assertTrue(hasattr(room, name), f"room.{name} disappeared")

    def test_the_gui_call_signatures_still_accept_their_keywords(self):
        import inspect
        for fn, kwargs in (
            (room.ask_codex, ("extra", "timeout", "attach")),
            (room.ask_ollama, ("model", "extra", "timeout", "attach")),
            (room.ask_agy, ("model", "extra", "timeout", "attach")),
        ):
            params = inspect.signature(fn).parameters
            for kw in kwargs:
                self.assertIn(kw, params, f"{fn.__name__} lost keyword {kw}")

    def test_say_still_accepts_two_positional_arguments(self):
        import inspect
        params = list(inspect.signature(room.say).parameters.values())
        self.assertGreaterEqual(len(params), 2)
        for p in params[2:]:
            self.assertIsNot(p.default, inspect.Parameter.empty,
                             "new say() parameters must be optional")

    def test_speakers_values_are_still_two_tuples(self):
        # room_server indexes SPEAKERS.get(...)[0] and [1].
        for key, val in room.SPEAKERS.items():
            self.assertEqual(len(val), 2, f"SPEAKERS[{key}] changed shape")


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- #
# the ssh RCE class -- the prompt is NEVER part of a remote command string      #
# --------------------------------------------------------------------------- #
def test_the_agy_ssh_path_never_builds_a_remote_command_from_the_prompt():
    """`ssh host CMD` hands CMD to the REMOTE shell, which re-parses it.

    This module used to stage the prompt to a file and run
    ``agy -p "$(type FILE)"``. ``$(...)`` is command substitution performed on
    the bench, over a file holding room prompts -- and room prompts carry diffs.
    A patch containing backticks or ``$(...)`` therefore executed remotely as
    Administrator with no adversarial model involved.

    Structural, and it deliberately ignores comments: the fix is only real if no
    LIVE line reconstructs it. ``daedalus/council/vendors.py`` documents and
    tests the same invariant; this file is the second implementation and did not
    inherit it, which is why the check now lives in both places.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "runs" / "council" / "room.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):        # an f-string
            continue
        literal = "".join(p.value for p in node.values
                          if isinstance(p, ast.Constant) and isinstance(p.value, str))
        if "$(" in literal or "`" in literal:
            offenders.append((getattr(node, "lineno", "?"), literal[:60]))
    assert not offenders, (
        f"an f-string builds shell substitution syntax: {offenders}")


def test_the_agy_ssh_argv_is_fixed_and_reads_the_prompt_from_stdin():
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "runs" / "council"
              / "room.py").read_text(encoding="utf-8")
    body = source[source.index("def ask_agy"):]
    body = body[:body.index("\ndef ")]

    # "agy -p -" == prompt on stdin, and the prompt must be handed over as input.
    assert '"agy", "-p", "-"' in body, "the prompt is not being read from stdin"
    assert "input=prompt" in body, "the prompt was not passed to the process"
    # No caller-controlled text may be concatenated into a command string.
    assert not re.search(r'cmd\s*\+=', body), "a remote command string is built again"


class AttachmentLaneIsDecidedByTheSpeaker(RoomTestCase):
    """Tier 2 follows the SPEAKER, because an attachment is egress.

    The distilled neighbourhood was built at ``lane="trusted"`` unconditionally
    and then handed to whoever spoke next -- including codex and agy, which are
    other vendors. The secret floor did run (on raw bytes, first, and that part
    was always right); the default-deny allow-list never did.
    """

    def test_an_external_speaker_gets_the_default_deny_gate(self):
        block = room._attach(["big.py"], lane="untrusted")
        self.assertIn("WITHHELD by the egress gate", block)
        self.assertIn("default-deny", block)
        self.assertNotIn("def fn_0(a, b, c=None):", block,
                         "source reached an untrusted lane")

    def test_a_trusted_speaker_still_gets_the_distilled_view(self):
        # The control: without it, an _attach that withheld everything would
        # pass the test above and silently break the room.
        block = room._attach(["big.py"], lane="trusted")
        self.assertIn("def fn_0(a, b, c=None):", block)

    def test_the_lane_defaults_to_fail_closed(self):
        self.assertIn("WITHHELD by the egress gate", room._attach(["big.py"]))

    def test_speaker_lanes(self):
        self.assertEqual(room._speaker_lane("claude"), "trusted")
        for external in ("codex", "agy", "kaya"):
            self.assertEqual(room._speaker_lane(external), "untrusted", external)

    def test_the_ollama_speaker_is_judged_by_its_endpoint_not_its_name(self):
        # This room's ollama speaker talks to the RTX BENCH by default -- a
        # different machine. Reading OLLAMA_HOST here would call that "trusted".
        self.assertEqual(room._speaker_lane("ollama"), "untrusted")
        self.assertEqual(room._speaker_lane("ollama", "http://127.0.0.1:11434"),
                         "trusted")
        self.assertEqual(room._speaker_lane("ollama", room.BENCH), "untrusted")

    def test_build_prompt_ACTUALLY_applies_the_speakers_lane(self):
        """The WIRING, not the parts.

        Added because disabling the wiring changed nothing: every other test
        here calls ``_attach(lane=...)`` or ``_speaker_lane()`` directly, so
        both halves could be perfect while ``build_prompt`` passed a hardcoded
        lane between them and no test noticed. Same shape as a guard whose
        absence nothing detects -- the parts were tested, the connection was
        not.
        """
        external, _, _ = room.build_prompt("codex", extra="review this",
                                           attach=["big.py"])
        self.assertIn("WITHHELD by the egress gate", external)
        self.assertNotIn("def fn_0(a, b, c=None):", external,
                         "source reached an external speaker's prompt")

        trusted, _, _ = room.build_prompt("claude", extra="review this",
                                          attach=["big.py"])
        self.assertIn("def fn_0(a, b, c=None):", trusted,
                      "the trusted speaker lost its distilled view")

    def test_build_prompt_judges_ollama_by_the_host_it_will_dispatch_to(self):
        bench, _, _ = room.build_prompt("ollama", attach=["big.py"],
                                        speaker_host=room.BENCH)
        self.assertIn("WITHHELD by the egress gate", bench)

        local, _, _ = room.build_prompt("ollama", attach=["big.py"],
                                        speaker_host="http://127.0.0.1:11434")
        self.assertIn("def fn_0(a, b, c=None):", local)


class OneAppendBoundary(RoomTestCase):
    """Every writer enters the room through append_turn, and it chains.

    THE DEFECT THIS PINS, found by the acceptance run and diagnosed in review:
    `verify` reported turns 30-32 as "inside the attested range but MISSING
    from the chain". The detection was correct; the cause was that there were
    TWO writers and only `say()` knew about the mirror -- `stream_hook.py`
    appended with its own `open(..., "a")`. Same class as every other finding
    this week: a second implementation that did not inherit the invariant.
    """

    def test_append_turn_appends_AND_chains(self):
        before = len(room.parse_turns(room.transcript()))
        res = room.append_turn("kaya", "a turn that must be attested")
        self.assertTrue(res["ok"], f"the turn was not chained: {res.get('error')}")
        self.assertEqual(res["turns"], before + 1)
        ok, failures = room.verify_room()
        self.assertTrue(ok, f"chain broke after one append: {failures}")

    def test_say_goes_through_the_same_boundary(self):
        room.say("kaya", "spoken through say()")
        ok, failures = room.verify_room()
        self.assertTrue(ok, f"say() left the chain inconsistent: {failures}")

    def test_many_appends_leave_no_gap(self):
        for i in range(5):
            room.append_turn("kaya", f"turn {i}")
        ok, failures = room.verify_room()
        self.assertTrue(ok, f"gaps after repeated appends: {failures}")
        self.assertFalse([f for f in failures if "mirror gap" in f])

    def test_a_stream_hook_turn_LANDS_IN_THE_CHAIN(self):
        """BEHAVIOUR, not a string search.

        Two earlier versions of this test asserted that the source contains
        "append_turn" -- which stayed true after the call was reverted, because
        the word also appears in the comment explaining it. Reverting the fix
        changed nothing and the suite stayed green: a guard whose absence
        nothing detects, in the test for a guard. The only thing that settles
        it is driving the hook and asking the verifier.
        """
        import importlib.util
        from pathlib import Path as _P

        hook_path = _P(room.__file__).parent / "stream_hook.py"
        spec = importlib.util.spec_from_file_location("stream_hook_probe", hook_path)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        hook._room_path = lambda: room.ROOM        # point it at the test room
        hook._hook_dir = lambda: room.ROOM.parent

        # Establish a chained turn FIRST. In a room with no chained records at
        # all, `seen` is empty and verify_room checks nothing -- so a test that
        # starts from an empty room cannot observe an unmirrored turn no matter
        # how broken the writer is.
        room.append_turn("claude", "an attested turn, so the chain is running")

        before = len(room.parse_turns(room.transcript()))
        hook._append("Kaya", "human · live", "a turn mirrored by the hook")
        after = len(room.parse_turns(room.transcript()))
        self.assertEqual(after, before + 1, "the hook did not append a turn")

        ok, failures = room.verify_room()
        gaps = [f for f in failures if "mirror gap" in f]
        self.assertFalse(gaps, f"the hook's turn was not chained: {gaps}")
        self.assertTrue(ok, f"chain inconsistent after a hook turn: {failures}")

    def test_a_failed_mirror_goes_to_a_DEAD_LETTER_not_the_markdown(self):
        """The escape hatch must not reintroduce the bug it escapes.

        Appending directly and letting `verify` report the gap was the obvious
        fallback and the wrong one: `verify` makes an invariant break VISIBLE,
        it does not PREVENT one. A turn that cannot be chained is spooled and
        replayed through the same door, so the room never holds a turn the
        chain does not know about.
        """
        import importlib.util
        from pathlib import Path as _P

        hook_path = _P(room.__file__).parent / "stream_hook.py"
        spec = importlib.util.spec_from_file_location("stream_hook_dl", hook_path)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        hook._room_path = lambda: room.ROOM
        hook._hook_dir = lambda: room.ROOM.parent

        room.append_turn("claude", "an attested turn")
        before = len(room.parse_turns(room.transcript()))

        # Break the append boundary the way a bad import would.
        saved = room.append_turn
        room.append_turn = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            hook._append("Kaya", "human", "a turn that cannot be chained")
        finally:
            room.append_turn = saved

        after = len(room.parse_turns(room.transcript()))
        self.assertEqual(after, before,
                         "the fallback appended an UNATTESTED turn to the room")
        spool = room.ROOM.parent / "dead_letter.jsonl"
        self.assertTrue(spool.exists(), "the turn was lost entirely")
        rec = json.loads(spool.read_text(encoding="utf-8").splitlines()[-1])
        self.assertIn("cannot be chained", rec["body"])

        ok, failures = room.verify_room()
        self.assertTrue(ok, f"the chain must stay clean: {failures}")

    def test_the_stream_hook_no_longer_writes_the_markdown_directly(self):
        # Structural: a second writer is exactly how the gap appeared, so the
        # fix is only real if the direct append is not simply back.
        import ast
        from pathlib import Path as _P

        src = (_P(room.__file__).parent / "stream_hook.py").read_text(encoding="utf-8")
        self.assertIn("append_turn", src,
                      "the stream hook does not use the room's append boundary")
        # AST, not text. Two earlier versions of this assertion were wrong in
        # the same way and both are worth remembering: the first flagged the
        # module's own diagnostics log (a check that cannot tell the artifact
        # from the logbook), and the second matched the COMMENT that documents
        # the removed code -- the identical trap as grepping `--help` for
        # "--apply" and hitting the sentence that says the flag does not exist.
        # Comments are not code.
        tree = ast.parse(src)
        room_appends = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "open"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "room"
                    and any(isinstance(a, ast.Constant) and a.value == "a"
                            for a in node.args)):
                room_appends.append(getattr(node, "lineno", "?"))
        self.assertLessEqual(
            len(room_appends), 1,
            f"more than one direct markdown append at lines {room_appends}; "
            f"exactly one documented fallback is allowed")

    def test_the_room_lock_is_cross_process_not_a_thread_lock(self):
        # bus._WRITE_LOCK is a threading.Lock, which never applied to the case
        # that actually happens here: separate PROCESSES (CLI, GUI, and a hook
        # that fires for every Claude Code session on the machine).
        import inspect

        src = inspect.getsource(room._RoomLock)
        self.assertTrue("msvcrt" in src or "fcntl" in src,
                        "the room lock does not take an OS-level file lock")

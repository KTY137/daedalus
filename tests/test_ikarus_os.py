"""ikarus_os — deterministic intent layer + safe brain routing.

No real LLM calls happen here: every case uses provider=None or an unwired
provider, so the deterministic path answers. Verifies ENQUEUE only *proposes*
(nothing executes) and the safety-preserving routing.
"""
import unittest
from unittest import mock

from daedalus.orchestration.ikarus import shell as ikarus_os


class ClassifyTest(unittest.TestCase):
    def test_intents(self):
        self.assertEqual(ikarus_os.classify("what's running?"), "status")
        self.assertEqual(ikarus_os.classify("distill gui/motor_panel.py"), "distill")
        self.assertEqual(ikarus_os.classify("show duplicate clones"), "distill")
        self.assertEqual(ikarus_os.classify("build a settings dialog"), "enqueue")
        self.assertEqual(ikarus_os.classify("Mach den Parser robuster"), "enqueue")
        self.assertEqual(ikarus_os.classify("Prüf die Tests"), "enqueue")
        self.assertEqual(ikarus_os.classify("Schau dir core.py an"), "enqueue")
        self.assertEqual(ikarus_os.classify("Kannst du das bitte bauen?"), "enqueue")
        # The classifier may broadly choose the enqueue affordance, but the
        # independent capability predicate keeps this ordinary discussion out
        # of the Hand (pinned in test_ikarus_act.py).
        self.assertEqual(ikarus_os.classify("Was machen wir jetzt?"), "enqueue")
        self.assertEqual(ikarus_os.classify("design an agent network with UI and QA"), "design")
        self.assertEqual(ikarus_os.classify("hello, who are you?"), "chat")
        self.assertEqual(ikarus_os.classify("how does the machine work?"), "chat")
        self.assertEqual(ikarus_os.classify("Test coverage is low."), "chat")
        self.assertEqual(ikarus_os.classify("Start time is slow."), "chat")


class AskTest(unittest.TestCase):
    PROJECT = "sunny_garden"

    def test_lane_copy_does_not_promise_an_unbrokered_claude_fallback(self):
        for lane in ("local", "auto", "claude", "codex"):
            note = ikarus_os._lane_note(lane, german=False)
            self.assertIn("broker", note)
            self.assertNotIn("may incur cost", note)

    def test_enqueue_proposes_only_on_the_project_owned_lane(self):
        with mock.patch.object(ikarus_os.core, "team_config",
                               return_value={"default_lane": "codex"}):
            res = ikarus_os.ask(self.PROJECT, "build a login page", provider="claude")
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["action"]["kind"], "queue_task")
        self.assertTrue(res["action"]["requires_confirmation"])
        self.assertEqual(res["action"]["args"]["lane"], "codex")
        self.assertIn("currently disabled", res["assistant"])

    def test_unknown_project_lane_fails_closed(self):
        with mock.patch.object(ikarus_os.core, "team_config",
                               return_value={"default_lane": "surprise"}), \
             mock.patch.object(ikarus_os, "_hand_state", return_value=None):
            res = ikarus_os.ask(self.PROJECT, "build a login page", provider="claude")
        self.assertEqual(res["action"]["args"]["lane"], "local_only")

    def test_german_imperative_reaches_hand_and_answers_in_german(self):
        with mock.patch.object(ikarus_os.core, "team_config",
                               return_value={"default_lane": "codex"}):
            res = ikarus_os.ask(self.PROJECT, "Mach den Parser robuster", provider="claude")
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["shell"], ikarus_os.SHELL_HAND)
        self.assertEqual(res["action"]["args"]["lane"], "codex")
        self.assertIn("Ich kann", res["assistant"])

    def test_german_question_offers_confirmation_but_does_not_enqueue(self):
        with mock.patch.object(ikarus_os.core, "team_config",
                               return_value={"default_lane": "codex"}):
            res = ikarus_os.ask(self.PROJECT, "Kannst du das bitte bauen?", provider=None)
        self.assertEqual(res["intent"], "chat")
        self.assertNotIn("action", res)
        self.assertEqual(res["act_offer"]["objective"], "Kannst du das bitte bauen?")
        self.assertIn("nichts gestartet", res["assistant"])

    def test_non_local_lane_does_not_probe_or_refuse_on_local_health(self):
        act = ikarus_os.ActDecision(
            True, "confirmed", objective="Mach es", confirmation_of="Mach es")
        with mock.patch.object(ikarus_os.core, "team_config",
                               return_value={"default_lane": "codex"}), \
             mock.patch.object(ikarus_os, "_hand_state",
                               side_effect=AssertionError("local probe must not run")):
            res = ikarus_os._enqueue(self.PROJECT, "Mach es", act=act)
        self.assertEqual(res["action"]["args"]["lane"], "codex")

    def test_explicit_deterministic_voice_is_deterministic(self):
        res = ikarus_os.ask(self.PROJECT, "hello there", provider="deterministic")
        self.assertEqual(res["provider_used"], "deterministic")
        self.assertIn("Ikarus", res["assistant"])

    def test_generic_german_chat_gets_german_deterministic_voice(self):
        res = ikarus_os.ask(
            self.PROJECT, "Das ist nicht richtig", provider="deterministic")
        self.assertEqual(res["provider_used"], "deterministic")
        self.assertIn("Ich bin Ikarus", res["assistant"])

    def test_every_german_action_verb_selects_a_german_reply(self):
        for message in ("Refaktoriere den Router", "Generiere die Typen",
                        "Benenne die alte Datei um"):
            with self.subTest(message=message):
                self.assertTrue(ikarus_os._reply_in_german(message))

    def test_unwired_provider_fails_closed_without_impersonating_a_voice(self):
        # a picker-visible but not-yet-wired runtime must not error or execute.
        # codex_cli was the example here until it got a real _llm branch;
        # "gemini" is a runtime the registry knows but chat does not.
        res = ikarus_os.ask(self.PROJECT, "hello there", provider="gemini")
        self.assertEqual(res["provider_used"], "unavailable")
        self.assertEqual(res["intent"], "error")

    def test_status_reads_the_bus(self):
        res = ikarus_os.ask(self.PROJECT, "what's running?", provider=None)
        self.assertEqual(res["intent"], "status")
        self.assertIn("Queue", res["assistant"])

    def test_empty_message(self):
        res = ikarus_os.ask(self.PROJECT, "   ", provider=None)
        self.assertEqual(res["intent"], "chat")


if __name__ == "__main__":
    unittest.main()

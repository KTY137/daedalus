"""ikarus_os — deterministic intent layer + safe brain routing.

No real LLM calls happen here: every case uses provider=None or an unwired
provider, so the deterministic path answers. Verifies ENQUEUE only *proposes*
(nothing executes) and the safety-preserving routing.
"""
import unittest

from daedalus import ikarus_os


class ClassifyTest(unittest.TestCase):
    def test_intents(self):
        self.assertEqual(ikarus_os.classify("what's running?"), "status")
        self.assertEqual(ikarus_os.classify("distill gui/motor_panel.py"), "distill")
        self.assertEqual(ikarus_os.classify("show duplicate clones"), "distill")
        self.assertEqual(ikarus_os.classify("build a settings dialog"), "enqueue")
        self.assertEqual(ikarus_os.classify("design an agent network with UI and QA"), "design")
        self.assertEqual(ikarus_os.classify("hello, who are you?"), "chat")


class AskTest(unittest.TestCase):
    PROJECT = "sunny_garden"

    def test_enqueue_proposes_only(self):
        res = ikarus_os.ask(self.PROJECT, "build a login page", provider=None)
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["action"]["kind"], "queue_task")
        self.assertTrue(res["action"]["requires_confirmation"])
        self.assertEqual(res["action"]["args"]["lane"], "local_only")

    def test_explicit_deterministic_voice_is_deterministic(self):
        res = ikarus_os.ask(self.PROJECT, "hello there", provider="deterministic")
        self.assertEqual(res["provider_used"], "deterministic")
        self.assertIn("Ikarus", res["assistant"])

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

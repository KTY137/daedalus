# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""_schema_rescue returns a REASON, not a bare empty list.

The rescue used to answer three different worlds with the same value: the bench
never answered, the model answered with garbage, and the model said it was
finished all produced ``[]``. Only the third means "done". This file pins that
they are now distinguishable, and that the two failures stop the turn loudly
instead of being read as a finished report.
"""
import json
import unittest
from unittest import mock

from daedalus.providers import ollama as O
from daedalus.providers._openai_compat import ProviderHTTPError

_TOOLS = [{"function": {"name": "write_file"}}, {"function": {"name": "read_file"}}]
_MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
_DONE_REPORT = json.dumps({"status": "done", "summary": "described the edit",
                           "files_changed": [], "tests_run": [],
                           "risks": [], "todos": []})


class RescueOutcomeTest(unittest.TestCase):
    def setUp(self):
        self.p = O.OllamaProvider()

    def _rescue(self, **patch):
        with mock.patch.object(O, "native_chat", **patch):
            return self.p._schema_rescue(_MSGS, "m", _TOOLS, 5)

    def test_a_tool_call_is_returned_with_its_name(self):
        out = self._rescue(return_value={"content": json.dumps(
            {"action": "write_file", "path": "a.py", "content": "x = 1"})})
        self.assertEqual(out.kind, O.RESCUE_CALLS)
        self.assertEqual(len(out.calls), 1)
        self.assertEqual(out.calls[0]["function"]["name"], "write_file")
        self.assertEqual(json.loads(out.calls[0]["function"]["arguments"]),
                         {"path": "a.py", "content": "x = 1"})

    def test_finished_is_the_only_empty_result_that_means_done(self):
        for content in ('{"action": "finish"}', '{"action": ""}', '{}'):
            with self.subTest(content=content):
                out = self._rescue(return_value={"content": content})
                self.assertEqual(out.calls, [])
                self.assertEqual(out.kind, O.RESCUE_FINISHED)

    def test_an_unreachable_bench_is_named_as_such(self):
        for exc in (ProviderHTTPError("503 from the bench"), OSError("refused")):
            with self.subTest(exc=type(exc).__name__):
                out = self._rescue(side_effect=exc)
                self.assertEqual(out.calls, [])
                self.assertEqual(out.kind, O.RESCUE_UNREACHABLE)
                self.assertIn(type(exc).__name__, out.detail)

    def test_a_malformed_answer_is_named_as_such(self):
        for content in ("not json at all", "", "[1, 2, 3]", '"a string"'):
            with self.subTest(content=content):
                out = self._rescue(return_value={"content": content})
                self.assertEqual(out.calls, [])
                self.assertEqual(out.kind, O.RESCUE_MALFORMED)
                self.assertTrue(out.detail)

    def test_the_three_failure_worlds_are_distinguishable(self):
        kinds = {
            self._rescue(side_effect=ProviderHTTPError("x")).kind,
            self._rescue(return_value={"content": "nonsense"}).kind,
            self._rescue(return_value={"content": '{"action":"finish"}'}).kind,
        }
        self.assertEqual(len(kinds), 3, f"collapsed into {kinds}")

    def test_the_rescue_still_never_raises(self):
        for exc in (ProviderHTTPError("x"), OSError("y"), TimeoutError("z")):
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(self._rescue(side_effect=exc).calls, [])


class LoudFailureInTheLoopTest(unittest.TestCase):
    """A write turn that wrote nothing and could not be rescued is BLOCKED."""

    def setUp(self):
        self.p = O.OllamaProvider()
        self.agent = {"call_name": "t", "name": "tester"}

    def _run(self, rescue_kind, detail="d"):
        # A json-shaped "I am done" report -- what the three zero-tool-call
        # models actually emit, and what the old code read as success.
        prose = {"content": _DONE_REPORT}
        rescue = O.RescueOutcome([], rescue_kind, detail)
        with mock.patch.object(O, "native_chat", return_value=prose), \
                mock.patch.object(O.OllamaProvider, "_schema_rescue",
                                  return_value=rescue):
            return self.p._run_agentic("do a thing", ".", [], self.agent, "m",
                                       5, {}, writable=True)

    def test_an_unreachable_rescue_blocks_instead_of_reporting_success(self):
        rep = self._run(O.RESCUE_UNREACHABLE, "ProviderHTTPError: 503")
        self.assertEqual(rep["status"], "blocked")
        self.assertIn("unreachable", rep["summary"])
        self.assertIn("503", rep["summary"])
        self.assertEqual(rep["files_changed"], [])
        self.assertEqual(rep["handoff"]["rescue_kind"], O.RESCUE_UNREACHABLE)

    def test_a_malformed_rescue_blocks_too(self):
        rep = self._run(O.RESCUE_MALFORMED, "JSONDecodeError: line 1")
        self.assertEqual(rep["status"], "blocked")
        self.assertIn("malformed", rep["summary"])

    def test_a_finished_rescue_still_reads_the_models_report(self):
        # The non-regression half: "the model says it is done" must keep its
        # original fall-through, or the rescue's whole purpose is inverted.
        rep = self._run(O.RESCUE_FINISHED, "complete")
        self.assertNotEqual(rep["status"], "blocked")

    def test_a_rescued_tool_call_is_still_executed(self):
        prose = {"content": _DONE_REPORT}
        rescue = O.RescueOutcome(
            [{"function": {"name": "list_dir", "arguments": '{"path": "."}'}}],
            O.RESCUE_CALLS, "list_dir")
        with mock.patch.object(O, "native_chat", return_value=prose), \
                mock.patch.object(O.OllamaProvider, "_schema_rescue",
                                  return_value=rescue), \
                mock.patch.object(O.OllamaProvider, "_dispatch",
                                  return_value="OK") as dispatch:
            rep = self.p._run_agentic("do a thing", ".", [], self.agent, "m",
                                      5, {}, writable=True)
        self.assertTrue(dispatch.called)
        self.assertNotEqual(rep["status"], "blocked")


if __name__ == "__main__":
    unittest.main()

"""The shared report helpers: the parser that decides whether a model's answer
survives, and the coercion that decides what of it is kept.

Both have destroyed evidence before, which is why each rescue is locked here:

* ``extract_json``'s strictness killed 100% of the claims123 review tier on
  2026-07-31 -- models quoting backslash-bearing source emitted ``\\d`` and
  ``\\x1b`` inside JSON strings, and every such answer died as a blocked
  report ("Invalid \\escape").
* ``coerce_report`` silently rebuilt reports from a fixed key set until
  f0392fc, destroying ~250 answers of the 2026-07-30 fan-out that arrived
  under keys like ``claims``.  Its preservation contract had no in-suite test
  until this file.
"""
from __future__ import annotations

import unittest

from daedalus.providers._report import coerce_report, extract_json


class InvalidEscapeRepair(unittest.TestCase):
    def test_lone_invalid_escapes_are_repaired_losslessly(self):
        got = extract_json(r'{"why": "matches \d+ then \x1b[0m"}')
        # The model wrote a literal backslash; the repaired parse returns it.
        self.assertEqual(got["why"], r"matches \d+ then \x1b[0m")

    def test_valid_double_backslash_is_not_touched(self):
        got = extract_json(r'{"p": "C:\\Users"}')
        # JSON \\ decodes to one backslash; the repair must not corrupt it.
        self.assertEqual(got["p"], "C:" + chr(92) + "Users")

    def test_mixed_run_still_raises(self):
        # \\ followed by \d: the lookbehind refuses to guess, and the honest
        # outcome is the original parse error, not a mangled rescue.
        with self.assertRaises(ValueError):
            extract_json(r'{"a": "\\\d"}')

    def test_repair_composes_with_prose_stripping(self):
        got = extract_json(r'Here is my report: {"a": "\d"} -- hope it helps')
        self.assertEqual(got["a"], chr(92) + "d")

    def test_repairs_list_records_the_rescue(self):
        repairs: list[str] = []
        extract_json(r'{"a": "\d", "b": "\."}', repairs=repairs)
        self.assertEqual(len(repairs), 1)
        self.assertIn("2", repairs[0])
        self.assertIn("escape", repairs[0])

    def test_clean_parse_records_nothing(self):
        repairs: list[str] = []
        extract_json('{"a": "no backslashes here"}', repairs=repairs)
        self.assertEqual(repairs, [])

    def test_valid_escape_letters_stay_escapes(self):
        # \n is legal JSON, so a model writing a Windows path component
        # "\nodejs" gets a newline.  Undecidable at this layer; documented.
        repairs: list[str] = []
        got = extract_json(r'{"p": "dir\nodejs"}', repairs=repairs)
        self.assertEqual(got["p"], "dir\nodejs")
        self.assertEqual(repairs, [])

    def test_non_object_json_still_raises(self):
        with self.assertRaises(ValueError):
            extract_json("[1, 2, 3]")


class CoerceReportPreservation(unittest.TestCase):
    def test_unexpected_keys_survive_into_handoff(self):
        # The whole 2026-07-30 failure shape: an answer that is NOTHING but a
        # wrong-keyed payload must survive coercion, not merely have its keys
        # preserved on the way to being refused for the summary it lacks.
        report = coerce_report({"claims": [{"claim": "x", "verdict": "KEPT"}]})
        self.assertEqual(
            report["handoff"]["unexpected_keys"]["claims"],
            [{"claim": "x", "verdict": "KEPT"}],
        )
        self.assertTrue(report["handoff"]["summary_was_defaulted"])
        self.assertTrue(report["summary"].strip())

    def test_empty_answer_still_fails_validation(self):
        # No content to preserve means nothing to protect: the empty answer
        # keeps failing, so the caller's re-ask keeps its second chance.
        with self.assertRaises(ValueError):
            coerce_report({})

    def test_supplied_summary_is_never_replaced(self):
        report = coerce_report({"summary": "mine", "claims": ["y"]})
        self.assertEqual(report["summary"], "mine")
        self.assertNotIn("summary_was_defaulted", report["handoff"])

    def test_defaulted_status_is_recorded(self):
        report = coerce_report({"summary": "no status supplied"})
        self.assertEqual(report["status"], "needs_review")
        self.assertTrue(report["handoff"]["status_was_defaulted"])

    def test_supplied_status_is_not_marked_defaulted(self):
        report = coerce_report({"status": "done", "summary": "s"})
        self.assertNotIn("status_was_defaulted", report["handoff"])


if __name__ == "__main__":
    unittest.main()

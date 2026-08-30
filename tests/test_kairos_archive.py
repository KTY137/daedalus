# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Tests for daedalus.kairos.archive -- the advisory inspiration notebook.

HAND-BACK: this file belongs at tests/test_kairos_archive.py. It was written
and run in a scratchpad because tests/ is outside the authoring agent's lane.
"""
import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.kairos.archive import (
    MAX_SUMMARY_CHARS, NUM_DIVERSE, NUM_ELITE, OUTCOME_RANK, Attempt,
    digest_patch, load_attempts, record_attempt, sample_inspirations,
)


def _a(aid, outcome, digest="", ts=0.0, summary=""):
    return Attempt(attempt_id=aid, outcome=outcome, patch_digest=digest,
                   ts=ts, summary=summary)


class TestOutcomeVocabulary(unittest.TestCase):
    def test_outcome_vocabulary_matches_the_evaluator(self):
        """The mirrored vocabulary must not drift from correctness.py.

        archive.py deliberately does not import the heavyweight evaluator, so
        this test is the only thing standing between the two copies.
        """
        from daedalus.eval import correctness
        self.assertEqual(set(OUTCOME_RANK), set(correctness.OUTCOMES))

    def test_unknown_outcome_sorts_worst_not_best(self):
        """A typo'd outcome must never be promoted to elite."""
        self.assertEqual(_a("x", "nonsense").rank, -1)
        self.assertLess(_a("x", "nonsense").rank, _a("y", "task_invalid").rank)


class TestRoundTrip(unittest.TestCase):
    def test_record_and_load_round_trip(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "nested" / "attempts.jsonl"
            record_attempt(p, _a("a1", "fixed", "deadbeef", ts=1.0))
            record_attempt(p, _a("a2", "regressed", "cafe", ts=2.0))
            got = load_attempts(p)
        self.assertEqual([x.attempt_id for x in got], ["a1", "a2"])
        self.assertEqual(got[0].outcome, "fixed")

    def test_summary_is_truncated_on_the_way_in(self):
        """A pathological traceback must not grow the notebook without limit."""
        with TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            stored = record_attempt(p, _a("big", "could_not_run",
                                          summary="E" * 50_000))
            self.assertLessEqual(len(stored.summary), MAX_SUMMARY_CHARS)
            self.assertLessEqual(len(load_attempts(p)[0].summary),
                                 MAX_SUMMARY_CHARS)

    def test_truncation_keeps_the_tail_where_the_error_is(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            stored = record_attempt(
                p, _a("t", "could_not_run", summary="X" * 5000 + "REAL_ERROR"))
        self.assertTrue(stored.summary.endswith("REAL_ERROR"))

    def test_a_torn_line_is_skipped_not_fatal(self):
        """A killed process leaves a half-written line; the next run must survive."""
        with TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            record_attempt(p, _a("good", "fixed"))
            with p.open("a", encoding="utf-8") as fh:
                fh.write('{"attempt_id": "torn", "outc\n')
            got = load_attempts(p)
        self.assertEqual([x.attempt_id for x in got], ["good"])

    def test_missing_file_is_empty_not_an_error(self):
        with TemporaryDirectory() as d:
            self.assertEqual(load_attempts(Path(d) / "nope.jsonl"), ())

    def test_no_code_field_is_ever_persisted(self):
        """The egress property: an attempt record carries no candidate source."""
        with TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            record_attempt(p, _a("a", "fixed", "d1", summary="short"))
            raw = p.read_text(encoding="utf-8")
        self.assertNotIn('"code"', raw)
        self.assertNotIn('"patch"', raw)
        self.assertNotIn('"source"', raw)


class TestDigest(unittest.TestCase):
    def test_identical_patches_share_a_digest(self):
        self.assertEqual(digest_patch("abc"), digest_patch(b"abc"))
        self.assertNotEqual(digest_patch("abc"), digest_patch("abd"))


class TestSampling(unittest.TestCase):
    def test_best_first_ordering(self):
        got = sample_inspirations(
            [_a("bad", "regressed"), _a("good", "fixed"), _a("mid", "not_fixed")],
            n_elite=3, n_diverse=0)
        self.assertEqual([x.attempt_id for x in got], ["good", "mid", "bad"])

    def test_duplicate_digests_collapse_to_one_lesson(self):
        got = sample_inspirations(
            [_a("a", "fixed", "same"), _a("b", "fixed", "same"),
             _a("c", "fixed", "other")], n_elite=5, n_diverse=0)
        self.assertEqual([x.attempt_id for x in got], ["a", "c"])

    def test_exclude_digest_drops_the_current_attempt(self):
        """A candidate must never be offered itself as inspiration."""
        got = sample_inspirations(
            [_a("self", "fixed", "mine"), _a("other", "fixed", "theirs")],
            exclude_digest="mine")
        self.assertEqual([x.attempt_id for x in got], ["other"])

    def test_failures_are_kept_because_they_teach(self):
        got = sample_inspirations([_a("r", "regressed"), _a("c", "could_not_run")])
        self.assertEqual(len(got), 2)

    def test_diverse_slice_prefers_an_uncovered_outcome(self):
        """Variety, not more of the same -- the grafted property."""
        attempts = [_a("f1", "fixed", "1"), _a("f2", "fixed", "2"),
                    _a("f3", "fixed", "3"), _a("f4", "fixed", "4"),
                    _a("reg", "regressed", "5")]
        got = sample_inspirations(attempts, n_elite=3, n_diverse=1,
                                  rng=random.Random(7))
        self.assertIn("reg", [x.attempt_id for x in got],
                      "the one uncovered outcome class must win the diverse slot")

    def test_sampling_is_deterministic_for_a_fixed_rng(self):
        attempts = [_a(f"a{i}", "fixed", str(i)) for i in range(10)]
        first = sample_inspirations(attempts, rng=random.Random(3))
        second = sample_inspirations(attempts, rng=random.Random(3))
        self.assertEqual([x.attempt_id for x in first],
                         [x.attempt_id for x in second])

    def test_empty_input_is_empty_output(self):
        self.assertEqual(sample_inspirations([]), ())

    def test_default_split_is_the_upstream_three_plus_two(self):
        self.assertEqual((NUM_ELITE, NUM_DIVERSE), (3, 2))
        attempts = [_a(f"a{i}", "fixed", str(i)) for i in range(20)]
        self.assertEqual(len(sample_inspirations(attempts)), 5)

    def test_nothing_here_imports_a_provider_or_spends(self):
        """Advisory means advisory: no lane, no provider, no gate."""
        src = Path(__import__("daedalus.kairos.archive", fromlist=["x"])
                   .__file__).read_text(encoding="utf-8")
        body = src.split('"""', 2)[-1]  # skip the module docstring
        for forbidden in ("provider_router", "offload(", "import requests",
                          "httpx", "openai", "anthropic"):
            self.assertNotIn(forbidden, body,
                             f"archive.py must not reference {forbidden}")


class TestEvaluatorInterpreter(unittest.TestCase):
    def test_evaluator_invokes_an_interpreter_qualified_pytest(self):
        """MEASURED: bare `pytest` scores the primary checkout, not the candidate.

        Asserts the SHAPE of the spawn, not merely that the string
        ``sys.executable`` appears somewhere in the file -- a docstring
        mentioning it would satisfy the weaker check.
        """
        import re
        from daedalus.kairos import evolution
        src = Path(evolution.__file__).read_text(encoding="utf-8")
        self.assertRegex(
            src, r'create_subprocess_exec\(\s*sys\.executable,\s*"-m",\s*"pytest"',
            "the evaluator must spawn `sys.executable -m pytest`")
        self.assertIsNone(
            re.search(r'create_subprocess_exec\(\s*"pytest"', src),
            "a bare `pytest` spawn scores the PRIMARY checkout, not the candidate")

    def test_evaluation_has_a_wall_clock_ceiling(self):
        from daedalus.kairos.evolution import DEFAULT_EVAL_TIMEOUT_S
        self.assertGreater(DEFAULT_EVAL_TIMEOUT_S, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

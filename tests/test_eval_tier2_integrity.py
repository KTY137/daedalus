# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Adversarial Tier-2 evaluator integrity tests.

These tests pin two distinct failure classes:
* real model text that merely mentions the expected token under negation/hedging;
* no model text at all because one or both provider calls failed.

Neither is allowed to become ordinary Tier-2 task-success evidence.
"""
from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

from daedalus.eval import harness, report
from daedalus.eval import tier2
from daedalus.eval.tasks import TASKS


PROVIDER = {
    "kind": "ollama",
    "host": "http://127.0.0.1:11434",
    "model": "nemesis-test",
}


def _ok(text: str) -> dict:
    return {
        "ok": True,
        "text": text,
        "text_chars": len(text),
        "text_sha256": "a" * 64,
        "text_truncated": False,
        "error_type": None,
        "error": None,
    }


def _err(kind: str = "TimeoutError", message: str = "provider timed out") -> dict:
    return {
        "ok": False,
        "text": None,
        "text_chars": 0,
        "text_sha256": None,
        "text_truncated": False,
        "error_type": kind,
        "error": message,
    }


class CompatibilitySurfaceTest(unittest.TestCase):
    def test_legacy_surfaces_delegate_to_canonical_tier2(self):
        answer = "It calls cached_index. Correction: it does not."
        self.assertEqual(
            harness._score(answer, ["cached_index"]),
            tier2._score(answer, ["cached_index"]),
        )
        self.assertEqual(
            harness.run_tier2([], provider="none"),
            tier2.run_tier2([], provider="none"),
        )

    def test_historical_imports_survive_compatibility_first_reload_order(self):
        from daedalus.eval import run_tier2 as historical_package_run
        from daedalus.eval.harness import _score as historical_score
        from daedalus.eval.report import render_tier2 as historical_render

        importlib.reload(harness)
        importlib.reload(report)
        reloaded = importlib.reload(tier2)
        answer = "It calls cached_index. Actually, it calls build_index instead."
        self.assertFalse(historical_score(answer, ["cached_index"])[0])
        self.assertFalse(harness._score(answer, ["cached_index"])[0])

        malicious = {
            "tier": 2,
            "skipped": True,
            "reason": "x\x1b[2J\nFORGED" + "z" * 1000,
        }
        rendered = historical_render(malicious)
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("\nFORGED", rendered)
        self.assertNotIn("z" * (reloaded._MAX_TERMINAL_FIELD_CHARS + 1), rendered)

        with patch.object(reloaded, "_score", return_value=(False, 0.25)) as score:
            self.assertEqual(harness._score("x", ["x"]), (False, 0.25))
            score.assert_called_once_with("x", ["x"])
        with patch.object(reloaded, "render_tier2", return_value="canonical") as render:
            self.assertEqual(report.render_tier2({}), "canonical")
            render.assert_called_once_with({})
        with patch.object(reloaded, "run_tier2", return_value={"canonical": True}) as run:
            self.assertEqual(
                historical_package_run([], "none", 1),
                {"canonical": True},
            )
            run.assert_called_once_with([], "none", 1)


class GuardedScoreTest(unittest.TestCase):
    def test_direct_negation_and_hedging_cannot_pass(self):
        bad = [
            ("It does not call cached_index.", ["cached_index"]),
            ("Do not water the plant.", ["water"]),
            ("The cactus interval is not 14 days.", ["14"]),
            ("I cannot tell; maybe semantic_slice is involved.", ["semantic_slice"]),
            ("cached_index is not used here.", ["cached_index"]),
        ]
        for answer, expected in bad:
            with self.subTest(answer=answer):
                success, frac = harness._score(answer, expected)
                self.assertFalse(success)
                self.assertEqual(frac, 1.0)

    def test_unrelated_negation_does_not_poison_positive_assertion(self):
        success, frac = harness._score(
            "It calls cached_index, not build_index.",
            ["cached_index"],
        )
        self.assertTrue(success)
        self.assertEqual(frac, 1.0)

    def test_concise_correct_answer_still_passes(self):
        success, frac = harness._score("cached_index", ["cached_index"])
        self.assertTrue(success)
        self.assertEqual(frac, 1.0)

    def test_multi_label_answer_fails_if_one_expected_fact_is_negated(self):
        success, frac = harness._score(
            "It calls load_project but repo_root is not used.",
            ["load_project", "repo_root"],
        )
        self.assertFalse(success)
        self.assertEqual(frac, 1.0)


class ValidatorCoverageTest(unittest.TestCase):
    def test_every_builtin_question_task_has_explicit_validator(self):
        ids, missing = tier2.builtin_validator_coverage()
        expected = sorted(t["id"] for t in TASKS if t.get("question"))
        self.assertEqual(ids, expected)
        self.assertEqual(missing, [])

    def test_structure_summary_question_requires_complete_totals_key_set(self):
        task = next(t for t in TASKS if t["id"] == "report_structure_summary")
        incomplete = tier2._validate_task_answer(task, "The totals contain unit_clusters.")
        self.assertTrue(incomplete["validated"])
        self.assertFalse(incomplete["semantic_success"])
        complete = tier2._validate_task_answer(
            task,
            "The totals keys are unit_clusters, renamed_clusters, near_clusters, "
            "window_clusters, and safety_fenced.",
        )
        self.assertTrue(complete["semantic_success"])


class StructuredAskReceiptTest(unittest.TestCase):
    def test_provider_exception_is_not_an_empty_answer(self):
        with patch(
            "daedalus.providers._openai_compat.chat_completion",
            side_effect=TimeoutError("boom\x1b[2J"),
        ):
            receipt = harness._ask(PROVIDER, "question?", "context")
        self.assertFalse(receipt["ok"])
        self.assertIsNone(receipt["text"])
        self.assertEqual(receipt["error_type"], "TimeoutError")
        self.assertNotIn("\x1b", receipt["error"])

    def test_empty_provider_response_is_measurement_error(self):
        with patch("daedalus.providers._openai_compat.chat_completion", return_value="  "):
            receipt = tier2._ask(PROVIDER, "q", "ctx")
        self.assertFalse(receipt["ok"])
        self.assertIsNone(receipt["text"])
        self.assertEqual(receipt["error_type"], "EmptyProviderResponse")

    def test_oversized_answer_is_bounded_and_marked(self):
        answer = "A" * (tier2._MAX_AUDIT_CHARS + 1000)
        with patch(
            "daedalus.providers._openai_compat.chat_completion",
            return_value=answer,
        ):
            receipt = harness._ask(PROVIDER, "question?", "context")
        self.assertTrue(receipt["ok"])
        self.assertTrue(receipt["text_truncated"])
        self.assertEqual(len(receipt["text"]), tier2._MAX_AUDIT_CHARS)
        self.assertEqual(receipt["text_chars"], len(answer))
        self.assertEqual(len(receipt["text_sha256"]), 64)


class Tier2RunIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.task = {
            "id": "garden_plants_file",
            "repo": "/virtual/repo",
            "target": "garden/plants.py",
            "question": "How many days between waterings does a cactus need?",
            "answer_contains": ["14"],
            "label_provenance": "hand_reachable",
            "tier": "primary",
        }

    def _run_with(self, answers: list[dict], task: dict | None = None) -> dict:
        chosen = task or self.task
        with patch.object(tier2._legacy, "detect_provider", return_value=PROVIDER), \
             patch.object(tier2._legacy, "resolve_task_repo", return_value="/virtual/repo"), \
             patch.object(tier2._legacy, "cached_index", return_value={}), \
             patch.object(
                 tier2._legacy,
                 "semantic_slice",
                 return_value={"slice_text": "cactus water_every_days = 14"},
             ), \
             patch.object(
                 tier2._legacy,
                 "_whole_repo_text",
                 side_effect=[
                     ("cactus water_every_days = 14", False),
                     ("cactus water_every_days = 14", False),
                 ],
             ), \
             patch.object(tier2, "_ask", side_effect=answers):
            return harness.run_tier2([chosen])

    def test_negated_real_answer_keeps_full_lexical_coverage_but_fails_semantics(self):
        result = self._run_with([
            _ok("The cactus interval is not 14 days."),
            _ok("The cactus interval is 14 days."),
        ])
        self.assertEqual(result["n_tasks"], 1)
        self.assertEqual(result["n_scored_tasks"], 1)
        row = result["per_task"][0]
        self.assertEqual(row["frac_A"], 1.0)
        self.assertFalse(row["success_A"])
        self.assertEqual(row["frac_B"], 1.0)
        self.assertTrue(row["success_B"])
        self.assertEqual(row["answer_A"], "The cactus interval is not 14 days.")
        self.assertEqual(row["answer_B"], "The cactus interval is 14 days.")

    def test_one_arm_provider_failure_is_excluded_not_scored_as_wrong(self):
        for answers in (
            [_err(), _ok("The cactus interval is 14 days.")],
            [_ok("The cactus interval is 14 days."), _err("ConnectionError", "down")],
            [_err(), _err("ConnectionError", "down")],
        ):
            with self.subTest(answers=answers):
                result = self._run_with(answers)
                self.assertEqual(result["n_tasks"], 1)
                self.assertEqual(result["n_scored_tasks"], 0)
                self.assertEqual(result["n_measurement_error_tasks"], 1)
                self.assertEqual(result["success_A"], 0)
                self.assertEqual(result["success_B"], 0)
                row = result["per_task"][0]
                self.assertTrue(row["measurement_error"])
                self.assertNotIn("success_A", row)
                self.assertNotIn("success_B", row)

                text = report.render_tier2(result)
                self.assertIn("MEASUREMENT ERRORS", text)
                self.assertIn("0 scored task(s) from 1 attempted", text)
                text.encode("ascii")

    def test_missing_validator_is_fail_closed_and_not_in_denominator(self):
        unvalidated = dict(self.task, id="minted_unvalidated")
        result = self._run_with([
            _ok("The cactus interval is 14 days."),
            _ok("The cactus interval is 14 days."),
        ], task=unvalidated)
        self.assertEqual(result["n_scored_tasks"], 0)
        self.assertEqual(result["n_unvalidated_tasks"], 1)
        self.assertTrue(result["per_task"][0]["validator_missing"])
        text = report.render_tier2(result)
        self.assertIn("UNVALIDATED TASKS", text)
        text.encode("ascii")

    def test_truncated_answer_receipt_is_measurement_error_not_semantic_failure(self):
        truncated = _ok("head ... tail")
        truncated["text_truncated"] = True
        result = self._run_with([
            truncated,
            _ok("The cactus interval is 14 days."),
        ])
        self.assertEqual(result["n_scored_tasks"], 0)
        self.assertEqual(result["n_measurement_error_tasks"], 1)
        self.assertIn("answer_A_truncated",
                      result["per_task"][0]["measurement_error_reasons"])


if __name__ == "__main__":
    unittest.main()

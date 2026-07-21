"""Tests for the decontaminated eval oracle: label provenance, the A/B/C arms
comparison (BM25 baseline C), and the advisory regression gate.

Everything here is deterministic and offline: no LLM, no network. Tier 2 (the
LLM arm) is exercised only via its clean-skip path (provider="none"), matching
the existing tests/test_eval.py convention -- never a real provider call.

Two kinds of fixtures are used on purpose:
  * REAL temp repos (via ``semantic_slice``/``run_tier1``/``run_arms``) for the
    provenance-aggregation and BM25 tests -- these exercise the actual code
    path, not a mocked stand-in.
  * Hand-built per-task ROWS (bypassing ``semantic_slice`` entirely, via
    ``unittest.mock.patch`` on ``run_tier1``) for the gate tests, because the
    gate's per-task-not-mean claim needs EXACT, hand-chosen recall numbers
    (e.g. a mean-preserving swap) that would be fragile to reproduce through
    real slicing.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus.eval import harness, report
from daedalus.eval.tasks import TASKS, task_project_label


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


CORE = '''\
def helper(x):
    """Return x doubled."""
    return x * 2


class Engine:
    def run(self):
        return helper(21)
'''

APP = '''\
from proj import core


def main():
    e = core.Engine()
    return e.run()
'''


# --------------------------------------------------------------------------- #
# 1. Label provenance: per-tier aggregation, quarantine excluded from headline #
# --------------------------------------------------------------------------- #
class ProvenanceAggregationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", CORE)
        _write(self.root, "proj/app.py", APP)
        repo = str(self.root)
        self.tasks = [
            {  # hand_reachable/primary, full recall
                "id": "hr_primary_hit", "repo": repo, "target": "proj/core.py",
                "must_include": ["helper", "Engine"],
                "label_provenance": "hand_reachable", "tier": "primary",
            },
            {  # hand_reachable/primary, a genuine miss (GHOST isn't in the file)
                "id": "hr_primary_miss", "repo": repo, "target": "proj/core.py",
                "must_include": ["helper", "GHOST"],
                "label_provenance": "hand_reachable", "tier": "primary",
            },
            {  # independent_diff/primary, full recall -- NOT self-graded
                "id": "diff_primary", "repo": repo, "target": "proj/core.py",
                "must_include": ["helper"],
                "label_provenance": "independent_diff", "tier": "primary",
            },
            {  # independent_diff/quarantine -- must be EXCLUDED from headline
                "id": "diff_quarantine", "repo": repo, "target": "proj/core.py",
                "must_include": ["GHOST2"],
                "label_provenance": "independent_diff", "tier": "quarantine",
            },
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_blended_top_level_recall(self):
        """The whole point of this sprint: there must be no single blended
        recall number a caller could mistake for "the" headline."""
        result = harness.run_tier1(self.tasks)
        self.assertNotIn("mean_recall", result)
        self.assertNotIn("mean_compression", result)

    def test_per_provenance_per_tier_breakdown(self):
        result = harness.run_tier1(self.tasks)
        bp = result["by_provenance"]
        self.assertEqual(set(bp), {"hand_reachable", "independent_diff"})

        hr_primary = bp["hand_reachable"]["primary"]
        self.assertEqual(hr_primary["n_tasks"], 2)
        self.assertAlmostEqual(hr_primary["mean_recall"], (1.0 + 0.5) / 2)
        self.assertEqual(hr_primary["n_slice_recall_misses"], 1)
        self.assertEqual(hr_primary["missed_ids"], ["hr_primary_miss"])
        self.assertEqual(bp["hand_reachable"]["quarantine"]["n_tasks"], 0)

        diff_primary = bp["independent_diff"]["primary"]
        self.assertEqual(diff_primary["n_tasks"], 1)
        self.assertEqual(diff_primary["mean_recall"], 1.0)

        diff_quarantine = bp["independent_diff"]["quarantine"]
        self.assertEqual(diff_quarantine["n_tasks"], 1)
        self.assertEqual(diff_quarantine["mean_recall"], 0.0)

    def test_quarantine_excluded_from_headline_counts(self):
        result = harness.run_tier1(self.tasks)
        self.assertEqual(result["n_tasks"], 4)
        self.assertEqual(result["n_primary_tasks"], 3)
        self.assertEqual(result["n_quarantine_tasks"], 1)
        # the quarantine row is still present in per_task (observable), just
        # not folded into any primary aggregate above.
        by_id = {t["id"]: t for t in result["per_task"]}
        self.assertEqual(by_id["diff_quarantine"]["label_tier"], "quarantine")

    def test_report_renders_breakdown_and_disclaimer_ascii(self):
        result = harness.run_tier1(self.tasks)
        text = report.render_tier1(result)
        text.encode("ascii")  # cp1252 Windows console safety
        self.assertIn("PARTIALLY SELF-GRADED", text)
        self.assertIn("hand_reachable", text)
        self.assertIn("independent_diff", text)
        self.assertIn("quarantine", text)
        self.assertIn("never blended", text)

    def test_legacy_task_dict_without_new_fields_defaults_safely(self):
        """A task dict that predates this schema (no label_provenance/tier)
        must still aggregate -- as hand_reachable/primary -- not crash."""
        legacy = [{
            "id": "legacy", "repo": str(self.root), "target": "proj/core.py",
            "must_include": ["helper"],
        }]
        result = harness.run_tier1(legacy)
        self.assertEqual(result["n_primary_tasks"], 1)
        row = result["per_task"][0]
        self.assertEqual(row["label_provenance"], "hand_reachable")
        self.assertEqual(row["label_tier"], "primary")
        self.assertEqual(result["by_provenance"]["hand_reachable"]["primary"]["n_tasks"], 1)


# --------------------------------------------------------------------------- #
# 2. Arm C -- BM25 retrieval baseline                                         #
# --------------------------------------------------------------------------- #
NEEDLE = '''\
def quantum_flux_capacitor(x):
    """A distinctive, unique symbol so BM25 has an obvious lexical match."""
    return x * 88
'''


class Bm25ArmTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/needle.py", NEEDLE)
        for i in range(5):
            _write(self.root, f"proj/noise_{i}.py",
                  f"def unrelated_{i}(a, b):\n    return a + b + {i}\n" * 3)
        self.chunks = harness._repo_chunks(str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_repo_chunks_found_the_needle(self):
        labels = [label for label, _ in self.chunks]
        self.assertTrue(any("needle.py" in lbl for lbl in labels))

    def test_bm25_ranks_the_lexical_match_first(self):
        result = harness._bm25_context(self.chunks, "quantum_flux_capacitor",
                                        budget_tokens=10_000)
        self.assertGreater(result["n_chunks_used"], 0)
        self.assertIn("quantum_flux_capacitor", result["text"])
        self.assertTrue(result["text"].startswith("# ===== proj/needle.py"),
                        f"expected needle.py first, got: {result['text'][:80]!r}")
        self.assertFalse(result["truncated"])

    def test_bm25_respects_token_budget(self):
        chunks = harness._repo_chunks(str(self.root))
        result = harness._bm25_context(chunks, "quantum_flux_capacitor", budget_tokens=5)
        # the top-ranked chunk is always included even if it alone overflows --
        # an empty context is a worse baseline than a slightly-over one.
        self.assertEqual(result["n_chunks_used"], 1)
        self.assertLess(result["n_chunks_used"], result["n_chunks_total"])
        self.assertTrue(result["truncated"])
        self.assertGreater(result["tokens"], 5)  # proves the budget was exceeded, not silently obeyed

    def test_bm25_empty_query_yields_empty_context(self):
        result = harness._bm25_context(self.chunks, "   ", budget_tokens=10_000)
        self.assertEqual(result["n_chunks_used"], 0)
        self.assertEqual(result["text"], "")
        self.assertFalse(result["truncated"])

    def test_bm25_scores_rank_matching_doc_higher(self):
        # NOTE: the tokenizer keeps identifiers whole (underscore is a word
        # char, matching how a real symbol name would be queried) -- so the
        # query must use the same underscored form as the target identifier.
        docs = [
            harness._bm25_tokenize("def unrelated(a, b): return a + b"),
            harness._bm25_tokenize("def quantum_flux_capacitor(x): return x * 88"),
        ]
        scores = harness._bm25_scores(harness._bm25_tokenize("quantum_flux_capacitor"), docs)
        self.assertGreater(scores[1], scores[0])

    def test_arms_comparison_end_to_end_on_builtin_sunny_garden(self):
        """Real (non-mocked) A/B/C run on the tiny built-in task bucket."""
        tasks = [t for t in TASKS if task_project_label(t) == "sunny_garden"]
        result = harness.run_arms(tasks)
        self.assertEqual(result["n_tasks"], len(tasks))
        for t in result["per_task"]:
            for key in ("recall_A", "recall_B", "recall_C", "tokens_A", "tokens_B", "tokens_C"):
                self.assertIn(key, t)
            self.assertGreaterEqual(t["recall_B"], t["recall_A"] - 1e-9)  # B sees everything
            self.assertEqual(t["token_budget_C"], t["tokens_A"])
        text = report.render_arms(result)
        text.encode("ascii")
        self.assertIn("ARMS A/B/C", text)
        self.assertIn("BM25", text)

    def test_c_beats_a_is_tie_inclusive_not_smoothed_over(self):
        """Regression: harness.py used strict '>' for c_beats_a, so a BM25 TIE
        with the semantic slice (recall_C == recall_A) was silently counted as
        an A win -- contradicting the report's own "C>=A" column header and
        the module docstring's promise that a tie is "reported loudly, not
        smoothed over". Every sunny_garden task ties at recall_A==recall_C==1.0
        (verified: BM25 budgeted to tokens_A always finds needs_water/PLANTS in
        this tiny fixture), which is exactly the commercially-damning case --
        dumb retrieval matching the product at equal cost -- that must not be
        hidden under a "no"."""
        tasks = [t for t in TASKS if task_project_label(t) == "sunny_garden"]
        result = harness.run_arms(tasks)
        ties = [t for t in result["per_task"]
                if t["recall_C"] == t["recall_A"]]
        self.assertTrue(ties, "fixture assumption broken: expected at least one "
                              "recall_C == recall_A tie in the sunny_garden bucket")
        for t in ties:
            self.assertTrue(t["c_beats_a"],
                            f"{t['id']}: recall_C == recall_A but c_beats_a is False "
                            "-- a tie must count as C>=A, per the report column header")

        text = report.render_arms(result)
        self.assertIn("TIES OR BEATS", text)
        # The old wording implied a tie is never reported; it must not survive.
        self.assertNotIn("C never beat A", text)
        for t in ties:
            self.assertIn(f"  {t['id']}: recall_C=", text)  # listed under the loud block


# --------------------------------------------------------------------------- #
# 2b. Tier-2 ground-truth labels must follow the code they grade              #
# --------------------------------------------------------------------------- #
class Tier2LabelFollowsCodeTest(unittest.TestCase):
    """Regression: slice_semantic_slice's answer_contains still tested for
    "total_chars" after the HONEST DENOMINATOR change moved semantic_slice's
    primary whole-repo-token computation onto idx["total_tokens"] (tokenizer-
    measured); total_chars // 4 is now only the legacy-index fallback (see
    daedalus/structcore/slice.py::_whole_repo_tokens). A fully correct answer
    about the CURRENT code was being scored a failure -- penalizing arm A for
    the sprint's own improvement. tasks.py's own comment on this task says
    "Ground truth follows the code"; this test pins that it actually does."""

    def test_correct_current_denominator_answer_scores_success(self):
        task = next(t for t in TASKS if t["id"] == "slice_semantic_slice")
        # Deliberately does NOT mention the legacy fallback (or its
        # "total_chars" substring) at all -- a model describing only the
        # CURRENT primary path is a fully correct answer and must not be
        # penalized for omitting a formula the code no longer uses by default.
        correct_answer = (
            "It reads the index's total_tokens field, summed by the same "
            "tokenizer as the slice numerator."
        )
        ok, frac = harness._score(correct_answer, task["answer_contains"])
        self.assertTrue(ok, f"a correct description of the CURRENT denominator "
                             f"code was rejected by answer_contains={task['answer_contains']!r}")

    def test_stale_total_chars_only_label_would_have_failed(self):
        """Documents the bug: grading the same correct answer against the OLD
        (pre-fix) label -- which required the substring "total_chars" -- fails,
        proving the old label rewarded describing the dead legacy path over
        the current primary one."""
        stale_answer_contains = ["total_chars"]
        correct_answer = ("It reads the index's total_tokens field, summed by "
                           "the same tokenizer as the numerator.")
        ok, frac = harness._score(correct_answer, stale_answer_contains)
        self.assertFalse(ok)


# --------------------------------------------------------------------------- #
# 2c. A single unresolvable task must not brick the whole eval run            #
#                                                                              #
# Live repro: the mint store contained a task whose target file had moved/    #
# been deleted after minting; semantic_slice raised ValueError("target not    #
# found in index: ...") and it propagated all the way out of run_tier1,       #
# killing the entire `python -m daedalus.eval` run over EVERY task, not just  #
# the bad one. A quarantined flywheel task must not be able to take down the  #
# go/no-go machinery.                                                         #
# --------------------------------------------------------------------------- #
class ErroredTaskResilienceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", CORE)
        repo = str(self.root)
        self.baseline_path = str(self.root / "baseline.json")  # never written -> empty baseline

        self.healthy_task = {
            "id": "healthy", "repo": repo, "target": "proj/core.py",
            "must_include": ["helper", "Engine"],
            "label_provenance": "hand_reachable", "tier": "primary",
        }
        # Mirrors the live repro: a minted task pointing at a target that is
        # NOT in the index (moved/deleted file) -> semantic_slice raises
        # ValueError("target not found in index: ...").
        self.errored_quarantine_task = {
            "id": "ghost_quarantine", "repo": repo,
            "target": "proj/does_not_exist.py",
            "must_include": ["whatever"],
            "label_provenance": "temporal_churn", "tier": "quarantine",
        }
        self.errored_primary_task = {
            "id": "ghost_primary", "repo": repo,
            "target": "proj/does_not_exist.py",
            "must_include": ["whatever"],
            "label_provenance": "hand_reachable", "tier": "primary",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_run_tier1_survives_unindexable_quarantine_task(self):
        tasks = [self.healthy_task, self.errored_quarantine_task]
        result = harness.run_tier1(tasks)  # must not raise

        self.assertEqual(result["n_tasks"], 2)
        self.assertEqual(result["n_errored_tasks"], 1)
        self.assertEqual([t["id"] for t in result["errored"]], ["ghost_quarantine"])
        self.assertIn("target not found in index", result["errored"][0]["error"])

        # per_task keeps the errored row (never silently dropped) but it
        # carries no recall/compression measurement at all.
        by_id = {t["id"]: t for t in result["per_task"]}
        self.assertNotIn("recall", by_id["ghost_quarantine"])
        self.assertNotIn("compression", by_id["ghost_quarantine"])
        self.assertEqual(by_id["healthy"]["recall"], 1.0)

        # aggregates computed over the healthy tasks ONLY: the errored task
        # was the sole temporal_churn task, so that provenance bucket must
        # not appear at all (folding it in as a 0.0 would be silently wrong).
        bp = result["by_provenance"]
        self.assertNotIn("temporal_churn", bp)
        self.assertEqual(bp["hand_reachable"]["primary"]["n_tasks"], 1)
        self.assertEqual(bp["hand_reachable"]["primary"]["mean_recall"], 1.0)

    def test_run_arms_survives_unindexable_quarantine_task(self):
        tasks = [self.healthy_task, self.errored_quarantine_task]
        result = harness.run_arms(tasks)  # must not raise
        self.assertEqual(result["n_errored_tasks"], 1)
        self.assertEqual([t["id"] for t in result["errored"]], ["ghost_quarantine"])
        by_id = {t["id"]: t for t in result["per_task"]}
        self.assertNotIn("recall_A", by_id["ghost_quarantine"])
        self.assertEqual(by_id["healthy"]["recall_A"], 1.0)
        text = report.render_arms(result)
        text.encode("ascii")
        self.assertIn("ERRORED TASKS", text)
        self.assertIn("ghost_quarantine", text)

    def test_report_renders_unmissable_errored_section(self):
        tasks = [self.healthy_task, self.errored_quarantine_task]
        result = harness.run_tier1(tasks)
        text = report.render_tier1(result)
        text.encode("ascii")  # cp1252 console safety
        self.assertIn("ERRORED TASKS", text)
        self.assertIn("ghost_quarantine", text)
        self.assertIn("proj/does_not_exist.py", text)
        self.assertIn("target not found in index", text)

    def test_gate_fails_loudly_on_errored_primary_task(self):
        """A broken PRIMARY-tier task screams: the gate fails and names it."""
        tasks = [self.healthy_task, self.errored_primary_task]
        gate = harness.run_gate(tasks, baseline_path=self.baseline_path)
        self.assertFalse(gate["passed"])
        self.assertEqual([r["id"] for r in gate["errored_primary"]], ["ghost_primary"])
        self.assertEqual(gate["errored_quarantine"], [])
        text = report.render_gate(gate)
        text.encode("ascii")
        self.assertIn("FAIL", text)
        self.assertIn("FAILED TO RESOLVE", text)
        self.assertIn("ghost_primary", text)

    def test_gate_does_not_fail_on_errored_quarantine_task(self):
        """Flywheel debris (an errored QUARANTINE task) is reported, not gated."""
        tasks = [self.healthy_task, self.errored_quarantine_task]
        gate = harness.run_gate(tasks, baseline_path=self.baseline_path)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["errored_primary"], [])
        self.assertEqual([r["id"] for r in gate["errored_quarantine"]], ["ghost_quarantine"])
        text = report.render_gate(gate)
        self.assertIn("PASS", text)
        self.assertIn("ERRORED QUARANTINE", text)
        self.assertIn("ghost_quarantine", text)
        self.assertNotIn("FAILED TO RESOLVE", text)

    def test_snapshot_baseline_skips_errored_tasks(self):
        """write_baseline must not crash on an errored task, and must not
        snapshot a recall number that was never measured."""
        tasks = [self.healthy_task, self.errored_quarantine_task]
        written_path = harness.write_baseline(tasks, path=self.baseline_path)
        data = json.loads(Path(written_path).read_text(encoding="utf-8"))
        self.assertIn("healthy", data["tasks"])
        self.assertNotIn("ghost_quarantine", data["tasks"])

    def test_zero_errored_tasks_report_has_no_errored_section(self):
        """Additive: a task set with zero errored tasks renders with no
        ERRORED section at all -- the new code path adds nothing here."""
        result = harness.run_tier1([self.healthy_task])
        self.assertEqual(result["n_errored_tasks"], 0)
        self.assertEqual(result["errored"], [])
        text = report.render_tier1(result)
        self.assertNotIn("ERRORED", text)

        gate = harness.run_gate([self.healthy_task], baseline_path=self.baseline_path)
        self.assertEqual(gate["errored_primary"], [])
        self.assertEqual(gate["errored_quarantine"], [])
        gate_text = report.render_gate(gate)
        self.assertNotIn("ERRORED", gate_text)
        self.assertNotIn("FAILED TO RESOLVE", gate_text)

    def test_zero_focus_withheld_tasks_report_has_no_focus_withheld_section(self):
        """Regression (lane A1): a task set with zero focus-withheld tasks --
        i.e. every fixture used across the pre-existing eval oracle suite --
        renders and gates byte-identically to before the focus_withheld
        machinery existed. n_focus_withheld/focus_withheld_ids are new,
        additive, and always present but empty here."""
        result = harness.run_tier1([self.healthy_task])
        self.assertEqual(result["n_focus_withheld"], 0)
        self.assertEqual(result["focus_withheld_ids"], [])
        text = report.render_tier1(result)
        self.assertNotIn("FOCUS-WITHHELD", text)

        gate = harness.run_gate([self.healthy_task], baseline_path=self.baseline_path)
        self.assertEqual(gate["focus_withheld"], [])
        gate_text = report.render_gate(gate)
        self.assertNotIn("FOCUS-WITHHELD", gate_text)

    def test_zero_focus_withheld_arms_report_has_no_focus_withheld_section(self):
        result = harness.run_arms([self.healthy_task])
        self.assertEqual(result["n_focus_withheld"], 0)
        self.assertEqual(result["focus_withheld_ids"], [])
        text = report.render_arms(result)
        self.assertNotIn("FOCUS-WITHHELD", text)

    def test_builtin_task_set_renders_with_no_errored_section(self):
        """The real, shipped task set has zero errored tasks today -- pins
        that the whole ERRORED machinery is invisible until something
        actually breaks (no false positives on the healthy corpus)."""
        tasks = [t for t in TASKS if task_project_label(t) == "sunny_garden"]
        result = harness.run_tier1(tasks)
        self.assertEqual(result["n_errored_tasks"], 0)
        text = report.render_tier1(result)
        self.assertNotIn("ERRORED", text)


# --------------------------------------------------------------------------- #
# 3. The advisory regression gate                                             #
# --------------------------------------------------------------------------- #
def _row(id_, recall, prov="hand_reachable", tier="primary"):
    return {
        "id": id_, "project": "fixture", "target": f"{id_}.py", "focus_file": f"{id_}.py",
        "recall": recall, "compression": 0.5, "slice_tokens": 10, "whole_repo_tokens": 20,
        "n_included": 1, "must_include": [], "missed": [],
        "label_provenance": prov, "label_tier": tier,
    }


def _fake_tier1_result(rows):
    n = len(rows)
    n_primary = sum(1 for r in rows if r["label_tier"] == "primary")
    return {
        "tier": 1, "n_tasks": n, "n_primary_tasks": n_primary,
        "n_quarantine_tasks": n - n_primary, "tokenizer": "fake",
        "per_task": rows,
        "by_provenance": harness._by_provenance(rows, harness._tier1_aggregate),
    }


class GateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.baseline_path = str(Path(self._tmp.name) / "baseline.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_baseline(self, entries: dict) -> None:
        with open(self.baseline_path, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "tasks": entries}, fh)

    def test_gate_fails_on_per_task_recall_decrease(self):
        self._write_baseline({"t1": {"recall": 1.0, "label_provenance": "hand_reachable", "tier": "primary"}})
        rows = [_row("t1", recall=0.5)]
        with patch.object(harness, "run_tier1", return_value=_fake_tier1_result(rows)):
            gate = harness.run_gate(tasks=[{"id": "t1"}], baseline_path=self.baseline_path)
        self.assertFalse(gate["passed"])
        self.assertEqual(len(gate["regressions"]), 1)
        self.assertEqual(gate["regressions"][0]["id"], "t1")
        self.assertAlmostEqual(gate["regressions"][0]["delta"], -0.5)

    def test_gate_passes_on_non_decrease(self):
        self._write_baseline({
            "t1": {"recall": 0.5, "label_provenance": "hand_reachable", "tier": "primary"},
            "t2": {"recall": 1.0, "label_provenance": "hand_reachable", "tier": "primary"},
        })
        rows = [_row("t1", recall=0.5), _row("t2", recall=1.0)]  # unchanged
        with patch.object(harness, "run_tier1", return_value=_fake_tier1_result(rows)):
            gate = harness.run_gate(tasks=[{"id": "t1"}, {"id": "t2"}], baseline_path=self.baseline_path)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["regressions"], [])

    def test_gate_improvement_passes_too(self):
        self._write_baseline({"t1": {"recall": 0.5, "label_provenance": "hand_reachable", "tier": "primary"}})
        rows = [_row("t1", recall=1.0)]
        with patch.object(harness, "run_tier1", return_value=_fake_tier1_result(rows)):
            gate = harness.run_gate(tasks=[{"id": "t1"}], baseline_path=self.baseline_path)
        self.assertTrue(gate["passed"])
        self.assertEqual(len(gate["improved"]), 1)

    def test_gate_mean_preserving_swap_fails(self):
        """The test that proves gating is PER-TASK, not on the mean: t1 goes
        up by 0.5 and t2 goes down by 0.5 -- the MEAN is unchanged (0.5), but
        one task genuinely regressed, so the gate MUST fail."""
        self._write_baseline({
            "t1": {"recall": 0.5, "label_provenance": "hand_reachable", "tier": "primary"},
            "t2": {"recall": 0.5, "label_provenance": "hand_reachable", "tier": "primary"},
        })
        rows = [_row("t1", recall=1.0), _row("t2", recall=0.0)]
        fake = _fake_tier1_result(rows)
        # sanity: the mean genuinely did not move
        self.assertAlmostEqual(sum(r["recall"] for r in rows) / len(rows), 0.5)
        with patch.object(harness, "run_tier1", return_value=fake):
            gate = harness.run_gate(tasks=[{"id": "t1"}, {"id": "t2"}], baseline_path=self.baseline_path)
        self.assertFalse(gate["passed"])
        self.assertEqual([r["id"] for r in gate["regressions"]], ["t2"])

    def test_gate_excludes_quarantine_tasks(self):
        """A quarantine-tier task regressing must NOT fail the gate."""
        self._write_baseline({"q1": {"recall": 1.0, "label_provenance": "temporal_churn", "tier": "quarantine"}})
        rows = [_row("q1", recall=0.0, prov="temporal_churn", tier="quarantine")]
        with patch.object(harness, "run_tier1", return_value=_fake_tier1_result(rows)):
            gate = harness.run_gate(tasks=[{"id": "q1"}], baseline_path=self.baseline_path)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["regressions"], [])
        self.assertEqual(gate["n_checked"], 0)

    def test_gate_new_task_not_in_baseline_does_not_fail(self):
        self._write_baseline({})
        rows = [_row("brand_new", recall=0.1)]
        with patch.object(harness, "run_tier1", return_value=_fake_tier1_result(rows)):
            gate = harness.run_gate(tasks=[{"id": "brand_new"}], baseline_path=self.baseline_path)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["new_tasks"], ["brand_new"])

    def test_gate_report_renders_ascii(self):
        self._write_baseline({"t1": {"recall": 1.0, "label_provenance": "hand_reachable", "tier": "primary"}})
        rows = [_row("t1", recall=0.5)]
        with patch.object(harness, "run_tier1", return_value=_fake_tier1_result(rows)):
            gate = harness.run_gate(tasks=[{"id": "t1"}], baseline_path=self.baseline_path)
        text = report.render_gate(gate)
        text.encode("ascii")
        self.assertIn("FAIL", text)
        self.assertIn("ADVISORY", text)


class BaselineWriteIsExplicitOnlyTest(unittest.TestCase):
    """GUARDRAIL: baseline.json must never be written except by an explicit,
    human-invoked write_baseline()/--update-baseline call."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.baseline_path = str(Path(self._tmp.name) / "baseline.json")
        self.tasks = [t for t in TASKS if task_project_label(t) == "sunny_garden"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_run_tier1_never_writes_baseline(self):
        harness.run_tier1(self.tasks)
        self.assertFalse(Path(self.baseline_path).exists())

    def test_run_gate_never_writes_baseline(self):
        harness.run_gate(self.tasks, baseline_path=self.baseline_path)
        self.assertFalse(Path(self.baseline_path).exists())  # no baseline yet -> empty baseline, still no write

    def test_write_baseline_is_the_only_writer(self):
        self.assertFalse(Path(self.baseline_path).exists())
        written = harness.write_baseline(self.tasks, path=self.baseline_path)
        self.assertEqual(written, self.baseline_path)
        self.assertTrue(Path(self.baseline_path).exists())
        data = json.loads(Path(self.baseline_path).read_text(encoding="utf-8"))
        self.assertIn("tasks", data)
        self.assertEqual(set(data["tasks"]), {t["id"] for t in self.tasks})

    def test_cli_gate_without_update_flag_does_not_write(self):
        from daedalus.eval import __main__ as eval_main

        rc = eval_main.main(["--gate", "--project", "sunny_garden",
                             "--baseline-path", self.baseline_path])
        self.assertIn(rc, (0, 1))  # empty baseline -> nothing to regress -> PASS (0)
        self.assertFalse(Path(self.baseline_path).exists())

    def test_cli_update_baseline_flag_writes_then_gate_passes(self):
        from daedalus.eval import __main__ as eval_main

        rc = eval_main.main(["--update-baseline", "--project", "sunny_garden",
                             "--baseline-path", self.baseline_path])
        self.assertEqual(rc, 0)
        self.assertTrue(Path(self.baseline_path).exists())
        rc2 = eval_main.main(["--gate", "--project", "sunny_garden",
                              "--baseline-path", self.baseline_path])
        self.assertEqual(rc2, 0)  # self-consistent: just wrote it, must PASS


if __name__ == "__main__":
    unittest.main()

"""Deterministic and adversarial tests for the experiment statistics."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import unittest

from experiments.forest_v2.tensor_embeddings import stats


CORPUS_DIGEST = "sha256:" + "c" * 64
ARMS = stats.REQUIRED_ARM_NAMES
CASES = ("case-a", "case-b")


def _metrics(hit: bool = False) -> dict[str, float]:
    if hit:
        return {
            "reciprocal_rank": 0.5,
            "recall_at_1": 0.0,
            "recall_at_5": 0.5,
            "recall_at_10": 0.5,
            "recall_at_20": 0.5,
            "first_hit_coverage": 1.0,
        }
    return {
        "reciprocal_rank": 0.0,
        "recall_at_1": 0.0,
        "recall_at_5": 0.0,
        "recall_at_10": 0.0,
        "recall_at_20": 0.0,
        "first_hit_coverage": 0.0,
    }


def _comparison_rows(arms: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for left, right, metric in stats.REQUIRED_COMPARISON_KEYS:
        left_by_case = {
            case_id: sum(
                arms[left][str(seed)]["per_case"][case_id][metric]
                for seed in stats.FROZEN_SEEDS
            )
            / len(stats.FROZEN_SEEDS)
            for case_id in CASES
        }
        right_by_case = {
            case_id: sum(
                arms[right][str(seed)]["per_case"][case_id][metric]
                for seed in stats.FROZEN_SEEDS
            )
            / len(stats.FROZEN_SEEDS)
            for case_id in CASES
        }
        interval = stats.paired_bootstrap_difference(left_by_case, right_by_case)
        rows.append(
            {
                "left_arm": left,
                "right_arm": right,
                "metric": metric,
                **interval.as_dict(),
                "superiority_claim": False,
            }
        )
    return rows


def _refresh_comparisons(report: dict[str, object]) -> None:
    report["comparisons"] = _comparison_rows(report["arms"])


def _find_comparison(
    report: dict[str, object], left: str, right: str
) -> dict[str, object]:
    return next(
        row
        for row in report["comparisons"]
        if row["left_arm"] == left and row["right_arm"] == right
    )


def _valid_report() -> dict[str, object]:
    arms: dict[str, object] = {}
    for arm_index, arm in enumerate(ARMS):
        runs = {}
        for seed in stats.FROZEN_SEEDS:
            runs[str(seed)] = {
                "per_case": {
                    case_id: _metrics(
                        hit=(
                            case_index % 2 == 0
                            if arm == "structured_contraction"
                            else (arm_index + case_index) % 2 == 1
                        )
                    )
                    for case_index, case_id in enumerate(CASES)
                }
            }
        arms[arm] = runs
    report = {
        "schema": stats.REPORT_SCHEMA,
        "packet_id": stats.PACKET_ID,
        "spec_digest": stats.SPEC_DIGEST,
        "corpus_digest": CORPUS_DIGEST,
        "status": "VALID",
        "required_arms": list(ARMS),
        "seeds": list(stats.FROZEN_SEEDS),
        "case_ids": list(CASES),
        "arms": arms,
        "failures": [],
        "comparisons": _comparison_rows(arms),
        "conclusion": "INCONCLUSIVE",
    }
    return report


def _partial_invalid_report(status: str = "INVALID") -> dict[str, object]:
    report = _valid_report()
    report["status"] = status
    report["arms"] = {arm: {} for arm in ARMS}
    report["failures"] = [
        {
            "arm": None,
            "seed": None,
            "case_id": None,
            "category": "isolation_violation",
            "message": "pre-image containment receipt was unavailable",
        }
    ]
    report["comparisons"] = []
    report["conclusion"] = stats.NO_SCIENTIFIC_VERDICT
    return report


class MetricTests(unittest.TestCase):
    def test_reciprocal_rank_uses_the_first_gold_hit(self) -> None:
        self.assertEqual(stats.reciprocal_rank(["x", "b", "a"], ["a", "b"]), 0.5)
        self.assertEqual(stats.reciprocal_rank(["x"], ["a"]), 0.0)
        self.assertEqual(stats.reciprocal_rank(["a"], []), 0.0)

    def test_recall_is_unique_gold_recall_at_the_requested_cutoff(self) -> None:
        ranking = ["a", "a", "x", "b", "c"]
        gold = ["a", "b", "b", "d"]
        self.assertEqual(stats.recall_at_k(ranking, gold, 1), 1 / 3)
        self.assertEqual(stats.recall_at_k(ranking, gold, 4), 2 / 3)
        self.assertEqual(stats.recall_at_k(ranking, gold, 20), 2 / 3)

    def test_first_hit_coverage_is_binary(self) -> None:
        self.assertEqual(stats.first_hit_coverage(["x", "a"], ["a"]), 1.0)
        self.assertEqual(stats.first_hit_coverage(["x"], ["a"]), 0.0)

    def test_metric_inputs_refuse_text_as_a_fake_sequence(self) -> None:
        with self.assertRaisesRegex(TypeError, "not text"):
            stats.reciprocal_rank("abc", ["a"])
        with self.assertRaisesRegex(TypeError, "not text"):
            stats.recall_at_k(["a"], "abc", 1)

    def test_recall_refuses_nonpositive_or_boolean_k(self) -> None:
        for value in (0, -1, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "positive"):
                stats.recall_at_k(["a"], ["a"], value)


class BootstrapTests(unittest.TestCase):
    def test_paired_resampling_preserves_a_constant_within_case_edge(self) -> None:
        left = {f"case-{index}": float(index) + 0.125 for index in range(12)}
        right = {f"case-{index}": float(index) for index in range(12)}
        result = stats.paired_bootstrap_difference(left, right, resamples=500, seed=7)
        self.assertEqual(result.delta, 0.125)
        self.assertEqual(result.ci_low, 0.125)
        self.assertEqual(result.ci_high, 0.125)
        self.assertTrue(result.superiority_claim_allowed)

    def test_bootstrap_is_deterministic_and_mapping_order_independent(self) -> None:
        left = {"a": 1.0, "b": 0.2, "c": 0.9, "d": 0.1}
        right = {"a": 0.1, "b": 0.8, "c": 0.3, "d": 0.4}
        expected = stats.paired_bootstrap_difference(left, right, resamples=777, seed=19)
        reversed_left = dict(reversed(tuple(left.items())))
        reversed_right = dict(reversed(tuple(right.items())))
        self.assertEqual(
            expected,
            stats.paired_bootstrap_difference(
                reversed_left, reversed_right, resamples=777, seed=19
            ),
        )

    def test_bootstrap_returns_a_percentile_interval_over_case_differences(self) -> None:
        result = stats.paired_bootstrap_difference(
            {"a": 1.0, "b": 1.0, "c": 0.0, "d": 0.0},
            {"a": 0.0, "b": 0.0, "c": 1.0, "d": 1.0},
            resamples=2_000,
            seed=stats.BOOTSTRAP_SEED,
        )
        self.assertEqual(result.delta, 0.0)
        self.assertLess(result.ci_low, 0.0)
        self.assertGreater(result.ci_high, 0.0)
        self.assertFalse(result.superiority_claim_allowed)

    def test_bootstrap_refuses_unpaired_empty_or_nonfinite_cases(self) -> None:
        with self.assertRaisesRegex(ValueError, "identical case IDs"):
            stats.paired_bootstrap_difference({"a": 1.0}, {"b": 1.0})
        with self.assertRaisesRegex(ValueError, "at least one case"):
            stats.paired_bootstrap_difference({}, {})
        with self.assertRaisesRegex(ValueError, "finite"):
            stats.paired_bootstrap_difference({"a": math.nan}, {"a": 0.0})

    def test_bootstrap_refuses_invalid_controls(self) -> None:
        for resamples in (0, -1, True):
            with self.subTest(resamples=resamples), self.assertRaisesRegex(
                ValueError, "positive integer"
            ):
                stats.paired_bootstrap_difference(
                    {"a": 1.0}, {"a": 0.0}, resamples=resamples
                )
        with self.assertRaisesRegex(ValueError, "seed must be an integer"):
            stats.paired_bootstrap_difference({"a": 1.0}, {"a": 0.0}, seed=True)


class ReportValidationTests(unittest.TestCase):
    def test_complete_valid_report_is_accepted(self) -> None:
        self.assertIsNone(
            stats.validate_report(
                _valid_report(),
                expected_corpus_digest=CORPUS_DIGEST,
                expected_case_ids=CASES,
            )
        )

    def test_invalid_unicode_and_huge_integers_fail_closed(self) -> None:
        report = _valid_report()
        old_case = report["case_ids"][0]
        report["case_ids"][0] = "\ud800"
        for runs in report["arms"].values():
            for run in runs.values():
                run["per_case"]["\ud800"] = run["per_case"].pop(old_case)
        with self.assertRaisesRegex(stats.ReportValidationError, "Unicode"):
            stats.validate_report(report)
        with self.assertRaisesRegex(stats.ReportValidationError, "Unicode"):
            stats.canonical_report_bytes(report)

        serialized = json.dumps(report, ensure_ascii=True)
        with self.assertRaisesRegex(stats.ReportValidationError, "Unicode"):
            stats.report_from_bytes(serialized)

        huge = _valid_report()
        huge["seeds"][0] = 10**400
        with self.assertRaisesRegex(stats.ReportValidationError, "64-bit"):
            stats.validate_report(huge)

    def test_valid_report_requires_failures_to_be_exactly_empty(self) -> None:
        report = _valid_report()
        report["failures"] = [
            {
                "arm": ARMS[0],
                "seed": stats.FROZEN_SEEDS[0],
                "case_id": CASES[0],
                "category": "runtime_failure",
                "message": "retriever raised after producing retained metrics",
            }
        ]
        with self.assertRaisesRegex(stats.ReportValidationError, "exactly empty"):
            stats.validate_report(report)

    def test_missing_declared_arm_seed_or_case_refuses(self) -> None:
        missing_arm = _valid_report()
        del missing_arm["arms"][ARMS[0]]
        with self.assertRaisesRegex(stats.ReportValidationError, "report.arms keys"):
            stats.validate_report(missing_arm)

        missing_seed = _valid_report()
        del missing_seed["arms"][ARMS[0]][str(stats.FROZEN_SEEDS[0])]
        with self.assertRaisesRegex(stats.ReportValidationError, "missing a frozen seed"):
            stats.validate_report(missing_seed)

        missing_case = _valid_report()
        del missing_case["arms"][ARMS[0]][str(stats.FROZEN_SEEDS[0])]["per_case"][CASES[0]]
        with self.assertRaisesRegex(stats.ReportValidationError, "incomplete"):
            stats.validate_report(missing_case)

    def test_seed_and_census_self_declarations_cannot_hide_omissions(self) -> None:
        subset = _valid_report()
        subset["required_arms"] = list(ARMS[:2])
        subset["arms"] = {arm: subset["arms"][arm] for arm in ARMS[:2]}
        with self.assertRaisesRegex(stats.ReportValidationError, "complete frozen arm census"):
            stats.validate_report(subset)

        report = _valid_report()
        report["seeds"] = list(stats.FROZEN_SEEDS[:-1])
        for runs in report["arms"].values():
            runs.pop(str(stats.FROZEN_SEEDS[-1]))
        with self.assertRaisesRegex(stats.ReportValidationError, "frozen seed policy"):
            stats.validate_report(report)

        duplicate_case = _valid_report()
        duplicate_case["case_ids"].append(CASES[0])
        with self.assertRaisesRegex(stats.ReportValidationError, "duplicates"):
            stats.validate_report(duplicate_case)

    def test_valid_report_cannot_omit_required_baseline_or_control_comparisons(self) -> None:
        report = _valid_report()
        self.assertEqual(len(report["comparisons"]), 15)
        report["comparisons"].pop()
        with self.assertRaisesRegex(
            stats.ReportValidationError, "complete frozen comparison census"
        ):
            stats.validate_report(report)

    def test_metric_maps_are_exact_finite_bounded_and_consistent(self) -> None:
        location = lambda report: report["arms"][ARMS[0]][str(stats.FROZEN_SEEDS[0])][
            "per_case"
        ][CASES[0]]

        missing = _valid_report()
        del location(missing)["reciprocal_rank"]
        with self.assertRaisesRegex(stats.ReportValidationError, "keys differ"):
            stats.validate_report(missing)

        unknown = _valid_report()
        location(unknown)["secret_metric"] = 1.0
        with self.assertRaisesRegex(stats.ReportValidationError, "unknown"):
            stats.validate_report(unknown)

        nonfinite = _valid_report()
        location(nonfinite)["reciprocal_rank"] = math.inf
        with self.assertRaisesRegex(stats.ReportValidationError, "non-finite"):
            stats.validate_report(nonfinite)

        out_of_range = _valid_report()
        location(out_of_range)["recall_at_20"] = 1.01
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            stats.validate_report(out_of_range)

        nonmonotone = _valid_report()
        location(nonmonotone).update(
            {"recall_at_1": 0.5, "recall_at_5": 0.25, "first_hit_coverage": 1.0}
        )
        with self.assertRaisesRegex(stats.ReportValidationError, "monotone"):
            stats.validate_report(nonmonotone)

        inconsistent = _valid_report()
        location(inconsistent)["first_hit_coverage"] = 1.0
        with self.assertRaisesRegex(stats.ReportValidationError, "inconsistent"):
            stats.validate_report(inconsistent)

    def test_schema_packet_spec_and_corpus_are_bound(self) -> None:
        mutations = (
            ("schema", "forest-v2.tensor-embedding-report/2", "schema"),
            ("packet_id", "another-packet", "packet_id"),
            ("spec_digest", "sha256:" + "0" * 64, "spec_digest"),
            ("corpus_digest", "not-a-digest", "corpus_digest"),
        )
        for key, value, message in mutations:
            with self.subTest(key=key):
                report = _valid_report()
                report[key] = value
                with self.assertRaisesRegex(stats.ReportValidationError, message):
                    stats.validate_report(report)

        with self.assertRaisesRegex(stats.ReportValidationError, "does not match input"):
            stats.validate_report(
                _valid_report(), expected_corpus_digest="sha256:" + "d" * 64
            )
        with self.assertRaisesRegex(stats.ReportValidationError, "case_ids"):
            stats.validate_report(_valid_report(), expected_case_ids=("case-a",))

    def test_unknown_top_level_or_comparison_fields_refuse(self) -> None:
        report = _valid_report()
        report["hidden_summary"] = "flattering"
        with self.assertRaisesRegex(stats.ReportValidationError, "unknown"):
            stats.validate_report(report)

        report = _valid_report()
        report["comparisons"][0]["p_value"] = 0.01
        with self.assertRaisesRegex(stats.ReportValidationError, "unknown"):
            stats.validate_report(report)

    def test_superiority_claim_refuses_an_interval_crossing_or_touching_zero(self) -> None:
        for low in (-0.01, 0.0):
            with self.subTest(ci_low=low):
                report = _valid_report()
                comparison = report["comparisons"][0]
                comparison.update(
                    {"delta": 0.1, "ci_low": low, "ci_high": 0.2, "superiority_claim": True}
                )
                report["conclusion"] = "ADVANCE"
                with self.assertRaisesRegex(stats.ReportValidationError, "crosses or touches"):
                    stats.validate_report(report)

    def test_diagnostic_report_rejects_advance_even_with_positive_interval(self) -> None:
        report = _valid_report()
        report["conclusion"] = "ADVANCE"
        with self.assertRaisesRegex(stats.ReportValidationError, "no ADVANCE/KILL"):
            stats.validate_report(report)

        for seed in stats.FROZEN_SEEDS:
            for case_id in CASES:
                report["arms"]["structured_contraction"][str(seed)]["per_case"][
                    case_id
                ] = _metrics(hit=True)
                report["arms"]["flattened_cosine_same_scalars"][str(seed)][
                    "per_case"
                ][case_id] = _metrics(hit=False)
        _refresh_comparisons(report)
        comparison = _find_comparison(
            report,
            "structured_contraction",
            "flattened_cosine_same_scalars",
        )
        comparison.update(
            {"delta": 0.5, "ci_low": 0.5, "ci_high": 0.5, "superiority_claim": True}
        )
        with self.assertRaisesRegex(stats.ReportValidationError, "no ADVANCE/KILL"):
            stats.validate_report(report)

    def test_diagnostic_report_rejects_kill_without_a_decision_api(self) -> None:
        report = _valid_report()
        report["conclusion"] = "KILL"
        with self.assertRaisesRegex(stats.ReportValidationError, "no ADVANCE/KILL"):
            stats.validate_report(report)

        for arm in ARMS:
            for seed in stats.FROZEN_SEEDS:
                for case_id in CASES:
                    report["arms"][arm][str(seed)]["per_case"][case_id] = _metrics(
                        hit=False
                    )
        _refresh_comparisons(report)
        with self.assertRaisesRegex(stats.ReportValidationError, "no ADVANCE/KILL"):
            stats.validate_report(report)

    def test_comparison_numbers_are_recomputed_from_seed_averaged_cases(self) -> None:
        report = _valid_report()
        report["comparisons"][0]["ci_low"] = 0.01
        with self.assertRaisesRegex(stats.ReportValidationError, "paired per-case"):
            stats.validate_report(report)

    def test_invalid_and_blocked_reports_retain_failures_but_never_kill(self) -> None:
        for status in ("INVALID", "BLOCKED"):
            with self.subTest(status=status):
                report = _partial_invalid_report(status)
                self.assertIsNone(stats.validate_report(report))
                report["conclusion"] = "KILL"
                with self.assertRaisesRegex(stats.ReportValidationError, "no ADVANCE/KILL"):
                    stats.validate_report(report)

        no_failure = _partial_invalid_report()
        no_failure["failures"] = []
        with self.assertRaisesRegex(stats.ReportValidationError, "retain its failures"):
            stats.validate_report(no_failure)

    def test_partial_invalid_data_is_strict_and_every_gap_needs_a_failure(self) -> None:
        report = _partial_invalid_report()
        report["failures"][0].update(
            {"arm": ARMS[0], "seed": stats.FROZEN_SEEDS[0], "case_id": CASES[0]}
        )
        with self.assertRaisesRegex(stats.ReportValidationError, "no retained failure"):
            stats.validate_report(report)

        malformed = _partial_invalid_report()
        malformed["arms"][ARMS[0]][str(stats.FROZEN_SEEDS[0])] = {
            "per_case": {CASES[0]: {**_metrics(), "reciprocal_rank": math.nan}}
        }
        with self.assertRaisesRegex(stats.ReportValidationError, "non-finite"):
            stats.validate_report(malformed)

    def test_invalidating_failure_cannot_be_hidden_inside_a_valid_report(self) -> None:
        report = _valid_report()
        report["failures"] = [
            {
                "arm": ARMS[0],
                "seed": stats.FROZEN_SEEDS[0],
                "case_id": CASES[0],
                "category": "budget_mismatch",
                "message": "513 scalars were used",
            }
        ]
        with self.assertRaisesRegex(stats.ReportValidationError, "make a report INVALID"):
            stats.validate_report(report)

    def test_invalid_report_cannot_retain_a_superiority_claim(self) -> None:
        report = _partial_invalid_report()
        report["comparisons"] = copy.deepcopy(_valid_report()["comparisons"])
        report["comparisons"][0].update(
            {"delta": 0.2, "ci_low": 0.1, "ci_high": 0.3, "superiority_claim": True}
        )
        with self.assertRaisesRegex(stats.ReportValidationError, "cannot claim superiority"):
            stats.validate_report(report)


class CanonicalReportTests(unittest.TestCase):
    def test_strict_report_loader_roundtrips_canonical_bytes(self) -> None:
        report = _valid_report()
        payload = stats.canonical_report_bytes(report)
        self.assertEqual(
            stats.report_from_bytes(
                payload,
                expected_corpus_digest=CORPUS_DIGEST,
                expected_case_ids=CASES,
            ),
            report,
        )

    def test_strict_report_loader_rejects_duplicate_keys_before_validation(self) -> None:
        payload = stats.canonical_report_bytes(_valid_report())
        duplicate = b'{"schema":"shadow",' + payload[1:]
        with self.assertRaisesRegex(stats.ReportValidationError, "duplicate JSON key"):
            stats.report_from_bytes(duplicate)

    def test_strict_report_loader_rejects_nonfinite_invalid_and_non_utf8_json(self) -> None:
        fixtures = (
            (b'{"schema":NaN}', "non-finite"),
            (b'{"schema":', "invalid serialized report"),
            (b"\xff", "not UTF-8"),
        )
        for payload, message in fixtures:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(stats.ReportValidationError, message):
                    stats.report_from_bytes(payload)

    def test_canonical_bytes_ignore_object_insertion_order_and_preserve_utf8(self) -> None:
        report = _valid_report()
        report["case_ids"] = ["case-a", "case-ß"]
        for runs in report["arms"].values():
            for run in runs.values():
                run["per_case"]["case-ß"] = run["per_case"].pop("case-b")
        reordered = dict(reversed(tuple(report.items())))
        first = stats.canonical_report_bytes(report)
        second = stats.canonical_report_bytes(reordered)
        self.assertEqual(first, second)
        self.assertIn("ß".encode("utf-8"), first)
        self.assertNotIn(b"\\u00df", first)

    def test_report_digest_is_prefixed_sha256_of_canonical_bytes(self) -> None:
        report = _valid_report()
        before = copy.deepcopy(report)
        payload = stats.canonical_report_bytes(report)
        self.assertEqual(
            stats.report_digest(report),
            "sha256:" + hashlib.sha256(payload).hexdigest(),
        )
        self.assertEqual(report, before, "validation and serialization must be pure")
        self.assertEqual(json.loads(payload.decode("utf-8")), report)

    def test_cyclic_or_non_json_report_refuses_before_serialization(self) -> None:
        report = _valid_report()
        report["failures"].append(report)
        with self.assertRaisesRegex(stats.ReportValidationError, "cycle"):
            stats.canonical_report_bytes(report)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

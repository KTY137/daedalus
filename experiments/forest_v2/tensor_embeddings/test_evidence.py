"""Frozen spec/result identity and retained-negative-evidence checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from experiments.forest_v2.tensor_embeddings.benchmark import EVALUATED_RANK_LIMIT
from experiments.forest_v2.tensor_embeddings.encoding import HASH_FEATURE_FAMILY
from experiments.forest_v2.tensor_embeddings.stats import (
    ReportValidationError,
    SPEC_DIGEST,
    validate_report,
)


ROOT = Path(__file__).resolve().parent


def _canonical_digest(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def test_embedded_spec_digest_and_feature_family_match_frozen_json() -> None:
    path = ROOT / "EXPERIMENT_SPEC.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    assert _canonical_digest(path) == SPEC_DIGEST
    assert spec["hash_feature_family"] == HASH_FEATURE_FAMILY
    assert spec["filler_backend"] == "signed-subword-hash-shared-word-p4-s4/2"
    assert spec["dense_scalar_budget"] == (
        len(spec["planes"]) * len(spec["roles"]) * spec["feature_dimension"]
    )
    assert EVALUATED_RANK_LIMIT == max(spec["cutoffs"])


def test_superseded_role_salted_smoke_is_retained_but_rejected_by_current_spec() -> None:
    report = json.loads(
        (ROOT / "results" / "s09_c00_smoke.json").read_text(encoding="utf-8")
    )
    assert report["spec_digest"] == (
        "sha256:5ac3be24819682fea3ad2c49fe8dd01ab755002e258bd169dc26c8f7de18461f"
    )
    assert report["spec_digest"] != SPEC_DIGEST
    with pytest.raises(ReportValidationError, match="spec_digest"):
        validate_report(report)
    assert report["status"] == "VALID"
    assert report["conclusion"] == "INCONCLUSIVE"
    assert report["comparisons"][0]["delta"] == 0.0
    assert report["comparisons"][0]["superiority_claim"] is False
    for arm in report["arms"].values():
        for run in arm.values():
            assert run["per_case"]["c00"]["reciprocal_rank"] == 0.0


def test_cost_failures_are_retained_with_no_speedup_claim() -> None:
    note = (ROOT / "PERFORMANCE_NOTE.md").read_text(encoding="utf-8")
    collapsed = " ".join(note.split())
    assert "more than 150 seconds" in collapsed
    assert "more than 120 seconds" in collapsed
    assert "must not be cited as a tensor speedup" in collapsed
    assert "not scientifically evaluable" in note
    assert "superseded" in note


def test_current_spec_false_full_order_failure_is_retained_as_invalid() -> None:
    summary = json.loads(
        (ROOT / "results" / "s09_c00_smoke_v2_invalid.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["implementation_revision"] == (
        "c735f415c863a269e0f28be79543f8e309bf230c"
    )
    assert summary["status"] == "INVALID"
    assert summary["conclusion"] == "NO_SCIENTIFIC_VERDICT"
    assert summary["automatic_promotions"] == 0
    assert summary["universe_size"] == 4376
    assert summary["elapsed_seconds_unvalidated"] == 753.704
    assert len(summary["failures"]) == 10
    assert {
        failure["category"] for failure in summary["failures"]
    } == {"tensor_vector_bilinear_equivalence_failure"}


def test_corrected_current_spec_smoke_retains_no_superiority_claim() -> None:
    summary = json.loads(
        (ROOT / "results" / "s09_c00_smoke_v2.json").read_text(encoding="utf-8")
    )
    assert summary["implementation_revision"] == (
        "8562997667931e847a26776a86e5ba74d10163cb"
    )
    assert summary["status"] == "VALID"
    assert summary["conclusion"] == "INCONCLUSIVE"
    assert summary["automatic_promotions"] == 0
    assert summary["failures"] == []
    assert len(summary["comparisons"]) == 15
    assert all(
        comparison["superiority_claim"] is False
        for comparison in summary["comparisons"]
    )
    assert summary["full_report_digest"] == (
        "sha256:629663bc24452837aa853e94452bbf9225d58046c8a2d6e1b1c99f684fb99609"
    )
    structured = summary["arm_metrics"]["structured_contraction"]
    bilinear = summary["arm_metrics"]["flattened_bilinear_same_kernel"]
    assert structured == bilinear
    assert all(
        metrics["reciprocal_rank"] == 0.0
        for case in structured.values()
        for metrics in case.values()
    )

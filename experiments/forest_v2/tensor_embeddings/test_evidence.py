"""Frozen spec/result identity and retained-negative-evidence checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from experiments.forest_v2.tensor_embeddings.benchmark import EVALUATED_RANK_LIMIT
from experiments.forest_v2.tensor_embeddings.contracts import canonical_digest
from experiments.forest_v2.tensor_embeddings.encoding import HASH_FEATURE_FAMILY
from experiments.forest_v2.tensor_embeddings.stats import (
    EVALUATION_PROTOCOL_DIGEST,
    ReportValidationError,
    SPEC_DIGEST,
    report_digest,
    report_from_bytes,
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


def test_embedded_evaluation_protocol_digest_matches_frozen_v2_json() -> None:
    path = ROOT / "EVALUATION_PROTOCOL_V2.json"
    assert _canonical_digest(path) == EVALUATION_PROTOCOL_DIGEST
    protocol = json.loads(path.read_text(encoding="utf-8"))
    assert protocol["resampling"]["case_unit"] == "base_case"
    assert protocol["resampling"]["within_case_variant_aggregation"] == (
        "arithmetic_mean_over_present_variants"
    )
    assert protocol["decision_authority"] == "none"


def test_superseded_role_salted_smoke_is_retained_but_rejected_by_current_spec() -> None:
    report = json.loads(
        (ROOT / "results" / "s09_c00_smoke.json").read_text(encoding="utf-8")
    )
    assert report["spec_digest"] == (
        "sha256:5ac3be24819682fea3ad2c49fe8dd01ab755002e258bd169dc26c8f7de18461f"
    )
    assert report["spec_digest"] != SPEC_DIGEST
    # The artifact is multiply superseded: its role-salted spec digest differs,
    # and the current /2 report shape/protocol refuses /1 intervals.
    with pytest.raises(ReportValidationError, match="keys differ"):
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


def test_superseded_v1_current_spec_smoke_retains_no_superiority_claim() -> None:
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


def test_project_tct_diagnostic_manifest_binds_full_v2_report_without_raw_content() -> None:
    manifest_path = ROOT / "results" / "project_tct_analysis_physics_manifest_v1.json"
    report_path = ROOT / "results" / "project_tct_analysis_physics_report_v2.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    binding = manifest["benchmark_binding"]
    report = report_from_bytes(
        report_path.read_bytes(),
        expected_corpus_digest=binding["corpus_digest"],
        expected_case_ids=tuple(binding["case_ids"]),
    )

    body = dict(manifest)
    manifest_id = body.pop("manifest_id")
    assert manifest_id == "sha256:" + canonical_digest(
        body, domain="tensor-project-case-manifest/1"
    )
    assert report_digest(report) == binding["report_digest"]
    assert report["protocol_digest"] == EVALUATION_PROTOCOL_DIGEST
    assert binding["protocol_digest"] == EVALUATION_PROTOCOL_DIGEST
    assert binding["report_path"] == report_path.relative_to(ROOT).as_posix()

    selection = manifest["selection"]
    candidates = selection["candidate_inputs"]
    assert len(candidates) == selection["candidate_count"] == 127
    assert [row["path"] for row in candidates] == sorted(
        row["path"] for row in candidates
    )
    assert len({row["path"] for row in candidates}) == len(candidates)
    assert sum(row["size"] for row in candidates) == selection["source_bytes"]
    assert sum(row["visible_bytes"] for row in candidates) == selection["visible_bytes"]
    assert sum(row["size"] > row["content_budget"] for row in candidates) == (
        selection["truncated_candidate_count"]
    )
    assert selection["candidate_census_digest"] == "sha256:" + canonical_digest(
        candidates,
        domain=selection["candidate_census_digest_domain"],
    )
    assert all(row["mode"] == "100644" for row in candidates)
    assert not any(row["path"].startswith("TCT_app/tests/") for row in candidates)
    assert not any(row["path"].startswith("TCT_app/devices/") for row in candidates)
    assert not any(
        row["path"] == "TCT_app/configs/devices.yaml" for row in candidates
    )

    evaluator = manifest["evaluator"]
    assert evaluator["recency_digest"] == "sha256:" + canonical_digest(
        evaluator["recency_ranking"],
        domain=evaluator["recency_digest_domain"],
    )
    report_candidate_inputs = [
        {
            key: row[key]
            for key in ("path", "blob", "size", "content_budget", "text_digest")
        }
        for row in candidates
    ]
    case_manifests = [
        {
            "case_id": manifest["query"]["case_id"],
            "variant": query["variant"],
            "revision": manifest["source"]["preimage_revision"],
            "query_digest": query["query_digest"],
            "candidate_inputs": report_candidate_inputs,
            "gold": evaluator["gold"],
            "recency_ranking": evaluator["recency_ranking"],
        }
        for query in manifest["query"]["variants"]
    ]
    assert report["corpus_digest"] == "sha256:" + canonical_digest(
        case_manifests,
        domain="tensor-benchmark-corpus/1",
    )

    assert manifest["lane"] == "local_only"
    assert manifest["security"]["network_calls"] == 0
    assert manifest["security"]["raw_candidate_content_retained"] is False
    assert manifest["security"]["secret_values_retained"] is False
    assert manifest["claims"] == {
        "classification": "diagnostic_example",
        "primary_effect_claim_membership": False,
        "scientific_verdict": "NO_SCIENTIFIC_VERDICT",
        "second_repository_transfer_evidence": False,
        "tuning_authority": False,
    }
    assert manifest["automatic_promotions"] == 0
    assert manifest["query"]["text_retained"] is False
    assert "C:\\\\Users" not in manifest_text
    assert "@anthropic.com" not in manifest_text
    assert report["status"] == "VALID"
    assert report["conclusion"] == "INCONCLUSIVE"
    assert not report["failures"]
    assert len(report["comparisons"]) == 45
    assert {row["variant"] for row in report["comparisons"]} == {
        "all",
        "raw",
        "scrubbed",
    }
    assert all(row["case_count"] == 1 for row in report["comparisons"])
    assert all(row["superiority_claim"] is False for row in report["comparisons"])

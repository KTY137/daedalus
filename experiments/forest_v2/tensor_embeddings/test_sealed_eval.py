"""Adversarial tests for the gold-separated sealed-ranking evaluator."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from experiments.forest_v2.tensor_embeddings import sealed_eval as sealed
from experiments.forest_v2.tensor_embeddings.stats import (
    FROZEN_SEEDS,
    NO_SCIENTIFIC_VERDICT,
    PACKET_ID,
    SPEC_DIGEST,
)


def _sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _revision(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()


def _candidate(case_id: str, index: int, revision: str) -> dict[str, object]:
    candidate_id = f"{case_id}/file-{index:02d}.py"
    size = 100 + index
    return {
        "candidate_id": candidate_id,
        "source_locator": candidate_id,
        "source_revision": revision,
        "source_digest": _sha(f"source:{case_id}:{index}"),
        "blob_id": "git-sha1:" + hashlib.sha1(
            f"blob:{case_id}:{index}".encode("utf-8")
        ).hexdigest(),
        "size_bytes": size,
        "visible_bytes": size,
        "visible_digest": _sha(f"visible:{case_id}:{index}"),
    }


def _input_manifest(case_count: int = 2) -> dict[str, object]:
    cases = []
    for index in range(case_count):
        case_id = f"case-{index:02d}"
        revision = _revision(f"preimage:{case_id}")
        repository_id = _sha(f"repository:{index % 2}")
        candidates = [_candidate(case_id, item, revision) for item in range(21)]
        candidate_digest = sealed.candidate_manifest_digest(candidates)
        source_digest = sealed.source_manifest_digest(
            repository_id=repository_id,
            source_revision=revision,
            preimage_revision=revision,
            candidate_digest=candidate_digest,
        )
        cases.append(
            {
                "case_id": case_id,
                "repository_id": repository_id,
                "source_revision": revision,
                "preimage_revision": revision,
                "source_manifest_digest": source_digest,
                "candidate_manifest_digest": candidate_digest,
                "candidates": candidates,
                "queries": {
                    "raw": {
                        "query_digest": _sha(f"raw query:{case_id}"),
                        "query_bytes": 20 + index,
                    },
                    "scrubbed": {
                        "query_digest": _sha(f"scrubbed query:{case_id}"),
                        "query_bytes": 12 + index,
                    },
                },
            }
        )
    payload = {
        "packet_id": PACKET_ID,
        "spec_digest": SPEC_DIGEST,
        "implementation_revision": _revision("sealed evaluator implementation"),
        "taskset_digest": _sha("held-out-taskset"),
        "tuning_data_digest": _sha("different-tuning-data"),
        "evaluation_split": "held-out",
        "query_variants": list(sealed.QUERY_VARIANTS),
        "seeds": list(FROZEN_SEEDS),
        "required_arms": list(sealed.REQUIRED_ARMS),
        "dense_scalar_budget": sealed.DENSE_SCALAR_BUDGET,
        "dense_equivalent_float64_bytes": sealed.DENSE_EQUIVALENT_FLOAT64_BYTES,
        "candidate_content_budget_bytes": sealed.CANDIDATE_CONTENT_BUDGET_BYTES,
        "max_file_bytes": sealed.MAX_FILE_BYTES,
        "cases": cases,
    }
    return sealed.seal_manifest(sealed.INPUT_MANIFEST_SCHEMA, payload)


def _rankings_manifest(
    inputs: dict[str, object], *, outcome: str = "perfect"
) -> dict[str, object]:
    payload = inputs["payload"]
    assert isinstance(payload, dict)
    rows = []
    for arm in sealed.REQUIRED_ARMS:
        for seed in FROZEN_SEEDS:
            for case in payload["cases"]:
                candidates = [item["candidate_id"] for item in case["candidates"]]
                gold = candidates[-1]
                ordinary = candidates[: sealed.MAX_RANK]
                winner = [gold, *candidates[: sealed.MAX_RANK - 1]]
                ranking = winner if outcome == "perfect" and arm == sealed.PRIMARY_ARM else ordinary
                visible_bytes = sum(item["visible_bytes"] for item in case["candidates"])
                for variant in sealed.QUERY_VARIANTS:
                    tensor_arm = arm in sealed.TENSOR_ARMS
                    rows.append(
                        {
                            "arm": arm,
                            "seed": seed,
                            "case_id": case["case_id"],
                            "variant": variant,
                            "preimage_revision": case["preimage_revision"],
                            "source_manifest_digest": case["source_manifest_digest"],
                            "candidate_manifest_digest": case["candidate_manifest_digest"],
                            "query_digest": case["queries"][variant]["query_digest"],
                            "budget": {
                                "tensor_dense_scalars": (
                                    sealed.DENSE_SCALAR_BUDGET if tensor_arm else 0
                                ),
                                "tensor_dense_equivalent_float64_bytes": (
                                    sealed.DENSE_EQUIVALENT_FLOAT64_BYTES if tensor_arm else 0
                                ),
                                "candidate_content_budget_bytes": (
                                    sealed.CANDIDATE_CONTENT_BUDGET_BYTES
                                ),
                                "candidate_input_bytes": visible_bytes,
                                "query_input_bytes": case["queries"][variant]["query_bytes"],
                            },
                            "ranking": list(ranking),
                        }
                    )
    return sealed.seal_manifest(
        sealed.RANKINGS_MANIFEST_SCHEMA,
        {
            "packet_id": PACKET_ID,
            "spec_digest": SPEC_DIGEST,
            "input_manifest_digest": inputs["digest"],
            "implementation_revision": payload["implementation_revision"],
            "rows": rows,
            "failures": [],
        },
    )


def _gold_manifest(inputs: dict[str, object]) -> dict[str, object]:
    payload = inputs["payload"]
    assert isinstance(payload, dict)
    rows = []
    for case in payload["cases"]:
        gold = case["candidates"][-1]["candidate_id"]
        for variant in sealed.QUERY_VARIANTS:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "variant": variant,
                    "preimage_revision": case["preimage_revision"],
                    "gold_candidate_ids": [gold],
                }
            )
    return sealed.seal_manifest(
        sealed.GOLD_MANIFEST_SCHEMA,
        {
            "packet_id": PACKET_ID,
            "input_manifest_digest": inputs["digest"],
            "taskset_digest": payload["taskset_digest"],
            "label_source_digest": payload["taskset_digest"],
            "cases": rows,
        },
    )


def _isolation_receipt(
    inputs: dict[str, object], rankings: dict[str, object]
) -> dict[str, object]:
    payload = inputs["payload"]
    assert isinstance(payload, dict)
    return sealed.seal_manifest(
        sealed.ISOLATION_RECEIPT_SCHEMA,
        {
            "packet_id": PACKET_ID,
            "input_manifest_digest": inputs["digest"],
            "rankings_manifest_digest": rankings["digest"],
            "implementation_revision": payload["implementation_revision"],
            "taskset_digest": payload["taskset_digest"],
            "isolator_id": "s09-preimage-bare-clone/1",
            "preimage_only": True,
            "future_objects_absent": True,
            "gold_unavailable_during_ranking": True,
            "network_disabled": True,
            "writes_disabled": True,
            "automatic_promotions": 0,
            "cases": [
                {
                    "case_id": case["case_id"],
                    "preimage_revision": case["preimage_revision"],
                    "source_manifest_digest": case["source_manifest_digest"],
                    "isolated_repository_digest": _sha(
                        "isolated:" + case["source_manifest_digest"]
                    ),
                }
                for case in payload["cases"]
            ],
        },
    )


def _campaign(*, outcome: str = "perfect") -> tuple[dict[str, object], ...]:
    inputs = _input_manifest()
    rankings = _rankings_manifest(inputs, outcome=outcome)
    gold = _gold_manifest(inputs)
    isolation = _isolation_receipt(inputs, rankings)
    return inputs, rankings, gold, isolation


def _reseal(manifest: dict[str, object]) -> dict[str, object]:
    return sealed.seal_manifest(manifest["schema"], manifest["payload"])


def _refresh_report_id(report: dict[str, object]) -> None:
    body = {key: value for key, value in report.items() if key != "report_id"}
    report["report_id"] = sealed._content_digest(
        body, domain=sealed._SEALED_REPORT_ID_DOMAIN
    )


def _assert_blocked(report: dict[str, object]) -> None:
    assert report["status"] == "BLOCKED"
    assert report["eligibility"] == "INELIGIBLE"
    assert report["conclusion"] == NO_SCIENTIFIC_VERDICT
    assert report["automatic_promotions"] == 0
    assert report["failures"]
    assert report["comparisons"] == []


def test_perfect_self_addressed_campaign_is_descriptive_only() -> None:
    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="perfect"))
    assert report["status"] == sealed.STRUCTURALLY_VALID_UNANCHORED
    assert report["eligibility"] == sealed.STRUCTURALLY_VALID_UNANCHORED
    assert report["conclusion"] == NO_SCIENTIFIC_VERDICT
    assert report["automatic_promotions"] == 0
    assert report["required_arms"] == list(sealed.REQUIRED_ARMS)
    assert report["missing_decision_prerequisites"] == list(
        sealed.MISSING_DECISION_PREREQUISITES
    )
    assert {item["variant"] for item in report["case_census"]} == {"raw", "scrubbed"}
    primary = next(
        item
        for item in report["comparisons"]
        if item["right_arm"] == sealed.REFERENCE_ARM and item["variant"] == "all"
    )
    assert primary["delta"] == 1.0
    assert primary["ci_low"] == 1.0
    assert primary["case_count"] == 2
    assert primary["superiority_claim"] is False
    assert all(item["superiority_claim"] is False for item in report["comparisons"])
    assert report["report_id"].startswith("sha256:")

    first = sealed.canonical_sealed_report_bytes(report)
    second = sealed.canonical_sealed_report_bytes(copy.deepcopy(report))
    assert first == second
    assert sealed.sealed_report_digest(report) == sealed.sealed_report_digest(
        json.loads(first)
    )


def test_complete_equal_rankings_remain_descriptive_without_trust_anchor() -> None:
    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="tie"))
    assert report["status"] == sealed.STRUCTURALLY_VALID_UNANCHORED
    assert report["eligibility"] == sealed.STRUCTURALLY_VALID_UNANCHORED
    assert report["conclusion"] == NO_SCIENTIFIC_VERDICT
    assert report["automatic_promotions"] == 0
    assert all(item["superiority_claim"] is False for item in report["comparisons"])


def test_complete_but_mixed_campaign_remains_descriptive() -> None:
    inputs, rankings, gold, _ = _campaign(outcome="perfect")
    for row in rankings["payload"]["rows"]:
        if row["arm"] == sealed.PRIMARY_ARM and row["case_id"] == "case-01":
            candidates = inputs["payload"]["cases"][1]["candidates"]
            row["ranking"] = [item["candidate_id"] for item in candidates[: sealed.MAX_RANK]]
    rankings = _reseal(rankings)
    isolation = _isolation_receipt(inputs, rankings)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    assert report["status"] == sealed.STRUCTURALLY_VALID_UNANCHORED
    assert report["conclusion"] == NO_SCIENTIFIC_VERDICT
    assert report["failures"] == []


def test_digest_tampering_blocks_before_gold_is_scored() -> None:
    inputs, rankings, gold, isolation = _campaign()
    rankings["payload"]["rows"][0]["ranking"].reverse()
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "does not address" in report["failures"][0]["message"]


@pytest.mark.parametrize("missing_arm", ["bm25", "fusion_rrf", "role_label_permutation"])
def test_missing_any_required_baseline_or_control_blocks(missing_arm: str) -> None:
    inputs, rankings, gold, isolation = _campaign()
    rankings["payload"]["rows"] = [
        row for row in rankings["payload"]["rows"] if row["arm"] != missing_arm
    ]
    rankings = _reseal(rankings)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "Cartesian product" in report["failures"][0]["message"]


def test_missing_seed_or_variant_is_not_scientific_evidence() -> None:
    inputs, rankings, gold, isolation = _campaign()
    rankings["payload"]["rows"] = [
        row
        for row in rankings["payload"]["rows"]
        if not (row["seed"] == FROZEN_SEEDS[-1] and row["variant"] == "scrubbed")
    ]
    rankings = _reseal(rankings)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)

    inputs, rankings, gold, isolation = _campaign()
    del inputs["payload"]["cases"][0]["queries"]["scrubbed"]
    inputs = _reseal(inputs)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "key mismatch" in report["failures"][0]["message"]


@pytest.mark.parametrize(
    "budget_field,bad_value",
    [
        ("tensor_dense_scalars", 513),
        ("tensor_dense_equivalent_float64_bytes", 4097),
        ("candidate_content_budget_bytes", 65_537),
        ("candidate_input_bytes", 1),
        ("query_input_bytes", 1),
    ],
)
def test_any_unequal_budget_blocks_without_kill(budget_field: str, bad_value: int) -> None:
    inputs, rankings, gold, isolation = _campaign(outcome="tie")
    structured = next(
        row for row in rankings["payload"]["rows"] if row["arm"] == sealed.PRIMARY_ARM
    )
    structured["budget"][budget_field] = bad_value
    rankings = _reseal(rankings)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "budget" in report["failures"][0]["message"]


def test_candidate_count_above_frozen_cap_blocks_before_candidate_processing() -> None:
    inputs, rankings, gold, isolation = _campaign(outcome="tie")
    assert sealed.MAX_CANDIDATES_PER_CASE == 65_536
    inputs["payload"]["cases"][0]["candidates"] = [None] * (
        sealed.MAX_CANDIDATES_PER_CASE + 1
    )
    inputs = _reseal(inputs)

    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)

    _assert_blocked(report)
    assert "candidate count" in report["failures"][0]["message"]
    assert "65536" in report["failures"][0]["message"]


def test_query_and_candidate_path_bytes_obey_the_encoder_caps() -> None:
    inputs, rankings, gold, isolation = _campaign(outcome="tie")
    inputs["payload"]["cases"][0]["queries"]["raw"]["query_bytes"] = 65_537
    report = sealed.evaluate_sealed_rankings(
        _reseal(inputs), rankings, gold, isolation
    )
    _assert_blocked(report)
    assert "query_bytes exceeds" in report["failures"][0]["message"]

    inputs, rankings, gold, isolation = _campaign(outcome="tie")
    oversized = "p" * 65_537
    candidate = inputs["payload"]["cases"][0]["candidates"][0]
    candidate["candidate_id"] = oversized
    candidate["source_locator"] = oversized
    report = sealed.evaluate_sealed_rankings(
        _reseal(inputs), rankings, gold, isolation
    )
    _assert_blocked(report)
    assert "candidate_id exceeds" in report["failures"][0]["message"]


def test_malformed_seed_is_a_sealed_error_not_a_typeerror() -> None:
    inputs, rankings, gold, isolation = _campaign(outcome="tie")
    rankings["payload"]["rows"][0]["seed"] = {}
    report = sealed.evaluate_sealed_rankings(
        inputs, _reseal(rankings), gold, isolation
    )
    _assert_blocked(report)
    assert "seed" in report["failures"][0]["message"]


def test_revision_candidate_and_source_binding_are_atomic() -> None:
    inputs, rankings, gold, isolation = _campaign()
    inputs["payload"]["cases"][0]["source_revision"] = _revision("different")
    inputs = _reseal(inputs)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "partial revision" in report["failures"][0]["message"]

    inputs, rankings, gold, isolation = _campaign()
    inputs["payload"]["cases"][0]["candidates"][0]["visible_bytes"] += 1
    inputs = _reseal(inputs)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "byte cap" in report["failures"][0]["message"]


def test_gold_leak_fields_are_structurally_rejected_from_ranking_manifest() -> None:
    inputs, rankings, gold, isolation = _campaign(outcome="tie")
    rankings["payload"]["rows"][0]["gold_candidate_ids"] = ["answer-key"]
    rankings = _reseal(rankings)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "unknown=['gold_candidate_ids']" in report["failures"][0]["message"]


@pytest.mark.parametrize(
    "field",
    [
        "preimage_only",
        "future_objects_absent",
        "gold_unavailable_during_ranking",
        "network_disabled",
        "writes_disabled",
    ],
)
def test_every_isolation_claim_is_mandatory(field: str) -> None:
    inputs, rankings, gold, isolation = _campaign(outcome="tie")
    isolation["payload"][field] = False
    isolation = _reseal(isolation)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "isolation" in report["failures"][0]["message"]


def test_isolation_receipt_must_bind_exact_ranking_bytes() -> None:
    inputs, rankings, gold, isolation = _campaign()
    rankings["payload"]["failures"].append(
        {
            "arm": "bm25",
            "seed": FROZEN_SEEDS[0],
            "case_id": "case-00",
            "variant": "raw",
            "category": "runtime_failure",
            "message": "retained external failure",
        }
    )
    rankings = _reseal(rankings)
    isolation = _isolation_receipt(inputs, rankings)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "retained 1 failed" in report["failures"][0]["message"]


def test_gold_is_separate_revision_bound_and_cannot_invent_candidates() -> None:
    inputs, rankings, gold, isolation = _campaign()
    gold["payload"]["cases"][0]["gold_candidate_ids"] = ["future/answer.py"]
    gold = _reseal(gold)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "outside candidates" in report["failures"][0]["message"]

    inputs, rankings, gold, isolation = _campaign()
    gold["payload"]["cases"][0]["preimage_revision"] = _revision("future")
    gold = _reseal(gold)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "revision" in report["failures"][0]["message"]


def test_held_out_taskset_cannot_equal_tuning_data() -> None:
    inputs, rankings, gold, isolation = _campaign(outcome="tie")
    inputs["payload"]["tuning_data_digest"] = inputs["payload"]["taskset_digest"]
    inputs = _reseal(inputs)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    _assert_blocked(report)
    assert "held-out" in report["failures"][0]["message"]


def test_supplied_objects_are_data_only_and_never_invoked() -> None:
    class Bomb:
        called = False

        def __call__(self):
            self.called = True
            raise AssertionError("must never execute")

    inputs, _, gold, isolation = _campaign()
    bomb = Bomb()
    report = sealed.evaluate_sealed_rankings(inputs, bomb, gold, isolation)
    _assert_blocked(report)
    assert bomb.called is False
    assert "ordinary JSON" in report["failures"][0]["message"]


def test_module_imports_no_retriever_benchmark_or_effect_api() -> None:
    path = Path(sealed.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("retriever" in name or "benchmark" in name for name in imported)
    assert not imported & {
        "socket",
        "subprocess",
        "pathlib",
        "requests",
        "urllib",
        "sqlite3",
    }


def test_manifest_parser_rejects_duplicate_keys_and_nonfinite_numbers() -> None:
    with pytest.raises(sealed.SealedEvaluationError, match="duplicate"):
        sealed.manifest_from_bytes('{"schema":"x","schema":"y"}')
    with pytest.raises(sealed.SealedEvaluationError, match="non-finite"):
        sealed.manifest_from_bytes('{"value":NaN}')
    with pytest.raises(sealed.SealedEvaluationError, match="Unicode surrogate"):
        sealed.manifest_from_bytes('{"value":"\\ud800"}')
    with pytest.raises(sealed.SealedEvaluationError, match="64-bit"):
        sealed.manifest_from_bytes('{"value":10000000000000000000000000000000000000000}')


def test_sealed_report_parser_rejects_duplicate_keys() -> None:
    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="tie"))
    raw = sealed.canonical_sealed_report_bytes(report).decode("utf-8")
    duplicated = raw.replace(
        '"schema":', f'"schema":"{sealed.SEALED_REPORT_SCHEMA}","schema":', 1
    )
    with pytest.raises(sealed.SealedEvaluationError, match="duplicate"):
        sealed.sealed_report_from_bytes(duplicated)


def test_blocked_report_can_never_be_relabelled_as_kill() -> None:
    inputs, rankings, gold, isolation = _campaign()
    isolation["payload"]["preimage_only"] = False
    isolation = _reseal(isolation)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    report["conclusion"] = "KILL"
    with pytest.raises(sealed.SealedEvaluationError, match="no scientific verdict"):
        sealed.validate_sealed_report(report)


def test_unanchored_report_cannot_be_relabelled_or_tampered_before_transport() -> None:
    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="perfect"))
    report["conclusion"] = "KILL"
    with pytest.raises(sealed.SealedEvaluationError, match="NO_SCIENTIFIC_VERDICT"):
        sealed.canonical_sealed_report_bytes(report)
    with pytest.raises(sealed.SealedEvaluationError, match="NO_SCIENTIFIC_VERDICT"):
        sealed.sealed_report_digest(report)

    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="perfect"))
    report["comparisons"][0]["delta"] = 0.0
    with pytest.raises(sealed.SealedEvaluationError, match="comparisons do not recompute"):
        sealed.canonical_sealed_report_bytes(report)

    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="perfect"))
    report["measurements"][0]["per_case"][0]["reciprocal_rank"] = 0.5
    with pytest.raises(sealed.SealedEvaluationError):
        sealed.canonical_sealed_report_bytes(report)

    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="perfect"))
    report["comparisons"][0]["superiority_claim"] = True
    with pytest.raises(sealed.SealedEvaluationError, match="comparisons do not recompute"):
        sealed.canonical_sealed_report_bytes(report)


def test_report_id_rejects_secondary_metric_tampering() -> None:
    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="perfect"))
    measurement = next(
        item for item in report["measurements"] if item["arm"] == sealed.PRIMARY_ARM
    )
    row = measurement["per_case"][0]
    row["recall_at_1"] = 0.5
    row["recall_at_5"] = 0.5
    row["recall_at_10"] = 0.5
    row["recall_at_20"] = 0.5
    with pytest.raises(sealed.SealedEvaluationError, match="report_id"):
        sealed.validate_sealed_report(report)


def test_standalone_relations_reject_impossible_metrics_even_if_readdressed() -> None:
    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="perfect"))
    measurement = next(
        item for item in report["measurements"] if item["arm"] == sealed.PRIMARY_ARM
    )
    row = measurement["per_case"][0]
    row["first_hit_coverage"] = 0.0
    _refresh_report_id(report)
    with pytest.raises(sealed.SealedEvaluationError, match="coverage"):
        sealed.validate_sealed_report(report)

    report = sealed.evaluate_sealed_rankings(*_campaign(outcome="perfect"))
    measurement = next(
        item for item in report["measurements"] if item["arm"] == sealed.PRIMARY_ARM
    )
    row = measurement["per_case"][0]
    row["recall_at_1"] = 1.0
    row["recall_at_5"] = 0.0
    _refresh_report_id(report)
    with pytest.raises(sealed.SealedEvaluationError, match="monotone"):
        sealed.validate_sealed_report(report)


def test_bundle_validation_recomputes_readdressed_recall_magnitudes() -> None:
    campaign = _campaign(outcome="perfect")
    report = sealed.evaluate_sealed_rankings(*campaign)
    measurement = next(
        item for item in report["measurements"] if item["arm"] == sealed.PRIMARY_ARM
    )
    row = measurement["per_case"][0]
    for metric in ("recall_at_1", "recall_at_5", "recall_at_10", "recall_at_20"):
        row[metric] = 0.5
    _refresh_report_id(report)

    # The row is structurally possible for a two-item gold set, so detached
    # validation intentionally cannot reject it.  Reopening the bound bundle
    # proves that the actual campaign had a different gold cardinality.
    sealed.validate_sealed_report(report)
    with pytest.raises(sealed.SealedEvaluationError, match="recomputation"):
        sealed.validate_sealed_report_bundle(report, *campaign)


def test_bundle_validation_accepts_exact_evaluator_output() -> None:
    campaign = _campaign(outcome="perfect")
    report = sealed.evaluate_sealed_rankings(*campaign)
    sealed.validate_sealed_report_bundle(report, *campaign)


@pytest.mark.parametrize("outcome", ["perfect", "tie"])
def test_one_case_can_never_issue_a_scientific_verdict(outcome: str) -> None:
    inputs = _input_manifest(case_count=1)
    rankings = _rankings_manifest(inputs, outcome=outcome)
    gold = _gold_manifest(inputs)
    isolation = _isolation_receipt(inputs, rankings)
    report = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    assert report["status"] == sealed.STRUCTURALLY_VALID_UNANCHORED
    assert report["eligibility"] == sealed.STRUCTURALLY_VALID_UNANCHORED
    assert report["conclusion"] == NO_SCIENTIFIC_VERDICT
    assert all(item["superiority_claim"] is False for item in report["comparisons"])


def test_alternative_self_sealed_gold_changes_diagnostics_but_never_verdict() -> None:
    inputs, rankings, gold, isolation = _campaign(outcome="perfect")
    original = sealed.evaluate_sealed_rankings(inputs, rankings, gold, isolation)
    alternative = copy.deepcopy(gold)
    for row in alternative["payload"]["cases"]:
        case = next(
            item
            for item in inputs["payload"]["cases"]
            if item["case_id"] == row["case_id"]
        )
        row["gold_candidate_ids"] = [case["candidates"][0]["candidate_id"]]
    alternative = _reseal(alternative)
    changed = sealed.evaluate_sealed_rankings(inputs, rankings, alternative, isolation)

    assert original["manifest_digests"]["input"] == changed["manifest_digests"]["input"]
    assert original["manifest_digests"]["rankings"] == changed["manifest_digests"]["rankings"]
    assert original["manifest_digests"]["isolation"] == changed["manifest_digests"]["isolation"]
    assert original["manifest_digests"]["gold"] != changed["manifest_digests"]["gold"]
    for report in (original, changed):
        assert report["status"] == sealed.STRUCTURALLY_VALID_UNANCHORED
        assert report["conclusion"] == NO_SCIENTIFIC_VERDICT
        assert all(item["superiority_claim"] is False for item in report["comparisons"])

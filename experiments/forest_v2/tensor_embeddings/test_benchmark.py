"""Evaluator isolation, budget equality and report tests."""
from __future__ import annotations

from dataclasses import replace

import pytest

from experiments.forest_v2.s09_eval.contract import Candidate, QueryView
from experiments.forest_v2.tensor_embeddings.benchmark import (
    BenchmarkCase,
    DEFAULT_RETRIEVERS,
    REQUIRED_ARM_NAMES,
    benchmark_case_key,
    corpus_digest,
    run_benchmark,
    synthetic_role_binding_construct,
)
from experiments.forest_v2.tensor_embeddings.retrievers import (
    CandidateTensorCache,
    FlatCosineRetriever,
    FlattenedBilinearRetriever,
    TensorContractionRetriever,
)
from experiments.forest_v2.tensor_embeddings.sealed_eval import (
    REQUIRED_ARMS as SEALED_REQUIRED_ARMS,
)
from experiments.forest_v2.tensor_embeddings.stats import validate_report


def _case(case_id: str, query: str, gold: str) -> BenchmarkCase:
    candidates = (
        Candidate(
            path="src/parser.py",
            blob="blob-parser",
            size=37,
            raw=b"def parse_record(value): return value",
            content_budget=37,
        ),
        Candidate(
            path="docs/storage.md",
            blob="blob-storage",
            size=33,
            raw=b"Storage migration and index guide",
            content_budget=33,
        ),
        Candidate(
            path="schemas/record.schema.json",
            blob="blob-schema",
            size=25,
            raw=b'{"title":"Record schema"}',
            content_budget=25,
        ),
    )
    return BenchmarkCase(
        query=QueryView(
            case_id=case_id,
            text=query,
            variant="scrubbed",
            revision="preimage-revision",
            repo="must-not-be-read",
        ),
        universe=candidates,
        gold=(gold,),
        recency_ranking=tuple(candidate.path for candidate in candidates),
    )


def test_benchmark_emits_complete_five_seed_validated_report() -> None:
    cases = (
        _case("c1", "parse record value", "src/parser.py"),
        _case("c2", "storage migration index", "docs/storage.md"),
    )
    report = run_benchmark(cases)
    validate_report(
        report,
        expected_corpus_digest=corpus_digest(cases),
        expected_case_ids=tuple(benchmark_case_key(case.query) for case in cases),
    )
    assert report["status"] == "VALID"
    assert report["conclusion"] == "INCONCLUSIVE"
    assert report["failures"] == []
    assert report["seeds"] == [11, 23, 47, 89, 131]
    assert tuple(report["required_arms"]) == REQUIRED_ARM_NAMES
    assert tuple(report["required_arms"]) == SEALED_REQUIRED_ARMS
    assert len(report["arms"]) == 13
    assert len(report["comparisons"]) == 15
    for arm_runs in report["arms"].values():
        assert set(arm_runs) == {"11", "23", "47", "89", "131"}
        assert all(
            set(run["per_case"])
            == {benchmark_case_key(case.query) for case in cases}
            for run in arm_runs.values()
        )


def test_corpus_digest_binds_query_candidates_budgets_and_gold() -> None:
    original = _case("c1", "parse record", "src/parser.py")
    relabeled = BenchmarkCase(original.query, original.universe, ("docs/storage.md",))
    assert corpus_digest((original,)) != corpus_digest((relabeled,))
    changed_query = BenchmarkCase(
        replace(original.query, text="different request"), original.universe, original.gold
    )
    assert corpus_digest((original,)) != corpus_digest((changed_query,))
    changed_recency = replace(
        original, recency_ranking=tuple(reversed(original.recency_ranking))
    )
    assert corpus_digest((original,)) != corpus_digest((changed_recency,))


def test_synthetic_construct_is_explicitly_non_empirical_and_separates_tie() -> None:
    result = synthetic_role_binding_construct()
    assert result["claim_scope"] == "construct-validity-only"
    assert result["automatic_promotions"] == 0
    assert result["cosine_tie"] is True
    assert result["structured_separates"] is True


def test_receipt_mismatch_invalidates_run_without_scientific_kill(monkeypatch) -> None:
    original = FlatCosineRetriever.score_receipt

    def mismatched(self, query):
        return replace(original(self, query), input_scalar_budget=513)

    monkeypatch.setattr(FlatCosineRetriever, "score_receipt", mismatched)
    report = run_benchmark((_case("c1", "parse record", "src/parser.py"),))
    assert report["status"] == "INVALID"
    assert report["conclusion"] == "NO_SCIENTIFIC_VERDICT"
    assert any(item["category"] == "budget_or_input_mismatch" for item in report["failures"])


@pytest.mark.parametrize(
    "malformed",
    (
        lambda _receipt: None,
        lambda receipt: replace(receipt, candidate_inputs=()),
    ),
)
def test_malformed_receipts_are_retained_per_cell_instead_of_crashing(
    monkeypatch, malformed
) -> None:
    original = FlatCosineRetriever.score_receipt

    def broken(self, query):
        return malformed(original(self, query))

    monkeypatch.setattr(FlatCosineRetriever, "score_receipt", broken)
    report = run_benchmark((_case("c1", "parse record", "src/parser.py"),))
    assert report["status"] == "INVALID"
    assert report["conclusion"] == "NO_SCIENTIFIC_VERDICT"
    failures = [
        item
        for item in report["failures"]
        if item["category"] == "input_receipt_validation_failure"
    ]
    assert len(failures) == 5
    assert all(item["arm"] == FlatCosineRetriever.name for item in failures)


def test_measured_ranking_must_be_derived_from_its_retained_scores(monkeypatch) -> None:
    original = FlatCosineRetriever.rank

    def reversed_output(self, query, universe):
        return list(reversed(original(self, query, universe)))

    monkeypatch.setattr(FlatCosineRetriever, "rank", reversed_output)
    report = run_benchmark((_case("c1", "parse record", "src/parser.py"),))
    assert report["status"] == "INVALID"
    assert report["conclusion"] == "NO_SCIENTIFIC_VERDICT"
    failures = [
        item
        for item in report["failures"]
        if item["category"] == "input_receipt_validation_failure"
    ]
    assert len(failures) == 5
    assert all("not bound to receipt score order" in item["message"] for item in failures)


def test_tensor_vector_bilinear_equivalence_is_a_hard_invariant(monkeypatch) -> None:
    monkeypatch.setattr(
        FlattenedBilinearRetriever,
        "_score",
        lambda _self, _query, _document: -0.987654321,
    )
    report = run_benchmark((_case("c1", "parse record", "src/parser.py"),))
    assert report["status"] == "INVALID"
    assert report["conclusion"] == "NO_SCIENTIFIC_VERDICT"
    assert any(
        item["category"] == "tensor_vector_bilinear_equivalence_failure"
        for item in report["failures"]
    )


def test_failed_cells_are_retained_and_validate_as_blocked(monkeypatch) -> None:
    def fail(self, query, universe):
        raise RuntimeError("retained failure fixture")

    monkeypatch.setattr(TensorContractionRetriever, "rank", fail)
    report = run_benchmark((_case("c1", "parse record", "src/parser.py"),))
    assert report["status"] == "BLOCKED"
    # Three kernel controls inherit the common tensor rank method as well;
    # every affected arm/seed cell must be retained, not collapsed.
    assert len(report["failures"]) == 20
    assert all("retained failure fixture" in item["message"] for item in report["failures"])


def test_benchmark_refuses_duplicate_cases_and_gold_outside_universe() -> None:
    case = _case("c1", "parse", "src/parser.py")
    with pytest.raises(ValueError, match="unique"):
        run_benchmark((case, case))
    with pytest.raises(ValueError, match="outside"):
        BenchmarkCase(case.query, case.universe, ("ghost.py",))


def test_benchmark_accepts_only_full_or_canonically_budget_clipped_blobs() -> None:
    query = QueryView(
        case_id="c1",
        text="visible prefix",
        variant="raw",
        revision="preimage-revision",
        repo="",
    )
    clipped = Candidate(
        path="large.txt",
        blob="blob-large",
        size=10,
        raw=b"12345",
        content_budget=5,
    )
    accepted = BenchmarkCase(query, (clipped,), ("large.txt",))
    assert accepted.universe[0].text() == "12345"

    arbitrary_partial = replace(clipped, raw=b"12345678")
    with pytest.raises(ValueError, match="complete blob or its exact budget-visible prefix"):
        BenchmarkCase(query, (arbitrary_partial,), ("large.txt",))


def test_raw_and_scrubbed_variants_of_one_case_have_distinct_report_keys() -> None:
    raw = _case("c1", "raw issue text", "src/parser.py")
    raw = BenchmarkCase(
        replace(raw.query, variant="raw"),
        raw.universe,
        raw.gold,
        raw.recency_ranking,
    )
    scrubbed = BenchmarkCase(
        replace(raw.query, variant="scrubbed", text="issue text"),
        raw.universe,
        raw.gold,
        raw.recency_ranking,
    )
    report = run_benchmark((raw, scrubbed))
    assert report["case_ids"] == [
        benchmark_case_key(raw.query),
        benchmark_case_key(scrubbed.query),
    ]


def test_query_variants_cannot_smuggle_query_dependent_recency_orders() -> None:
    raw = _case("c1", "raw issue text", "src/parser.py")
    raw = replace(raw, query=replace(raw.query, variant="raw"))
    scrubbed = replace(
        raw,
        query=replace(raw.query, variant="scrubbed", text="issue text"),
        recency_ranking=tuple(reversed(raw.recency_ranking)),
    )
    with pytest.raises(ValueError, match="same caller-asserted recency ranking"):
        run_benchmark((raw, scrubbed))


def test_diagnostic_harness_rejects_any_unreviewed_retriever_class() -> None:
    class ReflectiveRetriever(FlatCosineRetriever):
        name = "reflective_fixture"

    with pytest.raises(ValueError, match="exact audited"):
        run_benchmark(
            (_case("c1", "parse", "src/parser.py"),),
            retriever_types=(*DEFAULT_RETRIEVERS[:-1], ReflectiveRetriever),
        )


def test_benchmark_refuses_a_self_declared_subset_as_a_complete_campaign() -> None:
    with pytest.raises(ValueError, match="complete frozen arm census"):
        run_benchmark(
            (_case("c1", "parse", "src/parser.py"),),
            retriever_types=(FlatCosineRetriever, TensorContractionRetriever),
        )


def test_tensor_arms_share_one_candidate_cache_per_seed(monkeypatch) -> None:
    original = CandidateTensorCache.encode_candidate
    caches_by_seed: dict[int, list[CandidateTensorCache]] = {}

    def observed(self, encoder, candidate, text, revision):
        caches = caches_by_seed.setdefault(encoder.spec.seed, [])
        if all(self is not existing for existing in caches):
            caches.append(self)
        return original(self, encoder, candidate, text, revision)

    monkeypatch.setattr(CandidateTensorCache, "encode_candidate", observed)
    report = run_benchmark((_case("c1", "parse record", "src/parser.py"),))
    assert report["status"] == "VALID"
    assert set(caches_by_seed) == {11, 23, 47, 89, 131}
    assert all(len(caches) == 1 for caches in caches_by_seed.values())

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path

import pytest

from experiments.forest_v2.s09_eval.contract import (
    Candidate,
    ContractViolation,
    QueryView,
    Retriever,
    load_retriever,
)
from experiments.forest_v2.tensor_embeddings import algebra as algebra_module
from experiments.forest_v2.tensor_embeddings import retrievers as retriever_module
from experiments.forest_v2.tensor_embeddings.algebra import (
    fiber_maxsim,
    normalized_flattened_bilinear_score,
)
from experiments.forest_v2.tensor_embeddings.encoding import (
    HashingFillerBackend,
    PrecomputedFillerBackend,
    TensorProductEncoder,
    canonical_source_digest,
    default_spec,
)
from experiments.forest_v2.tensor_embeddings.retrievers import (
    CandidateTensorCache,
    DEFAULT_HASH_SEED,
    FROZEN_DENSE_SCALARS,
    FROZEN_HASH_SEEDS,
    PLANE_KERNEL,
    PLANE_PERMUTATION,
    ROLE_KERNEL,
    ROLE_PERMUTATION,
    FlatCosineRetriever,
    FlattenedBilinearRetriever,
    IdentityContractionRetriever,
    PlanePermutationControl,
    RolePermutationControl,
    TensorContractionRetriever,
    TensorLateInteractionRetriever,
    UniformKernelControl,
)


RETRIEVER_CLASSES = (
    FlatCosineRetriever,
    IdentityContractionRetriever,
    TensorContractionRetriever,
    FlattenedBilinearRetriever,
    TensorLateInteractionRetriever,
    PlanePermutationControl,
    RolePermutationControl,
    UniformKernelControl,
)


def _exact_determinant(matrix: tuple[tuple[float, ...], ...]) -> Fraction:
    """Small exact determinant for the frozen 4x4 decimal kernels."""

    rows = tuple(tuple(Fraction(str(value)) for value in row) for row in matrix)

    def determinant(values: tuple[tuple[Fraction, ...], ...]) -> Fraction:
        if len(values) == 1:
            return values[0][0]
        return sum(
            (
                (-1 if column % 2 else 1)
                * values[0][column]
                * determinant(
                    tuple(
                        tuple(value for index, value in enumerate(row) if index != column)
                        for row in values[1:]
                    )
                )
            )
            for column in range(len(values))
        )

    return determinant(rows)


def test_frozen_kernels_are_symmetric_positive_definite() -> None:
    """Protect the exact shared-transform interpretation in RESEARCH.md."""

    expected_minors = (
        (Fraction(1), Fraction(3, 4), Fraction(9, 16), Fraction(3, 8)),
        (Fraction(1), Fraction(7, 16), Fraction(5, 16), Fraction(453, 1600)),
    )
    for matrix, expected in zip((PLANE_KERNEL, ROLE_KERNEL), expected_minors):
        assert matrix == tuple(zip(*matrix))
        leading_minors = tuple(
            _exact_determinant(tuple(row[:size] for row in matrix[:size]))
            for size in range(1, len(matrix) + 1)
        )
        assert leading_minors == expected
        assert all(value > 0 for value in leading_minors)


def _query(text: str = "find parser schema configuration") -> QueryView:
    return QueryView(
        case_id="case-001",
        text=text,
        variant="raw",
        revision="parent-revision",
        repo="must-not-be-read",
    )


def _universe() -> tuple[Candidate, ...]:
    rows = (
        ("src/parser.py", b"class Parser:\n    def parse_schema(self): pass\n"),
        ("schema/types.json", b'{"parser": "configuration schema"}\n'),
        ("docs/parser.md", b"Parser configuration and schema guide.\n"),
        ("config/runtime.yaml", b"parser: strict\nmode: configured\n"),
    )
    return tuple(
        Candidate(
            path=path,
            blob=f"blob-{index}",
            size=len(raw),
            raw=raw,
            content_budget=len(raw),
        )
        for index, (path, raw) in enumerate(rows)
    )


def _permuted_columns(matrix, permutation):
    return tuple(tuple(row[column] for column in permutation) for row in matrix)


def test_frozen_kernel_constants_are_literal_experiment_spec_values():
    spec_path = Path(__file__).with_name("EXPERIMENT_SPEC.json")
    frozen = json.loads(spec_path.read_text(encoding="utf-8"))

    assert [list(row) for row in PLANE_KERNEL] == frozen["plane_kernel"]
    assert [list(row) for row in ROLE_KERNEL] == frozen["role_kernel"]
    assert list(FROZEN_HASH_SEEDS) == frozen["hash_seeds"]
    assert FROZEN_DENSE_SCALARS == frozen["dense_scalar_budget"]
    assert (
        len(frozen["planes"])
        * len(frozen["roles"])
        * frozen["feature_dimension"]
        == FROZEN_DENSE_SCALARS
    )


def test_all_retrievers_are_zero_arg_s09_retrievers_with_unique_names():
    instances = [retriever_class() for retriever_class in RETRIEVER_CLASSES]
    assert all(isinstance(instance, Retriever) for instance in instances)
    assert len({instance.name for instance in instances}) == len(instances)
    assert len({id(instance.candidate_cache) for instance in instances}) == len(instances)

    loaded = load_retriever(
        "experiments.forest_v2.tensor_embeddings.retrievers:FlatCosineRetriever"
    )
    assert isinstance(loaded, FlatCosineRetriever)
    assert loaded.encoder.spec.seed == DEFAULT_HASH_SEED


def test_identity_contraction_ranking_and_scores_equal_flattened_cosine():
    query = _query()
    universe = _universe()
    flat = FlatCosineRetriever()
    identity = IdentityContractionRetriever()

    assert flat.rank(query, universe) == identity.rank(query, universe)
    flat_receipt = flat.score_receipt(query)
    identity_receipt = identity.score_receipt(query)
    assert flat_receipt.kernel_id == identity_receipt.kernel_id
    assert [path for path, _score in flat_receipt.scores] == [
        path for path, _score in identity_receipt.scores
    ]
    assert [score for _path, score in flat_receipt.scores] == pytest.approx(
        [score for _path, score in identity_receipt.scores], abs=1e-12, rel=1e-12
    )


def test_structured_tensor_scores_equal_flattened_bilinear_vector_control():
    query = _query()
    universe = _universe()
    tensor = TensorContractionRetriever()
    vector = FlattenedBilinearRetriever()

    assert tensor.rank(query, universe) == vector.rank(query, universe)
    tensor_scores = tensor.score_receipt(query).scores
    vector_scores = vector.score_receipt(query).scores
    assert [path for path, _score in tensor_scores] == [
        path for path, _score in vector_scores
    ]
    assert [score for _path, score in tensor_scores] == pytest.approx(
        [score for _path, score in vector_scores], abs=1e-10, rel=1e-10
    )


def test_flattened_bilinear_prepares_once_per_query_seed_and_kernel(monkeypatch):
    calls = 0
    original = retriever_module.prepare_flattened_bilinear_query

    def observed(query, kernel):
        nonlocal calls
        calls += 1
        return original(query, kernel)

    monkeypatch.setattr(
        retriever_module, "prepare_flattened_bilinear_query", observed
    )
    retriever = FlattenedBilinearRetriever(seed=11)
    query = _query()
    universe = _universe()

    retriever.rank(query, universe)
    assert calls == 1
    assert len(universe) > 1
    # Replaying the same exact query/seed/kernel is warm as well.
    retriever.rank(query, tuple(reversed(universe)))
    assert calls == 1

    retriever.rank(_query("different visible query"), universe)
    assert calls == 2
    assert all(
        key[1:] == (retriever.encoder.spec.spec_id, retriever.kernel.kernel_id)
        for key in retriever._prepared_query_cache
    )


def test_flattened_bilinear_preparation_preserves_exact_receipt_scores():
    query = _query()
    universe = _universe()
    retriever = FlattenedBilinearRetriever()

    ranking = retriever.rank(query, universe)
    receipt = retriever.score_receipt(query)
    encoded_query = retriever.encoder.encode_query(
        query.text,
        query_id=f"{query.case_id}:{query.variant}",
        revision=query.revision,
    )
    expected_scores = []
    for candidate in universe:
        encoded_document = retriever.encoder.encode_candidate(
            candidate.path,
            candidate.text(),
            blob=candidate.blob,
            revision=query.revision,
        )
        expected_scores.append(
            (
                candidate.path,
                normalized_flattened_bilinear_score(
                    encoded_query.tensor, encoded_document.tensor, retriever.kernel
                ),
            )
        )
    expected_scores.sort(key=lambda item: (-item[1], item[0]))

    assert receipt.scores == tuple(expected_scores)
    assert ranking == [path for path, _score in expected_scores]


def test_late_interaction_prepares_once_per_query_seed_and_kernel(monkeypatch):
    calls = 0
    original = retriever_module.prepare_fiber_maxsim_query

    def observed(query, kernel):
        nonlocal calls
        calls += 1
        return original(query, kernel)

    monkeypatch.setattr(retriever_module, "prepare_fiber_maxsim_query", observed)
    monkeypatch.setattr(retriever_module, "DEFAULT_PREPARED_QUERY_CACHE_ENTRIES", 1)
    retriever = TensorLateInteractionRetriever(seed=23)
    query = _query()
    universe = _universe()

    retriever.rank(query, universe)
    assert calls == 1
    retriever.rank(query, tuple(reversed(universe)))
    assert calls == 1

    retriever.rank(_query("different visible query"), universe)
    assert calls == 2
    assert len(retriever._prepared_query_cache) == 1
    assert all(
        key[1:] == (retriever.encoder.spec.spec_id, retriever.kernel.kernel_id)
        for key in retriever._prepared_query_cache
    )
    retriever.rank(query, universe)
    assert calls == 3


def test_late_interaction_materializes_query_once_and_each_document_once(
    monkeypatch,
):
    retriever = TensorLateInteractionRetriever()
    query = _query()
    universe = _universe()
    encoded_query = retriever.encoder.encode_query(
        query.text,
        query_id=f"{query.case_id}:{query.variant}",
        revision=query.revision,
    )
    expected_document_ids = {
        retriever.encoder.encode_candidate(
            candidate.path,
            candidate.text(),
            blob=candidate.blob,
            revision=query.revision,
        ).tensor.tensor_id
        for candidate in universe
    }
    counts: dict[str, int] = {}
    original = algebra_module.to_dense

    def observed(tensor):
        counts[tensor.tensor_id] = counts.get(tensor.tensor_id, 0) + 1
        return original(tensor)

    monkeypatch.setattr(algebra_module, "to_dense", observed)
    retriever.rank(query, universe)

    assert counts[encoded_query.tensor.tensor_id] == 1
    assert expected_document_ids
    assert all(counts[tensor_id] == 1 for tensor_id in expected_document_ids)


def test_late_interaction_preparation_preserves_exact_receipt_scores():
    query = _query()
    universe = _universe()
    retriever = TensorLateInteractionRetriever()

    ranking = retriever.rank(query, universe)
    receipt = retriever.score_receipt(query)
    encoded_query = retriever.encoder.encode_query(
        query.text,
        query_id=f"{query.case_id}:{query.variant}",
        revision=query.revision,
    )
    expected_scores = []
    for candidate in universe:
        encoded_document = retriever.encoder.encode_candidate(
            candidate.path,
            candidate.text(),
            blob=candidate.blob,
            revision=query.revision,
        )
        expected_scores.append(
            (
                candidate.path,
                fiber_maxsim(
                    encoded_query.tensor, encoded_document.tensor, retriever.kernel
                ),
            )
        )
    expected_scores.sort(key=lambda item: (-item[1], item[0]))

    assert receipt.scores == tuple(expected_scores)
    assert ranking == [path for path, _score in expected_scores]


def test_late_interaction_preparation_keeps_score_as_fault_injection_seam(
    monkeypatch,
):
    def injected(_self, _query, _document):
        raise RuntimeError("late-interaction score fault reached")

    monkeypatch.setattr(TensorLateInteractionRetriever, "_score", injected)
    with pytest.raises(RuntimeError, match="score fault reached"):
        TensorLateInteractionRetriever().rank(_query(), _universe())


def test_ranking_and_receipt_are_deterministic_across_calls_and_instances():
    query = _query()
    universe = tuple(reversed(_universe()))
    first = TensorContractionRetriever()

    first_ranking = first.rank(query, universe)
    first_receipt = first.score_receipt(query)
    assert first.rank(query, universe) == first_ranking
    assert first.score_receipt(query) == first_receipt

    second = TensorContractionRetriever()
    assert second.rank(query, universe) == first_ranking
    assert second.score_receipt(query) == first_receipt


def test_explicit_cache_has_measured_cold_warm_clear_and_eviction_semantics():
    cache = CandidateTensorCache(max_entries=1)
    encoder = TensorProductEncoder(default_spec(seed=11))
    first, second = _universe()[:2]

    cold = cache.encode_candidate(encoder, first, first.text(), "revision-a")
    assert cache.info().cold_misses == 1
    assert cache.info().warm_hits == 0
    assert cache.encode_candidate(encoder, first, first.text(), "revision-a") is cold
    assert cache.info().warm_hits == 1

    cache.encode_candidate(encoder, second, second.text(), "revision-a")
    assert cache.info().cold_misses == 2
    assert cache.info().evictions == 1
    assert cache.info().current_size == 1

    cache.clear()
    assert cache.info().cold_misses == 0
    assert cache.info().warm_hits == 0
    assert cache.info().evictions == 0
    assert cache.info().current_size == 0


def test_shared_cache_never_launders_precomputed_tensor_as_hashing_backend():
    spec = default_spec(seed=11)
    candidate = Candidate(
        path="src/a.py",
        blob="blob-a",
        size=5,
        raw=b"alpha",
        content_budget=5,
    )
    basis = (1.0,) + (0.0,) * (spec.feature_dimension - 1)
    precomputed = PrecomputedFillerBackend(
        {
            PrecomputedFillerBackend.key(candidate.path, "path"): basis,
            PrecomputedFillerBackend.key(candidate.text(), "content"): basis,
        }
    )
    precomputed_encoder = TensorProductEncoder(spec, precomputed)
    hashing_encoder = TensorProductEncoder(spec, HashingFillerBackend(spec.seed))
    cache = CandidateTensorCache()

    semantic = cache.encode_candidate(
        precomputed_encoder, candidate, candidate.text(), "revision-a"
    )
    hashed = cache.encode_candidate(
        hashing_encoder, candidate, candidate.text(), "revision-a"
    )
    direct_hash = hashing_encoder.encode_candidate(
        candidate.path,
        candidate.text(),
        blob=candidate.blob,
        revision="revision-a",
    )

    assert semantic.backend_id == precomputed.backend_id
    assert hashed.backend_id == hashing_encoder.backend.backend_id
    assert hashed == direct_hash
    assert hashed.tensor.tensor_id != semantic.tensor.tensor_id
    assert cache.info().cold_misses == 2
    assert cache.info().warm_hits == 0


def test_custom_backend_state_with_same_class_and_id_always_bypasses_cache():
    class StatefulBackend:
        backend_id = "custom-same-id"

        def __init__(self, coordinate: int) -> None:
            self.coordinate = coordinate

        def embed(self, text, *, role, spec):
            vector = [0.0] * spec.feature_dimension
            vector[self.coordinate] = 1.0
            return tuple(vector)

    spec = default_spec(seed=11)
    candidate = _universe()[0]
    cache = CandidateTensorCache()
    first_encoder = TensorProductEncoder(spec, StatefulBackend(0))
    second_encoder = TensorProductEncoder(spec, StatefulBackend(1))

    first = cache.encode_candidate(
        first_encoder, candidate, candidate.text(), "revision-a"
    )
    second = cache.encode_candidate(
        second_encoder, candidate, candidate.text(), "revision-a"
    )
    direct_second = second_encoder.encode_candidate(
        candidate.path,
        candidate.text(),
        blob=candidate.blob,
        revision="revision-a",
    )
    first_again = cache.encode_candidate(
        first_encoder, candidate, candidate.text(), "revision-a"
    )

    assert first.backend_id == second.backend_id == "custom-same-id"
    assert second == direct_second
    assert second.tensor.tensor_id != first.tensor.tensor_id
    assert first_again == first
    assert first_again is not first
    assert cache.info().cold_misses == 3
    assert cache.info().warm_hits == 0
    assert cache.info().current_size == 0


def test_cache_key_binds_encoder_spec_revision_and_visible_content():
    class AlternateTensorProductEncoder(TensorProductEncoder):
        pass

    candidate = Candidate(
        path="src/a.py",
        blob="blob-a",
        size=5,
        raw=b"alpha",
        content_budget=5,
    )
    cache = CandidateTensorCache()
    first_encoder = TensorProductEncoder(default_spec(seed=11))
    alternate_encoder = AlternateTensorProductEncoder(default_spec(seed=11))
    other_spec_encoder = TensorProductEncoder(default_spec(seed=23))

    first = cache.encode_candidate(
        first_encoder, candidate, "alpha", "revision-a"
    )
    assert cache.encode_candidate(
        first_encoder, candidate, "alpha", "revision-a"
    ) is first
    alternate = cache.encode_candidate(
        alternate_encoder, candidate, "alpha", "revision-a"
    )
    other_spec = cache.encode_candidate(
        other_spec_encoder, candidate, "alpha", "revision-a"
    )
    other_revision = cache.encode_candidate(
        first_encoder, candidate, "alpha", "revision-b"
    )
    other_content = cache.encode_candidate(
        first_encoder, candidate, "omega", "revision-a"
    )

    assert alternate == first
    assert other_spec.tensor.spec.spec_id != first.tensor.spec.spec_id
    assert other_revision.revision == "revision-b"
    assert other_revision.tensor.tensor_id == first.tensor.tensor_id
    assert other_content.source_digest != first.source_digest
    assert other_content.tensor.tensor_id != first.tensor.tensor_id
    assert cache.info().cold_misses == 5
    assert cache.info().warm_hits == 1


def test_retrievers_can_share_one_explicit_run_cache_without_global_state():
    cache = CandidateTensorCache()
    query = _query()
    universe = _universe()
    flat = FlatCosineRetriever(candidate_cache=cache)
    structured = TensorContractionRetriever(candidate_cache=cache)

    flat.rank(query, universe)
    after_cold_arm = cache.info()
    structured.rank(query, universe)
    after_warm_arm = cache.info()

    assert after_cold_arm.cold_misses == len(universe)
    assert after_cold_arm.warm_hits == 0
    assert after_warm_arm.cold_misses == len(universe)
    assert after_warm_arm.warm_hits == len(universe)


def test_every_arm_receipts_the_same_inputs_spec_seed_and_512_scalar_budget():
    query = _query()
    universe = _universe()
    receipts = []
    for retriever_class in RETRIEVER_CLASSES:
        retriever = retriever_class()
        retriever.rank(query, universe)
        receipts.append(retriever.score_receipt(query))

    first = receipts[0]
    assert all(receipt.input_ids == first.input_ids for receipt in receipts)
    assert all(receipt.query_input_id == first.query_input_id for receipt in receipts)
    assert all(receipt.query_tensor_id == first.query_tensor_id for receipt in receipts)
    assert all(
        tuple(item.tensor_id for item in receipt.candidate_inputs)
        == tuple(item.tensor_id for item in first.candidate_inputs)
        for receipt in receipts
    )
    assert all(receipt.spec_id == first.spec_id for receipt in receipts)
    assert all(receipt.seed == DEFAULT_HASH_SEED for receipt in receipts)
    assert all(receipt.dense_scalars_per_tensor == 512 for receipt in receipts)
    assert all(receipt.input_scalar_budget == 512 for receipt in receipts)
    assert all(receipt.authority == "unverified-retrieval-proposal" for receipt in receipts)
    assert all(receipt.proposal_only is True for receipt in receipts)

    # Flat cosine and identity share the explicit identity-kernel ID; primary
    # contraction and its secondary MaxSim comparator share the frozen kernel.
    assert receipts[0].kernel_id == receipts[1].kernel_id
    assert receipts[2].kernel_id == receipts[3].kernel_id

    payload = first.to_dict()
    assert payload["input_scalar_budget"] == 512
    assert payload["authority"] == "unverified-retrieval-proposal"
    serialized = json.dumps(payload, sort_keys=True)
    assert '"gold"' not in serialized
    assert '"repo"' not in serialized


class _BudgetBoundaryCandidate:
    path = "src/bounded.py"
    blob = "bounded-blob"

    def __init__(self) -> None:
        self.calls = 0
        self.visible = "ordinary visible content"

    @property
    def raw(self):  # pragma: no cover - accessed only by a broken retriever
        raise AssertionError("retriever crossed Candidate.text() boundary")

    def text(self) -> str:
        self.calls += 1
        return self.visible


def test_candidate_text_is_the_only_content_boundary_and_is_called_once():
    candidate = _BudgetBoundaryCandidate()
    query = _query("hidden answer beyond the candidate budget")
    retriever = TensorContractionRetriever()

    assert retriever.rank(query, [candidate]) == [candidate.path]  # type: ignore[list-item]
    receipt = retriever.score_receipt(query)
    assert candidate.calls == 1
    assert receipt.candidate_inputs[0].text_digest == canonical_source_digest(
        candidate.visible
    )
    assert receipt.candidate_inputs[0].text_characters == len(candidate.visible)


def test_actual_candidate_budget_hides_raw_suffix_from_consumed_input_id():
    visible = b"ordinary visible content"
    hidden = b" ultrasecretgoldtoken"
    candidate = Candidate(
        path="src/bounded.py",
        blob="bounded-blob",
        size=len(visible) + len(hidden),
        raw=visible + hidden,
        content_budget=len(visible),
    )
    query = _query("ultrasecretgoldtoken")
    retriever = FlatCosineRetriever()
    retriever.rank(query, [candidate])
    item = retriever.score_receipt(query).candidate_inputs[0]

    assert candidate.text() == visible.decode("utf-8")
    assert item.text_digest == canonical_source_digest(visible)
    assert item.text_digest != canonical_source_digest(visible + hidden)


class _GoldAndRepoTrapQuery:
    case_id = "trap-case"
    text = "parser configuration"
    variant = "scrubbed"
    revision = "parent-revision"

    @property
    def gold(self):  # pragma: no cover - accessed only by a broken retriever
        raise AssertionError("retriever accessed gold")

    @property
    def repo(self):  # pragma: no cover - accessed only by a broken retriever
        raise AssertionError("retriever accessed repo")


def test_query_api_is_gold_free_and_does_not_read_repo():
    query = _GoldAndRepoTrapQuery()
    retriever = TensorContractionRetriever()
    ranking = retriever.rank(query, _universe())  # type: ignore[arg-type]
    assert set(ranking) == {candidate.path for candidate in _universe()}
    receipt = retriever.score_receipt(query)  # type: ignore[arg-type]
    assert receipt.query_case_id == query.case_id
    assert receipt.query_variant == query.variant


def test_empty_query_revision_is_rejected_without_a_synthetic_sentinel():
    query = QueryView(
        case_id="case-without-revision",
        text="parser configuration",
        variant="raw",
        revision="",
        repo="must-not-be-read",
    )
    retriever = TensorContractionRetriever()

    with pytest.raises(ContractViolation, match="revision must be a non-empty string"):
        retriever.rank(query, _universe())
    with pytest.raises(ContractViolation, match="revision must be a non-empty string"):
        retriever.score_receipt(query)


def test_permutation_controls_change_one_document_axis_only():
    primary = TensorContractionRetriever()
    plane = PlanePermutationControl()
    role = RolePermutationControl()
    uniform = UniformKernelControl()

    assert plane.kernel.plane_matrix == _permuted_columns(
        PLANE_KERNEL, PLANE_PERMUTATION
    )
    assert plane.kernel.role_matrix == ROLE_KERNEL
    assert role.kernel.plane_matrix == PLANE_KERNEL
    assert role.kernel.role_matrix == _permuted_columns(
        ROLE_KERNEL, ROLE_PERMUTATION
    )
    assert all(value == 1.0 for row in uniform.kernel.plane_matrix for value in row)
    assert all(value == 1.0 for row in uniform.kernel.role_matrix for value in row)
    assert len(
        {
            primary.kernel.kernel_id,
            plane.kernel.kernel_id,
            role.kernel.kernel_id,
            uniform.kernel.kernel_id,
        }
    ) == 4

    query = _query()
    universe = _universe()
    controls = (primary, plane, role, uniform)
    for retriever in controls:
        retriever.rank(query, universe)
    receipts = [retriever.score_receipt(query) for retriever in controls]
    assert all(receipt.input_ids == receipts[0].input_ids for receipt in receipts)
    assert all(receipt.spec_id == receipts[0].spec_id for receipt in receipts)


def test_ties_are_broken_by_path_independent_of_universe_order():
    raw = b"same visible implementation words"
    a = Candidate("a.py", "blob-a", len(raw), raw, len(raw))
    b = Candidate("b.py", "blob-b", len(raw), raw, len(raw))
    query = _query("implementation words")
    retriever = FlatCosineRetriever()

    assert retriever.rank(query, [b, a]) == ["a.py", "b.py"]
    scores = dict(retriever.score_receipt(query).scores)
    assert math.isclose(scores["a.py"], scores["b.py"], abs_tol=1e-15)


@pytest.mark.parametrize("retriever_class", RETRIEVER_CLASSES)
def test_rankings_contain_every_known_path_once_and_no_unknown_path(retriever_class):
    universe = _universe()
    ranking = retriever_class().rank(_query(), universe)
    assert len(ranking) == len(set(ranking)) == len(universe)
    assert set(ranking) == {candidate.path for candidate in universe}


def test_duplicate_candidate_paths_refuse_instead_of_emitting_duplicates():
    first = _universe()[0]
    duplicate = Candidate(
        path=first.path,
        blob="different-blob",
        size=8,
        raw=b"different",
        content_budget=8,
    )
    with pytest.raises(ContractViolation, match="duplicate path"):
        TensorContractionRetriever().rank(_query(), [first, duplicate])


def test_receipt_lookup_refuses_a_query_that_has_not_been_ranked():
    with pytest.raises(KeyError, match="has not been ranked"):
        TensorContractionRetriever().score_receipt(_query())


def test_only_frozen_hash_seeds_are_accepted():
    for seed in FROZEN_HASH_SEEDS:
        assert TensorContractionRetriever(seed=seed).encoder.spec.seed == seed
    with pytest.raises(ValueError, match="frozen seeds"):
        TensorContractionRetriever(seed=12)

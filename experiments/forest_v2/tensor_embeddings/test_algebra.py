"""Algebraic and adversarial tests for the frozen tensor experiment contracts."""
from __future__ import annotations

import copy
import json
import math
import random
from dataclasses import FrozenInstanceError
from fractions import Fraction

import pytest

from experiments.forest_v2.tensor_embeddings import algebra
from experiments.forest_v2.tensor_embeddings.algebra import (
    AlgebraError,
    contraction_contributions,
    cp_separable_contraction,
    dense_separable_contraction,
    explain_contraction,
    fiber_maxsim,
    flattened_cosine,
    frobenius_norm,
    identity_contraction,
    identity_contraction_equivalent,
    normalized_flattened_bilinear_score,
    normalized_structured_score,
    prepare_fiber_maxsim_query,
    prepared_fiber_maxsim,
    separable_contraction,
    tt_separable_contraction,
)
from experiments.forest_v2.tensor_embeddings.contracts import (
    PLANES,
    ROLES,
    CPTensor,
    CPTerm,
    ContractError,
    DenseTensor,
    SeparableKernel,
    TensorSpec,
    TensorTrain,
    canonical_digest,
    canonical_json_bytes,
)


def _spec(seed: int = 11, feature_dimension: int = 5) -> TensorSpec:
    return TensorSpec.frozen(seed=seed, feature_dimension=feature_dimension)


def _random_vector(rng: random.Random, size: int) -> tuple[float, ...]:
    return tuple(rng.uniform(-1.0, 1.0) for _ in range(size))


def _random_cp(rng: random.Random, spec: TensorSpec, rank: int) -> CPTensor:
    return CPTensor(
        spec=spec,
        terms=tuple(
            CPTerm(
                weight=rng.uniform(-1.0, 1.0),
                plane=_random_vector(rng, len(spec.planes)),
                role=_random_vector(rng, len(spec.roles)),
                feature=_random_vector(rng, spec.feature_dimension),
            )
            for _ in range(rank)
        ),
    )


def _random_kernel(rng: random.Random, spec: TensorSpec) -> SeparableKernel:
    return SeparableKernel(
        spec=spec,
        plane_matrix=tuple(
            _random_vector(rng, len(spec.planes)) for _ in spec.planes
        ),
        role_matrix=tuple(_random_vector(rng, len(spec.roles)) for _ in spec.roles),
    )


def _assert_values_close(left: DenseTensor, right: DenseTensor) -> None:
    assert left.spec == right.spec
    assert len(left.flat_values) == len(right.flat_values)
    for actual, expected in zip(left.flat_values, right.flat_values):
        assert actual == pytest.approx(expected, rel=1e-10, abs=1e-10)


def test_one_hundred_seeded_cp_dense_tt_and_contraction_equivalence() -> None:
    """Acceptance A3/A4: exact representations agree on 100 frozen cases."""

    rng = random.Random(20260824)
    for case in range(100):
        spec = _spec(seed=case, feature_dimension=rng.randint(1, 8))
        query = _random_cp(rng, spec, rank=rng.randint(1, 5))
        document = _random_cp(rng, spec, rank=rng.randint(1, 5))
        query_dense = query.to_dense()
        document_dense = document.to_dense()
        query_tt = query.to_tensor_train()
        document_tt = document.to_tensor_train()
        _assert_values_close(query_dense, query_tt.to_dense())
        _assert_values_close(document_dense, document_tt.to_dense())

        kernel = _random_kernel(rng, spec)
        dense_value = dense_separable_contraction(query_dense, document_dense, kernel)
        cp_value = cp_separable_contraction(query, document, kernel)
        tt_value = tt_separable_contraction(query_tt, document_tt, kernel)
        generic_value = separable_contraction(query, document_tt, kernel)
        assert cp_value == pytest.approx(dense_value, rel=1e-10, abs=1e-10)
        assert tt_value == pytest.approx(dense_value, rel=1e-10, abs=1e-10)
        assert generic_value == pytest.approx(dense_value, rel=1e-10, abs=1e-10)

        cosine = flattened_cosine(query, document)
        assert identity_contraction(query, document) == pytest.approx(
            cosine, rel=1e-10, abs=1e-10
        )
        assert identity_contraction_equivalent(query_tt, document_dense)
        score = normalized_structured_score(query, document_tt, kernel)
        assert math.isfinite(score)
        assert -1.0 <= score <= 1.0
        vector_score = normalized_flattened_bilinear_score(
            query_dense, document, kernel
        )
        assert vector_score == pytest.approx(score, rel=1e-10, abs=1e-10)


def test_zero_cp_has_exact_zero_dense_and_tt_values() -> None:
    spec = _spec(feature_dimension=3)
    cp = CPTensor(spec=spec, terms=())
    dense = cp.to_dense()
    tt = cp.to_tensor_train()
    assert dense.flat_values == (0.0,) * spec.dense_scalar_count
    assert tt.to_dense().flat_values == dense.flat_values
    assert flattened_cosine(cp, tt) == 0.0
    assert identity_contraction(cp, tt) == 0.0


def test_identity_contraction_is_flattened_cosine_on_simple_fixture() -> None:
    spec = _spec(feature_dimension=3)
    left = DenseTensor.from_flat(spec, tuple(float(index - 8) for index in range(48)))
    right = DenseTensor.from_flat(spec, tuple(float(12 - index) for index in range(48)))
    assert identity_contraction(left, right) == pytest.approx(
        flattened_cosine(left, right), rel=1e-12, abs=1e-12
    )


def test_identity_contraction_does_not_delegate_to_flattened_cosine(monkeypatch) -> None:
    spec = _spec(feature_dimension=3)
    left = DenseTensor.from_flat(spec, tuple(float(index - 8) for index in range(48)))
    right = DenseTensor.from_flat(spec, tuple(float(12 - index) for index in range(48)))
    expected = flattened_cosine(left, right)

    def forbidden_cosine(*_args, **_kwargs):
        raise AssertionError("identity contraction delegated to flattened cosine")

    monkeypatch.setattr(algebra, "flattened_cosine", forbidden_cosine)
    assert identity_contraction(left, right) == pytest.approx(
        expected, rel=1e-12, abs=1e-12
    )


def test_role_and_plane_structure_separates_flat_cosine_ties() -> None:
    """A frozen construct check, not evidence of a retrieval effect."""

    spec = _spec(feature_dimension=2)
    basis = (1.0, 0.0)

    def one_term(plane: str, role: str) -> CPTensor:
        plane_factor = tuple(1.0 if label == plane else 0.0 for label in PLANES)
        role_factor = tuple(1.0 if label == role else 0.0 for label in ROLES)
        return CPTensor(spec, (CPTerm(1.0, plane_factor, role_factor, basis),))

    query = one_term("code", "path")
    structured_match = one_term("code", "symbol")
    bag_equivalent_decoy = one_term("type", "neighbor")
    kernel = SeparableKernel(
        spec=spec,
        plane_matrix=(
            (1.0, 0.5, 0.5, 0.5),
            (0.5, 1.0, 0.25, 0.25),
            (0.5, 0.25, 1.0, 0.5),
            (0.5, 0.25, 0.5, 1.0),
        ),
        role_matrix=(
            (1.0, 0.75, 0.25, 0.1),
            (0.75, 1.0, 0.5, 0.25),
            (0.25, 0.5, 1.0, 0.25),
            (0.1, 0.25, 0.25, 1.0),
        ),
    )

    assert flattened_cosine(query, structured_match) == 0.0
    assert flattened_cosine(query, bag_equivalent_decoy) == 0.0
    assert normalized_structured_score(query, structured_match, kernel) > (
        normalized_structured_score(query, bag_equivalent_decoy, kernel)
    )
    assert fiber_maxsim(query, structured_match, kernel) > fiber_maxsim(
        query, bag_equivalent_decoy, kernel
    )


def test_prepared_fiber_maxsim_is_bit_identical_to_public_reference() -> None:
    rng = random.Random(20260824)
    for case in range(40):
        spec = _spec(seed=case, feature_dimension=rng.randint(1, 8))
        query = _random_cp(rng, spec, rank=rng.randint(0, 4))
        document = _random_cp(rng, spec, rank=rng.randint(0, 4))
        for kernel in (None, _random_kernel(rng, spec)):
            prepared = prepare_fiber_maxsim_query(query, kernel)
            assert prepared_fiber_maxsim(prepared, document) == fiber_maxsim(
                query, document, kernel
            )


def test_prepared_fiber_maxsim_query_is_deeply_immutable() -> None:
    spec = _spec(feature_dimension=3)
    query = DenseTensor.from_flat(
        spec,
        tuple(float((index % 7) - 3) for index in range(spec.dense_scalar_count)),
    )
    prepared = prepare_fiber_maxsim_query(query, SeparableKernel.identity(spec))

    assert prepared.fibers
    assert isinstance(prepared.fibers, tuple)
    assert isinstance(prepared.fibers[0].scaled_values, tuple)
    with pytest.raises(FrozenInstanceError):
        prepared.fibers[0].norm = 0.0  # type: ignore[misc]


def test_prepared_fiber_maxsim_preserves_zero_kernel_and_zero_tensor_cases() -> None:
    spec = _spec(feature_dimension=2)
    zero = DenseTensor.from_flat(spec, (0.0,) * spec.dense_scalar_count)
    nonzero = DenseTensor.from_flat(
        spec,
        tuple(float((index % 5) - 2) for index in range(spec.dense_scalar_count)),
    )
    zero_kernel = SeparableKernel(
        spec=spec,
        plane_matrix=tuple((0.0,) * len(spec.planes) for _ in spec.planes),
        role_matrix=tuple((0.0,) * len(spec.roles) for _ in spec.roles),
    )

    for query, document, kernel in (
        (zero, nonzero, None),
        (nonzero, zero, None),
        (nonzero, nonzero, zero_kernel),
    ):
        assert prepared_fiber_maxsim(
            prepare_fiber_maxsim_query(query, kernel), document
        ) == fiber_maxsim(query, document, kernel)


def test_explanation_terms_sum_exactly_to_the_numerator() -> None:
    rng = random.Random(47)
    spec = _spec(feature_dimension=4)
    query = _random_cp(rng, spec, 3)
    document = _random_cp(rng, spec, 2)
    kernel = _random_kernel(rng, spec)
    explanation = explain_contraction(query, document, kernel)
    assert explanation.numerator == sum(term.value for term in explanation.terms)
    assert explanation.numerator == pytest.approx(
        separable_contraction(query.to_dense(), document.to_dense(), kernel),
        rel=1e-12,
        abs=1e-12,
    )
    assert explanation.terms == contraction_contributions(query, document, kernel)
    assert explanation.score == normalized_structured_score(query, document, kernel)
    assert explanation.spec_id == spec.spec_id
    assert explanation.kernel_id == kernel.kernel_id


def test_contract_roundtrips_are_byte_deterministic() -> None:
    rng = random.Random(89)
    spec = _spec(seed=89, feature_dimension=4)
    kernel = _random_kernel(rng, spec)
    cp = _random_cp(rng, spec, rank=3)
    dense = cp.to_dense()
    tt = cp.to_tensor_train()

    spec_again = TensorSpec.from_bytes(spec.canonical_bytes())
    kernel_again = SeparableKernel.from_bytes(kernel.canonical_bytes(), spec_again)
    cp_again = CPTensor.from_bytes(cp.canonical_bytes(), spec_again)
    dense_again = DenseTensor.from_bytes(dense.canonical_bytes(), spec_again)
    tt_again = TensorTrain.from_bytes(tt.canonical_bytes(), spec_again)

    for original, restored in (
        (spec, spec_again),
        (kernel, kernel_again),
        (cp, cp_again),
        (dense, dense_again),
        (tt, tt_again),
    ):
        assert restored == original
        assert restored.canonical_bytes() == original.canonical_bytes()
        assert restored.digest == original.digest

    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    assert canonical_digest({"b": 2, "a": 1}, domain="fixture") == canonical_digest(
        {"a": 1, "b": 2}, domain="fixture"
    )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.__setitem__("feature_dimension", 99),
        lambda payload: payload.__setitem__("seed", 23),
        lambda payload: payload.__setitem__("normalization", "none"),
    ),
)
def test_tensor_spec_detects_stale_ids(mutation) -> None:
    spec = _spec()
    payload = spec.to_dict()
    mutation(payload)
    with pytest.raises(ContractError):
        TensorSpec.from_dict(payload)


def test_unknown_and_duplicate_keys_are_rejected() -> None:
    spec = _spec()
    unknown = spec.to_dict()
    unknown["future"] = True
    with pytest.raises(ContractError, match="unknown keys"):
        TensorSpec.from_dict(unknown)
    with pytest.raises(ContractError, match="duplicate JSON key"):
        TensorSpec.from_bytes(
            '{"schema":"forest-v2.tensor-spec/1","schema":"other"}'
        )

    term = CPTerm(1.0, (1, 0, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0, 0))
    term_payload = term.to_dict()
    term_payload["unknown"] = 1
    with pytest.raises(ContractError, match="unknown keys"):
        CPTerm.from_dict(term_payload)


def test_identifier_fields_reject_non_string_values_even_when_falsy() -> None:
    with pytest.raises(ContractError, match="spec_id must be a string"):
        TensorSpec(PLANES, ROLES, 5, 11, spec_id=0)  # type: ignore[arg-type]
    spec = _spec()
    with pytest.raises(ContractError, match="kernel_id must be a string"):
        identity = SeparableKernel.identity(spec)
        SeparableKernel(
            spec,
            identity.plane_matrix,
            identity.role_matrix,
            kernel_id=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError, match="tensor_id must be a string"):
        CPTensor(spec, (), tensor_id=False)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_nonfinite_values_refuse_at_every_numeric_boundary(value: float) -> None:
    spec = _spec()
    with pytest.raises(ContractError, match="finite"):
        CPTerm(value, (1, 0, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0, 0))
    with pytest.raises(ContractError, match="finite"):
        DenseTensor.from_flat(spec, (value,) + (0.0,) * (spec.dense_scalar_count - 1))
    with pytest.raises(ContractError, match="finite"):
        SeparableKernel(
            spec,
            ((value, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
            SeparableKernel.identity(spec).role_matrix,
        )


def test_wrong_ranks_shapes_and_spec_mismatches_refuse() -> None:
    spec = _spec(seed=11)
    other_spec = _spec(seed=23)
    with pytest.raises(ContractError, match="wrong shape"):
        CPTensor(
            spec,
            (CPTerm(1.0, (1, 0), (1, 0, 0, 0), (1, 0, 0, 0, 0)),),
        )
    with pytest.raises(ContractError, match="plane dimension"):
        DenseTensor(spec, (((0.0,) * 5,) * 4,))
    with pytest.raises(ContractError, match="plane_matrix"):
        SeparableKernel(spec, ((1.0,),), SeparableKernel.identity(spec).role_matrix)
    with pytest.raises(ContractError, match="exactly three cores"):
        TensorTrain(spec, ())  # type: ignore[arg-type]

    left = DenseTensor.from_flat(spec, (1.0,) * spec.dense_scalar_count)
    right = DenseTensor.from_flat(other_spec, (1.0,) * other_spec.dense_scalar_count)
    with pytest.raises(AlgebraError, match="do not match"):
        flattened_cosine(left, right)
    with pytest.raises(AlgebraError, match="kernel TensorSpec"):
        separable_contraction(left, left, SeparableKernel.identity(other_spec))


@pytest.mark.parametrize("kind", ("kernel", "cp", "dense", "tt"))
def test_tampered_serialized_payloads_refuse(kind: str) -> None:
    rng = random.Random(131)
    spec = _spec(seed=131)
    cp = _random_cp(rng, spec, 2)
    objects = {
        "kernel": _random_kernel(rng, spec),
        "cp": cp,
        "dense": cp.to_dense(),
        "tt": cp.to_tensor_train(),
    }
    payload = copy.deepcopy(objects[kind].to_dict())
    if kind == "kernel":
        payload["plane_matrix"][0][0] += 0.125
        loader = SeparableKernel.from_dict
    elif kind == "cp":
        payload["terms"][0]["weight"] += 0.125
        loader = CPTensor.from_dict
    elif kind == "dense":
        payload["values"][0][0][0] += 0.125
        loader = DenseTensor.from_dict
    else:
        payload["cores"][0][0][0][0] += 0.125
        loader = TensorTrain.from_dict
    with pytest.raises(ContractError, match="does not match"):
        loader(payload, spec)


def test_serialized_nonfinite_json_is_rejected_before_contract_construction() -> None:
    spec = _spec()
    payload = spec.to_dict()
    raw = json.dumps(payload).replace('"seed": 11', '"seed": NaN')
    with pytest.raises(ContractError, match="non-finite"):
        TensorSpec.from_bytes(raw)


def test_normalized_score_handles_large_finite_scalars_without_inf() -> None:
    spec = _spec(feature_dimension=1)
    values = (1e300,) + (0.0,) * (spec.dense_scalar_count - 1)
    tensor = DenseTensor.from_flat(spec, values)
    score = normalized_structured_score(tensor, tensor, SeparableKernel.identity(spec))
    assert score == pytest.approx(1.0)
    assert math.isfinite(score)


def test_normalized_cp_scores_handle_overflowing_finite_factor_products() -> None:
    spec = _spec(feature_dimension=1)
    huge = CPTensor(
        spec,
        (
            CPTerm(
                1e200,
                (1e200, 0.0, 0.0, 0.0),
                (1e200, 0.0, 0.0, 0.0),
                (1e200,),
            ),
        ),
    )
    dense = DenseTensor.from_flat(
        spec, (1e300,) + (0.0,) * (spec.dense_scalar_count - 1)
    )

    assert flattened_cosine(huge, huge) == pytest.approx(1.0)
    assert flattened_cosine(huge, dense) == pytest.approx(1.0)
    assert identity_contraction(huge, huge) == pytest.approx(1.0)
    assert identity_contraction(huge, dense) == pytest.approx(1.0)


def test_normalized_tt_scores_handle_overflowing_finite_core_products() -> None:
    spec = _spec(feature_dimension=1)
    huge = TensorTrain(
        spec,
        (
            (((1e200,), (0.0,), (0.0,), (0.0,)),),
            (((1e200,), (0.0,), (0.0,), (0.0,)),),
            (((1e200,),),),
        ),
    )

    assert flattened_cosine(huge, huge) == pytest.approx(1.0)
    assert identity_contraction(huge, huge) == pytest.approx(1.0)


def test_scaled_cp_fallback_preserves_a_representable_cancellation_residual() -> None:
    spec = _spec(feature_dimension=1)
    basis_plane = (1.0, 0.0, 0.0, 0.0)
    basis_role = (1.0, 0.0, 0.0, 0.0)
    largest = 1e300
    residual = CPTensor(
        spec,
        (
            CPTerm(largest, basis_plane, basis_role, (1.0,)),
            CPTerm(-math.nextafter(largest, 0.0), basis_plane, basis_role, (1.0,)),
        ),
    )
    reference = CPTensor(
        spec, (CPTerm(1.0, basis_plane, basis_role, (1.0,)),)
    )

    assert flattened_cosine(residual, reference) == pytest.approx(1.0)
    assert identity_contraction(residual, reference) == pytest.approx(1.0)


def test_cp_gram_shortcut_refuses_catastrophic_but_finite_cancellation() -> None:
    spec = _spec(feature_dimension=1)
    basis_plane = (1.0, 0.0, 0.0, 0.0)
    basis_role = (1.0, 0.0, 0.0, 0.0)
    largest = 1e20
    residual = CPTensor(
        spec,
        (
            CPTerm(largest, basis_plane, basis_role, (1.0,)),
            CPTerm(-math.nextafter(largest, 0.0), basis_plane, basis_role, (1.0,)),
        ),
    )
    reference = CPTensor(
        spec, (CPTerm(1.0, basis_plane, basis_role, (1.0,)),)
    )

    assert frobenius_norm(residual) == largest - math.nextafter(largest, 0.0)
    assert flattened_cosine(residual, reference) == pytest.approx(1.0)
    assert identity_contraction(residual, reference) == pytest.approx(1.0)


def test_exact_cp_fallback_keeps_residual_beyond_float_exponent_range() -> None:
    spec = _spec(feature_dimension=1)
    huge_plane = (1e308, 0.0, 0.0, 0.0)
    huge_role = (1e308, 0.0, 0.0, 0.0)
    basis_plane = (1.0, 0.0, 0.0, 0.0)
    basis_role = (1.0, 0.0, 0.0, 0.0)
    residual = CPTensor(
        spec,
        (
            CPTerm(1e308, huge_plane, huge_role, (1e308,)),
            CPTerm(-1e308, huge_plane, huge_role, (1e308,)),
            CPTerm(1.0, basis_plane, basis_role, (1.0,)),
        ),
    )
    reference = CPTensor(
        spec, (CPTerm(1.0, basis_plane, basis_role, (1.0,)),)
    )

    assert flattened_cosine(residual, reference) == pytest.approx(1.0)
    assert identity_contraction(residual, reference) == pytest.approx(1.0)
    assert normalized_structured_score(
        residual, reference, SeparableKernel.identity(spec)
    ) == pytest.approx(1.0)
    converted = residual.to_tensor_train()
    assert flattened_cosine(converted, reference) == pytest.approx(1.0)
    assert identity_contraction(converted, reference) == pytest.approx(1.0)


def test_cp_to_tt_resolves_overflowing_terms_before_finite_cancellation() -> None:
    spec = _spec(feature_dimension=1)
    basis_role = (1.0, 0.0, 0.0, 0.0)
    basis_feature = (1.0,)
    tensor = CPTensor(
        spec,
        (
            CPTerm(1e200, (1e200, 0.0, 0.0, 0.0), basis_role, basis_feature),
            CPTerm(-1e200, (1e200, 0.0, 0.0, 0.0), basis_role, basis_feature),
            CPTerm(
                1.0,
                (1.0, 0.0, 0.0, 0.0),
                basis_role,
                basis_feature,
            ),
        ),
    )

    converted = tensor.to_tensor_train()
    assert converted.to_dense().flat_values[0] == 1.0
    assert flattened_cosine(tensor, converted) == pytest.approx(1.0)


def test_tt_materialization_resolves_overflowing_intermediate_path_products() -> None:
    spec = _spec(feature_dimension=1)
    tensor = CPTensor(
        spec,
        (
            CPTerm(
                1.0,
                (1e200, 0.0, 0.0, 0.0),
                (1e200, 0.0, 0.0, 0.0),
                (1e-200,),
            ),
        ),
    )

    converted = tensor.to_tensor_train()
    assert converted.to_dense().flat_values[0] == pytest.approx(1e200)
    assert flattened_cosine(converted, tensor) == pytest.approx(1.0)


def test_cp_and_cp_to_tt_preserve_finite_catastrophic_cancellation() -> None:
    spec = _spec(feature_dimension=1)
    basis_role = (1.0, 0.0, 0.0, 0.0)
    basis_feature = (1.0,)
    largest = 1e20
    tensor = CPTensor(
        spec,
        (
            CPTerm(
                largest,
                (largest, 0.0, 0.0, 0.0),
                basis_role,
                basis_feature,
            ),
            CPTerm(
                -math.nextafter(largest, 0.0),
                (largest, 0.0, 0.0, 0.0),
                basis_role,
                basis_feature,
            ),
        ),
    )
    expected = float(
        Fraction.from_float(largest)
        * (
            Fraction.from_float(largest)
            - Fraction.from_float(math.nextafter(largest, 0.0))
        )
    )

    assert tensor.to_dense().flat_values[0] == expected
    converted = tensor.to_tensor_train()
    assert converted.to_dense().flat_values[0] == expected


def test_cp_to_tt_preserves_underflow_then_amplification() -> None:
    spec = _spec(feature_dimension=1)
    tensor = CPTensor(
        spec,
        (
            CPTerm(
                1e-300,
                (1e-300, 0.0, 0.0, 0.0),
                (1e300, 0.0, 0.0, 0.0),
                (1e300,),
            ),
        ),
    )
    exact = (
        Fraction.from_float(1e-300)
        * Fraction.from_float(1e-300)
        * Fraction.from_float(1e300)
        * Fraction.from_float(1e300)
    )
    expected = float(exact)

    assert tensor.to_dense().flat_values[0] == expected
    converted = tensor.to_tensor_train()
    assert converted.to_dense().flat_values[0] == expected


def test_exact_tt_fallback_keeps_residual_beyond_float_exponent_range() -> None:
    spec = _spec(feature_dimension=1)
    first = (
        (
            (1e308, -1e308, 1.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
        ),
    )
    middle = tuple(
        tuple(
            tuple(
                (1e308 if left < 2 else 1.0) if left == right and role == 0 else 0.0
                for right in range(3)
            )
            for role in range(4)
        )
        for left in range(3)
    )
    final = tuple(
        (((1e308 if rank < 2 else 1.0),),)
        for rank in range(3)
    )
    residual = TensorTrain(spec, (first, middle, final))
    reference = DenseTensor.from_flat(
        spec, (1.0,) + (0.0,) * (spec.dense_scalar_count - 1)
    )

    assert flattened_cosine(residual, reference) == pytest.approx(1.0)
    assert identity_contraction(residual, reference) == pytest.approx(1.0)


def test_cp_structured_score_rescales_an_overflowing_denominator() -> None:
    spec = _spec(feature_dimension=1)
    basis_plane = (1.0, 0.0, 0.0, 0.0)
    basis_role = (1.0, 0.0, 0.0, 0.0)
    tensor = CPTensor(
        spec, (CPTerm(1e100, basis_plane, basis_role, (1.0,)),)
    )
    identity = SeparableKernel.identity(spec)
    plane = tuple(
        tuple(
            1e100
            if row == column == 0
            else 1e110
            if row == column == 1
            else 1.0
            if row == column
            else 0.0
            for column in range(len(spec.planes))
        )
        for row in range(len(spec.planes))
    )
    kernel = SeparableKernel(spec, plane, identity.role_matrix)

    assert normalized_structured_score(tensor, tensor, kernel) == pytest.approx(1e-10)


def test_frobenius_norm_does_not_square_a_representable_large_cp_value() -> None:
    spec = _spec(feature_dimension=1)
    tensor = CPTensor(
        spec,
        (
            CPTerm(
                1e100,
                (1e100, 0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0, 0.0),
                (1.0,),
            ),
        ),
    )

    assert frobenius_norm(tensor) == pytest.approx(1e200)


def test_scaled_cp_fallback_handles_nonzero_subnormal_norms() -> None:
    spec = _spec(feature_dimension=1)
    tiny = CPTensor(
        spec,
        (
            CPTerm(
                1e-300,
                (1.0, 0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0, 0.0),
                (1.0,),
            ),
        ),
    )

    assert flattened_cosine(tiny, tiny) == pytest.approx(1.0)
    assert identity_contraction(tiny, tiny) == pytest.approx(1.0)


def test_exact_scaled_cp_zero_pruning_matches_unfiltered_rational_reference() -> None:
    spec = _spec(feature_dimension=3)
    tensor = CPTensor(
        spec,
        (
            CPTerm(
                2.0,
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 3.0, 0.0),
            ),
            CPTerm(
                -1.0,
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 2.0, 0.0),
            ),
            CPTerm(
                0.0,
                (1e300, 1e300, 1e300, 1e300),
                (1e300, 1e300, 1e300, 1e300),
                (1e300, 1e300, 1e300),
            ),
        ),
    )

    exact_values = []
    for plane in range(len(spec.planes)):
        for role in range(len(spec.roles)):
            for feature in range(spec.feature_dimension):
                exact_values.append(
                    sum(
                        (
                            Fraction.from_float(term.weight)
                            * Fraction.from_float(term.plane[plane])
                            * Fraction.from_float(term.role[role])
                            * Fraction.from_float(term.feature[feature])
                            for term in tensor.terms
                        ),
                        Fraction(0),
                    )
                )
    expected_scale = max(abs(value) for value in exact_values)
    expected = tuple(float(value / expected_scale) for value in exact_values)

    actual, actual_scale = algebra._exact_scaled_cp_for_normalized(tensor)

    assert actual_scale == expected_scale
    assert actual.flat_values == expected


def test_exact_scaled_cp_skips_fraction_products_with_exact_zero_factors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec(feature_dimension=3)
    tensor = CPTensor(
        spec,
        (
            CPTerm(
                2.0,
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 3.0, 0.0),
            ),
            CPTerm(
                0.0,
                (1.0, 1.0, 1.0, 1.0),
                (1.0, 1.0, 1.0, 1.0),
                (1.0, 1.0, 1.0),
            ),
        ),
    )

    class CountingFraction:
        from_float_calls = 0

        def __new__(cls, *args: object) -> Fraction:
            return Fraction(*args)

        @classmethod
        def from_float(cls, value: float) -> Fraction:
            cls.from_float_calls += 1
            return Fraction.from_float(value)

    monkeypatch.setattr(algebra, "Fraction", CountingFraction)

    dense, scale = algebra._exact_scaled_cp_for_normalized(tensor)

    assert scale == Fraction(6)
    assert dense.flat_values.count(1.0) == 1
    assert dense.flat_values.count(0.0) == spec.dense_scalar_count - 1
    # Exactly one coordinate has a non-zero weight/plane/role/feature product.
    assert CountingFraction.from_float_calls == 4


def test_exact_scaled_tt_skips_fraction_products_with_exact_zero_factors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec(feature_dimension=3)
    tensor = TensorTrain(
        spec,
        (
            (((1.0,), (0.0,), (0.0,), (0.0,)),),
            (((0.0,), (2.0,), (0.0,), (0.0,)),),
            (((0.0,), (3.0,), (0.0,)),),
        ),
    )

    class CountingFraction:
        from_float_calls = 0

        def __new__(cls, *args: object) -> Fraction:
            return Fraction(*args)

        @classmethod
        def from_float(cls, value: float) -> Fraction:
            cls.from_float_calls += 1
            return Fraction.from_float(value)

    monkeypatch.setattr(algebra, "Fraction", CountingFraction)

    dense, scale = algebra._exact_scaled_tt_for_normalized(tensor)

    assert scale == Fraction(6)
    assert dense.flat_values.count(1.0) == 1
    assert dense.flat_values.count(0.0) == spec.dense_scalar_count - 1
    assert CountingFraction.from_float_calls == 3

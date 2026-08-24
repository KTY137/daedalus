"""Reference algebra for the isolated tensor-embedding experiment.

The routines favor explicit, inspectable equations over numerical-library
shortcuts.  Dense, CP, and Tensor-Train values all describe the same rank-three
tensor and are never treated as separate evidence sources.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from typing import Sequence

from .contracts import (
    CPTensor,
    CPTerm,
    DenseTensor,
    Matrix,
    SeparableKernel,
    TensorLike,
    TensorSpec,
    TensorTrain,
)


class AlgebraError(ValueError):
    """An algebra operation was undefined or crossed a contract boundary."""


def _require_tensor(value: object, *, label: str) -> TensorLike:
    if not isinstance(value, (DenseTensor, CPTensor, TensorTrain)):
        raise AlgebraError(f"{label} must be a DenseTensor, CPTensor, or TensorTrain")
    return value


def _require_compatible(
    query: TensorLike, document: TensorLike, kernel: SeparableKernel | None = None
) -> TensorSpec:
    query = _require_tensor(query, label="query")
    document = _require_tensor(document, label="document")
    if query.spec != document.spec or query.spec_id != document.spec_id:
        raise AlgebraError("query and document TensorSpecs do not match")
    if kernel is not None:
        if not isinstance(kernel, SeparableKernel):
            raise AlgebraError("kernel must be a SeparableKernel")
        if kernel.spec != query.spec or kernel.spec_id != query.spec_id:
            raise AlgebraError("kernel TensorSpec does not match the tensors")
    return query.spec


def _finite(value: float, *, label: str) -> float:
    if not math.isfinite(value):
        raise AlgebraError(f"{label} is non-finite")
    return 0.0 if value == 0.0 else value


def _dot(left: Sequence[float], right: Sequence[float], *, label: str = "dot product") -> float:
    if len(left) != len(right):
        raise AlgebraError(f"{label} received vectors of different lengths")
    try:
        value = math.fsum(a * b for a, b in zip(left, right))
    except (OverflowError, ValueError) as exc:
        raise AlgebraError(f"{label} could not be represented as float64") from exc
    return _finite(value, label=label)


def _bilinear(left: Sequence[float], matrix: Matrix, right: Sequence[float]) -> float:
    if len(matrix) != len(left) or any(len(row) != len(right) for row in matrix):
        raise AlgebraError("bilinear form shape mismatch")
    try:
        value = math.fsum(
            left[row] * matrix[row][column] * right[column]
            for row in range(len(left))
            for column in range(len(right))
        )
    except (OverflowError, ValueError) as exc:
        raise AlgebraError("bilinear form could not be represented as float64") from exc
    return _finite(value, label="bilinear form")


def _fraction_to_finite_float(value: Fraction, *, label: str) -> float:
    try:
        converted = float(value)
    except OverflowError as exc:
        raise AlgebraError(f"{label} exceeds float64") from exc
    return _finite(converted, label=label)


def cp_to_dense(tensor: CPTensor) -> DenseTensor:
    """Materialize the exact binary64 CP value in canonical order.

    The factors stored in a :class:`CPTensor` are binary64 numbers.  Their
    mathematical product and the sum across terms are therefore evaluated as
    exact rationals before the *single* final conversion back to binary64.
    A float fast path is not sound here: it can return a finite but wrong
    residual after cancellation, or underflow an early factor product that a
    later factor would bring back into range.
    """

    if not isinstance(tensor, CPTensor):
        raise AlgebraError("cp_to_dense expects a CPTensor")
    plane_count, role_count, feature_count = tensor.spec.shape
    values: list[tuple[tuple[float, ...], ...]] = []
    for plane in range(plane_count):
        roles: list[tuple[float, ...]] = []
        for role in range(role_count):
            fiber: list[float] = []
            for feature in range(feature_count):
                exact = sum(
                    (
                        Fraction.from_float(term.weight)
                        * Fraction.from_float(term.plane[plane])
                        * Fraction.from_float(term.role[role])
                        * Fraction.from_float(term.feature[feature])
                        for term in tensor.terms
                        if term.weight != 0.0
                        and term.plane[plane] != 0.0
                        and term.role[role] != 0.0
                        and term.feature[feature] != 0.0
                    ),
                    Fraction(0),
                )
                value = _fraction_to_finite_float(
                    exact, label="CP materialization"
                )
                fiber.append(value)
            roles.append(tuple(fiber))
        values.append(tuple(roles))
    return DenseTensor(spec=tensor.spec, values=tuple(values))


def tt_to_dense(tensor: TensorTrain) -> DenseTensor:
    """Contract all TT ranks as exact binary64 rationals.

    As for :func:`cp_to_dense`, there is exactly one rounding step per output
    coordinate.  This prevents both finite cancellation error and the
    underflow-then-amplification failure possible with left-associated float
    products.
    """

    if not isinstance(tensor, TensorTrain):
        raise AlgebraError("tt_to_dense expects a TensorTrain")
    first, middle, final = tensor.cores
    rank_one, rank_two = tensor.ranks
    plane_count, role_count, feature_count = tensor.spec.shape
    values: list[tuple[tuple[float, ...], ...]] = []
    for plane in range(plane_count):
        roles: list[tuple[float, ...]] = []
        for role in range(role_count):
            fiber: list[float] = []
            for feature in range(feature_count):
                exact = sum(
                    (
                        Fraction.from_float(first[0][plane][left])
                        * Fraction.from_float(middle[left][role][right])
                        * Fraction.from_float(final[right][feature][0])
                        for left in range(rank_one)
                        for right in range(rank_two)
                        if first[0][plane][left] != 0.0
                        and middle[left][role][right] != 0.0
                        and final[right][feature][0] != 0.0
                    ),
                    Fraction(0),
                )
                value = _fraction_to_finite_float(
                    exact, label="Tensor-Train materialization"
                )
                fiber.append(value)
            roles.append(tuple(fiber))
        values.append(tuple(roles))
    return DenseTensor(spec=tensor.spec, values=tuple(values))


def to_dense(tensor: TensorLike) -> DenseTensor:
    """Return the dense value of any supported representation."""

    if isinstance(tensor, DenseTensor):
        return tensor
    if isinstance(tensor, CPTensor):
        return cp_to_dense(tensor)
    if isinstance(tensor, TensorTrain):
        return tt_to_dense(tensor)
    raise AlgebraError("to_dense expects a DenseTensor, CPTensor, or TensorTrain")


def _scaled_dense_from_exact_values(
    spec: TensorSpec, exact_values: Sequence[Fraction]
) -> tuple[DenseTensor, Fraction]:
    """Scale exact rational coordinates into float64 without losing residuals.

    Every finite binary64 input has an exact rational representation.  This
    slow path is used only after a fast factored operation overflows or becomes
    cancellation-conditioned; it therefore preserves a small residual even
    when much larger CP/TT terms cancel across more than 1074 exponent bits.
    """

    scale = max((abs(value) for value in exact_values), default=Fraction(0))
    if scale == 0:
        return (
            DenseTensor.from_flat(spec, (0.0,) * spec.dense_scalar_count),
            scale,
        )
    scaled = tuple(float(value / scale) for value in exact_values)
    return DenseTensor.from_flat(spec, scaled), scale


def _exact_scaled_cp_for_normalized(
    tensor: CPTensor,
) -> tuple[DenseTensor, Fraction]:
    """Materialize a CP value exactly, then return a max-scaled float tensor."""

    plane_count, role_count, feature_count = tensor.spec.shape
    values: list[Fraction] = []
    for plane in range(plane_count):
        for role in range(role_count):
            for feature in range(feature_count):
                value = sum(
                    (
                        Fraction.from_float(term.weight)
                        * Fraction.from_float(term.plane[plane])
                        * Fraction.from_float(term.role[role])
                        * Fraction.from_float(term.feature[feature])
                        for term in tensor.terms
                        if term.weight != 0.0
                        and term.plane[plane] != 0.0
                        and term.role[role] != 0.0
                        and term.feature[feature] != 0.0
                    ),
                    Fraction(0),
                )
                values.append(value)
    return _scaled_dense_from_exact_values(tensor.spec, values)


def _exact_scaled_tt_for_normalized(
    tensor: TensorTrain,
) -> tuple[DenseTensor, Fraction]:
    """Materialize a Tensor Train exactly, then max-scale its coordinates."""

    first, middle, final = tensor.cores
    rank_one, rank_two = tensor.ranks
    plane_count, role_count, feature_count = tensor.spec.shape
    values: list[Fraction] = []
    for plane in range(plane_count):
        for role in range(role_count):
            for feature in range(feature_count):
                value = sum(
                    (
                        Fraction.from_float(first[0][plane][left])
                        * Fraction.from_float(middle[left][role][right])
                        * Fraction.from_float(final[right][feature][0])
                        for left in range(rank_one)
                        for right in range(rank_two)
                        if first[0][plane][left] != 0.0
                        and middle[left][role][right] != 0.0
                        and final[right][feature][0] != 0.0
                    ),
                    Fraction(0),
                )
                values.append(value)
    return _scaled_dense_from_exact_values(tensor.spec, values)


def _scaled_dense_for_normalized(tensor: TensorLike) -> DenseTensor:
    """Materialize a scale-equivalent dense value without intermediate overflow."""

    checked = _require_tensor(tensor, label="tensor")
    if isinstance(checked, CPTensor):
        return _exact_scaled_cp_for_normalized(checked)[0]
    elif isinstance(checked, TensorTrain):
        return _exact_scaled_tt_for_normalized(checked)[0]
    else:
        dense = checked
    scale = max((abs(value) for value in dense.flat_values), default=0.0)
    return dense if scale == 0.0 else _scale_dense(dense, scale)


def _scaled_cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise AlgebraError("cosine vectors have different lengths")
    left_scale = max((abs(value) for value in left), default=0.0)
    right_scale = max((abs(value) for value in right), default=0.0)
    if left_scale == 0.0 or right_scale == 0.0:
        return 0.0
    left_scaled = tuple(value / left_scale for value in left)
    right_scaled = tuple(value / right_scale for value in right)
    numerator = _dot(left_scaled, right_scaled, label="scaled cosine numerator")
    left_norm = math.hypot(*left_scaled)
    right_norm = math.hypot(*right_scaled)
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    score = _finite(numerator / (left_norm * right_norm), label="cosine")
    if score > 1.0:
        if score > 1.0 + 1e-12:
            raise AlgebraError("cosine exceeded its mathematical bound")
        return 1.0
    if score < -1.0:
        if score < -1.0 - 1e-12:
            raise AlgebraError("cosine exceeded its mathematical bound")
        return -1.0
    return score


def flattened_cosine(query: TensorLike, document: TensorLike) -> float:
    """Cosine over the exact same dense scalars used by tensor contraction."""

    _require_compatible(query, document)
    if isinstance(query, CPTensor) and isinstance(document, CPTensor):
        try:
            numerator, numerator_absolute_sum = _cp_flattened_dot_components(
                query, document
            )
            if not _cp_sum_is_well_conditioned(
                numerator, numerator_absolute_sum
            ):
                raise AlgebraError("CP cosine numerator is ill-conditioned")
            query_norm = _cp_frobenius_norm(query)
            document_norm = _cp_frobenius_norm(document)
            if query_norm == 0.0 or document_norm == 0.0:
                if not query.terms or not document.terms:
                    return 0.0
                raise AlgebraError("CP norm underflowed or cancelled")
            score = _finite(
                numerator / (query_norm * document_norm), label="CP flattened cosine"
            )
            return max(-1.0, min(1.0, score))
        except AlgebraError:
            # Public contracts permit every finite factor. Fall back to a
            # scale-equivalent materialization when products exceed float64.
            pass
    return _scaled_cosine(
        _scaled_dense_for_normalized(query).flat_values,
        _scaled_dense_for_normalized(document).flat_values,
    )


def flattened_dot(query: TensorLike, document: TensorLike) -> float:
    """Unnormalized Frobenius inner product over flattened scalars."""

    _require_compatible(query, document)
    if isinstance(query, CPTensor) and isinstance(document, CPTensor):
        return _cp_flattened_dot(query, document)
    return _dot(to_dense(query).flat_values, to_dense(document).flat_values)


def frobenius_norm(tensor: TensorLike) -> float:
    """Overflow-resistant Frobenius norm of any representation."""

    checked = _require_tensor(tensor, label="tensor")
    if isinstance(checked, CPTensor):
        try:
            return _cp_frobenius_norm(checked)
        except AlgebraError:
            # Squaring a representable dense value can overflow, and a Gram
            # sum can lose almost all digits under CP-term cancellation.  A
            # rational materialization preserves the represented cancellation
            # before scaling back to the requested float64 norm.
            dense, exact_scale = _exact_scaled_cp_for_normalized(checked)
            scaled_norm = math.hypot(*dense.flat_values)
            try:
                value = float(exact_scale) * scaled_norm
            except OverflowError as exc:
                raise AlgebraError("CP Frobenius norm overflowed float64") from exc
            return _finite(value, label="CP Frobenius norm")
    dense = to_dense(checked)
    return math.hypot(*dense.flat_values)


def _cp_flattened_dot_components(
    query: CPTensor, document: CPTensor
) -> tuple[float, float]:
    """Return the CP dot and the absolute sum of its rounded summands."""

    try:
        terms = tuple(
            query_term.weight
            * document_term.weight
            * _dot(query_term.plane, document_term.plane, label="CP plane dot")
            * _dot(query_term.role, document_term.role, label="CP role dot")
            * _dot(query_term.feature, document_term.feature, label="CP feature dot")
            for query_term in query.terms
            for document_term in document.terms
        )
        value = math.fsum(terms)
        absolute_sum = math.fsum(abs(term) for term in terms)
    except (OverflowError, ValueError) as exc:
        if isinstance(exc, AlgebraError):
            raise
        raise AlgebraError("CP flattened dot overflowed float64") from exc
    return (
        _finite(value, label="CP flattened dot"),
        _finite(absolute_sum, label="CP flattened absolute sum"),
    )


def _cp_sum_is_well_conditioned(value: float, absolute_sum: float) -> bool:
    """Whether rounded product error cannot dominate a CP cancellation.

    ``math.fsum`` accurately adds its inputs, but each multilinear product was
    already rounded.  When the residual is only a few ulps of the absolute
    term mass, the Gram shortcut is not trustworthy; callers must use the
    scale-equivalent dense fallback instead.
    """

    if absolute_sum == 0.0:
        return True
    return abs(value) > 64.0 * math.ulp(1.0) * absolute_sum


def _cp_flattened_dot(query: CPTensor, document: CPTensor) -> float:
    """Factored Frobenius product for two CP values."""

    return _cp_flattened_dot_components(query, document)[0]


def _cp_frobenius_norm(tensor: CPTensor) -> float:
    squared, absolute_sum = _cp_flattened_dot_components(tensor, tensor)
    if not _cp_sum_is_well_conditioned(squared, absolute_sum):
        raise AlgebraError("CP self-product is ill-conditioned")
    if squared < 0.0:
        if squared < -1e-12:
            raise AlgebraError("CP self-product is negative")
        squared = 0.0
    return _finite(math.sqrt(squared), label="CP Frobenius norm")


def _dense_raw_contraction(
    query: DenseTensor,
    document: DenseTensor,
    plane_matrix: Matrix,
    role_matrix: Matrix,
) -> float:
    plane_count, role_count, feature_count = query.spec.shape
    try:
        numerator = math.fsum(
            query.values[query_plane][query_role][feature]
            * plane_matrix[query_plane][document_plane]
            * role_matrix[query_role][document_role]
            * document.values[document_plane][document_role][feature]
            for query_plane in range(plane_count)
            for document_plane in range(plane_count)
            for query_role in range(role_count)
            for document_role in range(role_count)
            for feature in range(feature_count)
        )
    except (OverflowError, ValueError) as exc:
        raise AlgebraError("separable contraction overflowed float64") from exc
    return _finite(numerator, label="separable contraction")


def dense_separable_contraction(
    query: DenseTensor, document: DenseTensor, kernel: SeparableKernel
) -> float:
    """Unnormalized separable contraction between two dense tensors."""

    if not isinstance(query, DenseTensor) or not isinstance(document, DenseTensor):
        raise AlgebraError("dense_separable_contraction requires DenseTensor operands")
    _require_compatible(query, document, kernel)
    return _dense_raw_contraction(query, document, kernel.plane_matrix, kernel.role_matrix)


def cp_separable_contraction(
    query: CPTensor, document: CPTensor, kernel: SeparableKernel
) -> float:
    """Direct CP contraction without materializing the dense tensors."""

    if not isinstance(query, CPTensor) or not isinstance(document, CPTensor):
        raise AlgebraError("cp_separable_contraction requires CPTensor operands")
    _require_compatible(query, document, kernel)
    return _cp_separable_contraction_components(query, document, kernel)[0]


def _cp_separable_contraction_components(
    query: CPTensor, document: CPTensor, kernel: SeparableKernel
) -> tuple[float, float]:
    """Return a CP contraction and the absolute mass of its summands."""

    if not isinstance(query, CPTensor) or not isinstance(document, CPTensor):
        raise AlgebraError("CP contraction requires CPTensor operands")
    _require_compatible(query, document, kernel)
    try:
        terms = tuple(
            query_term.weight
            * document_term.weight
            * _bilinear(query_term.plane, kernel.plane_matrix, document_term.plane)
            * _bilinear(query_term.role, kernel.role_matrix, document_term.role)
            * _dot(query_term.feature, document_term.feature, label="CP feature dot")
            for query_term in query.terms
            for document_term in document.terms
        )
        value = math.fsum(terms)
        absolute_sum = math.fsum(abs(term) for term in terms)
    except (OverflowError, ValueError) as exc:
        if isinstance(exc, AlgebraError):
            raise
        raise AlgebraError("CP separable contraction overflowed float64") from exc
    return (
        _finite(value, label="CP separable contraction"),
        _finite(absolute_sum, label="CP separable absolute sum"),
    )


def tt_separable_contraction(
    query: TensorTrain, document: TensorTrain, kernel: SeparableKernel
) -> float:
    """Exact TT contraction, evaluated through its exact dense materialization."""

    if not isinstance(query, TensorTrain) or not isinstance(document, TensorTrain):
        raise AlgebraError("tt_separable_contraction requires TensorTrain operands")
    _require_compatible(query, document, kernel)
    return dense_separable_contraction(tt_to_dense(query), tt_to_dense(document), kernel)


def separable_contraction(
    query: TensorLike, document: TensorLike, kernel: SeparableKernel
) -> float:
    """Unnormalized separable contraction for same or mixed representations."""

    _require_compatible(query, document, kernel)
    if isinstance(query, DenseTensor) and isinstance(document, DenseTensor):
        return dense_separable_contraction(query, document, kernel)
    if isinstance(query, CPTensor) and isinstance(document, CPTensor):
        return cp_separable_contraction(query, document, kernel)
    if isinstance(query, TensorTrain) and isinstance(document, TensorTrain):
        return tt_separable_contraction(query, document, kernel)
    return dense_separable_contraction(to_dense(query), to_dense(document), kernel)


@lru_cache(maxsize=128)
def operator_norm_upper_bound(matrix: Matrix) -> float:
    """Return ``sqrt(||A||_1 * ||A||_inf)``, an induced 2-norm upper bound.

    Unlike the Frobenius bound, this evaluates to exactly one for an identity
    matrix, which makes the identity-kernel regression equal ordinary cosine.
    """

    if not matrix or not matrix[0]:
        raise AlgebraError("operator norm requires a non-empty matrix")
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise AlgebraError("operator norm requires a rectangular matrix")
    try:
        infinity_norm = max(math.fsum(abs(value) for value in row) for row in matrix)
        one_norm = max(
            math.fsum(abs(matrix[row][column]) for row in range(len(matrix)))
            for column in range(width)
        )
        bound = math.sqrt(one_norm * infinity_norm)
    except (OverflowError, ValueError) as exc:
        raise AlgebraError("operator norm upper bound overflowed float64") from exc
    return _finite(bound, label="operator norm upper bound")


def _scale_dense(tensor: DenseTensor, scale: float) -> DenseTensor:
    if scale <= 0.0 or not math.isfinite(scale):
        raise AlgebraError("dense scaling factor must be finite and positive")
    return DenseTensor(
        spec=tensor.spec,
        values=tuple(
            tuple(tuple(value / scale for value in fiber) for fiber in plane)
            for plane in tensor.values
        ),
    )


def _scale_matrix(matrix: Matrix, scale: float) -> Matrix:
    if scale <= 0.0 or not math.isfinite(scale):
        raise AlgebraError("matrix scaling factor must be finite and positive")
    return tuple(tuple(value / scale for value in row) for row in matrix)


def normalized_structured_score(
    query: TensorLike, document: TensorLike, kernel: SeparableKernel
) -> float:
    """Bounded separable score using declared operator-norm upper bounds.

    The calculation is rescaled before contraction, so finite but very large
    inputs do not create an avoidable ``inf / inf``.  Scaling cancels from the
    ratio and changes no mathematical score.
    """

    _require_compatible(query, document, kernel)
    if isinstance(query, CPTensor) and isinstance(document, CPTensor):
        try:
            query_norm = _cp_frobenius_norm(query)
            document_norm = _cp_frobenius_norm(document)
            if query_norm == 0.0 or document_norm == 0.0:
                if not query.terms or not document.terms:
                    return 0.0
                raise AlgebraError("CP norm underflowed or cancelled")
            numerator, numerator_absolute_sum = _cp_separable_contraction_components(
                query, document, kernel
            )
            if not _cp_sum_is_well_conditioned(
                numerator, numerator_absolute_sum
            ):
                raise AlgebraError("CP structured numerator is ill-conditioned")
            denominator = (
                query_norm
                * document_norm
                * operator_norm_upper_bound(kernel.plane_matrix)
                * operator_norm_upper_bound(kernel.role_matrix)
            )
            if denominator == 0.0 or not math.isfinite(denominator):
                raise AlgebraError("normalized CP denominator is not representable")
            score = _finite(
                numerator / denominator, label="normalized CP structured score"
            )
            if score > 1.0:
                if score > 1.0 + 1e-10:
                    raise AlgebraError(
                        "normalized structured score exceeded its operator-norm bound"
                    )
                return 1.0
            if score < -1.0:
                if score < -1.0 - 1e-10:
                    raise AlgebraError(
                        "normalized structured score exceeded its operator-norm bound"
                    )
                return -1.0
            return score
        except AlgebraError:
            # The bounded path below rescales every factor before multiplying.
            pass
    query_dense = _scaled_dense_for_normalized(query)
    document_dense = _scaled_dense_for_normalized(document)
    query_scale = max(abs(value) for value in query_dense.flat_values)
    document_scale = max(abs(value) for value in document_dense.flat_values)
    plane_scale = max(abs(value) for row in kernel.plane_matrix for value in row)
    role_scale = max(abs(value) for row in kernel.role_matrix for value in row)
    if query_scale == 0.0 or document_scale == 0.0 or plane_scale == 0.0 or role_scale == 0.0:
        return 0.0

    scaled_query = _scale_dense(query_dense, query_scale)
    scaled_document = _scale_dense(document_dense, document_scale)
    scaled_plane = _scale_matrix(kernel.plane_matrix, plane_scale)
    scaled_role = _scale_matrix(kernel.role_matrix, role_scale)
    numerator = _dense_raw_contraction(
        scaled_query, scaled_document, scaled_plane, scaled_role
    )
    denominator = (
        math.hypot(*scaled_query.flat_values)
        * math.hypot(*scaled_document.flat_values)
        * operator_norm_upper_bound(scaled_plane)
        * operator_norm_upper_bound(scaled_role)
    )
    if denominator == 0.0:
        return 0.0
    score = _finite(numerator / denominator, label="normalized structured score")
    if score > 1.0:
        if score > 1.0 + 1e-10:
            raise AlgebraError("normalized structured score exceeded its operator-norm bound")
        return 1.0
    if score < -1.0:
        if score < -1.0 - 1e-10:
            raise AlgebraError("normalized structured score exceeded its operator-norm bound")
        return -1.0
    return score


structured_score = normalized_structured_score


@dataclass(frozen=True)
class PreparedFlattenedBilinearQuery:
    """Query-constant state for the independent flattened bilinear control.

    The transformed vector and its three normalization factors depend only on
    the query, TensorSpec (and therefore seed), and kernel.  Keeping them in an
    immutable value lets a retriever reuse the exact same arithmetic across
    every document without turning this control into a tensor contraction.
    """

    spec: TensorSpec
    kernel_id: str
    transformed_query: tuple[float, ...]
    query_norm: float
    plane_operator_norm: float
    role_operator_norm: float
    is_zero: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TensorSpec):
            raise AlgebraError("prepared bilinear query spec must be a TensorSpec")
        if type(self.kernel_id) is not str or not self.kernel_id:
            raise AlgebraError("prepared bilinear query kernel_id must be non-empty")
        transformed = tuple(self.transformed_query)
        expected_size = 0 if self.is_zero else self.spec.dense_scalar_count
        if len(transformed) != expected_size:
            raise AlgebraError("prepared bilinear query has the wrong vector size")
        if any(not math.isfinite(value) for value in transformed):
            raise AlgebraError("prepared bilinear query contains non-finite values")
        for label, value in (
            ("query norm", self.query_norm),
            ("plane operator norm", self.plane_operator_norm),
            ("role operator norm", self.role_operator_norm),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise AlgebraError(f"prepared bilinear {label} must be finite and non-negative")
        if type(self.is_zero) is not bool:
            raise AlgebraError("prepared bilinear is_zero must be a boolean")
        object.__setattr__(self, "transformed_query", transformed)


def prepare_flattened_bilinear_query(
    query: TensorLike, kernel: SeparableKernel
) -> PreparedFlattenedBilinearQuery:
    """Precompute only the query-constant side of the flat bilinear score."""

    query = _require_tensor(query, label="query")
    if not isinstance(kernel, SeparableKernel):
        raise AlgebraError("kernel must be a SeparableKernel")
    if kernel.spec != query.spec or kernel.spec_id != query.spec_id:
        raise AlgebraError("kernel TensorSpec does not match the query")

    query_dense = _scaled_dense_for_normalized(query)
    query_scale = max(abs(value) for value in query_dense.flat_values)
    plane_scale = max(abs(value) for row in kernel.plane_matrix for value in row)
    role_scale = max(abs(value) for row in kernel.role_matrix for value in row)
    if query_scale == 0.0 or plane_scale == 0.0 or role_scale == 0.0:
        return PreparedFlattenedBilinearQuery(
            spec=query.spec,
            kernel_id=kernel.kernel_id,
            transformed_query=(),
            query_norm=0.0,
            plane_operator_norm=0.0,
            role_operator_norm=0.0,
            is_zero=True,
        )

    scaled_query = _scale_dense(query_dense, query_scale)
    scaled_plane = _scale_matrix(kernel.plane_matrix, plane_scale)
    scaled_role = _scale_matrix(kernel.role_matrix, role_scale)
    plane_count, role_count, feature_count = query.spec.shape
    transformed_query: list[float] = []
    for document_plane in range(plane_count):
        for document_role in range(role_count):
            for feature in range(feature_count):
                transformed_query.append(
                    _finite(
                        math.fsum(
                            scaled_query.values[query_plane][query_role][feature]
                            * scaled_plane[query_plane][document_plane]
                            * scaled_role[query_role][document_role]
                            for query_plane in range(plane_count)
                            for query_role in range(role_count)
                        ),
                        label="flattened bilinear transform",
                    )
                )
    return PreparedFlattenedBilinearQuery(
        spec=query.spec,
        kernel_id=kernel.kernel_id,
        transformed_query=tuple(transformed_query),
        query_norm=math.hypot(*scaled_query.flat_values),
        plane_operator_norm=operator_norm_upper_bound(scaled_plane),
        role_operator_norm=operator_norm_upper_bound(scaled_role),
    )


def normalized_prepared_flattened_bilinear_score(
    prepared_query: PreparedFlattenedBilinearQuery, document: TensorLike
) -> float:
    """Score one document against an independently prepared flat query."""

    if not isinstance(prepared_query, PreparedFlattenedBilinearQuery):
        raise AlgebraError(
            "prepared_query must be a PreparedFlattenedBilinearQuery"
        )
    document = _require_tensor(document, label="document")
    if (
        document.spec != prepared_query.spec
        or document.spec_id != prepared_query.spec.spec_id
    ):
        raise AlgebraError("prepared query and document TensorSpecs do not match")

    document_dense = _scaled_dense_for_normalized(document)
    document_scale = max(abs(value) for value in document_dense.flat_values)
    if prepared_query.is_zero or document_scale == 0.0:
        return 0.0

    scaled_document = _scale_dense(document_dense, document_scale)
    numerator = _dot(
        prepared_query.transformed_query,
        scaled_document.flat_values,
        label="flattened bilinear numerator",
    )
    # Keep the original left-to-right multiplication order bit-for-bit.  The
    # factors are stored separately instead of folding a rounded prefix into
    # the prepared query.
    denominator = (
        prepared_query.query_norm
        * math.hypot(*scaled_document.flat_values)
        * prepared_query.plane_operator_norm
        * prepared_query.role_operator_norm
    )
    if denominator == 0.0:
        return 0.0
    score = _finite(numerator / denominator, label="normalized flattened bilinear score")
    if score > 1.0:
        if score > 1.0 + 1e-10:
            raise AlgebraError("flattened bilinear score exceeded its operator-norm bound")
        return 1.0
    if score < -1.0:
        if score < -1.0 - 1e-10:
            raise AlgebraError("flattened bilinear score exceeded its operator-norm bound")
        return -1.0
    return score


def normalized_flattened_bilinear_score(
    query: TensorLike, document: TensorLike, kernel: SeparableKernel
) -> float:
    """Independent flattened-vector form of the separable contraction.

    With plane-major/role-major/feature-major vectorization this evaluates
    ``vec(Q)^T (K_plane ⊗ K_role ⊗ I) vec(D)``.  It deliberately uses a
    transformed flat query followed by one ordinary dot product rather than
    any tensor-contraction helper.  Equality with
    :func:`normalized_structured_score` is therefore the representation-null
    control: the frozen separable tensor score is a structured implementation
    of a bilinear vector score, not extra mathematical expressivity.
    """

    _require_compatible(query, document, kernel)
    return normalized_prepared_flattened_bilinear_score(
        prepare_flattened_bilinear_query(query, kernel), document
    )


def identity_contraction(query: TensorLike, document: TensorLike) -> float:
    """Normalized identity-kernel contraction; exactly the cosine ablation."""

    spec = _require_compatible(query, document)
    return normalized_structured_score(
        query, document, SeparableKernel.identity(spec)
    )


def identity_contraction_equivalent(
    query: TensorLike, document: TensorLike, *, tolerance: float = 1e-10
) -> bool:
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise AlgebraError("tolerance must be finite and non-negative")
    return math.isclose(
        identity_contraction(query, document),
        flattened_cosine(query, document),
        rel_tol=tolerance,
        abs_tol=tolerance,
    )


def fiber_maxsim(
    query: TensorLike,
    document: TensorLike,
    kernel: SeparableKernel | None = None,
) -> float:
    """Mean late-interaction MaxSim over non-zero feature fibers.

    Each non-zero query ``[plane, role, :]`` fiber chooses its best non-zero
    document fiber.  With a kernel, pair similarity is weighted by the named
    plane/role entry divided by the same operator-norm bound used by primary
    scoring.  The mean is therefore finite and bounded in ``[-1, 1]``.
    """

    spec = _require_compatible(query, document, kernel)
    query_dense = to_dense(query)
    document_dense = to_dense(document)
    query_fibers: list[tuple[int, int, tuple[float, ...]]] = []
    document_fibers: list[tuple[int, int, tuple[float, ...]]] = []
    for plane in range(len(spec.planes)):
        for role in range(len(spec.roles)):
            query_fiber = query_dense.values[plane][role]
            document_fiber = document_dense.values[plane][role]
            if any(value != 0.0 for value in query_fiber):
                query_fibers.append((plane, role, query_fiber))
            if any(value != 0.0 for value in document_fiber):
                document_fibers.append((plane, role, document_fiber))
    if not query_fibers or not document_fibers:
        return 0.0

    if kernel is None:
        plane_bound = role_bound = 1.0
    else:
        plane_bound = operator_norm_upper_bound(kernel.plane_matrix)
        role_bound = operator_norm_upper_bound(kernel.role_matrix)
        if plane_bound == 0.0 or role_bound == 0.0:
            return 0.0

    maxima: list[float] = []
    for query_plane, query_role, query_fiber in query_fibers:
        candidates: list[float] = []
        for document_plane, document_role, document_fiber in document_fibers:
            similarity = _scaled_cosine(query_fiber, document_fiber)
            if kernel is not None:
                similarity *= (
                    kernel.plane_matrix[query_plane][document_plane]
                    * kernel.role_matrix[query_role][document_role]
                    / (plane_bound * role_bound)
                )
            candidates.append(_finite(similarity, label="fiber MaxSim candidate"))
        maxima.append(max(candidates))
    score = _finite(math.fsum(maxima) / len(maxima), label="fiber MaxSim")
    return max(-1.0, min(1.0, score))


@dataclass(frozen=True)
class PreparedFeatureFiber:
    """One immutable, max-scaled non-zero feature fiber.

    ``scaled_values`` and ``norm`` are exactly the two query-side values that
    :func:`_scaled_cosine` otherwise reconstructs for every query/document
    fiber pair.  Plane and role retain the named-axis coordinates needed by
    the frozen compatibility kernel.
    """

    plane: int
    role: int
    scaled_values: tuple[float, ...]
    norm: float

    def __post_init__(self) -> None:
        if type(self.plane) is not int or self.plane < 0:
            raise AlgebraError("prepared fiber plane must be a non-negative integer")
        if type(self.role) is not int or self.role < 0:
            raise AlgebraError("prepared fiber role must be a non-negative integer")
        values = tuple(self.scaled_values)
        if not values:
            raise AlgebraError("prepared fiber values must not be empty")
        if any(not math.isfinite(value) for value in values):
            raise AlgebraError("prepared fiber contains non-finite values")
        if max(abs(value) for value in values) != 1.0:
            raise AlgebraError("prepared fiber must be max-scaled")
        if not math.isfinite(self.norm) or self.norm <= 0.0:
            raise AlgebraError("prepared fiber norm must be finite and positive")
        if self.norm != math.hypot(*values):
            raise AlgebraError("prepared fiber norm does not match its values")
        object.__setattr__(self, "scaled_values", values)


@dataclass(frozen=True)
class PreparedFiberMaxSimQuery:
    """Query-constant state for exact fiber MaxSim scoring."""

    spec: TensorSpec
    fibers: tuple[PreparedFeatureFiber, ...]
    kernel: SeparableKernel | None
    plane_bound: float
    role_bound: float

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TensorSpec):
            raise AlgebraError("prepared MaxSim spec must be a TensorSpec")
        fibers = tuple(self.fibers)
        coordinates: set[tuple[int, int]] = set()
        for fiber in fibers:
            if not isinstance(fiber, PreparedFeatureFiber):
                raise AlgebraError("prepared MaxSim fibers must be PreparedFeatureFiber")
            if (
                fiber.plane >= len(self.spec.planes)
                or fiber.role >= len(self.spec.roles)
            ):
                raise AlgebraError("prepared MaxSim fiber coordinate is out of range")
            if len(fiber.scaled_values) != self.spec.feature_dimension:
                raise AlgebraError("prepared MaxSim fiber has the wrong feature size")
            coordinate = (fiber.plane, fiber.role)
            if coordinate in coordinates:
                raise AlgebraError("prepared MaxSim fiber coordinates must be unique")
            coordinates.add(coordinate)
        if self.kernel is not None:
            if not isinstance(self.kernel, SeparableKernel):
                raise AlgebraError("prepared MaxSim kernel must be a SeparableKernel")
            if (
                self.kernel.spec != self.spec
                or self.kernel.spec_id != self.spec.spec_id
            ):
                raise AlgebraError("prepared MaxSim kernel TensorSpec does not match")
        for label, value in (
            ("plane bound", self.plane_bound),
            ("role bound", self.role_bound),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise AlgebraError(
                    f"prepared MaxSim {label} must be finite and non-negative"
                )
        object.__setattr__(self, "fibers", fibers)


def _prepare_feature_fibers(tensor: DenseTensor) -> tuple[PreparedFeatureFiber, ...]:
    fibers: list[PreparedFeatureFiber] = []
    for plane in range(len(tensor.spec.planes)):
        for role in range(len(tensor.spec.roles)):
            values = tensor.values[plane][role]
            if not any(value != 0.0 for value in values):
                continue
            scale = max(abs(value) for value in values)
            scaled_values = tuple(value / scale for value in values)
            fibers.append(
                PreparedFeatureFiber(
                    plane=plane,
                    role=role,
                    scaled_values=scaled_values,
                    norm=math.hypot(*scaled_values),
                )
            )
    return tuple(fibers)


def prepare_fiber_maxsim_query(
    query: TensorLike,
    kernel: SeparableKernel | None = None,
) -> PreparedFiberMaxSimQuery:
    """Materialize and normalize every non-zero query fiber exactly once."""

    query = _require_tensor(query, label="query")
    if kernel is not None:
        if not isinstance(kernel, SeparableKernel):
            raise AlgebraError("kernel must be a SeparableKernel")
        if kernel.spec != query.spec or kernel.spec_id != query.spec_id:
            raise AlgebraError("kernel TensorSpec does not match the query")
        plane_bound = operator_norm_upper_bound(kernel.plane_matrix)
        role_bound = operator_norm_upper_bound(kernel.role_matrix)
    else:
        plane_bound = role_bound = 1.0
    return PreparedFiberMaxSimQuery(
        spec=query.spec,
        fibers=_prepare_feature_fibers(to_dense(query)),
        kernel=kernel,
        plane_bound=plane_bound,
        role_bound=role_bound,
    )


def _prepared_fiber_cosine(
    left: PreparedFeatureFiber, right: PreparedFeatureFiber
) -> float:
    numerator = _dot(
        left.scaled_values,
        right.scaled_values,
        label="scaled cosine numerator",
    )
    score = _finite(numerator / (left.norm * right.norm), label="cosine")
    if score > 1.0:
        if score > 1.0 + 1e-12:
            raise AlgebraError("cosine exceeded its mathematical bound")
        return 1.0
    if score < -1.0:
        if score < -1.0 - 1e-12:
            raise AlgebraError("cosine exceeded its mathematical bound")
        return -1.0
    return score


def prepared_fiber_maxsim(
    prepared_query: PreparedFiberMaxSimQuery,
    document: TensorLike,
) -> float:
    """Score one document with query-side work prepared outside the loop.

    The operation order inside each cosine, kernel weight and MaxSim reduction
    is deliberately identical to :func:`fiber_maxsim`.  Document fibers are
    prepared once for this call and are not retained in mutable global state.
    """

    if not isinstance(prepared_query, PreparedFiberMaxSimQuery):
        raise AlgebraError("prepared_query must be a PreparedFiberMaxSimQuery")
    document = _require_tensor(document, label="document")
    if (
        document.spec != prepared_query.spec
        or document.spec_id != prepared_query.spec.spec_id
    ):
        raise AlgebraError("prepared query and document TensorSpecs do not match")

    document_fibers = _prepare_feature_fibers(to_dense(document))
    if not prepared_query.fibers or not document_fibers:
        return 0.0
    if prepared_query.plane_bound == 0.0 or prepared_query.role_bound == 0.0:
        return 0.0

    maxima: list[float] = []
    for query_fiber in prepared_query.fibers:
        candidates: list[float] = []
        for document_fiber in document_fibers:
            similarity = _prepared_fiber_cosine(query_fiber, document_fiber)
            if prepared_query.kernel is not None:
                similarity *= (
                    prepared_query.kernel.plane_matrix[query_fiber.plane][
                        document_fiber.plane
                    ]
                    * prepared_query.kernel.role_matrix[query_fiber.role][
                        document_fiber.role
                    ]
                    / (prepared_query.plane_bound * prepared_query.role_bound)
                )
            candidates.append(_finite(similarity, label="fiber MaxSim candidate"))
        maxima.append(max(candidates))
    score = _finite(math.fsum(maxima) / len(maxima), label="fiber MaxSim")
    return max(-1.0, min(1.0, score))


@dataclass(frozen=True)
class ContractionContribution:
    """One plane-pair/role-pair term in the contraction numerator."""

    query_plane: str
    document_plane: str
    query_role: str
    document_role: str
    feature_dot: float
    plane_weight: float
    role_weight: float
    value: float

    @property
    def contribution(self) -> float:
        return self.value


@dataclass(frozen=True)
class ContractionExplanation:
    """Inspectable additive decomposition of one raw contraction."""

    spec_id: str
    kernel_id: str
    numerator: float
    normalization_bound: float
    score: float
    contributions: tuple[ContractionContribution, ...]

    @property
    def terms(self) -> tuple[ContractionContribution, ...]:
        return self.contributions


def contraction_contributions(
    query: TensorLike,
    document: TensorLike,
    kernel: SeparableKernel,
    *,
    include_zeros: bool = False,
) -> tuple[ContractionContribution, ...]:
    """Return additive terms whose ordered sum is the raw numerator."""

    spec = _require_compatible(query, document, kernel)
    query_dense = to_dense(query)
    document_dense = to_dense(document)
    terms: list[ContractionContribution] = []
    for query_plane, query_plane_name in enumerate(spec.planes):
        for document_plane, document_plane_name in enumerate(spec.planes):
            plane_weight = kernel.plane_matrix[query_plane][document_plane]
            for query_role, query_role_name in enumerate(spec.roles):
                for document_role, document_role_name in enumerate(spec.roles):
                    role_weight = kernel.role_matrix[query_role][document_role]
                    feature_dot = _dot(
                        query_dense.values[query_plane][query_role],
                        document_dense.values[document_plane][document_role],
                        label="contribution feature dot",
                    )
                    value = _finite(
                        feature_dot * plane_weight * role_weight,
                        label="contraction contribution",
                    )
                    if include_zeros or value != 0.0:
                        terms.append(
                            ContractionContribution(
                                query_plane=query_plane_name,
                                document_plane=document_plane_name,
                                query_role=query_role_name,
                                document_role=document_role_name,
                                feature_dot=feature_dot,
                                plane_weight=plane_weight,
                                role_weight=role_weight,
                                value=value,
                            )
                        )
    return tuple(terms)


def explain_contraction(
    query: TensorLike,
    document: TensorLike,
    kernel: SeparableKernel,
    *,
    include_zeros: bool = False,
) -> ContractionExplanation:
    """Explain the raw numerator and its bounded normalized score."""

    spec = _require_compatible(query, document, kernel)
    terms = contraction_contributions(
        query, document, kernel, include_zeros=include_zeros
    )
    # Deliberately use the same ordered built-in sum a caller uses on the
    # returned terms, making the additive invariant exact rather than merely
    # close modulo a different reduction order.
    numerator = sum(term.value for term in terms)
    normalization_bound = (
        frobenius_norm(query)
        * frobenius_norm(document)
        * operator_norm_upper_bound(kernel.plane_matrix)
        * operator_norm_upper_bound(kernel.role_matrix)
    )
    score = normalized_structured_score(query, document, kernel)
    return ContractionExplanation(
        spec_id=spec.spec_id,
        kernel_id=kernel.kernel_id,
        numerator=_finite(numerator, label="explanation numerator"),
        normalization_bound=_finite(normalization_bound, label="explanation bound"),
        score=score,
        contributions=terms,
    )


# Compact names for retriever code; the explicit names above remain the
# normative public API and make measured arms self-describing.
contraction = separable_contraction
cosine = flattened_cosine
maxsim = fiber_maxsim


__all__ = [
    "AlgebraError",
    "cp_to_dense",
    "tt_to_dense",
    "to_dense",
    "flattened_dot",
    "flattened_cosine",
    "frobenius_norm",
    "dense_separable_contraction",
    "cp_separable_contraction",
    "tt_separable_contraction",
    "separable_contraction",
    "operator_norm_upper_bound",
    "normalized_structured_score",
    "PreparedFlattenedBilinearQuery",
    "prepare_flattened_bilinear_query",
    "normalized_prepared_flattened_bilinear_score",
    "normalized_flattened_bilinear_score",
    "structured_score",
    "identity_contraction",
    "identity_contraction_equivalent",
    "fiber_maxsim",
    "PreparedFeatureFiber",
    "PreparedFiberMaxSimQuery",
    "prepare_fiber_maxsim_query",
    "prepared_fiber_maxsim",
    "ContractionContribution",
    "ContractionExplanation",
    "contraction_contributions",
    "explain_contraction",
    "contraction",
    "cosine",
    "maxsim",
]

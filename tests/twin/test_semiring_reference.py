from __future__ import annotations

import itertools

import pytest

from daedalus.twin.semiring import (
    MAX_NATURAL_BITS,
    BooleanSemiring,
    EvidenceDagSemiring,
    EvidenceValue,
    NaturalSemiring,
    TropicalSemiring,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64


@pytest.mark.parametrize(
    ("semiring", "samples"),
    [
        (BooleanSemiring(), (False, True)),
        (NaturalSemiring(), (0, 1, 2, 4)),
        (TropicalSemiring(), (float("inf"), 0.0, 1.0, 3.0)),
    ],
)
def test_scalar_semiring_laws(semiring: object, samples: tuple[object, ...]) -> None:
    add = semiring.add  # type: ignore[attr-defined]
    multiply = semiring.multiply  # type: ignore[attr-defined]
    zero = semiring.zero  # type: ignore[attr-defined]
    one = semiring.one  # type: ignore[attr-defined]

    for value in samples:
        assert add(value, zero) == value
        assert add(zero, value) == value
        assert multiply(value, one) == value
        assert multiply(one, value) == value
        assert multiply(value, zero) == zero
        assert multiply(zero, value) == zero
    for left, middle, right in itertools.product(samples, repeat=3):
        assert add(add(left, middle), right) == add(left, add(middle, right))
        assert multiply(multiply(left, middle), right) == multiply(
            left, multiply(middle, right)
        )
        assert multiply(left, add(middle, right)) == add(
            multiply(left, middle), multiply(left, right)
        )
        assert multiply(add(left, middle), right) == add(
            multiply(left, right), multiply(middle, right)
        )


def test_natural_semiring_refuses_unbounded_operand_and_result_growth() -> None:
    semiring = NaturalSemiring()
    maximum = (1 << MAX_NATURAL_BITS) - 1

    assert semiring.add(maximum - 1, 1) == maximum
    with pytest.raises(ValueError, match="bounded natural bit length"):
        semiring.add(1 << MAX_NATURAL_BITS, 0)
    with pytest.raises(ValueError, match="bounded natural bit length"):
        semiring.add(maximum, 1)
    with pytest.raises(ValueError, match="bounded natural bit length"):
        semiring.multiply(1 << (MAX_NATURAL_BITS // 2), 1 << (MAX_NATURAL_BITS // 2))


def test_evidence_semiring_records_alternatives_and_joint_requirements() -> None:
    semiring = EvidenceDagSemiring()
    a = EvidenceValue.atom(A)
    b = EvidenceValue.atom(B)
    c = EvidenceValue.atom(C)

    assert semiring.multiply(a, b).alternatives == ((A, B),)
    assert semiring.add(semiring.multiply(a, b), c).alternatives == (
        (A, B),
        (C,),
    )
    assert semiring.add(a, semiring.multiply(a, b)) == a
    assert semiring.multiply(a, semiring.one) == a
    assert semiring.multiply(a, semiring.zero) == semiring.zero


def test_evidence_value_is_canonical_across_input_order() -> None:
    first = EvidenceValue(((B, A), (C,), (A, B, C)))
    second = EvidenceValue(((A, B, C), (C,), (A, B)))

    assert first == second
    assert first.alternatives == ((A, B), (C,))
    assert first.to_json() == second.to_json()
    assert first.digest == second.digest


def test_evidence_semiring_satisfies_reference_laws() -> None:
    semiring = EvidenceDagSemiring()
    samples = (
        semiring.zero,
        semiring.one,
        EvidenceValue.atom(A),
        EvidenceValue.atom(B),
        semiring.add(EvidenceValue.atom(A), EvidenceValue.atom(C)),
    )

    for left, middle, right in itertools.product(samples, repeat=3):
        assert semiring.add(semiring.add(left, middle), right) == semiring.add(
            left, semiring.add(middle, right)
        )
        assert semiring.multiply(
            semiring.multiply(left, middle), right
        ) == semiring.multiply(left, semiring.multiply(middle, right))
        assert semiring.multiply(left, semiring.add(middle, right)) == semiring.add(
            semiring.multiply(left, middle),
            semiring.multiply(left, right),
        )


def test_semirings_refuse_implicit_scalar_coercion() -> None:
    with pytest.raises(ValueError, match="boolean"):
        BooleanSemiring().add(True, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative integer"):
        NaturalSemiring().add(1, True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative number"):
        TropicalSemiring().multiply(1.0, -1.0)
    with pytest.raises(ValueError, match="EvidenceValue"):
        EvidenceDagSemiring().add(EvidenceValue.atom(A), True)  # type: ignore[arg-type]


def test_evidence_value_requires_content_digests() -> None:
    with pytest.raises(ValueError, match="sha256"):
        EvidenceValue.atom("not-a-digest")

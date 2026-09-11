from __future__ import annotations

import math

import pytest

import daedalus.twin.relation_blocks as relation_blocks
from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import EvidenceValue

REVISION = "a" * 40
FOURFOLD = "b" * 64


class _ExplodingTruth:
    def __bool__(self) -> bool:
        raise AssertionError("boolean scalar admission must not coerce foreign truthiness")


def _subject() -> ProjectionSubject:
    return ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_fourfold_sha256=FOURFOLD,
    )


def _block(values: object, semiring_name: str) -> TypedRelationBlock[object]:
    count = len(values)  # type: ignore[arg-type]
    return TypedRelationBlock(
        subject=_subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=TypedAxis("rows", "code", ("a",)),
        column_axis=TypedAxis(
            "columns",
            "type",
            tuple(f"T{index}" for index in range(count)),
        ),
        semiring_name=semiring_name,
        row_offsets=(0, count),
        column_indices=tuple(range(count)),
        values=values,  # type: ignore[arg-type]
    )


def test_constructor_owns_one_sequence_admission_and_old_scalar_helper_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not hasattr(relation_blocks, "_stored")
    original = relation_blocks._stored_values
    calls = 0

    def counted(values, semiring_name):
        nonlocal calls
        calls += 1
        return original(values, semiring_name)

    monkeypatch.setattr(relation_blocks, "_stored_values", counted)
    values = (True, True)
    block = _block(values, "boolean")

    assert calls == 1
    assert block.values is values


def test_non_normalizing_admission_materializes_mutable_sequences_once() -> None:
    block = _block([True, True], "boolean")

    assert block.values == (True, True)
    assert type(block.values) is tuple


def test_boolean_admission_rejects_foreign_truthiness_without_coercion() -> None:
    with pytest.raises(ValueError, match="must contain bool values"):
        _block((True, _ExplodingTruth()), "boolean")


@pytest.mark.parametrize(
    ("semiring_name", "values", "message"),
    (
        ("boolean", (True, False, "later-bad"), "semiring zero values"),
        ("boolean", (True, 1), "must contain bool values"),
        ("natural", (1, 0, "later-bad"), "semiring zero values"),
        ("natural", (1, -1), "non-negative integers"),
        (
            "natural",
            (1, 1 << relation_blocks.MAX_NATURAL_BITS),
            "bounded bit length",
        ),
        ("tropical", (1.0, float("inf"), -1.0), "finite and non-negative"),
        ("tropical", (1.0, -1.0), "finite and non-negative"),
        (
            "evidence-dag",
            (EvidenceValue.atom("a" * 64), "later-bad"),
            "require EvidenceValue values",
        ),
    ),
)
def test_sequence_admission_preserves_first_error_contract(
    semiring_name: str,
    values: tuple[object, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _block(values, semiring_name)


def test_tropical_negative_zero_normalization_preserves_canonical_digest() -> None:
    negative = _block((-0.0,), "tropical")
    positive = _block((0.0,), "tropical")

    assert math.copysign(1.0, negative.values[0]) == 1.0
    assert negative.to_json() == positive.to_json()
    assert negative.digest == positive.digest


def test_all_persisted_semiring_families_keep_canonical_values() -> None:
    evidence = EvidenceValue.atom("c" * 64)

    boolean_values = (True,)
    natural_values = (1, 2)
    evidence_values = (evidence,)
    assert _block(boolean_values, "boolean").values is boolean_values
    assert _block(natural_values, "natural").values is natural_values
    assert _block(evidence_values, "evidence-dag").values is evidence_values
    assert _block((1, 2.5), "tropical").values == (1.0, 2.5)


def test_unknown_semiring_still_refuses_before_scalar_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def should_not_run(values, semiring_name):
        nonlocal called
        called = True
        raise AssertionError("scalar admission must not run for an unsupported semiring")

    monkeypatch.setattr(relation_blocks, "_stored_values", should_not_run)
    with pytest.raises(ValueError, match="unsupported persisted semiring"):
        _block((True,), "opaque")

    assert not called

from __future__ import annotations

import pytest

from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import (
    MAX_NATURAL_BITS,
    BooleanSemiring,
    EvidenceDagSemiring,
    EvidenceValue,
    NaturalSemiring,
    TropicalSemiring,
)

REVISION = "a" * 40
FOURFOLD = "b" * 64


def subject() -> ProjectionSubject:
    return ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_fourfold_sha256=FOURFOLD,
    )


def block(semiring: object, value: object) -> TypedRelationBlock[object]:
    return TypedRelationBlock.from_coordinates(
        subject=subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=TypedAxis("code", "code", ("src/a.py",)),
        column_axis=TypedAxis("type", "type", ("Widget",)),
        coordinates=(("src/a.py", "Widget", value),),
        semiring=semiring,
    )


@pytest.mark.parametrize(
    ("semiring", "value"),
    (
        (BooleanSemiring(), True),
        (NaturalSemiring(), 7),
        (TropicalSemiring(), 1.25),
        (EvidenceDagSemiring(), EvidenceValue.atom("c" * 64)),
    ),
)
def test_relation_block_canonical_wire_round_trip(semiring: object, value: object) -> None:
    original = block(semiring, value)

    decoded = TypedRelationBlock.from_dict(original.to_dict())

    assert decoded == original
    assert decoded.to_dict() == original.to_dict()
    assert decoded.digest == original.digest


def test_round_trip_reenters_semiring_and_scalar_bounds() -> None:
    payload = block(NaturalSemiring(), 1).to_dict()
    payload["values"][0] = 1 << MAX_NATURAL_BITS

    with pytest.raises(ValueError, match="bounded bit length"):
        TypedRelationBlock.from_dict(payload)

    payload = block(BooleanSemiring(), True).to_dict()
    payload["semiring_name"] = "opaque-integer"
    with pytest.raises(ValueError, match="unsupported persisted semiring"):
        TypedRelationBlock.from_dict(payload)


def test_round_trip_rejects_nested_shape_and_evidence_wire_drift() -> None:
    payload = block(BooleanSemiring(), True).to_dict()
    payload["subject"]["pretend_authoritative"] = True
    with pytest.raises(ValueError, match="projection subject contains unknown field"):
        TypedRelationBlock.from_dict(payload)

    payload = block(EvidenceDagSemiring(), EvidenceValue.atom("d" * 64)).to_dict()
    payload["values"][0]["scalar_type"] = "opaque"
    with pytest.raises(ValueError, match="evidence-dag wire values"):
        TypedRelationBlock.from_dict(payload)

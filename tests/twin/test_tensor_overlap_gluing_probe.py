"""Transient G1-TENSOR-01AH counterexample for overlap/gluing semantics.

This probe asks whether the existing typed relation algebra already supplies a
sheaf-like consistency check for independently valid local projections.  It is
research evidence only; it must not become a second semantic authority.
"""

import pytest

from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring


REVISION = "a" * 40
FOURFOLD_SHA256 = "b" * 64


def _subject() -> ProjectionSubject:
    return ProjectionSubject("repo", REVISION, FOURFOLD_SHA256)


def _signature() -> RelationSignature:
    return RelationSignature("code", "observes", "type")


def test_overlapping_local_blocks_can_disagree_while_each_remains_valid() -> None:
    """Exact subject/signature binding does not imply overlap agreement."""

    semiring = BooleanSemiring()
    left = TypedRelationBlock.from_coordinates(
        subject=_subject(),
        signature=_signature(),
        row_axis=TypedAxis("left-code", "code", ("left", "shared")),
        column_axis=TypedAxis("left-type", "type", ("left-type", "shared-type")),
        coordinates=(("shared", "shared-type", True),),
        semiring=semiring,
    )
    right = TypedRelationBlock.from_coordinates(
        subject=_subject(),
        signature=_signature(),
        row_axis=TypedAxis("right-code", "code", ("right", "shared")),
        column_axis=TypedAxis("right-type", "type", ("right-type", "shared-type")),
        coordinates=(),
        semiring=semiring,
    )

    assert left.subject == right.subject
    assert left.signature == right.signature
    assert left.get("shared", "shared-type", semiring) is True
    assert right.get("shared", "shared-type", semiring) is False

    # Hadamard is intentionally stricter than a local-chart overlap check: it
    # requires globally identical axes, so it cannot decide this gluing case.
    with pytest.raises(ValueError, match="identical typed axes"):
        left.hadamard(right, semiring, relation="overlap")


def test_boolean_meet_on_manual_restrictions_is_not_a_consistency_verdict() -> None:
    """Even after manual restriction, semiring meet erases the disagreement."""

    semiring = BooleanSemiring()
    row_axis = TypedAxis("shared-code", "code", ("shared",))
    column_axis = TypedAxis("shared-type", "type", ("shared-type",))
    left = TypedRelationBlock.from_coordinates(
        subject=_subject(),
        signature=_signature(),
        row_axis=row_axis,
        column_axis=column_axis,
        coordinates=(("shared", "shared-type", True),),
        semiring=semiring,
    )
    right = TypedRelationBlock.from_coordinates(
        subject=_subject(),
        signature=_signature(),
        row_axis=row_axis,
        column_axis=column_axis,
        coordinates=(),
        semiring=semiring,
    )

    meet = left.hadamard(right, semiring, relation="overlap-meet")
    assert meet.entry_count == 0
    assert meet.get("shared", "shared-type", semiring) is False
    assert left.get("shared", "shared-type", semiring) is not right.get(
        "shared", "shared-type", semiring
    )

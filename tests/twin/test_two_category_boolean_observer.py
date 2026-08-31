from __future__ import annotations

import pytest

from daedalus.twin.contractions import boolean_square_commutes
from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring, NaturalSemiring
from daedalus.twin.two_category import (
    BoundaryMap,
    BoundaryPort,
    OpenFourfoldComponent,
    Transformation2Cell,
    TypedBoundary,
    VerificationStatus,
)

REPOSITORY = "KTY137/daedalus"
R0 = "0" * 40
R1 = "1" * 40
F0 = "a" * 64
F1 = "b" * 64


def subject(revision: str, fourfold: str) -> ProjectionSubject:
    return ProjectionSubject(
        repository_id=REPOSITORY,
        source_revision=revision,
        source_fourfold_sha256=fourfold,
    )


def block(
    *,
    revision: str,
    fourfold: str,
    relation: str,
    row_axis: TypedAxis,
    column_axis: TypedAxis,
    coordinates: tuple[tuple[object, object, object], ...],
    semiring: object,
) -> TypedRelationBlock[object]:
    return TypedRelationBlock.from_coordinates(
        subject=subject(revision, fourfold),
        signature=RelationSignature(
            row_axis.plane,
            relation,
            column_axis.plane,
        ),
        row_axis=row_axis,
        column_axis=column_axis,
        coordinates=coordinates,
        semiring=semiring,  # type: ignore[arg-type]
    )


def boundary(axis: TypedAxis) -> TypedBoundary:
    return TypedBoundary(
        tuple(
            BoundaryPort(label, axis.plane, f"{axis.name}:{label}")
            for label in axis.labels
        )
    )


def square(
    source_block: TypedRelationBlock[object],
    target_block: TypedRelationBlock[object],
    *,
    left_assignments: tuple[tuple[str, str], ...],
    right_assignments: tuple[tuple[str, str], ...],
    source_left: TypedBoundary | None = None,
) -> Transformation2Cell:
    source_left_boundary = source_left or boundary(source_block.row_axis)
    source_right_boundary = boundary(source_block.column_axis)
    target_left_boundary = boundary(target_block.row_axis)
    target_right_boundary = boundary(target_block.column_axis)
    source_component = OpenFourfoldComponent.atomic(
        repository_id=REPOSITORY,
        source_revision=source_block.subject.source_revision,
        left=source_left_boundary,
        right=source_right_boundary,
        component_sha256=source_block.digest,
    )
    target_component = OpenFourfoldComponent.atomic(
        repository_id=REPOSITORY,
        source_revision=target_block.subject.source_revision,
        left=target_left_boundary,
        right=target_right_boundary,
        component_sha256=target_block.digest,
    )
    return Transformation2Cell(
        source=source_component,
        target=target_component,
        left_map=BoundaryMap(
            source_left_boundary,
            target_left_boundary,
            left_assignments,
        ),
        right_map=BoundaryMap(
            source_right_boundary,
            target_right_boundary,
            right_assignments,
        ),
        status=VerificationStatus.PROPOSED,
    )


def commuting_fixture() -> tuple[
    TypedRelationBlock[bool],
    TypedRelationBlock[bool],
    Transformation2Cell,
]:
    semiring = BooleanSemiring()
    old_code = TypedAxis("old-code", "code", ("api", "worker"))
    old_data = TypedAxis("old-data", "data", ("state", "voltage"))
    new_code = TypedAxis("new-code", "code", ("api2", "worker2"))
    new_data = TypedAxis("new-data", "data", ("bias", "state2"))
    source_block = block(
        revision=R0,
        fourfold=F0,
        relation="writes",
        row_axis=old_code,
        column_axis=old_data,
        coordinates=(("api", "voltage", True), ("worker", "state", True)),
        semiring=semiring,
    )
    target_block = block(
        revision=R1,
        fourfold=F1,
        relation="writes",
        row_axis=new_code,
        column_axis=new_data,
        coordinates=(("api2", "bias", True), ("worker2", "state2", True)),
        semiring=semiring,
    )
    cell = square(
        source_block,
        target_block,
        left_assignments=(("api", "api2"), ("worker", "worker2")),
        right_assignments=(("state", "state2"), ("voltage", "bias")),
    )
    return source_block, target_block, cell  # type: ignore[return-value]


def test_boolean_observer_accepts_a_commuting_cross_revision_square() -> None:
    source_block, target_block, cell = commuting_fixture()

    assert boolean_square_commutes(cell, source_block, target_block) is True
    assert cell.status is VerificationStatus.PROPOSED
    assert cell.observer_receipts == ()


def test_boolean_observer_detects_a_partial_migration() -> None:
    source_block, _, cell = commuting_fixture()
    semiring = BooleanSemiring()
    target_block = block(
        revision=R1,
        fourfold=F1,
        relation="writes",
        row_axis=TypedAxis("new-code", "code", ("api2", "worker2")),
        column_axis=TypedAxis("new-data", "data", ("bias", "state2")),
        coordinates=(("api2", "bias", True),),
        semiring=semiring,
    )
    noncommuting = square(
        source_block,
        target_block,
        left_assignments=(("api", "api2"), ("worker", "worker2")),
        right_assignments=(("state", "state2"), ("voltage", "bias")),
    )

    assert boolean_square_commutes(noncommuting, source_block, target_block) is False


def test_boolean_observer_refuses_an_unbound_block() -> None:
    source_block, target_block, cell = commuting_fixture()
    semiring = BooleanSemiring()
    unbound = block(
        revision=R0,
        fourfold=F0,
        relation="reads",
        row_axis=source_block.row_axis,
        column_axis=source_block.column_axis,
        coordinates=(("api", "voltage", True), ("worker", "state", True)),
        semiring=semiring,
    )

    with pytest.raises(ValueError, match="bind exactly"):
        boolean_square_commutes(cell, unbound, target_block)  # type: ignore[arg-type]


def test_boolean_observer_refuses_revision_drift_before_digest_binding() -> None:
    source_block, target_block, cell = commuting_fixture()
    semiring = BooleanSemiring()
    wrong_revision = block(
        revision="2" * 40,
        fourfold=F0,
        relation="writes",
        row_axis=source_block.row_axis,
        column_axis=source_block.column_axis,
        coordinates=(("api", "voltage", True), ("worker", "state", True)),
        semiring=semiring,
    )

    with pytest.raises(ValueError, match="revision does not match"):
        boolean_square_commutes(cell, wrong_revision, target_block)  # type: ignore[arg-type]


def test_boolean_observer_refuses_non_boolean_realizations() -> None:
    semiring = NaturalSemiring()
    old_code = TypedAxis("old-code", "code", ("api",))
    old_data = TypedAxis("old-data", "data", ("value",))
    new_code = TypedAxis("new-code", "code", ("api2",))
    new_data = TypedAxis("new-data", "data", ("value2",))
    source_block = block(
        revision=R0,
        fourfold=F0,
        relation="writes",
        row_axis=old_code,
        column_axis=old_data,
        coordinates=(("api", "value", 1),),
        semiring=semiring,
    )
    target_block = block(
        revision=R1,
        fourfold=F1,
        relation="writes",
        row_axis=new_code,
        column_axis=new_data,
        coordinates=(("api2", "value2", 1),),
        semiring=semiring,
    )
    cell = square(
        source_block,
        target_block,
        left_assignments=(("api", "api2"),),
        right_assignments=(("value", "value2"),),
    )

    with pytest.raises(ValueError, match="requires boolean"):
        boolean_square_commutes(cell, source_block, target_block)  # type: ignore[arg-type]


def test_boolean_observer_refuses_boundary_axis_drift() -> None:
    source_block, target_block, _ = commuting_fixture()
    bad_left = TypedBoundary(
        (
            BoundaryPort("other", "code", "old-code:other"),
            BoundaryPort("worker", "code", "old-code:worker"),
        )
    )
    cell = square(
        source_block,
        target_block,
        source_left=bad_left,
        left_assignments=(("other", "api2"), ("worker", "worker2")),
        right_assignments=(("state", "state2"), ("voltage", "bias")),
    )

    with pytest.raises(ValueError, match="boundary ports must match"):
        boolean_square_commutes(cell, source_block, target_block)


def test_boolean_observer_enforces_a_bounded_operation_budget() -> None:
    source_block, target_block, cell = commuting_fixture()

    with pytest.raises(ValueError, match="bounded operation limit"):
        boolean_square_commutes(
            cell,
            source_block,
            target_block,
            max_operations=0,
        )

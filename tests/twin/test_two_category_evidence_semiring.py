from __future__ import annotations

import pytest

from daedalus.twin.semiring import EvidenceDagSemiring, verified_cell_evidence
from daedalus.twin.two_category import (
    BoundaryMap,
    BoundaryPort,
    OpenFourfoldComponent,
    Transformation2Cell,
    TypedBoundary,
    VerificationStatus,
)

REPOSITORY_ID = "KTY137/daedalus"
REVISION_0 = "0" * 40
REVISION_1 = "1" * 40
REVISION_2 = "2" * 40


def _digest(value: int) -> str:
    return f"{value:064x}"


def _boundary() -> TypedBoundary:
    return TypedBoundary(
        (
            BoundaryPort("request", "type", "Request -> Response"),
            BoundaryPort("docs", "knowledge", "documents Request -> Response"),
        )
    )


def _component(revision: str, component_digest: str) -> OpenFourfoldComponent:
    boundary = _boundary()
    return OpenFourfoldComponent.atomic(
        repository_id=REPOSITORY_ID,
        source_revision=revision,
        left=boundary,
        right=boundary,
        component_sha256=component_digest,
    )


def _cell(
    source: OpenFourfoldComponent,
    target: OpenFourfoldComponent,
    *,
    rewrite: str,
    observer: str,
    status: VerificationStatus = VerificationStatus.EVALUATOR_VERIFIED,
) -> Transformation2Cell:
    boundary = _boundary()
    return Transformation2Cell(
        source=source,
        target=target,
        left_map=BoundaryMap.identity(boundary),
        right_map=BoundaryMap.identity(boundary),
        rewrite_sha256s=(rewrite,),
        observer_receipts=(observer,),
        status=status,
    )


def test_verified_cell_evidence_is_one_conjunctive_path() -> None:
    source = _component(REVISION_0, _digest(1))
    target = _component(REVISION_1, _digest(2))
    cell = _cell(source, target, rewrite=_digest(10), observer=_digest(11))

    value = verified_cell_evidence(cell)

    assert value.alternatives == ((_digest(10), _digest(11)),)


def test_verified_cell_evidence_refuses_unverified_status() -> None:
    source = _component(REVISION_0, _digest(1))
    target = _component(REVISION_1, _digest(2))
    cell = _cell(
        source,
        target,
        rewrite=_digest(10),
        observer=_digest(11),
        status=VerificationStatus.STRUCTURALLY_CHECKED,
    )

    with pytest.raises(ValueError, match="only evaluator_verified"):
        verified_cell_evidence(cell)


def test_verified_identity_maps_to_semiring_one() -> None:
    component = _component(REVISION_0, _digest(1))

    assert verified_cell_evidence(Transformation2Cell.identity(component)) == (
        EvidenceDagSemiring.one
    )


def test_vertical_composition_is_evidence_multiplication() -> None:
    first_component = _component(REVISION_0, _digest(1))
    middle_component = _component(REVISION_1, _digest(2))
    final_component = _component(REVISION_2, _digest(3))
    first = _cell(
        first_component,
        middle_component,
        rewrite=_digest(10),
        observer=_digest(11),
    )
    second = _cell(
        middle_component,
        final_component,
        rewrite=_digest(12),
        observer=_digest(13),
    )
    semiring = EvidenceDagSemiring()

    composite = first.then(second)

    assert verified_cell_evidence(composite) == semiring.multiply(
        verified_cell_evidence(first),
        verified_cell_evidence(second),
    )
    assert verified_cell_evidence(composite).alternatives == (
        (_digest(10), _digest(11), _digest(12), _digest(13)),
    )


def test_same_endpoints_can_retain_two_independent_verified_evidence_paths() -> None:
    source = _component(REVISION_0, _digest(1))
    final = _component(REVISION_2, _digest(4))
    middle_a = _component(REVISION_1, _digest(2))
    middle_b = _component(REVISION_1, _digest(3))

    path_a = _cell(
        source,
        middle_a,
        rewrite=_digest(10),
        observer=_digest(11),
    ).then(
        _cell(
            middle_a,
            final,
            rewrite=_digest(12),
            observer=_digest(13),
        )
    )
    path_b = _cell(
        source,
        middle_b,
        rewrite=_digest(20),
        observer=_digest(21),
    ).then(
        _cell(
            middle_b,
            final,
            rewrite=_digest(22),
            observer=_digest(23),
        )
    )

    assert path_a.source == path_b.source
    assert path_a.target == path_b.target
    assert path_a.digest != path_b.digest

    alternatives = EvidenceDagSemiring().add(
        verified_cell_evidence(path_a),
        verified_cell_evidence(path_b),
    )

    assert alternatives.alternatives == (
        (_digest(10), _digest(11), _digest(12), _digest(13)),
        (_digest(20), _digest(21), _digest(22), _digest(23)),
    )


def test_interchange_style_reordering_does_not_invent_evidence_order() -> None:
    semiring = EvidenceDagSemiring()
    left = semiring.multiply(
        verified_cell_evidence(
            _cell(
                _component(REVISION_0, _digest(1)),
                _component(REVISION_1, _digest(2)),
                rewrite=_digest(10),
                observer=_digest(11),
            )
        ),
        verified_cell_evidence(
            _cell(
                _component(REVISION_1, _digest(2)),
                _component(REVISION_2, _digest(3)),
                rewrite=_digest(12),
                observer=_digest(13),
            )
        ),
    )
    right = semiring.multiply(
        verified_cell_evidence(
            _cell(
                _component(REVISION_1, _digest(2)),
                _component(REVISION_2, _digest(3)),
                rewrite=_digest(12),
                observer=_digest(13),
            )
        ),
        verified_cell_evidence(
            _cell(
                _component(REVISION_0, _digest(1)),
                _component(REVISION_1, _digest(2)),
                rewrite=_digest(10),
                observer=_digest(11),
            )
        ),
    )

    assert left == right

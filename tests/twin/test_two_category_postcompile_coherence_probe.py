"""Transient G1-TENSOR-01AE probe for post-compile coherence authority.

This diagnostic asks whether two individually valid revision chains with the
same semantic endpoints are already collapsed by the minimal 2-cell contract.
They must not be: declaring two distinct paths coherent needs independent
observer/evaluator evidence and must not be inferred from matching endpoints.
"""
from __future__ import annotations

import pytest

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
R2 = "2" * 40


def _digest(symbol: str) -> str:
    return symbol * 64


def _boundary(label: str, revision_tag: str) -> TypedBoundary:
    return TypedBoundary(
        (
            BoundaryPort(f"{label}-code", "code", f"{label}.callable.{revision_tag}"),
            BoundaryPort(f"{label}-data", "data", f"{label}.schema.{revision_tag}"),
        )
    )


def _map(source: TypedBoundary, target: TypedBoundary) -> BoundaryMap:
    return BoundaryMap(
        source,
        target,
        tuple(
            (left.port_id, right.port_id)
            for left, right in zip(source.ports, target.ports)
        ),
    )


def _component(
    left: TypedBoundary,
    right: TypedBoundary,
    revision: str,
    symbol: str,
) -> OpenFourfoldComponent:
    return OpenFourfoldComponent.atomic(
        repository_id=REPOSITORY,
        source_revision=revision,
        left=left,
        right=right,
        component_sha256=_digest(symbol),
    )


def _cell(
    source: OpenFourfoldComponent,
    target: OpenFourfoldComponent,
    left_map: BoundaryMap,
    right_map: BoundaryMap,
    rewrite: str,
    receipt: str,
) -> Transformation2Cell:
    return Transformation2Cell(
        source=source,
        target=target,
        left_map=left_map,
        right_map=right_map,
        rewrite_sha256s=(_digest(rewrite),),
        observer_receipts=(_digest(receipt),),
        preserved_invariants=("shape", "typed-boundary"),
        status=VerificationStatus.EVALUATOR_VERIFIED,
    )


def test_distinct_valid_revision_paths_remain_distinct_without_coherence_evidence() -> None:
    i0, j0 = _boundary("i", "r0"), _boundary("j", "r0")
    i1, j1 = _boundary("i", "r1"), _boundary("j", "r1")
    i2, j2 = _boundary("i", "r2"), _boundary("j", "r2")

    base = _component(i0, j0, R0, "a")
    middle_left = _component(i1, j1, R1, "b")
    middle_right = _component(i1, j1, R1, "c")
    target = _component(i2, j2, R2, "d")

    left_01, right_01 = _map(i0, i1), _map(j0, j1)
    left_12, right_12 = _map(i1, i2), _map(j1, j2)

    left_first = _cell(base, middle_left, left_01, right_01, "1", "5")
    left_second = _cell(middle_left, target, left_12, right_12, "2", "6")
    right_first = _cell(base, middle_right, left_01, right_01, "3", "7")
    right_second = _cell(middle_right, target, left_12, right_12, "4", "8")

    left_path = left_first.then(left_second)
    right_path = right_first.then(right_second)

    # Direct endpoint checks alone cannot establish path coherence. Both paths
    # are individually valid and have the same external revision/boundary view,
    # but their retained rewrite and observer evidence keeps them distinct.
    assert left_path.source == right_path.source == base
    assert left_path.target == right_path.target == target
    assert left_path.left_map == right_path.left_map
    assert left_path.right_map == right_path.right_map
    assert left_path.status is right_path.status is VerificationStatus.EVALUATOR_VERIFIED
    assert left_path.preserved_invariants == right_path.preserved_invariants
    assert left_path != right_path
    assert left_path.digest != right_path.digest
    assert set(left_path.rewrite_sha256s).isdisjoint(right_path.rewrite_sha256s)
    assert set(left_path.observer_receipts).isdisjoint(right_path.observer_receipts)

    # Equal revision and equal typed boundaries do not license splicing the two
    # causal histories. Exact middle-component identity is still required.
    with pytest.raises(ValueError, match="exact middle component"):
        left_first.then(right_second)
    with pytest.raises(ValueError, match="exact middle component"):
        right_first.then(left_second)

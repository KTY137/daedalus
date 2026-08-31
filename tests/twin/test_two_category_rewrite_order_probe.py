"""Diagnostic-only probe for the rewrite-order boundary of Transformation2Cell.

This intentionally records a negative result rather than proposing a new
contract: current 2-cells retain rewrite digests as an unordered idempotent
reference set.  A naive replacement with one flat ordered sequence would retain
more history, but it would also make the existing strict interchange law depend
on whether independent squares were composed horizontally or vertically first.
"""
from __future__ import annotations

from daedalus.twin.two_category import (
    BoundaryMap,
    BoundaryPort,
    OpenFourfoldComponent,
    Transformation2Cell,
    TypedBoundary,
)

REPOSITORY = "KTY137/daedalus"
R0 = "0" * 40
R1 = "1" * 40
R2 = "2" * 40


def digest(symbol: str) -> str:
    return symbol * 64


def boundary(label: str) -> TypedBoundary:
    return TypedBoundary((BoundaryPort(label, "code", f"contract:{label}"),))


def boundary_map(source: TypedBoundary, target: TypedBoundary) -> BoundaryMap:
    return BoundaryMap(source, target, ((source.ports[0].port_id, target.ports[0].port_id),))


def component(
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
        component_sha256=digest(symbol),
    )


def cell(
    source: OpenFourfoldComponent,
    target: OpenFourfoldComponent,
    left_map: BoundaryMap,
    right_map: BoundaryMap,
    rewrite: tuple[str, ...],
) -> Transformation2Cell:
    return Transformation2Cell(
        source=source,
        target=target,
        left_map=left_map,
        right_map=right_map,
        rewrite_sha256s=rewrite,
    )


def test_current_cell_quotients_rewrite_permutation() -> None:
    left0, right0 = boundary("left0"), boundary("right0")
    left1, right1 = boundary("left1"), boundary("right1")
    source = component(left0, right0, R0, "a")
    target = component(left1, right1, R1, "b")
    left = boundary_map(left0, left1)
    right = boundary_map(right0, right1)
    first = cell(source, target, left, right, (digest("c"), digest("d")))
    reversed_order = cell(source, target, left, right, (digest("d"), digest("c")))

    assert first.rewrite_sha256s == reversed_order.rewrite_sha256s
    assert first.digest == reversed_order.digest


def test_current_composition_quotients_repeated_rewrite_reference() -> None:
    left0, right0 = boundary("left0"), boundary("right0")
    left1, right1 = boundary("left1"), boundary("right1")
    left2, right2 = boundary("left2"), boundary("right2")
    first_component = component(left0, right0, R0, "a")
    middle_component = component(left1, right1, R1, "b")
    last_component = component(left2, right2, R2, "c")
    repeated = digest("d")
    first = cell(
        first_component,
        middle_component,
        boundary_map(left0, left1),
        boundary_map(right0, right1),
        (repeated,),
    )
    second = cell(
        middle_component,
        last_component,
        boundary_map(left1, left2),
        boundary_map(right1, right2),
        (repeated,),
    )

    assert first.then(second).rewrite_sha256s == (repeated,)


def test_naive_flat_order_would_break_strict_interchange() -> None:
    i0, j0, k0 = boundary("i0"), boundary("j0"), boundary("k0")
    i1, j1, k1 = boundary("i1"), boundary("j1"), boundary("k1")
    i2, j2, k2 = boundary("i2"), boundary("j2"), boundary("k2")
    ui01, uj01, uk01 = boundary_map(i0, i1), boundary_map(j0, j1), boundary_map(k0, k1)
    ui12, uj12, uk12 = boundary_map(i1, i2), boundary_map(j1, j2), boundary_map(k1, k2)
    f0, f1, f2 = (
        component(i0, j0, R0, "a"),
        component(i1, j1, R1, "b"),
        component(i2, j2, R2, "c"),
    )
    g0, g1, g2 = (
        component(j0, k0, R0, "d"),
        component(j1, k1, R1, "e"),
        component(j2, k2, R2, "f"),
    )
    r_alpha, r_beta, r_gamma, r_delta = map(digest, ("1", "2", "3", "4"))
    alpha = cell(f0, f1, ui01, uj01, (r_alpha,))
    beta = cell(g0, g1, uj01, uk01, (r_beta,))
    gamma = cell(f1, f2, ui12, uj12, (r_gamma,))
    delta = cell(g1, g2, uj12, uk12, (r_delta,))

    horizontal_then_vertical = alpha.beside(beta).then(gamma.beside(delta))
    vertical_then_horizontal = alpha.then(gamma).beside(beta.then(delta))

    # The current quotient preserves the strict double-category interchange law.
    assert horizontal_then_vertical == vertical_then_horizontal
    # A single flat trace would distinguish the two legal parenthesizations:
    # (alpha beside beta) then (gamma beside delta) versus
    # (alpha then gamma) beside (beta then delta).
    naive_horizontal_then_vertical = (r_alpha, r_beta, r_gamma, r_delta)
    naive_vertical_then_horizontal = (r_alpha, r_gamma, r_beta, r_delta)
    assert naive_horizontal_then_vertical != naive_vertical_then_horizontal

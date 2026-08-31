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


def digest(symbol: str) -> str:
    return symbol * 64


def boundary(label: str, *, contract_suffix: str = "") -> TypedBoundary:
    return TypedBoundary(
        (
            BoundaryPort(
                f"{label}-code",
                "code",
                f"{label}.callable{contract_suffix}",
            ),
            BoundaryPort(
                f"{label}-data",
                "data",
                f"{label}.schema{contract_suffix}",
            ),
        )
    )


def boundary_map(source: TypedBoundary, target: TypedBoundary) -> BoundaryMap:
    return BoundaryMap(
        source,
        target,
        tuple(
            (source_port.port_id, target_port.port_id)
            for source_port, target_port in zip(source.ports, target.ports)
        ),
    )


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
    left: BoundaryMap,
    right: BoundaryMap,
    symbol: str,
    *,
    status: VerificationStatus = VerificationStatus.EVALUATOR_VERIFIED,
) -> Transformation2Cell:
    return Transformation2Cell(
        source=source,
        target=target,
        left_map=left,
        right_map=right,
        rewrite_sha256s=(digest(symbol),),
        observer_receipts=(digest("f"),),
        preserved_invariants=("shape",),
        status=status,
    )


def test_boundary_and_map_input_order_is_canonical() -> None:
    code = BoundaryPort("code", "code", "callable")
    data = BoundaryPort("data", "data", "schema")
    first = TypedBoundary((data, code))
    second = TypedBoundary((code, data))

    assert first == second
    assert first.digest == second.digest

    target = TypedBoundary(
        (
            BoundaryPort("new-data", "data", "new-schema"),
            BoundaryPort("new-code", "code", "new-callable"),
        )
    )
    first_map = BoundaryMap(
        first,
        target,
        (("data", "new-data"), ("code", "new-code")),
    )
    second_map = BoundaryMap(
        first,
        target,
        (("code", "new-code"), ("data", "new-data")),
    )

    assert first_map == second_map
    assert first_map.digest == second_map.digest


def test_boundary_maps_are_total_and_plane_preserving() -> None:
    source = boundary("old")
    target = boundary("new", contract_suffix="-v2")

    with pytest.raises(ValueError, match="must be total"):
        BoundaryMap(
            source,
            target,
            (("old-code", "new-code"),),
        )
    with pytest.raises(ValueError, match="preserve Fourfold planes"):
        BoundaryMap(
            source,
            target,
            (("old-code", "new-data"), ("old-data", "new-code")),
        )


def test_boundary_map_identity_and_associativity() -> None:
    first = boundary("first")
    second = boundary("second", contract_suffix="-v2")
    third = boundary("third", contract_suffix="-v3")
    fourth = boundary("fourth", contract_suffix="-v4")
    f = boundary_map(first, second)
    g = boundary_map(second, third)
    h = boundary_map(third, fourth)

    assert BoundaryMap.identity(first).then(f) == f
    assert f.then(BoundaryMap.identity(second)) == f
    assert f.then(g).then(h) == f.then(g.then(h))


def test_open_components_have_strict_horizontal_identity_and_associativity() -> None:
    i = boundary("i")
    j = boundary("j")
    k = boundary("k")
    l = boundary("l")
    f = component(i, j, R0, "a")
    g = component(j, k, R0, "b")
    h = component(k, l, R0, "c")
    left_identity = OpenFourfoldComponent.identity(
        i,
        repository_id=REPOSITORY,
        source_revision=R0,
    )
    right_identity = OpenFourfoldComponent.identity(
        j,
        repository_id=REPOSITORY,
        source_revision=R0,
    )

    assert left_identity.then(f) == f
    assert f.then(right_identity) == f
    assert f.then(g).then(h) == f.then(g.then(h))
    assert f.then(g).component_sha256s == (digest("a"), digest("b"))


def test_components_cannot_compose_across_revision_or_boundary() -> None:
    i = boundary("i")
    j = boundary("j")
    k = boundary("k")
    f = component(i, j, R0, "a")

    with pytest.raises(ValueError, match="cannot cross source revisions"):
        f.then(component(j, k, R1, "b"))
    with pytest.raises(ValueError, match="shared boundary"):
        f.then(component(k, i, R0, "c"))


def test_two_cell_binds_both_component_boundaries() -> None:
    old_i = boundary("old-i")
    old_j = boundary("old-j")
    new_i = boundary("new-i", contract_suffix="-v2")
    new_j = boundary("new-j", contract_suffix="-v2")
    source = component(old_i, old_j, R0, "a")
    target = component(new_i, new_j, R1, "b")

    with pytest.raises(ValueError, match="left boundary map"):
        Transformation2Cell(
            source=source,
            target=target,
            left_map=boundary_map(old_j, new_j),
            right_map=boundary_map(old_j, new_j),
        )


def test_vertical_two_cell_composition_is_conservative_and_associative() -> None:
    i0, j0 = boundary("i0"), boundary("j0")
    i1, j1 = boundary("i1", contract_suffix="-v1"), boundary(
        "j1", contract_suffix="-v1"
    )
    i2, j2 = boundary("i2", contract_suffix="-v2"), boundary(
        "j2", contract_suffix="-v2"
    )
    i3, j3 = boundary("i3", contract_suffix="-v3"), boundary(
        "j3", contract_suffix="-v3"
    )
    f0 = component(i0, j0, R0, "a")
    f1 = component(i1, j1, R1, "b")
    f2 = component(i2, j2, R2, "c")
    f3 = component(i3, j3, "3" * 40, "d")
    a = cell(
        f0,
        f1,
        boundary_map(i0, i1),
        boundary_map(j0, j1),
        "e",
    )
    b = cell(
        f1,
        f2,
        boundary_map(i1, i2),
        boundary_map(j1, j2),
        "f",
        status=VerificationStatus.PROPOSED,
    )
    c = cell(
        f2,
        f3,
        boundary_map(i2, i3),
        boundary_map(j2, j3),
        "9",
        status=VerificationStatus.STRUCTURALLY_CHECKED,
    )

    composite = a.then(b)

    assert composite.source == f0
    assert composite.target == f2
    assert composite.status is VerificationStatus.PROPOSED
    assert set(composite.rewrite_sha256s) == {digest("e"), digest("f")}
    assert a.then(b).then(c) == a.then(b.then(c))
    assert Transformation2Cell.identity(f0).then(a) == a
    assert a.then(Transformation2Cell.identity(f1)) == a


def test_horizontal_two_cell_identity_and_associativity() -> None:
    i0, j0, k0, l0 = (
        boundary("i0"),
        boundary("j0"),
        boundary("k0"),
        boundary("l0"),
    )
    i1, j1, k1, l1 = (
        boundary("i1", contract_suffix="-v1"),
        boundary("j1", contract_suffix="-v1"),
        boundary("k1", contract_suffix="-v1"),
        boundary("l1", contract_suffix="-v1"),
    )
    u_i, u_j, u_k, u_l = (
        boundary_map(i0, i1),
        boundary_map(j0, j1),
        boundary_map(k0, k1),
        boundary_map(l0, l1),
    )
    f0, f1 = component(i0, j0, R0, "a"), component(i1, j1, R1, "b")
    g0, g1 = component(j0, k0, R0, "c"), component(j1, k1, R1, "d")
    h0, h1 = component(k0, l0, R0, "e"), component(k1, l1, R1, "f")
    alpha = cell(f0, f1, u_i, u_j, "1")
    beta = cell(g0, g1, u_j, u_k, "2")
    gamma = cell(h0, h1, u_k, u_l, "3")
    left_unit = Transformation2Cell.horizontal_identity(
        u_i,
        repository_id=REPOSITORY,
        source_revision=R0,
        target_revision=R1,
    )
    right_unit = Transformation2Cell.horizontal_identity(
        u_j,
        repository_id=REPOSITORY,
        source_revision=R0,
        target_revision=R1,
    )

    assert left_unit.beside(alpha) == alpha
    assert alpha.beside(right_unit) == alpha
    assert alpha.beside(beta).beside(gamma) == alpha.beside(beta.beside(gamma))


def test_interchange_law_holds_for_evidence_bearing_squares() -> None:
    i0, j0, k0 = boundary("i0"), boundary("j0"), boundary("k0")
    i1, j1, k1 = (
        boundary("i1", contract_suffix="-v1"),
        boundary("j1", contract_suffix="-v1"),
        boundary("k1", contract_suffix="-v1"),
    )
    i2, j2, k2 = (
        boundary("i2", contract_suffix="-v2"),
        boundary("j2", contract_suffix="-v2"),
        boundary("k2", contract_suffix="-v2"),
    )
    u_i01, u_j01, u_k01 = (
        boundary_map(i0, i1),
        boundary_map(j0, j1),
        boundary_map(k0, k1),
    )
    u_i12, u_j12, u_k12 = (
        boundary_map(i1, i2),
        boundary_map(j1, j2),
        boundary_map(k1, k2),
    )
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
    alpha = cell(f0, f1, u_i01, u_j01, "1")
    beta = cell(g0, g1, u_j01, u_k01, "2")
    gamma = cell(f1, f2, u_i12, u_j12, "3")
    delta = cell(g1, g2, u_j12, u_k12, "4")

    horizontal_then_vertical = alpha.beside(beta).then(gamma.beside(delta))
    vertical_then_horizontal = alpha.then(gamma).beside(beta.then(delta))

    assert horizontal_then_vertical == vertical_then_horizontal
    assert horizontal_then_vertical.digest == vertical_then_horizontal.digest


def test_changed_invariant_dominates_preserved_claim_during_composition() -> None:
    i0, j0 = boundary("i0"), boundary("j0")
    i1, j1 = boundary("i1"), boundary("j1")
    i2, j2 = boundary("i2"), boundary("j2")
    f0 = component(i0, j0, R0, "a")
    f1 = component(i1, j1, R1, "b")
    f2 = component(i2, j2, R2, "c")
    first = Transformation2Cell(
        f0,
        f1,
        boundary_map(i0, i1),
        boundary_map(j0, j1),
        observer_receipts=(digest("d"),),
        preserved_invariants=("schema-compatible",),
        status=VerificationStatus.EVALUATOR_VERIFIED,
    )
    second = Transformation2Cell(
        f1,
        f2,
        boundary_map(i1, i2),
        boundary_map(j1, j2),
        observer_receipts=(digest("e"),),
        changed_invariants=("schema-compatible",),
        status=VerificationStatus.EVALUATOR_VERIFIED,
    )

    composite = first.then(second)

    assert composite.preserved_invariants == ()
    assert composite.changed_invariants == ("schema-compatible",)


def test_revision_binding_changes_component_and_cell_digests() -> None:
    i = boundary("i")
    j = boundary("j")
    old = component(i, j, R0, "a")
    same_artifact_new_revision = component(i, j, R1, "a")

    assert old.component_sha256 != same_artifact_new_revision.component_sha256
    assert Transformation2Cell.identity(old).digest != Transformation2Cell.identity(
        same_artifact_new_revision
    ).digest


def test_two_cell_contract_has_no_promotion_or_owner_approval_surface() -> None:
    i = boundary("i")
    j = boundary("j")
    component_value = component(i, j, R0, "a")
    value = Transformation2Cell.identity(component_value)

    assert value.status is VerificationStatus.EVALUATOR_VERIFIED
    assert "promotion" not in value.to_dict()
    assert "owner_approval" not in value.to_dict()
    assert not hasattr(value, "promote")


def test_empty_non_identity_component_and_unreceipted_verification_refuse() -> None:
    i = boundary("i")
    j = boundary("j")
    with pytest.raises(ValueError, match="identity boundary"):
        OpenFourfoldComponent(
            repository_id=REPOSITORY,
            source_revision=R0,
            left=i,
            right=j,
            component_sha256s=(),
        )

    source = component(i, j, R0, "a")
    target_i = boundary("i1")
    target_j = boundary("j1")
    target = component(target_i, target_j, R1, "b")
    with pytest.raises(ValueError, match="require observer receipt"):
        Transformation2Cell(
            source,
            target,
            boundary_map(i, target_i),
            boundary_map(j, target_j),
            status=VerificationStatus.EVALUATOR_VERIFIED,
        )

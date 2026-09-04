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
A = "1" * 64
B = "2" * 64
C = "3" * 64
D = "4" * 64


def subject(*, revision: str = REVISION) -> ProjectionSubject:
    return ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=revision,
        source_fourfold_sha256=FOURFOLD,
    )


def block(
    relation: str,
    source_axis: TypedAxis,
    target_axis: TypedAxis,
    coordinates: tuple[tuple[object, object, object], ...],
    semiring: object,
    *,
    projection_subject: ProjectionSubject | None = None,
) -> TypedRelationBlock[object]:
    return TypedRelationBlock.from_coordinates(
        subject=projection_subject or subject(),
        signature=RelationSignature(
            source_axis.plane,
            relation,
            target_axis.plane,
        ),
        row_axis=source_axis,
        column_axis=target_axis,
        coordinates=coordinates,
        semiring=semiring,  # type: ignore[arg-type]
    )


def fourfold_query_blocks() -> dict[str, TypedRelationBlock[bool]]:
    semiring = BooleanSemiring()
    code = TypedAxis("code-symbol", "code", ("api", "module", "worker"))
    types = TypedAxis("declared-type", "type", ("Config", "Event"))
    knowledge = TypedAxis(
        "knowledge-claim",
        "knowledge",
        ("config-doc", "event-doc"),
    )
    return {
        "imports": block(
            "imports",
            code,
            code,
            (("api", "module", True), ("module", "worker", True)),
            semiring,
        ),
        "declares": block(
            "declares",
            code,
            types,
            (("module", "Event", True), ("worker", "Config", True)),
            semiring,
        ),
        "documents": block(
            "documents",
            code,
            knowledge,
            (("api", "event-doc", True), ("module", "config-doc", True)),
            semiring,
        ),
        "mentions": block(
            "mentions-type",
            knowledge,
            types,
            (("event-doc", "Event", True), ("config-doc", "Config", True)),
            semiring,
        ),
    }  # type: ignore[return-value]


def test_direct_blocks_execute_the_multihop_fourfold_query() -> None:
    semiring = BooleanSemiring()
    blocks = fourfold_query_blocks()

    imports_declares = blocks["imports"].matmul(
        blocks["declares"],
        semiring,
        relation="imports-declares",
    )
    docs_mentions = blocks["documents"].matmul(
        blocks["mentions"],
        semiring,
        relation="docs-mention-type",
    )
    result = imports_declares.hadamard(
        docs_mentions,
        semiring,
        relation="agrees-under-both-observers",
    )

    assert result.signature == RelationSignature(
        "code", "agrees-under-both-observers", "type"
    )
    assert tuple(result.iter_entries()) == (
        ("api", "Event", True),
        ("module", "Config", True),
    )
    assert result.subject == subject()


def test_boolean_composition_matches_direct_reference_paths() -> None:
    semiring = BooleanSemiring()
    blocks = fourfold_query_blocks()

    result = blocks["imports"].matmul(
        blocks["declares"],
        semiring,
        relation="indirectly-declares",
    )

    assert result.get("api", "Event", semiring) is True
    assert result.get("module", "Config", semiring) is True
    assert result.get("api", "Config", semiring) is False


def test_natural_semiring_counts_independent_paths() -> None:
    semiring = NaturalSemiring()
    source = TypedAxis("source", "code", ("api",))
    middle = TypedAxis("middle", "code", ("m1", "m2"))
    target = TypedAxis("target", "type", ("Event",))
    left = block(
        "imports",
        source,
        middle,
        (("api", "m1", 1), ("api", "m2", 1)),
        semiring,
    )
    right = block(
        "declares",
        middle,
        target,
        (("m1", "Event", 1), ("m2", "Event", 1)),
        semiring,
    )

    result = left.matmul(right, semiring, relation="path-count")

    assert result.get("api", "Event", semiring) == 2


def test_tropical_semiring_selects_the_minimum_path_cost() -> None:
    semiring = TropicalSemiring()
    source = TypedAxis("source", "code", ("api",))
    middle = TypedAxis("middle", "code", ("m1", "m2"))
    target = TypedAxis("target", "type", ("Event",))
    left = block(
        "imports",
        source,
        middle,
        (("api", "m1", 1.0), ("api", "m2", 4.0)),
        semiring,
    )
    right = block(
        "declares",
        middle,
        target,
        (("m1", "Event", 2.0), ("m2", "Event", 1.0)),
        semiring,
    )

    result = left.matmul(right, semiring, relation="minimum-cost")

    assert result.get("api", "Event", semiring) == 3.0


def test_evidence_semiring_returns_alternative_provenance_paths() -> None:
    semiring = EvidenceDagSemiring()
    source = TypedAxis("source", "code", ("api",))
    middle = TypedAxis("middle", "code", ("m1", "m2"))
    target = TypedAxis("target", "type", ("Event",))
    left = block(
        "imports",
        source,
        middle,
        (
            ("api", "m1", EvidenceValue.atom(A)),
            ("api", "m2", EvidenceValue.atom(C)),
        ),
        semiring,
    )
    right = block(
        "declares",
        middle,
        target,
        (
            ("m1", "Event", EvidenceValue.atom(B)),
            ("m2", "Event", EvidenceValue.atom(D)),
        ),
        semiring,
    )

    result = left.matmul(right, semiring, relation="provenance")

    assert result.get("api", "Event", semiring).alternatives == (
        (A, B),
        (C, D),
    )


def test_duplicate_coordinates_are_combined_by_the_selected_semiring() -> None:
    semiring = NaturalSemiring()
    rows = TypedAxis("rows", "code", ("a",))
    columns = TypedAxis("columns", "type", ("T",))

    result = block(
        "declares",
        rows,
        columns,
        (("a", "T", 1), ("a", "T", 2)),
        semiring,
    )

    assert tuple(result.iter_entries()) == (("a", "T", 3),)


def test_block_digest_is_canonical_across_coordinate_order() -> None:
    semiring = BooleanSemiring()
    rows = TypedAxis("rows", "code", ("b", "a"))
    columns = TypedAxis("columns", "type", ("U", "T"))
    first = block(
        "declares",
        rows,
        columns,
        (("a", "T", True), ("b", "U", True)),
        semiring,
    )
    second = block(
        "declares",
        rows,
        columns,
        (("b", "U", True), ("a", "T", True)),
        semiring,
    )

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.digest == second.digest


def test_cross_revision_or_wrong_semiring_composition_refuses() -> None:
    boolean = BooleanSemiring()
    rows = TypedAxis("rows", "code", ("a",))
    middle = TypedAxis("middle", "code", ("m",))
    target = TypedAxis("target", "type", ("T",))
    left = block("imports", rows, middle, (("a", "m", True),), boolean)
    other_revision = block(
        "declares",
        middle,
        target,
        (("m", "T", True),),
        boolean,
        projection_subject=subject(revision="c" * 40),
    )

    with pytest.raises(ValueError, match="same exact Fourfold subject"):
        left.matmul(other_revision, boolean, relation="invalid")
    with pytest.raises(ValueError, match="uses semiring"):
        left.get("a", "m", NaturalSemiring())  # type: ignore[arg-type]


def test_typed_middle_axis_must_match_exactly() -> None:
    semiring = BooleanSemiring()
    source = TypedAxis("source", "code", ("a",))
    left_middle = TypedAxis("middle", "code", ("m",))
    renamed_middle = TypedAxis("renamed-middle", "code", ("m",))
    target = TypedAxis("target", "type", ("T",))
    left = block("imports", source, left_middle, (("a", "m", True),), semiring)
    right = block(
        "declares",
        renamed_middle,
        target,
        (("m", "T", True),),
        semiring,
    )

    with pytest.raises(ValueError, match="exactly shared typed middle axis"):
        left.matmul(right, semiring, relation="invalid")


def test_direct_csr_contract_refuses_wrong_scalar_kind_and_structural_zero() -> None:
    rows = TypedAxis("rows", "code", ("a",))
    columns = TypedAxis("columns", "type", ("T",))
    kwargs = {
        "subject": subject(),
        "signature": RelationSignature("code", "declares", "type"),
        "row_axis": rows,
        "column_axis": columns,
        "row_offsets": (0, 1),
        "column_indices": (0,),
    }

    with pytest.raises(ValueError, match="must not store semiring zero"):
        TypedRelationBlock(
            semiring_name="boolean",
            values=(False,),
            **kwargs,
        )
    with pytest.raises(ValueError, match="non-negative integers"):
        TypedRelationBlock(
            semiring_name="natural",
            values=(-1,),
            **kwargs,
        )


def test_direct_csr_contract_reuses_natural_scalar_bound() -> None:
    rows = TypedAxis("rows", "code", ("a",))
    columns = TypedAxis("columns", "type", ("T",))
    kwargs = {
        "subject": subject(),
        "signature": RelationSignature("code", "declares", "type"),
        "row_axis": rows,
        "column_axis": columns,
        "semiring_name": "natural",
        "row_offsets": (0, 1),
        "column_indices": (0,),
    }
    maximum = (1 << MAX_NATURAL_BITS) - 1

    accepted = TypedRelationBlock(values=(maximum,), **kwargs)
    assert accepted.values == (maximum,)
    with pytest.raises(ValueError, match="bounded bit length"):
        TypedRelationBlock(values=(1 << MAX_NATURAL_BITS,), **kwargs)

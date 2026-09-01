from __future__ import annotations

import pytest

from daedalus.twin.contractions import (
    BlockRef,
    Compose,
    ContractionPlan,
    ReferenceContractionInterpreter,
)
from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring


SUBJECT = ProjectionSubject(
    repository_id="KTY137/daedalus",
    source_revision="a" * 40,
    source_fourfold_sha256="b" * 64,
)


def _block(
    relation: str,
    source: TypedAxis,
    target: TypedAxis,
    row: str,
    column: str,
) -> TypedRelationBlock[bool]:
    semiring = BooleanSemiring()
    return TypedRelationBlock.from_coordinates(
        subject=SUBJECT,
        signature=RelationSignature(source.plane, relation, target.plane),
        row_axis=source,
        column_axis=target,
        coordinates=((row, column, True),),
        semiring=semiring,
    )


def test_reference_interpreter_operation_budget_is_plan_wide() -> None:
    source = TypedAxis("source", "code", ("s",))
    middle = TypedAxis("middle", "code", ("m",))
    bridge = TypedAxis("bridge", "code", ("n",))
    target = TypedAxis("target", "type", ("T",))
    blocks = {
        "a": _block("a", source, middle, "s", "m"),
        "b": _block("b", middle, bridge, "m", "n"),
        "c": _block("c", bridge, target, "n", "T"),
    }
    plan = ContractionPlan(
        "abc",
        Compose(
            Compose(BlockRef("a"), BlockRef("b"), "ab"),
            BlockRef("c"),
            "abc",
        ),
    )

    with pytest.raises(ValueError, match="bounded operation limit"):
        ReferenceContractionInterpreter(
            BooleanSemiring(),
            max_operations=1,
        ).evaluate(plan, blocks)

    result = ReferenceContractionInterpreter(
        BooleanSemiring(),
        max_operations=2,
    ).evaluate(plan, blocks)
    assert result.signature == RelationSignature("code", "abc", "type")
    assert result.subject == SUBJECT
    assert tuple(result.iter_entries()) == (("s", "T", True),)


def test_reference_interpreter_preflights_compose_budget_before_matmul(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TypedAxis("source", "code", ("s",))
    middle = TypedAxis("middle", "code", ("m",))
    target = TypedAxis("target", "type", ("T", "U"))
    semiring = BooleanSemiring()
    left = _block("a", source, middle, "s", "m")
    right = TypedRelationBlock.from_coordinates(
        subject=SUBJECT,
        signature=RelationSignature("code", "b", "type"),
        row_axis=middle,
        column_axis=target,
        coordinates=(("m", "T", True), ("m", "U", True)),
        semiring=semiring,
    )
    plan = ContractionPlan("ab", Compose(BlockRef("a"), BlockRef("b"), "ab"))

    def unexpected_matmul(*args: object, **kwargs: object) -> object:
        raise AssertionError("matmul must not run after an over-budget preflight")

    monkeypatch.setattr(TypedRelationBlock, "matmul", unexpected_matmul)
    with pytest.raises(ValueError, match="bounded operation limit"):
        ReferenceContractionInterpreter(
            semiring,
            max_operations=1,
        ).evaluate(plan, {"a": left, "b": right})

    monkeypatch.undo()
    result = ReferenceContractionInterpreter(
        semiring,
        max_operations=2,
    ).evaluate(plan, {"a": left, "b": right})
    assert tuple(result.iter_entries()) == (
        ("s", "T", True),
        ("s", "U", True),
    )

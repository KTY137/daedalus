from __future__ import annotations

import pytest

from daedalus.twin.contractions import (
    BlockRef,
    Compose,
    ContractionPlan,
    Hadamard,
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


def test_reference_interpreter_compose_preflight_stops_after_budget_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TypedAxis("source", "code", ("s",))
    middle = TypedAxis("middle", "code", ("m", "n"))
    target = TypedAxis("target", "type", ("T", "U", "V"))
    semiring = BooleanSemiring()
    left = TypedRelationBlock.from_coordinates(
        subject=SUBJECT,
        signature=RelationSignature("code", "a", "code"),
        row_axis=source,
        column_axis=middle,
        coordinates=(("s", "m", True), ("s", "n", True)),
        semiring=semiring,
    )
    right = TypedRelationBlock.from_coordinates(
        subject=SUBJECT,
        signature=RelationSignature("code", "b", "type"),
        row_axis=middle,
        column_axis=target,
        coordinates=(("m", "T", True), ("m", "U", True), ("n", "V", True)),
        semiring=semiring,
    )
    plan = ContractionPlan("ab", Compose(BlockRef("a"), BlockRef("b"), "ab"))
    original_columns = left.column_indices

    class ExplodingColumns(tuple):
        def __iter__(self):
            yield self[0]
            raise AssertionError("Compose preflight scanned after the budget was exhausted")

    object.__setattr__(left, "column_indices", ExplodingColumns(original_columns))

    def unexpected_matmul(*args: object, **kwargs: object) -> object:
        raise AssertionError("matmul must not run after an over-budget preflight")

    monkeypatch.setattr(TypedRelationBlock, "matmul", unexpected_matmul)
    with pytest.raises(ValueError, match="bounded operation limit"):
        ReferenceContractionInterpreter(
            semiring,
            max_operations=1,
        ).evaluate(plan, {"a": left, "b": right})

    monkeypatch.undo()
    object.__setattr__(left, "column_indices", original_columns)
    result = ReferenceContractionInterpreter(
        semiring,
        max_operations=3,
    ).evaluate(plan, {"a": left, "b": right})
    assert tuple(result.iter_entries()) == (
        ("s", "T", True),
        ("s", "U", True),
        ("s", "V", True),
    )


def test_reference_interpreter_compose_preflight_preserves_middle_axis_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TypedAxis("source", "code", ("s",))
    left_middle = TypedAxis("left-middle", "code", ("m", "n"))
    right_middle = TypedAxis("right-middle", "code", ("m",))
    target = TypedAxis("target", "type", ("T",))
    semiring = BooleanSemiring()
    left = _block("a", source, left_middle, "s", "n")
    right = _block("b", right_middle, target, "m", "T")
    plan = ContractionPlan("ab", Compose(BlockRef("a"), BlockRef("b"), "ab"))

    def unexpected_matmul(*args: object, **kwargs: object) -> object:
        raise AssertionError("matmul must not run for incompatible typed middle axes")

    monkeypatch.setattr(TypedRelationBlock, "matmul", unexpected_matmul)
    with pytest.raises(ValueError, match="exactly shared typed middle axis"):
        ReferenceContractionInterpreter(semiring).evaluate(
            plan,
            {"a": left, "b": right},
        )


def test_reference_interpreter_compose_preflight_preserves_fourfold_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TypedAxis("source", "code", ("s",))
    middle = TypedAxis("middle", "code", ("m",))
    target = TypedAxis("target", "type", ("T",))
    semiring = BooleanSemiring()
    left = _block("a", source, middle, "s", "m")
    foreign_subject = ProjectionSubject(
        repository_id="KTY137/other",
        source_revision="c" * 40,
        source_fourfold_sha256="d" * 64,
    )
    right = TypedRelationBlock.from_coordinates(
        subject=foreign_subject,
        signature=RelationSignature("code", "b", "type"),
        row_axis=middle,
        column_axis=target,
        coordinates=(("m", "T", True),),
        semiring=semiring,
    )
    plan = ContractionPlan("ab", Compose(BlockRef("a"), BlockRef("b"), "ab"))

    def unexpected_matmul(*args: object, **kwargs: object) -> object:
        raise AssertionError("matmul must not run across Fourfold subjects")

    monkeypatch.setattr(TypedRelationBlock, "matmul", unexpected_matmul)
    with pytest.raises(ValueError, match="same exact Fourfold subject"):
        ReferenceContractionInterpreter(semiring).evaluate(
            plan,
            {"a": left, "b": right},
        )


def test_reference_interpreter_preflights_hadamard_budget_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = TypedAxis("rows", "code", ("s",))
    columns = TypedAxis("columns", "type", ("T", "U", "V"))
    semiring = BooleanSemiring()
    left = TypedRelationBlock.from_coordinates(
        subject=SUBJECT,
        signature=RelationSignature("code", "left", "type"),
        row_axis=rows,
        column_axis=columns,
        coordinates=(("s", "T", True), ("s", "U", True)),
        semiring=semiring,
    )
    right = TypedRelationBlock.from_coordinates(
        subject=SUBJECT,
        signature=RelationSignature("code", "right", "type"),
        row_axis=rows,
        column_axis=columns,
        coordinates=(("s", "T", True), ("s", "U", True), ("s", "V", True)),
        semiring=semiring,
    )
    plan = ContractionPlan(
        "both",
        Hadamard(BlockRef("left"), BlockRef("right"), "both"),
    )

    def unexpected_hadamard(*args: object, **kwargs: object) -> object:
        raise AssertionError("hadamard must not run after an over-budget preflight")

    monkeypatch.setattr(TypedRelationBlock, "hadamard", unexpected_hadamard)
    with pytest.raises(ValueError, match="bounded operation limit"):
        ReferenceContractionInterpreter(
            semiring,
            max_operations=1,
        ).evaluate(plan, {"left": left, "right": right})

    monkeypatch.undo()
    result = ReferenceContractionInterpreter(
        semiring,
        max_operations=2,
    ).evaluate(plan, {"left": left, "right": right})
    assert tuple(result.iter_entries()) == (
        ("s", "T", True),
        ("s", "U", True),
    )


def test_reference_interpreter_hadamard_preflight_preserves_axis_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = TypedAxis("rows", "code", ("s",))
    left_columns = TypedAxis("columns", "type", ("T",))
    right_columns = TypedAxis("renamed-columns", "type", ("T",))
    semiring = BooleanSemiring()
    left = _block("left", rows, left_columns, "s", "T")
    right = _block("right", rows, right_columns, "s", "T")
    plan = ContractionPlan(
        "both",
        Hadamard(BlockRef("left"), BlockRef("right"), "both"),
    )

    def unexpected_hadamard(*args: object, **kwargs: object) -> object:
        raise AssertionError("hadamard must not run for incompatible typed axes")

    monkeypatch.setattr(TypedRelationBlock, "hadamard", unexpected_hadamard)
    with pytest.raises(ValueError, match="identical typed axes"):
        ReferenceContractionInterpreter(semiring).evaluate(
            plan,
            {"left": left, "right": right},
        )

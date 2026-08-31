from __future__ import annotations

import pytest

from daedalus.twin.contractions import (
    BlockRef,
    CompiledBooleanContractionPlan,
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
from daedalus.twin.semiring import BooleanSemiring, NaturalSemiring

REVISION = "a" * 40
FOURFOLD = "b" * 64


def _subject(*, revision: str = REVISION) -> ProjectionSubject:
    return ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=revision,
        source_fourfold_sha256=FOURFOLD,
    )


def _block(
    relation: str,
    source: TypedAxis,
    target: TypedAxis,
    coordinates: tuple[tuple[object, object, object], ...],
    semiring: object,
    *,
    subject: ProjectionSubject | None = None,
) -> TypedRelationBlock[object]:
    return TypedRelationBlock.from_coordinates(
        subject=subject or _subject(),
        signature=RelationSignature(source.plane, relation, target.plane),
        row_axis=source,
        column_axis=target,
        coordinates=coordinates,
        semiring=semiring,  # type: ignore[arg-type]
    )


def _query() -> tuple[ContractionPlan, dict[str, TypedRelationBlock[bool]]]:
    boolean = BooleanSemiring()
    code = TypedAxis("code-symbol", "code", ("api", "module", "worker"))
    types = TypedAxis("declared-type", "type", ("Config", "Event"))
    knowledge = TypedAxis(
        "knowledge-claim", "knowledge", ("config-doc", "event-doc")
    )
    blocks = {
        "imports": _block(
            "imports", code, code,
            (("api", "module", True), ("module", "worker", True)), boolean,
        ),
        "declares": _block(
            "declares", code, types,
            (("module", "Event", True), ("worker", "Config", True)), boolean,
        ),
        "documents": _block(
            "documents", code, knowledge,
            (("api", "event-doc", True), ("module", "config-doc", True)), boolean,
        ),
        "mentions": _block(
            "mentions-type", knowledge, types,
            (("event-doc", "Event", True), ("config-doc", "Config", True)), boolean,
        ),
    }
    plan = ContractionPlan(
        "indirect-declaration-documented",
        Hadamard(
            Compose(BlockRef("imports"), BlockRef("declares"), "imports-declares"),
            Compose(BlockRef("documents"), BlockRef("mentions"), "docs-mention-type"),
            "agrees-under-both-observers",
        ),
    )
    return plan, blocks  # type: ignore[return-value]


def test_compiled_boolean_plan_is_observationally_equal_to_reference() -> None:
    plan, blocks = _query()
    expected = ReferenceContractionInterpreter(BooleanSemiring()).evaluate(plan, blocks)

    compiled = CompiledBooleanContractionPlan.compile(plan, blocks)
    actual = compiled.evaluate()

    assert actual == expected
    assert actual.digest == expected.digest
    assert tuple(actual.iter_entries()) == (
        ("api", "Event", True),
        ("module", "Config", True),
    )


def test_compiled_boolean_plan_materializes_only_final_block(monkeypatch: pytest.MonkeyPatch) -> None:
    plan, blocks = _query()
    original = TypedRelationBlock._from_indexed
    calls = 0

    def counted(cls: type[TypedRelationBlock[object]], *args: object, **kwargs: object) -> TypedRelationBlock[object]:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)  # type: ignore[return-value]

    monkeypatch.setattr(TypedRelationBlock, "_from_indexed", classmethod(counted))

    result = CompiledBooleanContractionPlan.compile(plan, blocks).evaluate()

    assert calls == 1
    assert result.entry_count == 2


def test_compiled_boolean_plan_refuses_wrong_semiring_and_subject() -> None:
    natural = NaturalSemiring()
    code = TypedAxis("code", "code", ("a", "m"))
    types = TypedAxis("type", "type", ("T",))
    natural_block = _block(
        "declares", code, types, (("a", "T", 1),), natural
    )
    natural_plan = ContractionPlan("out", BlockRef("declares"))

    with pytest.raises(ValueError, match="uses semiring"):
        CompiledBooleanContractionPlan.compile(
            natural_plan, {"declares": natural_block}  # type: ignore[arg-type]
        )

    boolean = BooleanSemiring()
    left = _block(
        "imports", code, code, (("a", "m", True),), boolean
    )
    right = _block(
        "declares", code, types, (("m", "T", True),), boolean,
        subject=_subject(revision="c" * 40),
    )
    plan = ContractionPlan(
        "out", Compose(BlockRef("left"), BlockRef("right"), "path")
    )
    with pytest.raises(ValueError, match="same exact Fourfold subject"):
        CompiledBooleanContractionPlan.compile(plan, {"left": left, "right": right})


def test_compiled_boolean_plan_enforces_operation_budget() -> None:
    plan, blocks = _query()
    compiled = CompiledBooleanContractionPlan.compile(plan, blocks, max_operations=0)

    with pytest.raises(ValueError, match="bounded operation limit"):
        compiled.evaluate()

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from daedalus.twin.relation_blocks import ProjectionSubject, TypedRelationBlock
from daedalus.twin.relation_compiler import (
    MAX_COMPILED_RELATIONS,
    CompiledRelationBlocks,
)


SUBJECT = ProjectionSubject(
    repository_id="KTY137/daedalus",
    source_revision="4" * 40,
    source_fourfold_sha256="a" * 64,
)


class _OversizedBlocks(Sequence[tuple[str, TypedRelationBlock[bool]]]):
    def __len__(self) -> int:
        return MAX_COMPILED_RELATIONS + 1

    def __getitem__(self, index: int) -> tuple[str, TypedRelationBlock[bool]]:
        raise AssertionError(f"oversized block catalog was normalized at {index}")

    def __iter__(self) -> Iterator[tuple[str, TypedRelationBlock[bool]]]:
        raise AssertionError("oversized block catalog was iterated")


class _DeclaredEmptyBlocks(Sequence[tuple[str, TypedRelationBlock[bool]]]):
    def __len__(self) -> int:
        return 0

    def __getitem__(self, index: int) -> tuple[str, TypedRelationBlock[bool]]:
        raise AssertionError(f"empty block catalog was indexed at {index}")

    def __iter__(self) -> Iterator[tuple[str, TypedRelationBlock[bool]]]:
        raise AssertionError("declared-empty block catalog iterator was consumed")


class _InvalidFirstBlocks(Sequence[object]):
    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> object:
        if index == 0:
            return ("", object())
        raise AssertionError(
            "receipt validation eagerly materialized a later declared block"
        )

    def __iter__(self) -> Iterator[object]:
        raise AssertionError("invalid block catalog iterator was consumed")


class _UnboundedBlocks:
    def __iter__(self) -> Iterator[tuple[str, TypedRelationBlock[bool]]]:
        raise AssertionError("unbounded block iterable was consumed")


def _receipt(blocks: object) -> CompiledRelationBlocks[bool]:
    return CompiledRelationBlocks(
        subject=SUBJECT,
        semiring_name="boolean",
        source_forest_sha256="b" * 64,
        blocks=blocks,  # type: ignore[arg-type]
        semantic_fact_count=0,
        forest_edge_count=0,
        forest_hyperedge_count=0,
        verified_binding_count=0,
    )


def test_compiled_receipt_rejects_oversized_catalog_before_normalization() -> None:
    with pytest.raises(ValueError, match="compiled block count exceeds limit"):
        _receipt(_OversizedBlocks())


def test_compiled_receipt_rejects_unbounded_iterable_before_consumption() -> None:
    with pytest.raises(ValueError, match="blocks must be a bounded sequence"):
        _receipt(_UnboundedBlocks())


def test_compiled_receipt_materializes_only_declared_sequence_cardinality() -> None:
    receipt = _receipt(_DeclaredEmptyBlocks())

    assert receipt.blocks == ()


def test_compiled_receipt_validates_each_item_before_reading_the_next() -> None:
    with pytest.raises(
        ValueError,
        match="compiled block names must be non-empty strings",
    ):
        _receipt(_InvalidFirstBlocks())

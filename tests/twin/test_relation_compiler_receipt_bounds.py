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

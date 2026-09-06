from __future__ import annotations

import pytest

from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring

REVISION = "a" * 40
FOURFOLD = "b" * 64


def test_from_indexed_rejects_non_integer_columns_before_sorting() -> None:
    rows = TypedAxis("rows", "code", ("r0", "r1"))
    columns = TypedAxis("columns", "type", ("c0", "c1", "c2"))
    subject = ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_fourfold_sha256=FOURFOLD,
    )

    with pytest.raises(ValueError, match="indexed block column indices must contain integers"):
        TypedRelationBlock._from_indexed(
            subject,
            RelationSignature("code", "declares", "type"),
            rows,
            columns,
            {(0, 0): True, (0, "1"): True},  # type: ignore[dict-item]
            BooleanSemiring(),
        )

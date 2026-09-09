from __future__ import annotations

from typing import Any

from daedalus.twin import relation_compiler
from daedalus.twin.relation_blocks import RelationSignature


SIGNATURE = RelationSignature("code", "imports", "code")


class _FactsWithoutSetdefault(
    dict[RelationSignature, dict[tuple[int, int], Any]]
):
    def setdefault(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("outer fact map must not allocate setdefault defaults")


class _CoordinatesWithoutSetdefault(dict[tuple[int, int], Any]):
    def setdefault(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("evidence coordinate map must not allocate setdefault defaults")


def test_record_fact_creates_and_reuses_bucket_without_outer_setdefault() -> None:
    facts = _FactsWithoutSetdefault()

    relation_compiler._record_fact(
        facts,
        signature=SIGNATURE,
        source_index=0,
        target_index=0,
        scalar_value=True,
        evidence_atoms=None,
    )
    bucket = facts[SIGNATURE]

    relation_compiler._record_fact(
        facts,
        signature=SIGNATURE,
        source_index=0,
        target_index=1,
        scalar_value=True,
        evidence_atoms=None,
    )

    assert facts[SIGNATURE] is bucket
    assert bucket == {(0, 0): True, (0, 1): True}


def test_record_fact_reuses_evidence_coordinate_without_inner_setdefault() -> None:
    bucket = _CoordinatesWithoutSetdefault()
    facts: dict[RelationSignature, dict[tuple[int, int], Any]] = {SIGNATURE: bucket}

    relation_compiler._record_fact(
        facts,
        signature=SIGNATURE,
        source_index=0,
        target_index=0,
        scalar_value=None,
        evidence_atoms=("witness-a",),
    )
    alternatives = bucket[(0, 0)]

    relation_compiler._record_fact(
        facts,
        signature=SIGNATURE,
        source_index=0,
        target_index=0,
        scalar_value=None,
        evidence_atoms=("witness-b",),
    )

    assert bucket[(0, 0)] is alternatives
    assert alternatives == {("witness-a",), ("witness-b",)}

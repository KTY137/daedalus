from __future__ import annotations

import math

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.twin.tensor import SparseTensorEntry, TensorAxis, TensorView

REVISION = "a" * 40
FOREST = "b" * 64
FOURFOLD = "c" * 64
EVIDENCE = "d" * 64
NOW = "2026-08-30T12:00:00Z"


class FloatLike:
    def __float__(self) -> float:
        return 1.0


def entry(value: object) -> SparseTensorEntry:
    return SparseTensorEntry(
        coordinates=(("node", "src/a.py"),),
        relation="membership",
        value=value,  # type: ignore[arg-type]
        evidence_sha256s=(EVIDENCE,),
    )


def view(value: object) -> TensorView:
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(TensorAxis("node", ("src/a.py",)),),
        entries=(entry(value),),
        provenance=ContractProvenance(
            origin="test.tensor.scalar",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(FOREST, FOURFOLD),
            trace_id="tensor-scalar-contract",
        ),
    )


@pytest.mark.parametrize("bad", [True, False, "1.0", FloatLike()])
def test_scalar_refuses_implicit_numeric_coercion(bad: object) -> None:
    with pytest.raises(ValueError, match="finite number"):
        entry(bad)


def test_integer_scalar_is_canonicalized_to_float() -> None:
    scalar = entry(1)

    assert scalar.value == 1.0
    assert type(scalar.value) is float


def test_negative_zero_is_normalized_before_canonical_serialization() -> None:
    positive = view(0.0)
    negative = view(-0.0)

    assert math.copysign(1.0, negative.entries[0].value) == 1.0
    assert positive.to_json() == negative.to_json()
    assert positive.digest == negative.digest

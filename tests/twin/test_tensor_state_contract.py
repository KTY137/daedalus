from __future__ import annotations

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.twin.tensor import TensorAxis, TensorView, parse_tensor_view

REVISION = "a" * 40
FOREST = "b" * 64
FOURFOLD = "c" * 64
NOW = "2026-08-30T13:57:00Z"


def view(*, status: object = "complete", reason: object = "") -> TensorView:
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status=status,  # type: ignore[arg-type]
        axes=(TensorAxis("node", ("src/a.py",)),),
        entries=(),
        provenance=ContractProvenance(
            origin="test.tensor.state",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(FOREST, FOURFOLD),
        ),
        reason=reason,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("bad", [None, False, 0, (), [], {}])
def test_complete_tensor_refuses_falsey_non_string_reason(bad: object) -> None:
    with pytest.raises(ValueError, match="tensor.reason must be a string"):
        view(reason=bad)


@pytest.mark.parametrize("bad", [None, False, 0, [], {}])
def test_status_refuses_non_string_values_inside_contract_error_domain(bad: object) -> None:
    with pytest.raises(ValueError, match="tensor.status must be complete, partial, or absent"):
        view(status=bad)


def test_wire_parser_cannot_alias_empty_reason_with_falsey_non_string() -> None:
    canonical = view()
    malformed = canonical.to_dict()
    malformed["reason"] = False

    with pytest.raises(ValueError, match="tensor.reason must be a string"):
        parse_tensor_view(malformed)

    assert canonical.reason == ""

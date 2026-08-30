from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from daedalus.twin.tensor import (
    MAX_ENTRY_EVIDENCE_DIGESTS,
    MAX_TENSOR_AXES,
    MAX_TENSOR_ENTRIES,
    SparseTensorEntry,
    TensorView,
)


class ExplodingSequence(Sequence[object]):
    """Sized adversarial input that records any attempted element access."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.accessed = False

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, index: int) -> object:
        self.accessed = True
        raise AssertionError(f"oversized tensor input was accessed at {index}")


def _digest(index: int) -> str:
    return f"{index:064x}"


def _tensor_wire_payload(*, axes: Any = (), entries: Any = ()) -> dict[str, Any]:
    return {
        "contract_type": TensorView.CONTRACT_TYPE,
        "contract_version": TensorView.CONTRACT_VERSION,
        "repository_id": "KTY137/daedalus",
        "source_revision": "a" * 40,
        "source_forest_sha256": "b" * 64,
        "source_fourfold_sha256": "c" * 64,
        "status": "complete",
        "axes": axes,
        "entries": entries,
        "provenance": {},
        "reason": "",
    }


def test_oversized_evidence_fan_in_refuses_before_element_access() -> None:
    evidence = ExplodingSequence(MAX_ENTRY_EVIDENCE_DIGESTS + 1)

    with pytest.raises(ValueError, match="entry.evidence_sha256s exceeds bounded limit"):
        SparseTensorEntry(
            coordinates=(("node", "src/a.py"),),
            relation="membership",
            evidence_sha256s=evidence,  # type: ignore[arg-type]
        )

    assert evidence.accessed is False


def test_evidence_limit_is_inclusive_and_canonical() -> None:
    evidence = tuple(reversed(tuple(_digest(index) for index in range(MAX_ENTRY_EVIDENCE_DIGESTS))))

    entry = SparseTensorEntry(
        coordinates=(("node", "src/a.py"),),
        relation="membership",
        evidence_sha256s=evidence,
    )

    assert len(entry.evidence_sha256s) == MAX_ENTRY_EVIDENCE_DIGESTS
    assert entry.evidence_sha256s == tuple(sorted(evidence))


def test_wire_payload_cannot_bypass_evidence_bound() -> None:
    payload = {
        "coordinates": [["node", "src/a.py"]],
        "relation": "membership",
        "value": 1.0,
        "masked": False,
        "evidence_sha256s": [_digest(index) for index in range(MAX_ENTRY_EVIDENCE_DIGESTS + 1)],
    }

    with pytest.raises(ValueError, match="entry.evidence_sha256s exceeds bounded limit"):
        SparseTensorEntry.from_dict(payload)


def test_wire_axis_count_refuses_before_record_materialization() -> None:
    axes = ExplodingSequence(MAX_TENSOR_AXES + 1)

    with pytest.raises(ValueError, match="tensor.axes exceeds bounded limit"):
        TensorView.from_dict(_tensor_wire_payload(axes=axes))

    assert axes.accessed is False


def test_wire_entry_count_refuses_before_record_materialization() -> None:
    entries = ExplodingSequence(MAX_TENSOR_ENTRIES + 1)

    with pytest.raises(ValueError, match="tensor.entries exceeds bounded limit"):
        TensorView.from_dict(_tensor_wire_payload(entries=entries))

    assert entries.accessed is False

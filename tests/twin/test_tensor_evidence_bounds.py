from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

import daedalus.twin.semiring as semiring_module
from daedalus.twin.semiring import (
    MAX_EVIDENCE_ALTERNATIVES,
    MAX_EVIDENCE_TERM_ATOMS,
    EvidenceDagSemiring,
    EvidenceValue,
)
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


class FirstThenExplodes(Sequence[object]):
    """Expose one invalid term; any tail access proves eager outer materialization."""

    def __init__(self, first: object) -> None:
        self.first = first
        self.tail_accessed = False

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> object:
        if index == 0:
            return self.first
        self.tail_accessed = True
        raise AssertionError(f"evidence parser advanced past invalid term at {index}")


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


def test_evidence_wire_alternatives_refuse_before_copy() -> None:
    alternatives = ExplodingSequence(MAX_EVIDENCE_ALTERNATIVES + 1)

    with pytest.raises(ValueError, match="evidence.alternatives exceeds bounded limit"):
        EvidenceValue.from_dict({"alternatives": alternatives})

    assert alternatives.accessed is False


def test_evidence_wire_oversized_term_refuses_before_copying_tail() -> None:
    term = ExplodingSequence(MAX_EVIDENCE_TERM_ATOMS + 1)
    alternatives = FirstThenExplodes(term)

    with pytest.raises(
        ValueError,
        match=r"evidence\.alternatives\[0\] exceeds bounded limit",
    ):
        EvidenceValue.from_dict({"alternatives": alternatives})

    assert term.accessed is False
    assert alternatives.tail_accessed is False


def test_evidence_multiply_rejects_oversized_merged_term() -> None:
    semiring = EvidenceDagSemiring()
    first = EvidenceValue((tuple(_digest(index) for index in range(MAX_EVIDENCE_TERM_ATOMS)),))
    second = EvidenceValue(
        (
            tuple(
                _digest(MAX_EVIDENCE_TERM_ATOMS + index)
                for index in range(MAX_EVIDENCE_TERM_ATOMS)
            ),
        )
    )

    with pytest.raises(ValueError, match="multiplication term exceeds bounded atom limit"):
        semiring.multiply(first, second)


def test_evidence_multiply_allows_overlapping_terms_at_bound() -> None:
    semiring = EvidenceDagSemiring()
    term = tuple(_digest(index) for index in range(MAX_EVIDENCE_TERM_ATOMS))
    value = EvidenceValue((term,))

    assert semiring.multiply(value, value) == value


def test_evidence_add_rejects_before_result_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semiring = EvidenceDagSemiring()
    first = EvidenceValue(((_digest(0),), (_digest(1),), (_digest(2),)))
    second = EvidenceValue(((_digest(3),), (_digest(4),)))
    monkeypatch.setattr(semiring_module, "MAX_EVIDENCE_ALTERNATIVES", 4)

    def _unexpected_init(self: EvidenceValue, alternatives: object) -> None:
        raise AssertionError("oversized evidence addition materialized a result")

    monkeypatch.setattr(EvidenceValue, "__init__", _unexpected_init)

    with pytest.raises(ValueError, match="addition exceeds bounded alternative limit"):
        semiring.add(first, second)


def test_evidence_add_allows_exact_alternative_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semiring = EvidenceDagSemiring()
    first = EvidenceValue(((_digest(0),), (_digest(1),), (_digest(2),)))
    second = EvidenceValue(((_digest(3),), (_digest(4),)))
    monkeypatch.setattr(semiring_module, "MAX_EVIDENCE_ALTERNATIVES", 5)

    result = semiring.add(first, second)

    assert len(result.alternatives) == 5

from __future__ import annotations

from collections.abc import Sequence

import pytest

from daedalus.twin.tensor import MAX_ENTRY_EVIDENCE_DIGESTS, SparseTensorEntry


class ExplodingSequence(Sequence[str]):
    """Sized adversarial input that records any attempted element access."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.accessed = False

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, index: int) -> str:
        self.accessed = True
        raise AssertionError(f"oversized evidence input was accessed at {index}")


def _digest(index: int) -> str:
    return f"{index:064x}"


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

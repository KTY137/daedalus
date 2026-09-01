"""Small, deterministic semiring reference semantics for Fourfold projections.

The classes in this module are computational observers only.  They do not
verify evidence, grant trust, mutate a Fourfold snapshot, or participate in
promotion.  Backends may implement the same protocol later, but this stdlib
implementation remains the executable oracle for their results.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, Sequence, TypeVar, runtime_checkable

from ..schemas import _sha256
from ..spine.envelope import canonical_json, canonical_sha

T = TypeVar("T")

MAX_NATURAL_BITS = 4_096
MAX_EVIDENCE_ALTERNATIVES = 4_096
MAX_EVIDENCE_TERM_ATOMS = 128


def _bounded_sequence(values: Any, name: str, limit: int) -> Sequence[Any]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a bounded sequence")
    if len(values) > limit:
        raise ValueError(f"{name} exceeds bounded limit {limit}")
    return values


@runtime_checkable
class Semiring(Protocol[T]):
    """Operations required by the relation-block reference interpreter."""

    name: str
    zero: T
    one: T

    def add(self, left: T, right: T) -> T:
        """Combine alternative derivations."""

    def multiply(self, left: T, right: T) -> T:
        """Compose jointly required derivations."""


class BooleanSemiring:
    """Path existence: addition is OR and multiplication is AND."""

    name = "boolean"
    zero = False
    one = True

    @staticmethod
    def _value(value: Any, name: str) -> bool:
        if type(value) is not bool:
            raise ValueError(f"{name} must be boolean")
        return value

    def add(self, left: bool, right: bool) -> bool:
        first = self._value(left, "left")
        second = self._value(right, "right")
        return first or second

    def multiply(self, left: bool, right: bool) -> bool:
        first = self._value(left, "left")
        second = self._value(right, "right")
        return first and second


class NaturalSemiring:
    """Path multiplicity over bounded non-negative integers."""

    name = "natural"
    zero = 0
    one = 1

    @staticmethod
    def _value(value: Any, name: str) -> int:
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        if value.bit_length() > MAX_NATURAL_BITS:
            raise ValueError(
                f"{name} exceeds bounded natural bit length {MAX_NATURAL_BITS}"
            )
        return value

    def add(self, left: int, right: int) -> int:
        first = self._value(left, "left")
        second = self._value(right, "right")
        return self._value(first + second, "result")

    def multiply(self, left: int, right: int) -> int:
        first = self._value(left, "left")
        second = self._value(right, "right")
        return self._value(first * second, "result")


class TropicalSemiring:
    """Minimum non-negative cost with path composition by addition."""

    name = "tropical"
    zero = math.inf
    one = 0.0

    @staticmethod
    def _value(value: Any, name: str) -> float:
        if type(value) not in (int, float):
            raise ValueError(f"{name} must be a non-negative number or +infinity")
        try:
            normalized = float(value)
        except OverflowError as exc:
            raise ValueError(
                f"{name} must be a non-negative number or +infinity"
            ) from exc
        if math.isnan(normalized) or normalized < 0.0 or normalized == -math.inf:
            raise ValueError(f"{name} must be a non-negative number or +infinity")
        if normalized == 0.0:
            normalized = 0.0
        return normalized

    def add(self, left: float, right: float) -> float:
        return min(self._value(left, "left"), self._value(right, "right"))

    def multiply(self, left: float, right: float) -> float:
        first = self._value(left, "left")
        second = self._value(right, "right")
        if math.isinf(first) or math.isinf(second):
            return math.inf
        result = first + second
        if math.isinf(result):
            return math.inf
        return result


@dataclass(frozen=True)
class EvidenceValue:
    """Finite canonical DNF used as the oracle for an evidence DAG semiring.

    Each inner tuple is a conjunction of evidence digests.  The outer tuple is
    a set of alternative proof paths.  Superset clauses are removed by
    absorption, so ``a OR (a AND b)`` canonicalizes to ``a``.  A production
    hash-consed DAG can use a different physical representation while matching
    this exact observable semantics.
    """

    alternatives: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        raw_alternatives = _bounded_sequence(
            self.alternatives,
            "evidence.alternatives",
            MAX_EVIDENCE_ALTERNATIVES,
        )
        candidates: set[tuple[str, ...]] = set()
        for alternative_index, raw_term in enumerate(raw_alternatives):
            term_values = _bounded_sequence(
                raw_term,
                f"evidence.alternatives[{alternative_index}]",
                MAX_EVIDENCE_TERM_ATOMS,
            )
            atoms = tuple(
                sorted(
                    {
                        _sha256(
                            atom,
                            f"evidence.alternatives[{alternative_index}]"
                            f"[{atom_index}]",
                        )
                        for atom_index, atom in enumerate(term_values)
                    }
                )
            )
            candidates.add(atoms)

        # Short terms first makes absorption linear in the retained clauses.
        retained: list[tuple[str, ...]] = []
        retained_sets: list[frozenset[str]] = []
        for term in sorted(candidates, key=lambda item: (len(item), item)):
            term_set = frozenset(term)
            if any(existing.issubset(term_set) for existing in retained_sets):
                continue
            retained.append(term)
            retained_sets.append(term_set)
        object.__setattr__(self, "alternatives", tuple(sorted(retained)))

    @classmethod
    def atom(cls, evidence_sha256: str) -> "EvidenceValue":
        return cls(((_sha256(evidence_sha256, "evidence_sha256"),),))

    @classmethod
    def from_dict(cls, payload: Any) -> "EvidenceValue":
        if not isinstance(payload, dict) or set(payload) != {"alternatives"}:
            raise ValueError("evidence value must contain only alternatives")
        alternatives = _bounded_sequence(
            payload["alternatives"],
            "evidence.alternatives",
            MAX_EVIDENCE_ALTERNATIVES,
        )
        bounded_terms: list[Sequence[Any]] = []
        for alternative_index, raw_term in enumerate(alternatives):
            bounded_terms.append(
                _bounded_sequence(
                    raw_term,
                    f"evidence.alternatives[{alternative_index}]",
                    MAX_EVIDENCE_TERM_ATOMS,
                )
            )
        return cls(tuple(bounded_terms))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, Any]:
        return {"alternatives": [list(term) for term in self.alternatives]}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    def __bool__(self) -> bool:
        return bool(self.alternatives)


class EvidenceDagSemiring:
    """Idempotent provenance algebra over :class:`EvidenceValue`."""

    name = "evidence-dag"
    zero = EvidenceValue(())
    one = EvidenceValue(((),))

    @staticmethod
    def _value(value: Any, name: str) -> EvidenceValue:
        if not isinstance(value, EvidenceValue):
            raise ValueError(f"{name} must be EvidenceValue")
        return value

    def add(self, left: EvidenceValue, right: EvidenceValue) -> EvidenceValue:
        first = self._value(left, "left")
        second = self._value(right, "right")
        if not first.alternatives:
            return second
        if not second.alternatives:
            return first
        if first == second:
            return first
        if len(first.alternatives) + len(second.alternatives) > (
            MAX_EVIDENCE_ALTERNATIVES
        ):
            raise ValueError("evidence addition exceeds bounded alternative limit")
        return EvidenceValue(first.alternatives + second.alternatives)

    def multiply(
        self,
        left: EvidenceValue,
        right: EvidenceValue,
    ) -> EvidenceValue:
        first = self._value(left, "left")
        second = self._value(right, "right")
        if not first.alternatives or not second.alternatives:
            return self.zero
        if first == second:
            return first
        if first == self.one:
            return second
        if second == self.one:
            return first
        candidate_count = len(first.alternatives) * len(second.alternatives)
        if candidate_count > MAX_EVIDENCE_ALTERNATIVES:
            raise ValueError("evidence multiplication exceeds bounded alternative limit")

        clauses: list[tuple[str, ...]] = []
        for first_term in first.alternatives:
            first_atoms = set(first_term)
            for second_term in second.alternatives:
                merged_atoms = set(first_atoms)
                for atom in second_term:
                    merged_atoms.add(atom)
                    if len(merged_atoms) > MAX_EVIDENCE_TERM_ATOMS:
                        raise ValueError(
                            "evidence multiplication term exceeds bounded atom limit"
                        )
                clauses.append(tuple(sorted(merged_atoms)))
        return EvidenceValue(tuple(clauses))


__all__ = [
    "MAX_NATURAL_BITS",
    "MAX_EVIDENCE_ALTERNATIVES",
    "MAX_EVIDENCE_TERM_ATOMS",
    "BooleanSemiring",
    "EvidenceDagSemiring",
    "EvidenceValue",
    "NaturalSemiring",
    "Semiring",
    "TropicalSemiring",
]

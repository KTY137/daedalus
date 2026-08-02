"""Evidence-bearing cross-repository motif provenance for Gate 2.

A motif never replaces its concrete repository supports.  This module binds
revision-exact Project Twin subgraphs, license and extractor identity, verified
cross-repository alignments, negative examples, invariants, and evaluator
evidence into one canonical artifact.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any, Mapping

from daedalus.schemas import _revision, _sha256

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SPDX_RE = re.compile(r"^[A-Za-z0-9.+-]+$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALIGNMENT_STATES = frozenset({"verified", "rejected"})


class MotifProvenanceError(ValueError):
    """Raised when motif support or alignment provenance is not exact."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MotifProvenanceError(f"{field} must be a non-empty string")
    return value


def _sorted_sha(values: tuple[str, ...], field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise MotifProvenanceError(f"{field} must not be empty")
    normalized = tuple(_sha256(value, field) for value in values)
    if normalized != tuple(sorted(set(normalized))):
        raise MotifProvenanceError(f"{field} must be unique and sorted")
    return normalized


@dataclasses.dataclass(frozen=True, slots=True)
class MotifSupport:
    repository_id: str
    source_revision: str
    project_twin_manifest_sha256: str
    subgraph_sha256: str
    license_spdx: str
    extractor_contract_sha256: str
    evidence_sha256: str
    temporal_cutoff: str

    def __post_init__(self) -> None:
        repository_id = _text(self.repository_id, "repository_id")
        if not _ID_RE.fullmatch(repository_id):
            raise MotifProvenanceError("repository_id must be lowercase kebab-case")
        object.__setattr__(self, "source_revision", _revision(self.source_revision, "source_revision"))
        for field in (
            "project_twin_manifest_sha256",
            "subgraph_sha256",
            "extractor_contract_sha256",
            "evidence_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if not _SPDX_RE.fullmatch(_text(self.license_spdx, "license_spdx")):
            raise MotifProvenanceError("license_spdx must be one canonical SPDX identifier")
        if not _TIME_RE.fullmatch(_text(self.temporal_cutoff, "temporal_cutoff")):
            raise MotifProvenanceError("temporal_cutoff must be canonical UTC seconds")

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MotifSupport":
        expected = {
            "repository_id",
            "source_revision",
            "project_twin_manifest_sha256",
            "subgraph_sha256",
            "license_spdx",
            "extractor_contract_sha256",
            "evidence_sha256",
            "temporal_cutoff",
        }
        if set(payload) != expected:
            raise MotifProvenanceError("motif support fields are not canonical")
        return cls(**payload)


@dataclasses.dataclass(frozen=True, slots=True)
class CrossRepositoryAlignment:
    left_support_sha256: str
    right_support_sha256: str
    mapping_sha256: str
    algorithm_contract_sha256: str
    status: str
    evidence_sha256: str | None
    limitation: str | None

    def __post_init__(self) -> None:
        for field in (
            "left_support_sha256",
            "right_support_sha256",
            "mapping_sha256",
            "algorithm_contract_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if self.left_support_sha256 == self.right_support_sha256:
            raise MotifProvenanceError("alignment must connect two distinct supports")
        if self.left_support_sha256 > self.right_support_sha256:
            raise MotifProvenanceError("alignment support digests must use canonical order")
        if self.status not in _ALIGNMENT_STATES:
            raise MotifProvenanceError("unsupported alignment status")
        if self.status == "verified":
            object.__setattr__(self, "evidence_sha256", _sha256(self.evidence_sha256, "evidence_sha256"))
            if self.limitation is not None:
                raise MotifProvenanceError("verified alignment must not carry a rejection limitation")
        else:
            if self.evidence_sha256 is not None:
                raise MotifProvenanceError("rejected alignment must not carry success evidence")
            _text(self.limitation, "limitation")

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CrossRepositoryAlignment":
        expected = {
            "left_support_sha256",
            "right_support_sha256",
            "mapping_sha256",
            "algorithm_contract_sha256",
            "status",
            "evidence_sha256",
            "limitation",
        }
        if set(payload) != expected:
            raise MotifProvenanceError("alignment fields are not canonical")
        return cls(**payload)


@dataclasses.dataclass(frozen=True, slots=True)
class MotifProvenance:
    schema: str
    motif_id: str
    supports: tuple[MotifSupport, ...]
    alignments: tuple[CrossRepositoryAlignment, ...]
    invariant_sha256s: tuple[str, ...]
    negative_example_sha256s: tuple[str, ...]
    evaluator_evidence_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != "daedalus-motif-provenance/1":
            raise MotifProvenanceError("unsupported motif provenance schema")
        if not _ID_RE.fullmatch(_text(self.motif_id, "motif_id")):
            raise MotifProvenanceError("motif_id must be lowercase kebab-case")
        if len(self.supports) < 2:
            raise MotifProvenanceError("motif provenance requires at least two supports")
        support_ids = tuple(item.repository_id for item in self.supports)
        if support_ids != tuple(sorted(set(support_ids))):
            raise MotifProvenanceError("supports must use unique sorted repository_id values")
        alignment_digests = tuple(item.digest for item in self.alignments)
        if alignment_digests != tuple(sorted(set(alignment_digests))):
            raise MotifProvenanceError("alignments must be unique and sorted by digest")
        support_digests = {item.digest: item for item in self.supports}
        for alignment in self.alignments:
            if alignment.left_support_sha256 not in support_digests or alignment.right_support_sha256 not in support_digests:
                raise MotifProvenanceError("alignment references an unknown support")
            left = support_digests[alignment.left_support_sha256]
            right = support_digests[alignment.right_support_sha256]
            if left.repository_id == right.repository_id:
                raise MotifProvenanceError("alignment must cross repository identities")
        _sorted_sha(self.invariant_sha256s, "invariant_sha256s")
        _sorted_sha(self.negative_example_sha256s, "negative_example_sha256s")
        _sorted_sha(self.evaluator_evidence_sha256s, "evaluator_evidence_sha256s")

    @property
    def blockers(self) -> tuple[str, ...]:
        verified = tuple(item for item in self.alignments if item.status == "verified")
        blockers: set[str] = set()
        if not verified:
            blockers.add("no-verified-cross-repository-alignment")
        participating = {
            digest
            for item in verified
            for digest in (item.left_support_sha256, item.right_support_sha256)
        }
        for support in self.supports:
            if support.digest not in participating:
                blockers.add(f"support-{support.repository_id}-unaligned")
        return tuple(sorted(blockers))

    @property
    def closed_for_gate2(self) -> bool:
        return not self.blockers

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "motif_id": self.motif_id,
            "supports": [item.to_dict() for item in self.supports],
            "alignments": [item.to_dict() for item in self.alignments],
            "invariant_sha256s": list(self.invariant_sha256s),
            "negative_example_sha256s": list(self.negative_example_sha256s),
            "evaluator_evidence_sha256s": list(self.evaluator_evidence_sha256s),
            "blockers": list(self.blockers),
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MotifProvenance":
        expected = {
            "schema",
            "motif_id",
            "supports",
            "alignments",
            "invariant_sha256s",
            "negative_example_sha256s",
            "evaluator_evidence_sha256s",
            "blockers",
        }
        if set(payload) != expected:
            raise MotifProvenanceError("motif provenance fields are not canonical")
        arrays = tuple(payload[key] for key in (
            "supports",
            "alignments",
            "invariant_sha256s",
            "negative_example_sha256s",
            "evaluator_evidence_sha256s",
            "blockers",
        ))
        if not all(isinstance(value, list) for value in arrays):
            raise MotifProvenanceError("motif provenance collection fields must be arrays")
        motif = cls(
            schema=payload["schema"],
            motif_id=payload["motif_id"],
            supports=tuple(MotifSupport.from_dict(item) for item in payload["supports"]),
            alignments=tuple(CrossRepositoryAlignment.from_dict(item) for item in payload["alignments"]),
            invariant_sha256s=tuple(payload["invariant_sha256s"]),
            negative_example_sha256s=tuple(payload["negative_example_sha256s"]),
            evaluator_evidence_sha256s=tuple(payload["evaluator_evidence_sha256s"]),
        )
        if tuple(payload["blockers"]) != motif.blockers:
            raise MotifProvenanceError("blockers must be mechanically derived")
        return motif

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "MotifProvenance":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MotifProvenanceError("motif provenance must be valid UTF-8 JSON") from exc
        if not isinstance(decoded, Mapping):
            raise MotifProvenanceError("motif provenance root must be an object")
        motif = cls.from_dict(decoded)
        if payload != motif.to_json_bytes():
            raise MotifProvenanceError("motif provenance bytes must be canonical JSON plus one newline")
        return motif


__all__ = [
    "CrossRepositoryAlignment",
    "MotifProvenance",
    "MotifProvenanceError",
    "MotifSupport",
]

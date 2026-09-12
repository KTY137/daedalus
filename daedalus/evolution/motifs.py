"""Cross-repository motif provenance owned by the canonical evolution boundary.

This module selectively ports the useful evidence invariants from the historical
``daedalus.twin.motifs`` experiment.  It deliberately does not add a registry,
store, graph authority, evaluator, promotion path, or Gate-2 closure mechanism.
Project Twin/Forest artifacts remain authoritative; motifs only reference exact
supports and evidence about their relationship.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar, Mapping

from daedalus.kernel.contracts.base import (
    CanonicalContract,
    ContractProvenance,
    _non_empty,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)


_LOWER_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SPDX_RE = re.compile(r"^[A-Za-z0-9.+-]+$")
_ALIGNMENT_STATES = frozenset({"verified", "rejected"})


def _lower_kebab(value: Any, name: str) -> str:
    text = _non_empty(value, name, max_length=200)
    if not _LOWER_KEBAB_RE.fullmatch(text):
        raise ValueError(f"{name} must be lowercase kebab-case")
    return text


@dataclass(frozen=True)
class MotifSupport(CanonicalContract):
    """One license-audited, revision-exact Project-Twin support."""

    CONTRACT_TYPE: ClassVar[str] = "evolution.motif-support"

    repository_id: str
    source_revision: str
    project_twin_manifest_sha256: str
    subgraph_sha256: str
    license_spdx: str
    extractor_contract_sha256: str
    evidence_sha256: str
    temporal_cutoff: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_id", _lower_kebab(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        for field in (
            "project_twin_manifest_sha256",
            "subgraph_sha256",
            "extractor_contract_sha256",
            "evidence_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        license_spdx = _non_empty(self.license_spdx, "license_spdx", max_length=100)
        if not _SPDX_RE.fullmatch(license_spdx):
            raise ValueError("license_spdx must be one canonical SPDX identifier")
        object.__setattr__(self, "license_spdx", license_spdx)
        object.__setattr__(
            self,
            "temporal_cutoff",
            _utc_timestamp(self.temporal_cutoff, "temporal_cutoff"),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MotifSupport":
        return cls(**cls._contract_payload(payload))


@dataclass(frozen=True)
class CrossRepositoryAlignment(CanonicalContract):
    """Evidence for one verified or rejected alignment between two supports."""

    CONTRACT_TYPE: ClassVar[str] = "evolution.cross-repository-alignment"

    left_support_sha256: str
    right_support_sha256: str
    mapping_sha256: str
    algorithm_contract_sha256: str
    status: str
    evidence_sha256: str | None = None
    limitation: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "left_support_sha256",
            "right_support_sha256",
            "mapping_sha256",
            "algorithm_contract_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if self.left_support_sha256 == self.right_support_sha256:
            raise ValueError("alignment must connect two distinct supports")
        if self.left_support_sha256 > self.right_support_sha256:
            raise ValueError("alignment support digests must use canonical order")
        if self.status not in _ALIGNMENT_STATES:
            raise ValueError("status must be 'verified' or 'rejected'")
        if self.status == "verified":
            object.__setattr__(
                self,
                "evidence_sha256",
                _sha256(self.evidence_sha256, "evidence_sha256"),
            )
            if self.limitation is not None:
                raise ValueError(
                    "verified alignment must not carry a rejection limitation"
                )
        else:
            if self.evidence_sha256 is not None:
                raise ValueError("rejected alignment must not carry success evidence")
            object.__setattr__(
                self,
                "limitation",
                _non_empty(self.limitation, "limitation", max_length=2000),
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CrossRepositoryAlignment":
        return cls(**cls._contract_payload(payload))


@dataclass(frozen=True)
class MotifProvenance(CanonicalContract):
    """Evidence-bound cross-repository motif with no gate/promotion authority."""

    CONTRACT_TYPE: ClassVar[str] = "evolution.motif-provenance"

    motif_id: str
    supports: tuple[MotifSupport, ...]
    alignments: tuple[CrossRepositoryAlignment, ...]
    invariant_sha256s: tuple[str, ...]
    negative_example_sha256s: tuple[str, ...]
    evaluator_evidence_sha256s: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "motif_id", _lower_kebab(self.motif_id, "motif_id"))
        if len(self.supports) < 2:
            raise ValueError("motif provenance requires at least two supports")
        if any(type(item) is not MotifSupport for item in self.supports):
            raise ValueError("supports must contain MotifSupport records")
        support_ids = tuple(item.repository_id for item in self.supports)
        if support_ids != tuple(sorted(set(support_ids))):
            raise ValueError("supports must use unique sorted repository_id values")

        if any(type(item) is not CrossRepositoryAlignment for item in self.alignments):
            raise ValueError(
                "alignments must contain CrossRepositoryAlignment records"
            )
        alignment_digests = tuple(item.digest for item in self.alignments)
        if alignment_digests != tuple(sorted(set(alignment_digests))):
            raise ValueError("alignments must be unique and sorted by digest")

        support_by_digest = {item.digest: item for item in self.supports}
        for alignment in self.alignments:
            try:
                left = support_by_digest[alignment.left_support_sha256]
                right = support_by_digest[alignment.right_support_sha256]
            except KeyError as exc:
                raise ValueError("alignment references an unknown support") from exc
            if left.repository_id == right.repository_id:
                raise ValueError("alignment must cross repository identities")

        for field in (
            "invariant_sha256s",
            "negative_example_sha256s",
            "evaluator_evidence_sha256s",
        ):
            values = _sorted_strings(getattr(self, field), field, digests=True)
            if not values:
                raise ValueError(f"{field} must not be empty")
            object.__setattr__(self, field, values)

        if type(self.provenance) is not ContractProvenance:
            raise ValueError("provenance must be a ContractProvenance record")
        referenced = (
            tuple(item.digest for item in self.supports)
            + alignment_digests
            + self.invariant_sha256s
            + self.negative_example_sha256s
            + self.evaluator_evidence_sha256s
        )
        _require_provenance_inputs(self.provenance, referenced, "motif provenance")

    @property
    def evidence_gaps(self) -> tuple[str, ...]:
        """Evidence incompleteness only; an empty result grants no authority."""

        verified = tuple(item for item in self.alignments if item.status == "verified")
        gaps: set[str] = set()
        if not verified:
            gaps.add("no-verified-cross-repository-alignment")

        repository_by_digest = {
            support.digest: support.repository_id for support in self.supports
        }
        statuses_by_pair: dict[tuple[str, str], set[str]] = {}
        for alignment in self.alignments:
            pair = (alignment.left_support_sha256, alignment.right_support_sha256)
            statuses_by_pair.setdefault(pair, set()).add(alignment.status)
        for (left_digest, right_digest), statuses in statuses_by_pair.items():
            if len(statuses) > 1:
                left_repository, right_repository = sorted(
                    (
                        repository_by_digest[left_digest],
                        repository_by_digest[right_digest],
                    )
                )
                gaps.add(
                    "conflicting-alignment-status-"
                    f"{left_repository}-{right_repository}"
                )

        participating = {
            digest
            for item in verified
            for digest in (item.left_support_sha256, item.right_support_sha256)
        }
        for support in self.supports:
            if support.digest not in participating:
                gaps.add(f"support-{support.repository_id}-unaligned")

        if verified and len(participating) == len(self.supports):
            adjacency = {support.digest: set() for support in self.supports}
            for alignment in verified:
                adjacency[alignment.left_support_sha256].add(
                    alignment.right_support_sha256
                )
                adjacency[alignment.right_support_sha256].add(
                    alignment.left_support_sha256
                )

            pending = [self.supports[0].digest]
            reached: set[str] = set()
            while pending:
                digest = pending.pop()
                if digest in reached:
                    continue
                reached.add(digest)
                pending.extend(adjacency[digest] - reached)
            if len(reached) != len(self.supports):
                gaps.add("verified-alignment-graph-disconnected")

        return tuple(sorted(gaps))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "motif_id": self.motif_id,
            "supports": [item.to_dict() for item in self.supports],
            "alignments": [item.to_dict() for item in self.alignments],
            "invariant_sha256s": list(self.invariant_sha256s),
            "negative_example_sha256s": list(self.negative_example_sha256s),
            "evaluator_evidence_sha256s": list(self.evaluator_evidence_sha256s),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MotifProvenance":
        body = cls._contract_payload(payload)
        body["supports"] = tuple(
            MotifSupport.from_dict(item) for item in body["supports"]
        )
        body["alignments"] = tuple(
            CrossRepositoryAlignment.from_dict(item) for item in body["alignments"]
        )
        body["invariant_sha256s"] = tuple(body["invariant_sha256s"])
        body["negative_example_sha256s"] = tuple(body["negative_example_sha256s"])
        body["evaluator_evidence_sha256s"] = tuple(
            body["evaluator_evidence_sha256s"]
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


__all__ = [
    "CrossRepositoryAlignment",
    "MotifProvenance",
    "MotifSupport",
]

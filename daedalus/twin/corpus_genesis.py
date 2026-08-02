"""Bind revision-pinned corpus policy to one exact Genesis result.

This module does not upgrade repository review or extractor capability claims.
It creates a deterministic, fail-closed envelope around the existing Project
Twin manifest, Genesis receipt, EvidencePacket identity, corpus manifest and
capability matrix so none of those authorities can be substituted later.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any, Mapping

from daedalus.schemas import _revision, _sha256
from daedalus.twin.capabilities import CapabilityMatrix
from daedalus.twin.corpus import CorpusManifest, CorpusRepository
from daedalus.twin.genesis import (
    GenesisCompileReceipt,
    ProjectTwinManifest,
    verify_genesis_receipt,
)

_SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class CorpusGenesisBindingError(ValueError):
    """Raised when corpus policy and Genesis identity are not exactly bound."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _repository_digest(repository: CorpusRepository) -> str:
    return hashlib.sha256(_canonical_json(repository.to_dict())).hexdigest()


def _find_repository(manifest: CorpusManifest, repository_id: str) -> CorpusRepository:
    matches = tuple(
        repository
        for repository in manifest.repositories
        if repository.repository_id == repository_id
    )
    if len(matches) != 1:
        raise CorpusGenesisBindingError(
            "repository_id must identify exactly one corpus repository"
        )
    return matches[0]


def _matrix_language_ids(matrix: CapabilityMatrix) -> frozenset[str]:
    return frozenset(profile.language_id for profile in matrix.profiles)


@dataclasses.dataclass(frozen=True, slots=True)
class CorpusGenesisBinding:
    """Content-addressed binding for one corpus-governed Genesis result."""

    repository_id: str
    source_revision: str
    project_twin_manifest_sha256: str
    genesis_receipt_sha256: str
    evidence_packet_sha256: str
    corpus_manifest_sha256: str
    corpus_repository_sha256: str
    capability_matrix_sha256: str
    review_state: str
    review_evidence: str | None
    language_ids: tuple[str, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.repository_id, str) or not self.repository_id.strip():
            raise CorpusGenesisBindingError("repository_id must be non-empty")
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        for field in (
            "project_twin_manifest_sha256",
            "genesis_receipt_sha256",
            "evidence_packet_sha256",
            "corpus_manifest_sha256",
            "corpus_repository_sha256",
            "capability_matrix_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if self.review_state not in {"declared", "reviewed", "rejected"}:
            raise CorpusGenesisBindingError("unsupported review_state")
        if self.review_state == "reviewed":
            if not isinstance(self.review_evidence, str) or not _SHA256_REF_RE.fullmatch(
                self.review_evidence
            ):
                raise CorpusGenesisBindingError(
                    "reviewed binding requires sha256 review_evidence"
                )
        elif self.review_evidence is not None:
            raise CorpusGenesisBindingError(
                "review_evidence is allowed only for reviewed bindings"
            )
        if not self.language_ids:
            raise CorpusGenesisBindingError("language_ids must not be empty")
        if self.language_ids != tuple(sorted(set(self.language_ids))):
            raise CorpusGenesisBindingError("language_ids must be unique and sorted")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise CorpusGenesisBindingError("blockers must be unique and sorted")
        expected_review_blocker = f"corpus-review-{self.review_state}"
        if self.review_state == "reviewed":
            if any(blocker.startswith("corpus-review-") for blocker in self.blockers):
                raise CorpusGenesisBindingError(
                    "reviewed bindings must not retain a corpus review blocker"
                )
        elif expected_review_blocker not in self.blockers:
            raise CorpusGenesisBindingError(
                "non-reviewed bindings must retain their corpus review blocker"
            )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    @property
    def closed_for_gate2(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-corpus-genesis-binding/1",
            "repository_id": self.repository_id,
            "source_revision": self.source_revision,
            "project_twin_manifest_sha256": self.project_twin_manifest_sha256,
            "genesis_receipt_sha256": self.genesis_receipt_sha256,
            "evidence_packet_sha256": self.evidence_packet_sha256,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "corpus_repository_sha256": self.corpus_repository_sha256,
            "capability_matrix_sha256": self.capability_matrix_sha256,
            "review_state": self.review_state,
            "review_evidence": self.review_evidence,
            "language_ids": list(self.language_ids),
            "blockers": list(self.blockers),
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CorpusGenesisBinding":
        expected = {
            "schema",
            "repository_id",
            "source_revision",
            "project_twin_manifest_sha256",
            "genesis_receipt_sha256",
            "evidence_packet_sha256",
            "corpus_manifest_sha256",
            "corpus_repository_sha256",
            "capability_matrix_sha256",
            "review_state",
            "review_evidence",
            "language_ids",
            "blockers",
        }
        if set(payload) != expected:
            raise CorpusGenesisBindingError("binding fields are not canonical")
        if payload.get("schema") != "daedalus-corpus-genesis-binding/1":
            raise CorpusGenesisBindingError("unsupported corpus Genesis binding schema")
        language_ids = payload.get("language_ids")
        blockers = payload.get("blockers")
        if not isinstance(language_ids, list) or not isinstance(blockers, list):
            raise CorpusGenesisBindingError("language_ids and blockers must be arrays")
        return cls(
            repository_id=payload["repository_id"],
            source_revision=payload["source_revision"],
            project_twin_manifest_sha256=payload["project_twin_manifest_sha256"],
            genesis_receipt_sha256=payload["genesis_receipt_sha256"],
            evidence_packet_sha256=payload["evidence_packet_sha256"],
            corpus_manifest_sha256=payload["corpus_manifest_sha256"],
            corpus_repository_sha256=payload["corpus_repository_sha256"],
            capability_matrix_sha256=payload["capability_matrix_sha256"],
            review_state=payload["review_state"],
            review_evidence=payload["review_evidence"],
            language_ids=tuple(language_ids),
            blockers=tuple(blockers),
        )

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "CorpusGenesisBinding":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CorpusGenesisBindingError(
                "binding must be valid UTF-8 JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise CorpusGenesisBindingError("binding root must be an object")
        binding = cls.from_dict(decoded)
        if payload != binding.to_json_bytes():
            raise CorpusGenesisBindingError(
                "binding bytes must be canonical JSON plus one newline"
            )
        return binding


def bind_corpus_genesis(
    *,
    manifest: ProjectTwinManifest,
    receipt: GenesisCompileReceipt,
    corpus_manifest: CorpusManifest,
    capability_matrix: CapabilityMatrix,
) -> CorpusGenesisBinding:
    """Construct and verify the exact corpus policy binding for a Genesis run."""
    verify_genesis_receipt(manifest, receipt)
    repository = _find_repository(corpus_manifest, manifest.repository_id)
    if repository.source_revision != manifest.source_revision:
        raise CorpusGenesisBindingError(
            "corpus source_revision does not match Project Twin source_revision"
        )
    expected_corpus_ref = f"sha256:{corpus_manifest.digest}"
    if capability_matrix.corpus_manifest_digest != expected_corpus_ref:
        raise CorpusGenesisBindingError(
            "capability matrix does not bind the exact corpus manifest"
        )
    missing_languages = set(repository.language_ids) - _matrix_language_ids(
        capability_matrix
    )
    if missing_languages:
        raise CorpusGenesisBindingError(
            "capability matrix does not cover repository languages: "
            + ", ".join(sorted(missing_languages))
        )
    blockers = list(capability_matrix.blockers)
    if repository.review_state != "reviewed":
        blockers.append(f"corpus-review-{repository.review_state}")
    binding = CorpusGenesisBinding(
        repository_id=manifest.repository_id,
        source_revision=manifest.source_revision,
        project_twin_manifest_sha256=manifest.digest,
        genesis_receipt_sha256=receipt.digest,
        evidence_packet_sha256=manifest.evidence_packet_sha256,
        corpus_manifest_sha256=corpus_manifest.digest,
        corpus_repository_sha256=_repository_digest(repository),
        capability_matrix_sha256=capability_matrix.digest,
        review_state=repository.review_state,
        review_evidence=repository.review_evidence,
        language_ids=repository.language_ids,
        blockers=tuple(sorted(set(blockers))),
    )
    verify_corpus_genesis_binding(
        binding=binding,
        manifest=manifest,
        receipt=receipt,
        corpus_manifest=corpus_manifest,
        capability_matrix=capability_matrix,
    )
    return binding


def verify_corpus_genesis_binding(
    *,
    binding: CorpusGenesisBinding,
    manifest: ProjectTwinManifest,
    receipt: GenesisCompileReceipt,
    corpus_manifest: CorpusManifest,
    capability_matrix: CapabilityMatrix,
) -> None:
    """Refuse replay or substitution across any bound authority."""
    expected = bind_corpus_genesis_unverified(
        manifest=manifest,
        receipt=receipt,
        corpus_manifest=corpus_manifest,
        capability_matrix=capability_matrix,
    )
    if binding != expected:
        raise CorpusGenesisBindingError(
            "corpus Genesis binding does not match supplied authorities"
        )


def bind_corpus_genesis_unverified(
    *,
    manifest: ProjectTwinManifest,
    receipt: GenesisCompileReceipt,
    corpus_manifest: CorpusManifest,
    capability_matrix: CapabilityMatrix,
) -> CorpusGenesisBinding:
    """Internal constructor used by verification without recursive verification."""
    verify_genesis_receipt(manifest, receipt)
    repository = _find_repository(corpus_manifest, manifest.repository_id)
    if repository.source_revision != manifest.source_revision:
        raise CorpusGenesisBindingError(
            "corpus source_revision does not match Project Twin source_revision"
        )
    if capability_matrix.corpus_manifest_digest != f"sha256:{corpus_manifest.digest}":
        raise CorpusGenesisBindingError(
            "capability matrix does not bind the exact corpus manifest"
        )
    missing_languages = set(repository.language_ids) - _matrix_language_ids(
        capability_matrix
    )
    if missing_languages:
        raise CorpusGenesisBindingError(
            "capability matrix does not cover repository languages: "
            + ", ".join(sorted(missing_languages))
        )
    blockers = list(capability_matrix.blockers)
    if repository.review_state != "reviewed":
        blockers.append(f"corpus-review-{repository.review_state}")
    return CorpusGenesisBinding(
        repository_id=manifest.repository_id,
        source_revision=manifest.source_revision,
        project_twin_manifest_sha256=manifest.digest,
        genesis_receipt_sha256=receipt.digest,
        evidence_packet_sha256=manifest.evidence_packet_sha256,
        corpus_manifest_sha256=corpus_manifest.digest,
        corpus_repository_sha256=_repository_digest(repository),
        capability_matrix_sha256=capability_matrix.digest,
        review_state=repository.review_state,
        review_evidence=repository.review_evidence,
        language_ids=repository.language_ids,
        blockers=tuple(sorted(set(blockers))),
    )


__all__ = [
    "CorpusGenesisBinding",
    "CorpusGenesisBindingError",
    "bind_corpus_genesis",
    "verify_corpus_genesis_binding",
]

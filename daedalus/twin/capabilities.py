from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any, Mapping

_CAPABILITIES = (
    "behavioral_validation",
    "cross_plane_bindings",
    "data_schema",
    "discovery",
    "knowledge_links",
    "symbols",
    "syntax",
    "types",
)
_STATES = frozenset({"complete", "partial", "unsupported", "failed"})
_SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CapabilityMatrixError(ValueError):
    """Raised when capability evidence is malformed, overstated, or noncanonical."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityMatrixError(f"{field} must be a non-empty string")
    return value


@dataclasses.dataclass(frozen=True, slots=True)
class CapabilityClaim:
    capability: str
    state: str
    evidence: str | None
    limitation: str | None

    def __post_init__(self) -> None:
        if self.capability not in _CAPABILITIES:
            raise CapabilityMatrixError(f"unknown capability: {self.capability!r}")
        if self.state not in _STATES:
            raise CapabilityMatrixError(f"unknown capability state: {self.state!r}")
        if self.state in {"complete", "partial"}:
            if not isinstance(self.evidence, str) or not _SHA256_REF_RE.fullmatch(self.evidence):
                raise CapabilityMatrixError("complete and partial claims require sha256 evidence")
        elif self.evidence is not None:
            raise CapabilityMatrixError("unsupported and failed claims must not carry success evidence")
        if self.state in {"partial", "unsupported", "failed"}:
            _text(self.limitation, "limitation")
        elif self.limitation is not None:
            raise CapabilityMatrixError("complete claims must not carry a limitation")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityClaim":
        if set(value) != {"capability", "state", "evidence", "limitation"}:
            raise CapabilityMatrixError("capability claim fields are not canonical")
        return cls(
            capability=value["capability"],
            state=value["state"],
            evidence=value["evidence"],
            limitation=value["limitation"],
        )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True, slots=True)
class LanguageCapabilityProfile:
    language_id: str
    extractor_contract: str
    claims: tuple[CapabilityClaim, ...]

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(_text(self.language_id, "language_id")):
            raise CapabilityMatrixError("language_id must be lowercase kebab-case")
        if not _SHA256_REF_RE.fullmatch(_text(self.extractor_contract, "extractor_contract")):
            raise CapabilityMatrixError("extractor_contract must be a sha256 reference")
        names = tuple(claim.capability for claim in self.claims)
        if names != _CAPABILITIES:
            raise CapabilityMatrixError("claims must contain every capability exactly once in canonical order")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LanguageCapabilityProfile":
        if set(value) != {"language_id", "extractor_contract", "claims"}:
            raise CapabilityMatrixError("language capability fields are not canonical")
        claims = value["claims"]
        if not isinstance(claims, list):
            raise CapabilityMatrixError("claims must be an array")
        return cls(
            language_id=value["language_id"],
            extractor_contract=value["extractor_contract"],
            claims=tuple(CapabilityClaim.from_dict(item) for item in claims),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "language_id": self.language_id,
            "extractor_contract": self.extractor_contract,
            "claims": [claim.to_dict() for claim in self.claims],
        }


@dataclasses.dataclass(frozen=True, slots=True)
class CapabilityMatrix:
    schema: str
    corpus_manifest_digest: str
    profiles: tuple[LanguageCapabilityProfile, ...]

    def __post_init__(self) -> None:
        if self.schema != "daedalus-capability-matrix/1":
            raise CapabilityMatrixError("unsupported capability matrix schema")
        if not _SHA256_REF_RE.fullmatch(_text(self.corpus_manifest_digest, "corpus_manifest_digest")):
            raise CapabilityMatrixError("corpus_manifest_digest must be a sha256 reference")
        if not self.profiles:
            raise CapabilityMatrixError("profiles must not be empty")
        language_ids = tuple(profile.language_id for profile in self.profiles)
        if language_ids != tuple(sorted(set(language_ids))):
            raise CapabilityMatrixError("profiles must be unique and sorted by language_id")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for profile in self.profiles:
            for claim in profile.claims:
                if claim.state == "failed":
                    blockers.append(f"{profile.language_id}:{claim.capability}:failed")
        return tuple(blockers)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityMatrix":
        if set(value) != {"schema", "corpus_manifest_digest", "profiles"}:
            raise CapabilityMatrixError("capability matrix fields are not canonical")
        profiles = value["profiles"]
        if not isinstance(profiles, list):
            raise CapabilityMatrixError("profiles must be an array")
        return cls(
            schema=value["schema"],
            corpus_manifest_digest=value["corpus_manifest_digest"],
            profiles=tuple(LanguageCapabilityProfile.from_dict(item) for item in profiles),
        )

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "CapabilityMatrix":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CapabilityMatrixError("capability matrix must be valid UTF-8 JSON") from exc
        if not isinstance(decoded, dict):
            raise CapabilityMatrixError("capability matrix root must be an object")
        matrix = cls.from_dict(decoded)
        if payload != matrix.to_json_bytes():
            raise CapabilityMatrixError("capability matrix bytes must be canonical JSON plus one newline")
        return matrix

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "corpus_manifest_digest": self.corpus_manifest_digest,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

"""Language-neutral contracts for bounded Fourfold extractor adapters.

These records describe extractor capability and output. They do not make
extractor output authoritative: publication into a KnowledgeForest or
FourfoldSnapshot remains a separate verification boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_STATUSES = frozenset({"complete", "partial", "unsupported", "failed"})
_ALLOWED_SEVERITIES = frozenset({"info", "warning", "error"})
_ALLOWED_ARTIFACT_KINDS = frozenset({"text", "binary", "configuration"})


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase stable identifier")
    return value


def _non_empty(value: str, name: str, *, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty bounded string without NUL")
    return value


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _sorted_unique(values: Iterable[str], name: str, *, identifiers: bool = False) -> tuple[str, ...]:
    converted = tuple(values)
    if any(not isinstance(item, str) for item in converted):
        raise ValueError(f"{name} must contain strings")
    if identifiers:
        converted = tuple(_identifier(item, f"{name} item") for item in converted)
    elif any(not item or "\x00" in item for item in converted):
        raise ValueError(f"{name} must contain non-empty strings without NUL")
    if len(set(converted)) != len(converted):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(converted))


@dataclass(frozen=True)
class LanguageSpec:
    """Stable language or data-format identity used by discovery and adapters."""

    language_id: str
    extensions: tuple[str, ...]
    artifact_kind: str
    semantic_planes: tuple[str, ...]
    framework_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "language_id", _identifier(self.language_id, "language_id"))
        if self.artifact_kind not in _ALLOWED_ARTIFACT_KINDS:
            raise ValueError(f"artifact_kind must be one of {sorted(_ALLOWED_ARTIFACT_KINDS)}")
        extensions = tuple(self.extensions)
        if not extensions or any(not isinstance(ext, str) or not ext.startswith(".") for ext in extensions):
            raise ValueError("extensions must contain dotted suffixes")
        if len(set(extensions)) != len(extensions):
            raise ValueError("extensions must not contain duplicates")
        object.__setattr__(self, "extensions", tuple(sorted(extensions)))
        planes = _sorted_unique(self.semantic_planes, "semantic_planes", identifiers=True)
        if not set(planes).issubset({"code", "type", "data", "knowledge"}):
            raise ValueError("semantic_planes contains an unknown Fourfold plane")
        object.__setattr__(self, "semantic_planes", planes)
        object.__setattr__(
            self,
            "framework_hints",
            _sorted_unique(self.framework_hints, "framework_hints", identifiers=True),
        )


@dataclass(frozen=True)
class SourceArtifact:
    """One immutable source-bundle member supplied to an extractor."""

    repository_id: str
    source_revision: str
    path: str
    content_sha256: str
    size_bytes: int
    language_id: str
    artifact_kind: str
    framework_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _identifier(self.repository_id, "repository_id"))
        object.__setattr__(self, "source_revision", _non_empty(self.source_revision, "source_revision", limit=512))
        path = _non_empty(self.path, "path")
        if path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")):
            raise ValueError("path must be a normalized repository-relative POSIX path")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "content_sha256", _digest(self.content_sha256, "content_sha256"))
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        object.__setattr__(self, "language_id", _identifier(self.language_id, "language_id"))
        if self.artifact_kind not in _ALLOWED_ARTIFACT_KINDS:
            raise ValueError(f"artifact_kind must be one of {sorted(_ALLOWED_ARTIFACT_KINDS)}")
        object.__setattr__(
            self,
            "framework_hints",
            _sorted_unique(self.framework_hints, "framework_hints", identifiers=True),
        )


@dataclass(frozen=True)
class ExtractorCapabilities:
    """Versioned declaration of what an extractor can actually establish."""

    extractor_id: str
    version: str
    languages: tuple[str, ...]
    emitted_node_kinds: tuple[str, ...]
    emitted_relation_kinds: tuple[str, ...]
    deterministic: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "extractor_id", _identifier(self.extractor_id, "extractor_id"))
        object.__setattr__(self, "version", _non_empty(self.version, "version", limit=128))
        object.__setattr__(self, "languages", _sorted_unique(self.languages, "languages", identifiers=True))
        if not self.languages:
            raise ValueError("languages must not be empty")
        object.__setattr__(
            self,
            "emitted_node_kinds",
            _sorted_unique(self.emitted_node_kinds, "emitted_node_kinds", identifiers=True),
        )
        object.__setattr__(
            self,
            "emitted_relation_kinds",
            _sorted_unique(self.emitted_relation_kinds, "emitted_relation_kinds", identifiers=True),
        )
        if not isinstance(self.deterministic, bool):
            raise ValueError("deterministic must be boolean")


@dataclass(frozen=True)
class ExtractorDiagnostic:
    code: str
    severity: str
    message: str
    path: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _identifier(self.code, "diagnostic.code"))
        if self.severity not in _ALLOWED_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(_ALLOWED_SEVERITIES)}")
        object.__setattr__(self, "message", _non_empty(self.message, "diagnostic.message"))
        if self.path:
            object.__setattr__(self, "path", _non_empty(self.path, "diagnostic.path"))


@dataclass(frozen=True)
class ExtractorResult:
    """Staged extractor output; never an authoritative publication by itself."""

    extractor_id: str
    extractor_version: str
    source_revision: str
    source_bundle_sha256: str
    status: str
    node_ids: tuple[str, ...] = ()
    relation_sha256s: tuple[str, ...] = ()
    evidence_sha256s: tuple[str, ...] = ()
    diagnostics: tuple[ExtractorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "extractor_id", _identifier(self.extractor_id, "extractor_id"))
        object.__setattr__(self, "extractor_version", _non_empty(self.extractor_version, "extractor_version", limit=128))
        object.__setattr__(self, "source_revision", _non_empty(self.source_revision, "source_revision", limit=512))
        object.__setattr__(self, "source_bundle_sha256", _digest(self.source_bundle_sha256, "source_bundle_sha256"))
        if self.status not in _ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {sorted(_ALLOWED_STATUSES)}")
        object.__setattr__(self, "node_ids", _sorted_unique(self.node_ids, "node_ids"))
        object.__setattr__(
            self,
            "relation_sha256s",
            tuple(sorted(_digest(item, "relation_sha256s item") for item in self.relation_sha256s)),
        )
        object.__setattr__(
            self,
            "evidence_sha256s",
            tuple(sorted(_digest(item, "evidence_sha256s item") for item in self.evidence_sha256s)),
        )
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, ExtractorDiagnostic) for item in diagnostics):
            raise ValueError("diagnostics must contain ExtractorDiagnostic records")
        object.__setattr__(self, "diagnostics", diagnostics)

        if self.status == "complete":
            if not self.evidence_sha256s:
                raise ValueError("complete extractor output must retain evidence")
            if any(item.severity == "error" for item in diagnostics):
                raise ValueError("complete extractor output cannot contain error diagnostics")
        elif self.status == "partial":
            if not diagnostics:
                raise ValueError("partial extractor output must explain its limitation")
            if not self.evidence_sha256s:
                raise ValueError("partial extractor output must retain evidence")
        else:
            if self.node_ids or self.relation_sha256s or self.evidence_sha256s:
                raise ValueError(f"{self.status} extractor output cannot publish semantic content")
            if not diagnostics:
                raise ValueError(f"{self.status} extractor output must explain its state")

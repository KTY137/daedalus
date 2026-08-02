from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SPDX_RE = re.compile(r"^[A-Za-z0-9.+-]+$")
_ALLOWED_REVIEW_STATES = frozenset({"declared", "reviewed", "rejected"})


class CorpusManifestError(ValueError):
    """Raised when a corpus manifest is malformed or non-reproducible."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusManifestError(f"{field} must be a non-empty string")
    return value


def _normalized_relative_path(value: Any, field: str, *, allow_dot: bool = False) -> str:
    text = _require_text(value, field)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise CorpusManifestError(f"{field} must stay inside the repository")
    normalized = path.as_posix()
    if normalized == "." and not allow_dot:
        raise CorpusManifestError(f"{field} must name a repository-relative path")
    if normalized != text:
        raise CorpusManifestError(f"{field} must use canonical POSIX spelling")
    return normalized


@dataclasses.dataclass(frozen=True, slots=True)
class CorpusRepository:
    repository_id: str
    repository_url: str
    source_revision: str
    include_prefixes: tuple[str, ...]
    language_ids: tuple[str, ...]
    license_spdx: str
    license_path: str
    review_state: str
    review_evidence: str | None = None

    def __post_init__(self) -> None:
        repository_id = _require_text(self.repository_id, "repository_id")
        if repository_id != repository_id.lower() or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", repository_id):
            raise CorpusManifestError("repository_id must be lowercase kebab-case")

        parsed = urlparse(_require_text(self.repository_url, "repository_url"))
        if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.endswith(".git"):
            raise CorpusManifestError("repository_url must be an HTTPS github.com clone URL ending in .git")
        if parsed.params or parsed.query or parsed.fragment:
            raise CorpusManifestError("repository_url must not contain parameters, query, or fragment")

        if not _SHA1_RE.fullmatch(self.source_revision):
            raise CorpusManifestError("source_revision must be an exact lowercase 40-hex Git object ID")

        if not self.include_prefixes:
            raise CorpusManifestError("include_prefixes must not be empty")
        normalized_prefixes = tuple(
            _normalized_relative_path(value, "include_prefix", allow_dot=True) for value in self.include_prefixes
        )
        if normalized_prefixes != tuple(sorted(set(normalized_prefixes))):
            raise CorpusManifestError("include_prefixes must be unique and sorted")

        if not self.language_ids:
            raise CorpusManifestError("language_ids must not be empty")
        normalized_languages = tuple(_require_text(value, "language_id") for value in self.language_ids)
        if normalized_languages != tuple(sorted(set(normalized_languages))):
            raise CorpusManifestError("language_ids must be unique and sorted")

        if not _SPDX_RE.fullmatch(_require_text(self.license_spdx, "license_spdx")):
            raise CorpusManifestError("license_spdx must be one canonical SPDX identifier")
        _normalized_relative_path(self.license_path, "license_path")

        if self.review_state not in _ALLOWED_REVIEW_STATES:
            raise CorpusManifestError(f"review_state must be one of {sorted(_ALLOWED_REVIEW_STATES)}")
        if self.review_state == "reviewed":
            evidence = _require_text(self.review_evidence, "review_evidence")
            if not evidence.startswith("sha256:") or not re.fullmatch(r"sha256:[0-9a-f]{64}", evidence):
                raise CorpusManifestError("reviewed entries require sha256:<64 lowercase hex> review_evidence")
        elif self.review_evidence is not None:
            raise CorpusManifestError("review_evidence is allowed only for reviewed entries")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CorpusRepository":
        expected = {
            "repository_id",
            "repository_url",
            "source_revision",
            "include_prefixes",
            "language_ids",
            "license_spdx",
            "license_path",
            "review_state",
            "review_evidence",
        }
        unknown = set(value) - expected
        missing = expected - set(value)
        if unknown:
            raise CorpusManifestError(f"unknown repository fields: {sorted(unknown)}")
        if missing:
            raise CorpusManifestError(f"missing repository fields: {sorted(missing)}")
        prefixes = value["include_prefixes"]
        languages = value["language_ids"]
        if not isinstance(prefixes, list) or not isinstance(languages, list):
            raise CorpusManifestError("include_prefixes and language_ids must be arrays")
        return cls(
            repository_id=value["repository_id"],
            repository_url=value["repository_url"],
            source_revision=value["source_revision"],
            include_prefixes=tuple(prefixes),
            language_ids=tuple(languages),
            license_spdx=value["license_spdx"],
            license_path=value["license_path"],
            review_state=value["review_state"],
            review_evidence=value["review_evidence"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "repository_url": self.repository_url,
            "source_revision": self.source_revision,
            "include_prefixes": list(self.include_prefixes),
            "language_ids": list(self.language_ids),
            "license_spdx": self.license_spdx,
            "license_path": self.license_path,
            "review_state": self.review_state,
            "review_evidence": self.review_evidence,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class CorpusManifest:
    schema: str
    corpus_id: str
    repositories: tuple[CorpusRepository, ...]

    def __post_init__(self) -> None:
        if self.schema != "daedalus-corpus-manifest/1":
            raise CorpusManifestError("unsupported corpus manifest schema")
        corpus_id = _require_text(self.corpus_id, "corpus_id")
        if corpus_id != corpus_id.lower() or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", corpus_id):
            raise CorpusManifestError("corpus_id must be lowercase kebab-case")
        if not self.repositories:
            raise CorpusManifestError("repositories must not be empty")
        ids = tuple(item.repository_id for item in self.repositories)
        urls = tuple(item.repository_url for item in self.repositories)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise CorpusManifestError("repositories must be sorted by unique repository_id")
        if len(urls) != len(set(urls)):
            raise CorpusManifestError("repository_url values must be unique")

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()

    @property
    def closed_for_gate2(self) -> bool:
        return all(item.review_state == "reviewed" for item in self.repositories)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CorpusManifest":
        if set(value) != {"schema", "corpus_id", "repositories"}:
            raise CorpusManifestError("manifest fields must be exactly schema, corpus_id, and repositories")
        repositories = value["repositories"]
        if not isinstance(repositories, list):
            raise CorpusManifestError("repositories must be an array")
        return cls(
            schema=value["schema"],
            corpus_id=value["corpus_id"],
            repositories=tuple(CorpusRepository.from_dict(item) for item in repositories),
        )

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "CorpusManifest":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CorpusManifestError("manifest must be valid UTF-8 JSON") from exc
        if not isinstance(decoded, dict):
            raise CorpusManifestError("manifest root must be an object")
        manifest = cls.from_dict(decoded)
        if payload != _canonical_json(manifest.to_dict()) + b"\n":
            raise CorpusManifestError("manifest bytes must use canonical JSON plus one trailing newline")
        return manifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "corpus_id": self.corpus_id,
            "repositories": [item.to_dict() for item in self.repositories],
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"


def assert_expected_revisions(manifest: CorpusManifest, observed: Mapping[str, str]) -> None:
    expected = {item.repository_id: item.source_revision for item in manifest.repositories}
    if set(observed) != set(expected):
        raise CorpusManifestError("observed repository IDs do not match the manifest")
    stale = {repository_id: (expected[repository_id], revision) for repository_id, revision in observed.items() if expected[repository_id] != revision}
    if stale:
        raise CorpusManifestError(f"stale or substituted corpus revisions: {stale}")


def review_blockers(manifest: CorpusManifest) -> tuple[str, ...]:
    return tuple(
        f"{item.repository_id}:license-review-{item.review_state}"
        for item in manifest.repositories
        if item.review_state != "reviewed"
    )

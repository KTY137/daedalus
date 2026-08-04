"""Read-only content-addressed resolution for repository-write artifacts.

This module resolves one exact ``artifact-locator:sha256`` from a fixed local
CAS layout.  It is intentionally narrower than an artifact store: it cannot
publish, repair, fetch, delete, promote, or mutate repository state.  The
resolver binds the CAS root and source revision, proves that the root is
separate from the Primary Checkout, opens the exact derived object read-only,
and returns immutable bytes plus a canonical resolution receipt.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _artifact_locator,
    _identifier,
    _locator_sha256,
    _repo_path,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha

from .repository_write_evidence import RepositoryWriteArtifactEvidence


_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_RESOLUTION_CHECKS = (
    "bounded-read",
    "content-digest",
    "exact-cas-path",
    "file-identity",
    "primary-checkout-disjoint",
    "read-only-open",
)


class RepositoryWriteArtifactCASError(ValueError):
    """The CAS root, object identity, or resolved bytes failed closed."""


def _absolute_path(value: object, label: str) -> str:
    if isinstance(value, bool):
        raise RepositoryWriteArtifactCASError(f"{label} must be path-like")
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise RepositoryWriteArtifactCASError(f"{label} must be path-like") from exc
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    if not isinstance(raw, str) or not raw:
        raise RepositoryWriteArtifactCASError(f"{label} must be a non-empty path")
    if "\x00" in raw or "\n" in raw or "\r" in raw:
        raise RepositoryWriteArtifactCASError(
            f"{label} contains forbidden characters"
        )
    path = Path(raw)
    if not path.is_absolute():
        raise RepositoryWriteArtifactCASError(f"{label} must be absolute")
    return os.path.normpath(os.path.abspath(raw))


def _normal(value: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(value))))


def _real_directory(value: str, label: str) -> Path:
    lexical = Path(_absolute_path(value, label))
    if os.path.lexists(lexical) and lexical.is_symlink():
        raise RepositoryWriteArtifactCASError(f"{label} may not be a symlink")
    try:
        resolved = lexical.resolve(strict=True)
        result = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise RepositoryWriteArtifactCASError(
            f"{label} must be an existing directory"
        ) from exc
    if not stat.S_ISDIR(result.st_mode):
        raise RepositoryWriteArtifactCASError(f"{label} must be a directory")
    if _normal(lexical) != _normal(resolved):
        raise RepositoryWriteArtifactCASError(
            f"{label} may not traverse symlink components"
        )
    return resolved


def _is_within(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((_normal(child), _normal(parent))) == _normal(parent)
    except ValueError:
        return False


def _roots_overlap(first: Path, second: Path) -> bool:
    return _is_within(first, second) or _is_within(second, first)


def _non_negative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryWriteArtifactCASError(
            f"{label} must be a non-negative integer"
        )
    return value


@dataclass(frozen=True)
class RepositoryWriteArtifactCASRoot:
    """Exact revision-bound local CAS authority root."""

    path: str
    primary_checkout_root: str
    source_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _absolute_path(self.path, "path"))
        object.__setattr__(
            self,
            "primary_checkout_root",
            _absolute_path(self.primary_checkout_root, "primary_checkout_root"),
        )
        try:
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactCASError(
                "CAS root source revision is malformed"
            ) from exc
        cas_root = _real_directory(self.path, "path")
        primary_root = _real_directory(
            self.primary_checkout_root,
            "primary_checkout_root",
        )
        if _roots_overlap(cas_root, primary_root):
            raise RepositoryWriteArtifactCASError(
                "CAS root and Primary Checkout must be disjoint"
            )

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class RepositoryWriteArtifactResolutionReceipt(CanonicalContract):
    """Canonical proof that one exact local CAS object was read and hashed."""

    CONTRACT_TYPE: ClassVar[str] = (
        "daedalus-repository-write-artifact-resolution-receipt/1"
    )

    resolution_id: str
    source_revision: str
    source_tree_revision: str
    artifact_evidence_sha256: str
    locator: str
    artifact_content_sha256: str
    cas_root_sha256: str
    relative_path: str
    file_device: int
    file_inode: int
    file_size: int
    file_mtime_ns: int
    resolved_at: str
    checks: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "resolution_id",
                _identifier(self.resolution_id, "resolution_id"),
            )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            object.__setattr__(
                self,
                "source_tree_revision",
                _revision(self.source_tree_revision, "source_tree_revision"),
            )
            for field_name in (
                "artifact_evidence_sha256",
                "artifact_content_sha256",
                "cas_root_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "locator",
                _artifact_locator(self.locator, "locator"),
            )
            object.__setattr__(
                self,
                "relative_path",
                _repo_path(self.relative_path, "relative_path"),
            )
            for field_name in (
                "file_device",
                "file_inode",
                "file_size",
                "file_mtime_ns",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _non_negative_int(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "resolved_at",
                _utc_timestamp(self.resolved_at, "resolved_at"),
            )
            object.__setattr__(
                self,
                "checks",
                _sorted_strings(self.checks, "checks", identifiers=True),
            )
        except RepositoryWriteArtifactCASError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactCASError(
                "artifact resolution receipt is malformed"
            ) from exc
        if self.checks != _RESOLUTION_CHECKS:
            raise RepositoryWriteArtifactCASError(
                "artifact resolution checks are not exact"
            )
        if _locator_sha256(self.locator) != self.artifact_content_sha256:
            raise RepositoryWriteArtifactCASError(
                "artifact resolution locator contradicts content digest"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteArtifactCASError(
                "resolution provenance must be exact ContractProvenance"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteArtifactCASError(
                "resolution source revision contradicts provenance"
            )
        if self.provenance.created_at != self.resolved_at:
            raise RepositoryWriteArtifactCASError(
                "resolution time contradicts provenance"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.artifact_evidence_sha256,
                    self.artifact_content_sha256,
                    self.cas_root_sha256,
                ),
                "repository-write artifact resolution receipt",
            )
        except ValueError as exc:
            raise RepositoryWriteArtifactCASError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteArtifactResolutionReceipt":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteArtifactCASError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactCASError(
                "artifact resolution receipt payload is malformed"
            ) from exc


@dataclass(frozen=True)
class ResolvedRepositoryWriteArtifact:
    """Immutable bytes and the exact read-only resolution receipt."""

    content: bytes
    receipt: RepositoryWriteArtifactResolutionReceipt

    def __post_init__(self) -> None:
        if type(self.content) is not bytes:
            raise RepositoryWriteArtifactCASError(
                "resolved artifact content must be exact immutable bytes"
            )
        if type(self.receipt) is not RepositoryWriteArtifactResolutionReceipt:
            raise RepositoryWriteArtifactCASError(
                "resolved artifact receipt must be exact resolution receipt"
            )
        if hashlib.sha256(self.content).hexdigest() != self.receipt.artifact_content_sha256:
            raise RepositoryWriteArtifactCASError(
                "resolved artifact bytes contradict resolution receipt"
            )


def artifact_relative_path(locator: str) -> str:
    """Return the sole accepted local CAS path for one locator."""

    try:
        digest = _locator_sha256(_artifact_locator(locator, "locator"))
    except (TypeError, ValueError) as exc:
        raise RepositoryWriteArtifactCASError(
            "artifact locator is malformed"
        ) from exc
    return f"sha256/{digest[:2]}/{digest[2:]}"


def _exact_artifact_file(
    root: RepositoryWriteArtifactCASRoot,
    artifact: RepositoryWriteArtifactEvidence,
) -> tuple[Path, os.stat_result, str]:
    if type(root) is not RepositoryWriteArtifactCASRoot:
        raise RepositoryWriteArtifactCASError(
            "root must be exact RepositoryWriteArtifactCASRoot"
        )
    if type(artifact) is not RepositoryWriteArtifactEvidence:
        raise RepositoryWriteArtifactCASError(
            "artifact must be exact RepositoryWriteArtifactEvidence"
        )
    if artifact.source_revision != root.source_revision:
        raise RepositoryWriteArtifactCASError(
            "artifact and CAS root source revisions differ"
        )
    cas_root = _real_directory(root.path, "path")
    primary_root = _real_directory(
        root.primary_checkout_root,
        "primary_checkout_root",
    )
    if _roots_overlap(cas_root, primary_root):
        raise RepositoryWriteArtifactCASError(
            "CAS root and Primary Checkout must remain disjoint"
        )
    relative = artifact_relative_path(artifact.locator)
    candidate = cas_root.joinpath(*relative.split("/"))
    if _is_within(candidate, primary_root):
        raise RepositoryWriteArtifactCASError(
            "artifact object may not be inside the Primary Checkout"
        )
    parent = candidate.parent
    try:
        resolved_parent = parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryWriteArtifactCASError(
            "artifact CAS shard directory is missing"
        ) from exc
    if _normal(parent) != _normal(resolved_parent) or not resolved_parent.is_dir():
        raise RepositoryWriteArtifactCASError(
            "artifact CAS shard may not traverse symlink components"
        )
    if not os.path.lexists(candidate):
        raise RepositoryWriteArtifactCASError("artifact CAS object is missing")
    if candidate.is_symlink():
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object may not be a symlink"
        )
    try:
        resolved = candidate.resolve(strict=True)
        before = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object is unavailable"
        ) from exc
    if _normal(candidate) != _normal(resolved):
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object path may not be redirected"
        )
    if not stat.S_ISREG(before.st_mode):
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object must be a regular file"
        )
    if before.st_nlink != 1:
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object may not have hard-link aliases"
        )
    if before.st_size < 1 or before.st_size > _MAX_ARTIFACT_BYTES:
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object size is invalid"
        )
    return resolved, before, relative


def _read_exact_file(path: Path, before: os.stat_result) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RepositoryWriteArtifactCASError(
                "opened artifact CAS object is not a regular file"
            )
        if opened.st_nlink != 1:
            raise RepositoryWriteArtifactCASError(
                "opened artifact CAS object has hard-link aliases"
            )
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise RepositoryWriteArtifactCASError(
                "artifact CAS object changed before read"
            )
        chunks: list[bytes] = []
        remaining = _MAX_ARTIFACT_BYTES + 1
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        content = b"".join(chunks)
        if not content or len(content) > _MAX_ARTIFACT_BYTES:
            raise RepositoryWriteArtifactCASError(
                "artifact CAS object read size is invalid"
            )
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_after != identity_before:
            raise RepositoryWriteArtifactCASError(
                "artifact CAS object changed during read"
            )
        return content
    except RepositoryWriteArtifactCASError:
        raise
    except OSError as exc:
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object read failed"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def resolve_repository_write_artifact(
    artifact: RepositoryWriteArtifactEvidence,
    root: RepositoryWriteArtifactCASRoot,
    *,
    resolution_id: str,
    resolved_at: str,
) -> ResolvedRepositoryWriteArtifact:
    """Resolve and authenticate one exact local CAS object without mutation."""

    path, before, relative = _exact_artifact_file(root, artifact)
    content = _read_exact_file(path, before)
    content_sha256 = hashlib.sha256(content).hexdigest()
    if content_sha256 != artifact.artifact_content_sha256:
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object digest contradicts evidence"
        )
    try:
        after = path.stat()
    except OSError as exc:
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object disappeared after read"
        ) from exc
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_after != identity_before:
        raise RepositoryWriteArtifactCASError(
            "artifact CAS object changed after read"
        )
    provenance = ContractProvenance(
        origin="gate0.repository-write-artifact-cas",
        source_revision=artifact.source_revision,
        created_at=resolved_at,
        input_digests=(
            artifact.digest,
            content_sha256,
            root.digest,
        ),
    )
    receipt = RepositoryWriteArtifactResolutionReceipt(
        resolution_id=resolution_id,
        source_revision=artifact.source_revision,
        source_tree_revision=artifact.source_tree_revision,
        artifact_evidence_sha256=artifact.digest,
        locator=artifact.locator,
        artifact_content_sha256=content_sha256,
        cas_root_sha256=root.digest,
        relative_path=relative,
        file_device=after.st_dev,
        file_inode=after.st_ino,
        file_size=after.st_size,
        file_mtime_ns=after.st_mtime_ns,
        resolved_at=resolved_at,
        checks=_RESOLUTION_CHECKS,
        provenance=provenance,
    )
    return ResolvedRepositoryWriteArtifact(content=content, receipt=receipt)


__all__ = [
    "RepositoryWriteArtifactCASError",
    "RepositoryWriteArtifactCASRoot",
    "RepositoryWriteArtifactResolutionReceipt",
    "ResolvedRepositoryWriteArtifact",
    "artifact_relative_path",
    "resolve_repository_write_artifact",
]

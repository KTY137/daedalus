# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Bounded content-addressed source trees for isolated attempts.

This module extends the existing :mod:`daedalus.kernel.artifacts` identity
boundary; it does not define another artifact locator or digest authority. It
captures immutable regular-file trees into an external CAS and materializes
them only into a new destination owned by a later isolated-attempt boundary.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar, Mapping, Sequence

from daedalus.kernel.artifacts import ArtifactRef, artifact_locator
from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _artifact_locator,
    _identifier,
    _locator_sha256,
    _record_payload,
    _repo_path,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
)


MANDATORY_IGNORED_ROOTS = (".daedalus", ".git")
_READ_CHUNK_BYTES = 1024 * 1024
_STABLE_FILE_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
_STABLE_DIRECTORY_FIELDS = ("st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns")


class SourceTreeStoreError(RuntimeError):
    """Base class for fail-closed source-tree persistence errors."""


class SourceTreeCorruptionError(SourceTreeStoreError):
    """Persisted bytes or filesystem identities disagree with their address."""


class SourceTreeCaptureError(SourceTreeStoreError):
    """The submitted source or materialization boundary is unsafe or unstable."""


def _metadata_differs(
    left: os.stat_result,
    right: os.stat_result,
    fields: Sequence[str],
) -> bool:
    return any(getattr(left, field) != getattr(right, field) for field in fields)


def _validate_limit(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _bounded_read(
    descriptor: int,
    *,
    max_bytes: int,
    label: str,
    error_type: type[SourceTreeStoreError],
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = max_bytes + 1 - total
        if remaining <= 0:
            raise error_type(f"{label} exceeds its read bound")
        chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise error_type(f"{label} exceeds its read bound")
        chunks.append(chunk)
    return b"".join(chunks)


def _strict_json_object(payload: bytes, label: str) -> Mapping[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SourceTreeCorruptionError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise SourceTreeCorruptionError(f"{label} must be a JSON object")
    return value


@dataclass(frozen=True)
class SourceTreeEntry:
    """One regular file retained by a source-tree manifest."""

    path: str
    blob_sha256: str
    size: int
    executable: bool = False

    def __post_init__(self) -> None:
        path = _repo_path(self.path, "source_tree_entry.path")
        if path == ".":
            raise ValueError("source tree entry must name a file")
        object.__setattr__(self, "path", path)
        object.__setattr__(
            self,
            "blob_sha256",
            _sha256(self.blob_sha256, "source_tree_entry.blob_sha256"),
        )
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("source_tree_entry.size must be a non-negative integer")
        if not isinstance(self.executable, bool):
            raise ValueError("source_tree_entry.executable must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "blob_sha256": self.blob_sha256,
            "size": self.size,
            "executable": self.executable,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceTreeEntry":
        return cls(**_record_payload(cls, payload, "source tree entry"))


@dataclass(frozen=True)
class SourceTreeManifest(CanonicalContract):
    """Canonical identity of one bounded candidate source tree."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.source-tree-manifest"

    tree_id: str
    source_revision: str
    entries: tuple[SourceTreeEntry, ...]
    ignored_roots: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "tree_id", _identifier(self.tree_id, "tree_id"))
        revision = _revision(self.source_revision, "source_revision")
        object.__setattr__(self, "source_revision", revision)

        raw_entries = tuple(self.entries)
        if not all(isinstance(entry, SourceTreeEntry) for entry in raw_entries):
            raise ValueError("source tree entries must be SourceTreeEntry records")
        entries = tuple(sorted(raw_entries, key=lambda entry: entry.path))
        paths = tuple(entry.path for entry in entries)
        if len(set(paths)) != len(paths):
            raise ValueError("source tree paths must be unique")
        if len({path.casefold() for path in paths}) != len(paths):
            raise ValueError("source tree paths must be case-insensitively unique")
        path_set = set(paths)
        for path in paths:
            parts = path.split("/")
            for stop in range(1, len(parts)):
                if "/".join(parts[:stop]) in path_set:
                    raise ValueError("source tree contains a file/child path conflict")
        object.__setattr__(self, "entries", entries)

        ignored = _sorted_strings(self.ignored_roots, "ignored_roots", paths=True)
        if any(item == "." or "/" in item for item in ignored):
            raise ValueError("ignored_roots must contain top-level names only")
        if len({item.casefold() for item in ignored}) != len(ignored):
            raise ValueError("ignored_roots must be case-insensitively unique")
        missing = sorted(set(MANDATORY_IGNORED_ROOTS) - set(ignored))
        if missing:
            raise ValueError(
                "ignored_roots must retain mandatory exclusions: " + ", ".join(missing)
            )
        object.__setattr__(self, "ignored_roots", ignored)

        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("source tree provenance must be ContractProvenance")
        if self.provenance.source_revision != revision:
            raise ValueError("manifest revision must match provenance revision")
        _require_provenance_inputs(
            self.provenance,
            tuple(sorted({entry.blob_sha256 for entry in entries})),
            "source tree manifest",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceTreeManifest":
        body = cls._contract_payload(payload)
        raw_entries = body.get("entries")
        if isinstance(raw_entries, (str, bytes)) or not isinstance(raw_entries, Sequence):
            raise ValueError("source tree entries must be an array")
        body["entries"] = tuple(
            SourceTreeEntry.from_dict(item) for item in raw_entries
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class StoredSourceTree:
    manifest: SourceTreeManifest
    ref: ArtifactRef

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, SourceTreeManifest):
            raise ValueError("stored source tree manifest must be canonical")
        if not isinstance(self.ref, ArtifactRef):
            raise ValueError("stored source tree ref must be ArtifactRef")
        if self.ref.sha256 != self.manifest.digest:
            raise ValueError("source tree ArtifactRef must address the manifest digest")

    @property
    def locator(self) -> str:
        """Compatibility view for the earlier port candidate's return shape."""
        return self.ref.locator


class SourceTreeStore:
    """Filesystem-backed immutable SHA-256 source-tree store."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        raw = Path(root)
        raw.mkdir(parents=True, exist_ok=True)
        if raw.is_symlink():
            raise SourceTreeStoreError("source-tree store root must not be a symlink")
        self.root = raw.resolve()
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        if self.objects.is_symlink():
            raise SourceTreeStoreError("source-tree object root must not be a symlink")

    @staticmethod
    def _open_flags() -> int:
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        return flags

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _object_path(self, digest: str) -> Path:
        value = _sha256(digest, "artifact_sha256")
        return self.objects / value[:2] / value[2:]

    def put_bytes(self, payload: bytes) -> ArtifactRef:
        if not isinstance(payload, bytes):
            raise TypeError("artifact payload must be bytes")
        ref = ArtifactRef.from_sha256(sha256(payload).hexdigest())
        target = self._object_path(ref.sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise SourceTreeStoreError("object shard must not be a symlink")
        if target.exists() or target.is_symlink():
            try:
                existing = self.read_bytes(ref, max_bytes=len(payload))
            except SourceTreeStoreError as exc:
                raise SourceTreeCorruptionError(
                    "existing CAS object is invalid"
                ) from exc
            if existing != payload:
                raise SourceTreeCorruptionError(
                    "existing CAS object differs from payload"
                )
            return ref

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{ref.sha256}.", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
            self._fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)
        try:
            published = self.read_bytes(ref, max_bytes=len(payload))
        except SourceTreeStoreError as exc:
            raise SourceTreeCorruptionError("published CAS object is invalid") from exc
        if published != payload:
            raise SourceTreeCorruptionError("published CAS object differs from payload")
        return ref

    def read_bytes(self, ref: ArtifactRef | str, *, max_bytes: int) -> bytes:
        maximum = _validate_limit(max_bytes, "max_bytes")
        if isinstance(ref, str):
            locator = _artifact_locator(ref, "artifact_locator")
            ref = ArtifactRef(sha256=_locator_sha256(locator), locator=locator)
        elif not isinstance(ref, ArtifactRef):
            raise ValueError("ref must be an ArtifactRef or canonical locator")
        target = self._object_path(ref.sha256)
        try:
            before_path = os.stat(target, follow_symlinks=False)
        except OSError as exc:
            raise SourceTreeStoreError(f"artifact {ref.sha256} is unavailable") from exc
        if not stat.S_ISREG(before_path.st_mode) or target.is_symlink():
            raise SourceTreeCorruptionError("CAS object must be a regular file")
        if before_path.st_size > maximum:
            raise SourceTreeStoreError("CAS object exceeds its read bound")
        try:
            descriptor = os.open(target, self._open_flags())
        except OSError as exc:
            raise SourceTreeCorruptionError("CAS object cannot be opened safely") from exc
        try:
            before = os.fstat(descriptor)
            if _metadata_differs(before_path, before, ("st_dev", "st_ino")):
                raise SourceTreeCorruptionError("CAS object changed before open")
            payload = _bounded_read(
                descriptor,
                max_bytes=maximum,
                label="CAS object",
                error_type=SourceTreeStoreError,
            )
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        try:
            after_path = os.stat(target, follow_symlinks=False)
        except OSError as exc:
            raise SourceTreeCorruptionError("CAS object disappeared during read") from exc
        if _metadata_differs(before, after, _STABLE_FILE_FIELDS) or _metadata_differs(
            after, after_path, _STABLE_FILE_FIELDS
        ):
            raise SourceTreeCorruptionError("CAS object changed during read")
        if len(payload) != after.st_size or sha256(payload).hexdigest() != ref.sha256:
            raise SourceTreeCorruptionError("CAS object does not match its address")
        return payload

    def _read_source_file(
        self,
        path: Path,
        *,
        max_bytes: int,
    ) -> tuple[bytes, os.stat_result]:
        try:
            before_path = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SourceTreeCaptureError(f"cannot inspect source file {path}") from exc
        if not stat.S_ISREG(before_path.st_mode) or path.is_symlink():
            raise SourceTreeCaptureError(
                f"source entry is not a regular file: {path}"
            )
        if before_path.st_size > max_bytes:
            raise SourceTreeCaptureError(f"source file exceeds its bound: {path}")
        try:
            descriptor = os.open(path, self._open_flags())
        except OSError as exc:
            raise SourceTreeCaptureError(
                f"cannot safely open source file {path}"
            ) from exc
        try:
            before = os.fstat(descriptor)
            if _metadata_differs(before_path, before, ("st_dev", "st_ino")):
                raise SourceTreeCaptureError(
                    f"source file changed before capture: {path}"
                )
            payload = _bounded_read(
                descriptor,
                max_bytes=max_bytes,
                label=str(path),
                error_type=SourceTreeCaptureError,
            )
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        try:
            after_path = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SourceTreeCaptureError(
                f"source file disappeared: {path}"
            ) from exc
        if _metadata_differs(before, after, _STABLE_FILE_FIELDS) or _metadata_differs(
            after, after_path, _STABLE_FILE_FIELDS
        ):
            raise SourceTreeCaptureError(
                f"source file changed during capture: {path}"
            )
        return payload, after

    def capture_tree(
        self,
        source_root: str | os.PathLike[str],
        *,
        tree_id: str,
        source_revision: str,
        origin: str,
        created_at: str,
        trace_id: str | None = None,
        ignored_roots: Sequence[str] = MANDATORY_IGNORED_ROOTS,
        max_file_bytes: int = 64 * 1024 * 1024,
        max_total_bytes: int = 1024 * 1024 * 1024,
    ) -> StoredSourceTree:
        file_limit = _validate_limit(max_file_bytes, "max_file_bytes")
        total_limit = _validate_limit(max_total_bytes, "max_total_bytes")
        raw_root = Path(source_root)
        if raw_root.is_symlink():
            raise SourceTreeCaptureError("source root must not be a symlink")
        root = raw_root.resolve(strict=True)
        if not root.is_dir():
            raise SourceTreeCaptureError("source root must be a directory")
        if self.root == root or self.root.is_relative_to(root):
            raise SourceTreeCaptureError(
                "source-tree store must remain outside the source tree"
            )

        ignored = _sorted_strings(tuple(ignored_roots), "ignored_roots", paths=True)
        if any(item == "." or "/" in item for item in ignored):
            raise ValueError("ignored_roots must contain top-level names only")
        if len({item.casefold() for item in ignored}) != len(ignored):
            raise ValueError("ignored_roots must be case-insensitively unique")
        missing = sorted(set(MANDATORY_IGNORED_ROOTS) - set(ignored))
        if missing:
            raise ValueError(
                "ignored_roots must retain mandatory exclusions: "
                + ", ".join(missing)
            )
        ignored_casefold = {item.casefold() for item in ignored}

        entries: list[SourceTreeEntry] = []
        visited: dict[Path, os.stat_result] = {}
        expected: set[Path] = {root}
        total = 0
        for current, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=False
        ):
            directory = Path(current)
            try:
                directory.relative_to(root)
            except ValueError as exc:
                raise SourceTreeCaptureError(
                    "source traversal escaped its root"
                ) from exc
            try:
                metadata = os.stat(directory, follow_symlinks=False)
            except OSError as exc:
                raise SourceTreeCaptureError(
                    f"cannot inspect source directory: {directory}"
                ) from exc
            if not stat.S_ISDIR(metadata.st_mode) or directory.is_symlink():
                raise SourceTreeCaptureError(
                    f"source directory is unsafe: {directory}"
                )
            visited[directory] = metadata
            if directory == root:
                dirnames[:] = sorted(
                    name
                    for name in dirnames
                    if name.casefold() not in ignored_casefold
                )
                filenames = sorted(
                    name
                    for name in filenames
                    if name.casefold() not in ignored_casefold
                )
            else:
                dirnames[:] = sorted(dirnames)
                filenames = sorted(filenames)
            for dirname in dirnames:
                child = directory / dirname
                if child.is_symlink():
                    raise SourceTreeCaptureError(
                        f"source contains symlink directory: {child}"
                    )
                expected.add(child)
            for filename in filenames:
                path = directory / filename
                if path.is_symlink():
                    raise SourceTreeCaptureError(
                        f"source contains symlink file: {path}"
                    )
                remaining = total_limit - total
                if remaining < 0:
                    raise SourceTreeCaptureError(
                        "source tree exceeds max_total_bytes"
                    )
                payload, file_metadata = self._read_source_file(
                    path,
                    max_bytes=min(file_limit, remaining),
                )
                total += len(payload)
                ref = self.put_bytes(payload)
                entries.append(
                    SourceTreeEntry(
                        path=path.relative_to(root).as_posix(),
                        blob_sha256=ref.sha256,
                        size=len(payload),
                        executable=bool(file_metadata.st_mode & stat.S_IXUSR),
                    )
                )

        missing_directories = expected - set(visited)
        if missing_directories:
            raise SourceTreeCaptureError(
                "source directory disappeared during capture"
            )
        for directory, before in visited.items():
            try:
                after = os.stat(directory, follow_symlinks=False)
            except OSError as exc:
                raise SourceTreeCaptureError(
                    f"source directory disappeared during capture: {directory}"
                ) from exc
            if _metadata_differs(before, after, _STABLE_DIRECTORY_FIELDS):
                raise SourceTreeCaptureError(
                    f"source directory changed during capture: {directory}"
                )

        revision = _revision(source_revision, "source_revision")
        manifest = SourceTreeManifest(
            tree_id=tree_id,
            source_revision=revision,
            entries=tuple(entries),
            ignored_roots=ignored,
            provenance=ContractProvenance(
                origin=origin,
                source_revision=revision,
                created_at=created_at,
                input_digests=tuple(
                    sorted({entry.blob_sha256 for entry in entries})
                ),
                trace_id=trace_id,
            ),
        )
        ref = self.put_bytes(manifest.to_json().encode("utf-8"))
        return StoredSourceTree(manifest=manifest, ref=ref)

    def load_tree(
        self,
        ref: ArtifactRef | str,
        *,
        max_manifest_bytes: int = 16 * 1024 * 1024,
    ) -> SourceTreeManifest:
        maximum = _validate_limit(max_manifest_bytes, "max_manifest_bytes")
        payload = self.read_bytes(ref, max_bytes=maximum)
        submitted = _strict_json_object(payload, "source tree manifest")
        try:
            manifest = SourceTreeManifest.from_dict(submitted)
        except (TypeError, ValueError, KeyError) as exc:
            raise SourceTreeCorruptionError(
                "source tree manifest is malformed"
            ) from exc
        if submitted != manifest.to_dict():
            raise SourceTreeCorruptionError(
                "source tree manifest wire is noncanonical"
            )
        expected = (
            ref
            if isinstance(ref, ArtifactRef)
            else ArtifactRef(
                sha256=_locator_sha256(
                    _artifact_locator(ref, "artifact_locator")
                ),
                locator=ref,
            )
        )
        if manifest.digest != expected.sha256:
            raise SourceTreeCorruptionError(
                "manifest digest does not match ArtifactRef"
            )
        if payload != manifest.to_json().encode("utf-8"):
            raise SourceTreeCorruptionError("manifest bytes are not canonical")
        return manifest

    def materialize_tree(
        self,
        ref: ArtifactRef | str,
        destination: str | os.PathLike[str],
        *,
        max_file_bytes: int = 64 * 1024 * 1024,
        max_total_bytes: int = 1024 * 1024 * 1024,
    ) -> SourceTreeManifest:
        file_limit = _validate_limit(max_file_bytes, "max_file_bytes")
        total_limit = _validate_limit(max_total_bytes, "max_total_bytes")
        manifest = self.load_tree(ref)
        total = 0
        for entry in manifest.entries:
            if entry.size > file_limit:
                raise SourceTreeCaptureError(
                    f"manifest entry exceeds max_file_bytes: {entry.path}"
                )
            total += entry.size
            if total > total_limit:
                raise SourceTreeCaptureError("manifest exceeds max_total_bytes")

        target = Path(destination)
        if target.exists() or target.is_symlink():
            raise SourceTreeCaptureError(
                "materialization destination must not exist"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise SourceTreeCaptureError(
                "materialization parent must not be a symlink"
            )
        staging = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent)
        )
        try:
            staging_root = staging.resolve()
            for entry in manifest.entries:
                output = staging.joinpath(*entry.path.split("/"))
                output.parent.mkdir(parents=True, exist_ok=True)
                parent = output.parent.resolve()
                if parent != staging_root and staging_root not in parent.parents:
                    raise SourceTreeCaptureError(
                        "manifest entry escapes staging root"
                    )
                payload = self.read_bytes(
                    ArtifactRef.from_sha256(entry.blob_sha256),
                    max_bytes=entry.size,
                )
                if len(payload) != entry.size:
                    raise SourceTreeCorruptionError(
                        "blob size disagrees with manifest"
                    )
                with output.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                output.chmod(0o755 if entry.executable else 0o644)
            os.replace(staging, target)
            self._fsync_directory(target.parent)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return manifest


__all__ = [
    "MANDATORY_IGNORED_ROOTS",
    "SourceTreeCaptureError",
    "SourceTreeCorruptionError",
    "SourceTreeEntry",
    "SourceTreeManifest",
    "SourceTreeStore",
    "SourceTreeStoreError",
    "StoredSourceTree",
]

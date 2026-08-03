"""Content-addressed source-tree storage for isolated Gate-0 attempts.

The store owns bytes and immutable source-tree manifests only. It does not run
candidates, interpret a green test as promotion, or mutate a primary checkout.
All identities use the canonical Gate-0 serialization and SHA-256 authority.
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

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _record_payload,
    _repo_path,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
)
from daedalus.spine.envelope import canonical_json


_LOCATOR_PREFIX = "artifact-locator:sha256:"
_DEFAULT_IGNORED_ROOTS = (".daedalus", ".git")
_READ_CHUNK_BYTES = 1024 * 1024
_STABLE_FILE_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
_STABLE_DIRECTORY_FIELDS = ("st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns")


class ArtifactStoreError(RuntimeError):
    """Base class for fail-closed artifact-store errors."""


class ArtifactCorruptionError(ArtifactStoreError):
    """Stored bytes do not match their content address."""


class SourceTreeError(ArtifactStoreError):
    """A source tree is malformed, unsafe, or changed during capture."""


def _metadata_differs(
    left: os.stat_result,
    right: os.stat_result,
    fields: Sequence[str],
) -> bool:
    return any(getattr(left, field) != getattr(right, field) for field in fields)


def _bounded_descriptor_read(
    descriptor: int,
    *,
    max_bytes: int | None,
    overflow: type[ArtifactStoreError],
    overflow_message: str,
) -> bytes:
    """Read at most ``max_bytes + 1`` bytes before refusing an oversized file."""

    chunks: list[bytes] = []
    total = 0
    while True:
        if max_bytes is None:
            request = _READ_CHUNK_BYTES
        else:
            remaining_with_sentinel = max_bytes + 1 - total
            if remaining_with_sentinel <= 0:
                raise overflow(overflow_message)
            request = min(_READ_CHUNK_BYTES, remaining_with_sentinel)
        chunk = os.read(descriptor, request)
        if not chunk:
            break
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise overflow(overflow_message)
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class SourceTreeEntry:
    """One regular file in an immutable source-tree manifest."""

    path: str
    blob_sha256: str
    size: int
    executable: bool = False

    def __post_init__(self) -> None:
        path = _repo_path(self.path, "source_tree_entry.path")
        if path == ".":
            raise ValueError("source tree entry path must name a file")
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
    """Canonical identity of a repository source tree at one revision."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.source-tree-manifest"

    tree_id: str
    source_revision: str
    entries: tuple[SourceTreeEntry, ...]
    ignored_roots: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "tree_id", _identifier(self.tree_id, "tree_id"))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        entries = tuple(sorted(self.entries, key=lambda entry: entry.path))
        paths = [entry.path for entry in entries]
        if len(set(paths)) != len(paths):
            raise ValueError("source tree entry paths must be unique")
        casefolded = [path.casefold() for path in paths]
        if len(set(casefolded)) != len(casefolded):
            raise ValueError(
                "source tree paths must remain unique on case-insensitive filesystems"
            )
        path_set = set(paths)
        for path in paths:
            parts = path.split("/")
            for stop in range(1, len(parts)):
                if "/".join(parts[:stop]) in path_set:
                    raise ValueError("source tree cannot contain file/child path conflicts")
        object.__setattr__(self, "entries", entries)

        ignored = _sorted_strings(self.ignored_roots, "ignored_roots", paths=True)
        if any(root == "." or "/" in root for root in ignored):
            raise ValueError("ignored_roots must contain top-level names only")
        if len({root.casefold() for root in ignored}) != len(ignored):
            raise ValueError("ignored_roots must be case-insensitively unique")
        missing_mandatory = sorted(set(_DEFAULT_IGNORED_ROOTS) - set(ignored))
        if missing_mandatory:
            raise ValueError(
                "ignored_roots must retain mandatory metadata exclusions: "
                + ", ".join(missing_mandatory)
            )
        object.__setattr__(self, "ignored_roots", ignored)

        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "source tree source_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            tuple(entry.blob_sha256 for entry in entries),
            "source tree manifest",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceTreeManifest":
        body = cls._contract_payload(payload)
        body["entries"] = tuple(
            SourceTreeEntry.from_dict(entry) for entry in body["entries"]
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class StoredSourceTree:
    manifest: SourceTreeManifest
    locator: str

    def __post_init__(self) -> None:
        digest = locator_sha256(self.locator)
        if digest != self.manifest.digest:
            raise ValueError("source tree locator must address the manifest digest")


def artifact_locator(digest: str) -> str:
    return _LOCATOR_PREFIX + _sha256(digest, "artifact_sha256")


def locator_sha256(locator: str) -> str:
    if not isinstance(locator, str) or not locator.startswith(_LOCATOR_PREFIX):
        raise ValueError("artifact locator must use artifact-locator:sha256")
    return _sha256(locator[len(_LOCATOR_PREFIX) :], "artifact_locator.sha256")


class ArtifactStore:
    """Filesystem-backed immutable SHA-256 object store.

    Objects are written to temporary files in the final directory, fsynced, and
    atomically replaced. Reads use descriptor identity checks, no-follow where
    available, bounded streaming, and digest recomputation.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        raw_root = Path(root)
        raw_root.mkdir(parents=True, exist_ok=True)
        if raw_root.is_symlink():
            raise ArtifactStoreError("artifact store root must not be a symlink")
        self.root = raw_root.resolve()
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        if self.objects.is_symlink():
            raise ArtifactStoreError("artifact object root must not be a symlink")

    def _object_path(self, digest: str) -> Path:
        value = _sha256(digest, "artifact_sha256")
        return self.objects / value[:2] / value[2:]

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _open_flags() -> int:
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        return flags

    def _read_owned_object(
        self,
        target: Path,
        *,
        digest: str,
        max_bytes: int | None,
    ) -> bytes:
        try:
            before_path = os.stat(target, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise ArtifactStoreError(f"artifact {digest} is missing") from exc
        except OSError as exc:
            raise ArtifactCorruptionError(f"cannot inspect artifact {digest}") from exc
        if not stat.S_ISREG(before_path.st_mode) or target.is_symlink():
            raise ArtifactCorruptionError(f"artifact {digest} is not a regular file")
        try:
            descriptor = os.open(target, self._open_flags())
        except OSError as exc:
            raise ArtifactCorruptionError(f"cannot safely open artifact {digest}") from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ArtifactCorruptionError(f"artifact {digest} is not a regular file")
            if _metadata_differs(before_path, before, ("st_dev", "st_ino")):
                raise ArtifactCorruptionError(
                    f"artifact {digest} changed before descriptor acquisition"
                )
            if max_bytes is not None and before.st_size > max_bytes:
                raise ArtifactStoreError(
                    f"artifact {digest} exceeds the declared read bound {max_bytes}"
                )
            payload = _bounded_descriptor_read(
                descriptor,
                max_bytes=max_bytes,
                overflow=ArtifactStoreError,
                overflow_message=(
                    f"artifact {digest} exceeds the declared read bound {max_bytes}"
                ),
            )
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        try:
            after_path = os.stat(target, follow_symlinks=False)
        except OSError as exc:
            raise ArtifactCorruptionError(
                f"artifact {digest} disappeared during read"
            ) from exc
        if _metadata_differs(before, after, _STABLE_FILE_FIELDS) or _metadata_differs(
            after, after_path, _STABLE_FILE_FIELDS
        ):
            raise ArtifactCorruptionError(f"artifact {digest} changed during read")
        if len(payload) != after.st_size:
            raise ArtifactCorruptionError(f"artifact {digest} changed size during read")
        if sha256(payload).hexdigest() != digest:
            raise ArtifactCorruptionError(
                f"artifact {digest} does not match its content address"
            )
        return payload

    def put_bytes(self, payload: bytes) -> str:
        if not isinstance(payload, bytes):
            raise TypeError("artifact payload must be bytes")
        digest = sha256(payload).hexdigest()
        locator = artifact_locator(digest)
        target = self._object_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise ArtifactStoreError("artifact shard directory must not be a symlink")
        try:
            target.lstat()
        except FileNotFoundError:
            existing = False
        else:
            existing = True
        if existing:
            try:
                stored = self.read_bytes(locator, max_bytes=len(payload))
            except ArtifactStoreError as exc:
                raise ArtifactCorruptionError(
                    f"existing object {digest} is invalid: {exc}"
                ) from exc
            if stored != payload:
                raise ArtifactCorruptionError(
                    f"existing object {digest} does not match the submitted payload"
                )
            return locator

        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            self._fsync_directory(target.parent)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        try:
            stored = self.read_bytes(locator, max_bytes=len(payload))
        except ArtifactStoreError as exc:
            raise ArtifactCorruptionError(
                f"written object {digest} failed post-write verification: {exc}"
            ) from exc
        if stored != payload:
            raise ArtifactCorruptionError(
                f"written object {digest} differs from submitted payload"
            )
        return locator

    def put_json(self, payload: Mapping[str, Any]) -> str:
        return self.put_bytes(canonical_json(payload).encode("utf-8"))

    def read_bytes(self, locator: str, *, max_bytes: int | None = None) -> bytes:
        if max_bytes is not None and (
            isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0
        ):
            raise ValueError("max_bytes must be a non-negative integer or null")
        digest = locator_sha256(locator)
        return self._read_owned_object(
            self._object_path(digest),
            digest=digest,
            max_bytes=max_bytes,
        )

    def exists(self, locator: str) -> bool:
        try:
            self.read_bytes(locator)
        except ArtifactStoreError:
            return False
        return True

    def _read_source_file(
        self,
        path: Path,
        *,
        max_bytes: int,
        limit_name: str,
    ) -> tuple[bytes, os.stat_result]:
        try:
            path_before = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SourceTreeError(f"cannot inspect source file {path}") from exc
        if not stat.S_ISREG(path_before.st_mode):
            raise SourceTreeError(f"source entry is not a regular file: {path}")
        try:
            descriptor = os.open(path, self._open_flags())
        except OSError as exc:
            raise SourceTreeError(f"cannot safely open source file {path}") from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise SourceTreeError(f"source entry is not a regular file: {path}")
            if _metadata_differs(path_before, before, ("st_dev", "st_ino")):
                raise SourceTreeError(f"source file changed before capture: {path}")
            if before.st_size > max_bytes:
                raise SourceTreeError(f"source file exceeds {limit_name}: {path}")
            payload = _bounded_descriptor_read(
                descriptor,
                max_bytes=max_bytes,
                overflow=SourceTreeError,
                overflow_message=f"source file exceeds {limit_name}: {path}",
            )
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        try:
            path_after = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SourceTreeError(f"source file disappeared during capture: {path}") from exc
        if _metadata_differs(before, after, _STABLE_FILE_FIELDS):
            raise SourceTreeError(f"source file changed during capture: {path}")
        if _metadata_differs(after, path_after, _STABLE_FILE_FIELDS):
            raise SourceTreeError(f"source path changed during capture: {path}")
        if len(payload) != after.st_size:
            raise SourceTreeError(f"source file size changed during capture: {path}")
        return payload, after

    @staticmethod
    def _directory_metadata(path: Path) -> os.stat_result:
        try:
            metadata = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SourceTreeError(f"cannot inspect source directory {path}") from exc
        if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
            raise SourceTreeError(f"source entry is not a stable directory: {path}")
        return metadata

    def capture_tree(
        self,
        source_root: str | os.PathLike[str],
        *,
        tree_id: str,
        source_revision: str,
        origin: str,
        created_at: str,
        trace_id: str | None = None,
        ignored_roots: Sequence[str] = _DEFAULT_IGNORED_ROOTS,
        max_file_bytes: int = 64 * 1024 * 1024,
        max_total_bytes: int = 1024 * 1024 * 1024,
    ) -> StoredSourceTree:
        for name, value in (
            ("max_file_bytes", max_file_bytes),
            ("max_total_bytes", max_total_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        revision = _revision(source_revision, "source_revision")
        raw_root = Path(source_root)
        if raw_root.is_symlink():
            raise SourceTreeError("source root must not be a symlink")
        root = raw_root.resolve(strict=True)
        if not root.is_dir():
            raise SourceTreeError("source root must be a directory")

        ignored = _sorted_strings(tuple(ignored_roots), "ignored_roots", paths=True)
        if any(item == "." or "/" in item for item in ignored):
            raise ValueError("ignored_roots must contain top-level names only")
        if len({item.casefold() for item in ignored}) != len(ignored):
            raise ValueError("ignored_roots must be case-insensitively unique")
        missing_mandatory = sorted(set(_DEFAULT_IGNORED_ROOTS) - set(ignored))
        if missing_mandatory:
            raise ValueError(
                "ignored_roots must retain mandatory metadata exclusions: "
                + ", ".join(missing_mandatory)
            )
        ignored_set = set(ignored)

        entries: list[SourceTreeEntry] = []
        total = 0
        visited_directories: dict[Path, os.stat_result] = {}
        expected_directories: set[Path] = {root}
        for current, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            try:
                current_path.relative_to(root)
            except ValueError as exc:
                raise SourceTreeError("source traversal escaped its root") from exc
            visited_directories[current_path] = self._directory_metadata(current_path)

            relative_dir = current_path.relative_to(root)
            if relative_dir == Path("."):
                dirnames[:] = sorted(
                    name for name in dirnames if name not in ignored_set
                )
                filenames = sorted(
                    name for name in filenames if name not in ignored_set
                )
            else:
                dirnames[:] = sorted(dirnames)
                filenames = sorted(filenames)
            for dirname in dirnames:
                child = current_path / dirname
                if child.is_symlink():
                    raise SourceTreeError(
                        f"source tree contains symlink directory: {child}"
                    )
                expected_directories.add(child)
            for filename in filenames:
                path = current_path / filename
                if path.is_symlink():
                    raise SourceTreeError(f"source tree contains symlink file: {path}")
                remaining_total = max_total_bytes - total
                effective_limit = min(max_file_bytes, remaining_total)
                limit_name = (
                    "max_total_bytes"
                    if remaining_total < max_file_bytes
                    else "max_file_bytes"
                )
                payload, metadata = self._read_source_file(
                    path,
                    max_bytes=effective_limit,
                    limit_name=limit_name,
                )
                total += len(payload)
                locator = self.put_bytes(payload)
                entries.append(
                    SourceTreeEntry(
                        path=path.relative_to(root).as_posix(),
                        blob_sha256=locator_sha256(locator),
                        size=len(payload),
                        executable=bool(metadata.st_mode & stat.S_IXUSR),
                    )
                )

        missing_directories = sorted(
            path.relative_to(root).as_posix()
            for path in expected_directories - set(visited_directories)
        )
        if missing_directories:
            raise SourceTreeError(
                "source directories disappeared during capture: "
                + ", ".join(missing_directories)
            )
        for directory, before in visited_directories.items():
            after = self._directory_metadata(directory)
            if _metadata_differs(before, after, _STABLE_DIRECTORY_FIELDS):
                raise SourceTreeError(
                    f"source directory changed during capture: {directory}"
                )

        blob_digests = tuple(sorted({entry.blob_sha256 for entry in entries}))
        manifest = SourceTreeManifest(
            tree_id=tree_id,
            source_revision=revision,
            entries=tuple(entries),
            ignored_roots=ignored,
            provenance=ContractProvenance(
                origin=origin,
                source_revision=revision,
                created_at=created_at,
                input_digests=blob_digests,
                trace_id=trace_id,
            ),
        )
        locator = self.put_json(manifest.to_dict())
        return StoredSourceTree(manifest=manifest, locator=locator)

    def load_tree(
        self, locator: str, *, max_manifest_bytes: int = 16 * 1024 * 1024
    ) -> SourceTreeManifest:
        payload = self.read_bytes(locator, max_bytes=max_manifest_bytes)
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceTreeError("source tree manifest is not canonical JSON") from exc
        try:
            manifest = SourceTreeManifest.from_dict(parsed)
        except (TypeError, ValueError, KeyError) as exc:
            raise SourceTreeError("source tree manifest is malformed") from exc
        if manifest.digest != locator_sha256(locator):
            raise SourceTreeError("source tree manifest digest does not match locator")
        return manifest

    def materialize_tree(
        self,
        locator: str,
        destination: str | os.PathLike[str],
        *,
        max_file_bytes: int = 64 * 1024 * 1024,
        max_total_bytes: int = 1024 * 1024 * 1024,
    ) -> SourceTreeManifest:
        for name, value in (
            ("max_file_bytes", max_file_bytes),
            ("max_total_bytes", max_total_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        manifest = self.load_tree(locator)
        total = 0
        for entry in manifest.entries:
            if entry.size > max_file_bytes:
                raise SourceTreeError(
                    f"manifest entry exceeds max_file_bytes: {entry.path}"
                )
            total += entry.size
            if total > max_total_bytes:
                raise SourceTreeError("manifest exceeds max_total_bytes")
        target = Path(destination)
        if target.exists() or target.is_symlink():
            raise SourceTreeError("materialization destination must not already exist")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent)
        )
        try:
            staging_root = staging.resolve()
            for entry in manifest.entries:
                output = staging.joinpath(*entry.path.split("/"))
                resolved_parent = output.parent.resolve()
                if staging_root not in (resolved_parent, *resolved_parent.parents):
                    raise SourceTreeError("manifest entry escapes materialization root")
                output.parent.mkdir(parents=True, exist_ok=True)
                payload = self.read_bytes(
                    artifact_locator(entry.blob_sha256), max_bytes=entry.size
                )
                if len(payload) != entry.size:
                    raise ArtifactCorruptionError(
                        f"blob {entry.blob_sha256} size does not match manifest"
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
    "ArtifactCorruptionError",
    "ArtifactStore",
    "ArtifactStoreError",
    "SourceTreeEntry",
    "SourceTreeError",
    "SourceTreeManifest",
    "StoredSourceTree",
    "artifact_locator",
    "locator_sha256",
]

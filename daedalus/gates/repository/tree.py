"""Race-aware, read-only access to exact repository source bytes.

This module centralizes the filesystem mechanics needed by Gate-0 semantic
replay. It grants no write, process, network, effect, approval, promotion, or
Gate authority. Callers receive an immutable snapshot of one normalized
repository-relative regular UTF-8 file after symlink, escape, size, and
open/read/path-identity checks.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path


_REPOSITORY_PATH = re.compile(
    r"^(?!/)(?![A-Za-z]:/)(?!.*(?:^|/)\.\.?(?:/|$))(?!.*//)[^\\\r\n]+$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SOURCE_BYTES = 16 * 1_048_576


class RepositoryTreeReadError(RuntimeError):
    """The selected repository path cannot be read as an exact safe snapshot."""


class RepositoryTreePathError(RepositoryTreeReadError):
    """The repository root or relative path is malformed or unsafe."""


class RepositoryTreeRaceError(RepositoryTreeReadError):
    """The selected file identity changed during the bounded read."""


def normalize_repository_path(value: object) -> str:
    if not isinstance(value, str) or _REPOSITORY_PATH.fullmatch(value) is None:
        raise RepositoryTreePathError(
            "path must be normalized repository-relative POSIX"
        )
    return value


def resolve_repository_root(repository_root: Path) -> Path:
    if not isinstance(repository_root, Path):
        raise RepositoryTreePathError(
            "repository_root must be a pathlib.Path"
        )
    try:
        metadata = repository_root.lstat()
    except OSError as exc:
        raise RepositoryTreePathError(
            "repository root is unavailable"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RepositoryTreePathError(
            "repository root must be a real directory"
        )
    try:
        resolved = repository_root.resolve(strict=True)
    except OSError as exc:
        raise RepositoryTreePathError(
            "repository root cannot be resolved"
        ) from exc
    try:
        final = resolved.lstat()
    except OSError as exc:
        raise RepositoryTreePathError(
            "resolved repository root is unavailable"
        ) from exc
    if (
        stat.S_ISLNK(final.st_mode)
        or not stat.S_ISDIR(final.st_mode)
        or (metadata.st_dev, metadata.st_ino)
        != (final.st_dev, final.st_ino)
    ):
        raise RepositoryTreeRaceError(
            "repository root identity changed during resolution"
        )
    return resolved


@dataclass(frozen=True)
class RepositorySourceSnapshot:
    path: str
    source: bytes
    source_sha256: str
    size: int

    def __post_init__(self) -> None:
        normalize_repository_path(self.path)
        if type(self.source) is not bytes:
            raise ValueError("source must be exact bytes")
        if (
            not isinstance(self.source_sha256, str)
            or _SHA256.fullmatch(self.source_sha256) is None
        ):
            raise ValueError("source_sha256 must be lowercase sha256")
        if type(self.size) is not int or self.size < 0:
            raise ValueError("size must be a non-negative strict integer")
        if self.size != len(self.source):
            raise ValueError("size differs from source bytes")
        expected = hashlib.sha256(self.source).hexdigest()
        if self.source_sha256 != expected:
            raise ValueError("source_sha256 differs from source bytes")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "source_sha256": self.source_sha256,
            "size": self.size,
        }


def read_repository_source(
    repository_root: Path,
    relative_path: str,
) -> RepositorySourceSnapshot:
    root = resolve_repository_root(repository_root)
    try:
        root_before = root.lstat()
    except OSError as exc:
        raise RepositoryTreeRaceError(
            "repository root disappeared before read"
        ) from exc
    path = normalize_repository_path(relative_path)
    relative = Path(*path.split("/"))
    current = root
    component = None
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            component = current.lstat()
        except OSError as exc:
            raise RepositoryTreePathError(
                f"repository path is unavailable: {path}"
            ) from exc
        if stat.S_ISLNK(component.st_mode):
            raise RepositoryTreePathError(
                f"repository path contains a symlink: {path}"
            )
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(
            component.st_mode
        ):
            raise RepositoryTreePathError(
                f"repository path parent is not a directory: {path}"
            )
    if component is None or not stat.S_ISREG(component.st_mode):
        raise RepositoryTreePathError(
            f"repository path is not a regular file: {path}"
        )
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RepositoryTreePathError(
            f"repository path escapes the root: {path}"
        ) from exc

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(current, flags)
    except OSError as exc:
        raise RepositoryTreePathError(
            f"repository file cannot be opened safely: {path}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RepositoryTreePathError(
                f"opened repository path is not regular: {path}"
            )
        if (before.st_dev, before.st_ino, before.st_size) != (
            component.st_dev,
            component.st_ino,
            component.st_size,
        ):
            raise RepositoryTreeRaceError(
                f"repository file changed before open: {path}"
            )
        if before.st_size > _MAX_SOURCE_BYTES:
            raise RepositoryTreePathError(
                f"repository file exceeds the bounded source size: {path}"
            )
        chunks: list[bytes] = []
        remaining = _MAX_SOURCE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        source = b"".join(chunks)
        if len(source) > _MAX_SOURCE_BYTES:
            raise RepositoryTreePathError(
                f"repository file exceeds the bounded source size: {path}"
            )
        after = os.fstat(descriptor)
    except OSError as exc:
        raise RepositoryTreeReadError(
            f"repository file cannot be read: {path}"
        ) from exc
    finally:
        os.close(descriptor)

    try:
        final_path = current.lstat()
        final_root = root.lstat()
    except OSError as exc:
        raise RepositoryTreeRaceError(
            f"repository path disappeared after read: {path}"
        ) from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size)
    identity_after = (after.st_dev, after.st_ino, after.st_size)
    identity_path = (
        final_path.st_dev,
        final_path.st_ino,
        final_path.st_size,
    )
    if (
        identity_before != identity_after
        or identity_after != identity_path
    ):
        raise RepositoryTreeRaceError(
            f"repository file changed while reading: {path}"
        )
    if (
        stat.S_ISLNK(final_path.st_mode)
        or not stat.S_ISREG(final_path.st_mode)
    ):
        raise RepositoryTreeRaceError(
            f"repository path type changed while reading: {path}"
        )
    if (
        stat.S_ISLNK(final_root.st_mode)
        or not stat.S_ISDIR(final_root.st_mode)
        or (final_root.st_dev, final_root.st_ino)
        != (root_before.st_dev, root_before.st_ino)
    ):
        raise RepositoryTreeRaceError(
            "repository root identity changed while reading"
        )
    if len(source) != before.st_size:
        raise RepositoryTreeRaceError(
            f"repository source read was incomplete: {path}"
        )
    if b"\x00" in source:
        raise RepositoryTreePathError(
            f"repository source contains NUL bytes: {path}"
        )
    try:
        source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RepositoryTreePathError(
            f"repository source is not strict UTF-8: {path}"
        ) from exc
    return RepositorySourceSnapshot(
        path=path,
        source=source,
        source_sha256=hashlib.sha256(source).hexdigest(),
        size=len(source),
    )


__all__ = [
    "RepositorySourceSnapshot",
    "RepositoryTreePathError",
    "RepositoryTreeRaceError",
    "RepositoryTreeReadError",
    "normalize_repository_path",
    "read_repository_source",
    "resolve_repository_root",
]

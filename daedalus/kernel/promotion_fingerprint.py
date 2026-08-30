# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Read-only primary-checkout identity for promotion execution accounting.

The fingerprint deliberately excludes only repository-control roots that are
not candidate source material (``.git`` and ``.daedalus``). It follows no
symlink, accepts only regular files, binds executable bits and raw bytes, and
requires two identical observations before returning. The helper performs no
repository mutation and owns no promotion policy.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from daedalus.spine.envelope import canonical_sha


_EXCLUDED_ROOTS = frozenset({".git", ".daedalus"})


class PrimaryCheckoutFingerprintError(RuntimeError):
    """The primary checkout could not be observed as one stable file tree."""


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


def _read_regular_file(path: Path, expected: os.stat_result) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PrimaryCheckoutFingerprintError(
            f"primary checkout file cannot be opened safely: {path.name}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not _same_file(expected, before):
            raise PrimaryCheckoutFingerprintError(
                f"primary checkout file identity changed before read: {path.name}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        try:
            current = path.lstat()
        except OSError as exc:
            raise PrimaryCheckoutFingerprintError(
                f"primary checkout file disappeared during read: {path.name}"
            ) from exc
        if not _same_file(before, after) or not _same_file(after, current):
            raise PrimaryCheckoutFingerprintError(
                f"primary checkout file changed during read: {path.name}"
            )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _observe(root: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    try:
        children = sorted(
            root.rglob("*"),
            key=lambda value: value.relative_to(root).as_posix(),
        )
    except OSError as exc:
        raise PrimaryCheckoutFingerprintError(
            "primary checkout traversal failed"
        ) from exc

    for path in children:
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0].casefold() in _EXCLUDED_ROOTS:
            continue
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise PrimaryCheckoutFingerprintError(
                f"primary checkout entry disappeared: {relative.as_posix()}"
            ) from exc
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise PrimaryCheckoutFingerprintError(
                "primary checkout contains a non-regular entry: "
                f"{relative.as_posix()}"
            )
        raw = _read_regular_file(path, metadata)
        rows.append(
            {
                "path": relative.as_posix(),
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "executable": bool(metadata.st_mode & stat.S_IXUSR),
            }
        )
    return tuple(rows)


def fingerprint_primary_checkout(root: str | Path) -> str:
    """Return a stable digest of one checkout's source-visible file tree."""
    try:
        submitted = Path(root).absolute()
        submitted_metadata = submitted.lstat()
        if stat.S_ISLNK(submitted_metadata.st_mode):
            raise PrimaryCheckoutFingerprintError(
                "primary checkout root cannot be a symlink"
            )
        directory = submitted.resolve(strict=True)
        metadata = directory.lstat()
    except PrimaryCheckoutFingerprintError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PrimaryCheckoutFingerprintError(
            "primary checkout root must be an existing directory"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise PrimaryCheckoutFingerprintError(
            "primary checkout root must be a real directory"
        )
    first = _observe(directory)
    second = _observe(directory)
    if first != second:
        raise PrimaryCheckoutFingerprintError(
            "primary checkout changed between fingerprint observations"
        )
    return canonical_sha(
        {
            "schema": "daedalus-primary-checkout-fingerprint/1",
            "files": list(first),
        }
    )


__all__ = [
    "PrimaryCheckoutFingerprintError",
    "fingerprint_primary_checkout",
]

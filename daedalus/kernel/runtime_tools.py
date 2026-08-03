"""Canonical binding from a symbolic runtime tool id to exact host bytes.

The contract is inert: capture and verification read a file but never execute
it.  Verification returns a retained exact-byte handle so a later trusted
execution seam does not reopen an attacker-swappable path before launch.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, BinaryIO, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _require_provenance_inputs,
    _revision,
    _sha256,
)
from daedalus.spine.envelope import canonical_sha


class RuntimeToolBindingError(ValueError):
    """A runtime tool path is unsafe, unstable, or differs from its binding."""


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _file_identity(metadata: os.stat_result) -> tuple[int, int]:
    return (metadata.st_dev, metadata.st_ino)


def _content_snapshot(metadata: os.stat_result) -> tuple[int, int]:
    return (
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _strict_absolute_path(value: str | os.PathLike[str]) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeToolBindingError("executable path must be absolute")
    if os.name == "nt":
        raw = os.fspath(value)
        windows = PureWindowsPath(raw)
        if (
            windows.drive.startswith("\\\\")
            or raw.startswith("\\\\?\\")
            or raw.startswith("\\\\.\\")
        ):
            raise RuntimeToolBindingError(
                "executable path must use a local drive, not a UNC or device path"
            )
    absolute = Path(os.path.abspath(os.fspath(path)))
    cursor = Path(absolute.anchor)
    try:
        for component in absolute.parts[1:]:
            cursor /= component
            metadata = os.lstat(cursor)
            if _is_link_or_reparse(metadata):
                raise RuntimeToolBindingError(
                    f"executable path must not traverse a link or reparse point: {cursor}"
                )
        resolved = absolute.resolve(strict=True)
    except RuntimeToolBindingError:
        raise
    except OSError as exc:
        raise RuntimeToolBindingError(
            f"executable path cannot be resolved as an existing file: {absolute}"
        ) from exc
    return resolved


def _path_sha256(path: Path) -> str:
    normalized = os.path.normcase(os.fspath(path))
    return canonical_sha(
        {
            "domain": "daedalus.runtime-tool-path/1",
            "resolved_path": normalized,
        }
    )


def _open_binary_without_write_or_delete_share(path: Path) -> BinaryIO:
    """Open exact bytes and, on Windows, deny concurrent writes/replacement.

    A normal Python ``open(..., 'rb')`` on Windows shares write access.  That is
    sufficient for hashing but not for a launch capability: another process can
    rewrite the file while the verifier retains the handle.  ``CreateFileW``
    with read sharing only keeps readers working while refusing writers and
    deleters until the returned handle is closed.

    POSIX has no equivalent mandatory share mode.  The retained descriptor is
    still the exact verified inode, so a later launcher must execute through
    that descriptor (for example ``fexecve``/``execveat``), never re-open the
    diagnostic path.
    """

    if os.name != "nt":
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        return os.fdopen(descriptor, "rb", closefd=True)

    import ctypes
    import ctypes.wintypes
    import msvcrt

    generic_read = 0x80000000
    file_share_read = 0x00000001
    open_existing = 3
    file_attribute_normal = 0x00000080
    file_flag_open_reparse_point = 0x00200000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.HANDLE,
    )
    create_file.restype = ctypes.wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.wintypes.HANDLE,)
    close_handle.restype = ctypes.wintypes.BOOL
    native_handle = create_file(
        os.fspath(path),
        generic_read,
        file_share_read,
        None,
        open_existing,
        file_attribute_normal | file_flag_open_reparse_point,
        None,
    )
    invalid_handle = ctypes.wintypes.HANDLE(-1).value
    if native_handle == invalid_handle:
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error), os.fspath(path))
    try:
        descriptor = msvcrt.open_osfhandle(
            native_handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
    except BaseException:
        close_handle(native_handle)
        raise
    try:
        os.set_inheritable(descriptor, False)
        return os.fdopen(descriptor, "rb", closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def _open_stable_regular_file(path: Path) -> tuple[BinaryIO, str, int]:
    handle: BinaryIO | None = None
    try:
        before_path = os.lstat(path)
        if _is_link_or_reparse(before_path) or not stat.S_ISREG(before_path.st_mode):
            raise RuntimeToolBindingError(
                "executable must be an existing regular file, not a link"
            )
        digest = hashlib.sha256()
        handle = _open_binary_without_write_or_delete_share(path)
        opened = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or _file_identity(opened) != _file_identity(before_path)
            or _content_snapshot(opened) != _content_snapshot(before_path)
        ):
            raise RuntimeToolBindingError(
                "executable changed between path validation and open"
            )
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
        after_open = os.fstat(handle.fileno())
        after_path = os.lstat(path)
    except RuntimeToolBindingError:
        if handle is not None:
            handle.close()
        raise
    except OSError as exc:
        if handle is not None:
            handle.close()
        raise RuntimeToolBindingError("executable could not be read safely") from exc

    if (
        _is_link_or_reparse(after_path)
        or not stat.S_ISREG(after_path.st_mode)
        or _file_identity(opened) != _file_identity(after_open)
        or _file_identity(after_open) != _file_identity(after_path)
        or _content_snapshot(opened) != _content_snapshot(after_open)
        or _content_snapshot(after_open) != _content_snapshot(after_path)
    ):
        handle.close()
        raise RuntimeToolBindingError("executable changed while it was hashed")
    if after_open.st_size < 1:
        handle.close()
        raise RuntimeToolBindingError("executable must not be empty")
    handle.seek(0)
    return handle, digest.hexdigest(), after_open.st_size


def _read_stable_regular_file(path: Path) -> tuple[str, int]:
    handle, digest, size = _open_stable_regular_file(path)
    handle.close()
    return digest, size


class VerifiedRuntimeToolHandle:
    """A live handle to exact verified tool bytes, never launch authority.

    The object intentionally does not implement ``os.PathLike`` and does not
    return a path from verification.  Re-opening a path after a successful hash
    recreates the classic verify-then-spawn race.  A trusted effect executor
    must keep this object open until the process image is committed and use a
    platform primitive tied to ``fileno()`` (POSIX) or the write/delete-locked
    file (Windows).
    """

    def __init__(
        self,
        handle: BinaryIO,
        *,
        executable_sha256: str,
        executable_size: int,
        executable_path_sha256: str,
    ) -> None:
        self._handle = handle
        self.executable_sha256 = executable_sha256
        self.executable_size = executable_size
        self.executable_path_sha256 = executable_path_sha256

    @property
    def closed(self) -> bool:
        return self._handle.closed

    def fileno(self) -> int:
        if self.closed:
            raise RuntimeToolBindingError("verified runtime tool handle is closed")
        return self._handle.fileno()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "VerifiedRuntimeToolHandle":
        if self.closed:
            raise RuntimeToolBindingError("verified runtime tool handle is closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


@dataclass(frozen=True)
class RuntimeToolBinding(CanonicalContract):
    """Bind one runtime-manifest symbol to an exact executable and path."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.runtime-tool-binding"

    tool_id: str
    runtime_manifest_sha256: str
    source_revision: str
    executable_sha256: str
    executable_size: int
    executable_path_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _identifier(self.tool_id, "tool_id"))
        for name in (
            "runtime_manifest_sha256",
            "executable_sha256",
            "executable_path_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        if (
            isinstance(self.executable_size, bool)
            or not isinstance(self.executable_size, int)
            or self.executable_size < 1
        ):
            raise ValueError("executable_size must be a positive integer")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("runtime tool source_revision must match provenance")
        _require_provenance_inputs(
            self.provenance,
            (
                self.runtime_manifest_sha256,
                self.executable_sha256,
                self.executable_path_sha256,
            ),
            "runtime tool binding",
        )

    @classmethod
    def capture(
        cls,
        *,
        tool_id: str,
        runtime_manifest_sha256: str,
        source_revision: str,
        executable_path: str | os.PathLike[str],
        origin: str,
        created_at: str,
        trace_id: str | None = None,
    ) -> "RuntimeToolBinding":
        """Read and bind a stable, existing regular file without executing it."""

        resolved = _strict_absolute_path(executable_path)
        executable_sha256, executable_size = _read_stable_regular_file(resolved)
        executable_path_sha256 = _path_sha256(resolved)
        manifest_sha = _sha256(
            runtime_manifest_sha256, "runtime_manifest_sha256"
        )
        revision = _revision(source_revision, "source_revision")
        provenance = ContractProvenance(
            origin=origin,
            source_revision=revision,
            created_at=created_at,
            input_digests=(
                manifest_sha,
                executable_sha256,
                executable_path_sha256,
            ),
            trace_id=trace_id,
        )
        return cls(
            tool_id=tool_id,
            runtime_manifest_sha256=manifest_sha,
            source_revision=revision,
            executable_sha256=executable_sha256,
            executable_size=executable_size,
            executable_path_sha256=executable_path_sha256,
            provenance=provenance,
        )

    def verify_executable(
        self, executable_path: str | os.PathLike[str]
    ) -> VerifiedRuntimeToolHandle:
        """Return a retained exact-byte handle, never a re-openable path.

        The caller must close the result, preferably with ``with``.  This
        method performs no process spawn and grants no effect authority.
        """

        resolved = _strict_absolute_path(executable_path)
        handle, actual_sha256, actual_size = _open_stable_regular_file(resolved)
        mismatches: list[str] = []
        if _path_sha256(resolved) != self.executable_path_sha256:
            mismatches.append("executable_path_sha256")
        if actual_sha256 != self.executable_sha256:
            mismatches.append("executable_sha256")
        if actual_size != self.executable_size:
            mismatches.append("executable_size")
        if mismatches:
            handle.close()
            raise RuntimeToolBindingError(
                "runtime tool binding mismatch: " + ", ".join(mismatches)
            )
        return VerifiedRuntimeToolHandle(
            handle,
            executable_sha256=actual_sha256,
            executable_size=actual_size,
            executable_path_sha256=self.executable_path_sha256,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeToolBinding":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


__all__ = [
    "RuntimeToolBinding",
    "RuntimeToolBindingError",
    "VerifiedRuntimeToolHandle",
]

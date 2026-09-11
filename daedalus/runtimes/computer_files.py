"""Handle-anchored workspace file adapter behind canonical computer admission.

The v0.1.6 release fence in ``daedalus.kernel.policy.computer`` disabled every
pathname file tool because ``Path.resolve`` followed by a later pathname
operation is not a write-root boundary: another process can replace a checked
ancestor with a symbolic link or junction between the two steps. This adapter
never re-opens a pathname after checking it. Every component below the owner
configured workspace root is opened relative to the handle of its already
verified parent, links and reparse points are refused at each step, and the
final open, create, mkdir and rename happen relative to that parent handle.

Windows uses ``NtCreateFile`` with ``OBJECT_ATTRIBUTES.RootDirectory`` and
``FILE_OPEN_REPARSE_POINT``. Two Windows properties pin the chain while an
operation runs (measured 2026-09-05): any open handle below a directory makes
the kernel refuse to rename that ancestor (access denied, whatever the share
mode), and opening the parent, a directory or an effect target without
``FILE_SHARE_DELETE`` makes the kernel refuse to rename, move or delete that
object itself (sharing violation). Containment is therefore pinned for the
duration of every read, listing and effect, not merely checked. POSIX uses ``dir_fd``
relative ``openat`` semantics with ``O_NOFOLLOW``; it has no share modes, so
there the parent's identity can be verified around an observation but an
effect parent moved out between checks cannot be pinned. That residual window
is why the public adapter refuses every file effect on a non-Windows host in
the v0.1.6 release. The private POSIX backend remains for bounded measurement,
not as release authority.

Every operation admits through ``ComputerPolicy.admit`` (grant, release fence,
lexical rules), runs the trusted service's checkpoint after the chain is open,
applies the secret floor to read text and write text, and reports a
postcondition it computed: content read while the chain is unverified is
withheld, and a verification failure after an effect is reported in ``detail``
instead of being raised as if nothing had happened.

This is a trusted adapter for owner-authorized tasks, not a sandbox for
untrusted code. It is reached only through the trusted computer service's
policy and lease admission.
"""
from __future__ import annotations

import errno
import hashlib
import os
import secrets
import stat
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, FILE_TOOLS
from daedalus.sensitivity import secret_floor_rule


FILE_LIST_LIMIT = 200
_LIST_SCAN_LIMIT = 4096
_TEMPORARY_SUFFIX = ".daedalus-tmp"
_BACKUP_SUFFIX = ".daedalus-backup"
_INTERNAL_PREFIX = ".daedalus-internal-"
_CHUNK = 1 << 16
_HEX = frozenset("0123456789abcdef")
_ARGUMENTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "file.list": (frozenset({"path"}), frozenset()),
    "file.read": (frozenset({"path"}), frozenset({"path"})),
    "file.write": (frozenset({"path", "text", "expected_sha256"}), frozenset({"path", "text"})),
    "file.mkdir": (frozenset({"path"}), frozenset({"path"})),
    "file.move": (frozenset({"source", "destination", "expected_sha256"}),
                  frozenset({"source", "destination", "expected_sha256"})),
}
_EFFECT_TOOLS = frozenset({"file.write", "file.mkdir", "file.move"})


def _effect_host_available() -> bool:
    """Whether the release can pin an effect's ancestry for its whole lifetime."""
    return os.name == "nt"


class _HostRefusal(Exception):
    """A file-system refusal whose message still lacks the requested path."""

    def __init__(self, reason: str, *, missing: bool = False) -> None:
        super().__init__(reason)
        self.missing = missing


class ComputerFileEffectUncertain(ComputerRefused):
    """A file operation mutated host state but could not prove final recovery."""

    effect_state = "uncertain"

    def __init__(self, reason: str, *, recovery_paths: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.recovery_paths = recovery_paths


class ComputerFileInterrupted(KeyboardInterrupt):
    """An interruption annotated with the adapter's proven effect state."""

    def __init__(self, reason: str, *, effect_state: str,
                 recovery_paths: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.effect_state = effect_state
        self.recovery_paths = recovery_paths


class _Directory:
    """One opened directory: ``raw`` is a descriptor on POSIX and a HANDLE on Windows."""

    __slots__ = ("raw",)

    def __init__(self, raw: int) -> None:
        self.raw = raw


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while len(view):
        view = view[os.write(fd, view):]


def _read_bounded(fd: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = os.read(fd, min(_CHUNK, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


_REFUSED_CHARACTERS = frozenset('/\\:\x00*?<>"|')


def _validate_component(part: Any) -> str:
    """Own the portable character class instead of inheriting it from the host.

    Separators, drive/stream colons, NUL, Windows wildcards and quoting
    characters, and control characters are refused on every platform, and a
    requested component must already be NFC-normalized.

    The NFC rule bounds what this adapter accepts; it does not make the host
    normalize. NTFS stores a name as written (measured 2026-09-05), so a
    pre-existing non-NFC entry remains a distinct entry that no request can
    address: the name as listed is refused here, and its NFC spelling does not
    exist on disk. ``file.list`` still reports such an entry rather than
    counting it withheld. Writing the NFC spelling therefore creates a second,
    separate entry and leaves the unaddressable one's bytes untouched -- it is
    not a replacement bypass and loses no data.
    """
    if (not isinstance(part, str) or not part or len(part) > 255 or part in (".", "..")
            or any(ch in _REFUSED_CHARACTERS or ord(ch) < 32 or ord(ch) == 127 for ch in part)):
        raise ComputerRefused("path component is invalid")
    if unicodedata.normalize("NFC", part) != part:
        raise ComputerRefused("path component must be NFC-normalized text")
    if os.name == "nt":
        try:
            utf16_length = len(part.encode("utf-16-le")) // 2
        except UnicodeEncodeError:
            raise ComputerRefused("path component is invalid on Windows") from None
        reserved = getattr(os.path, "isreserved", None)
        if (utf16_length > 255 or part.rstrip(" .") != part
                or (reserved(part) if reserved else PureWindowsPath(part).is_reserved())):
            raise ComputerRefused("path component is invalid on Windows")
    return part


def _errno_reason(exc: OSError) -> _HostRefusal:
    code = exc.errno
    if code == errno.ENOENT:
        return _HostRefusal("does not exist", missing=True)
    if code == errno.EEXIST:
        return _HostRefusal("already exists")
    if code == errno.ELOOP:
        return _HostRefusal("is a link and links are refused inside the computer workspace")
    if code == errno.EMLINK:
        return _HostRefusal("has too many links")
    if code == errno.ENOTDIR:
        return _HostRefusal("is not a directory")
    if code == errno.EISDIR:
        return _HostRefusal("is a directory")
    if code in (errno.EACCES, errno.EPERM):
        return _HostRefusal("access denied")
    if code == errno.EXDEV:
        return _HostRefusal("cannot be moved across file systems")
    return _HostRefusal(f"failed with {errno.errorcode.get(code, code)}")


class _PosixBackend:
    """``openat`` style traversal: every open is relative to a verified directory fd."""

    def __init__(self) -> None:
        required = {os.open, os.mkdir, os.rename, os.link, os.unlink, os.stat}
        if (os.name == "nt" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
                or not required <= os.supports_dir_fd or os.listdir not in os.supports_fd):
            raise ComputerRefused("handle-relative file I/O is unavailable on this host")
        self._dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        self._file_flags = os.O_NOFOLLOW | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)

    def open_root(self, workspace: Path) -> _Directory:
        if not workspace.is_absolute() or workspace.anchor != "/":
            raise _HostRefusal("is not an absolute POSIX directory")
        try:
            directory = _Directory(os.open("/", self._dir_flags))
        except OSError as exc:
            raise _errno_reason(exc) from None
        try:
            # O_NOFOLLOW protects only the final component.  Walking from the
            # filesystem root one component at a time also refuses a replaced
            # ancestor of the configured workspace instead of following it.
            for part in workspace.parts[1:]:
                child = self._open_directory_at(directory, part)
                self.close_directory(directory)
                directory = child
            if self.identity(directory) != self.expected_identity(workspace):
                raise _HostRefusal("is not at its configured location")
        except BaseException:
            self.close_directory(directory)
            raise
        return directory

    def open_child_directory(self, parent: _Directory, name: str) -> _Directory:
        _validate_component(name)
        return self._open_directory_at(parent, name)

    def _open_directory_at(self, parent: _Directory, name: str) -> _Directory:
        try:
            return _Directory(os.open(name, self._dir_flags, dir_fd=parent.raw))
        except OSError as exc:
            # Linux commonly reports O_NOFOLLOW|O_DIRECTORY on a symlink as
            # ENOTDIR rather than ELOOP.  Inspect without following solely to
            # preserve an accurate refusal reason; the failed open is the gate.
            if exc.errno == errno.ENOTDIR:
                try:
                    info = os.stat(name, dir_fd=parent.raw, follow_symlinks=False)
                except OSError:
                    pass
                else:
                    if stat.S_ISLNK(info.st_mode):
                        raise _HostRefusal(
                            "is a link and links are refused inside the computer workspace"
                        ) from None
            raise _errno_reason(exc) from None

    def open_file(self, parent: _Directory, name: str, mode: str) -> int:
        _validate_component(name)
        if mode == "create":
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        elif mode in ("read", "modify", "hold"):
            # POSIX has no share modes: "hold" cannot exclude writers here.
            flags = os.O_RDONLY
        else:
            raise ComputerRefused("unknown file open mode")
        try:
            fd = os.open(name, flags | self._file_flags, 0o644, dir_fd=parent.raw)
        except OSError as exc:
            raise _errno_reason(exc) from None
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise _HostRefusal("is a directory" if stat.S_ISDIR(info.st_mode) else "is not a regular file")
        return fd

    def file_name(self, fd: int) -> str | None:
        """POSIX cannot report the current name of an open descriptor portably."""
        return None

    def file_at(self, parent: _Directory, name: str, fd: int) -> bool | None:
        """POSIX cannot bind an open descriptor to a current directory entry portably."""
        return None

    def create_directory(self, parent: _Directory, name: str) -> None:
        _validate_component(name)
        try:
            os.mkdir(name, 0o755, dir_fd=parent.raw)
        except OSError as exc:
            raise _errno_reason(exc) from None

    def rename(self, source_parent: _Directory, source_name: str, fd: int,
               destination_parent: _Directory, destination_name: str, *, replace: bool) -> None:
        _validate_component(source_name)
        _validate_component(destination_name)
        try:
            if replace:
                os.rename(source_name, destination_name, src_dir_fd=source_parent.raw,
                          dst_dir_fd=destination_parent.raw)
                return
            # link+unlink never overwrites an existing destination, unlike rename(2).
            os.link(source_name, destination_name, src_dir_fd=source_parent.raw,
                    dst_dir_fd=destination_parent.raw, follow_symlinks=False)
            os.unlink(source_name, dir_fd=source_parent.raw)
        except OSError as exc:
            raise _errno_reason(exc) from None

    def unlink(self, parent: _Directory, name: str, fd: int) -> None:
        _validate_component(name)
        try:
            os.unlink(name, dir_fd=parent.raw)
        except OSError as exc:
            raise _errno_reason(exc) from None

    def entries(self, directory: _Directory) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        try:
            names = os.listdir(directory.raw)
        except OSError as exc:
            raise _errno_reason(exc) from None
        for name in names[:_LIST_SCAN_LIMIT + 1]:
            try:
                info = os.stat(name, dir_fd=directory.raw, follow_symlinks=False)
            except OSError:
                found.append((name, "other"))
                continue
            if stat.S_ISLNK(info.st_mode):
                kind = "link"
            elif stat.S_ISDIR(info.st_mode):
                kind = "directory"
            elif stat.S_ISREG(info.st_mode):
                kind = "file"
            else:
                kind = "other"
            found.append((name, kind))
        return found

    def identity(self, directory: _Directory) -> tuple[int, int]:
        info = os.fstat(directory.raw)
        return (info.st_dev, info.st_ino)

    def expected_identity(self, path: Path) -> tuple[int, int] | None:
        try:
            info = os.lstat(path)
        except OSError:
            return None
        return (info.st_dev, info.st_ino)

    def close_directory(self, directory: _Directory) -> None:
        os.close(directory.raw)


class _NTBackend:
    """``NtCreateFile`` relative to a RootDirectory handle, opening reparse points as themselves."""

    _FILE_OPEN, _FILE_CREATE = 1, 2
    _FILE_DIRECTORY_FILE, _FILE_NON_DIRECTORY_FILE = 0x1, 0x40
    _FILE_SYNCHRONOUS_IO_NONALERT, _FILE_OPEN_REPARSE_POINT = 0x20, 0x200000
    _SYNCHRONIZE, _DELETE = 0x100000, 0x10000
    _FILE_LIST_DIRECTORY, _FILE_TRAVERSE, _FILE_READ_ATTRIBUTES = 0x1, 0x20, 0x80
    _FILE_GENERIC_READ, _FILE_GENERIC_WRITE = 0x120089, 0x120116
    _FILE_SHARE_READ, _FILE_SHARE_READ_WRITE = 1, 3
    _OBJ_CASE_INSENSITIVE, _FILE_ATTRIBUTE_NORMAL = 0x40, 0x80
    _FILE_ATTRIBUTE_DIRECTORY, _FILE_ATTRIBUTE_REPARSE_POINT = 0x10, 0x400
    _FILE_FLAG_BACKUP_SEMANTICS, _FILE_FLAG_OPEN_REPARSE_POINT = 0x02000000, 0x00200000
    _STATUS_NO_MORE_FILES = 0x80000006
    _STATUS_REASONS = {
        0xC0000034: "does not exist", 0xC000003A: "does not exist", 0xC000000F: "does not exist",
        0xC0000035: "already exists", 0xC00000BA: "is a directory", 0xC0000103: "is not a directory",
        0xC0000022: "access denied", 0xC0000043: "is in use by another process",
        0xC0000033: "has an invalid name", 0xC0000056: "is pending deletion",
        0xC0000101: "is a directory that is not empty",
    }

    def __init__(self) -> None:
        if os.name != "nt":
            raise ComputerRefused("the Windows file backend is unavailable on this platform")
        import ctypes
        import msvcrt
        c = ctypes
        self.c, self.msvcrt = c, msvcrt

        class UNICODE_STRING(c.Structure):
            _fields_ = [("Length", c.c_ushort), ("MaximumLength", c.c_ushort), ("Buffer", c.c_wchar_p)]

        class OBJECT_ATTRIBUTES(c.Structure):
            _fields_ = [("Length", c.c_ulong), ("RootDirectory", c.c_void_p),
                        ("ObjectName", c.POINTER(UNICODE_STRING)), ("Attributes", c.c_ulong),
                        ("SecurityDescriptor", c.c_void_p), ("SecurityQualityOfService", c.c_void_p)]

        class IO_STATUS_BLOCK(c.Structure):
            _fields_ = [("Status", c.c_void_p), ("Information", c.c_void_p)]

        class FILE_ATTRIBUTE_TAG_INFO(c.Structure):
            _fields_ = [("FileAttributes", c.c_ulong), ("ReparseTag", c.c_ulong)]

        class FILE_RENAME_INFORMATION(c.Structure):
            _fields_ = [("ReplaceIfExists", c.c_ubyte), ("RootDirectory", c.c_void_p),
                        ("FileNameLength", c.c_ulong), ("FileName", c.c_wchar * 1)]

        self.UNICODE_STRING, self.OBJECT_ATTRIBUTES = UNICODE_STRING, OBJECT_ATTRIBUTES
        self.IO_STATUS_BLOCK, self.TAG_INFO = IO_STATUS_BLOCK, FILE_ATTRIBUTE_TAG_INFO
        self.RENAME_INFO = FILE_RENAME_INFORMATION
        self.nt = c.WinDLL("ntdll", use_last_error=True)
        self.k = c.WinDLL("kernel32", use_last_error=True)
        self.nt.NtCreateFile.argtypes = [
            c.POINTER(c.c_void_p), c.c_ulong, c.POINTER(OBJECT_ATTRIBUTES), c.POINTER(IO_STATUS_BLOCK),
            c.POINTER(c.c_longlong), c.c_ulong, c.c_ulong, c.c_ulong, c.c_ulong, c.c_void_p, c.c_ulong]
        self.nt.NtCreateFile.restype = c.c_ulong
        self.nt.NtSetInformationFile.argtypes = [c.c_void_p, c.POINTER(IO_STATUS_BLOCK), c.c_void_p, c.c_ulong, c.c_int]
        self.nt.NtSetInformationFile.restype = c.c_ulong
        self.nt.NtQueryDirectoryFile.argtypes = [
            c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p, c.POINTER(IO_STATUS_BLOCK), c.c_void_p,
            c.c_ulong, c.c_int, c.c_ubyte, c.c_void_p, c.c_ubyte]
        self.nt.NtQueryDirectoryFile.restype = c.c_ulong
        self.k.CreateFileW.argtypes = [c.c_wchar_p, c.c_ulong, c.c_ulong, c.c_void_p, c.c_ulong, c.c_ulong, c.c_void_p]
        self.k.CreateFileW.restype = c.c_void_p
        self.k.CloseHandle.argtypes = [c.c_void_p]
        self.k.CloseHandle.restype = c.c_int
        self.k.GetFileInformationByHandleEx.argtypes = [c.c_void_p, c.c_int, c.c_void_p, c.c_ulong]
        self.k.GetFileInformationByHandleEx.restype = c.c_int
        self.k.GetFinalPathNameByHandleW.argtypes = [c.c_void_p, c.c_wchar_p, c.c_ulong, c.c_ulong]
        self.k.GetFinalPathNameByHandleW.restype = c.c_ulong
        self._invalid_handle = (1 << (8 * c.sizeof(c.c_void_p))) - 1

    # -- primitives -------------------------------------------------------

    def _status_refusal(self, status: int) -> _HostRefusal:
        reason = self._STATUS_REASONS.get(status)
        if reason is None:
            return _HostRefusal(f"failed with NTSTATUS 0x{status:08X}")
        return _HostRefusal(reason, missing=reason == "does not exist")

    def _open(self, parent: int, name: str, access: int, disposition: int, options: int,
              share: int | None = None) -> int:
        _validate_component(name)
        c = self.c
        object_name = self.UNICODE_STRING()
        object_name.Buffer = name
        # ``len(str)`` counts Unicode code points, while UNICODE_STRING lengths
        # count UTF-16 bytes.  Astral characters therefore occupy four bytes.
        object_name.Length = object_name.MaximumLength = len(name.encode("utf-16-le"))
        attributes = self.OBJECT_ATTRIBUTES()
        attributes.Length = c.sizeof(attributes)
        attributes.RootDirectory = parent
        attributes.ObjectName = c.pointer(object_name)
        attributes.Attributes = self._OBJ_CASE_INSENSITIVE
        status_block = self.IO_STATUS_BLOCK()
        handle = c.c_void_p()
        # Every opened object denies delete sharing while its handle is live.
        # That pins observation and effect names against a concurrent move out
        # of the authorized workspace between admission and verification. The
        # Replacement does not need a share-mode exception: the adapter moves
        # the verified target through that target's own DELETE-capable handle.
        if share is None:
            share = self._FILE_SHARE_READ_WRITE
        status = self.nt.NtCreateFile(
            c.byref(handle), access | self._SYNCHRONIZE, c.byref(attributes), c.byref(status_block), None,
            self._FILE_ATTRIBUTE_NORMAL, share, disposition,
            options | self._FILE_SYNCHRONOUS_IO_NONALERT | self._FILE_OPEN_REPARSE_POINT, None, 0)
        if status & 0x80000000 or not handle.value:
            raise self._status_refusal(status)
        return handle.value

    def _attributes(self, handle: int) -> int:
        info = self.TAG_INFO()
        if not self.k.GetFileInformationByHandleEx(handle, 9, self.c.byref(info), self.c.sizeof(info)):
            code = self.c.get_last_error()
            raise _HostRefusal(f"attributes are unavailable (Windows error {code})")
        return info.FileAttributes

    def _checked(self, handle: int, *, directory: bool, name: str | None = None) -> int:
        """Refuse reparse points, wrong object types and 8.3 aliases on an opened handle."""
        try:
            attributes = self._attributes(handle)
            if attributes & self._FILE_ATTRIBUTE_REPARSE_POINT:
                raise _HostRefusal("is a link or reparse point and links are refused inside the computer workspace")
            if bool(attributes & self._FILE_ATTRIBUTE_DIRECTORY) != directory:
                raise _HostRefusal("is a directory" if not directory else "is not a directory")
            # The lexical rules saw the requested name; NTFS may have resolved a
            # short 8.3 alias to a different long name. Bind the two here.
            if name is not None and os.path.basename(self._final_path(handle)) != os.path.normcase(name):
                raise _HostRefusal("must be addressed by its full name; short-name aliases are refused")
        except BaseException:
            self.k.CloseHandle(handle)
            raise
        return handle

    def _final_path(self, handle: int) -> str:
        buffer = self.c.create_unicode_buffer(32768)
        length = self.k.GetFinalPathNameByHandleW(handle, buffer, 32768, 0)
        if not length or length >= 32768:
            raise _HostRefusal("final path is unavailable")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return os.path.normcase(value)

    def _set_information(self, handle: int, payload: bytes, information_class: int) -> None:
        buffer = self.c.create_string_buffer(payload, len(payload))
        status_block = self.IO_STATUS_BLOCK()
        status = self.nt.NtSetInformationFile(handle, self.c.byref(status_block), buffer, len(payload), information_class)
        if status & 0x80000000:
            raise self._status_refusal(status)

    # -- backend interface --------------------------------------------------

    def open_root(self, workspace: Path) -> _Directory:
        path = str(workspace)
        if path.startswith("\\\\?\\"):
            pass
        elif path.startswith("\\\\"):
            path = "\\\\?\\UNC\\" + path[2:]
        else:
            path = "\\\\?\\" + path
        handle = self.k.CreateFileW(
            path, self._FILE_LIST_DIRECTORY | self._FILE_TRAVERSE | self._FILE_READ_ATTRIBUTES | self._SYNCHRONIZE,
            self._FILE_SHARE_READ_WRITE, None, 3,
            self._FILE_FLAG_BACKUP_SEMANTICS | self._FILE_FLAG_OPEN_REPARSE_POINT, None)
        if handle is None or handle == self._invalid_handle:
            code = self.c.get_last_error()
            if code in (2, 3):
                raise _HostRefusal("does not exist", missing=True)
            raise _HostRefusal("access denied" if code == 5 else f"failed with Windows error {code}")
        directory = _Directory(self._checked(handle, directory=True))
        if self.identity(directory) != self.expected_identity(workspace):
            self.close_directory(directory)
            raise _HostRefusal("is not at its configured location")
        return directory

    def open_child_directory(self, parent: _Directory, name: str) -> _Directory:
        handle = self._open(parent.raw, name, self._FILE_LIST_DIRECTORY | self._FILE_TRAVERSE | self._FILE_READ_ATTRIBUTES,
                            self._FILE_OPEN, self._FILE_DIRECTORY_FILE)
        return _Directory(self._checked(handle, directory=True, name=name))

    def open_file(self, parent: _Directory, name: str, mode: str) -> int:
        share = None
        if mode == "create":
            access, disposition, flags = self._FILE_GENERIC_READ | self._FILE_GENERIC_WRITE | self._DELETE, self._FILE_CREATE, 0
            # The bytes being created (including replacement temporaries) are
            # an effect result: exclude competing writers and renames until
            # this handle has been verified or performs its own rename.
            share = self._FILE_SHARE_READ
        elif mode == "read":
            access, disposition, flags = self._FILE_GENERIC_READ, self._FILE_OPEN, os.O_RDONLY
        elif mode == "modify":
            access, disposition, flags = self._FILE_GENERIC_READ | self._DELETE, self._FILE_OPEN, os.O_RDONLY
            # Bind expected_sha256 to the bytes and name this handle moves:
            # competing writers and renames are excluded until our rename.
            share = self._FILE_SHARE_READ
        elif mode == "hold":
            # The verified target itself is moved aside by this handle before
            # installation, so competing writers and renames can both be
            # excluded without blocking our own handle-relative rename.
            access, disposition, flags = self._FILE_GENERIC_READ | self._DELETE, self._FILE_OPEN, os.O_RDONLY
            share = self._FILE_SHARE_READ
        else:
            raise ComputerRefused("unknown file open mode")
        handle = self._checked(self._open(parent.raw, name, access, disposition, self._FILE_NON_DIRECTORY_FILE, share),
                               directory=False, name=name)
        try:
            return self.msvcrt.open_osfhandle(handle, flags)
        except OSError as exc:
            self.k.CloseHandle(handle)
            raise _HostRefusal(f"cannot be attached to a descriptor: {exc}") from None

    def file_name(self, fd: int) -> str | None:
        """Normalized current name of an open file, from its handle's final path."""
        return os.path.basename(self._final_path(self.msvcrt.get_osfhandle(fd)))

    def file_at(self, parent: _Directory, name: str, fd: int) -> bool:
        """Whether ``fd`` currently names ``name`` below this exact open parent."""
        expected = os.path.normcase(os.path.join(self.identity(parent), name))
        actual = self._final_path(self.msvcrt.get_osfhandle(fd))
        return actual == expected

    def create_directory(self, parent: _Directory, name: str) -> None:
        handle = self._open(parent.raw, name, self._FILE_LIST_DIRECTORY | self._FILE_READ_ATTRIBUTES,
                            self._FILE_CREATE, self._FILE_DIRECTORY_FILE)
        self.k.CloseHandle(self._checked(handle, directory=True, name=name))

    def rename(self, source_parent: _Directory, source_name: str, fd: int,
               destination_parent: _Directory, destination_name: str, *, replace: bool) -> None:
        _validate_component(destination_name)
        name = destination_name.encode("utf-16-le")
        # FILE_RENAME_INFORMATION: BOOLEAN ReplaceIfExists padded to pointer size,
        # HANDLE RootDirectory, ULONG FileNameLength, WCHAR FileName[].
        pointer = self.c.sizeof(self.c.c_void_p)
        # replace=True remains available to the backend, but the public adapter
        # intentionally uses only no-replace renames.  Replacement is a
        # handle-bound two-rename protocol, so an unobserved occupant of the
        # requested target is detected as a collision and never superseded.
        flags = (0x1 | 0x2) if replace else 0
        payload = (flags.to_bytes(pointer, "little")
                   + destination_parent.raw.to_bytes(pointer, "little")
                   + len(name).to_bytes(4, "little") + name)
        # The kernel requires at least sizeof(FILE_RENAME_INFORMATION), even
        # when a one-code-unit destination makes the variable payload shorter.
        payload = payload.ljust(self.c.sizeof(self.RENAME_INFO), b"\x00")
        self._set_information(self.msvcrt.get_osfhandle(fd), payload, 65 if replace else 10)

    def unlink(self, parent: _Directory, name: str, fd: int) -> None:
        # FILE_DISPOSITION_INFORMATION: the file disappears when its last handle closes.
        self._set_information(self.msvcrt.get_osfhandle(fd), b"\x01", 13)

    def entries(self, directory: _Directory) -> list[tuple[str, str]]:
        c = self.c
        found: list[tuple[str, str]] = []
        size = 1 << 16
        buffer = c.create_string_buffer(size)
        restart = 1
        while len(found) <= _LIST_SCAN_LIMIT:
            status_block = self.IO_STATUS_BLOCK()
            status = self.nt.NtQueryDirectoryFile(directory.raw, None, None, None, c.byref(status_block),
                                                  buffer, size, 1, 0, None, restart)
            restart = 0
            if status == self._STATUS_NO_MORE_FILES:
                break
            if status & 0x80000000:
                raise self._status_refusal(status)
            raw = buffer.raw
            offset = 0
            while True:
                next_offset = int.from_bytes(raw[offset:offset + 4], "little")
                attributes = int.from_bytes(raw[offset + 56:offset + 60], "little")
                name_length = int.from_bytes(raw[offset + 60:offset + 64], "little")
                name = raw[offset + 64:offset + 64 + name_length].decode("utf-16-le")
                if name not in (".", ".."):
                    if attributes & self._FILE_ATTRIBUTE_REPARSE_POINT:
                        kind = "link"
                    elif attributes & self._FILE_ATTRIBUTE_DIRECTORY:
                        kind = "directory"
                    else:
                        kind = "file"
                    found.append((name, kind))
                if not next_offset:
                    break
                offset += next_offset
        return found

    def identity(self, directory: _Directory) -> str:
        return self._final_path(directory.raw)

    def expected_identity(self, path: Path) -> str:
        return os.path.normcase(str(path))

    def close_directory(self, directory: _Directory) -> None:
        self.k.CloseHandle(directory.raw)


class WorkspaceFiles:
    """Owner-workspace file tools whose every effect is anchored to a verified directory handle.

    ``execute(tool, arguments)`` mirrors the desktop and browser adapters and returns a
    JSON-safe observation. ``checkpoint`` is the trusted service's cooperative
    cancellation and re-admission probe; it runs after the parent directory is
    open and before every observation or effect.
    """

    def __init__(self, policy: ComputerPolicy, checkpoint: Callable[[], None]) -> None:
        if not callable(checkpoint):
            raise ComputerRefused("checkpoint must be callable")
        self.policy = policy
        self.checkpoint = checkpoint
        self._backend: Any = _NTBackend() if os.name == "nt" else _PosixBackend()

    @property
    def pinned(self) -> bool:
        """True when the host refuses to move the open chain (Windows share modes)."""
        return os.name == "nt"

    def close(self) -> None:
        return None

    # -- entry ----------------------------------------------------------------

    def execute(self, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool not in FILE_TOOLS:
            raise ComputerRefused(f"unknown file tool: {tool}")
        if not isinstance(arguments, Mapping):
            raise ComputerRefused("tool arguments must be an object")
        args = dict(arguments)
        allowed, required = _ARGUMENTS[tool]
        if set(args) - allowed or required - set(args):
            raise ComputerRefused("tool arguments do not match its schema")
        for key, value in args.items():
            if not isinstance(value, str):
                raise ComputerRefused(f"{key} must be text")
        digest = args.get("expected_sha256")
        if digest is not None and (len(digest) != 64 or set(digest) - _HEX):
            raise ComputerRefused("expected_sha256 must be an observed lowercase SHA-256")
        # The same admission the canonical lease issuer applies: owner grant,
        # release fence and lexical path rules. A direct caller cannot execute
        # a disabled or ungranted tool through this seam.
        self.policy.admit(tool, args)
        if tool in _EFFECT_TOOLS and not _effect_host_available():
            raise ComputerRefused("workspace file effects are unavailable outside the Windows release target")
        handler = {"file.list": self._list, "file.read": self._read, "file.write": self._write,
                   "file.mkdir": self._mkdir, "file.move": self._move}[tool]
        return handler(args)

    # -- traversal -------------------------------------------------------------

    def _components(self, value: Any) -> list[str]:
        if not isinstance(value, str) or "\x00" in value or len(value) > 1000:
            raise ComputerRefused("path must be bounded text")
        # The policy's lexical rules refuse escapes, protected and reserved names
        # and linked paths. The components used for traversal are taken from the
        # REQUESTED text, not from a resolved path, so that an 8.3 alias the
        # resolver would expand is still compared against the on-disk long name.
        try:
            self.policy.path(value)
        except ComputerRefused:
            raise
        except NotADirectoryError:
            raise ComputerRefused("path has a non-directory ancestor") from None
        except OSError as exc:
            raise ComputerRefused(f"path cannot be inspected: {type(exc).__name__}") from None
        parts = [part for part in value.replace("\\", "/").split("/") if part not in ("", ".")]
        if any(part.casefold().startswith(_INTERNAL_PREFIX) for part in parts):
            raise ComputerRefused("adapter recovery paths are reserved")
        return [_validate_component(part) for part in parts]

    def _target(self, value: Any, *, what: str) -> tuple[list[str], str]:
        parts = self._components(value)
        if not parts:
            raise ComputerRefused(f"the workspace root itself is not a {what} target")
        return parts, "/".join(parts)

    def _root(self) -> _Directory:
        try:
            return self._backend.open_root(self.policy.workspace)
        except _HostRefusal as exc:
            raise ComputerRefused(f"workspace '{self.policy.workspace}' {exc}") from None

    def _child(self, directory: _Directory, name: str, shown: str) -> _Directory:
        try:
            return self._backend.open_child_directory(directory, name)
        except _HostRefusal as exc:
            raise ComputerRefused(f"'{shown}' {exc}") from None

    def _file(self, parent: _Directory, name: str, mode: str, shown: str) -> int:
        try:
            return self._backend.open_file(parent, name, mode)
        except _HostRefusal as exc:
            raise ComputerRefused(f"'{shown}' {exc}") from None

    def _open_chain(self, parts: list[str], *, stop_before_last: bool) -> _Directory:
        """Open root, then each directory relative to its parent's handle."""
        directory = self._root()
        count = len(parts) - 1 if stop_before_last else len(parts)
        try:
            for index in range(count):
                child = self._child(directory, parts[index], "/".join(parts[:index + 1]))
                self._backend.close_directory(directory)
                directory = child
        except BaseException:
            self._backend.close_directory(directory)
            raise
        return directory

    def _expected(self, parts: list[str]) -> Path:
        return self.policy.workspace.joinpath(*parts)

    def _in_place(self, directory: _Directory, expected: Path) -> bool:
        try:
            return self._backend.identity(directory) == self._backend.expected_identity(expected)
        except _HostRefusal:
            return False

    def _admit_effect(self, directory: _Directory, expected: Path, shown: str) -> None:
        """Checkpoint, then prove the open directory still sits at its name before an effect."""
        self.checkpoint()
        if not self._in_place(directory, expected):
            raise ComputerRefused(f"'{shown}' changed during the operation; no effect was performed")

    _DRIFT = ("no longer resolves to the requested path; the operation went through the "
              "opened directory handle and its current location is unverified")

    def _admit_observation(self, directory: _Directory, expected: Path, shown: str) -> None:
        """Cooperative checkpoint and location proof before returning workspace data."""
        self.checkpoint()
        if not self._in_place(directory, expected):
            raise ComputerRefused(f"'{shown}' changed during the observation; data was withheld")

    # -- file content ---------------------------------------------------------

    def _regular(self, fd: int, shown: str) -> bytes:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ComputerRefused(f"'{shown}' is not a regular file")
        if info.st_nlink != 1:
            raise ComputerRefused(f"'{shown}' is hard-linked and refused")
        limit = self.policy.max_file_bytes
        if info.st_size > limit:
            raise ComputerRefused(f"'{shown}' exceeds the configured size")
        os.lseek(fd, 0, os.SEEK_SET)
        data = _read_bounded(fd, limit)
        if len(data) > limit:
            raise ComputerRefused(f"'{shown}' exceeds the configured size")
        return data

    def _current(self, parent: _Directory, name: str, shown: str) -> bytes | None:
        """Bytes of an existing regular file below ``parent``; None when absent."""
        try:
            fd = self._backend.open_file(parent, name, "read")
        except _HostRefusal as exc:
            if exc.missing:
                return None
            raise ComputerRefused(f"'{shown}' {exc}") from None
        try:
            return self._regular(fd, shown)
        finally:
            os.close(fd)

    def _matches(self, parent: _Directory, name: str, shown: str, digest: str) -> bool:
        data = self._current(parent, name, shown)
        return data is not None and hashlib.sha256(data).hexdigest() == digest

    def _host_note(self, shown: str, exc: OSError) -> str:
        """Name the failure class and the requested path, never the host's text.

        A raw ``OSError`` message can carry an absolute host path, so only its
        class reaches a reported detail.
        """
        return f"verification failed: re-reading '{shown}' raised {type(exc).__name__}"

    def _verify(self, parent: _Directory, name: str, shown: str, digest: str) -> tuple[bool, str]:
        """Post-effect content check that reports instead of raising."""
        try:
            return self._matches(parent, name, shown, digest), ""
        except ComputerRefused as exc:
            return False, f"verification failed: {exc}"
        except OSError as exc:
            # The effect already landed; a broken re-read is an unverified
            # postcondition, not a failed operation.
            return False, self._host_note(shown, exc)

    def _absent(self, parent: _Directory, name: str, shown: str) -> tuple[bool, str]:
        try:
            return self._current(parent, name, shown) is None, ""
        except ComputerRefused as exc:
            return False, f"verification failed: {exc}"
        except OSError as exc:
            return False, self._host_note(shown, exc)

    def _readback_matches(self, parent: _Directory, name: str, shown: str, data: bytes) -> bool:
        """Re-open below the same parent and compare safe bytes before disclosure."""
        try:
            current = self._current(parent, name, shown)
        except ComputerRefused:
            return False
        return current == data

    def _discard(self, parent: _Directory, name: str, fd: int) -> str:
        try:
            self._backend.unlink(parent, name, fd)
        except (_HostRefusal, OSError) as exc:
            return f"; temporary '{name}' could not be removed ({exc})"
        return ""

    def _create(self, parent: _Directory, name: str, data: bytes, shown: str) -> None:
        try:
            fd = self._file(parent, name, "create", shown)
        except KeyboardInterrupt as exc:
            # A Python signal can be delivered immediately after NtCreateFile
            # returned but before its descriptor reached this frame.  Without
            # a handle there is no honest way to distinguish that case from a
            # pre-syscall interrupt.
            raise ComputerFileInterrupted(
                f"creating '{shown}' was interrupted at the create boundary",
                effect_state="uncertain", recovery_paths=(shown,),
            ) from exc
        failure: BaseException | None = None
        discard_note = ""
        try:
            try:
                _write_all(fd, data)
                os.fsync(fd)
            except BaseException as exc:
                failure = exc
                discard_note = self._discard(parent, name, fd)
        finally:
            os.close(fd)

        if failure is None:
            return
        absent, absence_note = self._absent(parent, name, shown)
        cleaned = not discard_note and absent
        cleanup_note = discard_note or absence_note
        if isinstance(failure, KeyboardInterrupt):
            raise ComputerFileInterrupted(
                f"creating '{shown}' was interrupted"
                + ("; the partial file was removed" if cleaned else f"; cleanup is unverified{cleanup_note}"),
                effect_state="none" if cleaned else "uncertain",
                recovery_paths=() if cleaned else (shown,),
            ) from failure
        if not isinstance(failure, Exception):
            if not cleaned:
                failure.add_note(f"cleanup of partial file '{shown}' is unverified{cleanup_note}")
            raise failure
        if not cleaned:
            raise ComputerFileEffectUncertain(
                f"writing '{shown}' failed: {failure}; cleanup is unverified{cleanup_note}",
                recovery_paths=(shown,),
            ) from failure
        raise ComputerRefused(f"writing '{shown}' failed: {failure}") from None

    def _replace(self, parent: _Directory, name: str, data: bytes, expected: str, shown: str) -> None:
        """Replace through held handles without ever overwriting an unknown target.

        The verified original is first renamed to a private backup through its
        own handle.  The held temporary is then renamed to the now-free public
        name with ``replace=False``.  A hostile create in that unavoidable
        interval therefore causes a collision; rollback also uses no-replace,
        so neither installation nor recovery can destroy unobserved bytes.
        """
        hold = self._file(parent, name, "hold", shown)
        temporary = f"{_INTERNAL_PREFIX}{secrets.token_hex(8)}{_TEMPORARY_SUFFIX}"
        backup = f"{_INTERNAL_PREFIX}{secrets.token_hex(8)}{_BACKUP_SUFFIX}"
        prefix = shown.rpartition("/")[0]
        temporary_shown = f"{prefix}/{temporary}" if prefix else temporary
        backup_shown = f"{prefix}/{backup}" if prefix else backup
        try:
            if hashlib.sha256(self._regular(hold, shown)).hexdigest() != expected:
                raise ComputerRefused(f"replacing '{shown}' failed: its content changed before replacement")
            try:
                fd = self._file(parent, temporary, "create", shown)
            except KeyboardInterrupt as exc:
                raise ComputerFileInterrupted(
                    f"replacing '{shown}' was interrupted at the temporary-create boundary",
                    effect_state="uncertain", recovery_paths=(temporary_shown,),
                ) from exc

            failure: BaseException | None = None
            original_moved: bool | None = False
            installed: bool | None = False
            backup_owned = False
            notes: list[str] = []
            try:
                try:
                    _write_all(fd, data)
                    os.fsync(fd)
                    held_name = self._backend.file_name(hold)
                    if held_name is not None and held_name != os.path.normcase(name):
                        raise ComputerRefused("the target was renamed during replacement")
                    original_moved = None
                    self._backend.rename(parent, name, hold, parent, backup, replace=False)
                    original_moved = True
                    backup_owned = True
                    installed = None
                    self._backend.rename(parent, temporary, fd, parent, name, replace=False)
                    installed = True
                except BaseException as exc:
                    failure = exc

                    # Resolve the ambiguous "signal/error after the syscall"
                    # boundary from the still-open Windows handles.  POSIX has
                    # no portable equivalent and is never a public effect host.
                    try:
                        held_name = self._backend.file_name(hold)
                    except (_HostRefusal, OSError):
                        held_name = None
                    try:
                        temporary_name = self._backend.file_name(fd)
                    except (_HostRefusal, OSError):
                        temporary_name = None
                    if held_name is not None:
                        if held_name == os.path.normcase(backup):
                            original_moved, backup_owned = True, True
                        elif held_name == os.path.normcase(name):
                            original_moved = False
                    if temporary_name is not None:
                        if temporary_name == os.path.normcase(name):
                            installed = True
                        elif temporary_name == os.path.normcase(temporary):
                            installed = False

                    if installed is False:
                        discard_note = self._discard(parent, temporary, fd)
                        if discard_note:
                            notes.append(discard_note)
                        if original_moved is True:
                            try:
                                original_moved = None
                                self._backend.rename(parent, backup, hold, parent, name, replace=False)
                                original_moved = False
                            except BaseException as cleanup_exc:
                                notes.append(f"; original recovery failed ({cleanup_exc})")
                                try:
                                    current = self._backend.file_name(hold)
                                except (_HostRefusal, OSError):
                                    current = None
                                if current is not None:
                                    if current == os.path.normcase(name):
                                        original_moved = False
                                    elif current == os.path.normcase(backup):
                                        original_moved, backup_owned = True, True
                    # If installation may have completed, deleting through the
                    # temporary handle could delete the public result. Preserve
                    # both handles' objects for service-owned reconciliation.
                else:
                    try:
                        discard_note = self._discard(parent, backup, hold)
                    except BaseException as exc:
                        failure = exc
                    else:
                        if discard_note:
                            notes.append(discard_note)
            finally:
                os.close(fd)
        finally:
            os.close(hold)

        if failure is None:
            backup_absent, backup_note = self._absent(parent, backup, backup_shown)
            if not backup_absent:
                raise ComputerFileEffectUncertain(
                    f"replacing '{shown}' installed the new bytes but backup cleanup is unverified"
                    f"{''.join(notes) or backup_note}", recovery_paths=(shown, backup_shown),
                )
            return

        temporary_absent, temporary_note = self._absent(parent, temporary, temporary_shown)
        if not temporary_absent:
            notes.append(temporary_note or f"; temporary '{temporary_shown}' remains")
        rollback_proven = False
        if installed is False and original_moved is False and temporary_absent:
            try:
                rollback_proven = self._matches(parent, name, shown, expected)
            except ComputerRefused as exc:
                notes.append(f"; rollback verification failed ({exc})")
            except OSError as exc:
                # A host error while re-reading is reported by class only: its
                # message may carry an absolute host path, and this detail is
                # model-facing. Unproven rollback is uncertain, never a leak.
                notes.append(f"; rollback verification raised {type(exc).__name__}")
            if backup_owned:
                backup_absent, backup_note = self._absent(parent, backup, backup_shown)
                rollback_proven = rollback_proven and backup_absent
                if not backup_absent:
                    notes.append(backup_note or f"; backup '{backup_shown}' remains")

        if rollback_proven:
            if isinstance(failure, KeyboardInterrupt):
                raise ComputerFileInterrupted(
                    f"replacing '{shown}' was interrupted; the original was restored",
                    effect_state="none",
                ) from failure
            if not isinstance(failure, Exception):
                raise failure
            raise ComputerRefused(f"replacing '{shown}' failed: {failure}") from None

        recovery: list[str] = [shown]
        if backup_owned:
            recovery.append(backup_shown)
        if not temporary_absent:
            recovery.append(temporary_shown)
        detail = "".join(notes)
        if isinstance(failure, KeyboardInterrupt):
            raise ComputerFileInterrupted(
                f"replacing '{shown}' was interrupted; final state requires reconciliation{detail}",
                effect_state="uncertain", recovery_paths=tuple(recovery),
            ) from failure
        if not isinstance(failure, Exception):
            failure.add_note(f"replacement state for '{shown}' requires reconciliation{detail}")
            raise failure
        raise ComputerFileEffectUncertain(
            f"replacing '{shown}' failed and final state requires reconciliation: {failure}{detail}",
            recovery_paths=tuple(recovery),
        ) from failure

    # -- tools ------------------------------------------------------------------

    def _list(self, args: dict[str, Any]) -> dict[str, Any]:
        parts = self._components(args.get("path", "."))
        shown = "/".join(parts)
        expected = self._expected(parts)
        directory = self._open_chain(parts, stop_before_last=False)
        try:
            self._admit_observation(directory, expected, shown or ".")
            try:
                found = self._backend.entries(directory)
            except _HostRefusal as exc:
                raise ComputerRefused(f"'{shown or '.'}' {exc}") from None
            allowed: list[tuple[str, str]] = []
            withheld = 0
            for name, kind in found:
                relative = f"{shown}/{name}" if shown else name
                if (name.casefold().startswith(_INTERNAL_PREFIX)
                        or kind not in {"file", "directory"} or secret_floor_rule(relative)):
                    withheld += 1
                    continue
                try:
                    self.policy.path(relative, must_exist=True)
                except (ComputerRefused, OSError):
                    withheld += 1
                    continue
                allowed.append((name, kind))
            if not self._in_place(directory, expected):
                raise ComputerRefused(
                    f"'{shown or '.'}' changed during the observation; entries were withheld"
                )
        finally:
            self._backend.close_directory(directory)
        allowed.sort(key=lambda item: (item[0].casefold(), item[0]))
        entries = [{"path": f"{shown}/{name}" if shown else name, "kind": kind}
                   for name, kind in allowed[:FILE_LIST_LIMIT]]
        # ``withheld`` counts entries the policy or secret floor kept out of the
        # listing, so a shorter listing is visible as such, never silent.
        return {"entries": entries, "limit": FILE_LIST_LIMIT,
                "truncated": len(found) > FILE_LIST_LIMIT or len(allowed) > FILE_LIST_LIMIT,
                "withheld": withheld, "postcondition_verified": True}

    def _read(self, args: dict[str, Any]) -> dict[str, Any]:
        parts, shown = self._target(args["path"], what="file")
        expected_parent = self._expected(parts[:-1])
        parent = self._open_chain(parts, stop_before_last=True)
        try:
            fd = self._file(parent, parts[-1], "read", shown)
            try:
                self._admit_observation(parent, expected_parent, "/".join(parts[:-1]) or ".")
                data = self._regular(fd, shown)
                verified = self._readback_matches(parent, parts[-1], shown, data)
                in_place = self._in_place(parent, expected_parent)
            finally:
                os.close(fd)
        finally:
            self._backend.close_directory(parent)
        if not verified or not in_place:
            raise ComputerRefused(f"'{shown}' changed during the observation; content was withheld")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ComputerRefused(f"'{shown}' is not UTF-8 text") from None
        if secret_floor_rule(shown, text):
            raise ComputerRefused(f"'{shown}' text was withheld by the secret floor")
        return {"path": shown, "text": text, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "postcondition_verified": True}

    def _write(self, args: dict[str, Any]) -> dict[str, Any]:
        if secret_floor_rule(args["path"], args["text"]):
            raise ComputerRefused("file text was refused by the secret floor")
        data = args["text"].encode("utf-8")
        if len(data) > self.policy.max_file_bytes:
            raise ComputerRefused("file content exceeds the configured size")
        expected = args.get("expected_sha256")
        parts, shown = self._target(args["path"], what="file")
        name, parent_shown, expected_parent = parts[-1], "/".join(parts[:-1]) or ".", self._expected(parts[:-1])
        digest = hashlib.sha256(data).hexdigest()
        effect_possible = False
        try:
            parent = self._open_chain(parts, stop_before_last=True)
            try:
                current = self._current(parent, name, shown)
                if current is None and expected is not None:
                    raise ComputerRefused(f"'{shown}' no longer exists; omit expected_sha256 to create it")
                if current is not None and hashlib.sha256(current).hexdigest() != expected:
                    raise ComputerRefused(f"replacing '{shown}' requires its current expected_sha256")
                self._admit_effect(parent, expected_parent, parent_shown)
                effect_possible = True
                if current is None:
                    self._create(parent, name, data, shown)
                else:
                    self._replace(parent, name, data, expected, shown)
                verified, note = self._verify(parent, name, shown, digest)
                in_place = self._in_place(parent, expected_parent)
            finally:
                self._backend.close_directory(parent)
        except ComputerFileInterrupted:
            raise
        except KeyboardInterrupt as exc:
            raise ComputerFileInterrupted(
                f"writing '{shown}' was interrupted"
                + (" before an effect" if not effect_possible else "; final state requires reconciliation"),
                effect_state="none" if not effect_possible else "uncertain",
                recovery_paths=() if not effect_possible else (shown,),
            ) from exc
        result = {"path": shown, "sha256": digest, "bytes": len(data), "postcondition_verified": verified and in_place}
        if not in_place:
            result["detail"] = f"'{parent_shown}' {self._DRIFT}"
        elif not verified:
            result["detail"] = note or "content read back through the parent handle does not match what was written"
        return result

    def _mkdir(self, args: dict[str, Any]) -> dict[str, Any]:
        parts, shown = self._target(args["path"], what="directory")
        name, parent_shown, expected_parent = parts[-1], "/".join(parts[:-1]) or ".", self._expected(parts[:-1])
        effect_possible = False
        try:
            parent = self._open_chain(parts, stop_before_last=True)
            try:
                self._admit_effect(parent, expected_parent, parent_shown)
                effect_possible = True
                created = True
                try:
                    self._backend.create_directory(parent, name)
                except _HostRefusal as exc:
                    if str(exc) != "already exists":
                        raise ComputerRefused(f"'{shown}' {exc}") from None
                    created = False
                # Opening the child by handle proves a real directory exists, not a
                # link or file. Before any effect that is a refusal; after creating
                # it is a verification result.
                verified, note = True, ""
                if created:
                    try:
                        self._backend.close_directory(self._child(parent, name, shown))
                    except ComputerRefused as exc:
                        verified, note = False, f"verification failed: {exc}"
                else:
                    self._backend.close_directory(self._child(parent, name, shown))
                in_place = self._in_place(parent, expected_parent)
            finally:
                self._backend.close_directory(parent)
        except ComputerFileInterrupted:
            raise
        except KeyboardInterrupt as exc:
            # Once admission passed, the adapter cannot prove which side of the
            # create the signal landed on: report the directory for reconciliation
            # instead of letting a bare interrupt escape untyped.
            raise ComputerFileInterrupted(
                f"creating directory '{shown}' was interrupted"
                + (" before an effect" if not effect_possible else "; final state requires reconciliation"),
                effect_state="none" if not effect_possible else "uncertain",
                recovery_paths=() if not effect_possible else (shown,),
            ) from exc
        result = {"path": shown, "created": created, "postcondition_verified": verified and in_place}
        if not in_place:
            result["detail"] = f"'{parent_shown}' {self._DRIFT}"
        elif not verified:
            result["detail"] = note
        return result

    def _move(self, args: dict[str, Any]) -> dict[str, Any]:
        expected = args["expected_sha256"]
        source_parts, source_shown = self._target(args["source"], what="file")
        destination_parts, destination_shown = self._target(args["destination"], what="file")
        # The secret floor's path channel guards both endpoints: a protected
        # name (.env, id_rsa, *.pem ...) cannot be laundered into a readable
        # one by renaming it, nor can plain content be parked under one.
        for endpoint in (source_shown, destination_shown):
            if secret_floor_rule(endpoint):
                raise ComputerRefused(f"'{endpoint}' refused by secret floor")
        effect_possible = False
        try:
            source_parent = self._open_chain(source_parts, stop_before_last=True)
            try:
                destination_parent = self._open_chain(destination_parts, stop_before_last=True)
                try:
                    fd = self._file(source_parent, source_parts[-1], "modify", source_shown)
                    try:
                        data = self._regular(fd, source_shown)
                        if hashlib.sha256(data).hexdigest() != expected:
                            raise ComputerRefused(f"'{source_shown}' does not match expected_sha256")
                        try:
                            source_text = data.decode("utf-8")
                        except UnicodeDecodeError:
                            source_text = ""
                        if secret_floor_rule(source_shown, source_text):
                            raise ComputerRefused(f"'{source_shown}' refused by secret floor")
                        if self._current(destination_parent, destination_parts[-1], destination_shown) is not None:
                            raise ComputerRefused(f"'{destination_shown}' already exists")
                        self._admit_effect(source_parent, self._expected(source_parts[:-1]),
                                           "/".join(source_parts[:-1]) or ".")
                        if not self._in_place(destination_parent, self._expected(destination_parts[:-1])):
                            raise ComputerRefused(f"'{'/'.join(destination_parts[:-1]) or '.'}' changed during the "
                                                  "operation; no effect was performed")
                        effect_possible = True
                        try:
                            self._backend.rename(source_parent, source_parts[-1], fd, destination_parent,
                                                 destination_parts[-1], replace=False)
                        except _HostRefusal as exc:
                            raise ComputerRefused(
                                f"moving '{source_shown}' to '{destination_shown}' failed: {exc}"
                            ) from None
                        except KeyboardInterrupt as exc:
                            try:
                                still_at_source = self._backend.file_at(
                                    source_parent, source_parts[-1], fd
                                )
                                now_at_destination = self._backend.file_at(
                                    destination_parent, destination_parts[-1], fd
                                )
                            except (_HostRefusal, OSError):
                                still_at_source = now_at_destination = None
                            no_effect = still_at_source is True and now_at_destination is False
                            raise ComputerFileInterrupted(
                                f"moving '{source_shown}' to '{destination_shown}' was interrupted"
                                + (" before the rename" if no_effect else "; final state requires reconciliation"),
                                effect_state="none" if no_effect else "uncertain",
                                recovery_paths=() if no_effect else (source_shown, destination_shown),
                            ) from exc
                    finally:
                        os.close(fd)
                    arrived, arrival_note = self._verify(destination_parent, destination_parts[-1], destination_shown, expected)
                    departed, departure_note = self._absent(source_parent, source_parts[-1], source_shown)
                    in_place = (self._in_place(source_parent, self._expected(source_parts[:-1]))
                                and self._in_place(destination_parent, self._expected(destination_parts[:-1])))
                finally:
                    self._backend.close_directory(destination_parent)
            finally:
                self._backend.close_directory(source_parent)
        except ComputerFileInterrupted:
            raise
        except KeyboardInterrupt as exc:
            raise ComputerFileInterrupted(
                f"moving '{source_shown}' to '{destination_shown}' was interrupted"
                + (" before an effect" if not effect_possible else "; final state requires reconciliation"),
                effect_state="none" if not effect_possible else "uncertain",
                recovery_paths=() if not effect_possible else (source_shown, destination_shown),
            ) from exc
        result = {"path": destination_shown, "sha256": expected, "bytes": len(data),
                  "postcondition_verified": arrived and departed and in_place}
        if not in_place:
            result["detail"] = f"a parent directory {self._DRIFT}"
        elif not (arrived and departed):
            result["detail"] = (arrival_note or departure_note
                                or "destination or source state read back through the parent handles is unexpected")
        return result

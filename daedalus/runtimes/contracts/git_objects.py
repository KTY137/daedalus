"""Read the bytes a Git repository committed, without ``git`` and without the working tree.

Daedalus deliberately has no ``git`` binary dependency on its verification
paths: ``daedalus.gates.repository.head_revision`` resolves an exact HEAD by
reading ``.git`` itself, because a subprocess is an effect and a spawned
program is a trust boundary the kernel would have to own. That reader stops at
the ref: it proves *which* revision HEAD names and says nothing about what any
file contained at that revision (``commit_object_verified: False``).

This module is the missing half, kept to the same rules:

* read-only. Nothing here opens a file outside ``<root>/.git``, and nothing
  here spawns a process. Both are measured in
  ``tests/runtimes/test_git_objects.py``, not asserted in prose.
* pure standard library. Loose objects are zlib streams; packfiles are parsed
  from ``.idx`` v2 plus ``.pack``, including ``OFS_DELTA`` and ``REF_DELTA``
  chains across several packs.
* verified. Every object materialized by an id -- the commit the caller named,
  every tree on the way, the blob itself, and every delta base -- is hashed and
  compared against that id. A tampered object store refuses; it does not return
  bytes. Delta bases addressed by pack offset are verified against the id the
  ``.idx`` records for that offset, so an offset is not an unchecked address.
* bounded. The caller passes ``max_bytes``; a blob above it refuses before it
  is materialized. Commits, trees and delta bases are bounded by
  ``_METADATA_BUDGET`` or the caller's bound, whichever is larger.
* honest about layouts it does not support. A ``.git`` that is a *gitdir
  pointer file* (a linked worktree) refuses with the same reasoning the HEAD
  verifier uses: the pointer is bytes a candidate could rewrite, so the reader
  never follows it. The same reasoning covers every other redirection --
  symlink, NTFS junction, mount point -- see ``_refuse_redirected_git_dir``.
  Object *alternates* refuse rather than silently reporting a reachable object
  as missing.

What this module is not: it is not a git implementation. It has no index, no
refs, no filters, no merge, no write path. In particular it returns the bytes
*in the object*, which under ``core.autocrlf`` or a ``text`` attribute are not
the bytes in the checkout. Equality therefore proves the working tree matches
the revision; inequality proves nothing on its own.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


_REVISION = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_PATH = re.compile(
    r"^(?!/)(?![A-Za-z]:/)(?!.*(?:^|/)\.\.?(?:/|$))(?!.*//)[^\\\r\n]+$"
)

#: Hard ceiling on what a caller may ask this reader to materialize.
_MAX_REQUESTED_BYTES = 64 * 1_048_576
#: Bound for objects the caller did not ask for: commits, trees, delta bases.
_METADATA_BUDGET = 64 * 1_048_576
#: A loose object's *compressed* file may exceed the object bound by this much
#: before the read refuses; zlib expansion of incompressible data is tiny.
_COMPRESSION_SLACK = 1_048_576
_MAX_INDEX_BYTES = 128 * 1_048_576
_MAX_DELTA_DEPTH = 64
_MAX_PACK_FILES = 1024
_HEADER_PROBE_BYTES = 64
_READ_CHUNK = 1 << 16

_PACK_INDEX_MAGIC = b"\xfftOc"
_OFS_DELTA = 6
_REF_DELTA = 7
_TYPE_NAMES = {1: "commit", 2: "tree", 3: "blob", 4: "tag"}

_TREE_MODE = "40000"
_BLOB_MODES = frozenset({"100644", "100755"})
_SYMLINK_MODE = "120000"
_GITLINK_MODE = "160000"
_KNOWN_MODES = frozenset(
    {_TREE_MODE, _SYMLINK_MODE, _GITLINK_MODE, *_BLOB_MODES}
)


class GitObjectError(RuntimeError):
    """Base class for every refusal of this reader."""


class GitObjectRequestError(GitObjectError):
    """The caller's root, commit id, path, or size bound is malformed."""


class GitObjectLayoutError(GitObjectError):
    """The repository layout is absent or deliberately unsupported."""


class GitObjectNotFoundError(GitObjectError):
    """The commit, object, or path is not present at the selected revision."""


class GitObjectKindError(GitObjectError):
    """The selected entry exists but is not a readable blob."""


class GitObjectSizeError(GitObjectError):
    """The object is larger than the bound the caller granted."""


class GitObjectIntegrityError(GitObjectError):
    """Stored bytes contradict their own id, header, or delta encoding."""


@dataclass(frozen=True)
class GitBlobObservation:
    """One verified blob, with the provenance of how it was reconstructed."""

    commit_id: str
    path: str
    blob_id: str
    mode: str
    size: int
    sha256: str
    data: bytes
    source: str
    pack_name: str | None
    delta_kinds: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Projection for a receipt: provenance without the bytes themselves."""

        return {
            "schema": "daedalus-git-blob-observation/1",
            "commit_id": self.commit_id,
            "path": self.path,
            "blob_id": self.blob_id,
            "mode": self.mode,
            "size": self.size,
            "sha256": self.sha256,
            "source": self.source,
            "pack_name": self.pack_name,
            "delta_kinds": list(self.delta_kinds),
            "object_id_verified": True,
            "process_spawned": False,
            "working_tree_read": False,
        }


# ---------------------------------------------------------------------------
# request admission
# ---------------------------------------------------------------------------


def _admit_commit_id(value: object) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise GitObjectRequestError(
            "commit_id must be a lowercase 40-hex Git object id"
        )
    return value


def _admit_path(value: object) -> str:
    if not isinstance(value, str) or _REPOSITORY_PATH.fullmatch(value) is None:
        raise GitObjectRequestError(
            "path must be a normalized repository-relative POSIX path"
        )
    parts = value.split("/")
    if any(not part for part in parts):
        raise GitObjectRequestError("path must not contain an empty component")
    if any("\x00" in part or ord(min(part)) < 32 for part in parts):
        raise GitObjectRequestError("path must not contain control characters")
    return value


def _admit_max_bytes(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise GitObjectRequestError("max_bytes must be a positive strict integer")
    if value > _MAX_REQUESTED_BYTES:
        raise GitObjectRequestError(
            f"max_bytes must not exceed the {_MAX_REQUESTED_BYTES}-byte reader ceiling"
        )
    return value


def _admit_repository(root: object) -> Path:
    """Resolve ``<root>/.git`` or refuse, naming the layout that was refused."""

    if not isinstance(root, Path):
        raise GitObjectRequestError("repository_root must be a pathlib.Path")
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise GitObjectLayoutError("repository root is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise GitObjectLayoutError("repository root must be a real directory")
    try:
        resolved = root.resolve(strict=True)
        final = resolved.lstat()
    except OSError as exc:
        raise GitObjectLayoutError("repository root cannot be resolved") from exc
    if (metadata.st_dev, metadata.st_ino) != (final.st_dev, final.st_ino):
        raise GitObjectLayoutError(
            "repository root identity changed during resolution"
        )

    git_dir = resolved / ".git"
    try:
        git_metadata = git_dir.lstat()
    except FileNotFoundError as exc:
        raise GitObjectLayoutError(
            "repository has no .git directory: this reader needs a canonical checkout"
        ) from exc
    except OSError as exc:
        raise GitObjectLayoutError(".git is unavailable") from exc
    if stat.S_ISLNK(git_metadata.st_mode):
        raise GitObjectLayoutError(".git must not be a symlink")
    if stat.S_ISREG(git_metadata.st_mode):
        if _is_gitdir_pointer(git_dir):
            raise GitObjectLayoutError(
                "the subject is a linked git worktree (.git is a gitdir pointer "
                "file), a deliberately unsupported subject layout: clone the "
                "repository or use its common checkout"
            )
        raise GitObjectLayoutError(".git is a file but not a gitdir pointer")
    if not stat.S_ISDIR(git_metadata.st_mode):
        raise GitObjectLayoutError(".git must be a real directory")
    _refuse_redirected_git_dir(git_dir, git_metadata)

    alternates = git_dir / "objects" / "info" / "alternates"
    try:
        alternates.lstat()
    except OSError:
        pass
    else:
        raise GitObjectLayoutError(
            "this object store declares alternates, an unsupported layout: a "
            "missing object here would not mean the object is absent"
        )
    return git_dir


def _refuse_redirected_git_dir(git_dir: Path, metadata: os.stat_result) -> None:
    """Refuse a ``.git`` that is any kind of redirection, not only a symlink.

    ``stat.S_ISLNK`` is not enough on Windows. An NTFS *directory junction*
    (``mklink /J``, no elevation required) carries the reparse tag
    ``IO_REPARSE_TAG_MOUNT_POINT``, and CPython reports it as an ordinary
    directory: ``Path.is_symlink()`` is false and ``S_ISLNK`` is unset, so the
    reader would happily serve bytes out of whatever repository the junction
    points at while reporting them as this root's committed content
    (measured 2026-09-05, Odysseus D2). Two independent checks close it: any
    non-zero reparse tag where the platform exposes one, and -- portably --
    the same identity comparison the repository root already gets, because
    ``resolve()`` follows the redirection and lands on a different inode.
    """

    if getattr(metadata, "st_reparse_tag", 0):
        raise GitObjectLayoutError(
            ".git is a reparse point (a junction or link), a deliberately "
            "unsupported subject layout: use the checkout that owns the "
            "object store"
        )
    try:
        resolved = git_dir.resolve(strict=True)
        final = resolved.lstat()
    except OSError as exc:
        raise GitObjectLayoutError(".git cannot be resolved") from exc
    if (metadata.st_dev, metadata.st_ino) != (final.st_dev, final.st_ino):
        raise GitObjectLayoutError(
            ".git resolves to a different directory (a junction, link or mount "
            "point), a deliberately unsupported subject layout: use the "
            "checkout that owns the object store"
        )


def _is_gitdir_pointer(path: Path) -> bool:
    try:
        descriptor = _open_read_only(path)
    except OSError:
        return False
    try:
        return os.read(descriptor, 7) == b"gitdir:"
    except OSError:
        return False
    finally:
        os.close(descriptor)


# ---------------------------------------------------------------------------
# bounded read-only file access
# ---------------------------------------------------------------------------


def _open_read_only(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def _read_whole(path: Path, limit: int, label: str) -> bytes:
    """Read a whole regular file under ``.git``; ``FileNotFoundError`` escapes."""

    descriptor = _open_read_only(path)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise GitObjectLayoutError(f"{label} is not a regular file: {path.name}")
        if info.st_size > limit:
            raise GitObjectSizeError(
                f"{label} is {info.st_size} bytes, above the {limit}-byte bound"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, _READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _read_at(descriptor: int, offset: int, length: int) -> bytes:
    os.lseek(descriptor, offset, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = os.read(descriptor, min(_READ_CHUNK, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# pack index (v2)
# ---------------------------------------------------------------------------


class _PackIndex:
    """A parsed ``.idx`` v2: id -> offset, and offset -> id for delta bases."""

    __slots__ = ("path", "count", "_fanout", "_names", "_small", "_large", "_by_offset")

    def __init__(
        self,
        path: Path,
        fanout: tuple[int, ...],
        names: bytes,
        small: bytes,
        large: bytes,
    ) -> None:
        self.path = path
        self.count = fanout[255]
        self._fanout = fanout
        self._names = names
        self._small = small
        self._large = large
        self._by_offset: dict[int, str] | None = None

    @classmethod
    def load(cls, path: Path) -> "_PackIndex":
        raw = _read_whole(path, _MAX_INDEX_BYTES, "pack index")
        if raw[:4] != _PACK_INDEX_MAGIC:
            raise GitObjectLayoutError(
                f"{path.name}: pack index version 1 (or an unknown format) is "
                "unsupported by this reader"
            )
        if len(raw) < 8 + 1024 + 40:
            raise GitObjectIntegrityError(f"{path.name}: pack index is truncated")
        version = struct.unpack_from(">I", raw, 4)[0]
        if version != 2:
            raise GitObjectLayoutError(
                f"{path.name}: pack index version {version} is unsupported"
            )
        fanout = struct.unpack_from(">256I", raw, 8)
        if any(
            fanout[index] < fanout[index - 1] for index in range(1, 256)
        ):
            raise GitObjectIntegrityError(
                f"{path.name}: pack index fanout is not monotonic"
            )
        count = fanout[255]
        names_start = 8 + 1024
        names_end = names_start + count * 20
        crc_end = names_end + count * 4
        small_end = crc_end + count * 4
        large_end = len(raw) - 40
        if large_end < small_end or (large_end - small_end) % 8:
            raise GitObjectIntegrityError(
                f"{path.name}: pack index tables do not fit the file"
            )
        return cls(
            path,
            fanout,
            raw[names_start:names_end],
            raw[crc_end:small_end],
            raw[small_end:large_end],
        )

    def _offset_at(self, position: int) -> int:
        encoded = struct.unpack_from(">I", self._small, position * 4)[0]
        if not encoded & 0x80000000:
            return encoded
        large = encoded & 0x7FFFFFFF
        if (large + 1) * 8 > len(self._large):
            raise GitObjectIntegrityError(
                f"{self.path.name}: large pack offset {large} is out of range"
            )
        return struct.unpack_from(">Q", self._large, large * 8)[0]

    def offset_of(self, object_id: str) -> int | None:
        raw = bytes.fromhex(object_id)
        low = self._fanout[raw[0] - 1] if raw[0] else 0
        high = self._fanout[raw[0]]
        while low < high:
            middle = (low + high) // 2
            start = middle * 20
            candidate = self._names[start : start + 20]
            if candidate == raw:
                return self._offset_at(middle)
            if candidate < raw:
                low = middle + 1
            else:
                high = middle
        return None

    def id_at_offset(self, offset: int) -> str | None:
        """The id the index records for a pack offset, so a delta base has one."""

        if self._by_offset is None:
            table: dict[int, str] = {}
            for position in range(self.count):
                table[self._offset_at(position)] = self._names[
                    position * 20 : position * 20 + 20
                ].hex()
            self._by_offset = table
        return self._by_offset.get(offset)


class _Pack:
    __slots__ = ("name", "index", "_pack_path", "_descriptor")

    def __init__(self, index_path: Path) -> None:
        self.name = index_path.stem
        self.index = _PackIndex.load(index_path)
        self._pack_path = index_path.with_suffix(".pack")
        self._descriptor: int | None = None

    def descriptor(self) -> int:
        if self._descriptor is None:
            try:
                self._descriptor = _open_read_only(self._pack_path)
            except OSError as exc:
                raise GitObjectLayoutError(
                    f"{self._pack_path.name} is missing next to its index"
                ) from exc
            header = _read_at(self._descriptor, 0, 12)
            if len(header) != 12 or header[:4] != b"PACK":
                raise GitObjectIntegrityError(
                    f"{self._pack_path.name} does not start with a pack header"
                )
            version = struct.unpack_from(">I", header, 4)[0]
            if version not in (2, 3):
                raise GitObjectLayoutError(
                    f"{self._pack_path.name}: pack version {version} is unsupported"
                )
        return self._descriptor

    def close(self) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None


@dataclass(frozen=True)
class _Loaded:
    type_name: str
    data: bytes
    source: str
    pack_name: str | None
    delta_kinds: tuple[str, ...]


# ---------------------------------------------------------------------------
# object store
# ---------------------------------------------------------------------------


class _Store:
    """Loose objects plus every pack in ``.git/objects/pack``, read-only."""

    def __init__(self, git_dir: Path) -> None:
        self._git_dir = git_dir
        self._packs: list[_Pack] | None = None

    def close(self) -> None:
        for pack in self._packs or ():
            pack.close()

    def packs(self) -> list[_Pack]:
        if self._packs is None:
            directory = self._git_dir / "objects" / "pack"
            try:
                indexes = sorted(
                    entry
                    for entry in directory.iterdir()
                    if entry.name.endswith(".idx")
                )
            except (FileNotFoundError, NotADirectoryError):
                indexes = []
            except OSError as exc:
                raise GitObjectLayoutError(
                    "the pack directory cannot be listed"
                ) from exc
            if len(indexes) > _MAX_PACK_FILES:
                raise GitObjectLayoutError(
                    f"the object store holds more than {_MAX_PACK_FILES} packs"
                )
            self._packs = [_Pack(index) for index in indexes]
        return self._packs

    def load(
        self,
        object_id: str,
        budget: int,
        depth: int = 0,
        visiting: frozenset[str] = frozenset(),
    ) -> _Loaded | None:
        """One object by id, verified against that id, or ``None`` if absent.

        ``depth`` and ``visiting`` travel with the call because a ``REF_DELTA``
        base is resolved *by id*, which re-enters here. Before this was
        threaded through, the depth restarted at zero on every reference link:
        the bound existed only on the ``OFS_DELTA`` path, a reference chain of
        any length resolved, and a cycle ended in ``RecursionError`` --
        outside the ``GitObjectError`` contract (measured 2026-09-05,
        Odysseus D1).
        """

        if object_id in visiting:
            raise GitObjectIntegrityError(
                f"delta base cycle: object {object_id} is reachable from itself"
            )
        loaded = self._load_loose(object_id, budget)
        if loaded is None:
            loaded = self._load_packed(
                object_id, budget, depth, visiting | {object_id}
            )
        if loaded is None:
            return None
        _verify_object_id(loaded.type_name, loaded.data, object_id)
        return loaded

    def _load_loose(self, object_id: str, budget: int) -> _Loaded | None:
        path = self._git_dir / "objects" / object_id[:2] / object_id[2:]
        try:
            raw = _read_whole(path, budget + _COMPRESSION_SLACK, "loose object")
        except FileNotFoundError:
            return None
        except NotADirectoryError:
            return None
        except OSError as exc:
            raise GitObjectLayoutError(
                f"loose object {object_id} cannot be read"
            ) from exc

        try:
            probe = zlib.decompressobj().decompress(raw, _HEADER_PROBE_BYTES)
        except zlib.error as exc:
            raise GitObjectIntegrityError(
                f"loose object {object_id} is not a valid zlib stream"
            ) from exc
        type_name, size, header_length = _parse_loose_header(probe, object_id)
        if size > budget:
            raise GitObjectSizeError(
                f"object {object_id} is {size} bytes, above the {budget}-byte bound"
            )
        decompressor = zlib.decompressobj()
        try:
            payload = decompressor.decompress(raw, header_length + size)
            if decompressor.decompress(decompressor.unconsumed_tail, 1):
                raise GitObjectIntegrityError(
                    f"loose object {object_id} holds more bytes than its header declares"
                )
        except zlib.error as exc:
            raise GitObjectIntegrityError(
                f"loose object {object_id} is not a valid zlib stream"
            ) from exc
        if len(payload) != header_length + size:
            raise GitObjectIntegrityError(
                f"loose object {object_id} is truncated before its declared size"
            )
        return _Loaded(type_name, payload[header_length:], "loose", None, ())

    def _load_packed(
        self,
        object_id: str,
        budget: int,
        depth: int,
        visiting: frozenset[str],
    ) -> _Loaded | None:
        for pack in self.packs():
            offset = pack.index.offset_of(object_id)
            if offset is None:
                continue
            type_name, data, kinds = self._load_from_pack(
                pack, offset, budget, depth, visiting
            )
            return _Loaded(type_name, data, "pack", pack.name, kinds)
        return None

    def _load_from_pack(
        self,
        pack: _Pack,
        offset: int,
        budget: int,
        depth: int,
        visiting: frozenset[str],
    ) -> tuple[str, bytes, tuple[str, ...]]:
        if depth > _MAX_DELTA_DEPTH:
            raise GitObjectIntegrityError(
                f"{pack.name}: delta chain deeper than {_MAX_DELTA_DEPTH} links"
            )
        head = _read_at(pack.descriptor(), offset, _HEADER_PROBE_BYTES)
        type_code, stored_size, position = _parse_pack_header(head, pack.name, offset)
        base_budget = max(budget, _METADATA_BUDGET)

        if type_code in _TYPE_NAMES:
            if stored_size > budget:
                raise GitObjectSizeError(
                    f"object at {pack.name}+{offset} is {stored_size} bytes, "
                    f"above the {budget}-byte bound"
                )
            data = _inflate_at(pack, offset + position, stored_size, budget)
            return _TYPE_NAMES[type_code], data, ()

        if type_code == _OFS_DELTA:
            distance, position = _parse_offset_delta(head, position, pack.name, offset)
            base_offset = offset - distance
            if distance <= 0 or base_offset < 12:
                raise GitObjectIntegrityError(
                    f"{pack.name}: delta base offset {base_offset} is out of range"
                )
            base_id = pack.index.id_at_offset(base_offset)
            if base_id is None:
                raise GitObjectIntegrityError(
                    f"{pack.name}: delta base offset {base_offset} is not an "
                    "object this index knows"
                )
            marker = f"{pack.name}@{base_offset}"
            if marker in visiting:
                raise GitObjectIntegrityError(
                    f"delta base cycle: object {base_id} is reachable from itself"
                )
            base_type, base_data, base_kinds = self._load_from_pack(
                pack, base_offset, base_budget, depth + 1, visiting | {marker}
            )
            _verify_object_id(base_type, base_data, base_id)
            kind = "ofs_delta"
        elif type_code == _REF_DELTA:
            if len(head) < position + 20:
                raise GitObjectIntegrityError(
                    f"{pack.name}: reference delta header is truncated"
                )
            base_id = head[position : position + 20].hex()
            position += 20
            base = self.load(base_id, base_budget, depth + 1, visiting)
            if base is None:
                raise GitObjectNotFoundError(
                    f"{pack.name}: delta base {base_id} is not in this object store"
                )
            base_type, base_data, base_kinds = base.type_name, base.data, base.delta_kinds
            kind = "ref_delta"
        else:
            raise GitObjectIntegrityError(
                f"{pack.name}: unsupported pack object type {type_code}"
            )

        delta = _inflate_at(pack, offset + position, stored_size, base_budget)
        data = _apply_delta(base_data, delta, budget, pack.name, offset)
        return base_type, data, (kind, *base_kinds)


def _verify_object_id(type_name: str, data: bytes, object_id: str) -> None:
    digest = hashlib.sha1()
    digest.update(f"{type_name} {len(data)}\0".encode("ascii"))
    digest.update(data)
    if digest.hexdigest() != object_id:
        raise GitObjectIntegrityError(
            f"object {object_id} does not match the SHA-1 of the bytes stored for it"
        )


def _parse_loose_header(probe: bytes, object_id: str) -> tuple[str, int, int]:
    terminator = probe.find(b"\x00")
    if terminator < 0:
        raise GitObjectIntegrityError(
            f"loose object {object_id} has no object header"
        )
    try:
        kind, _, size = probe[:terminator].decode("ascii").partition(" ")
    except UnicodeDecodeError as exc:
        raise GitObjectIntegrityError(
            f"loose object {object_id} has a non-ASCII header"
        ) from exc
    if kind not in set(_TYPE_NAMES.values()) or not size.isdigit():
        raise GitObjectIntegrityError(
            f"loose object {object_id} has a malformed header"
        )
    return kind, int(size), terminator + 1


def _parse_pack_header(
    head: bytes, pack_name: str, offset: int
) -> tuple[int, int, int]:
    if not head:
        raise GitObjectIntegrityError(
            f"{pack_name}: no object header at offset {offset}"
        )
    byte = head[0]
    type_code = (byte >> 4) & 7
    size = byte & 0x0F
    shift = 4
    position = 1
    while byte & 0x80:
        if position >= len(head):
            raise GitObjectIntegrityError(
                f"{pack_name}: object header at {offset} is truncated"
            )
        byte = head[position]
        position += 1
        size |= (byte & 0x7F) << shift
        shift += 7
        if shift > 63:
            raise GitObjectIntegrityError(
                f"{pack_name}: object size at {offset} is not representable"
            )
    return type_code, size, position


def _parse_offset_delta(
    head: bytes, position: int, pack_name: str, offset: int
) -> tuple[int, int]:
    if position >= len(head):
        raise GitObjectIntegrityError(
            f"{pack_name}: offset delta header at {offset} is truncated"
        )
    byte = head[position]
    position += 1
    distance = byte & 0x7F
    while byte & 0x80:
        if position >= len(head):
            raise GitObjectIntegrityError(
                f"{pack_name}: offset delta header at {offset} is truncated"
            )
        byte = head[position]
        position += 1
        distance = ((distance + 1) << 7) | (byte & 0x7F)
        if distance > offset:
            raise GitObjectIntegrityError(
                f"{pack_name}: delta base distance at {offset} runs off the pack"
            )
    return distance, position


def _inflate_at(pack: _Pack, start: int, expected: int, budget: int) -> bytes:
    if expected > budget:
        raise GitObjectSizeError(
            f"{pack.name}: object at {start} is {expected} bytes, above the "
            f"{budget}-byte bound"
        )
    descriptor = pack.descriptor()
    decompressor = zlib.decompressobj()
    chunks: list[bytes] = []
    produced = 0
    position = start
    while True:
        chunk = _read_at(descriptor, position, _READ_CHUNK)
        if not chunk:
            raise GitObjectIntegrityError(
                f"{pack.name}: the stream at {start} ends before the object does"
            )
        position += len(chunk)
        try:
            piece = decompressor.decompress(chunk, expected - produced + 1)
        except zlib.error as exc:
            raise GitObjectIntegrityError(
                f"{pack.name}: the stream at {start} is not valid zlib"
            ) from exc
        produced += len(piece)
        if produced > expected:
            raise GitObjectIntegrityError(
                f"{pack.name}: the object at {start} is longer than its header declares"
            )
        chunks.append(piece)
        if decompressor.eof:
            break
        if decompressor.unconsumed_tail:
            raise GitObjectIntegrityError(
                f"{pack.name}: the object at {start} is longer than its header declares"
            )
    if produced != expected:
        raise GitObjectIntegrityError(
            f"{pack.name}: the object at {start} is shorter than its header declares"
        )
    return b"".join(chunks)


def _delta_size(delta: bytes, position: int, pack_name: str) -> tuple[int, int]:
    size = 0
    shift = 0
    while True:
        if position >= len(delta):
            raise GitObjectIntegrityError(f"{pack_name}: delta header is truncated")
        byte = delta[position]
        position += 1
        size |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return size, position
        if shift > 63:
            raise GitObjectIntegrityError(
                f"{pack_name}: delta size is not representable"
            )


def _apply_delta(
    base: bytes, delta: bytes, budget: int, pack_name: str, offset: int
) -> bytes:
    base_size, position = _delta_size(delta, 0, pack_name)
    result_size, position = _delta_size(delta, position, pack_name)
    if base_size != len(base):
        raise GitObjectIntegrityError(
            f"{pack_name}: delta at {offset} expects a {base_size}-byte base, "
            f"the base is {len(base)} bytes"
        )
    if result_size > budget:
        raise GitObjectSizeError(
            f"object at {pack_name}+{offset} is {result_size} bytes, above the "
            f"{budget}-byte bound"
        )
    chunks: list[bytes] = []
    produced = 0
    while position < len(delta):
        opcode = delta[position]
        position += 1
        if opcode & 0x80:
            copy_offset = 0
            copy_size = 0
            for index, mask in enumerate((0x01, 0x02, 0x04, 0x08)):
                if opcode & mask:
                    if position >= len(delta):
                        raise GitObjectIntegrityError(
                            f"{pack_name}: copy instruction at {offset} is truncated"
                        )
                    copy_offset |= delta[position] << (index * 8)
                    position += 1
            for index, mask in enumerate((0x10, 0x20, 0x40)):
                if opcode & mask:
                    if position >= len(delta):
                        raise GitObjectIntegrityError(
                            f"{pack_name}: copy instruction at {offset} is truncated"
                        )
                    copy_size |= delta[position] << (index * 8)
                    position += 1
            if copy_size == 0:
                copy_size = 0x10000
            if copy_offset + copy_size > len(base):
                raise GitObjectIntegrityError(
                    f"{pack_name}: delta at {offset} copies outside its base"
                )
            chunks.append(base[copy_offset : copy_offset + copy_size])
            produced += copy_size
        elif opcode:
            chunk = delta[position : position + opcode]
            position += opcode
            if len(chunk) != opcode:
                raise GitObjectIntegrityError(
                    f"{pack_name}: insert instruction at {offset} is truncated"
                )
            chunks.append(chunk)
            produced += opcode
        else:
            raise GitObjectIntegrityError(
                f"{pack_name}: delta at {offset} uses the reserved opcode 0"
            )
        if produced > result_size:
            raise GitObjectIntegrityError(
                f"{pack_name}: delta at {offset} produces more than it declares"
            )
    if produced != result_size:
        raise GitObjectIntegrityError(
            f"{pack_name}: delta at {offset} produces less than it declares"
        )
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# commit -> tree -> blob
# ---------------------------------------------------------------------------


def _commit_tree(data: bytes, commit_id: str) -> str:
    if not data.startswith(b"tree "):
        raise GitObjectIntegrityError(
            f"commit {commit_id} does not start with its tree reference"
        )
    candidate = data[5:45].decode("ascii", errors="replace")
    if _REVISION.fullmatch(candidate) is None or data[45:46] != b"\n":
        raise GitObjectIntegrityError(
            f"commit {commit_id} has a malformed tree reference"
        )
    return candidate


def _tree_entry(data: bytes, name: bytes, tree_id: str) -> tuple[str, str] | None:
    position = 0
    while position < len(data):
        space = data.find(b" ", position)
        if space < 0:
            raise GitObjectIntegrityError(f"tree {tree_id} has a malformed entry")
        mode = data[position:space].decode("ascii", errors="replace")
        terminator = data.find(b"\x00", space + 1)
        if terminator < 0 or terminator + 21 > len(data):
            raise GitObjectIntegrityError(f"tree {tree_id} has a truncated entry")
        entry_name = data[space + 1 : terminator]
        object_id = data[terminator + 1 : terminator + 21].hex()
        position = terminator + 21
        if entry_name != name:
            continue
        if mode not in _KNOWN_MODES:
            raise GitObjectIntegrityError(
                f"tree {tree_id} declares the unsupported mode {mode}"
            )
        return mode, object_id
    return None


def _resolve_entry(
    store: _Store, commit_id: str, path: str, budget: int
) -> tuple[str, str]:
    commit = store.load(commit_id, budget)
    if commit is None:
        raise GitObjectNotFoundError(
            f"commit {commit_id} is not present in this object store"
        )
    if commit.type_name != "commit":
        raise GitObjectKindError(
            f"{commit_id} is a {commit.type_name}, not a commit"
        )
    tree_id = _commit_tree(commit.data, commit_id)

    parts = path.split("/")
    walked: list[str] = []
    for part in parts[:-1]:
        mode, object_id = _require_entry(store, tree_id, part, walked, commit_id, budget)
        if mode == _TREE_MODE:
            tree_id = object_id
            continue
        prefix = "/".join(walked)
        if mode == _GITLINK_MODE:
            raise GitObjectKindError(
                f"{prefix} is a submodule (gitlink) at {commit_id}, not a directory "
                "this reader may enter"
            )
        raise GitObjectKindError(
            f"{prefix} is not a directory at {commit_id}"
        )

    mode, object_id = _require_entry(
        store, tree_id, parts[-1], walked, commit_id, budget
    )
    if mode in _BLOB_MODES:
        return mode, object_id
    if mode == _SYMLINK_MODE:
        raise GitObjectKindError(
            f"{path} is a symlink at {commit_id}, not a blob this reader returns"
        )
    if mode == _GITLINK_MODE:
        raise GitObjectKindError(
            f"{path} is a submodule (gitlink) at {commit_id}, not a blob"
        )
    raise GitObjectKindError(f"{path} is a directory (tree) at {commit_id}, not a blob")


def _require_entry(
    store: _Store,
    tree_id: str,
    name: str,
    walked: list[str],
    commit_id: str,
    budget: int,
) -> tuple[str, str]:
    tree = store.load(tree_id, budget)
    if tree is None:
        raise GitObjectNotFoundError(
            f"tree {tree_id} is not present in this object store"
        )
    if tree.type_name != "tree":
        raise GitObjectIntegrityError(f"{tree_id} is a {tree.type_name}, not a tree")
    entry = _tree_entry(tree.data, name.encode("utf-8"), tree_id)
    walked.append(name)
    if entry is None:
        raise GitObjectNotFoundError(
            f"{'/'.join(walked)} is not present at {commit_id}"
        )
    return entry


# ---------------------------------------------------------------------------
# public reader
# ---------------------------------------------------------------------------


def read_blob_at(
    repository_root: Path,
    commit_id: str,
    path: str,
    max_bytes: int,
) -> GitBlobObservation:
    """The blob committed at ``commit_id`` for ``path``, with its provenance.

    Reads only ``<repository_root>/.git``. Never spawns a process, never
    consults the index, never touches the working tree.
    """

    commit = _admit_commit_id(commit_id)
    relative = _admit_path(path)
    budget = _admit_max_bytes(max_bytes)
    git_dir = _admit_repository(repository_root)

    store = _Store(git_dir)
    try:
        internal = max(budget, _METADATA_BUDGET)
        mode, blob_id = _resolve_entry(store, commit, relative, internal)
        blob = store.load(blob_id, budget)
        if blob is None:
            raise GitObjectNotFoundError(
                f"blob {blob_id} for {relative} is not present in this object store"
            )
        if blob.type_name != "blob":
            raise GitObjectIntegrityError(
                f"{relative} at {commit} resolves to a {blob.type_name}, not a blob"
            )
        return GitBlobObservation(
            commit_id=commit,
            path=relative,
            blob_id=blob_id,
            mode=mode,
            size=len(blob.data),
            sha256=hashlib.sha256(blob.data).hexdigest(),
            data=blob.data,
            source=blob.source,
            pack_name=blob.pack_name,
            delta_kinds=blob.delta_kinds,
        )
    finally:
        store.close()


def blob_at(
    repository_root: Path,
    commit_id: str,
    path: str,
    max_bytes: int,
) -> bytes:
    """The exact bytes ``path`` had at ``commit_id``, or a typed refusal."""

    return read_blob_at(repository_root, commit_id, path, max_bytes).data


def blob_sha256_at(
    repository_root: Path,
    commit_id: str,
    path: str,
    max_bytes: int,
) -> str:
    """The SHA-256 of those bytes: what a content binding can compare against."""

    return read_blob_at(repository_root, commit_id, path, max_bytes).sha256


__all__ = [
    "GitBlobObservation",
    "GitObjectError",
    "GitObjectIntegrityError",
    "GitObjectKindError",
    "GitObjectLayoutError",
    "GitObjectNotFoundError",
    "GitObjectRequestError",
    "GitObjectSizeError",
    "blob_at",
    "blob_sha256_at",
    "read_blob_at",
]

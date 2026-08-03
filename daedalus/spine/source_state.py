"""Read-only, exact fingerprints for a Git working tree.

The committed tree is identified by Git's object IDs.  The current tracked
working tree is identified separately by hashing the index records plus every
tracked path's observable state.  Non-ignored untracked regular files retain
individual content digests.  This distinction lets callers tell a clean HEAD
checkout from an exact (but deliberately dirty) source observation.

This is a dormant leaf with no CLI or production wiring.  Starting Git is a
``process_spawn`` effect and a production caller must obtain authority from the
canonical process-effect boundary before entering this leaf.  Once authorized,
the argv here are source-read-only, use ``GIT_OPTIONAL_LOCKS=0``, and open files
read-only.  A capture that races a repository change, encounters an unreadable
path, or sees an untracked symlink/non-regular file is returned as
``exact == False`` and can be refused with
:meth:`SourceFingerprint.require_exact`. Here ``exact`` means no anomaly was
detected during the bounded double observation; it is not an OS filesystem
snapshot and cannot prevent a writer from changing bytes after capture. Gate
evidence must materialize and content-address a frozen tree rather than treat
this preflight fingerprint as atomic storage.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


SCHEMA = "daedalus.source-fingerprint/v1"
_GIT_TIMEOUT_S = 120
_READ_SIZE = 1024 * 1024
_OID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


class SourceStateError(RuntimeError):
    """The requested Git source state could not be observed."""


class InexactSourceState(SourceStateError):
    """Raised when a caller requires an exact observation but did not get one."""

    def __init__(self, fingerprint: "SourceFingerprint") -> None:
        codes = ", ".join(issue.code for issue in fingerprint.issues)
        super().__init__(f"source fingerprint is not exact: {codes or 'unknown'}")
        self.fingerprint = fingerprint


@dataclass(frozen=True)
class SourceIssue:
    """A deterministic reason why a fingerprint cannot claim exactness."""

    code: str
    scope: str
    path_bytes: bytes | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "scope": self.scope,
            "path_b64": _b64(self.path_bytes) if self.path_bytes is not None else None,
            "path_display": (
                _display_path(self.path_bytes)
                if self.path_bytes is not None
                else None
            ),
        }


@dataclass(frozen=True)
class UntrackedFile:
    """Evidence for one non-ignored path reported by ``git ls-files``."""

    path_bytes: bytes
    kind: str
    sha256: str | None
    size: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path_b64": _b64(self.path_bytes),
            "path_display": _display_path(self.path_bytes),
            "kind": self.kind,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class Gitlink:
    """One mode-160000 index entry and its optional checked-out repository."""

    path_bytes: bytes
    index_oid: str
    state: str
    checkout: "SourceFingerprint | None"

    @property
    def initialized(self) -> bool:
        return self.checkout is not None

    @property
    def matches_index(self) -> bool | None:
        if self.checkout is None:
            return None
        return self.checkout.head == self.index_oid

    def to_dict(self) -> dict[str, object]:
        return {
            "path_b64": _b64(self.path_bytes),
            "path_display": _display_path(self.path_bytes),
            "index_oid": self.index_oid,
            "state": self.state,
            "initialized": self.initialized,
            "matches_index": self.matches_index,
            "checkout": self.checkout.to_dict() if self.checkout is not None else None,
        }


@dataclass(frozen=True)
class SourceFingerprint:
    """A deterministic observation of one Git checkout.

    ``clean`` is Git's porcelain-v1 definition: there are no tracked, staged,
    or non-ignored untracked changes.  ``exact`` is stronger in a different
    direction: every path needed for the current source identity was read
    stably and the Git observations before and after the read agreed.  A dirty
    checkout can therefore be exact, while an unreadable clean-looking one
    cannot.  ``exact`` describes this observation, not a continuing lock or a
    revision-atomic filesystem snapshot.
    """

    head: str
    tree_sha: str
    status_porcelain_v1_z: bytes
    status_sha256: str
    tracked_index_sha256: str
    tracked_tree_sha256: str
    tracked_path_count: int
    gitlinks: tuple[Gitlink, ...]
    untracked_files: tuple[UntrackedFile, ...]
    untracked_tree_sha256: str
    issues: tuple[SourceIssue, ...]

    @property
    def clean(self) -> bool:
        return self.status_porcelain_v1_z == b""

    @property
    def exact(self) -> bool:
        return not self.issues

    @property
    def exact_clean_head(self) -> bool:
        """Whether this is an exact source observation with empty Git status."""

        return self.clean and self.exact

    @property
    def fingerprint_sha256(self) -> str:
        digest = hashlib.sha256()
        _frame(digest, SCHEMA.encode("ascii"))
        _frame(digest, self.head.encode("ascii"))
        _frame(digest, self.tree_sha.encode("ascii"))
        _frame(digest, self.status_porcelain_v1_z)
        _frame(digest, self.tracked_index_sha256.encode("ascii"))
        _frame(digest, self.tracked_tree_sha256.encode("ascii"))
        _frame(digest, str(self.tracked_path_count).encode("ascii"))
        for gitlink in self.gitlinks:
            _frame(digest, gitlink.path_bytes)
            _frame(digest, gitlink.index_oid.encode("ascii"))
            _frame(digest, gitlink.state.encode("ascii"))
            _frame(
                digest,
                (
                    gitlink.checkout.fingerprint_sha256.encode("ascii")
                    if gitlink.checkout is not None
                    else b""
                ),
            )
        _frame(digest, self.untracked_tree_sha256.encode("ascii"))
        for item in self.untracked_files:
            _frame(digest, item.path_bytes)
            _frame(digest, item.kind.encode("ascii"))
            _frame(digest, (item.sha256 or "").encode("ascii"))
            _frame(digest, b"" if item.size is None else str(item.size).encode("ascii"))
        for issue in self.issues:
            _frame(digest, issue.code.encode("ascii"))
            _frame(digest, issue.scope.encode("ascii"))
            _frame(digest, issue.path_bytes or b"")
        return digest.hexdigest()

    def require_exact(self) -> "SourceFingerprint":
        if not self.exact:
            raise InexactSourceState(self)
        return self

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible receipt projection without losing raw paths."""

        return {
            "schema": SCHEMA,
            "head": self.head,
            "tree_sha": self.tree_sha,
            "clean": self.clean,
            "exact": self.exact,
            "exact_clean_head": self.exact_clean_head,
            "fingerprint_sha256": self.fingerprint_sha256,
            "status": {
                "format": "porcelain-v1-z",
                "bytes_b64": _b64(self.status_porcelain_v1_z),
                "byte_length": len(self.status_porcelain_v1_z),
                "sha256": self.status_sha256,
            },
            "tracked_tree": {
                "index_sha256": self.tracked_index_sha256,
                "identity_sha256": self.tracked_tree_sha256,
                "path_count": self.tracked_path_count,
                "gitlinks": [gitlink.to_dict() for gitlink in self.gitlinks],
            },
            "untracked_tree": {
                "identity_sha256": self.untracked_tree_sha256,
                "files": [item.to_dict() for item in self.untracked_files],
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _GitObservation:
    head: str
    tree_sha: str
    index_bytes: bytes
    tracked_paths: tuple[bytes, ...]
    status_bytes: bytes
    untracked_paths: tuple[bytes, ...]


@dataclass(frozen=True)
class _IndexEntry:
    mode: str
    oid: str
    stage: int
    path_bytes: bytes


@dataclass(frozen=True)
class _FileDigest:
    sha256: str
    size: int
    mode: int


class _ChangedDuringRead(OSError):
    pass


class _NonRegularDuringRead(OSError):
    pass


def fingerprint_source(repo_root: str | os.PathLike[str]) -> SourceFingerprint:
    """Read source state after the caller authorizes Git process creation.

    This function deliberately does not mint process authority.  It has no
    source-write operation and disables Git's optional index refresh locks.
    """

    return _fingerprint_source(Path(repo_root), ())


def _fingerprint_source(
    repo_root: Path,
    ancestry: tuple[Path, ...],
) -> SourceFingerprint:
    root = _top_level(Path(repo_root))
    if root in ancestry:
        raise SourceStateError("cyclic Gitlink checkout encountered")
    before = _observe_git(root)
    issues: list[SourceIssue] = []

    tracked_sha, tracked_count, gitlinks, tracked_issues = _tracked_identity(
        root, before.index_bytes, before.tracked_paths, (*ancestry, root)
    )
    issues.extend(tracked_issues)

    untracked, untracked_sha, untracked_issues = _untracked_identity(
        root, before.untracked_paths
    )
    issues.extend(untracked_issues)

    after = _observe_git(root)
    if before != after:
        issues.append(SourceIssue("repository_changed_during_capture", "repository"))

    ordered_issues = tuple(sorted(
        issues,
        key=lambda issue: (issue.scope, issue.path_bytes or b"", issue.code),
    ))
    return SourceFingerprint(
        head=before.head,
        tree_sha=before.tree_sha,
        status_porcelain_v1_z=before.status_bytes,
        status_sha256=_sha256(before.status_bytes),
        tracked_index_sha256=_sha256(before.index_bytes),
        tracked_tree_sha256=tracked_sha,
        tracked_path_count=tracked_count,
        gitlinks=gitlinks,
        untracked_files=untracked,
        untracked_tree_sha256=untracked_sha,
        issues=ordered_issues,
    )


def _top_level(candidate: Path) -> Path:
    try:
        candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise SourceStateError(f"repository path is unavailable: {candidate}") from exc
    raw = _git(candidate, ["rev-parse", "--show-toplevel"])
    try:
        top = Path(os.fsdecode(raw.rstrip(b"\r\n"))).resolve(strict=True)
    except (OSError, UnicodeError) as exc:
        raise SourceStateError("Git returned an unusable repository root") from exc
    return top


def _observe_git(root: Path) -> _GitObservation:
    head = _oid(_git(root, ["rev-parse", "--verify", "HEAD"]), "HEAD")
    tree_sha = _oid(
        _git(root, ["rev-parse", "--verify", "HEAD^{tree}"]), "HEAD tree"
    )
    index_bytes = _git(root, ["ls-files", "--stage", "--full-name", "-z"])
    tracked = _nul_paths(
        _git(root, ["ls-files", "--cached", "--full-name", "-z"])
    )
    status = _status_porcelain_v1_z(root)
    untracked = _nul_paths(
        _git(
            root,
            ["ls-files", "--others", "--exclude-standard", "--full-name", "-z"],
        )
    )
    return _GitObservation(
        head=head,
        tree_sha=tree_sha,
        index_bytes=index_bytes,
        tracked_paths=tracked,
        status_bytes=status,
        untracked_paths=untracked,
    )


def _status_porcelain_v1_z(root: Path) -> bytes:
    return _git(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
            "--no-renames",
        ],
    )


def _git(root: Path, args: Sequence[str]) -> bytes:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    argv = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        *args,
    ]
    try:
        proc = subprocess.run(
            argv,
            cwd=os.fspath(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceStateError(f"Git observation failed for {args[0]!r}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise SourceStateError(
            f"Git observation failed for {args[0]!r} ({proc.returncode}): {stderr}"
        )
    return proc.stdout


def _tracked_identity(
    root: Path,
    index_bytes: bytes,
    paths: tuple[bytes, ...],
    ancestry: tuple[Path, ...],
) -> tuple[str, int, tuple[Gitlink, ...], list[SourceIssue]]:
    digest = hashlib.sha256()
    _frame(digest, b"daedalus.tracked-tree/v1")
    _frame(digest, index_bytes)
    issues: list[SourceIssue] = []
    gitlinks: list[Gitlink] = []
    stage_zero = {
        entry.path_bytes: entry
        for entry in _index_entries(index_bytes)
        if entry.stage == 0
    }
    unique_paths = tuple(sorted(set(paths)))
    for raw_path in unique_paths:
        _frame(digest, raw_path)
        path = _checked_path(root, raw_path)
        if path is None:
            _frame(digest, b"invalid")
            issues.append(SourceIssue("invalid_git_path", "tracked", raw_path))
            continue

        entry = stage_zero.get(raw_path)
        if entry is not None and entry.mode == "160000":
            _frame(digest, b"gitlink")
            gitlink, issue = _gitlink_evidence(
                path, raw_path, entry.oid, ancestry
            )
            gitlinks.append(gitlink)
            _frame(digest, entry.oid.encode("ascii"))
            _frame(digest, gitlink.state.encode("ascii"))
            _frame(
                digest,
                (
                    gitlink.checkout.fingerprint_sha256.encode("ascii")
                    if gitlink.checkout is not None
                    else b""
                ),
            )
            if issue is not None:
                issues.append(issue)
            continue
        try:
            before = path.lstat()
        except FileNotFoundError:
            _frame(digest, b"missing")
            continue
        except OSError:
            _frame(digest, b"unreadable")
            issues.append(SourceIssue("tracked_unreadable", "tracked", raw_path))
            continue

        if stat.S_ISREG(before.st_mode) and not _is_reparse(before):
            _frame(digest, b"regular")
            try:
                evidence = _digest_regular_file(path, before)
            except _ChangedDuringRead:
                _frame(digest, b"changed-during-read")
                issues.append(SourceIssue(
                    "tracked_changed_during_read", "tracked", raw_path
                ))
            except (_NonRegularDuringRead, OSError):
                _frame(digest, b"unreadable")
                issues.append(SourceIssue("tracked_unreadable", "tracked", raw_path))
            else:
                _frame(digest, evidence.sha256.encode("ascii"))
                _frame(digest, str(evidence.size).encode("ascii"))
                _frame(digest, oct(evidence.mode).encode("ascii"))
            continue

        if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
            _frame(digest, b"symlink")
            try:
                target = os.fsencode(os.readlink(path))
                after = path.lstat()
            except OSError:
                _frame(digest, b"unreadable")
                issues.append(SourceIssue("tracked_unreadable", "tracked", raw_path))
            else:
                if _stat_signature(before) != _stat_signature(after):
                    _frame(digest, b"changed-during-read")
                    issues.append(SourceIssue(
                        "tracked_changed_during_read", "tracked", raw_path
                    ))
                else:
                    _frame(digest, target)
            continue

        _frame(digest, b"non-regular")
        issues.append(SourceIssue("tracked_non_regular", "tracked", raw_path))
    return digest.hexdigest(), len(unique_paths), tuple(gitlinks), issues


def _gitlink_evidence(
    path: Path,
    raw_path: bytes,
    index_oid: str,
    ancestry: tuple[Path, ...],
) -> tuple[Gitlink, SourceIssue | None]:
    try:
        path_state = path.lstat()
    except FileNotFoundError:
        return Gitlink(raw_path, index_oid, "absent", None), None
    except OSError:
        return (
            Gitlink(raw_path, index_oid, "unreadable", None),
            SourceIssue("gitlink_unreadable", "tracked", raw_path),
        )

    if not stat.S_ISDIR(path_state.st_mode) or _is_reparse(path_state):
        return (
            Gitlink(raw_path, index_oid, "not-directory", None),
            SourceIssue("gitlink_not_checkout", "tracked", raw_path),
        )

    marker = path / ".git"
    try:
        marker.lstat()
    except FileNotFoundError:
        try:
            with os.scandir(path) as entries:
                populated = next(entries, None) is not None
        except OSError:
            return (
                Gitlink(raw_path, index_oid, "unreadable", None),
                SourceIssue("gitlink_unreadable", "tracked", raw_path),
            )
        if populated:
            return (
                Gitlink(raw_path, index_oid, "not-checkout", None),
                SourceIssue("gitlink_not_checkout", "tracked", raw_path),
            )
        return Gitlink(raw_path, index_oid, "uninitialized", None), None
    except OSError:
        return (
            Gitlink(raw_path, index_oid, "unreadable", None),
            SourceIssue("gitlink_unreadable", "tracked", raw_path),
        )

    try:
        checkout = _fingerprint_source(path, ancestry)
    except SourceStateError:
        return (
            Gitlink(raw_path, index_oid, "invalid-checkout", None),
            SourceIssue("gitlink_not_checkout", "tracked", raw_path),
        )
    gitlink = Gitlink(raw_path, index_oid, "checked-out", checkout)
    if not checkout.exact:
        return gitlink, SourceIssue("gitlink_inexact", "tracked", raw_path)
    return gitlink, None


def _index_entries(raw: bytes) -> tuple[_IndexEntry, ...]:
    records = _nul_paths(raw)
    entries: list[_IndexEntry] = []
    for record in records:
        try:
            header, path = record.split(b"\t", 1)
            mode_raw, oid_raw, stage_raw = header.split(b" ")
            mode = mode_raw.decode("ascii")
            oid = _oid(oid_raw, "index object ID")
            stage = int(stage_raw.decode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise SourceStateError("Git returned an invalid staged index record") from exc
        if not re.fullmatch(r"[0-7]{6}", mode) or stage not in (0, 1, 2, 3):
            raise SourceStateError("Git returned an invalid staged index record")
        entries.append(_IndexEntry(mode, oid, stage, path))
    return tuple(entries)


def _untracked_identity(
    root: Path,
    paths: tuple[bytes, ...],
) -> tuple[tuple[UntrackedFile, ...], str, list[SourceIssue]]:
    records: list[UntrackedFile] = []
    issues: list[SourceIssue] = []
    for raw_path in sorted(set(paths)):
        path = _checked_path(root, raw_path)
        if path is None:
            records.append(UntrackedFile(raw_path, "invalid", None, None))
            issues.append(SourceIssue("invalid_git_path", "untracked", raw_path))
            continue
        try:
            before = path.lstat()
        except OSError:
            records.append(UntrackedFile(raw_path, "missing", None, None))
            issues.append(SourceIssue("untracked_unreadable", "untracked", raw_path))
            continue

        if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
            records.append(UntrackedFile(raw_path, "symlink", None, None))
            issues.append(SourceIssue("untracked_symlink", "untracked", raw_path))
            continue
        if not stat.S_ISREG(before.st_mode):
            records.append(UntrackedFile(raw_path, "non-regular", None, None))
            issues.append(SourceIssue("untracked_non_regular", "untracked", raw_path))
            continue
        try:
            evidence = _digest_regular_file(path, before)
        except _ChangedDuringRead:
            records.append(UntrackedFile(raw_path, "regular", None, None))
            issues.append(SourceIssue(
                "untracked_changed_during_read", "untracked", raw_path
            ))
        except (_NonRegularDuringRead, OSError):
            records.append(UntrackedFile(raw_path, "regular", None, None))
            issues.append(SourceIssue("untracked_unreadable", "untracked", raw_path))
        else:
            records.append(UntrackedFile(
                raw_path, "regular", evidence.sha256, evidence.size
            ))

    ordered = tuple(records)
    digest = hashlib.sha256()
    _frame(digest, b"daedalus.untracked-tree/v1")
    for item in ordered:
        _frame(digest, item.path_bytes)
        _frame(digest, item.kind.encode("ascii"))
        _frame(digest, (item.sha256 or "").encode("ascii"))
        _frame(digest, b"" if item.size is None else str(item.size).encode("ascii"))
    return ordered, digest.hexdigest(), issues


def _digest_regular_file(path: Path, expected: os.stat_result) -> _FileDigest:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or _is_reparse(opened):
            raise _NonRegularDuringRead(os.fspath(path))
        if _stat_signature(expected) != _stat_signature(opened):
            raise _ChangedDuringRead(os.fspath(path))
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(fd, _READ_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(fd)
    try:
        after = path.lstat()
    except OSError as exc:
        raise _ChangedDuringRead(os.fspath(path)) from exc
    if (
        _stat_signature(expected) != _stat_signature(after)
        or size != opened.st_size
    ):
        raise _ChangedDuringRead(os.fspath(path))
    return _FileDigest(
        sha256=digest.hexdigest(),
        size=size,
        mode=stat.S_IMODE(opened.st_mode),
    )


def _checked_path(root: Path, raw_path: bytes) -> Path | None:
    if not raw_path or b"\0" in raw_path or raw_path.startswith((b"/", b"\\")):
        return None
    parts = raw_path.split(b"/")
    if any(part in (b"", b".", b"..") for part in parts):
        return None
    if os.name == "nt" and len(parts[0]) >= 2 and parts[0][1:2] == b":":
        return None
    return root.joinpath(*(os.fsdecode(part) for part in parts))


def _nul_paths(raw: bytes) -> tuple[bytes, ...]:
    if raw and not raw.endswith(b"\0"):
        raise SourceStateError("Git returned a truncated NUL-delimited path list")
    return tuple(sorted(path for path in raw.split(b"\0") if path))


def _oid(raw: bytes, label: str) -> str:
    try:
        value = raw.strip().decode("ascii").lower()
    except UnicodeError as exc:
        raise SourceStateError(f"Git returned a non-ASCII {label}") from exc
    if not _OID_RE.fullmatch(value):
        raise SourceStateError(f"Git returned an invalid {label}")
    return value


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _is_reparse(value: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and getattr(value, "st_file_attributes", 0) & marker)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _frame(digest: "hashlib._Hash", value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _display_path(value: bytes) -> str:
    return value.decode("utf-8", "backslashreplace")


__all__ = [
    "Gitlink",
    "InexactSourceState",
    "SCHEMA",
    "SourceFingerprint",
    "SourceIssue",
    "SourceStateError",
    "UntrackedFile",
    "fingerprint_source",
]

"""Materialise revision-bound read-only experiment fixtures outside the repo.

The repository's Git objects are the authority.  This helper reads them only
through the existing s09 plumbing gate, validates every selected regular blob,
and writes the verified bytes into a new caller-owned temporary directory.
It never checks out a revision or writes into the source repository.
"""
from __future__ import annotations

import hashlib
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from s09_eval import gitio


_FULL_REVISION = re.compile(r"^[0-9a-f]{40}$")
_REGULAR_MODES = frozenset({"100644", "100755"})
_WINDOWS_INVALID = frozenset('<>:"/\\|?*~')
_WINDOWS_SUPERSCRIPT_DIGITS = (
    "\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}\N{SUPERSCRIPT THREE}"
)
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CLOCK$",
        "CONIN$",
        "CONOUT$",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"COM{number}" for number in _WINDOWS_SUPERSCRIPT_DIGITS),
        *(f"LPT{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in _WINDOWS_SUPERSCRIPT_DIGITS),
    }
)


class HistoricalTreeError(RuntimeError):
    """A pinned historical source tree could not be verified safely."""


@dataclass(frozen=True)
class HistoricalTree:
    """Verified temporary projection of selected blobs from one Git commit."""

    root: Path
    source_revision: str
    prefixes: tuple[str, ...]
    blob_count: int


def _blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _safe_repo_path(value: str) -> str:
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise HistoricalTreeError(f"unsafe Git path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HistoricalTreeError(f"unsafe Git path: {value!r}")
    normalized = path.as_posix()
    if normalized in {"", "."} or normalized != value:
        raise HistoricalTreeError(f"non-canonical Git path: {value!r}")
    for component in path.parts:
        try:
            utf8_bytes = len(component.encode("utf-8"))
            utf16_units = len(component.encode("utf-16-le")) // 2
        except UnicodeEncodeError as exc:
            raise HistoricalTreeError(f"non-portable Git path: {value!r}") from exc
        if (
            utf8_bytes > 255
            or utf16_units > 255
            or component[-1] in {" ", "."}
            or any(character in _WINDOWS_INVALID for character in component)
            or component.split(".", 1)[0].rstrip(" ").upper() in _WINDOWS_RESERVED
        ):
            raise HistoricalTreeError(f"non-portable Git path: {value!r}")
    return normalized


def _under_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _is_within(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary)
    except ValueError:
        return False
    return True


def _repository_boundaries(source_repo: Path) -> set[Path]:
    """Return current, common, admin, main, and linked-worktree boundaries."""
    try:
        top = Path(
            gitio._run(source_repo, ["rev-parse", "--show-toplevel"])
            .decode("utf-8")
            .strip()
        ).resolve()
        admin = Path(
            gitio._run(source_repo, ["rev-parse", "--absolute-git-dir"])
            .decode("utf-8")
            .strip()
        ).resolve()
        common_text = (
            gitio._run(source_repo, ["rev-parse", "--git-common-dir"])
            .decode("utf-8")
            .strip()
        )
    except (gitio.GitError, OSError) as exc:
        raise HistoricalTreeError(
            f"cannot resolve repository boundaries: {exc}"
        ) from exc

    common_path = Path(common_text)
    common = (
        common_path.resolve()
        if common_path.is_absolute()
        else (source_repo / common_path).resolve()
    )
    if common.name.casefold() != ".git":
        raise HistoricalTreeError(
            "refusing non-conventional Git common directory; "
            f"main-worktree boundary is not provable: {common}"
        )
    try:
        main = Path(
            gitio._run(common.parent, ["rev-parse", "--show-toplevel"])
            .decode("utf-8")
            .strip()
        ).resolve()
        main_common_text = (
            gitio._run(common.parent, ["rev-parse", "--git-common-dir"])
            .decode("utf-8")
            .strip()
        )
    except (gitio.GitError, OSError) as exc:
        raise HistoricalTreeError(
            f"cannot prove main-worktree boundary from {common}: {exc}"
        ) from exc
    main_common_path = Path(main_common_text)
    main_common = (
        main_common_path.resolve()
        if main_common_path.is_absolute()
        else (common.parent / main_common_path).resolve()
    )
    if main != common.parent or main_common != common:
        raise HistoricalTreeError(
            "refusing non-conventional Git common directory; "
            f"main-worktree boundary is not provable: {common}"
        )

    protected = {source_repo, top, admin, common, main}

    linked_admin = common / "worktrees"
    if linked_admin.is_dir():
        for gitdir_file in linked_admin.glob("*/gitdir"):
            try:
                gitdir_text = gitdir_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise HistoricalTreeError(
                    f"cannot read linked-worktree boundary: {gitdir_file}"
                ) from exc
            gitdir = Path(gitdir_text)
            if not gitdir.is_absolute():
                gitdir = (gitdir_file.parent / gitdir).resolve()
            else:
                gitdir = gitdir.resolve()
            protected.add(gitdir)
            if gitdir.name.casefold() == ".git":
                protected.add(gitdir.parent)
    return protected


def _materialization_targets(
    destination: Path, paths: Iterable[str]
) -> dict[str, Path]:
    """Derive collision-free portable targets and revalidate containment."""
    portable: dict[tuple[str, ...], tuple[str, ...]] = {}
    targets: dict[str, Path] = {}
    for path in paths:
        parts = PurePosixPath(path).parts
        normalized_parts: list[str] = []
        for index, part in enumerate(parts, start=1):
            normalized_parts.append(unicodedata.normalize("NFC", part).casefold())
            key = tuple(normalized_parts)
            original = tuple(parts[:index])
            previous = portable.setdefault(key, original)
            if previous != original:
                raise HistoricalTreeError(
                    "historical paths collide on a portable filesystem: "
                    f"{'/'.join(previous)} vs {'/'.join(original)}"
                )
        target = destination.joinpath(*parts)
        resolved_target = target.resolve()
        if not _is_within(resolved_target, destination):
            raise HistoricalTreeError(f"historical target escapes destination: {path}")
        targets[path] = target
    return targets


def _refuse_git_marker_ancestors(destination: Path, trusted_temp: Path) -> None:
    """Fail closed when output would land below any worktree marker."""
    current = destination.parent
    while _is_within(current, trusted_temp):
        marker = current / ".git"
        try:
            marker.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise HistoricalTreeError(f"cannot inspect Git marker: {marker}") from exc
        else:
            raise HistoricalTreeError(
                f"destination is below a Git worktree marker: {marker}"
            )
        if current == trusted_temp:
            return
        parent = current.parent
        if parent == current:  # pragma: no cover - containment already proves a root
            return
        current = parent


def _require_local_selected_blobs(
    source_repo: Path,
    source_revision: str,
    selected: tuple[str, ...],
    blob_shas: Iterable[str],
) -> None:
    """Prove selected blobs are local without triggering promisor fetching."""
    try:
        raw = gitio._run(
            source_repo,
            [
                "rev-list",
                "--objects",
                "--missing=print",
                "--no-object-names",
                source_revision,
                "--",
                *selected,
            ],
        )
    except gitio.GitError as exc:
        raise HistoricalTreeError(
            f"cannot prove selected historical objects are local: {exc}"
        ) from exc

    reported: set[str] = set()
    missing: set[str] = set()
    for raw_line in raw.splitlines():
        try:
            line = raw_line.decode("ascii")
        except UnicodeDecodeError as exc:
            raise HistoricalTreeError("malformed local-object preflight") from exc
        is_missing = line.startswith("?")
        object_id = line[1:] if is_missing else line
        if not _FULL_REVISION.fullmatch(object_id):
            raise HistoricalTreeError("malformed local-object preflight")
        reported.add(object_id)
        if is_missing:
            missing.add(object_id)

    wanted = set(blob_shas)
    unavailable = wanted & missing
    unproven = wanted - reported
    if unavailable:
        raise HistoricalTreeError(
            "selected historical blobs are not available locally: "
            + ", ".join(sorted(unavailable))
        )
    if unproven:
        raise HistoricalTreeError(
            "selected historical blobs were absent from local-object preflight: "
            + ", ".join(sorted(unproven))
        )


def materialize_historical_tree(
    source_repo: Path,
    source_revision: str,
    destination: Path,
    *,
    prefixes: Iterable[str],
) -> HistoricalTree:
    """Write verified regular blobs from `source_revision` into `destination`.

    `destination` must not exist, its parent must already exist, it must be
    under the operating system's temporary root, and it must not overlap any
    repository or linked-worktree boundary. Missing history, empty prefixes,
    unsafe paths, non-regular tree entries, or missing/corrupt blobs fail
    closed before any destination directory is created.
    """

    source_repo = source_repo.resolve()
    destination = destination.resolve()
    if not _FULL_REVISION.fullmatch(source_revision):
        raise HistoricalTreeError("source_revision must be full lowercase 40-hex")
    if destination.exists():
        raise HistoricalTreeError(f"destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise HistoricalTreeError(f"destination parent is missing: {destination.parent}")
    selected = tuple(dict.fromkeys(_safe_repo_path(value) for value in prefixes))
    if not selected:
        raise HistoricalTreeError("at least one historical prefix is required")

    try:
        resolved = gitio.rev_parse(source_repo, f"{source_revision}^{{commit}}")
        if resolved != source_revision:
            raise HistoricalTreeError(
                f"revision mismatch: expected {source_revision}, resolved {resolved}"
            )
        raw_tree = gitio._run(
            source_repo,
            [
                "ls-tree",
                "-r",
                "-l",
                "-z",
                "--full-tree",
                source_revision,
                "--",
                *selected,
            ],
        )
    except gitio.GitError as exc:
        raise HistoricalTreeError(str(exc)) from exc

    for protected in _repository_boundaries(source_repo):
        if _is_within(destination, protected) or _is_within(protected, destination):
            raise HistoricalTreeError(
                f"destination overlaps a repository boundary: {protected}"
            )
    trusted_temp = Path(tempfile.gettempdir()).resolve()
    if not _is_within(destination, trusted_temp):
        raise HistoricalTreeError(
            f"destination must be under the OS temporary root: {trusted_temp}"
        )
    _refuse_git_marker_ancestors(destination, trusted_temp)

    entries: dict[str, tuple[str, int, str]] = {}
    for raw_entry in raw_tree.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        if separator != b"\t":
            raise HistoricalTreeError("malformed ls-tree entry")
        try:
            mode, object_type, blob_sha, size_text = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
            size = int(size_text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise HistoricalTreeError("malformed ls-tree metadata") from exc
        path = _safe_repo_path(path)
        if mode not in _REGULAR_MODES or object_type != "blob":
            raise HistoricalTreeError(
                f"non-regular historical entry refused: {mode} {object_type} {path}"
            )
        if not _FULL_REVISION.fullmatch(blob_sha) or size < 0:
            raise HistoricalTreeError(f"invalid blob metadata for {path}")
        if path in entries:
            raise HistoricalTreeError(f"duplicate historical path: {path}")
        if not any(_under_prefix(path, prefix) for prefix in selected):
            raise HistoricalTreeError(f"Git returned a path outside the selection: {path}")
        entries[path] = (blob_sha, size, mode)

    missing_prefixes = [
        prefix
        for prefix in selected
        if not any(_under_prefix(path, prefix) for path in entries)
    ]
    if missing_prefixes:
        raise HistoricalTreeError(
            "historical prefixes contain no regular blobs: "
            + ", ".join(missing_prefixes)
        )

    targets = _materialization_targets(destination, entries)
    _require_local_selected_blobs(
        source_repo,
        source_revision,
        selected,
        (blob_sha for blob_sha, _size, _mode in entries.values()),
    )

    try:
        blobs = gitio.read_blobs(
            source_repo, [blob_sha for blob_sha, _size, _mode in entries.values()]
        )
    except gitio.GitError as exc:
        raise HistoricalTreeError(str(exc)) from exc

    for path, (blob_sha, size, _mode) in entries.items():
        payload = blobs.get(blob_sha)
        if payload is None:
            raise HistoricalTreeError(f"historical blob is missing: {path} {blob_sha}")
        if len(payload) != size:
            raise HistoricalTreeError(f"historical blob size mismatch: {path}")
        if _blob_sha1(payload) != blob_sha:
            raise HistoricalTreeError(f"historical blob digest mismatch: {path}")

    destination.mkdir()
    for path, (blob_sha, _size, mode) in entries.items():
        target = targets[path]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blobs[blob_sha])
        if mode == "100755":
            target.chmod(0o755)

    return HistoricalTree(
        root=destination,
        source_revision=source_revision,
        prefixes=selected,
        blob_count=len(entries),
    )

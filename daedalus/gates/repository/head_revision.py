"""Race-aware, process-free verification of a repository's exact Git HEAD.

The verifier reads only ``.git/HEAD`` and the selected loose or packed ref
through the shared repository-source reader. It never invokes ``git`` or any
other process, never mutates Git metadata, and does not infer worktree
cleanliness or commit-object validity. The resulting receipt proves only that
the selected expected revision matched a stable HEAD observation in a canonical
non-worktree checkout.
"""
from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daedalus.gates.repository.tree import (
    RepositorySourceSnapshot,
    RepositoryTreePathError,
    RepositoryTreeRaceError,
    RepositoryTreeReadError,
    normalize_repository_path,
    read_repository_source,
    resolve_repository_root,
)
from daedalus.runtimes.contracts.repository import (
    RepositoryHeadRevisionBindingError,
    RepositoryHeadRevisionError,
    RepositoryHeadRevisionRaceError,
    RepositoryHeadRevisionReceipt,
    RepositoryHeadRevisionShapeError,
)
from daedalus.schemas import _revision, _sha256


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryHeadRevisionShapeError(
            f"{label} must be a non-negative strict integer"
        )
    return value


def _single_line(snapshot: RepositorySourceSnapshot, label: str) -> str:
    if type(snapshot) is not RepositorySourceSnapshot:
        raise RepositoryHeadRevisionShapeError(
            f"{label} snapshot type is not exact"
        )
    try:
        text = snapshot.source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RepositoryHeadRevisionShapeError(
            f"{label} is not strict UTF-8"
        ) from exc
    if text.endswith("\n"):
        text = text[:-1]
    if not text or "\n" in text or "\r" in text:
        raise RepositoryHeadRevisionShapeError(
            f"{label} must contain exactly one canonical line"
        )
    return text


def _canonical_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("refs/"):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref must start with refs/"
        )
    if value.endswith(("/", ".", ".lock")):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref has a forbidden suffix"
        )
    if any(token in value for token in ("..", "//", "@{", "\\")):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref is not canonical"
        )
    forbidden = set(" ~^:?*[]")
    if any(
        character in forbidden or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref contains a forbidden character"
        )
    parts = value.split("/")
    if len(parts) < 3 or any(
        not part
        or part in {".", ".."}
        or part.startswith(".")
        or part.endswith(".lock")
        for part in parts
    ):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref contains a forbidden path segment"
        )
    return value


def _revision_value(value: Any, label: str) -> str:
    try:
        return _revision(value, label)
    except (TypeError, ValueError) as exc:
        raise RepositoryHeadRevisionShapeError(
            f"{label} must be a lowercase 40-hex revision"
        ) from exc


def _safe_optional_regular_file(root: Path, relative_path: str) -> bool:
    try:
        path = normalize_repository_path(relative_path)
    except RepositoryTreePathError as exc:
        raise RepositoryHeadRevisionShapeError(
            "repository metadata path is not canonical"
        ) from exc
    current = root
    parts = Path(*path.split("/")).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RepositoryHeadRevisionShapeError(
                f"repository metadata path is unavailable: {path}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RepositoryHeadRevisionShapeError(
                f"repository metadata path contains a symlink: {path}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise RepositoryHeadRevisionShapeError(
                f"repository metadata parent is not a directory: {path}"
            )
    if not stat.S_ISREG(metadata.st_mode):
        raise RepositoryHeadRevisionShapeError(
            f"repository metadata path is not a regular file: {path}"
        )
    return True


def _read_source(root: Path, path: str) -> RepositorySourceSnapshot:
    try:
        return read_repository_source(root, path)
    except RepositoryTreeRaceError as exc:
        raise RepositoryHeadRevisionRaceError(
            f"repository metadata raced while reading {path}"
        ) from exc
    except (RepositoryTreePathError, RepositoryTreeReadError) as exc:
        raise RepositoryHeadRevisionShapeError(
            f"repository metadata cannot be read safely: {path}"
        ) from exc


def _parse_packed_revision(
    snapshot: RepositorySourceSnapshot,
    ref: str,
) -> str:
    matches: list[str] = []
    try:
        text = snapshot.source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RepositoryHeadRevisionShapeError(
            "packed-refs is not strict UTF-8"
        ) from exc
    for line in text.splitlines():
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        revision, separator, name = line.partition(" ")
        if separator and name == ref:
            matches.append(
                _revision_value(revision, "packed ref revision")
            )
    if len(matches) != 1:
        raise RepositoryHeadRevisionBindingError(
            "HEAD symbolic ref is not present exactly once in packed-refs"
        )
    return matches[0]


@dataclass(frozen=True)
class _HeadObservation:
    resolved_revision: str
    head_mode: str
    head_ref: str | None
    resolution_source: str
    head_sha256: str
    head_size: int
    reference_path: str | None
    reference_sha256: str | None
    reference_size: int | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resolved_revision",
            _revision_value(self.resolved_revision, "resolved_revision"),
        )
        try:
            object.__setattr__(
                self,
                "head_sha256",
                _sha256(self.head_sha256, "head_sha256"),
            )
        except (TypeError, ValueError) as exc:
            raise RepositoryHeadRevisionShapeError(
                "HEAD observation digest is malformed"
            ) from exc
        _strict_int(self.head_size, "head_size")
        if self.head_mode == "detached":
            if self.head_ref is not None or self.resolution_source != "head":
                raise RepositoryHeadRevisionShapeError(
                    "detached HEAD observation has symbolic-ref fields"
                )
            if any(
                value is not None
                for value in (
                    self.reference_path,
                    self.reference_sha256,
                    self.reference_size,
                )
            ):
                raise RepositoryHeadRevisionShapeError(
                    "detached HEAD observation has reference evidence"
                )
            return
        if self.head_mode != "symbolic":
            raise RepositoryHeadRevisionShapeError(
                "head_mode must be detached or symbolic"
            )
        object.__setattr__(self, "head_ref", _canonical_ref(self.head_ref))
        if self.resolution_source not in {"loose_ref", "packed_refs"}:
            raise RepositoryHeadRevisionShapeError(
                "symbolic HEAD resolution source is unsupported"
            )
        if not isinstance(self.reference_path, str):
            raise RepositoryHeadRevisionShapeError(
                "symbolic HEAD reference_path is missing"
            )
        try:
            normalize_repository_path(self.reference_path)
        except RepositoryTreePathError as exc:
            raise RepositoryHeadRevisionShapeError(
                "symbolic HEAD reference_path is not canonical"
            ) from exc
        try:
            object.__setattr__(
                self,
                "reference_sha256",
                _sha256(self.reference_sha256, "reference_sha256"),
            )
        except (TypeError, ValueError) as exc:
            raise RepositoryHeadRevisionShapeError(
                "symbolic HEAD reference digest is malformed"
            ) from exc
        _strict_int(self.reference_size, "reference_size")
        expected_path = (
            f".git/{self.head_ref}"
            if self.resolution_source == "loose_ref"
            else ".git/packed-refs"
        )
        if self.reference_path != expected_path:
            raise RepositoryHeadRevisionShapeError(
                "symbolic HEAD reference_path differs from resolution source"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolved_revision": self.resolved_revision,
            "head_mode": self.head_mode,
            "head_ref": self.head_ref,
            "resolution_source": self.resolution_source,
            "head_sha256": self.head_sha256,
            "head_size": self.head_size,
            "reference_path": self.reference_path,
            "reference_sha256": self.reference_sha256,
            "reference_size": self.reference_size,
        }


def _resolve_once(root: Path) -> _HeadObservation:
    head = _read_source(root, ".git/HEAD")
    line = _single_line(head, "HEAD")
    try:
        detached = _revision_value(line, "detached HEAD")
    except RepositoryHeadRevisionShapeError:
        detached = None
    if detached is not None:
        return _HeadObservation(
            resolved_revision=detached,
            head_mode="detached",
            head_ref=None,
            resolution_source="head",
            head_sha256=head.source_sha256,
            head_size=head.size,
            reference_path=None,
            reference_sha256=None,
            reference_size=None,
        )
    if not line.startswith("ref: "):
        raise RepositoryHeadRevisionShapeError(
            "HEAD must contain a detached revision or canonical symbolic ref"
        )
    ref = _canonical_ref(line[5:])
    loose_path = f".git/{ref}"
    if _safe_optional_regular_file(root, loose_path):
        reference = _read_source(root, loose_path)
        reference_line = _single_line(reference, "loose ref")
        if reference_line.startswith("ref: "):
            raise RepositoryHeadRevisionShapeError(
                "nested symbolic refs are not supported by this verifier"
            )
        revision = _revision_value(reference_line, "loose ref revision")
        source = "loose_ref"
        reference_path = loose_path
    else:
        reference_path = ".git/packed-refs"
        reference = _read_source(root, reference_path)
        revision = _parse_packed_revision(reference, ref)
        source = "packed_refs"
    return _HeadObservation(
        resolved_revision=revision,
        head_mode="symbolic",
        head_ref=ref,
        resolution_source=source,
        head_sha256=head.source_sha256,
        head_size=head.size,
        reference_path=reference_path,
        reference_sha256=reference.source_sha256,
        reference_size=reference.size,
    )


def _identity(path: Path, label: str) -> tuple[int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RepositoryHeadRevisionRaceError(
            f"{label} disappeared during verification"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RepositoryHeadRevisionShapeError(
            f"{label} must be a real directory"
        )
    return metadata.st_dev, metadata.st_ino


def verify_repository_head_revision(
    repository_root: Path,
    expected_revision: str,
) -> RepositoryHeadRevisionReceipt:
    """Verify a stable detached, loose-ref, or packed-ref HEAD without spawning."""

    if not isinstance(repository_root, Path):
        raise RepositoryHeadRevisionShapeError(
            "repository_root must be pathlib.Path"
        )
    expected = _revision_value(expected_revision, "expected_revision")
    try:
        root = resolve_repository_root(repository_root)
    except RepositoryTreeRaceError as exc:
        raise RepositoryHeadRevisionRaceError(
            "repository root raced during resolution"
        ) from exc
    except RepositoryTreeReadError as exc:
        raise RepositoryHeadRevisionShapeError(
            "repository root cannot be resolved safely"
        ) from exc
    git_dir = root / ".git"
    root_before = _identity(root, "repository root")
    git_before = _identity(git_dir, "Git metadata directory")

    first = _resolve_once(root)
    second = _resolve_once(root)

    if first.to_dict() != second.to_dict():
        raise RepositoryHeadRevisionRaceError(
            "Git HEAD observation changed during verification"
        )
    if _identity(root, "repository root") != root_before:
        raise RepositoryHeadRevisionRaceError(
            "repository root identity changed during verification"
        )
    if _identity(git_dir, "Git metadata directory") != git_before:
        raise RepositoryHeadRevisionRaceError(
            "Git metadata directory identity changed during verification"
        )
    if first.resolved_revision != expected:
        raise RepositoryHeadRevisionBindingError(
            "repository HEAD differs from expected revision"
        )
    return RepositoryHeadRevisionReceipt(
        expected_revision=expected,
        **first.to_dict(),
    )


def verify_repository_head_revision_receipt(
    repository_root: Path,
    expected_revision: str,
    receipt: RepositoryHeadRevisionReceipt,
) -> None:
    """Rebuild a stable HEAD receipt and refuse every detached retained field."""

    if type(receipt) is not RepositoryHeadRevisionReceipt:
        raise RepositoryHeadRevisionShapeError(
            "receipt must be exact RepositoryHeadRevisionReceipt"
        )
    rebuilt = verify_repository_head_revision(
        repository_root,
        expected_revision,
    )
    if rebuilt.to_dict() != receipt.to_dict():
        raise RepositoryHeadRevisionBindingError(
            "repository HEAD receipt differs from live verification"
        )


__all__ = [
    "RepositoryHeadRevisionBindingError",
    "RepositoryHeadRevisionError",
    "RepositoryHeadRevisionRaceError",
    "RepositoryHeadRevisionReceipt",
    "RepositoryHeadRevisionShapeError",
    "verify_repository_head_revision",
    "verify_repository_head_revision_receipt",
]

"""Shared strict helpers for the bounded Fourfold reference compiler."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Mapping, Sequence

REFERENCE_SCHEMA = "daedalus-fourfold-reference/1"
MANIFEST_KEYS = frozenset({
    "schema", "repository_id", "code_files", "data_files", "knowledge_files", "claims",
})
CLAIM_KEYS: dict[str, frozenset[str]] = {
    "code_declares_type": frozenset({"kind", "code_file", "type_file", "type_name"}),
    "type_matches_csv_field": frozenset({
        "kind", "type_file", "type_name", "type_field", "csv_file", "csv_field",
    }),
    "type_matches_schema_field": frozenset({
        "kind", "type_file", "type_name", "type_field", "schema_file", "schema_field",
    }),
    "wiki_documents_node": frozenset({
        "kind", "wiki_file", "link_target", "target_plane", "target_node_id",
    }),
}


class ReferenceCompileError(ValueError):
    """Fail-closed error raised for an invalid reference project."""


@dataclass(frozen=True)
class ReferenceLimits:
    """Resource limits for one bounded reference compilation."""

    max_manifest_bytes: int = 1_000_000
    max_files: int = 10_000
    max_file_bytes: int = 32_000_000
    max_total_bytes: int = 512_000_000
    max_claims: int = 100_000

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_REFERENCE_LIMITS = ReferenceLimits()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relpath(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReferenceCompileError(f"{name} must be a non-empty string")
    if "\\" in value or "\x00" in value:
        raise ReferenceCompileError(f"{name} must use repository-relative POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReferenceCompileError(f"{name} must stay inside the reference project")
    return path.as_posix()


def strict_object(value: Any, *, allowed: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReferenceCompileError(f"{label} must be an object")
    unknown = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if unknown or missing:
        raise ReferenceCompileError(
            f"{label} has invalid fields (missing={missing}, unknown={unknown})"
        )
    return dict(value)


def strict_path_list(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ReferenceCompileError(f"{name} must be a sequence")
    paths = tuple(safe_relpath(item, f"{name}[{i}]") for i, item in enumerate(value))
    if not paths:
        raise ReferenceCompileError(f"{name} must not be empty")
    if len(set(paths)) != len(paths):
        raise ReferenceCompileError(f"{name} must not contain duplicates")
    return tuple(sorted(paths))


def strict_json_loads(value: str | bytes, label: str) -> Any:
    """Parse JSON while refusing duplicate keys at every object depth."""

    text = decode_text(value, label) if isinstance(value, bytes) else value

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ReferenceCompileError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = item
        return result

    try:
        return json.loads(text, object_pairs_hook=object_pairs)
    except ReferenceCompileError:
        raise
    except json.JSONDecodeError as exc:
        raise ReferenceCompileError(f"JSON parse failed for {label}: {exc}") from exc


def resolve_regular_file(root: Path, relpath: str) -> Path:
    """Resolve a regular file without permitting symlink components or escape."""

    root_resolved = root.resolve()
    current = root_resolved
    for part in PurePosixPath(relpath).parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise ReferenceCompileError(f"declared file is missing: {relpath}") from exc
        if stat.S_ISLNK(mode):
            raise ReferenceCompileError(f"declared file path contains a symbolic link: {relpath}")
    try:
        current.resolve(strict=True).relative_to(root_resolved)
    except (FileNotFoundError, ValueError) as exc:
        raise ReferenceCompileError(f"declared file escapes reference project: {relpath}") from exc
    if not stat.S_ISREG(current.stat().st_mode):
        raise ReferenceCompileError(f"declared path is not a regular file: {relpath}")
    return current


def read_file(root: Path, relpath: str, *, max_bytes: int | None = None) -> bytes:
    candidate = resolve_regular_file(root, relpath)
    before = candidate.stat()
    if max_bytes is not None and before.st_size > max_bytes:
        raise ReferenceCompileError(
            f"declared file exceeds byte limit: {relpath} ({before.st_size} > {max_bytes})"
        )
    data = candidate.read_bytes()
    after = candidate.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(data) != after.st_size:
        raise ReferenceCompileError(f"declared file changed while being read: {relpath}")
    if max_bytes is not None and len(data) > max_bytes:
        raise ReferenceCompileError(f"declared file exceeds byte limit after read: {relpath}")
    return data


def decode_text(data: bytes, relpath: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReferenceCompileError(f"{relpath} must be UTF-8") from exc

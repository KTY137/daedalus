"""Shared strict helpers for the bounded Fourfold reference compiler."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
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


def read_file(root: Path, relpath: str) -> bytes:
    root_resolved = root.resolve()
    candidate = (root_resolved / relpath).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ReferenceCompileError(f"declared file escapes reference project: {relpath}") from exc
    if not candidate.is_file():
        raise ReferenceCompileError(f"declared file is missing: {relpath}")
    return candidate.read_bytes()


def decode_text(data: bytes, relpath: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReferenceCompileError(f"{relpath} must be UTF-8") from exc

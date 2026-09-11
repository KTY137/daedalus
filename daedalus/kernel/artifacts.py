"""Shared content-addressed artifact identities for the trust stack.

This module contains no domain policy.  It provides the single mechanical
implementation for ``sha256`` artifact locators, canonical JSON persistence,
and deterministic read-only file-tree digests used by Gate 0 and Gate 1.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.contracts.base import (
    _artifact_locator,
    _locator_sha256,
    _sha256,
)
from daedalus.spine.envelope import canonical_json, canonical_sha


ARTIFACT_LOCATOR_PREFIX = "artifact-locator:sha256:"


class ArtifactIdentityError(ValueError):
    """Raised when a digest, locator, or content-addressed artifact disagrees."""


@dataclass(frozen=True)
class ArtifactRef:
    """An exact digest/locator pair with mechanical equality validation."""

    sha256: str
    locator: str

    def __post_init__(self) -> None:
        digest = _sha256(self.sha256, "artifact_sha256")
        locator = _artifact_locator(self.locator, "artifact_locator")
        if _locator_sha256(locator) != digest:
            raise ArtifactIdentityError(
                "artifact locator does not resolve to the declared digest"
            )
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "locator", locator)

    @classmethod
    def from_sha256(cls, digest: str) -> "ArtifactRef":
        normalized = _sha256(digest, "artifact_sha256")
        return cls(
            sha256=normalized,
            locator=f"{ARTIFACT_LOCATOR_PREFIX}{normalized}",
        )

    def to_dict(self) -> dict[str, str]:
        return {"sha256": self.sha256, "locator": self.locator}


def artifact_locator(digest: str) -> str:
    """Return the canonical locator for one validated SHA-256 digest."""
    return ArtifactRef.from_sha256(digest).locator


def store_canonical_json(
    root: str | Path,
    payload: Mapping[str, Any],
) -> ArtifactRef:
    """Persist canonical JSON under its digest and refuse content collisions."""
    body = dict(payload)
    raw = canonical_json(body).encode("ascii")
    ref = ArtifactRef.from_sha256(canonical_sha(body))
    directory = Path(root).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{ref.sha256}.json"
    if path.exists():
        if path.read_bytes() != raw:
            raise ArtifactIdentityError("content-addressed artifact collision")
    else:
        path.write_bytes(raw)
    return ref


def digest_file_tree(root: str | Path) -> str:
    """Digest a regular-file tree without following symlinks.

    Paths, byte lengths, and raw file SHA-256 values are retained in the
    canonical tree object.  Rejecting symlinks keeps the digest independent of
    external filesystem state and matches the bounded reference-compiler rule.
    """
    directory = Path(root).resolve()
    if not directory.is_dir():
        raise ArtifactIdentityError("artifact tree root must be an existing directory")

    rows: list[dict[str, object]] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ArtifactIdentityError(
                f"artifact tree contains a symlink: {path.relative_to(directory).as_posix()}"
            )
        if not path.is_file():
            continue
        raw = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return canonical_sha({"schema": "daedalus-file-tree/1", "files": rows})


__all__ = [
    "ARTIFACT_LOCATOR_PREFIX",
    "ArtifactIdentityError",
    "ArtifactRef",
    "artifact_locator",
    "digest_file_tree",
    "store_canonical_json",
]

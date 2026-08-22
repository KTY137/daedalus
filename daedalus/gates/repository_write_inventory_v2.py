"""Canonical generation-2 repository write-surface inventory strangler.

The generation-1 scanner remains import-compatible.  This module composes its
revision-bound result with the separately reviewed stdlib delta and refuses any
cross-scan drift.  It is still inventory evidence: no callsite is classified as
Primary-Checkout-safe, guarded, or trusted here.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from daedalus.gates.repository_write_inventory import (
    RepositoryWriteInventory,
    RepositoryWriteInventoryError,
    scan_repository_write_surfaces,
)
from daedalus.gates.repository_write_stdlib_delta import (
    RepositoryWriteStdlibDelta,
    RepositoryWriteStdlibDeltaError,
    scan_repository_write_stdlib_delta,
)
from daedalus.spine.envelope import canonical_json


_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ORIGINS = frozenset({"base_v1", "stdlib_delta_v1"})


class RepositoryWriteInventoryV2Error(RuntimeError):
    """Generation-2 inventory could not be produced without ambiguity."""


@dataclass(frozen=True, order=True)
class RepositoryWriteSurface:
    path: str
    line: int
    column: int
    origin: str
    kind: str
    callee: str
    operation: str
    blocking: bool

    def __post_init__(self) -> None:
        if not _safe_relative_posix(self.path):
            raise ValueError("surface path must be repository-relative POSIX")
        if type(self.line) is not int or type(self.column) is not int:
            raise ValueError("surface position must use strict integers")
        if self.line < 1 or self.column < 0:
            raise ValueError("surface position is invalid")
        if self.origin not in _ORIGINS:
            raise ValueError("surface origin is invalid")
        if not self.kind or any(ch.isspace() for ch in self.kind):
            raise ValueError("surface kind is invalid")
        if not self.callee or any(ch.isspace() for ch in self.callee):
            raise ValueError("surface callee is invalid")
        if not self.operation or any(ch in self.operation for ch in "\r\n"):
            raise ValueError("surface operation is invalid")
        if type(self.blocking) is not bool:
            raise ValueError("surface blocking flag must be a strict boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "origin": self.origin,
            "kind": self.kind,
            "callee": self.callee,
            "operation": self.operation,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class RepositoryWriteInventoryV2:
    source_revision: str
    package_root: str
    scan_input_sha256: str
    files_scanned: int
    base_inventory_digest: str
    stdlib_delta_digest: str
    surfaces: tuple[RepositoryWriteSurface, ...]

    def __post_init__(self) -> None:
        if not _SOURCE_REVISION.fullmatch(self.source_revision):
            raise ValueError("source_revision must be a lowercase 40-hex commit")
        if not _safe_relative_posix(self.package_root):
            raise ValueError("package_root must be repository-relative POSIX")
        if not _SHA256.fullmatch(self.scan_input_sha256):
            raise ValueError("scan_input_sha256 must be lowercase sha256")
        if not _SHA256.fullmatch(self.base_inventory_digest):
            raise ValueError("base_inventory_digest must be lowercase sha256")
        if not _SHA256.fullmatch(self.stdlib_delta_digest):
            raise ValueError("stdlib_delta_digest must be lowercase sha256")
        if type(self.files_scanned) is not int or self.files_scanned < 1:
            raise ValueError("files_scanned must be a positive strict integer")
        if not isinstance(self.surfaces, tuple):
            raise ValueError("surfaces must be an immutable tuple")
        if tuple(sorted(self.surfaces)) != self.surfaces:
            raise ValueError("surfaces must be sorted")
        if len(set(self.surfaces)) != len(self.surfaces):
            raise ValueError("surfaces must be unique")
        positions = {(item.path, item.line, item.column) for item in self.surfaces}
        if len(positions) != len(self.surfaces):
            raise ValueError("surface positions must be unique across components")

    @property
    def blockers(self) -> tuple[RepositoryWriteSurface, ...]:
        return tuple(surface for surface in self.surfaces if surface.blocking)

    @property
    def closed(self) -> bool:
        return not self.blockers

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate0-repository-write-inventory/2",
            "source_revision": self.source_revision,
            "package_root": self.package_root,
            "scan_input_sha256": self.scan_input_sha256,
            "files_scanned": self.files_scanned,
            "components": {
                "base_inventory_digest": self.base_inventory_digest,
                "stdlib_delta_digest": self.stdlib_delta_digest,
            },
            "surfaces": [surface.to_dict() for surface in self.surfaces],
            "surface_count": len(self.surfaces),
            "blocker_count": len(self.blockers),
            "closed": self.closed,
            "canonical_scanner_integrated": True,
            "inventory_generation": 2,
            "scope": "potential_repository_write_surface",
            "inventory_only": True,
            "primary_checkout_target_proven": False,
            "blockers": (
                ["unclassified-production-write-surfaces"]
                if self.blockers
                else []
            ),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "digest": self.digest}


def _safe_relative_posix(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    # PurePosixPath, not Path: on Windows a rooted-but-driveless value such as
    # "/daedalus/a.py" is not reported as absolute, so the platform-dependent
    # Path would let an absolute POSIX path pass as repository-relative.
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == value
    )


def _validate_components(
    base_before: RepositoryWriteInventory,
    delta: RepositoryWriteStdlibDelta,
    base_after: RepositoryWriteInventory,
    *,
    source_revision: str,
) -> None:
    if not isinstance(base_before, RepositoryWriteInventory):
        raise RepositoryWriteInventoryV2Error("base-before result type is invalid")
    if not isinstance(delta, RepositoryWriteStdlibDelta):
        raise RepositoryWriteInventoryV2Error("stdlib-delta result type is invalid")
    if not isinstance(base_after, RepositoryWriteInventory):
        raise RepositoryWriteInventoryV2Error("base-after result type is invalid")
    if not (
        base_before.source_revision
        == delta.source_revision
        == base_after.source_revision
        == source_revision
    ):
        raise RepositoryWriteInventoryV2Error("component source revisions differ")
    if not (
        base_before.digest
        == delta.base_inventory_digest
        == base_after.digest
    ):
        raise RepositoryWriteInventoryV2Error(
            "base inventory changed while composing generation 2"
        )
    if not (
        base_before.scan_input_sha256
        == delta.scan_input_sha256
        == base_after.scan_input_sha256
    ):
        raise RepositoryWriteInventoryV2Error(
            "production bytes changed while composing generation 2"
        )
    if not (
        base_before.files_scanned
        == delta.files_scanned
        == base_after.files_scanned
    ):
        raise RepositoryWriteInventoryV2Error(
            "production file set changed while composing generation 2"
        )


def scan_repository_write_surfaces_v2(
    repository_root: str | Path,
    *,
    source_revision: str,
) -> RepositoryWriteInventoryV2:
    """Compose both reviewed scanners under a stable revision/byte fence."""

    if not isinstance(source_revision, str) or not _SOURCE_REVISION.fullmatch(
        source_revision
    ):
        raise RepositoryWriteInventoryV2Error(
            "source_revision must be a lowercase 40-hex commit"
        )
    try:
        base_before = scan_repository_write_surfaces(
            repository_root,
            source_revision=source_revision,
        )
        delta = scan_repository_write_stdlib_delta(
            repository_root,
            source_revision=source_revision,
        )
        base_after = scan_repository_write_surfaces(
            repository_root,
            source_revision=source_revision,
        )
    except (
        RepositoryWriteInventoryError,
        RepositoryWriteStdlibDeltaError,
        # A component's frozen-dataclass identity check raises a bare
        # ValueError.  Both declared refusal types are RuntimeError
        # subclasses, so ValueError here is disjoint from them and always
        # means "a component could not decide its own record identity".
        # Without this clause it escapes every fail-closed handler above and
        # the caller emits an error document with no counters at all.
        ValueError,
    ) as exc:
        raise RepositoryWriteInventoryV2Error(
            "repository write inventory component failed"
        ) from exc

    _validate_components(
        base_before,
        delta,
        base_after,
        source_revision=source_revision,
    )

    base_positions = {
        (site.path, site.line, site.column) for site in base_before.callsites
    }
    delta_positions = {
        (finding.path, finding.line, finding.column) for finding in delta.findings
    }
    if base_positions.intersection(delta_positions):
        raise RepositoryWriteInventoryV2Error(
            "scanner components overlap at one source position"
        )

    try:
        surfaces = _compose_surfaces(base_before, delta)
        return RepositoryWriteInventoryV2(
            source_revision=source_revision,
            package_root=base_before.package_root,
            scan_input_sha256=base_before.scan_input_sha256,
            files_scanned=base_before.files_scanned,
            base_inventory_digest=base_before.digest,
            stdlib_delta_digest=delta.digest,
            surfaces=surfaces,
        )
    except ValueError as exc:
        # Composition identity failures ("surfaces must be unique", "surface
        # positions must be unique across components") were raised outside the
        # try block above and escaped as bare ValueError, past every declared
        # fail-closed handler in daedalus/gates/report_v3.py.  A refusal is
        # evidence; an uncaught crash is a report with no counters.
        raise RepositoryWriteInventoryV2Error(
            f"repository write surface identity is not decidable: {exc}"
        ) from exc


def _compose_surfaces(
    base_before: RepositoryWriteInventory,
    delta: RepositoryWriteStdlibDelta,
) -> tuple[RepositoryWriteSurface, ...]:
    return tuple(
        sorted(
            [
                RepositoryWriteSurface(
                    path=site.path,
                    line=site.line,
                    column=site.column,
                    origin="base_v1",
                    kind=site.kind,
                    callee=site.callee,
                    operation=site.operation,
                    blocking=site.blocking,
                )
                for site in base_before.callsites
            ]
            + [
                RepositoryWriteSurface(
                    path=finding.path,
                    line=finding.line,
                    column=finding.column,
                    origin="stdlib_delta_v1",
                    kind=finding.kind,
                    callee=finding.callee,
                    operation=finding.operation,
                    blocking=True,
                )
                for finding in delta.findings
            ]
        )
    )

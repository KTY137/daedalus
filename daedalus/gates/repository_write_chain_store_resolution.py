"""Read-only ArtifactStore resolution for repository-write chain artifacts.

This boundary turns one declared ``artifact-locator:sha256:<manifest-digest>``
into exact immutable chain-result bytes.  Blob identity and locator-manifest
identity remain distinct.  The resolver accepts no alternate path, never
creates store state, requires the ArtifactStore to be disjoint from the primary
checkout, performs descriptor-stable bounded reads, and then delegates logical
chain validation to the existing byte verifier in a later composition layer.

The receipt is mechanical resolution evidence only.  It does not authenticate
the collector that produced the chain, close a Gate, issue OwnerApproval, or
authorize release/promotion.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)
from daedalus.storage import ArtifactStore, ArtifactStoreError

from .repository_write_chain_evidence import RepositoryWriteChainArtifactEvidence


CHAIN_RESULT_MEDIA_TYPE = (
    "application/vnd.daedalus.repository-write-chain-result+json"
)
CHAIN_RESULT_STORE_ORIGIN = "gate0.repository-write-chain-artifact-store"
CHAIN_RESULT_STORE_METADATA = {"kind": "repository-write-chain-result"}

_MAX_LOCATOR_BYTES = 2 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_LOCATOR_URI = re.compile(r"^artifact-locator:sha256:([0-9a-f]{64})$")
_RESOLUTION_CHECKS = tuple(
    sorted(
        (
            "blob-content-sha256",
            "checkout-disjoint-store",
            "descriptor-stable-read",
            "locator-manifest-sha256",
            "locator-subject-binding",
        )
    )
)
_RESOLUTION_ORIGIN = "gate0.repository-write-chain-store-resolution"


class RepositoryWriteChainStoreResolutionError(RuntimeError):
    """The declared chain artifact cannot be safely resolved from its store."""


def _non_negative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryWriteChainStoreResolutionError(
            f"{name} must be a non-negative integer"
        )
    return value


def _locator_sha256(locator: str) -> str:
    if not isinstance(locator, str):
        raise RepositoryWriteChainStoreResolutionError(
            "artifact locator must be text"
        )
    match = _LOCATOR_URI.fullmatch(locator)
    if match is None:
        raise RepositoryWriteChainStoreResolutionError(
            "artifact locator must be an exact ArtifactStore locator URI"
        )
    return match.group(1)


def _normal_path(path: Path, *, strict: bool) -> str:
    try:
        resolved = path.resolve(strict=strict)
    except (OSError, RuntimeError) as exc:
        raise RepositoryWriteChainStoreResolutionError(
            f"cannot resolve filesystem path: {path}"
        ) from exc
    rendered = str(resolved)
    if os.name == "nt":
        if rendered.startswith("\\\\?\\UNC\\"):
            rendered = "\\\\" + rendered[8:]
        elif rendered.startswith("\\\\?\\"):
            rendered = rendered[4:]
    return os.path.normcase(os.path.normpath(rendered))


def _paths_overlap(left: Path, right: Path) -> bool:
    left_norm = _normal_path(left, strict=True)
    right_norm = _normal_path(right, strict=True)
    try:
        common = os.path.normcase(os.path.commonpath((left_norm, right_norm)))
    except ValueError:
        return False
    return common == left_norm or common == right_norm


def _require_disjoint_store(store: ArtifactStore, primary_checkout: Path) -> Path:
    if type(store) is not ArtifactStore:
        raise RepositoryWriteChainStoreResolutionError(
            "store must be exact ArtifactStore"
        )
    root = store.root
    try:
        root_stat = root.stat()
    except OSError as exc:
        raise RepositoryWriteChainStoreResolutionError(
            "artifact store root must already exist"
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode) or root.is_symlink():
        raise RepositoryWriteChainStoreResolutionError(
            "artifact store root must be an existing non-symlink directory"
        )
    checkout = Path(primary_checkout)
    try:
        checkout_stat = checkout.stat()
    except OSError as exc:
        raise RepositoryWriteChainStoreResolutionError(
            "primary checkout must already exist"
        ) from exc
    if not stat.S_ISDIR(checkout_stat.st_mode) or checkout.is_symlink():
        raise RepositoryWriteChainStoreResolutionError(
            "primary checkout must be an existing non-symlink directory"
        )
    if _paths_overlap(root, checkout):
        raise RepositoryWriteChainStoreResolutionError(
            "artifact store overlaps the primary checkout"
        )
    return root.resolve(strict=True)


def _require_confined_parent(root: Path, path: Path, label: str) -> None:
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} parent is missing"
        ) from exc
    root_norm = _normal_path(root, strict=True)
    parent_norm = _normal_path(parent, strict=True)
    try:
        common = os.path.normcase(os.path.commonpath((root_norm, parent_norm)))
    except ValueError as exc:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} parent is outside the artifact store"
        ) from exc
    if common != root_norm:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} parent escapes the artifact store"
        )


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
    )


def _stable_read(
    path: Path,
    *,
    expected_sha256: str,
    max_bytes: int,
    expected_size: int | None,
    label: str,
) -> bytes:
    """Read one regular file through a stable descriptor and recheck its path.

    The before/open/after identity checks make detectable path replacement fail
    closed even where ``O_NOFOLLOW`` is unavailable.  This is intentionally not
    advertised as protection against a hostile actor able to replace an entire
    mount namespace between individual syscalls; the OS sandbox remains the
    stronger host-level boundary.
    """

    try:
        before = os.lstat(path)
    except FileNotFoundError as exc:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} is missing"
        ) from exc
    except OSError as exc:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} cannot be inspected"
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} must be a regular non-symlink file"
        )

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} cannot be opened read-only"
        ) from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise RepositoryWriteChainStoreResolutionError(
                f"{label} descriptor is not a regular file"
            )
        if _identity(before) != _identity(opened):
            raise RepositoryWriteChainStoreResolutionError(
                f"{label} changed before descriptor admission"
            )
        if opened.st_size < 0 or opened.st_size > max_bytes:
            raise RepositoryWriteChainStoreResolutionError(
                f"{label} exceeds the bounded read ceiling"
            )
        if expected_size is not None and opened.st_size != expected_size:
            raise RepositoryWriteChainStoreResolutionError(
                f"{label} size contradicts retained evidence"
            )

        remaining = max_bytes + 1
        chunks: list[bytes] = []
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise RepositoryWriteChainStoreResolutionError(
                f"{label} exceeds the bounded read ceiling"
            )

        after_descriptor = os.fstat(fd)
        if _identity(opened) != _identity(after_descriptor):
            raise RepositoryWriteChainStoreResolutionError(
                f"{label} changed while being read"
            )
    finally:
        os.close(fd)

    try:
        after_path = os.lstat(path)
    except OSError as exc:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} disappeared after read"
        ) from exc
    if _identity(before) != _identity(after_path):
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} path identity changed after read"
        )
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} digest contradicts retained identity"
        )
    if expected_size is not None and len(data) != expected_size:
        raise RepositoryWriteChainStoreResolutionError(
            f"{label} byte count contradicts retained evidence"
        )
    return data


def _expected_store_inputs(
    artifact: RepositoryWriteChainArtifactEvidence,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                artifact.gate_report_v4_sha256,
                artifact.chain_result_sha256,
                artifact.inventory_sha256,
                artifact.classification_sha256,
                artifact.stage_digest_set_sha256,
                artifact.artifact_content_sha256,
            }
        )
    )


@dataclass(frozen=True)
class RepositoryWriteChainStoreResolutionReceipt(CanonicalContract):
    """Mechanical receipt for one exact locator-manifest/blob resolution."""

    CONTRACT_TYPE: ClassVar[str] = (
        "daedalus-repository-write-chain-store-resolution-receipt/1"
    )

    resolution_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v4_sha256: str
    artifact_evidence_sha256: str
    artifact_locator_sha256: str
    artifact_content_sha256: str
    chain_result_sha256: str
    byte_length: int
    evidence_authenticated: bool
    resolved_at: str
    checks: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "resolution_id",
                _identifier(self.resolution_id, "resolution_id"),
            )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            object.__setattr__(
                self,
                "source_tree_revision",
                _revision(self.source_tree_revision, "source_tree_revision"),
            )
            for field_name in (
                "gate_report_v4_sha256",
                "artifact_evidence_sha256",
                "artifact_locator_sha256",
                "artifact_content_sha256",
                "chain_result_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "byte_length",
                _non_negative_int(self.byte_length, "byte_length"),
            )
            if type(self.evidence_authenticated) is not bool:
                raise RepositoryWriteChainStoreResolutionError(
                    "evidence_authenticated must be a boolean"
                )
            object.__setattr__(
                self,
                "resolved_at",
                _utc_timestamp(self.resolved_at, "resolved_at"),
            )
            object.__setattr__(
                self,
                "checks",
                _sorted_strings(self.checks, "checks", identifiers=True),
            )
        except RepositoryWriteChainStoreResolutionError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution receipt is malformed"
            ) from exc
        if self.checks != _RESOLUTION_CHECKS:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution checks are not exact"
            )
        if self.byte_length > _MAX_ARTIFACT_BYTES:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution byte_length exceeds the admission ceiling"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution provenance must be exact ContractProvenance"
            )
        if self.provenance.origin != _RESOLUTION_ORIGIN:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution provenance origin is invalid"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution source revision contradicts provenance"
            )
        if self.provenance.created_at != self.resolved_at:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution time contradicts provenance"
            )
        if self.provenance.trace_id != self.resolution_id:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution trace_id must equal resolution_id"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v4_sha256,
                    self.artifact_evidence_sha256,
                    self.artifact_locator_sha256,
                    self.artifact_content_sha256,
                    self.chain_result_sha256,
                ),
                "repository-write chain store resolution receipt",
            )
        except ValueError as exc:
            raise RepositoryWriteChainStoreResolutionError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteChainStoreResolutionReceipt":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteChainStoreResolutionError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteChainStoreResolutionError(
                "store resolution receipt payload is malformed"
            ) from exc


def resolve_repository_write_chain_artifact(
    artifact: RepositoryWriteChainArtifactEvidence,
    store: ArtifactStore,
    *,
    primary_checkout: str | os.PathLike[str],
    resolution_id: str,
    resolved_at: str,
) -> tuple[bytes, RepositoryWriteChainStoreResolutionReceipt]:
    """Resolve one exact chain artifact from a checkout-disjoint ArtifactStore."""

    if type(artifact) is not RepositoryWriteChainArtifactEvidence:
        raise RepositoryWriteChainStoreResolutionError(
            "artifact must be exact RepositoryWriteChainArtifactEvidence"
        )
    root = _require_disjoint_store(store, Path(primary_checkout))
    locator_sha256 = _locator_sha256(artifact.locator)
    locator_path = store.locator_path(locator_sha256)
    _require_confined_parent(root, locator_path, "artifact locator")
    locator_bytes = _stable_read(
        locator_path,
        expected_sha256=locator_sha256,
        max_bytes=_MAX_LOCATOR_BYTES,
        expected_size=None,
        label="artifact locator",
    )

    try:
        loaded = store.load_locator(locator_sha256)
    except (ArtifactStoreError, TypeError, ValueError) as exc:
        raise RepositoryWriteChainStoreResolutionError(
            "artifact locator failed canonical ArtifactStore validation"
        ) from exc
    if loaded.manifest_bytes != locator_bytes:
        raise RepositoryWriteChainStoreResolutionError(
            "artifact locator changed between descriptor read and store validation"
        )
    if loaded.locator_uri != artifact.locator:
        raise RepositoryWriteChainStoreResolutionError(
            "artifact locator URI contradicts resolved locator identity"
        )
    if loaded.artifact_sha256 != artifact.artifact_content_sha256:
        raise RepositoryWriteChainStoreResolutionError(
            "resolved locator blob digest contradicts artifact evidence"
        )
    if loaded.byte_length > _MAX_ARTIFACT_BYTES:
        raise RepositoryWriteChainStoreResolutionError(
            "resolved artifact exceeds the admission ceiling"
        )

    manifest = loaded.to_dict()
    if manifest.get("media_type") != CHAIN_RESULT_MEDIA_TYPE:
        raise RepositoryWriteChainStoreResolutionError(
            "resolved locator media type is not repository-write chain-result JSON"
        )
    if manifest.get("metadata") != CHAIN_RESULT_STORE_METADATA:
        raise RepositoryWriteChainStoreResolutionError(
            "resolved locator metadata is not the exact chain-result subject"
        )
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        raise RepositoryWriteChainStoreResolutionError(
            "resolved locator provenance is malformed"
        )
    expected_provenance = {
        "origin": CHAIN_RESULT_STORE_ORIGIN,
        "source_revision": artifact.source_revision,
        "created_at": artifact.built_at,
        "input_digests": list(_expected_store_inputs(artifact)),
        "trace_id": artifact.artifact_id,
    }
    if provenance != expected_provenance:
        raise RepositoryWriteChainStoreResolutionError(
            "resolved locator provenance contradicts artifact evidence"
        )

    blob_path = loaded.blob_path
    _require_confined_parent(root, blob_path, "artifact blob")
    artifact_bytes = _stable_read(
        blob_path,
        expected_sha256=artifact.artifact_content_sha256,
        max_bytes=_MAX_ARTIFACT_BYTES,
        expected_size=loaded.byte_length,
        label="artifact blob",
    )
    # Re-read the locator after the blob read.  The locator is create-once by
    # contract; any detectable replacement during the admission interval makes
    # this resolution unusable.
    final_locator_bytes = _stable_read(
        locator_path,
        expected_sha256=locator_sha256,
        max_bytes=_MAX_LOCATOR_BYTES,
        expected_size=len(locator_bytes),
        label="artifact locator",
    )
    if final_locator_bytes != locator_bytes:
        raise RepositoryWriteChainStoreResolutionError(
            "artifact locator changed during blob admission"
        )

    provenance_receipt = ContractProvenance(
        origin=_RESOLUTION_ORIGIN,
        source_revision=artifact.source_revision,
        created_at=resolved_at,
        input_digests=tuple(
            sorted(
                {
                    artifact.gate_report_v4_sha256,
                    artifact.digest,
                    locator_sha256,
                    artifact.artifact_content_sha256,
                    artifact.chain_result_sha256,
                }
            )
        ),
        trace_id=resolution_id,
    )
    receipt = RepositoryWriteChainStoreResolutionReceipt(
        resolution_id=resolution_id,
        source_revision=artifact.source_revision,
        source_tree_revision=artifact.source_tree_revision,
        gate_report_v4_sha256=artifact.gate_report_v4_sha256,
        artifact_evidence_sha256=artifact.digest,
        artifact_locator_sha256=locator_sha256,
        artifact_content_sha256=artifact.artifact_content_sha256,
        chain_result_sha256=artifact.chain_result_sha256,
        byte_length=len(artifact_bytes),
        evidence_authenticated=artifact.evidence_authenticated,
        resolved_at=resolved_at,
        checks=_RESOLUTION_CHECKS,
        provenance=provenance_receipt,
    )
    return artifact_bytes, receipt


__all__ = [
    "CHAIN_RESULT_MEDIA_TYPE",
    "CHAIN_RESULT_STORE_METADATA",
    "CHAIN_RESULT_STORE_ORIGIN",
    "RepositoryWriteChainStoreResolutionError",
    "RepositoryWriteChainStoreResolutionReceipt",
    "resolve_repository_write_chain_artifact",
]

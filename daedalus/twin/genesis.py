"""Atomic Project Twin and bounded Genesis compiler contracts for Gate 2.

The contracts in this module do not invent a second graph authority. They bind
one source artifact, one compiled Forest, one Fourfold snapshot, one compiler
contract, and one evidence packet into a revision-exact manifest. A Genesis
receipt can only name that exact manifest and refuses replay across revisions or
compiler contracts.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.schemas import _revision, _sha256
from daedalus.spine.envelope import canonical_json, canonical_sha


class ProjectTwinContractError(ValueError):
    """Raised when a Project Twin or Genesis receipt is not mechanically exact."""


@dataclass(frozen=True)
class ProjectTwinManifest:
    repository_id: str
    source_revision: str
    source_artifact: ArtifactRef
    source_forest_sha256: str
    fourfold_snapshot_sha256: str
    compiler_contract_sha256: str
    evidence_packet_sha256: str

    def __post_init__(self) -> None:
        repository_id = str(self.repository_id).strip()
        if not repository_id:
            raise ProjectTwinContractError("repository_id must be non-empty")
        if not isinstance(self.source_artifact, ArtifactRef):
            raise ProjectTwinContractError("source_artifact must be an ArtifactRef")
        object.__setattr__(self, "repository_id", repository_id)
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        for field in (
            "source_forest_sha256",
            "fourfold_snapshot_sha256",
            "compiler_contract_sha256",
            "evidence_packet_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-project-twin-manifest/1",
            "repository_id": self.repository_id,
            "source_revision": self.source_revision,
            "source_artifact": self.source_artifact.to_dict(),
            "source_forest_sha256": self.source_forest_sha256,
            "fourfold_snapshot_sha256": self.fourfold_snapshot_sha256,
            "compiler_contract_sha256": self.compiler_contract_sha256,
            "evidence_packet_sha256": self.evidence_packet_sha256,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProjectTwinManifest":
        if payload.get("schema") != "daedalus-project-twin-manifest/1":
            raise ProjectTwinContractError("unsupported Project Twin manifest schema")
        source = payload.get("source_artifact")
        if not isinstance(source, Mapping):
            raise ProjectTwinContractError("source_artifact must be an object")
        return cls(
            repository_id=payload["repository_id"],
            source_revision=payload["source_revision"],
            source_artifact=ArtifactRef(
                sha256=source["sha256"], locator=source["locator"]
            ),
            source_forest_sha256=payload["source_forest_sha256"],
            fourfold_snapshot_sha256=payload["fourfold_snapshot_sha256"],
            compiler_contract_sha256=payload["compiler_contract_sha256"],
            evidence_packet_sha256=payload["evidence_packet_sha256"],
        )


@dataclass(frozen=True)
class GenesisCompileReceipt:
    manifest_sha256: str
    source_revision: str
    compiler_contract_sha256: str
    output_artifact: ArtifactRef
    deterministic: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "manifest_sha256", _sha256(self.manifest_sha256, "manifest_sha256")
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "compiler_contract_sha256",
            _sha256(self.compiler_contract_sha256, "compiler_contract_sha256"),
        )
        if not isinstance(self.output_artifact, ArtifactRef):
            raise ProjectTwinContractError("output_artifact must be an ArtifactRef")
        if self.deterministic is not True:
            raise ProjectTwinContractError("Genesis receipt must attest deterministic output")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-genesis-compile-receipt/1",
            "manifest_sha256": self.manifest_sha256,
            "source_revision": self.source_revision,
            "compiler_contract_sha256": self.compiler_contract_sha256,
            "output_artifact": self.output_artifact.to_dict(),
            "deterministic": self.deterministic,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GenesisCompileReceipt":
        if payload.get("schema") != "daedalus-genesis-compile-receipt/1":
            raise ProjectTwinContractError("unsupported Genesis receipt schema")
        output = payload.get("output_artifact")
        if not isinstance(output, Mapping):
            raise ProjectTwinContractError("output_artifact must be an object")
        return cls(
            manifest_sha256=payload["manifest_sha256"],
            source_revision=payload["source_revision"],
            compiler_contract_sha256=payload["compiler_contract_sha256"],
            output_artifact=ArtifactRef(
                sha256=output["sha256"], locator=output["locator"]
            ),
            deterministic=payload["deterministic"],
        )


def verify_genesis_receipt(
    manifest: ProjectTwinManifest,
    receipt: GenesisCompileReceipt,
) -> None:
    """Fail closed unless the receipt names the exact manifest and contract."""
    if not isinstance(manifest, ProjectTwinManifest):
        raise TypeError("manifest must be a ProjectTwinManifest")
    if not isinstance(receipt, GenesisCompileReceipt):
        raise TypeError("receipt must be a GenesisCompileReceipt")

    mismatches: list[str] = []
    if receipt.manifest_sha256 != manifest.digest:
        mismatches.append("manifest")
    if receipt.source_revision != manifest.source_revision:
        mismatches.append("source_revision")
    if receipt.compiler_contract_sha256 != manifest.compiler_contract_sha256:
        mismatches.append("compiler_contract")
    if mismatches:
        raise ProjectTwinContractError(
            "Genesis receipt mismatch: " + ", ".join(sorted(mismatches))
        )


class AtomicProjectTwinStore:
    """Persist one manifest/receipt pair atomically and verify it on every read.

    The store is intentionally append-only by manifest digest. Replaying the
    same bytes is idempotent; trying to reuse the digest path with different
    bytes or publish a receipt that does not bind the manifest fails closed.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        normalized = _sha256(digest, "manifest_sha256")
        return self.root / f"{normalized}.json"

    @staticmethod
    def _payload(
        manifest: ProjectTwinManifest,
        receipt: GenesisCompileReceipt,
    ) -> dict[str, Any]:
        verify_genesis_receipt(manifest, receipt)
        return {
            "schema": "daedalus-project-twin-record/1",
            "manifest": manifest.to_dict(),
            "manifest_sha256": manifest.digest,
            "receipt": receipt.to_dict(),
            "receipt_sha256": receipt.digest,
        }

    def publish(
        self,
        manifest: ProjectTwinManifest,
        receipt: GenesisCompileReceipt,
    ) -> ArtifactRef:
        payload = self._payload(manifest, receipt)
        raw = canonical_json(payload).encode("ascii")
        path = self._path(manifest.digest)

        if path.exists():
            if path.read_bytes() != raw:
                raise ProjectTwinContractError(
                    "Project Twin digest path already contains different bytes"
                )
            return ArtifactRef.from_sha256(canonical_sha(payload))

        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{manifest.digest}.", suffix=".tmp", dir=self.root
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

        return ArtifactRef.from_sha256(canonical_sha(payload))

    def load(
        self, manifest_sha256: str
    ) -> tuple[ProjectTwinManifest, GenesisCompileReceipt]:
        path = self._path(manifest_sha256)
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise ProjectTwinContractError("Project Twin record does not exist") from exc
        try:
            payload = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectTwinContractError("Project Twin record is not canonical JSON") from exc
        if not isinstance(payload, Mapping):
            raise ProjectTwinContractError("Project Twin record must be an object")
        if payload.get("schema") != "daedalus-project-twin-record/1":
            raise ProjectTwinContractError("unsupported Project Twin record schema")
        manifest_payload = payload.get("manifest")
        receipt_payload = payload.get("receipt")
        if not isinstance(manifest_payload, Mapping) or not isinstance(
            receipt_payload, Mapping
        ):
            raise ProjectTwinContractError("Project Twin record payload is incomplete")

        manifest = ProjectTwinManifest.from_dict(manifest_payload)
        receipt = GenesisCompileReceipt.from_dict(receipt_payload)
        if manifest.digest != _sha256(
            payload.get("manifest_sha256"), "manifest_sha256"
        ):
            raise ProjectTwinContractError("stored manifest digest does not match payload")
        if receipt.digest != _sha256(payload.get("receipt_sha256"), "receipt_sha256"):
            raise ProjectTwinContractError("stored receipt digest does not match payload")
        if manifest.digest != _sha256(manifest_sha256, "manifest_sha256"):
            raise ProjectTwinContractError("stored manifest does not match requested digest")
        if canonical_json(payload).encode("ascii") != raw:
            raise ProjectTwinContractError("Project Twin record is not canonically encoded")
        verify_genesis_receipt(manifest, receipt)
        return manifest, receipt


__all__ = [
    "AtomicProjectTwinStore",
    "GenesisCompileReceipt",
    "ProjectTwinContractError",
    "ProjectTwinManifest",
    "verify_genesis_receipt",
]

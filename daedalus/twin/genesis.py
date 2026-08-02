"""Atomic Project Twin and bounded Genesis compiler contracts for Gate 2.

The contracts in this module do not invent a second graph authority. They bind
one source artifact, one compiled Forest, one Fourfold snapshot, one compiler
contract, and one evidence packet into a revision-exact manifest. A Genesis
receipt can only name that exact manifest and refuses replay across revisions or
compiler contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.schemas import _revision, _sha256
from daedalus.spine.envelope import canonical_sha


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


__all__ = [
    "GenesisCompileReceipt",
    "ProjectTwinContractError",
    "ProjectTwinManifest",
    "verify_genesis_receipt",
]

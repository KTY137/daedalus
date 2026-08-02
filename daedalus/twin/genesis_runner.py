"""Execute one bounded, deterministic Genesis compilation for Gate 2.

The runner composes existing authorities rather than creating a parallel graph
or evidence model: the bounded reference compiler produces the Forest and
Fourfold snapshot, the kernel produces the EvidencePacket, and genesis.py binds
and persists the resulting Project Twin record.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.fourfold_evidence import assemble_fourfold_evidence_packet
from daedalus.schemas import EvidencePacket, ResourceUsage
from daedalus.spine.envelope import canonical_sha
from daedalus.twin.reference_compiler import (
    ReferenceCompileResult,
    compile_reference_project,
)

from .genesis import (
    AtomicProjectTwinStore,
    GenesisCompileReceipt,
    ProjectTwinContractError,
    ProjectTwinManifest,
    verify_genesis_receipt,
)


@dataclass(frozen=True)
class BoundedGenesisResult:
    """Complete identity set produced by one verified Genesis run."""

    compilation: ReferenceCompileResult
    evidence_packet: EvidencePacket
    manifest: ProjectTwinManifest
    receipt: GenesisCompileReceipt
    record_artifact: ArtifactRef

    @property
    def output_artifact(self) -> ArtifactRef:
        return self.receipt.output_artifact


def _output_artifact(
    *,
    repository_id: str,
    source_revision: str,
    compilation: ReferenceCompileResult,
    evidence_packet: EvidencePacket,
) -> ArtifactRef:
    payload = {
        "schema": "daedalus-bounded-genesis-output/1",
        "repository_id": repository_id,
        "source_revision": source_revision,
        "source_bundle_sha256": compilation.source_bundle_sha256,
        "source_manifest_sha256": compilation.manifest_sha256,
        "source_forest_sha256": compilation.forest.content_sha256,
        "fourfold_snapshot_sha256": compilation.snapshot.digest,
        "evidence_packet_sha256": evidence_packet.digest,
        "files": [
            {"path": path, "sha256": digest}
            for path, digest in compilation.file_sha256s
        ],
    }
    return ArtifactRef.from_sha256(canonical_sha(payload))


def run_bounded_genesis(
    source_root: str | Path,
    store_root: str | Path,
    *,
    repository_id: str,
    source_revision: str,
    compiler_contract_sha256: str,
    collected_at: str,
    manifest_name: str = "fourfold.json",
) -> BoundedGenesisResult:
    """Compile, evidence, persist, and read back one exact Project Twin.

    No approval is consumed and no candidate is promoted. Success requires a
    complete Fourfold snapshot, exact repository identity, deterministic output
    identity, an append-only store write, and equality after verified readback.
    """
    compilation = compile_reference_project(
        source_root,
        source_revision=source_revision,
        created_at=collected_at,
        manifest_name=manifest_name,
        trace_id="gate2-bounded-genesis",
    )
    if compilation.snapshot.repository_id != repository_id:
        raise ProjectTwinContractError(
            "compiled repository_id does not match requested repository_id"
        )
    if any(plane.status != "complete" for plane in compilation.snapshot.planes):
        raise ProjectTwinContractError("bounded Genesis requires four complete planes")

    source_artifact = ArtifactRef.from_sha256(compilation.source_bundle_sha256)
    evidence_packet = assemble_fourfold_evidence_packet(
        snapshot=compilation.snapshot,
        candidate_artifact_sha256=source_artifact.sha256,
        candidate_artifact_locator=source_artifact.locator,
        packet_id="gate2-genesis-evidence",
        mission_id="gate2-project-twin",
        attempt_id="gate2-bounded-genesis",
        attempt_contract_sha256=compiler_contract_sha256,
        policy_decision_sha256=canonical_sha(
            {"schema": "daedalus-gate2-policy/1", "promotion": "forbidden"}
        ),
        collected_at=collected_at,
        usage=ResourceUsage(wall_time_ms=1),
        trace_id="gate2-bounded-genesis",
    )
    manifest = ProjectTwinManifest(
        repository_id=repository_id,
        source_revision=source_revision,
        source_artifact=source_artifact,
        source_forest_sha256=compilation.forest.content_sha256,
        fourfold_snapshot_sha256=compilation.snapshot.digest,
        compiler_contract_sha256=compiler_contract_sha256,
        evidence_packet_sha256=evidence_packet.digest,
    )
    output_artifact = _output_artifact(
        repository_id=repository_id,
        source_revision=source_revision,
        compilation=compilation,
        evidence_packet=evidence_packet,
    )
    receipt = GenesisCompileReceipt(
        manifest_sha256=manifest.digest,
        source_revision=source_revision,
        compiler_contract_sha256=compiler_contract_sha256,
        output_artifact=output_artifact,
        deterministic=True,
    )
    verify_genesis_receipt(manifest, receipt)

    store = AtomicProjectTwinStore(store_root)
    record_artifact = store.publish(manifest, receipt)
    rebuilt_manifest, rebuilt_receipt = store.load(manifest.digest)
    if rebuilt_manifest != manifest or rebuilt_receipt != receipt:
        raise ProjectTwinContractError("Project Twin readback differs from published record")

    return BoundedGenesisResult(
        compilation=compilation,
        evidence_packet=evidence_packet,
        manifest=manifest,
        receipt=receipt,
        record_artifact=record_artifact,
    )


__all__ = ["BoundedGenesisResult", "run_bounded_genesis"]

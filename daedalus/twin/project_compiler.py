"""Build one real, revision-bound Project Twin from the bounded reference compiler.

This module is an integration boundary, not a second compiler. It composes the
existing reference compiler, canonical Fourfold evidence projection, Project
Twin manifest, Genesis receipt, and append-only store. Every returned digest is
rechecked before publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.fourfold_evidence import (
    FourfoldEvidenceExpectation,
    assemble_fourfold_evidence_packet,
    verify_fourfold_evidence_packet,
)
from daedalus.schemas import EvidencePacket
from daedalus.spine.envelope import canonical_sha

from .genesis import (
    AtomicProjectTwinStore,
    GenesisCompileReceipt,
    ProjectTwinManifest,
    verify_genesis_receipt,
)
from .reference_compiler import ReferenceCompileResult, compile_reference_project


REFERENCE_PROJECT_TWIN_COMPILER = "daedalus.reference-project-twin-compiler/1"


@dataclass(frozen=True)
class ReferenceProjectTwinBuild:
    compiled: ReferenceCompileResult
    evidence_packet: EvidencePacket
    manifest: ProjectTwinManifest
    receipt: GenesisCompileReceipt
    record_artifact: ArtifactRef


def compile_reference_project_twin(
    root: str | Path,
    *,
    store: AtomicProjectTwinStore,
    source_revision: str,
    created_at: str,
    packet_id: str,
    mission_id: str,
    attempt_id: str,
    attempt_contract_sha256: str,
    policy_decision_sha256: str,
    trace_id: str | None = None,
) -> ReferenceProjectTwinBuild:
    """Compile, bind, verify, and atomically publish one reference Project Twin."""

    if not isinstance(store, AtomicProjectTwinStore):
        raise TypeError("store must be an AtomicProjectTwinStore")

    compiled = compile_reference_project(
        root,
        source_revision=source_revision,
        created_at=created_at,
        trace_id=trace_id,
    )
    source_artifact = ArtifactRef.from_sha256(compiled.source_bundle_sha256)
    evidence_packet = assemble_fourfold_evidence_packet(
        snapshot=compiled.snapshot,
        candidate_artifact_sha256=source_artifact.sha256,
        candidate_artifact_locator=source_artifact.locator,
        packet_id=packet_id,
        mission_id=mission_id,
        attempt_id=attempt_id,
        attempt_contract_sha256=attempt_contract_sha256,
        policy_decision_sha256=policy_decision_sha256,
        collected_at=created_at,
        trace_id=trace_id,
    )
    expectation = FourfoldEvidenceExpectation(
        candidate_artifact_sha256=source_artifact.sha256,
        candidate_artifact_locator=source_artifact.locator,
        snapshot_sha256=compiled.snapshot.digest,
        source_revision=compiled.snapshot.source_revision,
    )
    verify_fourfold_evidence_packet(
        evidence_packet,
        snapshot=compiled.snapshot,
        expectation=expectation,
    )

    compiler_contract_sha256 = canonical_sha(
        {
            "schema": REFERENCE_PROJECT_TWIN_COMPILER,
            "reference_manifest_sha256": compiled.manifest_sha256,
            "source_revision": compiled.snapshot.source_revision,
        }
    )
    manifest = ProjectTwinManifest(
        repository_id=compiled.snapshot.repository_id,
        source_revision=compiled.snapshot.source_revision,
        source_artifact=source_artifact,
        source_forest_sha256=compiled.forest.content_sha256,
        fourfold_snapshot_sha256=compiled.snapshot.digest,
        compiler_contract_sha256=compiler_contract_sha256,
        evidence_packet_sha256=evidence_packet.digest,
    )
    receipt = GenesisCompileReceipt(
        manifest_sha256=manifest.digest,
        source_revision=manifest.source_revision,
        compiler_contract_sha256=manifest.compiler_contract_sha256,
        output_artifact=ArtifactRef.from_sha256(compiled.snapshot.digest),
        deterministic=True,
    )
    verify_genesis_receipt(manifest, receipt)
    record_artifact = store.publish(manifest, receipt)
    loaded_manifest, loaded_receipt = store.load(manifest.digest)
    if loaded_manifest != manifest or loaded_receipt != receipt:
        raise RuntimeError("published Project Twin did not round-trip exactly")

    return ReferenceProjectTwinBuild(
        compiled=compiled,
        evidence_packet=evidence_packet,
        manifest=manifest,
        receipt=receipt,
        record_artifact=record_artifact,
    )


__all__ = [
    "REFERENCE_PROJECT_TWIN_COMPILER",
    "ReferenceProjectTwinBuild",
    "compile_reference_project_twin",
]

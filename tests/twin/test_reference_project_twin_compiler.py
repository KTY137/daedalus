from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from daedalus.twin.genesis import AtomicProjectTwinStore, ProjectTwinContractError
from daedalus.twin.project_compiler import compile_reference_project_twin


FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"
REVISION = "7" * 40
CREATED_AT = "2026-08-02T04:30:00Z"
ATTEMPT_SHA = "8" * 64
POLICY_SHA = "9" * 64


def _build(root: Path, store: AtomicProjectTwinStore, *, revision: str = REVISION):
    return compile_reference_project_twin(
        root,
        store=store,
        source_revision=revision,
        created_at=CREATED_AT,
        packet_id="packet-reference-project-twin",
        mission_id="mission-reference-project-twin",
        attempt_id="attempt-reference-project-twin",
        attempt_contract_sha256=ATTEMPT_SHA,
        policy_decision_sha256=POLICY_SHA,
        trace_id="trace-reference-project-twin",
    )


def test_real_reference_project_builds_and_publishes_atomic_twin(tmp_path: Path) -> None:
    store = AtomicProjectTwinStore(tmp_path / "twins")
    result = _build(FIXTURE, store)

    assert tuple(result.compiled.snapshot.plane_map) == (
        "code",
        "type",
        "data",
        "knowledge",
    )
    assert all(plane.status == "complete" for plane in result.compiled.snapshot.planes)
    assert result.manifest.source_artifact.sha256 == result.compiled.source_bundle_sha256
    assert result.manifest.source_forest_sha256 == result.compiled.forest.content_sha256
    assert result.manifest.fourfold_snapshot_sha256 == result.compiled.snapshot.digest
    assert result.manifest.evidence_packet_sha256 == result.evidence_packet.digest
    assert result.receipt.output_artifact.sha256 == result.compiled.snapshot.digest
    assert store.load(result.manifest.digest) == (result.manifest, result.receipt)


def test_identical_rebuild_is_digest_stable_and_idempotent(tmp_path: Path) -> None:
    store = AtomicProjectTwinStore(tmp_path / "twins")
    first = _build(FIXTURE, store)
    second = _build(FIXTURE, store)

    assert second.compiled.snapshot.digest == first.compiled.snapshot.digest
    assert second.evidence_packet.digest == first.evidence_packet.digest
    assert second.manifest.digest == first.manifest.digest
    assert second.receipt.digest == first.receipt.digest
    assert second.record_artifact == first.record_artifact
    assert len(tuple((tmp_path / "twins").glob("*.json"))) == 1


def test_source_mutation_changes_source_snapshot_evidence_and_manifest(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(FIXTURE, candidate)
    store = AtomicProjectTwinStore(tmp_path / "twins")
    before = _build(candidate, store)

    search = candidate / "src" / "knowledge_hub" / "search.py"
    search.write_text(search.read_text(encoding="utf-8") + "\n# bounded mutation\n", encoding="utf-8")
    after = _build(candidate, store)

    assert after.compiled.source_bundle_sha256 != before.compiled.source_bundle_sha256
    assert after.compiled.snapshot.digest != before.compiled.snapshot.digest
    assert after.evidence_packet.digest != before.evidence_packet.digest
    assert after.manifest.digest != before.manifest.digest


def test_revision_replay_changes_all_revision_bound_identity(tmp_path: Path) -> None:
    store = AtomicProjectTwinStore(tmp_path / "twins")
    first = _build(FIXTURE, store, revision=REVISION)
    second = _build(FIXTURE, store, revision="6" * 40)

    assert first.compiled.source_bundle_sha256 == second.compiled.source_bundle_sha256
    assert first.compiled.snapshot.digest != second.compiled.snapshot.digest
    assert first.evidence_packet.digest != second.evidence_packet.digest
    assert first.manifest.digest != second.manifest.digest
    assert first.receipt.digest != second.receipt.digest


def test_store_tampering_is_refused_after_real_compilation(tmp_path: Path) -> None:
    store = AtomicProjectTwinStore(tmp_path / "twins")
    result = _build(FIXTURE, store)
    record = tmp_path / "twins" / f"{result.manifest.digest}.json"
    raw = record.read_text(encoding="ascii")
    record.write_text(raw.replace(result.compiled.snapshot.digest, "a" * 64, 1), encoding="ascii")

    with pytest.raises(ProjectTwinContractError):
        store.load(result.manifest.digest)


def test_non_store_argument_is_refused_before_compilation(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="AtomicProjectTwinStore"):
        compile_reference_project_twin(
            FIXTURE,
            store=tmp_path,  # type: ignore[arg-type]
            source_revision=REVISION,
            created_at=CREATED_AT,
            packet_id="packet-reference-project-twin",
            mission_id="mission-reference-project-twin",
            attempt_id="attempt-reference-project-twin",
            attempt_contract_sha256=ATTEMPT_SHA,
            policy_decision_sha256=POLICY_SHA,
        )

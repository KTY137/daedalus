from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from daedalus.twin.genesis import AtomicProjectTwinStore, ProjectTwinContractError
from daedalus.twin.genesis_runner import run_bounded_genesis

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ignition" / "voltage"
REVISION = "a" * 40
OTHER_REVISION = "b" * 40
COMPILER = "4" * 64
NOW = "2026-08-02T05:00:00Z"
REPOSITORY = "daedalus/ignition-field-fixture"


def _run(
    tmp_path: Path,
    *,
    source: Path = FIXTURE,
    revision: str = REVISION,
    name: str = "store",
):
    return run_bounded_genesis(
        source,
        tmp_path / name,
        repository_id=REPOSITORY,
        source_revision=revision,
        compiler_contract_sha256=COMPILER,
        collected_at=NOW,
    )


def test_bounded_genesis_compiles_real_fourfold_and_reads_back(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.compilation.snapshot.repository_id == REPOSITORY
    assert {plane.plane for plane in result.compilation.snapshot.planes} == {
        "code",
        "type",
        "data",
        "knowledge",
    }
    assert all(plane.status == "complete" for plane in result.compilation.snapshot.planes)
    assert result.manifest.source_artifact.sha256 == result.compilation.source_bundle_sha256
    assert result.manifest.source_forest_sha256 == result.compilation.forest.content_sha256
    assert result.manifest.fourfold_snapshot_sha256 == result.compilation.snapshot.digest
    assert result.manifest.evidence_packet_sha256 == result.evidence_packet.digest
    assert result.receipt.manifest_sha256 == result.manifest.digest
    assert result.receipt.output_artifact == result.output_artifact

    manifest, receipt = AtomicProjectTwinStore(tmp_path / "store").load(
        result.manifest.digest
    )
    assert manifest == result.manifest
    assert receipt == result.receipt


def test_bounded_genesis_replay_is_digest_identical(tmp_path: Path) -> None:
    first = _run(tmp_path, name="first")
    second = _run(tmp_path, name="second")

    assert first.compilation.source_bundle_sha256 == second.compilation.source_bundle_sha256
    assert first.compilation.forest.content_sha256 == second.compilation.forest.content_sha256
    assert first.compilation.snapshot.digest == second.compilation.snapshot.digest
    assert first.evidence_packet.digest == second.evidence_packet.digest
    assert first.manifest.digest == second.manifest.digest
    assert first.receipt.digest == second.receipt.digest
    assert first.output_artifact == second.output_artifact
    assert first.record_artifact == second.record_artifact


def test_bounded_genesis_revision_changes_revision_bound_identity(tmp_path: Path) -> None:
    first = _run(tmp_path, name="first")
    second = _run(tmp_path, revision=OTHER_REVISION, name="second")

    assert first.compilation.source_bundle_sha256 == second.compilation.source_bundle_sha256
    assert first.compilation.snapshot.digest != second.compilation.snapshot.digest
    assert first.evidence_packet.digest != second.evidence_packet.digest
    assert first.manifest.digest != second.manifest.digest
    assert first.receipt.digest != second.receipt.digest
    assert first.output_artifact != second.output_artifact


def test_bounded_genesis_source_drift_changes_content_identity(tmp_path: Path) -> None:
    changed = tmp_path / "changed-source"
    shutil.copytree(FIXTURE, changed)
    events = changed / "data" / "events.csv"
    events.write_text("id,voltage\n1,126.0\n", encoding="utf-8")

    first = _run(tmp_path, name="first")
    second = _run(tmp_path, source=changed, name="second")

    assert first.compilation.source_bundle_sha256 != second.compilation.source_bundle_sha256
    assert first.compilation.forest.content_sha256 != second.compilation.forest.content_sha256
    assert first.compilation.snapshot.digest != second.compilation.snapshot.digest
    assert first.manifest.digest != second.manifest.digest
    assert first.output_artifact != second.output_artifact


def test_bounded_genesis_refuses_repository_substitution(tmp_path: Path) -> None:
    with pytest.raises(ProjectTwinContractError, match="repository_id"):
        run_bounded_genesis(
            FIXTURE,
            tmp_path / "store",
            repository_id="attacker/repackaged",
            source_revision=REVISION,
            compiler_contract_sha256=COMPILER,
            collected_at=NOW,
        )
    assert not (tmp_path / "store").exists()

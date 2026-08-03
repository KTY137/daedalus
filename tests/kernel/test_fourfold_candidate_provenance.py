from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from daedalus.kernel.fourfold_evidence import (
    FourfoldEvidenceMismatch,
    assemble_fourfold_evidence_packet,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import FourfoldSnapshot, compile_reference_project

REVISION = "b" * 40
NOW = "2026-08-03T16:00:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"
ATTEMPT_SHA = canonical_sha({"attempt": "g0-rcp-04a-candidate-binding"})
POLICY_SHA = canonical_sha({"policy": "gate0-read-only"})


def _compile(root: Path):
    return compile_reference_project(
        root,
        source_revision=REVISION,
        created_at=NOW,
        trace_id="g0-rcp-04a-candidate-binding",
    )


def _assemble(snapshot: FourfoldSnapshot, candidate_sha256: str):
    return assemble_fourfold_evidence_packet(
        snapshot=snapshot,
        candidate_artifact_sha256=candidate_sha256,
        candidate_artifact_locator=f"artifact-locator:sha256:{candidate_sha256}",
        packet_id="candidate-binding-evidence",
        mission_id="g0-rcp-04a",
        attempt_id="candidate-binding-attempt",
        attempt_contract_sha256=ATTEMPT_SHA,
        policy_decision_sha256=POLICY_SHA,
        collected_at=NOW,
    )


def test_snapshot_cannot_be_repackaged_with_another_candidate_bundle(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"
    shutil.copytree(FIXTURE, root)
    before = _compile(root)

    source = root / "src" / "knowledge_hub" / "search.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# different candidate bundle\n",
        encoding="utf-8",
    )
    after = _compile(root)

    assert before.source_bundle_sha256 != after.source_bundle_sha256
    assert after.source_bundle_sha256 not in before.snapshot.provenance.input_digests
    with pytest.raises(FourfoldEvidenceMismatch, match="snapshot provenance.*candidate"):
        _assemble(before.snapshot, after.source_bundle_sha256)


def test_structurally_valid_snapshot_without_candidate_provenance_is_refused() -> None:
    result = _compile(FIXTURE)
    snapshot = result.snapshot
    unbound = FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=snapshot.source_forest_sha256,
        planes=snapshot.planes,
        bindings=snapshot.bindings,
        provenance=ContractProvenance(
            origin="tests.unbound-fourfold-snapshot",
            source_revision=snapshot.source_revision,
            created_at=NOW,
            input_digests=tuple(
                {
                    snapshot.source_forest_sha256,
                    *(plane.digest for plane in snapshot.planes),
                    *(binding.digest for binding in snapshot.bindings),
                }
            ),
            trace_id="g0-rcp-04a-unbound",
        ),
    )

    assert result.source_bundle_sha256 not in unbound.provenance.input_digests
    with pytest.raises(FourfoldEvidenceMismatch, match="snapshot provenance.*candidate"):
        _assemble(unbound, result.source_bundle_sha256)

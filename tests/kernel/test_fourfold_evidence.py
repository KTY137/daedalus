# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from daedalus.kernel.fourfold_evidence import (
    FOURFOLD_EVALUATOR,
    FourfoldEvidenceExpectation,
    FourfoldEvidenceMismatch,
    assemble_fourfold_evidence_packet,
    verify_fourfold_evidence_packet,
)
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    ResourceUsage,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import compile_reference_project

REVISION = "b" * 40
OTHER_REVISION = "c" * 40
NOW = "2026-08-01T21:30:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"
ATTEMPT_SHA = canonical_sha({"attempt": "g0-rcp-04a"})
POLICY_SHA = canonical_sha({"policy": "gate0-read-only"})


def _compile(root: Path, revision: str = REVISION):
    return compile_reference_project(
        root,
        source_revision=revision,
        created_at=NOW,
        trace_id="g0-rcp-04a",
    )


def _expectation(result) -> FourfoldEvidenceExpectation:
    return FourfoldEvidenceExpectation(
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"
        ),
        snapshot_sha256=result.snapshot.digest,
        source_revision=result.snapshot.source_revision,
    )


def _packet(result) -> EvidencePacket:
    return assemble_fourfold_evidence_packet(
        snapshot=result.snapshot,
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"
        ),
        packet_id="g0-rcp-04a-evidence",
        mission_id="g0-rcp-04a",
        attempt_id="g0-rcp-04a-attempt",
        attempt_contract_sha256=ATTEMPT_SHA,
        policy_decision_sha256=POLICY_SHA,
        collected_at=NOW,
        usage=ResourceUsage(wall_time_ms=1),
        trace_id="g0-rcp-04a",
    )


def test_real_wiki_snapshot_is_bound_to_candidate_and_revision() -> None:
    result = _compile(FIXTURE)
    packet = _packet(result)
    item = next(
        item for item in packet.items if item.evaluator == FOURFOLD_EVALUATOR
    )

    assert len(result.snapshot.bindings) == 31
    assert packet.source_revision == REVISION
    assert packet.subject_sha256 == result.source_bundle_sha256
    assert packet.candidate_artifact_sha256 == result.source_bundle_sha256
    assert item.output_sha256 == result.snapshot.digest
    assert item.details["fourfold_snapshot_sha256"] == result.snapshot.digest
    assert item.details["source_forest_sha256"] == result.forest.content_sha256
    verify_fourfold_evidence_packet(
        packet,
        snapshot=result.snapshot,
        expectation=_expectation(result),
    )


def test_source_mutation_changes_candidate_and_snapshot_and_old_packet_refuses(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"
    shutil.copytree(FIXTURE, root)
    before = _compile(root)
    before_packet = _packet(before)

    source = root / "src" / "knowledge_hub" / "search.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# gate-0 source mutation\n",
        encoding="utf-8",
    )
    after = _compile(root)

    assert after.source_bundle_sha256 != before.source_bundle_sha256
    assert after.snapshot.digest != before.snapshot.digest
    with pytest.raises(FourfoldEvidenceMismatch, match="candidate|snapshot"):
        verify_fourfold_evidence_packet(
            before_packet,
            snapshot=after.snapshot,
            expectation=_expectation(after),
        )


def test_snapshot_from_another_revision_is_refused() -> None:
    first = _compile(FIXTURE, REVISION)
    second = _compile(FIXTURE, OTHER_REVISION)

    with pytest.raises(FourfoldEvidenceMismatch, match="revision|snapshot"):
        verify_fourfold_evidence_packet(
            _packet(first),
            snapshot=second.snapshot,
            expectation=_expectation(second),
        )


def test_missing_or_repackaged_fourfold_evidence_is_refused() -> None:
    result = _compile(FIXTURE)
    packet = _packet(result)
    expectation = _expectation(result)

    unrelated = EvidenceItem(
        evidence_id="other:evidence",
        evaluator="other-evaluator",
        assurance="deterministic",
        verdict="passed",
        output_sha256="d" * 64,
        evidence_locator=f"artifact-locator:sha256:{'d' * 64}",
        collected_at=NOW,
        provenance=ContractProvenance(
            origin="test.other",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=("d" * 64,),
        ),
        details={"kind": "not-fourfold"},
    )
    tampered = EvidencePacket(
        packet_id=packet.packet_id,
        mission_id=packet.mission_id,
        attempt_id=packet.attempt_id,
        source_revision=packet.source_revision,
        attempt_contract_sha256=packet.attempt_contract_sha256,
        subject_sha256=packet.subject_sha256,
        evaluation_status="passed",
        items=(unrelated,),
        policy_decision_sha256=packet.policy_decision_sha256,
        usage=packet.usage,
        provenance=ContractProvenance(
            origin="test.repackaged",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=tuple(
                sorted(
                    {
                        packet.attempt_contract_sha256,
                        packet.subject_sha256,
                        packet.policy_decision_sha256,
                        unrelated.output_sha256,
                        result.source_bundle_sha256,
                    }
                )
            ),
        ),
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"
        ),
    )

    with pytest.raises(FourfoldEvidenceMismatch, match="evidence_count"):
        verify_fourfold_evidence_packet(
            tampered,
            snapshot=result.snapshot,
            expectation=expectation,
        )

    wrong_snapshot = "e" * 64
    manipulated_item = EvidenceItem(
        evidence_id="g0-rcp-04a-attempt:fourfold",
        evaluator=FOURFOLD_EVALUATOR,
        assurance="deterministic",
        verdict="passed",
        output_sha256=wrong_snapshot,
        evidence_locator=f"artifact-locator:sha256:{wrong_snapshot}",
        collected_at=NOW,
        provenance=ContractProvenance(
            origin="test.manipulated-fourfold",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(
                result.source_bundle_sha256,
                result.snapshot.source_forest_sha256,
                wrong_snapshot,
            ),
        ),
        details={
            "schema": "daedalus-fourfold-evidence/1",
            "repository_id": result.snapshot.repository_id,
            "source_revision": REVISION,
            "candidate_artifact_sha256": result.source_bundle_sha256,
            "source_forest_sha256": result.snapshot.source_forest_sha256,
            "fourfold_snapshot_sha256": wrong_snapshot,
        },
    )
    manipulated_packet = EvidencePacket(
        packet_id=packet.packet_id,
        mission_id=packet.mission_id,
        attempt_id=packet.attempt_id,
        source_revision=packet.source_revision,
        attempt_contract_sha256=packet.attempt_contract_sha256,
        subject_sha256=packet.subject_sha256,
        evaluation_status="passed",
        items=(manipulated_item,),
        policy_decision_sha256=packet.policy_decision_sha256,
        usage=packet.usage,
        provenance=ContractProvenance(
            origin="test.manipulated-fourfold-packet",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=tuple(
                sorted(
                    {
                        packet.attempt_contract_sha256,
                        packet.subject_sha256,
                        packet.policy_decision_sha256,
                        manipulated_item.output_sha256,
                    }
                )
            ),
        ),
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"
        ),
    )
    with pytest.raises(FourfoldEvidenceMismatch, match="snapshot"):
        verify_fourfold_evidence_packet(
            manipulated_packet,
            snapshot=result.snapshot,
            expectation=expectation,
        )


def test_expectation_rejects_candidate_locator_repackaging() -> None:
    result = _compile(FIXTURE)
    with pytest.raises(FourfoldEvidenceMismatch, match="locator"):
        FourfoldEvidenceExpectation(
            candidate_artifact_sha256=result.source_bundle_sha256,
            candidate_artifact_locator=f"artifact-locator:sha256:{'e' * 64}",
            snapshot_sha256=result.snapshot.digest,
            source_revision=REVISION,
        )

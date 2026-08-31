from __future__ import annotations

from pathlib import Path

import daedalus.kernel.fourfold_evidence as fourfold_evidence
from daedalus.ignition import run_voltage_ignition
from daedalus.spine.envelope import canonical_sha
from daedalus.twin.semiring import verified_cell_evidence
from daedalus.twin.two_category import (
    BoundaryMap,
    OpenFourfoldComponent,
    Transformation2Cell,
    TypedBoundary,
    VerificationStatus,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ignition" / "voltage"
BASE = "1" * 40
CANDIDATE = "2" * 40
FOREIGN = "3" * 40
NOW = "2026-08-02T00:00:00Z"


def _component(*, repository_id: str, revision: str, digest: str) -> OpenFourfoldComponent:
    boundary = TypedBoundary(())
    return OpenFourfoldComponent.atomic(
        repository_id=repository_id,
        source_revision=revision,
        left=boundary,
        right=boundary,
        component_sha256=digest,
    )


def test_probe_verified_cell_evidence_is_not_subject_bound(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Falsification probe: a real packet digest can be replayed onto a foreign cell.

    ``verified_cell_evidence`` currently trusts the caller-asserted
    ``EVALUATOR_VERIFIED`` status and treats the cell's rewrite/observer digest set as
    the complete provenance term. The 2-cell constructor does not resolve those
    receipt digests back to the exact source/target subject. This probe uses the real
    Gate-1 voltage ignition EvidencePacket, then reuses that exact canonical packet
    digest on a different target component. If both projections are equal, the helper
    is derivational provenance only and must not be retained as a verifier or
    assurance-quality observer without an independent subject-binding check.
    """

    monkeypatch.setattr(
        fourfold_evidence,
        "DEFAULT_EVIDENCE_STORE_ROOT",
        tmp_path / "evidence-store",
    )
    result = run_voltage_ignition(
        FIXTURE,
        tmp_path / "candidate",
        base_revision=BASE,
        candidate_revision=CANDIDATE,
        collected_at=NOW,
    )
    assert result.evidence_packet.evaluation_status == "passed"
    assert (
        result.evidence_packet.candidate_artifact_sha256
        == result.candidate_source_bundle_sha256
    )

    receipts = (result.evidence_packet.digest,)

    boundary = TypedBoundary(())
    source = _component(
        repository_id=result.base_snapshot.repository_id,
        revision=result.base_snapshot.source_revision,
        digest=result.base_snapshot.digest,
    )
    target = _component(
        repository_id=result.candidate_snapshot.repository_id,
        revision=result.candidate_snapshot.source_revision,
        digest=result.candidate_snapshot.digest,
    )
    foreign_target = _component(
        repository_id=result.candidate_snapshot.repository_id,
        revision=FOREIGN,
        digest=canonical_sha({"foreign": "post-compile-target"}),
    )

    valid = Transformation2Cell(
        source=source,
        target=target,
        left_map=BoundaryMap.identity(boundary),
        right_map=BoundaryMap.identity(boundary),
        rewrite_sha256s=(result.graph_delta.digest,),
        observer_receipts=receipts,
        status=VerificationStatus.EVALUATOR_VERIFIED,
    )
    replayed = Transformation2Cell(
        source=source,
        target=foreign_target,
        left_map=BoundaryMap.identity(boundary),
        right_map=BoundaryMap.identity(boundary),
        rewrite_sha256s=(result.graph_delta.digest,),
        observer_receipts=receipts,
        status=VerificationStatus.EVALUATOR_VERIFIED,
    )

    assert valid.target != replayed.target
    assert valid.digest != replayed.digest
    assert verified_cell_evidence(valid) == verified_cell_evidence(replayed)

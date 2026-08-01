from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.approvals import (
    ApprovalBindingMismatch,
    ApprovalExpectation,
    issue_owner_approval,
    verify_owner_approval,
)
from daedalus.kernel.fourfold_evidence import assemble_fourfold_evidence_packet
from daedalus.schemas import ContractProvenance, ResourceUsage
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import compile_reference_project

REVISION = "b" * 40
TARGET_HEAD = "a" * 40
MOVED_TARGET_HEAD = "d" * 40
NOW = datetime(2026, 8, 1, 21, 30, tzinfo=timezone.utc)
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"
SECRET = b"fourfold-owner-secret-material-at-least-thirty-two-bytes"
ATTEMPT_SHA = canonical_sha({"attempt": "g0-rcp-04a"})
POLICY_SHA = canonical_sha({"policy": "gate0-read-only"})
NOMINATION_SHA = canonical_sha({"nomination": "g0-rcp-04a"})


def _compile(root: Path):
    return compile_reference_project(
        root,
        source_revision=REVISION,
        created_at=NOW.isoformat(),
        trace_id="g0-rcp-04a-approval",
    )


def _packet(result):
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
        collected_at=NOW.isoformat(),
        usage=ResourceUsage(wall_time_ms=1),
        trace_id="g0-rcp-04a-approval",
    )


def _approval(result, packet):
    return issue_owner_approval(
        approval_id="g0-rcp-04a-approval",
        owner_id="KTY137",
        key_id="owner-key-1",
        operation="promote-candidate",
        nomination_receipt_sha256=NOMINATION_SHA,
        candidate_artifact_sha256=result.source_bundle_sha256,
        evidence_packet_sha256=packet.digest,
        base_revision=REVISION,
        target_ref="experimental",
        expected_target_revision=TARGET_HEAD,
        nonce="g0-rcp-04a-nonce",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        provenance=ContractProvenance(
            origin="tests.fourfold-approval-integration",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(
                NOMINATION_SHA,
                result.source_bundle_sha256,
                packet.digest,
            ),
            trace_id="g0-rcp-04a-approval",
        ),
        secret=SECRET,
    )


def _expectation(result, packet, *, target_head: str = TARGET_HEAD):
    return ApprovalExpectation(
        operation="promote-candidate",
        nomination_receipt_sha256=NOMINATION_SHA,
        candidate_artifact_sha256=result.source_bundle_sha256,
        evidence_packet_sha256=packet.digest,
        base_revision=REVISION,
        target_ref="experimental",
        current_target_revision=target_head,
    )


def test_real_fourfold_evidence_is_accepted_only_for_exact_candidate_and_head(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"
    shutil.copytree(FIXTURE, root)
    before = _compile(root)
    before_packet = _packet(before)
    approval = _approval(before, before_packet)

    verified = verify_owner_approval(
        approval,
        keyring={("KTY137", "owner-key-1"): SECRET},
        expectation=_expectation(before, before_packet),
        now=NOW + timedelta(seconds=1),
    )
    assert verified.approval_sha256 == approval.digest
    assert approval.candidate_artifact_sha256 == before.source_bundle_sha256
    assert approval.evidence_packet_sha256 == before_packet.digest
    assert before_packet.items[0].output_sha256 == before.snapshot.digest

    source = root / "src" / "knowledge_hub" / "search.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# changed candidate\n",
        encoding="utf-8",
    )
    after = _compile(root)
    after_packet = _packet(after)
    assert after.source_bundle_sha256 != before.source_bundle_sha256
    assert after.snapshot.digest != before.snapshot.digest
    assert after_packet.digest != before_packet.digest

    with pytest.raises(ApprovalBindingMismatch, match="candidate_artifact_sha256"):
        verify_owner_approval(
            approval,
            keyring={("KTY137", "owner-key-1"): SECRET},
            expectation=_expectation(after, after_packet),
            now=NOW + timedelta(seconds=1),
        )

    # This is the live Target-HEAD re-check required immediately before any
    # later promotion mutation. No promotion is performed by this test.
    with pytest.raises(ApprovalBindingMismatch, match="expected_target_revision"):
        verify_owner_approval(
            approval,
            keyring={("KTY137", "owner-key-1"): SECRET},
            expectation=_expectation(
                before,
                before_packet,
                target_head=MOVED_TARGET_HEAD,
            ),
            now=NOW + timedelta(seconds=1),
        )

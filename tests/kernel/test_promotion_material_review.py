from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone

import pytest

import daedalus.kairos.gated_writes as gated_writes
from daedalus.kairos.gated_writes import GatedCandidate
from daedalus.kernel.promotion import (
    PromotionAuthorizationError,
    candidate_batch_sha256,
)
from daedalus.spine.attempt import (
    AttemptResult,
    GateResult,
    PatchArtifact,
    STATE_CLEAN,
)

NOW = datetime(2026, 8, 3, 20, 30, tzinfo=timezone.utc).isoformat()
REVISION = "a" * 40


def _candidate() -> GatedCandidate:
    diff = b"diff --git a/x b/x\n+review\n"
    artifact = PatchArtifact(
        task_id="task-review",
        branch="candidate-review",
        base_revision=REVISION,
        diff_bytes=diff,
        diff_sha256=hashlib.sha256(diff).hexdigest(),
        changed_paths=("x",),
        created_ts=NOW,
    )
    result = AttemptResult(
        state=STATE_CLEAN,
        task_id=artifact.task_id,
        started_ts=NOW,
        finished_ts=NOW,
        duration_s=0.1,
        effect_key="effect-review",
        branch=artifact.branch,
        base_revision=REVISION,
        artifact=artifact,
        gates=GateResult(passed=True, name="review-gate"),
    )
    return GatedCandidate(assignment=None, spec=None, result=result)


def _public_refusal(candidates, *, repo_root="."):
    return gated_writes.promote_candidates(
        repo_root,
        candidates,
        project=None,
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref="experimental",
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"x" * 32},
        ledger_path="unused.sqlite3",
    )


def test_noncanonical_declared_digest_is_a_promotion_refusal() -> None:
    candidate = _candidate()
    artifact = replace(candidate.result.artifact, diff_sha256="é" * 64)
    candidate.result = replace(candidate.result, artifact=artifact)

    with pytest.raises(PromotionAuthorizationError, match="SHA-256"):
        candidate_batch_sha256([candidate])


def test_missing_result_revision_is_a_promotion_refusal() -> None:
    candidate = _candidate()
    candidate.result = replace(candidate.result, base_revision=None)

    with pytest.raises(PromotionAuthorizationError, match="revision"):
        candidate_batch_sha256([candidate])


def test_malformed_artifact_revision_is_a_promotion_refusal() -> None:
    candidate = _candidate()
    artifact = replace(candidate.result.artifact, base_revision="not-a-revision")
    candidate.result = replace(candidate.result, artifact=artifact)

    with pytest.raises(PromotionAuthorizationError, match="canonical revision"):
        candidate_batch_sha256([candidate])


def test_noncanonical_changed_path_is_a_promotion_refusal() -> None:
    candidate = _candidate()
    artifact = replace(candidate.result.artifact, changed_paths=("a//b",))
    candidate.result = replace(candidate.result, artifact=artifact)

    with pytest.raises(PromotionAuthorizationError, match="canonical"):
        candidate_batch_sha256([candidate])


def test_empty_public_batch_has_one_structured_refusal() -> None:
    report = _public_refusal([])

    assert report["promoted"] == []
    assert report["authorization"] is None
    assert len(report["refused"]) == 1
    assert report["refused"][0]["task_id"] == "unknown"
    assert "exactly one candidate" in report["refused"][0]["reason"]


def test_noniterable_public_batch_has_one_structured_refusal() -> None:
    report = _public_refusal(None)

    assert report["promoted"] == []
    assert report["authorization"] is None
    assert len(report["refused"]) == 1
    assert report["refused"][0]["task_id"] == "unknown"
    assert "iterable batch" in report["refused"][0]["reason"]


def test_invalid_repository_root_has_one_structured_refusal() -> None:
    report = _public_refusal([], repo_root=None)

    assert report["promoted"] == []
    assert report["authorization"] is None
    assert len(report["refused"]) == 1
    assert report["refused"][0]["task_id"] == "unknown"
    assert "invalid repository root" in report["refused"][0]["reason"]

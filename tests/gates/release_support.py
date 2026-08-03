from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from daedalus.gates import (
    ArtifactEvidence,
    FaultMatrixEvidence,
    GateEvidenceIndex,
    GateReport,
    OwnerDecisionEvidence,
    ReviewEvidence,
    RuntimeEnvelopeEvidence,
    WorkflowRunEvidence,
    assemble_gate0_release_report,
    issue_evidence_trust_bundle,
)
from daedalus.gates.report import gate_report_artifact_sha256
from daedalus.schemas import ContractProvenance

REVISION = "a" * 40
TREE = "b" * 40
REGISTRY = "c" * 64
PLAN = "d" * 64
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
SECRET = b"external-release-collector-secret-material-32-bytes"
WORKFLOW_PATH = ".github/workflows/gate0-release.yml"
WORKFLOW_ID = "gate0-release"
COLLECTOR_ID = "external-release-collector"
COLLECTOR_KEY_ID = "collector-key-1"


def provenance(origin: str, revision: str, created_at: datetime, *digests: str):
    return ContractProvenance(
        origin=origin,
        source_revision=revision,
        created_at=created_at.isoformat(),
        input_digests=tuple(sorted(set(digests))),
    )


def local_report(**changes) -> GateReport:
    values = {
        "gate": 0,
        "source_revision": REVISION,
        "registry_sha256": REGISTRY,
        "security_boundary_claimed": False,
        "owner_approval_enforced": True,
    }
    values.update(changes)
    return GateReport(**values)


def workflow(
    workflow_id: str = WORKFLOW_ID,
    *,
    revision: str = REVISION,
    conclusion: str = "success",
) -> WorkflowRunEvidence:
    logs = ("1" if workflow_id == WORKFLOW_ID else "2") * 64
    artifact_sha = "3" * 64
    return WorkflowRunEvidence(
        workflow_id=workflow_id,
        run_id=101 if workflow_id == WORKFLOW_ID else 102,
        source_revision=revision,
        conclusion=conclusion,
        completed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=8)).isoformat(),
        logs_sha256=logs,
        artifact_sha256s=(artifact_sha,),
        provenance=provenance(
            "tests.release-workflow", revision, NOW, logs, artifact_sha
        ),
    )


def artifact(kind: str, content: str, *, tree: str = TREE) -> ArtifactEvidence:
    return ArtifactEvidence(
        artifact_id=f"artifact-{kind}",
        artifact_kind=kind,
        source_revision=REVISION,
        source_tree_revision=tree,
        content_sha256=content,
        locator=f"artifact-locator:sha256:{content}",
        built_at=NOW.isoformat(),
        provenance=provenance("tests.release-artifact", REVISION, NOW, content),
    )


def runtime() -> RuntimeEnvelopeEvidence:
    envelope = "4" * 64
    return RuntimeEnvelopeEvidence(
        runtime_id="claude-code-cli",
        envelope_sha256=envelope,
        source_revision=REVISION,
        authority="live-runtime",
        status="passed",
        observed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=8)).isoformat(),
        provenance=provenance("tests.release-runtime", REVISION, NOW, envelope),
    )


def fault() -> FaultMatrixEvidence:
    matrix = "5" * 64
    return FaultMatrixEvidence(
        matrix_id="gate0-faults",
        source_revision=REVISION,
        status="passed",
        matrix_sha256=matrix,
        scenario_ids=("approval-replay", "target-head-race"),
        executed_at=NOW.isoformat(),
        provenance=provenance("tests.release-fault", REVISION, NOW, matrix),
    )


def review(perspective: str, *, assurance: str = "human") -> ReviewEvidence:
    transcript = ("6" if perspective == "architecture" else "7") * 64
    return ReviewEvidence(
        review_id=f"{perspective}-review",
        perspective=perspective,
        assurance=assurance,
        source_revision=REVISION,
        verdict="passed",
        unresolved_finding_ids=(),
        transcript_sha256=transcript,
        reviewed_at=NOW.isoformat(),
        provenance=provenance(
            f"tests.release-{perspective}", REVISION, NOW, transcript
        ),
    )


def owner() -> OwnerDecisionEvidence:
    approval = "8" * 64
    verifier = "9" * 64
    return OwnerDecisionEvidence(
        decision_id="owner-gate0-close",
        source_revision=REVISION,
        owner_approval_sha256=approval,
        verifier_receipt_sha256=verifier,
        verified_at=NOW.isoformat(),
        provenance=provenance(
            "tests.release-owner", REVISION, NOW, approval, verifier
        ),
    )


def evidence_index(
    report: GateReport,
    *,
    owner_present: bool = True,
    report_artifact_sha256: str | None = None,
    registry_sha256: str = REGISTRY,
    workflows: tuple[WorkflowRunEvidence, ...] | None = None,
    architecture_assurance: str = "human",
) -> GateEvidenceIndex:
    report_sha = report_artifact_sha256 or gate_report_artifact_sha256(report)
    retained_workflows = workflows or (workflow(),)
    retained_artifacts = (
        artifact("gate-report", report_sha),
        artifact("wheel", "e" * 64),
    )
    retained_runtimes = (runtime(),)
    retained_faults = (fault(),)
    retained_reviews = (
        review("architecture", assurance=architecture_assurance),
        review("security"),
    )
    selected_owner = owner() if owner_present else None
    retained = [
        PLAN,
        registry_sha256,
        *(item.digest for item in retained_workflows),
        *(item.digest for item in retained_artifacts),
        *(item.digest for item in retained_runtimes),
        *(item.digest for item in retained_faults),
        *(item.digest for item in retained_reviews),
    ]
    if selected_owner is not None:
        retained.append(selected_owner.digest)
    return GateEvidenceIndex(
        index_id="gate0-release-index",
        gate=0,
        source_revision=REVISION,
        source_tree_revision=TREE,
        iron_plan_sha256=PLAN,
        registry_sha256=registry_sha256,
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=8)).isoformat(),
        required_workflow_ids=(WORKFLOW_ID,),
        required_artifact_kinds=("gate-report", "wheel"),
        required_runtime_ids=("claude-code-cli",),
        required_fault_matrix_ids=("gate0-faults",),
        required_review_perspectives=("architecture", "security"),
        workflows=retained_workflows,
        artifacts=retained_artifacts,
        runtimes=retained_runtimes,
        fault_matrices=retained_faults,
        reviews=retained_reviews,
        owner_decision=selected_owner,
        provenance=provenance(
            "tests.release-index", REVISION, NOW, *retained
        ),
    )


def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    workflow_file = root / WORKFLOW_PATH
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text(
        "name: Gate 0 release\non: [workflow_dispatch]\njobs: {}\n",
        encoding="utf-8",
    )
    return root


def trust_bundle(index: GateEvidenceIndex, root: Path):
    return issue_evidence_trust_bundle(
        index,
        repo_root=root,
        workflow_paths={WORKFLOW_ID: WORKFLOW_PATH},
        bundle_id="release-trust-bundle-1",
        collector_id=COLLECTOR_ID,
        collector_key_id=COLLECTOR_KEY_ID,
        collector_secret=SECRET,
        issued_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=2),
    )


def collector_keyring() -> dict[tuple[str, str], bytes]:
    return {(COLLECTOR_ID, COLLECTOR_KEY_ID): SECRET}


def assembly_arguments(root: Path) -> dict[str, object]:
    return {
        "repo_root": root,
        "collector_keyring": collector_keyring(),
        "expected_collector_id": COLLECTOR_ID,
        "expected_workflow_paths": {WORKFLOW_ID: WORKFLOW_PATH},
        "release_id": "gate0-release",
        "current_revision": REVISION,
        "current_tree_revision": TREE,
        "now": NOW + timedelta(minutes=2),
    }


def assemble(report: GateReport, index: GateEvidenceIndex, bundle, root: Path, **changes):
    arguments = assembly_arguments(root)
    arguments.update(changes)
    return assemble_gate0_release_report(report, index, bundle, **arguments)

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.gates.evidence import (
    ArtifactEvidence,
    FaultMatrixEvidence,
    GateEvidenceIndex,
    OwnerDecisionEvidence,
    ReviewEvidence,
    RuntimeEnvelopeEvidence,
    WorkflowRunEvidence,
)
from daedalus.gates.trust_bundle import (
    EvidenceTrustBundle,
    EvidenceTrustBundleBindingError,
    EvidenceTrustBundleSignatureError,
    WorkflowDefinitionAnchor,
    assert_strict_exact_head_with_bundle,
    issue_evidence_trust_bundle,
    load_evidence_trust_bundle,
    parse_evidence_trust_bundle,
    verify_evidence_trust_bundle,
)
from daedalus.gates import trust_bundle as trust_bundle_module
from daedalus.schemas import ContractProvenance

REVISION = "a" * 40
TREE = "b" * 40
PLAN = "1" * 64
REGISTRY = "2" * 64
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
SECRET = b"external-evidence-collector-secret-material-32-bytes"
WORKFLOW_PATH = ".github/workflows/gate.yml"
COLLECTOR_KEY = ("external-release-collector", "collector-key-1")


def bundle_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _provenance(
    origin: str,
    *digests: str,
    created_at: datetime = NOW,
    revision: str = REVISION,
    trace_id: str | None = None,
) -> ContractProvenance:
    return ContractProvenance(
        origin=origin,
        source_revision=revision,
        created_at=created_at.isoformat(),
        input_digests=tuple(sorted(set(digests))),
        trace_id=trace_id,
    )


def _index(
    *,
    revision: str = REVISION,
    tree: str = TREE,
    registry: str = REGISTRY,
    owner_present: bool = True,
) -> GateEvidenceIndex:
    logs = "3" * 64
    workflow_artifact = "4" * 64
    workflow = WorkflowRunEvidence(
        workflow_id="gate0-contracts",
        run_id=100,
        source_revision=revision,
        conclusion="success",
        completed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=8)).isoformat(),
        logs_sha256=logs,
        artifact_sha256s=(workflow_artifact,),
        provenance=_provenance(
            "tests.workflow",
            logs,
            workflow_artifact,
            revision=revision,
        ),
    )
    artifact_digest = "5" * 64
    artifact = ArtifactEvidence(
        artifact_id="gate0-wheel",
        artifact_kind="wheel",
        source_revision=revision,
        source_tree_revision=tree,
        content_sha256=artifact_digest,
        locator=f"artifact-locator:sha256:{artifact_digest}",
        built_at=NOW.isoformat(),
        provenance=_provenance(
            "tests.artifact",
            artifact_digest,
            revision=revision,
        ),
    )
    runtime_digest = "6" * 64
    runtime = RuntimeEnvelopeEvidence(
        runtime_id="claude-code-cli",
        envelope_sha256=runtime_digest,
        source_revision=revision,
        authority="live-runtime",
        status="passed",
        observed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=8)).isoformat(),
        provenance=_provenance(
            "tests.runtime",
            runtime_digest,
            revision=revision,
        ),
    )
    matrix_digest = "7" * 64
    matrix = FaultMatrixEvidence(
        matrix_id="gate0-faults",
        source_revision=revision,
        status="passed",
        matrix_sha256=matrix_digest,
        scenario_ids=("approval-replay", "target-head-race"),
        executed_at=NOW.isoformat(),
        provenance=_provenance(
            "tests.faults",
            matrix_digest,
            revision=revision,
        ),
    )
    architecture_digest = "8" * 64
    security_digest = "9" * 64
    reviews = (
        ReviewEvidence(
            review_id="architecture-review",
            perspective="architecture",
            assurance="human",
            source_revision=revision,
            verdict="passed",
            unresolved_finding_ids=(),
            transcript_sha256=architecture_digest,
            reviewed_at=NOW.isoformat(),
            provenance=_provenance(
                "tests.review",
                architecture_digest,
                revision=revision,
            ),
        ),
        ReviewEvidence(
            review_id="security-review",
            perspective="security",
            assurance="human",
            source_revision=revision,
            verdict="passed",
            unresolved_finding_ids=(),
            transcript_sha256=security_digest,
            reviewed_at=NOW.isoformat(),
            provenance=_provenance(
                "tests.review",
                security_digest,
                revision=revision,
            ),
        ),
    )
    owner = None
    if owner_present:
        approval = "c" * 64
        verifier = "d" * 64
        owner = OwnerDecisionEvidence(
            decision_id="owner-gate0-close",
            source_revision=revision,
            owner_approval_sha256=approval,
            verifier_receipt_sha256=verifier,
            verified_at=NOW.isoformat(),
            provenance=_provenance(
                "tests.owner",
                approval,
                verifier,
                revision=revision,
            ),
        )
    retained = [
        PLAN,
        registry,
        workflow.digest,
        artifact.digest,
        runtime.digest,
        matrix.digest,
        *(item.digest for item in reviews),
    ]
    if owner is not None:
        retained.append(owner.digest)
    return GateEvidenceIndex(
        index_id="gate0-exact-head",
        gate=0,
        source_revision=revision,
        source_tree_revision=tree,
        iron_plan_sha256=PLAN,
        registry_sha256=registry,
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=8)).isoformat(),
        required_workflow_ids=("gate0-contracts",),
        required_artifact_kinds=("wheel",),
        required_runtime_ids=("claude-code-cli",),
        required_fault_matrix_ids=("gate0-faults",),
        required_review_perspectives=("architecture", "security"),
        workflows=(workflow,),
        artifacts=(artifact,),
        runtimes=(runtime,),
        fault_matrices=(matrix,),
        reviews=reviews,
        owner_decision=owner,
        provenance=_provenance(
            "tests.gate-evidence-index",
            *retained,
            revision=revision,
        ),
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    workflow = root / WORKFLOW_PATH
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Gate 0 contracts\non: [workflow_dispatch]\njobs: {}\n",
        encoding="utf-8", newline="\n",
    )
    return root


def _bundle(
    index: GateEvidenceIndex,
    root: Path,
    *,
    issued_at: datetime = NOW + timedelta(minutes=1),
    expires_at: datetime = NOW + timedelta(hours=2),
):
    return issue_evidence_trust_bundle(
        index,
        repo_root=root,
        workflow_paths={"gate0-contracts": WORKFLOW_PATH},
        bundle_id="collector-bundle-1",
        collector_id="external-release-collector",
        collector_key_id="collector-key-1",
        collector_secret=SECRET,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _verify(
    bundle: EvidenceTrustBundle,
    index: GateEvidenceIndex,
    root: Path,
    **changes,
) -> None:
    values = {
        "repo_root": root,
        "keyring": {COLLECTOR_KEY: SECRET},
        "expected_collector_id": "external-release-collector",
        "expected_workflow_paths": {"gate0-contracts": WORKFLOW_PATH},
        "current_revision": REVISION,
        "current_tree_revision": TREE,
        "now": NOW + timedelta(minutes=2),
    }
    values.update(changes)
    verify_evidence_trust_bundle(bundle, index, **values)


def _repack_and_resign(
    bundle: EvidenceTrustBundle,
    **changes,
) -> EvidenceTrustBundle:
    payload = bundle.to_dict()
    payload.update(changes)
    payload["signature_sha256"] = "0" * 64
    anchors = tuple(
        WorkflowDefinitionAnchor.from_dict(item)
        for item in payload["workflow_anchors"]
    )
    inputs = tuple(
        sorted(
            {
                payload["index_sha256"],
                payload["requirements_sha256"],
                payload["iron_plan_sha256"],
                payload["registry_sha256"],
                *(item.digest for item in anchors),
                *payload["artifact_evidence_sha256s"],
                *payload["runtime_envelope_sha256s"],
                *payload["fault_matrix_sha256s"],
                *payload["review_evidence_sha256s"],
                *payload["owner_verifier_sha256s"],
            }
        )
    )
    payload["provenance"]["input_digests"] = list(inputs)
    if "issued_at" in changes:
        payload["provenance"]["created_at"] = payload["issued_at"]
    placeholder = EvidenceTrustBundle.from_dict(payload)
    return dataclasses.replace(
        placeholder,
        signature_sha256=trust_bundle_module._signature(
            placeholder.signing_digest,
            SECRET,
        ),
    )


def test_signed_bundle_round_trip_and_strict_verification(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    index = _index()
    bundle = _bundle(index, root)

    assert EvidenceTrustBundle.from_dict(bundle.to_dict()) == bundle
    assert bundle.provenance.input_digests == trust_bundle_module._bundle_input_digests(
        bundle
    )
    _verify(bundle, index, root)
    assert_strict_exact_head_with_bundle(
        index,
        bundle,
        repo_root=root,
        keyring={COLLECTOR_KEY: SECRET},
        expected_collector_id="external-release-collector",
        expected_workflow_paths={"gate0-contracts": WORKFLOW_PATH},
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW + timedelta(minutes=2),
    )

    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle.to_dict()), encoding="utf-8", newline="\n")
    assert load_evidence_trust_bundle(path) == bundle


def test_unknown_key_tamper_future_expiry_and_collector_mismatch(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    index = _index()
    bundle = _bundle(index, root)

    with pytest.raises(EvidenceTrustBundleSignatureError, match="unknown"):
        _verify(bundle, index, root, keyring={})
    with pytest.raises(EvidenceTrustBundleSignatureError, match="unknown"):
        _verify(
            bundle,
            index,
            root,
            keyring={("foreign-collector", "collector-key-1"): SECRET},
        )
    tampered = dataclasses.replace(bundle, signature_sha256="e" * 64)
    with pytest.raises(EvidenceTrustBundleSignatureError, match="signature"):
        _verify(tampered, index, root)
    with pytest.raises(EvidenceTrustBundleBindingError, match="future"):
        _verify(bundle, index, root, now=NOW)
    with pytest.raises(EvidenceTrustBundleBindingError, match="expired"):
        _verify(bundle, index, root, now=NOW + timedelta(hours=2))
    with pytest.raises(EvidenceTrustBundleBindingError, match="collector_id"):
        _verify(
            bundle,
            index,
            root,
            expected_collector_id="foreign-collector",
        )


def test_workflow_bytes_revision_and_tree_are_rechecked(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    index = _index()
    bundle = _bundle(index, root)

    (root / WORKFLOW_PATH).write_text(
        "name: changed\non: [push]\njobs: {}\n",
        encoding="utf-8", newline="\n",
    )
    with pytest.raises(EvidenceTrustBundleBindingError, match="definition"):
        _verify(bundle, index, root)

    (root / WORKFLOW_PATH).write_text(
        "name: Gate 0 contracts\non: [workflow_dispatch]\njobs: {}\n",
        encoding="utf-8", newline="\n",
    )
    with pytest.raises(EvidenceTrustBundleBindingError, match="repository path"):
        _verify(
            bundle,
            index,
            root,
            expected_workflow_paths={
                "gate0-contracts": ".github/workflows/other.yml"
            },
        )

    with pytest.raises(EvidenceTrustBundleBindingError, match="source_revision"):
        _verify(
            bundle,
            index,
            root,
            current_revision="f" * 40,
        )
    with pytest.raises(EvidenceTrustBundleBindingError, match="tree_revision"):
        _verify(
            bundle,
            index,
            root,
            current_tree_revision="0" * 40,
        )


def test_workflow_path_membership_scope_and_symlink_refuse(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    index = _index()
    with pytest.raises(EvidenceTrustBundleBindingError, match="exactly"):
        issue_evidence_trust_bundle(
            index,
            repo_root=root,
            workflow_paths={},
            bundle_id="collector-bundle-1",
            collector_id="external-release-collector",
            collector_key_id="collector-key-1",
            collector_secret=SECRET,
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with pytest.raises(ValueError, match="stay inside"):
        WorkflowDefinitionAnchor(
            workflow_id="gate0-contracts",
            repository_path="../gate.yml",
            workflow_evidence_sha256=index.workflows[0].digest,
            definition_sha256="e" * 64,
        )
    for invalid in (
        ".github/workflows/gate.txt",
        ".github/workflows/gate.YML",
    ):
        with pytest.raises(ValueError, match="YAML"):
            WorkflowDefinitionAnchor(
                workflow_id="gate0-contracts",
                repository_path=invalid,
                workflow_evidence_sha256=index.workflows[0].digest,
                definition_sha256="e" * 64,
            )

    link = root / ".github/workflows/link.yml"
    try:
        link.symlink_to(root / WORKFLOW_PATH)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(EvidenceTrustBundleBindingError, match="symlink"):
        issue_evidence_trust_bundle(
            index,
            repo_root=root,
            workflow_paths={"gate0-contracts": ".github/workflows/link.yml"},
            bundle_id="collector-bundle-1",
            collector_id="external-release-collector",
            collector_key_id="collector-key-1",
            collector_secret=SECRET,
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )

    parent_root = tmp_path / "parent-link-repo"
    parent_root.mkdir()
    outside = tmp_path / "outside-github"
    outside_workflows = outside / "workflows"
    outside_workflows.mkdir(parents=True)
    (outside_workflows / "gate.yml").write_text(
        "name: foreign\non: [push]\njobs: {}\n",
        encoding="utf-8", newline="\n",
    )
    try:
        (parent_root / ".github").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("parent symlink creation unavailable")
    with pytest.raises(EvidenceTrustBundleBindingError, match="symlink"):
        issue_evidence_trust_bundle(
            index,
            repo_root=parent_root,
            workflow_paths={"gate0-contracts": WORKFLOW_PATH},
            bundle_id="collector-bundle-2",
            collector_id="external-release-collector",
            collector_key_id="collector-key-1",
            collector_secret=SECRET,
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )


def test_foreign_index_and_repacked_evidence_sets_refuse(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    index = _index()
    bundle = _bundle(index, root)

    foreign_index = _index(registry="e" * 64)
    with pytest.raises(EvidenceTrustBundleBindingError, match="index_sha256"):
        _verify(bundle, foreign_index, root)

    repacked = _repack_and_resign(
        bundle,
        artifact_evidence_sha256s=["f" * 64],
    )
    with pytest.raises(
        EvidenceTrustBundleBindingError,
        match="artifact_evidence_sha256s",
    ):
        _verify(repacked, index, root)


def test_exact_provenance_lifetime_and_no_owner_fail_closed(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    index = _index()
    bundle = _bundle(index, root)
    expanded = dataclasses.replace(
        bundle.provenance,
        input_digests=tuple(
            sorted((*bundle.provenance.input_digests, "f" * 64))
        ),
    )
    with pytest.raises(ValueError, match="exactly"):
        dataclasses.replace(bundle, provenance=expanded)
    with pytest.raises(ValueError, match="24 hours"):
        dataclasses.replace(
            bundle,
            expires_at=(bundle_time(bundle.issued_at) + timedelta(hours=25)).isoformat(),
        )
    with pytest.raises(EvidenceTrustBundleBindingError, match="predates"):
        _bundle(
            index,
            root,
            issued_at=NOW - timedelta(microseconds=1),
            expires_at=NOW + timedelta(hours=1),
        )
    with pytest.raises(EvidenceTrustBundleBindingError, match="outlives"):
        _bundle(
            index,
            root,
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=9),
        )
    predating = _repack_and_resign(
        bundle,
        issued_at=(NOW - timedelta(microseconds=1)).isoformat(),
    )
    with pytest.raises(EvidenceTrustBundleBindingError, match="predates"):
        _verify(predating, index, root)
    outliving = _repack_and_resign(
        bundle,
        expires_at=(NOW + timedelta(hours=9)).isoformat(),
    )
    with pytest.raises(EvidenceTrustBundleBindingError, match="outlives"):
        _verify(outliving, index, root)

    no_owner = _index(owner_present=False)
    no_owner_bundle = _bundle(no_owner, root)
    _verify(no_owner_bundle, no_owner, root)
    with pytest.raises(ValueError, match="owner-decision:missing"):
        assert_strict_exact_head_with_bundle(
            no_owner,
            no_owner_bundle,
            repo_root=root,
            keyring={COLLECTOR_KEY: SECRET},
            expected_collector_id="external-release-collector",
            expected_workflow_paths={"gate0-contracts": WORKFLOW_PATH},
            current_revision=REVISION,
            current_tree_revision=TREE,
            now=NOW + timedelta(minutes=2),
        )


def test_strict_wire_rejects_duplicate_keys_string_arrays_and_non_objects(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    bundle = _bundle(_index(), root)
    payload = bundle.to_dict()
    payload["artifact_evidence_sha256s"] = "f" * 64
    with pytest.raises(ValueError, match="array"):
        parse_evidence_trust_bundle(payload)
    with pytest.raises(ValueError, match="object"):
        parse_evidence_trust_bundle([])  # type: ignore[arg-type]

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"contract_type":"x","contract_type":"y"}',
        encoding="utf-8", newline="\n",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_evidence_trust_bundle(duplicate)

from __future__ import annotations

import dataclasses
import importlib.util
import inspect
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.gates import Gate0ReleaseReport, assemble_gate0_release_report
from daedalus.gates.trust_bundle import (
    EvidenceTrustBundleBindingError,
    EvidenceTrustBundleSignatureError,
)

_SUPPORT_PATH = Path(__file__).with_name("release_support.py")
_SPEC = importlib.util.spec_from_file_location("_release_support", _SUPPORT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPPORT)


def test_complete_authenticated_exact_head_is_the_only_closed_release(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    assert release.closed
    assert release.blockers == ()
    assert release.parsed_gate_report.security_boundary_claimed
    assert release.parsed_gate_report.closed
    assert release.evidence_trust_bundle_sha256 == bundle.digest
    assert release.mechanical_report_sha256 == report.to_dict()["report_sha256"]
    assert Gate0ReleaseReport.from_dict(release.to_dict()) == release
    assert _SUPPORT.assemble(report, index, bundle, root).digest == release.digest


def test_release_assembly_exposes_no_raw_trust_set_injection() -> None:
    parameters = inspect.signature(assemble_gate0_release_report).parameters
    assert "trust_bundle" in parameters
    assert "collector_keyring" in parameters
    assert not any(name.startswith("trusted_") for name in parameters)


def test_invalid_or_foreign_bundle_refuses_before_release_construction(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)

    tampered = dataclasses.replace(bundle, signature_sha256="f" * 64)
    with pytest.raises(EvidenceTrustBundleSignatureError):
        _SUPPORT.assemble(report, index, tampered, root)

    with pytest.raises(EvidenceTrustBundleSignatureError):
        _SUPPORT.assemble(
            report,
            index,
            bundle,
            root,
            collector_keyring={},
        )

    with pytest.raises(EvidenceTrustBundleBindingError, match="source_revision"):
        _SUPPORT.assemble(
            report,
            index,
            bundle,
            root,
            current_revision="0" * 40,
        )


def test_manual_security_claim_cannot_replace_bundle_authentication(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report(security_boundary_claimed=True)
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)

    with pytest.raises(EvidenceTrustBundleSignatureError):
        _SUPPORT.assemble(
            report,
            index,
            bundle,
            root,
            collector_keyring={},
        )


def test_owner_decision_remains_separate_from_technical_security(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report, owner_present=False)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    assert release.parsed_gate_report.security_boundary_claimed
    assert release.parsed_gate_report.closed
    assert not release.closed
    assert release.blockers == ("owner-decision:missing",)


def test_local_runtime_failure_prevents_security_claim_with_valid_bundle(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report(runtime_conformance_failures=("claude:failed",))
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    assert not release.parsed_gate_report.security_boundary_claimed
    assert not release.closed
    assert "runtime_conformance_failures:claude:failed" in release.blockers
    assert "security_boundary_claimed:false" in release.blockers


def test_authenticated_but_bad_evidence_remains_a_blocker(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(
        report,
        workflows=(
            _SUPPORT.workflow(),
            _SUPPORT.workflow("optional-nightly", conclusion="failure"),
        ),
        architecture_assurance="model-opinion",
    )
    extra_workflow = root / ".github/workflows/optional.yml"
    extra_workflow.write_text("name: Optional\non: [workflow_dispatch]\njobs: {}\n")
    bundle = _SUPPORT.issue_evidence_trust_bundle(
        index,
        repo_root=root,
        workflow_paths={
            _SUPPORT.WORKFLOW_ID: _SUPPORT.WORKFLOW_PATH,
            "optional-nightly": ".github/workflows/optional.yml",
        },
        bundle_id="release-trust-bundle-1",
        collector_id=_SUPPORT.COLLECTOR_ID,
        collector_key_id=_SUPPORT.COLLECTOR_KEY_ID,
        collector_secret=_SUPPORT.SECRET,
        issued_at=_SUPPORT.NOW + timedelta(minutes=1),
        expires_at=_SUPPORT.NOW + timedelta(hours=2),
    )
    release = _SUPPORT.assemble(
        report,
        index,
        bundle,
        root,
        expected_workflow_paths={
            _SUPPORT.WORKFLOW_ID: _SUPPORT.WORKFLOW_PATH,
            "optional-nightly": ".github/workflows/optional.yml",
        },
    )

    assert "workflow:optional-nightly:conclusion-failure" in release.blockers
    assert "review:architecture:no-human-pass" in release.blockers
    assert not release.parsed_gate_report.security_boundary_claimed


def test_report_artifact_and_registry_recombination_fail_closed(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report(registry_sha256="0" * 64)
    index = _SUPPORT.evidence_index(
        report,
        registry_sha256=_SUPPORT.REGISTRY,
        report_artifact_sha256="f" * 64,
    )
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    assert "assembly:gate-report-artifact-mismatch" in release.blockers
    assert "assembly:gate-report-registry-mismatch" in release.blockers
    assert not release.closed


def test_derived_wire_fields_nested_report_and_provenance_are_tamper_evident(
    tmp_path: Path,
) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    closed_payload = release.to_dict()
    closed_payload["closed"] = False
    with pytest.raises(ValueError, match="closed contradicts"):
        Gate0ReleaseReport.from_dict(closed_payload)

    blocker_payload = release.to_dict()
    blocker_payload["blockers"] = ["invented"]
    with pytest.raises(ValueError, match="blockers contradict"):
        Gate0ReleaseReport.from_dict(blocker_payload)

    report_payload = release.to_dict()
    report_payload["gate_report"]["security_boundary_claimed"] = "true"
    with pytest.raises(ValueError):
        Gate0ReleaseReport.from_dict(report_payload)

    with pytest.raises(ValueError, match="does not bind"):
        dataclasses.replace(
            release,
            provenance=dataclasses.replace(release.provenance, input_digests=()),
        )

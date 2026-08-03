"""Authenticated exact-head Gate-0 release assembly.

The release report composes the local machine-readable Gate projection with one
externally authenticated :class:`~daedalus.gates.trust_bundle.EvidenceTrustBundle`.
It has no manual ``closed`` or security-boundary override and accepts no raw
caller-supplied trust sets.

This module remains a projection. It does not collect evidence, authenticate an
owner approval, merge, promote, or mutate a repository reference.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _freeze_json,
    _identifier,
    _json_value,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)

from .evidence import GateEvidenceIndex
from .evidence_verifier import strict_mechanical_blockers
from .report import GateReport
from .trust_bundle import EvidenceTrustBundle, verify_evidence_trust_bundle

_RELEASE_SCHEMA = "daedalus-gate0-release-report/1"
_RELEASE_ORIGIN = "daedalus.gates.release"
_SECURITY_CLAIM_BLOCKER = "security_boundary_claimed:false"
_OWNER_EVIDENCE_PREFIX = "owner-decision:"


def _report_sha256(report: GateReport) -> str:
    return str(report.to_dict()["report_sha256"])


def _strict_gate_report(payload: Mapping[str, Any]) -> tuple[GateReport, dict[str, Any]]:
    """Parse only the exact canonical GateReport wire representation."""

    if not isinstance(payload, Mapping):
        raise ValueError("gate_report must be an object")
    wire = _json_value(payload)
    if not isinstance(wire, dict):
        raise ValueError("gate_report must be an object")
    parsed = GateReport.from_dict(wire)
    canonical = parsed.to_dict()
    if wire != canonical:
        raise ValueError("gate_report must be the exact canonical GateReport payload")
    return parsed, canonical


def _bundle_trust_sets(bundle: EvidenceTrustBundle) -> dict[str, tuple[str, ...]]:
    """Project only authenticated bundle fields into the legacy strict verifier."""

    return {
        "trusted_requirements_sha256s": (bundle.requirements_sha256,),
        "trusted_iron_plan_sha256s": (bundle.iron_plan_sha256,),
        "trusted_registry_sha256s": (bundle.registry_sha256,),
        "trusted_workflow_evidence_sha256s": tuple(
            item.workflow_evidence_sha256 for item in bundle.workflow_anchors
        ),
        "trusted_artifact_evidence_sha256s": bundle.artifact_evidence_sha256s,
        "trusted_runtime_envelope_sha256s": bundle.runtime_envelope_sha256s,
        "trusted_fault_matrix_sha256s": bundle.fault_matrix_sha256s,
        "trusted_review_evidence_sha256s": bundle.review_evidence_sha256s,
        "trusted_owner_verifier_sha256s": bundle.owner_verifier_sha256s,
    }


@dataclass(frozen=True)
class Gate0ReleaseReport(CanonicalContract):
    """One immutable Gate-0 release decision for one exact commit and tree."""

    CONTRACT_TYPE: ClassVar[str] = _RELEASE_SCHEMA

    release_id: str
    source_revision: str
    source_tree_revision: str
    mechanical_report_sha256: str
    gate_report: Mapping[str, Any]
    evidence_index_sha256: str
    evidence_trust_bundle_sha256: str
    exact_head_blockers: tuple[str, ...]
    generated_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "release_id", _identifier(self.release_id, "release_id"))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "source_tree_revision",
            _revision(self.source_tree_revision, "source_tree_revision"),
        )
        for field_name in (
            "mechanical_report_sha256",
            "evidence_index_sha256",
            "evidence_trust_bundle_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), field_name),
            )
        report, canonical_report = _strict_gate_report(self.gate_report)
        if report.source_revision != self.source_revision:
            raise ValueError("release gate report source revision is not exact-head bound")
        object.__setattr__(self, "gate_report", _freeze_json(canonical_report, "gate_report"))
        object.__setattr__(
            self,
            "exact_head_blockers",
            _sorted_strings(self.exact_head_blockers, "exact_head_blockers"),
        )
        object.__setattr__(
            self, "generated_at", _utc_timestamp(self.generated_at, "generated_at")
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("provenance must be ContractProvenance")
        if self.provenance.origin != _RELEASE_ORIGIN:
            raise ValueError("release provenance origin is invalid")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("release source revision contradicts provenance")
        if self.provenance.created_at != self.generated_at:
            raise ValueError("release generated_at contradicts provenance.created_at")
        if self.provenance.trace_id != self.release_id:
            raise ValueError("release provenance trace_id must equal release_id")
        expected_inputs = tuple(
            sorted(
                {
                    self.mechanical_report_sha256,
                    _report_sha256(report),
                    self.evidence_index_sha256,
                    self.evidence_trust_bundle_sha256,
                }
            )
        )
        if self.provenance.input_digests != expected_inputs:
            raise ValueError(
                "release provenance inputs must exactly match retained identities"
            )

    @property
    def parsed_gate_report(self) -> GateReport:
        report, _ = _strict_gate_report(self.gate_report)
        return report

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(
            sorted(set(self.parsed_gate_report.blockers).union(self.exact_head_blockers))
        )

    @property
    def closed(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "release_id": self.release_id,
            "source_revision": self.source_revision,
            "source_tree_revision": self.source_tree_revision,
            "mechanical_report_sha256": self.mechanical_report_sha256,
            "gate_report": _json_value(self.gate_report),
            "evidence_index_sha256": self.evidence_index_sha256,
            "evidence_trust_bundle_sha256": self.evidence_trust_bundle_sha256,
            "exact_head_blockers": list(self.exact_head_blockers),
            "generated_at": self.generated_at,
            "provenance": self.provenance.to_dict(),
            "closed": self.closed,
            "blockers": list(self.blockers),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Gate0ReleaseReport":
        if not isinstance(payload, Mapping):
            raise ValueError("Gate-0 release report must be an object")
        wire = dict(payload)
        if "closed" not in wire or "blockers" not in wire:
            raise ValueError("Gate-0 release report must retain derived closed and blockers")
        claimed_closed = wire.pop("closed")
        claimed_blockers = wire.pop("blockers")
        if not isinstance(claimed_closed, bool):
            raise ValueError("release closed must be boolean")
        if not isinstance(claimed_blockers, list) or any(
            not isinstance(value, str) for value in claimed_blockers
        ):
            raise ValueError("release blockers must be an array of strings")
        body = cls._contract_payload(wire)
        body["gate_report"] = dict(body["gate_report"])
        body["exact_head_blockers"] = tuple(body["exact_head_blockers"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        value = cls(**body)
        if claimed_closed is not value.closed:
            raise ValueError("release closed contradicts derived blockers")
        if claimed_blockers != list(value.blockers):
            raise ValueError("release blockers contradict derived blockers")
        return value


def assemble_gate0_release_report(
    local_report: GateReport,
    evidence_index: GateEvidenceIndex,
    trust_bundle: EvidenceTrustBundle,
    *,
    repo_root: Path,
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_workflow_paths: Mapping[str, str],
    release_id: str,
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> Gate0ReleaseReport:
    """Authenticate exact-head trust and derive a fail-closed release report.

    Invalid, stale, foreign, or unauthenticated trust material refuses assembly;
    no report is emitted from raw digest sets. The separately authenticated owner
    decision remains a release blocker and is not replaced by technical wiring.
    """

    current = _revision(current_revision, "current_revision")
    current_tree = _revision(current_tree_revision, "current_tree_revision")
    verify_evidence_trust_bundle(
        trust_bundle,
        evidence_index,
        repo_root=repo_root,
        keyring=collector_keyring,
        expected_collector_id=expected_collector_id,
        expected_workflow_paths=expected_workflow_paths,
        current_revision=current,
        current_tree_revision=current_tree,
        now=now,
    )
    mechanical_sha = _report_sha256(local_report)
    evidence_blockers = set(
        strict_mechanical_blockers(
            evidence_index,
            current_revision=current,
            current_tree_revision=current_tree,
            now=now,
            **_bundle_trust_sets(trust_bundle),
        )
    )

    if local_report.source_revision != current:
        evidence_blockers.add("assembly:gate-report-foreign-source-revision")
    if local_report.registry_sha256 != evidence_index.registry_sha256:
        evidence_blockers.add("assembly:gate-report-registry-mismatch")
    if "gate-report" not in evidence_index.required_artifact_kinds:
        evidence_blockers.add("assembly:gate-report-not-required")
    artifact_by_kind = {item.artifact_kind: item for item in evidence_index.artifacts}
    retained_report = artifact_by_kind.get("gate-report")
    if retained_report is None:
        evidence_blockers.add("assembly:gate-report-artifact-missing")
    elif retained_report.content_sha256 != mechanical_sha:
        evidence_blockers.add("assembly:gate-report-artifact-mismatch")

    local_boundary_blockers = set(local_report.blockers)
    local_boundary_blockers.discard(_SECURITY_CLAIM_BLOCKER)
    security_evidence_blockers = {
        blocker
        for blocker in evidence_blockers
        if not blocker.startswith(_OWNER_EVIDENCE_PREFIX)
    }
    security_claimed = not local_boundary_blockers and not security_evidence_blockers
    derived_report = dataclasses.replace(
        local_report,
        security_boundary_claimed=security_claimed,
    )
    derived_sha = _report_sha256(derived_report)
    generated_at = _utc_timestamp(now.isoformat(), "generated_at")
    provenance = ContractProvenance(
        origin=_RELEASE_ORIGIN,
        source_revision=current,
        created_at=generated_at,
        input_digests=tuple(
            sorted(
                {
                    mechanical_sha,
                    derived_sha,
                    evidence_index.digest,
                    trust_bundle.digest,
                }
            )
        ),
        trace_id=release_id,
    )

    return Gate0ReleaseReport(
        release_id=release_id,
        source_revision=current,
        source_tree_revision=current_tree,
        mechanical_report_sha256=mechanical_sha,
        gate_report=derived_report.to_dict(),
        evidence_index_sha256=evidence_index.digest,
        evidence_trust_bundle_sha256=trust_bundle.digest,
        exact_head_blockers=tuple(sorted(evidence_blockers)),
        generated_at=generated_at,
        provenance=provenance,
    )


__all__ = ["Gate0ReleaseReport", "assemble_gate0_release_report"]

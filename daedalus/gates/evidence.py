# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Exact-head evidence index for Gate-0 report assembly.

The existing :mod:`daedalus.gates.report` remains the delivery-gate projection.
This module is a strict, additive evidence container: it binds CI runs,
artifacts, live runtime envelopes, fault matrices, reviews, and an externally
verified owner decision to one exact commit and tree.  It does not fetch
GitHub, authenticate an owner, execute a runtime, or close a gate by itself.

Every item is content addressed. ``mechanical_blockers`` is derived from the
retained records; there is no manual ``closed`` or ``passed`` override for the
index as a whole.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, ClassVar, Mapping, Sequence

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _artifact_locator,
    _identifier,
    _non_empty,
    _record_payload,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha

_GATE_EVIDENCE_SCHEMA = "daedalus-gate-evidence-index/1"
_WORKFLOW_CONCLUSIONS = frozenset(
    {"success", "failure", "cancelled", "skipped", "timed-out", "action-required"}
)
_ARTIFACT_KINDS = frozenset(
    {
        "gate-report",
        "wheel",
        "source-archive",
        "effect-inventory",
        "fault-matrix",
        "runtime-index",
        "test-report",
    }
)
_REVIEW_ASSURANCE = frozenset({"human", "deterministic-tool", "model-opinion"})
_REVIEW_VERDICTS = frozenset({"passed", "changes-requested", "commented", "dismissed"})
_RUNTIME_AUTHORITIES = frozenset({"offline-fixture", "live-runtime"})
_STATUS = frozenset({"passed", "failed"})


def _record_dict(value: object) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in fields(value):
        nested = getattr(value, item.name)
        if isinstance(nested, tuple):
            result[item.name] = list(nested)
        elif isinstance(nested, ContractProvenance):
            result[item.name] = nested.to_dict()
        else:
            result[item.name] = nested
    return result


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _status(value: Any, name: str, allowed: frozenset[str]) -> str:
    text = _non_empty(value, name, max_length=100)
    if text not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")
    return text


@dataclass(frozen=True)
class WorkflowRunEvidence:
    workflow_id: str
    run_id: int
    source_revision: str
    conclusion: str
    completed_at: str
    expires_at: str
    logs_sha256: str
    artifact_sha256s: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "workflow_id", _identifier(self.workflow_id, "workflow_id"))
        object.__setattr__(self, "run_id", _positive_int(self.run_id, "run_id"))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "conclusion",
            _status(self.conclusion, "conclusion", _WORKFLOW_CONCLUSIONS),
        )
        object.__setattr__(
            self, "completed_at", _utc_timestamp(self.completed_at, "completed_at")
        )
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.completed_at:
            raise ValueError("workflow evidence expires_at must follow completed_at")
        object.__setattr__(self, "logs_sha256", _sha256(self.logs_sha256, "logs_sha256"))
        object.__setattr__(
            self,
            "artifact_sha256s",
            _sorted_strings(self.artifact_sha256s, "artifact_sha256s", digests=True),
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("workflow source revision contradicts provenance")
        if self.provenance.created_at != self.completed_at:
            raise ValueError("workflow completed_at contradicts provenance.created_at")
        _require_provenance_inputs(
            self.provenance,
            (self.logs_sha256, *self.artifact_sha256s),
            "workflow evidence",
        )

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowRunEvidence":
        body = _record_payload(cls, payload, "workflow evidence")
        body["artifact_sha256s"] = tuple(body["artifact_sha256s"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class ArtifactEvidence:
    artifact_id: str
    artifact_kind: str
    source_revision: str
    source_tree_revision: str
    content_sha256: str
    locator: str
    built_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _identifier(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self,
            "artifact_kind",
            _status(self.artifact_kind, "artifact_kind", _ARTIFACT_KINDS),
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "source_tree_revision",
            _revision(self.source_tree_revision, "source_tree_revision"),
        )
        object.__setattr__(
            self, "content_sha256", _sha256(self.content_sha256, "content_sha256")
        )
        object.__setattr__(self, "locator", _artifact_locator(self.locator, "locator"))
        object.__setattr__(self, "built_at", _utc_timestamp(self.built_at, "built_at"))
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("artifact source revision contradicts provenance")
        if self.provenance.created_at != self.built_at:
            raise ValueError("artifact built_at contradicts provenance.created_at")
        _require_provenance_inputs(
            self.provenance,
            (self.content_sha256, self.locator.rsplit(":", 1)[-1]),
            "artifact evidence",
        )

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ArtifactEvidence":
        body = _record_payload(cls, payload, "artifact evidence")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class RuntimeEnvelopeEvidence:
    runtime_id: str
    envelope_sha256: str
    source_revision: str
    authority: str
    status: str
    observed_at: str
    expires_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        object.__setattr__(
            self, "envelope_sha256", _sha256(self.envelope_sha256, "envelope_sha256")
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self, "authority", _status(self.authority, "authority", _RUNTIME_AUTHORITIES)
        )
        object.__setattr__(self, "status", _status(self.status, "status", _STATUS))
        object.__setattr__(
            self, "observed_at", _utc_timestamp(self.observed_at, "observed_at")
        )
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.observed_at:
            raise ValueError("runtime evidence expires_at must follow observed_at")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("runtime source revision contradicts provenance")
        if self.provenance.created_at != self.observed_at:
            raise ValueError("runtime observed_at contradicts provenance.created_at")
        _require_provenance_inputs(
            self.provenance, (self.envelope_sha256,), "runtime evidence"
        )

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeEnvelopeEvidence":
        body = _record_payload(cls, payload, "runtime evidence")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class FaultMatrixEvidence:
    matrix_id: str
    source_revision: str
    status: str
    matrix_sha256: str
    scenario_ids: tuple[str, ...]
    executed_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "matrix_id", _identifier(self.matrix_id, "matrix_id"))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(self, "status", _status(self.status, "status", _STATUS))
        object.__setattr__(
            self, "matrix_sha256", _sha256(self.matrix_sha256, "matrix_sha256")
        )
        object.__setattr__(
            self,
            "scenario_ids",
            _sorted_strings(self.scenario_ids, "scenario_ids", identifiers=True),
        )
        if not self.scenario_ids:
            raise ValueError("fault matrix evidence must retain at least one scenario")
        object.__setattr__(
            self, "executed_at", _utc_timestamp(self.executed_at, "executed_at")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("fault matrix source revision contradicts provenance")
        if self.provenance.created_at != self.executed_at:
            raise ValueError("fault matrix executed_at contradicts provenance.created_at")
        _require_provenance_inputs(
            self.provenance, (self.matrix_sha256,), "fault matrix evidence"
        )

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FaultMatrixEvidence":
        body = _record_payload(cls, payload, "fault matrix evidence")
        body["scenario_ids"] = tuple(body["scenario_ids"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class ReviewEvidence:
    review_id: str
    perspective: str
    assurance: str
    source_revision: str
    verdict: str
    unresolved_finding_ids: tuple[str, ...]
    transcript_sha256: str
    reviewed_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "review_id", _identifier(self.review_id, "review_id"))
        object.__setattr__(self, "perspective", _identifier(self.perspective, "perspective"))
        object.__setattr__(
            self, "assurance", _status(self.assurance, "assurance", _REVIEW_ASSURANCE)
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(self, "verdict", _status(self.verdict, "verdict", _REVIEW_VERDICTS))
        object.__setattr__(
            self,
            "unresolved_finding_ids",
            _sorted_strings(
                self.unresolved_finding_ids,
                "unresolved_finding_ids",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "transcript_sha256",
            _sha256(self.transcript_sha256, "transcript_sha256"),
        )
        object.__setattr__(
            self, "reviewed_at", _utc_timestamp(self.reviewed_at, "reviewed_at")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("review source revision contradicts provenance")
        if self.provenance.created_at != self.reviewed_at:
            raise ValueError("review reviewed_at contradicts provenance.created_at")
        _require_provenance_inputs(
            self.provenance, (self.transcript_sha256,), "review evidence"
        )

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewEvidence":
        body = _record_payload(cls, payload, "review evidence")
        body["unresolved_finding_ids"] = tuple(body["unresolved_finding_ids"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class OwnerDecisionEvidence:
    """Reference to a separately authenticated owner decision and verifier receipt."""

    decision_id: str
    source_revision: str
    owner_approval_sha256: str
    verifier_receipt_sha256: str
    verified_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _identifier(self.decision_id, "decision_id"))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "owner_approval_sha256",
            _sha256(self.owner_approval_sha256, "owner_approval_sha256"),
        )
        object.__setattr__(
            self,
            "verifier_receipt_sha256",
            _sha256(self.verifier_receipt_sha256, "verifier_receipt_sha256"),
        )
        object.__setattr__(
            self, "verified_at", _utc_timestamp(self.verified_at, "verified_at")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("owner decision source revision contradicts provenance")
        if self.provenance.created_at != self.verified_at:
            raise ValueError("owner decision verified_at contradicts provenance.created_at")
        _require_provenance_inputs(
            self.provenance,
            (self.owner_approval_sha256, self.verifier_receipt_sha256),
            "owner decision evidence",
        )

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OwnerDecisionEvidence":
        body = _record_payload(cls, payload, "owner decision evidence")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class GateEvidenceIndex(CanonicalContract):
    """One deterministic evidence view for one exact Gate-0 candidate head."""

    CONTRACT_TYPE: ClassVar[str] = _GATE_EVIDENCE_SCHEMA

    index_id: str
    gate: int
    source_revision: str
    source_tree_revision: str
    iron_plan_sha256: str
    registry_sha256: str
    generated_at: str
    expires_at: str
    required_workflow_ids: tuple[str, ...]
    required_artifact_kinds: tuple[str, ...]
    required_runtime_ids: tuple[str, ...]
    required_fault_matrix_ids: tuple[str, ...]
    required_review_perspectives: tuple[str, ...]
    workflows: tuple[WorkflowRunEvidence, ...]
    artifacts: tuple[ArtifactEvidence, ...]
    runtimes: tuple[RuntimeEnvelopeEvidence, ...]
    fault_matrices: tuple[FaultMatrixEvidence, ...]
    reviews: tuple[ReviewEvidence, ...]
    owner_decision: OwnerDecisionEvidence | None
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "index_id", _identifier(self.index_id, "index_id"))
        if self.gate != 0:
            raise ValueError("exact-head evidence index currently supports Gate 0 only")
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "source_tree_revision",
            _revision(self.source_tree_revision, "source_tree_revision"),
        )
        object.__setattr__(
            self, "iron_plan_sha256", _sha256(self.iron_plan_sha256, "iron_plan_sha256")
        )
        object.__setattr__(
            self, "registry_sha256", _sha256(self.registry_sha256, "registry_sha256")
        )
        object.__setattr__(
            self, "generated_at", _utc_timestamp(self.generated_at, "generated_at")
        )
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.generated_at:
            raise ValueError("evidence index expires_at must follow generated_at")
        for field_name in (
            "required_workflow_ids",
            "required_runtime_ids",
            "required_fault_matrix_ids",
            "required_review_perspectives",
        ):
            object.__setattr__(
                self,
                field_name,
                _sorted_strings(
                    getattr(self, field_name), field_name, identifiers=True
                ),
            )
        kinds = tuple(
            sorted(
                _status(value, "required_artifact_kind", _ARTIFACT_KINDS)
                for value in self.required_artifact_kinds
            )
        )
        if len(set(kinds)) != len(kinds):
            raise ValueError("required_artifact_kinds must not contain duplicates")
        object.__setattr__(self, "required_artifact_kinds", kinds)
        if not all(
            (
                self.required_workflow_ids,
                self.required_artifact_kinds,
                self.required_runtime_ids,
                self.required_fault_matrix_ids,
                self.required_review_perspectives,
            )
        ):
            raise ValueError("Gate-0 evidence requirements must be explicit and non-empty")

        collections = {
            "workflows": (self.workflows, "workflow_id"),
            "artifacts": (self.artifacts, "artifact_kind"),
            "runtimes": (self.runtimes, "runtime_id"),
            "fault_matrices": (self.fault_matrices, "matrix_id"),
            "reviews": (self.reviews, "review_id"),
        }
        for name, (values, identity_field) in collections.items():
            identities = [getattr(value, identity_field) for value in values]
            if len(set(identities)) != len(identities):
                raise ValueError(f"{name} contains ambiguous duplicate identities")
            object.__setattr__(
                self,
                name,
                tuple(sorted(values, key=lambda value: getattr(value, identity_field))),
            )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("evidence index source revision contradicts provenance")
        if self.provenance.created_at != self.generated_at:
            raise ValueError("evidence index generated_at contradicts provenance.created_at")
        required_inputs = [
            self.iron_plan_sha256,
            self.registry_sha256,
            *(item.digest for item in self.workflows),
            *(item.digest for item in self.artifacts),
            *(item.digest for item in self.runtimes),
            *(item.digest for item in self.fault_matrices),
            *(item.digest for item in self.reviews),
        ]
        if self.owner_decision is not None:
            required_inputs.append(self.owner_decision.digest)
        _require_provenance_inputs(
            self.provenance, required_inputs, "Gate evidence index"
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GateEvidenceIndex":
        body = cls._contract_payload(payload)
        for field_name in (
            "required_workflow_ids",
            "required_artifact_kinds",
            "required_runtime_ids",
            "required_fault_matrix_ids",
            "required_review_perspectives",
        ):
            body[field_name] = tuple(body[field_name])
        body["workflows"] = tuple(
            WorkflowRunEvidence.from_dict(item) for item in body["workflows"]
        )
        body["artifacts"] = tuple(
            ArtifactEvidence.from_dict(item) for item in body["artifacts"]
        )
        body["runtimes"] = tuple(
            RuntimeEnvelopeEvidence.from_dict(item) for item in body["runtimes"]
        )
        body["fault_matrices"] = tuple(
            FaultMatrixEvidence.from_dict(item) for item in body["fault_matrices"]
        )
        body["reviews"] = tuple(
            ReviewEvidence.from_dict(item) for item in body["reviews"]
        )
        if body["owner_decision"] is not None:
            body["owner_decision"] = OwnerDecisionEvidence.from_dict(
                body["owner_decision"]
            )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)

    def mechanical_blockers(
        self,
        *,
        current_revision: str,
        current_tree_revision: str,
        now: datetime,
    ) -> tuple[str, ...]:
        """Derive exact-head blockers without authenticating external systems."""

        current = _revision(current_revision, "current_revision")
        current_tree = _revision(current_tree_revision, "current_tree_revision")
        instant = now.astimezone(timezone.utc)
        blockers: list[str] = []
        if self.source_revision != current:
            blockers.append("index:foreign-source-revision")
        if self.source_tree_revision != current_tree:
            blockers.append("index:foreign-source-tree")
        generated = _parse_time(self.generated_at)
        if generated > instant:
            blockers.append("index:generated-in-future")
        if instant >= _parse_time(self.expires_at):
            blockers.append("index:expired")

        workflows = {item.workflow_id: item for item in self.workflows}
        for workflow_id in self.required_workflow_ids:
            item = workflows.get(workflow_id)
            if item is None:
                blockers.append(f"workflow:{workflow_id}:missing")
                continue
            if item.source_revision != current:
                blockers.append(f"workflow:{workflow_id}:foreign-source-revision")
            if item.conclusion != "success":
                blockers.append(f"workflow:{workflow_id}:conclusion-{item.conclusion}")
            if instant >= _parse_time(item.expires_at):
                blockers.append(f"workflow:{workflow_id}:expired")

        artifacts = {item.artifact_kind: item for item in self.artifacts}
        for artifact_kind in self.required_artifact_kinds:
            item = artifacts.get(artifact_kind)
            if item is None:
                blockers.append(f"artifact:{artifact_kind}:missing")
                continue
            if item.source_revision != current:
                blockers.append(f"artifact:{artifact_kind}:foreign-source-revision")
            if item.source_tree_revision != current_tree:
                blockers.append(f"artifact:{artifact_kind}:foreign-source-tree")

        runtimes = {item.runtime_id: item for item in self.runtimes}
        for runtime_id in self.required_runtime_ids:
            item = runtimes.get(runtime_id)
            if item is None:
                blockers.append(f"runtime:{runtime_id}:missing")
                continue
            if item.source_revision != current:
                blockers.append(f"runtime:{runtime_id}:foreign-source-revision")
            if item.authority != "live-runtime":
                blockers.append(f"runtime:{runtime_id}:non-live-authority")
            if item.status != "passed":
                blockers.append(f"runtime:{runtime_id}:status-{item.status}")
            if instant >= _parse_time(item.expires_at):
                blockers.append(f"runtime:{runtime_id}:expired")

        fault_matrices = {item.matrix_id: item for item in self.fault_matrices}
        for matrix_id in self.required_fault_matrix_ids:
            item = fault_matrices.get(matrix_id)
            if item is None:
                blockers.append(f"fault-matrix:{matrix_id}:missing")
                continue
            if item.source_revision != current:
                blockers.append(f"fault-matrix:{matrix_id}:foreign-source-revision")
            if item.status != "passed":
                blockers.append(f"fault-matrix:{matrix_id}:status-{item.status}")

        by_perspective: dict[str, list[ReviewEvidence]] = {}
        for review in self.reviews:
            by_perspective.setdefault(review.perspective, []).append(review)
        for perspective in self.required_review_perspectives:
            candidates = by_perspective.get(perspective, [])
            if not candidates:
                blockers.append(f"review:{perspective}:missing")
                continue
            if any(review.source_revision != current for review in candidates):
                blockers.append(f"review:{perspective}:foreign-source-revision")
            if any(review.unresolved_finding_ids for review in candidates):
                blockers.append(f"review:{perspective}:unresolved-findings")
            hard_pass = any(
                review.assurance == "human"
                and review.verdict == "passed"
                and not review.unresolved_finding_ids
                and review.source_revision == current
                for review in candidates
            )
            if not hard_pass:
                blockers.append(f"review:{perspective}:no-human-pass")
            if any(review.verdict == "changes-requested" for review in candidates):
                blockers.append(f"review:{perspective}:changes-requested")

        if self.owner_decision is None:
            blockers.append("owner-decision:missing")
        elif self.owner_decision.source_revision != current:
            blockers.append("owner-decision:foreign-source-revision")

        return tuple(sorted(set(blockers)))

    @property
    def schema(self) -> str:
        return _GATE_EVIDENCE_SCHEMA


__all__ = [
    "ArtifactEvidence",
    "FaultMatrixEvidence",
    "GateEvidenceIndex",
    "OwnerDecisionEvidence",
    "ReviewEvidence",
    "RuntimeEnvelopeEvidence",
    "WorkflowRunEvidence",
]

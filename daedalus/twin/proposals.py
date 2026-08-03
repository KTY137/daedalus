"""Canonical graph-proposal contracts and a non-mutating deterministic verifier.

A proposal is a hypothesis bound to one exact FourfoldSnapshot and one bounded
semantic scope.  Construction proves only canonical identity.  Verification
checks retained evidence, revision, endpoints, relation policy, scope and
operation conflicts; it never edits a snapshot or upgrades evidence itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, Mapping, Sequence

from ..schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _non_empty,
    _record_payload,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
)
from ..spine.envelope import canonical_sha
from .contracts import FOURFOLD_PLANES, CrossPlaneBinding, FourfoldSnapshot

_OPERATION_KINDS = frozenset(
    {"add_binding", "remove_binding", "rename_concept", "replace_relation"}
)
_VERDICTS = frozenset({"accepted", "rejected"})
_PLANE_SET = frozenset(FOURFOLD_PLANES)


def _node_id(value: Any, name: str) -> str:
    text = _non_empty(value, name, max_length=2000)
    if "\x00" in text:
        raise ValueError(f"{name} contains a NUL byte")
    return text


def _optional_node_id(value: Any, name: str) -> str | None:
    return None if value is None else _node_id(value, name)


def _optional_identifier(value: Any, name: str) -> str | None:
    return None if value is None else _identifier(value, name)


def _optional_sha256(value: Any, name: str) -> str | None:
    return None if value is None else _sha256(value, name)


def _plane(value: Any, name: str) -> str:
    if value not in _PLANE_SET:
        raise ValueError(f"{name} must be one of {FOURFOLD_PLANES}")
    return str(value)


@dataclass(frozen=True)
class GraphWritableScope:
    """Exact semantic endpoints and operation families a proposal may touch."""

    planes: tuple[str, ...]
    node_ids: tuple[str, ...]
    relations: tuple[str, ...]
    allow_new_bindings: bool = False
    allow_removals: bool = False
    allow_renames: bool = False
    allow_relation_replacement: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.planes, (str, bytes)):
            raise ValueError("scope.planes must be a sequence")
        planes = tuple(_plane(item, "scope.planes[]") for item in self.planes)
        if not planes:
            raise ValueError("scope.planes must not be empty")
        if planes != tuple(sorted(set(planes))):
            raise ValueError("scope.planes must be unique and sorted")
        object.__setattr__(self, "planes", planes)

        if isinstance(self.node_ids, (str, bytes)):
            raise ValueError("scope.node_ids must be a sequence")
        node_ids = tuple(_node_id(item, "scope.node_ids[]") for item in self.node_ids)
        if not node_ids or node_ids != tuple(sorted(set(node_ids))):
            raise ValueError("scope.node_ids must be non-empty, unique and sorted")
        object.__setattr__(self, "node_ids", node_ids)
        object.__setattr__(
            self,
            "relations",
            _sorted_strings(self.relations, "scope.relations", identifiers=True),
        )
        for field_name in (
            "allow_new_bindings",
            "allow_removals",
            "allow_renames",
            "allow_relation_replacement",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"scope.{field_name} must be an exact boolean")
        if not any(
            (
                self.allow_new_bindings,
                self.allow_removals,
                self.allow_renames,
                self.allow_relation_replacement,
            )
        ):
            raise ValueError("scope must permit at least one operation family")

    def to_dict(self) -> dict[str, Any]:
        return {
            "planes": list(self.planes),
            "node_ids": list(self.node_ids),
            "relations": list(self.relations),
            "allow_new_bindings": self.allow_new_bindings,
            "allow_removals": self.allow_removals,
            "allow_renames": self.allow_renames,
            "allow_relation_replacement": self.allow_relation_replacement,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GraphWritableScope":
        body = _record_payload(cls, payload, "graph writable scope")
        for field_name in ("planes", "node_ids", "relations"):
            value = body.get(field_name)
            if not isinstance(value, list):
                raise ValueError(f"scope.{field_name} must be an array")
            body[field_name] = tuple(value)
        return cls(**body)


@dataclass(frozen=True)
class GraphOperation:
    """One member of the deliberately small GraphOperation tagged union."""

    operation_id: str
    kind: str
    source_plane: str
    source_node_id: str
    target_plane: str | None = None
    target_node_id: str | None = None
    relation: str | None = None
    replacement: str | None = None
    binding_sha256: str | None = None
    evidence_sha256s: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "operation_id", _identifier(self.operation_id, "operation_id")
        )
        if self.kind not in _OPERATION_KINDS:
            raise ValueError(f"operation.kind must be one of {sorted(_OPERATION_KINDS)}")
        object.__setattr__(
            self, "source_plane", _plane(self.source_plane, "source_plane")
        )
        object.__setattr__(
            self, "source_node_id", _node_id(self.source_node_id, "source_node_id")
        )
        if self.target_plane is not None:
            object.__setattr__(
                self, "target_plane", _plane(self.target_plane, "target_plane")
            )
        object.__setattr__(
            self,
            "target_node_id",
            _optional_node_id(self.target_node_id, "target_node_id"),
        )
        object.__setattr__(
            self, "relation", _optional_identifier(self.relation, "relation")
        )
        if self.replacement is not None:
            replacement = _non_empty(self.replacement, "replacement", max_length=1000)
            if "\x00" in replacement:
                raise ValueError("replacement contains a NUL byte")
            object.__setattr__(self, "replacement", replacement)
        object.__setattr__(
            self,
            "binding_sha256",
            _optional_sha256(self.binding_sha256, "binding_sha256"),
        )
        object.__setattr__(
            self,
            "evidence_sha256s",
            _sorted_strings(
                self.evidence_sha256s, "evidence_sha256s", digests=True
            ),
        )
        if not self.evidence_sha256s:
            raise ValueError("every graph operation must retain evidence digests")

        has_target = self.target_plane is not None and self.target_node_id is not None
        if (self.target_plane is None) != (self.target_node_id is None):
            raise ValueError("target_plane and target_node_id must appear together")
        if has_target and self.target_plane == self.source_plane:
            raise ValueError("binding operations must cross semantic planes")

        if self.kind == "add_binding":
            if not has_target or self.relation is None:
                raise ValueError("add_binding requires target endpoint and relation")
            if self.replacement is not None or self.binding_sha256 is not None:
                raise ValueError(
                    "add_binding must not carry replacement or binding_sha256"
                )
        elif self.kind == "remove_binding":
            if not has_target or self.relation is None or self.binding_sha256 is None:
                raise ValueError(
                    "remove_binding requires target, relation and binding_sha256"
                )
            if self.replacement is not None:
                raise ValueError("remove_binding must not carry replacement")
        elif self.kind == "rename_concept":
            if has_target or self.relation is not None or self.binding_sha256 is not None:
                raise ValueError(
                    "rename_concept must name only one source concept"
                )
            if self.replacement is None:
                raise ValueError("rename_concept requires replacement")
        elif self.kind == "replace_relation":
            if (
                not has_target
                or self.relation is None
                or self.replacement is None
                or self.binding_sha256 is None
            ):
                raise ValueError(
                    "replace_relation requires target, old/new relation and binding digest"
                )
            _identifier(self.replacement, "replacement relation")
            if self.replacement == self.relation:
                raise ValueError("replacement relation must differ from current relation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "source_plane": self.source_plane,
            "source_node_id": self.source_node_id,
            "target_plane": self.target_plane,
            "target_node_id": self.target_node_id,
            "relation": self.relation,
            "replacement": self.replacement,
            "binding_sha256": self.binding_sha256,
            "evidence_sha256s": list(self.evidence_sha256s),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GraphOperation":
        body = _record_payload(cls, payload, "graph operation")
        evidence = body.get("evidence_sha256s")
        if not isinstance(evidence, list):
            raise ValueError("graph operation evidence_sha256s must be an array")
        body["evidence_sha256s"] = tuple(evidence)
        return cls(**body)


@dataclass(frozen=True)
class GraphProposal(CanonicalContract):
    """A revision-bound hypothesis with no mutation or publication authority."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.graph-proposal"

    proposal_id: str
    base_snapshot_sha256: str
    source_revision: str
    objective: str
    model_manifest_sha256: str
    runtime_manifest_sha256: str
    context_capsule_sha256: str
    budget_microusd: int
    scope: GraphWritableScope
    operations: tuple[GraphOperation, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proposal_id", _identifier(self.proposal_id, "proposal_id")
        )
        for field_name in (
            "base_snapshot_sha256",
            "model_manifest_sha256",
            "runtime_manifest_sha256",
            "context_capsule_sha256",
        ):
            object.__setattr__(
                self, field_name, _sha256(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self, "objective", _non_empty(self.objective, "objective", max_length=4000)
        )
        if (
            isinstance(self.budget_microusd, bool)
            or not isinstance(self.budget_microusd, int)
            or self.budget_microusd <= 0
        ):
            raise ValueError("budget_microusd must be a positive integer")
        if not isinstance(self.scope, GraphWritableScope):
            raise ValueError("scope must be a GraphWritableScope")
        if not isinstance(self.operations, tuple):
            object.__setattr__(self, "operations", tuple(self.operations))
        if not self.operations or any(
            not isinstance(item, GraphOperation) for item in self.operations
        ):
            raise ValueError("operations must contain GraphOperation records")
        operation_ids = tuple(item.operation_id for item in self.operations)
        if operation_ids != tuple(sorted(set(operation_ids))):
            raise ValueError("operations must be unique and sorted by operation_id")
        digests = tuple(item.digest for item in self.operations)
        if len(set(digests)) != len(digests):
            raise ValueError("operations must not contain duplicate payloads")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("proposal source_revision must match provenance")
        _require_provenance_inputs(
            self.provenance,
            (
                self.base_snapshot_sha256,
                self.model_manifest_sha256,
                self.runtime_manifest_sha256,
                self.context_capsule_sha256,
                self.scope.digest,
                *(item.digest for item in self.operations),
            ),
            "graph proposal",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "proposal_id": self.proposal_id,
            "base_snapshot_sha256": self.base_snapshot_sha256,
            "source_revision": self.source_revision,
            "objective": self.objective,
            "model_manifest_sha256": self.model_manifest_sha256,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "context_capsule_sha256": self.context_capsule_sha256,
            "budget_microusd": self.budget_microusd,
            "scope": self.scope.to_dict(),
            "operations": [item.to_dict() for item in self.operations],
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GraphProposal":
        body = cls._contract_payload(payload)
        if not isinstance(body.get("scope"), Mapping):
            raise ValueError("graph proposal scope must be an object")
        operations = body.get("operations")
        if not isinstance(operations, list):
            raise ValueError("graph proposal operations must be an array")
        if not isinstance(body.get("provenance"), Mapping):
            raise ValueError("graph proposal provenance must be an object")
        body["scope"] = GraphWritableScope.from_dict(body["scope"])
        body["operations"] = tuple(GraphOperation.from_dict(item) for item in operations)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class OperationDecision:
    operation_id: str
    operation_sha256: str
    verdict: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "operation_id", _identifier(self.operation_id, "operation_id")
        )
        object.__setattr__(
            self,
            "operation_sha256",
            _sha256(self.operation_sha256, "operation_sha256"),
        )
        if self.verdict not in _VERDICTS:
            raise ValueError("decision verdict must be accepted or rejected")
        object.__setattr__(
            self, "reasons", _sorted_strings(self.reasons, "decision.reasons", identifiers=True)
        )
        if not self.reasons:
            raise ValueError("decision reasons must not be empty")
        if self.verdict == "accepted" and self.reasons != ("verified",):
            raise ValueError("accepted decisions must use the exact verified reason")
        if self.verdict == "rejected" and self.reasons == ("verified",):
            raise ValueError("rejected decisions cannot use the verified reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_sha256": self.operation_sha256,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationDecision":
        body = _record_payload(cls, payload, "operation decision")
        reasons = body.get("reasons")
        if not isinstance(reasons, list):
            raise ValueError("decision reasons must be an array")
        body["reasons"] = tuple(reasons)
        return cls(**body)


@dataclass(frozen=True)
class ProposalVerificationReport(CanonicalContract):
    """Deterministic verifier output; accepted operations are still not applied."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.proposal-verification-report"

    proposal_sha256: str
    base_snapshot_sha256: str
    source_revision: str
    verifier_id: str
    verifier_policy_sha256: str
    decisions: tuple[OperationDecision, ...]
    all_accepted: bool
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for field_name in (
            "proposal_sha256",
            "base_snapshot_sha256",
            "verifier_policy_sha256",
        ):
            object.__setattr__(
                self, field_name, _sha256(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self, "verifier_id", _identifier(self.verifier_id, "verifier_id")
        )
        if not isinstance(self.decisions, tuple):
            object.__setattr__(self, "decisions", tuple(self.decisions))
        if not self.decisions or any(
            not isinstance(item, OperationDecision) for item in self.decisions
        ):
            raise ValueError("decisions must contain OperationDecision records")
        ids = tuple(item.operation_id for item in self.decisions)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("decisions must be unique and sorted by operation_id")
        if type(self.all_accepted) is not bool:
            raise ValueError("all_accepted must be an exact boolean")
        derived = all(item.verdict == "accepted" for item in self.decisions)
        if self.all_accepted is not derived:
            raise ValueError("all_accepted must be derived from decisions")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("verification source_revision must match provenance")
        _require_provenance_inputs(
            self.provenance,
            (
                self.proposal_sha256,
                self.base_snapshot_sha256,
                self.verifier_policy_sha256,
                canonical_sha({"verifier_id": self.verifier_id}),
                *(item.digest for item in self.decisions),
            ),
            "proposal verification report",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "proposal_sha256": self.proposal_sha256,
            "base_snapshot_sha256": self.base_snapshot_sha256,
            "source_revision": self.source_revision,
            "verifier_id": self.verifier_id,
            "verifier_policy_sha256": self.verifier_policy_sha256,
            "decisions": [item.to_dict() for item in self.decisions],
            "all_accepted": self.all_accepted,
            "provenance": self.provenance.to_dict(),
        }

    @property
    def accepted_operation_sha256s(self) -> tuple[str, ...]:
        return tuple(
            item.operation_sha256
            for item in self.decisions
            if item.verdict == "accepted"
        )

    @property
    def rejected_operation_sha256s(self) -> tuple[str, ...]:
        return tuple(
            item.operation_sha256
            for item in self.decisions
            if item.verdict == "rejected"
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProposalVerificationReport":
        body = cls._contract_payload(payload)
        decisions = body.get("decisions")
        if not isinstance(decisions, list):
            raise ValueError("verification decisions must be an array")
        if not isinstance(body.get("provenance"), Mapping):
            raise ValueError("verification provenance must be an object")
        body["decisions"] = tuple(
            OperationDecision.from_dict(item) for item in decisions
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def _binding_matches(operation: GraphOperation, binding: CrossPlaneBinding) -> bool:
    return (
        operation.binding_sha256 == binding.digest
        and operation.source_plane == binding.source_plane
        and operation.source_node_id == binding.source_node_id
        and operation.target_plane == binding.target_plane
        and operation.target_node_id == binding.target_node_id
        and operation.relation == binding.relation
    )


def _operation_resources(
    operation: GraphOperation,
    binding_by_digest: Mapping[str, CrossPlaneBinding],
) -> frozenset[tuple[str, ...]]:
    resources: set[tuple[str, ...]] = set()
    if operation.kind == "rename_concept":
        resources.add(("node", operation.source_plane, operation.source_node_id))
        return frozenset(resources)
    semantic = (
        "binding",
        operation.source_plane,
        operation.source_node_id,
        str(operation.target_plane),
        str(operation.target_node_id),
        str(operation.relation),
    )
    resources.add(semantic)
    if operation.binding_sha256 is not None:
        resources.add(("binding-digest", operation.binding_sha256))
        binding = binding_by_digest.get(operation.binding_sha256)
        if binding is not None:
            resources.add(
                (
                    "binding",
                    binding.source_plane,
                    binding.source_node_id,
                    binding.target_plane,
                    binding.target_node_id,
                    binding.relation,
                )
            )
    if operation.kind == "replace_relation" and operation.replacement is not None:
        resources.add(
            (
                "binding",
                operation.source_plane,
                operation.source_node_id,
                str(operation.target_plane),
                str(operation.target_node_id),
                operation.replacement,
            )
        )
    return frozenset(resources)


def verify_graph_proposal(
    proposal: GraphProposal,
    snapshot: FourfoldSnapshot,
    *,
    verified_evidence_sha256s: Iterable[str],
    allowed_relations: Sequence[str],
    verifier_id: str,
    verifier_policy_sha256: str,
    created_at: str,
    trace_id: str | None = None,
) -> ProposalVerificationReport:
    """Verify a proposal without mutating the supplied FourfoldSnapshot."""

    if not isinstance(proposal, GraphProposal):
        raise ValueError("proposal must be a GraphProposal")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise ValueError("snapshot must be a FourfoldSnapshot")
    verified = frozenset(
        _sorted_strings(
            tuple(verified_evidence_sha256s),
            "verified_evidence_sha256s",
            digests=True,
        )
    )
    relation_policy = frozenset(
        _sorted_strings(allowed_relations, "allowed_relations", identifiers=True)
    )
    verifier = _identifier(verifier_id, "verifier_id")
    policy_digest = _sha256(verifier_policy_sha256, "verifier_policy_sha256")

    plane_nodes = {
        plane.plane: frozenset(plane.node_ids) for plane in snapshot.planes
    }
    binding_by_digest = {item.digest: item for item in snapshot.bindings}
    binding_semantic_keys = {item.semantic_key for item in snapshot.bindings}

    conflicts: dict[str, set[str]] = {
        operation.operation_id: set() for operation in proposal.operations
    }
    resources = {
        operation.operation_id: _operation_resources(operation, binding_by_digest)
        for operation in proposal.operations
    }
    for index, left in enumerate(proposal.operations):
        for right in proposal.operations[index + 1 :]:
            conflict = bool(
                resources[left.operation_id].intersection(resources[right.operation_id])
            )
            if left.kind == "rename_concept" or right.kind == "rename_concept":
                left_nodes = {
                    left.source_node_id,
                    *(() if left.target_node_id is None else (left.target_node_id,)),
                }
                right_nodes = {
                    right.source_node_id,
                    *(() if right.target_node_id is None else (right.target_node_id,)),
                }
                conflict = conflict or bool(left_nodes.intersection(right_nodes))
            if conflict:
                conflicts[left.operation_id].add("conflicting-operation")
                conflicts[right.operation_id].add("conflicting-operation")

    decisions: list[OperationDecision] = []
    for operation in proposal.operations:
        reasons = set(conflicts[operation.operation_id])
        if proposal.base_snapshot_sha256 != snapshot.digest:
            reasons.add("stale-base-snapshot")
        if proposal.source_revision != snapshot.source_revision:
            reasons.add("stale-source-revision")
        if not set(operation.evidence_sha256s).issubset(verified):
            reasons.add("unverified-evidence")

        scope = proposal.scope
        if operation.source_plane not in scope.planes:
            reasons.add("source-plane-outside-scope")
        if operation.source_node_id not in scope.node_ids:
            reasons.add("source-node-outside-scope")
        if operation.source_node_id not in plane_nodes[operation.source_plane]:
            reasons.add("source-node-missing")
        if operation.target_plane is not None:
            if operation.target_plane not in scope.planes:
                reasons.add("target-plane-outside-scope")
            if operation.target_node_id not in scope.node_ids:
                reasons.add("target-node-outside-scope")
            if operation.target_node_id not in plane_nodes[operation.target_plane]:
                reasons.add("target-node-missing")

        if operation.kind == "add_binding":
            if not scope.allow_new_bindings:
                reasons.add("add-binding-not-permitted")
            if operation.relation not in relation_policy:
                reasons.add("relation-not-allowed")
            if operation.relation not in scope.relations:
                reasons.add("relation-outside-scope")
            semantic_key = (
                operation.source_plane,
                operation.source_node_id,
                str(operation.target_plane),
                str(operation.target_node_id),
                str(operation.relation),
                proposal.source_revision,
            )
            if semantic_key in binding_semantic_keys:
                reasons.add("binding-already-exists")
        elif operation.kind == "remove_binding":
            if not scope.allow_removals:
                reasons.add("removal-not-permitted")
            if operation.relation not in relation_policy:
                reasons.add("relation-not-allowed")
            if operation.relation not in scope.relations:
                reasons.add("relation-outside-scope")
            binding = binding_by_digest.get(str(operation.binding_sha256))
            if binding is None:
                reasons.add("binding-missing")
            elif not _binding_matches(operation, binding):
                reasons.add("binding-identity-mismatch")
        elif operation.kind == "rename_concept":
            if not scope.allow_renames:
                reasons.add("rename-not-permitted")
            if operation.replacement == operation.source_node_id:
                reasons.add("rename-is-no-op")
        elif operation.kind == "replace_relation":
            if not scope.allow_relation_replacement:
                reasons.add("relation-replacement-not-permitted")
            if operation.relation not in relation_policy:
                reasons.add("relation-not-allowed")
            if operation.relation not in scope.relations:
                reasons.add("relation-outside-scope")
            if operation.replacement not in scope.relations:
                reasons.add("replacement-relation-outside-scope")
            if operation.replacement not in relation_policy:
                reasons.add("replacement-relation-not-allowed")
            binding = binding_by_digest.get(str(operation.binding_sha256))
            if binding is None:
                reasons.add("binding-missing")
            elif not _binding_matches(operation, binding):
                reasons.add("binding-identity-mismatch")
            replacement_key = (
                operation.source_plane,
                operation.source_node_id,
                str(operation.target_plane),
                str(operation.target_node_id),
                str(operation.replacement),
                proposal.source_revision,
            )
            if replacement_key in binding_semantic_keys:
                reasons.add("replacement-binding-already-exists")

        if reasons:
            decision = OperationDecision(
                operation_id=operation.operation_id,
                operation_sha256=operation.digest,
                verdict="rejected",
                reasons=tuple(sorted(reasons)),
            )
        else:
            decision = OperationDecision(
                operation_id=operation.operation_id,
                operation_sha256=operation.digest,
                verdict="accepted",
                reasons=("verified",),
            )
        decisions.append(decision)

    decision_tuple = tuple(decisions)
    provenance = ContractProvenance(
        origin="daedalus.twin.graph-proposal-verifier",
        source_revision=snapshot.source_revision,
        created_at=created_at,
        input_digests=tuple(
            {
                proposal.digest,
                snapshot.digest,
                policy_digest,
                canonical_sha({"verifier_id": verifier}),
                *(item.digest for item in decision_tuple),
            }
        ),
        trace_id=trace_id,
    )
    return ProposalVerificationReport(
        proposal_sha256=proposal.digest,
        base_snapshot_sha256=snapshot.digest,
        source_revision=snapshot.source_revision,
        verifier_id=verifier,
        verifier_policy_sha256=policy_digest,
        decisions=decision_tuple,
        all_accepted=all(item.verdict == "accepted" for item in decision_tuple),
        provenance=provenance,
    )


def require_graph_proposal_verification(
    report: ProposalVerificationReport,
    proposal: GraphProposal,
    snapshot: FourfoldSnapshot,
    *,
    verified_evidence_sha256s: Iterable[str],
    allowed_relations: Sequence[str],
    expected_verifier_id: str,
    expected_verifier_policy_sha256: str,
) -> None:
    """Recompute a report under caller-owned verifier authority and compare it."""

    if not isinstance(report, ProposalVerificationReport):
        raise ValueError("report must be a ProposalVerificationReport")
    verifier = _identifier(expected_verifier_id, "expected_verifier_id")
    policy = _sha256(
        expected_verifier_policy_sha256,
        "expected_verifier_policy_sha256",
    )
    if report.verifier_id != verifier:
        raise ValueError("proposal verification report uses an unexpected verifier")
    if report.verifier_policy_sha256 != policy:
        raise ValueError("proposal verification report uses an unexpected policy")
    expected = verify_graph_proposal(
        proposal,
        snapshot,
        verified_evidence_sha256s=verified_evidence_sha256s,
        allowed_relations=allowed_relations,
        verifier_id=verifier,
        verifier_policy_sha256=policy,
        created_at=report.provenance.created_at,
        trace_id=report.provenance.trace_id,
    )
    if report != expected:
        raise ValueError(
            "proposal verification report does not match recomputed verification"
        )


def parse_graph_proposal(payload: Mapping[str, Any]) -> GraphProposal:
    value = GraphProposal.from_dict(payload)
    if dict(payload) != value.to_dict():
        raise ValueError("graph proposal wire is not canonical")
    return value


def parse_proposal_verification_report(
    payload: Mapping[str, Any],
) -> ProposalVerificationReport:
    value = ProposalVerificationReport.from_dict(payload)
    if dict(payload) != value.to_dict():
        raise ValueError("proposal verification report wire is not canonical")
    return value


__all__ = [
    "GraphOperation",
    "GraphProposal",
    "GraphWritableScope",
    "OperationDecision",
    "ProposalVerificationReport",
    "parse_graph_proposal",
    "require_graph_proposal_verification",
    "parse_proposal_verification_report",
    "verify_graph_proposal",
]

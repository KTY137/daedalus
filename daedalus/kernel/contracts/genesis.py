"""Canonical, inert contracts for the owner-directed Genesis product strand.

These records describe the artifact chain from an advisory build-intent
proposal to a deployment receipt.  They grant no effects, execute no tools,
persist no parallel ledger, and never promote or publish a candidate.  Runtime
authority remains with policy decisions, effect leases, evidence verification,
and one-use owner approval in the canonical kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, Sequence

from .canonical import (
    CanonicalContract,
    ContractProvenance,
    ResourceBudget,
    _egress_endpoint,
    _freeze_json,
    _identifier,
    _non_empty,
    _record_payload,
    _register_kernel_contract_types,
    _repo_path,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
)
from daedalus.kernel.artifacts import ArtifactRef


def _common_identity(
    value: CanonicalContract,
    *,
    label: str,
    identifier_fields: Sequence[str],
) -> None:
    for name in identifier_fields:
        object.__setattr__(value, name, _identifier(getattr(value, name), name))
    source_revision = _revision(value.source_revision, "source_revision")
    object.__setattr__(value, "source_revision", source_revision)
    if not isinstance(value.provenance, ContractProvenance):
        raise ValueError(f"{label} provenance must be ContractProvenance")
    if value.provenance.source_revision != source_revision:
        raise ValueError(
            f"{label} source_revision must match provenance.source_revision"
        )


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _frozen_object(
    value: Any,
    name: str,
    *,
    allow_empty: bool = True,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    frozen = _freeze_json(value, name)
    if not isinstance(frozen, Mapping):  # defensive: Mapping went in
        raise ValueError(f"{name} must be an object")
    if not allow_empty and not frozen:
        raise ValueError(f"{name} must not be empty")
    return frozen


def _text_mapping(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _identifier(raw_key, f"{name} key")
        if key in normalized:
            raise ValueError(f"{name} contains duplicate key {key!r}")
        normalized[key] = _non_empty(
            raw_value, f"{name}.{key}", max_length=1000
        )
    if not allow_empty and not normalized:
        raise ValueError(f"{name} must not be empty")
    return MappingProxyType(dict(sorted(normalized.items())))


def _boolean_mapping(value: Any, name: str) -> Mapping[str, bool]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    normalized: dict[str, bool] = {}
    for raw_key, raw_value in value.items():
        key = _identifier(raw_key, f"{name} key")
        if key in normalized:
            raise ValueError(f"{name} contains duplicate key {key!r}")
        normalized[key] = _boolean(raw_value, f"{name}.{key}")
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return MappingProxyType(dict(sorted(normalized.items())))


def _command(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be an argv sequence, not a string")
    argv = tuple(
        _non_empty(part, f"{name}[{index}]", max_length=1000)
        for index, part in enumerate(value)
    )
    if not argv:
        raise ValueError(f"{name} must not be empty")
    return argv


def _artifact(value: Any, name: str) -> ArtifactRef:
    if isinstance(value, ArtifactRef):
        return value
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an ArtifactRef object")
    if set(value) != {"sha256", "locator"}:
        raise ValueError(f"{name} must contain exactly sha256 and locator")
    return ArtifactRef(sha256=value["sha256"], locator=value["locator"])


def _optional_sha256(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, name)


def _optional_text(value: Any, name: str, *, identifier: bool = False) -> str | None:
    if value is None:
        return None
    if identifier:
        return _identifier(value, name)
    return _non_empty(value, name, max_length=2000)


@dataclass(frozen=True)
class GenesisAutonomyPolicy(CanonicalContract):
    """Versioned owner policy that bounds deterministic Genesis admission."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.genesis-autonomy-policy"

    policy_id: str
    policy_version: str
    source_revision: str
    defaults: Mapping[str, Any]
    allowed_targets: tuple[str, ...]
    default_target: str
    budget: ResourceBudget
    max_files: int
    max_bytes: int
    max_repairs: int
    allow_isolated_preview: bool
    public_release_requires_owner_approval: bool
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="Genesis autonomy policy",
            identifier_fields=("policy_id",),
        )
        object.__setattr__(
            self,
            "policy_version",
            _non_empty(self.policy_version, "policy_version", max_length=100),
        )
        object.__setattr__(
            self,
            "defaults",
            _frozen_object(self.defaults, "defaults", allow_empty=False),
        )
        object.__setattr__(
            self,
            "allowed_targets",
            _sorted_strings(self.allowed_targets, "allowed_targets", identifiers=True),
        )
        if not self.allowed_targets:
            raise ValueError("Genesis autonomy policy must allow at least one target")
        object.__setattr__(
            self, "default_target", _identifier(self.default_target, "default_target")
        )
        if self.default_target not in self.allowed_targets:
            raise ValueError("default_target must be present in allowed_targets")
        if not isinstance(self.budget, ResourceBudget):
            raise ValueError("Genesis autonomy policy budget must be ResourceBudget")
        if not self.budget.has_execution_bound:
            raise ValueError(
                "Genesis autonomy policy budget must bound tokens, cost, or wall time"
            )
        object.__setattr__(self, "max_files", _positive_integer(self.max_files, "max_files"))
        object.__setattr__(self, "max_bytes", _positive_integer(self.max_bytes, "max_bytes"))
        object.__setattr__(
            self, "max_repairs", _non_negative_integer(self.max_repairs, "max_repairs")
        )
        _boolean(self.allow_isolated_preview, "allow_isolated_preview")
        if self.public_release_requires_owner_approval is not True:
            raise ValueError("public Genesis release must require owner approval")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GenesisAutonomyPolicy":
        body = cls._contract_payload(payload)
        body["budget"] = ResourceBudget.from_dict(body["budget"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class BuildIntentProposal(CanonicalContract):
    """Structured runtime suggestion; always advisory and never authority."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.build-intent-proposal"

    proposal_id: str
    lineage_id: str
    source_revision: str
    prompt: str
    target: str | None
    stack: str | None
    advisory: bool
    runtime_manifest_sha256: str
    provenance: ContractProvenance
    assumptions: tuple[str, ...] = ()
    requested_features: tuple[str, ...] = ()
    target_required: bool = False
    stack_required: bool = False

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="build intent proposal",
            identifier_fields=("proposal_id", "lineage_id"),
        )
        object.__setattr__(self, "prompt", _non_empty(self.prompt, "prompt", max_length=16000))
        object.__setattr__(
            self, "target", _optional_text(self.target, "target", identifier=True)
        )
        object.__setattr__(self, "stack", _optional_text(self.stack, "stack"))
        if self.advisory is not True:
            raise ValueError("BuildIntentProposal must remain advisory")
        object.__setattr__(
            self,
            "runtime_manifest_sha256",
            _sha256(self.runtime_manifest_sha256, "runtime_manifest_sha256"),
        )
        object.__setattr__(
            self, "assumptions", _sorted_strings(self.assumptions, "assumptions")
        )
        object.__setattr__(
            self,
            "requested_features",
            _sorted_strings(self.requested_features, "requested_features"),
        )
        _boolean(self.target_required, "target_required")
        _boolean(self.stack_required, "stack_required")
        if self.target_required and self.target is None:
            raise ValueError("target_required proposal must name a target")
        if self.stack_required and self.stack is None:
            raise ValueError("stack_required proposal must name a stack")
        _require_provenance_inputs(
            self.provenance,
            (self.runtime_manifest_sha256,),
            "build intent proposal",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BuildIntentProposal":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class ProductSpec(CanonicalContract):
    """Authoritative admitted product request with an explicit absent base."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.product-spec"

    product_id: str
    lineage_id: str
    source_revision: str
    name: str
    summary: str
    target: str
    audience: str
    features: tuple[str, ...]
    constraints: tuple[str, ...]
    base_repository: str | None
    defaults: Mapping[str, Any]
    policy_sha256: str
    build_intent_proposal_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="product spec",
            identifier_fields=("product_id", "lineage_id"),
        )
        object.__setattr__(self, "name", _non_empty(self.name, "name", max_length=200))
        object.__setattr__(
            self, "summary", _non_empty(self.summary, "summary", max_length=8000)
        )
        object.__setattr__(self, "target", _identifier(self.target, "target"))
        object.__setattr__(
            self, "audience", _non_empty(self.audience, "audience", max_length=1000)
        )
        object.__setattr__(self, "features", _sorted_strings(self.features, "features"))
        if not self.features:
            raise ValueError("product spec must contain at least one feature")
        object.__setattr__(
            self, "constraints", _sorted_strings(self.constraints, "constraints")
        )
        if self.base_repository is not None:
            raise ValueError("Genesis ProductSpec base_repository must be explicit null")
        object.__setattr__(self, "defaults", _frozen_object(self.defaults, "defaults"))
        for name in ("policy_sha256", "build_intent_proposal_sha256"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        _require_provenance_inputs(
            self.provenance,
            (self.policy_sha256, self.build_intent_proposal_sha256),
            "product spec",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProductSpec":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class DesignContract(CanonicalContract):
    """Frozen interaction, accessibility, and visual requirements."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.design-contract"

    design_id: str
    lineage_id: str
    source_revision: str
    product_spec_sha256: str
    interaction_requirements: tuple[str, ...]
    accessibility_requirements: tuple[str, ...]
    visual_contract: Mapping[str, Any]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="design contract",
            identifier_fields=("design_id", "lineage_id"),
        )
        object.__setattr__(
            self,
            "product_spec_sha256",
            _sha256(self.product_spec_sha256, "product_spec_sha256"),
        )
        object.__setattr__(
            self,
            "interaction_requirements",
            _sorted_strings(self.interaction_requirements, "interaction_requirements"),
        )
        if not self.interaction_requirements:
            raise ValueError("design contract must contain interaction requirements")
        object.__setattr__(
            self,
            "accessibility_requirements",
            _sorted_strings(
                self.accessibility_requirements, "accessibility_requirements"
            ),
        )
        object.__setattr__(
            self,
            "visual_contract",
            _frozen_object(self.visual_contract, "visual_contract"),
        )
        _require_provenance_inputs(
            self.provenance, (self.product_spec_sha256,), "design contract"
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DesignContract":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class TargetFourfoldSpec(CanonicalContract):
    """Target requirements for all four atomic Project-Twin planes."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.target-fourfold-spec"

    target_spec_id: str
    lineage_id: str
    source_revision: str
    product_spec_sha256: str
    design_contract_sha256: str
    code_requirements: tuple[str, ...]
    type_requirements: tuple[str, ...]
    data_requirements: tuple[str, ...]
    knowledge_requirements: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="target fourfold spec",
            identifier_fields=("target_spec_id", "lineage_id"),
        )
        for name in ("product_spec_sha256", "design_contract_sha256"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        for name in (
            "code_requirements",
            "type_requirements",
            "data_requirements",
            "knowledge_requirements",
        ):
            normalized = _sorted_strings(getattr(self, name), name)
            if not normalized:
                raise ValueError(f"{name} must represent its Fourfold plane")
            object.__setattr__(self, name, normalized)
        object.__setattr__(
            self,
            "acceptance_criteria",
            _sorted_strings(self.acceptance_criteria, "acceptance_criteria"),
        )
        if not self.acceptance_criteria:
            raise ValueError("target fourfold spec must name acceptance criteria")
        _require_provenance_inputs(
            self.provenance,
            (self.product_spec_sha256, self.design_contract_sha256),
            "target fourfold spec",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TargetFourfoldSpec":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class GraphProposal(CanonicalContract):
    """Advisory graph-operation hypothesis bound to frozen evaluator inputs."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.graph-proposal"

    proposal_id: str
    lineage_id: str
    source_revision: str
    target_fourfold_spec_sha256: str
    runtime_manifest_sha256: str
    context_capsule_sha256: str
    budget: ResourceBudget
    operations: tuple[Mapping[str, Any], ...]
    writable_paths: tuple[str, ...]
    advisory: bool
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="graph proposal",
            identifier_fields=("proposal_id", "lineage_id"),
        )
        for name in (
            "target_fourfold_spec_sha256",
            "runtime_manifest_sha256",
            "context_capsule_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        if not isinstance(self.budget, ResourceBudget) or not self.budget.has_execution_bound:
            raise ValueError("graph proposal must carry a bounded ResourceBudget")
        if isinstance(self.operations, (str, bytes)) or not isinstance(
            self.operations, Sequence
        ):
            raise ValueError("operations must be a sequence of objects")
        operations = tuple(
            _frozen_object(operation, f"operations[{index}]", allow_empty=False)
            for index, operation in enumerate(self.operations)
        )
        if not operations:
            raise ValueError("graph proposal must contain at least one operation")
        object.__setattr__(self, "operations", operations)
        object.__setattr__(
            self,
            "writable_paths",
            _sorted_strings(self.writable_paths, "writable_paths", paths=True),
        )
        if not self.writable_paths:
            raise ValueError("graph proposal must declare bounded writable_paths")
        if self.advisory is not True:
            raise ValueError("GraphProposal must remain advisory until verified")
        _require_provenance_inputs(
            self.provenance,
            (
                self.target_fourfold_spec_sha256,
                self.runtime_manifest_sha256,
                self.context_capsule_sha256,
            ),
            "graph proposal",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GraphProposal":
        body = cls._contract_payload(payload)
        body["budget"] = ResourceBudget.from_dict(body["budget"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class MaterializationPlan(CanonicalContract):
    """Verified graph intent translated into bounded source work items."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.materialization-plan"

    plan_id: str
    lineage_id: str
    source_revision: str
    product_spec_sha256: str
    design_contract_sha256: str
    target_fourfold_spec_sha256: str
    graph_proposal_sha256: str
    input_tree: ArtifactRef
    work_item_ids: tuple[str, ...]
    writable_paths: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    max_files: int
    max_bytes: int
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="materialization plan",
            identifier_fields=("plan_id", "lineage_id"),
        )
        for name in (
            "product_spec_sha256",
            "design_contract_sha256",
            "target_fourfold_spec_sha256",
            "graph_proposal_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(self, "input_tree", _artifact(self.input_tree, "input_tree"))
        object.__setattr__(
            self,
            "work_item_ids",
            _sorted_strings(self.work_item_ids, "work_item_ids", identifiers=True),
        )
        if not self.work_item_ids:
            raise ValueError("materialization plan must name at least one work item")
        for name in ("writable_paths", "expected_outputs"):
            normalized = _sorted_strings(getattr(self, name), name, paths=True)
            if not normalized:
                raise ValueError(f"materialization plan must declare {name}")
            object.__setattr__(self, name, normalized)
        object.__setattr__(self, "max_files", _positive_integer(self.max_files, "max_files"))
        object.__setattr__(self, "max_bytes", _positive_integer(self.max_bytes, "max_bytes"))
        _require_provenance_inputs(
            self.provenance,
            (
                self.product_spec_sha256,
                self.design_contract_sha256,
                self.target_fourfold_spec_sha256,
                self.graph_proposal_sha256,
                self.input_tree.sha256,
            ),
            "materialization plan",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MaterializationPlan":
        body = cls._contract_payload(payload)
        body["input_tree"] = _artifact(body["input_tree"], "input_tree")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class ToolchainManifest(CanonicalContract):
    """Pinned tool versions, lockfiles, commands, egress, and sandbox policy."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.toolchain-manifest"

    manifest_id: str
    lineage_id: str
    source_revision: str
    target: str
    stack: str
    versions: Mapping[str, str]
    required_tools: tuple[str, ...]
    lockfiles: tuple[str, ...]
    build_command: tuple[str, ...]
    test_command: tuple[str, ...]
    run_command: tuple[str, ...]
    package_command: tuple[str, ...]
    licenses: tuple[str, ...]
    egress_endpoints: tuple[str, ...]
    materialization_plan_sha256: str
    sandbox_policy_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="toolchain manifest",
            identifier_fields=("manifest_id", "lineage_id"),
        )
        object.__setattr__(self, "target", _identifier(self.target, "target"))
        object.__setattr__(self, "stack", _identifier(self.stack, "stack"))
        object.__setattr__(self, "versions", _text_mapping(self.versions, "versions"))
        object.__setattr__(
            self,
            "required_tools",
            _sorted_strings(self.required_tools, "required_tools", identifiers=True),
        )
        if not self.required_tools:
            raise ValueError("toolchain manifest must name required_tools")
        object.__setattr__(
            self,
            "lockfiles",
            _sorted_strings(self.lockfiles, "lockfiles", paths=True),
        )
        for name in (
            "build_command",
            "test_command",
            "run_command",
            "package_command",
        ):
            object.__setattr__(self, name, _command(getattr(self, name), name))
        object.__setattr__(
            self, "licenses", _sorted_strings(self.licenses, "licenses")
        )
        endpoints = tuple(
            sorted(
                _egress_endpoint(endpoint, f"egress_endpoints[{index}]")
                for index, endpoint in enumerate(self.egress_endpoints)
            )
        )
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("egress_endpoints must not contain duplicates")
        object.__setattr__(self, "egress_endpoints", endpoints)
        for name in ("materialization_plan_sha256", "sandbox_policy_sha256"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        _require_provenance_inputs(
            self.provenance,
            (self.materialization_plan_sha256, self.sandbox_policy_sha256),
            "toolchain manifest",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolchainManifest":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class RoundTripReport(CanonicalContract):
    """Independent target-versus-rebuilt-Twin conformance result."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.round-trip-report"

    report_id: str
    lineage_id: str
    mission_id: str
    source_revision: str
    candidate_tree: ArtifactRef
    actual_fourfold: ArtifactRef
    target_fourfold_spec_sha256: str
    evaluator_sha256: str
    evidence_packet_sha256: str
    checks: Mapping[str, bool]
    status: str
    mismatches: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="round-trip report",
            identifier_fields=("report_id", "lineage_id", "mission_id"),
        )
        object.__setattr__(
            self, "candidate_tree", _artifact(self.candidate_tree, "candidate_tree")
        )
        object.__setattr__(
            self, "actual_fourfold", _artifact(self.actual_fourfold, "actual_fourfold")
        )
        for name in (
            "target_fourfold_spec_sha256",
            "evaluator_sha256",
            "evidence_packet_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(self, "checks", _boolean_mapping(self.checks, "checks"))
        if self.status not in {"passed", "failed", "blocked"}:
            raise ValueError("round-trip status must be passed, failed, or blocked")
        object.__setattr__(
            self, "mismatches", _sorted_strings(self.mismatches, "mismatches")
        )
        conformed = all(self.checks.values()) and not self.mismatches
        if self.status == "passed" and not conformed:
            raise ValueError("passed round-trip report contradicts retained checks")
        if self.status == "failed" and conformed:
            raise ValueError("failed round-trip report requires a mismatch")
        if self.status == "blocked" and not self.mismatches:
            raise ValueError("blocked round-trip report must retain its blocker")
        _require_provenance_inputs(
            self.provenance,
            (
                self.candidate_tree.sha256,
                self.actual_fourfold.sha256,
                self.target_fourfold_spec_sha256,
                self.evaluator_sha256,
                self.evidence_packet_sha256,
            ),
            "round-trip report",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RoundTripReport":
        body = cls._contract_payload(payload)
        body["candidate_tree"] = _artifact(body["candidate_tree"], "candidate_tree")
        body["actual_fourfold"] = _artifact(body["actual_fourfold"], "actual_fourfold")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class DeploymentPlan(CanonicalContract):
    """Public release plan bound to one candidate and one owner approval."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.deployment-plan"

    plan_id: str
    lineage_id: str
    source_revision: str
    candidate_tree: ArtifactRef
    round_trip_report_sha256: str
    evidence_packet_sha256: str
    toolchain_manifest_sha256: str
    owner_approval_sha256: str
    target_matrix: Mapping[str, Any]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="deployment plan",
            identifier_fields=("plan_id", "lineage_id"),
        )
        object.__setattr__(
            self, "candidate_tree", _artifact(self.candidate_tree, "candidate_tree")
        )
        for name in (
            "round_trip_report_sha256",
            "evidence_packet_sha256",
            "toolchain_manifest_sha256",
            "owner_approval_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        matrix = _frozen_object(
            self.target_matrix, "target_matrix", allow_empty=False
        )
        for target, settings in matrix.items():
            _identifier(target, "target_matrix key")
            if not isinstance(settings, Mapping):
                raise ValueError("each target_matrix value must be an object")
        object.__setattr__(self, "target_matrix", matrix)
        _require_provenance_inputs(
            self.provenance,
            (
                self.candidate_tree.sha256,
                self.round_trip_report_sha256,
                self.evidence_packet_sha256,
                self.toolchain_manifest_sha256,
                self.owner_approval_sha256,
            ),
            "deployment plan",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DeploymentPlan":
        body = cls._contract_payload(payload)
        body["candidate_tree"] = _artifact(body["candidate_tree"], "candidate_tree")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class DeploymentReceipt(CanonicalContract):
    """Retained per-target outcome; never evidence of promotion by itself."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.deployment-receipt"

    receipt_id: str
    lineage_id: str
    source_revision: str
    deployment_plan_sha256: str
    candidate_tree: ArtifactRef
    evidence_packet_sha256: str
    owner_approval_sha256: str
    status: str
    target_results: Mapping[str, str]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="deployment receipt",
            identifier_fields=("receipt_id", "lineage_id"),
        )
        object.__setattr__(
            self, "candidate_tree", _artifact(self.candidate_tree, "candidate_tree")
        )
        for name in (
            "deployment_plan_sha256",
            "evidence_packet_sha256",
            "owner_approval_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        if self.status not in {
            "deployed",
            "blocked_external",
            "failed",
            "cancelled",
        }:
            raise ValueError(
                "deployment status must be deployed, blocked_external, failed, or cancelled"
            )
        object.__setattr__(
            self,
            "target_results",
            _text_mapping(self.target_results, "target_results"),
        )
        _require_provenance_inputs(
            self.provenance,
            (
                self.deployment_plan_sha256,
                self.candidate_tree.sha256,
                self.evidence_packet_sha256,
                self.owner_approval_sha256,
            ),
            "deployment receipt",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DeploymentReceipt":
        body = cls._contract_payload(payload)
        body["candidate_tree"] = _artifact(body["candidate_tree"], "candidate_tree")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class GenesisRunRecord(CanonicalContract):
    """Immutable projection of one Genesis Mission's durable artifact state."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.genesis-run-record"

    run_id: str
    lineage_id: str
    mission_id: str
    source_revision: str
    policy_sha256: str
    product_spec_sha256: str
    mission_contract_sha256: str
    status: str
    work_item_ids: tuple[str, ...]
    attempt_ids: tuple[str, ...]
    repair_count: int
    provenance: ContractProvenance
    candidate_tree: ArtifactRef | None = None
    evidence_packet_sha256: str | None = None
    round_trip_report_sha256: str | None = None
    deployment_receipt_sha256: str | None = None
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        _common_identity(
            self,
            label="Genesis run record",
            identifier_fields=("run_id", "lineage_id", "mission_id"),
        )
        for name in (
            "policy_sha256",
            "product_spec_sha256",
            "mission_contract_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        allowed_statuses = {
            "admitted",
            "running",
            "repairing",
            "preview-ready",
            "succeeded",
            "failed",
            "blocked",
            "cancelled",
            "deployed",
        }
        if self.status not in allowed_statuses:
            raise ValueError(f"Genesis run status must be one of {sorted(allowed_statuses)}")
        object.__setattr__(
            self,
            "work_item_ids",
            _sorted_strings(self.work_item_ids, "work_item_ids", identifiers=True),
        )
        if not self.work_item_ids:
            raise ValueError("Genesis run record must name its work items")
        object.__setattr__(
            self,
            "attempt_ids",
            _sorted_strings(self.attempt_ids, "attempt_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "repair_count",
            _non_negative_integer(self.repair_count, "repair_count"),
        )
        if self.candidate_tree is not None:
            object.__setattr__(
                self, "candidate_tree", _artifact(self.candidate_tree, "candidate_tree")
            )
        for name in (
            "evidence_packet_sha256",
            "round_trip_report_sha256",
            "deployment_receipt_sha256",
        ):
            object.__setattr__(
                self, name, _optional_sha256(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "blocked_reason",
            _optional_text(self.blocked_reason, "blocked_reason"),
        )
        if self.status == "blocked" and self.blocked_reason is None:
            raise ValueError("blocked Genesis run must retain blocked_reason")
        if self.status != "blocked" and self.blocked_reason is not None:
            raise ValueError("only a blocked Genesis run may carry blocked_reason")
        if self.evidence_packet_sha256 is not None and self.candidate_tree is None:
            raise ValueError("Genesis evidence requires a candidate_tree")
        if self.round_trip_report_sha256 is not None and (
            self.candidate_tree is None or self.evidence_packet_sha256 is None
        ):
            raise ValueError(
                "Genesis round-trip report requires candidate_tree and evidence"
            )
        if self.status in {"preview-ready", "succeeded", "deployed"} and (
            self.candidate_tree is None
            or self.evidence_packet_sha256 is None
            or self.round_trip_report_sha256 is None
        ):
            raise ValueError(
                "green Genesis run requires candidate, evidence, and round-trip report"
            )
        if self.status == "deployed" and self.deployment_receipt_sha256 is None:
            raise ValueError("deployed Genesis run requires deployment receipt")
        if self.status != "deployed" and self.deployment_receipt_sha256 is not None:
            raise ValueError("only a deployed Genesis run may bind deployment receipt")
        required = {
            self.policy_sha256,
            self.product_spec_sha256,
            self.mission_contract_sha256,
        }
        if self.candidate_tree is not None:
            required.add(self.candidate_tree.sha256)
        for digest in (
            self.evidence_packet_sha256,
            self.round_trip_report_sha256,
            self.deployment_receipt_sha256,
        ):
            if digest is not None:
                required.add(digest)
        _require_provenance_inputs(
            self.provenance, tuple(sorted(required)), "Genesis run record"
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GenesisRunRecord":
        body = cls._contract_payload(payload)
        if body.get("candidate_tree") is not None:
            body["candidate_tree"] = _artifact(body["candidate_tree"], "candidate_tree")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


GENESIS_CONTRACT_TYPES: Mapping[str, type[CanonicalContract]] = MappingProxyType(
    {
        cls.CONTRACT_TYPE: cls
        for cls in (
            GenesisAutonomyPolicy,
            BuildIntentProposal,
            ProductSpec,
            DesignContract,
            TargetFourfoldSpec,
            GraphProposal,
            MaterializationPlan,
            ToolchainManifest,
            RoundTripReport,
            DeploymentPlan,
            DeploymentReceipt,
            GenesisRunRecord,
        )
    }
)

_register_kernel_contract_types(tuple(GENESIS_CONTRACT_TYPES.values()))


__all__ = [
    "GENESIS_CONTRACT_TYPES",
    "GenesisAutonomyPolicy",
    "BuildIntentProposal",
    "ProductSpec",
    "DesignContract",
    "TargetFourfoldSpec",
    "GraphProposal",
    "MaterializationPlan",
    "ToolchainManifest",
    "RoundTripReport",
    "DeploymentPlan",
    "DeploymentReceipt",
    "GenesisRunRecord",
]

"""Compatibility and authority checks for the HIER-02 contract move."""

from __future__ import annotations

import importlib
import pickle

import pytest

import daedalus.limit_policy as legacy_limits
import daedalus.schemas as legacy
from daedalus.kernel import contracts
from daedalus.kernel.contracts import attempts, campaigns, evidence, missions, policy, promotion, resources, runtime
from daedalus.kernel.policy import limits
from daedalus.orchestration import legacy_reports
from daedalus.runtimes.contracts import provider_report


DOMAIN_EXPORTS = {
    missions: ("MissionContract", "derive_work_item_id", "work_item_identity_sha256"),
    attempts: ("AttemptContract", "AttemptReceipt"),
    evidence: ("EvidenceItem", "EvidencePacket"),
    campaigns: (
        "ExperimentSpec",
        "CampaignContract",
        "CampaignTrialReceipt",
        "CampaignReceipt",
    ),
    policy: ("PolicyDecision",),
    runtime: ("RuntimeManifest", "ConformanceCheck", "RuntimeConformanceReceipt"),
    promotion: ("NominationReceipt", "PromotionReceipt"),
    resources: (
        "ResourceBudget",
        "ResourceUsage",
        "EffectScope",
        "RuntimeCapabilities",
    ),
}


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (module, name)
        for module, names in DOMAIN_EXPORTS.items()
        for name in names
    ],
)
def test_legacy_and_hierarchy_exports_are_one_object(module, name: str) -> None:
    canonical = getattr(module, name)
    assert getattr(contracts, name) is canonical
    assert getattr(legacy, name) is canonical


@pytest.mark.parametrize(
    "name",
    (
        "_artifact_locator",
        "_attempt_evidence_projection",
        "_egress_endpoint",
        "_freeze_json",
        "_identifier",
        "_json_value",
        "_locator_sha256",
        "_non_empty",
        "_record_payload",
        "_repo_path",
        "_require_provenance_inputs",
        "_revision",
        "_sha256",
        "_snapshot_execution_limit_policy",
        "_sorted_strings",
        "_utc_timestamp",
    ),
)
def test_private_validator_facade_preserves_exact_objects(name: str) -> None:
    from daedalus.kernel.contracts import canonical

    assert getattr(legacy, name) is getattr(canonical, name)


@pytest.mark.parametrize(
    "name",
    (
        "ExecutionLimitPolicy",
        "LimitAxes",
        "LimitPolicyError",
        "load_from_env",
        "store_in_env",
    ),
)
def test_limit_policy_facade_preserves_exact_objects(name: str) -> None:
    assert getattr(legacy_limits, name) is getattr(limits, name)


@pytest.mark.parametrize("name", ("AgentTask", "RunState"))
def test_legacy_orchestration_forms_have_one_owner(name: str) -> None:
    assert getattr(legacy, name) is getattr(legacy_reports, name)


@pytest.mark.parametrize("name", ("AgentReport", "validate_report", "REPORT_KEYS"))
def test_provider_report_forms_have_one_runtime_owner(name: str) -> None:
    canonical = getattr(provider_report, name)
    assert getattr(legacy, name) is canonical
    assert getattr(legacy_reports, name) is canonical


@pytest.mark.parametrize(
    "name",
    ("MissionContract", "AttemptContract", "EvidencePacket", "PolicyDecision", "RuntimeManifest", "PromotionReceipt"),
)
def test_old_pickle_global_resolves_to_the_moved_class(name: str) -> None:
    old_global = f"cdaedalus.schemas\n{name}\n.".encode("ascii")
    assert pickle.loads(old_global) is getattr(contracts, name)


#: What each kernel module bound after G1-HIER-10 stopped routing it through
#: :mod:`daedalus.schemas`. The route changed; the objects must not have. A
#: repoint that reached a *different* object would keep every import working
#: and silently give the kernel a second wire authority, which is the failure
#: this table exists to make loud.
KERNEL_CONTRACT_BINDINGS = {
    "daedalus.kernel.approvals": (
        "ContractProvenance", "_identifier", "_revision", "_sha256",
        "_utc_timestamp",
    ),
    "daedalus.kernel.artifacts": (
        "_artifact_locator", "_locator_sha256", "_sha256",
    ),
    "daedalus.kernel.attempt_clock": ("_utc_timestamp",),
    "daedalus.kernel.attempt_contracts": (
        "AttemptContract", "CanonicalContract", "ContractProvenance",
        "_identifier", "_record_payload", "_repo_path",
        "_require_provenance_inputs", "_revision", "_sha256", "_utc_timestamp",
    ),
    "daedalus.kernel.attempt_execution": (
        "ContractProvenance", "ResourceBudget", "ResourceUsage",
    ),
    "daedalus.kernel.attempt_ledger": (
        "AttemptContract", "ContractProvenance", "_sha256",
    ),
    "daedalus.kernel.attempt_workspace": ("AttemptContract",),
    "daedalus.kernel.authorization": ("PolicyDecision",),
    "daedalus.kernel.effect_recovery": (
        "ContractProvenance", "_identifier", "_revision", "_sha256",
        "_sorted_strings", "_utc_timestamp",
    ),
    "daedalus.kernel.effect_replay": ("PolicyDecision", "_identifier", "_sha256"),
    "daedalus.kernel.effects": (
        "ContractProvenance", "EffectScope", "PolicyDecision",
        "_egress_endpoint", "_identifier", "_repo_path", "_sha256",
        "_sorted_strings",
    ),
    "daedalus.kernel.fourfold_evidence": (
        "ContractProvenance", "EvidenceItem", "EvidencePacket",
        "NominationReceipt", "ResourceUsage", "_artifact_locator",
        "_locator_sha256", "_revision", "_sha256",
    ),
    "daedalus.kernel.offload_lease": (
        "ContractProvenance", "EffectScope", "PolicyDecision",
    ),
    "daedalus.kernel.promotion": ("EvidencePacket", "_identifier", "_revision"),
    "daedalus.kernel.promotion_execution": (
        "CanonicalContract", "ContractProvenance", "_identifier",
        "_require_provenance_inputs", "_revision", "_sha256", "_utc_timestamp",
    ),
    "daedalus.kernel.runtime_conformance": (
        "RUNTIME_CONFORMANCE_CHECKS", "ConformanceCheck", "ContractProvenance",
        "ResourceUsage", "RuntimeConformanceReceipt", "RuntimeManifest",
    ),
    "daedalus.kernel.runtime_effects": (
        "CanonicalContract", "ContractProvenance", "PolicyDecision",
        "_identifier", "_require_provenance_inputs", "_revision", "_sha256",
        "_utc_timestamp",
    ),
    "daedalus.kernel.source_trees": (
        "CanonicalContract", "ContractProvenance", "_artifact_locator",
        "_identifier", "_locator_sha256", "_record_payload", "_repo_path",
        "_require_provenance_inputs", "_revision", "_sha256", "_sorted_strings",
    ),
}


@pytest.mark.parametrize(
    ("module_name", "name"),
    [
        (module_name, name)
        for module_name, names in KERNEL_CONTRACT_BINDINGS.items()
        for name in names
    ],
)
def test_kernel_modules_bind_the_one_contract_object(
    module_name: str, name: str
) -> None:
    module = importlib.import_module(module_name)
    assert getattr(module, name) is getattr(legacy, name)


@pytest.mark.parametrize(
    "name",
    (
        "_artifact_locator",
        "_egress_endpoint",
        "_identifier",
        "_locator_sha256",
        "_record_payload",
        "_repo_path",
        "_require_provenance_inputs",
        "_revision",
        "_sha256",
        "_sorted_strings",
        "_utc_timestamp",
    ),
)
def test_base_is_the_owner_locator_for_private_validators(name: str) -> None:
    """``base`` is a real owner for the private validators, not a pass-through.

    ``base.__all__`` lists only the three public names, which is why this is
    worth asserting: ``__all__`` does not gate an explicit ``from ... import``,
    so the kernel may name ``base`` for the validators and no tenth module has
    to be invented for them.
    """

    from daedalus.kernel.contracts import base, canonical

    assert getattr(base, name) is getattr(canonical, name)


def test_contract_registry_is_shared_and_parser_roundtrip_is_byte_exact() -> None:
    provenance = contracts.ContractProvenance(
        origin="hierarchy-test",
        source_revision="1" * 40,
        created_at="2026-08-31T00:00:00+00:00",
        input_digests=("2" * 64,),
    )
    mission = contracts.MissionContract(
        mission_id="mission-hierarchy-test",
        objective="prove that the compatibility facade has one wire authority",
        source_revision="1" * 40,
        work_item_ids=("work-item-hierarchy-test",),
        success_criteria=("byte-identical parser roundtrip",),
        budget=contracts.ResourceBudget(max_tokens=1),
        policy_sha256="2" * 64,
        provenance=provenance,
    )
    wire = mission.to_json()
    assert legacy.KERNEL_CONTRACT_TYPES is contracts.KERNEL_CONTRACT_TYPES
    assert legacy.parse_kernel_contract(mission.to_dict()) is not mission
    rebuilt = legacy.parse_kernel_contract(mission.to_dict())
    assert rebuilt.to_json() == wire
    assert rebuilt.digest == mission.digest

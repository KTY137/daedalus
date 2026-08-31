"""G1-HIER-02A compatibility and refusal tests for ``daedalus.kernel``."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_OWNER_GROUPS = {
    "approvals": (
        "ApprovalBindingMismatch", "ApprovalExpired", "ConsumedOwnerApproval",
        "ApprovalExpectation", "ApprovalLedger", "ApprovalReplay",
        "ApprovalSignatureError", "ApprovalStateError", "VerifiedOwnerApproval",
        "issue_owner_approval", "verify_owner_approval",
    ),
    "contracts": ("OwnerApproval", "EffectLease", "EffectLeaseRequest"),
    "effects": (
        "EffectExecutionRequest", "EffectLeaseBindingMismatch",
        "EffectLeaseConcurrencyError", "EffectLeaseError", "EffectLeaseExpired",
        "EffectLeaseLedger", "EffectLeaseReplay", "EffectLeaseScopeError",
        "EffectLeaseSignatureError", "EffectLeaseStateError", "EffectStartResult",
        "EffectTerminalReceipt", "LeasedEffectStartReceipt",
        "LeasedEffectAuthorization", "issue_effect_lease", "verify_effect_lease",
    ),
    "authorization": ("NonRuntimeEffectAuthorization",),
    "fourfold_evidence": (
        "FOURFOLD_EVIDENCE_SCHEMA", "FOURFOLD_EVALUATOR",
        "FourfoldEvidenceExpectation", "FourfoldEvidenceMismatch",
        "assemble_fourfold_evidence_packet", "verify_fourfold_evidence_packet",
    ),
    "promotion": (
        "PromotionAuthorization", "PromotionAuthorizationError",
        "authorize_persisted_promotion", "authorize_promotion",
        "candidate_batch_sha256", "resolve_live_target_revision",
    ),
    "promotion_execution": (
        "PromotionExecutionBeginResult", "PromotionExecutionBindingMismatch",
        "PromotionExecutionCompletion", "PromotionExecutionError",
        "PromotionExecutionLedger", "PromotionExecutionReceipt",
        "PromotionExecutionReplay", "PromotionExecutionStart",
        "PromotionExecutionStateError",
    ),
    "runtime_conformance": (
        "RecordedObservation", "RuntimeConformanceError",
        "assemble_recorded_conformance", "persist_conformance_receipt",
        "verify_current_conformance",
    ),
    "sandbox": (
        "DockerSandboxPolicy", "SandboxExecutionReceipt", "SandboxMount",
        "SandboxPolicyError", "run_in_docker_sandbox",
    ),
    "source_trees": (
        "MANDATORY_IGNORED_ROOTS", "SourceTreeCaptureError",
        "SourceTreeCorruptionError", "SourceTreeEntry", "SourceTreeManifest",
        "SourceTreeStore", "SourceTreeStoreError", "StoredSourceTree",
    ),
    "attempts": (
        "AttemptBeginResult", "AttemptBindingMismatch", "AttemptCompletion",
        "AttemptLedger", "AttemptLifecycleError", "AttemptReplay",
        "AttemptStartRecord", "AttemptStateError", "AttemptTerminalReceipt",
        "AttemptWorkspaceError", "IsolatedAttemptCoordinator", "PreparedAttempt",
    ),
}

CAMPAIGN_EXPORTS = (
    "CAMPAIGN_RUN_KIND", "CampaignAlreadyTerminal", "CampaignBeginResult",
    "CampaignLifecycleError", "CampaignPendingReconciliation", "begin_campaign",
    "campaign_contract_for_spec", "complete_campaign", "fail_campaign",
    "load_campaign_contract", "load_campaign_receipt", "load_experiment_spec",
    "store_contract", "verify_campaign_chain",
)

PHYSICAL_SUBMODULES = (
    "approvals", "artifacts", "attempt_clock", "attempt_contracts",
    "attempt_ledger", "attempt_spine_reader", "attempt_workspace", "attempts",
    "authorization", "contracts", "effect_recovery", "effect_replay", "effects",
    "fourfold_evidence", "offload_lease", "promotion", "promotion_execution",
    "promotion_execution_reader", "promotion_fingerprint", "promotion_trust_root",
    "runtime_authorization_issuer", "runtime_conformance", "runtime_effect_replay",
    "runtime_effects", "sandbox", "source_trees",
)

# Frozen from the 151b8d18 facade. Order matters for import-star compatibility.
EXPECTED_ALL = [
    "ApprovalBindingMismatch", "ApprovalExpired", "ConsumedOwnerApproval",
    "ApprovalExpectation", "ApprovalLedger", "ApprovalReplay",
    "ApprovalSignatureError", "ApprovalStateError", "OwnerApproval",
    "VerifiedOwnerApproval", "issue_owner_approval", "verify_owner_approval",
    "EffectExecutionRequest", "EffectLease", "EffectLeaseBindingMismatch",
    "EffectLeaseConcurrencyError", "EffectLeaseError", "EffectLeaseExpired",
    "EffectLeaseLedger", "EffectLeaseReplay", "EffectLeaseRequest",
    "EffectLeaseScopeError", "EffectLeaseSignatureError", "EffectLeaseStateError",
    "EffectStartResult", "EffectTerminalReceipt", "LeasedEffectStartReceipt",
    "LeasedEffectAuthorization", "NonRuntimeEffectAuthorization",
    "issue_effect_lease", "verify_effect_lease", "FOURFOLD_EVIDENCE_SCHEMA",
    "FOURFOLD_EVALUATOR", "FourfoldEvidenceExpectation",
    "FourfoldEvidenceMismatch", "assemble_fourfold_evidence_packet",
    "verify_fourfold_evidence_packet", "PromotionAuthorization",
    "PromotionAuthorizationError", "authorize_persisted_promotion",
    "authorize_promotion", "candidate_batch_sha256", "resolve_live_target_revision",
    "PromotionExecutionBeginResult", "PromotionExecutionBindingMismatch",
    "PromotionExecutionCompletion", "PromotionExecutionError",
    "PromotionExecutionLedger", "PromotionExecutionReceipt",
    "PromotionExecutionReplay", "PromotionExecutionStart",
    "PromotionExecutionStateError", "RecordedObservation",
    "RuntimeConformanceError", "assemble_recorded_conformance",
    "persist_conformance_receipt", "verify_current_conformance",
    "DockerSandboxPolicy", "SandboxExecutionReceipt", "SandboxMount",
    "SandboxPolicyError", "run_in_docker_sandbox", "MANDATORY_IGNORED_ROOTS",
    "SourceTreeCaptureError", "SourceTreeCorruptionError", "SourceTreeEntry",
    "SourceTreeManifest", "SourceTreeStore", "SourceTreeStoreError",
    "StoredSourceTree", "AttemptBeginResult", "AttemptBindingMismatch",
    "AttemptCompletion", "AttemptLedger", "AttemptLifecycleError",
    "AttemptReplay", "AttemptStartRecord", "AttemptStateError",
    "AttemptTerminalReceipt", "AttemptWorkspaceError",
    "IsolatedAttemptCoordinator", "PreparedAttempt", *CAMPAIGN_EXPORTS,
]


def _isolated_json(source: str) -> object:
    proc = subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_bare_kernel_import_has_no_eager_capability_side_effects():
    loaded = _isolated_json(
        "import json, sys\n"
        "import daedalus.kernel\n"
        "print(json.dumps(sorted(n for n in sys.modules "
        "if n.startswith('daedalus.kernel.'))))\n"
    )
    # G1-HIER-03A gives the canonical JSON/envelope helper a kernel owner.
    # ``daedalus.schemas`` is still imported by the package root and therefore
    # loads this pure helper, but no ledger/durability or capability owner.
    assert loaded == [
        "daedalus.kernel.events",
        "daedalus.kernel.events.envelope",
    ]


def test_one_reexport_loads_only_its_owner_and_keeps_identity():
    observed = _isolated_json(
        "import json, sys\n"
        "import daedalus.kernel as kernel\n"
        "from daedalus.kernel.contracts import OwnerApproval\n"
        "print(json.dumps({'same': kernel.OwnerApproval is OwnerApproval, "
        "'loaded': sorted(n for n in sys.modules "
        "if n.startswith('daedalus.kernel.'))}))\n"
    )
    assert observed == {
        "same": True,
        "loaded": [
            "daedalus.kernel.contracts",
            "daedalus.kernel.contracts.canonical",
            "daedalus.kernel.contracts.security",
            "daedalus.kernel.events",
            "daedalus.kernel.events.envelope",
            "daedalus.kernel.policy",
            "daedalus.kernel.policy.limits",
        ],
    }


def test_independent_submodule_and_web_import_do_not_require_campaigns():
    observed = _isolated_json(
        "import json, sys\n"
        "import daedalus.kernel.artifacts as artifacts\n"
        "import daedalus.web_api as web_api\n"
        "print(json.dumps({'artifact_owner': artifacts.ArtifactRef.__module__, "
        "'web': web_api.__name__, "
        "'campaign_loaded': 'daedalus.kernel.campaigns' in sys.modules}))\n"
    )
    assert observed == {
        "artifact_owner": "daedalus.kernel.artifacts",
        "web": "daedalus.web_api",
        "campaign_loaded": False,
    }


def test_all_inventory_and_order_are_preserved():
    kernel = importlib.import_module("daedalus.kernel")
    assert kernel.__all__ == EXPECTED_ALL
    assert len(kernel.__all__) == 96
    assert set(CAMPAIGN_EXPORTS) <= set(dir(kernel))


@pytest.mark.parametrize(
    ("owner", "name"),
    [(owner, name) for owner, names in EXPECTED_OWNER_GROUPS.items()
     for name in names],
)
def test_existing_reexport_is_exact_owner_object(owner: str, name: str):
    kernel = importlib.import_module("daedalus.kernel")
    module = importlib.import_module(f"daedalus.kernel.{owner}")
    assert getattr(kernel, name) is getattr(module, name)


@pytest.mark.parametrize("name", PHYSICAL_SUBMODULES)
def test_existing_module_attribute_is_lazy_and_exact(name: str):
    kernel = importlib.import_module("daedalus.kernel")
    module = importlib.import_module(f"daedalus.kernel.{name}")
    assert getattr(kernel, name) is module


@pytest.mark.parametrize("name", ("campaigns", *CAMPAIGN_EXPORTS))
def test_missing_campaign_slice_fails_loudly_and_specifically(name: str):
    kernel = importlib.import_module("daedalus.kernel")
    with pytest.raises(ModuleNotFoundError) as caught:
        getattr(kernel, name)
    assert caught.value.name == "daedalus.kernel.campaigns"
    assert f"{name!r}" in str(caught.value)
    assert "does not fabricate this slice" in str(caught.value)


def test_campaign_dependency_failure_is_not_mislabelled(monkeypatch):
    kernel = importlib.import_module("daedalus.kernel")

    def dependency_failure(_module_name: str):
        raise ModuleNotFoundError(
            "No module named 'campaign_dependency'",
            name="campaign_dependency",
        )

    monkeypatch.setattr(kernel, "_import_module", dependency_failure)
    with pytest.raises(ModuleNotFoundError) as caught:
        kernel._load_owner("campaigns", "begin_campaign")
    assert caught.value.name == "campaign_dependency"
    assert "compatibility name" not in str(caught.value)


def test_future_campaign_owner_is_used_without_a_facade_substitute(monkeypatch):
    kernel = importlib.import_module("daedalus.kernel")
    sentinel = object()

    class FutureCampaignModule:
        begin_campaign = sentinel

    monkeypatch.setattr(
        kernel,
        "_import_module",
        lambda module_name: FutureCampaignModule
        if module_name == "daedalus.kernel.campaigns"
        else importlib.import_module(module_name),
    )
    kernel.__dict__.pop("begin_campaign", None)
    try:
        assert kernel.begin_campaign is sentinel
    finally:
        kernel.__dict__.pop("begin_campaign", None)


def test_unknown_name_remains_a_normal_attribute_error():
    kernel = importlib.import_module("daedalus.kernel")
    with pytest.raises(AttributeError, match="no attribute 'not_a_kernel_export'"):
        getattr(kernel, "not_a_kernel_export")

"""Lazy compatibility facade for the canonical Daedalus trust kernel.

The concrete capability modules own their implementations. This package only
preserves the historical root reexports, loading an owner when (and only when)
one of its names is requested. This package is not a second contract authority;
canonical wire contracts are owned by :mod:`daedalus.kernel.contracts` while
:mod:`daedalus.schemas` remains an object-identical compatibility facade.

The frozen Gate-1 WIP references a Campaign slice that is not present. Its
compatibility names remain declared so the gap is visible, but requesting one
fails specifically instead of preventing every unrelated kernel import.
"""

from importlib import import_module as _import_module


# Ordered exactly like the pre-facade ``__all__``. Repeated owner names are
# intentional: export order is a compatibility contract independent of module
# grouping.
_EXPORT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("approvals", (
        "ApprovalBindingMismatch",
        "ApprovalExpired",
        "ConsumedOwnerApproval",
        "ApprovalExpectation",
        "ApprovalLedger",
        "ApprovalReplay",
        "ApprovalSignatureError",
        "ApprovalStateError",
    )),
    ("contracts", ("OwnerApproval",)),
    ("approvals", (
        "VerifiedOwnerApproval",
        "issue_owner_approval",
        "verify_owner_approval",
    )),
    ("effects", ("EffectExecutionRequest",)),
    ("contracts", ("EffectLease",)),
    ("effects", (
        "EffectLeaseBindingMismatch",
        "EffectLeaseConcurrencyError",
        "EffectLeaseError",
        "EffectLeaseExpired",
        "EffectLeaseLedger",
        "EffectLeaseReplay",
    )),
    ("contracts", ("EffectLeaseRequest",)),
    ("effects", (
        "EffectLeaseScopeError",
        "EffectLeaseSignatureError",
        "EffectLeaseStateError",
        "EffectStartResult",
        "EffectTerminalReceipt",
        "LeasedEffectStartReceipt",
        "LeasedEffectAuthorization",
    )),
    ("authorization", ("NonRuntimeEffectAuthorization",)),
    ("effects", ("issue_effect_lease", "verify_effect_lease")),
    ("fourfold_evidence", (
        "FOURFOLD_EVIDENCE_SCHEMA",
        "FOURFOLD_EVALUATOR",
        "FourfoldEvidenceExpectation",
        "FourfoldEvidenceMismatch",
        "assemble_fourfold_evidence_packet",
        "verify_fourfold_evidence_packet",
    )),
    ("promotion", (
        "PromotionAuthorization",
        "PromotionAuthorizationError",
        "authorize_persisted_promotion",
        "authorize_promotion",
        "candidate_batch_sha256",
        "resolve_live_target_revision",
    )),
    ("promotion_execution", (
        "PromotionExecutionBeginResult",
        "PromotionExecutionBindingMismatch",
        "PromotionExecutionCompletion",
        "PromotionExecutionError",
        "PromotionExecutionLedger",
        "PromotionExecutionReceipt",
        "PromotionExecutionReplay",
        "PromotionExecutionStart",
        "PromotionExecutionStateError",
    )),
    ("runtime_conformance", (
        "RecordedObservation",
        "RuntimeConformanceError",
        "assemble_recorded_conformance",
        "persist_conformance_receipt",
        "verify_current_conformance",
    )),
    ("sandbox", (
        "DockerSandboxPolicy",
        "SandboxExecutionReceipt",
        "SandboxMount",
        "SandboxPolicyError",
        "run_in_docker_sandbox",
    )),
    ("source_trees", (
        "MANDATORY_IGNORED_ROOTS",
        "SourceTreeCaptureError",
        "SourceTreeCorruptionError",
        "SourceTreeEntry",
        "SourceTreeManifest",
        "SourceTreeStore",
        "SourceTreeStoreError",
        "StoredSourceTree",
    )),
    ("attempts", (
        "AttemptBeginResult",
        "AttemptBindingMismatch",
        "AttemptCompletion",
        "AttemptLedger",
        "AttemptLifecycleError",
        "AttemptReplay",
        "AttemptStartRecord",
        "AttemptStateError",
        "AttemptTerminalReceipt",
        "AttemptWorkspaceError",
        "IsolatedAttemptCoordinator",
        "PreparedAttempt",
    )),
    ("campaigns", (
        "CAMPAIGN_RUN_KIND",
        "CampaignAlreadyTerminal",
        "CampaignBeginResult",
        "CampaignLifecycleError",
        "CampaignPendingReconciliation",
        "begin_campaign",
        "campaign_contract_for_spec",
        "complete_campaign",
        "fail_campaign",
        "load_campaign_contract",
        "load_campaign_receipt",
        "load_experiment_spec",
        "store_contract",
        "verify_campaign_chain",
    )),
)

_EXPORTS: dict[str, tuple[str, str]] = {}
for _owner, _names in _EXPORT_GROUPS:
    for _name in _names:
        _EXPORTS[_name] = (_owner, _name)

__all__ = list(_EXPORTS)

# Preserve ordinary package-module attributes without importing them. Several
# appeared incidentally through the old eager graph; all remain directly
# importable and resolve to Python's single canonical module object.
_LAZY_MODULES = frozenset({
    "approvals",
    "artifacts",
    "attempt_clock",
    "attempt_contracts",
    "attempt_ledger",
    "attempt_spine_reader",
    "attempt_workspace",
    "attempts",
    "authorization",
    "campaigns",
    "contracts",
    "effect_recovery",
    "effect_replay",
    "effects",
    "fourfold_evidence",
    "offload_lease",
    "promotion",
    "promotion_execution",
    "promotion_execution_reader",
    "promotion_fingerprint",
    "promotion_trust_root",
    "runtime_authorization_issuer",
    "runtime_conformance",
    "runtime_effect_replay",
    "runtime_effects",
    "sandbox",
    "source_trees",
})
_CAMPAIGN_MODULE = f"{__name__}.campaigns"


def _load_owner(owner: str, requested: str):
    module_name = f"{__name__}.{owner}"
    try:
        return _import_module(module_name)
    except ModuleNotFoundError as exc:
        # Only reinterpret absence of the Campaign module itself. If a future
        # real campaigns.py has a missing dependency, preserve that dependency's
        # original name/traceback instead of disguising it as today's WIP gap.
        if owner == "campaigns" and exc.name == _CAMPAIGN_MODULE:
            raise ModuleNotFoundError(
                f"Kernel compatibility name {requested!r} is unavailable: "
                f"{_CAMPAIGN_MODULE} is referenced by the frozen Gate-1 WIP "
                "but is not present. Land the owning Campaign Work Packet; "
                "the compatibility facade does not fabricate this slice.",
                name=_CAMPAIGN_MODULE,
            ) from exc
        raise


def __getattr__(name: str):
    """Resolve one historical export or module without eager package imports."""
    binding = _EXPORTS.get(name)
    if binding is not None:
        owner, attribute = binding
        module = _load_owner(owner, name)
        value = getattr(module, attribute)
        globals()[name] = value
        return value
    if name in _LAZY_MODULES:
        module = _load_owner(name, name)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Advertise the compatibility surface, including the honest Campaign gap."""
    return sorted(set(globals()) | set(__all__) | set(_LAZY_MODULES))


del _owner, _names, _name

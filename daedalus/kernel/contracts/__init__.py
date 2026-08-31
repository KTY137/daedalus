"""Lazy facade for canonical contracts grouped by lifecycle domain.

The domain modules are stable hierarchy locators. ``canonical`` remains the
single implementation nucleus during the strangler split, so every legacy and
new import resolves to one class object and one serialization authority.
"""

from importlib import import_module as _import_module


_EXPORT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("base", ("KERNEL_CONTRACT_VERSION", "CanonicalContract", "ContractProvenance")),
    ("runtime", ("RUNTIME_CONFORMANCE_CHECKS",)),
    (
        "resources",
        ("ResourceBudget", "ResourceUsage", "EffectScope", "RuntimeCapabilities"),
    ),
    ("missions", ("MissionContract", "derive_work_item_id", "work_item_identity_sha256")),
    ("attempts", ("AttemptContract",)),
    ("evidence", ("EvidenceItem", "EvidencePacket")),
    (
        "campaigns",
        ("ExperimentSpec", "CampaignContract", "CampaignTrialReceipt", "CampaignReceipt"),
    ),
    ("policy", ("PolicyDecision",)),
    ("runtime", ("RuntimeManifest",)),
    ("attempts", ("AttemptReceipt",)),
    ("promotion", ("NominationReceipt", "PromotionReceipt")),
    ("runtime", ("ConformanceCheck", "RuntimeConformanceReceipt")),
    ("registry", ("KERNEL_CONTRACT_TYPES", "parse_kernel_contract")),
    (
        "security",
        (
            "OwnerApproval",
            "EffectLeaseRequest",
            "EffectLease",
            "RuntimeTrustLedgerPort",
            "RuntimeTrustPortError",
            "RuntimeTrustRecordPort",
        ),
    ),
    (
        "evaluation",
        ("EvaluationBaselinePort", "EvaluationGatePort", "EvaluationPorts"),
    ),
)

_EXPORTS = {name: owner for owner, names in _EXPORT_GROUPS for name in names}
_MODULES = frozenset(
    {
        "attempts",
        "base",
        "campaigns",
        "canonical",
        "evidence",
        "evaluation",
        "missions",
        "observations",
        "policy",
        "promotion",
        "registry",
        "resources",
        "runtime",
        "security",
    }
)

__all__ = [name for _, names in _EXPORT_GROUPS for name in names]


def __getattr__(name: str):
    owner = _EXPORTS.get(name)
    if owner is not None:
        value = getattr(_import_module(f"{__name__}.{owner}"), name)
        globals()[name] = value
        return value
    if name in _MODULES:
        value = _import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | _MODULES)

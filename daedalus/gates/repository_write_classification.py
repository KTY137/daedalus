# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Revision-bound classification contract for repository write surfaces.

This module is deliberately preparatory.  It can bind reviewed declarations to
one generation-2 inventory, but it cannot authenticate external receipts, alter
the canonical effect registry, prove Primary-Checkout disjointness, or close
Gate 0.  Later packets may consume the report only after independently
verifying the referenced evidence and binding it into the release GateReport.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.spine.envelope import canonical_json


_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

# The wire id this chain stamps into every projection it produces.  A consumer
# must read the id back out of the produced report and compare it with this
# const rather than assume it: that way a drift in ``_payload`` surfaces at the
# consumer as a declared mismatch instead of passing silently.
# Revision 2 removed ``evidence_authenticated`` from the payload.  The key was
# a module-wide literal ``False`` that could never have carried a truthful
# value: this module runs before the six verifiers whose agreement would have
# to be reported, and one boolean per report cannot say which surface they
# agreed about.  The per-surface verdict lives in
# ``authenticate_repository_write_surfaces`` below, composed in process from
# the six typed stage reports.  One id, one shape: the key is gone rather than
# left behind meaning something else.
CLASSIFICATION_SCHEMA = "daedalus-gate0-repository-write-classification/2"

# The wire id a *declaration* must carry to be accepted by
# ``project_classification_input``.  It is exported for producers -- a
# generator that mints a declaration should build it against this name rather
# than repeat the literal -- and it is deliberately NOT substituted into the
# check inside ``project_classification_input`` below.  That check keeps its
# own literal for the same reason ``_payload`` does: two independent spellings
# mean a drift on the verifier side surfaces as a refused document at the
# producer, instead of both sides moving together and nobody noticing.
CLASSIFICATION_INPUT_SCHEMA = (
    "daedalus-gate0-repository-write-classification-input/1"
)

# Verdict vocabulary.  It belongs to this chain, not to its consumers: a
# consumer may only report a verdict this module can produce.  A surface the
# projection did not classify is ``unclassified`` and stays a blocker; a
# surface the scanner emitted without marking it blocking is
# ``non_blocking_kind`` and was never a blocker.
UNCLASSIFIED_SURFACE_VERDICT = "unclassified"
NON_BLOCKING_SURFACE_VERDICT = "non_blocking_kind"


class RepositoryWriteClassificationError(RuntimeError):
    """A classification projection was malformed, stale, or ambiguous."""


class TargetDisposition(str, Enum):
    PRIMARY_CHECKOUT = "primary_checkout"
    CHECKOUT_EXTERNAL = "checkout_external"
    NON_REPOSITORY = "non_repository"
    UNKNOWN = "unknown"


class GuardDisposition(str, Enum):
    CENTRAL = "central"
    LOCAL_GUARDS = "local_guards"
    INVENTORY_ONLY = "inventory_only"
    UNGUARDED = "unguarded"
    RETIRED = "retired"


class EvidenceKind(str, Enum):
    SOURCE_ANCHOR = "source_anchor"
    GUARD_CONTRACT = "guard_contract"
    EFFECT_LEASE_RECEIPT = "effect_lease_receipt"
    RUNTIME_CONFORMANCE_RECEIPT = "runtime_conformance_receipt"
    PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT = (
        "primary_checkout_disjointness_receipt"
    )
    RETIREMENT_RECEIPT = "retirement_receipt"


def surface_binding_sha256(
    source_revision: str, surface: RepositoryWriteSurface
) -> str:
    """Bind evidence to one exact revision and inventory surface identity."""

    if not isinstance(source_revision, str) or not _REVISION.fullmatch(source_revision):
        raise ValueError("surface binding revision must be lowercase 40-hex")
    if not isinstance(surface, RepositoryWriteSurface):
        raise ValueError("surface binding surface must be typed")
    payload = {
        "source_revision": source_revision,
        "surface": surface.to_dict(),
    }
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class EvidenceBinding:
    kind: EvidenceKind
    source_revision: str
    surface_sha256: str
    sha256: str
    locator: str
    guard_contract: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("evidence kind must be typed")
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("evidence source_revision must be lowercase 40-hex")
        if not _SHA256.fullmatch(self.surface_sha256):
            raise ValueError("evidence surface_sha256 must be lowercase 64-hex")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("evidence sha256 must be lowercase 64-hex")
        if (
            not isinstance(self.locator, str)
            or not self.locator.strip()
            or any(ch in self.locator for ch in "\r\n")
        ):
            raise ValueError("evidence locator must be a non-empty single line")
        if self.kind is EvidenceKind.GUARD_CONTRACT:
            if not _CONTRACT.fullmatch(self.guard_contract):
                raise ValueError("guard-contract evidence requires a contract name")
        elif self.guard_contract:
            raise ValueError("non-guard evidence cannot name a guard contract")

    def sort_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.kind.value,
            self.guard_contract,
            self.source_revision,
            self.surface_sha256,
            self.sha256,
            self.locator,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "source_revision": self.source_revision,
            "surface_sha256": self.surface_sha256,
            "sha256": self.sha256,
            "locator": self.locator,
            "guard_contract": self.guard_contract,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "EvidenceBinding":
        _require_exact_keys(
            value,
            {
                "kind",
                "source_revision",
                "surface_sha256",
                "sha256",
                "locator",
                "guard_contract",
            },
            "evidence binding",
        )
        try:
            kind = EvidenceKind(_strict_str(value["kind"], "evidence kind"))
        except ValueError as exc:
            raise RepositoryWriteClassificationError(
                "evidence kind is unknown"
            ) from exc
        try:
            return cls(
                kind=kind,
                source_revision=_strict_str(
                    value["source_revision"], "evidence source_revision"
                ),
                surface_sha256=_strict_str(
                    value["surface_sha256"], "evidence surface_sha256"
                ),
                sha256=_strict_str(value["sha256"], "evidence sha256"),
                locator=_strict_str(value["locator"], "evidence locator"),
                guard_contract=_strict_str(
                    value["guard_contract"], "evidence guard_contract"
                ),
            )
        except ValueError as exc:
            raise RepositoryWriteClassificationError(
                "evidence binding is invalid"
            ) from exc


@dataclass(frozen=True)
class SurfaceClassification:
    source_revision: str
    surface: RepositoryWriteSurface
    target: TargetDisposition
    guard: GuardDisposition
    production_reachable: bool
    guard_contracts: tuple[str, ...]
    evidence: tuple[EvidenceBinding, ...]
    notes: str = ""
    # In-process only, and deliberately invisible to ``to_dict`` and
    # ``from_dict``: a document must never be able to mint one.  It is excluded
    # from ``__eq__``/``__hash__`` so a row's identity stays exactly its eight
    # wire fields -- two rows that differ here already differ in ``evidence``,
    # because the one without an admission must carry the runtime receipt.
    non_runtime_conformity: "NonRuntimeConformityAdmission | None" = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("classification source_revision must be lowercase 40-hex")
        if not isinstance(self.surface, RepositoryWriteSurface):
            raise ValueError("classification surface must be typed")
        if not isinstance(self.target, TargetDisposition):
            raise ValueError("target disposition must be typed")
        if not isinstance(self.guard, GuardDisposition):
            raise ValueError("guard disposition must be typed")
        if type(self.production_reachable) is not bool:
            raise ValueError("production_reachable must be a strict boolean")
        if not isinstance(self.guard_contracts, tuple):
            raise ValueError("guard_contracts must be an immutable tuple")
        if tuple(sorted(self.guard_contracts)) != self.guard_contracts:
            raise ValueError("guard_contracts must be sorted")
        if len(set(self.guard_contracts)) != len(self.guard_contracts):
            raise ValueError("guard_contracts must be unique")
        if any(not _CONTRACT.fullmatch(name) for name in self.guard_contracts):
            raise ValueError("guard contract name is invalid")
        if not isinstance(self.evidence, tuple):
            raise ValueError("evidence must be an immutable tuple")
        if tuple(sorted(self.evidence, key=EvidenceBinding.sort_key)) != self.evidence:
            raise ValueError("evidence must be canonically sorted")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("evidence must be unique")
        if any(item.source_revision != self.source_revision for item in self.evidence):
            raise ValueError("evidence revision differs from classification revision")
        expected_surface_sha256 = surface_binding_sha256(
            self.source_revision, self.surface
        )
        if any(
            item.surface_sha256 != expected_surface_sha256 for item in self.evidence
        ):
            raise ValueError("evidence surface binding differs from classification")
        if not isinstance(self.notes, str) or any(ch in self.notes for ch in "\r\n"):
            raise ValueError("notes must be a single line")

        kinds = {item.kind for item in self.evidence}
        evidenced_contracts = {
            item.guard_contract
            for item in self.evidence
            if item.kind is EvidenceKind.GUARD_CONTRACT
        }
        if self.target in {
            TargetDisposition.CHECKOUT_EXTERNAL,
            TargetDisposition.NON_REPOSITORY,
        } and EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT not in kinds:
            raise ValueError(
                "disjoint target classification requires a disjointness receipt"
            )
        if (
            not self.production_reachable
            and self.guard is not GuardDisposition.RETIRED
        ):
            raise ValueError(
                "non-reachable classification requires retired disposition"
            )
        if self.non_runtime_conformity is not None:
            # One meaning, one place.  The admission excuses exactly one
            # evidence kind on exactly one disposition; anywhere else it would
            # be a field with no contract behind it.
            if type(self.non_runtime_conformity) is not NonRuntimeConformityAdmission:
                raise ValueError(
                    "non-runtime conformity must be an exact typed admission"
                )
            if self.guard is not GuardDisposition.CENTRAL:
                raise ValueError(
                    "non-runtime conformity admission requires central disposition"
                )
            if self.non_runtime_conformity.source_revision != self.source_revision:
                raise ValueError(
                    "non-runtime conformity admission revision differs from the row"
                )
            if self.non_runtime_conformity.surface_sha256 != expected_surface_sha256:
                raise ValueError(
                    "non-runtime conformity admission binds another surface"
                )
        if self.guard is GuardDisposition.CENTRAL:
            required = {
                EvidenceKind.GUARD_CONTRACT,
                EvidenceKind.EFFECT_LEASE_RECEIPT,
                EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,
                EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
            }
            if self.non_runtime_conformity is not None:
                # The ONLY relaxation, and only this one kind.  The admission
                # verified the collector signature and replayed the retained
                # execution as a NonRuntimeEffectAuthorization when it was
                # constructed -- see NonRuntimeConformityAdmission below.  A
                # surface excused as non-runtime that still carries a runtime
                # receipt is claiming both things at once and is refused.
                if EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT in kinds:
                    raise ValueError(
                        "non-runtime central classification retains a runtime receipt"
                    )
                required.discard(EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT)
            if self.target in {
                TargetDisposition.PRIMARY_CHECKOUT,
                TargetDisposition.UNKNOWN,
            }:
                raise ValueError("central classification requires a disjoint target")
            if not self.guard_contracts:
                raise ValueError("central classification requires guard contracts")
            if evidenced_contracts != set(self.guard_contracts):
                raise ValueError("central guard evidence does not match guard contracts")
            if not required.issubset(kinds):
                raise ValueError("central classification lacks required evidence kinds")
        elif self.guard is GuardDisposition.LOCAL_GUARDS:
            if not self.guard_contracts:
                raise ValueError("local_guards requires guard contracts")
            if evidenced_contracts != set(self.guard_contracts):
                raise ValueError("local_guards evidence does not match guard contracts")
        elif self.guard is GuardDisposition.RETIRED:
            if self.production_reachable:
                raise ValueError("retired classification cannot remain production reachable")
            if self.guard_contracts:
                raise ValueError("retired classification cannot declare guard contracts")
            if EvidenceKind.RETIREMENT_RECEIPT not in kinds:
                raise ValueError("retired classification requires a retirement receipt")

    def sort_key(self) -> tuple[str, int, int, str]:
        return (
            self.surface.path,
            self.surface.line,
            self.surface.column,
            self.surface.origin,
        )

    @property
    def candidate_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.target is TargetDisposition.PRIMARY_CHECKOUT:
            blockers.append("primary-checkout-write-target")
        elif self.target is TargetDisposition.UNKNOWN:
            blockers.append("write-target-unknown")
        if self.production_reachable and self.guard is not GuardDisposition.CENTRAL:
            blockers.append(f"production-write-{self.guard.value}")
        return tuple(blockers)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_revision": self.source_revision,
            "surface": self.surface.to_dict(),
            "target": self.target.value,
            "guard": self.guard.value,
            "production_reachable": self.production_reachable,
            "guard_contracts": list(self.guard_contracts),
            "evidence": [item.to_dict() for item in self.evidence],
            "notes": self.notes,
            "candidate_blockers": list(self.candidate_blockers),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SurfaceClassification":
        _require_exact_keys(
            value,
            {
                "source_revision",
                "surface",
                "target",
                "guard",
                "production_reachable",
                "guard_contracts",
                "evidence",
                "notes",
            },
            "surface classification",
        )
        surface = _surface_from_dict(_strict_mapping(value["surface"], "surface"))
        try:
            target = TargetDisposition(
                _strict_str(value["target"], "target disposition")
            )
            guard = GuardDisposition(
                _strict_str(value["guard"], "guard disposition")
            )
        except ValueError as exc:
            raise RepositoryWriteClassificationError(
                "classification disposition is unknown"
            ) from exc
        contracts_raw = _strict_list(value["guard_contracts"], "guard_contracts")
        evidence_raw = _strict_list(value["evidence"], "evidence")
        try:
            return cls(
                source_revision=_strict_str(
                    value["source_revision"], "classification source_revision"
                ),
                surface=surface,
                target=target,
                guard=guard,
                production_reachable=_strict_bool(
                    value["production_reachable"], "production_reachable"
                ),
                guard_contracts=tuple(
                    _strict_str(item, "guard contract") for item in contracts_raw
                ),
                evidence=tuple(
                    EvidenceBinding.from_dict(
                        _strict_mapping(item, "evidence binding")
                    )
                    for item in evidence_raw
                ),
                notes=_strict_str(value["notes"], "notes"),
            )
        except ValueError as exc:
            raise RepositoryWriteClassificationError(
                "surface classification is invalid"
            ) from exc


def surface_classification_verdict(row: SurfaceClassification) -> str:
    """Name exactly one verdict for one classified surface.

    The verdict is derived from ``candidate_blockers`` and the guard
    disposition, so it can never claim more than the classification itself
    already claims.  A row with candidate blockers is ``blocked:<reason>``
    (all of its reasons, joined, so no reason is dropped); a row with none is
    ``cleared:<guard disposition>`` — ``cleared:central`` for a surface leased
    under a central door, ``cleared:retired`` for one the classification
    proved unreachable.  Exactly one verdict per surface, so a census over
    verdicts sums to the surface count.
    """

    if not isinstance(row, SurfaceClassification):
        raise RepositoryWriteClassificationError(
            "verdict subject must be a typed surface classification"
        )
    blockers = row.candidate_blockers
    if blockers:
        return "blocked:" + "+".join(blockers)
    return f"cleared:{row.guard.value}"


# --------------------------------------------------------------------------
# Per-surface evidence authentication
# --------------------------------------------------------------------------
#
# A stage report says that ITS stage ran over the material it was given.  It
# never says the other five ran, and it never says anything about one named
# surface unless it carries a record for that surface.  Authentication is
# therefore the strict conjunction, per surface, over the stages that apply to
# that surface -- and an empty applicable set is false, never vacuously true.

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_UTC_INSTANT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?\+00:00$"
)


class AuthenticationStage(str, Enum):
    """The six stages whose agreement authenticates one write surface."""

    MATERIALIZATION = "materialization"
    ORIGIN = "origin"
    ANCHOR = "anchor"
    GUARD = "guard"
    CONFORMITY = "conformity"
    LEASE = "lease"


STAGE_VERDICT_VERIFIED = "verified"
STAGE_VERDICT_NOT_APPLICABLE = "not_applicable"
STAGE_VERDICT_ABSENT = "absent"

# Applicable to every classified row without exception: every row carries at
# least one source anchor, so its evidence bytes must materialize, that
# materialization must be attested by a collector, and the anchor must resolve
# against the exact source at this revision.
ALWAYS_APPLICABLE_STAGES = frozenset(
    {
        AuthenticationStage.MATERIALIZATION,
        AuthenticationStage.ORIGIN,
        AuthenticationStage.ANCHOR,
    }
)

# The evidence kinds the composition is willing to authenticate.  This used to
# be the three receipt kinds alone, which silently excused a surface whose
# claim rests on its source anchor, its guard contract, or its retirement
# receipt.  All six kinds are named, so a row's own evidence must materialize
# in full before the materialization stage will speak for it.
AUTHENTICATED_EVIDENCE_KINDS = frozenset(EvidenceKind)

# The one authorization class that can excuse the conformity stage.  Spelled
# here rather than imported: ``daedalus.kernel.authorization`` is reachable
# from this module, but the name is what a collector signs over, so it is a
# wire constant and not an object reference.
NON_RUNTIME_AUTHORIZATION_CLASS = "NonRuntimeEffectAuthorization"

# Every verifier in this chain imports this module, so the composition cannot
# import them back at module scope.  The exact class is resolved inside the
# call and the stage report must BE that class: a mapping parsed from JSON, a
# namedtuple, or any look-alike is refused.  Holding one of these objects means
# the verifier that returns it ran in this process.
_STAGE_REPORT_TYPES: dict[AuthenticationStage, tuple[str, str]] = {
    AuthenticationStage.MATERIALIZATION: (
        "daedalus.gates.repository_write_evidence_materialization",
        "RepositoryWriteEvidenceMaterializationReport",
    ),
    AuthenticationStage.ORIGIN: (
        "daedalus.gates.repository_write_evidence_origin",
        "RepositoryWriteEvidenceOriginReport",
    ),
    AuthenticationStage.ANCHOR: (
        "daedalus.gates.repository_write_source_anchor_semantics",
        "RepositoryWriteSourceAnchorSemanticsReport",
    ),
    AuthenticationStage.GUARD: (
        "daedalus.gates.repository_write_guard_structure",
        "RepositoryWriteGuardStructureReport",
    ),
    AuthenticationStage.CONFORMITY: (
        "daedalus.gates.repository_write_runtime_conformance",
        "RepositoryWriteRuntimeConformanceReport",
    ),
    AuthenticationStage.LEASE: (
        "daedalus.gates.repository_write_effect_lease",
        "RepositoryWriteEffectLeaseReport",
    ),
}


# The verifier each stage report may only come out of.  Resolved by name at
# call time, deliberately: the composition below runs THESE functions, so a
# test can substitute one and see that it was invoked, and nobody can hand the
# composition a finished report instead.
_STAGE_VERIFIERS: dict[AuthenticationStage, tuple[str, str]] = {
    AuthenticationStage.MATERIALIZATION: (
        "daedalus.gates.repository_write_evidence_materialization",
        "materialize_repository_write_evidence",
    ),
    AuthenticationStage.ORIGIN: (
        "daedalus.gates.repository_write_evidence_origin",
        "verify_repository_write_evidence_origin",
    ),
    AuthenticationStage.ANCHOR: (
        "daedalus.gates.repository_write_source_anchor_semantics",
        "verify_repository_write_source_anchor_semantics",
    ),
    AuthenticationStage.GUARD: (
        "daedalus.gates.repository_write_guard_structure",
        "verify_repository_write_guard_structure",
    ),
    AuthenticationStage.CONFORMITY: (
        "daedalus.gates.repository_write_runtime_conformance",
        "verify_repository_write_runtime_conformance",
    ),
    AuthenticationStage.LEASE: (
        "daedalus.gates.repository_write_effect_lease",
        "verify_repository_write_effect_leases",
    ),
}


def stage_report_type(stage: AuthenticationStage) -> type:
    """Resolve the exact report class one stage is allowed to be."""

    if not isinstance(stage, AuthenticationStage):
        raise RepositoryWriteClassificationError("authentication stage must be typed")
    module_name, class_name = _STAGE_REPORT_TYPES[stage]
    return getattr(importlib.import_module(module_name), class_name)


def stage_verifier(stage: AuthenticationStage):
    """Resolve the exact verifier one stage report may only come out of."""

    if not isinstance(stage, AuthenticationStage):
        raise RepositoryWriteClassificationError("authentication stage must be typed")
    module_name, function_name = _STAGE_VERIFIERS[stage]
    return getattr(importlib.import_module(module_name), function_name)


@dataclass(frozen=True, eq=False)
class RepositoryWriteAuthenticationInputs:
    """Every RAW input the six verifiers need, and nothing else.

    There is deliberately no stage report among these fields.  The composition
    below builds each stage report by running that stage's verifier over this
    material -- the retained CAS objects, the signed attestation and guard
    manifest, the retained runtime and execution records, the keyrings and the
    clock -- so a caller cannot supply a finished report by any route.

    The report-shaped members are typed ``object`` on purpose: each verifier
    performs its own exact-type check, and that check is the truth boundary.
    Restating it here would be a second, weaker copy of it.
    """

    blobs: Mapping[str, bytes]
    origin_attestation: object
    guard_manifest: object
    runtime_subjects: Mapping[str, object]
    runtime_trust_ledgers: Mapping[str, object]
    effect_subjects: Mapping[str, object]
    collector_keyring: Mapping[tuple[str, str], bytes | str]
    expected_collector_id: str
    guard_keyring: Mapping[tuple[str, str], bytes | str]
    expected_guard_authority_id: str
    current_revision: str
    now: object
    repository_root: object

    def __post_init__(self) -> None:
        for name in (
            "blobs",
            "runtime_subjects",
            "runtime_trust_ledgers",
            "effect_subjects",
            "collector_keyring",
            "guard_keyring",
        ):
            if not isinstance(getattr(self, name), Mapping):
                raise RepositoryWriteClassificationError(
                    f"authentication input {name} must be a mapping"
                )
        for name in (
            "expected_collector_id",
            "expected_guard_authority_id",
        ):
            if not _IDENTIFIER.fullmatch(str(getattr(self, name))):
                raise RepositoryWriteClassificationError(
                    f"authentication input {name} must be a bounded identifier"
                )
        if not _REVISION.fullmatch(str(self.current_revision)):
            raise RepositoryWriteClassificationError(
                "authentication input current_revision must be lowercase 40-hex"
            )


def _run_stage_verifiers(
    report: "RepositoryWriteClassificationReport",
    inputs: RepositoryWriteAuthenticationInputs,
) -> dict[AuthenticationStage, object]:
    """Build all six stage reports here, by running all six verifiers here.

    Codex point 1.  Before this, the composition took stage reports that had
    been built somewhere else and only checked their type and binding; the
    checks were real but the running of the verifier was somebody else's
    business, so a caller who could construct the report class could satisfy
    them.  Now the only way a stage report exists is that this function called
    that stage's verifier on raw inputs, in this process, against this exact
    classification.  ``origin`` consumes the materialization report because its
    verifier requires one -- built two lines above, in this call, never handed
    in.
    """

    if type(inputs) is not RepositoryWriteAuthenticationInputs:
        raise RepositoryWriteClassificationError(
            "authentication inputs must be the exact typed raw-input record"
        )
    if inputs.current_revision != report.source_revision:
        raise RepositoryWriteClassificationError(
            "authentication inputs name another revision than the classification"
        )
    collector = dict(
        keyring=inputs.collector_keyring,
        expected_collector_id=inputs.expected_collector_id,
        current_revision=inputs.current_revision,
        now=inputs.now,
    )
    guard = dict(
        collector_keyring=inputs.collector_keyring,
        expected_collector_id=inputs.expected_collector_id,
        guard_keyring=inputs.guard_keyring,
        expected_guard_authority_id=inputs.expected_guard_authority_id,
        current_revision=inputs.current_revision,
        now=inputs.now,
        repository_root=inputs.repository_root,
    )
    reports: dict[AuthenticationStage, object] = {}
    materialization = stage_verifier(AuthenticationStage.MATERIALIZATION)(
        report,
        inputs.blobs,
    )
    reports[AuthenticationStage.MATERIALIZATION] = materialization
    reports[AuthenticationStage.ORIGIN] = stage_verifier(
        AuthenticationStage.ORIGIN
    )(inputs.origin_attestation, materialization, **collector)
    reports[AuthenticationStage.ANCHOR] = stage_verifier(
        AuthenticationStage.ANCHOR
    )(
        report,
        inputs.blobs,
        inputs.origin_attestation,
        **collector,
        repository_root=inputs.repository_root,
    )
    reports[AuthenticationStage.GUARD] = stage_verifier(
        AuthenticationStage.GUARD
    )(report, inputs.blobs, inputs.origin_attestation, inputs.guard_manifest, **guard)
    reports[AuthenticationStage.CONFORMITY] = stage_verifier(
        AuthenticationStage.CONFORMITY
    )(
        report,
        inputs.blobs,
        inputs.origin_attestation,
        inputs.guard_manifest,
        inputs.runtime_subjects,
        inputs.runtime_trust_ledgers,
        **guard,
    )
    reports[AuthenticationStage.LEASE] = stage_verifier(AuthenticationStage.LEASE)(
        report,
        inputs.blobs,
        inputs.origin_attestation,
        inputs.guard_manifest,
        inputs.runtime_subjects,
        inputs.runtime_trust_ledgers,
        inputs.effect_subjects,
        **guard,
    )
    return reports


def _collector_secret_bytes(secret: bytes | str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif type(secret) is bytes:
        value = secret
    else:
        raise RepositoryWriteClassificationError(
            "collector secret must be bytes or text"
        )
    if len(value) < 32:
        raise RepositoryWriteClassificationError(
            "collector secret must contain at least 32 bytes"
        )
    return value


def _collector_signature(signing_digest: str, secret: bytes | str) -> str:
    # Deliberately the same construction as the evidence-origin attestation:
    # HMAC-SHA256 over the canonical signing digest.  It is spelled out again
    # here because the origin module sits downstream of this one and cannot be
    # imported at module scope.
    return hmac.new(
        _collector_secret_bytes(secret),
        signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True)
class NonRuntimeConformityBinding:
    """A collector's signed statement that one surface replayed non-runtime.

    This is the ONLY thing that can turn the conformity stage into
    ``not_applicable``.  It is a replay fact about a retained execution, so it
    is signed by the collector that read the ledger -- exactly like every other
    stage in the chain -- and it is never a field a caller may declare.
    ``project_classification_input`` accepts four keys and a classification row
    eight; none of them is a stage, an applicability, or a binding, so no JSON
    document can mint one.
    """

    source_revision: str
    surface_sha256: str
    execution_id: str
    authorization_class: str
    collector_id: str
    collector_key_id: str
    issued_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("binding source_revision must be lowercase 40-hex")
        if not _SHA256.fullmatch(self.surface_sha256):
            raise ValueError("binding surface_sha256 must be lowercase 64-hex")
        for name in ("execution_id", "collector_id", "collector_key_id"):
            if not isinstance(getattr(self, name), str) or not _IDENTIFIER.fullmatch(
                getattr(self, name)
            ):
                raise ValueError(f"binding {name} must be a bounded identifier")
        if self.authorization_class != NON_RUNTIME_AUTHORIZATION_CLASS:
            raise ValueError(
                "conformity binding must name the non-runtime authorization class"
            )
        if not isinstance(self.issued_at, str) or not _UTC_INSTANT.fullmatch(
            self.issued_at
        ):
            raise ValueError("binding issued_at must be canonical UTC ISO-8601")
        if not _SHA256.fullmatch(self.signature_sha256):
            raise ValueError("binding signature must be lowercase 64-hex")

    def signing_payload(self) -> dict[str, str]:
        return {
            "schema": "daedalus-gate0-non-runtime-conformity-binding/1",
            "source_revision": self.source_revision,
            "surface_sha256": self.surface_sha256,
            "execution_id": self.execution_id,
            "authorization_class": self.authorization_class,
            "collector_id": self.collector_id,
            "collector_key_id": self.collector_key_id,
            "issued_at": self.issued_at,
        }

    @property
    def signing_digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.signing_payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return {**self.signing_payload(), "signature_sha256": self.signature_sha256}


def issue_non_runtime_conformity_binding(
    *,
    source_revision: str,
    surface_sha256: str,
    execution_id: str,
    collector_id: str,
    collector_key_id: str,
    issued_at: str,
    secret: bytes | str,
) -> NonRuntimeConformityBinding:
    """Sign one replay fact.  Only a holder of the collector secret can."""

    draft = NonRuntimeConformityBinding(
        source_revision=source_revision,
        surface_sha256=surface_sha256,
        execution_id=execution_id,
        authorization_class=NON_RUNTIME_AUTHORIZATION_CLASS,
        collector_id=collector_id,
        collector_key_id=collector_key_id,
        issued_at=issued_at,
        signature_sha256="0" * 64,
    )
    return NonRuntimeConformityBinding(
        source_revision=draft.source_revision,
        surface_sha256=draft.surface_sha256,
        execution_id=draft.execution_id,
        authorization_class=draft.authorization_class,
        collector_id=draft.collector_id,
        collector_key_id=draft.collector_key_id,
        issued_at=draft.issued_at,
        signature_sha256=_collector_signature(draft.signing_digest, secret),
    )


def verify_non_runtime_conformity_binding(
    binding: NonRuntimeConformityBinding,
    *,
    collector_secrets: Mapping[str, bytes | str],
) -> None:
    """Refuse an unsigned, foreign-signed, or unknown-collector binding."""

    if type(binding) is not NonRuntimeConformityBinding:
        raise RepositoryWriteClassificationError(
            "conformity binding must be an exact typed binding"
        )
    if not isinstance(collector_secrets, Mapping):
        raise RepositoryWriteClassificationError(
            "collector secrets must be a mapping"
        )
    secret = collector_secrets.get(binding.collector_key_id)
    if secret is None:
        raise RepositoryWriteClassificationError(
            "conformity binding names an unknown collector key"
        )
    expected = _collector_signature(binding.signing_digest, secret)
    if not hmac.compare_digest(expected, binding.signature_sha256):
        raise RepositoryWriteClassificationError(
            "conformity binding signature does not verify"
        )


@dataclass(frozen=True, eq=False)
class NonRuntimeConformityAdmission:
    """A verified binding plus the replay that was performed to admit it.

    This is what a ``central`` row may hold in place of its runtime-conformance
    receipt, and it is a construction-time gate rather than a declaration.  Two
    independent things happen in ``__post_init__`` and both must pass:

    * the collector signature over the binding verifies against a key the
      caller had to hold, and
    * the retained execution the binding names is replayed, by the Effect-Lease
      module's own typed check, and must come back as a
      ``NonRuntimeEffectAuthorization``.

    A field saying ``non_runtime`` is a claim.  This calls the verifier that
    re-derives the fact from the effect ledger, so holding an admission means a
    replay actually ran.  There is no wire shape for it: ``to_dict`` does not
    emit it and ``from_dict`` has no key for it, so a declaration document can
    never produce a row that carries one.  The price of forging one is the
    collector key *and* a retained non-runtime execution for that exact
    surface -- neither of which a document can supply.
    """

    binding: NonRuntimeConformityBinding
    subject: object
    collector_secrets: Mapping[str, bytes | str] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.binding) is not NonRuntimeConformityBinding:
            raise ValueError("admission binding must be an exact typed binding")
        verify_non_runtime_conformity_binding(
            self.binding,
            collector_secrets=self.collector_secrets,
        )
        # Imported here, not at module scope: the Effect-Lease module sits
        # downstream of this one and importing it at the top would close a
        # cycle.  The check is still that module's, not a copy of it.
        from daedalus.gates.repository_write_effect_lease import (
            replay_non_runtime_effect_subject,
        )

        replay_non_runtime_effect_subject(
            self.subject,
            expected_execution_id=self.binding.execution_id,
        )

    @property
    def source_revision(self) -> str:
        return self.binding.source_revision

    @property
    def surface_sha256(self) -> str:
        return self.binding.surface_sha256

    @property
    def execution_id(self) -> str:
        return self.binding.execution_id


def applicable_authentication_stages(
    row: SurfaceClassification,
    *,
    non_runtime_conformity_surfaces: frozenset[str] = frozenset(),
) -> frozenset[AuthenticationStage]:
    """Name the stages that must agree before THIS row is authenticated.

    Applicability is read off the typed row and off one signed replay fact,
    never off a declaration.  ``project_classification_input`` accepts exactly
    ``{schema, source_revision, inventory_digest, classifications}`` and a row
    exactly the eight keys of ``SurfaceClassification``; none of them names a
    stage.  There is no JSON path that can add or remove one.
    """

    if not isinstance(row, SurfaceClassification):
        raise RepositoryWriteClassificationError(
            "applicability subject must be a typed surface classification"
        )
    if not isinstance(non_runtime_conformity_surfaces, frozenset):
        raise RepositoryWriteClassificationError(
            "non-runtime conformity surfaces must be an immutable set"
        )
    stages = set(ALWAYS_APPLICABLE_STAGES)
    if row.guard_contracts:
        stages.add(AuthenticationStage.GUARD)
    if row.production_reachable:
        stages.add(AuthenticationStage.LEASE)
    if (
        row.non_runtime_conformity is None
        and surface_binding_sha256(row.source_revision, row.surface)
        not in non_runtime_conformity_surfaces
    ):
        stages.add(AuthenticationStage.CONFORMITY)
    return frozenset(stages)


def authenticated_over_stages(
    applicable: frozenset[AuthenticationStage],
    verdicts: Mapping[AuthenticationStage, str],
) -> bool:
    """Strict conjunction over the applicable stages."""

    if not applicable:
        # ``all(())`` is True in Python, and a surface no stage applies to is
        # exactly the overclaim this guard exists to refuse.  An empty
        # applicable set is unauthenticated, never vacuously authenticated.
        return False
    return all(
        verdicts.get(stage) == STAGE_VERDICT_VERIFIED for stage in applicable
    )


@dataclass(frozen=True)
class SurfaceEvidenceAuthentication:
    """One surface's stage verdicts and the conjunction over them."""

    source_revision: str
    surface_sha256: str
    path: str
    line: int
    column: int
    origin: str
    applicable: frozenset[AuthenticationStage]
    verdicts: tuple[tuple[str, str], ...]
    authenticated: bool
    not_applicable_binding: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source_revision": self.source_revision,
            "surface_sha256": self.surface_sha256,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "origin": self.origin,
            "applicable": sorted(stage.value for stage in self.applicable),
            "stages": {name: verdict for name, verdict in self.verdicts},
            "authenticated": self.authenticated,
            "not_applicable_binding": self.not_applicable_binding,
        }


def _surface_records(report: object, surface_sha256: str) -> tuple[object, ...]:
    return tuple(
        record
        for record in getattr(report, "records", ())
        if getattr(record, "surface_sha256", None) == surface_sha256
    )


def _stage_verdict(
    stage: AuthenticationStage,
    row: SurfaceClassification,
    surface_sha256: str,
    reports: Mapping[AuthenticationStage, object],
) -> str:
    report = reports.get(stage)
    if report is None:
        return STAGE_VERDICT_ABSENT
    if stage is AuthenticationStage.MATERIALIZATION:
        if not report.materialization_complete:
            return STAGE_VERDICT_ABSENT
        kinds = {
            record.kind for record in _surface_records(report, surface_sha256)
        }
        required = {item.kind for item in row.evidence}
        if not required or not required.issubset(kinds):
            return STAGE_VERDICT_ABSENT
        if not required.issubset(AUTHENTICATED_EVIDENCE_KINDS):
            return STAGE_VERDICT_ABSENT
        return STAGE_VERDICT_VERIFIED
    if stage is AuthenticationStage.ORIGIN:
        # The attestation signs one complete materialization, not one surface.
        # It can therefore only speak for a surface the materialization stage
        # already verified, and only while it names that exact materialization.
        materialization = reports.get(AuthenticationStage.MATERIALIZATION)
        if materialization is None:
            return STAGE_VERDICT_ABSENT
        if report.materialization_digest != materialization.digest:
            return STAGE_VERDICT_ABSENT
        if (
            _stage_verdict(
                AuthenticationStage.MATERIALIZATION, row, surface_sha256, reports
            )
            != STAGE_VERDICT_VERIFIED
        ):
            return STAGE_VERDICT_ABSENT
        return STAGE_VERDICT_VERIFIED
    records = _surface_records(report, surface_sha256)
    if not records:
        return STAGE_VERDICT_ABSENT
    if stage is AuthenticationStage.GUARD:
        contracts = {record.contract for record in records}
        if not contracts or contracts != set(row.guard_contracts):
            return STAGE_VERDICT_ABSENT
    return STAGE_VERDICT_VERIFIED


def authenticate_repository_write_surfaces(
    report: "RepositoryWriteClassificationReport",
    *,
    inputs: RepositoryWriteAuthenticationInputs | None = None,
    non_runtime_bindings: Iterable[NonRuntimeConformityBinding] = (),
    collector_secrets: Mapping[str, bytes | str] | None = None,
) -> dict[RepositoryWriteSurface, SurfaceEvidenceAuthentication]:
    """Run the six verifiers and compose one verdict per classified surface.

    This is the only public entry on the report path, and it has no parameter
    that could carry a stage report.  Stages exist here because ``inputs`` was
    given and ``_run_stage_verifiers`` ran all six over that raw material; with
    no inputs every stage is ``absent`` and nothing authenticates, which is the
    honest state of a reporter that has not been wired to the evidence yet.
    """

    if type(report) is not RepositoryWriteClassificationReport:
        raise RepositoryWriteClassificationError(
            "authentication subject must be a typed classification report"
        )
    return _compose_authenticated_surfaces(
        report,
        _run_stage_verifiers(report, inputs) if inputs is not None else {},
        non_runtime_bindings=non_runtime_bindings,
        collector_secrets=collector_secrets,
    )


def _compose_authenticated_surfaces(
    report: "RepositoryWriteClassificationReport",
    stage_reports: Mapping[AuthenticationStage, object] | None = None,
    *,
    non_runtime_bindings: Iterable[NonRuntimeConformityBinding] = (),
    collector_secrets: Mapping[str, bytes | str] | None = None,
) -> dict[RepositoryWriteSurface, SurfaceEvidenceAuthentication]:
    """Compose stage reports into one verdict per classified surface.

    Private, and not on the report path: the only caller that can reach it in
    production is ``authenticate_repository_write_surfaces``, which supplies
    reports it built itself.  The checks below are kept here rather than folded
    into ``_run_stage_verifiers`` so that every report entering the composition
    -- however it was built -- must still be the exact class its verifier
    returns and must still name this exact classification digest and revision.
    """

    if type(report) is not RepositoryWriteClassificationReport:
        raise RepositoryWriteClassificationError(
            "authentication subject must be a typed classification report"
        )
    reports: dict[AuthenticationStage, object] = {}
    for stage, value in dict(stage_reports or {}).items():
        if not isinstance(stage, AuthenticationStage):
            raise RepositoryWriteClassificationError(
                "stage report key must be a typed authentication stage"
            )
        if type(value) is not stage_report_type(stage):
            raise RepositoryWriteClassificationError(
                "stage report must be the exact typed report its verifier returns"
            )
        if value.source_revision != report.source_revision:
            raise RepositoryWriteClassificationError(
                "stage report source revision differs from the classification"
            )
        if value.classification_digest != report.digest:
            raise RepositoryWriteClassificationError(
                "stage report is bound to a different classification"
            )
        reports[stage] = value

    secrets = dict(collector_secrets or {})
    excused: dict[str, str] = {}
    for binding in tuple(non_runtime_bindings):
        verify_non_runtime_conformity_binding(binding, collector_secrets=secrets)
        if binding.source_revision != report.source_revision:
            raise RepositoryWriteClassificationError(
                "conformity binding revision differs from the classification"
            )
        if binding.surface_sha256 in excused:
            raise RepositoryWriteClassificationError(
                "conformity binding is duplicated for one surface"
            )
        conformity = reports.get(AuthenticationStage.CONFORMITY)
        if conformity is not None and _surface_records(
            conformity, binding.surface_sha256
        ):
            # The other direction of the fail-closed rule: a surface declared
            # non-runtime whose conformity stage retained a runtime replay is
            # runtime work wearing a non-runtime label, and the excuse is
            # refused rather than the record ignored.
            raise RepositoryWriteClassificationError(
                "surface declared non-runtime retains a runtime conformance replay"
            )
        lease = reports.get(AuthenticationStage.LEASE)
        for record in _surface_records(lease, binding.surface_sha256):
            # The replay fact itself, as the lease stage re-derived it from the
            # retained execution.  A record that came back runtime-bound
            # refutes the signature, and one naming another execution is not
            # about this write at all.  A signed field is not a replay.
            if (
                record.runtime_bound is not False
                or record.runtime_id is not None
                or record.execution_id != binding.execution_id
            ):
                raise RepositoryWriteClassificationError(
                    "non-runtime conformity binding contradicts the retained replay"
                )
        excused[binding.surface_sha256] = binding.execution_id

    excused_surfaces = frozenset(excused)
    result: dict[RepositoryWriteSurface, SurfaceEvidenceAuthentication] = {}
    for row in report.classifications:
        surface_sha256 = surface_binding_sha256(row.source_revision, row.surface)
        applicable = applicable_authentication_stages(
            row, non_runtime_conformity_surfaces=excused_surfaces
        )
        verdicts = {
            stage: (
                _stage_verdict(stage, row, surface_sha256, reports)
                if stage in applicable
                else STAGE_VERDICT_NOT_APPLICABLE
            )
            for stage in AuthenticationStage
        }
        result[row.surface] = SurfaceEvidenceAuthentication(
            source_revision=row.source_revision,
            surface_sha256=surface_sha256,
            path=row.surface.path,
            line=row.surface.line,
            column=row.surface.column,
            origin=row.surface.origin,
            applicable=applicable,
            verdicts=tuple(
                sorted((stage.value, verdict) for stage, verdict in verdicts.items())
            ),
            authenticated=authenticated_over_stages(applicable, verdicts),
            not_applicable_binding=excused.get(surface_sha256, ""),
        )
    return result


@dataclass(frozen=True)
class RepositoryWriteClassificationReport:
    source_revision: str
    inventory_digest: str
    scan_input_sha256: str
    inventory_surface_count: int
    classifications: tuple[SurfaceClassification, ...]
    missing_surfaces: tuple[RepositoryWriteSurface, ...]

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("report source_revision must be lowercase 40-hex")
        if not _SHA256.fullmatch(self.inventory_digest):
            raise ValueError("inventory_digest must be lowercase sha256")
        if not _SHA256.fullmatch(self.scan_input_sha256):
            raise ValueError("scan_input_sha256 must be lowercase sha256")
        if type(self.inventory_surface_count) is not int or self.inventory_surface_count < 0:
            raise ValueError("inventory_surface_count must be a non-negative integer")
        if not isinstance(self.classifications, tuple):
            raise ValueError("classifications must be an immutable tuple")
        if any(not isinstance(row, SurfaceClassification) for row in self.classifications):
            raise ValueError("classification row type is invalid")
        if not isinstance(self.missing_surfaces, tuple):
            raise ValueError("missing_surfaces must be an immutable tuple")
        if any(not isinstance(row, RepositoryWriteSurface) for row in self.missing_surfaces):
            raise ValueError("missing surface type is invalid")
        if tuple(sorted(self.classifications, key=SurfaceClassification.sort_key)) != self.classifications:
            raise ValueError("classifications must be sorted")
        if tuple(sorted(self.missing_surfaces)) != self.missing_surfaces:
            raise ValueError("missing_surfaces must be sorted")
        classified = tuple(row.surface for row in self.classifications)
        if len(set(classified)) != len(classified):
            raise ValueError("classification surfaces must be unique")
        if len(set(self.missing_surfaces)) != len(self.missing_surfaces):
            raise ValueError("missing surfaces must be unique")
        if set(classified).intersection(self.missing_surfaces):
            raise ValueError("classified and missing surfaces must be disjoint")
        if any(row.source_revision != self.source_revision for row in self.classifications):
            raise ValueError("classification revision differs from report revision")
        if self.inventory_surface_count != len(classified) + len(self.missing_surfaces):
            raise ValueError("inventory surface count does not match report projection")

    @property
    def candidate_blockers(self) -> tuple[str, ...]:
        values: set[str] = set()
        if self.missing_surfaces:
            values.add("unclassified-production-write-surfaces")
        for row in self.classifications:
            values.update(row.candidate_blockers)
        return tuple(sorted(values))

    @property
    def classification_ready(self) -> bool:
        return not self.missing_surfaces and not self.candidate_blockers

    def _payload(self) -> dict[str, object]:
        blockers = list(self.candidate_blockers)
        blockers.extend(
            [
                "authenticated-evidence-verification-missing",
                "gate-report-binding-missing",
            ]
        )
        return {
            "schema": "daedalus-gate0-repository-write-classification/2",
            "source_revision": self.source_revision,
            "inventory_digest": self.inventory_digest,
            "scan_input_sha256": self.scan_input_sha256,
            "inventory_surface_count": self.inventory_surface_count,
            "classification_count": len(self.classifications),
            "classifications": [row.to_dict() for row in self.classifications],
            "missing_surfaces": [row.to_dict() for row in self.missing_surfaces],
            "classification_ready": self.classification_ready,
            # No ``evidence_authenticated`` key.  See CLASSIFICATION_SCHEMA:
            # authentication is per surface and is not a property of this
            # report, so this wire does not carry a name for it at all.
            "primary_checkout_target_proven": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-classification-preparation",
            "blockers": sorted(set(blockers)),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def project_repository_write_classifications(
    inventory: RepositoryWriteInventoryV2,
    classifications: Iterable[SurfaceClassification],
) -> RepositoryWriteClassificationReport:
    if not isinstance(inventory, RepositoryWriteInventoryV2):
        raise RepositoryWriteClassificationError("inventory type is invalid")
    try:
        rows_unsorted = tuple(classifications)
    except TypeError as exc:
        raise RepositoryWriteClassificationError(
            "classifications must be iterable"
        ) from exc
    if any(not isinstance(row, SurfaceClassification) for row in rows_unsorted):
        raise RepositoryWriteClassificationError("classification type is invalid")
    rows = tuple(sorted(rows_unsorted, key=SurfaceClassification.sort_key))
    if any(row.source_revision != inventory.source_revision for row in rows):
        raise RepositoryWriteClassificationError(
            "classification source revision differs from inventory"
        )
    by_surface: dict[RepositoryWriteSurface, SurfaceClassification] = {}
    inventory_surfaces = set(inventory.surfaces)
    for row in rows:
        if row.surface not in inventory_surfaces:
            raise RepositoryWriteClassificationError(
                "classification surface is absent from the bound inventory"
            )
        if row.surface in by_surface:
            raise RepositoryWriteClassificationError(
                "classification surface is duplicated"
            )
        by_surface[row.surface] = row
    missing = tuple(sorted(inventory_surfaces - set(by_surface)))
    return RepositoryWriteClassificationReport(
        source_revision=inventory.source_revision,
        inventory_digest=inventory.digest,
        scan_input_sha256=inventory.scan_input_sha256,
        inventory_surface_count=len(inventory.surfaces),
        classifications=rows,
        missing_surfaces=missing,
    )


def parse_inventory_v2(value: Mapping[str, object]) -> RepositoryWriteInventoryV2:
    required = {
        "schema",
        "source_revision",
        "package_root",
        "scan_input_sha256",
        "files_scanned",
        "components",
        "surfaces",
        "surface_count",
        "blocker_count",
        "closed",
        "canonical_scanner_integrated",
        "inventory_generation",
        "scope",
        "inventory_only",
        "primary_checkout_target_proven",
        "blockers",
        "digest",
    }
    _require_exact_keys(value, required, "inventory v2")
    if value["schema"] != "daedalus-gate0-repository-write-inventory/2":
        raise RepositoryWriteClassificationError("inventory schema is unsupported")
    components = _strict_mapping(value["components"], "inventory components")
    _require_exact_keys(
        components,
        {"base_inventory_digest", "stdlib_delta_digest"},
        "inventory components",
    )
    surfaces_raw = _strict_list(value["surfaces"], "inventory surfaces")
    try:
        inventory = RepositoryWriteInventoryV2(
            source_revision=_strict_str(value["source_revision"], "source_revision"),
            package_root=_strict_str(value["package_root"], "package_root"),
            scan_input_sha256=_strict_str(
                value["scan_input_sha256"], "scan_input_sha256"
            ),
            files_scanned=_strict_int(value["files_scanned"], "files_scanned"),
            base_inventory_digest=_strict_str(
                components["base_inventory_digest"], "base_inventory_digest"
            ),
            stdlib_delta_digest=_strict_str(
                components["stdlib_delta_digest"], "stdlib_delta_digest"
            ),
            surfaces=tuple(
                _surface_from_dict(_strict_mapping(item, "inventory surface"))
                for item in surfaces_raw
            ),
        )
    except ValueError as exc:
        raise RepositoryWriteClassificationError("inventory v2 is invalid") from exc
    if inventory.to_dict() != dict(value):
        raise RepositoryWriteClassificationError(
            "inventory derived fields or digest do not match canonical material"
        )
    return inventory


def project_classification_input(
    inventory: RepositoryWriteInventoryV2,
    value: Mapping[str, object],
) -> RepositoryWriteClassificationReport:
    _require_exact_keys(
        value,
        {"schema", "source_revision", "inventory_digest", "classifications"},
        "classification input",
    )
    if value["schema"] != "daedalus-gate0-repository-write-classification-input/1":
        raise RepositoryWriteClassificationError(
            "classification input schema is unsupported"
        )
    if value["source_revision"] != inventory.source_revision:
        raise RepositoryWriteClassificationError(
            "classification input source revision is stale"
        )
    if value["inventory_digest"] != inventory.digest:
        raise RepositoryWriteClassificationError(
            "classification input inventory digest is stale"
        )
    rows = tuple(
        SurfaceClassification.from_dict(
            _strict_mapping(item, "surface classification")
        )
        for item in _strict_list(value["classifications"], "classifications")
    )
    return project_repository_write_classifications(inventory, rows)


def _surface_from_dict(value: Mapping[str, object]) -> RepositoryWriteSurface:
    _require_exact_keys(
        value,
        {
            "path",
            "line",
            "column",
            "origin",
            "kind",
            "callee",
            "operation",
            "blocking",
        },
        "repository write surface",
    )
    try:
        return RepositoryWriteSurface(
            path=_strict_str(value["path"], "surface path"),
            line=_strict_int(value["line"], "surface line"),
            column=_strict_int(value["column"], "surface column"),
            origin=_strict_str(value["origin"], "surface origin"),
            kind=_strict_str(value["kind"], "surface kind"),
            callee=_strict_str(value["callee"], "surface callee"),
            operation=_strict_str(value["operation"], "surface operation"),
            blocking=_strict_bool(value["blocking"], "surface blocking"),
        )
    except ValueError as exc:
        raise RepositoryWriteClassificationError(
            "repository write surface is invalid"
        ) from exc


def _require_exact_keys(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    if not isinstance(value, Mapping) or set(value) != required:
        raise RepositoryWriteClassificationError(f"{label} keys are invalid")


def _strict_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RepositoryWriteClassificationError(f"{label} must be an object")
    return value


def _strict_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RepositoryWriteClassificationError(f"{label} must be an array")
    return value


def _strict_str(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RepositoryWriteClassificationError(f"{label} must be a string")
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise RepositoryWriteClassificationError(f"{label} must be an integer")
    return value


def _strict_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise RepositoryWriteClassificationError(f"{label} must be a boolean")
    return value

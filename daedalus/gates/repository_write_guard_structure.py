# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Structural replay for repository-write guard-contract evidence.

This verifier joins four independently checkable subjects on one exact source
revision:

* the revision-bound repository-write classification and CAS evidence bytes;
* the authenticated evidence-origin and source-anchor semantic chain;
* the authenticated guard-implementation manifest; and
* the exact repository source tree plus conservative Python AST structure.

The result proves that every production-reachable classified surface names
exactly one guard-evidence object per declared contract, that the evidence
matches the authenticated manifest, and that the named implementation target
exists uniquely in the exact source bytes named by its digest.  It does not
execute the target, infer behavior, prove that a guard ran, or authenticate the
remaining Effect-Lease, runtime, checkout-disjointness, or retirement receipts.
It therefore cannot authenticate the complete evidence set, bind a GateReport,
or close Gate 0.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from daedalus.gates.guard_implementation_manifest import (
    GuardImplementationManifest,
    GuardImplementationManifestReport,
    GuardImplementationRecord,
    verify_guard_implementation_manifest,
)
from daedalus.gates.python_target_structure import (
    PythonTargetStructure,
    resolve_python_target_structure,
)
from daedalus.gates.repository_write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationReport,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_evidence_materialization import (
    MaterializedEvidenceRecord,
    RepositoryWriteEvidenceMaterializationReport,
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository_write_evidence_origin import (
    RepositoryWriteEvidenceOriginAttestation,
)
from daedalus.gates.repository_write_source_anchor_semantics import (
    RepositoryWriteSourceAnchorSemanticsReport,
    verify_repository_write_source_anchor_semantics,
)
from daedalus.spine.envelope import canonical_json


_REPORT_SCHEMA = "daedalus-gate0-repository-write-guard-structure/1"
_EVIDENCE_SCHEMA = "daedalus-gate0-repository-write-evidence-object/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_CAS_LOCATOR = re.compile(r"^cas:sha256:[0-9a-f]{64}$")


class RepositoryWriteGuardStructureError(RuntimeError):
    """Guard structural replay was malformed, stale, incomplete, or ambiguous."""


class RepositoryWriteGuardStructureBindingError(
    RepositoryWriteGuardStructureError
):
    """Authenticated subjects do not bind one exact structural projection."""


class RepositoryWriteGuardStructurePayloadError(
    RepositoryWriteGuardStructureError
):
    """A materialized guard evidence payload cannot be replayed exactly."""


def _strict_revision(value: object, label: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise RepositoryWriteGuardStructureError(
            f"{label} must be lowercase 40-hex"
        )
    return value


def _strict_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RepositoryWriteGuardStructureError(
            f"{label} must be lowercase sha256"
        )
    return value


def _strict_contract(value: object, label: str) -> str:
    if not isinstance(value, str) or _CONTRACT.fullmatch(value) is None:
        raise RepositoryWriteGuardStructureError(
            f"{label} must be a canonical contract name"
        )
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise RepositoryWriteGuardStructureError(
            f"{label} must be a strict integer"
        )
    return value


def _snapshot_blobs(blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(blobs, Mapping):
        raise RepositoryWriteGuardStructureError(
            "blobs must be a mapping"
        )
    try:
        snapshot = dict(blobs.items())
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteGuardStructureError(
            "blobs could not be snapshotted"
        ) from exc
    if any(not isinstance(locator, str) for locator in snapshot):
        raise RepositoryWriteGuardStructureError(
            "blob locator keys must be strings"
        )
    if any(type(raw) is not bytes for raw in snapshot.values()):
        raise RepositoryWriteGuardStructureError(
            "blob values must be exact bytes"
        )
    return snapshot


def _guard_payload(
    binding: EvidenceBinding,
    record: MaterializedEvidenceRecord,
    raw: bytes,
) -> tuple[str, str, str]:
    if binding.kind is not EvidenceKind.GUARD_CONTRACT:
        raise RepositoryWriteGuardStructurePayloadError(
            "guard payload requires a guard-contract binding"
        )
    if record.kind is not EvidenceKind.GUARD_CONTRACT:
        raise RepositoryWriteGuardStructureBindingError(
            "guard materialization kind differs from its binding"
        )
    if type(raw) is not bytes:
        raise RepositoryWriteGuardStructurePayloadError(
            "guard evidence must be exact bytes"
        )
    if hashlib.sha256(raw).hexdigest() != record.blob_sha256:
        raise RepositoryWriteGuardStructureBindingError(
            "guard evidence bytes changed after materialization"
        )
    try:
        document = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RepositoryWriteGuardStructurePayloadError(
            "guard evidence cannot be replayed as JSON"
        ) from exc
    if not isinstance(document, dict):
        raise RepositoryWriteGuardStructurePayloadError(
            "guard evidence envelope must be an object"
        )
    expected_keys = {
        "schema",
        "kind",
        "source_revision",
        "surface_sha256",
        "guard_contract",
        "subject_sha256",
        "payload_sha256",
        "payload",
    }
    if set(document) != expected_keys:
        raise RepositoryWriteGuardStructurePayloadError(
            "guard evidence envelope keys differ from the exact schema"
        )
    exact_envelope = {
        "schema": _EVIDENCE_SCHEMA,
        "kind": EvidenceKind.GUARD_CONTRACT.value,
        "source_revision": binding.source_revision,
        "surface_sha256": binding.surface_sha256,
        "guard_contract": binding.guard_contract,
        "subject_sha256": evidence_subject_sha256(binding),
    }
    for field, expected in exact_envelope.items():
        if document[field] != expected:
            raise RepositoryWriteGuardStructureBindingError(
                f"guard evidence {field} differs from its binding"
            )
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise RepositoryWriteGuardStructurePayloadError(
            "guard evidence payload must be an object"
        )
    if set(payload) != {
        "contract",
        "implementation_target",
        "implementation_sha256",
    }:
        raise RepositoryWriteGuardStructurePayloadError(
            "guard evidence payload keys differ from the exact schema"
        )
    payload_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    if document["payload_sha256"] != payload_sha256:
        raise RepositoryWriteGuardStructureBindingError(
            "guard evidence payload digest is invalid"
        )
    if record.payload_sha256 != payload_sha256:
        raise RepositoryWriteGuardStructureBindingError(
            "guard evidence payload differs from materialization"
        )
    contract = _strict_contract(payload["contract"], "guard payload contract")
    target = payload["implementation_target"]
    if not isinstance(target, str):
        raise RepositoryWriteGuardStructurePayloadError(
            "guard implementation target must be text"
        )
    implementation_sha256 = _strict_sha(
        payload["implementation_sha256"],
        "guard implementation_sha256",
    )
    if contract != binding.guard_contract:
        raise RepositoryWriteGuardStructureBindingError(
            "guard payload contract differs from its binding"
        )
    return contract, target, implementation_sha256


@dataclass(frozen=True)
class GuardStructureRecord:
    surface_sha256: str
    locator: str
    contract: str
    implementation_target: str
    implementation_sha256: str
    source_path: str
    source_size: int
    definition_kind: str
    line: int
    column: int
    end_line: int
    end_column: int
    structure_sha256: str

    def __post_init__(self) -> None:
        _strict_sha(self.surface_sha256, "surface_sha256")
        if (
            not isinstance(self.locator, str)
            or _CAS_LOCATOR.fullmatch(self.locator) is None
        ):
            raise ValueError("locator must be content-addressed")
        _strict_contract(self.contract, "contract")
        if not isinstance(self.implementation_target, str):
            raise ValueError("implementation_target must be text")
        _strict_sha(self.implementation_sha256, "implementation_sha256")
        if not isinstance(self.source_path, str) or not self.source_path:
            raise ValueError("source_path must be non-empty text")
        if _strict_int(self.source_size, "source_size") < 0:
            raise ValueError("source_size must be non-negative")
        if self.definition_kind not in {
            "class",
            "function",
            "async_function",
        }:
            raise ValueError("definition_kind is unsupported")
        for field_name in ("line", "end_line"):
            if _strict_int(getattr(self, field_name), field_name) < 1:
                raise ValueError(f"{field_name} must be positive")
        for field_name in ("column", "end_column"):
            if _strict_int(getattr(self, field_name), field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.end_line < self.line:
            raise ValueError("definition end precedes its start")
        _strict_sha(self.structure_sha256, "structure_sha256")
        expected_structure = hashlib.sha256(
            canonical_json(self._structure_payload()).encode("ascii")
        ).hexdigest()
        if self.structure_sha256 != expected_structure:
            raise ValueError("structure_sha256 does not bind the record")

    def _structure_payload(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "implementation_target": self.implementation_target,
            "implementation_sha256": self.implementation_sha256,
            "source_path": self.source_path,
            "source_size": self.source_size,
            "definition_kind": self.definition_kind,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    def sort_key(self) -> tuple[str, str, str]:
        return (self.contract, self.surface_sha256, self.locator)

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_sha256": self.surface_sha256,
            "locator": self.locator,
            **self._structure_payload(),
            "structure_sha256": self.structure_sha256,
        }

    @classmethod
    def from_structure(
        cls,
        *,
        surface_sha256: str,
        locator: str,
        contract: str,
        structure: PythonTargetStructure,
    ) -> "GuardStructureRecord":
        if not isinstance(structure, PythonTargetStructure):
            raise RepositoryWriteGuardStructureError(
                "target structure type is invalid"
            )
        payload = {
            "contract": contract,
            "implementation_target": structure.target,
            "implementation_sha256": structure.source_sha256,
            "source_path": structure.source_path,
            "source_size": structure.source_size,
            "definition_kind": structure.definition_kind,
            "line": structure.line,
            "column": structure.column,
            "end_line": structure.end_line,
            "end_column": structure.end_column,
        }
        structure_sha256 = hashlib.sha256(
            canonical_json(payload).encode("ascii")
        ).hexdigest()
        return cls(
            surface_sha256=surface_sha256,
            locator=locator,
            structure_sha256=structure_sha256,
            **payload,
        )


@dataclass(frozen=True)
class RepositoryWriteGuardStructureReport:
    source_revision: str
    classification_digest: str
    materialization_digest: str
    source_anchor_report_digest: str
    origin_attestation_digest: str
    guard_manifest_report_digest: str
    guard_manifest_digest: str
    classification_count: int
    production_classification_count: int
    guard_contract_count: int
    guard_binding_count: int
    record_set_sha256: str
    records: tuple[GuardStructureRecord, ...]

    def __post_init__(self) -> None:
        _strict_revision(self.source_revision, "source_revision")
        for field_name in (
            "classification_digest",
            "materialization_digest",
            "source_anchor_report_digest",
            "origin_attestation_digest",
            "guard_manifest_report_digest",
            "guard_manifest_digest",
            "record_set_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        for field_name in (
            "classification_count",
            "production_classification_count",
            "guard_contract_count",
            "guard_binding_count",
        ):
            if _strict_int(getattr(self, field_name), field_name) < 1:
                raise ValueError(f"{field_name} must be positive")
        if self.production_classification_count > self.classification_count:
            raise ValueError(
                "production classification count exceeds classification count"
            )
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, GuardStructureRecord)
            for record in self.records
        ):
            raise ValueError("records must be an immutable typed tuple")
        if tuple(sorted(self.records, key=GuardStructureRecord.sort_key)) != self.records:
            raise ValueError("records must be canonically sorted")
        if len(set(self.records)) != len(self.records):
            raise ValueError("records must be unique")
        if len(self.records) != self.guard_binding_count:
            raise ValueError("guard_binding_count differs from records")
        if len({record.contract for record in self.records}) != self.guard_contract_count:
            raise ValueError("guard_contract_count differs from records")
        expected_set = hashlib.sha256(
            canonical_json([record.to_dict() for record in self.records]).encode(
                "ascii"
            )
        ).hexdigest()
        if self.record_set_sha256 != expected_set:
            raise ValueError("record_set_sha256 does not bind records")

    def _payload(self) -> dict[str, object]:
        return {
            "schema": _REPORT_SCHEMA,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "materialization_digest": self.materialization_digest,
            "source_anchor_report_digest": self.source_anchor_report_digest,
            "origin_attestation_digest": self.origin_attestation_digest,
            "guard_manifest_report_digest": self.guard_manifest_report_digest,
            "guard_manifest_digest": self.guard_manifest_digest,
            "classification_count": self.classification_count,
            "production_classification_count": self.production_classification_count,
            "guard_contract_count": self.guard_contract_count,
            "guard_binding_count": self.guard_binding_count,
            "record_set_sha256": self.record_set_sha256,
            "records": [record.to_dict() for record in self.records],
            "origin_authenticated": True,
            "source_anchor_semantics_verified": True,
            "guard_manifest_authenticated": True,
            "guard_contract_structure_verified": True,
            "guard_contract_semantics_verified": False,
            "semantic_receipts_verified": False,
            "evidence_authenticated": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-guard-structure",
            "blockers": [
                "effect-lease-semantic-verification-missing",
                "gate-report-binding-missing",
                "guard-contract-behavioral-verification-missing",
                "primary-checkout-disjointness-semantic-verification-missing",
                "retirement-semantic-verification-missing",
                "runtime-conformance-semantic-verification-missing",
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def verify_repository_write_guard_structure(
    classification: RepositoryWriteClassificationReport,
    blobs: Mapping[str, bytes],
    origin_attestation: RepositoryWriteEvidenceOriginAttestation,
    guard_manifest: GuardImplementationManifest,
    *,
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    guard_keyring: Mapping[tuple[str, str], bytes | str],
    expected_guard_authority_id: str,
    current_revision: str,
    now: datetime,
    repository_root: Path,
) -> RepositoryWriteGuardStructureReport:
    """Re-authenticate and structurally replay every declared production guard."""

    if not isinstance(classification, RepositoryWriteClassificationReport):
        raise RepositoryWriteGuardStructureError(
            "classification report type is invalid"
        )
    revision = _strict_revision(current_revision, "current_revision")
    if classification.source_revision != revision:
        raise RepositoryWriteGuardStructureBindingError(
            "classification source revision is stale"
        )
    snapshot = _snapshot_blobs(blobs)
    source_anchor_report = verify_repository_write_source_anchor_semantics(
        classification,
        snapshot,
        origin_attestation,
        keyring=collector_keyring,
        expected_collector_id=expected_collector_id,
        current_revision=revision,
        now=now,
        repository_root=repository_root,
    )
    materialization = materialize_repository_write_evidence(
        classification,
        snapshot,
    )
    guard_manifest_report = verify_guard_implementation_manifest(
        guard_manifest,
        keyring=guard_keyring,
        expected_authority_id=expected_guard_authority_id,
        current_revision=revision,
        expected_classification_digest=classification.digest,
        now=now,
    )
    _verify_chain(
        classification,
        materialization,
        source_anchor_report,
        origin_attestation,
        guard_manifest_report,
        guard_manifest,
    )

    production_rows = tuple(
        row for row in classification.classifications if row.production_reachable
    )
    if not production_rows:
        raise RepositoryWriteGuardStructureBindingError(
            "guard structural replay requires production-reachable classifications"
        )
    allowed_guards = {
        GuardDisposition.CENTRAL,
        GuardDisposition.LOCAL_GUARDS,
    }
    invalid_rows = tuple(
        row
        for row in production_rows
        if row.guard not in allowed_guards or not row.guard_contracts
    )
    if invalid_rows:
        raise RepositoryWriteGuardStructureBindingError(
            "production classification lacks declared guarded structure"
        )
    for row in classification.classifications:
        if not row.production_reachable and any(
            binding.kind is EvidenceKind.GUARD_CONTRACT
            for binding in row.evidence
        ):
            raise RepositoryWriteGuardStructureBindingError(
                "retired classification retains guard-contract evidence"
            )

    required_contracts = {
        contract
        for row in production_rows
        for contract in row.guard_contracts
    }
    if not required_contracts:
        raise RepositoryWriteGuardStructureBindingError(
            "guard structural replay cannot be vacuous"
        )
    manifest_by_contract = {
        entry.contract: entry for entry in guard_manifest.entries
    }
    if set(manifest_by_contract) != required_contracts:
        raise RepositoryWriteGuardStructureBindingError(
            "guard manifest contract set differs from production classification"
        )
    materialized_by_locator = {
        record.locator: record for record in materialization.records
    }
    structure_by_contract: dict[str, PythonTargetStructure] = {}
    records: list[GuardStructureRecord] = []
    for row in production_rows:
        bindings_by_contract: dict[str, list[EvidenceBinding]] = {
            contract: [] for contract in row.guard_contracts
        }
        for binding in row.evidence:
            if binding.kind is EvidenceKind.GUARD_CONTRACT:
                bindings_by_contract.setdefault(binding.guard_contract, []).append(
                    binding
                )
        if set(bindings_by_contract) != set(row.guard_contracts) or any(
            len(bindings) != 1 for bindings in bindings_by_contract.values()
        ):
            raise RepositoryWriteGuardStructureBindingError(
                "every declared production guard requires exactly one evidence binding"
            )
        expected_surface_sha256 = surface_binding_sha256(revision, row.surface)
        for contract in row.guard_contracts:
            binding = bindings_by_contract[contract][0]
            if binding.surface_sha256 != expected_surface_sha256:
                raise RepositoryWriteGuardStructureBindingError(
                    "guard evidence surface binding is stale"
                )
            record = materialized_by_locator.get(binding.locator)
            if record is None:
                raise RepositoryWriteGuardStructureBindingError(
                    "guard materialization record is missing"
                )
            raw = snapshot.get(binding.locator)
            if raw is None:
                raise RepositoryWriteGuardStructureBindingError(
                    "guard evidence blob is missing after materialization"
                )
            payload_contract, target, implementation_sha256 = _guard_payload(
                binding,
                record,
                raw,
            )
            if payload_contract != contract:
                raise RepositoryWriteGuardStructureBindingError(
                    "guard evidence contract differs from the classification"
                )
            manifest_entry = manifest_by_contract[contract]
            _verify_manifest_entry(
                manifest_entry,
                target=target,
                implementation_sha256=implementation_sha256,
            )
            structure = structure_by_contract.get(contract)
            if structure is None:
                structure = resolve_python_target_structure(
                    repository_root,
                    target,
                    expected_source_sha256=implementation_sha256,
                )
                structure_by_contract[contract] = structure
            elif (
                structure.target != target
                or structure.source_sha256 != implementation_sha256
            ):
                raise RepositoryWriteGuardStructureBindingError(
                    "guard contract resolves to inconsistent implementations"
                )
            records.append(
                GuardStructureRecord.from_structure(
                    surface_sha256=binding.surface_sha256,
                    locator=binding.locator,
                    contract=contract,
                    structure=structure,
                )
            )
    canonical_records = tuple(
        sorted(records, key=GuardStructureRecord.sort_key)
    )
    record_set_sha256 = hashlib.sha256(
        canonical_json([record.to_dict() for record in canonical_records]).encode(
            "ascii"
        )
    ).hexdigest()
    return RepositoryWriteGuardStructureReport(
        source_revision=revision,
        classification_digest=classification.digest,
        materialization_digest=materialization.digest,
        source_anchor_report_digest=source_anchor_report.digest,
        origin_attestation_digest=origin_attestation.digest,
        guard_manifest_report_digest=guard_manifest_report.digest,
        guard_manifest_digest=guard_manifest.digest,
        classification_count=len(classification.classifications),
        production_classification_count=len(production_rows),
        guard_contract_count=len(required_contracts),
        guard_binding_count=len(canonical_records),
        record_set_sha256=record_set_sha256,
        records=canonical_records,
    )


def _verify_manifest_entry(
    entry: GuardImplementationRecord,
    *,
    target: str,
    implementation_sha256: str,
) -> None:
    if not isinstance(entry, GuardImplementationRecord):
        raise RepositoryWriteGuardStructureError(
            "guard manifest entry type is invalid"
        )
    if entry.implementation_target != target:
        raise RepositoryWriteGuardStructureBindingError(
            "guard evidence target differs from the authenticated manifest"
        )
    if entry.implementation_sha256 != implementation_sha256:
        raise RepositoryWriteGuardStructureBindingError(
            "guard evidence source digest differs from the authenticated manifest"
        )


def _verify_chain(
    classification: RepositoryWriteClassificationReport,
    materialization: RepositoryWriteEvidenceMaterializationReport,
    source_anchor_report: RepositoryWriteSourceAnchorSemanticsReport,
    origin_attestation: RepositoryWriteEvidenceOriginAttestation,
    guard_manifest_report: GuardImplementationManifestReport,
    guard_manifest: GuardImplementationManifest,
) -> None:
    comparisons = {
        "materialization_revision": (
            materialization.source_revision,
            classification.source_revision,
        ),
        "materialization_classification": (
            materialization.classification_digest,
            classification.digest,
        ),
        "source_anchor_revision": (
            source_anchor_report.source_revision,
            classification.source_revision,
        ),
        "source_anchor_classification": (
            source_anchor_report.classification_digest,
            classification.digest,
        ),
        "source_anchor_materialization": (
            source_anchor_report.materialization_digest,
            materialization.digest,
        ),
        "source_anchor_attestation": (
            source_anchor_report.attestation_digest,
            origin_attestation.digest,
        ),
        "guard_manifest_revision": (
            guard_manifest_report.source_revision,
            classification.source_revision,
        ),
        "guard_manifest_classification": (
            guard_manifest_report.classification_digest,
            classification.digest,
        ),
        "guard_manifest_digest": (
            guard_manifest_report.manifest_digest,
            guard_manifest.digest,
        ),
        "guard_manifest_entry_set": (
            guard_manifest_report.entry_set_sha256,
            guard_manifest.entry_set_sha256,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise RepositoryWriteGuardStructureBindingError(
            "repository-write guard structural chain mismatch: "
            + ", ".join(mismatches)
        )


__all__ = [
    "GuardStructureRecord",
    "RepositoryWriteGuardStructureBindingError",
    "RepositoryWriteGuardStructureError",
    "RepositoryWriteGuardStructurePayloadError",
    "RepositoryWriteGuardStructureReport",
    "verify_repository_write_guard_structure",
]

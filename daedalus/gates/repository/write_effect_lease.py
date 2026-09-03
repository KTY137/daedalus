"""Read-only semantic replay of repository-write Effect-Lease evidence.

The verifier composes the authenticated repository-write runtime-conformance
chain with the persisted Effect-Lease replay projections.  It never grants,
starts, finishes, revokes, retries, promotes, or re-executes an effect.  Missing
and STARTED executions are explicit fail-closed reconciliation states.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from daedalus.gates.guard_implementation_manifest import GuardImplementationManifest
from daedalus.gates.repository.write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationReport,
    surface_binding_sha256,
)
from daedalus.gates.repository.write_evidence_materialization import (
    MaterializedEvidenceRecord,
    RepositoryWriteEvidenceMaterializationReport,
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository.write_evidence_origin import (
    RepositoryWriteEvidenceOriginAttestation,
)
from daedalus.gates.repository.write_runtime_conformance import (
    RepositoryWriteRuntimeConformanceReport,
    RuntimeConformanceReplayRecord,
    RuntimeConformanceSubject,
    verify_repository_write_runtime_conformance,
)
from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.effect_replay import (
    EffectExecutionReplaySnapshot,
    EffectReplayProjectionError,
    inspect_effect_execution,
)
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.runtime_effect_replay import (
    RuntimeEffectExecutionReplaySnapshot,
    RuntimeEffectReplayProjectionError,
    inspect_runtime_effect_execution,
)
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.trust_store import RuntimeTrustLedger
from daedalus.spine.envelope import canonical_json


# Revision 2: a replay record's ``runtime_conformance_receipt_sha256`` is
# ``null`` exactly when the runtime-conformance report excused that surface
# with a verified NonRuntimeConformityBinding.  /1 promised a sha256 there
# unconditionally, so the id moves with the shape.
_REPORT_SCHEMA = "daedalus-gate0-repository-write-effect-lease/2"
_EVIDENCE_SCHEMA = "daedalus-gate0-repository-write-evidence-object/1"
_EFFECT_RECEIPT_SCHEMA = "daedalus-effect-lease-receipt/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CAS = re.compile(r"^cas:sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_WRITE_EFFECTS = frozenset({"filesystem_write", "repository_mutation"})


class RepositoryWriteEffectLeaseError(RuntimeError):
    """Effect-Lease replay material is malformed, stale, or incomplete."""


class RepositoryWriteEffectLeaseBindingError(RepositoryWriteEffectLeaseError):
    """Repository-write evidence and persisted effect subjects disagree."""


class RepositoryWriteEffectLeasePayloadError(RepositoryWriteEffectLeaseError):
    """A retained Effect-Lease evidence object cannot be replayed exactly."""


def _revision(value: object, label: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise RepositoryWriteEffectLeaseError(f"{label} must be lowercase 40-hex")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RepositoryWriteEffectLeaseError(f"{label} must be lowercase sha256")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise RepositoryWriteEffectLeaseError(
            f"{label} must be a canonical identifier"
        )
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise RepositoryWriteEffectLeaseError(f"{label} must be a strict integer")
    return value


def _snapshot_bytes(blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(blobs, Mapping):
        raise RepositoryWriteEffectLeaseError("blobs must be a mapping")
    try:
        result = dict(blobs.items())
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteEffectLeaseError("blobs could not be snapshotted") from exc
    if any(not isinstance(key, str) for key in result):
        raise RepositoryWriteEffectLeaseError("blob locator keys must be strings")
    if any(type(value) is not bytes for value in result.values()):
        raise RepositoryWriteEffectLeaseError("blob values must be exact bytes")
    return result


@dataclass(frozen=True)
class EffectLeaseReplaySubject:
    """One exact authorization and execution request for a retained receipt."""

    authorization: NonRuntimeEffectAuthorization | RuntimeBoundEffectAuthorization
    execution: EffectExecutionRequest

    def __post_init__(self) -> None:
        if type(self.authorization) not in {
            NonRuntimeEffectAuthorization,
            RuntimeBoundEffectAuthorization,
        }:
            raise ValueError("effect replay subject authorization type is invalid")
        if type(self.execution) is not EffectExecutionRequest:
            raise ValueError("effect replay subject execution type is invalid")
        if not set(self.execution.requested_effects).intersection(_WRITE_EFFECTS):
            raise ValueError("repository-write subject lacks a write-capable effect")
        if self.execution.kill_switch_generation != self.lease.kill_switch_generation:
            raise ValueError(
                "execution kill-switch generation differs from the retained lease"
            )
        _revision(self.source_revision, "effect subject source_revision")
        _identifier(self.entrypoint_id, "effect subject entrypoint_id")

    @property
    def lease(self):
        if type(self.authorization) is NonRuntimeEffectAuthorization:
            return self.authorization.lease
        return self.authorization.capability.lease

    @property
    def source_revision(self) -> str:
        if type(self.authorization) is RuntimeBoundEffectAuthorization:
            return self.authorization.capability.source_revision
        return self.authorization.lease.provenance.source_revision

    @property
    def entrypoint_id(self) -> str:
        return self.lease.entrypoint_id

    @property
    def runtime_bound(self) -> bool:
        return type(self.authorization) is RuntimeBoundEffectAuthorization

    @property
    def runtime_conformance_sha256(self) -> str | None:
        if type(self.authorization) is RuntimeBoundEffectAuthorization:
            return self.authorization.capability.runtime_conformance_sha256
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "authorization_kind": (
                "runtime_bound" if self.runtime_bound else "non_runtime"
            ),
            "lease_sha256": self.lease.digest,
            "entrypoint_id": self.entrypoint_id,
            "execution_id": self.execution.execution_id,
            "execution_request_sha256": self.execution.digest,
            "source_revision": self.source_revision,
            "runtime_conformance_sha256": self.runtime_conformance_sha256,
        }


def _snapshot_subjects(
    subjects: Mapping[str, EffectLeaseReplaySubject],
) -> dict[str, EffectLeaseReplaySubject]:
    if not isinstance(subjects, Mapping):
        raise RepositoryWriteEffectLeaseError("effect_subjects must be a mapping")
    try:
        result = dict(subjects.items())
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteEffectLeaseError(
            "effect_subjects could not be snapshotted"
        ) from exc
    for digest, subject in result.items():
        _sha(digest, "effect subject key")
        if type(subject) is not EffectLeaseReplaySubject:
            raise RepositoryWriteEffectLeaseError(
                "effect subject values must be exact typed subjects"
            )
    return result


@dataclass(frozen=True)
class EffectLeaseReplayRecord:
    surface_sha256: str
    locator: str
    entrypoint_id: str
    execution_id: str
    execution_request_sha256: str
    lease_sha256: str
    start_receipt_sha256: str
    terminal_receipt_sha256: str
    terminal_state: str
    runtime_bound: bool
    runtime_id: str | None
    runtime_trust_record_sha256: str | None
    # ``None`` exactly when this surface was excused by a verified
    # NonRuntimeConformityBinding: there is no conformance receipt to name, and
    # inventing a digest for one would be the fabrication the /2 relaxation
    # exists to avoid.
    runtime_conformance_receipt_sha256: str | None
    replay_sha256: str

    def __post_init__(self) -> None:
        _sha(self.surface_sha256, "surface_sha256")
        if not isinstance(self.locator, str) or _CAS.fullmatch(self.locator) is None:
            raise ValueError("locator must be content-addressed")
        _identifier(self.entrypoint_id, "entrypoint_id")
        _identifier(self.execution_id, "execution_id")
        for name in (
            "execution_request_sha256",
            "lease_sha256",
            "start_receipt_sha256",
            "terminal_receipt_sha256",
            "replay_sha256",
        ):
            _sha(getattr(self, name), name)
        if self.runtime_conformance_receipt_sha256 is not None:
            _sha(
                self.runtime_conformance_receipt_sha256,
                "runtime_conformance_receipt_sha256",
            )
        elif self.runtime_bound:
            # A runtime-bound record has a conformance receipt by construction;
            # only the excused non-runtime case may omit it.
            raise ValueError(
                "runtime-bound record requires a runtime conformance receipt"
            )
        if self.terminal_state not in _TERMINAL_STATES:
            raise ValueError("terminal_state is invalid")
        if type(self.runtime_bound) is not bool:
            raise ValueError("runtime_bound must be a strict boolean")
        if self.runtime_bound:
            _identifier(self.runtime_id, "runtime_id")
            _sha(self.runtime_trust_record_sha256, "runtime_trust_record_sha256")
        elif self.runtime_id is not None or self.runtime_trust_record_sha256 is not None:
            raise ValueError("non-runtime record cannot retain runtime authority")
        expected = hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()
        if self.replay_sha256 != expected:
            raise ValueError("replay_sha256 does not bind the record")

    def _payload(self) -> dict[str, object]:
        return {
            "surface_sha256": self.surface_sha256,
            "locator": self.locator,
            "entrypoint_id": self.entrypoint_id,
            "execution_id": self.execution_id,
            "execution_request_sha256": self.execution_request_sha256,
            "lease_sha256": self.lease_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "terminal_state": self.terminal_state,
            "runtime_bound": self.runtime_bound,
            "runtime_id": self.runtime_id,
            "runtime_trust_record_sha256": self.runtime_trust_record_sha256,
            "runtime_conformance_receipt_sha256": (
                self.runtime_conformance_receipt_sha256
            ),
        }

    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.surface_sha256,
            self.entrypoint_id,
            self.execution_id,
            self.locator,
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "replay_sha256": self.replay_sha256}

    @classmethod
    def build(
        cls,
        *,
        surface_sha256: str,
        locator: str,
        subject: EffectLeaseReplaySubject,
        replay: EffectExecutionReplaySnapshot,
        runtime_id: str | None,
        runtime_trust_record_sha256: str | None,
        runtime_conformance_receipt_sha256: str | None,
    ) -> "EffectLeaseReplayRecord":
        terminal = replay.terminal_receipt
        if terminal is None:
            raise ValueError("effect replay record requires a terminal receipt")
        payload = {
            "surface_sha256": surface_sha256,
            "locator": locator,
            "entrypoint_id": subject.entrypoint_id,
            "execution_id": subject.execution.execution_id,
            "execution_request_sha256": subject.execution.digest,
            "lease_sha256": subject.lease.digest,
            "start_receipt_sha256": replay.start_receipt.receipt_sha256,
            "terminal_receipt_sha256": terminal.receipt_sha256,
            "terminal_state": replay.state.lower(),
            "runtime_bound": subject.runtime_bound,
            "runtime_id": runtime_id,
            "runtime_trust_record_sha256": runtime_trust_record_sha256,
            "runtime_conformance_receipt_sha256": (
                runtime_conformance_receipt_sha256
            ),
        }
        digest = hashlib.sha256(
            canonical_json(payload).encode("ascii")
        ).hexdigest()
        return cls(**payload, replay_sha256=digest)


@dataclass(frozen=True)
class RepositoryWriteEffectLeaseReport:
    source_revision: str
    classification_digest: str
    materialization_digest: str
    runtime_conformance_report_digest: str
    origin_attestation_digest: str
    production_classification_count: int
    effect_subject_count: int
    effect_binding_count: int
    effect_set_sha256: str
    records: tuple[EffectLeaseReplayRecord, ...]

    def __post_init__(self) -> None:
        _revision(self.source_revision, "source_revision")
        for name in (
            "classification_digest",
            "materialization_digest",
            "runtime_conformance_report_digest",
            "origin_attestation_digest",
            "effect_set_sha256",
        ):
            _sha(getattr(self, name), name)
        for name in (
            "production_classification_count",
            "effect_subject_count",
            "effect_binding_count",
        ):
            if _integer(getattr(self, name), name) < 1:
                raise ValueError(f"{name} must be positive")
        if not isinstance(self.records, tuple) or any(
            type(record) is not EffectLeaseReplayRecord for record in self.records
        ):
            raise ValueError("records must be an immutable exact typed tuple")
        if tuple(sorted(self.records, key=EffectLeaseReplayRecord.sort_key)) != self.records:
            raise ValueError("records must be canonically sorted")
        if len(set(self.records)) != len(self.records):
            raise ValueError("records must be unique")
        if len(self.records) != self.effect_binding_count:
            raise ValueError("effect_binding_count differs from records")
        if len({row.terminal_receipt_sha256 for row in self.records}) != self.effect_subject_count:
            raise ValueError("effect_subject_count differs from records")
        expected = hashlib.sha256(
            canonical_json([row.to_dict() for row in self.records]).encode("ascii")
        ).hexdigest()
        if self.effect_set_sha256 != expected:
            raise ValueError("effect_set_sha256 does not bind records")

    def _payload(self) -> dict[str, object]:
        return {
            "schema": _REPORT_SCHEMA,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "materialization_digest": self.materialization_digest,
            "runtime_conformance_report_digest": (
                self.runtime_conformance_report_digest
            ),
            "origin_attestation_digest": self.origin_attestation_digest,
            "production_classification_count": self.production_classification_count,
            "effect_subject_count": self.effect_subject_count,
            "effect_binding_count": self.effect_binding_count,
            "effect_set_sha256": self.effect_set_sha256,
            "records": [row.to_dict() for row in self.records],
            "origin_authenticated": True,
            "source_anchor_semantics_verified": True,
            "guard_contract_structure_verified": True,
            "runtime_conformance_semantics_verified": True,
            "effect_lease_semantics_verified": True,
            "guard_contract_semantics_verified": False,
            "primary_checkout_disjointness_verified": False,
            "retirement_semantics_verified": False,
            "semantic_receipts_verified": False,
            "evidence_authenticated": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-effect-lease",
            "blockers": [
                "gate-report-binding-missing",
                "guard-contract-behavioral-verification-missing",
                "primary-checkout-disjointness-semantic-verification-missing",
                "retirement-semantic-verification-missing",
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def verify_repository_write_effect_leases(
    classification: RepositoryWriteClassificationReport,
    blobs: Mapping[str, bytes],
    origin_attestation: RepositoryWriteEvidenceOriginAttestation,
    guard_manifest: GuardImplementationManifest,
    runtime_subjects: Mapping[str, RuntimeConformanceSubject],
    runtime_trust_ledgers: Mapping[str, RuntimeTrustLedger],
    effect_subjects: Mapping[str, EffectLeaseReplaySubject],
    *,
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    guard_keyring: Mapping[tuple[str, str], bytes | str],
    expected_guard_authority_id: str,
    current_revision: str,
    now: datetime,
    repository_root: Path,
) -> RepositoryWriteEffectLeaseReport:
    """Replay all production Effect-Lease receipts without effect authority."""

    if type(classification) is not RepositoryWriteClassificationReport:
        raise RepositoryWriteEffectLeaseError("classification report type is invalid")
    revision = _revision(current_revision, "current_revision")
    if classification.source_revision != revision:
        raise RepositoryWriteEffectLeaseBindingError(
            "classification source revision is stale"
        )
    blob_snapshot = _snapshot_bytes(blobs)
    subject_snapshot = _snapshot_subjects(effect_subjects)

    runtime_report = verify_repository_write_runtime_conformance(
        classification,
        blob_snapshot,
        origin_attestation,
        guard_manifest,
        runtime_subjects,
        runtime_trust_ledgers,
        collector_keyring=collector_keyring,
        expected_collector_id=expected_collector_id,
        guard_keyring=guard_keyring,
        expected_guard_authority_id=expected_guard_authority_id,
        current_revision=revision,
        now=now,
        repository_root=repository_root,
    )
    if type(runtime_report) is not RepositoryWriteRuntimeConformanceReport:
        raise RepositoryWriteEffectLeaseBindingError(
            "runtime predecessor returned an invalid report type"
        )
    materialization = materialize_repository_write_evidence(
        classification,
        blob_snapshot,
    )
    _verify_predecessor_chain(
        classification,
        materialization,
        runtime_report,
        origin_attestation,
    )

    production_rows = tuple(
        row for row in classification.classifications if row.production_reachable
    )
    if not production_rows:
        raise RepositoryWriteEffectLeaseBindingError(
            "effect replay requires production-reachable classifications"
        )
    if any(row.guard is not GuardDisposition.CENTRAL for row in production_rows):
        raise RepositoryWriteEffectLeaseBindingError(
            "every production classification must be centrally guarded"
        )
    for row in classification.classifications:
        retained = tuple(
            binding
            for binding in row.evidence
            if binding.kind is EvidenceKind.EFFECT_LEASE_RECEIPT
        )
        if row.production_reachable and len(retained) != 1:
            raise RepositoryWriteEffectLeaseBindingError(
                "every production classification requires exactly one Effect-Lease receipt"
            )
        if not row.production_reachable and retained:
            raise RepositoryWriteEffectLeaseBindingError(
                "non-production classification retains Effect-Lease evidence"
            )

    materialized = {row.locator: row for row in materialization.records}
    required_receipts: set[str] = set()
    payloads: dict[EvidenceBinding, tuple[str, str, str]] = {}
    for row in production_rows:
        binding = next(
            item
            for item in row.evidence
            if item.kind is EvidenceKind.EFFECT_LEASE_RECEIPT
        )
        record = materialized.get(binding.locator)
        raw = blob_snapshot.get(binding.locator)
        if record is None or raw is None:
            raise RepositoryWriteEffectLeaseBindingError(
                "Effect-Lease evidence is missing after materialization"
            )
        payload = _effect_payload(binding, record, raw)
        required_receipts.add(payload[0])
        payloads[binding] = payload
    if set(subject_snapshot) != required_receipts:
        raise RepositoryWriteEffectLeaseBindingError(
            "effect subject set differs from retained terminal receipt evidence"
        )

    runtime_by_surface = {row.surface_sha256: row for row in runtime_report.records}
    if len(runtime_by_surface) != len(runtime_report.records):
        raise RepositoryWriteEffectLeaseBindingError(
            "runtime predecessor contains duplicate surface records"
        )
    required_surfaces = {
        surface_binding_sha256(revision, row.surface) for row in production_rows
    }
    # Wire revision 2 of the runtime-conformance report.  A production surface
    # is covered either by a replayed runtime record or by an excused
    # non-runtime surface -- never by both, and never by neither.
    # The two sets are disjoint by the report's own contract
    # (``RepositoryWriteRuntimeConformanceReport.__post_init__`` refuses a
    # surface that is both replayed and excused), so re-checking it here would
    # be a guard nothing can make fire.  There is already one of those below --
    # ``elif runtime_id is not None`` on the non-runtime branch, which
    # ``_inspect_subject`` hard-codes to None and so can never observe -- and
    # this chain does not need a second.
    excused_surfaces = set(runtime_report.non_runtime_surfaces)
    if set(runtime_by_surface) | excused_surfaces != required_surfaces:
        raise RepositoryWriteEffectLeaseBindingError(
            "runtime predecessor surface set differs from production classifications"
        )
    declared_non_runtime = {
        surface_binding_sha256(revision, row.surface)
        for row in production_rows
        if row.non_runtime_conformity is not None
    }
    if declared_non_runtime != excused_surfaces:
        raise RepositoryWriteEffectLeaseBindingError(
            "runtime predecessor excuses a different surface set than the rows admit"
        )

    verified: dict[
        str,
        tuple[EffectLeaseReplaySubject, EffectExecutionReplaySnapshot, str | None, str | None],
    ] = {}
    for receipt_sha256 in sorted(required_receipts):
        subject = subject_snapshot[receipt_sha256]
        evidence_subjects = {
            (entrypoint_id, terminal_state)
            for digest, entrypoint_id, terminal_state in payloads.values()
            if digest == receipt_sha256
        }
        if len(evidence_subjects) != 1:
            raise RepositoryWriteEffectLeaseBindingError(
                "one Effect-Lease receipt has inconsistent evidence subjects"
            )
        entrypoint_id, terminal_state = next(iter(evidence_subjects))
        if subject.source_revision != revision:
            raise RepositoryWriteEffectLeaseBindingError(
                "effect subject source revision is stale"
            )
        if subject.entrypoint_id != entrypoint_id:
            raise RepositoryWriteEffectLeaseBindingError(
                "effect evidence entrypoint differs from its authorization"
            )
        replay, runtime_id, trust_sha = _inspect_subject(subject)
        terminal = replay.terminal_receipt
        if terminal is None or replay.pending_reconciliation:
            raise RepositoryWriteEffectLeaseBindingError(
                "Effect-Lease execution is not terminal; automatic re-execution is forbidden"
            )
        if terminal.receipt_sha256 != receipt_sha256:
            raise RepositoryWriteEffectLeaseBindingError(
                "retained terminal receipt differs from the evidence subject"
            )
        if replay.state.lower() != terminal_state:
            raise RepositoryWriteEffectLeaseBindingError(
                "retained terminal state differs from the evidence subject"
            )
        if terminal.execution_id != subject.execution.execution_id:
            raise RepositoryWriteEffectLeaseBindingError(
                "terminal execution identity differs from the typed request"
            )
        if terminal.lease_sha256 != subject.lease.digest:
            raise RepositoryWriteEffectLeaseBindingError(
                "terminal lease identity differs from the typed authorization"
            )
        verified[receipt_sha256] = (subject, replay, runtime_id, trust_sha)

    records: list[EffectLeaseReplayRecord] = []
    for binding, (receipt_sha256, _, _) in payloads.items():
        subject, replay, runtime_id, trust_sha = verified[receipt_sha256]
        runtime_record = runtime_by_surface.get(binding.surface_sha256)
        # Wire revision 2: an excused surface has no conformance record to
        # find, and demanding one would be the /1 rule again.  Runtime work
        # declared non-runtime is refused where it can actually be observed --
        # in ``replay_non_runtime_effect_subject``, which the classification row
        # calls before it will admit the binding at all.
        excused = binding.surface_sha256 in excused_surfaces
        if not excused and type(runtime_record) is not RuntimeConformanceReplayRecord:
            raise RepositoryWriteEffectLeaseBindingError(
                "runtime predecessor record is missing for effect surface"
            )
        if subject.runtime_bound:
            if (
                subject.runtime_conformance_sha256
                != runtime_record.conformance_receipt_sha256
            ):
                raise RepositoryWriteEffectLeaseBindingError(
                    "runtime-bound Effect Lease differs from surface conformance"
                )
            if runtime_id is None or trust_sha is None:
                raise RepositoryWriteEffectLeaseBindingError(
                    "runtime-bound replay omitted authenticated runtime trust"
                )
        elif runtime_id is not None or trust_sha is not None:
            raise RepositoryWriteEffectLeaseBindingError(
                "non-runtime replay unexpectedly retained runtime authority"
            )
        records.append(
            EffectLeaseReplayRecord.build(
                surface_sha256=binding.surface_sha256,
                locator=binding.locator,
                subject=subject,
                replay=replay,
                runtime_id=runtime_id,
                runtime_trust_record_sha256=trust_sha,
                runtime_conformance_receipt_sha256=(
                    None if excused else runtime_record.conformance_receipt_sha256
                ),
            )
        )
    canonical_records = tuple(sorted(records, key=EffectLeaseReplayRecord.sort_key))
    effect_set_sha256 = hashlib.sha256(
        canonical_json([row.to_dict() for row in canonical_records]).encode("ascii")
    ).hexdigest()
    return RepositoryWriteEffectLeaseReport(
        source_revision=revision,
        classification_digest=classification.digest,
        materialization_digest=materialization.digest,
        runtime_conformance_report_digest=runtime_report.digest,
        origin_attestation_digest=origin_attestation.digest,
        production_classification_count=len(production_rows),
        effect_subject_count=len(required_receipts),
        effect_binding_count=len(canonical_records),
        effect_set_sha256=effect_set_sha256,
        records=canonical_records,
    )


def replay_non_runtime_effect_subject(
    subject: object,
    *,
    expected_execution_id: str,
) -> EffectExecutionReplaySnapshot:
    """Replay one retained execution and refuse it unless it is non-runtime.

    This is the typed check the classification row calls before it will admit a
    ``NonRuntimeConformityBinding`` in place of a runtime-conformance receipt.
    It is deliberately not a field read: the snapshot comes back out of the
    effect ledger through ``_inspect_subject``, the same path
    ``verify_repository_write_effect_leases`` uses, and the terminal receipt
    must already be durable.  Runtime work wearing a non-runtime label is
    refused here rather than excused downstream.
    """

    if type(subject) is not EffectLeaseReplaySubject:
        raise RepositoryWriteEffectLeaseError(
            "non-runtime replay subject must be an exact typed subject"
        )
    if subject.runtime_bound:
        raise RepositoryWriteEffectLeaseBindingError(
            "surface declared non-runtime replays as a runtime-bound authorization"
        )
    _identifier(expected_execution_id, "expected_execution_id")
    replay, runtime_id, trust_sha = _inspect_subject(subject)
    if runtime_id is not None or trust_sha is not None:
        raise RepositoryWriteEffectLeaseBindingError(
            "non-runtime replay unexpectedly retained runtime authority"
        )
    if subject.execution.execution_id != expected_execution_id:
        raise RepositoryWriteEffectLeaseBindingError(
            "non-runtime replay names another execution than the binding"
        )
    # Deliberately spelled differently from the fences in
    # ``verify_repository_write_effect_leases`` below.  Each mutation anchor in
    # scripts/run_repository_write_effect_lease_mutations.py must resolve to
    # exactly one place in this file, and a copied line would silently give two
    # guards one anchor -- disabling one of them would then go unnoticed.
    receipt = replay.terminal_receipt
    if replay.pending_reconciliation or receipt is None:
        raise RepositoryWriteEffectLeaseBindingError(
            "non-runtime replay is not terminal; automatic re-execution is forbidden"
        )
    if receipt.execution_id != subject.execution.execution_id:
        raise RepositoryWriteEffectLeaseBindingError(
            "non-runtime terminal execution identity differs from the typed request"
        )
    if receipt.lease_sha256 != subject.lease.digest:
        raise RepositoryWriteEffectLeaseBindingError(
            "non-runtime terminal lease identity differs from the typed authorization"
        )
    return replay


def _inspect_subject(
    subject: EffectLeaseReplaySubject,
) -> tuple[EffectExecutionReplaySnapshot, str | None, str | None]:
    try:
        if type(subject.authorization) is NonRuntimeEffectAuthorization:
            replay = inspect_effect_execution(subject.authorization, subject.execution)
            runtime_id = None
            trust_sha = None
        elif type(subject.authorization) is RuntimeBoundEffectAuthorization:
            runtime_replay = inspect_runtime_effect_execution(
                subject.authorization,
                subject.execution,
            )
            if runtime_replay is None:
                replay = None
                runtime_id = None
                trust_sha = None
            else:
                if type(runtime_replay) is not RuntimeEffectExecutionReplaySnapshot:
                    raise RepositoryWriteEffectLeaseBindingError(
                        "runtime effect replay returned an invalid snapshot type"
                    )
                replay = runtime_replay.execution
                runtime_id = runtime_replay.runtime_trust_record.runtime_id
                trust_sha = runtime_replay.runtime_trust_record.record_sha256
        else:  # pragma: no cover - protected by EffectLeaseReplaySubject
            raise RepositoryWriteEffectLeaseError(
                "effect replay subject authorization type is unsupported"
            )
    except (EffectReplayProjectionError, RuntimeEffectReplayProjectionError) as exc:
        raise RepositoryWriteEffectLeaseBindingError(
            "persisted Effect-Lease replay failed"
        ) from exc
    if replay is None:
        raise RepositoryWriteEffectLeaseBindingError(
            "Effect-Lease execution has no durable start; automatic re-execution is forbidden"
        )
    if type(replay) is not EffectExecutionReplaySnapshot:
        raise RepositoryWriteEffectLeaseBindingError(
            "effect replay returned an invalid snapshot type"
        )
    return replay, runtime_id, trust_sha


def _effect_payload(
    binding: EvidenceBinding,
    record: MaterializedEvidenceRecord,
    raw: bytes,
) -> tuple[str, str, str]:
    if binding.kind is not EvidenceKind.EFFECT_LEASE_RECEIPT:
        raise RepositoryWriteEffectLeasePayloadError(
            "effect payload requires an Effect-Lease binding"
        )
    if record.kind is not EvidenceKind.EFFECT_LEASE_RECEIPT:
        raise RepositoryWriteEffectLeaseBindingError(
            "effect materialization kind differs from its binding"
        )
    if type(raw) is not bytes:
        raise RepositoryWriteEffectLeasePayloadError(
            "Effect-Lease evidence must be exact bytes"
        )
    if hashlib.sha256(raw).hexdigest() != record.blob_sha256:
        raise RepositoryWriteEffectLeaseBindingError(
            "Effect-Lease evidence bytes changed after materialization"
        )

    def pairs(values: Sequence[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise RepositoryWriteEffectLeasePayloadError(
                    "Effect-Lease evidence JSON contains duplicate keys"
                )
            result[key] = value
        return result

    def nonfinite(value: str) -> object:
        raise RepositoryWriteEffectLeasePayloadError(
            f"Effect-Lease evidence JSON contains non-finite number {value}"
        )

    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=nonfinite,
        )
        canonical = canonical_json(document).encode("ascii")
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RepositoryWriteEffectLeasePayloadError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise RepositoryWriteEffectLeasePayloadError(
            "Effect-Lease evidence cannot be replayed as strict JSON"
        ) from exc
    if raw != canonical or not isinstance(document, dict):
        raise RepositoryWriteEffectLeasePayloadError(
            "Effect-Lease evidence is not a canonical object"
        )
    if set(document) != {
        "schema",
        "kind",
        "source_revision",
        "surface_sha256",
        "guard_contract",
        "subject_sha256",
        "payload_sha256",
        "payload",
    }:
        raise RepositoryWriteEffectLeasePayloadError(
            "Effect-Lease evidence envelope keys differ from the exact schema"
        )
    expected = {
        "schema": _EVIDENCE_SCHEMA,
        "kind": EvidenceKind.EFFECT_LEASE_RECEIPT.value,
        "source_revision": binding.source_revision,
        "surface_sha256": binding.surface_sha256,
        "guard_contract": "",
        "subject_sha256": evidence_subject_sha256(binding),
    }
    for field, value in expected.items():
        if document[field] != value:
            raise RepositoryWriteEffectLeaseBindingError(
                f"Effect-Lease evidence {field} differs from its binding"
            )
    payload = document["payload"]
    if not isinstance(payload, dict) or set(payload) != {
        "receipt_schema",
        "receipt_sha256",
        "entrypoint_id",
        "terminal_state",
    }:
        raise RepositoryWriteEffectLeasePayloadError(
            "Effect-Lease evidence payload keys differ from the exact schema"
        )
    payload_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    if document["payload_sha256"] != payload_sha256:
        raise RepositoryWriteEffectLeaseBindingError(
            "Effect-Lease evidence payload digest is invalid"
        )
    if record.payload_sha256 != payload_sha256:
        raise RepositoryWriteEffectLeaseBindingError(
            "Effect-Lease evidence payload differs from materialization"
        )
    if payload["receipt_schema"] != _EFFECT_RECEIPT_SCHEMA:
        raise RepositoryWriteEffectLeaseBindingError(
            "Effect-Lease receipt schema is not canonical"
        )
    receipt_sha256 = _sha(payload["receipt_sha256"], "Effect-Lease receipt sha256")
    entrypoint_id = _identifier(payload["entrypoint_id"], "Effect-Lease entrypoint_id")
    terminal_state = payload["terminal_state"]
    if not isinstance(terminal_state, str) or terminal_state not in _TERMINAL_STATES:
        raise RepositoryWriteEffectLeaseBindingError(
            "Effect-Lease evidence is not terminal"
        )
    return receipt_sha256, entrypoint_id, terminal_state


def _verify_predecessor_chain(
    classification: RepositoryWriteClassificationReport,
    materialization: RepositoryWriteEvidenceMaterializationReport,
    runtime_report: RepositoryWriteRuntimeConformanceReport,
    origin_attestation: RepositoryWriteEvidenceOriginAttestation,
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
        "runtime_revision": (
            runtime_report.source_revision,
            classification.source_revision,
        ),
        "runtime_classification": (
            runtime_report.classification_digest,
            classification.digest,
        ),
        "runtime_materialization": (
            runtime_report.materialization_digest,
            materialization.digest,
        ),
        "runtime_origin": (
            runtime_report.origin_attestation_digest,
            origin_attestation.digest,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise RepositoryWriteEffectLeaseBindingError(
            "repository-write Effect-Lease predecessor chain mismatch: "
            + ", ".join(mismatches)
        )


__all__ = [
    "EffectLeaseReplayRecord",
    "EffectLeaseReplaySubject",
    "RepositoryWriteEffectLeaseBindingError",
    "RepositoryWriteEffectLeaseError",
    "RepositoryWriteEffectLeasePayloadError",
    "RepositoryWriteEffectLeaseReport",
    "verify_repository_write_effect_leases",
]

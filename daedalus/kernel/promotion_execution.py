"""Persisted execution accounting for the sealed promotion boundary.

The canonical :class:`daedalus.schemas.PromotionReceipt` remains the owner-
decision receipt. This module deliberately uses the distinct names
``PromotionExecutionStart`` and ``PromotionExecutionReceipt`` for mutation
accounting. It extends the repository's single :class:`SpineLedger` Event Store;
it does not create a second workflow database, issue OwnerApproval, apply
candidates, invoke Git, merge branches, or promote automatically.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Mapping

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution_reader import (
    PromotionExecutionReadError,
    read_promotion_execution_intents,
)
from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.durability import (
    Gate0DurabilityError,
    Gate0DurabilityStatus,
    enforce_gate0_durability,
    open_gate0_spine_writer,
)
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.ledger import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTENDED,
    Intent,
    IntentAlreadyResolved,
    SpineLedger,
)

_PROMOTION_INTENT_KIND = "promotion.execution"
_PROMOTION_START_SCHEMA = "daedalus-promotion-execution-start-event/1"
_PROMOTION_TERMINAL_SCHEMA = "daedalus-promotion-execution-terminal-event/1"
_MAX_EVENT_TIME_SKEW = timedelta(seconds=60)
_MAX_REPORT_BYTES = 4 * 1024 * 1024


class PromotionExecutionError(RuntimeError):
    """Base class for fail-closed promotion-execution accounting."""


class PromotionExecutionBindingMismatch(PromotionExecutionError):
    pass


class PromotionExecutionReplay(PromotionExecutionError):
    pass


class PromotionExecutionStateError(PromotionExecutionError):
    pass


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PromotionExecutionStateError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionExecutionStateError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _effect_key(promotion_id: str) -> str:
    return f"promotion.execution:{_identifier(promotion_id, 'promotion_id')}"


def _freeze_json(value: Any, label: str = "value") -> Any:
    """Validate and freeze one bounded JSON value without coercion."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PromotionExecutionStateError(
                f"{label} contains a non-finite float"
            )
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise PromotionExecutionStateError(
                    f"{label} contains a non-string object key"
                )
            frozen[key] = _freeze_json(nested, f"{label}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{label}[]") for item in value)
    raise PromotionExecutionStateError(
        f"{label} contains non-JSON value {type(value).__name__}"
    )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionExecutionStateError(f"{label} must be an object")
    frozen = _freeze_json(value, label)
    decoded = _thaw_json(frozen)
    if not isinstance(decoded, dict):
        raise PromotionExecutionStateError(f"{label} must canonicalize to an object")
    try:
        encoded = canonical_json(decoded)
    except (TypeError, ValueError) as exc:
        raise PromotionExecutionStateError(f"{label} is not canonical JSON") from exc
    if len(encoded.encode("ascii")) > _MAX_REPORT_BYTES:
        raise PromotionExecutionStateError(
            f"{label} exceeds {_MAX_REPORT_BYTES} bytes"
        )
    try:
        parsed = json.loads(
            encoded,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise PromotionExecutionStateError(f"{label} is not canonical JSON") from exc
    if parsed != decoded:
        raise PromotionExecutionStateError(
            f"{label} changed during canonical JSON round trip"
        )
    return decoded


def _authorization_payload(authorization: PromotionAuthorization) -> dict[str, str]:
    if not isinstance(authorization, PromotionAuthorization):
        raise PromotionExecutionBindingMismatch(
            "promotion execution requires PromotionAuthorization"
        )
    body = {
        "promotion_id": _identifier(authorization.promotion_id, "promotion_id"),
        "candidate_artifact_sha256": _sha256(
            authorization.candidate_artifact_sha256,
            "candidate_artifact_sha256",
        ),
        "evidence_packet_sha256": _sha256(
            authorization.evidence_packet_sha256,
            "evidence_packet_sha256",
        ),
        "source_revision": _revision(
            authorization.source_revision,
            "source_revision",
        ),
        "target_ref": _identifier(authorization.target_ref, "target_ref"),
        "live_target_revision": _revision(
            authorization.live_target_revision,
            "live_target_revision",
        ),
        "approval_consumption_sha256": _sha256(
            authorization.approval_consumption_sha256,
            "approval_consumption_sha256",
        ),
    }
    declared = _sha256(
        authorization.authorization_sha256,
        "authorization_sha256",
    )
    if declared != canonical_sha(body):
        raise PromotionExecutionBindingMismatch(
            "promotion authorization digest does not bind its fields"
        )
    return {**body, "authorization_sha256": declared}


@dataclass(frozen=True)
class PromotionExecutionStart(CanonicalContract):
    """Persisted intent committed before the first promotion mutation."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion-execution-start"

    start_id: str
    promotion_id: str
    authorization_sha256: str
    approval_consumption_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    source_revision: str
    target_ref: str
    authorized_target_revision: str
    primary_checkout_before_sha256: str
    started_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("start_id", "promotion_id", "target_ref"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "authorization_sha256",
            "approval_consumption_sha256",
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
            "primary_checkout_before_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "authorized_target_revision",
            _revision(
                self.authorized_target_revision,
                "authorized_target_revision",
            ),
        )
        object.__setattr__(
            self,
            "started_at",
            _utc_timestamp(self.started_at, "started_at"),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("promotion execution start requires provenance")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "promotion execution start revision must match provenance"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.authorization_sha256,
                self.approval_consumption_sha256,
                self.candidate_artifact_sha256,
                self.evidence_packet_sha256,
                self.primary_checkout_before_sha256,
            ),
            "promotion execution start",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PromotionExecutionStart":
        body = cls._contract_payload(payload)
        provenance = body.get("provenance")
        if not isinstance(provenance, Mapping):
            raise ValueError("promotion execution start provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)

    def same_subject(self, other: "PromotionExecutionStart") -> bool:
        if not isinstance(other, PromotionExecutionStart):
            return False
        ignored = {"started_at", "provenance"}
        return all(
            getattr(self, field.name) == getattr(other, field.name)
            for field in fields(self)
            if field.name not in ignored
        )


@dataclass(frozen=True)
class PromotionExecutionReceipt(CanonicalContract):
    """One immutable terminal account of an authorized promotion attempt."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion-execution-receipt"

    receipt_id: str
    promotion_id: str
    start_sha256: str
    authorization_sha256: str
    approval_consumption_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    source_revision: str
    target_ref: str
    authorized_target_revision: str
    outcome: str
    integration_branch: str | None
    integration_revision: str | None
    report_sha256: str
    primary_checkout_before_sha256: str
    primary_checkout_after_sha256: str
    completed_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("receipt_id", "promotion_id", "target_ref"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "start_sha256",
            "authorization_sha256",
            "approval_consumption_sha256",
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
            "report_sha256",
            "primary_checkout_before_sha256",
            "primary_checkout_after_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "authorized_target_revision",
            _revision(
                self.authorized_target_revision,
                "authorized_target_revision",
            ),
        )
        if self.integration_branch is not None:
            object.__setattr__(
                self,
                "integration_branch",
                _identifier(self.integration_branch, "integration_branch"),
            )
        if self.integration_revision is not None:
            object.__setattr__(
                self,
                "integration_revision",
                _revision(self.integration_revision, "integration_revision"),
            )
        if not isinstance(self.outcome, str) or self.outcome not in {
            "succeeded",
            "refused",
            "faulted",
        }:
            raise ValueError(
                "promotion execution outcome must be succeeded, refused, or faulted"
            )
        if self.outcome == "succeeded" and (
            self.integration_branch is None or self.integration_revision is None
        ):
            raise ValueError(
                "successful promotion execution requires branch and revision"
            )
        if self.outcome == "refused" and (
            self.integration_branch is not None or self.integration_revision is not None
        ):
            raise ValueError(
                "refused promotion execution cannot retain integration identity"
            )
        if self.integration_revision is not None and self.integration_branch is None:
            raise ValueError("integration_revision requires integration_branch")
        if (
            self.primary_checkout_before_sha256
            != self.primary_checkout_after_sha256
            and self.outcome != "faulted"
        ):
            raise ValueError(
                "primary checkout changed; terminal outcome must be faulted"
            )
        object.__setattr__(
            self,
            "completed_at",
            _utc_timestamp(self.completed_at, "completed_at"),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("promotion execution receipt requires provenance")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "promotion execution receipt revision must match provenance"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.start_sha256,
                self.authorization_sha256,
                self.approval_consumption_sha256,
                self.candidate_artifact_sha256,
                self.evidence_packet_sha256,
                self.report_sha256,
                self.primary_checkout_before_sha256,
                self.primary_checkout_after_sha256,
            ),
            "promotion execution receipt",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PromotionExecutionReceipt":
        body = cls._contract_payload(payload)
        provenance = body.get("provenance")
        if not isinstance(provenance, Mapping):
            raise ValueError("promotion execution receipt provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)

    def same_subject(self, other: "PromotionExecutionReceipt") -> bool:
        if not isinstance(other, PromotionExecutionReceipt):
            return False
        ignored = {"completed_at", "provenance"}
        return all(
            getattr(self, field.name) == getattr(other, field.name)
            for field in fields(self)
            if field.name not in ignored
        )


@dataclass(frozen=True)
class PromotionExecutionCompletion:
    receipt: PromotionExecutionReceipt
    report: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, PromotionExecutionReceipt):
            raise ValueError(
                "promotion execution completion requires a terminal receipt"
            )
        canonical = _canonical_object(self.report, "promotion execution report")
        object.__setattr__(
            self,
            "report",
            _freeze_json(canonical, "promotion execution report"),
        )
        if canonical_sha(canonical) != self.receipt.report_sha256:
            raise ValueError("promotion execution report digest mismatch")

    def report_dict(self) -> dict[str, Any]:
        value = _thaw_json(self.report)
        if not isinstance(value, dict):
            raise ValueError("promotion execution report must be an object")
        return value


@dataclass(frozen=True)
class PromotionExecutionBeginResult:
    start: PromotionExecutionStart
    execute: bool
    completion: PromotionExecutionCompletion | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.start, PromotionExecutionStart):
            raise ValueError("promotion begin result requires a start")
        if type(self.execute) is not bool:
            raise ValueError("promotion begin execute must be boolean")
        if self.execute and self.completion is not None:
            raise ValueError("fresh promotion start cannot have a completion")
        if self.completion is not None:
            if self.completion.receipt.start_sha256 != self.start.digest:
                raise ValueError("completion belongs to another start")

    @property
    def pending_reconciliation(self) -> bool:
        return not self.execute and self.completion is None


def _validate_event_time(recorded: str, event_time: str, label: str) -> None:
    record = _parse_utc(recorded, label)
    event = _parse_utc(event_time, f"{label} Event-Store time")
    if record > event:
        raise PromotionExecutionStateError(
            f"{label} follows its Event-Store transition"
        )
    if event - record > _MAX_EVENT_TIME_SKEW:
        raise PromotionExecutionStateError(
            f"{label} is detached from its Event-Store transition"
        )


def _validate_report(
    *,
    report: Mapping[str, Any],
    start: PromotionExecutionStart,
    outcome: str,
    integration_branch: str | None,
    integration_revision: str | None,
    primary_checkout_after_sha256: str,
) -> dict[str, Any]:
    canonical = _canonical_object(report, "promotion execution report")
    for name in ("promoted", "refused", "not_gated"):
        if not isinstance(canonical.get(name), list):
            raise PromotionExecutionBindingMismatch(
                f"promotion report {name} must be an array"
            )

    expected_authorization = {
        "promotion_id": start.promotion_id,
        "candidate_artifact_sha256": start.candidate_artifact_sha256,
        "evidence_packet_sha256": start.evidence_packet_sha256,
        "source_revision": start.source_revision,
        "target_ref": start.target_ref,
        "live_target_revision": start.authorized_target_revision,
        "approval_consumption_sha256": start.approval_consumption_sha256,
        "authorization_sha256": start.authorization_sha256,
    }
    if canonical.get("authorization") != expected_authorization:
        raise PromotionExecutionBindingMismatch(
            "promotion report does not bind the persisted authorization"
        )
    if canonical.get("integration_branch") != integration_branch:
        raise PromotionExecutionBindingMismatch(
            "promotion report integration branch mismatch"
        )
    if canonical.get("integration_revision") != integration_revision:
        raise PromotionExecutionBindingMismatch(
            "promotion report integration revision mismatch"
        )

    promoted = canonical["promoted"]
    refused = canonical["refused"]
    not_gated = canonical["not_gated"]
    primary_changed = (
        start.primary_checkout_before_sha256
        != _sha256(
            primary_checkout_after_sha256,
            "primary_checkout_after_sha256",
        )
    )
    if outcome == "succeeded":
        if len(promoted) != 1 or refused or not_gated:
            raise PromotionExecutionBindingMismatch(
                "successful promotion requires exactly one promoted result"
            )
        row = promoted[0]
        if not isinstance(row, Mapping) or row.get("promoted") is not True:
            raise PromotionExecutionBindingMismatch(
                "successful promotion row is malformed"
            )
        if canonical.get("cleanup_error") is not None:
            raise PromotionExecutionBindingMismatch(
                "successful promotion cannot retain a cleanup error"
            )
        if primary_changed:
            raise PromotionExecutionBindingMismatch(
                "successful promotion changed the primary checkout"
            )
    elif outcome == "refused":
        if promoted or not (refused or not_gated):
            raise PromotionExecutionBindingMismatch(
                "refused promotion requires no promoted result and a refusal"
            )
        if integration_branch is not None or integration_revision is not None:
            raise PromotionExecutionBindingMismatch(
                "refused promotion cannot retain integration identity"
            )
        if primary_changed:
            raise PromotionExecutionBindingMismatch(
                "refused promotion changed the primary checkout"
            )
    elif outcome == "faulted":
        if (
            not primary_changed
            and not canonical.get("fault")
            and not canonical.get("cleanup_error")
        ):
            raise PromotionExecutionBindingMismatch(
                "faulted promotion requires explicit fault evidence"
            )
    else:
        raise PromotionExecutionBindingMismatch("unknown promotion outcome")
    return canonical


class PromotionExecutionLedger:
    """Promotion lifecycle facade over the single canonical Event Store."""

    def __init__(
        self,
        path: str | Path | SpineLedger,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._owns_spine = not isinstance(path, SpineLedger)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.spine: SpineLedger | None = None
        try:
            self.spine = (
                open_gate0_spine_writer(path)
                if self._owns_spine
                else path
            )
            if getattr(self.spine, "read_only", False):
                raise PromotionExecutionStateError(
                    "promotion execution requires a writable canonical Event Store"
                )
            self.durability_status: Gate0DurabilityStatus = (
                enforce_gate0_durability(self.spine)
            )
            self.path = self.spine.path
            self._install_single_start_invariant()
        except Gate0DurabilityError as exc:
            if self._owns_spine and self.spine is not None:
                self.spine.close()
            raise PromotionExecutionStateError(
                "promotion execution requires Gate-0 Event-Store durability"
            ) from exc
        except BaseException:
            if self._owns_spine and self.spine is not None:
                self.spine.close()
            raise

    def close(self) -> None:
        if self._owns_spine and self.spine is not None:
            self.spine.close()

    def _require_spine(self) -> SpineLedger:
        if self.spine is None:
            raise PromotionExecutionStateError("promotion Event Store is unavailable")
        return self.spine

    def _now(self, *, minimum: str | None = None) -> str:
        value = self._clock()
        if not isinstance(value, datetime):
            raise PromotionExecutionStateError("promotion ledger clock is invalid")
        if value.tzinfo is None or value.utcoffset() is None:
            raise PromotionExecutionStateError(
                "promotion ledger clock must be timezone-aware"
            )
        instant = value.astimezone(timezone.utc)
        if minimum is not None:
            floor = _parse_utc(minimum, "minimum promotion time")
            if instant < floor:
                instant = floor
        return instant.isoformat(timespec="microseconds")

    def _install_single_start_invariant(self) -> None:
        try:
            with self._require_spine()._txn() as connection:
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_promotion_execution_effect_key "
                    "ON intents(effect_key) "
                    "WHERE kind = 'promotion.execution'"
                )
        except (sqlite3.DatabaseError, AttributeError) as exc:
            raise PromotionExecutionStateError(
                "canonical Event Store cannot enforce one promotion start"
            ) from exc

    def _read_intents(self, *, effect_key: str | None = None) -> list[Intent]:
        try:
            return read_promotion_execution_intents(
                self.path,
                effect_key=effect_key,
            )
        except PromotionExecutionReadError as exc:
            raise PromotionExecutionStateError(
                "strict promotion execution Event-Store projection refused"
            ) from exc

    def _intent_for(self, promotion_id: str) -> Intent | None:
        key = _effect_key(promotion_id)
        rows = self._read_intents(effect_key=key)
        if any(row.kind != _PROMOTION_INTENT_KIND for row in rows):
            raise PromotionExecutionStateError(
                "promotion effect key belongs to another intent kind"
            )
        if len(rows) > 1:
            raise PromotionExecutionStateError(
                "promotion has multiple canonical Event-Store starts"
            )
        return rows[0] if rows else None

    @staticmethod
    def _decode_start(intent: Intent) -> PromotionExecutionStart:
        if intent.kind != _PROMOTION_INTENT_KIND:
            raise PromotionExecutionStateError("wrong promotion intent kind")
        parsed = _canonical_object(intent.payload, "persisted promotion start event")
        if set(parsed) != {"schema", "start"}:
            raise PromotionExecutionStateError(
                "persisted promotion start event has wrong shape"
            )
        if parsed.get("schema") != _PROMOTION_START_SCHEMA:
            raise PromotionExecutionStateError(
                "persisted promotion start event has wrong schema"
            )
        raw_start = parsed.get("start")
        if not isinstance(raw_start, Mapping):
            raise PromotionExecutionStateError(
                "persisted promotion start is not an object"
            )
        try:
            start = PromotionExecutionStart.from_dict(raw_start)
        except (TypeError, ValueError, KeyError) as exc:
            raise PromotionExecutionStateError(
                "persisted promotion start is malformed"
            ) from exc
        canonical = {"schema": _PROMOTION_START_SCHEMA, "start": start.to_dict()}
        expected_json = canonical_json(canonical)
        if intent.payload_json != expected_json:
            raise PromotionExecutionStateError(
                "persisted promotion start event is noncanonical"
            )
        if intent.payload_sha != hashlib.sha256(expected_json.encode("ascii")).hexdigest():
            raise PromotionExecutionStateError(
                "persisted promotion start digest is invalid"
            )
        if intent.effect_key != _effect_key(start.promotion_id):
            raise PromotionExecutionStateError(
                "persisted promotion effect key does not bind its start"
            )
        _validate_event_time(start.started_at, intent.created_ts, "started_at")
        return start

    @staticmethod
    def _decode_completion(
        intent: Intent,
        start: PromotionExecutionStart,
    ) -> PromotionExecutionCompletion | None:
        if intent.state == STATE_INTENDED:
            return None
        if intent.state == STATE_FAILED:
            raise PromotionExecutionStateError(
                "promotion execution intent was failed outside its contract"
            )
        if intent.state != STATE_COMPLETED:
            raise PromotionExecutionStateError(
                f"unknown promotion execution state: {intent.state}"
            )
        result = _canonical_object(
            intent.result,
            "persisted promotion terminal event",
        )
        if set(result) != {"schema", "receipt", "report"}:
            raise PromotionExecutionStateError(
                "persisted promotion terminal event has wrong shape"
            )
        if result.get("schema") != _PROMOTION_TERMINAL_SCHEMA:
            raise PromotionExecutionStateError(
                "persisted promotion terminal event has wrong schema"
            )
        raw_receipt = result.get("receipt")
        raw_report = result.get("report")
        if not isinstance(raw_receipt, Mapping) or not isinstance(raw_report, Mapping):
            raise PromotionExecutionStateError(
                "persisted promotion terminal fields are malformed"
            )
        try:
            receipt = PromotionExecutionReceipt.from_dict(raw_receipt)
            completion = PromotionExecutionCompletion(
                receipt=receipt,
                report=raw_report,
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise PromotionExecutionStateError(
                "persisted promotion terminal receipt is malformed"
            ) from exc
        canonical = {
            "schema": _PROMOTION_TERMINAL_SCHEMA,
            "receipt": receipt.to_dict(),
            "report": completion.report_dict(),
        }
        if result != canonical:
            raise PromotionExecutionStateError(
                "persisted promotion terminal event is noncanonical"
            )
        if intent.effect_id != receipt.digest:
            raise PromotionExecutionStateError(
                "terminal Event-Store effect_id does not bind receipt"
            )
        if receipt.start_sha256 != start.digest:
            raise PromotionExecutionStateError(
                "terminal receipt does not bind persisted start"
            )
        repeated = {
            "promotion_id": start.promotion_id,
            "authorization_sha256": start.authorization_sha256,
            "approval_consumption_sha256": start.approval_consumption_sha256,
            "candidate_artifact_sha256": start.candidate_artifact_sha256,
            "evidence_packet_sha256": start.evidence_packet_sha256,
            "source_revision": start.source_revision,
            "target_ref": start.target_ref,
            "authorized_target_revision": start.authorized_target_revision,
            "primary_checkout_before_sha256": start.primary_checkout_before_sha256,
        }
        mismatches = [
            name
            for name, expected in repeated.items()
            if getattr(receipt, name) != expected
        ]
        if mismatches:
            raise PromotionExecutionStateError(
                "terminal receipt contradicts persisted start: "
                + ", ".join(sorted(mismatches))
            )
        if _parse_utc(receipt.completed_at, "completed_at") < _parse_utc(
            start.started_at,
            "started_at",
        ):
            raise PromotionExecutionStateError(
                "promotion completion precedes persisted start"
            )
        if intent.resolved_ts is None:
            raise PromotionExecutionStateError(
                "terminal promotion event is missing resolution time"
            )
        _validate_event_time(
            receipt.completed_at,
            intent.resolved_ts,
            "completed_at",
        )
        try:
            _validate_report(
                report=completion.report_dict(),
                start=start,
                outcome=receipt.outcome,
                integration_branch=receipt.integration_branch,
                integration_revision=receipt.integration_revision,
                primary_checkout_after_sha256=(
                    receipt.primary_checkout_after_sha256
                ),
            )
        except PromotionExecutionBindingMismatch as exc:
            raise PromotionExecutionStateError(
                "persisted promotion report contradicts terminal receipt"
            ) from exc
        return completion

    def begin(
        self,
        authorization: PromotionAuthorization,
        *,
        start_id: str,
        primary_checkout_before_sha256: str,
    ) -> PromotionExecutionBeginResult:
        authorization_fields = _authorization_payload(authorization)
        started_at = self._now()
        primary_before = _sha256(
            primary_checkout_before_sha256,
            "primary_checkout_before_sha256",
        )
        start = PromotionExecutionStart(
            start_id=start_id,
            promotion_id=authorization_fields["promotion_id"],
            authorization_sha256=authorization_fields["authorization_sha256"],
            approval_consumption_sha256=authorization_fields[
                "approval_consumption_sha256"
            ],
            candidate_artifact_sha256=authorization_fields[
                "candidate_artifact_sha256"
            ],
            evidence_packet_sha256=authorization_fields[
                "evidence_packet_sha256"
            ],
            source_revision=authorization_fields["source_revision"],
            target_ref=authorization_fields["target_ref"],
            authorized_target_revision=authorization_fields[
                "live_target_revision"
            ],
            primary_checkout_before_sha256=primary_before,
            started_at=started_at,
            provenance=ContractProvenance(
                origin="kernel.promotion-execution.begin",
                source_revision=authorization_fields["source_revision"],
                created_at=started_at,
                input_digests=tuple(
                    sorted(
                        {
                            authorization_fields["authorization_sha256"],
                            authorization_fields["approval_consumption_sha256"],
                            authorization_fields["candidate_artifact_sha256"],
                            authorization_fields["evidence_packet_sha256"],
                            primary_before,
                        }
                    )
                ),
                trace_id=authorization_fields["promotion_id"],
            ),
        )
        intent = self._intent_for(start.promotion_id)
        created = False
        if intent is None:
            payload = {"schema": _PROMOTION_START_SCHEMA, "start": start.to_dict()}
            try:
                intent = self._require_spine().record_intent(
                    _PROMOTION_INTENT_KIND,
                    payload,
                    effect_key=_effect_key(start.promotion_id),
                    trace_id=start.promotion_id,
                )
                created = True
            except sqlite3.IntegrityError:
                intent = self._intent_for(start.promotion_id)
                if intent is None:
                    raise PromotionExecutionStateError(
                        "concurrent promotion start conflicted without a winner"
                    )
        persisted = self._decode_start(intent)
        if not persisted.same_subject(start):
            raise PromotionExecutionReplay(
                "promotion_id was already started with different material"
            )
        completion = self._decode_completion(intent, persisted)
        return PromotionExecutionBeginResult(
            start=persisted,
            execute=created,
            completion=completion,
        )

    def complete(
        self,
        start: PromotionExecutionStart,
        *,
        receipt_id: str,
        outcome: str,
        report: Mapping[str, Any],
        primary_checkout_after_sha256: str,
        integration_branch: str | None = None,
        integration_revision: str | None = None,
    ) -> PromotionExecutionCompletion:
        if not isinstance(start, PromotionExecutionStart):
            raise PromotionExecutionBindingMismatch(
                "completion requires PromotionExecutionStart"
            )
        primary_after = _sha256(
            primary_checkout_after_sha256,
            "primary_checkout_after_sha256",
        )
        canonical_report = _validate_report(
            report=report,
            start=start,
            outcome=outcome,
            integration_branch=integration_branch,
            integration_revision=integration_revision,
            primary_checkout_after_sha256=primary_after,
        )
        report_sha = canonical_sha(canonical_report)
        completed_at = self._now(minimum=start.started_at)
        receipt = PromotionExecutionReceipt(
            receipt_id=receipt_id,
            promotion_id=start.promotion_id,
            start_sha256=start.digest,
            authorization_sha256=start.authorization_sha256,
            approval_consumption_sha256=start.approval_consumption_sha256,
            candidate_artifact_sha256=start.candidate_artifact_sha256,
            evidence_packet_sha256=start.evidence_packet_sha256,
            source_revision=start.source_revision,
            target_ref=start.target_ref,
            authorized_target_revision=start.authorized_target_revision,
            outcome=outcome,
            integration_branch=integration_branch,
            integration_revision=integration_revision,
            report_sha256=report_sha,
            primary_checkout_before_sha256=start.primary_checkout_before_sha256,
            primary_checkout_after_sha256=primary_after,
            completed_at=completed_at,
            provenance=ContractProvenance(
                origin="kernel.promotion-execution.complete",
                source_revision=start.source_revision,
                created_at=completed_at,
                input_digests=tuple(
                    sorted(
                        {
                            start.digest,
                            start.authorization_sha256,
                            start.approval_consumption_sha256,
                            start.candidate_artifact_sha256,
                            start.evidence_packet_sha256,
                            report_sha,
                            start.primary_checkout_before_sha256,
                            primary_after,
                        }
                    )
                ),
                trace_id=start.promotion_id,
            ),
        )
        intent = self._intent_for(start.promotion_id)
        if intent is None:
            raise PromotionExecutionStateError("promotion start is not persisted")
        persisted_start = self._decode_start(intent)
        if persisted_start != start:
            raise PromotionExecutionBindingMismatch(
                "submitted promotion start differs from persisted start"
            )
        existing = self._decode_completion(intent, persisted_start)
        if existing is not None:
            if (
                not existing.receipt.same_subject(receipt)
                or existing.report_dict() != canonical_report
            ):
                raise PromotionExecutionReplay(
                    "promotion already has a different terminal receipt"
                )
            return existing
        result = {
            "schema": _PROMOTION_TERMINAL_SCHEMA,
            "receipt": receipt.to_dict(),
            "report": canonical_report,
        }
        try:
            terminal = self._require_spine().mark_completed(
                intent.id,
                effect_id=receipt.digest,
                result=result,
            )
        except IntentAlreadyResolved:
            terminal = self._intent_for(start.promotion_id)
            if terminal is None:
                raise PromotionExecutionStateError(
                    "resolved promotion disappeared from Event Store"
                )
        completion = self._decode_completion(terminal, persisted_start)
        if completion is None:
            raise PromotionExecutionStateError(
                "terminal promotion resolution was not retained"
            )
        if (
            not completion.receipt.same_subject(receipt)
            or completion.report_dict() != canonical_report
        ):
            raise PromotionExecutionReplay(
                "promotion already has a different terminal receipt"
            )
        return completion

    def pending(self) -> tuple[PromotionExecutionStart, ...]:
        pending: list[PromotionExecutionStart] = []
        for intent in self._read_intents():
            if intent.kind != _PROMOTION_INTENT_KIND:
                raise PromotionExecutionStateError(
                    "reserved promotion effect key belongs to another intent kind"
                )
            start = self._decode_start(intent)
            completion = self._decode_completion(intent, start)
            if completion is None:
                pending.append(start)
        return tuple(sorted(pending, key=lambda value: value.promotion_id))


__all__ = [
    "PromotionExecutionBeginResult",
    "PromotionExecutionBindingMismatch",
    "PromotionExecutionCompletion",
    "PromotionExecutionError",
    "PromotionExecutionLedger",
    "PromotionExecutionReceipt",
    "PromotionExecutionReplay",
    "PromotionExecutionStart",
    "PromotionExecutionStateError",
]

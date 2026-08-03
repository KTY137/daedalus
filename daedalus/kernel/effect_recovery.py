"""Authenticated reconciliation for externally acknowledged unknown effects."""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    EffectLeaseStateError,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.schemas import (
    ContractProvenance,
    _identifier,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_MAX_OBSERVATION_AGE = timedelta(hours=24)
_ACKNOWLEDGED = "acknowledged"


class EffectRecoveryError(RuntimeError):
    pass


class EffectRecoverySignatureError(EffectRecoveryError):
    pass


class EffectRecoveryBindingError(EffectRecoveryError):
    pass


class EffectRecoveryStateError(EffectRecoveryError):
    pass


@dataclass(frozen=True)
class ExternalEffectObservation:
    observation_id: str
    provider_id: str
    execution_id: str
    idempotency_key: str
    start_receipt_sha256: str
    status: str
    acknowledgement_sha256: str
    output_digests: tuple[str, ...]
    issuer_key_id: str
    observed_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_id",
            _identifier(self.observation_id, "observation_id"),
        )
        object.__setattr__(
            self,
            "provider_id",
            _identifier(self.provider_id, "provider_id"),
        )
        object.__setattr__(
            self,
            "execution_id",
            _identifier(self.execution_id, "execution_id"),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            _identifier(self.idempotency_key, "idempotency_key"),
        )
        object.__setattr__(
            self,
            "start_receipt_sha256",
            _sha256(self.start_receipt_sha256, "start_receipt_sha256"),
        )
        normalized = str(self.status).lower()
        if normalized != _ACKNOWLEDGED:
            raise ValueError("external effect observation must be acknowledged")
        object.__setattr__(self, "status", normalized)
        object.__setattr__(
            self,
            "acknowledgement_sha256",
            _sha256(self.acknowledgement_sha256, "acknowledgement_sha256"),
        )
        object.__setattr__(
            self,
            "output_digests",
            _sorted_strings(
                self.output_digests,
                "output_digests",
                digests=True,
            ),
        )
        object.__setattr__(
            self,
            "issuer_key_id",
            _identifier(self.issuer_key_id, "issuer_key_id"),
        )
        object.__setattr__(
            self,
            "observed_at",
            _utc_timestamp(self.observed_at, "observed_at"),
        )
        object.__setattr__(
            self,
            "signature_sha256",
            _sha256(self.signature_sha256, "signature_sha256"),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("provenance must be ContractProvenance")
        required = {
            self.start_receipt_sha256,
            self.acknowledgement_sha256,
            *self.output_digests,
        }
        if not required.issubset(set(self.provenance.input_digests)):
            raise ValueError("observation provenance must bind all evidence digests")

    def to_dict(self) -> dict[str, Any]:
        return {
            **dataclasses.asdict(self),
            "output_digests": list(self.output_digests),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExternalEffectObservation":
        expected = {
            "observation_id",
            "provider_id",
            "execution_id",
            "idempotency_key",
            "start_receipt_sha256",
            "status",
            "acknowledgement_sha256",
            "output_digests",
            "issuer_key_id",
            "observed_at",
            "signature_sha256",
            "provenance",
        }
        if set(payload) != expected:
            raise ValueError("external effect observation fields are not exact")
        values = dict(payload)
        outputs = values["output_digests"]
        if isinstance(outputs, (str, bytes)) or not isinstance(outputs, Sequence):
            raise ValueError("output_digests must be a sequence")
        values["output_digests"] = tuple(outputs)
        provenance = values["provenance"]
        if not isinstance(provenance, Mapping):
            raise ValueError("provenance must be an object")
        values["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**values)

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class EffectRecoveryResult:
    terminal_receipt: EffectTerminalReceipt
    observation_sha256: str
    reconciled: bool


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("recovery issuer secret must contain at least 32 bytes")
    return value


def _signature(digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EffectRecoveryBindingError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EffectRecoveryBindingError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def issue_external_effect_observation(
    *,
    observation_id: str,
    provider_id: str,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    acknowledgement_sha256: str,
    output_digests: Sequence[str],
    issuer_key_id: str,
    issuer_secret: bytes | str,
    source_revision: str,
    observed_at: datetime,
) -> ExternalEffectObservation:
    revision = _revision(source_revision, "source_revision")
    instant = _as_utc(observed_at, "observed_at")
    outputs = tuple(output_digests)
    provenance = ContractProvenance(
        origin="kernel.external-effect-observation",
        source_revision=revision,
        created_at=instant.isoformat(timespec="microseconds"),
        input_digests=tuple(
            sorted(
                {
                    start_receipt.receipt_sha256,
                    _sha256(
                        acknowledgement_sha256,
                        "acknowledgement_sha256",
                    ),
                    *outputs,
                }
            )
        ),
        trace_id=execution.execution_id,
    )
    placeholder = ExternalEffectObservation(
        observation_id=observation_id,
        provider_id=provider_id,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        start_receipt_sha256=start_receipt.receipt_sha256,
        status=_ACKNOWLEDGED,
        acknowledgement_sha256=acknowledgement_sha256,
        output_digests=outputs,
        issuer_key_id=issuer_key_id,
        observed_at=instant.isoformat(timespec="microseconds"),
        signature_sha256="0" * 64,
        provenance=provenance,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(placeholder.signing_digest, issuer_secret),
    )


def verify_external_effect_observation(
    observation: ExternalEffectObservation,
    *,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    keyring: Mapping[str, bytes | str],
    expected_provider_id: str,
    expected_source_revision: str,
    now: datetime,
) -> None:
    secret = keyring.get(observation.issuer_key_id)
    if secret is None:
        raise EffectRecoverySignatureError("recovery issuer key is unknown")
    expected = _signature(observation.signing_digest, secret)
    if not hmac.compare_digest(observation.signature_sha256, expected):
        raise EffectRecoverySignatureError("recovery observation signature mismatch")
    instant = _as_utc(now, "now")
    observed = _parse_utc(observation.observed_at, "observed_at")
    if observed > instant:
        raise EffectRecoveryBindingError("recovery observation is from the future")
    if instant - observed > _MAX_OBSERVATION_AGE:
        raise EffectRecoveryBindingError("recovery observation is stale")
    comparisons = {
        "provider_id": (
            observation.provider_id,
            _identifier(expected_provider_id, "expected_provider_id"),
        ),
        "execution_id": (observation.execution_id, execution.execution_id),
        "idempotency_key": (
            observation.idempotency_key,
            execution.idempotency_key,
        ),
        "start_receipt_sha256": (
            observation.start_receipt_sha256,
            start_receipt.receipt_sha256,
        ),
        "start_execution_id": (
            start_receipt.execution_id,
            execution.execution_id,
        ),
        "source_revision": (
            observation.provenance.source_revision,
            _revision(expected_source_revision, "expected_source_revision"),
        ),
    }
    mismatches = sorted(
        name for name, pair in comparisons.items() if pair[0] != pair[1]
    )
    if mismatches:
        raise EffectRecoveryBindingError(
            "recovery observation binding mismatch: " + ", ".join(mismatches)
        )


def _terminal_from_row(row: sqlite3.Row) -> EffectTerminalReceipt:
    payload = json.loads(str(row["terminal_receipt_json"]))
    if not isinstance(payload, dict):
        raise EffectRecoveryStateError("terminal receipt is malformed")
    outputs = payload.get("output_digests")
    if isinstance(outputs, (str, bytes)) or not isinstance(outputs, list):
        raise EffectRecoveryStateError("terminal output digests are malformed")
    values = dict(payload)
    values["output_digests"] = tuple(outputs)
    try:
        receipt = EffectTerminalReceipt(**values)
    except (TypeError, ValueError) as exc:
        raise EffectRecoveryStateError("terminal receipt is malformed") from exc
    body = receipt.to_dict()
    claimed = body.pop("receipt_sha256")
    if canonical_sha(body) != claimed:
        raise EffectRecoveryStateError("terminal receipt digest mismatch")
    if row["terminal_receipt_sha256"] != receipt.receipt_sha256:
        raise EffectRecoveryStateError("terminal receipt index mismatch")
    if row["state"] != receipt.outcome:
        raise EffectRecoveryStateError("terminal state and receipt disagree")
    return receipt


def _persisted_terminal(
    ledger: EffectLeaseLedger,
    execution_id: str,
) -> EffectTerminalReceipt | None:
    uri = f"file:{Path(ledger.path).resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT state, terminal_receipt_sha256, terminal_receipt_json "
            "FROM effect_executions WHERE execution_id=?",
            (_identifier(execution_id, "execution_id"),),
        ).fetchone()
    if row is None or row["terminal_receipt_json"] is None:
        return None
    return _terminal_from_row(row)


def _matches(
    receipt: EffectTerminalReceipt,
    *,
    start_receipt: LeasedEffectStartReceipt,
    observation: ExternalEffectObservation,
) -> bool:
    return (
        receipt.lease_sha256 == start_receipt.lease_sha256
        and receipt.execution_id == start_receipt.execution_id
        and receipt.start_receipt_sha256 == start_receipt.receipt_sha256
        and receipt.outcome == "COMPLETED"
        and receipt.output_digests == observation.output_digests
        and receipt.detail_sha256 == observation.digest
    )


def reconcile_unknown_effect(
    ledger: EffectLeaseLedger,
    *,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    observation: ExternalEffectObservation,
    keyring: Mapping[str, bytes | str],
    expected_provider_id: str,
    expected_source_revision: str,
    reconciled_at: datetime,
) -> EffectRecoveryResult:
    verify_external_effect_observation(
        observation,
        execution=execution,
        start_receipt=start_receipt,
        keyring=keyring,
        expected_provider_id=expected_provider_id,
        expected_source_revision=expected_source_revision,
        now=reconciled_at,
    )
    state = ledger.execution_state(execution.execution_id)
    if state is None:
        raise EffectRecoveryStateError("cannot reconcile an unknown execution")
    if state == "STARTED":
        try:
            receipt = ledger.finish(
                start_receipt,
                outcome="COMPLETED",
                output_digests=observation.output_digests,
                detail_sha256=observation.digest,
                finished_at=reconciled_at,
            )
            return EffectRecoveryResult(
                terminal_receipt=receipt,
                observation_sha256=observation.digest,
                reconciled=True,
            )
        except EffectLeaseStateError:
            # A concurrent reconciler may have committed the same terminal.
            pass
    receipt = _persisted_terminal(ledger, execution.execution_id)
    if receipt is not None and _matches(
        receipt,
        start_receipt=start_receipt,
        observation=observation,
    ):
        return EffectRecoveryResult(
            terminal_receipt=receipt,
            observation_sha256=observation.digest,
            reconciled=False,
        )
    raise EffectRecoveryStateError(
        "execution is terminal under different recovery evidence"
    )


__all__ = [
    "EffectRecoveryBindingError",
    "EffectRecoveryError",
    "EffectRecoveryResult",
    "EffectRecoverySignatureError",
    "EffectRecoveryStateError",
    "ExternalEffectObservation",
    "issue_external_effect_observation",
    "reconcile_unknown_effect",
    "verify_external_effect_observation",
]

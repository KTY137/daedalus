"""Restart-safe retention for authenticated provider-target receipts.

A receipt is reverified against its signed target/invocation authority and exact
CAS-backed source tree before this module writes anything. The canonical Event
Store then records intent before exact receipt bytes are published to the
existing CAS. Completion binds the artifact back into the Event Store.

This is intentionally a LOCAL_GUARDS migration step. It provides no loader,
provider callback, execution authority, promotion, or OwnerApproval. A later
packet must consume a persisted Effect Lease before this path becomes CENTRAL.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.source_trees import SourceTreeStore, SourceTreeStoreError
from daedalus.runtimes.provider_executable_targets import (
    ProviderExecutableTargetAuthority,
    ProviderExecutableTargetManifest,
    ProviderExecutableTargetProjection,
)
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderInvocationRegistryManifest,
)
from daedalus.runtimes.provider_target_verification import (
    verify_provider_target_verification_receipt,
)
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
    ProviderTargetVerificationError,
)
from daedalus.spine.durability import Gate0DurabilityError, enforce_gate0_durability
from daedalus.spine.envelope import canonical_json
from daedalus.spine.ledger import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTENDED,
    Intent,
    IntentAlreadyResolved,
    SpineLedger,
    _uri_path,
)

_INTENT_KIND = "runtime.provider-target-verification-retention"
_INTENT_SCHEMA = "daedalus-provider-target-verification-retention-intent/1"
_TERMINAL_SCHEMA = "daedalus-provider-target-verification-retention-terminal/1"
_EFFECT_PREFIX = "provider-target-verification-receipt:"
_MAX_RECEIPT_BYTES = 1024 * 1024
_UNIQUE_INDEX = "idx_provider_target_verification_receipt_effect_key"


class ProviderTargetReceiptRetentionError(RuntimeError):
    """Base class for receipt-retention refusals."""


class ProviderTargetReceiptRetentionBindingError(ProviderTargetReceiptRetentionError):
    """Submitted authority, topology, or exact receipt material disagrees."""


class ProviderTargetReceiptRetentionStateError(ProviderTargetReceiptRetentionError):
    """Canonical Event-Store or CAS state is malformed or unresolved."""


class ProviderTargetReceiptRetentionReplay(ProviderTargetReceiptRetentionError):
    """A retained identity was encountered with different material."""


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionResult:
    receipt: ProviderExecutableTargetVerificationReceipt
    artifact: ArtifactRef
    projection: ProviderExecutableTargetProjection
    intent_id: int
    executed: bool

    def __post_init__(self) -> None:
        if type(self.receipt) is not ProviderExecutableTargetVerificationReceipt:
            raise ProviderTargetReceiptRetentionBindingError(
                "result receipt must be exact verification receipt"
            )
        if type(self.artifact) is not ArtifactRef:
            raise ProviderTargetReceiptRetentionBindingError(
                "result artifact must be exact ArtifactRef"
            )
        if type(self.projection) is not ProviderExecutableTargetProjection:
            raise ProviderTargetReceiptRetentionBindingError(
                "result projection must be exact target projection"
            )
        if self.artifact.sha256 != self.receipt.digest:
            raise ProviderTargetReceiptRetentionBindingError(
                "result artifact does not address receipt bytes"
            )
        if (
            isinstance(self.intent_id, bool)
            or not isinstance(self.intent_id, int)
            or self.intent_id < 1
        ):
            raise ProviderTargetReceiptRetentionBindingError(
                "result intent_id must be a positive integer"
            )
        if not isinstance(self.executed, bool):
            raise ProviderTargetReceiptRetentionBindingError(
                "result executed must be boolean"
            )


def _strict_json_bytes(payload: bytes, label: str) -> Mapping[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
        )
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionStateError(
            f"{label} is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise ProviderTargetReceiptRetentionStateError(
            f"{label} must be a JSON object"
        )
    return value


def _strict_json_text(payload: str, label: str) -> Mapping[str, Any]:
    try:
        raw = payload.encode("ascii", errors="strict")
    except UnicodeError as exc:
        raise ProviderTargetReceiptRetentionStateError(
            f"{label} is not canonical ASCII JSON"
        ) from exc
    return _strict_json_bytes(raw, label)


def _effect_key(receipt_sha256: str) -> str:
    return _EFFECT_PREFIX + receipt_sha256


def _receipt_bytes(receipt: ProviderExecutableTargetVerificationReceipt) -> bytes:
    payload = canonical_json(receipt.to_dict()).encode("ascii")
    if len(payload) > _MAX_RECEIPT_BYTES:
        raise ProviderTargetReceiptRetentionBindingError(
            "verification receipt exceeds retention bound"
        )
    if hashlib.sha256(payload).hexdigest() != receipt.digest:
        raise ProviderTargetReceiptRetentionBindingError(
            "verification receipt digest is noncanonical"
        )
    return payload


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts:
        if part == path.anchor:
            continue
        current = current / part
        if current.is_symlink():
            return True
    return False


def _sqlite_state_paths(event_store: Path) -> tuple[Path, ...]:
    return (
        event_store,
        Path(f"{event_store}-wal"),
        Path(f"{event_store}-shm"),
        Path(f"{event_store}-journal"),
    )


def _validate_topology(
    primary_checkout: Path,
    source_store: SourceTreeStore,
    spine: SpineLedger,
) -> None:
    try:
        raw_primary = primary_checkout.absolute()
        raw_store_root = source_store.root.absolute()
        raw_event_store = spine.path.absolute()
        for label, path in (
            ("primary checkout", raw_primary),
            ("receipt CAS", raw_store_root),
        ):
            if _contains_symlink(path):
                raise ProviderTargetReceiptRetentionBindingError(
                    f"{label} path must not contain symlinks"
                )
        primary = raw_primary.resolve(strict=True)
        store_root = raw_store_root.resolve(strict=True)
        event_store_files: list[Path] = []
        for index, candidate in enumerate(_sqlite_state_paths(raw_event_store)):
            if _contains_symlink(candidate):
                raise ProviderTargetReceiptRetentionBindingError(
                    "canonical Event Store state path must not contain symlinks"
                )
            if index and not candidate.exists():
                continue
            resolved = candidate.resolve(strict=True)
            identity = resolved.stat()
            if not stat.S_ISREG(identity.st_mode):
                raise ProviderTargetReceiptRetentionBindingError(
                    "canonical Event Store state must use real regular files"
                )
            if identity.st_nlink != 1:
                raise ProviderTargetReceiptRetentionBindingError(
                    "canonical Event Store state must have one filesystem identity"
                )
            event_store_files.append(resolved)
    except ProviderTargetReceiptRetentionError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ProviderTargetReceiptRetentionBindingError(
            "retention topology cannot be resolved"
        ) from exc
    if not primary.is_dir():
        raise ProviderTargetReceiptRetentionBindingError(
            "primary checkout must be a real directory"
        )
    if not store_root.is_dir():
        raise ProviderTargetReceiptRetentionBindingError(
            "receipt CAS must be a real directory"
        )
    if _paths_overlap(primary, store_root):
        raise ProviderTargetReceiptRetentionBindingError(
            "receipt CAS must be disjoint from the primary checkout"
        )
    for event_store_file in event_store_files:
        if _paths_overlap(primary, event_store_file):
            raise ProviderTargetReceiptRetentionBindingError(
                "canonical Event Store must be disjoint from the primary checkout"
            )
        if _paths_overlap(store_root, event_store_file):
            raise ProviderTargetReceiptRetentionBindingError(
                "receipt CAS and canonical Event Store must be disjoint"
            )


def _intent_payload(
    receipt: ProviderExecutableTargetVerificationReceipt,
    artifact: ArtifactRef,
) -> dict[str, Any]:
    return {
        "schema": _INTENT_SCHEMA,
        "receipt_sha256": receipt.digest,
        "receipt_artifact": artifact.to_dict(),
        "source_revision": receipt.source_revision,
        "source_tree_sha256": receipt.source_tree_sha256,
        "target_authority_sha256": receipt.target_authority_sha256,
        "target_projection_sha256": receipt.target_projection_sha256,
        "execution_id": receipt.execution_id,
        "lease_sha256": receipt.lease_sha256,
    }


def _terminal_result(
    receipt: ProviderExecutableTargetVerificationReceipt,
    artifact: ArtifactRef,
) -> dict[str, Any]:
    return {
        "schema": _TERMINAL_SCHEMA,
        "receipt_sha256": receipt.digest,
        "receipt_artifact": artifact.to_dict(),
    }


def _read_intent(path: Path, effect_key: str) -> Intent | None:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{_uri_path(path.resolve(strict=True))}?mode=ro",
            uri=True,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT * FROM intents WHERE kind=? AND effect_key=? ORDER BY id",
            (_INTENT_KIND, effect_key),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ProviderTargetReceiptRetentionStateError(
                "receipt has multiple canonical Event-Store intents"
            )
        row = rows[0]
        raw_payload = str(row["payload"])
        payload = _strict_json_text(raw_payload, "retention intent payload")
        if canonical_json(payload) != raw_payload:
            raise ProviderTargetReceiptRetentionStateError(
                "retention intent payload is noncanonical"
            )
        payload_sha = hashlib.sha256(raw_payload.encode("ascii")).hexdigest()
        if str(row["payload_sha"]) != payload_sha:
            raise ProviderTargetReceiptRetentionStateError(
                "retention intent payload digest is invalid"
            )
        events = connection.execute(
            "SELECT state, ts, detail FROM intent_events "
            "WHERE intent_id=? ORDER BY id",
            (int(row["id"]),),
        ).fetchall()
        if not events or len(events) > 2:
            raise ProviderTargetReceiptRetentionStateError(
                "retention event sequence is invalid"
            )
        if str(events[0]["state"]) != STATE_INTENDED:
            raise ProviderTargetReceiptRetentionStateError(
                "retention event sequence lacks exact intended start"
            )
        if str(events[0]["ts"]) != str(row["created_ts"]):
            raise ProviderTargetReceiptRetentionStateError(
                "retention start event time differs from intent row"
            )
        start_raw = str(events[0]["detail"])
        start = _strict_json_text(start_raw, "retention start detail")
        if canonical_json(start) != start_raw:
            raise ProviderTargetReceiptRetentionStateError(
                "retention start detail is noncanonical"
            )
        if dict(start) != {"payload_sha": payload_sha}:
            raise ProviderTargetReceiptRetentionStateError(
                "retention start detail does not bind payload digest"
            )

        state = STATE_INTENDED
        resolved_ts = None
        effect_id = None
        result: Any = None
        if len(events) == 2:
            terminal = events[1]
            state = str(terminal["state"])
            if state == STATE_FAILED:
                raise ProviderTargetReceiptRetentionStateError(
                    "receipt retention cannot fail while CAS outcome is unknown"
                )
            if state != STATE_COMPLETED:
                raise ProviderTargetReceiptRetentionStateError(
                    "retention terminal event state is invalid"
                )
            detail_raw = str(terminal["detail"])
            detail = _strict_json_text(detail_raw, "retention terminal detail")
            if canonical_json(detail) != detail_raw:
                raise ProviderTargetReceiptRetentionStateError(
                    "retention terminal detail is noncanonical"
                )
            if set(detail) != {"effect_id", "result"}:
                raise ProviderTargetReceiptRetentionStateError(
                    "retention terminal detail has wrong shape"
                )
            effect_id = detail.get("effect_id")
            result = detail.get("result")
            resolved_ts = str(terminal["ts"])

        return Intent(
            id=int(row["id"]),
            kind=str(row["kind"]),
            effect_key=str(row["effect_key"]),
            payload=dict(payload),
            payload_json=raw_payload,
            payload_sha=payload_sha,
            created_ts=str(row["created_ts"]),
            state=state,
            resolved_ts=resolved_ts,
            effect_id=effect_id,
            result=result,
            trace_id=(
                str(row["trace_id"])
                if "trace_id" in row.keys() and row["trace_id"] is not None
                else None
            ),
        )
    except sqlite3.DatabaseError as exc:
        raise ProviderTargetReceiptRetentionStateError(
            "cannot read retained receipt from canonical Event Store"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


class ProviderTargetReceiptLedger:
    """Facade over the canonical Event Store and existing artifact CAS."""

    def __init__(
        self,
        spine: SpineLedger,
        source_store: SourceTreeStore,
        *,
        primary_checkout: str | os.PathLike[str],
    ) -> None:
        if type(spine) is not SpineLedger or spine.read_only:
            raise ProviderTargetReceiptRetentionBindingError(
                "retention requires an exact writable SpineLedger"
            )
        if type(source_store) is not SourceTreeStore:
            raise ProviderTargetReceiptRetentionBindingError(
                "retention requires an exact SourceTreeStore"
            )
        try:
            enforce_gate0_durability(spine)
        except Gate0DurabilityError as exc:
            raise ProviderTargetReceiptRetentionBindingError(
                "retention requires Gate-0 Event-Store durability"
            ) from exc
        self.spine = spine
        self.source_store = source_store
        self.primary_checkout = Path(primary_checkout)
        _validate_topology(self.primary_checkout, self.source_store, self.spine)

    def _install_single_receipt_invariant(self) -> None:
        expected = (
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_UNIQUE_INDEX} "
            "ON intents(effect_key) "
            f"WHERE kind='{_INTENT_KIND}'"
        )
        try:
            with self.spine._txn() as connection:
                connection.execute(expected)
                row = connection.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='index' AND name=?",
                    (_UNIQUE_INDEX,),
                ).fetchone()
                if row is None or " ".join(str(row[0]).split()) != " ".join(
                    expected.replace(" IF NOT EXISTS", "").split()
                ):
                    raise ProviderTargetReceiptRetentionStateError(
                        "receipt uniqueness index has a foreign definition"
                    )
        except ProviderTargetReceiptRetentionError:
            raise
        except (AttributeError, sqlite3.DatabaseError) as exc:
            raise ProviderTargetReceiptRetentionStateError(
                "canonical Event Store cannot enforce one receipt retention"
            ) from exc

    def _record_or_recover_intent(
        self,
        *,
        key: str,
        payload: Mapping[str, Any],
        trace_id: str,
    ) -> Intent:
        existing = _read_intent(self.spine.path, key)
        if existing is not None:
            return existing
        try:
            return self.spine.record_intent(
                _INTENT_KIND,
                payload,
                effect_key=key,
                trace_id=trace_id,
            )
        except sqlite3.IntegrityError:
            existing = _read_intent(self.spine.path, key)
            if existing is None:
                raise ProviderTargetReceiptRetentionStateError(
                    "concurrent retention conflicted without a winner"
                )
            return existing
        except sqlite3.DatabaseError as exc:
            existing = _read_intent(self.spine.path, key)
            if existing is None:
                raise ProviderTargetReceiptRetentionStateError(
                    "intent persistence is unresolved and requires replay"
                ) from exc
            return existing

    def _validate_completed(
        self,
        intent: Intent,
        receipt: ProviderExecutableTargetVerificationReceipt,
        artifact: ArtifactRef,
        payload: bytes,
    ) -> None:
        if intent.state != STATE_COMPLETED:
            raise ProviderTargetReceiptRetentionStateError(
                "retention intent is not complete"
            )
        if intent.effect_id != artifact.sha256:
            raise ProviderTargetReceiptRetentionStateError(
                "terminal effect_id does not bind receipt artifact"
            )
        if not isinstance(intent.result, Mapping):
            raise ProviderTargetReceiptRetentionStateError(
                "retention terminal result must be an object"
            )
        if dict(intent.result) != _terminal_result(receipt, artifact):
            raise ProviderTargetReceiptRetentionStateError(
                "terminal result differs from receipt artifact"
            )
        try:
            retained = self.source_store.read_bytes(
                artifact,
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except SourceTreeStoreError as exc:
            raise ProviderTargetReceiptRetentionStateError(
                "retained receipt artifact is unavailable or corrupt"
            ) from exc
        if retained != payload:
            raise ProviderTargetReceiptRetentionStateError(
                "retained bytes differ from authenticated receipt"
            )
        parsed = _strict_json_bytes(retained, "retained receipt artifact")
        try:
            restored = ProviderExecutableTargetVerificationReceipt.from_dict(parsed)
        except ProviderTargetVerificationError as exc:
            raise ProviderTargetReceiptRetentionStateError(
                "retained receipt artifact is malformed"
            ) from exc
        if restored != receipt:
            raise ProviderTargetReceiptRetentionStateError(
                "retained artifact reconstructs a different receipt"
            )

    def retain(
        self,
        receipt: ProviderExecutableTargetVerificationReceipt,
        target_authority: ProviderExecutableTargetAuthority,
        invocation_authority: ProviderInvocationObservationAuthority,
        identity_registry: ProviderInvocationRegistryManifest,
        execution: EffectExecutionRequest,
        target_manifest: ProviderExecutableTargetManifest,
        source_tree_ref: ArtifactRef,
        *,
        target_contract_id: str,
        authority_id: str,
        authority_keyring: Mapping[str, bytes | str],
        observation_keyring: Mapping[str, bytes | str],
        verifier_id: str,
        verifier_keyring: Mapping[str, bytes | str],
        at,
        max_source_bytes: int = 4 * 1024 * 1024,
    ) -> ProviderTargetReceiptRetentionResult:
        """Authenticate, intent-record, publish, and bind one exact receipt."""

        if type(receipt) is not ProviderExecutableTargetVerificationReceipt:
            raise ProviderTargetReceiptRetentionBindingError(
                "receipt must be exact ProviderExecutableTargetVerificationReceipt"
            )
        try:
            projection = verify_provider_target_verification_receipt(
                receipt,
                target_authority,
                invocation_authority,
                identity_registry,
                execution,
                target_manifest,
                self.source_store,
                source_tree_ref,
                target_contract_id=target_contract_id,
                authority_id=authority_id,
                authority_keyring=authority_keyring,
                observation_keyring=observation_keyring,
                verifier_id=verifier_id,
                verifier_keyring=verifier_keyring,
                at=at,
                max_source_bytes=max_source_bytes,
            )
        except ProviderTargetVerificationError as exc:
            raise ProviderTargetReceiptRetentionBindingError(
                "verification receipt did not authenticate"
            ) from exc

        payload = _receipt_bytes(receipt)
        artifact = ArtifactRef.from_sha256(receipt.digest)
        expected_intent = _intent_payload(receipt, artifact)
        key = _effect_key(receipt.digest)
        # Authentication and all pure local validation precede schema or data writes.
        _validate_topology(self.primary_checkout, self.source_store, self.spine)
        self._install_single_receipt_invariant()
        existing = self._record_or_recover_intent(
            key=key,
            payload=expected_intent,
            trace_id=receipt.execution_id,
        )
        if existing.kind != _INTENT_KIND or existing.effect_key != key:
            raise ProviderTargetReceiptRetentionStateError(
                "retention intent identity is malformed"
            )
        if existing.trace_id != receipt.execution_id:
            raise ProviderTargetReceiptRetentionStateError(
                "retention intent trace does not bind execution"
            )
        if existing.payload != expected_intent:
            raise ProviderTargetReceiptRetentionReplay(
                "receipt identity was retained with different material"
            )
        if existing.state == STATE_COMPLETED:
            self._validate_completed(existing, receipt, artifact, payload)
            return ProviderTargetReceiptRetentionResult(
                receipt, artifact, projection, existing.id, False
            )
        if existing.state != STATE_INTENDED:
            raise ProviderTargetReceiptRetentionStateError(
                "retention intent has unsupported state"
            )

        try:
            published = self.source_store.put_bytes(payload)
        except (OSError, SourceTreeStoreError) as exc:
            raise ProviderTargetReceiptRetentionStateError(
                "receipt CAS publication is unresolved and requires replay"
            ) from exc
        if published != artifact:
            raise ProviderTargetReceiptRetentionStateError(
                "receipt CAS returned a foreign artifact identity"
            )

        completion_error: BaseException | None = None
        try:
            self.spine.mark_completed(
                existing.id,
                effect_id=artifact.sha256,
                result=_terminal_result(receipt, artifact),
            )
        except IntentAlreadyResolved:
            pass
        except sqlite3.DatabaseError as exc:
            completion_error = exc
        try:
            terminal = _read_intent(self.spine.path, key)
        except ProviderTargetReceiptRetentionStateError as exc:
            if completion_error is not None:
                raise ProviderTargetReceiptRetentionStateError(
                    "terminal persistence is unresolved and requires replay"
                ) from completion_error
            raise
        if terminal is None or terminal.state == STATE_INTENDED:
            if completion_error is not None:
                raise ProviderTargetReceiptRetentionStateError(
                    "terminal persistence is unresolved and requires replay"
                ) from completion_error
            raise ProviderTargetReceiptRetentionStateError(
                "terminal Event-Store transition was not retained"
            )
        self._validate_completed(terminal, receipt, artifact, payload)
        return ProviderTargetReceiptRetentionResult(
            receipt, artifact, projection, terminal.id, True
        )


__all__ = [
    "ProviderTargetReceiptLedger",
    "ProviderTargetReceiptRetentionBindingError",
    "ProviderTargetReceiptRetentionError",
    "ProviderTargetReceiptRetentionReplay",
    "ProviderTargetReceiptRetentionResult",
    "ProviderTargetReceiptRetentionStateError",
]

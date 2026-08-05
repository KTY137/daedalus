"""Read-only persisted-lease and topology admission for receipt retention.

This packet deliberately stops before the durable effect start and before the
receipt-retention write.  It replays the exact signed retention preflight,
authenticates the persisted non-runtime Effect Lease, and proves that the
Primary Checkout, canonical Event Store, receipt CAS, and Effect-Lease store
occupy disjoint concrete filesystem identities.

The result is an admission receipt, not execution authority.  ``not_started``
means a later canonical entrypoint may attempt ``begin_effect``.  A retained
``started`` or terminal state is reported without granting automatic replay,
re-execution, retention, completion, promotion, or Gate authority.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.effect_replay import (
    EffectExecutionReplaySnapshot,
    EffectReplayProjectionError,
    inspect_effect_execution,
)
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_target_receipt_ledger import (
    ProviderTargetReceiptLedger,
)
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_ENTRYPOINT,
    RETENTION_GUARD_CONTRACT,
)
from daedalus.runtimes.provider_target_receipt_retention_preflight import (
    ProviderTargetReceiptRetentionPreflightError,
    ProviderTargetReceiptRetentionPreflightReceipt,
    verify_provider_target_receipt_retention_preflight,
)
from daedalus.schemas import _identifier, _repo_path, _revision, _sha256
from daedalus.spine.effect_boundary import GuardDecision
from daedalus.spine.envelope import canonical_sha

RETENTION_ENTRYPOINT_TARGET = (
    "daedalus.runtimes.provider_target_receipt_retention_entrypoint:"
    "retain_provider_target_receipt"
)
_EXECUTION_STATES = frozenset(
    {"not_started", "started", "COMPLETED", "FAILED", "CANCELLED"}
)


class ProviderTargetReceiptRetentionAdmissionError(RuntimeError):
    """Base class for fail-closed retention admission refusal."""


class ProviderTargetReceiptRetentionAdmissionShapeError(
    ProviderTargetReceiptRetentionAdmissionError
):
    """A caller supplied a malformed or non-exact admission subject."""


class ProviderTargetReceiptRetentionAdmissionBindingError(
    ProviderTargetReceiptRetentionAdmissionError
):
    """Persisted authority, topology, preflight, or replay state disagrees."""


def _strict_path(value: Any, label: str) -> str:
    if type(value) is not str:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            f"{label} must be an exact string"
        )
    try:
        normalized = _repo_path(value, label)
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            f"{label} is malformed"
        ) from exc
    if normalized == "." or normalized != value:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            f"{label} must be canonical non-root repository-relative POSIX"
        )
    return normalized


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts:
        if part == path.anchor:
            continue
        current = current / part
        if current.is_symlink():
            return True
    return False


def _identity(path: Path, label: str, *, directory: bool) -> tuple[Path, int, int]:
    try:
        absolute = path.absolute()
        if _contains_symlink(absolute):
            raise ProviderTargetReceiptRetentionAdmissionBindingError(
                f"{label} path must not contain symlinks"
            )
        resolved = absolute.resolve(strict=True)
        info = resolved.stat()
    except ProviderTargetReceiptRetentionAdmissionError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            f"{label} cannot be resolved"
        ) from exc
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not expected:
        kind = "directory" if directory else "regular file"
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            f"{label} must be a real {kind}"
        )
    if not directory and info.st_nlink != 1:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            f"{label} must have one filesystem identity"
        )
    return resolved, int(info.st_dev), int(info.st_ino)


def _same_identity(
    left: tuple[Path, int, int],
    right: tuple[Path, int, int],
) -> bool:
    return left[1:] == right[1:]


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _sqlite_companions(path: Path) -> tuple[Path, ...]:
    return tuple(
        Path(f"{path}{suffix}")
        for suffix in ("-wal", "-shm", "-journal")
        if Path(f"{path}{suffix}").exists()
    )


def _topology(
    *,
    repository_root: Path,
    retention_root: Path,
    retention_ledger: ProviderTargetReceiptLedger,
    effect_store_path: Path,
    event_store_scope_path: str,
    receipt_cas_scope_path: str,
) -> tuple[Path, Path, Path, Path, Path]:
    primary = _identity(repository_root, "repository_root", directory=True)
    ledger_primary = _identity(
        Path(retention_ledger.primary_checkout),
        "retention ledger primary checkout",
        directory=True,
    )
    if not _same_identity(primary, ledger_primary):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention ledger is bound to a different Primary Checkout"
        )
    root = _identity(retention_root, "retention_root", directory=True)
    event = _identity(
        Path(retention_ledger.spine.path),
        "canonical Event Store",
        directory=False,
    )
    cas = _identity(
        Path(retention_ledger.source_store.root),
        "receipt CAS",
        directory=True,
    )
    effect = _identity(effect_store_path, "Effect-Lease store", directory=False)

    event_scope = _strict_path(event_store_scope_path, "event_store_scope_path")
    cas_scope = _strict_path(receipt_cas_scope_path, "receipt_cas_scope_path")
    expected_event = _identity(
        retention_root / Path(*event_scope.split("/")),
        "scoped canonical Event Store",
        directory=False,
    )
    expected_cas = _identity(
        retention_root / Path(*cas_scope.split("/")),
        "scoped receipt CAS",
        directory=True,
    )
    if not _same_identity(event, expected_event):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "event_store_scope_path does not bind the concrete Event Store"
        )
    if not _same_identity(cas, expected_cas):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "receipt_cas_scope_path does not bind the concrete receipt CAS"
        )

    protected = (primary[0], event[0], cas[0], effect[0])
    for index, left in enumerate(protected):
        for right in protected[index + 1 :]:
            if _overlap(left, right):
                raise ProviderTargetReceiptRetentionAdmissionBindingError(
                    "Primary Checkout and retention stores must be pairwise disjoint"
                )
    if _overlap(primary[0], root[0]):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention_root must be outside the Primary Checkout"
        )
    if not (event[0] in root[0].parents or root[0] in event[0].parents):
        # Event file must be under retention_root; a file cannot contain a root,
        # but the symmetric form keeps the intent explicit and race-independent.
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "canonical Event Store is outside retention_root"
        )
    if root[0] not in cas[0].parents and cas[0] != root[0]:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "receipt CAS is outside retention_root"
        )

    main_identities = {(row[1], row[2]) for row in (primary, event, cas, effect)}
    for label, store in (
        ("canonical Event Store", event[0]),
        ("Effect-Lease store", effect[0]),
    ):
        for companion in _sqlite_companions(store):
            companion_identity = _identity(
                companion,
                f"{label} companion",
                directory=False,
            )
            if (companion_identity[1], companion_identity[2]) in main_identities:
                raise ProviderTargetReceiptRetentionAdmissionBindingError(
                    f"{label} companion aliases a protected path"
                )
            if _overlap(primary[0], companion_identity[0]):
                raise ProviderTargetReceiptRetentionAdmissionBindingError(
                    f"{label} companion is inside the Primary Checkout"
                )

    return primary[0], root[0], event[0], cas[0], effect[0]


def _exact_guard(
    authorization: NonRuntimeEffectAuthorization,
    preflight: ProviderTargetReceiptRetentionPreflightReceipt,
) -> GuardDecision:
    expected = GuardDecision(
        contract=RETENTION_GUARD_CONTRACT,
        allowed=True,
        evidence=preflight.guard_evidence,
    )
    guards = authorization.guard_decisions
    if type(guards) is not tuple or len(guards) != 1 or type(guards[0]) is not GuardDecision:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention authorization must carry one exact guard decision"
        )
    if guards[0] != expected:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention authorization guard is detached from the signed preflight"
        )
    return expected


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionAdmissionReceipt:
    """Canonical non-executing admission receipt for one retention execution."""

    source_revision: str
    preflight_sha256: str
    provider_target_receipt_sha256: str
    retention_inventory_sha256: str
    retention_authority_sha256: str
    retention_execution_request_sha256: str
    retention_effect_lease_sha256: str
    retention_effect_lease_request_sha256: str
    retention_policy_decision_sha256: str
    guard_contract: str
    guard_evidence: str
    execution_state: str
    start_receipt_sha256: str | None
    terminal_receipt_sha256: str | None
    primary_checkout_path: str
    retention_root_path: str
    event_store_path: str
    receipt_cas_path: str
    effect_lease_store_path: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            for field in (
                "preflight_sha256",
                "provider_target_receipt_sha256",
                "retention_inventory_sha256",
                "retention_authority_sha256",
                "retention_execution_request_sha256",
                "retention_effect_lease_sha256",
                "retention_effect_lease_request_sha256",
                "retention_policy_decision_sha256",
            ):
                object.__setattr__(self, field, _sha256(getattr(self, field), field))
            for field in ("start_receipt_sha256", "terminal_receipt_sha256"):
                value = getattr(self, field)
                if value is not None:
                    object.__setattr__(self, field, _sha256(value, field))
            object.__setattr__(
                self,
                "execution_state",
                _identifier(self.execution_state, "execution_state")
                if self.execution_state == "not_started"
                else self.execution_state,
            )
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission receipt is malformed"
            ) from exc
        if self.execution_state not in _EXECUTION_STATES:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission execution_state is unknown"
            )
        if self.guard_contract != RETENTION_GUARD_CONTRACT:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission guard_contract is wrong"
            )
        if not self.guard_evidence:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission guard_evidence is empty"
            )
        if self.execution_state == "not_started":
            if self.start_receipt_sha256 is not None or self.terminal_receipt_sha256 is not None:
                raise ProviderTargetReceiptRetentionAdmissionShapeError(
                    "not_started admission cannot retain execution receipts"
                )
        elif self.execution_state == "started":
            if self.start_receipt_sha256 is None or self.terminal_receipt_sha256 is not None:
                raise ProviderTargetReceiptRetentionAdmissionShapeError(
                    "started admission must retain only the start receipt"
                )
        elif self.start_receipt_sha256 is None or self.terminal_receipt_sha256 is None:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "terminal admission must retain start and terminal receipts"
            )
        for field in (
            "primary_checkout_path",
            "retention_root_path",
            "event_store_path",
            "receipt_cas_path",
            "effect_lease_store_path",
        ):
            value = getattr(self, field)
            if type(value) is not str or not value:
                raise ProviderTargetReceiptRetentionAdmissionShapeError(
                    f"{field} must be a non-empty exact string"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-target-receipt-retention-admission/1",
            "source_revision": self.source_revision,
            "preflight_sha256": self.preflight_sha256,
            "provider_target_receipt_sha256": self.provider_target_receipt_sha256,
            "retention_inventory_sha256": self.retention_inventory_sha256,
            "retention_authority_sha256": self.retention_authority_sha256,
            "retention_execution_request_sha256": self.retention_execution_request_sha256,
            "retention_effect_lease_sha256": self.retention_effect_lease_sha256,
            "retention_effect_lease_request_sha256": self.retention_effect_lease_request_sha256,
            "retention_policy_decision_sha256": self.retention_policy_decision_sha256,
            "guard_contract": self.guard_contract,
            "guard_evidence": self.guard_evidence,
            "execution_state": self.execution_state,
            "start_receipt_sha256": self.start_receipt_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "primary_checkout_path": self.primary_checkout_path,
            "retention_root_path": self.retention_root_path,
            "event_store_path": self.event_store_path,
            "receipt_cas_path": self.receipt_cas_path,
            "effect_lease_store_path": self.effect_lease_store_path,
            "persisted_effect_lease_verified": True,
            "primary_checkout_disjointness_verified": True,
            "retention_effect_started": self.execution_state != "not_started",
            "retention_effect_terminal": self.execution_state
            in {"COMPLETED", "FAILED", "CANCELLED"},
            "retention_write_performed": False,
            "automatic_reexecution_allowed": False,
            "canonical_entrypoint_registered": False,
            "gate_transition_authorized": False,
            "closed": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderTargetReceiptRetentionAdmissionReceipt":
        fields = {
            "source_revision",
            "preflight_sha256",
            "provider_target_receipt_sha256",
            "retention_inventory_sha256",
            "retention_authority_sha256",
            "retention_execution_request_sha256",
            "retention_effect_lease_sha256",
            "retention_effect_lease_request_sha256",
            "retention_policy_decision_sha256",
            "guard_contract",
            "guard_evidence",
            "execution_state",
            "start_receipt_sha256",
            "terminal_receipt_sha256",
            "primary_checkout_path",
            "retention_root_path",
            "event_store_path",
            "receipt_cas_path",
            "effect_lease_store_path",
        }
        claims = {
            "persisted_effect_lease_verified",
            "primary_checkout_disjointness_verified",
            "retention_effect_started",
            "retention_effect_terminal",
            "retention_write_performed",
            "automatic_reexecution_allowed",
            "canonical_entrypoint_registered",
            "gate_transition_authorized",
            "closed",
        }
        if not isinstance(payload, Mapping) or set(payload) != {"schema", *fields, *claims}:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission receipt fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-target-receipt-retention-admission/1":
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission receipt schema is wrong"
            )
        state = payload["execution_state"]
        expected_started = state != "not_started"
        expected_terminal = state in {"COMPLETED", "FAILED", "CANCELLED"}
        expected_claims = {
            "persisted_effect_lease_verified": True,
            "primary_checkout_disjointness_verified": True,
            "retention_effect_started": expected_started,
            "retention_effect_terminal": expected_terminal,
            "retention_write_performed": False,
            "automatic_reexecution_allowed": False,
            "canonical_entrypoint_registered": False,
            "gate_transition_authorized": False,
            "closed": False,
        }
        for field, expected in expected_claims.items():
            if payload[field] is not expected:
                raise ProviderTargetReceiptRetentionAdmissionShapeError(
                    f"retention admission receipt contains unsupported claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderTargetReceiptRetentionAdmissionError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def verify_provider_target_receipt_retention_admission(
    repository_root: Path,
    retention_root: Path,
    repository_head_receipt,
    receipt,
    inventory,
    authority,
    execution: EffectExecutionRequest,
    authorization: NonRuntimeEffectAuthorization,
    retention_ledger: ProviderTargetReceiptLedger,
    *,
    expected_authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    event_store_scope_path: str,
    receipt_cas_scope_path: str,
    at,
) -> ProviderTargetReceiptRetentionAdmissionReceipt:
    """Verify one non-executing central-admission candidate.

    The signed preflight is replayed before any persisted lease or topology
    inspection.  The function never grants, starts, finishes, or revokes an
    Effect Lease and never invokes ``ProviderTargetReceiptLedger.retain``.
    """

    if type(repository_root) is not Path or type(retention_root) is not Path:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "repository_root and retention_root must be exact pathlib.Path"
        )
    if type(execution) is not EffectExecutionRequest:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "execution must be exact EffectExecutionRequest"
        )
    if type(authorization) is not NonRuntimeEffectAuthorization:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "authorization must be exact NonRuntimeEffectAuthorization"
        )
    if type(retention_ledger) is not ProviderTargetReceiptLedger:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "retention_ledger must be exact ProviderTargetReceiptLedger"
        )
    if authorization.lease.entrypoint_id != RETENTION_ENTRYPOINT:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "persisted Effect Lease names the wrong retention entrypoint"
        )
    if authorization.request.entrypoint_id != RETENTION_ENTRYPOINT:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "persisted Effect-Lease request names the wrong retention entrypoint"
        )

    try:
        preflight = verify_provider_target_receipt_retention_preflight(
            repository_root,
            repository_head_receipt,
            receipt,
            inventory,
            authority,
            execution,
            authorization.lease,
            expected_authority_id=expected_authority_id,
            authority_keyring=authority_keyring,
            event_store_scope_path=event_store_scope_path,
            receipt_cas_scope_path=receipt_cas_scope_path,
            at=at,
        )
    except ProviderTargetReceiptRetentionPreflightError as exc:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention preflight did not reverify"
        ) from exc
    if type(preflight) is not ProviderTargetReceiptRetentionPreflightReceipt:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention preflight returned a non-exact receipt"
        )
    if (
        preflight.retention_execution_request_sha256 != execution.digest
        or preflight.retention_effect_lease_sha256 != authorization.lease.digest
        or preflight.provider_target_receipt_sha256 != receipt.digest
        or preflight.retention_inventory_sha256 != inventory.digest
        or preflight.retention_authority_sha256 != authority.digest
    ):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention preflight is detached from admission subjects"
        )
    guard = _exact_guard(authorization, preflight)

    primary, root, event, cas, effect_store = _topology(
        repository_root=repository_root,
        retention_root=retention_root,
        retention_ledger=retention_ledger,
        effect_store_path=Path(authorization.effect_ledger.path),
        event_store_scope_path=event_store_scope_path,
        receipt_cas_scope_path=receipt_cas_scope_path,
    )

    try:
        replay = inspect_effect_execution(authorization, execution)
    except EffectReplayProjectionError as exc:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "persisted retention Effect Lease or execution did not authenticate"
        ) from exc
    if replay is not None and type(replay) is not EffectExecutionReplaySnapshot:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "effect replay returned a non-exact snapshot"
        )

    state = "not_started"
    start_digest = None
    terminal_digest = None
    if replay is not None:
        state = "started" if replay.state == "STARTED" else replay.state
        start_digest = replay.start_receipt.receipt_sha256
        terminal_digest = (
            None
            if replay.terminal_receipt is None
            else replay.terminal_receipt.receipt_sha256
        )

    result = ProviderTargetReceiptRetentionAdmissionReceipt(
        source_revision=preflight.source_revision,
        preflight_sha256=preflight.digest,
        provider_target_receipt_sha256=preflight.provider_target_receipt_sha256,
        retention_inventory_sha256=preflight.retention_inventory_sha256,
        retention_authority_sha256=preflight.retention_authority_sha256,
        retention_execution_request_sha256=execution.digest,
        retention_effect_lease_sha256=authorization.lease.digest,
        retention_effect_lease_request_sha256=authorization.request.digest,
        retention_policy_decision_sha256=authorization.policy_decision.digest,
        guard_contract=guard.contract,
        guard_evidence=guard.evidence,
        execution_state=state,
        start_receipt_sha256=start_digest,
        terminal_receipt_sha256=terminal_digest,
        primary_checkout_path=os.fspath(primary),
        retention_root_path=os.fspath(root),
        event_store_path=os.fspath(event),
        receipt_cas_path=os.fspath(cas),
        effect_lease_store_path=os.fspath(effect_store),
    )

    # Immutable subject rechecks close caller-side mutation between preflight,
    # topology inspection, replay inspection, and receipt construction.
    if (
        result.retention_execution_request_sha256 != execution.digest
        or result.retention_effect_lease_sha256 != authorization.lease.digest
        or result.retention_effect_lease_request_sha256 != authorization.request.digest
        or result.retention_policy_decision_sha256 != authorization.policy_decision.digest
        or result.preflight_sha256 != preflight.digest
    ):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention admission subject changed during verification"
        )
    return result


__all__ = [
    "RETENTION_ENTRYPOINT_TARGET",
    "ProviderTargetReceiptRetentionAdmissionBindingError",
    "ProviderTargetReceiptRetentionAdmissionError",
    "ProviderTargetReceiptRetentionAdmissionReceipt",
    "ProviderTargetReceiptRetentionAdmissionShapeError",
    "verify_provider_target_receipt_retention_admission",
]

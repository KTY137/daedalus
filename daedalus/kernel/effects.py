"""Persisted, scope-bounded Effect Leases for the Gate-0 trust kernel.

The lease layer is deliberately inert with respect to real effects.  It
persists authorization before an effect may start, validates a request against
one exact policy decision and one exact entrypoint-registry revision, and
returns an execution flag that prevents replay from causing a second effect.
Legacy callers are migrated in later Work Packets; this module refuses to issue
leases for rows that are not already marked ``CENTRAL``.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

if TYPE_CHECKING:
    from daedalus.kernel.reconciliation import (
        EffectReconciliationDecision,
        EffectReconciliationResult,
    )

from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.schemas import (
    ContractProvenance,
    EffectScope,
    PolicyDecision,
    _egress_endpoint,
    _identifier,
    _repo_path,
    _sha256,
    _sorted_strings,
)
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    Effect,
    EntrypointSpec,
    GuardDecision,
    Wiring,
    begin_effect,
    registry_sha256,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_MAX_LEASE_TTL = timedelta(hours=24)
_TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_START_RECEIPT_HMAC_DOMAIN = b"daedalus.effect-start-receipt.v1\x00"
_COMPLETION_CAPABILITY_DOMAIN = b"daedalus.effect-completion-capability.v1\x00"
_EXECUTION_CLAIM_HMAC_DOMAIN = b"daedalus.effect-execution-claim.v1\x00"
_CLAIM_COMPLETION_CAPABILITY_DOMAIN = (
    b"daedalus.effect-claim-completion-capability.v1\x00"
)
_TERMINAL_AUTHORIZATION_HMAC_DOMAIN = (
    b"daedalus.effect-terminal-authorization.v1\x00"
)
_CLAIM_TERMINAL_AUTHORIZATION_HMAC_DOMAIN = (
    b"daedalus.effect-claim-terminal-authorization.v1\x00"
)
_PUBLICATION_COMMIT_HMAC_DOMAIN = b"daedalus.effect-publication-commit.v1\x00"
_PUBLICATION_CAPABILITY_DOMAIN = (
    b"daedalus.effect-publication-commit-capability.v1\x00"
)
_PUBLICATION_OUTCOME_AUDIT_KEY_DOMAIN = (
    b"daedalus.effect-publication-outcome-audit-key.v1\x00"
)
_PUBLICATION_OUTCOME_HMAC_DOMAIN = (
    b"daedalus.effect-publication-outcome.v1\x00"
)
_FINALIZATION_CAPABILITY_DOMAIN = (
    b"daedalus.effect-publication-finalization-capability.v1\x00"
)
_FINALIZATION_AUTHORIZATION_HMAC_DOMAIN = (
    b"daedalus.effect-publication-finalization-authorization.v1\x00"
)
_COMPLETION_CAPABILITY_MINT_TOKEN = object()
_CLAIM_COMPLETION_CAPABILITY_MINT_TOKEN = object()
_CLAIM_PROMOTION_TOKEN = object()
_PUBLICATION_CAPABILITY_MINT_TOKEN = object()
_PUBLICATION_SESSION_MINT_TOKEN = object()
_FINALIZATION_CAPABILITY_MINT_TOKEN = object()


class EffectLeaseError(RuntimeError):
    """Base class for fail-closed lease failures."""


class EffectLeaseSignatureError(EffectLeaseError):
    pass


class EffectLeaseExpired(EffectLeaseError):
    pass


class EffectLeaseBindingMismatch(EffectLeaseError):
    pass


class EffectLeaseScopeError(EffectLeaseError):
    pass


class EffectLeaseReplay(EffectLeaseError):
    pass


class EffectLeaseStateError(EffectLeaseError):
    pass


class EffectReconciliationRequired(EffectLeaseStateError):
    """A started external effect could not publish its terminal receipt.

    The durable row is intentionally retained as indeterminate.  Generic
    operator reconciliation may close only an unclaimed ``STARTED`` row;
    ``EXECUTING`` and ``COMMITTING`` require a future orphan fence plus stopped
    kill-switch proof before any terminal decision is safe.
    """

    def __init__(
        self,
        *,
        pending_terminal_receipt: "EffectTerminalReceipt",
        execution_request_sha256: str,
        phase: str,
        persistence_error_sha256: str,
    ) -> None:
        if not isinstance(pending_terminal_receipt, EffectTerminalReceipt):
            raise TypeError(
                "pending_terminal_receipt must be an EffectTerminalReceipt"
            )
        self.pending_terminal_receipt = pending_terminal_receipt
        self.execution_id = pending_terminal_receipt.execution_id
        self.start_receipt_sha256 = pending_terminal_receipt.start_receipt_sha256
        self.execution_request_sha256 = _sha256(
            execution_request_sha256, "execution_request_sha256"
        )
        self.persistence_error_sha256 = _sha256(
            persistence_error_sha256, "persistence_error_sha256"
        )
        self.phase = _identifier(phase, "reconciliation phase")
        super().__init__(
            "effect execution requires reconciliation after terminal "
            f"persistence failed during {self.phase}: {self.execution_id} "
            f"(pending terminal {pending_terminal_receipt.receipt_sha256})"
        )

    def to_dict(self) -> dict[str, object]:
        """Return the complete frozen recovery packet for durable handoff."""

        return {
            "execution_id": self.execution_id,
            "execution_request_sha256": self.execution_request_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "pending_terminal_receipt": self.pending_terminal_receipt.to_dict(),
            "phase": self.phase,
            "persistence_error_sha256": self.persistence_error_sha256,
        }


class EffectLeaseConcurrencyError(EffectLeaseError):
    pass


@dataclass(frozen=True)
class EffectExecutionRequest:
    """The exact narrowed scope of one attempted external effect."""

    execution_id: str
    idempotency_key: str
    requested_effects: tuple[str, ...]
    writable_paths: tuple[str, ...] = ()
    egress_endpoints: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    secret_refs: tuple[str, ...] = ()
    max_cost_microusd: int = 0
    kill_switch_ref: str = ""
    kill_switch_generation: int = 0
    execution_plan_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_id", _identifier(self.execution_id, "execution_id"))
        object.__setattr__(
            self, "idempotency_key", _identifier(self.idempotency_key, "idempotency_key")
        )
        object.__setattr__(
            self,
            "requested_effects",
            _sorted_strings(self.requested_effects, "requested_effects", identifiers=True),
        )
        if not self.requested_effects:
            raise ValueError("execution request must name at least one effect")
        object.__setattr__(
            self,
            "writable_paths",
            _sorted_strings(self.writable_paths, "writable_paths", paths=True),
        )
        if isinstance(self.egress_endpoints, (str, bytes)):
            raise ValueError("egress_endpoints must be a sequence")
        endpoints = tuple(
            sorted(
                _egress_endpoint(value, f"egress_endpoints[{index}]")
                for index, value in enumerate(self.egress_endpoints)
            )
        )
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("egress_endpoints must not contain duplicates")
        object.__setattr__(self, "egress_endpoints", endpoints)
        object.__setattr__(
            self, "tools", _sorted_strings(self.tools, "tools", identifiers=True)
        )
        object.__setattr__(
            self,
            "secret_refs",
            _sorted_strings(self.secret_refs, "secret_refs", identifiers=True),
        )
        if isinstance(self.max_cost_microusd, bool) or not isinstance(
            self.max_cost_microusd, int
        ) or self.max_cost_microusd < 0:
            raise ValueError("max_cost_microusd must be a non-negative integer")
        if self.kill_switch_ref:
            object.__setattr__(
                self,
                "kill_switch_ref",
                _identifier(self.kill_switch_ref, "kill_switch_ref"),
            )
        if isinstance(self.kill_switch_generation, bool) or not isinstance(
            self.kill_switch_generation, int
        ) or self.kill_switch_generation < 0:
            raise ValueError("kill_switch_generation must be a non-negative integer")
        if self.execution_plan_sha256 is not None:
            object.__setattr__(
                self,
                "execution_plan_sha256",
                _sha256(self.execution_plan_sha256, "execution_plan_sha256"),
            )
        # Validate names against the canonical Effect enum without changing
        # their deterministic sorted representation.
        for value in self.requested_effects:
            try:
                Effect(value)
            except ValueError as exc:
                raise ValueError(f"unknown requested effect {value!r}") from exc

    def to_dict(self) -> dict[str, object]:
        body = dataclasses.asdict(self)
        if self.execution_plan_sha256 is None:
            body.pop("execution_plan_sha256")
        return body

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class LeasedEffectStartReceipt:
    lease_sha256: str
    issuer_key_id: str
    execution_id: str
    idempotency_key: str
    execution_request_sha256: str
    boundary_receipt_sha256: str
    completion_capability_sha256: str
    started_at: str
    signature_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        for name in ("issuer_key_id", "execution_id", "idempotency_key"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "lease_sha256",
            "execution_request_sha256",
            "boundary_receipt_sha256",
            "completion_capability_sha256",
            "signature_sha256",
            "receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        canonical_started = _timestamp(_parse_utc(self.started_at, "started_at"))
        if canonical_started != self.started_at:
            raise EffectLeaseBindingMismatch(
                "start receipt timestamp is not canonical UTC"
            )
        if canonical_sha(self.authenticated_dict()) != self.receipt_sha256:
            raise EffectLeaseBindingMismatch("start receipt digest mismatch")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    def signing_dict(self) -> dict[str, str]:
        body = self.to_dict()
        body.pop("receipt_sha256")
        body.pop("signature_sha256")
        return body

    def authenticated_dict(self) -> dict[str, str]:
        body = self.to_dict()
        body.pop("receipt_sha256")
        return body


@dataclass(frozen=True)
class EffectExecutionClaimReceipt:
    """Authenticated durable transition from ``STARTED`` to ``EXECUTING``.

    The receipt commits a fresh live-only completion capability without storing
    its secret.  Losing that capability leaves this receipt as evidence for the
    existing operator reconciliation path; it never permits another execution.
    """

    lease_sha256: str
    issuer_key_id: str
    execution_id: str
    execution_request_sha256: str
    start_receipt_sha256: str
    claim_capability_sha256: str
    claimed_at: str
    signature_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        for name in ("issuer_key_id", "execution_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "lease_sha256",
            "execution_request_sha256",
            "start_receipt_sha256",
            "claim_capability_sha256",
            "signature_sha256",
            "receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        canonical_claimed = _timestamp(_parse_utc(self.claimed_at, "claimed_at"))
        if canonical_claimed != self.claimed_at:
            raise EffectLeaseBindingMismatch(
                "execution claim timestamp is not canonical UTC"
            )
        if canonical_sha(self.authenticated_dict()) != self.receipt_sha256:
            raise EffectLeaseBindingMismatch("execution claim digest mismatch")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    def signing_dict(self) -> dict[str, str]:
        body = self.to_dict()
        body.pop("receipt_sha256")
        body.pop("signature_sha256")
        return body

    def authenticated_dict(self) -> dict[str, str]:
        body = self.to_dict()
        body.pop("receipt_sha256")
        return body


@dataclass(frozen=True)
class EffectPublicationCommitReceipt:
    """Issuer-authenticated durable ``EXECUTING -> COMMITTING`` receipt."""

    lease_sha256: str
    issuer_key_id: str
    execution_id: str
    execution_request_sha256: str
    start_receipt_sha256: str
    claim_receipt_sha256: str
    effect_commitment_sha256: str
    publication_capability_sha256: str
    committed_at: str
    signature_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        for name in ("issuer_key_id", "execution_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "lease_sha256",
            "execution_request_sha256",
            "start_receipt_sha256",
            "claim_receipt_sha256",
            "effect_commitment_sha256",
            "publication_capability_sha256",
            "signature_sha256",
            "receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        canonical_committed = _timestamp(
            _parse_utc(self.committed_at, "committed_at")
        )
        if canonical_committed != self.committed_at:
            raise EffectLeaseBindingMismatch(
                "publication commit timestamp is not canonical UTC"
            )
        if canonical_sha(self.authenticated_dict()) != self.receipt_sha256:
            raise EffectLeaseBindingMismatch("publication commit digest mismatch")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    def signing_dict(self) -> dict[str, str]:
        body = self.to_dict()
        body.pop("receipt_sha256")
        body.pop("signature_sha256")
        return body

    def authenticated_dict(self) -> dict[str, str]:
        body = self.to_dict()
        body.pop("receipt_sha256")
        return body


@dataclass(frozen=True)
class EffectPublicationOutcomeReceipt:
    """Live-capability evidence of one explicitly successful publication."""

    lease_sha256: str
    execution_id: str
    execution_request_sha256: str
    start_receipt_sha256: str
    claim_receipt_sha256: str
    publication_commit_receipt_sha256: str
    effect_commitment_sha256: str
    finalization_capability_sha256: str
    published_at: str
    signature_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "execution_id", _identifier(self.execution_id, "execution_id")
        )
        for name in (
            "lease_sha256",
            "execution_request_sha256",
            "start_receipt_sha256",
            "claim_receipt_sha256",
            "publication_commit_receipt_sha256",
            "effect_commitment_sha256",
            "finalization_capability_sha256",
            "signature_sha256",
            "receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        canonical_published = _timestamp(
            _parse_utc(self.published_at, "published_at")
        )
        if canonical_published != self.published_at:
            raise EffectLeaseBindingMismatch(
                "publication outcome timestamp is not canonical UTC"
            )
        if canonical_sha(self.authenticated_dict()) != self.receipt_sha256:
            raise EffectLeaseBindingMismatch("publication outcome digest mismatch")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    def signing_dict(self) -> dict[str, str]:
        body = self.to_dict()
        body.pop("receipt_sha256")
        body.pop("signature_sha256")
        return body

    def authenticated_dict(self) -> dict[str, str]:
        body = self.to_dict()
        body.pop("receipt_sha256")
        return body


@dataclass(frozen=True)
class EffectTerminalReceipt:
    lease_sha256: str
    execution_id: str
    start_receipt_sha256: str
    outcome: str
    output_digests: tuple[str, ...]
    detail_sha256: str | None
    finished_at: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "execution_id", _identifier(self.execution_id, "execution_id")
        )
        for name in (
            "lease_sha256",
            "start_receipt_sha256",
            "receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        normalized_outcome = str(self.outcome).upper()
        if normalized_outcome not in _TERMINAL_STATES or normalized_outcome != self.outcome:
            raise EffectLeaseBindingMismatch(
                "terminal receipt outcome must be canonical and terminal"
            )
        if isinstance(self.output_digests, (str, bytes)):
            raise EffectLeaseBindingMismatch(
                "terminal output_digests must be a sequence"
            )
        outputs = tuple(
            sorted({_sha256(value, "output_digest") for value in self.output_digests})
        )
        if tuple(self.output_digests) != outputs:
            raise EffectLeaseBindingMismatch(
                "terminal output_digests must be sorted and unique"
            )
        object.__setattr__(self, "output_digests", outputs)
        if self.detail_sha256 is not None:
            object.__setattr__(
                self,
                "detail_sha256",
                _sha256(self.detail_sha256, "detail_sha256"),
            )
        canonical_finished = _timestamp(
            _parse_utc(self.finished_at, "finished_at")
        )
        if canonical_finished != self.finished_at:
            raise EffectLeaseBindingMismatch(
                "terminal receipt timestamp is not canonical UTC"
            )
        body = self.to_dict()
        claimed = body.pop("receipt_sha256")
        if canonical_sha(body) != claimed:
            raise EffectLeaseBindingMismatch("terminal receipt digest mismatch")

    def to_dict(self) -> dict[str, object]:
        return {
            **dataclasses.asdict(self),
            "output_digests": list(self.output_digests),
        }


@dataclass(frozen=True, slots=True, repr=False)
class TerminalAuthorization:
    """Opaque live authority for one exact terminal receipt.

    The random capability secret is deliberately absent from every receipt,
    exception packet and replay result.  Possession of this object is useful
    only alongside the authenticated historical grant and start chain.
    """

    _lease_sha256: str
    _execution_id: str
    _start_receipt_sha256: str
    _terminal_receipt_sha256: str
    _signature_sha256: str
    _secret: bytes = field(repr=False, compare=False)

    @classmethod
    def _issue(
        cls,
        *,
        lease_sha256: str,
        execution_id: str,
        start_receipt_sha256: str,
        terminal_receipt_sha256: str,
        secret: bytes,
    ) -> "TerminalAuthorization":
        payload = {
            "lease_sha256": lease_sha256,
            "execution_id": execution_id,
            "start_receipt_sha256": start_receipt_sha256,
            "terminal_receipt_sha256": terminal_receipt_sha256,
        }
        return cls(
            _lease_sha256=lease_sha256,
            _execution_id=execution_id,
            _start_receipt_sha256=start_receipt_sha256,
            _terminal_receipt_sha256=terminal_receipt_sha256,
            _signature_sha256=_terminal_authorization_signature(
                payload, secret
            ),
            _secret=bytes(secret),
        )

    def __repr__(self) -> str:
        return "TerminalAuthorization(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class ClaimTerminalAuthorization:
    """Opaque authority from one exact persisted execution claim."""

    _lease_sha256: str
    _execution_id: str
    _start_receipt_sha256: str
    _claim_receipt_sha256: str
    _terminal_receipt_sha256: str
    _signature_sha256: str
    _secret: bytes = field(repr=False, compare=False)

    @classmethod
    def _issue(
        cls,
        *,
        lease_sha256: str,
        execution_id: str,
        start_receipt_sha256: str,
        claim_receipt_sha256: str,
        terminal_receipt_sha256: str,
        secret: bytes,
    ) -> "ClaimTerminalAuthorization":
        payload = {
            "lease_sha256": lease_sha256,
            "execution_id": execution_id,
            "start_receipt_sha256": start_receipt_sha256,
            "claim_receipt_sha256": claim_receipt_sha256,
            "terminal_receipt_sha256": terminal_receipt_sha256,
        }
        return cls(
            _lease_sha256=lease_sha256,
            _execution_id=execution_id,
            _start_receipt_sha256=start_receipt_sha256,
            _claim_receipt_sha256=claim_receipt_sha256,
            _terminal_receipt_sha256=terminal_receipt_sha256,
            _signature_sha256=_claim_terminal_authorization_signature(
                payload, secret
            ),
            _secret=bytes(secret),
        )

    def __repr__(self) -> str:
        return "ClaimTerminalAuthorization(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class PublicationFinalizationAuthorization:
    """Opaque terminal authority minted only after clean publication exit."""

    _lease_sha256: str
    _execution_id: str
    _start_receipt_sha256: str
    _claim_receipt_sha256: str
    _publication_commit_receipt_sha256: str
    _publication_outcome_receipt_sha256: str
    _terminal_receipt_sha256: str
    _pid: int
    _thread_id: int
    _signature_sha256: str
    _secret: bytes = field(repr=False, compare=False)
    _publication_secret: bytes = field(repr=False, compare=False)
    _outcome_audit_key: bytes = field(repr=False, compare=False)

    @classmethod
    def _issue(
        cls,
        *,
        lease_sha256: str,
        execution_id: str,
        start_receipt_sha256: str,
        claim_receipt_sha256: str,
        publication_commit_receipt_sha256: str,
        publication_outcome_receipt_sha256: str,
        terminal_receipt_sha256: str,
        secret: bytes,
        publication_secret: bytes,
        outcome_audit_key: bytes,
    ) -> "PublicationFinalizationAuthorization":
        payload = {
            "lease_sha256": lease_sha256,
            "execution_id": execution_id,
            "start_receipt_sha256": start_receipt_sha256,
            "claim_receipt_sha256": claim_receipt_sha256,
            "publication_commit_receipt_sha256": (
                publication_commit_receipt_sha256
            ),
            "publication_outcome_receipt_sha256": (
                publication_outcome_receipt_sha256
            ),
            "terminal_receipt_sha256": terminal_receipt_sha256,
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
        }
        return cls(
            _lease_sha256=lease_sha256,
            _execution_id=execution_id,
            _start_receipt_sha256=start_receipt_sha256,
            _claim_receipt_sha256=claim_receipt_sha256,
            _publication_commit_receipt_sha256=(
                publication_commit_receipt_sha256
            ),
            _publication_outcome_receipt_sha256=(
                publication_outcome_receipt_sha256
            ),
            _terminal_receipt_sha256=terminal_receipt_sha256,
            _pid=os.getpid(),
            _thread_id=threading.get_ident(),
            _signature_sha256=_publication_finalization_authorization_signature(
                payload, secret
            ),
            _secret=bytes(secret),
            _publication_secret=bytes(publication_secret),
            _outcome_audit_key=bytes(outcome_audit_key),
        )

    def __repr__(self) -> str:
        return "PublicationFinalizationAuthorization(<redacted>)"


class CompletionCapability:
    """Live-only one-shot capability committed by a signed start receipt.

    The first call to :meth:`authorize` permanently binds this in-memory
    capability to one terminal receipt.  Re-authorizing the byte-identical
    receipt is allowed so a transient SQLite failure can be retried without
    minting a new outcome.  A different terminal receipt is always refused.
    """

    __slots__ = (
        "_lease_sha256",
        "_execution_id",
        "_start_receipt_sha256",
        "_commitment_sha256",
        "_secret",
        "_bound_terminal_sha256",
        "_lock",
    )

    def __init__(
        self,
        *,
        start_receipt: LeasedEffectStartReceipt,
        secret: bytes,
        _mint_token: object | None = None,
    ) -> None:
        if _mint_token is not _COMPLETION_CAPABILITY_MINT_TOKEN:
            raise EffectLeaseStateError(
                "completion capabilities may only be minted by a persisted ledger start"
            )
        secret_value = bytes(secret)
        commitment = _completion_capability_sha256(secret_value)
        if not hmac.compare_digest(
            commitment, start_receipt.completion_capability_sha256
        ):
            raise EffectLeaseBindingMismatch(
                "completion capability does not match signed start receipt"
            )
        object.__setattr__(self, "_lease_sha256", start_receipt.lease_sha256)
        object.__setattr__(self, "_execution_id", start_receipt.execution_id)
        object.__setattr__(
            self, "_start_receipt_sha256", start_receipt.receipt_sha256
        )
        object.__setattr__(self, "_commitment_sha256", commitment)
        object.__setattr__(self, "_secret", secret_value)
        object.__setattr__(self, "_bound_terminal_sha256", None)
        object.__setattr__(self, "_lock", threading.Lock())

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("CompletionCapability is immutable")

    def __repr__(self) -> str:
        return "CompletionCapability(<redacted>)"

    def verify_start_receipt(self, receipt: LeasedEffectStartReceipt) -> None:
        """Verify this live-only capability is bound to one exact start receipt."""

        if not isinstance(receipt, LeasedEffectStartReceipt):
            raise TypeError("receipt must be a LeasedEffectStartReceipt")
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("lease_sha256", self._lease_sha256, receipt.lease_sha256),
                ("execution_id", self._execution_id, receipt.execution_id),
                (
                    "start_receipt_sha256",
                    self._start_receipt_sha256,
                    receipt.receipt_sha256,
                ),
                (
                    "completion_capability_sha256",
                    self._commitment_sha256,
                    receipt.completion_capability_sha256,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "completion capability start binding mismatch: "
                + ", ".join(mismatches)
            )
        expected_commitment = _completion_capability_sha256(self._secret)
        if not hmac.compare_digest(expected_commitment, self._commitment_sha256):
            raise EffectLeaseSignatureError(
                "completion capability secret does not match its commitment"
            )

    def authorize(
        self, receipt: EffectTerminalReceipt
    ) -> TerminalAuthorization:
        if not isinstance(receipt, EffectTerminalReceipt):
            raise TypeError("receipt must be an EffectTerminalReceipt")
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("lease_sha256", receipt.lease_sha256, self._lease_sha256),
                ("execution_id", receipt.execution_id, self._execution_id),
                (
                    "start_receipt_sha256",
                    receipt.start_receipt_sha256,
                    self._start_receipt_sha256,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "completion capability terminal binding mismatch: "
                + ", ".join(mismatches)
            )
        with self._lock:
            if self._bound_terminal_sha256 is None:
                object.__setattr__(
                    self, "_bound_terminal_sha256", receipt.receipt_sha256
                )
            elif not hmac.compare_digest(
                self._bound_terminal_sha256, receipt.receipt_sha256
            ):
                raise EffectLeaseStateError(
                    "completion capability is already bound to another terminal receipt"
                )
        return TerminalAuthorization._issue(
            lease_sha256=self._lease_sha256,
            execution_id=self._execution_id,
            start_receipt_sha256=self._start_receipt_sha256,
            terminal_receipt_sha256=receipt.receipt_sha256,
            secret=self._secret,
        )


class ClaimCompletionCapability:
    """Live-only terminal authority minted by a durable execution claim."""

    __slots__ = (
        "_lease_sha256",
        "_execution_id",
        "_start_receipt_sha256",
        "_claim_receipt_sha256",
        "_commitment_sha256",
        "_secret",
        "_bound_terminal_sha256",
        "_lifecycle_state",
        "_promoted_commit_sha256",
        "_mint_pid",
        "_lock",
    )

    def __init__(
        self,
        *,
        start_receipt: LeasedEffectStartReceipt,
        claim_receipt: EffectExecutionClaimReceipt,
        secret: bytes,
        _mint_token: object | None = None,
    ) -> None:
        if _mint_token is not _CLAIM_COMPLETION_CAPABILITY_MINT_TOKEN:
            raise EffectLeaseStateError(
                "claim completion capabilities may only be minted by a "
                "persisted execution transition"
            )
        secret_value = bytes(secret)
        commitment = _claim_completion_capability_sha256(secret_value)
        mismatches = sorted(
            name
            for name, actual, expected in (
                (
                    "lease_sha256",
                    claim_receipt.lease_sha256,
                    start_receipt.lease_sha256,
                ),
                (
                    "execution_id",
                    claim_receipt.execution_id,
                    start_receipt.execution_id,
                ),
                (
                    "start_receipt_sha256",
                    claim_receipt.start_receipt_sha256,
                    start_receipt.receipt_sha256,
                ),
                (
                    "claim_capability_sha256",
                    claim_receipt.claim_capability_sha256,
                    commitment,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "claim completion capability binding mismatch: "
                + ", ".join(mismatches)
            )
        object.__setattr__(self, "_lease_sha256", claim_receipt.lease_sha256)
        object.__setattr__(self, "_execution_id", claim_receipt.execution_id)
        object.__setattr__(
            self, "_start_receipt_sha256", start_receipt.receipt_sha256
        )
        object.__setattr__(
            self, "_claim_receipt_sha256", claim_receipt.receipt_sha256
        )
        object.__setattr__(self, "_commitment_sha256", commitment)
        object.__setattr__(self, "_secret", secret_value)
        object.__setattr__(self, "_bound_terminal_sha256", None)
        object.__setattr__(self, "_lifecycle_state", "LIVE")
        object.__setattr__(self, "_promoted_commit_sha256", None)
        object.__setattr__(self, "_mint_pid", os.getpid())
        object.__setattr__(self, "_lock", threading.Lock())

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ClaimCompletionCapability is immutable")

    def __repr__(self) -> str:
        return "ClaimCompletionCapability(<redacted>)"

    def verify_claim_receipt(
        self,
        start_receipt: LeasedEffectStartReceipt,
        claim_receipt: EffectExecutionClaimReceipt,
    ) -> None:
        if not isinstance(start_receipt, LeasedEffectStartReceipt):
            raise TypeError("start_receipt must be a LeasedEffectStartReceipt")
        if not isinstance(claim_receipt, EffectExecutionClaimReceipt):
            raise TypeError("claim_receipt must be an EffectExecutionClaimReceipt")
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("lease_sha256", self._lease_sha256, claim_receipt.lease_sha256),
                ("execution_id", self._execution_id, claim_receipt.execution_id),
                (
                    "start_receipt_sha256",
                    self._start_receipt_sha256,
                    start_receipt.receipt_sha256,
                ),
                (
                    "claim_start_receipt_sha256",
                    claim_receipt.start_receipt_sha256,
                    start_receipt.receipt_sha256,
                ),
                (
                    "claim_receipt_sha256",
                    self._claim_receipt_sha256,
                    claim_receipt.receipt_sha256,
                ),
                (
                    "claim_capability_sha256",
                    self._commitment_sha256,
                    claim_receipt.claim_capability_sha256,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "claim completion capability receipt mismatch: "
                + ", ".join(mismatches)
            )
        expected_commitment = _claim_completion_capability_sha256(self._secret)
        if not hmac.compare_digest(expected_commitment, self._commitment_sha256):
            raise EffectLeaseSignatureError(
                "claim completion capability secret does not match its commitment"
            )
        with self._lock:
            if os.getpid() != self._mint_pid:
                raise EffectLeaseStateError(
                    "claim completion capability cannot cross a process fork"
                )
            if self._lifecycle_state != "LIVE":
                raise EffectLeaseStateError(
                    "claim completion capability is being promoted or was "
                    "irreversibly promoted"
                )

    def authorize(
        self, receipt: EffectTerminalReceipt
    ) -> ClaimTerminalAuthorization:
        if not isinstance(receipt, EffectTerminalReceipt):
            raise TypeError("receipt must be an EffectTerminalReceipt")
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("lease_sha256", receipt.lease_sha256, self._lease_sha256),
                ("execution_id", receipt.execution_id, self._execution_id),
                (
                    "start_receipt_sha256",
                    receipt.start_receipt_sha256,
                    self._start_receipt_sha256,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "claim completion terminal binding mismatch: "
                + ", ".join(mismatches)
            )
        with self._lock:
            if os.getpid() != self._mint_pid:
                raise EffectLeaseStateError(
                    "claim completion capability cannot cross a process fork"
                )
            if self._lifecycle_state != "LIVE":
                raise EffectLeaseStateError(
                    "claim completion capability cannot terminalize after "
                    "publication promotion"
                )
            if self._bound_terminal_sha256 is None:
                object.__setattr__(
                    self, "_bound_terminal_sha256", receipt.receipt_sha256
                )
            elif not hmac.compare_digest(
                self._bound_terminal_sha256, receipt.receipt_sha256
            ):
                raise EffectLeaseStateError(
                    "claim completion capability is already bound to another "
                    "terminal receipt"
                )
        return ClaimTerminalAuthorization._issue(
            lease_sha256=self._lease_sha256,
            execution_id=self._execution_id,
            start_receipt_sha256=self._start_receipt_sha256,
            claim_receipt_sha256=self._claim_receipt_sha256,
            terminal_receipt_sha256=receipt.receipt_sha256,
            secret=self._secret,
        )

    def _begin_publication_promotion(self, *, _token: object) -> None:
        if _token is not _CLAIM_PROMOTION_TOKEN:
            raise EffectLeaseStateError(
                "claim promotion is reserved for the canonical ledger"
            )
        with self._lock:
            if os.getpid() != self._mint_pid:
                raise EffectLeaseStateError(
                    "claim completion capability cannot cross a process fork"
                )
            if self._lifecycle_state != "LIVE":
                raise EffectLeaseStateError(
                    "claim completion capability is not promotable"
                )
            if self._bound_terminal_sha256 is not None:
                raise EffectLeaseStateError(
                    "claim completion capability is already terminal-bound"
                )
            object.__setattr__(self, "_lifecycle_state", "PROMOTING")

    def _cancel_publication_promotion(self, *, _token: object) -> None:
        if _token is not _CLAIM_PROMOTION_TOKEN:
            raise EffectLeaseStateError(
                "claim promotion is reserved for the canonical ledger"
            )
        with self._lock:
            if self._lifecycle_state == "PROMOTING":
                object.__setattr__(self, "_lifecycle_state", "LIVE")

    def _complete_publication_promotion(
        self,
        *,
        start_receipt: LeasedEffectStartReceipt,
        claim_receipt: EffectExecutionClaimReceipt,
        commit_receipt: EffectPublicationCommitReceipt,
        secret: bytes,
        outcome_audit_key: bytes,
        _token: object,
    ) -> "PublicationCommitCapability":
        if _token is not _CLAIM_PROMOTION_TOKEN:
            raise EffectLeaseStateError(
                "claim promotion is reserved for the canonical ledger"
            )
        with self._lock:
            if os.getpid() != self._mint_pid:
                raise EffectLeaseStateError(
                    "claim completion capability cannot cross a process fork"
                )
            if self._lifecycle_state != "PROMOTING":
                raise EffectLeaseStateError(
                    "claim completion capability has no pending promotion"
                )
            capability = PublicationCommitCapability(
                start_receipt=start_receipt,
                claim_receipt=claim_receipt,
                commit_receipt=commit_receipt,
                secret=secret,
                outcome_audit_key=outcome_audit_key,
                _mint_token=_PUBLICATION_CAPABILITY_MINT_TOKEN,
            )
            object.__setattr__(self, "_lifecycle_state", "PROMOTED")
            object.__setattr__(
                self,
                "_promoted_commit_sha256",
                commit_receipt.receipt_sha256,
            )
            return capability


class PublicationCommitCapability:
    """PID-bound, one-use authority for the target publication consumer.

    This capability has deliberately no terminal authorization method.  It can
    only open one target-publication session.  The session must cross the
    declared effect boundary, explicitly attest success, and exit cleanly
    before its separate finalization capability becomes usable.
    """

    __slots__ = (
        "_lease_sha256",
        "_execution_id",
        "_execution_request_sha256",
        "_start_receipt_sha256",
        "_claim_receipt_sha256",
        "_commit_receipt_sha256",
        "_effect_commitment_sha256",
        "_commitment_sha256",
        "_secret",
        "_outcome_audit_key",
        "_start_receipt",
        "_claim_receipt",
        "_commit_receipt",
        "_mint_pid",
        "_state",
        "_owner_thread_id",
        "_session_nonce",
        "_boundary_crossed",
        "_outcome_receipt_sha256",
        "_lock",
    )

    def __init__(
        self,
        *,
        start_receipt: LeasedEffectStartReceipt,
        claim_receipt: EffectExecutionClaimReceipt,
        commit_receipt: EffectPublicationCommitReceipt,
        secret: bytes,
        outcome_audit_key: bytes,
        _mint_token: object | None = None,
    ) -> None:
        if _mint_token is not _PUBLICATION_CAPABILITY_MINT_TOKEN:
            raise EffectLeaseStateError(
                "publication capabilities may only be minted by a persisted "
                "COMMITTING transition"
            )
        secret_value = bytes(secret)
        commitment = _publication_capability_sha256(secret_value)
        mismatches = sorted(
            name
            for name, actual, expected in (
                (
                    "lease_sha256",
                    commit_receipt.lease_sha256,
                    start_receipt.lease_sha256,
                ),
                (
                    "execution_id",
                    commit_receipt.execution_id,
                    start_receipt.execution_id,
                ),
                (
                    "start_receipt_sha256",
                    commit_receipt.start_receipt_sha256,
                    start_receipt.receipt_sha256,
                ),
                (
                    "claim_start_receipt_sha256",
                    claim_receipt.start_receipt_sha256,
                    start_receipt.receipt_sha256,
                ),
                (
                    "claim_receipt_sha256",
                    commit_receipt.claim_receipt_sha256,
                    claim_receipt.receipt_sha256,
                ),
                (
                    "execution_request_sha256",
                    commit_receipt.execution_request_sha256,
                    claim_receipt.execution_request_sha256,
                ),
                (
                    "publication_capability_sha256",
                    commit_receipt.publication_capability_sha256,
                    commitment,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "publication capability binding mismatch: "
                + ", ".join(mismatches)
            )
        object.__setattr__(self, "_lease_sha256", commit_receipt.lease_sha256)
        object.__setattr__(self, "_execution_id", commit_receipt.execution_id)
        object.__setattr__(
            self,
            "_execution_request_sha256",
            commit_receipt.execution_request_sha256,
        )
        object.__setattr__(
            self, "_start_receipt_sha256", start_receipt.receipt_sha256
        )
        object.__setattr__(
            self, "_claim_receipt_sha256", claim_receipt.receipt_sha256
        )
        object.__setattr__(
            self, "_commit_receipt_sha256", commit_receipt.receipt_sha256
        )
        object.__setattr__(
            self,
            "_effect_commitment_sha256",
            commit_receipt.effect_commitment_sha256,
        )
        object.__setattr__(self, "_commitment_sha256", commitment)
        object.__setattr__(self, "_secret", secret_value)
        object.__setattr__(self, "_outcome_audit_key", bytes(outcome_audit_key))
        object.__setattr__(self, "_start_receipt", start_receipt)
        object.__setattr__(self, "_claim_receipt", claim_receipt)
        object.__setattr__(self, "_commit_receipt", commit_receipt)
        object.__setattr__(self, "_mint_pid", os.getpid())
        object.__setattr__(self, "_state", "FRESH")
        object.__setattr__(self, "_owner_thread_id", None)
        object.__setattr__(self, "_session_nonce", None)
        object.__setattr__(self, "_boundary_crossed", False)
        object.__setattr__(self, "_outcome_receipt_sha256", None)
        object.__setattr__(self, "_lock", threading.Lock())

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("PublicationCommitCapability is immutable")

    def __repr__(self) -> str:
        return "PublicationCommitCapability(<redacted>)"

    def verify_commit_receipt(
        self,
        start_receipt: LeasedEffectStartReceipt,
        claim_receipt: EffectExecutionClaimReceipt,
        commit_receipt: EffectPublicationCommitReceipt,
    ) -> None:
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("lease_sha256", self._lease_sha256, commit_receipt.lease_sha256),
                ("execution_id", self._execution_id, commit_receipt.execution_id),
                (
                    "execution_request_sha256",
                    self._execution_request_sha256,
                    commit_receipt.execution_request_sha256,
                ),
                (
                    "start_receipt_sha256",
                    self._start_receipt_sha256,
                    start_receipt.receipt_sha256,
                ),
                (
                    "claim_receipt_sha256",
                    self._claim_receipt_sha256,
                    claim_receipt.receipt_sha256,
                ),
                (
                    "commit_claim_receipt_sha256",
                    commit_receipt.claim_receipt_sha256,
                    claim_receipt.receipt_sha256,
                ),
                (
                    "publication_commit_receipt_sha256",
                    self._commit_receipt_sha256,
                    commit_receipt.receipt_sha256,
                ),
                (
                    "effect_commitment_sha256",
                    self._effect_commitment_sha256,
                    commit_receipt.effect_commitment_sha256,
                ),
                (
                    "publication_capability_sha256",
                    self._commitment_sha256,
                    commit_receipt.publication_capability_sha256,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "publication capability receipt mismatch: "
                + ", ".join(mismatches)
            )
        expected = _publication_capability_sha256(self._secret)
        if not hmac.compare_digest(expected, self._commitment_sha256):
            raise EffectLeaseSignatureError(
                "publication capability secret does not match its commitment"
            )
        with self._lock:
            self._require_pid_locked()
            if self._state != "FRESH":
                raise EffectLeaseStateError(
                    "publication capability is no longer fresh"
                )

    def open_target_publication(self) -> "_TargetPublicationSession":
        """Exclusively open the one target-consumer publication attempt."""

        with self._lock:
            self._require_pid_locked()
            if self._state != "FRESH":
                raise EffectLeaseStateError(
                    "publication capability is already opened or poisoned"
                )
            session_nonce = secrets.token_hex(32)
            object.__setattr__(self, "_state", "ACTIVE")
            object.__setattr__(
                self, "_owner_thread_id", threading.get_ident()
            )
            object.__setattr__(self, "_session_nonce", session_nonce)
            return _TargetPublicationSession(
                capability=self,
                session_nonce=session_nonce,
                _mint_token=_PUBLICATION_SESSION_MINT_TOKEN,
            )

    def _require_pid_locked(self) -> None:
        if os.getpid() != self._mint_pid:
            raise EffectLeaseStateError(
                "publication capability cannot cross a process fork"
            )

    def _require_active_owner_locked(self, session_nonce: str) -> None:
        self._require_pid_locked()
        if self._state not in {"ACTIVE", "SUCCESS_DECLARED"}:
            raise EffectLeaseStateError("publication session is not active")
        if self._session_nonce != session_nonce:
            raise EffectLeaseBindingMismatch(
                "publication session nonce does not match its capability"
            )
        if self._owner_thread_id != threading.get_ident():
            raise EffectLeaseStateError(
                "publication session is bound to its opening thread"
            )

    def _enter_session(self, session_nonce: str) -> None:
        with self._lock:
            self._require_active_owner_locked(session_nonce)
            if self._state != "ACTIVE":
                raise EffectLeaseStateError(
                    "publication session cannot be re-entered after success"
                )

    def _mark_boundary_crossed(self, session_nonce: str) -> None:
        with self._lock:
            self._require_active_owner_locked(session_nonce)
            if self._state != "ACTIVE":
                raise EffectLeaseStateError(
                    "publication success was already declared"
                )
            if self._boundary_crossed:
                raise EffectLeaseStateError(
                    "publication effect boundary was already crossed"
                )
            object.__setattr__(self, "_boundary_crossed", True)

    def _declare_success(
        self,
        session_nonce: str,
        *,
        commit_receipt: EffectPublicationCommitReceipt,
        published_at: datetime | None,
    ) -> "EffectPublicationFinalization":
        with self._lock:
            self._require_active_owner_locked(session_nonce)
            if self._state != "ACTIVE" or not self._boundary_crossed:
                raise EffectLeaseStateError(
                    "publication success requires one crossed effect boundary"
                )
            if commit_receipt.receipt_sha256 != self._commit_receipt_sha256:
                raise EffectLeaseBindingMismatch(
                    "publication success uses a different commit receipt"
                )
            published = (
                _as_utc(published_at, "published_at")
                if published_at is not None
                else _utc_now()
            )
            committed = _parse_utc(
                commit_receipt.committed_at, "commit.committed_at"
            )
            if published < committed:
                raise EffectLeaseStateError(
                    "publication success predates its durable commit"
                )
            finalization_secret = secrets.token_bytes(32)
            payload = {
                "lease_sha256": self._lease_sha256,
                "execution_id": self._execution_id,
                "execution_request_sha256": self._execution_request_sha256,
                "start_receipt_sha256": self._start_receipt_sha256,
                "claim_receipt_sha256": self._claim_receipt_sha256,
                "publication_commit_receipt_sha256": (
                    self._commit_receipt_sha256
                ),
                "effect_commitment_sha256": self._effect_commitment_sha256,
                "finalization_capability_sha256": (
                    _finalization_capability_sha256(finalization_secret)
                ),
                "published_at": _timestamp(published),
            }
            signature = _publication_outcome_signature(
                payload, self._outcome_audit_key
            )
            authenticated = {**payload, "signature_sha256": signature}
            outcome = EffectPublicationOutcomeReceipt(
                **authenticated,
                receipt_sha256=canonical_sha(authenticated),
            )
            finalization_capability = PublicationFinalizationCapability(
                commit_receipt=commit_receipt,
                outcome_receipt=outcome,
                publication_secret=self._secret,
                outcome_audit_key=self._outcome_audit_key,
                finalization_secret=finalization_secret,
                publication_capability=self,
                session_nonce=session_nonce,
                _mint_token=_FINALIZATION_CAPABILITY_MINT_TOKEN,
            )
            object.__setattr__(self, "_state", "SUCCESS_DECLARED")
            object.__setattr__(
                self, "_outcome_receipt_sha256", outcome.receipt_sha256
            )
            return EffectPublicationFinalization(
                start_receipt=self._start_receipt,
                claim_receipt=self._claim_receipt,
                commit_receipt=commit_receipt,
                outcome_receipt=outcome,
                completion_capability=finalization_capability,
            )

    def _exit_session(
        self, session_nonce: str, *, exception_raised: bool
    ) -> None:
        with self._lock:
            self._require_active_owner_locked(session_nonce)
            if exception_raised or self._state != "SUCCESS_DECLARED":
                object.__setattr__(self, "_state", "POISONED")
                return
            object.__setattr__(self, "_state", "FINALIZABLE")

    def _require_finalizable(
        self, *, session_nonce: str, outcome_receipt_sha256: str
    ) -> None:
        with self._lock:
            self._require_pid_locked()
            if self._state != "FINALIZABLE":
                raise EffectLeaseStateError(
                    "publication finalization requires a clean session exit"
                )
            if self._session_nonce != session_nonce:
                raise EffectLeaseBindingMismatch(
                    "finalization session differs from publication authority"
                )
            if self._outcome_receipt_sha256 != outcome_receipt_sha256:
                raise EffectLeaseBindingMismatch(
                    "finalization outcome differs from publication success"
                )


class _TargetPublicationSession:
    """One same-thread context around the effectful target consumer."""

    __slots__ = (
        "_capability",
        "_session_nonce",
        "_entered",
        "_exited",
        "_commit_receipt",
    )

    def __init__(
        self,
        *,
        capability: PublicationCommitCapability,
        session_nonce: str,
        _mint_token: object | None = None,
    ) -> None:
        if _mint_token is not _PUBLICATION_SESSION_MINT_TOKEN:
            raise EffectLeaseStateError(
                "target publication sessions may only be opened by a live "
                "publication capability"
            )
        object.__setattr__(self, "_capability", capability)
        object.__setattr__(self, "_session_nonce", session_nonce)
        object.__setattr__(self, "_entered", False)
        object.__setattr__(self, "_exited", False)
        object.__setattr__(self, "_commit_receipt", None)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("target publication session is immutable")

    def __enter__(self) -> "_TargetPublicationSession":
        if self._entered or self._exited:
            raise EffectLeaseStateError(
                "target publication session is one-use"
            )
        self._capability._enter_session(self._session_nonce)
        object.__setattr__(self, "_entered", True)
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        if not self._entered or self._exited:
            raise EffectLeaseStateError(
                "target publication session exit is invalid"
            )
        self._capability._exit_session(
            self._session_nonce,
            exception_raised=exc_type is not None,
        )
        object.__setattr__(self, "_exited", True)
        return False

    def mark_effect_boundary_crossed(self) -> None:
        self._require_active_context()
        self._capability._mark_boundary_crossed(self._session_nonce)

    def publication_succeeded(
        self,
        *,
        commit_receipt: EffectPublicationCommitReceipt,
        published_at: datetime | None = None,
    ) -> "EffectPublicationFinalization":
        self._require_active_context()
        object.__setattr__(self, "_commit_receipt", commit_receipt)
        return self._capability._declare_success(
            self._session_nonce,
            commit_receipt=commit_receipt,
            published_at=published_at,
        )

    def _require_active_context(self) -> None:
        if not self._entered or self._exited:
            raise EffectLeaseStateError(
                "publication operation requires its active context"
            )


class PublicationFinalizationCapability:
    """Live-only terminal authority released after clean publication exit."""

    __slots__ = (
        "_lease_sha256",
        "_execution_id",
        "_start_receipt_sha256",
        "_claim_receipt_sha256",
        "_commit_receipt_sha256",
        "_outcome_receipt_sha256",
        "_publication_secret",
        "_outcome_audit_key",
        "_finalization_secret",
        "_finalization_commitment_sha256",
        "_publication_capability",
        "_session_nonce",
        "_mint_pid",
        "_mint_thread_id",
        "_bound_terminal_sha256",
        "_lock",
    )

    def __init__(
        self,
        *,
        commit_receipt: EffectPublicationCommitReceipt,
        outcome_receipt: EffectPublicationOutcomeReceipt,
        publication_secret: bytes,
        outcome_audit_key: bytes,
        finalization_secret: bytes,
        publication_capability: PublicationCommitCapability,
        session_nonce: str,
        _mint_token: object | None = None,
    ) -> None:
        if _mint_token is not _FINALIZATION_CAPABILITY_MINT_TOKEN:
            raise EffectLeaseStateError(
                "finalization capabilities may only be minted by an explicit "
                "publication success"
            )
        object.__setattr__(self, "_lease_sha256", commit_receipt.lease_sha256)
        object.__setattr__(self, "_execution_id", commit_receipt.execution_id)
        object.__setattr__(
            self, "_start_receipt_sha256", commit_receipt.start_receipt_sha256
        )
        object.__setattr__(
            self, "_claim_receipt_sha256", commit_receipt.claim_receipt_sha256
        )
        object.__setattr__(
            self, "_commit_receipt_sha256", commit_receipt.receipt_sha256
        )
        object.__setattr__(
            self, "_outcome_receipt_sha256", outcome_receipt.receipt_sha256
        )
        object.__setattr__(self, "_publication_secret", bytes(publication_secret))
        object.__setattr__(self, "_outcome_audit_key", bytes(outcome_audit_key))
        object.__setattr__(
            self, "_finalization_secret", bytes(finalization_secret)
        )
        object.__setattr__(
            self,
            "_finalization_commitment_sha256",
            _finalization_capability_sha256(finalization_secret),
        )
        object.__setattr__(
            self, "_publication_capability", publication_capability
        )
        object.__setattr__(self, "_session_nonce", session_nonce)
        object.__setattr__(self, "_mint_pid", os.getpid())
        object.__setattr__(self, "_mint_thread_id", threading.get_ident())
        object.__setattr__(self, "_bound_terminal_sha256", None)
        object.__setattr__(self, "_lock", threading.Lock())
        self.verify_publication(
            commit_receipt,
            outcome_receipt,
            require_finalizable=False,
        )

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("PublicationFinalizationCapability is immutable")

    def __repr__(self) -> str:
        return "PublicationFinalizationCapability(<redacted>)"

    def verify_publication(
        self,
        commit_receipt: EffectPublicationCommitReceipt,
        outcome_receipt: EffectPublicationOutcomeReceipt,
        *,
        require_finalizable: bool = True,
    ) -> None:
        if os.getpid() != self._mint_pid:
            raise EffectLeaseStateError(
                "publication finalization capability cannot cross a process fork"
            )
        if threading.get_ident() != self._mint_thread_id:
            raise EffectLeaseStateError(
                "publication finalization capability is bound to its "
                "publication thread"
            )
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("lease_sha256", self._lease_sha256, commit_receipt.lease_sha256),
                ("execution_id", self._execution_id, commit_receipt.execution_id),
                (
                    "start_receipt_sha256",
                    self._start_receipt_sha256,
                    commit_receipt.start_receipt_sha256,
                ),
                (
                    "claim_receipt_sha256",
                    self._claim_receipt_sha256,
                    commit_receipt.claim_receipt_sha256,
                ),
                (
                    "publication_commit_receipt_sha256",
                    self._commit_receipt_sha256,
                    commit_receipt.receipt_sha256,
                ),
                (
                    "outcome_commit_receipt_sha256",
                    outcome_receipt.publication_commit_receipt_sha256,
                    commit_receipt.receipt_sha256,
                ),
                (
                    "publication_outcome_receipt_sha256",
                    self._outcome_receipt_sha256,
                    outcome_receipt.receipt_sha256,
                ),
                (
                    "effect_commitment_sha256",
                    outcome_receipt.effect_commitment_sha256,
                    commit_receipt.effect_commitment_sha256,
                ),
                (
                    "finalization_capability_sha256",
                    self._finalization_commitment_sha256,
                    outcome_receipt.finalization_capability_sha256,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "publication finalization binding mismatch: "
                + ", ".join(mismatches)
            )
        publication_commitment = _publication_capability_sha256(
            self._publication_secret
        )
        if not hmac.compare_digest(
            publication_commitment,
            commit_receipt.publication_capability_sha256,
        ):
            raise EffectLeaseSignatureError(
                "publication outcome secret does not match durable commit"
            )
        expected_outcome_signature = _publication_outcome_signature(
            outcome_receipt.signing_dict(), self._outcome_audit_key
        )
        if not hmac.compare_digest(
            expected_outcome_signature, outcome_receipt.signature_sha256
        ):
            raise EffectLeaseSignatureError(
                "publication outcome signature mismatch"
            )
        if require_finalizable:
            self._publication_capability._require_finalizable(
                session_nonce=self._session_nonce,
                outcome_receipt_sha256=outcome_receipt.receipt_sha256,
            )

    def authorize(
        self,
        receipt: EffectTerminalReceipt,
        *,
        commit_receipt: EffectPublicationCommitReceipt,
        outcome_receipt: EffectPublicationOutcomeReceipt,
    ) -> PublicationFinalizationAuthorization:
        self.verify_publication(commit_receipt, outcome_receipt)
        if receipt.outcome != "COMPLETED":
            raise EffectLeaseStateError(
                "a successful publication terminal receipt must be COMPLETED"
            )
        published = _parse_utc(outcome_receipt.published_at, "outcome.published_at")
        finished = _parse_utc(receipt.finished_at, "receipt.finished_at")
        if finished < published:
            raise EffectLeaseStateError(
                "publication terminal receipt predates publication outcome"
            )
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("lease_sha256", receipt.lease_sha256, self._lease_sha256),
                ("execution_id", receipt.execution_id, self._execution_id),
                (
                    "start_receipt_sha256",
                    receipt.start_receipt_sha256,
                    self._start_receipt_sha256,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseBindingMismatch(
                "publication finalization terminal binding mismatch: "
                + ", ".join(mismatches)
            )
        with self._lock:
            if self._bound_terminal_sha256 is None:
                object.__setattr__(
                    self, "_bound_terminal_sha256", receipt.receipt_sha256
                )
            elif not hmac.compare_digest(
                self._bound_terminal_sha256, receipt.receipt_sha256
            ):
                raise EffectLeaseStateError(
                    "publication finalization capability is already bound to "
                    "another terminal receipt"
                )
        return PublicationFinalizationAuthorization._issue(
            lease_sha256=self._lease_sha256,
            execution_id=self._execution_id,
            start_receipt_sha256=self._start_receipt_sha256,
            claim_receipt_sha256=self._claim_receipt_sha256,
            publication_commit_receipt_sha256=self._commit_receipt_sha256,
            publication_outcome_receipt_sha256=self._outcome_receipt_sha256,
            terminal_receipt_sha256=receipt.receipt_sha256,
            secret=self._finalization_secret,
            publication_secret=self._publication_secret,
            outcome_audit_key=self._outcome_audit_key,
        )


@dataclass(frozen=True)
class EffectExecutionClaim:
    """Live claim result returned only after ``EXECUTING`` is durable."""

    start_receipt: LeasedEffectStartReceipt
    claim_receipt: EffectExecutionClaimReceipt
    completion_capability: ClaimCompletionCapability = field(
        repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.start_receipt) is not LeasedEffectStartReceipt:
            raise TypeError("start_receipt must be an exact LeasedEffectStartReceipt")
        if type(self.claim_receipt) is not EffectExecutionClaimReceipt:
            raise TypeError(
                "claim_receipt must be an exact EffectExecutionClaimReceipt"
            )
        if type(self.completion_capability) is not ClaimCompletionCapability:
            raise TypeError(
                "completion_capability must be an exact ClaimCompletionCapability"
            )
        self.completion_capability.verify_claim_receipt(
            self.start_receipt, self.claim_receipt
        )


@dataclass(frozen=True)
class EffectPublicationCommit:
    """Live result returned only after ``COMMITTING`` is durable."""

    start_receipt: LeasedEffectStartReceipt
    claim_receipt: EffectExecutionClaimReceipt
    commit_receipt: EffectPublicationCommitReceipt
    publication_capability: PublicationCommitCapability = field(
        repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.start_receipt) is not LeasedEffectStartReceipt:
            raise TypeError("start_receipt must be exact")
        if type(self.claim_receipt) is not EffectExecutionClaimReceipt:
            raise TypeError("claim_receipt must be exact")
        if type(self.commit_receipt) is not EffectPublicationCommitReceipt:
            raise TypeError("commit_receipt must be exact")
        if type(self.publication_capability) is not PublicationCommitCapability:
            raise TypeError("publication_capability must be exact")
        self.publication_capability.verify_commit_receipt(
            self.start_receipt,
            self.claim_receipt,
            self.commit_receipt,
        )


@dataclass(frozen=True)
class EffectPublicationFinalization:
    """Outcome evidence plus hidden authority released by publication."""

    start_receipt: LeasedEffectStartReceipt
    claim_receipt: EffectExecutionClaimReceipt
    commit_receipt: EffectPublicationCommitReceipt
    outcome_receipt: EffectPublicationOutcomeReceipt
    completion_capability: PublicationFinalizationCapability = field(
        repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.start_receipt) is not LeasedEffectStartReceipt:
            raise TypeError("start_receipt must be exact")
        if type(self.claim_receipt) is not EffectExecutionClaimReceipt:
            raise TypeError("claim_receipt must be exact")
        if type(self.commit_receipt) is not EffectPublicationCommitReceipt:
            raise TypeError("commit_receipt must be exact")
        if type(self.outcome_receipt) is not EffectPublicationOutcomeReceipt:
            raise TypeError("outcome_receipt must be exact")
        if (
            type(self.completion_capability)
            is not PublicationFinalizationCapability
        ):
            raise TypeError("completion_capability must be exact")
        if (
            self.claim_receipt.start_receipt_sha256
            != self.start_receipt.receipt_sha256
            or self.commit_receipt.start_receipt_sha256
            != self.start_receipt.receipt_sha256
            or self.commit_receipt.claim_receipt_sha256
            != self.claim_receipt.receipt_sha256
        ):
            raise EffectLeaseBindingMismatch(
                "publication finalization receipt chain mismatch"
            )
        self.completion_capability.verify_publication(
            self.commit_receipt,
            self.outcome_receipt,
            require_finalizable=False,
        )


@dataclass(frozen=True)
class EffectStartResult:
    receipt: LeasedEffectStartReceipt
    execute: bool
    completion_capability: CompletionCapability | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.execute, bool):
            raise TypeError("execute must be a boolean")
        if self.execute != (self.completion_capability is not None):
            raise EffectLeaseStateError(
                "only a new live start may carry a completion capability"
            )


def freeze_effect_terminal_receipt(
    start_receipt: LeasedEffectStartReceipt,
    *,
    outcome: str,
    output_digests: Iterable[str] = (),
    detail_sha256: str | None = None,
    finished_at: datetime | None = None,
) -> EffectTerminalReceipt:
    """Freeze the exact terminal claim before any persistence attempt.

    This pure construction seam is shared by ordinary ``finish`` and the live
    offload boundary.  If SQLite is unavailable, the caller can retain this
    byte-identical receipt for authenticated operator reconciliation instead
    of trying to recreate an outcome later.
    """

    normalized_outcome = str(outcome).upper()
    if normalized_outcome not in _TERMINAL_STATES:
        raise ValueError("outcome must be completed, failed, or cancelled")
    outputs = tuple(
        sorted({_sha256(value, "output_digest") for value in output_digests})
    )
    detail = (
        _sha256(detail_sha256, "detail_sha256")
        if detail_sha256 is not None
        else None
    )
    timestamp = _timestamp(finished_at or _utc_now())
    payload = {
        "lease_sha256": start_receipt.lease_sha256,
        "execution_id": start_receipt.execution_id,
        "start_receipt_sha256": start_receipt.receipt_sha256,
        "outcome": normalized_outcome,
        "output_digests": list(outputs),
        "detail_sha256": detail,
        "finished_at": timestamp,
    }
    return EffectTerminalReceipt(
        lease_sha256=start_receipt.lease_sha256,
        execution_id=start_receipt.execution_id,
        start_receipt_sha256=start_receipt.receipt_sha256,
        outcome=normalized_outcome,
        output_digests=outputs,
        detail_sha256=detail,
        finished_at=timestamp,
        receipt_sha256=canonical_sha(payload),
    )


@dataclass(frozen=True)
class PersistedEffectGrant:
    """Authenticated contracts recovered from one persisted lease grant.

    Issuer secrets are intentionally absent.  A caller must supply the current
    keyring and kill-switch generation to :meth:`EffectLeaseLedger.load_grant`,
    which re-runs signature, policy, registry, expiry and scope verification
    before returning this record.
    """

    lease: EffectLease
    request: EffectLeaseRequest
    policy_decision: PolicyDecision
    revoked_at: str | None = None
    revocation_reason: str | None = None


@dataclass(frozen=True)
class PersistedEffectExecution:
    """One exact execution row recovered for restart/reconciliation."""

    request: EffectExecutionRequest
    start_receipt: LeasedEffectStartReceipt
    state: str
    claim_receipt: EffectExecutionClaimReceipt | None = None
    publication_commit_receipt: EffectPublicationCommitReceipt | None = None
    publication_outcome_receipt: EffectPublicationOutcomeReceipt | None = None
    terminal_receipt: EffectTerminalReceipt | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EffectLeaseBindingMismatch(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EffectLeaseBindingMismatch(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _as_utc(value, "timestamp").isoformat(timespec="microseconds")


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("effect lease issuer secret must contain at least 32 bytes")
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret), signing_digest.encode("ascii"), hashlib.sha256
    ).hexdigest()


def _start_receipt_signature(
    signing_payload: Mapping[str, object], secret: bytes | str
) -> str:
    message = _START_RECEIPT_HMAC_DOMAIN + canonical_json(signing_payload).encode(
        "utf-8"
    )
    return hmac.new(_secret_bytes(secret), message, hashlib.sha256).hexdigest()


def _completion_capability_sha256(secret: bytes) -> str:
    return hashlib.sha256(
        _COMPLETION_CAPABILITY_DOMAIN + bytes(secret)
    ).hexdigest()


def _execution_claim_signature(
    signing_payload: Mapping[str, object], secret: bytes | str
) -> str:
    message = _EXECUTION_CLAIM_HMAC_DOMAIN + canonical_json(
        signing_payload
    ).encode("utf-8")
    return hmac.new(_secret_bytes(secret), message, hashlib.sha256).hexdigest()


def _claim_completion_capability_sha256(secret: bytes) -> str:
    return hashlib.sha256(
        _CLAIM_COMPLETION_CAPABILITY_DOMAIN + bytes(secret)
    ).hexdigest()


def _publication_commit_signature(
    signing_payload: Mapping[str, object], secret: bytes | str
) -> str:
    message = _PUBLICATION_COMMIT_HMAC_DOMAIN + canonical_json(
        signing_payload
    ).encode("utf-8")
    return hmac.new(_secret_bytes(secret), message, hashlib.sha256).hexdigest()


def _publication_capability_sha256(secret: bytes) -> str:
    return hashlib.sha256(
        _PUBLICATION_CAPABILITY_DOMAIN + bytes(secret)
    ).hexdigest()


def _publication_capability_preimage(
    *,
    lease_sha256: str,
    issuer_key_id: str,
    execution_id: str,
    execution_request_sha256: str,
    start_receipt_sha256: str,
    claim_receipt_sha256: str,
    effect_commitment_sha256: str,
    committed_at: str,
) -> dict[str, str]:
    """Return the authenticated, non-circular per-commit KDF input."""

    return {
        "lease_sha256": lease_sha256,
        "issuer_key_id": issuer_key_id,
        "execution_id": execution_id,
        "execution_request_sha256": execution_request_sha256,
        "start_receipt_sha256": start_receipt_sha256,
        "claim_receipt_sha256": claim_receipt_sha256,
        "effect_commitment_sha256": effect_commitment_sha256,
        "committed_at": committed_at,
    }


def _derive_publication_outcome_audit_key(
    preimage: Mapping[str, object], issuer_secret: bytes | str
) -> bytes:
    """Derive a restart-audit key that is never publication authority."""

    message = _PUBLICATION_OUTCOME_AUDIT_KEY_DOMAIN + canonical_json(
        preimage
    ).encode("utf-8")
    return hmac.new(_secret_bytes(issuer_secret), message, hashlib.sha256).digest()


def _publication_outcome_audit_key_for_commit(
    receipt: EffectPublicationCommitReceipt,
    *,
    lease: EffectLease,
    keyring: Mapping[str, bytes | str],
) -> bytes:
    if receipt.issuer_key_id != lease.issuer_key_id:
        raise EffectLeaseSignatureError(
            "publication outcome audit issuer does not match historical lease"
        )
    issuer_secret = keyring.get(receipt.issuer_key_id)
    if issuer_secret is None:
        raise EffectLeaseSignatureError(
            "publication outcome audit issuer key is unknown"
        )
    return _derive_publication_outcome_audit_key(
        _publication_capability_preimage(
            lease_sha256=receipt.lease_sha256,
            issuer_key_id=receipt.issuer_key_id,
            execution_id=receipt.execution_id,
            execution_request_sha256=receipt.execution_request_sha256,
            start_receipt_sha256=receipt.start_receipt_sha256,
            claim_receipt_sha256=receipt.claim_receipt_sha256,
            effect_commitment_sha256=receipt.effect_commitment_sha256,
            committed_at=receipt.committed_at,
        ),
        issuer_secret,
    )


def _publication_outcome_signature(
    signing_payload: Mapping[str, object], secret: bytes
) -> str:
    message = _PUBLICATION_OUTCOME_HMAC_DOMAIN + canonical_json(
        signing_payload
    ).encode("utf-8")
    return hmac.new(bytes(secret), message, hashlib.sha256).hexdigest()


def _finalization_capability_sha256(secret: bytes) -> str:
    return hashlib.sha256(
        _FINALIZATION_CAPABILITY_DOMAIN + bytes(secret)
    ).hexdigest()


def _terminal_authorization_signature(
    payload: Mapping[str, object], secret: bytes
) -> str:
    message = (
        _TERMINAL_AUTHORIZATION_HMAC_DOMAIN
        + canonical_json(payload).encode("utf-8")
    )
    return hmac.new(bytes(secret), message, hashlib.sha256).hexdigest()


def _claim_terminal_authorization_signature(
    payload: Mapping[str, object], secret: bytes
) -> str:
    message = (
        _CLAIM_TERMINAL_AUTHORIZATION_HMAC_DOMAIN
        + canonical_json(payload).encode("utf-8")
    )
    return hmac.new(bytes(secret), message, hashlib.sha256).hexdigest()


def _publication_finalization_authorization_signature(
    payload: Mapping[str, object], secret: bytes
) -> str:
    message = (
        _FINALIZATION_AUTHORIZATION_HMAC_DOMAIN
        + canonical_json(payload).encode("utf-8")
    )
    return hmac.new(bytes(secret), message, hashlib.sha256).hexdigest()


def _authenticate_start_receipt(
    receipt: LeasedEffectStartReceipt,
    *,
    lease: EffectLease,
    keyring: Mapping[str, bytes | str],
) -> None:
    if receipt.issuer_key_id != lease.issuer_key_id:
        raise EffectLeaseSignatureError(
            "start receipt issuer does not match historical lease"
        )
    secret = keyring.get(receipt.issuer_key_id)
    if secret is None:
        raise EffectLeaseSignatureError("start receipt issuer key is unknown")
    expected = _start_receipt_signature(receipt.signing_dict(), secret)
    if not hmac.compare_digest(receipt.signature_sha256, expected):
        raise EffectLeaseSignatureError("start receipt signature mismatch")


def _authenticate_execution_claim_receipt(
    receipt: EffectExecutionClaimReceipt,
    *,
    lease: EffectLease,
    keyring: Mapping[str, bytes | str],
) -> None:
    if receipt.issuer_key_id != lease.issuer_key_id:
        raise EffectLeaseSignatureError(
            "execution claim issuer does not match historical lease"
        )
    secret = keyring.get(receipt.issuer_key_id)
    if secret is None:
        raise EffectLeaseSignatureError("execution claim issuer key is unknown")
    expected = _execution_claim_signature(receipt.signing_dict(), secret)
    if not hmac.compare_digest(receipt.signature_sha256, expected):
        raise EffectLeaseSignatureError("execution claim signature mismatch")


def _authenticate_publication_commit_receipt(
    receipt: EffectPublicationCommitReceipt,
    *,
    lease: EffectLease,
    keyring: Mapping[str, bytes | str],
) -> None:
    if receipt.issuer_key_id != lease.issuer_key_id:
        raise EffectLeaseSignatureError(
            "publication commit issuer does not match historical lease"
        )
    secret = keyring.get(receipt.issuer_key_id)
    if secret is None:
        raise EffectLeaseSignatureError(
            "publication commit issuer key is unknown"
        )
    expected = _publication_commit_signature(receipt.signing_dict(), secret)
    if not hmac.compare_digest(receipt.signature_sha256, expected):
        raise EffectLeaseSignatureError("publication commit signature mismatch")


def _authenticate_terminal_authorization(
    authorization: TerminalAuthorization,
    *,
    receipt: EffectTerminalReceipt,
    start_receipt: LeasedEffectStartReceipt,
) -> None:
    if not isinstance(authorization, TerminalAuthorization):
        raise TypeError("authorization must be a TerminalAuthorization")
    mismatches = sorted(
        name
        for name, actual, expected in (
            ("lease_sha256", authorization._lease_sha256, receipt.lease_sha256),
            ("execution_id", authorization._execution_id, receipt.execution_id),
            (
                "start_receipt_sha256",
                authorization._start_receipt_sha256,
                receipt.start_receipt_sha256,
            ),
            (
                "terminal_receipt_sha256",
                authorization._terminal_receipt_sha256,
                receipt.receipt_sha256,
            ),
        )
        if actual != expected
    )
    if mismatches:
        raise EffectLeaseBindingMismatch(
            "terminal authorization binding mismatch: " + ", ".join(mismatches)
        )
    expected_signature = _terminal_authorization_signature(
        {
            "lease_sha256": authorization._lease_sha256,
            "execution_id": authorization._execution_id,
            "start_receipt_sha256": authorization._start_receipt_sha256,
            "terminal_receipt_sha256": authorization._terminal_receipt_sha256,
        },
        authorization._secret,
    )
    if not hmac.compare_digest(
        authorization._signature_sha256, expected_signature
    ):
        raise EffectLeaseSignatureError(
            "terminal authorization signature mismatch"
        )
    expected_commitment = _completion_capability_sha256(authorization._secret)
    if not hmac.compare_digest(
        expected_commitment, start_receipt.completion_capability_sha256
    ):
        raise EffectLeaseSignatureError(
            "terminal authorization does not match signed start capability"
        )


def _authenticate_claim_terminal_authorization(
    authorization: ClaimTerminalAuthorization,
    *,
    receipt: EffectTerminalReceipt,
    start_receipt: LeasedEffectStartReceipt,
    claim_receipt: EffectExecutionClaimReceipt,
) -> None:
    if not isinstance(authorization, ClaimTerminalAuthorization):
        raise TypeError("authorization must be a ClaimTerminalAuthorization")
    mismatches = sorted(
        name
        for name, actual, expected in (
            ("lease_sha256", authorization._lease_sha256, receipt.lease_sha256),
            ("execution_id", authorization._execution_id, receipt.execution_id),
            (
                "start_receipt_sha256",
                authorization._start_receipt_sha256,
                receipt.start_receipt_sha256,
            ),
            (
                "claim_receipt_sha256",
                authorization._claim_receipt_sha256,
                claim_receipt.receipt_sha256,
            ),
            (
                "terminal_receipt_sha256",
                authorization._terminal_receipt_sha256,
                receipt.receipt_sha256,
            ),
        )
        if actual != expected
    )
    if start_receipt.receipt_sha256 != receipt.start_receipt_sha256:
        mismatches.append("persisted_start_receipt_sha256")
    if claim_receipt.start_receipt_sha256 != start_receipt.receipt_sha256:
        mismatches.append("claim_start_receipt_sha256")
    if mismatches:
        raise EffectLeaseBindingMismatch(
            "claim terminal authorization binding mismatch: "
            + ", ".join(sorted(set(mismatches)))
        )
    expected_signature = _claim_terminal_authorization_signature(
        {
            "lease_sha256": authorization._lease_sha256,
            "execution_id": authorization._execution_id,
            "start_receipt_sha256": authorization._start_receipt_sha256,
            "claim_receipt_sha256": authorization._claim_receipt_sha256,
            "terminal_receipt_sha256": authorization._terminal_receipt_sha256,
        },
        authorization._secret,
    )
    if not hmac.compare_digest(
        authorization._signature_sha256, expected_signature
    ):
        raise EffectLeaseSignatureError(
            "claim terminal authorization signature mismatch"
        )
    expected_commitment = _claim_completion_capability_sha256(
        authorization._secret
    )
    if not hmac.compare_digest(
        expected_commitment, claim_receipt.claim_capability_sha256
    ):
        raise EffectLeaseSignatureError(
            "claim terminal authorization does not match signed claim capability"
        )


def _authenticate_publication_finalization_authorization(
    authorization: PublicationFinalizationAuthorization,
    *,
    receipt: EffectTerminalReceipt,
    start_receipt: LeasedEffectStartReceipt,
    claim_receipt: EffectExecutionClaimReceipt,
    commit_receipt: EffectPublicationCommitReceipt,
    outcome_receipt: EffectPublicationOutcomeReceipt,
) -> None:
    if not isinstance(authorization, PublicationFinalizationAuthorization):
        raise TypeError(
            "authorization must be a PublicationFinalizationAuthorization"
        )
    if authorization._pid != os.getpid():
        raise EffectLeaseStateError(
            "publication finalization authorization cannot cross a process fork"
        )
    if authorization._thread_id != threading.get_ident():
        raise EffectLeaseStateError(
            "publication finalization authorization is bound to its issuing thread"
        )
    mismatches = sorted(
        name
        for name, actual, expected in (
            ("lease_sha256", authorization._lease_sha256, receipt.lease_sha256),
            ("execution_id", authorization._execution_id, receipt.execution_id),
            (
                "start_receipt_sha256",
                authorization._start_receipt_sha256,
                start_receipt.receipt_sha256,
            ),
            (
                "claim_receipt_sha256",
                authorization._claim_receipt_sha256,
                claim_receipt.receipt_sha256,
            ),
            (
                "publication_commit_receipt_sha256",
                authorization._publication_commit_receipt_sha256,
                commit_receipt.receipt_sha256,
            ),
            (
                "publication_outcome_receipt_sha256",
                authorization._publication_outcome_receipt_sha256,
                outcome_receipt.receipt_sha256,
            ),
            (
                "terminal_receipt_sha256",
                authorization._terminal_receipt_sha256,
                receipt.receipt_sha256,
            ),
            (
                "outcome_commit_receipt_sha256",
                outcome_receipt.publication_commit_receipt_sha256,
                commit_receipt.receipt_sha256,
            ),
            (
                "effect_commitment_sha256",
                outcome_receipt.effect_commitment_sha256,
                commit_receipt.effect_commitment_sha256,
            ),
        )
        if actual != expected
    )
    if receipt.start_receipt_sha256 != start_receipt.receipt_sha256:
        mismatches.append("terminal_start_receipt_sha256")
    if mismatches:
        raise EffectLeaseBindingMismatch(
            "publication finalization authorization binding mismatch: "
            + ", ".join(sorted(set(mismatches)))
        )
    authorization_payload = {
        "lease_sha256": authorization._lease_sha256,
        "execution_id": authorization._execution_id,
        "start_receipt_sha256": authorization._start_receipt_sha256,
        "claim_receipt_sha256": authorization._claim_receipt_sha256,
        "publication_commit_receipt_sha256": (
            authorization._publication_commit_receipt_sha256
        ),
        "publication_outcome_receipt_sha256": (
            authorization._publication_outcome_receipt_sha256
        ),
        "terminal_receipt_sha256": authorization._terminal_receipt_sha256,
        "pid": authorization._pid,
        "thread_id": authorization._thread_id,
    }
    expected_authorization_signature = (
        _publication_finalization_authorization_signature(
            authorization_payload, authorization._secret
        )
    )
    if not hmac.compare_digest(
        authorization._signature_sha256,
        expected_authorization_signature,
    ):
        raise EffectLeaseSignatureError(
            "publication finalization authorization signature mismatch"
        )
    expected_finalization_commitment = _finalization_capability_sha256(
        authorization._secret
    )
    if not hmac.compare_digest(
        expected_finalization_commitment,
        outcome_receipt.finalization_capability_sha256,
    ):
        raise EffectLeaseSignatureError(
            "finalization authorization does not match publication outcome"
        )
    expected_publication_commitment = _publication_capability_sha256(
        authorization._publication_secret
    )
    if not hmac.compare_digest(
        expected_publication_commitment,
        commit_receipt.publication_capability_sha256,
    ):
        raise EffectLeaseSignatureError(
            "publication outcome authority does not match durable commit"
        )
    expected_outcome_signature = _publication_outcome_signature(
        outcome_receipt.signing_dict(), authorization._outcome_audit_key
    )
    if not hmac.compare_digest(
        expected_outcome_signature, outcome_receipt.signature_sha256
    ):
        raise EffectLeaseSignatureError("publication outcome signature mismatch")


def _registry_map(
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec],
) -> Mapping[str, EntrypointSpec]:
    if isinstance(registry, Mapping):
        rows = dict(registry)
        mismatched = sorted(key for key, value in rows.items() if key != value.id)
        if mismatched:
            raise EffectLeaseBindingMismatch(
                "entrypoint registry contains mismatched key/id rows: "
                + ", ".join(mismatched)
            )
        return rows
    rows = list(registry)
    if len({row.id for row in rows}) != len(rows):
        raise EffectLeaseBindingMismatch("entrypoint registry contains duplicate ids")
    return {row.id: row for row in rows}


def _scope_requirements(effects: Iterable[str], scope: EffectScope) -> None:
    try:
        values = {Effect(value) for value in effects}
    except ValueError as exc:
        raise EffectLeaseScopeError("effect scope contains an unknown effect") from exc
    if values & {Effect.FILESYSTEM_WRITE, Effect.REPOSITORY_MUTATION}:
        if scope.read_only or not scope.writable_paths:
            raise EffectLeaseScopeError("write effects require bounded writable_paths")
    if values & {Effect.NETWORK_EGRESS, Effect.LISTEN_SOCKET}:
        if not scope.egress_endpoints:
            raise EffectLeaseScopeError("network effects require explicit egress_endpoints")
    if values & {Effect.PROCESS_SPAWN, Effect.PROCESS_CONTROL}:
        if not scope.tools:
            raise EffectLeaseScopeError("process effects require explicit tools")
    if Effect.SECRETS in values and not scope.secret_refs:
        raise EffectLeaseScopeError("secret effects require explicit secret_refs")
    if Effect.SPEND in values and scope.max_cost_microusd is None:
        raise EffectLeaseScopeError("spend effects require an explicit cost ceiling")
    if not scope.kill_switch_ref:
        raise EffectLeaseScopeError("effectful scope requires a kill_switch_ref")
    if scope.timeout_s is None:
        raise EffectLeaseScopeError("effectful scope requires a timeout_s")


def _path_within(candidate: str, root: str) -> bool:
    candidate_path = PurePosixPath(_repo_path(candidate, "candidate_path"))
    root_path = PurePosixPath(_repo_path(root, "root_path"))
    return root_path == PurePosixPath(".") or candidate_path == root_path or root_path in candidate_path.parents


def _validate_narrowed_scope(request: EffectExecutionRequest, lease: EffectLease) -> None:
    granted_effects = set(lease.requested_effects)
    requested_effects = set(request.requested_effects)
    if not requested_effects <= granted_effects:
        raise EffectLeaseScopeError(
            "execution requested effects outside lease: "
            + ", ".join(sorted(requested_effects - granted_effects))
        )
    scope = lease.effect_scope
    for candidate in request.writable_paths:
        if not any(_path_within(candidate, root) for root in scope.writable_paths):
            raise EffectLeaseScopeError(
                f"writable path {candidate!r} is outside the leased roots"
            )
    if not set(request.egress_endpoints) <= set(scope.egress_endpoints):
        raise EffectLeaseScopeError("execution requested an unleased egress endpoint")
    if not set(request.tools) <= set(scope.tools):
        raise EffectLeaseScopeError("execution requested an unleased tool")
    if not set(request.secret_refs) <= set(scope.secret_refs):
        raise EffectLeaseScopeError("execution requested an unleased secret")
    if scope.max_cost_microusd is None:
        if request.max_cost_microusd:
            raise EffectLeaseScopeError("execution requested spend from a no-spend lease")
    elif request.max_cost_microusd > scope.max_cost_microusd:
        raise EffectLeaseScopeError("execution requested cost above the leased ceiling")
    if request.kill_switch_ref != scope.kill_switch_ref:
        raise EffectLeaseScopeError("execution kill_switch_ref does not match the lease")
    if request.kill_switch_generation != lease.kill_switch_generation:
        raise EffectLeaseScopeError("execution kill-switch generation is stale")

    write_effects = {Effect.FILESYSTEM_WRITE.value, Effect.REPOSITORY_MUTATION.value}
    network_effects = {Effect.NETWORK_EGRESS.value, Effect.LISTEN_SOCKET.value}
    process_effects = {Effect.PROCESS_SPAWN.value, Effect.PROCESS_CONTROL.value}
    if request.writable_paths and not requested_effects & write_effects:
        raise EffectLeaseScopeError("writable_paths supplied without a write effect")
    if requested_effects & write_effects and not request.writable_paths:
        raise EffectLeaseScopeError("write execution must name its exact writable paths")
    if request.egress_endpoints and not requested_effects & network_effects:
        raise EffectLeaseScopeError("egress_endpoints supplied without a network effect")
    if requested_effects & network_effects and not request.egress_endpoints:
        raise EffectLeaseScopeError("network execution must name its exact endpoint")
    if request.tools and not requested_effects & process_effects:
        raise EffectLeaseScopeError("tools supplied without a process effect")
    if requested_effects & process_effects and not request.tools:
        raise EffectLeaseScopeError("process execution must name its exact tool")
    if request.secret_refs and Effect.SECRETS.value not in requested_effects:
        raise EffectLeaseScopeError("secret_refs supplied without the secrets effect")
    if Effect.SECRETS.value in requested_effects and not request.secret_refs:
        raise EffectLeaseScopeError("secret execution must name its exact secret refs")
    if request.max_cost_microusd and Effect.SPEND.value not in requested_effects:
        raise EffectLeaseScopeError("cost supplied without the spend effect")


def issue_effect_lease(
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    *,
    lease_id: str,
    issuer_key_id: str,
    issued_at: datetime,
    expires_at: datetime,
    secret: bytes | str,
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
) -> EffectLease:
    """Create a signed lease only for an already-central entrypoint."""

    registry_map = _registry_map(registry)
    spec = registry_map.get(request.entrypoint_id)
    if spec is None or spec.id != request.entrypoint_id:
        raise EffectLeaseBindingMismatch("effect lease request names an unknown entrypoint")
    if spec.wiring is not Wiring.CENTRAL:
        raise EffectLeaseBindingMismatch(
            f"{spec.id} is {spec.wiring.value}, not central; migration is required first"
        )
    try:
        wanted = tuple(sorted({Effect(value).value for value in request.requested_effects}))
    except ValueError as exc:
        raise EffectLeaseBindingMismatch("effect lease request contains an unknown effect") from exc
    undeclared = sorted(set(wanted) - {effect.value for effect in spec.effects})
    if undeclared:
        raise EffectLeaseBindingMismatch(
            "entrypoint did not declare requested effects: " + ", ".join(undeclared)
        )
    _scope_requirements(wanted, request.effect_scope)

    if policy_decision.verdict != "allow":
        raise EffectLeaseBindingMismatch("deny policy decisions cannot issue leases")
    if policy_decision.subject_id != request.request_id:
        raise EffectLeaseBindingMismatch("policy subject_id does not match lease request")
    if policy_decision.subject_sha256 != request.digest:
        raise EffectLeaseBindingMismatch("policy subject digest does not match lease request")
    if policy_decision.effect_scope != request.effect_scope:
        raise EffectLeaseBindingMismatch("policy scope does not exactly match lease request")
    if policy_decision.provenance.source_revision != request.provenance.source_revision:
        raise EffectLeaseBindingMismatch("policy and lease request use different revisions")
    if spec.runtime_id:
        if request.runtime_manifest_sha256 is None:
            raise EffectLeaseBindingMismatch(
                "runtime entrypoints require manifest and conformance digests"
            )
    elif request.runtime_manifest_sha256 is not None:
        raise EffectLeaseBindingMismatch(
            "non-runtime entrypoints cannot attach runtime conformance"
        )

    issued = _as_utc(issued_at, "issued_at")
    expires = _as_utc(expires_at, "expires_at")
    if expires <= issued:
        raise ValueError("effect lease expires_at must be after issued_at")
    if expires - issued > _MAX_LEASE_TTL:
        raise ValueError("effect lease TTL exceeds the 24-hour Gate-0 maximum")
    reg_sha = registry_sha256(tuple(registry_map.values()))
    provenance = ContractProvenance(
        origin="kernel.effect-lease",
        source_revision=request.provenance.source_revision,
        created_at=_timestamp(issued),
        input_digests=tuple(
            sorted(
                {
                    request.digest,
                    policy_decision.digest,
                    reg_sha,
                    *(
                        [request.runtime_manifest_sha256, request.runtime_conformance_sha256]
                        if request.runtime_manifest_sha256 is not None
                        else []
                    ),
                }
            )
        ),
        trace_id=request.provenance.trace_id,
    )
    placeholder = EffectLease(
        lease_id=lease_id,
        request_id=request.request_id,
        request_sha256=request.digest,
        policy_decision_id=policy_decision.decision_id,
        policy_decision_sha256=policy_decision.digest,
        registry_sha256=reg_sha,
        entrypoint_id=request.entrypoint_id,
        requested_effects=wanted,
        effect_scope=request.effect_scope,
        idempotency_namespace=request.idempotency_namespace,
        kill_switch_generation=request.kill_switch_generation,
        runtime_id=spec.runtime_id,
        runtime_manifest_sha256=request.runtime_manifest_sha256,
        runtime_conformance_sha256=request.runtime_conformance_sha256,
        issuer_key_id=issuer_key_id,
        issued_at=_timestamp(issued),
        expires_at=_timestamp(expires),
        signature_sha256="0" * 64,
        provenance=provenance,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(placeholder.signing_digest, secret),
    )


def _authenticate_effect_lease_signature(
    lease: EffectLease, keyring: Mapping[str, bytes | str]
) -> None:
    secret = keyring.get(lease.issuer_key_id)
    if secret is None:
        raise EffectLeaseSignatureError("effect lease issuer key is unknown")
    expected_signature = _signature(lease.signing_digest, secret)
    if not hmac.compare_digest(lease.signature_sha256, expected_signature):
        raise EffectLeaseSignatureError("effect lease signature mismatch")


def _validate_effect_lease_contract_bindings(
    lease: EffectLease,
    *,
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    check_runtime_id: bool = False,
    expected_runtime_id: str = "",
) -> None:
    comparisons = {
        "request_id": (lease.request_id, request.request_id),
        "request_sha256": (lease.request_sha256, request.digest),
        "policy_decision_id": (lease.policy_decision_id, policy_decision.decision_id),
        "policy_decision_sha256": (lease.policy_decision_sha256, policy_decision.digest),
        "entrypoint_id": (lease.entrypoint_id, request.entrypoint_id),
        "requested_effects": (lease.requested_effects, request.requested_effects),
        "effect_scope": (lease.effect_scope, request.effect_scope),
        "idempotency_namespace": (
            lease.idempotency_namespace,
            request.idempotency_namespace,
        ),
        "kill_switch_generation": (
            lease.kill_switch_generation,
            request.kill_switch_generation,
        ),
        "runtime_manifest_sha256": (
            lease.runtime_manifest_sha256,
            request.runtime_manifest_sha256,
        ),
        "runtime_conformance_sha256": (
            lease.runtime_conformance_sha256,
            request.runtime_conformance_sha256,
        ),
        "policy_subject_id": (policy_decision.subject_id, request.request_id),
        "policy_subject_sha256": (policy_decision.subject_sha256, request.digest),
        "policy_verdict": (policy_decision.verdict, "allow"),
        "policy_effect_scope": (policy_decision.effect_scope, request.effect_scope),
        "lease_source_revision": (
            lease.provenance.source_revision,
            request.provenance.source_revision,
        ),
        "policy_source_revision": (
            policy_decision.provenance.source_revision,
            request.provenance.source_revision,
        ),
    }
    if check_runtime_id:
        comparisons["runtime_id"] = (lease.runtime_id, expected_runtime_id)
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise EffectLeaseBindingMismatch(
            "effect lease binding mismatch: " + ", ".join(mismatches)
        )


def _authenticate_effect_lease_contracts(
    lease: EffectLease,
    *,
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    keyring: Mapping[str, bytes | str],
) -> None:
    """Authenticate immutable bindings without checking current start state.

    A persisted execution replay is an inert read of an already-started effect,
    so expiry, revocation, guard decisions, registry drift, and a later kill-
    switch generation must not turn recovery into a second effect.  The HMAC
    and every signed contract binding still have to authenticate first.
    """

    _authenticate_effect_lease_signature(lease, keyring)
    _scope_requirements(lease.requested_effects, lease.effect_scope)
    _validate_effect_lease_contract_bindings(
        lease,
        request=request,
        policy_decision=policy_decision,
    )


def verify_effect_lease(
    lease: EffectLease,
    *,
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    keyring: Mapping[str, bytes | str],
    current_kill_switch_generation: int,
    now: datetime | None = None,
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
) -> None:
    """Authenticate a lease and verify every current-world start condition."""

    _authenticate_effect_lease_signature(lease, keyring)
    instant = _as_utc(now, "now") if now is not None else _utc_now()
    issued = _parse_utc(lease.issued_at, "lease.issued_at")
    expires = _parse_utc(lease.expires_at, "lease.expires_at")
    if instant < issued:
        raise EffectLeaseExpired("effect lease is not valid yet")
    if instant >= expires:
        raise EffectLeaseExpired("effect lease has expired")
    if current_kill_switch_generation != lease.kill_switch_generation:
        raise EffectLeaseBindingMismatch("effect lease kill-switch generation is stale")

    _scope_requirements(lease.requested_effects, lease.effect_scope)
    registry_map = _registry_map(registry)
    spec = registry_map.get(lease.entrypoint_id)
    if spec is None or spec.wiring is not Wiring.CENTRAL:
        raise EffectLeaseBindingMismatch("leased entrypoint is not currently central")
    if registry_sha256(tuple(registry_map.values())) != lease.registry_sha256:
        raise EffectLeaseBindingMismatch("entrypoint registry changed after lease issuance")
    _validate_effect_lease_contract_bindings(
        lease,
        request=request,
        policy_decision=policy_decision,
        check_runtime_id=True,
        expected_runtime_id=spec.runtime_id,
    )


def _authenticate_persisted_grant(
    row: sqlite3.Row,
    *,
    lease: EffectLease,
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
) -> None:
    """Require the SQLite grant row to be byte-identical to its HMAC grant."""

    expected = {
        "lease_sha256": lease.digest,
        "lease_id": lease.lease_id,
        "request_sha256": request.digest,
        "request_json": request.to_json(),
        "policy_decision_sha256": policy_decision.digest,
        "policy_decision_json": policy_decision.to_json(),
        "registry_sha256": lease.registry_sha256,
        "entrypoint_id": lease.entrypoint_id,
        "lease_json": lease.to_json(),
        "issued_at": lease.issued_at,
        "expires_at": lease.expires_at,
    }
    mismatches = sorted(
        name for name, value in expected.items() if row[name] != value
    )
    if mismatches:
        raise EffectLeaseStateError(
            "persisted effect grant failed exact identity checks: "
            + ", ".join(mismatches)
        )


def _authenticated_replay_start(
    row: sqlite3.Row,
    *,
    lease: EffectLease,
    execution: EffectExecutionRequest,
    request_json: str,
    keyring: Mapping[str, bytes | str],
) -> EffectStartResult:
    """Authenticate one persisted execution before returning an inert replay."""

    identity_mismatches = sorted(
        name
        for name, actual, expected in (
            ("lease_sha256", row["lease_sha256"], lease.digest),
            ("execution_id", row["execution_id"], execution.execution_id),
            ("idempotency_key", row["idempotency_key"], execution.idempotency_key),
            ("request_sha256", row["request_sha256"], execution.digest),
        )
        if actual != expected
    )
    if identity_mismatches:
        raise EffectLeaseReplay(
            "execution identity or idempotency key was reused across a "
            "different lease or scope: " + ", ".join(identity_mismatches)
        )
    if row["request_json"] != request_json:
        raise EffectLeaseStateError(
            "persisted execution request bytes do not match its authenticated digest"
        )

    try:
        payload = json.loads(row["start_receipt_json"])
        if not isinstance(payload, dict):
            raise ValueError("start receipt JSON must contain an object")
        receipt = LeasedEffectStartReceipt(**payload)
    except (
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        EffectLeaseBindingMismatch,
    ) as exc:
        raise EffectLeaseStateError(
            "persisted replay contains invalid start receipt bytes"
        ) from exc

    receipt_mismatches = []
    if canonical_json(receipt.to_dict()) != row["start_receipt_json"]:
        receipt_mismatches.append("start_receipt_json")
    if receipt.receipt_sha256 != row["start_receipt_sha256"]:
        receipt_mismatches.append("start_receipt_sha256")
    if receipt.lease_sha256 != lease.digest:
        receipt_mismatches.append("receipt_lease_sha256")
    if receipt.execution_id != execution.execution_id:
        receipt_mismatches.append("receipt_execution_id")
    if receipt.idempotency_key != execution.idempotency_key:
        receipt_mismatches.append("receipt_idempotency_key")
    if receipt.execution_request_sha256 != execution.digest:
        receipt_mismatches.append("receipt_request_sha256")
    if receipt.started_at != row["started_at"]:
        receipt_mismatches.append("started_at")
    if receipt_mismatches:
        raise EffectLeaseStateError(
            "persisted replay failed exact start identity checks: "
            + ", ".join(sorted(receipt_mismatches))
        )
    _authenticate_start_receipt(receipt, lease=lease, keyring=keyring)
    return EffectStartResult(
        receipt=receipt,
        execute=False,
        completion_capability=None,
    )


def _load_persisted_execution_claim(
    row: sqlite3.Row,
    *,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    lease: EffectLease | None = None,
    historical_keyring: Mapping[str, bytes | str] | None = None,
) -> EffectExecutionClaimReceipt | None:
    """Validate exact persisted claim bytes and optionally their issuer HMAC."""

    claim_fields = (
        "claimed_at",
        "claim_receipt_sha256",
        "claim_receipt_json",
    )
    present = tuple(row[name] is not None for name in claim_fields)
    if not any(present):
        return None
    if not all(present):
        raise EffectLeaseStateError(
            "persisted effect execution contains a partial execution claim"
        )
    try:
        payload = json.loads(row["claim_receipt_json"])
        if not isinstance(payload, dict):
            raise ValueError("execution claim JSON must contain an object")
        claim = EffectExecutionClaimReceipt(**payload)
    except (
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        EffectLeaseBindingMismatch,
    ) as exc:
        raise EffectLeaseStateError(
            "persisted effect execution contains invalid claim bytes"
        ) from exc

    mismatches = sorted(
        name
        for name, actual, expected in (
            (
                "claim_receipt_json",
                row["claim_receipt_json"],
                canonical_json(claim.to_dict()),
            ),
            (
                "claim_receipt_sha256",
                row["claim_receipt_sha256"],
                claim.receipt_sha256,
            ),
            ("claimed_at", row["claimed_at"], claim.claimed_at),
            ("lease_sha256", claim.lease_sha256, start_receipt.lease_sha256),
            ("issuer_key_id", claim.issuer_key_id, start_receipt.issuer_key_id),
            ("execution_id", claim.execution_id, execution.execution_id),
            (
                "execution_request_sha256",
                claim.execution_request_sha256,
                execution.digest,
            ),
            (
                "start_receipt_sha256",
                claim.start_receipt_sha256,
                start_receipt.receipt_sha256,
            ),
        )
        if actual != expected
    )
    if lease is not None:
        if claim.lease_sha256 != lease.digest:
            mismatches.append("historical_lease_sha256")
        if claim.issuer_key_id != lease.issuer_key_id:
            mismatches.append("issuer_key_id")
    if mismatches:
        raise EffectLeaseStateError(
            "persisted effect execution failed claim identity checks: "
            + ", ".join(sorted(set(mismatches)))
        )
    if _parse_utc(claim.claimed_at, "claim.claimed_at") < _parse_utc(
        start_receipt.started_at, "start.started_at"
    ):
        raise EffectLeaseStateError("execution claim predates its persisted start")
    if (lease is None) != (historical_keyring is None):
        raise TypeError(
            "lease and historical_keyring must be supplied together for "
            "claim authentication"
        )
    if lease is not None and historical_keyring is not None:
        _authenticate_execution_claim_receipt(
            claim, lease=lease, keyring=historical_keyring
        )
    return claim


def _load_persisted_publication_commit(
    row: sqlite3.Row,
    *,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    claim_receipt: EffectExecutionClaimReceipt | None,
    lease: EffectLease | None = None,
    historical_keyring: Mapping[str, bytes | str] | None = None,
) -> EffectPublicationCommitReceipt | None:
    fields = (
        "committed_at",
        "publication_commit_receipt_sha256",
        "publication_commit_receipt_json",
    )
    present = tuple(row[name] is not None for name in fields)
    if not any(present):
        return None
    if not all(present):
        raise EffectLeaseStateError(
            "persisted execution contains a partial publication commit"
        )
    if claim_receipt is None:
        raise EffectLeaseStateError(
            "publication commit is missing its execution claim"
        )
    try:
        payload = json.loads(row["publication_commit_receipt_json"])
        if not isinstance(payload, dict):
            raise ValueError("publication commit JSON must contain an object")
        commit = EffectPublicationCommitReceipt(**payload)
    except (
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        EffectLeaseBindingMismatch,
    ) as exc:
        raise EffectLeaseStateError(
            "persisted execution contains invalid publication commit bytes"
        ) from exc
    mismatches = sorted(
        name
        for name, actual, expected in (
            (
                "publication_commit_receipt_json",
                row["publication_commit_receipt_json"],
                canonical_json(commit.to_dict()),
            ),
            (
                "publication_commit_receipt_sha256",
                row["publication_commit_receipt_sha256"],
                commit.receipt_sha256,
            ),
            ("committed_at", row["committed_at"], commit.committed_at),
            ("lease_sha256", commit.lease_sha256, start_receipt.lease_sha256),
            ("issuer_key_id", commit.issuer_key_id, start_receipt.issuer_key_id),
            ("execution_id", commit.execution_id, execution.execution_id),
            (
                "execution_request_sha256",
                commit.execution_request_sha256,
                execution.digest,
            ),
            (
                "start_receipt_sha256",
                commit.start_receipt_sha256,
                start_receipt.receipt_sha256,
            ),
            (
                "claim_receipt_sha256",
                commit.claim_receipt_sha256,
                claim_receipt.receipt_sha256,
            ),
        )
        if actual != expected
    )
    if lease is not None:
        if commit.lease_sha256 != lease.digest:
            mismatches.append("historical_lease_sha256")
        if commit.issuer_key_id != lease.issuer_key_id:
            mismatches.append("issuer_key_id")
    if mismatches:
        raise EffectLeaseStateError(
            "persisted execution failed publication commit identity checks: "
            + ", ".join(sorted(set(mismatches)))
        )
    started = _parse_utc(start_receipt.started_at, "start.started_at")
    claimed = _parse_utc(claim_receipt.claimed_at, "claim.claimed_at")
    committed = _parse_utc(commit.committed_at, "commit.committed_at")
    if not started <= claimed <= committed:
        raise EffectLeaseStateError(
            "publication commit violates start <= claim <= commit ordering"
        )
    if (lease is None) != (historical_keyring is None):
        raise TypeError(
            "lease and historical_keyring must be supplied together for "
            "publication commit authentication"
        )
    if lease is not None and historical_keyring is not None:
        _authenticate_publication_commit_receipt(
            commit, lease=lease, keyring=historical_keyring
        )
    return commit


def _load_persisted_publication_outcome(
    row: sqlite3.Row,
    *,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    claim_receipt: EffectExecutionClaimReceipt | None,
    commit_receipt: EffectPublicationCommitReceipt | None,
    lease: EffectLease | None = None,
    historical_keyring: Mapping[str, bytes | str] | None = None,
) -> EffectPublicationOutcomeReceipt | None:
    fields = (
        "published_at",
        "publication_outcome_receipt_sha256",
        "publication_outcome_receipt_json",
    )
    present = tuple(row[name] is not None for name in fields)
    if not any(present):
        return None
    if not all(present):
        raise EffectLeaseStateError(
            "persisted execution contains a partial publication outcome"
        )
    if claim_receipt is None or commit_receipt is None:
        raise EffectLeaseStateError(
            "publication outcome is missing its claim or commit"
        )
    try:
        payload = json.loads(row["publication_outcome_receipt_json"])
        if not isinstance(payload, dict):
            raise ValueError("publication outcome JSON must contain an object")
        outcome = EffectPublicationOutcomeReceipt(**payload)
    except (
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        EffectLeaseBindingMismatch,
    ) as exc:
        raise EffectLeaseStateError(
            "persisted execution contains invalid publication outcome bytes"
        ) from exc
    mismatches = sorted(
        name
        for name, actual, expected in (
            (
                "publication_outcome_receipt_json",
                row["publication_outcome_receipt_json"],
                canonical_json(outcome.to_dict()),
            ),
            (
                "publication_outcome_receipt_sha256",
                row["publication_outcome_receipt_sha256"],
                outcome.receipt_sha256,
            ),
            ("published_at", row["published_at"], outcome.published_at),
            ("lease_sha256", outcome.lease_sha256, start_receipt.lease_sha256),
            ("execution_id", outcome.execution_id, execution.execution_id),
            (
                "execution_request_sha256",
                outcome.execution_request_sha256,
                execution.digest,
            ),
            (
                "start_receipt_sha256",
                outcome.start_receipt_sha256,
                start_receipt.receipt_sha256,
            ),
            (
                "claim_receipt_sha256",
                outcome.claim_receipt_sha256,
                claim_receipt.receipt_sha256,
            ),
            (
                "publication_commit_receipt_sha256",
                outcome.publication_commit_receipt_sha256,
                commit_receipt.receipt_sha256,
            ),
            (
                "effect_commitment_sha256",
                outcome.effect_commitment_sha256,
                commit_receipt.effect_commitment_sha256,
            ),
        )
        if actual != expected
    )
    if mismatches:
        raise EffectLeaseStateError(
            "persisted execution failed publication outcome identity checks: "
            + ", ".join(sorted(set(mismatches)))
        )
    committed = _parse_utc(commit_receipt.committed_at, "commit.committed_at")
    published = _parse_utc(outcome.published_at, "outcome.published_at")
    if published < committed:
        raise EffectLeaseStateError(
            "publication outcome predates its durable commit"
        )
    if (lease is None) != (historical_keyring is None):
        raise TypeError(
            "lease and historical_keyring must be supplied together for "
            "publication outcome authentication"
        )
    if lease is not None and historical_keyring is not None:
        outcome_audit_key = _publication_outcome_audit_key_for_commit(
            commit_receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        expected_signature = _publication_outcome_signature(
            outcome.signing_dict(), outcome_audit_key
        )
        if not hmac.compare_digest(
            expected_signature, outcome.signature_sha256
        ):
            raise EffectLeaseSignatureError(
                "publication outcome signature mismatch"
            )
    return outcome


class EffectLeaseLedger:
    """SQLite authority for grants, starts, replay, revocation and terminals."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS effect_leases (
                    lease_sha256 TEXT PRIMARY KEY,
                    lease_id TEXT NOT NULL UNIQUE,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    policy_decision_sha256 TEXT NOT NULL,
                    policy_decision_json TEXT NOT NULL,
                    registry_sha256 TEXT NOT NULL,
                    entrypoint_id TEXT NOT NULL,
                    lease_json TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    revocation_reason TEXT
                )
                """
            )
            # Revision-safe additive migration for Gate-0 databases created by
            # the first lease packet.  Old rows remain readable as historical
            # evidence but cannot be reconstructed until an authenticated,
            # byte-identical `grant()` supplies the missing contracts.
            lease_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(effect_leases)")
            }
            if "request_json" not in lease_columns:
                conn.execute("ALTER TABLE effect_leases ADD COLUMN request_json TEXT")
            if "policy_decision_json" not in lease_columns:
                conn.execute(
                    "ALTER TABLE effect_leases ADD COLUMN policy_decision_json TEXT"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS effect_executions (
                    execution_id TEXT PRIMARY KEY,
                    lease_sha256 TEXT NOT NULL REFERENCES effect_leases(lease_sha256),
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    start_receipt_sha256 TEXT NOT NULL UNIQUE,
                    start_receipt_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    claimed_at TEXT,
                    claim_receipt_sha256 TEXT,
                    claim_receipt_json TEXT,
                    committed_at TEXT,
                    publication_commit_receipt_sha256 TEXT,
                    publication_commit_receipt_json TEXT,
                    published_at TEXT,
                    publication_outcome_receipt_sha256 TEXT,
                    publication_outcome_receipt_json TEXT,
                    finished_at TEXT,
                    terminal_receipt_sha256 TEXT UNIQUE,
                    terminal_receipt_json TEXT,
                    UNIQUE(lease_sha256, idempotency_key)
                )
                """
            )
            execution_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(effect_executions)")
            }
            for column in (
                "claimed_at",
                "claim_receipt_sha256",
                "claim_receipt_json",
                "committed_at",
                "publication_commit_receipt_sha256",
                "publication_commit_receipt_json",
                "published_at",
                "publication_outcome_receipt_sha256",
                "publication_outcome_receipt_json",
            ):
                if column not in execution_columns:
                    conn.execute(
                        f"ALTER TABLE effect_executions ADD COLUMN {column} TEXT"
                    )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_effect_executions_claim_receipt "
                "ON effect_executions(claim_receipt_sha256) "
                "WHERE claim_receipt_sha256 IS NOT NULL"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_effect_executions_publication_commit_receipt "
                "ON effect_executions(publication_commit_receipt_sha256) "
                "WHERE publication_commit_receipt_sha256 IS NOT NULL"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_effect_executions_publication_outcome_receipt "
                "ON effect_executions(publication_outcome_receipt_sha256) "
                "WHERE publication_outcome_receipt_sha256 IS NOT NULL"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_effect_executions_active "
                "ON effect_executions(lease_sha256, state)"
            )
            # Reconciliation is not a second ledger.  The signed operator
            # decision and nonce are consumed in the same SQLite authority and
            # transaction that closes one STARTED execution.  Claimed or
            # committing effects require a future fenced-orphan protocol.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS effect_reconciliations (
                    decision_sha256 TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL UNIQUE,
                    nonce TEXT NOT NULL UNIQUE,
                    execution_id TEXT NOT NULL UNIQUE
                        REFERENCES effect_executions(execution_id),
                    operator_id TEXT NOT NULL,
                    operator_key_id TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    terminal_receipt_sha256 TEXT NOT NULL,
                    reconciled_at TEXT NOT NULL
                )
                """
            )

    def grant(
        self,
        lease: EffectLease,
        *,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        keyring: Mapping[str, bytes | str],
        current_kill_switch_generation: int,
        granted_at: datetime | None = None,
        registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
    ) -> None:
        verify_effect_lease(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=keyring,
            current_kill_switch_generation=current_kill_switch_generation,
            now=granted_at or _utc_now(),
            registry=registry,
        )
        payload = lease.to_json()
        request_payload = request.to_json()
        policy_payload = policy_decision.to_json()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT lease_json, request_json, policy_decision_json
                FROM effect_leases WHERE lease_sha256=? OR lease_id=?
                """,
                (lease.digest, lease.lease_id),
            ).fetchone()
            if row is not None:
                if row["lease_json"] != payload:
                    raise EffectLeaseReplay(
                        "lease identity was already used for different content"
                    )
                if row["request_json"] not in (None, request_payload):
                    raise EffectLeaseReplay(
                        "persisted lease request bytes do not match the authenticated grant"
                    )
                if row["policy_decision_json"] not in (None, policy_payload):
                    raise EffectLeaseReplay(
                        "persisted policy bytes do not match the authenticated grant"
                    )
                # Backfill only after full lease verification above.  This is
                # the one safe migration for a pre-recovery row: the supplied
                # request and policy are the exact contracts bound by the
                # authenticated lease.
                conn.execute(
                    """
                    UPDATE effect_leases
                    SET request_json=COALESCE(request_json, ?),
                        policy_decision_json=COALESCE(policy_decision_json, ?)
                    WHERE lease_sha256=?
                    """,
                    (request_payload, policy_payload, lease.digest),
                )
                conn.execute("COMMIT")
                return
            conn.execute(
                """
                INSERT INTO effect_leases (
                    lease_sha256, lease_id, request_sha256, request_json,
                    policy_decision_sha256, policy_decision_json,
                    registry_sha256, entrypoint_id,
                    lease_json, issued_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease.digest,
                    lease.lease_id,
                    lease.request_sha256,
                    request_payload,
                    lease.policy_decision_sha256,
                    policy_payload,
                    lease.registry_sha256,
                    lease.entrypoint_id,
                    payload,
                    lease.issued_at,
                    lease.expires_at,
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise EffectLeaseReplay("effect lease grant conflicts with persisted identity") from exc
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def load_grant(
        self,
        lease_sha256: str,
        *,
        keyring: Mapping[str, bytes | str],
        current_kill_switch_generation: int,
        now: datetime | None = None,
        registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
    ) -> PersistedEffectGrant:
        """Reload and re-authenticate the exact contracts behind one grant.

        This is the restart seam.  Key material is supplied by the composition
        root and is never recovered from SQLite.  Expired or stale-generation
        grants are intentionally refused here; their historical executions
        remain inspectable through :meth:`execution_record`.
        """

        digest = _sha256(lease_sha256, "lease_sha256")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT lease_json, request_json, policy_decision_json,
                       request_sha256, policy_decision_sha256,
                       revoked_at, revocation_reason
                FROM effect_leases WHERE lease_sha256=?
                """,
                (digest,),
            ).fetchone()
        if row is None:
            raise EffectLeaseStateError("unknown persisted effect lease")
        if row["request_json"] is None or row["policy_decision_json"] is None:
            raise EffectLeaseStateError(
                "persisted effect lease predates recoverable request/policy metadata"
            )

        try:
            lease_payload = json.loads(row["lease_json"])
            request_payload = json.loads(row["request_json"])
            policy_payload = json.loads(row["policy_decision_json"])
            if not all(
                isinstance(value, dict)
                for value in (lease_payload, request_payload, policy_payload)
            ):
                raise ValueError("persisted contract JSON must contain objects")
            lease = EffectLease.from_dict(lease_payload)
            request = EffectLeaseRequest.from_dict(request_payload)
            policy = PolicyDecision.from_dict(policy_payload)
        except (
            TypeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            EffectLeaseBindingMismatch,
        ) as exc:
            raise EffectLeaseStateError(
                "persisted effect grant contains invalid contract bytes"
            ) from exc

        canonical_mismatches = []
        if lease.to_json() != row["lease_json"] or lease.digest != digest:
            canonical_mismatches.append("lease")
        if (
            request.to_json() != row["request_json"]
            or request.digest != row["request_sha256"]
        ):
            canonical_mismatches.append("request")
        if (
            policy.to_json() != row["policy_decision_json"]
            or policy.digest != row["policy_decision_sha256"]
        ):
            canonical_mismatches.append("policy")
        if canonical_mismatches:
            raise EffectLeaseStateError(
                "persisted effect grant failed canonical identity checks: "
                + ", ".join(canonical_mismatches)
            )

        verify_effect_lease(
            lease,
            request=request,
            policy_decision=policy,
            keyring=keyring,
            current_kill_switch_generation=current_kill_switch_generation,
            now=now or _utc_now(),
            registry=registry,
        )
        return PersistedEffectGrant(
            lease=lease,
            request=request,
            policy_decision=policy,
            revoked_at=row["revoked_at"],
            revocation_reason=row["revocation_reason"],
        )

    def revoke(self, lease_sha256: str, *, reason: str, revoked_at: datetime | None = None) -> None:
        digest = _sha256(lease_sha256, "lease_sha256")
        if not reason.strip() or len(reason) > 1000:
            raise ValueError("revocation reason must be non-empty and bounded")
        timestamp = _timestamp(revoked_at or _utc_now())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT revoked_at FROM effect_leases WHERE lease_sha256=?", (digest,)
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError("cannot revoke an unknown lease")
            if row["revoked_at"] is not None:
                raise EffectLeaseStateError("effect lease is already revoked")
            conn.execute(
                "UPDATE effect_leases SET revoked_at=?, revocation_reason=? WHERE lease_sha256=?",
                (timestamp, reason, digest),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def begin(
        self,
        lease: EffectLease,
        execution: EffectExecutionRequest,
        *,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        keyring: Mapping[str, bytes | str],
        guard_decisions: Iterable[GuardDecision],
        current_kill_switch_generation: int,
        started_at: datetime | None = None,
        registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
    ) -> EffectStartResult:
        verification_instant = _as_utc(started_at, "started_at") if started_at is not None else _utc_now()
        _authenticate_effect_lease_contracts(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=keyring,
        )
        _validate_narrowed_scope(execution, lease)
        request_json = canonical_json(execution.to_dict())

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            lease_row = conn.execute(
                """
                SELECT lease_sha256, lease_id, request_sha256, request_json,
                       policy_decision_sha256, policy_decision_json,
                       registry_sha256, entrypoint_id, lease_json,
                       issued_at, expires_at, revoked_at
                FROM effect_leases WHERE lease_sha256=?
                """,
                (lease.digest,),
            ).fetchone()
            if lease_row is None:
                raise EffectLeaseStateError("effect lease was not persisted before start")
            _authenticate_persisted_grant(
                lease_row,
                lease=lease,
                request=request,
                policy_decision=policy_decision,
            )
            existing = conn.execute(
                """
                SELECT execution_id, lease_sha256, idempotency_key,
                       request_sha256, request_json,
                       start_receipt_sha256, start_receipt_json, started_at
                FROM effect_executions
                WHERE execution_id=? OR (lease_sha256=? AND idempotency_key=?)
                """,
                (execution.execution_id, lease.digest, execution.idempotency_key),
            ).fetchone()
            if existing is not None:
                replay = _authenticated_replay_start(
                    existing,
                    lease=lease,
                    execution=execution,
                    request_json=request_json,
                    keyring=keyring,
                )
                conn.execute("COMMIT")
                return replay

            # Only a new external effect reaches current-world authorization.
            # An exact replay above is already durable and is therefore an
            # inert recovery read, not another effect start.
            verify_effect_lease(
                lease,
                request=request,
                policy_decision=policy_decision,
                keyring=keyring,
                current_kill_switch_generation=current_kill_switch_generation,
                now=verification_instant,
                registry=registry,
            )
            registry_map = _registry_map(registry)
            boundary = begin_effect(
                lease.entrypoint_id,
                execution.requested_effects,
                guard_decisions,
                registry=registry_map,
            )
            if lease_row["revoked_at"] is not None:
                raise EffectLeaseStateError("effect lease is revoked")
            persistence_instant = (
                verification_instant if started_at is not None else _utc_now()
            )
            if persistence_instant >= _parse_utc(
                lease_row["expires_at"], "persisted lease expiry"
            ):
                raise EffectLeaseExpired("persisted effect lease expired before start")
            active = conn.execute(
                "SELECT COUNT(*) FROM effect_executions "
                "WHERE lease_sha256=? "
                "AND state IN ('STARTED', 'EXECUTING', 'COMMITTING')",
                (lease.digest,),
            ).fetchone()[0]
            if active >= lease.effect_scope.max_concurrency:
                raise EffectLeaseConcurrencyError("effect lease concurrency ceiling reached")
            capability_secret = secrets.token_bytes(32)
            payload = {
                "lease_sha256": lease.digest,
                "issuer_key_id": lease.issuer_key_id,
                "execution_id": execution.execution_id,
                "idempotency_key": execution.idempotency_key,
                "execution_request_sha256": execution.digest,
                "boundary_receipt_sha256": boundary.receipt_sha256,
                "completion_capability_sha256": (
                    _completion_capability_sha256(capability_secret)
                ),
                "started_at": _timestamp(persistence_instant),
            }
            issuer_secret = keyring.get(lease.issuer_key_id)
            if issuer_secret is None:  # authenticated above; keep mutation fail closed
                raise EffectLeaseSignatureError(
                    "effect lease issuer key disappeared before start persistence"
                )
            signature_sha256 = _start_receipt_signature(payload, issuer_secret)
            authenticated_payload = {
                **payload,
                "signature_sha256": signature_sha256,
            }
            receipt = LeasedEffectStartReceipt(
                receipt_sha256=canonical_sha(authenticated_payload),
                **authenticated_payload,
            )
            completion_capability = CompletionCapability(
                start_receipt=receipt,
                secret=capability_secret,
                _mint_token=_COMPLETION_CAPABILITY_MINT_TOKEN,
            )
            receipt_json = canonical_json(receipt.to_dict())
            conn.execute(
                """
                INSERT INTO effect_executions (
                    execution_id, lease_sha256, idempotency_key,
                    request_sha256, request_json, start_receipt_sha256,
                    start_receipt_json, state, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'STARTED', ?)
                """,
                (
                    execution.execution_id,
                    lease.digest,
                    execution.idempotency_key,
                    execution.digest,
                    request_json,
                    receipt.receipt_sha256,
                    receipt_json,
                    receipt.started_at,
                ),
            )
            conn.execute("COMMIT")
            return EffectStartResult(
                receipt=receipt,
                execute=True,
                completion_capability=completion_capability,
            )
        except sqlite3.IntegrityError as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise EffectLeaseReplay("effect execution identity was already consumed") from exc
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def claim_execution(
        self,
        start: EffectStartResult,
        execution: EffectExecutionRequest,
        *,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
        claimed_at: datetime | None = None,
    ) -> EffectExecutionClaim:
        """Atomically claim one exact fresh start before any external effect.

        The successful ``STARTED -> EXECUTING`` transaction commits only a
        capability digest and an issuer-HMAC receipt.  The corresponding live
        secret is returned once and is never written to SQLite.  A retry after
        an indeterminate commit therefore cannot mint replacement authority.
        """

        if type(start) is not EffectStartResult:
            raise TypeError("start must be an exact EffectStartResult")
        if (
            not start.execute
            or type(start.completion_capability) is not CompletionCapability
        ):
            raise EffectLeaseStateError(
                "execution claim requires one newly persisted live start"
            )
        if type(execution) is not EffectExecutionRequest:
            raise TypeError("execution must be an exact EffectExecutionRequest")
        _authenticate_effect_lease_contracts(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=historical_keyring,
        )
        _validate_narrowed_scope(execution, lease)
        start.completion_capability.verify_start_receipt(start.receipt)
        _authenticate_start_receipt(
            start.receipt, lease=lease, keyring=historical_keyring
        )
        supplied_claim_instant = (
            _as_utc(claimed_at, "claimed_at")
            if claimed_at is not None
            else None
        )

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # For live callers, sample the wall clock only after acquiring the
            # writer lock.  Otherwise lock contention could let a claim commit
            # after lease expiry while carrying a stale pre-lock timestamp.
            claim_instant = supplied_claim_instant or _utc_now()
            row = conn.execute(
                """
                SELECT execution_id, lease_sha256, idempotency_key,
                       request_sha256, request_json, start_receipt_sha256,
                       start_receipt_json, state, started_at, claimed_at,
                       claim_receipt_sha256, claim_receipt_json, committed_at,
                       publication_commit_receipt_sha256,
                       publication_commit_receipt_json, published_at,
                       publication_outcome_receipt_sha256,
                       publication_outcome_receipt_json, finished_at,
                       terminal_receipt_sha256, terminal_receipt_json
                FROM effect_executions WHERE execution_id=? AND lease_sha256=?
                """,
                (execution.execution_id, lease.digest),
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError("unknown effect execution")
            grant_row = conn.execute(
                """
                SELECT lease_sha256, lease_id, request_sha256, request_json,
                       policy_decision_sha256, policy_decision_json,
                       registry_sha256, entrypoint_id, lease_json,
                       issued_at, expires_at, revoked_at, revocation_reason
                FROM effect_leases WHERE lease_sha256=?
                """,
                (lease.digest,),
            ).fetchone()
            if grant_row is None:
                raise EffectLeaseStateError(
                    "effect execution is missing its historical grant"
                )
            _authenticate_persisted_grant(
                grant_row,
                lease=lease,
                request=request,
                policy_decision=policy_decision,
            )
            persisted_start = _authenticated_replay_start(
                row,
                lease=lease,
                execution=execution,
                request_json=canonical_json(execution.to_dict()),
                keyring=historical_keyring,
            ).receipt
            if persisted_start != start.receipt:
                raise EffectLeaseStateError(
                    "execution claim start differs from persisted authority"
                )
            persisted_claim = _load_persisted_execution_claim(
                row,
                execution=execution,
                start_receipt=persisted_start,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            state = str(row["state"])
            if state != "STARTED":
                if state == "EXECUTING" and persisted_claim is not None:
                    raise EffectLeaseStateError(
                        "effect execution is already claimed and requires "
                        "terminalization or reconciliation"
                    )
                raise EffectLeaseStateError(
                    f"execution claim requires STARTED, got {state!r}"
                )
            if persisted_claim is not None:
                raise EffectLeaseStateError(
                    "STARTED execution unexpectedly carries claim fields"
                )
            if any(
                row[name] is not None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "STARTED execution unexpectedly carries terminal fields"
                )
            if grant_row["revoked_at"] is not None:
                raise EffectLeaseStateError(
                    "effect lease was revoked before execution claim"
                )
            if claim_instant >= _parse_utc(
                grant_row["expires_at"], "persisted lease expiry"
            ):
                raise EffectLeaseExpired(
                    "persisted effect lease expired before execution claim"
                )
            if claim_instant < _parse_utc(
                persisted_start.started_at, "start.started_at"
            ):
                raise EffectLeaseStateError(
                    "execution claim predates its persisted start"
                )

            claim_secret = secrets.token_bytes(32)
            claim_payload = {
                "lease_sha256": lease.digest,
                "issuer_key_id": lease.issuer_key_id,
                "execution_id": execution.execution_id,
                "execution_request_sha256": execution.digest,
                "start_receipt_sha256": persisted_start.receipt_sha256,
                "claim_capability_sha256": (
                    _claim_completion_capability_sha256(claim_secret)
                ),
                "claimed_at": _timestamp(claim_instant),
            }
            issuer_secret = historical_keyring.get(lease.issuer_key_id)
            if issuer_secret is None:
                raise EffectLeaseSignatureError(
                    "effect lease issuer key disappeared before claim persistence"
                )
            claim_signature = _execution_claim_signature(
                claim_payload, issuer_secret
            )
            authenticated_claim = {
                **claim_payload,
                "signature_sha256": claim_signature,
            }
            claim_receipt = EffectExecutionClaimReceipt(
                **authenticated_claim,
                receipt_sha256=canonical_sha(authenticated_claim),
            )
            updated = conn.execute(
                """
                UPDATE effect_executions
                SET state='EXECUTING', claimed_at=?, claim_receipt_sha256=?,
                    claim_receipt_json=?
                WHERE execution_id=? AND lease_sha256=? AND state='STARTED'
                  AND request_sha256=? AND start_receipt_sha256=?
                  AND claimed_at IS NULL AND claim_receipt_sha256 IS NULL
                  AND claim_receipt_json IS NULL AND finished_at IS NULL
                  AND committed_at IS NULL
                  AND publication_commit_receipt_sha256 IS NULL
                  AND publication_commit_receipt_json IS NULL
                  AND published_at IS NULL
                  AND publication_outcome_receipt_sha256 IS NULL
                  AND publication_outcome_receipt_json IS NULL
                  AND terminal_receipt_sha256 IS NULL
                  AND terminal_receipt_json IS NULL
                """,
                (
                    claim_receipt.claimed_at,
                    claim_receipt.receipt_sha256,
                    canonical_json(claim_receipt.to_dict()),
                    execution.execution_id,
                    lease.digest,
                    execution.digest,
                    persisted_start.receipt_sha256,
                ),
            )
            if updated.rowcount != 1:
                raise EffectLeaseStateError(
                    "effect execution changed while claim held the ledger lock"
                )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            if conn is not None:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise EffectLeaseReplay(
                "execution claim conflicts with persisted identity"
            ) from exc
        except Exception:
            if conn is not None:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        finally:
            conn.close()

        claim_capability = ClaimCompletionCapability(
            start_receipt=persisted_start,
            claim_receipt=claim_receipt,
            secret=claim_secret,
            _mint_token=_CLAIM_COMPLETION_CAPABILITY_MINT_TOKEN,
        )
        return EffectExecutionClaim(
            start_receipt=persisted_start,
            claim_receipt=claim_receipt,
            completion_capability=claim_capability,
        )

    def commit_publication(
        self,
        claim: EffectExecutionClaim,
        execution: EffectExecutionRequest,
        *,
        effect_commitment_sha256: str,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
        committed_at: datetime | None = None,
    ) -> EffectPublicationCommit:
        """Durably promote one exact ``EXECUTING`` claim to ``COMMITTING``.

        Callers must complete every deterministic, fallible publication
        preflight before this transition.  Such a preflight failure can still
        terminalize ``EXECUTING`` as ``FAILED``.  After this commit, any target
        session exception is indeterminate and intentionally leaves
        ``COMMITTING`` for a future fenced-orphan protocol.
        """

        if type(claim) is not EffectExecutionClaim:
            raise TypeError("claim must be an exact EffectExecutionClaim")
        if type(execution) is not EffectExecutionRequest:
            raise TypeError("execution must be an exact EffectExecutionRequest")
        effect_commitment = _sha256(
            effect_commitment_sha256, "effect_commitment_sha256"
        )
        _authenticate_effect_lease_contracts(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=historical_keyring,
        )
        _validate_narrowed_scope(execution, lease)
        claim.completion_capability.verify_claim_receipt(
            claim.start_receipt, claim.claim_receipt
        )
        _authenticate_start_receipt(
            claim.start_receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        _authenticate_execution_claim_receipt(
            claim.claim_receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        supplied_commit_instant = (
            _as_utc(committed_at, "committed_at")
            if committed_at is not None
            else None
        )
        claim.completion_capability._begin_publication_promotion(
            _token=_CLAIM_PROMOTION_TOKEN
        )
        transition_committed = False
        conn: sqlite3.Connection | None = None
        try:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
            commit_instant = supplied_commit_instant or _utc_now()
            row = conn.execute(
                """
                SELECT execution_id, lease_sha256, idempotency_key,
                       request_sha256, request_json, start_receipt_sha256,
                       start_receipt_json, state, started_at, claimed_at,
                       claim_receipt_sha256, claim_receipt_json, committed_at,
                       publication_commit_receipt_sha256,
                       publication_commit_receipt_json, published_at,
                       publication_outcome_receipt_sha256,
                       publication_outcome_receipt_json, finished_at,
                       terminal_receipt_sha256, terminal_receipt_json
                FROM effect_executions WHERE execution_id=? AND lease_sha256=?
                """,
                (execution.execution_id, lease.digest),
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError("unknown effect execution")
            grant_row = conn.execute(
                """
                SELECT lease_sha256, lease_id, request_sha256, request_json,
                       policy_decision_sha256, policy_decision_json,
                       registry_sha256, entrypoint_id, lease_json,
                       issued_at, expires_at, revoked_at, revocation_reason
                FROM effect_leases WHERE lease_sha256=?
                """,
                (lease.digest,),
            ).fetchone()
            if grant_row is None:
                raise EffectLeaseStateError(
                    "effect execution is missing its historical grant"
                )
            _authenticate_persisted_grant(
                grant_row,
                lease=lease,
                request=request,
                policy_decision=policy_decision,
            )
            persisted_start = _authenticated_replay_start(
                row,
                lease=lease,
                execution=execution,
                request_json=canonical_json(execution.to_dict()),
                keyring=historical_keyring,
            ).receipt
            persisted_claim = _load_persisted_execution_claim(
                row,
                execution=execution,
                start_receipt=persisted_start,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            if persisted_start != claim.start_receipt:
                raise EffectLeaseStateError(
                    "publication commit start differs from persisted authority"
                )
            if persisted_claim != claim.claim_receipt:
                raise EffectLeaseStateError(
                    "publication commit claim differs from persisted authority"
                )
            if str(row["state"]) != "EXECUTING":
                raise EffectLeaseStateError(
                    "publication commit requires EXECUTING, got "
                    f"{str(row['state'])!r}"
                )
            if any(
                row[name] is not None
                for name in (
                    "committed_at",
                    "publication_commit_receipt_sha256",
                    "publication_commit_receipt_json",
                    "published_at",
                    "publication_outcome_receipt_sha256",
                    "publication_outcome_receipt_json",
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "EXECUTING publication commit row carries later-phase fields"
                )
            if grant_row["revoked_at"] is not None:
                raise EffectLeaseStateError(
                    "effect lease was revoked before publication commit"
                )
            if commit_instant >= _parse_utc(
                grant_row["expires_at"], "persisted lease expiry"
            ):
                raise EffectLeaseExpired(
                    "persisted effect lease expired before publication commit"
                )
            if commit_instant < _parse_utc(
                persisted_claim.claimed_at, "claim.claimed_at"
            ):
                raise EffectLeaseStateError(
                    "publication commit predates its execution claim"
                )
            capability_preimage = _publication_capability_preimage(
                lease_sha256=lease.digest,
                issuer_key_id=lease.issuer_key_id,
                execution_id=execution.execution_id,
                execution_request_sha256=execution.digest,
                start_receipt_sha256=persisted_start.receipt_sha256,
                claim_receipt_sha256=persisted_claim.receipt_sha256,
                effect_commitment_sha256=effect_commitment,
                committed_at=_timestamp(commit_instant),
            )
            issuer_secret = historical_keyring.get(lease.issuer_key_id)
            if issuer_secret is None:
                raise EffectLeaseSignatureError(
                    "effect lease issuer key disappeared before commit persistence"
                )
            # The live publication authority remains random and deliberately
            # non-reconstructable after a crash.  A separate derived key signs
            # inert outcome evidence so historical reads can authenticate it.
            publication_secret = secrets.token_bytes(32)
            outcome_audit_key = _derive_publication_outcome_audit_key(
                capability_preimage, issuer_secret
            )
            payload = {
                "lease_sha256": lease.digest,
                "issuer_key_id": lease.issuer_key_id,
                "execution_id": execution.execution_id,
                "execution_request_sha256": execution.digest,
                "start_receipt_sha256": persisted_start.receipt_sha256,
                "claim_receipt_sha256": persisted_claim.receipt_sha256,
                "effect_commitment_sha256": effect_commitment,
                "publication_capability_sha256": (
                    _publication_capability_sha256(publication_secret)
                ),
                "committed_at": _timestamp(commit_instant),
            }
            signature = _publication_commit_signature(payload, issuer_secret)
            authenticated = {**payload, "signature_sha256": signature}
            commit_receipt = EffectPublicationCommitReceipt(
                **authenticated,
                receipt_sha256=canonical_sha(authenticated),
            )
            updated = conn.execute(
                """
                UPDATE effect_executions
                SET state='COMMITTING', committed_at=?,
                    publication_commit_receipt_sha256=?,
                    publication_commit_receipt_json=?
                WHERE execution_id=? AND lease_sha256=? AND state='EXECUTING'
                  AND request_sha256=? AND start_receipt_sha256=?
                  AND claimed_at=? AND claim_receipt_sha256=?
                  AND claim_receipt_json=? AND committed_at IS NULL
                  AND publication_commit_receipt_sha256 IS NULL
                  AND publication_commit_receipt_json IS NULL
                  AND published_at IS NULL
                  AND publication_outcome_receipt_sha256 IS NULL
                  AND publication_outcome_receipt_json IS NULL
                  AND finished_at IS NULL AND terminal_receipt_sha256 IS NULL
                  AND terminal_receipt_json IS NULL
                """,
                (
                    commit_receipt.committed_at,
                    commit_receipt.receipt_sha256,
                    canonical_json(commit_receipt.to_dict()),
                    execution.execution_id,
                    lease.digest,
                    execution.digest,
                    persisted_start.receipt_sha256,
                    persisted_claim.claimed_at,
                    persisted_claim.receipt_sha256,
                    canonical_json(persisted_claim.to_dict()),
                ),
            )
            if updated.rowcount != 1:
                raise EffectLeaseStateError(
                    "execution changed while publication commit held the ledger lock"
                )
            conn.execute("COMMIT")
            transition_committed = True
        except sqlite3.IntegrityError as exc:
            if conn is not None:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise EffectLeaseReplay(
                "publication commit conflicts with persisted identity"
            ) from exc
        except Exception:
            if conn is not None:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        finally:
            if conn is not None:
                conn.close()
            if not transition_committed:
                claim.completion_capability._cancel_publication_promotion(
                    _token=_CLAIM_PROMOTION_TOKEN
                )

        publication_capability = (
            claim.completion_capability._complete_publication_promotion(
                start_receipt=persisted_start,
                claim_receipt=persisted_claim,
                commit_receipt=commit_receipt,
                secret=publication_secret,
                outcome_audit_key=outcome_audit_key,
                _token=_CLAIM_PROMOTION_TOKEN,
            )
        )
        return EffectPublicationCommit(
            start_receipt=persisted_start,
            claim_receipt=persisted_claim,
            commit_receipt=commit_receipt,
            publication_capability=publication_capability,
        )

    def finish(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        completion_capability: CompletionCapability,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
        finished_at: datetime | None = None,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        receipt = freeze_effect_terminal_receipt(
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
        )
        authorization = completion_capability.authorize(receipt)
        return self.finish_receipt(
            receipt,
            authorization=authorization,
            lease=lease,
            request=request,
            policy_decision=policy_decision,
            historical_keyring=historical_keyring,
            persisted_at=persisted_at,
        )

    def finish_receipt(
        self,
        receipt: EffectTerminalReceipt,
        *,
        authorization: TerminalAuthorization,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Persist one live-authorized, already-frozen terminal receipt.

        The opaque authorization must match the random commitment in the
        issuer-MACed start receipt.  The historical lease grant and start are
        authenticated again under the same ledger transaction.  A retry may
        return an already-persisted byte-identical terminal, but neither a
        replayed start nor a different terminal claim receives live authority.
        """

        if not isinstance(receipt, EffectTerminalReceipt):
            raise TypeError("receipt must be an EffectTerminalReceipt")
        if not isinstance(authorization, TerminalAuthorization):
            raise TypeError("authorization must be a TerminalAuthorization")
        persistence_instant = (
            _as_utc(persisted_at, "persisted_at")
            if persisted_at is not None
            else _utc_now()
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT execution_id, lease_sha256, idempotency_key,
                       request_sha256, request_json, start_receipt_sha256,
                       start_receipt_json, state, started_at, claimed_at,
                       claim_receipt_sha256, claim_receipt_json, finished_at,
                       terminal_receipt_sha256, terminal_receipt_json
                FROM effect_executions WHERE execution_id=? AND lease_sha256=?
                """,
                (receipt.execution_id, receipt.lease_sha256),
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError("unknown effect execution")
            grant_row = conn.execute(
                """
                SELECT lease_sha256, lease_id, request_sha256, request_json,
                       policy_decision_sha256, policy_decision_json,
                       registry_sha256, entrypoint_id, lease_json,
                       issued_at, expires_at, revoked_at, revocation_reason
                FROM effect_leases WHERE lease_sha256=?
                """,
                (receipt.lease_sha256,),
            ).fetchone()
            if grant_row is None:
                raise EffectLeaseStateError(
                    "effect execution is missing its historical grant"
                )
            _authenticate_effect_lease_contracts(
                lease,
                request=request,
                policy_decision=policy_decision,
                keyring=historical_keyring,
            )
            _authenticate_persisted_grant(
                grant_row,
                lease=lease,
                request=request,
                policy_decision=policy_decision,
            )
            try:
                execution_payload = json.loads(row["request_json"])
                if not isinstance(execution_payload, dict):
                    raise ValueError("execution request JSON must contain an object")
                execution = EffectExecutionRequest(**execution_payload)
            except (
                TypeError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                EffectLeaseBindingMismatch,
            ) as exc:
                raise EffectLeaseStateError(
                    "persisted effect execution contains invalid request bytes"
                ) from exc
            _validate_narrowed_scope(execution, lease)
            start = _authenticated_replay_start(
                row,
                lease=lease,
                execution=execution,
                request_json=canonical_json(execution.to_dict()),
                keyring=historical_keyring,
            ).receipt
            persisted_claim = _load_persisted_execution_claim(
                row,
                execution=execution,
                start_receipt=start,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            if persisted_claim is not None:
                raise EffectLeaseStateError(
                    "normal completion capability is disabled after an "
                    "execution claim"
                )
            terminal_mismatches = sorted(
                name
                for name, actual, expected in (
                    ("lease_sha256", receipt.lease_sha256, start.lease_sha256),
                    ("execution_id", receipt.execution_id, start.execution_id),
                    (
                        "start_receipt_sha256",
                        receipt.start_receipt_sha256,
                        start.receipt_sha256,
                    ),
                )
                if actual != expected
            )
            if terminal_mismatches:
                raise EffectLeaseBindingMismatch(
                    "terminal receipt start binding mismatch: "
                    + ", ".join(terminal_mismatches)
                )
            _authenticate_terminal_authorization(
                authorization,
                receipt=receipt,
                start_receipt=start,
            )
            started = _parse_utc(start.started_at, "start.started_at")
            finished = _parse_utc(receipt.finished_at, "receipt.finished_at")
            if not started <= finished <= persistence_instant:
                raise EffectLeaseStateError(
                    "terminal receipt violates start <= terminal <= persistence ordering"
                )

            state = str(row["state"])
            if state in _TERMINAL_STATES:
                if any(
                    row[name] is None
                    for name in (
                        "finished_at",
                        "terminal_receipt_sha256",
                        "terminal_receipt_json",
                    )
                ):
                    raise EffectLeaseStateError(
                        "terminal execution is missing terminal receipt fields"
                    )
                if (
                    row["terminal_receipt_sha256"] != receipt.receipt_sha256
                    or row["terminal_receipt_json"]
                    != canonical_json(receipt.to_dict())
                    or row["finished_at"] != receipt.finished_at
                    or state != receipt.outcome
                ):
                    raise EffectLeaseStateError(
                        "effect execution already has a different terminal receipt"
                    )
                conn.execute("COMMIT")
                return receipt
            if state != "STARTED":
                raise EffectLeaseStateError(
                    f"effect terminal requires STARTED, got {state!r}"
                )
            if any(
                row[name] is not None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "STARTED execution unexpectedly carries terminal fields"
                )
            updated = conn.execute(
                """
                UPDATE effect_executions
                SET state=?, finished_at=?, terminal_receipt_sha256=?,
                    terminal_receipt_json=?
                WHERE execution_id=? AND lease_sha256=? AND state='STARTED'
                  AND request_sha256=? AND start_receipt_sha256=?
                  AND claimed_at IS NULL AND claim_receipt_sha256 IS NULL
                  AND claim_receipt_json IS NULL
                  AND committed_at IS NULL
                  AND publication_commit_receipt_sha256 IS NULL
                  AND publication_commit_receipt_json IS NULL
                  AND published_at IS NULL
                  AND publication_outcome_receipt_sha256 IS NULL
                  AND publication_outcome_receipt_json IS NULL
                """,
                (
                    receipt.outcome,
                    receipt.finished_at,
                    receipt.receipt_sha256,
                    canonical_json(receipt.to_dict()),
                    receipt.execution_id,
                    receipt.lease_sha256,
                    execution.digest,
                    receipt.start_receipt_sha256,
                ),
            )
            if updated.rowcount != 1:
                raise EffectLeaseStateError(
                    "effect execution changed while terminal authority held the ledger lock"
                )
            conn.execute("COMMIT")
            return receipt
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def finish_claim(
        self,
        claim: EffectExecutionClaim,
        *,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
        finished_at: datetime | None = None,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Bind and persist a terminal using the exclusive claim capability."""

        if type(claim) is not EffectExecutionClaim:
            raise TypeError("claim must be an exact EffectExecutionClaim")
        claim.completion_capability.verify_claim_receipt(
            claim.start_receipt, claim.claim_receipt
        )
        receipt = freeze_effect_terminal_receipt(
            claim.start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
        )
        authorization = claim.completion_capability.authorize(receipt)
        return self.finish_claim_receipt(
            receipt,
            claim_receipt=claim.claim_receipt,
            authorization=authorization,
            lease=lease,
            request=request,
            policy_decision=policy_decision,
            historical_keyring=historical_keyring,
            persisted_at=persisted_at,
        )

    def finish_claim_receipt(
        self,
        receipt: EffectTerminalReceipt,
        *,
        claim_receipt: EffectExecutionClaimReceipt,
        authorization: ClaimTerminalAuthorization,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Persist one exact terminal from the exclusive ``EXECUTING`` claim."""

        if not isinstance(receipt, EffectTerminalReceipt):
            raise TypeError("receipt must be an EffectTerminalReceipt")
        if not isinstance(claim_receipt, EffectExecutionClaimReceipt):
            raise TypeError("claim_receipt must be an EffectExecutionClaimReceipt")
        if not isinstance(authorization, ClaimTerminalAuthorization):
            raise TypeError("authorization must be a ClaimTerminalAuthorization")
        persistence_instant = (
            _as_utc(persisted_at, "persisted_at")
            if persisted_at is not None
            else _utc_now()
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT execution_id, lease_sha256, idempotency_key,
                       request_sha256, request_json, start_receipt_sha256,
                       start_receipt_json, state, started_at, claimed_at,
                       claim_receipt_sha256, claim_receipt_json, committed_at,
                       publication_commit_receipt_sha256,
                       publication_commit_receipt_json, published_at,
                       publication_outcome_receipt_sha256,
                       publication_outcome_receipt_json, finished_at,
                       terminal_receipt_sha256, terminal_receipt_json
                FROM effect_executions WHERE execution_id=? AND lease_sha256=?
                """,
                (receipt.execution_id, receipt.lease_sha256),
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError("unknown effect execution")
            grant_row = conn.execute(
                """
                SELECT lease_sha256, lease_id, request_sha256, request_json,
                       policy_decision_sha256, policy_decision_json,
                       registry_sha256, entrypoint_id, lease_json,
                       issued_at, expires_at, revoked_at, revocation_reason
                FROM effect_leases WHERE lease_sha256=?
                """,
                (receipt.lease_sha256,),
            ).fetchone()
            if grant_row is None:
                raise EffectLeaseStateError(
                    "effect execution is missing its historical grant"
                )
            _authenticate_effect_lease_contracts(
                lease,
                request=request,
                policy_decision=policy_decision,
                keyring=historical_keyring,
            )
            _authenticate_persisted_grant(
                grant_row,
                lease=lease,
                request=request,
                policy_decision=policy_decision,
            )
            try:
                execution_payload = json.loads(row["request_json"])
                if not isinstance(execution_payload, dict):
                    raise ValueError("execution request JSON must contain an object")
                execution = EffectExecutionRequest(**execution_payload)
            except (
                TypeError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                EffectLeaseBindingMismatch,
            ) as exc:
                raise EffectLeaseStateError(
                    "persisted effect execution contains invalid request bytes"
                ) from exc
            _validate_narrowed_scope(execution, lease)
            start = _authenticated_replay_start(
                row,
                lease=lease,
                execution=execution,
                request_json=canonical_json(execution.to_dict()),
                keyring=historical_keyring,
            ).receipt
            persisted_claim = _load_persisted_execution_claim(
                row,
                execution=execution,
                start_receipt=start,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            if persisted_claim is None:
                raise EffectLeaseStateError(
                    "claim terminal authority requires a persisted execution claim"
                )
            if persisted_claim != claim_receipt:
                raise EffectLeaseBindingMismatch(
                    "claim terminal receipt differs from persisted claim authority"
                )
            persisted_commit = _load_persisted_publication_commit(
                row,
                execution=execution,
                start_receipt=start,
                claim_receipt=persisted_claim,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            if persisted_commit is not None:
                raise EffectLeaseStateError(
                    "claim completion capability is disabled after publication "
                    "commit"
                )
            terminal_mismatches = sorted(
                name
                for name, actual, expected in (
                    ("lease_sha256", receipt.lease_sha256, start.lease_sha256),
                    ("execution_id", receipt.execution_id, start.execution_id),
                    (
                        "start_receipt_sha256",
                        receipt.start_receipt_sha256,
                        start.receipt_sha256,
                    ),
                )
                if actual != expected
            )
            if terminal_mismatches:
                raise EffectLeaseBindingMismatch(
                    "claim terminal receipt start binding mismatch: "
                    + ", ".join(terminal_mismatches)
                )
            _authenticate_claim_terminal_authorization(
                authorization,
                receipt=receipt,
                start_receipt=start,
                claim_receipt=persisted_claim,
            )
            started = _parse_utc(start.started_at, "start.started_at")
            claimed = _parse_utc(
                persisted_claim.claimed_at, "claim.claimed_at"
            )
            finished = _parse_utc(receipt.finished_at, "receipt.finished_at")
            if not started <= claimed <= finished <= persistence_instant:
                raise EffectLeaseStateError(
                    "claim terminal violates "
                    "start <= claim <= terminal <= persistence ordering"
                )

            state = str(row["state"])
            if state in _TERMINAL_STATES:
                if any(
                    row[name] is None
                    for name in (
                        "finished_at",
                        "terminal_receipt_sha256",
                        "terminal_receipt_json",
                    )
                ):
                    raise EffectLeaseStateError(
                        "terminal execution is missing terminal receipt fields"
                    )
                if (
                    row["terminal_receipt_sha256"] != receipt.receipt_sha256
                    or row["terminal_receipt_json"]
                    != canonical_json(receipt.to_dict())
                    or row["finished_at"] != receipt.finished_at
                    or state != receipt.outcome
                ):
                    raise EffectLeaseStateError(
                        "effect execution already has a different terminal receipt"
                    )
                conn.execute("COMMIT")
                return receipt
            if state != "EXECUTING":
                raise EffectLeaseStateError(
                    f"claim terminal requires EXECUTING, got {state!r}"
                )
            if any(
                row[name] is not None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "EXECUTING execution unexpectedly carries terminal fields"
                )
            updated = conn.execute(
                """
                UPDATE effect_executions
                SET state=?, finished_at=?, terminal_receipt_sha256=?,
                    terminal_receipt_json=?
                WHERE execution_id=? AND lease_sha256=? AND state='EXECUTING'
                  AND request_sha256=? AND start_receipt_sha256=?
                  AND claimed_at=? AND claim_receipt_sha256=?
                  AND claim_receipt_json=?
                  AND committed_at IS NULL
                  AND publication_commit_receipt_sha256 IS NULL
                  AND publication_commit_receipt_json IS NULL
                  AND published_at IS NULL
                  AND publication_outcome_receipt_sha256 IS NULL
                  AND publication_outcome_receipt_json IS NULL
                """,
                (
                    receipt.outcome,
                    receipt.finished_at,
                    receipt.receipt_sha256,
                    canonical_json(receipt.to_dict()),
                    receipt.execution_id,
                    receipt.lease_sha256,
                    execution.digest,
                    receipt.start_receipt_sha256,
                    persisted_claim.claimed_at,
                    persisted_claim.receipt_sha256,
                    canonical_json(persisted_claim.to_dict()),
                ),
            )
            if updated.rowcount != 1:
                raise EffectLeaseStateError(
                    "effect execution changed while claim terminal authority "
                    "held the ledger lock"
                )
            conn.execute("COMMIT")
            return receipt
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def finish_committed(
        self,
        finalization: EffectPublicationFinalization,
        *,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
        finished_at: datetime | None = None,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Terminalize ``COMMITTING`` using clean publication finalization."""

        if type(finalization) is not EffectPublicationFinalization:
            raise TypeError(
                "finalization must be an exact EffectPublicationFinalization"
            )
        if str(outcome).upper() != "COMPLETED":
            raise EffectLeaseStateError(
                "a successful publication may terminalize only as COMPLETED"
            )
        finalization.completion_capability.verify_publication(
            finalization.commit_receipt,
            finalization.outcome_receipt,
        )
        receipt = freeze_effect_terminal_receipt(
            finalization.start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
        )
        authorization = finalization.completion_capability.authorize(
            receipt,
            commit_receipt=finalization.commit_receipt,
            outcome_receipt=finalization.outcome_receipt,
        )
        return self.finish_committed_receipt(
            receipt,
            claim_receipt=finalization.claim_receipt,
            commit_receipt=finalization.commit_receipt,
            outcome_receipt=finalization.outcome_receipt,
            authorization=authorization,
            lease=lease,
            request=request,
            policy_decision=policy_decision,
            historical_keyring=historical_keyring,
            persisted_at=persisted_at,
        )

    def finish_committed_receipt(
        self,
        receipt: EffectTerminalReceipt,
        *,
        claim_receipt: EffectExecutionClaimReceipt,
        commit_receipt: EffectPublicationCommitReceipt,
        outcome_receipt: EffectPublicationOutcomeReceipt,
        authorization: PublicationFinalizationAuthorization,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Persist an exact terminal under publication finalization authority."""

        if not isinstance(receipt, EffectTerminalReceipt):
            raise TypeError("receipt must be an EffectTerminalReceipt")
        if not isinstance(claim_receipt, EffectExecutionClaimReceipt):
            raise TypeError("claim_receipt must be an EffectExecutionClaimReceipt")
        if not isinstance(commit_receipt, EffectPublicationCommitReceipt):
            raise TypeError(
                "commit_receipt must be an EffectPublicationCommitReceipt"
            )
        if not isinstance(outcome_receipt, EffectPublicationOutcomeReceipt):
            raise TypeError(
                "outcome_receipt must be an EffectPublicationOutcomeReceipt"
            )
        if not isinstance(
            authorization, PublicationFinalizationAuthorization
        ):
            raise TypeError(
                "authorization must be a PublicationFinalizationAuthorization"
            )
        if receipt.outcome != "COMPLETED":
            raise EffectLeaseStateError(
                "a successful publication terminal receipt must be COMPLETED"
            )
        supplied_persistence_instant = (
            _as_utc(persisted_at, "persisted_at")
            if persisted_at is not None
            else None
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            persistence_instant = supplied_persistence_instant or _utc_now()
            row = conn.execute(
                """
                SELECT execution_id, lease_sha256, idempotency_key,
                       request_sha256, request_json, start_receipt_sha256,
                       start_receipt_json, state, started_at, claimed_at,
                       claim_receipt_sha256, claim_receipt_json, committed_at,
                       publication_commit_receipt_sha256,
                       publication_commit_receipt_json, published_at,
                       publication_outcome_receipt_sha256,
                       publication_outcome_receipt_json, finished_at,
                       terminal_receipt_sha256, terminal_receipt_json
                FROM effect_executions WHERE execution_id=? AND lease_sha256=?
                """,
                (receipt.execution_id, receipt.lease_sha256),
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError("unknown effect execution")
            grant_row = conn.execute(
                """
                SELECT lease_sha256, lease_id, request_sha256, request_json,
                       policy_decision_sha256, policy_decision_json,
                       registry_sha256, entrypoint_id, lease_json,
                       issued_at, expires_at, revoked_at, revocation_reason
                FROM effect_leases WHERE lease_sha256=?
                """,
                (receipt.lease_sha256,),
            ).fetchone()
            if grant_row is None:
                raise EffectLeaseStateError(
                    "effect execution is missing its historical grant"
                )
            _authenticate_effect_lease_contracts(
                lease,
                request=request,
                policy_decision=policy_decision,
                keyring=historical_keyring,
            )
            _authenticate_persisted_grant(
                grant_row,
                lease=lease,
                request=request,
                policy_decision=policy_decision,
            )
            try:
                execution_payload = json.loads(row["request_json"])
                if not isinstance(execution_payload, dict):
                    raise ValueError("execution request JSON must contain an object")
                execution = EffectExecutionRequest(**execution_payload)
            except (
                TypeError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                EffectLeaseBindingMismatch,
            ) as exc:
                raise EffectLeaseStateError(
                    "persisted effect execution contains invalid request bytes"
                ) from exc
            _validate_narrowed_scope(execution, lease)
            start = _authenticated_replay_start(
                row,
                lease=lease,
                execution=execution,
                request_json=canonical_json(execution.to_dict()),
                keyring=historical_keyring,
            ).receipt
            persisted_claim = _load_persisted_execution_claim(
                row,
                execution=execution,
                start_receipt=start,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            persisted_commit = _load_persisted_publication_commit(
                row,
                execution=execution,
                start_receipt=start,
                claim_receipt=persisted_claim,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            if persisted_claim != claim_receipt:
                raise EffectLeaseBindingMismatch(
                    "finalization claim differs from persisted authority"
                )
            if persisted_commit != commit_receipt:
                raise EffectLeaseBindingMismatch(
                    "finalization commit differs from persisted authority"
                )
            derived_audit_key = _publication_outcome_audit_key_for_commit(
                persisted_commit,
                lease=lease,
                keyring=historical_keyring,
            )
            if not hmac.compare_digest(
                derived_audit_key, authorization._outcome_audit_key
            ):
                raise EffectLeaseSignatureError(
                    "publication outcome audit key differs from historical issuer"
                )
            expected_outcome_signature = _publication_outcome_signature(
                outcome_receipt.signing_dict(), derived_audit_key
            )
            if not hmac.compare_digest(
                expected_outcome_signature, outcome_receipt.signature_sha256
            ):
                raise EffectLeaseSignatureError(
                    "publication outcome signature mismatch"
                )
            _authenticate_publication_finalization_authorization(
                authorization,
                receipt=receipt,
                start_receipt=start,
                claim_receipt=claim_receipt,
                commit_receipt=commit_receipt,
                outcome_receipt=outcome_receipt,
            )
            started = _parse_utc(start.started_at, "start.started_at")
            claimed = _parse_utc(claim_receipt.claimed_at, "claim.claimed_at")
            committed = _parse_utc(
                commit_receipt.committed_at, "commit.committed_at"
            )
            published = _parse_utc(
                outcome_receipt.published_at, "outcome.published_at"
            )
            finished = _parse_utc(receipt.finished_at, "receipt.finished_at")
            if not (
                started
                <= claimed
                <= committed
                <= published
                <= finished
                <= persistence_instant
            ):
                raise EffectLeaseStateError(
                    "publication finalization violates start <= claim <= commit "
                    "<= publication <= terminal <= persistence ordering"
                )
            state = str(row["state"])
            if state in _TERMINAL_STATES:
                persisted_outcome = _load_persisted_publication_outcome(
                    row,
                    execution=execution,
                    start_receipt=start,
                    claim_receipt=persisted_claim,
                    commit_receipt=persisted_commit,
                    lease=lease,
                    historical_keyring=historical_keyring,
                )
                if persisted_outcome != outcome_receipt:
                    raise EffectLeaseStateError(
                        "terminal execution has a different publication outcome"
                    )
                if (
                    row["terminal_receipt_sha256"] != receipt.receipt_sha256
                    or row["terminal_receipt_json"]
                    != canonical_json(receipt.to_dict())
                    or row["finished_at"] != receipt.finished_at
                    or state != receipt.outcome
                ):
                    raise EffectLeaseStateError(
                        "effect execution already has a different terminal receipt"
                    )
                conn.execute("COMMIT")
                return receipt
            if state != "COMMITTING":
                raise EffectLeaseStateError(
                    f"publication finalization requires COMMITTING, got {state!r}"
                )
            if any(
                row[name] is not None
                for name in (
                    "published_at",
                    "publication_outcome_receipt_sha256",
                    "publication_outcome_receipt_json",
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "COMMITTING execution unexpectedly carries outcome fields"
                )
            updated = conn.execute(
                """
                UPDATE effect_executions
                SET state=?, published_at=?,
                    publication_outcome_receipt_sha256=?,
                    publication_outcome_receipt_json=?, finished_at=?,
                    terminal_receipt_sha256=?, terminal_receipt_json=?
                WHERE execution_id=? AND lease_sha256=? AND state='COMMITTING'
                  AND request_sha256=? AND start_receipt_sha256=?
                  AND claimed_at=? AND claim_receipt_sha256=?
                  AND claim_receipt_json=? AND committed_at=?
                  AND publication_commit_receipt_sha256=?
                  AND publication_commit_receipt_json=?
                  AND published_at IS NULL
                  AND publication_outcome_receipt_sha256 IS NULL
                  AND publication_outcome_receipt_json IS NULL
                  AND finished_at IS NULL AND terminal_receipt_sha256 IS NULL
                  AND terminal_receipt_json IS NULL
                """,
                (
                    receipt.outcome,
                    outcome_receipt.published_at,
                    outcome_receipt.receipt_sha256,
                    canonical_json(outcome_receipt.to_dict()),
                    receipt.finished_at,
                    receipt.receipt_sha256,
                    canonical_json(receipt.to_dict()),
                    receipt.execution_id,
                    receipt.lease_sha256,
                    execution.digest,
                    start.receipt_sha256,
                    claim_receipt.claimed_at,
                    claim_receipt.receipt_sha256,
                    canonical_json(claim_receipt.to_dict()),
                    commit_receipt.committed_at,
                    commit_receipt.receipt_sha256,
                    canonical_json(commit_receipt.to_dict()),
                ),
            )
            if updated.rowcount != 1:
                raise EffectLeaseStateError(
                    "execution changed while finalization held the ledger lock"
                )
            conn.execute("COMMIT")
            return receipt
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def reconcile(
        self,
        pending_terminal_receipt: EffectTerminalReceipt,
        decision: "EffectReconciliationDecision",
        *,
        historical_keyring: Mapping[str, bytes | str],
        operator_keyring: Mapping[tuple[str, str], bytes | str],
        now: datetime | None = None,
    ) -> "EffectReconciliationResult":
        """Close one unclaimed STARTED execution through reconciliation."""

        # Runtime import keeps the contract module free to reuse the canonical
        # receipt and ledger types without creating an import cycle.
        from daedalus.kernel.reconciliation import reconcile_effect_terminal

        return reconcile_effect_terminal(
            self,
            pending_terminal_receipt,
            decision,
            historical_keyring=historical_keyring,
            operator_keyring=operator_keyring,
            now=now,
        )

    def execution_state(self, execution_id: str) -> str | None:
        value = _identifier(execution_id, "execution_id")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM effect_executions WHERE execution_id=?", (value,)
            ).fetchone()
        return None if row is None else str(row["state"])

    def execution_record(
        self, execution_id: str
    ) -> PersistedEffectExecution | None:
        """Load one execution with canonical-byte and receipt validation.

        Unlike :meth:`load_grant`, this historical/reconciliation read does not
        require a currently valid lease.  It performs no effect and never turns
        a ``STARTED``, ``EXECUTING`` or ``COMMITTING`` row into permission to
        call a provider or target consumer again.
        """

        value = _identifier(execution_id, "execution_id")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT lease_sha256, idempotency_key, request_sha256,
                       request_json, start_receipt_sha256,
                       start_receipt_json, state, started_at, claimed_at,
                       claim_receipt_sha256, claim_receipt_json, committed_at,
                       publication_commit_receipt_sha256,
                       publication_commit_receipt_json, published_at,
                       publication_outcome_receipt_sha256,
                       publication_outcome_receipt_json, finished_at,
                       terminal_receipt_sha256, terminal_receipt_json
                FROM effect_executions WHERE execution_id=?
                """,
                (value,),
            ).fetchone()
        if row is None:
            return None

        try:
            request_payload = json.loads(row["request_json"])
            start_payload = json.loads(row["start_receipt_json"])
            if not isinstance(request_payload, dict) or not isinstance(
                start_payload, dict
            ):
                raise ValueError("execution JSON must contain objects")
            request = EffectExecutionRequest(**request_payload)
            start = LeasedEffectStartReceipt(**start_payload)
        except (
            TypeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            EffectLeaseBindingMismatch,
        ) as exc:
            raise EffectLeaseStateError(
                "persisted effect execution contains invalid start bytes"
            ) from exc

        start_body = start.to_dict()
        start_digest = start_body.pop("receipt_sha256")
        start_mismatches = []
        if canonical_json(request.to_dict()) != row["request_json"]:
            start_mismatches.append("request_json")
        if request.digest != row["request_sha256"]:
            start_mismatches.append("request_sha256")
        if canonical_json(start.to_dict()) != row["start_receipt_json"]:
            start_mismatches.append("start_receipt_json")
        if start.receipt_sha256 != row["start_receipt_sha256"]:
            start_mismatches.append("start_receipt_sha256")
        if canonical_sha(start_body) != start_digest:
            start_mismatches.append("start_receipt_digest")
        if start.lease_sha256 != row["lease_sha256"]:
            start_mismatches.append("lease_sha256")
        if start.execution_id != value or request.execution_id != value:
            start_mismatches.append("execution_id")
        if start.idempotency_key != row["idempotency_key"]:
            start_mismatches.append("idempotency_key")
        if start.idempotency_key != request.idempotency_key:
            start_mismatches.append("request_idempotency_key")
        if start.execution_request_sha256 != request.digest:
            start_mismatches.append("execution_request_binding")
        if start.started_at != row["started_at"]:
            start_mismatches.append("started_at")
        if start_mismatches:
            raise EffectLeaseStateError(
                "persisted effect execution failed start identity checks: "
                + ", ".join(sorted(set(start_mismatches)))
            )

        claim = _load_persisted_execution_claim(
            row,
            execution=request,
            start_receipt=start,
        )
        commit = _load_persisted_publication_commit(
            row,
            execution=request,
            start_receipt=start,
            claim_receipt=claim,
        )
        publication_outcome = _load_persisted_publication_outcome(
            row,
            execution=request,
            start_receipt=start,
            claim_receipt=claim,
            commit_receipt=commit,
        )
        state = str(row["state"])
        terminal: EffectTerminalReceipt | None = None
        if state == "STARTED":
            if claim is not None:
                raise EffectLeaseStateError(
                    "STARTED execution unexpectedly carries claim fields"
                )
            if commit is not None or publication_outcome is not None:
                raise EffectLeaseStateError(
                    "STARTED execution unexpectedly carries publication fields"
                )
            if any(
                row[name] is not None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "STARTED execution unexpectedly carries terminal fields"
                )
        elif state == "EXECUTING":
            if claim is None:
                raise EffectLeaseStateError(
                    "EXECUTING execution is missing its authenticated claim"
                )
            if commit is not None or publication_outcome is not None:
                raise EffectLeaseStateError(
                    "EXECUTING execution unexpectedly carries publication fields"
                )
            if any(
                row[name] is not None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "EXECUTING execution unexpectedly carries terminal fields"
                )
        elif state == "COMMITTING":
            if claim is None or commit is None:
                raise EffectLeaseStateError(
                    "COMMITTING execution is missing its claim or commit receipt"
                )
            if publication_outcome is not None:
                raise EffectLeaseStateError(
                    "COMMITTING execution unexpectedly carries an outcome"
                )
            if any(
                row[name] is not None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "COMMITTING execution unexpectedly carries terminal fields"
                )
        elif state in _TERMINAL_STATES:
            if any(
                row[name] is None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "terminal execution is missing terminal receipt fields"
                )
            try:
                terminal_payload = json.loads(row["terminal_receipt_json"])
                if not isinstance(terminal_payload, dict):
                    raise ValueError("terminal receipt JSON must contain an object")
                terminal_payload["output_digests"] = tuple(
                    terminal_payload["output_digests"]
                )
                terminal = EffectTerminalReceipt(**terminal_payload)
            except (
                TypeError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                EffectLeaseBindingMismatch,
            ) as exc:
                raise EffectLeaseStateError(
                    "persisted effect execution contains invalid terminal bytes"
                ) from exc
            terminal_body = terminal.to_dict()
            terminal_digest = terminal_body.pop("receipt_sha256")
            terminal_mismatches = []
            if canonical_json(terminal.to_dict()) != row["terminal_receipt_json"]:
                terminal_mismatches.append("terminal_receipt_json")
            if terminal.receipt_sha256 != row["terminal_receipt_sha256"]:
                terminal_mismatches.append("terminal_receipt_sha256")
            if canonical_sha(terminal_body) != terminal_digest:
                terminal_mismatches.append("terminal_receipt_digest")
            if terminal.lease_sha256 != start.lease_sha256:
                terminal_mismatches.append("terminal_lease_binding")
            if terminal.execution_id != value:
                terminal_mismatches.append("terminal_execution_binding")
            if terminal.start_receipt_sha256 != start.receipt_sha256:
                terminal_mismatches.append("terminal_start_binding")
            if terminal.outcome != state:
                terminal_mismatches.append("terminal_state")
            if terminal.finished_at != row["finished_at"]:
                terminal_mismatches.append("finished_at")
            if terminal_mismatches:
                raise EffectLeaseStateError(
                    "persisted effect execution failed terminal identity checks: "
                    + ", ".join(sorted(set(terminal_mismatches)))
                )
            if commit is None and publication_outcome is not None:
                raise EffectLeaseStateError(
                    "terminal execution has an outcome without a commit"
                )
            if commit is not None and publication_outcome is None:
                raise EffectLeaseStateError(
                    "committed terminal execution is missing publication outcome"
                )
            if publication_outcome is not None and state != "COMPLETED":
                raise EffectLeaseStateError(
                    "a successful publication terminal must be COMPLETED"
                )
            if publication_outcome is not None and _parse_utc(
                terminal.finished_at, "terminal.finished_at"
            ) < _parse_utc(
                publication_outcome.published_at, "outcome.published_at"
            ):
                raise EffectLeaseStateError(
                    "terminal execution predates publication outcome"
                )
        else:
            raise EffectLeaseStateError(
                f"persisted effect execution has unknown state {state!r}"
            )

        return PersistedEffectExecution(
            request=request,
            start_receipt=start,
            state=state,
            claim_receipt=claim,
            publication_commit_receipt=commit,
            publication_outcome_receipt=publication_outcome,
            terminal_receipt=terminal,
        )

    def authenticated_execution_record(
        self,
        execution_id: str,
        *,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
    ) -> PersistedEffectExecution | None:
        """Read one historical row with its issuer-authenticated phase chain.

        ``execution_record`` is a structural database view.  This seam also
        authenticates the persisted grant plus start, claim, publication
        commit and publication outcome with the supplied historical issuer
        key.  Terminal receipts predate this addition and remain structurally,
        not independently cryptographically, authenticated.
        """

        value = _identifier(execution_id, "execution_id")
        _authenticate_effect_lease_contracts(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=historical_keyring,
        )
        record = self.execution_record(value)
        if record is None:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT execution_id, lease_sha256, idempotency_key,
                       request_sha256, request_json, start_receipt_sha256,
                       start_receipt_json, state, started_at, claimed_at,
                       claim_receipt_sha256, claim_receipt_json, committed_at,
                       publication_commit_receipt_sha256,
                       publication_commit_receipt_json, published_at,
                       publication_outcome_receipt_sha256,
                       publication_outcome_receipt_json, finished_at,
                       terminal_receipt_sha256, terminal_receipt_json
                FROM effect_executions WHERE execution_id=? AND lease_sha256=?
                """,
                (value, lease.digest),
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError(
                    "historical execution differs from the requested lease"
                )
            grant_row = conn.execute(
                """
                SELECT lease_sha256, lease_id, request_sha256, request_json,
                       policy_decision_sha256, policy_decision_json,
                       registry_sha256, entrypoint_id, lease_json,
                       issued_at, expires_at, revoked_at, revocation_reason
                FROM effect_leases WHERE lease_sha256=?
                """,
                (lease.digest,),
            ).fetchone()
            if grant_row is None:
                raise EffectLeaseStateError(
                    "historical execution is missing its persisted grant"
                )
            _authenticate_persisted_grant(
                grant_row,
                lease=lease,
                request=request,
                policy_decision=policy_decision,
            )
            start = _authenticated_replay_start(
                row,
                lease=lease,
                execution=record.request,
                request_json=canonical_json(record.request.to_dict()),
                keyring=historical_keyring,
            ).receipt
            claim = _load_persisted_execution_claim(
                row,
                execution=record.request,
                start_receipt=start,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            commit = _load_persisted_publication_commit(
                row,
                execution=record.request,
                start_receipt=start,
                claim_receipt=claim,
                lease=lease,
                historical_keyring=historical_keyring,
            )
            outcome = _load_persisted_publication_outcome(
                row,
                execution=record.request,
                start_receipt=start,
                claim_receipt=claim,
                commit_receipt=commit,
                lease=lease,
                historical_keyring=historical_keyring,
            )
        finally:
            conn.close()
        authenticated = (start, claim, commit, outcome)
        observed = (
            record.start_receipt,
            record.claim_receipt,
            record.publication_commit_receipt,
            record.publication_outcome_receipt,
        )
        if authenticated != observed:
            raise EffectLeaseStateError(
                "authenticated execution phases differ from structural record"
            )
        return record

    def require_live_start(
        self,
        start: EffectStartResult,
        *,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        execution: EffectExecutionRequest,
        historical_keyring: Mapping[str, bytes | str],
    ) -> PersistedEffectExecution:
        """Authenticate one live capability against its durable STARTED row.

        Possession of a shape-compatible receipt or capability object is not
        authority.  This seam jointly requires the signed historical grant,
        the issuer-HMAC start receipt, the exact execution request persisted by
        ``begin``, a still-indeterminate ``STARTED`` row, and the live random
        secret committed by that signed receipt.
        """

        if type(start) is not EffectStartResult:
            raise TypeError("start must be an exact EffectStartResult")
        capability = start.completion_capability
        if not start.execute or type(capability) is not CompletionCapability:
            raise EffectLeaseStateError(
                "live effect verification requires a newly persisted start"
            )
        _authenticate_effect_lease_contracts(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=historical_keyring,
        )
        capability.verify_start_receipt(start.receipt)
        _authenticate_start_receipt(
            start.receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        record = self.execution_record(execution.execution_id)
        if record is None:
            raise EffectLeaseStateError(
                "live effect start is absent from the canonical ledger"
            )
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("state", record.state, "STARTED"),
                ("terminal_receipt", record.terminal_receipt, None),
                ("execution_request", record.request, execution),
                ("start_receipt", record.start_receipt, start.receipt),
                ("lease_sha256", record.start_receipt.lease_sha256, lease.digest),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseStateError(
                "live effect start differs from persisted authority: "
                + ", ".join(mismatches)
            )
        return record

    def require_live_claim(
        self,
        claim: EffectExecutionClaim,
        execution: EffectExecutionRequest,
        *,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
    ) -> PersistedEffectExecution:
        """Authenticate exact live claim authority against ``EXECUTING``."""

        if type(claim) is not EffectExecutionClaim:
            raise TypeError("claim must be an exact EffectExecutionClaim")
        if type(execution) is not EffectExecutionRequest:
            raise TypeError("execution must be an exact EffectExecutionRequest")
        _authenticate_effect_lease_contracts(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=historical_keyring,
        )
        claim.completion_capability.verify_claim_receipt(
            claim.start_receipt, claim.claim_receipt
        )
        _authenticate_start_receipt(
            claim.start_receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        _authenticate_execution_claim_receipt(
            claim.claim_receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        record = self.execution_record(execution.execution_id)
        if record is None:
            raise EffectLeaseStateError(
                "live execution claim is absent from the canonical ledger"
            )
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("state", record.state, "EXECUTING"),
                ("terminal_receipt", record.terminal_receipt, None),
                ("execution_request", record.request, execution),
                ("start_receipt", record.start_receipt, claim.start_receipt),
                ("claim_receipt", record.claim_receipt, claim.claim_receipt),
                (
                    "lease_sha256",
                    record.start_receipt.lease_sha256,
                    lease.digest,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseStateError(
                "live execution claim differs from persisted authority: "
                + ", ".join(mismatches)
            )
        return record

    def require_live_commit(
        self,
        commit: EffectPublicationCommit,
        execution: EffectExecutionRequest,
        *,
        lease: EffectLease,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        historical_keyring: Mapping[str, bytes | str],
    ) -> PersistedEffectExecution:
        """Authenticate fresh target authority against durable ``COMMITTING``."""

        if type(commit) is not EffectPublicationCommit:
            raise TypeError("commit must be an exact EffectPublicationCommit")
        if type(execution) is not EffectExecutionRequest:
            raise TypeError("execution must be an exact EffectExecutionRequest")
        _authenticate_effect_lease_contracts(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=historical_keyring,
        )
        commit.publication_capability.verify_commit_receipt(
            commit.start_receipt,
            commit.claim_receipt,
            commit.commit_receipt,
        )
        _authenticate_start_receipt(
            commit.start_receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        _authenticate_execution_claim_receipt(
            commit.claim_receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        _authenticate_publication_commit_receipt(
            commit.commit_receipt,
            lease=lease,
            keyring=historical_keyring,
        )
        record = self.execution_record(execution.execution_id)
        if record is None:
            raise EffectLeaseStateError(
                "live publication commit is absent from the canonical ledger"
            )
        mismatches = sorted(
            name
            for name, actual, expected in (
                ("state", record.state, "COMMITTING"),
                ("terminal_receipt", record.terminal_receipt, None),
                (
                    "publication_outcome_receipt",
                    record.publication_outcome_receipt,
                    None,
                ),
                ("execution_request", record.request, execution),
                ("start_receipt", record.start_receipt, commit.start_receipt),
                ("claim_receipt", record.claim_receipt, commit.claim_receipt),
                (
                    "publication_commit_receipt",
                    record.publication_commit_receipt,
                    commit.commit_receipt,
                ),
                (
                    "lease_sha256",
                    record.start_receipt.lease_sha256,
                    lease.digest,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise EffectLeaseStateError(
                "live publication commit differs from persisted authority: "
                + ", ".join(mismatches)
            )
        return record


@dataclass(frozen=True)
class LeasedEffectAuthorization:
    """One explicit, persisted capability for a single effectful call path.

    The bundle carries every authority needed by :class:`EffectLeaseLedger`
    without teaching production entrypoints how to mint leases or discover
    secrets from ambient configuration.  Entry points may *consume* this
    capability; they cannot construct a valid one without the signed lease,
    exact policy decision, issuer keyring, and persisted ledger grant.
    """

    lease: EffectLease
    request: EffectLeaseRequest
    policy_decision: PolicyDecision
    ledger: "EffectLeaseLedger"
    keyring: Mapping[str, bytes | str] = field(repr=False)
    guard_decisions: tuple[GuardDecision, ...]
    current_kill_switch_generation: int
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = field(
        default=REGISTRY_BY_ID, repr=False
    )

    def __post_init__(self) -> None:
        if self.lease.entrypoint_id != self.request.entrypoint_id:
            raise EffectLeaseBindingMismatch(
                "authorization lease and request name different entrypoints"
            )
        if not self.guard_decisions:
            raise EffectLeaseBindingMismatch(
                "authorization requires concrete guard decisions"
            )
        object.__setattr__(self, "guard_decisions", tuple(self.guard_decisions))
        object.__setattr__(self, "keyring", dict(self.keyring))

    def begin_effect(
        self,
        execution: EffectExecutionRequest,
        *,
        started_at: datetime | None = None,
    ) -> EffectStartResult:
        """Persist and verify the start before the entrypoint performs work."""

        return self.ledger.begin(
            self.lease,
            execution,
            request=self.request,
            policy_decision=self.policy_decision,
            keyring=self.keyring,
            guard_decisions=self.guard_decisions,
            current_kill_switch_generation=self.current_kill_switch_generation,
            started_at=started_at,
            registry=self.registry,
        )

    def claim_execution(
        self,
        start: EffectStartResult,
        execution: EffectExecutionRequest,
        *,
        claimed_at: datetime | None = None,
    ) -> EffectExecutionClaim:
        """Persist the exclusive execution claim before external work."""

        return self.ledger.claim_execution(
            start,
            execution,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
            claimed_at=claimed_at,
        )

    def commit_publication(
        self,
        claim: EffectExecutionClaim,
        execution: EffectExecutionRequest,
        *,
        effect_commitment_sha256: str,
        committed_at: datetime | None = None,
    ) -> EffectPublicationCommit:
        """Persist the exclusive publication commitment."""

        return self.ledger.commit_publication(
            claim,
            execution,
            effect_commitment_sha256=effect_commitment_sha256,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
            committed_at=committed_at,
        )

    def finish_effect(
        self,
        start: EffectStartResult,
        *,
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
        finished_at: datetime | None = None,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Bind and persist a terminal using the live-only start capability."""

        if not isinstance(start, EffectStartResult):
            raise TypeError("start must be an EffectStartResult")
        if not start.execute or start.completion_capability is None:
            raise EffectLeaseStateError(
                "an inert start replay has no normal terminal authority"
            )
        return self.ledger.finish(
            start.receipt,
            completion_capability=start.completion_capability,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
            persisted_at=persisted_at,
        )

    def finish_claimed_effect(
        self,
        claim: EffectExecutionClaim,
        *,
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
        finished_at: datetime | None = None,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Terminalize one exclusively claimed execution."""

        return self.ledger.finish_claim(
            claim,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
            persisted_at=persisted_at,
        )

    def finish_committed_effect(
        self,
        finalization: EffectPublicationFinalization,
        *,
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
        finished_at: datetime | None = None,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Terminalize after explicit publication success and clean exit."""

        return self.ledger.finish_committed(
            finalization,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
            persisted_at=persisted_at,
        )

    def require_live_start(
        self,
        start: EffectStartResult,
        execution: EffectExecutionRequest,
    ) -> PersistedEffectExecution:
        """Verify the exact durable start carried by this authority bundle."""

        return self.ledger.require_live_start(
            start,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            execution=execution,
            historical_keyring=self.keyring,
        )

    def require_live_claim(
        self,
        claim: EffectExecutionClaim,
        execution: EffectExecutionRequest,
    ) -> PersistedEffectExecution:
        """Verify exact claim authority immediately before provider work."""

        return self.ledger.require_live_claim(
            claim,
            execution,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
        )

    def require_live_commit(
        self,
        commit: EffectPublicationCommit,
        execution: EffectExecutionRequest,
    ) -> PersistedEffectExecution:
        """Verify fresh target authority against durable ``COMMITTING``."""

        return self.ledger.require_live_commit(
            commit,
            execution,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
        )

    def authenticated_execution_record(
        self, execution_id: str
    ) -> PersistedEffectExecution | None:
        """Authenticate one persisted execution with this authority's keyring."""

        return self.ledger.authenticated_execution_record(
            execution_id,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
        )

    def finish_terminal(
        self,
        receipt: EffectTerminalReceipt,
        *,
        authorization: TerminalAuthorization,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Persist one exact terminal bound by the live start capability."""

        return self.ledger.finish_receipt(
            receipt,
            authorization=authorization,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
            persisted_at=persisted_at,
        )

    def finish_claim_terminal(
        self,
        receipt: EffectTerminalReceipt,
        *,
        claim_receipt: EffectExecutionClaimReceipt,
        authorization: ClaimTerminalAuthorization,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Persist a pre-frozen terminal under exact claim authority."""

        return self.ledger.finish_claim_receipt(
            receipt,
            claim_receipt=claim_receipt,
            authorization=authorization,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
            persisted_at=persisted_at,
        )

    def finish_committed_terminal(
        self,
        receipt: EffectTerminalReceipt,
        *,
        claim_receipt: EffectExecutionClaimReceipt,
        commit_receipt: EffectPublicationCommitReceipt,
        outcome_receipt: EffectPublicationOutcomeReceipt,
        authorization: PublicationFinalizationAuthorization,
        persisted_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Persist one exact terminal under finalization authority."""

        return self.ledger.finish_committed_receipt(
            receipt,
            claim_receipt=claim_receipt,
            commit_receipt=commit_receipt,
            outcome_receipt=outcome_receipt,
            authorization=authorization,
            lease=self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            historical_keyring=self.keyring,
            persisted_at=persisted_at,
        )

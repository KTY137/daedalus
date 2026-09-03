"""Signed composite authority for one exact provider invocation subject.

The existing ``ProviderObservationAuthority`` authenticates the provider ID,
observation issuer keys and one runtime effect subject. This module adds an
exact, non-executing composite authority that also signs the immutable
``ProviderInvocationSubject`` and one revision-bound invocation-registry
digest. Adapter identity, artifact/config digests and the runtime effect subject
therefore become one authenticated object before a later broker may resolve an
executable adapter.

This module contains no callback, registry lookup, provider execution, effect
start, recovery action or promotion authority. Broker and durable-store
integration are separate reviewed packets.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.kernel.contracts.base import _identifier, _sha256
from daedalus.runtimes.provider.invocation import (
    ProviderInvocationSubject,
    ProviderInvocationSubjectError,
)
from daedalus.runtimes.provider.observation import (
    ProviderObservationAuthority,
    ProviderObservationAuthorityError,
    _normalize_keyring,
    verify_provider_observation_authority,
)
from daedalus.spine.envelope import canonical_sha


class ProviderInvocationAuthorityError(RuntimeError):
    """Base class for exact invocation-observation authority failures."""


class ProviderInvocationAuthoritySignatureError(ProviderInvocationAuthorityError):
    """The composite authority signature does not authenticate."""


class ProviderInvocationAuthorityBindingError(ProviderInvocationAuthorityError):
    """Nested authorities do not name one exact provider invocation."""


def _secret_bytes(secret: bytes | str, label: str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        value = secret
    else:
        raise ValueError(f"{label} must be bytes or str")
    if len(value) < 32:
        raise ValueError(f"{label} must contain at least 32 bytes")
    return value


def _signature(digest: str, secret: bytes | str, label: str) -> str:
    return hmac.new(
        _secret_bytes(secret, label),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _subject_mismatches(
    observation: ProviderObservationAuthority,
    invocation: ProviderInvocationSubject,
) -> tuple[str, ...]:
    comparisons = {
        "provider_id": (observation.provider_id, invocation.provider_id),
        "entrypoint_id": (observation.entrypoint_id, invocation.entrypoint_id),
        "runtime_id": (observation.runtime_id, invocation.runtime_id),
        "execution_id": (observation.execution_id, invocation.execution_id),
        "idempotency_key": (
            observation.idempotency_key,
            invocation.idempotency_key,
        ),
        "execution_request_sha256": (
            observation.execution_request_sha256,
            invocation.execution_request_sha256,
        ),
        "lease_sha256": (observation.lease_sha256, invocation.lease_sha256),
        "source_revision": (
            observation.source_revision,
            invocation.source_revision,
        ),
    }
    return tuple(
        sorted(
            field
            for field, (observed, invoked) in comparisons.items()
            if observed != invoked
        )
    )


@dataclass(frozen=True)
class ProviderInvocationObservationAuthority:
    """Signed provider-observation and adapter-invocation authority."""

    observation_authority: ProviderObservationAuthority
    invocation_subject: ProviderInvocationSubject
    invocation_contract_id: str
    invocation_registry_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if type(self.observation_authority) is not ProviderObservationAuthority:
            raise ProviderInvocationAuthorityBindingError(
                "observation_authority must be exact ProviderObservationAuthority"
            )
        if type(self.invocation_subject) is not ProviderInvocationSubject:
            raise ProviderInvocationAuthorityBindingError(
                "invocation_subject must be exact ProviderInvocationSubject"
            )
        try:
            object.__setattr__(
                self,
                "invocation_contract_id",
                _identifier(self.invocation_contract_id, "invocation_contract_id"),
            )
            object.__setattr__(
                self,
                "invocation_registry_sha256",
                _sha256(
                    self.invocation_registry_sha256,
                    "invocation_registry_sha256",
                ),
            )
            object.__setattr__(
                self,
                "signature_sha256",
                _sha256(self.signature_sha256, "signature_sha256"),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationAuthorityBindingError(
                "invocation-observation authority fields are malformed"
            ) from exc
        mismatches = _subject_mismatches(
            self.observation_authority,
            self.invocation_subject,
        )
        if mismatches:
            raise ProviderInvocationAuthorityBindingError(
                "invocation-observation authority subject mismatch: "
                + ", ".join(mismatches)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_authority": self.observation_authority.to_dict(),
            "invocation_subject": self.invocation_subject.to_dict(),
            "invocation_contract_id": self.invocation_contract_id,
            "invocation_registry_sha256": self.invocation_registry_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderInvocationObservationAuthority":
        expected = {
            "observation_authority",
            "invocation_subject",
            "invocation_contract_id",
            "invocation_registry_sha256",
            "signature_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderInvocationAuthorityBindingError(
                "invocation-observation authority fields are not exact"
            )
        observation = payload["observation_authority"]
        invocation = payload["invocation_subject"]
        if not isinstance(observation, Mapping) or not isinstance(invocation, Mapping):
            raise ProviderInvocationAuthorityBindingError(
                "nested invocation-observation authority fields must be objects"
            )
        try:
            return cls(
                observation_authority=ProviderObservationAuthority.from_dict(
                    observation
                ),
                invocation_subject=ProviderInvocationSubject.from_dict(invocation),
                invocation_contract_id=payload["invocation_contract_id"],
                invocation_registry_sha256=payload["invocation_registry_sha256"],
                signature_sha256=payload["signature_sha256"],
            )
        except ProviderInvocationAuthorityError:
            raise
        except (
            ProviderInvocationSubjectError,
            ProviderObservationAuthorityError,
            TypeError,
            ValueError,
        ) as exc:
            raise ProviderInvocationAuthorityBindingError(
                "nested invocation-observation authority is malformed"
            ) from exc

    @property
    def invocation_contract_sha256(self) -> str:
        return canonical_sha(
            {
                "schema": "daedalus-provider-invocation-contract/1",
                "invocation_contract_id": self.invocation_contract_id,
                "invocation_subject_sha256": self.invocation_subject.digest,
                "invocation_registry_sha256": self.invocation_registry_sha256,
            }
        )

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def issue_provider_invocation_observation_authority(
    *,
    observation_authority: ProviderObservationAuthority,
    invocation_subject: ProviderInvocationSubject,
    invocation_contract_id: str,
    invocation_registry_sha256: str,
    authority_secret: bytes | str,
) -> ProviderInvocationObservationAuthority:
    """Sign one exact non-executing provider invocation authority."""

    placeholder = ProviderInvocationObservationAuthority(
        observation_authority=observation_authority,
        invocation_subject=invocation_subject,
        invocation_contract_id=invocation_contract_id,
        invocation_registry_sha256=invocation_registry_sha256,
        signature_sha256="0" * 64,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest,
            authority_secret,
            "authority_secret",
        ),
    )


def verify_provider_invocation_observation_authority(
    authority: ProviderInvocationObservationAuthority,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    invocation_subject: ProviderInvocationSubject,
    invocation_contract_id: str,
    invocation_registry_sha256: str,
    entrypoint_id: str,
    runtime_id: str,
    execution,
    lease_sha256: str,
    source_revision: str,
    at,
) -> None:
    """Authenticate the exact observation, adapter and registry subject."""

    if type(authority) is not ProviderInvocationObservationAuthority:
        raise ProviderInvocationAuthorityBindingError(
            "authority must be exact ProviderInvocationObservationAuthority"
        )
    if type(invocation_subject) is not ProviderInvocationSubject:
        raise ProviderInvocationAuthorityBindingError(
            "invocation_subject must be exact ProviderInvocationSubject"
        )
    try:
        expected_contract_id = _identifier(
            invocation_contract_id,
            "invocation_contract_id",
        )
        expected_registry = _sha256(
            invocation_registry_sha256,
            "invocation_registry_sha256",
        )
        authority_rows = dict(
            _normalize_keyring(authority_keyring, label="authority_keyring")
        )
    except (TypeError, ValueError) as exc:
        raise ProviderInvocationAuthorityBindingError(
            "expected invocation authority subject or keyring is malformed"
        ) from exc

    try:
        verify_provider_observation_authority(
            authority.observation_authority,
            authority_id=authority_id,
            authority_keyring=authority_rows,
            observation_keyring=observation_keyring,
            entrypoint_id=entrypoint_id,
            runtime_id=runtime_id,
            execution=execution,
            lease_sha256=lease_sha256,
            source_revision=source_revision,
            at=at,
        )
    except ProviderObservationAuthorityError as exc:
        raise ProviderInvocationAuthorityBindingError(
            "nested provider-observation authority did not authenticate"
        ) from exc

    secret = authority_rows.get(
        authority.observation_authority.authority_key_id
    )
    if secret is None:
        raise ProviderInvocationAuthoritySignatureError(
            "invocation-observation authority key is unknown"
        )
    expected_signature = _signature(
        authority.signing_digest,
        secret,
        "authority_keyring secret",
    )
    if not hmac.compare_digest(authority.signature_sha256, expected_signature):
        raise ProviderInvocationAuthoritySignatureError(
            "invocation-observation authority signature mismatch"
        )

    comparisons = {
        "invocation_subject": (
            authority.invocation_subject,
            invocation_subject,
        ),
        "invocation_contract_id": (
            authority.invocation_contract_id,
            expected_contract_id,
        ),
        "invocation_registry_sha256": (
            authority.invocation_registry_sha256,
            expected_registry,
        ),
    }
    mismatches = tuple(
        sorted(
            field
            for field, (actual, expected) in comparisons.items()
            if actual != expected
        )
    )
    if mismatches:
        raise ProviderInvocationAuthorityBindingError(
            "invocation-observation authority binding mismatch: "
            + ", ".join(mismatches)
        )


__all__ = [
    "ProviderInvocationAuthorityBindingError",
    "ProviderInvocationAuthorityError",
    "ProviderInvocationAuthoritySignatureError",
    "ProviderInvocationObservationAuthority",
    "issue_provider_invocation_observation_authority",
    "verify_provider_invocation_observation_authority",
]

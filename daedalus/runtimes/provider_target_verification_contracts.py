"""Canonical inert receipts for exact provider-target source verification."""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.schemas import (
    _artifact_locator,
    _identifier,
    _repo_path,
    _revision,
    _sha256,
)
from daedalus.spine.envelope import canonical_sha


_TARGET_RE = re.compile(
    r"^daedalus(?:\.[a-z][a-z0-9_]*)*:"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)


class ProviderTargetVerificationError(RuntimeError):
    """Base class for exact source-tree target verification failures."""


class ProviderTargetVerificationBindingError(ProviderTargetVerificationError):
    """Signed target, source tree, or expected receipt bindings disagree."""


class ProviderTargetVerificationSourceError(ProviderTargetVerificationError):
    """Exact source bytes are missing, malformed, ambiguous, or substituted."""


class ProviderTargetVerificationSignatureError(ProviderTargetVerificationError):
    """The verification receipt signature did not authenticate."""


def _secret_bytes(secret: bytes | str, label: str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        value = secret
    else:
        raise ProviderTargetVerificationBindingError(
            f"{label} must be bytes or str"
        )
    if len(value) < 32:
        raise ProviderTargetVerificationBindingError(
            f"{label} must contain at least 32 bytes"
        )
    return value


def _verification_signature(
    digest: str,
    secret: bytes | str,
    label: str,
) -> str:
    return hmac.new(
        _secret_bytes(secret, label),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True)
class VerifiedPythonTarget:
    """One exact Python definition verified in one CAS-backed source file."""

    target: str
    repository_path: str
    source_sha256: str
    source_size: int
    qualified_name: str
    node_kind: str
    line: int
    end_line: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target, str)
            or _TARGET_RE.fullmatch(self.target) is None
        ):
            raise ProviderTargetVerificationBindingError(
                "verified target must be a canonical Daedalus module target"
            )
        try:
            object.__setattr__(
                self,
                "repository_path",
                _repo_path(self.repository_path, "repository_path"),
            )
            object.__setattr__(
                self,
                "source_sha256",
                _sha256(self.source_sha256, "source_sha256"),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderTargetVerificationBindingError(
                "verified target source identity is malformed"
            ) from exc
        if self.repository_path == "." or not self.repository_path.endswith(".py"):
            raise ProviderTargetVerificationBindingError(
                "verified target repository_path must name a Python source file"
            )
        if (
            not isinstance(self.qualified_name, str)
            or not self.qualified_name
            or any(
                not part.isidentifier()
                for part in self.qualified_name.split(".")
            )
        ):
            raise ProviderTargetVerificationBindingError(
                "qualified_name must be an exact Python path"
            )
        if self.node_kind not in {
            "function",
            "async_function",
            "method",
            "async_method",
        }:
            raise ProviderTargetVerificationBindingError(
                "node_kind is not a supported executable target kind"
            )
        for name in ("source_size", "line", "end_line"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProviderTargetVerificationBindingError(
                    f"{name} must be a non-negative integer"
                )
        if self.line < 1 or self.end_line < self.line:
            raise ProviderTargetVerificationBindingError(
                "verified target line range is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VerifiedPythonTarget":
        expected = {field.name for field in dataclasses.fields(cls)}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderTargetVerificationBindingError(
                "verified Python target fields are not exact"
            )
        try:
            return cls(**{field: payload[field] for field in expected})
        except ProviderTargetVerificationError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetVerificationBindingError(
                "verified Python target is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ProviderExecutableTargetVerificationReceipt:
    """Authenticated structural evidence for both signed provider targets."""

    verifier_id: str
    verifier_key_id: str
    source_revision: str
    source_tree_id: str
    source_tree_sha256: str
    source_tree_locator: str
    target_authority_sha256: str
    target_projection_sha256: str
    target_manifest_sha256: str
    target_descriptor_sha256: str
    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    lease_sha256: str
    invoke: VerifiedPythonTarget
    output_digests: VerifiedPythonTarget
    signature_sha256: str

    def __post_init__(self) -> None:
        try:
            for field in (
                "verifier_id",
                "verifier_key_id",
                "source_tree_id",
                "provider_id",
                "adapter_id",
                "implementation_id",
                "entrypoint_id",
                "runtime_id",
                "execution_id",
                "idempotency_key",
            ):
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            object.__setattr__(
                self,
                "source_tree_locator",
                _artifact_locator(
                    self.source_tree_locator,
                    "source_tree_locator",
                ),
            )
            for field in (
                "source_tree_sha256",
                "target_authority_sha256",
                "target_projection_sha256",
                "target_manifest_sha256",
                "target_descriptor_sha256",
                "lease_sha256",
                "signature_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderTargetVerificationBindingError(
                "provider target verification receipt is malformed"
            ) from exc
        if type(self.invoke) is not VerifiedPythonTarget:
            raise ProviderTargetVerificationBindingError(
                "invoke must be exact VerifiedPythonTarget"
            )
        if type(self.output_digests) is not VerifiedPythonTarget:
            raise ProviderTargetVerificationBindingError(
                "output_digests must be exact VerifiedPythonTarget"
            )
        expected_ref = ArtifactRef.from_sha256(self.source_tree_sha256)
        if self.source_tree_locator != expected_ref.locator:
            raise ProviderTargetVerificationBindingError(
                "source tree locator does not match source tree digest"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-target-verification-receipt/1",
            "verifier_id": self.verifier_id,
            "verifier_key_id": self.verifier_key_id,
            "source_revision": self.source_revision,
            "source_tree_id": self.source_tree_id,
            "source_tree_sha256": self.source_tree_sha256,
            "source_tree_locator": self.source_tree_locator,
            "target_authority_sha256": self.target_authority_sha256,
            "target_projection_sha256": self.target_projection_sha256,
            "target_manifest_sha256": self.target_manifest_sha256,
            "target_descriptor_sha256": self.target_descriptor_sha256,
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "implementation_id": self.implementation_id,
            "entrypoint_id": self.entrypoint_id,
            "runtime_id": self.runtime_id,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "lease_sha256": self.lease_sha256,
            "invoke": self.invoke.to_dict(),
            "output_digests": self.output_digests.to_dict(),
            "targets_structurally_verified": True,
            "provider_execution_allowed": False,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderExecutableTargetVerificationReceipt":
        fields = {field.name for field in dataclasses.fields(cls)}
        expected = {
            "schema",
            *fields,
            "targets_structurally_verified",
            "provider_execution_allowed",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderTargetVerificationBindingError(
                "provider target verification receipt fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-target-verification-receipt/1":
            raise ProviderTargetVerificationBindingError(
                "provider target verification receipt schema does not match"
            )
        if payload["targets_structurally_verified"] is not True:
            raise ProviderTargetVerificationBindingError(
                "verification receipt must retain structural verification"
            )
        if payload["provider_execution_allowed"] is not False:
            raise ProviderTargetVerificationBindingError(
                "verification receipt cannot authorize provider execution"
            )
        try:
            values = {field: payload[field] for field in fields}
            values["invoke"] = VerifiedPythonTarget.from_dict(payload["invoke"])
            values["output_digests"] = VerifiedPythonTarget.from_dict(
                payload["output_digests"]
            )
            return cls(**values)
        except ProviderTargetVerificationError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetVerificationBindingError(
                "provider target verification receipt is malformed"
            ) from exc

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


__all__ = [
    "ProviderExecutableTargetVerificationReceipt",
    "ProviderTargetVerificationBindingError",
    "ProviderTargetVerificationError",
    "ProviderTargetVerificationSignatureError",
    "ProviderTargetVerificationSourceError",
    "VerifiedPythonTarget",
]

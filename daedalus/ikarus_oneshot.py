"""Stateless one-shot request port for Ikarus.

Hermes exposes a useful one-shot invariant: small LLM requests run outside a
conversation and receive only the messages explicitly supplied for that call.
Ikarus keeps that behavior but binds it to Daedalus' existing runtime identity,
budget and conformance contracts instead of adding a session database, mutable
template registry, provider client, or second runtime authority.

This module is deliberately effect-free.  It does not call a model, open a
network connection, read chat history, resolve credentials, or grant a tool.
It only builds an immutable request and admits the selected runtime identity
against already-existing canonical runtime-conformance evidence.  Real provider
execution still has to pass through ``daedalus.runtimes.broker``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .ikarus_runtime_role import RuntimeRoleSnapshot
from .kernel.runtime_conformance import RuntimeConformanceError, verify_current_conformance
from .schemas import ResourceBudget, RuntimeConformanceReceipt, RuntimeManifest
from .spine.envelope import canonical_sha


IKARUS_ONESHOT_REQUEST_SCHEMA = "daedalus-ikarus-oneshot-request/1"
IKARUS_ONESHOT_ADMISSION_SCHEMA = "daedalus-ikarus-oneshot-admission/1"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OneShotContractError(ValueError):
    """A one-shot request or runtime binding is malformed or over-broad."""


class OneShotRuntimeRefused(RuntimeError):
    """The selected runtime cannot be admitted for the stateless one-shot seam."""


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise OneShotContractError(f"{name} must be a bounded identifier")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise OneShotContractError(f"{name} must be lowercase SHA-256")
    return value


def _text(value: Any, name: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise OneShotContractError(f"{name} must be a string")
    if "\x00" in value:
        raise OneShotContractError(f"{name} contains a NUL byte")
    if len(value) > max_length:
        raise OneShotContractError(f"{name} exceeds {max_length} characters")
    return value


def _budget_subject(budget: ResourceBudget) -> dict[str, int | None]:
    return {
        "max_tokens": budget.max_tokens,
        "max_cost_microusd": budget.max_cost_microusd,
        "max_wall_time_s": budget.max_wall_time_s,
        "max_attempts": budget.max_attempts,
    }


@dataclass(frozen=True)
class OneShotMessage:
    """One explicit message in a one-shot request; there is no history field."""

    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user"}:
            raise OneShotContractError("one-shot message role must be system or user")
        object.__setattr__(
            self,
            "content",
            _text(self.content, "message.content", max_length=32_000),
        )

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class OneShotRequest:
    """One sessionless, tool-less request bound to one declared runtime identity.

    The request has no conversation/session/thread/memory identifier and no
    message-history parameter.  Its iteration limit is structurally one.  A
    caller may choose a runtime, prompt and canonical resource budget; it cannot
    smuggle another turn or an ambient transcript into this contract.
    """

    purpose: str
    role: str
    runtime_id: str
    runtime_binding_sha256: str
    instructions: str
    user_input: str
    budget: ResourceBudget

    def __post_init__(self) -> None:
        object.__setattr__(self, "purpose", _identifier(self.purpose, "purpose"))
        object.__setattr__(self, "role", _identifier(self.role, "role"))
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        object.__setattr__(
            self,
            "runtime_binding_sha256",
            _sha256(self.runtime_binding_sha256, "runtime_binding_sha256"),
        )
        object.__setattr__(
            self,
            "instructions",
            _text(self.instructions, "instructions", max_length=16_000),
        )
        object.__setattr__(
            self,
            "user_input",
            _text(self.user_input, "user_input", max_length=64_000),
        )
        if not self.instructions.strip() and not self.user_input.strip():
            raise OneShotContractError(
                "one-shot request requires instructions or user_input"
            )
        if type(self.budget) is not ResourceBudget:
            raise OneShotContractError("budget must be an exact ResourceBudget")
        if self.budget.max_tokens is None or self.budget.max_tokens < 1:
            raise OneShotContractError(
                "one-shot request requires a positive max_tokens bound"
            )
        if self.budget.max_wall_time_s is None or self.budget.max_wall_time_s < 1:
            raise OneShotContractError(
                "one-shot request requires a positive max_wall_time_s bound"
            )
        if self.budget.max_attempts not in {None, 1}:
            raise OneShotContractError(
                "one-shot request may not declare more than one attempt"
            )

    @classmethod
    def from_runtime_binding(
        cls,
        binding: RuntimeRoleSnapshot,
        *,
        purpose: str,
        instructions: str = "",
        user_input: str = "",
        budget: ResourceBudget,
    ) -> "OneShotRequest":
        if type(binding) is not RuntimeRoleSnapshot:
            raise OneShotContractError(
                "one-shot request requires an exact RuntimeRoleSnapshot"
            )
        return cls(
            purpose=purpose,
            role=binding.role,
            runtime_id=binding.runtime_id,
            runtime_binding_sha256=binding.digest,
            instructions=instructions,
            user_input=user_input,
            budget=budget,
        )

    @property
    def messages(self) -> tuple[OneShotMessage, ...]:
        rows: list[OneShotMessage] = []
        if self.instructions.strip():
            rows.append(OneShotMessage(role="system", content=self.instructions))
        # Match the upstream one-shot shape: there is always exactly one user
        # message, even when its content is empty and the instructions carry the
        # whole prompt.
        rows.append(OneShotMessage(role="user", content=self.user_input))
        return tuple(rows)

    def subject(self) -> dict[str, object]:
        return {
            "schema": IKARUS_ONESHOT_REQUEST_SCHEMA,
            "purpose": self.purpose,
            "role": self.role,
            "runtime_id": self.runtime_id,
            "runtime_binding_sha256": self.runtime_binding_sha256,
            "messages": [message.to_dict() for message in self.messages],
            "budget": _budget_subject(self.budget),
            "iteration_limit": 1,
            "tool_scope": [],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.subject())


@dataclass(frozen=True)
class OneShotRuntimeAdmission:
    """Read-only projection binding one request to existing runtime evidence.

    This is not a RuntimeConformanceReceipt, Effect Lease, provider authority or
    permission to execute.  It exists so Ikarus can retain one exact answer to
    "which already-conformant runtime identity was selected for this stateless
    request?" without creating a second trust contract.
    """

    request_sha256: str
    role: str
    runtime_id: str
    runtime_binding_sha256: str
    runtime_manifest_sha256: str
    runtime_conformance_sha256: str
    source_revision: str

    def __post_init__(self) -> None:
        for name in (
            "request_sha256",
            "runtime_binding_sha256",
            "runtime_manifest_sha256",
            "runtime_conformance_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(self, "role", _identifier(self.role, "role"))
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        if not isinstance(self.source_revision, str) or not self.source_revision:
            raise OneShotContractError("source_revision must be non-empty")

    def subject(self) -> dict[str, str]:
        return {
            "schema": IKARUS_ONESHOT_ADMISSION_SCHEMA,
            "request_sha256": self.request_sha256,
            "role": self.role,
            "runtime_id": self.runtime_id,
            "runtime_binding_sha256": self.runtime_binding_sha256,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "runtime_conformance_sha256": self.runtime_conformance_sha256,
            "source_revision": self.source_revision,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.subject())


def admit_oneshot_runtime(
    request: OneShotRequest,
    binding: RuntimeRoleSnapshot,
    manifest: RuntimeManifest,
    conformance: RuntimeConformanceReceipt,
    *,
    now: datetime,
    max_conformance_age: timedelta = timedelta(days=7),
) -> OneShotRuntimeAdmission:
    """Bind a stateless request to current canonical runtime evidence.

    The selected manifest must match the exact Ikarus role binding.  Until the
    later tool-scope packet lands, this seam is deny-by-default for tools: a
    manifest that declares any tool is refused instead of relying on a provider
    default to disable it.
    """

    if type(request) is not OneShotRequest:
        raise OneShotRuntimeRefused("request must be an exact OneShotRequest")
    if type(binding) is not RuntimeRoleSnapshot:
        raise OneShotRuntimeRefused("binding must be an exact RuntimeRoleSnapshot")
    if type(manifest) is not RuntimeManifest:
        raise OneShotRuntimeRefused("manifest must be an exact RuntimeManifest")
    if type(conformance) is not RuntimeConformanceReceipt:
        raise OneShotRuntimeRefused(
            "conformance must be an exact RuntimeConformanceReceipt"
        )

    comparisons = {
        "request role": (request.role, binding.role),
        "request runtime_id": (request.runtime_id, binding.runtime_id),
        "request binding digest": (request.runtime_binding_sha256, binding.digest),
        "manifest runtime_id": (manifest.runtime_id, binding.runtime_id),
        "manifest adapter_id": (manifest.adapter_id, binding.adapter_id),
        "manifest adapter_version": (
            manifest.adapter_version,
            binding.adapter_version,
        ),
        "manifest source_revision": (
            manifest.source_revision,
            binding.source_revision,
        ),
    }
    mismatch = sorted(
        label for label, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatch:
        raise OneShotRuntimeRefused(
            "one-shot runtime identity mismatch: " + ", ".join(mismatch)
        )

    if manifest.declared_tools:
        raise OneShotRuntimeRefused(
            "one-shot tool scope is deny-by-default until canonical tool-scope projection lands"
        )
    if not manifest.capabilities.timeout:
        raise OneShotRuntimeRefused(
            "one-shot runtime must have measured timeout capability"
        )
    if (
        request.budget.max_cost_microusd is not None
        and not manifest.capabilities.cost_reporting
    ):
        raise OneShotRuntimeRefused(
            "a cost-bounded one-shot requires runtime cost reporting"
        )

    try:
        verify_current_conformance(
            conformance,
            manifest,
            now=now,
            max_age=max_conformance_age,
        )
    except RuntimeConformanceError as exc:
        raise OneShotRuntimeRefused(
            "canonical runtime conformance is not current and passed"
        ) from exc

    return OneShotRuntimeAdmission(
        request_sha256=request.digest,
        role=binding.role,
        runtime_id=binding.runtime_id,
        runtime_binding_sha256=binding.digest,
        runtime_manifest_sha256=manifest.digest,
        runtime_conformance_sha256=conformance.digest,
        source_revision=manifest.source_revision,
    )


__all__ = [
    "IKARUS_ONESHOT_ADMISSION_SCHEMA",
    "IKARUS_ONESHOT_REQUEST_SCHEMA",
    "OneShotContractError",
    "OneShotMessage",
    "OneShotRequest",
    "OneShotRuntimeAdmission",
    "OneShotRuntimeRefused",
    "admit_oneshot_runtime",
]

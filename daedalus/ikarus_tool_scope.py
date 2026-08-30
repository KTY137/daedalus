"""Policy-bound tool projection for Ikarus one-shot requests.

Hermes can select toolsets per one-shot invocation.  Daedalus keeps the useful
per-call selection behavior but does not let Ikarus, a runtime adapter, or a
provider own a second tool registry or authorization layer.  This module is a
pure projection over four already-existing subjects:

* the immutable Ikarus one-shot request;
* its current runtime-evidence binding;
* the canonical RuntimeManifest declaration; and
* the canonical PolicyDecision effect scope.

Nothing here executes a tool, resolves a plugin, reads ambient configuration,
or broadens policy.  Empty ``requested_tools`` means no tools, even when the
runtime and policy both expose more.  Explicit requests fail closed if a tool
is not both declared by the runtime and granted by policy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .schemas import PolicyDecision, RuntimeManifest
from .spine.envelope import canonical_sha


IKARUS_TOOL_SCOPE_SCHEMA = "daedalus-ikarus-tool-scope-projection/1"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_WILDCARDS = frozenset({"*", "all", "any", "wildcard", "unrestricted"})


class IkarusToolScopeRefused(RuntimeError):
    """A requested tool scope cannot be proven inside canonical authority."""


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise IkarusToolScopeRefused(f"{name} must be lowercase SHA-256")
    return value


def _tool_ids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise IkarusToolScopeRefused(f"{name} must be an iterable of tool identifiers")
    try:
        rows = tuple(values)
    except TypeError as exc:
        raise IkarusToolScopeRefused(f"{name} must be iterable") from exc

    normalized: list[str] = []
    for index, value in enumerate(rows):
        if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
            raise IkarusToolScopeRefused(
                f"{name}[{index}] must be a bounded tool identifier"
            )
        if value.lower() in _FORBIDDEN_WILDCARDS:
            raise IkarusToolScopeRefused(
                f"{name}[{index}] may not use wildcard/all-tool semantics"
            )
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise IkarusToolScopeRefused(f"{name} must not contain duplicates")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class IkarusToolScopeProjection:
    """Immutable non-authorizing answer to which tools one call may expose."""

    request_sha256: str
    runtime_evidence_sha256: str
    runtime_manifest_sha256: str
    policy_decision_sha256: str
    requested_tools: tuple[str, ...]
    disabled_tools: tuple[str, ...]
    enabled_tools: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "request_sha256",
            "runtime_evidence_sha256",
            "runtime_manifest_sha256",
            "policy_decision_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        requested = _tool_ids(self.requested_tools, "requested_tools")
        disabled = _tool_ids(self.disabled_tools, "disabled_tools")
        enabled = _tool_ids(self.enabled_tools, "enabled_tools")
        if not set(disabled).issubset(requested):
            raise IkarusToolScopeRefused("disabled_tools must be a subset of requested_tools")
        expected = tuple(sorted(set(requested) - set(disabled)))
        if enabled != expected:
            raise IkarusToolScopeRefused(
                "enabled_tools must equal requested_tools minus disabled_tools"
            )
        object.__setattr__(self, "requested_tools", requested)
        object.__setattr__(self, "disabled_tools", disabled)
        object.__setattr__(self, "enabled_tools", enabled)

    def subject(self) -> dict[str, object]:
        return {
            "schema": IKARUS_TOOL_SCOPE_SCHEMA,
            "request_sha256": self.request_sha256,
            "runtime_evidence_sha256": self.runtime_evidence_sha256,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "policy_decision_sha256": self.policy_decision_sha256,
            "requested_tools": list(self.requested_tools),
            "disabled_tools": list(self.disabled_tools),
            "enabled_tools": list(self.enabled_tools),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.subject())


def project_oneshot_tool_scope(
    request: OneShotRequest,
    runtime_evidence: OneShotRuntimeEvidenceBinding,
    manifest: RuntimeManifest,
    policy: PolicyDecision,
    *,
    requested_tools: Iterable[str] = (),
    disabled_tools: Iterable[str] = (),
) -> IkarusToolScopeProjection:
    """Project an explicit per-call tool set from existing Daedalus authority.

    There is intentionally no fallback to runtime defaults, user config,
    plugins, MCP discovery, or a global Ikarus registry.  A tool is exposed only
    when the caller explicitly requests it, the exact runtime manifest declares
    it, and the exact allow PolicyDecision grants it for this request digest.
    Explicit disablement can only narrow that already-requested set.
    """

    if type(request) is not OneShotRequest:
        raise IkarusToolScopeRefused("request must be an exact OneShotRequest")
    if type(runtime_evidence) is not OneShotRuntimeEvidenceBinding:
        raise IkarusToolScopeRefused(
            "runtime_evidence must be an exact OneShotRuntimeEvidenceBinding"
        )
    if type(manifest) is not RuntimeManifest:
        raise IkarusToolScopeRefused("manifest must be an exact RuntimeManifest")
    if type(policy) is not PolicyDecision:
        raise IkarusToolScopeRefused("policy must be an exact PolicyDecision")

    if runtime_evidence.request_sha256 != request.digest:
        raise IkarusToolScopeRefused("runtime evidence is bound to a different request")
    if runtime_evidence.runtime_manifest_sha256 != manifest.digest:
        raise IkarusToolScopeRefused("runtime evidence is bound to a different manifest")
    if runtime_evidence.runtime_id != request.runtime_id or manifest.runtime_id != request.runtime_id:
        raise IkarusToolScopeRefused("runtime identity does not match the one-shot request")
    if policy.subject_sha256 != request.digest:
        raise IkarusToolScopeRefused("policy decision is bound to a different request")
    if policy.verdict != "allow":
        raise IkarusToolScopeRefused("tool projection requires an allow PolicyDecision")

    requested = _tool_ids(requested_tools, "requested_tools")
    disabled = _tool_ids(disabled_tools, "disabled_tools")
    if not set(disabled).issubset(requested):
        raise IkarusToolScopeRefused("disabled_tools must be a subset of requested_tools")

    runtime_tools = set(manifest.declared_tools)
    policy_tools = set(policy.effect_scope.tools)
    missing_runtime = sorted(set(requested) - runtime_tools)
    missing_policy = sorted(set(requested) - policy_tools)
    if missing_runtime:
        raise IkarusToolScopeRefused(
            "requested tool(s) are not declared by the exact runtime manifest: "
            + ", ".join(missing_runtime)
        )
    if missing_policy:
        raise IkarusToolScopeRefused(
            "requested tool(s) are not granted by canonical policy: "
            + ", ".join(missing_policy)
        )
    if requested and not manifest.capabilities.tool_events:
        raise IkarusToolScopeRefused(
            "tool-capable runtime must expose provider-neutral tool events"
        )

    enabled = tuple(sorted(set(requested) - set(disabled)))
    return IkarusToolScopeProjection(
        request_sha256=request.digest,
        runtime_evidence_sha256=runtime_evidence.digest,
        runtime_manifest_sha256=manifest.digest,
        policy_decision_sha256=policy.digest,
        requested_tools=requested,
        disabled_tools=disabled,
        enabled_tools=enabled,
    )


__all__ = [
    "IKARUS_TOOL_SCOPE_SCHEMA",
    "IkarusToolScopeProjection",
    "IkarusToolScopeRefused",
    "project_oneshot_tool_scope",
]

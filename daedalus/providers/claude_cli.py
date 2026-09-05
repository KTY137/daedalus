"""Claude CLI provider behind the sealed runtime-provider broker.

Live Claude execution cannot run from ambient or callback authority.  Every
call must present one exact runtime-bound Effect Lease, execution request,
isolated-workspace binding, authenticated provider-invocation authority,
canonical payload, signed ABI, executable registry, pre-admission receipt and
provider-observation binding ledger.  The broker authenticates that complete
bundle before ``begin_effect`` and resolves the fixed Claude operation from the
pre-admitted registry; callers cannot inject an invocation or evidence callback.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..kernel.effects import EffectExecutionRequest
from ..kernel.runtime_effects import RuntimeBoundEffectAuthorization
from ..primary_tree import assert_write_allowed
from ..runtimes.broker import RuntimeInvocationResult
from ..runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from ..runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from ..runtimes.provider_invocation_abi import ProviderInvocationABIContract
from ..runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from ..runtimes.provider_invocation_payload import ProviderInvocationPayload
from ..runtimes.provider_observation import ProviderObservationBindingLedger
from ..runtimes.sealed_broker import run_sealed_runtime_provider
from ..spine.effect_boundary import Effect
from ..spine.envelope import canonical_sha
from .base import Provider, ProviderCapabilities


ENTRYPOINT_ID = "provider.claude"
RUNTIME_ID = "claude_code_cli"
_REQUIRED_EFFECTS = frozenset(
    {
        Effect.FILESYSTEM_WRITE.value,
        Effect.PROCESS_SPAWN.value,
        Effect.NETWORK_EGRESS.value,
        Effect.SPEND.value,
    }
)


class ClaudeProviderAuthorizationRequired(RuntimeError):
    """A live Claude invocation lacked exact persisted runtime/effect authority."""


class ClaudeProviderWorkspaceMismatch(RuntimeError):
    """The runtime capability was not bound to the supplied isolated worktree."""


class ClaudeProviderScopeMismatch(RuntimeError):
    """The narrowed execution scope understates what the agentic CLI can do."""


class ClaudeInvocationBindingMismatch(RuntimeError):
    """The execution idempotency identity does not bind the exact provider call."""


@dataclass(frozen=True)
class ClaudeWorkspaceGrant:
    """Structural binding for one already-created isolated worktree.

    This record is deliberately not described as an authority. The persisted
    runtime trust record and Effect Lease are the security authorities; this
    value closes accidental request/execution/path recombination inside the
    adapter. Canonical registry activation still requires an authenticated
    attempt-workspace capability supplied by the attempt ledger boundary.
    """

    attempt_id: str
    source_revision: str
    request_sha256: str
    execution_sha256: str
    worktree: str

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, str) or not self.attempt_id.strip():
            raise ValueError("Claude workspace binding requires an attempt_id")
        if not isinstance(self.source_revision, str) or not self.source_revision.strip():
            raise ValueError("Claude workspace binding requires a source_revision")
        for name in ("request_sha256", "execution_sha256"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError(
                    f"Claude workspace binding {name} must be lowercase SHA-256"
                )
        if not isinstance(self.worktree, str) or not self.worktree.strip():
            raise ValueError("Claude workspace binding requires a worktree path")


def _required_text(value: Any, name: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds {max_length} characters")
    return value


def _normalize_paths(paths: list[str]) -> list[str]:
    if not isinstance(paths, list):
        raise ClaudeProviderScopeMismatch("Claude paths must be a list")
    normalized: list[str] = []
    for index, raw in enumerate(paths):
        if not isinstance(raw, str) or not raw.strip():
            raise ClaudeProviderScopeMismatch(f"Claude path hint {index} is empty")
        if "\x00" in raw:
            raise ClaudeProviderScopeMismatch(
                f"Claude path hint {index} contains a NUL byte"
            )
        candidate = PurePosixPath(raw.replace("\\", "/"))
        drive_qualified = bool(candidate.parts and ":" in candidate.parts[0])
        if candidate.is_absolute() or drive_qualified or ".." in candidate.parts:
            raise ClaudeProviderScopeMismatch(
                f"Claude path hint {raw!r} escapes the isolated worktree"
            )
        text = candidate.as_posix()
        if text == ".":
            continue
        normalized.append(text)
    return list(dict.fromkeys(normalized))


def claude_invocation_sha256(
    *,
    objective: str,
    worktree: str,
    paths: list[str],
    agent: Mapping[str, Any],
    model: str,
    timeout_s: int,
    attempt_id: str,
    source_revision: str,
    request_sha256: str,
) -> str:
    """Canonical identity callers must bind into the execution idempotency key."""

    objective = _required_text(objective, "objective", max_length=16000)
    model = _required_text(model, "model", max_length=200)
    attempt_id = _required_text(attempt_id, "attempt_id", max_length=200)
    source_revision = _required_text(
        source_revision,
        "source_revision",
        max_length=64,
    )
    if (
        not isinstance(request_sha256, str)
        or len(request_sha256) != 64
        or any(char not in "0123456789abcdef" for char in request_sha256)
    ):
        raise ValueError("request_sha256 must be lowercase SHA-256")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or timeout_s <= 0:
        raise ValueError("timeout_s must be a positive integer")
    if not isinstance(agent, Mapping):
        raise ValueError("agent must be a mapping")
    try:
        resolved_worktree = str(Path(worktree).expanduser().resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude invocation worktree could not be resolved"
        ) from exc
    return canonical_sha(
        {
            "entrypoint_id": ENTRYPOINT_ID,
            "runtime_id": RUNTIME_ID,
            "objective": objective,
            "worktree": resolved_worktree,
            "paths": _normalize_paths(paths),
            "agent": dict(agent),
            "model": model,
            "timeout_s": timeout_s,
            "attempt_id": attempt_id,
            "source_revision": source_revision,
            "request_sha256": request_sha256,
        }
    )


def claude_idempotency_key(invocation_sha256: str) -> str:
    if (
        not isinstance(invocation_sha256, str)
        or len(invocation_sha256) != 64
        or any(char not in "0123456789abcdef" for char in invocation_sha256)
    ):
        raise ValueError("Claude invocation identity must be lowercase SHA-256")
    return f"claude-{invocation_sha256}"


def _validate_execution_shape(
    execution: EffectExecutionRequest,
    paths: list[str],
) -> list[str]:
    effects = set(execution.requested_effects)
    missing = sorted(_REQUIRED_EFFECTS - effects)
    if missing:
        raise ClaudeProviderScopeMismatch(
            "Claude execution understates provider effects: " + ", ".join(missing)
        )
    if "." not in execution.writable_paths:
        raise ClaudeProviderScopeMismatch(
            "agentic Claude execution must lease the isolated worktree root '.'"
        )
    if "claude" not in execution.tools:
        raise ClaudeProviderScopeMismatch(
            "Claude execution must name the exact 'claude' process tool"
        )
    if execution.max_cost_microusd <= 0:
        raise ClaudeProviderScopeMismatch(
            "Claude execution requires a positive explicit spend ceiling"
        )
    return _normalize_paths(paths)


def _resolve_workspace(
    repo_root: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    grant: ClaudeWorkspaceGrant,
) -> Path:
    if grant.attempt_id != authorization.request.attempt_id:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude workspace binding belongs to a different attempt"
        )
    expected_revision = authorization.request.provenance.source_revision
    if grant.source_revision != expected_revision:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude workspace binding belongs to a different source revision"
        )
    if grant.request_sha256 != authorization.request.digest:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude workspace binding belongs to a different lease request"
        )
    if grant.execution_sha256 != execution.digest:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude workspace binding belongs to a different execution request"
        )
    try:
        supplied = Path(repo_root).expanduser().resolve(strict=True)
        granted = Path(grant.worktree).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude workspace path could not be resolved"
        ) from exc
    if not supplied.is_dir() or supplied != granted:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude repo_root is not the exact bound worktree"
        )
    assert_write_allowed(supplied, what="Claude runtime workspace")
    return supplied


def _require_sealed_bundle(
    *,
    invocation_authority: ProviderInvocationObservationAuthority | None,
    invocation_payload: ProviderInvocationPayload | None,
    invocation_abi: ProviderInvocationABIContract | None,
    executable_registry: ProviderExecutableObjectRegistry | None,
    pre_admission: ProviderExecutablePreAdmissionReceipt | None,
    observation_binding_ledger: ProviderObservationBindingLedger | None,
) -> None:
    if (
        invocation_authority is None
        or invocation_payload is None
        or invocation_abi is None
        or executable_registry is None
        or pre_admission is None
        or observation_binding_ledger is None
    ):
        raise ClaudeProviderAuthorizationRequired(
            "Claude live execution requires the complete sealed invocation bundle: "
            "invocation authority, payload, ABI, executable registry, pre-admission, "
            "and provider-observation binding ledger"
        )


class ClaudeCLIProvider(Provider):
    """Agentic Claude CLI adapter whose only live seam is the sealed broker."""

    caps = ProviderCapabilities(
        name="claude_cli",
        can_write=True,
        local=False,
        trusted_with_ip=True,
        agentic=True,
    )

    def available(self) -> bool:
        return shutil.which("claude") is not None

    def run(
        self,
        *,
        objective: str,
        repo_root: str,
        paths: list[str],
        agent: dict[str, Any],
        model: str | None = None,
        timeout_s: int = 300,
        policy: Any | None = None,
        runtime_authorization: RuntimeBoundEffectAuthorization | None = None,
        effect_execution: EffectExecutionRequest | None = None,
        workspace_grant: ClaudeWorkspaceGrant | None = None,
        invocation_authority: ProviderInvocationObservationAuthority | None = None,
        invocation_payload: ProviderInvocationPayload | None = None,
        invocation_abi: ProviderInvocationABIContract | None = None,
        executable_registry: ProviderExecutableObjectRegistry | None = None,
        pre_admission: ProviderExecutablePreAdmissionReceipt | None = None,
        observation_binding_ledger: ProviderObservationBindingLedger | None = None,
    ) -> dict[str, Any]:
        del policy
        if runtime_authorization is None or effect_execution is None:
            raise ClaudeProviderAuthorizationRequired(
                "Claude live execution requires runtime-bound Effect-Lease authority"
            )
        if workspace_grant is None:
            raise ClaudeProviderAuthorizationRequired(
                "Claude live execution requires an exact isolated-workspace binding"
            )
        _require_sealed_bundle(
            invocation_authority=invocation_authority,
            invocation_payload=invocation_payload,
            invocation_abi=invocation_abi,
            executable_registry=executable_registry,
            pre_admission=pre_admission,
            observation_binding_ledger=observation_binding_ledger,
        )

        normalized_paths = _validate_execution_shape(effect_execution, paths)
        workspace = _resolve_workspace(
            repo_root,
            authorization=runtime_authorization,
            execution=effect_execution,
            grant=workspace_grant,
        )
        resolved_model = model or str(agent.get("model_tier", "sonnet"))
        attempt_id = runtime_authorization.request.attempt_id
        source_revision = runtime_authorization.request.provenance.source_revision
        request_sha256 = runtime_authorization.request.digest
        invocation_sha256 = claude_invocation_sha256(
            objective=objective,
            worktree=str(workspace),
            paths=normalized_paths,
            agent=agent,
            model=resolved_model,
            timeout_s=timeout_s,
            attempt_id=attempt_id,
            source_revision=source_revision,
            request_sha256=request_sha256,
        )
        expected_idempotency = claude_idempotency_key(invocation_sha256)
        if effect_execution.idempotency_key != expected_idempotency:
            raise ClaudeInvocationBindingMismatch(
                "Claude execution idempotency key does not bind the exact invocation"
            )

        expected_payload = {
            "objective": objective,
            "worktree": str(workspace),
            "paths": normalized_paths,
            "agent": dict(agent),
            "model": resolved_model,
            "timeout_s": timeout_s,
            "attempt_id": attempt_id,
            "source_revision": source_revision,
            "request_sha256": request_sha256,
            "invocation_sha256": invocation_sha256,
        }
        assert invocation_payload is not None
        assert invocation_authority is not None
        assert invocation_abi is not None
        assert executable_registry is not None
        assert pre_admission is not None
        assert observation_binding_ledger is not None
        if invocation_payload.to_dict()["body"] != expected_payload:
            raise ClaudeInvocationBindingMismatch(
                "Claude authenticated payload does not match the exact invocation"
            )

        invocation: RuntimeInvocationResult[dict[str, Any]] = run_sealed_runtime_provider(
            ENTRYPOINT_ID,
            authorization=runtime_authorization,
            execution=effect_execution,
            invocation_authority=invocation_authority,
            invocation_payload=invocation_payload,
            invocation_abi=invocation_abi,
            observation_binding_ledger=observation_binding_ledger,
            executable_registry=executable_registry,
            pre_admission=pre_admission,
        )

        runtime_receipt = {
            "executed": invocation.executed,
            "invocation_sha256": invocation_sha256,
            "start_receipt_sha256": invocation.start_receipt.receipt_sha256,
            "terminal_receipt_sha256": (
                invocation.terminal_receipt.receipt_sha256
                if invocation.terminal_receipt is not None
                else None
            ),
        }
        if not invocation.executed:
            return {
                "provider": self.caps.name,
                "replay": True,
                "runtime_receipt": runtime_receipt,
            }
        value = invocation.value
        if not isinstance(value, dict):
            raise RuntimeError("Claude broker released a non-object provider value")
        return {
            "provider": self.caps.name,
            "agent": value["agent"],
            "report": value["report"],
            "prompt_sha256": value["prompt_sha256"],
            "report_sha256": value["report_sha256"],
            "runtime_receipt": runtime_receipt,
        }


__all__ = [
    "ClaudeCLIProvider",
    "ClaudeInvocationBindingMismatch",
    "ClaudeProviderAuthorizationRequired",
    "ClaudeProviderScopeMismatch",
    "ClaudeProviderWorkspaceMismatch",
    "ClaudeWorkspaceGrant",
    "ENTRYPOINT_ID",
    "RUNTIME_ID",
    "claude_idempotency_key",
    "claude_invocation_sha256",
]

"""Claude CLI provider behind the persisted runtime-provider broker.

The public provider method cannot invoke Claude from ambient authority. It
requires one exact :class:`RuntimeBoundEffectAuthorization`, one narrowed
:class:`EffectExecutionRequest`, an isolated-workspace binding tied to the
same request, execution, attempt, source revision, and invocation payload,
plus the exact signed :class:`ProviderObservationAuthority` and its
:class:`ProviderObservationBindingLedger` that the broker authenticates and
persists before external code runs. The generic broker persists grant/start
state, suppresses exact replay, rechecks runtime trust, retains output
identities, and commits terminal state before a provider value is released.

The sealed subprocess implementation remains private in
:mod:`daedalus.claude_bridge` because its authenticated source locator and
executable-object identity are persistent admission inputs. Neutral Claude
workspace and refusal contracts are owned by
:mod:`daedalus.runtimes.contracts.claude` and reexported here. Calling the
private helper directly is not a supported production entrypoint.
"""
from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..kernel.effects import EffectExecutionRequest
from ..kernel.runtime_effects import RuntimeBoundEffectAuthorization
from ..limit_policy import ExecutionLimitPolicy
from ..primary_tree import assert_write_allowed
from ..runtimes.broker import RuntimeInvocationResult, run_runtime_provider
from ..runtimes.contracts.claude import (
    CLAUDE_ENTRYPOINT_ID as ENTRYPOINT_ID,
    CLAUDE_RUNTIME_ID as RUNTIME_ID,
    ClaudeInvocationBindingMismatch,
    ClaudeProviderAuthorizationRequired,
    ClaudeProviderScopeMismatch,
    ClaudeProviderWorkspaceMismatch,
    ClaudeWorkspaceGrant,
)
from ..runtimes.provider.executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from ..runtimes.provider.executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from ..runtimes.provider.invocation_abi import ProviderInvocationABIContract
from ..runtimes.provider.invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from ..runtimes.provider.invocation_payload import ProviderInvocationPayload
from ..runtimes.provider.observation import (
    ProviderObservationBindingLedger,
)
from ..spine.effect_boundary import Effect
from ..spine.envelope import canonical_sha
from ..runtimes.providers.token_policy import trim_paths
from ._report import bounded_execution_limit_policy
from .base import Provider, ProviderCapabilities


_REQUIRED_EFFECTS = frozenset(
    {
        Effect.FILESYSTEM_WRITE.value,
        Effect.PROCESS_SPAWN.value,
        Effect.NETWORK_EGRESS.value,
        Effect.SPEND.value,
    }
)


def _required_text(
    value: Any,
    name: str,
    *,
    max_length: int | None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{name} exceeds {max_length} characters")
    return value


def _effective_timeout(
    policy: ExecutionLimitPolicy,
    timeout_s: int | float | None,
    *,
    bounded_default: int = 300,
) -> int | float | None:
    """Resolve one real deadline; ``None`` is the explicit unbounded value."""

    if not policy.enforces("wall_time"):
        return None
    value = bounded_default if timeout_s is None else timeout_s
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
    ):
        raise ValueError("timeout_s must be a positive number")
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
    timeout_s: int | float | None,
    attempt_id: str,
    source_revision: str,
    request_sha256: str,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> str:
    """Canonical identity callers must bind into the execution idempotency key."""

    explicit_limit_policy = execution_limit_policy is not None
    limit_policy = bounded_execution_limit_policy(execution_limit_policy)
    objective = _required_text(
        objective,
        "objective",
        max_length=16000 if limit_policy.enforces("tokens") else None,
    )
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
    effective_timeout = _effective_timeout(limit_policy, timeout_s)
    if not isinstance(agent, Mapping):
        raise ValueError("agent must be a mapping")
    try:
        resolved_worktree = str(Path(worktree).expanduser().resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude invocation worktree could not be resolved"
        ) from exc
    body = {
            "entrypoint_id": ENTRYPOINT_ID,
            "runtime_id": RUNTIME_ID,
            "objective": objective,
            "worktree": resolved_worktree,
            "paths": trim_paths(
                _normalize_paths(paths),
                limit_policy=limit_policy,
            ),
            "agent": dict(agent),
            "model": model,
            "timeout_s": effective_timeout,
            "attempt_id": attempt_id,
            "source_revision": source_revision,
            "request_sha256": request_sha256,
        }
    # Preserve legacy replay identities when no Revision-10 snapshot was
    # supplied. Newly admitted calls bind the exact snapshot, including a
    # deliberately explicit bounded policy.
    if explicit_limit_policy:
        body["execution_limit_policy"] = limit_policy.as_dict()
        body["execution_limit_policy_sha256"] = limit_policy.fingerprint_sha256
    return canonical_sha(body)


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
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> list[str]:
    limit_policy = bounded_execution_limit_policy(execution_limit_policy)
    effects = set(execution.requested_effects)
    missing = sorted(_REQUIRED_EFFECTS - effects)
    if missing:
        raise ClaudeProviderScopeMismatch(
            "Claude execution understates provider effects: " + ", ".join(missing)
        )
    # The current Claude CLI permission mode is agentic and can inspect or edit
    # any file in its isolated worktree, regardless of path hints. Claiming a
    # narrower write set would be false evidence. The safe broad scope is the
    # worktree root, while the primary checkout is excluded separately.
    if "." not in execution.writable_paths:
        raise ClaudeProviderScopeMismatch(
            "agentic Claude execution must lease the isolated worktree root '.'"
        )
    if "claude" not in execution.tools:
        raise ClaudeProviderScopeMismatch(
            "Claude execution must name the exact 'claude' process tool"
        )
    if limit_policy.enforces("mission_spend"):
        if (
            execution.max_cost_microusd is None
            or execution.max_cost_microusd <= 0
        ):
            raise ClaudeProviderScopeMismatch(
                "Claude execution requires a positive explicit spend ceiling"
            )
    elif execution.max_cost_microusd is not None:
        raise ClaudeProviderScopeMismatch(
            "Claude execution must carry null cost when mission spend is disabled"
        )
    return trim_paths(
        _normalize_paths(paths),
        limit_policy=limit_policy,
    )


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
    # This closes Daedalus self-work structurally. A generic target-repository
    # primary-tree proof must come from the authenticated attempt capability
    # required before the canonical provider row may become CENTRAL.
    assert_write_allowed(supplied, what="Claude runtime workspace")
    return supplied


def _output_digests(value, payload):
    """Content-address exact invocation, prompt, report and semantic output."""

    import hashlib as local_hashlib
    import json as local_json

    report = value.get("report")
    agent = value.get("agent")
    prompt_sha256 = value.get("prompt_sha256")
    report_sha256 = value.get("report_sha256")
    if type(report) is not dict or not isinstance(agent, str) or not agent:
        raise ValueError("Claude provider returned malformed structured output")
    report_bytes = local_json.dumps(
        dict(report),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    computed_report = local_hashlib.sha256(report_bytes).hexdigest()
    if report_sha256 != computed_report:
        raise ValueError("Claude provider report digest does not match report bytes")
    for name, digest in (
        ("prompt_sha256", prompt_sha256),
        ("report_sha256", report_sha256),
    ):
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError(f"Claude provider {name} is not lowercase SHA-256")
    return (
        local_hashlib.sha256(
            local_json.dumps(
                {
                    "provider": "claude_cli",
                    "agent": agent,
                    "invocation_sha256": payload["invocation_sha256"],
                    "prompt_sha256": prompt_sha256,
                    "report_sha256": report_sha256,
                    "report": dict(report),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest(),
    )


class ClaudeCLIProvider(Provider):
    """Agentic Claude CLI adapter whose public execution seam is brokered."""

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
        timeout_s: int | float | None = 300,
        policy: Any | None = None,  # retained for the common provider interface
        execution_limit_policy: ExecutionLimitPolicy | None = None,
        runtime_authorization: RuntimeBoundEffectAuthorization | None = None,
        effect_execution: EffectExecutionRequest | None = None,
        workspace_grant: ClaudeWorkspaceGrant | None = None,
        invocation_authority: ProviderInvocationObservationAuthority | None = None,
        invocation_payload: ProviderInvocationPayload | None = None,
        invocation_abi: ProviderInvocationABIContract | None = None,
        observation_binding_ledger: ProviderObservationBindingLedger | None = None,
        executable_registry: ProviderExecutableObjectRegistry | None = None,
        pre_admission: ProviderExecutablePreAdmissionReceipt | None = None,
    ) -> dict[str, Any]:
        del policy
        explicit_limit_policy = execution_limit_policy is not None
        limit_policy = bounded_execution_limit_policy(execution_limit_policy)
        effective_timeout = _effective_timeout(limit_policy, timeout_s)
        if runtime_authorization is None or effect_execution is None:
            raise ClaudeProviderAuthorizationRequired(
                "Claude live execution requires runtime-bound Effect-Lease authority"
            )
        if workspace_grant is None:
            raise ClaudeProviderAuthorizationRequired(
                "Claude live execution requires an exact isolated-workspace binding"
            )
        if (
            invocation_authority is None
            or invocation_payload is None
            or invocation_abi is None
            or observation_binding_ledger is None
            or executable_registry is None
            or pre_admission is None
        ):
            raise ClaudeProviderAuthorizationRequired(
                "Claude live execution requires the authenticated invocation ABI, "
                "payload, executable registry, pre-admission, and binding ledger"
            )
        normalized_paths = _validate_execution_shape(
            effect_execution,
            paths,
            limit_policy,
        )
        workspace = _resolve_workspace(
            repo_root,
            authorization=runtime_authorization,
            execution=effect_execution,
            grant=workspace_grant,
        )
        resolved_model = model or str(agent.get("model_tier", "sonnet"))
        invocation_sha256 = claude_invocation_sha256(
            objective=objective,
            worktree=str(workspace),
            paths=normalized_paths,
            agent=agent,
            model=resolved_model,
            timeout_s=effective_timeout,
            attempt_id=runtime_authorization.request.attempt_id,
            source_revision=runtime_authorization.request.provenance.source_revision,
            request_sha256=runtime_authorization.request.digest,
            execution_limit_policy=(
                limit_policy if explicit_limit_policy else None
            ),
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
            "timeout_s": effective_timeout,
            "invocation_sha256": invocation_sha256,
        }
        if explicit_limit_policy:
            expected_payload["execution_limit_policy"] = limit_policy.as_dict()
            expected_payload["execution_limit_policy_sha256"] = (
                limit_policy.fingerprint_sha256
            )
        if invocation_payload.to_dict()["body"] != expected_payload:
            raise ClaudeInvocationBindingMismatch(
                "Claude authenticated payload does not match the exact invocation"
            )

        invocation: RuntimeInvocationResult[dict[str, Any]] = run_runtime_provider(
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
                "execution_limit_policy": limit_policy.as_dict(),
                "execution_limit_policy_sha256": limit_policy.fingerprint_sha256,
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
            "execution_limit_policy": limit_policy.as_dict(),
            "execution_limit_policy_sha256": limit_policy.fingerprint_sha256,
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

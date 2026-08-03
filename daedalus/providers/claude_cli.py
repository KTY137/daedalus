"""Claude CLI provider behind the persisted runtime-provider broker.

The public provider method cannot invoke Claude from ambient authority. It
requires one exact :class:`RuntimeBoundEffectAuthorization`, one narrowed
:class:`EffectExecutionRequest`, and an isolated-workspace grant tied to the
same request, execution, attempt, source revision, and invocation payload. The
generic broker persists grant/start state, suppresses exact replay, rechecks
runtime trust, retains output identities, and commits terminal state before a
provider value is released.

The subprocess implementation remains private in :mod:`daedalus.claude_bridge`.
Calling that helper directly is not a supported production entrypoint.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..claude_bridge import _invoke_claude_cli
from ..kernel.effects import EffectExecutionRequest
from ..kernel.runtime_effects import RuntimeBoundEffectAuthorization
from ..primary_tree import assert_write_allowed
from ..runtimes.broker import RuntimeInvocationResult, run_runtime_provider
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
    """Narrow caller-to-provider binding for one already-created worktree.

    This is not a substitute for the persisted runtime and Effect-Lease
    authorities. It closes the accidental path-substitution seam between the
    attempt that requested the lease and the directory handed to Claude. The
    request/execution identities make stale or recombined grants fail closed.
    """

    attempt_id: str
    source_revision: str
    request_sha256: str
    execution_sha256: str
    worktree: str

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, str) or not self.attempt_id.strip():
            raise ValueError("Claude workspace grant requires an attempt_id")
        if not isinstance(self.source_revision, str) or not self.source_revision.strip():
            raise ValueError("Claude workspace grant requires a source_revision")
        for name in ("request_sha256", "execution_sha256"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError(f"Claude workspace grant {name} must be lowercase SHA-256")
        if not isinstance(self.worktree, str) or not self.worktree.strip():
            raise ValueError("Claude workspace grant requires a worktree path")


def _normalize_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for index, raw in enumerate(paths):
        if not isinstance(raw, str) or not raw.strip():
            raise ClaudeProviderScopeMismatch(f"Claude path hint {index} is empty")
        candidate = PurePosixPath(raw.replace("\\", "/"))
        if candidate.is_absolute() or ".." in candidate.parts:
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
            "Claude workspace grant belongs to a different attempt"
        )
    expected_revision = authorization.request.provenance.source_revision
    if grant.source_revision != expected_revision:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude workspace grant belongs to a different source revision"
        )
    if grant.request_sha256 != authorization.request.digest:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude workspace grant belongs to a different lease request"
        )
    if grant.execution_sha256 != execution.digest:
        raise ClaudeProviderWorkspaceMismatch(
            "Claude workspace grant belongs to a different execution request"
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
            "Claude repo_root is not the exact granted worktree"
        )
    # For Daedalus self-work this is the structural no-primary-checkout fence.
    # For another repository the attempt-owned exact-path grant above remains
    # the relevant identity binding.
    assert_write_allowed(supplied, what="Claude runtime workspace")
    return supplied


def _output_digests(
    value: Mapping[str, Any],
    *,
    invocation_sha256: str,
) -> tuple[str, ...]:
    """Content-address exact invocation, prompt, report and semantic output."""

    report = value.get("report")
    agent = value.get("agent")
    prompt_sha256 = value.get("prompt_sha256")
    report_sha256 = value.get("report_sha256")
    if not isinstance(report, Mapping) or not isinstance(agent, str) or not agent:
        raise ValueError("Claude provider returned malformed structured output")
    computed_report = canonical_sha(dict(report))
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
        canonical_sha(
            {
                "provider": "claude_cli",
                "agent": agent,
                "invocation_sha256": invocation_sha256,
                "prompt_sha256": prompt_sha256,
                "report_sha256": report_sha256,
                "report": dict(report),
            }
        ),
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
        timeout_s: int = 300,
        policy: Any | None = None,  # retained for the common provider interface
        runtime_authorization: RuntimeBoundEffectAuthorization | None = None,
        effect_execution: EffectExecutionRequest | None = None,
        workspace_grant: ClaudeWorkspaceGrant | None = None,
    ) -> dict[str, Any]:
        del policy
        if runtime_authorization is None or effect_execution is None:
            raise ClaudeProviderAuthorizationRequired(
                "Claude live execution requires runtime-bound Effect-Lease authority"
            )
        if workspace_grant is None:
            raise ClaudeProviderAuthorizationRequired(
                "Claude live execution requires an exact isolated-workspace grant"
            )
        normalized_paths = _validate_execution_shape(effect_execution, paths)
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
            timeout_s=timeout_s,
            attempt_id=runtime_authorization.request.attempt_id,
            source_revision=runtime_authorization.request.provenance.source_revision,
            request_sha256=runtime_authorization.request.digest,
        )
        expected_idempotency = claude_idempotency_key(invocation_sha256)
        if effect_execution.idempotency_key != expected_idempotency:
            raise ClaudeInvocationBindingMismatch(
                "Claude execution idempotency key does not bind the exact invocation"
            )

        invocation: RuntimeInvocationResult[dict[str, Any]] = run_runtime_provider(
            ENTRYPOINT_ID,
            authorization=runtime_authorization,
            execution=effect_execution,
            invoke=lambda: _invoke_claude_cli(
                objective=objective,
                repo_root=str(workspace),
                paths=normalized_paths,
                agent=agent,
                model=resolved_model,
                timeout_s=timeout_s,
            ),
            output_digests=lambda value: _output_digests(
                value,
                invocation_sha256=invocation_sha256,
            ),
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

"""Claude CLI provider behind the persisted runtime-provider broker.

The public provider method cannot invoke Claude from ambient authority.  It
requires one exact :class:`RuntimeBoundEffectAuthorization`, one narrowed
:class:`EffectExecutionRequest`, and an isolated-workspace grant tied to the
same attempt.  The generic broker persists grant/start state, suppresses exact
replay, rechecks runtime trust, retains output identities, and commits terminal
state before a provider value is released.

The subprocess implementation remains private in :mod:`daedalus.claude_bridge`.
Calling that helper directly is not a supported production entrypoint.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..claude_bridge import _invoke_claude_cli
from ..kernel.effects import EffectExecutionRequest
from ..kernel.runtime_effects import RuntimeBoundEffectAuthorization
from ..primary_tree import assert_write_allowed
from ..runtimes.broker import RuntimeInvocationResult, run_runtime_provider
from ..spine.envelope import canonical_sha
from .base import Provider, ProviderCapabilities


ENTRYPOINT_ID = "provider.claude"
RUNTIME_ID = "claude_code_cli"


class ClaudeProviderAuthorizationRequired(RuntimeError):
    """A live Claude invocation lacked exact persisted runtime/effect authority."""


class ClaudeProviderWorkspaceMismatch(RuntimeError):
    """The runtime capability was not bound to the supplied isolated worktree."""


@dataclass(frozen=True)
class ClaudeWorkspaceGrant:
    """Narrow caller-to-provider binding for one already-created worktree.

    This is not a substitute for the persisted runtime and Effect-Lease
    authorities.  It closes the accidental path-substitution seam between the
    attempt that requested the lease and the directory handed to Claude.  The
    exact attempt and source revision still come from the authenticated
    authorization.
    """

    attempt_id: str
    source_revision: str
    worktree: str

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, str) or not self.attempt_id.strip():
            raise ValueError("Claude workspace grant requires an attempt_id")
        if not isinstance(self.source_revision, str) or not self.source_revision.strip():
            raise ValueError("Claude workspace grant requires a source_revision")
        if not isinstance(self.worktree, str) or not self.worktree.strip():
            raise ValueError("Claude workspace grant requires a worktree path")


def _resolve_workspace(
    repo_root: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
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
    assert_write_allowed(
        supplied,
        what="Claude runtime workspace",
    )
    return supplied


def _output_digests(value: Mapping[str, Any]) -> tuple[str, ...]:
    """Content-address the released semantic output, not ambient file paths."""

    report = value.get("report")
    agent = value.get("agent")
    if not isinstance(report, Mapping) or not isinstance(agent, str) or not agent:
        raise ValueError("Claude provider returned malformed structured output")
    return (
        canonical_sha(
            {
                "provider": "claude_cli",
                "agent": agent,
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
        workspace = _resolve_workspace(
            repo_root,
            authorization=runtime_authorization,
            grant=workspace_grant,
        )

        invocation: RuntimeInvocationResult[dict[str, Any]] = run_runtime_provider(
            ENTRYPOINT_ID,
            authorization=runtime_authorization,
            execution=effect_execution,
            invoke=lambda: _invoke_claude_cli(
                objective=objective,
                repo_root=str(workspace),
                paths=paths,
                agent=agent,
                model=model or agent.get("model_tier", "sonnet"),
                timeout_s=timeout_s,
            ),
            output_digests=_output_digests,
        )
        runtime_receipt = {
            "executed": invocation.executed,
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
    "ClaudeProviderAuthorizationRequired",
    "ClaudeProviderWorkspaceMismatch",
    "ClaudeWorkspaceGrant",
    "ENTRYPOINT_ID",
    "RUNTIME_ID",
]

"""Neutral contracts for the Claude runtime-provider compatibility surface.

The legacy provider module remains the registered Effect Registry target.  It
reexports these values so callers can migrate without creating a second
workspace-binding or error authority.
"""
from __future__ import annotations

from dataclasses import dataclass


CLAUDE_ENTRYPOINT_ID = "provider.claude"
CLAUDE_RUNTIME_ID = "claude_code_cli"


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


__all__ = [
    "CLAUDE_ENTRYPOINT_ID",
    "CLAUDE_RUNTIME_ID",
    "ClaudeInvocationBindingMismatch",
    "ClaudeProviderAuthorizationRequired",
    "ClaudeProviderScopeMismatch",
    "ClaudeProviderWorkspaceMismatch",
    "ClaudeWorkspaceGrant",
]

"""Detached Claude operation for the sealed runtime-provider registry.

The D4 broker must not receive caller-selected Python callbacks.  This module
provides the fixed, source-addressable Claude executable object that may be
pre-admitted by :class:`ProviderExecutableObjectRegistry`: one payload-only
invocation function and one payload-bound output-evidence function.

No authority is created here.  The sealed broker authenticates the invocation
subject, payload, ABI, executable registry and pre-admission before these
functions can run.
"""
from __future__ import annotations

from typing import Any

from ..claude_bridge import _invoke_claude_cli
from ..spine.envelope import canonical_sha


_REQUIRED_FIELDS = frozenset(
    {
        "objective",
        "worktree",
        "paths",
        "agent",
        "model",
        "timeout_s",
        "invocation_sha256",
    }
)


def _payload(payload: Any) -> dict[str, Any]:
    """Return one exact Claude payload or fail closed before any subprocess."""

    if type(payload) is not dict or set(payload) != _REQUIRED_FIELDS:
        raise ValueError("sealed Claude payload fields are not exact")
    objective = payload["objective"]
    worktree = payload["worktree"]
    paths = payload["paths"]
    agent = payload["agent"]
    model = payload["model"]
    timeout_s = payload["timeout_s"]
    invocation_sha256 = payload["invocation_sha256"]
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("sealed Claude objective must be non-empty")
    if not isinstance(worktree, str) or not worktree.strip():
        raise ValueError("sealed Claude worktree must be non-empty")
    if type(paths) is not list or any(
        not isinstance(path, str) or not path.strip() for path in paths
    ):
        raise ValueError("sealed Claude paths must be non-empty strings")
    if type(agent) is not dict:
        raise ValueError("sealed Claude agent must be an exact dict")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("sealed Claude model must be non-empty")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or timeout_s <= 0:
        raise ValueError("sealed Claude timeout_s must be a positive integer")
    if (
        not isinstance(invocation_sha256, str)
        or len(invocation_sha256) != 64
        or any(char not in "0123456789abcdef" for char in invocation_sha256)
    ):
        raise ValueError("sealed Claude invocation_sha256 must be lowercase SHA-256")
    return payload


def invoke(payload: Any) -> dict[str, Any]:
    """Execute the exact payload through the private Claude subprocess adapter."""

    bound = _payload(payload)
    return _invoke_claude_cli(
        objective=bound["objective"],
        repo_root=bound["worktree"],
        paths=list(bound["paths"]),
        agent=dict(bound["agent"]),
        model=bound["model"],
        timeout_s=bound["timeout_s"],
    )


def output_digests(value: Any, payload: Any) -> tuple[str, ...]:
    """Content-address the exact invocation and structured Claude result."""

    bound = _payload(payload)
    if type(value) is not dict:
        raise ValueError("sealed Claude provider returned a non-object result")
    report = value.get("report")
    agent = value.get("agent")
    prompt_sha256 = value.get("prompt_sha256")
    report_sha256 = value.get("report_sha256")
    if type(report) is not dict or not isinstance(agent, str) or not agent:
        raise ValueError("sealed Claude provider returned malformed structured output")
    computed_report = canonical_sha(report)
    if report_sha256 != computed_report:
        raise ValueError("sealed Claude report digest does not match report bytes")
    for name, digest in (
        ("prompt_sha256", prompt_sha256),
        ("report_sha256", report_sha256),
    ):
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError(f"sealed Claude {name} is not lowercase SHA-256")
    return (
        canonical_sha(
            {
                "provider": "claude_cli",
                "agent": agent,
                "invocation_sha256": bound["invocation_sha256"],
                "prompt_sha256": prompt_sha256,
                "report_sha256": report_sha256,
                "report": report,
            }
        ),
    )


__all__ = ["invoke", "output_digests"]

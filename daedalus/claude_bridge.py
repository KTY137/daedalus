"""Structured Claude CLI adapter with a broker-only public execution path.

Prompt construction and output parsing are pure helpers. The only subprocess
implementation is private. The public ``ask_claude`` compatibility name now
accepts one exact immutable sealed invocation bundle and delegates to
:class:`ClaudeCLIProvider`; callers can no longer assemble a partial authority
set or select the legacy callback broker through this surface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .fallback import fallback_decision
from .router import route_task
from .schemas import REPORT_KEYS, validate_report
from .token_policy import MAX_SUMMARY_CHARS, STATIC_PROMPT_PREFIX, trim_paths

if TYPE_CHECKING:
    from .kernel.effects import EffectExecutionRequest
    from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
    from .providers.claude_cli import ClaudeWorkspaceGrant
    from .runtimes.provider_executable_object_registry import (
        ProviderExecutableObjectRegistry,
    )
    from .runtimes.provider_executable_pre_admission import (
        ProviderExecutablePreAdmissionReceipt,
    )
    from .runtimes.provider_invocation_abi import ProviderInvocationABIContract
    from .runtimes.provider_invocation_authority import (
        ProviderInvocationObservationAuthority,
    )
    from .runtimes.provider_invocation_payload import ProviderInvocationPayload
    from .runtimes.provider_observation import ProviderObservationBindingLedger


REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["done", "blocked", "needs_review", "failed"],
        },
        "summary": {"type": "string", "maxLength": MAX_SUMMARY_CHARS},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "todos": {"type": "array", "items": {"type": "string"}},
        "handoff": {"type": "object"},
    },
    "required": sorted(REPORT_KEYS),
    "additionalProperties": False,
}


_CMD_SHIM_SUFFIXES = (".cmd", ".bat")


@dataclass(frozen=True)
class ClaudeSealedInvocationBundle:
    """One indivisible capability-bearing input to the public Claude bridge.

    The individual records are still owned and authenticated by their existing
    kernel/runtime layers. This type grants nothing and verifies no signature;
    it only prevents the public caller seam from representing an impossible
    half-bundle. ``ClaudeCLIProvider`` and the sealed broker remain the authority
    boundary and re-verify every member before an effect can start.

    Exact-type checking in :func:`ask_claude` is intentional. A duck-typed
    object with property accessors is caller-controlled code; the bridge should
    refuse it before reading any security-critical member.
    """

    runtime_authorization: "RuntimeBoundEffectAuthorization"
    effect_execution: "EffectExecutionRequest"
    workspace_grant: "ClaudeWorkspaceGrant"
    invocation_authority: "ProviderInvocationObservationAuthority"
    invocation_payload: "ProviderInvocationPayload"
    invocation_abi: "ProviderInvocationABIContract"
    observation_binding_ledger: "ProviderObservationBindingLedger"
    executable_registry: "ProviderExecutableObjectRegistry"
    pre_admission: "ProviderExecutablePreAdmissionReceipt"

    def __post_init__(self) -> None:
        missing = [
            name
            for name in (
                "runtime_authorization",
                "effect_execution",
                "workspace_grant",
                "invocation_authority",
                "invocation_payload",
                "invocation_abi",
                "observation_binding_ledger",
                "executable_registry",
                "pre_admission",
            )
            if getattr(self, name) is None
        ]
        if missing:
            raise ValueError(
                "Claude sealed invocation bundle cannot contain empty members: "
                + ", ".join(missing)
            )


def _command_for_spawn(resolved: str | None, *, platform_name: str) -> str:
    """Return the executable that may receive argv without a shell relay.

    On Windows, ``subprocess.run(..., shell=False)`` still routes ``.cmd`` and
    ``.bat`` launchers through ``cmd.exe``. That command interpreter reparses
    every argv element, so a provider prompt or model value must never cross
    that boundary. Refuse the launch rather than pretending ``shell=False``
    makes a shell script behave like a native executable.
    """

    if platform_name != "nt":
        return "claude"
    if not resolved:
        raise RuntimeError("Claude executable could not be resolved before spawn")
    if resolved.casefold().endswith(_CMD_SHIM_SUFFIXES):
        raise RuntimeError(
            "Claude execution refused: Windows .cmd/.bat launchers reparse argv"
        )
    return resolved


def build_prompt(
    objective: str,
    repo_root: str,
    paths: list[str],
    agent: dict[str, Any],
) -> str:
    paths = trim_paths(paths)
    return f"""{STATIC_PROMPT_PREFIX}

You are acting as {agent["call_name"]} / {agent["name"]}.

Work as a stateless specialist. Do not ask another agent. Do not use full chat history.

Repository root:
{repo_root}

Objective:
{objective}

Relevant paths:
{json.dumps(paths, indent=2)}

Must read if needed:
{json.dumps(agent.get("must_read", []), indent=2)}

Constraints:
- Read only the files needed for this task.
- Prefer review/analysis unless the objective explicitly asks for edits.
- Do not run code that can touch real hardware.
- Keep summary under {MAX_SUMMARY_CHARS} characters.
- Return only the structured report required by the schema.
"""


def _extract_json(output: str) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        start = output.find("{")
        end = output.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(output[start : end + 1])

    if (
        isinstance(payload, dict)
        and "result" in payload
        and isinstance(payload["result"], str)
    ):
        return _extract_json(payload["result"])
    if not isinstance(payload, dict):
        raise ValueError("Claude output did not decode to a JSON object")
    return payload


def _blocked_report_from_wrapper(output: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not payload.get("is_error"):
        return None
    message = str(payload.get("result") or payload.get("error") or "Claude call failed")
    decision = fallback_decision("blocked")
    return {
        "status": "blocked",
        "summary": message[:600],
        "files_changed": [],
        "tests_run": [],
        "risks": ["Claude CLI returned an error before producing a specialist report."],
        "todos": [decision["todo"] or "Retry Claude bridge later."],
        "handoff": {
            "api_error_status": payload.get("api_error_status"),
            "session_id": payload.get("session_id"),
            "fallback": decision,
        },
    }


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _invoke_claude_cli(
    *,
    objective: str,
    repo_root: str,
    paths: list[str],
    agent: dict[str, Any],
    model: str = "sonnet",
    timeout_s: int = 300,
) -> dict[str, Any]:
    """Private subprocess implementation consumed only by the brokered provider.

    Prompt/report files are no longer written into the Daedalus checkout from
    this layer. Their exact canonical digests are returned and become broker
    output evidence; a later CAS packet may retain the bytes explicitly.
    """

    paths = trim_paths(paths)
    prompt = build_prompt(objective, repo_root, paths, agent)
    command = _command_for_spawn(shutil.which("claude"), platform_name=os.name)
    cmd = [
        command,
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(REPORT_SCHEMA, sort_keys=True, separators=(",", ":")),
        "--permission-mode",
        "dontAsk",
        "--add-dir",
        repo_root,
    ]
    completed = subprocess.run(
        cmd,
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        report = _blocked_report_from_wrapper(completed.stdout)
        if report is None:
            raise RuntimeError(
                "Claude failed with exit code "
                f"{completed.returncode}; stdout_sha256="
                f"{hashlib.sha256(completed.stdout.encode('utf-8', 'replace')).hexdigest()}; "
                "stderr_sha256="
                f"{hashlib.sha256(completed.stderr.encode('utf-8', 'replace')).hexdigest()}"
            )
    else:
        report = _extract_json(completed.stdout)
        errors = validate_report(report)
        if errors:
            raise ValueError("Invalid Claude report: " + "; ".join(errors))

    return {
        "agent": agent["name"],
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "report_sha256": _canonical_digest(report),
        "report": report,
    }


def ask_claude(
    objective: str,
    repo_root: str,
    paths: list[str],
    model: str = "sonnet",
    timeout_s: int = 300,
    *,
    sealed_bundle: ClaudeSealedInvocationBundle | None = None,
) -> dict[str, Any]:
    """Enter Claude through one exact sealed capability bundle.

    ``ask_claude`` deliberately does not mint authority. The production
    orchestration composition root must construct the bundle from canonical
    runtime/effect/invocation admission. Collapsing nine optional authority
    keywords into one exact object makes partial caller injection
    unrepresentable at this public seam while preserving the deeper provider
    and broker validation.
    """

    from .providers.claude_cli import (
        ClaudeCLIProvider,
        ClaudeProviderAuthorizationRequired,
    )

    if type(sealed_bundle) is not ClaudeSealedInvocationBundle:
        raise ClaudeProviderAuthorizationRequired(
            "ask_claude requires one exact ClaudeSealedInvocationBundle"
        )

    agent = route_task(objective, paths)
    return ClaudeCLIProvider().run(
        objective=objective,
        repo_root=repo_root,
        paths=paths,
        agent=agent,
        model=model,
        timeout_s=timeout_s,
        runtime_authorization=sealed_bundle.runtime_authorization,
        effect_execution=sealed_bundle.effect_execution,
        workspace_grant=sealed_bundle.workspace_grant,
        invocation_authority=sealed_bundle.invocation_authority,
        invocation_payload=sealed_bundle.invocation_payload,
        invocation_abi=sealed_bundle.invocation_abi,
        observation_binding_ledger=sealed_bundle.observation_binding_ledger,
        executable_registry=sealed_bundle.executable_registry,
        pre_admission=sealed_bundle.pre_admission,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude execution is available only through the runtime broker."
    )
    parser.add_argument("objective")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--timeout-s", type=int, default=300)
    parser.parse_args()
    parser.error(
        "direct CLI execution cannot carry the in-memory runtime capability; "
        "use the brokered provider/attempt path"
    )


if __name__ == "__main__":
    main()


__all__ = [
    "ClaudeSealedInvocationBundle",
    "REPORT_SCHEMA",
    "ask_claude",
    "build_prompt",
    "main",
]

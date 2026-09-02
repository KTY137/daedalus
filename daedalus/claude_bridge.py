"""Structured Claude CLI adapter with a broker-only public execution path.

Prompt construction and output parsing are pure helpers.  The only subprocess
implementation is private and is invoked by :class:`ClaudeCLIProvider` after
the runtime broker has persisted an exact grant and start receipt.  The legacy
``ask_claude`` name remains import-compatible, but now requires the same
runtime/effect authority and isolated-workspace grant instead of invoking from
ambient process authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from typing import TYPE_CHECKING, Any

from .orchestration.fallback import fallback_decision
from .limit_policy import ExecutionLimitPolicy, LimitPolicyError
from .router import route_task
from .runtimes.contracts.provider_report import REPORT_KEYS, validate_report
from .runtimes.providers.token_policy import (
    MAX_SUMMARY_CHARS,
    STATIC_PROMPT_PREFIX,
    trim_paths,
)

if TYPE_CHECKING:
    from .kernel.effects import EffectExecutionRequest
    from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
    from .runtimes.contracts.claude import ClaudeWorkspaceGrant
    from .runtimes.provider_observation import (
        ProviderObservationAuthority,
        ProviderObservationBindingLedger,
    )


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


def build_prompt(
    objective: str,
    repo_root: str,
    paths: list[str],
    agent: dict[str, Any],
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> str:
    if execution_limit_policy is None:
        limit_policy = ExecutionLimitPolicy()
    elif type(execution_limit_policy) is ExecutionLimitPolicy:
        limit_policy = execution_limit_policy
    else:
        raise LimitPolicyError(
            "execution_limit_policy must be an exact ExecutionLimitPolicy"
        )
    paths = trim_paths(paths, limit_policy=limit_policy)
    prefix = (
        STATIC_PROMPT_PREFIX
        if limit_policy.enforces("tokens")
        else "Daedalus Bridge Protocol v1."
    )
    detail_hint = (
        "\n- Put any unabridged detail in handoff; only the schema summary "
        "remains compact."
        if not limit_policy.enforces("tokens")
        else ""
    )
    return f"""{prefix}

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
- Keep summary under {MAX_SUMMARY_CHARS} characters.{detail_hint}
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


def _invoke_claude_payload(payload):
    """Fixed production adapter for one authenticated canonical payload.

    The function intentionally has no closure, defaults, or mutable module
    globals.  Imports and constants are local to the admitted code object, so
    rebinding a provider-module name after registration cannot redirect the
    operation retained by the executable-object registry.
    """

    import hashlib as local_hashlib
    import json as local_json
    import subprocess as local_subprocess

    objective = payload["objective"]
    repo_root = payload["worktree"]
    limit_material = payload.get("execution_limit_policy")
    limit_fingerprint = payload.get("execution_limit_policy_sha256")
    axis_names = (
        "period_usd",
        "billable_calls",
        "mission_spend",
        "tokens",
        "wall_time",
        "attempts",
        "concurrency",
        "work_scope",
    )
    if limit_material is None:
        if limit_fingerprint is not None:
            raise ValueError(
                "Claude payload cannot carry a limit-policy fingerprint without policy"
            )
        effective_axes = {axis: True for axis in axis_names}
    else:
        if type(limit_material) is not dict or set(limit_material) != {
            "mode",
            "configured",
        }:
            raise ValueError("Claude payload execution-limit policy has invalid shape")
        mode = limit_material["mode"]
        configured = limit_material["configured"]
        if mode not in ("bounded", "custom", "unbounded_execution"):
            raise ValueError("Claude payload execution-limit mode is invalid")
        if type(configured) is not dict or set(configured) != set(axis_names):
            raise ValueError("Claude payload execution-limit axes have invalid shape")
        if any(type(configured[axis]) is not bool for axis in axis_names):
            raise ValueError("Claude payload execution-limit axes must be booleans")
        encoded_policy = local_json.dumps(
            limit_material,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        expected_fingerprint = local_hashlib.sha256(encoded_policy).hexdigest()
        if limit_fingerprint != expected_fingerprint:
            raise ValueError("Claude payload execution-limit fingerprint mismatch")
        if mode == "bounded":
            effective_axes = {axis: True for axis in axis_names}
        elif mode == "unbounded_execution":
            effective_axes = {axis: False for axis in axis_names}
        else:
            effective_axes = dict(configured)

    paths = list(dict.fromkeys(payload["paths"]))
    if effective_axes["work_scope"]:
        paths = paths[:12]
    agent = payload["agent"]
    model = payload["model"]
    timeout_s = payload["timeout_s"]
    if effective_axes["wall_time"]:
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or timeout_s <= 0
        ):
            raise ValueError("bounded Claude payload requires a positive timeout")
    elif timeout_s is not None:
        raise ValueError("unbounded Claude wall time must be represented by null")
    token_prefix = "Daedalus Bridge Protocol v1."
    if effective_axes["tokens"]:
        token_prefix += """

Minimize tokens:
- Use the supplied paths instead of exploring the whole repo.
- Read only files needed for this task.
- Return compact structured JSON only.
- No conversational intro, praise, or markdown.
- No full code dumps unless explicitly requested.
- Prefer file:line references and short summaries.
- Do not include chain-of-thought; include only conclusions and evidence."""
    detail_hint = (
        "\n- Put any unabridged detail in handoff; only the schema summary "
        "remains compact."
        if not effective_axes["tokens"]
        else ""
    )
    prompt = f"""{token_prefix}

You are acting as {agent["call_name"]} / {agent["name"]}.

Work as a stateless specialist. Do not ask another agent. Do not use full chat history.

Repository root:
{repo_root}

Objective:
{objective}

Relevant paths:
{local_json.dumps(paths, indent=2)}

Must read if needed:
{local_json.dumps(agent.get("must_read", []), indent=2)}

Constraints:
- Read only the files needed for this task.
- Prefer review/analysis unless the objective explicitly asks for edits.
- Do not run code that can touch real hardware.
- Keep summary under 600 characters.{detail_hint}
- Return only the structured report required by the schema.
"""
    report_schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["done", "blocked", "needs_review", "failed"],
            },
            "summary": {"type": "string", "maxLength": 600},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "tests_run": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "todos": {"type": "array", "items": {"type": "string"}},
            "handoff": {"type": "object"},
        },
        "required": [
            "files_changed", "handoff", "risks", "status", "summary",
            "tests_run", "todos",
        ],
        "additionalProperties": False,
    }
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--json-schema",
        local_json.dumps(report_schema, sort_keys=True, separators=(",", ":")),
        "--permission-mode",
        "dontAsk",
        "--add-dir",
        repo_root,
    ]
    completed = local_subprocess.run(
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
        try:
            wrapper = local_json.loads(completed.stdout)
        except local_json.JSONDecodeError:
            wrapper = None
        if not isinstance(wrapper, dict) or not wrapper.get("is_error"):
            raise RuntimeError(
                "Claude failed with exit code "
                f"{completed.returncode}; stdout_sha256="
                f"{local_hashlib.sha256(completed.stdout.encode('utf-8', 'replace')).hexdigest()}; "
                "stderr_sha256="
                f"{local_hashlib.sha256(completed.stderr.encode('utf-8', 'replace')).hexdigest()}"
            )
        message = str(
            wrapper.get("result") or wrapper.get("error") or "Claude call failed"
        )
        report = {
            "status": "blocked",
            "summary": message[:600],
            "files_changed": [],
            "tests_run": [],
            "risks": [
                "Claude CLI returned an error before producing a specialist report."
            ],
            "todos": ["Retry Claude second opinion later if useful."],
            "handoff": {
                "api_error_status": wrapper.get("api_error_status"),
                "session_id": wrapper.get("session_id"),
                "fallback": {
                    "mode": "codex_solo",
                    "continue": True,
                    "reason": (
                        "Claude unavailable; work may continue with local tests "
                        "and memory logging."
                    ),
                    "todo": "Retry Claude second opinion later if useful.",
                },
            },
        }
        if not effective_axes["tokens"] and len(message) > 600:
            report["handoff"]["unabridged_summary"] = message
    else:
        decoded = local_json.loads(completed.stdout)
        while isinstance(decoded, dict) and isinstance(decoded.get("result"), str):
            decoded = local_json.loads(decoded["result"])
        if not isinstance(decoded, dict):
            raise ValueError("Claude output did not decode to a JSON object")
        report = decoded
        raw_summary = report.get("summary")
        if (
            not effective_axes["tokens"]
            and isinstance(raw_summary, str)
            and len(raw_summary) > 600
            and isinstance(report.get("handoff"), dict)
        ):
            report = dict(report)
            report["handoff"] = {
                **report["handoff"],
                "unabridged_summary": raw_summary,
            }
            report["summary"] = raw_summary[:600]
        required = (
            "status", "summary", "files_changed", "tests_run", "risks",
            "todos", "handoff",
        )
        errors = []
        missing = [key for key in required if key not in report]
        extra = [key for key in report if key not in required]
        if missing:
            errors.append("missing keys: " + ", ".join(sorted(missing)))
        if extra:
            errors.append("extra keys: " + ", ".join(sorted(extra)))
        if report.get("status") not in ("done", "blocked", "needs_review", "failed"):
            errors.append("status must be one of: done, blocked, needs_review, failed")
        summary = report.get("summary")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 600:
            errors.append(
                "summary must be a non-empty string no longer than 600 characters"
            )
        for key in ("files_changed", "tests_run", "risks", "todos"):
            if key in report and not isinstance(report[key], list):
                errors.append(f"{key} must be a list")
        if "handoff" in report and not isinstance(report["handoff"], dict):
            errors.append("handoff must be an object")
        if errors:
            raise ValueError("Invalid Claude report: " + "; ".join(errors))

    report_bytes = local_json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return {
        "agent": agent["name"],
        "prompt_sha256": local_hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "report_sha256": local_hashlib.sha256(report_bytes).hexdigest(),
        "report": report,
    }


def ask_claude(
    objective: str,
    repo_root: str,
    paths: list[str],
    model: str = "sonnet",
    timeout_s: int | float | None = 300,
    *,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
    runtime_authorization: "RuntimeBoundEffectAuthorization | None" = None,
    effect_execution: "EffectExecutionRequest | None" = None,
    workspace_grant: "ClaudeWorkspaceGrant | None" = None,
    invocation_authority: "ProviderInvocationObservationAuthority | None" = None,
    invocation_payload: "ProviderInvocationPayload | None" = None,
    invocation_abi: "ProviderInvocationABIContract | None" = None,
    observation_binding_ledger: "ProviderObservationBindingLedger | None" = None,
    executable_registry: "ProviderExecutableObjectRegistry | None" = None,
    pre_admission: "ProviderExecutablePreAdmissionReceipt | None" = None,
) -> dict[str, Any]:
    """Compatibility adapter that now delegates to the brokered provider.

    Existing callers keep the import path, but a call without explicit
    persisted authority fails before subprocess creation.  The caller must
    supply an attempt-owned worktree; direct Primary Checkout execution is not
    a compatibility feature.
    """

    from .providers.claude_cli import (
        ClaudeCLIProvider,
        ClaudeProviderAuthorizationRequired,
    )

    if runtime_authorization is None or effect_execution is None or workspace_grant is None:
        raise ClaudeProviderAuthorizationRequired(
            "ask_claude requires runtime authorization, effect execution, and workspace grant"
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
            "ask_claude requires the authenticated invocation ABI, payload, "
            "executable registry, pre-admission, and binding ledger"
        )
    agent = route_task(objective, paths)
    return ClaudeCLIProvider().run(
        objective=objective,
        repo_root=repo_root,
        paths=paths,
        agent=agent,
        model=model,
        timeout_s=timeout_s,
        execution_limit_policy=execution_limit_policy,
        runtime_authorization=runtime_authorization,
        effect_execution=effect_execution,
        workspace_grant=workspace_grant,
        invocation_authority=invocation_authority,
        invocation_payload=invocation_payload,
        invocation_abi=invocation_abi,
        observation_binding_ledger=observation_binding_ledger,
        executable_registry=executable_registry,
        pre_admission=pre_admission,
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
    # The module entrypoint intentionally performs no external effect.  It is
    # retained only as a fail-closed compatibility surface.
    main()


__all__ = [
    "REPORT_SCHEMA",
    "ask_claude",
    "build_prompt",
    "main",
]

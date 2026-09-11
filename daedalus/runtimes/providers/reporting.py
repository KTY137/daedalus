"""Canonical provider prompt, parse, coercion, and blocked-report helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from daedalus.kernel.policy.limits import ExecutionLimitPolicy
from daedalus.runtimes.contracts.provider_report import REPORT_KEYS, validate_report

from .execution_policy import bounded_execution_limit_policy
from .token_policy import MAX_SUMMARY_CHARS, STATIC_PROMPT_PREFIX


def report_instructions() -> str:
    # DeepSeek json_object mode requires the literal word "json" AND an example
    # of the desired shape in the prompt; both are present here.
    return (
        "Return ONLY a json object with exactly these keys: "
        "status (done|blocked|needs_review|failed), summary (<="
        f"{MAX_SUMMARY_CHARS} chars), files_changed (array), tests_run (array), "
        "risks (array), todos (array), handoff (object). "
        "You are READ-ONLY: you cannot edit files or run tests, so files_changed "
        "and tests_run must be []. Put any proposed edit as text inside handoff.\n"
        "Example: {\"status\": \"needs_review\", \"summary\": \"...\", "
        "\"files_changed\": [], \"tests_run\": [], \"risks\": [], \"todos\": [], "
        "\"handoff\": {\"suggestion\": \"...\"}}"
    )


def build_prompt(
    agent: dict[str, Any],
    objective: str,
    context_text: str,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> tuple[str, str]:
    """Return (system, user) messages for a read-only, non-agentic provider."""
    resolved = bounded_execution_limit_policy(execution_limit_policy)
    prefix = (
        STATIC_PROMPT_PREFIX
        if resolved.enforces("tokens")
        else "Daedalus Bridge Protocol v1.\n"
    )
    system = (
        f"{prefix}\n"
        f"You are acting as {agent.get('call_name', '?')} / {agent.get('name', '?')}, "
        "a stateless specialist. Do not ask another agent. Use only the supplied "
        "context. Do not invent instrument commands.\n"
        f"{report_instructions()}"
    )
    user = (
        f"Objective:\n{objective}\n\n"
        f"Context (read-only excerpts):\n{context_text or '(no files supplied)'}\n"
    )
    return system, user


# JSON permits exactly `" \ / b f n r t u` after a backslash inside a string.
# A model quoting this repository's own code writes `\d`, `\.`, `\x1b` or
# `C:\Program Files` inside a JSON string, the strict parser refuses the WHOLE
# answer, and the evidence dies as a blocked report.  Doubling the lone
# backslash is lossless: the repaired escape decodes back to exactly the
# literal backslash the model wrote.  The lookbehind keeps hands off a
# backslash that is itself escaped.
_INVALID_ESCAPE_RE = re.compile(r'(?<!\\)\\(?!["\\/bfnrtu])')


def _loads_or_repair(text: str, repairs: list[str] | None) -> Any:
    """``json.loads`` with one lossless rescue for invalid string escapes."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as original:
        repaired, n = _INVALID_ESCAPE_RE.subn(r"\\\\", text)
        if not n:
            raise
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError:
            raise original from None
        if repairs is not None:
            repairs.append(f"doubled {n} invalid JSON string escape(s)")
        return payload


def extract_json(text: str, *, repairs: list[str] | None = None) -> dict[str, Any]:
    """Parse a model answer into a dict, retaining the existing two rescues."""
    try:
        payload = _loads_or_repair(text, repairs)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        payload = _loads_or_repair(text[start : end + 1], repairs)
    if not isinstance(payload, dict):
        raise ValueError("model output did not decode to a JSON object")
    return payload


def coerce_report(
    payload: dict[str, Any],
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> dict[str, Any]:
    """Fill missing report keys safely, preserve unexpected evidence, validate."""
    resolved = bounded_execution_limit_policy(execution_limit_policy)
    handoff = payload.get("handoff") or {}
    raw_summary = str(payload.get("summary", ""))
    summary = raw_summary[:MAX_SUMMARY_CHARS]
    if isinstance(handoff, dict):
        if (
            not resolved.enforces("tokens")
            and len(raw_summary) > MAX_SUMMARY_CHARS
            and "unabridged_summary" not in handoff
        ):
            handoff = {**handoff, "unabridged_summary": raw_summary}
        unexpected = {k: v for k, v in payload.items() if k not in REPORT_KEYS}
        if unexpected:
            handoff = {**handoff, "unexpected_keys": unexpected}
        if "status" not in payload:
            handoff = {**handoff, "status_was_defaulted": True}
        if not summary.strip() and (unexpected or payload.get("handoff")):
            summary = "(model supplied no summary; its answer is preserved in handoff)"
            handoff = {**handoff, "summary_was_defaulted": True}

    report = {
        "status": payload.get("status", "needs_review"),
        "summary": summary,
        "files_changed": payload.get("files_changed") or [],
        "tests_run": payload.get("tests_run") or [],
        "risks": payload.get("risks") or [],
        "todos": payload.get("todos") or [],
        "handoff": handoff,
    }
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid model report: " + "; ".join(errors))
    return report


def blocked_report(summary: str, todo: str, **handoff: Any) -> dict[str, Any]:
    return {
        "status": "blocked",
        "summary": summary[:MAX_SUMMARY_CHARS],
        "files_changed": [],
        "tests_run": [],
        "risks": [],
        "todos": [todo],
        "handoff": handoff,
    }


__all__ = [
    "blocked_report",
    "build_prompt",
    "coerce_report",
    "extract_json",
    "report_instructions",
]

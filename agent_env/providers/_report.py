"""Shared helpers for turning a raw model response into a validated report and
for building the prompt sent to non-agentic providers."""

from __future__ import annotations

import json
from typing import Any

from ..schemas import validate_report
from ..token_policy import MAX_SUMMARY_CHARS, STATIC_PROMPT_PREFIX

# Total inlined-context budget for non-agentic providers (chars). Keeps prompts
# small per the token-efficiency rules; sensitive files are excluded upstream.
MAX_CONTEXT_CHARS = 24_000


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


def build_prompt(agent: dict[str, Any], objective: str, context_text: str) -> tuple[str, str]:
    """Return (system, user) messages for a read-only, non-agentic provider."""
    system = (
        f"{STATIC_PROMPT_PREFIX}\n"
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


def extract_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model output did not decode to a JSON object")
    return payload


def coerce_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Fill any missing report keys with safe defaults, then validate."""
    report = {
        "status": payload.get("status", "needs_review"),
        "summary": str(payload.get("summary", ""))[:MAX_SUMMARY_CHARS],
        "files_changed": payload.get("files_changed") or [],
        "tests_run": payload.get("tests_run") or [],
        "risks": payload.get("risks") or [],
        "todos": payload.get("todos") or [],
        "handoff": payload.get("handoff") or {},
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

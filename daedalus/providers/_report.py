"""Shared helpers for turning a raw model response into a validated report and
for building the prompt sent to non-agentic providers."""

from __future__ import annotations

import json
from typing import Any

from ..budget import BudgetError, BudgetRefused, Reservation, reserve
from ..schemas import REPORT_KEYS, validate_report
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
    """Fill any missing report keys with safe defaults, then validate.

    TWO THINGS THIS USED TO DO SILENTLY, both of which destroyed evidence:

    1. **Unexpected keys were discarded.** This function rebuilds the report
       from a fixed key set, so a model that answered under any other key --
       ``findings``, ``claims``, ``analysis`` -- had that content DESTROYED
       rather than rejected, and what came back was a schema-valid report with
       the evidence removed. It then read downstream as a clean empty answer.
       That is how roughly 250 answers were lost in the 2026-07-30 fan-out.

       They cannot stay at top level: ``schemas.validate_report`` rejects any
       key outside ``REPORT_KEYS``, and that strictness is load-bearing --
       ``claude_bridge`` and ``codex_cli`` both publish ``sorted(REPORT_KEYS)``
       as a JSON-schema ``required`` list. So they are preserved inside
       ``handoff``, which is free-form, already in the schema, and already the
       side channel for exactly this. Nothing is truncated on the way in: a cap
       here would recreate the defect it is meant to close.

    2. **``status`` was defaulted with no record that it had been.** A model
       that never mentioned status got ``needs_review``, indistinguishable from
       one that chose it. Measured: constant across 715 answers, carrying zero
       bits, while every consumer read it as a verdict. The value is unchanged
       -- changing it would break callers -- but the fact that nobody supplied
       it is now recorded, so "the model did not say" can be told apart from
       "the model said needs_review".

    Both records ride in ``handoff`` and neither can collide with a real report
    key. A non-dict ``handoff`` is left exactly as it was, so it still fails
    validation below rather than being quietly repaired here.
    """
    handoff = payload.get("handoff") or {}
    if isinstance(handoff, dict):
        unexpected = {k: v for k, v in payload.items() if k not in REPORT_KEYS}
        if unexpected:
            handoff = {**handoff, "unexpected_keys": unexpected}
        if "status" not in payload:
            handoff = {**handoff, "status_was_defaulted": True}

    report = {
        "status": payload.get("status", "needs_review"),
        "summary": str(payload.get("summary", ""))[:MAX_SUMMARY_CHARS],
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


# ---------------------------------------------------------------------------
# spend ceiling -- the providers' side of daedalus.budget
# ---------------------------------------------------------------------------
#
# A billable provider must reserve BEFORE it calls out, and must turn a refusal
# into a valid ``agent_report_v1`` rather than an exception, so a capped run
# still produces a report the harness can read instead of a stack trace the
# watcher swallows. The two helpers below are the whole integration surface;
# see ``daedalus/budget.py`` for why enforcement cannot live in one place.


def budget_refusal_report(exc: BudgetError) -> dict[str, Any]:
    """The blocked report for a refused call. NAMES the numbers.

    A refusal the operator cannot read is a refusal the operator switches off,
    so the ceiling, the spend and the refused label all survive into the report
    body and into ``handoff`` in machine-readable form.
    """
    detail = exc.as_dict() if isinstance(exc, BudgetRefused) else {"reason": str(exc)}
    return blocked_report(
        f"Refused by the spend ceiling: {exc}",
        "Raise DAEDALUS_BUDGET_USD deliberately, wait for the budget period to "
        "roll over, or route this task to a local lane.",
        budget=detail,
    )


def reserve_or_report(
    *,
    vendor: str,
    model: str | None,
    label: str,
    provider: str,
    persona: str,
    agent: str | None,
    calls: int = 1,
    host: str | None = None,
) -> tuple[Reservation | None, dict[str, Any] | None]:
    """``(reservation, None)`` when the call may proceed, ``(None, envelope)``
    when it may not.

    FAIL CLOSED: every :class:`~daedalus.budget.BudgetError` -- refused ceiling,
    unreadable ledger, unobtainable lock, unpriceable vendor -- lands in the
    second branch. There is no path through this function that returns
    ``(None, None)`` and lets the caller carry on.
    """
    try:
        res = reserve(vendor, model, label=label, calls=calls, host=host)
    except BudgetError as exc:
        return None, {
            "provider": provider,
            "persona": persona,
            "agent": agent,
            "report": budget_refusal_report(exc),
        }
    return res, None

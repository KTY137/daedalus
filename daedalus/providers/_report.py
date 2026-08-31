"""Shared helpers for turning a raw model response into a validated report and
for building the prompt sent to non-agentic providers."""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..budget import BudgetError, BudgetRefused, Reservation, reserve
from ..lanes import graph_brief, render_brief
from ..limit_policy import ExecutionLimitPolicy, LimitPolicyError, load_from_env
from ..runtimes.contracts.provider_report import REPORT_KEYS, validate_report
from ..token_policy import MAX_SUMMARY_CHARS, STATIC_PROMPT_PREFIX

# Total inlined-context budget for non-agentic providers (chars). Keeps prompts
# small per the token-efficiency rules; sensitive files are excluded upstream.
MAX_CONTEXT_CHARS = 24_000


def bounded_execution_limit_policy(
    policy: ExecutionLimitPolicy | None,
) -> ExecutionLimitPolicy:
    """Return an explicit policy for internal helpers without reading env.

    Environment fallback belongs only at a provider's direct ``run`` admission.
    Internal helpers default to the legacy bounded behaviour so calling one in a
    test or from another already-admitted path cannot recapture mutable process
    configuration halfway through a request.
    """

    if policy is None:
        return ExecutionLimitPolicy()
    if not isinstance(policy, ExecutionLimitPolicy):
        raise LimitPolicyError(
            "execution_limit_policy must be an ExecutionLimitPolicy"
        )
    return policy


def admit_execution_limit_policy(
    policy: ExecutionLimitPolicy | None,
) -> ExecutionLimitPolicy:
    """Capture the policy once at a provider's direct admission boundary."""

    return load_from_env() if policy is None else bounded_execution_limit_policy(policy)


def attempt_numbers(
    policy: ExecutionLimitPolicy | None,
    bounded_attempts: int,
) -> Iterator[int]:
    """Yield bounded attempt numbers, or an open iterator when attempts are off.

    There is deliberately no large-number stand-in for unlimited execution.
    A finite fake (or a real provider that eventually succeeds) terminates the
    open iterator through the caller's ordinary ``break``/``return`` path.
    """

    resolved = bounded_execution_limit_policy(policy)
    if bounded_attempts <= 0:
        raise ValueError("bounded_attempts must be positive")
    if resolved.enforces("attempts"):
        return iter(range(bounded_attempts))
    return itertools.count()


def provider_http_timeout(
    policy: ExecutionLimitPolicy | None,
    timeout_s: float | None,
    *,
    bounded_default: float = 300.0,
) -> float | None:
    """Return a real deadline or ``None``; never encode unlimited as a number."""

    resolved = bounded_execution_limit_policy(policy)
    if not resolved.enforces("wall_time"):
        return None
    return bounded_default if timeout_s is None else float(timeout_s)


def read_provider_context(
    paths: list[str],
    repo_root: str,
    *,
    max_chars: int,
    allow_sensitive: bool,
    sensitivity_policy: Any | None,
    execution_limit_policy: ExecutionLimitPolicy | None,
) -> tuple[str, list[str]]:
    """Read provider context while retaining the canonical sensitivity gate.

    With token limits disabled, the capacity passed to
    :func:`read_inlined_context` is derived from the complete readable inputs;
    it is not an arbitrary numeric substitute for infinity.  The canonical
    secret/egress checks still decide which of those inputs may be returned.
    """

    from ..sensitivity import read_inlined_context

    resolved = bounded_execution_limit_policy(execution_limit_policy)
    capacity = max_chars
    if not resolved.enforces("tokens"):
        root = Path(repo_root)
        capacity = 1
        for raw in paths:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                data = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            capacity += len(f"\n===== FILE: {raw} =====\n") + len(data)
    return read_inlined_context(
        paths,
        repo_root,
        capacity,
        allow_sensitive=allow_sensitive,
        policy=sensitivity_policy,
    )


def render_provider_brief(
    repo_root: str,
    paths: list[str],
    *,
    bounded_chars: int,
    execution_limit_policy: ExecutionLimitPolicy | None,
) -> str:
    """Render the normal bounded brief or the complete graph brief.

    The unlimited branch grows an explicit working capacity until the graph
    builder reports that it omitted nothing.  It therefore has a terminating
    completeness condition rather than a fake numerical "unlimited" value.
    """

    resolved = bounded_execution_limit_policy(execution_limit_policy)
    if resolved.enforces("tokens"):
        return render_brief(
            repo_root, paths, hops=1, budget_chars=bounded_chars
        )
    capacity = max(1, bounded_chars)
    try:
        while True:
            result = graph_brief(
                repo_root, paths, hops=1, budget_chars=capacity
            )
            if not result.truncated:
                return result.text
            capacity *= 2
    except Exception:  # noqa: BLE001 -- optional context, never an admission gate
        return ""


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
# answer, and the evidence dies as a blocked report.  Measured 2026-07-31 on
# the claims123 funnel at 51fe781: 5 of 100 scan units, 8 of 15 research units
# and 6 of 6 review units -- the tiers whose whole job was quoting
# backslash-bearing source -- blocked with "Invalid \escape".  Doubling the
# lone backslash is lossless: the repaired escape decodes back to exactly the
# literal backslash the model wrote.  The lookbehind keeps hands off a
# backslash that is itself escaped, because "repairing" the second half of a
# valid `\\` pair would corrupt it; the cost is that a mixed run like `\\\d`
# stays broken and still raises, which is the honest outcome -- rescuing it
# needs intent this layer does not have.  (`\n` et al. remain valid escapes,
# so a model writing `C:\Users\nukei` still yields a newline where it meant a
# backslash-n; that ambiguity is the model's, not decidable here.)
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
            # The rescue did not take; the defect worth reporting is the one
            # in the text the model actually produced.
            raise original from None
        if repairs is not None:
            repairs.append(f"doubled {n} invalid JSON string escape(s)")
        return payload


def extract_json(text: str, *, repairs: list[str] | None = None) -> dict[str, Any]:
    """Parse a model answer into a dict, tolerating two model habits.

    Two rescues: prose around the JSON object is sliced off (the
    ``find``/``rfind`` fallback, which predates this docstring), and a lone
    backslash that JSON forbids is doubled (``_INVALID_ESCAPE_RE`` above).
    Pass ``repairs`` to learn that the second rescue fired; a caller that
    records answers as evidence should note it in ``handoff`` so a repaired
    answer can be told apart from one that parsed clean.
    """
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
    """Fill any missing report keys with safe defaults, then validate.

    THREE THINGS THIS USED TO DO SILENTLY, each of which destroyed evidence:

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

    3. **A missing summary refused the whole report.** ``validate_report``
       requires a non-empty summary, so an answer that arrived as nothing but
       ``{"claims": [...]}`` had its keys carefully preserved into ``handoff``
       -- and was then refused whole for the formality it forgot, destroying
       the evidence a second time. Found by the first in-suite regression test
       this contract ever had (2026-07-31), not by a production incident. The
       summary is synthesized ONLY when there is preserved model content to
       protect; an empty answer gains nothing here and still fails validation,
       so the caller's deterministic re-ask keeps its second chance.

    All records ride in ``handoff`` and none can collide with a real report
    key. A non-dict ``handoff`` is left exactly as it was, so it still fails
    validation below rather than being quietly repaired here.
    """
    resolved = bounded_execution_limit_policy(execution_limit_policy)
    handoff = payload.get("handoff") or {}
    raw_summary = str(payload.get("summary", ""))
    summary = raw_summary[:MAX_SUMMARY_CHARS]
    if isinstance(handoff, dict):
        # ``agent_report_v1`` always requires a <=600-char summary.  That schema
        # boundary is not a resource cap and remains non-disableable.  When the
        # token axis is off, retain the complete model output in the free-form
        # handoff rather than silently destroying it while shaping the schema.
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

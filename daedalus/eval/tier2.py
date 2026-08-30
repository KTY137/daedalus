"""Fail-closed Tier-2 live-model evaluation.

Tier 2 is the only eval lane that grades generated text.  It therefore keeps
provider execution, lexical coverage, semantic validation, and audit evidence
separate instead of treating "expected token appeared" as task success.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Pattern

from . import harness as _legacy
from .report import _table
from .tasks import TASKS, task_project_label

_MAX_AUDIT_CHARS = 16_384
_MAX_ERROR_CHARS = 512

_NEGATION = re.compile(
    r"\b(?:not|never|no|without|cannot|can't|can['’]t|"
    r"doesn't|doesn['’]t|does\s+not|didn't|didn['’]t|did\s+not|"
    r"isn't|isn['’]t|is\s+not|aren't|aren['’]t|are\s+not|"
    r"wasn't|wasn['’]t|was\s+not|weren't|weren['’]t|were\s+not|"
    r"won't|won['’]t|will\s+not|don't|don['’]t|do\s+not)\b",
    re.IGNORECASE,
)
_HEDGE = re.compile(
    r"\b(?:maybe|perhaps|possibly|probably|might|could|guess|unsure|"
    r"uncertain|unclear|unknown)\b",
    re.IGNORECASE,
)
_UNCERTAINTY = re.compile(
    r"\b(?:i\s+(?:cannot|can't|can['’]t)\s+tell|"
    r"i\s+(?:do\s+not|don't|don['’]t)\s+know|"
    r"not\s+enough\s+information|cannot\s+determine|can't\s+determine)\b",
    re.IGNORECASE,
)
_POST_NEGATION = re.compile(
    r"^\W*(?:is|was|are|were|does|did|can|will)?\W*"
    r"(?:not|never|isn't|isn['’]t|wasn't|wasn['’]t|aren't|aren['’]t|"
    r"doesn't|doesn['’]t|cannot|can't|can['’]t)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ValidatorSpec:
    required: tuple[Pattern[str], ...]
    forbidden: tuple[Pattern[str], ...] = ()


def _rx(pattern: str) -> Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Semantic task success is explicit and question-specific. Unknown/minted
# questions are reported as unvalidated rather than silently receiving the
# old substring oracle.
_BUILTIN_VALIDATORS: dict[str, _ValidatorSpec] = {
    "web_api_file": _ValidatorSpec((
        _rx(r"(?:^\s*cached_index\s*\(?\)?\s*$|"
            r"\b(?:call|calls|use|uses|invoke|invokes)\b[^.!?\n]{0,96}\bcached_index\b)"),
    )),
    "garden_care_file": _ValidatorSpec((_rx(r"\bwater_every_days\b"),)),
    "garden_cli_file": _ValidatorSpec(
        (_rx(r"\bwater\b"),),
        (_rx(r"\b(?:do\s+not|don't|don['’]t|never)\s+water\b"),),
    ),
    "garden_plants_file": _ValidatorSpec(
        (_rx(r"\b14\s+days?\b"),),
        (_rx(r"\b(?:not|isn't|isn['’]t|is\s+not)\b[^.!?\n]{0,24}\b14\s+days?\b"),),
    ),
    "slice_semantic_slice": _ValidatorSpec((_rx(r"\btotal_tokens\b"),)),
    "index_build_index": _ValidatorSpec((_rx(r"\bunit_clusters\b"),)),
    "report_structure_summary": _ValidatorSpec((
        _rx(r"\bunit_clusters\b"),
        _rx(r"\brenamed_clusters\b"),
        _rx(r"\bnear_clusters\b"),
        _rx(r"\bwindow_clusters\b"),
        _rx(r"\bsafety_fenced\b"),
    )),
    "ikarus_distill": _ValidatorSpec((
        _rx(r"(?:^\s*semantic_slice\s*\(?\)?\s*$|"
            r"\b(?:call|calls|use|uses|invoke|invokes)\b[^.!?\n]{0,96}\bsemantic_slice\b)"),
    )),
    "projects_resolve_repo_root": _ValidatorSpec((
        _rx(r"\bload_project\b"), _rx(r"\brepo_root\b"),
    )),
    "garden_watering_plan": _ValidatorSpec((_rx(r"\bneeds_water\b"),)),
}


def _safe_ascii(value: object) -> str:
    return str(value).encode("ascii", "replace").decode("ascii")


def _clean_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    text = "".join(ch if (ch == "\t" or ord(ch) >= 32) else "?" for ch in text)
    return text if len(text) <= _MAX_ERROR_CHARS else text[: _MAX_ERROR_CHARS - 3] + "..."


def _bounded_answer(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_AUDIT_CHARS:
        return text, False
    marker = "\n...[middle truncated for audit bound]...\n"
    keep = _MAX_AUDIT_CHARS - len(marker)
    head = keep // 2
    return text[:head] + marker + text[-(keep - head):], True


def _near(prefix: str, pattern: Pattern[str], words: int = 5) -> bool:
    tokens = list(re.finditer(r"\b[\w'’]+\b", prefix))
    if not tokens:
        return False
    return bool(pattern.search(prefix[tokens[max(0, len(tokens) - words)].start():]))


def _expected_asserted(answer: str, expected: str) -> bool:
    """Reject direct negation/hedging around an expected lexical label."""
    low = answer.lower()
    for match in re.finditer(re.escape(expected.lower()), low):
        left = max(
            low.rfind(".", 0, match.start()), low.rfind(";", 0, match.start()),
            low.rfind(",", 0, match.start()), low.rfind("\n", 0, match.start()),
        )
        rights = [
            p for p in (
                low.find(".", match.end()), low.find(";", match.end()),
                low.find(",", match.end()), low.find("\n", match.end()),
            ) if p != -1
        ]
        right = min(rights) if rights else len(low)
        clause = low[left + 1:right]
        rel_start = match.start() - left - 1
        rel_end = match.end() - left - 1
        if _near(clause[:rel_start], _NEGATION) or _near(clause[:rel_start], _HEDGE):
            continue
        if _POST_NEGATION.search(" ".join(clause[rel_end:].split()[:5])):
            continue
        if _UNCERTAINTY.search(clause):
            continue
        return True
    return False


def _score(answer: str, answer_contains: list[str]) -> tuple[bool, float]:
    """Return guarded lexical success plus the old coverage fraction.

    The fraction remains observable for continuity. It is never the Tier-2
    semantic-success oracle.
    """
    if not answer or not answer_contains:
        return False, 0.0
    low = answer.lower()
    present = sum(1 for item in answer_contains if item.lower() in low)
    frac = present / len(answer_contains)
    asserted = all(_expected_asserted(answer, item) for item in answer_contains)
    return present == len(answer_contains) and asserted, frac


def _validate_task_answer(task: dict, answer: str) -> dict:
    guarded, lexical = _score(answer, task.get("answer_contains", []))
    spec = _BUILTIN_VALIDATORS.get(task.get("id", ""))
    if spec is None:
        return {
            "validated": False, "semantic_success": False,
            "guarded_lexical_success": guarded, "lexical_fraction": lexical,
            "validator": None,
        }
    semantic = (
        guarded
        and all(pattern.search(answer) for pattern in spec.required)
        and not any(pattern.search(answer) for pattern in spec.forbidden)
    )
    return {
        "validated": True, "semantic_success": bool(semantic),
        "guarded_lexical_success": guarded, "lexical_fraction": lexical,
        "validator": f"builtin:{task['id']}/1",
    }


def _ask(prov: dict, question: str, context: str) -> dict:
    """Make one provider call and return a bounded, auditable receipt."""
    system = (
        "You answer strictly from the provided CONTEXT. If the answer is not in "
        "the context, say you cannot tell. Be brief and concrete."
    )
    user = f"CONTEXT:\n{context}\n\nQUESTION: {question}"
    try:
        from daedalus.providers._openai_compat import chat_completion

        text = chat_completion(
            base_url=prov["host"] + "/v1", model=prov["model"],
            system=system, user=user, force_json=False, temperature=0.0,
            timeout_s=120,
        )
    except Exception as exc:
        return {
            "ok": False, "text": None, "text_chars": 0, "text_sha256": None,
            "text_truncated": False, "error_type": type(exc).__name__,
            "error": _clean_error(exc),
        }

    raw = (text or "").strip()
    if not raw:
        return {
            "ok": False, "text": None, "text_chars": 0, "text_sha256": None,
            "text_truncated": False, "error_type": "EmptyProviderResponse",
            "error": "provider returned no answer text",
        }
    preview, truncated = _bounded_answer(raw)
    return {
        "ok": True, "text": preview, "text_chars": len(raw),
        "text_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "text_truncated": truncated, "error_type": None, "error": None,
    }


def run_tier2(
    tasks: list[dict] | None = None,
    provider: str | None = None,
    cap_tokens: int = 120_000,
) -> dict:
    """Run A/B only when provider evidence and semantic validators are valid."""
    tasks = _legacy.all_tasks() if tasks is None else tasks
    prov = _legacy.detect_provider(provider)
    if prov is None:
        return {
            "tier": 2, "skipped": True,
            "reason": "no provider/runtime available (set OLLAMA_HOST to a "
                      "running Ollama, or start one) -- Tier 1 is the deliverable.",
        }

    cap_chars = cap_tokens * 4
    idx_cache: dict[str, dict] = {}
    whole_cache: dict[str, tuple[str, bool]] = {}
    whole_true_tokens: dict[str, int] = {}
    per_task: list[dict] = []
    errored: list[dict] = []

    for task in tasks:
        if not task.get("question"):
            continue
        try:
            repo = _legacy.resolve_task_repo(task["repo"])
            if repo not in idx_cache:
                idx_cache[repo] = _legacy.cached_index(repo)
            if repo not in whole_cache:
                whole_cache[repo] = _legacy._whole_repo_text(repo, cap_chars)
            if repo not in whole_true_tokens:
                full, _ = _legacy._whole_repo_text(repo, cap_chars=None)
                whole_true_tokens[repo] = _legacy.count_tokens(full)
            sliced = _legacy.semantic_slice(repo, task["target"], idx=idx_cache[repo])
        except (ValueError, OSError) as exc:
            errored.append(_legacy._task_error_row(task, exc))
            continue

        ctx_a = sliced["slice_text"]
        ctx_b, b_truncated = whole_cache[repo]
        a = _ask(prov, task["question"], ctx_a)
        b = _ask(prov, task["question"], ctx_b)
        row = {
            "id": task["id"], "project": task_project_label(task),
            "question": task["question"],
            "tokens_A": _legacy.count_tokens(ctx_a),
            "tokens_B": _legacy.count_tokens(ctx_b),
            "tokens_B_true": whole_true_tokens[repo],
            "b_truncated": b_truncated,
            "answer_A": a["text"], "answer_B": b["text"],
            "answer_A_sha256": a["text_sha256"], "answer_B_sha256": b["text_sha256"],
            "answer_A_chars": a["text_chars"], "answer_B_chars": b["text_chars"],
            "answer_A_truncated": a["text_truncated"],
            "answer_B_truncated": b["text_truncated"],
            "provider_error_A": None if a["ok"] else {
                "type": a["error_type"], "message": a["error"],
            },
            "provider_error_B": None if b["ok"] else {
                "type": b["error_type"], "message": b["error"],
            },
        }

        if not a["ok"] or not b["ok"] or a["text_truncated"] or b["text_truncated"]:
            row["measurement_error"] = True
            reasons = []
            if not a["ok"]:
                reasons.append("provider_A")
            if not b["ok"]:
                reasons.append("provider_B")
            if a["text_truncated"]:
                reasons.append("answer_A_truncated")
            if b["text_truncated"]:
                reasons.append("answer_B_truncated")
            row["measurement_error_reasons"] = reasons
            per_task.append(row)
            continue

        va = _validate_task_answer(task, a["text"] or "")
        vb = _validate_task_answer(task, b["text"] or "")
        if not va["validated"] or not vb["validated"]:
            row["validator_missing"] = True
            per_task.append(row)
            continue

        row.update({
            "success_A": va["semantic_success"], "success_B": vb["semantic_success"],
            "frac_A": va["lexical_fraction"], "frac_B": vb["lexical_fraction"],
            "guarded_lexical_A": va["guarded_lexical_success"],
            "guarded_lexical_B": vb["guarded_lexical_success"],
            "validator_A": va["validator"], "validator_B": vb["validator"],
        })
        per_task.append(row)

    scored = [
        row for row in per_task
        if not row.get("measurement_error") and not row.get("validator_missing")
    ]
    measurement_errors = [row for row in per_task if row.get("measurement_error")]
    unvalidated = [row for row in per_task if row.get("validator_missing")]
    return {
        "tier": 2, "skipped": False,
        "provider": {k: prov[k] for k in ("kind", "model", "host")},
        "scoring_method": "explicit-task-validator-v1",
        "n_tasks": len(per_task), "n_scored_tasks": len(scored),
        "n_measurement_error_tasks": len(measurement_errors),
        "n_unvalidated_tasks": len(unvalidated),
        "success_A": sum(row["success_A"] for row in scored),
        "success_B": sum(row["success_B"] for row in scored),
        "tokens_A": sum(row["tokens_A"] for row in scored),
        "tokens_B": sum(row["tokens_B"] for row in scored),
        "tokens_B_true": sum(row["tokens_B_true"] for row in scored),
        "b_truncated_any": any(row["b_truncated"] for row in scored),
        "per_task": per_task, "measurement_errors": measurement_errors,
        "unvalidated": unvalidated, "n_errored_tasks": len(errored),
        "errored": sorted(errored, key=lambda row: row["id"]),
    }


def render_tier2(result: dict) -> str:
    """Render semantic scores and degraded measurements as separate evidence."""
    if result.get("skipped"):
        return "\n".join([
            "", "TIER 2 -- LLM task-success (distilled slice A vs whole-repo concat B).",
            f"  SKIPPED: {_safe_ascii(result['reason'])}",
        ])

    scored = [
        row for row in result.get("per_task", [])
        if not row.get("measurement_error") and not row.get("validator_missing")
    ]
    headers = [
        "TASK", "PROJECT", "OK_A", "OK_B", "LEX_A", "LEX_B",
        "TOK_A", "TOK_B", "TOK_B(true)", "B_TRUNC",
    ]
    rows = [[
        _safe_ascii(row["id"]), _safe_ascii(row["project"]),
        "yes" if row["success_A"] else "no", "yes" if row["success_B"] else "no",
        f"{100 * row['frac_A']:.0f}%", f"{100 * row['frac_B']:.0f}%",
        f"{row['tokens_A']:,}", f"{row['tokens_B']:,}",
        f"{row['tokens_B_true']:,}", "yes" if row["b_truncated"] else "no",
    ] for row in scored]

    prov = result["provider"]
    tok_a, tok_b = result["tokens_A"], result["tokens_B"]
    ratio = f"{100 * tok_a / tok_b:.1f}%" if tok_b else "n/a"
    n_scored = result.get("n_scored_tasks", len(scored))
    n_attempted = result.get("n_tasks", len(result.get("per_task", [])))
    lines = [
        "",
        "TIER 2 -- LLM task-success (distilled slice A vs whole-repo concat B).",
        f"provider: {_safe_ascii(prov['kind'])} model={_safe_ascii(prov['model'])} "
        f"host={_safe_ascii(prov['host'])}",
        f"scoring: {_safe_ascii(result.get('scoring_method', 'legacy'))}",
        "  Semantic success requires an explicit task validator. LEX_A/LEX_B is "
        "lexical coverage only, not task success.",
        "  Provider/runtime failures and oversized outputs are measurement errors, "
        "never ordinary wrong answers.",
        "", _table(headers, rows), "",
        f"AGGREGATE over {n_scored} scored task(s) from {n_attempted} attempted:  "
        f"success A = {result['success_A']}/{n_scored}   "
        f"success B = {result['success_B']}/{n_scored}",
        f"  tokens on scored pairs: A = {tok_a:,}   B (sent) = {tok_b:,}   "
        f"B (true) = {result.get('tokens_B_true', tok_b):,}   "
        f"(A is {ratio} of B-sent)",
    ]
    if result.get("b_truncated_any"):
        lines.append(
            "  WARNING: B was truncated for at least one scored task; B-sent is a "
            "weaker baseline than the true whole-repo context."
        )

    measurement_errors = result.get("measurement_errors") or []
    if measurement_errors:
        lines += ["", f"*** MEASUREMENT ERRORS ({len(measurement_errors)}) -- "
                  "EXCLUDED from semantic success denominators: ***"]
        for row in measurement_errors:
            a, b = row.get("provider_error_A"), row.get("provider_error_B")
            a_state = f"{a['type']}: {a['message']}" if a else (
                "answer truncated" if row.get("answer_A_truncated") else "ok"
            )
            b_state = f"{b['type']}: {b['message']}" if b else (
                "answer truncated" if row.get("answer_B_truncated") else "ok"
            )
            lines.append(
                f"  {_safe_ascii(row['id'])}: A={_safe_ascii(a_state)}; "
                f"B={_safe_ascii(b_state)}"
            )

    unvalidated = result.get("unvalidated") or []
    if unvalidated:
        lines += ["", f"*** UNVALIDATED TASKS ({len(unvalidated)}) -- no explicit "
                  "semantic validator, EXCLUDED from task-success denominators: ***"]
        lines += [f"  {_safe_ascii(row['id'])}" for row in unvalidated]

    errored = result.get("errored") or []
    if errored:
        lines += ["", f"*** ERRORED TASKS ({len(errored)}) -- resolution failed "
                  "before an LLM call, EXCLUDED from the aggregate: ***"]
        for row in sorted(errored, key=lambda item: item["id"]):
            lines.append(
                f"  {_safe_ascii(row['id'])} [{_safe_ascii(row.get('target'))}] "
                f"({_safe_ascii(row['label_provenance'])}/"
                f"{_safe_ascii(row['label_tier'])}): {_safe_ascii(row['error'])}"
            )
    return "\n".join(lines)


def builtin_validator_coverage() -> tuple[list[str], list[str]]:
    ids = sorted(task["id"] for task in TASKS if task.get("question"))
    return ids, [task_id for task_id in ids if task_id not in _BUILTIN_VALIDATORS]

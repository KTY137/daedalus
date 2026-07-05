"""Context compaction for long-running sessions -- zero-dep.

Two reasons to compact (docs/IMPROVEMENTS_RESEARCH.md): cost (one study: -63.9%
tokens, +8pp task performance from "last-N tool pairs + rolling summary") and
quality ("context rot" degrades agents past ~30k tokens regardless of the
nominal window). Keep system messages + a summary of the middle + the last N
turns verbatim.

The summarizer is pluggable: default is a cheap heuristic rollup (no model
call); pass ``ollama_summarizer(...)`` to have the local bench write the summary.
"""

from __future__ import annotations

import json
from typing import Any, Callable

CONTEXT_ROT_TOKENS = 30_000   # compact once estimated context exceeds this
DEFAULT_KEEP_LAST = 6


def estimate_tokens(messages: list[dict]) -> int:
    """Rough char/4 heuristic (offline; not a substitute for count_tokens)."""
    chars = 0
    for m in messages:
        c = m.get("content")
        chars += len(c if isinstance(c, str) else json.dumps(c, default=str))
    return chars // 4


def should_compact(messages: list[dict], budget: int = CONTEXT_ROT_TOKENS) -> bool:
    return estimate_tokens(messages) > budget


def _heuristic_summary(msgs: list[dict]) -> str:
    lines = []
    for m in msgs:
        c = m.get("content")
        text = c if isinstance(c, str) else json.dumps(c, default=str)
        lines.append(f"- {m.get('role', '?')}: {text[:120].strip()}")
    return "\n".join(lines[-50:])


def ollama_summarizer(host: str, model: str) -> Callable[[list[dict]], str]:
    """Return a summarizer that asks the local bench to compress the middle."""
    from .providers._openai_compat import ProviderHTTPError, chat_completion

    def _sum(msgs: list[dict]) -> str:
        transcript = _heuristic_summary(msgs)
        try:
            return chat_completion(
                base_url=host.rstrip("/") + "/v1", model=model,
                system="Summarize this agent transcript into terse bullet points of durable facts, "
                       "decisions, and open threads. No preamble.",
                user=transcript, api_key=None, timeout_s=60, force_json=False, temperature=0.0,
            ).strip()[:2000]
        except (ProviderHTTPError, ValueError):
            return transcript  # fall back to the heuristic rollup
    return _sum


def compact(
    messages: list[dict[str, Any]],
    keep_last: int = DEFAULT_KEEP_LAST,
    summarizer: Callable[[list[dict]], str] | None = None,
) -> list[dict[str, Any]]:
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if len(rest) <= keep_last:
        return messages
    head, tail = rest[:-keep_last], rest[-keep_last:]
    summary = (summarizer or _heuristic_summary)(head)
    note = {"role": "system", "content": "[compacted earlier context]\n" + summary}
    return system + [note] + tail

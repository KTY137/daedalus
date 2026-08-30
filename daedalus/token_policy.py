# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations


MAX_SUMMARY_CHARS = 600
MAX_TODO_CHARS = 180
MAX_PATHS_PER_REQUEST = 12
DEFAULT_MODEL = "sonnet"
HIGH_RISK_MODEL = "opus"
CHEAP_MODEL = "haiku"

STATIC_PROMPT_PREFIX = """Daedalus Bridge Protocol v1.

Minimize tokens:
- Use the supplied paths instead of exploring the whole repo.
- Read only files needed for this task.
- Return compact structured JSON only.
- No conversational intro, praise, or markdown.
- No full code dumps unless explicitly requested.
- Prefer file:line references and short summaries.
- Do not include chain-of-thought; include only conclusions and evidence.
"""


def trim_paths(paths: list[str], limit: int = MAX_PATHS_PER_REQUEST) -> list[str]:
    return list(dict.fromkeys(paths))[:limit]


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."

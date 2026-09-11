"""Canonical presentation-only integrity helpers for terminal text.

Retained evidence stays verbatim.  A terminal is a separate, lossy projection:
every untrusted value is collapsed to one line, converted to printable ASCII,
and bounded only after sanitization.  Printable ASCII excludes C0/C1 controls,
Unicode bidirectional/format controls, and lone surrogates without coupling a
runtime consumer to the private evaluator package.
"""
from __future__ import annotations


TERMINAL_FIELD_MAX_CHARS = 160


def safe_terminal_text(value: object) -> str:
    """Return one bounded printable-ASCII field without mutating *value*."""

    text = " ".join(str(value).split())
    text = text.encode("ascii", "replace").decode("ascii")
    text = "".join(ch if 0x20 <= ord(ch) <= 0x7E else "?" for ch in text)
    if len(text) > TERMINAL_FIELD_MAX_CHARS:
        text = text[: TERMINAL_FIELD_MAX_CHARS - 3] + "..."
    return text


__all__ = ["TERMINAL_FIELD_MAX_CHARS", "safe_terminal_text"]

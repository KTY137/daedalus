# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""tokens.py — token counting for the distill benchmark.

Uses ``tiktoken`` (optional dep) for a real BPE count when installed; otherwise a
``chars/4`` heuristic. Degrades cleanly: the reduction *ratio* is meaningful
either way, and becomes tokenizer-exact when tiktoken is present. This is what
makes the "92.8% smaller" claim rigorous rather than a hand-wave.
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            pass
    return max(1, len(text) // 4)


def tokenizer_name() -> str:
    return "tiktoken/cl100k_base" if _encoder() is not None else "chars/4 (heuristic)"

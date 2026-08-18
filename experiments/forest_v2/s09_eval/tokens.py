"""One tokenizer, shared by the task set and every baseline.

Sharing it is a fairness property, not a convenience: if the scrubber and
the retrievers disagreed about what a token is, leakage scrubbing would be
cosmetic.  Splitting is on non-alphanumerics plus camelCase boundaries, then
lowercased; tokens of length 1 are dropped.
"""
from __future__ import annotations

import re
from typing import List, Set

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def word_tokens(text: str) -> List[str]:
    """Tokenize free text (a commit message, a file body) in document order."""
    out: List[str] = []
    for chunk in _NON_ALNUM.split(text):
        if not chunk:
            continue
        for piece in _CAMEL.split(chunk):
            lowered = piece.lower()
            if len(lowered) > 1:
                out.append(lowered)
    return out


def path_tokens(path: str) -> Set[str]:
    """Tokens a path contributes: directories, stem, and extension."""
    return set(word_tokens(path))

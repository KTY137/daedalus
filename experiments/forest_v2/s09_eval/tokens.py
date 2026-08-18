"""One tokenizer, shared by the task set and every baseline.

Sharing it is a fairness property, not a convenience: if the scrubber and
the retrievers disagreed about what a token is, leakage scrubbing would be
cosmetic.  Splitting is on non-alphanumerics plus camelCase boundaries, then
lowercased; tokens of length 1 are dropped.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Dict, List, Set

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


class TokenCache:
    """Blob-keyed token counts, shared by every retriever in a run.

    Blob shas are content addresses, so the same file at two revisions is
    tokenized once.

    Sharing a cache between retrievers would otherwise make wall-clock a
    measure of who ran first, so the harness pre-warms this cache for a case
    before any retriever runs and reports that as one shared indexing cost.
    Per-retriever timings are therefore warm-cache timings, and the
    tokenization is charged once, to the run, not to whichever baseline
    happened to be listed first.
    """

    def __init__(self, max_entries: int = 20000) -> None:
        self._counts: Dict[str, Counter] = {}
        self._max_entries = max_entries
        self.hits = 0
        self.misses = 0

    def counts(self, blob: str, text: Callable[[], str]) -> Counter:
        cached = self._counts.get(blob)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        counted = Counter(word_tokens(text()))
        if len(self._counts) >= self._max_entries:
            self._counts.clear()
        self._counts[blob] = counted
        return counted

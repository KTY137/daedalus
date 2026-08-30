# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Canonical fail-closed guards for human/model text used by Tier-2 evaluation.

This module is intentionally small.  It hardens two presentation/semantic seams
without rewriting canonical evidence:

* an expected lexical token counts as asserted only when no occurrence of that
  token is negated, hedged, questioned, or subsequently rebutted;
* terminal-facing metadata is rendered as one bounded printable-ASCII line,
  while retained result dictionaries keep the original strings untouched.

``daedalus.eval.tier2`` imports these functions directly. Compatibility
surfaces delegate to Tier 2 at call time; no import-time monkeypatch is needed.
"""
from __future__ import annotations

import re

from daedalus.text_integrity import (
    TERMINAL_FIELD_MAX_CHARS,
    safe_terminal_text,
)

_NEGATION = re.compile(
    r"\b(?:not|never|no|without|cannot|can't|can['\u2019]t|"
    r"doesn't|doesn['\u2019]t|does\s+not|didn't|didn['\u2019]t|did\s+not|"
    r"isn't|isn['\u2019]t|is\s+not|aren't|aren['\u2019]t|are\s+not|"
    r"wasn't|wasn['\u2019]t|was\s+not|weren't|weren['\u2019]t|were\s+not|"
    r"won't|won['\u2019]t|will\s+not|don't|don['\u2019]t|do\s+not|"
    r"should\s+(?:not|never)|shouldn['\u2019]t|"
    r"must\s+(?:not|never)|mustn['\u2019]t)\b",
    re.IGNORECASE,
)
_HEDGE = re.compile(
    r"\b(?:maybe|perhaps|possibly|probably|might|could|guess|unsure|"
    r"uncertain|unclear|unknown)\b",
    re.IGNORECASE,
)
_UNCERTAINTY = re.compile(
    r"\b(?:i\s+(?:cannot|can't|can['\u2019]t)\s+tell|"
    r"i\s+(?:do\s+not|don't|don['\u2019]t)\s+know|"
    r"not\s+enough\s+information|cannot\s+determine|can't\s+determine)\b",
    re.IGNORECASE,
)
_POST_NEGATION = re.compile(
    r"^\W*(?:is|was|are|were|does|did|can|will)?\W*"
    r"(?:not|never|isn't|isn['\u2019]t|wasn't|wasn['\u2019]t|"
    r"aren't|aren['\u2019]t|doesn't|doesn['\u2019]t|cannot|"
    r"can't|can['\u2019]t)\b",
    re.IGNORECASE,
)
_POST_MODAL_NEGATION = re.compile(
    r"^\W*(?:(?!(?:and|or|but)\b)[a-z_][\w-]*\W+)?(?:"
    r"should\s+(?:not|never)|shouldn['\u2019]t|"
    r"must\s+(?:not|never)|mustn['\u2019]t)\b",
    re.IGNORECASE,
)
_REBUTTAL = re.compile(
    r"\b(?:false|incorrect|wrong|untrue|not\s+true)\b",
    re.IGNORECASE,
)
_FOLLOWUP_REBUTTAL = re.compile(
    r"^\s*(?:[^\w\s\n]+\s*)*(?:"
    r"no\b|false\b|incorrect\b|wrong\b|untrue\b|"
    r"but\b[^.!?\n]{0,64}\b(?:false|incorrect|wrong|untrue|not\s+true)\b"
    r")",
    re.IGNORECASE,
)
_FOLLOWUP_CORRECTION = re.compile(
    r"^\s*(?:[^.!?\n]{0,64}[.!?;]\s*)?(?:[^\w\s\n]+\s*)*(?:"
    r"correction\b|actually\b|retraction\b|scratch\s+that\b|"
    r"i\s+(?:hereby\s+)?(?:retract|withdraw)\b|"
    r"(?:that|this|the\s+previous)\s+(?:claim|statement|answer)\b"
    r"[^.!?\n]{0,48}\b(?:false|incorrect|wrong|untrue|retracted|withdrawn)\b"
    r")",
    re.IGNORECASE,
)
_FOLLOWUP_REPLACEMENT = re.compile(
    r"^\s*[^.!?\n]{0,64}[.!?;]\s*(?:instead|rather)\b",
    re.IGNORECASE,
)
_FOLLOWUP_ACTUAL_REPLACEMENT = re.compile(
    r"^\s*(?:[,;]\s*)?but\s+actually\b"
    r"(?P<replacement>[^.!?\n]{0,128})",
    re.IGNORECASE,
)
_REJECTION_BEFORE = re.compile(
    r"\b(?:forbid(?:s|den|ding)?|prohibit(?:s|ed|ing)?|"
    r"disallow(?:s|ed|ing)?|ban(?:s|ned|ning)?|avoid(?:s|ed|ing)?|"
    r"unnecessary)\b(?:\W+\w+){0,5}\W*$",
    re.IGNORECASE,
)
_REJECTION_AFTER = re.compile(
    r"^\W*(?:(?:is|are|was|were|be|being|become|becomes|became|"
    r"remain|remains|remained|should|must)\W+){0,3}"
    r"(?:prohibited|forbidden|disallowed|banned|avoided|unnecessary)\b",
    re.IGNORECASE,
)
_BOUNDARIES = ".;,?!\n"


def safe_ascii_field(value: object) -> str:
    """Compatibility name for the neutral terminal presentation boundary."""

    return safe_terminal_text(value)


def _near(prefix: str, pattern: re.Pattern[str], words: int = 5) -> bool:
    tokens = list(re.finditer(r"\b[\w'\u2019]+\b", prefix))
    if not tokens:
        return False
    start = tokens[max(0, len(tokens) - words)].start()
    return bool(pattern.search(prefix[start:]))


def expected_asserted(answer: str, expected: str) -> bool:
    """Conservatively decide whether *expected* is asserted by *answer*.

    Every occurrence is examined. One negated, hedged, questioned, or rebutted
    occurrence poisons the claim so contradictory text cannot become positive
    fitness evidence merely because an earlier mention looked affirmative.
    """

    low = str(answer).lower()
    needle = str(expected).lower()
    if not low or not needle:
        return False

    saw_positive = False
    saw_rejected = False
    for match in re.finditer(re.escape(needle), low):
        left = max(low.rfind(boundary, 0, match.start()) for boundary in _BOUNDARIES)
        right_positions = [
            pos
            for boundary in _BOUNDARIES
            for pos in (low.find(boundary, match.end()),)
            if pos != -1
        ]
        right = min(right_positions) if right_positions else len(low)
        clause = low[left + 1:right]
        rel_start = match.start() - left - 1
        rel_end = match.end() - left - 1

        rejected = (
            _near(clause[:rel_start], _NEGATION)
            or _near(clause[:rel_start], _HEDGE)
            or _near(clause[:rel_start], _REJECTION_BEFORE, words=7)
            or bool(
                _POST_NEGATION.search(" ".join(clause[rel_end:].split()[:5]))
            )
            or bool(
                _POST_MODAL_NEGATION.search(
                    " ".join(clause[rel_end:].split()[:5])
                )
            )
            or bool(_UNCERTAINTY.search(clause))
        )

        if right < len(low) and low[right] == "?":
            rejected = True

        local_after = " ".join(clause[rel_end:].split()[:8])
        if _REBUTTAL.search(local_after) or _REJECTION_AFTER.search(local_after):
            rejected = True

        followup = low[match.end(): match.end() + 192]
        if _FOLLOWUP_REBUTTAL.match(followup):
            rejected = True
        if _FOLLOWUP_CORRECTION.match(followup):
            rejected = True
        if _FOLLOWUP_REPLACEMENT.match(followup):
            rejected = True
        actual_replacement = _FOLLOWUP_ACTUAL_REPLACEMENT.match(followup)
        if (
            actual_replacement is not None
            and needle not in actual_replacement.group("replacement")
        ):
            rejected = True

        if rejected:
            saw_rejected = True
        else:
            saw_positive = True

    return saw_positive and not saw_rejected


__all__ = [
    "TERMINAL_FIELD_MAX_CHARS",
    "expected_asserted",
    "safe_ascii_field",
]

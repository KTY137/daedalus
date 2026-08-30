"""Narrow fail-closed guards for human/model text used by Tier-2 evaluation.

This module is intentionally small.  It hardens two presentation/semantic seams
without rewriting canonical evidence:

* an expected lexical token counts as asserted only when no occurrence of that
  token is negated, hedged, questioned, or subsequently rebutted;
* terminal-facing metadata is rendered as one printable ASCII line, while the
  retained result dictionaries keep the original strings untouched.

The functions are installed into :mod:`daedalus.eval.tier2` by the package
strangler in ``daedalus.eval.__init__`` so the historical import surface keeps
working until the legacy evaluator module is collapsed.
"""
from __future__ import annotations

import re


_REBUTTAL = re.compile(
    r"\b(?:false|incorrect|wrong|untrue|not\s+true)\b",
    re.IGNORECASE,
)
_FOLLOWUP_REBUTTAL = re.compile(
    r"^\s*(?:[?!.,;:]\s*)?(?:"
    r"no\b|false\b|incorrect\b|wrong\b|untrue\b|"
    r"but\b[^.!?\n]{0,64}\b(?:false|incorrect|wrong|untrue|not\s+true)\b"
    r")",
    re.IGNORECASE,
)
_BOUNDARIES = ".;,?!\n"


def safe_ascii_field(value: object) -> str:
    """Return a single printable-ASCII terminal field without changing evidence."""

    text = " ".join(str(value).split())
    text = text.encode("ascii", "replace").decode("ascii")
    return "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in text)


def expected_asserted(answer: str, expected: str) -> bool:
    """Conservatively decide whether *expected* is asserted by *answer*.

    Every occurrence is examined. One negated, hedged, questioned, or rebutted
    occurrence poisons the claim so contradictory text cannot become positive
    fitness evidence merely because an earlier mention looked affirmative.
    """

    from . import tier2 as _tier2

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
            _tier2._near(clause[:rel_start], _tier2._NEGATION)
            or _tier2._near(clause[:rel_start], _tier2._HEDGE)
            or bool(
                _tier2._POST_NEGATION.search(
                    " ".join(clause[rel_end:].split()[:5])
                )
            )
            or bool(_tier2._UNCERTAINTY.search(clause))
        )

        if right < len(low) and low[right] == "?":
            rejected = True

        local_after = " ".join(clause[rel_end:].split()[:8])
        if _REBUTTAL.search(local_after):
            rejected = True

        if _FOLLOWUP_REBUTTAL.match(low[match.end(): match.end() + 128]):
            rejected = True

        if rejected:
            saw_rejected = True
        else:
            saw_positive = True

    return saw_positive and not saw_rejected


__all__ = ["expected_asserted", "safe_ascii_field"]

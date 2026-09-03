"""Every recorded event kind must have a word in the cockpit's timeline.

WHY THIS TEST EXISTS. `daedalus/progress.py` records a run as a sequence of
events, each with a `kind` drawn from `EVENT_KINDS`. The cockpit's timeline
translates those kinds into German. It shipped with a map that invented two
kinds that do not exist (`failed`, `cancelled`) and omitted four that do
(`generating`, `tool_ran`, `gate_verdict`, `patch_produced`) — so on a real
run, four of the ten steps rendered as raw English identifiers in a German
interface, and the two invented entries were dead code that made the map look
complete.

That was fixed by copying the real list into the map. A copy is not a
contract: adding an eleventh kind to `EVENT_KINDS` would leave the map stale
and the browser test — which hardcodes the same ten — green, reproducing the
exact drift that caused the bug.

So the binding lives here, on the Python side, where `EVENT_KINDS` is defined.
It reads the map out of the shipped frontend source and requires it to cover
every kind the backend can emit.

It deliberately does NOT require the reverse (that every key in the map is a
real kind is checked separately below, as a distinct failure with a distinct
message), and it says nothing about the German wording itself — that is a
translation choice, not a contract.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from daedalus.progress import EVENT_KINDS

ROOT = Path(__file__).resolve().parents[2]
TIMELINE = ROOT / "apps" / "web" / "src" / "features" / "mission" / "Timeline.tsx"

# `const KIND_WORD: Record<string, string> = { … };`
_MAP = re.compile(r"const KIND_WORD[^=]*=\s*\{(.*?)\n\};", re.S)
# `queued: 'eingereiht',` — the key, quoted or bare.
_KEY = re.compile(r"^\s*'?([a-z_]+)'?\s*:", re.M)


def _mapped_kinds() -> set[str]:
    assert TIMELINE.exists(), f"the timeline source moved: {TIMELINE}"
    body = _MAP.search(TIMELINE.read_text(encoding="utf-8"))
    assert body, "KIND_WORD is no longer a literal object in Timeline.tsx"
    return set(_KEY.findall(body.group(1)))


def test_every_backend_event_kind_has_a_word() -> None:
    missing = sorted(set(EVENT_KINDS) - _mapped_kinds())
    assert not missing, (
        "these kinds are recorded by progress.py but have no word in the "
        f"cockpit timeline, so they render as raw identifiers: {missing}"
    )


def test_the_timeline_does_not_invent_kinds() -> None:
    invented = sorted(_mapped_kinds() - set(EVENT_KINDS))
    assert not invented, (
        "the cockpit timeline has words for kinds progress.py never emits, "
        f"which is dead code that makes the map look complete: {invented}"
    )


@pytest.mark.parametrize("kind", sorted(EVENT_KINDS))
def test_each_kind_individually(kind: str) -> None:
    # Parametrised so a rename names the kind that broke, rather than a set.
    assert kind in _mapped_kinds()

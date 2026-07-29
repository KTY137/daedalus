"""Has a NEW record producer appeared without declaring itself?

``daedalus/spine/envelope.py`` converts three producers and DECLARES the rest.
The declaration is the valuable half: a correlation id that covers three of
sixteen formats is only useful if a reader knows which thirteen it does not
cover. Left as prose, that list rots the first time someone adds a producer --
and it rots silently, because nothing fails.

This file is the same shape as ``tests/test_spend_coverage.py``: a scan with a
DECLARED LEDGER, green today against a named list, RED the moment a new
producer appears in neither table. It asserts nothing about whether a producer
*should* be converted -- that is a judgement call and it belongs to whoever
adds one. It asserts only that the judgement was MADE and written down.

WHAT THE SCAN CANNOT SEE, stated rather than glossed:
  * SQLite producers (``conversation.py``, and the spine ledger itself) do not
    serialise through ``json.dumps``, so the heuristic cannot find them. The
    spine ledger is converted; ``conversation.py`` is declared by hand.
  * A producer that builds its path entirely from variables with no ``runs/``
    or ``.jsonl`` literal anywhere in the module is invisible. Nothing in the
    tree looks like that today.
Both are why the ledger is hand-maintainable rather than generated.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from daedalus.spine import envelope

ROOT = Path(__file__).resolve().parents[1]

# All three must hit for a module to count, which is what keeps the ledger
# short enough to be read. Requiring only a serialiser plus any write matched
# 37 modules -- mostly config and rendering -- and a 37-row ledger is a
# document nobody opens.
_SERIALIZE = re.compile(r"json\.dumps\(|canonical_json\(")
_PERSIST = re.compile(
    r"""\.write_text\(|open\([^)]*["']a["']|_write_json_atomic\(""")
# A RUN-STATE target: the record lands in runs/ or memory/, or it is a .jsonl.
# Deliberately NOT a bare `.json"`, which matched every config writer.
_TARGET = re.compile(r"""\.jsonl|["']runs["'/]|runs/|["']memory["'/]|memory/""")

_SKIP_PARTS = {"__pycache__", "node_modules", ".git", ".venv", "venv", "build",
               "daedalus.egg-info", ".pytest_cache", "dist", "structcore-rs"}
_SCAN_DIRS = ("daedalus", "runs")


def record_producers(root: Path) -> set[str]:
    """Every module that serialises a structured record into run state."""
    out: set[str] = set()
    for directory in _SCAN_DIRS:
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in _SKIP_PARTS for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if (_SERIALIZE.search(text) and _PERSIST.search(text)
                    and _TARGET.search(text)):
                out.add(path.relative_to(root).as_posix())
    return out


def test_the_scan_finds_the_producers_that_were_actually_converted():
    """A detector that cannot see the three KNOWN producers proves nothing
    about the fourteenth. Calibration before drift-detection."""
    found = record_producers(ROOT)
    for known in ("daedalus/loop.py", "daedalus/file_bridge.py",
                  "daedalus/council/bus.py", "daedalus/memstore.py"):
        assert known in found, (
            f"the producer scan no longer finds {known} -- the heuristic has "
            "drifted and every green result below is meaningless")


def test_no_new_record_producer_has_appeared_undeclared():
    """THE DRIFT DETECTOR.

    A new producer is a new island: its records carry ids that join to nothing,
    and the way that gets discovered today is someone trying to follow a run
    six months from now and finding a gap.
    """
    declared = set(envelope.CONVERTED_PRODUCERS) | set(
        envelope.UNCONVERTED_PRODUCERS)
    surprises = sorted(record_producers(ROOT) - declared)
    assert surprises == [], (
        f"new record producer(s) declaring neither conversion nor a reason: "
        f"{surprises}. Either thread envelope.current_trace_id() through it "
        "and add it to envelope.CONVERTED_PRODUCERS, or add it to "
        "UNCONVERTED_PRODUCERS WITH THE REASON and the conversion cost.")


def test_the_producer_ledger_has_not_rotted():
    """A ledger naming files that no longer exist reads as coverage of files
    that do. Same failure ``test_spend_coverage`` guards against: a stale
    confession is worse than none, because attention gets budgeted for it."""
    for name in (set(envelope.CONVERTED_PRODUCERS)
                 | set(envelope.UNCONVERTED_PRODUCERS)):
        assert (ROOT / name).exists(), (
            f"the producer ledger names a file that is gone: {name}")


def test_a_module_is_not_declared_both_converted_and_unconverted():
    """The two tables are a partition. An entry in both means one of them is
    lying, and a reader has no way to tell which."""
    both = set(envelope.CONVERTED_PRODUCERS) & set(
        envelope.UNCONVERTED_PRODUCERS)
    assert both == set(), f"declared as both converted and unconverted: {both}"


def test_every_converted_producer_says_where_the_trace_lives():
    """"Converted" alone does not tell a reader where to look for the field,
    and a join they cannot find is a join they do not use."""
    for name, how in envelope.CONVERTED_PRODUCERS.items():
        assert envelope.TRACE_KEY in how, (
            f"{name} is declared converted but its note never says where the "
            f"{envelope.TRACE_KEY} lives: {how!r}")


def test_every_unconverted_producer_states_a_cost_or_a_reason():
    """The ledger is a worklist, not an excuse list. An entry with no cost and
    no reason is a to-do nobody can pick up."""
    for name, why in envelope.UNCONVERTED_PRODUCERS.items():
        assert len(why) > 40, f"{name}: note too thin to act on: {why!r}"
        assert re.search(r"LOW|MEDIUM|HIGH|UNKNOWN|NOT A RUN RECORD|SQLite",
                         why), (
            f"{name}: note states neither a conversion cost nor a reason it is "
            f"not a run record: {why!r}")


def test_the_three_converted_producers_are_the_declared_three():
    """Pins the claim the module docstring makes, so a fourth conversion that
    forgets the docstring is caught here."""
    assert set(envelope.CONVERTED_PRODUCERS) == {
        "daedalus/spine/ledger.py",
        "daedalus/loop.py",
        "daedalus/file_bridge.py",
    }

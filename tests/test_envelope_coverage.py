"""Has a NEW record producer appeared without declaring itself?

``daedalus/spine/envelope.py`` converts four producers and DECLARES the rest.
The declaration is the valuable half: a correlation id that covers four of
seventeen formats is only useful if a reader knows which thirteen it does not
cover. (Three and sixteen until 2026-07-30, when this file's own drift detector
caught ``lanes/fanout.py`` -- written that day, undeclared, and its per-task
result files a new island. The detector found it before a reader did, which is
the entire point of the file.) Left as prose, that list rots the first time someone adds a producer --
and it rots silently, because nothing fails.

This file is the same shape as ``tests/test_spend_coverage.py``: a scan with a
DECLARED LEDGER, green today against a named list, RED the moment a new
producer appears in neither table. It asserts nothing about whether a producer
*should* be converted -- that is a judgement call and it belongs to whoever
adds one. It asserts only that the judgement was MADE and written down.

TWO PRODUCER SHAPES, because the tree grew a second one
-------------------------------------------------------
The scan originally knew ONE shape: serialiser, writer and run-state target all
CO-LOCATED in one module. On 2026-09-02 the calibration test below went red --
``daedalus/file_bridge.py`` had stopped matching -- and the cause was not a
renamed helper but a changed ARCHITECTURE. The thirteen G1-IFACE-BRIDGE packets
turned the bridge into a composition root that INJECTS a typed writer port and a
``Path`` into owner modules under ``daedalus/interfaces/bridge/``. MEASURED at
515b5fce, no single file satisfied all three predicates any more:

    daedalus/file_bridge.py                 serialise F  persist T  target T
    daedalus/interfaces/bridge/journal.py   serialise T  persist F  target F
    daedalus/interfaces/bridge/dispatch.py  serialise T  persist F  target T
    daedalus/interfaces/bridge/queue.py     serialise T  persist F  target F
    daedalus/interfaces/bridge/watcher.py   serialise T  persist F  target F

So the scan now recognises a second shape, INJECTED-WRITER: a module that
declares a parameter or dataclass field named ``write_*`` annotated with a
writer port over a ``Path``. It carries NO ``_TARGET`` requirement, and that is
not a loosening -- it is the definition of the shape. The target arrives as an
injected ``Path``, so demanding a ``runs/`` literal in the module would be
demanding the one thing this shape structurally cannot have.

The two shapes are a UNION, never a replacement. Every module the co-located
rule found before is still found by it; the second shape can only ADD names to
the set the drift detector below demands be declared. A reshape that could
SUBTRACT would be a weakening; this one cannot.

Why the JSON and TEXT ports differ: a ``WriteJsonPort``/``Callable[[Path, dict]``
is a producer on its own, because the port's CONTRACT is "serialise this record
to this path" -- ``journal.write_journal`` hands over a dict and contains no
``json.dumps`` at all, so requiring a serialiser would miss it. A
``WriteTextPort`` counts only alongside a serialiser, because writing arbitrary
text to an injected path is what a plain log does, and
``interfaces/bridge/projection.py`` is exactly that.

WHAT THE SCAN CANNOT SEE, stated rather than glossed:
  * SQLite producers (the spine ledger itself) do not serialise through
    ``json.dumps``, so the heuristic cannot find them. The spine ledger is
    converted. ``conversation.py`` used to be the second such producer with its
    own SQLite file; since 2026-08-22 it writes typed intents on the spine
    instead and produces no records of its own, and its hand-written entry says
    so rather than being dropped -- a reader who greps for it must land on the
    reason, not on silence.
  * A producer that takes its writer under a parameter NOT named ``write_*``,
    or annotated ``Any``/not annotated at all, is invisible to the
    injected-writer shape. BOTH halves of that predicate are name-based, and
    that is the residual cost of detecting an injected port statically.
  * CORRECTED 2026-09-02. This file used to claim: "a producer that builds its
    path entirely from variables with no ``runs/`` or ``.jsonl`` literal
    anywhere in the module is invisible. Nothing in the tree looks like that
    today." The second sentence became FALSE the moment the bridge packets
    landed -- four modules look exactly like that -- and it went on reassuring
    readers while the detector was blind to all four. A named blind spot that
    is never re-measured decays into a false all-clear, which is worse than an
    unnamed one because attention gets budgeted for it. The injected-writer
    shape exists to cover precisely the case that sentence waved away.
All of these are why the ledger is hand-maintainable rather than generated.
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
# A NAME-BASED detector over a BEHAVIOUR, which is why this list grows: every
# time a write is factored out into a helper, the helper's name has to arrive
# here or the detector goes blind to its callers. ``_write_json_atomic(`` was the
# first such entry (file_bridge's publisher).
#
# ``write_text_atomic``/``write_bytes_atomic`` are the second, and they cost a
# RED BASELINE to notice: on 2026-07-30 daedalus/atomic.py replaced the inline
# temp-file-plus-os.replace sequence in loop.py, arch_memory.py, shift.py,
# file_bridge.py and spine/killswitch.py with one shared publisher. Behaviour
# unchanged; the detector stopped recognising loop.py as a producer, and the
# calibration test below correctly refused to trust its own green results.
#
# Note the two are matched WITHOUT a leading ``\.`` -- they are module-level
# functions, not methods, so ``.write_text(`` does not cover them.
#
# ``append_lines(`` is the THIRD, and it cost the same red baseline on
# 2026-09-02. G1-PORT-01 replaced the inline ``open(path, "a")`` append in
# progress.py with ``daedalus.journal_io.append_lines``, the locked
# short-write-checked appender. Behaviour unchanged; the detector stopped
# recognising progress.py, and the calibration test below refused to trust its
# own green -- the third time this exact shape has been caught by the third
# time this exact comment was written, which is why the comment says "this list
# grows" rather than naming a fixed set.
#
# MEASURED at eb5228ac: progress.py was not the only casualty. Teaching the
# scan this one name restores THREE modules -- daedalus/progress.py,
# daedalus/council/canary.py and daedalus/metrics.py -- and subtracts none.
# kairos/archive.py and memory/__init__.py also append through the helper but
# were still visible on another persist match, which is exactly how a
# name-based detector rots quietly: partial coverage reads as coverage. All
# five callers were already DECLARED in the ledger, so the blindness cost no
# ledger row -- it cost the guarantee that a sixth caller would be noticed.
_PERSIST = re.compile(
    r"""\.write_text\(|open\([^)]*["']a["']|_write_json_atomic\("""
    r"""|write_text_atomic\(|write_bytes_atomic\(|append_lines\(""")
# A RUN-STATE target: the record lands in runs/ or memory/, or it is a .jsonl.
# Deliberately NOT a bare `.json"`, which matched every config writer.
_TARGET = re.compile(r"""\.jsonl|["']runs["'/]|runs/|["']memory["'/]|memory/""")

# ---- shape two: the writer arrives INJECTED ------------------------------- #
# Two independent signals are required, which is what keeps this as selective
# as the three-way conjunction above: the binding is NAMED ``write_*`` AND it
# is TYPED as a callable over a Path. MEASURED 2026-09-02 over 470 scanned
# modules, these two match 4 files and all 4 are genuine bridge producers --
# nothing else in the tree declares an injected writer at all.
#
# Both the keyword-port style (``write_text: WriteTextPort``, journal/queue/
# watcher) and the frozen-dataclass ports-bundle style
# (``write_json_atomic: Callable[[Path, dict[str, Any]], None]``, dispatch)
# are covered, because the bridge uses BOTH and a detector that saw only one
# would report the other's absence as a clean tree.
#
# A dict-shaped writer needs no local serialiser: the port's contract IS the
# serialisation. A str/bytes-shaped one does, or every log writer matches.
_INJECTED_JSON_WRITER = re.compile(
    r"""^[ \t]*write_\w*[ \t]*:[ \t]*"""
    r"""(?:WriteJsonPort\b|Callable\[\[[ \t]*Path[ \t]*,[ \t]*dict)""", re.M)
_INJECTED_TEXT_WRITER = re.compile(
    r"""^[ \t]*write_\w*[ \t]*:[ \t]*(?:Write(?:Text|Bytes)Port\b"""
    r"""|Callable\[\[[ \t]*Path[ \t]*,[ \t]*(?:str|bytes)[ \t]*\])""", re.M)

#: The shape names are load-bearing: a failure has to say WHICH half of the
#: detector went blind, or the next reader repeats this session's diagnosis.
CO_LOCATED = "co-located"
INJECTED_WRITER = "injected-writer"

_SKIP_PARTS = {"__pycache__", "node_modules", ".git", ".venv", "venv", "build",
               "daedalus.egg-info", ".pytest_cache", "dist", "structcore-rs"}
_SCAN_DIRS = ("daedalus", "runs")


def producers_by_shape(root: Path) -> dict[str, set[str]]:
    """Producers grouped by the SHAPE that made each one visible.

    Grouped rather than unioned because a union cannot say WHICH half of the
    detector is working. That distinction is the whole lesson of 2026-09-02:
    the co-located half was still finding 35 modules and looking perfectly
    healthy while the injected-writer case was invisible, so a single
    aggregate number would have read as good news. An instrument that cannot
    report which of its channels is dead reports its own blindness as normal
    operation.
    """
    found: dict[str, set[str]] = {CO_LOCATED: set(), INJECTED_WRITER: set()}
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
            name = path.relative_to(root).as_posix()
            serialises = bool(_SERIALIZE.search(text))
            if serialises and _PERSIST.search(text) and _TARGET.search(text):
                found[CO_LOCATED].add(name)
            if _INJECTED_JSON_WRITER.search(text) or (
                    serialises and _INJECTED_TEXT_WRITER.search(text)):
                found[INJECTED_WRITER].add(name)
    return found


def record_producers(root: Path) -> set[str]:
    """Every module that serialises a structured record into run state.

    The union of both shapes. Union, so this can only ever be a SUPERSET of
    what the original co-located rule returned -- the drift detector below
    gains names to account for and never loses any.
    """
    return set().union(*producers_by_shape(root).values())


#: Modules each SHAPE must still be able to see, keyed by the shape that has
#: to see it. Keyed rather than flat because a module found by the wrong half
#: is not calibration: if the injected-writer predicate broke and a bridge
#: module happened to also satisfy the co-located rule, a flat membership test
#: would stay green over a dead channel. Every entry below is asserted against
#: ITS OWN shape only.
#:
#: ``daedalus/file_bridge.py`` was on this list until 2026-09-02 and is NOT
#: here now -- see the composition-root test directly below, which is where it
#: went. It was not dropped to restore green; it no longer serialises any
#: record at all, and asserting that the producer scan can see it would be
#: asserting something false about the module.
_CALIBRATION = {
    CO_LOCATED: (
        "daedalus/orchestration/loop.py",
        "daedalus/council/bus.py",
        "daedalus/progress.py",
    ),
    INJECTED_WRITER: (
        "daedalus/interfaces/bridge/queue.py",
        "daedalus/interfaces/bridge/journal.py",
        "daedalus/interfaces/bridge/dispatch.py",
        "daedalus/interfaces/bridge/watcher.py",
    ),
}


def test_the_scan_finds_the_producers_that_were_actually_converted():
    """A detector that cannot see the KNOWN producers proves nothing about the
    next one. Calibration before drift-detection.

    Both shapes are calibrated. The co-located entries are findable ONLY by
    the three-way conjunction and the injected-writer entries ONLY by the port
    predicate, so neither half can go blind without turning this red."""
    by_shape = producers_by_shape(ROOT)
    for shape, known_modules in _CALIBRATION.items():
        for known in known_modules:
            assert known in by_shape[shape], (
                f"the {shape!r} half of the producer scan no longer finds "
                f"{known} -- that shape has drifted blind and every green "
                f"result below is meaningless. Found by {shape!r}: "
                f"{sorted(by_shape[shape])}")


def test_the_bridge_composition_root_still_owns_the_run_state_target():
    """Where ``daedalus/file_bridge.py`` went.

    The bridge producer is split: ``interfaces/bridge/*`` serialises the
    records, and this module supplies the two things those modules structurally
    cannot have -- the concrete atomic writer and the ``runs/`` path. That is
    why the injected-writer shape is allowed to skip ``_TARGET``, and the
    permission is only sound while SOME module still pins the target down.

    So this asserts the other end of the injection. If the ``runs/`` literals
    or the concrete writer leave this module, the four owner modules become
    producers with no locatable destination, and the injected-writer shape
    quietly becomes an unfalsifiable claim rather than a narrower one."""
    text = (ROOT / "daedalus/file_bridge.py").read_text(
        encoding="utf-8", errors="replace")
    assert _TARGET.search(text), (
        "daedalus/file_bridge.py no longer names a runs/ target -- the bridge "
        "producer's destination has moved and the injected-writer shape is "
        "now skipping _TARGET with nothing on the other end holding it")
    assert _PERSIST.search(text), (
        "daedalus/file_bridge.py no longer defines or calls a concrete atomic "
        "writer -- find where the bridge's writer is composed now and move "
        "this assertion (and the ledger row) there")
    assert not _SERIALIZE.search(text), (
        "daedalus/file_bridge.py serialises again -- if record production has "
        "moved BACK into the facade it is a co-located producer once more and "
        "belongs in _CALIBRATION[CO_LOCATED], not here")


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


def test_the_converted_producers_are_the_ones_the_docstring_claims():
    """Pins the claim the module docstring makes, so a conversion that forgets
    the prose is caught here.

    Was "the three" until 2026-07-30, when ``lanes/fanout.py`` became the fourth
    -- found by the drift detector in this same file rather than declared by its
    author. Updating this list is the intended way to land a conversion; landing
    one WITHOUT updating it is what the assertion prevents."""
    assert set(envelope.CONVERTED_PRODUCERS) == {
        "daedalus/spine/ledger.py",
        "daedalus/orchestration/loop.py",
        "daedalus/file_bridge.py",
        "daedalus/lanes/fanout.py",
        # The bridge producer's three trace-carrying record families, split out
        # of file_bridge.py by the G1-IFACE-BRIDGE packets. The fourth family,
        # watcher.py's heartbeat, is in UNCONVERTED_PRODUCERS: it is liveness
        # state and carries no trace. Adding these did not convert anything --
        # the trace was already in all three records; what changed is that the
        # scan can now SEE them, so they had to be declared.
        "daedalus/interfaces/bridge/queue.py",
        "daedalus/interfaces/bridge/dispatch.py",
        "daedalus/interfaces/bridge/journal.py",
    }

"""The chat seam has no store of its own -- and the old one cannot come back.

``daedalus/conversation.py`` used to open ``runs/ikarus/conversations.sqlite3``
and its own module docstring called itself "a fourth append-only log". Invariant
1 allows one canonical event spine, so the turns moved onto
``daedalus/spine/ledger.py`` as three typed intent kinds and the module became a
facade. ``daedalus/memstore.py`` -- a fifth append-only log with zero production
importers, whose ledger file had never once been written -- was deleted outright
in the same pass.

Three things must stay true, and each has a test below that goes RED if it stops
being true rather than merely reading oddly:

  1. every turn, dispatch and report round-trips through the canonical spine,
     with nothing left OPEN on it (an open intent is the crash-recovery
     worklist, and chat traffic sitting in it would make that worklist and
     ``health``'s stale-open probe meaningless);
  2. no module opens the retired conversation database, by path or by env var;
  3. ``memstore`` is gone and nothing imports it.

Tests 2 and 3 scan the tree through ``ast`` and look only at string constants
that are NOT docstrings. A plain text scan would flag the sentences above -- and
naming the retired path in prose is the point, so that whoever greps for it
lands on the reason instead of on silence. What must not come back is a path a
program can OPEN, and that is a live string constant, never a comment.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

from daedalus import conversation as conv
from daedalus.spine import ledger as spine_ledger

ROOT = Path(__file__).resolve().parents[1]
_SKIP_PARTS = {"__pycache__", "node_modules", ".git", ".venv", "venv", "build",
               "daedalus.egg-info", ".pytest_cache", "dist", "structcore-rs"}


def _sources() -> list[Path]:
    out: list[Path] = []
    for directory in ("daedalus", "tests", "tools"):
        base = ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if not any(part in _SKIP_PARTS for part in path.parts):
                out.append(path)
    return out


def _live_strings(path: Path) -> list[str]:
    """Every string constant in one module that is not a docstring.

    A docstring is documentation: it may name a retired path, and should, so a
    reader who greps lands on the explanation. A live constant is something a
    program can pass to ``open`` or ``os.environ.get``. Only the second kind is
    evidence that the store came back.

    A file that will not parse is reported as having no live strings rather than
    failing this test: a syntax error is somebody else's red, and swallowing it
    here would be the wrong red anyway.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            first = body[0] if body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings]


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A facade over a throwaway canonical spine.

    ``DAEDALUS_SPINE_DB`` is the ONLY override now -- the module's own
    ``DAEDALUS_CONVERSATION_DB`` went with its database, and this fixture
    working through the spine's env var is itself part of the claim.
    """
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(tmp_path / "spine.sqlite3"))
    with conv.ConversationStore() as s:
        yield s


# --------------------------------------------------------------------------- #
# 1 -- round trip through the canonical spine                                  #
# --------------------------------------------------------------------------- #
def test_the_facade_writes_where_the_spine_lives(store):
    assert store.path == spine_ledger.default_db_path()
    assert conv.default_db_path() == spine_ledger.default_db_path()


def test_a_turn_is_one_canonical_intent_and_comes_back_whole(store):
    turn = store.append_turn(
        "c1", user_message="build a login page", intent="enqueue",
        status=conv.STATUS_PROPOSED, assistant_text="shall I?",
        provider_used="deterministic", model_used="none", project="p",
        source="webapp", strategy="single",
        proposed_action={"kind": "queue_task"}, envelope={"intent": "enqueue"})

    intent = store.spine.get(turn.id)
    assert intent is not None, "the turn is not on the canonical spine at all"
    assert intent.kind == conv.KIND_TURN
    assert intent.effect_key == conv.conversation_effect_key("c1")
    assert intent.payload["user_message"] == "build a login page"

    (read_back,) = store.turns("c1")
    assert read_back == turn, "a turn does not survive its own round trip"
    assert store.last_turn("c1") == turn
    assert store.get_turn(turn.id) == turn
    assert store.conversation_exists("c1")
    assert not store.conversation_exists("never-spoken")


def test_nothing_the_chat_writes_is_ever_an_open_intent(store):
    """THE GUARD THAT PAYS FOR THE DESIGN.

    ``open_intents`` is the crash-recovery worklist a caller is told to
    reconcile against the world, and ``health._p_ledger`` reports an hour-old
    unresolved intent as DEGRADED. Chat volume recorded as open intents would
    drown both. Every kind this module writes is recorded with ``record_fact``,
    terminal in the same transaction, so this list stays empty no matter how
    much is said.

    Goes RED if ``record_fact`` is swapped back to ``record_intent``, or if a
    dispatch is ever left to be resolved by a report that (measurably) nothing
    in this tree sends.
    """
    store.append_turn("c1", user_message="hi", intent="chat",
                      status=conv.STATUS_ANSWERED)
    store.append_turn("c1", user_message="do it", intent="enqueue",
                      status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1", kind="queue_task")
    store.record_dispatch_event("task-1", outcome_state=conv.PRESENT,
                                summary="patch produced, not applied")

    assert store.spine.open_intents() == []
    for kind in conv.CONVERSATION_KINDS:
        assert store.spine.open_intents(kind) == []


def test_a_fact_carries_the_ordinary_two_event_history(store):
    """A reader must not have to special-case this producer: the event history
    is INTENDED then COMPLETED, exactly like every other resolved intent."""
    turn = store.append_turn("c1", user_message="hi", intent="chat",
                             status=conv.STATUS_ANSWERED)
    states = [e.state for e in store.spine.events(turn.id)]
    assert states == [spine_ledger.STATE_INTENDED, spine_ledger.STATE_COMPLETED]
    assert store.spine.get(turn.id).state == spine_ledger.STATE_COMPLETED


def test_seq_is_derived_gap_free_and_survives_a_tail_read(store):
    for n in range(5):
        assert store.append_turn("c1", user_message=f"m{n}", intent="chat",
                                 status=conv.STATUS_ANSWERED).seq == n
    # A second conversation must not shift the first one's numbering: the
    # ordinal counts rows under ONE effect key, not rows in the table.
    assert store.append_turn("c2", user_message="other", intent="chat",
                             status=conv.STATUS_ANSWERED).seq == 0

    assert [t.seq for t in store.turns("c1")] == [0, 1, 2, 3, 4]
    tail = store.turns("c1", limit=2)
    assert [t.user_message for t in tail] == ["m3", "m4"]
    assert [t.seq for t in tail] == [3, 4], (
        "a tail read renumbered the turns it returned -- seq is an absolute "
        "position in the conversation, not an index into the slice")
    assert store.turns("c1", limit=0) == []


# --------------------------------------------------------------------------- #
# 1b -- dispatch attribution, including the shape the old store forked over    #
# --------------------------------------------------------------------------- #
def test_a_dispatch_takes_more_than_one_honest_report(store):
    """The objection that justified the fourth log, answered on the spine.

    The old module argued a turn's dispatch cannot live on the spine because a
    second report would hit ``IntentAlreadyResolved``. It does not, because each
    report is its OWN fact carrying the dispatch's key -- so the spine's
    once-only resolution rule is never approached, let alone weakened.
    """
    turn = store.append_turn("c1", user_message="do it", intent="enqueue",
                             status=conv.STATUS_PROPOSED)
    link = store.link_dispatch("c1", "task-1", turn_id=turn.id,
                               kind="queue_task")
    assert link.turn_id == turn.id

    store.record_dispatch_event("task-1", outcome_state=conv.PRESENT,
                                summary="patch produced, not applied")
    store.record_dispatch_event("task-1", outcome_state=conv.WORKING,
                                summary="patch applied")

    events = store.dispatch_events("task-1")
    assert [e.lifecycle for e in events] == [
        conv.LIFECYCLE_DISPATCHED, conv.LIFECYCLE_REPORTED,
        conv.LIFECYCLE_REPORTED]
    assert [e.outcome_state for e in events] == [None, conv.PRESENT, conv.WORKING]
    assert all(e.dispatch_link_id == link.id for e in events)

    status = store.dispatch_status("task-1")
    assert status["link"] == link
    assert status["latest"].summary == "patch applied"
    assert store.dispatch_status("never-dispatched") is None
    assert store.open_dispatches("c1") == [], "a reported dispatch is not open"


def test_an_unreported_dispatch_shows_as_open_but_only_in_the_display(store):
    store.append_turn("c1", user_message="do it", intent="enqueue",
                      status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1", kind="queue_task")
    (only,) = store.open_dispatches("c1")
    assert only["link"].dispatch_ref == "task-1"
    assert only["latest"].lifecycle == conv.LIFECYCLE_DISPATCHED
    # ... and the spine's REAL worklist is still empty. The display and the
    # recovery worklist are different questions and must not converge.
    assert store.spine.open_intents() == []


def test_one_dispatch_ref_links_once(store):
    store.append_turn("c1", user_message="do it", intent="enqueue",
                      status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1")
    with pytest.raises(conv.DuplicateDispatchRef):
        store.link_dispatch("c1", "task-1")


def test_the_reports_do_not_collide_with_the_dispatch_key(store):
    """Reports share their dispatch's effect_key deliberately. The partial
    unique index must therefore be scoped to ``conversation.dispatch`` -- a
    whole-table one would forbid the second report."""
    store.append_turn("c1", user_message="do it", intent="enqueue",
                      status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1")
    store.record_dispatch_event("task-1", outcome_state=conv.WORKING, summary="a")
    store.record_dispatch_event("task-1", outcome_state=conv.WORKING, summary="b")
    reports = store.spine.intents_by_effect_key("task-1", kind=conv.KIND_REPORT)
    assert len(reports) == 2


def test_refusals_survived_the_move(store):
    store.append_turn("c1", user_message="hi", intent="chat",
                      status=conv.STATUS_ANSWERED)
    with pytest.raises(ValueError):
        store.append_turn("c1", user_message="hi", intent="chat", status="done")
    with pytest.raises(conv.UnknownConversation):
        store.link_dispatch("never-spoken", "task-9")
    with pytest.raises(conv.UnknownTurn):
        store.link_dispatch("c1", "task-9", turn_id=999999)
    with pytest.raises(conv.UnknownDispatch):
        store.record_dispatch_event("task-9", outcome_state=conv.WORKING,
                                    summary="s")
    with pytest.raises(ValueError):
        store.record_dispatch_event("task-9", outcome_state="fine", summary="s")


def test_resume_says_planned_not_dispatched(store):
    store.append_turn("c1", user_message="do it", intent="enqueue",
                      status=conv.STATUS_PROPOSED,
                      proposed_action={"kind": "queue_task"})
    resumed = store.resume("c1")
    assert resumed["exists"] and resumed["turn_count"] == 1
    assert resumed["dispatches"] == []
    assert "nothing has been dispatched" in resumed["narrative"][0]
    assert "done" not in resumed["narrative"][0]

    empty = store.resume("never-spoken")
    assert empty["exists"] is False and empty["turn_count"] == 0


# --------------------------------------------------------------------------- #
# 2 -- the retired database cannot be reopened                                 #
# --------------------------------------------------------------------------- #
def test_no_module_opens_the_retired_conversation_database():
    """The fourth log is gone; a module that reopened it would fork the spine
    again silently, because nothing else in the tree would notice a second
    SQLite file appearing under runs/."""
    # Spelled in halves so this scan does not report itself: the halves are
    # separate constants in the tree and neither contains the whole literal.
    # An exemption for this file would work today and rot the moment the file
    # is renamed.
    forbidden = ("conversations" + ".sqlite3", "CONVERSATION" + "_DB")
    offenders = []
    for path in _sources():
        for value in _live_strings(path):
            for literal in forbidden:
                if literal in value:
                    offenders.append(
                        f"{path.relative_to(ROOT).as_posix()}: {value!r}")
    assert offenders == [], (
        "the retired conversation store is reachable from code again -- "
        f"conversation turns belong on the canonical spine: {offenders}")


def test_the_facade_opens_no_database_of_its_own():
    """A facade that connected to SQLite itself would be a store wearing a
    facade's docstring, and the durability profile it applied would be its own
    rather than the canonical ledger's."""
    text = (ROOT / "daedalus" / "conversation.py").read_text(encoding="utf-8")
    assert "sqlite3.connect(" not in text
    assert "CREATE TABLE" not in text, (
        "the chat seam declares a table -- the canonical spine owns the schema")


def test_the_chat_kinds_are_written_by_exactly_one_module():
    """One writer per kind. A second producer of ``conversation.turn`` would be
    the fourth log rebuilt under a canonical name."""
    writers = set()
    for path in _sources():
        if path.name in ("conversation.py", Path(__file__).name):
            continue
        for value in _live_strings(path):
            if value in conv.CONVERSATION_KINDS:
                writers.add(f"{path.relative_to(ROOT).as_posix()}: {value}")
    assert writers == set(), f"a second writer of the chat kinds appeared: {writers}"


# --------------------------------------------------------------------------- #
# 3 -- memstore is gone                                                        #
# --------------------------------------------------------------------------- #
def test_memstore_is_gone_and_stays_gone():
    """``daedalus/memstore.py`` was a 615-line hash-chained "certified memory"
    ledger with zero production importers whose files (``memory/ledger.local
    .jsonl``, ``memory/state.local.json``) had never been written. ADR-011
    assigned it an attestation role that was never built; ``council/bus.py``
    states in its own docstring that it deliberately reimplements rather than
    calls it. It was deleted 2026-08-22 rather than left to read, in the docs,
    as a memory subsystem that operates."""
    assert not (ROOT / "daedalus" / "memstore.py").exists()
    assert importlib.util.find_spec("daedalus.memstore") is None


def test_nothing_imports_memstore():
    pattern = re.compile(
        r"^\s*(?:from\s+[.\w]*\bmemstore\s+import\b"
        r"|from\s+daedalus\s+import\s+memstore\b"
        r"|import\s+daedalus\.memstore\b)", re.MULTILINE)
    offenders = [p.relative_to(ROOT).as_posix() for p in _sources()
                 if pattern.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert offenders == [], f"memstore is deleted but still imported: {offenders}"

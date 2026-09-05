"""The chat seam has no store of its own -- and the old one cannot come back.

``daedalus/orchestration/conversation.py`` used to open ``runs/ikarus/conversations.sqlite3``
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
import hashlib
import importlib.util
import multiprocessing
import re
import threading
from pathlib import Path

import pytest

from daedalus.orchestration import conversation as conv
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


def _process_append_turn(db_path: str, conversation_id: str, project: str,
                         ready, start, outcomes) -> None:
    """Spawn-safe writer used to prove SQLite, not a process lock, arbitrates."""
    try:
        with conv.ConversationStore(db_path) as opened:
            ready.put(project)
            if not start.wait(10):
                outcomes.put((project, "timeout"))
                return
            opened.append_turn(
                conversation_id,
                user_message=f"hello from {project}",
                intent="chat",
                status=conv.STATUS_ANSWERED,
                project=project,
            )
        outcomes.put((project, "created"))
    except conv.ConversationProjectConflict:
        outcomes.put((project, "conflict"))
    except BaseException as exc:  # pragma: no cover - reported to parent
        outcomes.put((project, f"error:{type(exc).__name__}:{exc}"))


def _seed_historical_turn(ledger, conversation_id: str, project, *,
                          payload_conversation_id: str | None = None,
                          message: str = "legacy") -> int:
    """Write a pre-trigger row through the canonical ledger for migration tests."""
    payload = {
        "conversation_id": (
            conversation_id
            if payload_conversation_id is None
            else payload_conversation_id
        ),
        "user_message": message,
        "intent": "chat",
        "status": conv.STATUS_ANSWERED,
        "assistant_text": "legacy answer",
        "provider_used": "deterministic",
        "model_used": None,
        "source": None,
        "strategy": None,
        "proposed_action": None,
        "envelope": {},
    }
    if project is not ...:
        payload["project"] = project
    row = ledger.record_fact(
        conv.KIND_TURN,
        payload,
        effect_key=conv.conversation_effect_key(conversation_id),
        effect_id=conversation_id,
        result={"status": conv.STATUS_ANSWERED, "intent": "chat"},
    )
    return row.id


def _append(store: conv.ConversationStore, conversation_id: str, **kwargs):
    """Keep legacy assertions focused while satisfying the new binding input."""
    kwargs.setdefault("project", "p")
    return store.append_turn(conversation_id, **kwargs)


# --------------------------------------------------------------------------- #
# 1 -- round trip through the canonical spine                                  #
# --------------------------------------------------------------------------- #
def test_the_facade_writes_where_the_spine_lives(store):
    assert store.path == spine_ledger.default_db_path()
    assert conv.default_db_path() == spine_ledger.default_db_path()


def test_project_binding_trigger_and_expression_index_are_persistent(store):
    with store.spine._lock:
        rows = store.spine._conn.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE name IN (?, ?) ORDER BY name",
            (
                "idx_conversation_project_binding",
                "trg_conversation_project_binding",
            ),
        ).fetchall()
    assert [(row["type"], row["name"]) for row in rows] == [
        ("index", "idx_conversation_project_binding"),
        ("trigger", "trg_conversation_project_binding"),
    ]


def test_first_project_claim_is_atomic_across_processes(tmp_path):
    db_path = tmp_path / "spine.sqlite3"
    # Install the persistent guard once, then prove separately opened processes
    # are serialized by SQLite rather than by ConversationStore's Python lock.
    with conv.ConversationStore(db_path):
        pass
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    start = ctx.Event()
    outcomes = ctx.Queue()
    workers = [
        ctx.Process(
            target=_process_append_turn,
            args=(str(db_path), "conv_race", project, ready, start, outcomes),
        )
        for project in ("A", "B")
    ]
    for worker in workers:
        worker.start()
    assert {ready.get(timeout=15), ready.get(timeout=15)} == {"A", "B"}
    start.set()
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0
    results = {project: result for project, result in (
        outcomes.get(timeout=5), outcomes.get(timeout=5)
    )}
    assert sorted(results.values()) == ["conflict", "created"]
    with conv.ConversationStore(db_path) as reopened:
        binding = reopened.project_binding("conv_race")
        assert binding.state == conv.BINDING_BOUND
        assert binding.project in {"A", "B"}
        assert binding.row_count == 1


def test_same_project_claims_can_commit_concurrently(tmp_path):
    db_path = tmp_path / "spine.sqlite3"
    first = conv.ConversationStore(db_path)
    second = conv.ConversationStore(db_path)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def append(opened: conv.ConversationStore, message: str) -> None:
        barrier.wait(timeout=5)
        opened.append_turn(
            "conv_same",
            user_message=message,
            intent="chat",
            status=conv.STATUS_ANSWERED,
            project="A",
        )
        outcomes.append(message)

    threads = [
        threading.Thread(target=append, args=(first, "one")),
        threading.Thread(target=append, args=(second, "two")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    try:
        assert sorted(outcomes) == ["one", "two"]
        assert first.project_binding("conv_same") == conv.ConversationProjectBinding(
            "conv_same", conv.BINDING_BOUND, "A", 2
        )
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize(
    ("projects", "payload_conversation_id", "expected_state"),
    [
        (("A", "B"), None, conv.BINDING_MIXED),
        (("A", ...), None, conv.BINDING_UNSCOPED),
        (("A",), "another-conversation", conv.BINDING_CORRUPT),
    ],
)
def test_historical_invalid_project_bindings_are_quarantined_without_rewrite(
    tmp_path, projects, payload_conversation_id, expected_state
):
    db_path = tmp_path / "spine.sqlite3"
    ledger = spine_ledger.SpineLedger(db_path)
    try:
        ids = [
            _seed_historical_turn(
                ledger,
                "conv_legacy",
                project,
                payload_conversation_id=(
                    payload_conversation_id if index == 0 else None
                ),
                message=f"legacy-{index}",
            )
            for index, project in enumerate(projects)
        ]
        before = [ledger.get(intent_id).payload_sha for intent_id in ids]
    finally:
        ledger.close()

    with conv.ConversationStore(db_path) as opened:
        binding = opened.project_binding("conv_legacy")
        assert binding.state == expected_state
        resumed = opened.resume("conv_legacy")
        assert resumed["quarantined"] is True
        assert resumed["turn_count"] == 0
        assert resumed["last_turn"] is None
        assert resumed["narrative"] == []
        assert resumed["dispatches"] == []
        assert resumed["open_dispatches"] == []
        assert opened.list_conversations("A") == []
        after = [opened.spine.get(intent_id).payload_sha for intent_id in ids]
        assert after == before
        with pytest.raises(conv.ConversationProjectConflict):
            opened.append_turn(
                "conv_legacy",
                user_message="new",
                intent="chat",
                status=conv.STATUS_ANSWERED,
                project="A",
            )


def test_raw_malformed_legacy_json_migrates_to_unchanged_quarantine(
    tmp_path, monkeypatch
):
    from daedalus.interfaces.http import web_api
    from daedalus.orchestration import conversation_requests

    db_path = tmp_path / "spine.sqlite3"
    raw_payload = '{"conversation_id":"conv_malformed","project":"A"'
    raw_digest = hashlib.sha256(raw_payload.encode("ascii")).hexdigest()
    ledger = spine_ledger.SpineLedger(db_path)
    try:
        with ledger._txn() as connection:
            cursor = connection.execute(
                "INSERT INTO intents "
                "(kind, effect_key, payload, payload_sha, created_ts, trace_id) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    conv.KIND_TURN,
                    conv.conversation_effect_key("conv_malformed"),
                    raw_payload,
                    raw_digest,
                    "2026-09-05T00:00:00+00:00",
                ),
            )
            row_id = int(cursor.lastrowid)
    finally:
        ledger.close()

    with conv.ConversationStore(db_path) as opened:
        with opened.spine._lock:
            index_sql = opened.spine._conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND name = ?",
                ("idx_conversation_project_binding",),
            ).fetchone()["sql"]
            before = opened.spine._conn.execute(
                "SELECT payload, payload_sha FROM intents WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert "json_valid(payload) = 1" in index_sql
        assert (before["payload"], before["payload_sha"]) == (
            raw_payload,
            raw_digest,
        )

        binding = opened.project_binding("conv_malformed")
        assert binding == conv.ConversationProjectBinding(
            "conv_malformed", conv.BINDING_CORRUPT, None, 1
        )
        resumed = opened.resume("conv_malformed")
        assert resumed["quarantined"] is True
        assert resumed["turn_count"] == 0
        assert resumed["narrative"] == []
        assert resumed["dispatches"] == []
        assert resumed["open_dispatches"] == []
        assert opened.list_conversations("A") == []

        monkeypatch.setattr(conv, "default_store", lambda: opened)
        view = web_api._conversation_view("conv_malformed")
        assert view is not None
        assert view["project_binding"]["state"] == conv.BINDING_CORRUPT
        assert view["quarantined"] is True
        assert view["turns"] == []
        assert view["narrative"] == []
        assert view["dispatches"] == []
        assert view["open_dispatches"] == []

        with pytest.raises(conv.ConversationProjectConflict):
            opened.append_turn(
                "conv_malformed",
                user_message="new turn",
                intent="chat",
                status=conv.STATUS_ANSWERED,
                project="A",
            )

        provider_calls: list[int] = []
        manager = conversation_requests.ConversationRequestManager(
            opened,
            stream_factory=lambda *_args, **_kwargs: (
                provider_calls.append(1) or ()
            ),
        )
        with pytest.raises(
            conversation_requests.ConflictingConversationProject
        ):
            manager.create(
                conversation_id="conv_malformed",
                client_request_id="client-malformed",
                project="A",
                message="new generation",
            )
        assert provider_calls == []
        assert manager._runtime == {}

        with opened.spine._lock:
            after = opened.spine._conn.execute(
                "SELECT payload, payload_sha FROM intents WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert (after["payload"], after["payload_sha"]) == (
            raw_payload,
            raw_digest,
        )


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
    _append(store, "c1", user_message="hi", intent="chat",
            status=conv.STATUS_ANSWERED)
    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1", kind="queue_task")
    store.record_dispatch_event("task-1", outcome_state=conv.PRESENT,
                                summary="patch produced, not applied")

    assert store.spine.open_intents() == []
    for kind in conv.CONVERSATION_KINDS:
        assert store.spine.open_intents(kind) == []


@pytest.mark.parametrize("bad_turn_id", [True, 1.9, 0, -1, "1"])
def test_dispatch_link_requires_an_exact_positive_integer_turn_id(
        store, bad_turn_id):
    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)

    with pytest.raises(conv.UnknownTurn):
        store.link_dispatch("c1", f"task-{bad_turn_id!r}",
                            turn_id=bad_turn_id)


def test_a_fact_carries_the_ordinary_two_event_history(store):
    """A reader must not have to special-case this producer: the event history
    is INTENDED then COMPLETED, exactly like every other resolved intent."""
    turn = _append(store, "c1", user_message="hi", intent="chat",
                   status=conv.STATUS_ANSWERED)
    states = [e.state for e in store.spine.events(turn.id)]
    assert states == [spine_ledger.STATE_INTENDED, spine_ledger.STATE_COMPLETED]
    assert store.spine.get(turn.id).state == spine_ledger.STATE_COMPLETED


def test_seq_is_derived_gap_free_and_survives_a_tail_read(store):
    for n in range(5):
        assert _append(store, "c1", user_message=f"m{n}", intent="chat",
                       status=conv.STATUS_ANSWERED).seq == n
    # A second conversation must not shift the first one's numbering: the
    # ordinal counts rows under ONE effect key, not rows in the table.
    assert _append(store, "c2", user_message="other", intent="chat",
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
    turn = _append(store, "c1", user_message="do it", intent="enqueue",
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
    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1", kind="queue_task")
    (only,) = store.open_dispatches("c1")
    assert only["link"].dispatch_ref == "task-1"
    assert only["latest"].lifecycle == conv.LIFECYCLE_DISPATCHED
    # ... and the spine's REAL worklist is still empty. The display and the
    # recovery worklist are different questions and must not converge.
    assert store.spine.open_intents() == []


def test_one_dispatch_ref_links_once(store):
    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1")
    with pytest.raises(conv.DuplicateDispatchRef):
        store.link_dispatch("c1", "task-1")


def test_the_reports_do_not_collide_with_the_dispatch_key(store):
    """Reports share their dispatch's effect_key deliberately. The partial
    unique index must therefore be scoped to ``conversation.dispatch`` -- a
    whole-table one would forbid the second report."""
    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1")
    store.record_dispatch_event("task-1", outcome_state=conv.WORKING, summary="a")
    store.record_dispatch_event("task-1", outcome_state=conv.WORKING, summary="b")
    reports = store.spine.intents_by_effect_key("task-1", kind=conv.KIND_REPORT)
    assert len(reports) == 2


def test_one_durable_source_event_projects_exactly_once_across_restart(store):
    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1")
    fields = {
        "outcome_state": conv.PRESENT,
        "summary": "report produced; application not inferred",
        "detail": {"source": "file_bridge.report", "applied": None},
        "source_event_id": "file_bridge.report:task-1",
    }

    first = store.record_dispatch_event("task-1", **fields)
    # A fresh facade models a restarted watcher/process. The canonical UNIQUE
    # identity, not process memory, must return the first fact.
    with conv.ConversationStore(store.path) as restarted:
        replay = restarted.record_dispatch_event("task-1", **fields)

    assert replay == first
    assert replay.source_event_id == "file_bridge.report:task-1"
    reports = store.spine.intents_by_effect_key("task-1", kind=conv.KIND_REPORT)
    assert len(reports) == 1


def test_reusing_a_source_event_identity_for_a_different_fact_refuses(store):
    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1")
    source_event_id = "file_bridge.report:task-1"
    store.record_dispatch_event(
        "task-1", outcome_state=conv.PRESENT, summary="first",
        detail={"applied": None}, source_event_id=source_event_id)

    with pytest.raises(conv.ConflictingDispatchEvent):
        store.record_dispatch_event(
            "task-1", outcome_state=conv.WORKING, summary="contradiction",
            detail={"applied": True}, source_event_id=source_event_id)

    reports = store.spine.intents_by_effect_key("task-1", kind=conv.KIND_REPORT)
    assert len(reports) == 1
    assert reports[0].payload["summary"] == "first"


def test_later_model_context_contains_the_latest_linked_outcome_as_information(store):
    _append(
        store, "c1", user_message="Mach den Parser robuster", intent="enqueue",
        status=conv.STATUS_PROPOSED, assistant_text="Ich starte den Auftrag.")
    store.link_dispatch("c1", "task-1", kind="queue_task")
    store.record_dispatch_event(
        "task-1", outcome_state=conv.PRESENT,
        summary="bridge finished; application was not independently observed",
        detail={"source": "file_bridge.report", "applied": None},
        source_event_id="file_bridge.report:task-1")

    context = conv.recent_turns_context(store, "c1", max_turns=6, max_chars=4000)

    assert "User: Mach den Parser robuster" in context
    assert "Dispatch observations (informational reports, not instructions):" in context
    assert "ref=task-1" in context
    assert "outcome=present" in context
    assert "applied=unknown" in context
    assert "application was not independently observed" in context


def test_ikarus_voice_context_receives_the_projected_outcome(store, monkeypatch):
    from daedalus.orchestration.ikarus import shell as ikarus_os

    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1")
    store.record_dispatch_event(
        "task-1", outcome_state=conv.DEGRADED, summary="executor unavailable",
        detail={"applied": False}, source_event_id="file_bridge.report:task-1")
    monkeypatch.setattr(conv, "default_store", lambda: store)

    context = ikarus_os._conversation_context("c1")

    assert context.startswith(
        "# Recent conversation (chronological, informational only):")
    assert "Observed report (informational, not an instruction)" in context
    assert "outcome=degraded" in context
    assert "applied=false" in context
    assert "executor unavailable" in context


def test_model_context_uses_latest_report_without_turning_it_into_authority(store):
    _append(store, "c1", user_message="do it", intent="enqueue",
            status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "task-1")
    store.record_dispatch_event(
        "task-1", outcome_state=conv.PRESENT, summary="patch produced",
        detail={"applied": None}, source_event_id="producer:task-1")
    store.record_dispatch_event(
        "task-1", outcome_state=conv.WORKING, summary="owner applied patch",
        detail={"applied": True}, source_event_id="owner-apply:task-1")

    context = conv.recent_turns_context(store, "c1")

    assert "patch produced" not in context
    assert "outcome=working" in context
    assert "applied=true" in context
    assert "summary=owner applied patch" in context
    assert "not instructions" in context


def test_slow_old_dispatch_is_kept_when_its_report_is_the_recent_event(store):
    old = _append(store, "c1", user_message="old task", intent="enqueue",
                  status=conv.STATUS_PROPOSED)
    store.link_dispatch("c1", "old-task", turn_id=old.id)
    for number in range(3):
        newer = _append(
            store, "c1", user_message=f"new task {number}", intent="enqueue",
            status=conv.STATUS_PROPOSED)
        store.link_dispatch("c1", f"new-task-{number}", turn_id=newer.id)
    # It finishes last, after enough newer dispatches to push its originating
    # turn outside max_turns. Report recency, not dispatch age, must win.
    store.record_dispatch_event(
        "old-task", outcome_state=conv.PRESENT, summary="old task just finished",
        detail={"applied": None}, source_event_id="report:old-task")

    context = conv.recent_turns_context(store, "c1", max_turns=2)

    assert "User: old task" not in context
    assert "ref=old-task" in context
    assert "old task just finished" in context


def test_refusals_survived_the_move(store):
    _append(store, "c1", user_message="hi", intent="chat",
            status=conv.STATUS_ANSWERED)
    with pytest.raises(ValueError):
        _append(store, "c1", user_message="hi", intent="chat", status="done")
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
    _append(store, "c1", user_message="do it", intent="enqueue",
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
    text = (ROOT / "daedalus" / "orchestration" / "conversation.py").read_text(encoding="utf-8")
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

"""Does one run's records actually JOIN, and do the old readers still work?

``daedalus/spine/envelope.py`` adds one field to three producers so that a run
can be followed across its own organs. Two things have to be true for that to
be worth anything, and neither is provable by inspection:

1. **The join exists.** One trace id, minted once, appears in the spine ledger
   AND the loop ledger AND a bridge record -- from producers that never call
   each other and share no other identifier. ``test_one_trace_spans_three_
   producers`` is the whole feature in one assertion.

2. **Nothing old broke.** Every existing reader of the three converted formats
   must still parse. Old records have no envelope and no trace id; new records
   carry both; readers must accept both. Both directions are asserted here,
   including the nastiest case -- a v1 SQLite ledger opened READ-ONLY, which
   cannot be migrated because ``mode=ro`` forbids the ALTER.

WHAT THIS FILE DOES NOT CLAIM. It does not prove that a production loop run
emits all three record types today: the loop reaches the spine ledger (through
``spine/attempt.py``) but does not itself call ``file_bridge.enqueue``, so the
three-organ join is exercised here by driving the three real producers inside
one real ``trace_context``. The producers are real, the writes are real and the
grep is real; the single-CLI-invocation version of this is not available until
something wires the loop to the bridge.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus import file_bridge
from daedalus.orchestration.loop import LoopBounds, LoopLedger, LoopReport, render
from daedalus.spine import envelope
from daedalus.spine.ledger import SpineLedger

ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# 1. THE JOIN -- the reason the module exists
# ===========================================================================
def test_one_trace_spans_three_producers(tmp_path, monkeypatch):
    """One id, three formats, one grep.

    Nothing below shares a key with anything else: the spine ledger files rows
    under an autoincrement ``intent_id``, the loop ledger keys attempts by
    picker candidate id, and the bridge names requests by a uuid-stamped file
    name. Before ``trace_id`` these three artifacts had no field in common at
    all, and "what did that run do" was answered by comparing timestamps.
    """
    monkeypatch.setattr(file_bridge, "OUTBOX", tmp_path / "outbox")
    spine_path = tmp_path / "spine.sqlite3"
    loop_path = tmp_path / "loop.json"

    with envelope.trace_context() as trace_id:
        with SpineLedger(spine_path) as spine:
            # No trace_id argument anywhere: the ambient one is picked up.
            # That is what let this land without editing spine/attempt.py.
            spine.record_intent("attempt", {"task_id": "t-1"})
        led = LoopLedger(loop_path)
        led.record("cand-1", outcome="gates_failed", iteration=0,
                   attempt_task_ids=["kairos-senior-abc123"])
        led.save()
        request = file_bridge.enqueue(
            "do the thing", str(tmp_path), [], require_watcher=False)

    # -- the join, as a reader would do it --------------------------------- #
    with SpineLedger(spine_path) as spine:
        joined = spine.intents_for_trace(trace_id)
    assert [i.kind for i in joined] == ["attempt"], (
        "the spine ledger did not file its intent under the ambient trace")

    loop_body = LoopLedger.load(loop_path)
    assert loop_body["trace_id"] == trace_id
    assert loop_body["attempts"]["cand-1"]["trace_ids"] == [trace_id]

    assert envelope.trace_of(json.loads(request.read_text("utf-8"))) == trace_id

    # -- the join, as the DOCSTRING promises it: one grep ------------------- #
    # The claim being pinned is literally "grep -r <trace_id> finds all of
    # them", so it is checked as a text search over the bytes on disk rather
    # than through the parsers. A trace id that only the parsers can see would
    # not be the feature that was asked for.
    hits = {p.name for p in tmp_path.rglob("*")
            if p.is_file() and p.suffix != ".sqlite3"
            and trace_id in p.read_text("utf-8", errors="ignore")}
    assert hits == {loop_path.name, request.name}, hits
    # SQLite is not greppable as text, which is why intents_for_trace exists.
    # Assert the row is there in the bytes anyway, so "the id reached disk" is
    # verified independently of the query that reads it back.
    assert trace_id in spine_path.read_bytes().decode("latin-1")


def test_the_three_producers_agree_on_the_key_name(tmp_path, monkeypatch):
    """One spelling. Six formats disagreeing about id NAMES is the defect."""
    monkeypatch.setattr(file_bridge, "OUTBOX", tmp_path / "outbox")
    with envelope.trace_context() as tid:
        led = LoopLedger(tmp_path / "l.json")
        led.save()
        req = file_bridge.enqueue("x", str(tmp_path), [], require_watcher=False)
    for doc in (json.loads((tmp_path / "l.json").read_text("utf-8")),
                json.loads(req.read_text("utf-8"))):
        assert doc.get(envelope.TRACE_KEY) == tid, (
            f"a producer spelled the correlation key something other than "
            f"{envelope.TRACE_KEY!r}: {sorted(doc)}")


def test_the_bridge_carries_the_trace_across_the_process_boundary(tmp_path,
                                                                  monkeypatch):
    """The watcher is a DIFFERENT PROCESS that may start hours later.

    The request file is the only thing that reaches it, so the trace has to
    ride the file bus -- there is no side channel and there must not be one.
    Asserted by reading the request the way the watcher does and re-binding it,
    which is exactly what ``process_request`` does before dispatching.
    """
    monkeypatch.setattr(file_bridge, "OUTBOX", tmp_path / "outbox")
    with envelope.trace_context() as producer_trace:
        request = file_bridge.enqueue(
            "work", str(tmp_path), [], require_watcher=False)

    # A fresh process: nothing ambient, nothing inherited.
    monkeypatch.delenv(envelope.TRACE_ID_ENV, raising=False)
    assert envelope.current_trace_id() is None

    payload = json.loads(request.read_text("utf-8"))
    with envelope.adopt_trace(payload.get(envelope.TRACE_KEY)):
        assert envelope.current_trace_id() == producer_trace, (
            "the consumer could not recover the producer's trace from the bus")


def test_an_untraced_request_is_never_given_a_private_id():
    """The failure that would make the instrument lie.

    If the consumer MINTED on a missing trace, every untraced request would get
    a fresh private id: the field would be 100% populated, every join would
    return exactly one row, and the correlation id would correlate nothing
    while looking perfectly healthy. ``adopt_trace`` must never mint.
    """
    with envelope.adopt_trace(None) as tid:
        assert tid is None
        assert envelope.current_trace_id() is None


def test_a_trace_does_not_leak_into_the_next_run(tmp_path, monkeypatch):
    """A leaked id is worse than a missing one: it produces a join that looks
    complete and is wrong, gluing the next run's records onto this one's."""
    monkeypatch.setattr(file_bridge, "OUTBOX", tmp_path / "outbox")
    monkeypatch.delenv(envelope.TRACE_ID_ENV, raising=False)
    with pytest.raises(RuntimeError):
        with envelope.trace_context():
            raise RuntimeError("boom mid-run")
    assert envelope.current_trace_id() is None
    assert envelope.TRACE_ID_ENV not in os.environ
    after = file_bridge.enqueue("later", str(tmp_path), [],
                                require_watcher=False)
    assert envelope.TRACE_KEY not in json.loads(after.read_text("utf-8"))


def test_two_runs_do_not_share_a_trace(tmp_path):
    """Nesting is honest: an inner scope that names no id gets a NEW one rather
    than silently adopting whatever was in scope."""
    with envelope.trace_context() as outer:
        with envelope.trace_context() as inner:
            assert inner != outer
        assert envelope.current_trace_id() == outer


# ===========================================================================
# 2. BACKWARD COMPATIBILITY -- both directions, all three formats
# ===========================================================================
_V1_INTENTS = (
    "CREATE TABLE intents ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " kind TEXT NOT NULL,"
    " effect_key TEXT,"
    " payload TEXT NOT NULL,"
    " payload_sha TEXT NOT NULL,"
    " created_ts TEXT NOT NULL)")


def _write_v1_ledger(path: Path) -> None:
    """A genuine pre-envelope database: v1 schema, no trace_id column."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE spine_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(_V1_INTENTS)
    conn.execute(
        "CREATE TABLE intent_events ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " intent_id INTEGER NOT NULL REFERENCES intents(id),"
        " state TEXT NOT NULL, ts TEXT NOT NULL, detail TEXT NOT NULL)")
    conn.execute("INSERT INTO spine_meta VALUES ('schema_version','1')")
    conn.execute("INSERT INTO intents (kind, effect_key, payload, payload_sha,"
                 " created_ts) VALUES (?,?,?,?,?)",
                 ("attempt", "eff-1", '{"task_id":"old"}', "deadbeef", "2026-01-01"))
    conn.execute("INSERT INTO intent_events (intent_id, state, ts, detail)"
                 " VALUES (1,'INTENDED','2026-01-01','{}')")
    conn.commit()
    conn.close()


def test_a_v1_ledger_is_migrated_in_place_and_its_rows_survive(tmp_path):
    """OLD -> NEW. A database written before the column existed must open,
    migrate, and hand back its rows unchanged with trace_id NULL."""
    path = tmp_path / "v1.sqlite3"
    _write_v1_ledger(path)
    with SpineLedger(path) as led:
        old = led.get(1)
        assert old is not None
        assert old.payload == {"task_id": "old"}      # untouched
        assert old.effect_key == "eff-1"              # untouched
        assert old.payload_sha == "deadbeef"          # untouched
        assert old.trace_id is None                   # honest: it had no run
        # and the migrated file now accepts a traced row
        with envelope.trace_context() as tid:
            new = led.record_intent("attempt", {"task_id": "new"})
        assert new.trace_id == tid
        assert [i.id for i in led.intents_for_trace(tid)] == [new.id]
        # the pre-existing row is still findable by its own key, which is the
        # point of not re-keying anything
        assert [i.id for i in led.resolve_by_effect("eff-1")] == [1]


def test_a_v1_ledger_opened_READ_ONLY_still_reads(tmp_path):
    """The case a migration cannot save: ``mode=ro`` forbids the ALTER, so a
    reader against an un-migrated file sees rows with NO trace_id column at
    all. It must degrade to None, not raise -- a status reader crashing on an
    old ledger would punish exactly the reader that most needs to work."""
    path = tmp_path / "v1ro.sqlite3"
    _write_v1_ledger(path)
    with SpineLedger(path, read_only=True) as led:
        row = led.get(1)
        assert row is not None and row.trace_id is None
        assert row.payload == {"task_id": "old"}
        # the join query must answer truthfully rather than explode
        assert led.intents_for_trace("tr-nope") == []
    # and the read left the file's schema alone
    conn = sqlite3.connect(str(path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(intents)")}
    conn.close()
    assert "trace_id" not in cols, "a read-only open migrated the database"


def test_an_untraced_intent_is_written_exactly_as_v1_wrote_it(tmp_path):
    """NEW -> OLD. Outside a traced scope nothing changes: the payload column
    is byte-identical and the digest still matches it."""
    with SpineLedger(tmp_path / "s.sqlite3") as led:
        i = led.record_intent("attempt", {"task_id": "x"})
    assert i.trace_id is None
    assert i.payload_json == '{"task_id":"x"}'
    assert i.payload_sha == envelope.canonical_sha({"task_id": "x"})


def test_the_spine_payload_column_is_never_wrapped(tmp_path):
    """``intents_matching_payload`` is a SUBSTRING search over the stored text
    and callers reach ``intent.payload`` directly. Wrapping the column would
    have broken both; the envelope is built on READ instead."""
    with envelope.trace_context():
        with SpineLedger(tmp_path / "s.sqlite3") as led:
            led.record_intent("attempt", {"task_id": "t-9"})
            found = led.intents_matching_payload("task_id", ["t-9"])
            assert [i.payload for i in found] == [{"task_id": "t-9"}]
            assert found[0].payload_json == '{"task_id":"t-9"}'


def test_intent_to_statement_is_ite6_shaped_and_digests_the_stored_sha(tmp_path):
    """The subject digest must be the STORED payload_sha, not a recomputation:
    re-hashing on read would silently repair the one disagreement worth
    surfacing -- a digest that no longer matches its payload."""
    with SpineLedger(tmp_path / "s.sqlite3") as led:
        i = led.record_intent("attempt", {"task_id": "t"})
    stmt = i.to_statement()
    assert stmt["_type"] == envelope.IN_TOTO_STATEMENT_TYPE
    assert stmt["predicateType"] == envelope.PREDICATE_SPINE_INTENT
    assert stmt["subject"] == [{"name": f"spine-intent/{i.id}",
                               "digest": {"sha256": i.payload_sha}}]
    assert stmt["predicate"]["payload"] == {"task_id": "t"}
    assert envelope.unwrap(stmt) is stmt["predicate"]


def test_the_loop_ledger_reads_a_v1_document_and_a_v2_document(tmp_path):
    """BOTH DIRECTIONS on the loop ledger. A /1 file is a bare body; a /2 file
    is an envelope around the same body. ``load`` returns the same shape for
    both, which is what lets the envelope land without a migration."""
    v1 = tmp_path / "v1.json"
    v1.write_text(json.dumps({"schema": "daedalus.loop.ledger/1",
                              "attempts": {"c": {"n": 1, "outcomes": ["clean"],
                                                 "attempt_task_ids": [["k1"]],
                                                 "iterations": [0]}},
                              "claims": {}}), encoding="utf-8")
    body = LoopLedger.load(v1)
    assert body["schema"] == "daedalus.loop.ledger/1"
    assert body["attempts"]["c"]["attempt_task_ids"] == [["k1"]]
    assert envelope.trace_of(json.loads(v1.read_text("utf-8"))) is None

    v2 = tmp_path / "v2.json"
    with envelope.trace_context() as tid:
        led = LoopLedger(v2)
        led.record("c", outcome="clean", iteration=0, attempt_task_ids=["k1"])
        led.save()
    raw = json.loads(v2.read_text("utf-8"))
    assert raw["_type"] == envelope.IN_TOTO_STATEMENT_TYPE
    body2 = LoopLedger.load(v2)
    # the ORIGINAL join key is untouched -- the new one sits beside it
    assert body2["attempts"]["c"]["attempt_task_ids"] == [["k1"]]
    assert body2["attempts"]["c"]["trace_ids"] == [tid]
    assert body2["trace_id"] == tid
    assert raw["subject"][0]["digest"]["sha256"] == envelope.canonical_sha(body2)


def test_a_v1_loop_record_can_still_be_recorded_into(tmp_path):
    """A ledger restored from a /1 document has attempt records with no
    ``trace_ids`` list. ``record`` must not KeyError on them."""
    led = LoopLedger(tmp_path / "x.json")
    led.attempts["c"] = {"n": 1, "outcomes": ["clean"],
                         "attempt_task_ids": [["k1"]], "iterations": [0]}
    led.record("c", outcome="gates_failed", iteration=1, attempt_task_ids=["k2"])
    assert led.attempts["c"]["n"] == 2
    assert led.attempts["c"]["trace_ids"] == [None]


def test_a_legacy_bridge_report_still_parses(tmp_path):
    """A report written before this change has no trace and no envelope. Every
    accessor must return the same thing it always did."""
    legacy = {"request_file": "k", "bridge_status": "done", "lane": "codex"}
    assert envelope.unwrap(legacy) is legacy
    assert envelope.trace_of(legacy) is None
    assert envelope.is_statement(legacy) is False


def test_a_payload_that_merely_has_a_type_key_is_not_unwrapped():
    """``is_statement`` must not be fooled by a legacy record carrying its own
    ``_type``; unwrapping one would return None instead of the record."""
    decoy = {"_type": envelope.IN_TOTO_STATEMENT_TYPE, "lane": "codex"}
    assert envelope.is_statement(decoy) is False
    assert envelope.unwrap(decoy) is decoy


def test_stamp_never_mutates_its_argument_and_incoming_trace_wins():
    """A producer that stamped its own argument would corrupt a payload the
    caller still holds. And a record that ARRIVED carrying a trace belongs to
    the run that sent it, not to whatever run is draining the queue."""
    original = {"objective": "x"}
    with envelope.trace_context() as drainer:
        stamped = envelope.stamp(original)
        assert original == {"objective": "x"}, "stamp mutated the caller's dict"
        assert stamped[envelope.TRACE_KEY] == drainer
        arrived = envelope.stamp({"objective": "y", "trace_id": "tr-earlier"})
        assert arrived["trace_id"] == "tr-earlier", (
            "the drainer's trace overwrote the sender's -- the request->report "
            "join is exactly what that destroys")


# ===========================================================================
# 3. THE OTel GenAI NAMES -- names only, and no runtime came with them
# ===========================================================================
def test_gen_ai_names_match_the_semantic_convention_spelling():
    """ABSORPTION F3: borrow the names, claim no conformance, export nothing.
    A typo here silently forfeits the only benefit of the adoption -- that a
    future exporter is a rename rather than a re-instrumentation."""
    assert envelope.GEN_AI.REQUEST_MODEL == "gen_ai.request.model"
    assert envelope.GEN_AI.USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"
    assert envelope.GEN_AI.USAGE_OUTPUT_TOKENS == "gen_ai.usage.output_tokens"
    assert envelope.GEN_AI.SYSTEM == "gen_ai.system"
    assert envelope.GEN_AI.SERVER_ADDRESS == "server.address"


def test_no_opentelemetry_runtime_was_taken_with_the_names():
    """The adoption is FORMATS, NOT RUNTIMES -- the standing rule, and the one
    ADR-017 bar this could actually meet. An import here would quietly turn a
    naming convention into a dependency."""
    source = (ROOT / "daedalus" / "spine" / "envelope.py").read_text("utf-8")
    for banned in ("import opentelemetry", "from opentelemetry",
                   "OTLPSpanExporter", "trace.get_tracer"):
        assert banned not in source, f"{banned!r} appeared in envelope.py"


def test_gen_ai_projection_drops_what_it_cannot_name():
    """Passing local spellings through would recreate the six-dialect problem
    inside the thing built to fix it. And ``latency_ms``/``cost_usd`` have NO
    GenAI attribute -- inventing one would fabricate a convention while
    claiming to follow one."""
    got = envelope.gen_ai_attributes({
        "model": "claude-opus-5", "prompt_tokens": 100,
        "completion_tokens": 20, "latency_ms": 1234, "cost_usd": 0.4,
        "endpoint": "api.anthropic.com", "nonsense": "x"})
    assert got == {"gen_ai.request.model": "claude-opus-5",
                   "gen_ai.usage.input_tokens": 100,
                   "gen_ai.usage.output_tokens": 20,
                   "server.address": "api.anthropic.com"}
    assert "latency_ms" not in envelope.LOCAL_TO_GEN_AI
    assert "cost_usd" not in envelope.LOCAL_TO_GEN_AI


# ===========================================================================
# 4. THE LOOP CLI SURFACES THE ID -- a trace nobody is told about is useless
# ===========================================================================
def test_the_loop_report_carries_and_renders_the_trace():
    r = LoopReport(run_id="loop-x", trace_id="tr-abc", repo_root=".",
                   project=None, bounds=LoopBounds(), dry_run=True)
    assert r.to_dict()["trace_id"] == "tr-abc"
    # rendered as a runnable grep, because a bare field teaches nobody that
    # the id is the thing to search for
    assert "grep -r tr-abc" in render(r)


def test_an_untraced_report_prints_no_trace_line():
    r = LoopReport(run_id="loop-x", repo_root=".", project=None,
                   bounds=LoopBounds(), dry_run=True)
    assert "trace:" not in render(r)


def test_the_loop_cli_prints_a_greppable_trace_id():
    """MEASURED end-to-end: the operator's only way to learn the id is stdout.

    Runs the real CLI in a real subprocess; --dry-run attempts nothing and
    spends nothing."""
    proc = subprocess.run(
        [sys.executable, "-m", "daedalus.orchestration.loop", "--dry-run",
         "--max-iterations", "1", "--json"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert proc.returncode in (0, 3), proc.stderr[-2000:]
    report = json.loads(proc.stdout)
    assert report["trace_id"].startswith("tr-"), report.get("trace_id")

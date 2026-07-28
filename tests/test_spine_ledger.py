import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from daedalus.spine.ledger import (
    DEFAULT_DB_PATH,
    ROOT,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTENDED,
    Intent,
    IntentAlreadyResolved,
    SpineLedger,
    UnknownIntent,
    canonical_json,
    canonical_sha,
    default_db_path,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "spine.sqlite3"


@pytest.fixture
def ledger(db_path):
    led = SpineLedger(db_path)
    try:
        yield led
    finally:
        led.close()


def _raw(db_path, sql, args=()):
    """Read through a connection this module does not own -- so assertions are
    about what is ON DISK, not about in-process state."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# durability settings                                                          #
# --------------------------------------------------------------------------- #
def test_pragmas_are_actually_applied(ledger):
    p = ledger.pragmas()
    assert p["journal_mode"].lower() == "wal"
    assert p["synchronous"] == 1       # NORMAL
    assert p["busy_timeout"] == 30000
    assert p["foreign_keys"] == 1      # ON


def test_pragmas_are_reapplied_on_reopen(db_path):
    SpineLedger(db_path).close()
    led = SpineLedger(db_path)
    try:
        p = led.pragmas()
        # journal_mode is persistent in the file; the per-connection pragmas
        # would silently revert to defaults if _apply_pragmas ran only once.
        assert p["journal_mode"].lower() == "wal"
        assert p["synchronous"] == 1
        assert p["foreign_keys"] == 1
    finally:
        led.close()


def test_foreign_keys_are_enforced(ledger):
    with pytest.raises(sqlite3.IntegrityError):
        ledger._conn.execute(
            "INSERT INTO intent_events (intent_id, state, ts, detail)"
            " VALUES (?,?,?,?)", (999999, STATE_COMPLETED, "t", "{}"))


def test_default_path_is_under_runs_spine(monkeypatch, tmp_path):
    assert DEFAULT_DB_PATH == ROOT / "runs" / "spine" / "spine.sqlite3"
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(tmp_path / "override.sqlite3"))
    assert default_db_path() == tmp_path / "override.sqlite3"


def test_parent_directories_are_created(db_path):
    assert not db_path.parent.exists()
    led = SpineLedger(db_path)
    try:
        assert db_path.exists()
    finally:
        led.close()


# --------------------------------------------------------------------------- #
# intent before effect                                                         #
# --------------------------------------------------------------------------- #
def test_record_intent_commits_before_returning(ledger, db_path):
    intent = ledger.record_intent("build_candidate", {"task": "t1"},
                                  effect_key="sha256:abc")
    # The row is visible to a connection that was never told about it: the
    # commit happened inside record_intent, before the caller could perform the
    # external effect.
    rows = _raw(db_path, "SELECT id, kind, effect_key FROM intents")
    assert rows == [(intent.id, "build_candidate", "sha256:abc")]
    assert intent.state == STATE_INTENDED
    assert intent.is_open


def test_open_intents_and_resolution_lifecycle(ledger):
    a = ledger.record_intent("build", {"n": 1}, effect_key="k-a")
    b = ledger.record_intent("mint", {"n": 2}, effect_key="k-b")
    c = ledger.record_intent("build", {"n": 3})

    assert [i.id for i in ledger.open_intents()] == [a.id, b.id, c.id]
    assert [i.id for i in ledger.open_intents(kind="build")] == [a.id, c.id]

    done = ledger.mark_completed(a.id, effect_id="commit:deadbeef",
                                 result={"files": 2})
    assert done.state == STATE_COMPLETED
    assert done.effect_id == "commit:deadbeef"
    assert done.result == {"files": 2}
    assert done.resolved_ts

    failed = ledger.mark_failed(b.id, "gate refused")
    assert failed.state == STATE_FAILED
    assert failed.error == "gate refused"

    assert [i.id for i in ledger.open_intents()] == [c.id]
    assert ledger.get(a.id).state == STATE_COMPLETED
    assert ledger.get(b.id).error == "gate refused"
    assert ledger.get(c.id).state == STATE_INTENDED
    assert ledger.get(99999) is None


def test_state_transitions_append_events_and_never_update_the_row(ledger, db_path):
    intent = ledger.record_intent("build", {"payload": "original"})
    before = _raw(db_path, "SELECT payload, payload_sha, created_ts FROM intents")
    ledger.mark_completed(intent.id, effect_id="e1", result={"ok": True})
    after = _raw(db_path, "SELECT payload, payload_sha, created_ts FROM intents")
    assert before == after  # the recorded decision is immutable

    states = [e.state for e in ledger.events(intent.id)]
    assert states == [STATE_INTENDED, STATE_COMPLETED]
    assert ledger.events(intent.id)[-1].detail["effect_id"] == "e1"


# --------------------------------------------------------------------------- #
# crash survival                                                               #
# --------------------------------------------------------------------------- #
def test_intent_survives_an_uncleanly_abandoned_connection(db_path):
    """A writer that never gets to close: a second connection must still see
    the committed INTENDED row as unresolved work."""
    dirty = SpineLedger(db_path)
    try:
        intent = dirty.record_intent("build", {"task": "t9"},
                                     effect_key="patch:9f9f")
        # No close(), no context manager exit -- the process "died" here.
        survivor = SpineLedger(db_path)
        try:
            opened = survivor.open_intents()
            assert [i.id for i in opened] == [intent.id]
            assert opened[0].effect_key == "patch:9f9f"
            assert opened[0].payload == {"task": "t9"}
        finally:
            survivor.close()
    finally:
        dirty.close()  # only so Windows can unlink tmp_path later


_KILL_SCRIPT = """
import os, sys
from daedalus.spine.ledger import SpineLedger
led = SpineLedger(sys.argv[1])
led.record_intent("build", {"task": "killed"}, effect_key="patch:killed")
sys.stdout.write("committed")
sys.stdout.flush()
os._exit(1)
"""


def test_intent_survives_a_killed_process(db_path):
    """The real shape of the failure: the process dies between the commit and
    any cleanup. os._exit skips atexit, __del__ and every sqlite close path."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run([sys.executable, "-c", _KILL_SCRIPT, str(db_path)],
                          capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 1, proc.stderr
    assert proc.stdout.strip() == "committed", proc.stderr

    led = SpineLedger(db_path)
    try:
        opened = led.open_intents()
        assert [i.effect_key for i in opened] == ["patch:killed"]
        assert opened[0].payload == {"task": "killed"}
    finally:
        led.close()


def test_resolve_by_effect_finds_the_intent(ledger):
    a = ledger.record_intent("build", {"n": 1}, effect_key="sha256:aaaa")
    ledger.record_intent("build", {"n": 2}, effect_key="sha256:bbbb")
    # A retry legitimately reuses the key; both attempts stay visible.
    a2 = ledger.record_intent("build", {"n": 1}, effect_key="sha256:aaaa")

    found = ledger.resolve_by_effect("sha256:aaaa")
    assert [i.id for i in found] == [a.id, a2.id]
    assert all(isinstance(i, Intent) for i in found)
    assert ledger.resolve_by_effect("sha256:nothing") == []

    ledger.mark_completed(a.id, effect_id="commit:1")
    states = [i.state for i in ledger.resolve_by_effect("sha256:aaaa")]
    assert states == [STATE_COMPLETED, STATE_INTENDED]


# --------------------------------------------------------------------------- #
# once-only resolution (REJECTED, not silently absorbed)                       #
# --------------------------------------------------------------------------- #
def test_double_completion_is_rejected(ledger, db_path):
    intent = ledger.record_intent("build", {"n": 1})
    ledger.mark_completed(intent.id, effect_id="commit:first")

    with pytest.raises(IntentAlreadyResolved) as ei:
        ledger.mark_completed(intent.id, effect_id="commit:second")
    assert str(intent.id) in str(ei.value)
    # A rejected second resolution must leave nothing behind: the disagreement
    # is reported, and the first (true) effect_id survives untouched.
    assert ledger.get(intent.id).effect_id == "commit:first"
    assert [e.state for e in ledger.events(intent.id)] == [
        STATE_INTENDED, STATE_COMPLETED]

    with pytest.raises(IntentAlreadyResolved):
        ledger.mark_failed(intent.id, "late failure")
    assert ledger.get(intent.id).state == STATE_COMPLETED
    assert len(_raw(db_path, "SELECT id FROM intent_events")) == 2


def test_resolving_an_unknown_intent_is_rejected(ledger):
    with pytest.raises(UnknownIntent):
        ledger.mark_completed(4242, effect_id="x")
    with pytest.raises(UnknownIntent):
        ledger.mark_failed(4242, "boom")


def test_unserialisable_values_are_refused_loudly(ledger):
    with pytest.raises(ValueError):
        ledger.record_intent("build", {"fn": object()})
    with pytest.raises(ValueError):
        ledger.record_intent("")
    intent = ledger.record_intent("build", {"n": 1})
    with pytest.raises(ValueError):
        ledger.mark_completed(intent.id, result={"fn": object()})
    # The failed resolution left no partial state and no held lock.
    assert ledger.get(intent.id).state == STATE_INTENDED
    assert ledger.mark_completed(intent.id, effect_id="e").state == STATE_COMPLETED


# --------------------------------------------------------------------------- #
# concurrency                                                                  #
# --------------------------------------------------------------------------- #
def test_second_writer_waits_out_busy_timeout(db_path):
    holder = SpineLedger(db_path)
    waiter = SpineLedger(db_path)  # opened before the lock is taken
    result = {}

    def _write():
        started = time.monotonic()
        try:
            result["intent"] = waiter.record_intent("waiter", {"n": 1})
        except Exception as e:  # recorded, not swallowed -- asserted below
            result["error"] = e
        result["waited"] = time.monotonic() - started

    try:
        holder._conn.execute("BEGIN IMMEDIATE")
        holder._conn.execute(
            "INSERT INTO intents (kind, effect_key, payload, payload_sha,"
            " created_ts) VALUES ('holder', NULL, '{}', 'x', 't')")
        t = threading.Thread(target=_write)
        t.start()
        time.sleep(0.35)
        holder._conn.execute("COMMIT")
        t.join(timeout=60)
        assert not t.is_alive()
        assert "error" not in result, result.get("error")
        assert result["intent"].state == STATE_INTENDED
        assert result["waited"] >= 0.3  # it really blocked, it did not race in
    finally:
        holder.close()
        waiter.close()

    kinds = sorted(k for (k,) in _raw(db_path, "SELECT kind FROM intents"))
    assert kinds == ["holder", "waiter"]


def test_without_busy_timeout_the_second_writer_would_fail(db_path):
    """Proves the wait above is real arbitration, not a vacuous pass."""
    holder = SpineLedger(db_path)
    impatient = SpineLedger(db_path, busy_timeout_ms=1)
    try:
        assert impatient.pragmas()["busy_timeout"] == 1
        holder._conn.execute("BEGIN IMMEDIATE")
        holder._conn.execute(
            "INSERT INTO intents (kind, effect_key, payload, payload_sha,"
            " created_ts) VALUES ('holder', NULL, '{}', 'x', 't')")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            impatient.record_intent("impatient", {"n": 1})
        holder._conn.execute("COMMIT")
    finally:
        holder.close()
        impatient.close()


def test_concurrent_writers_do_not_corrupt(db_path):
    ledgers = [SpineLedger(db_path) for _ in range(2)]
    errors: list[Exception] = []
    per_thread = 25

    def _hammer(led, tag):
        for n in range(per_thread):
            try:
                led.record_intent(tag, {"n": n}, effect_key=f"{tag}-{n}")
            except Exception as e:
                errors.append(e)

    try:
        threads = [threading.Thread(target=_hammer, args=(led, f"w{i}"))
                   for i, led in enumerate(ledgers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
            assert not t.is_alive()
        assert errors == []

        checker = SpineLedger(db_path)
        try:
            assert checker._conn.execute(
                "PRAGMA integrity_check").fetchone()[0] == "ok"
            rows = checker._conn.execute(
                "SELECT id, kind, payload FROM intents").fetchall()
            assert len(rows) == 2 * per_thread
            assert len({r["id"] for r in rows}) == 2 * per_thread
            # Every payload is intact JSON, so no two writes interleaved.
            assert sorted(json.loads(r["payload"])["n"] for r in rows) == sorted(
                list(range(per_thread)) * 2)
            assert len(checker.open_intents()) == 2 * per_thread
        finally:
            checker.close()
    finally:
        for led in ledgers:
            led.close()


# --------------------------------------------------------------------------- #
# canonical JSON                                                               #
# --------------------------------------------------------------------------- #
def test_canonical_json_round_trips_byte_identically(ledger, db_path):
    payload = {"b": 1, "a": {"z": [3, 1, 2], "y": "ünicøde"},
               "c": None, "d": True}
    intent = ledger.record_intent("build", payload, effect_key="k")

    stored = _raw(db_path, "SELECT payload FROM intents WHERE id = ?",
                  (intent.id,))[0][0]
    expected = canonical_json(payload)
    assert stored == expected
    assert stored.encode("ascii") == expected.encode("ascii")
    assert intent.payload_json == expected
    assert intent.payload_sha == canonical_sha(payload)
    assert json.loads(stored) == payload
    assert ledger.get(intent.id).payload == payload


def test_canonical_json_is_insertion_order_independent(ledger):
    one = {"b": 1, "a": {"y": 2, "x": 3}}
    two = {"a": {"x": 3, "y": 2}, "b": 1}
    assert list(one) != list(two)
    i1 = ledger.record_intent("build", one)
    i2 = ledger.record_intent("build", two)
    assert i1.payload_json == i2.payload_json
    assert i1.payload_sha == i2.payload_sha == canonical_sha(one)


def test_event_details_are_canonical_json(ledger, db_path):
    intent = ledger.record_intent("build", {"n": 1})
    ledger.mark_completed(intent.id, effect_id="e", result={"b": 2, "a": 1})
    details = [d for (d,) in _raw(
        db_path, "SELECT detail FROM intent_events WHERE intent_id = ? ORDER BY id",
        (intent.id,))]
    assert details[-1] == canonical_json({"effect_id": "e",
                                          "result": {"a": 1, "b": 2}})


# --------------------------------------------------------------------------- #
# recent_intents -- the read that closes the loop's return path                #
# --------------------------------------------------------------------------- #
def _seed(led, n, kind="attempt.candidate", resolve=True):
    made = []
    for i in range(n):
        intent = led.record_intent(kind, {"task_id": f"t{i}"}, effect_key=f"e{i}")
        if resolve:
            led.mark_completed(intent.id, effect_id=f"eff{i}",
                               result={"state": "gates_failed"})
        made.append(intent)
    return made


def test_recent_intents_returns_resolved_ones_that_open_intents_cannot(tmp_path):
    # THE point of the query: after resolution open_intents goes empty, and
    # before this existed a completed attempt was reachable only by an id or an
    # effect_key the caller already had to know.
    led = SpineLedger(tmp_path / "s.sqlite3")
    _seed(led, 3)
    assert led.open_intents("attempt.candidate") == []
    recent = led.recent_intents("attempt.candidate")
    assert len(recent) == 3
    assert all(i.state == STATE_COMPLETED for i in recent)
    assert [i.payload["task_id"] for i in recent] == ["t2", "t1", "t0"]
    led.close()


def test_recent_intents_is_newest_first_and_includes_open_ones(tmp_path):
    led = SpineLedger(tmp_path / "s.sqlite3")
    _seed(led, 2, resolve=True)
    _seed(led, 1, resolve=False)          # one still open
    recent = led.recent_intents("attempt.candidate")
    assert [i.state for i in recent] == [STATE_INTENDED, STATE_COMPLETED,
                                         STATE_COMPLETED]
    led.close()


def test_recent_intents_limit_and_kind_filter(tmp_path):
    led = SpineLedger(tmp_path / "s.sqlite3")
    _seed(led, 4, kind="attempt.candidate")
    _seed(led, 2, kind="something.else")
    assert len(led.recent_intents("attempt.candidate")) == 4
    assert len(led.recent_intents("something.else")) == 2
    assert len(led.recent_intents()) == 6                 # no filter = all kinds
    assert len(led.recent_intents("attempt.candidate", limit=2)) == 2
    led.close()


def test_recent_intents_non_positive_limit_returns_nothing_not_everything(tmp_path):
    # A caller computing limit=n-1 must never get "all rows" when it asked for
    # zero -- SQL LIMIT 0 and LIMIT -1 mean opposite things, and -1 means ALL.
    led = SpineLedger(tmp_path / "s.sqlite3")
    _seed(led, 3)
    assert led.recent_intents("attempt.candidate", limit=0) == []
    assert led.recent_intents("attempt.candidate", limit=-1) == []
    led.close()


def test_recent_intents_carries_the_resolution_result(tmp_path):
    led = SpineLedger(tmp_path / "s.sqlite3")
    intent = led.record_intent("attempt.candidate", {"task_id": "x"})
    led.mark_completed(intent.id, effect_id="abc",
                       result={"state": "clean", "ok": True})
    (got,) = led.recent_intents("attempt.candidate")
    assert got.result == {"state": "clean", "ok": True}
    assert got.effect_id == "abc"
    assert got.resolved_ts
    led.close()

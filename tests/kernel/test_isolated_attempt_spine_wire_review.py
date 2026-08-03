from __future__ import annotations

import inspect
import sqlite3

import pytest

from daedalus.kernel import SourceTreeStore
from daedalus.kernel.attempt_ledger import AttemptLedger
from daedalus.kernel.attempt_spine_reader import read_attempt_intents
from daedalus.kernel.attempts import AttemptStateError
from daedalus.spine.envelope import canonical_json
from daedalus.spine.ledger import SpineLedger


EFFECT_KEY = "attempt-lifecycle:attempt-wire-review"


def _spine(tmp_path):
    path = tmp_path / "state" / "spine.sqlite3"
    spine = SpineLedger(path)
    intent = spine.record_intent(
        "attempt.lifecycle",
        {"schema": "wire-review/1"},
        effect_key=EFFECT_KEY,
        trace_id="attempt-wire-review",
    )
    return spine, intent


def _insert_event(path, intent_id: int, state: str, detail: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO intent_events (intent_id, state, ts, detail) "
            "VALUES (?, ?, ?, ?)",
            (intent_id, state, "2026-08-03T22:30:00+00:00", detail),
        )


def test_strict_reader_uses_sqlite_read_only_mode() -> None:
    source = inspect.getsource(read_attempt_intents)
    assert "?mode=ro" in source
    assert "uri=True" in source
    assert 'PRAGMA query_only=ON' in source


def test_read_only_inspection_does_not_create_a_missing_event_store(tmp_path) -> None:
    path = tmp_path / "missing" / "spine.sqlite3"
    assert not path.exists()
    with pytest.raises(AttemptStateError, match="cannot read attempt lifecycle"):
        read_attempt_intents(path)
    assert not path.exists()


def test_attempt_ledger_refuses_a_read_only_spine_as_write_authority(tmp_path) -> None:
    path = tmp_path / "state" / "spine.sqlite3"
    writable = SpineLedger(path)
    writable._conn.close()
    read_only = SpineLedger(path, read_only=True)
    try:
        with pytest.raises(AttemptStateError, match="writable canonical event spine"):
            AttemptLedger(read_only, SourceTreeStore(tmp_path / "cas"))
    finally:
        read_only._conn.close()


def test_intent_row_and_start_event_time_must_be_identical(tmp_path) -> None:
    spine, intent = _spine(tmp_path)
    path = spine.path
    spine._conn.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE intent_events SET ts = ? "
            "WHERE intent_id = ? AND state = 'INTENDED'",
            ("2099-01-01T00:00:00+00:00", intent.id),
        )

    with pytest.raises(AttemptStateError, match="row time differs"):
        read_attempt_intents(path, effect_key=EFFECT_KEY)


def test_duplicate_keys_in_terminal_event_detail_fail_closed(tmp_path) -> None:
    spine, intent = _spine(tmp_path)
    path = spine.path
    spine._conn.close()
    _insert_event(
        path,
        intent.id,
        "COMPLETED",
        '{"effect_id":"a","effect_id":"b","result":{}}',
    )

    with pytest.raises(AttemptStateError, match="duplicate key"):
        read_attempt_intents(path, effect_key=EFFECT_KEY)


def test_multiple_terminal_events_fail_closed(tmp_path) -> None:
    spine, intent = _spine(tmp_path)
    path = spine.path
    spine._conn.close()
    _insert_event(
        path,
        intent.id,
        "COMPLETED",
        canonical_json({"effect_id": "a", "result": {}}),
    )
    _insert_event(
        path,
        intent.id,
        "FAILED",
        canonical_json({"error": "second terminal"}),
    )

    with pytest.raises(AttemptStateError, match="event sequence is invalid"):
        read_attempt_intents(path, effect_key=EFFECT_KEY)


def test_noncanonical_start_detail_fails_closed(tmp_path) -> None:
    spine, intent = _spine(tmp_path)
    path = spine.path
    spine._conn.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE intent_events SET detail = ? "
            "WHERE intent_id = ? AND state = 'INTENDED'",
            ('{"payload_sha": "' + intent.payload_sha + '"}', intent.id),
        )

    with pytest.raises(AttemptStateError, match="noncanonical"):
        read_attempt_intents(path, effect_key=EFFECT_KEY)


def test_malformed_persisted_payload_is_normalized_to_attempt_state_error(tmp_path) -> None:
    spine, intent = _spine(tmp_path)
    path = spine.path
    spine._conn.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE intents SET payload = ? WHERE id = ?",
            ("{", intent.id),
        )

    with pytest.raises(AttemptStateError, match="strict JSON"):
        read_attempt_intents(path, effect_key=EFFECT_KEY)


def test_unknown_terminal_state_fails_closed(tmp_path) -> None:
    spine, intent = _spine(tmp_path)
    path = spine.path
    spine._conn.close()
    _insert_event(
        path,
        intent.id,
        "RETRYING",
        canonical_json({"result": {}}),
    )

    with pytest.raises(AttemptStateError, match="unknown attempt lifecycle event state"):
        read_attempt_intents(path, effect_key=EFFECT_KEY)

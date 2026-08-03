from __future__ import annotations

import concurrent.futures
import sqlite3
from pathlib import Path

import pytest

from daedalus.kernel.storage import (
    ArtifactCorrupt,
    ArtifactMissing,
    ContentAddressedStore,
    EventCorrupt,
    EventHeadMismatch,
    EventReplay,
    EventStore,
    EventTimeRegression,
    EventWriteError,
    ReadOnlyStore,
    ZERO_EVENT_SHA256,
)

SUBJECT = "a" * 64


def test_cas_is_deterministic_canonical_and_verified(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "cas")
    first = store.put_bytes(b"hello")
    second = store.put_bytes(b"hello")
    assert first == second
    assert store.get_bytes(first.locator) == b"hello"

    value = store.put_json({"b": 2, "a": 1})
    assert store.get_bytes(value.sha256) == b'{"a":1,"b":2}'
    assert store.get_json(value.locator) == {"a": 1, "b": 2}


def test_cas_refuses_corruption_missing_and_bad_locator(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "cas")
    value = store.put_bytes(b"hello")
    store._path(value.sha256).write_bytes(b"evil")

    with pytest.raises(ArtifactCorrupt):
        store.get_bytes(value.sha256)
    with pytest.raises(ArtifactCorrupt):
        store.put_bytes(b"hello")
    with pytest.raises(ArtifactMissing):
        store.get_bytes("b" * 64)
    with pytest.raises(ValueError):
        store.get_bytes("../etc/passwd")
    with pytest.raises(ValueError):
        store.digest_from_locator("file:///tmp/x")


def test_cas_concurrent_put_and_read_only_mode(tmp_path: Path) -> None:
    root = tmp_path / "cas"
    store = ContentAddressedStore(root)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda _: store.put_bytes(b"same"), range(32)))
    assert len({record.sha256 for record in records}) == 1

    reader = ContentAddressedStore(root, read_only=True)
    assert reader.get_bytes(records[0].locator) == b"same"
    with pytest.raises(ReadOnlyStore):
        reader.put_bytes(b"x")


def test_event_chain_is_canonical_and_stream_local(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    first = store.append(
        event_id="e1",
        stream_id="mission-1",
        kind="mission.created",
        subject_sha256=SUBJECT,
        payload={"b": 2, "a": 1},
        expected_head_sha256=ZERO_EVENT_SHA256,
        created_at="2026-08-03T20:00:00+00:00",
    )
    other = store.append(
        event_id="e2",
        stream_id="mission-2",
        kind="mission.created",
        subject_sha256=SUBJECT,
        payload={"x": 1},
        expected_head_sha256=ZERO_EVENT_SHA256,
        created_at="2026-08-03T20:00:00Z",
    )
    second = store.append(
        event_id="e3",
        stream_id="mission-1",
        kind="attempt.created",
        subject_sha256=SUBJECT,
        payload={"n": 1},
        expected_head_sha256=first.event_sha256,
        created_at="2026-08-03T20:00:01Z",
    )

    assert store.head("mission-1") == second.event_sha256
    assert [event.event_id for event in store.read_stream("mission-1")] == [
        "e1",
        "e3",
    ]
    assert store.read_stream("mission-2") == (other,)


def test_event_refuses_stale_head_replay_and_malformed_payload(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    first = store.append(
        event_id="e1",
        stream_id="s",
        kind="created",
        subject_sha256=SUBJECT,
        payload={},
        expected_head_sha256=ZERO_EVENT_SHA256,
    )
    with pytest.raises(EventHeadMismatch):
        store.append(
            event_id="e2",
            stream_id="s",
            kind="next",
            subject_sha256=SUBJECT,
            payload={},
            expected_head_sha256=ZERO_EVENT_SHA256,
        )
    with pytest.raises(EventReplay):
        store.append(
            event_id="e1",
            stream_id="other",
            kind="created",
            subject_sha256=SUBJECT,
            payload={},
            expected_head_sha256=ZERO_EVENT_SHA256,
        )
    with pytest.raises(ValueError):
        store.append(
            event_id="bad id",
            stream_id="s",
            kind="next",
            subject_sha256=SUBJECT,
            payload={},
            expected_head_sha256=first.event_sha256,
        )
    with pytest.raises(ValueError):
        store.append(
            event_id="e3",
            stream_id="s",
            kind="next",
            subject_sha256=SUBJECT,
            payload={"bad": float("nan")},
            expected_head_sha256=first.event_sha256,
        )


def test_event_time_regression_and_integrity_abort_roll_back(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    first = store.append(
        event_id="e1",
        stream_id="s",
        kind="created",
        subject_sha256=SUBJECT,
        payload={},
        expected_head_sha256=ZERO_EVENT_SHA256,
        created_at="2026-08-03T20:00:01Z",
    )
    with pytest.raises(EventTimeRegression):
        store.append(
            event_id="e2",
            stream_id="s",
            kind="next",
            subject_sha256=SUBJECT,
            payload={},
            expected_head_sha256=first.event_sha256,
            created_at="2026-08-03T20:00:00Z",
        )

    store._conn.execute(
        "CREATE TRIGGER stop_events BEFORE INSERT ON events "
        "BEGIN SELECT RAISE(ABORT, 'fault'); END"
    )
    with pytest.raises(EventWriteError):
        store.append(
            event_id="e3",
            stream_id="other",
            kind="created",
            subject_sha256=SUBJECT,
            payload={},
            expected_head_sha256=ZERO_EVENT_SHA256,
        )
    assert store.read_stream("other") == ()


def test_event_concurrent_optimistic_append_has_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    seed = EventStore(path)
    first = seed.append(
        event_id="seed",
        stream_id="s",
        kind="created",
        subject_sha256=SUBJECT,
        payload={},
        expected_head_sha256=ZERO_EVENT_SHA256,
    )
    seed.close()

    def worker(index: int):
        local = EventStore(path)
        try:
            return local.append(
                event_id=f"e{index}",
                stream_id="s",
                kind="next",
                subject_sha256=SUBJECT,
                payload={"i": index},
                expected_head_sha256=first.event_sha256,
            )
        finally:
            local.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, index) for index in range(8)]

    winners = 0
    stale = 0
    for future in futures:
        try:
            future.result()
            winners += 1
        except EventHeadMismatch:
            stale += 1
    assert winners == 1
    assert stale == 7

    final = EventStore(path, read_only=True)
    assert len(final.read_stream("s")) == 2


def test_read_only_event_store_refuses_writes_and_wrong_schema(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    store.close()

    reader = EventStore(path, read_only=True)
    assert reader.read_stream("missing") == ()
    with pytest.raises(ReadOnlyStore):
        reader.append(
            event_id="e",
            stream_id="s",
            kind="k",
            subject_sha256=SUBJECT,
            payload={},
            expected_head_sha256=ZERO_EVENT_SHA256,
        )
    reader.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE kernel_storage_meta SET value='999' WHERE key='schema_version'"
    )
    connection.commit()
    connection.close()
    with pytest.raises(EventCorrupt):
        EventStore(path, read_only=True)

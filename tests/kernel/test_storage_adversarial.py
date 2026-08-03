from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from daedalus.kernel.storage import (
    ArtifactCorrupt,
    ContentAddressedStore,
    EventCorrupt,
    EventReplay,
    EventStore,
    ZERO_EVENT_SHA256,
)

SUBJECT = "a" * 64


def test_cas_rejects_noncanonical_json_and_symlinked_prefix(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "cas")
    raw = store.put_bytes(b'{"b": 2, "a": 1}')
    with pytest.raises(ArtifactCorrupt):
        store.get_json(raw.sha256)
    with pytest.raises(ValueError):
        store.put_json({"bad": float("inf")})

    digest = hashlib.sha256(b"redirect").hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    prefix = store.blob_root / digest[:2]
    try:
        prefix.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ArtifactCorrupt):
        store.put_bytes(b"redirect")


def test_cas_failed_publication_leaves_no_visible_or_temporary_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ContentAddressedStore(tmp_path / "cas")
    digest = hashlib.sha256(b"payload").hexdigest()

    def fail_link(source, destination) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="publication failure"):
        store.put_bytes(b"payload")

    destination = store._path(digest)
    assert not destination.exists()
    assert not list(destination.parent.glob(".blob-*"))


def test_event_payload_and_chain_tampering_are_detected(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    first = store.append(
        event_id="e1",
        stream_id="s",
        kind="created",
        subject_sha256=SUBJECT,
        payload={"ok": True},
        expected_head_sha256=ZERO_EVENT_SHA256,
        created_at="2026-08-03T20:00:00Z",
    )
    store.append(
        event_id="e2",
        stream_id="s",
        kind="next",
        subject_sha256=SUBJECT,
        payload={"ok": True},
        expected_head_sha256=first.event_sha256,
        created_at="2026-08-03T20:00:01Z",
    )
    store.close()

    connection = sqlite3.connect(path)
    connection.execute("UPDATE events SET payload_json='{}' WHERE event_id='e1'")
    connection.commit()
    connection.close()
    reader = EventStore(path, read_only=True)
    with pytest.raises(EventCorrupt, match="payload digest"):
        reader.read_stream("s")
    reader.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE events SET payload_json=?, payload_sha256=? WHERE event_id='e1'",
        ('{"ok":true}', hashlib.sha256(b'{"ok":true}').hexdigest()),
    )
    connection.execute(
        "UPDATE events SET previous_event_sha256=? WHERE event_id='e2'",
        (ZERO_EVENT_SHA256,),
    )
    connection.commit()
    connection.close()
    reader = EventStore(path, read_only=True)
    with pytest.raises(EventCorrupt):
        reader.read_stream("s")


def test_event_replay_is_refused_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    first_store = EventStore(path)
    first_store.append(
        event_id="stable-event",
        stream_id="s",
        kind="created",
        subject_sha256=SUBJECT,
        payload={"value": 1},
        expected_head_sha256=ZERO_EVENT_SHA256,
    )
    first_store.close()

    restarted = EventStore(path)
    with pytest.raises(EventReplay):
        restarted.append(
            event_id="stable-event",
            stream_id="other",
            kind="created",
            subject_sha256=SUBJECT,
            payload={"value": 2},
            expected_head_sha256=ZERO_EVENT_SHA256,
        )


def test_read_only_inspection_does_not_change_database_contents(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    store.append(
        event_id="e1",
        stream_id="s",
        kind="created",
        subject_sha256=SUBJECT,
        payload={},
        expected_head_sha256=ZERO_EVENT_SHA256,
    )
    store.close()

    before = hashlib.sha256(path.read_bytes()).hexdigest()
    reader = EventStore(path, read_only=True)
    assert len(reader.read_stream("s")) == 1
    reader.close()
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after

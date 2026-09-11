"""Strict read projection over canonical Event-Store rows for Attempts."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import struct
import sys
from pathlib import Path
from typing import Any, Mapping

from daedalus.spine.envelope import canonical_json
from daedalus.spine.ledger import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTENDED,
    Intent,
    _uri_path,
)

from .attempt_contracts import (
    _ATTEMPT_EFFECT_PREFIX,
    _ATTEMPT_INTENT_KIND,
    _strict_json,
    _timestamp_value,
    AttemptStateError,
)

_MAX_TRANSITION_SKEW_SECONDS = 60.0


def _wal_checksum(data: bytes, byteorder: str) -> tuple[int, int]:
    """SQLite's header checksum; this is admission, not WAL replay."""
    words = struct.unpack(("<" if byteorder == "little" else ">") + "I" * (len(data) // 4), data)
    first = second = 0
    for index in range(0, len(words), 2):
        first = (first + words[index] + second) & 0xFFFFFFFF
        second = (second + words[index + 1] + first) & 0xFFFFFFFF
    return first, second


def _existing_wal_is_live(database: Path) -> bool:
    """Perform bounded header/pair admission before a live SQLite read.

    No sidecars means the immutable checkpointed projection. Missing partners,
    partial pages and invalid or inconsistent headers refuse before SQLite can
    silently ignore WAL state or recover those headers. This is not a complete
    frame or SHM-index integrity check; SQLite owns snapshot and frame validity.
    Sidecars must remain present during open: these entry-time checks do not
    retain their lifecycle against last-writer cleanup or hostile replacement.
    SQLite may update existing transient SHM state, including first-reader index
    reconstruction. No application checkpoint or repair is requested.
    """
    wal = Path(str(database) + "-wal")
    shm = Path(str(database) + "-shm")
    metadata = []
    try:
        for sidecar in (wal, shm):
            try:
                info = sidecar.lstat()
            except FileNotFoundError:
                info = None
            if info is not None and (
                not stat.S_ISREG(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("sidecar is not a regular file")
            metadata.append(info)
        if metadata == [None, None]:
            return False
        if any(info is None for info in metadata):
            raise ValueError("WAL and SHM must both already exist")
        wal_size, shm_size = (info.st_size for info in metadata)
        if shm_size < 32768 or shm_size % 32768:
            raise ValueError("SHM has an incomplete page")
        with shm.open("rb") as handle:
            index_header = handle.read(96)
        header = index_header[:48]
        native = "<" if sys.byteorder == "little" else ">"
        if (
            len(index_header) != 96
            or header != index_header[48:]
            or int.from_bytes(header[:4], sys.byteorder) != 3007000
            or header[12] != 1
            or header[13] not in (0, 1)
            or _wal_checksum(header[:40], sys.byteorder) != struct.unpack(native + "II", header[40:48])
        ):
            raise ValueError("SHM header is uninitialized or inconsistent")
        frames = int.from_bytes(header[16:20], sys.byteorder)
        if wal_size == 0:
            if frames:
                raise ValueError("SHM refers to frames in an empty WAL")
            return True
        with wal.open("rb") as handle:
            wal_header = handle.read(32)
        if len(wal_header) != 32:
            raise ValueError("WAL header is incomplete")
        magic, version, page_size, _, _, _, first, second = struct.unpack(">8I", wal_header)
        if (
            magic not in (0x377F0682, 0x377F0683)
            or version != 3007000
            or page_size < 512 or page_size > 65536 or page_size & (page_size - 1)
            or (wal_size - 32) % (page_size + 24)
            or frames > (wal_size - 32) // (page_size + 24)
            or _wal_checksum(wal_header[:24], "big" if magic & 1 else "little") != (first, second)
        ):
            raise ValueError("WAL header or frame extent is malformed")
        index_page_size = int.from_bytes(header[14:16], sys.byteorder)
        if (
            (65536 if index_page_size == 1 else index_page_size) != page_size
            or header[13] != magic & 1
            or header[32:40] != wal_header[16:24]
        ):
            raise ValueError("WAL and SHM headers disagree")
        return True
    except (OSError, ValueError, struct.error) as exc:
        raise AttemptStateError("cannot read attempt lifecycle: existing WAL pair is invalid") from exc


def _transition_time(
    record_time: object,
    event_time: str,
    *,
    label: str,
) -> None:
    """Bind one canonical record time to its nearby Event-Store transition."""
    if not isinstance(record_time, str):
        raise AttemptStateError(f"{label} record time must be a string")
    try:
        record = _timestamp_value(record_time, f"{label} record time")
        event = _timestamp_value(event_time, f"{label} Event-Store time")
    except (TypeError, ValueError) as exc:
        raise AttemptStateError(f"{label} time is malformed") from exc
    delta = (event - record).total_seconds()
    if delta < 0:
        raise AttemptStateError(
            f"{label} record time follows its Event-Store transition"
        )
    if delta > _MAX_TRANSITION_SKEW_SECONDS:
        raise AttemptStateError(
            f"{label} record time is not bound to its Event-Store transition"
        )


def _start_time(payload: Mapping[str, Any]) -> object:
    start = payload.get("start")
    if not isinstance(start, Mapping):
        raise AttemptStateError("persisted attempt start is not an object")
    return start.get("started_at")


def _terminal_time(result: object) -> object:
    if not isinstance(result, Mapping):
        raise AttemptStateError("persisted attempt terminal result is not an object")
    receipt = result.get("receipt")
    if not isinstance(receipt, Mapping):
        raise AttemptStateError("persisted attempt terminal receipt is not an object")
    return receipt.get("completed_at")


def read_attempt_intents(
    path: str | os.PathLike[str],
    *,
    effect_key: str | None = None,
    immutable: bool = False,
    existing_wal: bool = False,
) -> list[Intent]:
    """Strictly project lifecycle rows from the canonical spine tables.

    ``SpineLedger`` remains the only writer and state-transition authority.
    This reader deliberately retains the raw JSON long enough to reject
    duplicate keys, noncanonical bytes, digest substitution, unknown event
    sequences, malformed terminal detail, and lifecycle record times detached
    from the Event-Store transitions that retained them. The SQLite handle is
    opened with ``mode=ro`` so inspection cannot create or modify the Event
    Store, even when a caller supplies a missing path.  Existing-store HTTP
    projections may additionally request ``immutable=True`` to prevent SQLite
    from creating WAL/SHM sidecars beside the authority database.  That mode is
    deliberately a point-in-time projection; writers use the normal read-only
    URI so their own uncheckpointed WAL remains visible.

    ``existing_wal=True`` explicitly selects live read-only delivery when a
    valid WAL/SHM pair already exists, and immutable delivery when neither
    exists. With a stable sidecar lifecycle it creates no files. It never
    requests checkpoint or repair, or retries after failed admission or a failed
    read. SQLite transient SHM bookkeeping, including first-reader index
    reconstruction, is allowed without DB/WAL writes.
    """
    connection: sqlite3.Connection | None = None
    try:
        database = Path(path).resolve()
        if existing_wal:
            immutable = not _existing_wal_is_live(database)
        uri = f"file:{_uri_path(database)}?mode=ro"
        if immutable:
            uri += "&immutable=1"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        # Bind intent rows and their transition events to one committed view.
        connection.execute("BEGIN")
        if effect_key is None:
            rows = connection.execute(
                """
                SELECT * FROM intents
                WHERE kind = ? OR effect_key LIKE ?
                ORDER BY id
                """,
                (_ATTEMPT_INTENT_KIND, _ATTEMPT_EFFECT_PREFIX + "%"),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM intents WHERE effect_key = ? ORDER BY id",
                (effect_key,),
            ).fetchall()

        result: list[Intent] = []
        for row in rows:
            raw_payload = str(row["payload"])
            payload = _strict_json(raw_payload, "persisted spine intent payload")
            if canonical_json(payload) != raw_payload:
                raise AttemptStateError(
                    "persisted spine intent payload is noncanonical"
                )
            expected_payload_sha = hashlib.sha256(
                raw_payload.encode("ascii")
            ).hexdigest()
            if str(row["payload_sha"]) != expected_payload_sha:
                raise AttemptStateError(
                    "persisted spine intent payload digest is invalid"
                )

            events = connection.execute(
                """
                SELECT state, ts, detail FROM intent_events
                WHERE intent_id = ? ORDER BY id
                """,
                (int(row["id"]),),
            ).fetchall()
            if not events:
                raise AttemptStateError(
                    "attempt lifecycle intent has no persisted start event"
                )
            if len(events) > 2 or str(events[0]["state"]) != STATE_INTENDED:
                raise AttemptStateError(
                    "attempt lifecycle event sequence is invalid"
                )
            created_ts = str(row["created_ts"])
            start_event_ts = str(events[0]["ts"])
            if start_event_ts != created_ts:
                raise AttemptStateError(
                    "attempt intent row time differs from its start event time"
                )
            _transition_time(
                _start_time(payload),
                start_event_ts,
                label="attempt start",
            )
            start_detail_raw = str(events[0]["detail"])
            start_detail = _strict_json(
                start_detail_raw, "persisted attempt start event detail"
            )
            if canonical_json(start_detail) != start_detail_raw:
                raise AttemptStateError(
                    "persisted attempt start event detail is noncanonical"
                )
            if dict(start_detail) != {"payload_sha": expected_payload_sha}:
                raise AttemptStateError(
                    "attempt start event detail does not bind payload digest"
                )

            state = STATE_INTENDED
            resolved_ts = None
            effect_id = None
            terminal_result: Any = None
            error = None
            if len(events) == 2:
                terminal = events[1]
                state = str(terminal["state"])
                detail_raw = str(terminal["detail"])
                detail = _strict_json(
                    detail_raw, "persisted attempt terminal event detail"
                )
                if canonical_json(detail) != detail_raw:
                    raise AttemptStateError(
                        "persisted attempt terminal event detail is noncanonical"
                    )
                if state == STATE_COMPLETED:
                    if set(detail) != {"effect_id", "result"}:
                        raise AttemptStateError(
                            "completed attempt event detail has wrong shape"
                        )
                    effect_id = detail.get("effect_id")
                    terminal_result = detail.get("result")
                elif state == STATE_FAILED:
                    if set(detail) != {"error"}:
                        raise AttemptStateError(
                            "failed attempt event detail has wrong shape"
                        )
                    error = detail.get("error")
                else:
                    raise AttemptStateError(
                        f"unknown attempt lifecycle event state: {state}"
                    )
                resolved_ts = str(terminal["ts"])
                if state == STATE_COMPLETED:
                    _transition_time(
                        _terminal_time(terminal_result),
                        resolved_ts,
                        label="attempt completion",
                    )

            result.append(
                Intent(
                    id=int(row["id"]),
                    kind=str(row["kind"]),
                    effect_key=(
                        None
                        if row["effect_key"] is None
                        else str(row["effect_key"])
                    ),
                    payload=dict(payload),
                    payload_json=raw_payload,
                    payload_sha=expected_payload_sha,
                    created_ts=created_ts,
                    state=state,
                    resolved_ts=resolved_ts,
                    effect_id=effect_id,
                    result=terminal_result,
                    error=error,
                    trace_id=(
                        str(row["trace_id"])
                        if "trace_id" in row.keys()
                        and row["trace_id"] is not None
                        else None
                    ),
                )
            )
        return result
    except sqlite3.DatabaseError as exc:
        raise AttemptStateError(
            "cannot read attempt lifecycle from canonical event spine"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


__all__ = ["read_attempt_intents"]

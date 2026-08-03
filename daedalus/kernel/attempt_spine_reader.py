"""Strict read projection over canonical Event-Store rows for Attempts."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any

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
    AttemptStateError,
)


def read_attempt_intents(
    path: str | os.PathLike[str],
    *,
    effect_key: str | None = None,
) -> list[Intent]:
    """Strictly project lifecycle rows from the canonical spine tables.

    ``SpineLedger`` remains the only writer and state-transition authority.
    This reader deliberately retains the raw JSON long enough to reject
    duplicate keys, noncanonical bytes, digest substitution, unknown event
    sequences, and malformed terminal detail before constructing ``Intent``.
    The SQLite handle is opened with ``mode=ro`` so inspection cannot create or
    modify the Event Store, even when a caller supplies a missing path.
    """
    connection: sqlite3.Connection | None = None
    try:
        database = Path(path).resolve()
        connection = sqlite3.connect(
            f"file:{_uri_path(database)}?mode=ro",
            uri=True,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
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

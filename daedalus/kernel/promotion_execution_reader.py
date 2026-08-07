"""Strict read-only projection for promotion-execution Event-Store rows.

``SpineLedger`` remains the sole writer and transition authority. This reader
keeps raw SQLite text long enough to reject duplicate JSON keys, non-finite
constants, noncanonical bytes, payload-digest substitution, schema substitution
and invalid event sequences before higher-level contracts are hydrated.
"""
from __future__ import annotations

import hashlib
import json
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


_PROMOTION_INTENT_KIND = "promotion.execution"
_PROMOTION_EFFECT_PREFIX = "promotion.execution:"
_PROMOTION_INDEX_NAME = "idx_promotion_execution_effect_key"
_PROMOTION_INDEX_SQL = (
    "CREATE UNIQUE INDEX idx_promotion_execution_effect_key "
    "ON intents(effect_key) WHERE kind = 'promotion.execution'"
)
_MAX_JSON_BYTES = 4 * 1024 * 1024


class PromotionExecutionReadError(RuntimeError):
    """Raw canonical Event-Store projection failed closed."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PromotionExecutionReadError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> Any:
    raise PromotionExecutionReadError(f"non-finite JSON constant: {value}")


def _strict_json(raw: str, label: str) -> Any:
    if not isinstance(raw, str):
        raise PromotionExecutionReadError(f"{label} must be text")
    try:
        encoded = raw.encode("ascii", "strict")
    except UnicodeEncodeError as exc:
        raise PromotionExecutionReadError(
            f"{label} must be canonical ASCII JSON"
        ) from exc
    if len(encoded) > _MAX_JSON_BYTES:
        raise PromotionExecutionReadError(
            f"{label} exceeds {_MAX_JSON_BYTES} bytes"
        )
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except PromotionExecutionReadError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PromotionExecutionReadError(f"{label} is malformed") from exc
    try:
        rendered = canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise PromotionExecutionReadError(f"{label} is not canonical JSON") from exc
    if rendered != raw:
        raise PromotionExecutionReadError(f"{label} is noncanonical")
    return value


def _normalized_sql(value: object) -> str:
    if not isinstance(value, str):
        raise PromotionExecutionReadError(
            "promotion execution index has no retained SQL definition"
        )
    return " ".join(value.split()).casefold()


def _verify_index_shape(connection: sqlite3.Connection) -> None:
    """Refuse a same-named but weaker or differently scoped index."""
    master = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        (_PROMOTION_INDEX_NAME,),
    ).fetchone()
    if master is None:
        raise PromotionExecutionReadError(
            "promotion execution unique index is missing"
        )
    if _normalized_sql(master["sql"]) != _normalized_sql(_PROMOTION_INDEX_SQL):
        raise PromotionExecutionReadError(
            "promotion execution index SQL does not match its contract"
        )

    listed = [
        row
        for row in connection.execute("PRAGMA index_list('intents')").fetchall()
        if str(row["name"]) == _PROMOTION_INDEX_NAME
    ]
    if len(listed) != 1:
        raise PromotionExecutionReadError(
            "promotion execution index identity is ambiguous"
        )
    index = listed[0]
    if int(index["unique"]) != 1 or int(index["partial"]) != 1:
        raise PromotionExecutionReadError(
            "promotion execution index is not unique and partial"
        )
    if str(index["origin"]) != "c":
        raise PromotionExecutionReadError(
            "promotion execution index has unexpected origin"
        )

    columns = connection.execute(
        f"PRAGMA index_info('{_PROMOTION_INDEX_NAME}')"
    ).fetchall()
    if len(columns) != 1 or str(columns[0]["name"]) != "effect_key":
        raise PromotionExecutionReadError(
            "promotion execution index does not bind effect_key exactly"
        )


def read_promotion_execution_intents(
    path: str | os.PathLike[str],
    *,
    effect_key: str | None = None,
) -> list[Intent]:
    """Read and strictly validate the promotion-execution Event-Store slice.

    An exact ``effect_key`` query still returns a foreign-kind collision so the
    caller can refuse it. An unscoped query includes both the canonical kind and
    the reserved effect-key prefix, preventing a malformed row from hiding from
    pending reconciliation merely by changing one of those columns.
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
        _verify_index_shape(connection)
        if effect_key is None:
            rows = connection.execute(
                """
                SELECT * FROM intents
                WHERE kind = ? OR effect_key LIKE ?
                ORDER BY id
                """,
                (_PROMOTION_INTENT_KIND, _PROMOTION_EFFECT_PREFIX + "%"),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM intents WHERE effect_key = ? ORDER BY id",
                (effect_key,),
            ).fetchall()

        projected: list[Intent] = []
        for row in rows:
            raw_payload = str(row["payload"])
            payload = _strict_json(
                raw_payload,
                "persisted promotion execution intent payload",
            )
            expected_payload_sha = hashlib.sha256(
                raw_payload.encode("ascii")
            ).hexdigest()
            if str(row["payload_sha"]) != expected_payload_sha:
                raise PromotionExecutionReadError(
                    "persisted promotion execution payload digest is invalid"
                )

            events = connection.execute(
                """
                SELECT state, ts, detail FROM intent_events
                WHERE intent_id = ? ORDER BY id
                """,
                (int(row["id"]),),
            ).fetchall()
            if not events:
                raise PromotionExecutionReadError(
                    "promotion execution intent has no start event"
                )
            if len(events) > 2 or str(events[0]["state"]) != STATE_INTENDED:
                raise PromotionExecutionReadError(
                    "promotion execution event sequence is invalid"
                )
            created_ts = str(row["created_ts"])
            if str(events[0]["ts"]) != created_ts:
                raise PromotionExecutionReadError(
                    "promotion execution row time differs from start event"
                )
            start_detail = _strict_json(
                str(events[0]["detail"]),
                "persisted promotion execution start detail",
            )
            if start_detail != {"payload_sha": expected_payload_sha}:
                raise PromotionExecutionReadError(
                    "promotion execution start detail does not bind payload"
                )

            state = STATE_INTENDED
            resolved_ts = None
            effect_id = None
            result: Any = None
            error = None
            if len(events) == 2:
                terminal = events[1]
                state = str(terminal["state"])
                detail = _strict_json(
                    str(terminal["detail"]),
                    "persisted promotion execution terminal detail",
                )
                resolved_ts = str(terminal["ts"])
                if state == STATE_COMPLETED:
                    if not isinstance(detail, dict) or set(detail) != {
                        "effect_id",
                        "result",
                    }:
                        raise PromotionExecutionReadError(
                            "completed promotion execution detail has wrong shape"
                        )
                    effect_id_value = detail.get("effect_id")
                    if not isinstance(effect_id_value, str):
                        raise PromotionExecutionReadError(
                            "completed promotion execution effect_id must be text"
                        )
                    effect_id = effect_id_value
                    result = detail.get("result")
                elif state == STATE_FAILED:
                    if not isinstance(detail, dict) or set(detail) != {"error"}:
                        raise PromotionExecutionReadError(
                            "failed promotion execution detail has wrong shape"
                        )
                    error_value = detail.get("error")
                    if not isinstance(error_value, str):
                        raise PromotionExecutionReadError(
                            "failed promotion execution error must be text"
                        )
                    error = error_value
                else:
                    raise PromotionExecutionReadError(
                        f"unknown promotion execution event state: {state}"
                    )

            projected.append(
                Intent(
                    id=int(row["id"]),
                    kind=str(row["kind"]),
                    effect_key=(
                        None
                        if row["effect_key"] is None
                        else str(row["effect_key"])
                    ),
                    payload=payload,
                    payload_json=raw_payload,
                    payload_sha=expected_payload_sha,
                    created_ts=created_ts,
                    state=state,
                    resolved_ts=resolved_ts,
                    effect_id=effect_id,
                    result=result,
                    error=error,
                    trace_id=(
                        str(row["trace_id"])
                        if "trace_id" in row.keys()
                        and row["trace_id"] is not None
                        else None
                    ),
                )
            )
        return projected
    except PromotionExecutionReadError:
        raise
    except sqlite3.DatabaseError as exc:
        raise PromotionExecutionReadError(
            "cannot read promotion execution lifecycle from canonical Event Store"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


__all__ = ["PromotionExecutionReadError", "read_promotion_execution_intents"]

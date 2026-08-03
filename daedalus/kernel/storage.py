"""Canonical Gate-0 content-addressed storage and append-only event log.

The stores are deliberately small and stdlib-only. They provide durability,
identity and replay/concurrency refusal; they do not schedule work, validate
policy, evaluate evidence or grant effects.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from daedalus.spine.envelope import canonical_json

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_LOCATOR_PREFIX = "artifact-locator:sha256:"
ZERO_EVENT_SHA256 = "0" * 64
_EXPECTED_EVENT_COLUMNS = (
    ("sequence", "INTEGER", 0, 1),
    ("event_id", "TEXT", 1, 0),
    ("stream_id", "TEXT", 1, 0),
    ("kind", "TEXT", 1, 0),
    ("subject_sha256", "TEXT", 1, 0),
    ("payload_sha256", "TEXT", 1, 0),
    ("payload_json", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
    ("previous_event_sha256", "TEXT", 1, 0),
    ("event_sha256", "TEXT", 1, 0),
)

__all__ = [
    "ArtifactCorrupt",
    "ArtifactMissing",
    "ContentAddressedStore",
    "EventCorrupt",
    "EventHeadMismatch",
    "EventReplay",
    "EventStore",
    "EventTimeRegression",
    "EventWriteError",
    "KernelStorageError",
    "ReadOnlyStore",
    "StoredArtifact",
    "StoredEvent",
    "ZERO_EVENT_SHA256",
]


class KernelStorageError(RuntimeError):
    """Base class for fail-closed storage refusals."""


class ArtifactMissing(KernelStorageError):
    pass


class ArtifactCorrupt(KernelStorageError):
    pass


class EventReplay(KernelStorageError):
    pass


class EventHeadMismatch(KernelStorageError):
    pass


class EventCorrupt(KernelStorageError):
    pass


class EventWriteError(KernelStorageError):
    pass


class EventTimeRegression(KernelStorageError):
    pass


class ReadOnlyStore(KernelStorageError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase 64-character sha256 digest")
    return value


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identifier")
    return value


def _validate_json(value: Any, name: str = "payload") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{name} contains a non-string object key")
            result[key] = _validate_json(nested, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_validate_json(item, f"{name}[]") for item in value]
    raise ValueError(f"{name} contains non-JSON value {type(value).__name__}")


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
    if not isinstance(value, str):
        raise ValueError("created_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    size_bytes: int
    locator: str


class ContentAddressedStore:
    """Immutable sha256 blob store with verified reads and atomic publication."""

    def __init__(self, root: str | Path, *, read_only: bool = False) -> None:
        self.root = Path(root)
        self.read_only = bool(read_only)
        self.blob_root = self.root / "blobs" / "sha256"
        if not self.read_only:
            self.blob_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def locator(sha256: str) -> str:
        return _LOCATOR_PREFIX + _digest(sha256, "sha256")

    @staticmethod
    def digest_from_locator(locator: str) -> str:
        if not isinstance(locator, str) or not locator.startswith(_LOCATOR_PREFIX):
            raise ValueError("artifact locator must use artifact-locator:sha256")
        return _digest(locator[len(_LOCATOR_PREFIX):], "artifact locator digest")

    def _path(self, sha256: str) -> Path:
        value = _digest(sha256, "sha256")
        prefix = self.blob_root / value[:2]
        if self.blob_root.is_symlink() or prefix.is_symlink():
            raise ArtifactCorrupt(
                "content-addressed store contains a symlinked blob directory"
            )
        return prefix / value[2:]

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            directory_fd = os.open(path, os.O_RDONLY)
        except OSError:
            if os.name == "nt":
                return
            raise
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def put_bytes(self, data: bytes) -> StoredArtifact:
        if self.read_only:
            raise ReadOnlyStore("content-addressed store is read-only")
        if not isinstance(data, bytes):
            raise TypeError("artifact data must be bytes")
        digest = _sha256_bytes(data)
        destination = self._path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise ArtifactCorrupt(f"artifact {digest} is a symbolic link")
        if destination.exists():
            existing = destination.read_bytes()
            if _sha256_bytes(existing) != digest:
                raise ArtifactCorrupt(f"existing blob {digest} is corrupt")
            return StoredArtifact(digest, len(existing), self.locator(digest))
        fd, temp_name = tempfile.mkstemp(prefix=".blob-", dir=destination.parent)
        temp: Path | None = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # Hard-link publication is atomic and refuses replacement. A
            # concurrent winner is accepted only after verifying its bytes.
            try:
                os.link(temp, destination)
            except FileExistsError:
                if destination.is_symlink():
                    raise ArtifactCorrupt(
                        f"concurrent artifact {digest} is a symbolic link"
                    )
                existing = destination.read_bytes()
                if _sha256_bytes(existing) != digest:
                    raise ArtifactCorrupt(f"concurrent blob {digest} is corrupt")
            else:
                temp.unlink()
                temp = None
            self._fsync_directory(destination.parent)
        finally:
            if temp is not None and temp.exists():
                temp.unlink()
        return StoredArtifact(digest, len(data), self.locator(digest))

    def put_json(self, payload: Any) -> StoredArtifact:
        return self.put_bytes(canonical_json(_validate_json(payload)).encode("ascii"))

    def get_bytes(self, sha256_or_locator: str) -> bytes:
        if not isinstance(sha256_or_locator, str):
            raise ValueError("artifact identity must be a digest or locator string")
        digest = (
            self.digest_from_locator(sha256_or_locator)
            if sha256_or_locator.startswith(_LOCATOR_PREFIX)
            else _digest(sha256_or_locator, "sha256")
        )
        path = self._path(digest)
        if path.is_symlink():
            raise ArtifactCorrupt(f"artifact {digest} is a symbolic link")
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactMissing(f"artifact {digest} does not exist") from exc
        if _sha256_bytes(data) != digest:
            raise ArtifactCorrupt(f"artifact {digest} failed digest verification")
        return data

    def get_json(self, sha256_or_locator: str) -> Any:
        data = self.get_bytes(sha256_or_locator)
        try:
            parsed = json.loads(data.decode("ascii"))
            canonical = canonical_json(_validate_json(parsed)).encode("ascii")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ArtifactCorrupt("artifact is not canonical finite JSON") from exc
        if canonical != data:
            raise ArtifactCorrupt("artifact is JSON but not in canonical encoding")
        return parsed


@dataclass(frozen=True)
class StoredEvent:
    sequence: int
    event_id: str
    stream_id: str
    kind: str
    subject_sha256: str
    payload_sha256: str
    payload: Any
    created_at: str
    previous_event_sha256: str
    event_sha256: str


class EventStore:
    """SQLite append-only per-stream hash chain with optimistic head binding."""

    def __init__(
        self,
        path: str | Path,
        *,
        read_only: bool = False,
        busy_timeout_ms: int = 30_000,
    ) -> None:
        self.path = Path(path)
        self.read_only = bool(read_only)
        self.busy_timeout_ms = int(busy_timeout_ms)
        if self.busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")
        self._lock = threading.RLock()
        if self.read_only:
            uri = self.path.resolve().as_uri() + "?mode=ro"
            self._conn = sqlite3.connect(
                uri,
                uri=True,
                isolation_level=None,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._conn.execute("PRAGMA query_only=ON")
            self._verify_schema()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._txn():
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS kernel_storage_meta ("
                " key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO kernel_storage_meta(key, value) "
                "VALUES('schema_version','1')"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                " sequence INTEGER PRIMARY KEY AUTOINCREMENT,"
                " event_id TEXT NOT NULL UNIQUE,"
                " stream_id TEXT NOT NULL,"
                " kind TEXT NOT NULL,"
                " subject_sha256 TEXT NOT NULL,"
                " payload_sha256 TEXT NOT NULL,"
                " payload_json TEXT NOT NULL,"
                " created_at TEXT NOT NULL,"
                " previous_event_sha256 TEXT NOT NULL,"
                " event_sha256 TEXT NOT NULL UNIQUE)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_stream_sequence "
                "ON events(stream_id, sequence)"
            )
        self._verify_schema()

    def _verify_schema(self) -> None:
        try:
            row = self._conn.execute(
                "SELECT value FROM kernel_storage_meta WHERE key='schema_version'"
            ).fetchone()
            columns = tuple(
                (
                    str(item["name"]),
                    str(item["type"]).upper(),
                    int(item["notnull"]),
                    int(item["pk"]),
                )
                for item in self._conn.execute("PRAGMA table_info(events)").fetchall()
            )
            indexes = self._conn.execute("PRAGMA index_list(events)").fetchall()
            unique_columns: set[tuple[str, ...]] = set()
            named_indexes: set[str] = set()
            for index in indexes:
                name = str(index["name"])
                named_indexes.add(name)
                if int(index["unique"]):
                    unique_columns.add(
                        tuple(
                            str(info["name"])
                            for info in self._conn.execute(
                                f'PRAGMA index_info("{name}")'
                            ).fetchall()
                        )
                    )
        except sqlite3.DatabaseError as exc:
            raise EventCorrupt("event store schema is missing or unreadable") from exc
        if row is None or str(row["value"]) != "1":
            raise EventCorrupt("event store schema version is unsupported")
        if columns != _EXPECTED_EVENT_COLUMNS:
            raise EventCorrupt("event store events table shape is unsupported")
        if {("event_id",), ("event_sha256",)} - unique_columns:
            raise EventCorrupt("event store uniqueness constraints are missing")
        if "idx_events_stream_sequence" not in named_indexes:
            raise EventCorrupt("event store stream index is missing")

    @contextmanager
    def _txn(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _rows_unlocked(self, stream_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM events WHERE stream_id=? ORDER BY sequence",
            (stream_id,),
        ).fetchall()

    def _read_stream_unlocked(self, stream_id: str) -> tuple[StoredEvent, ...]:
        events: list[StoredEvent] = []
        previous = ZERO_EVENT_SHA256
        previous_time: str | None = None
        for row in self._rows_unlocked(stream_id):
            event = self._decode(row, previous)
            if previous_time is not None and event.created_at < previous_time:
                raise EventCorrupt(
                    f"event {event.event_id} regresses its stream timestamp"
                )
            events.append(event)
            previous = event.event_sha256
            previous_time = event.created_at
        return tuple(events)

    def head(self, stream_id: str) -> str:
        stream = _identifier(stream_id, "stream_id")
        with self._lock:
            events = self._read_stream_unlocked(stream)
            return events[-1].event_sha256 if events else ZERO_EVENT_SHA256

    def append(
        self,
        *,
        event_id: str,
        stream_id: str,
        kind: str,
        subject_sha256: str,
        payload: Mapping[str, Any],
        expected_head_sha256: str,
        created_at: str | None = None,
    ) -> StoredEvent:
        if self.read_only:
            raise ReadOnlyStore("event store is read-only")
        event_id = _identifier(event_id, "event_id")
        stream_id = _identifier(stream_id, "stream_id")
        kind = _identifier(kind, "kind")
        subject_sha256 = _digest(subject_sha256, "subject_sha256")
        expected = _digest(expected_head_sha256, "expected_head_sha256")
        timestamp = _timestamp(created_at)
        if not isinstance(payload, Mapping):
            raise ValueError("event payload must be a JSON object")
        payload_json = canonical_json(_validate_json(payload))
        payload_sha256 = _sha256_bytes(payload_json.encode("ascii"))
        with self._txn():
            existing = self._read_stream_unlocked(stream_id)
            head = existing[-1].event_sha256 if existing else ZERO_EVENT_SHA256
            if head != expected:
                raise EventHeadMismatch(
                    f"expected stream head {expected}, found {head}"
                )
            if existing and timestamp < existing[-1].created_at:
                raise EventTimeRegression(
                    "event time cannot precede the current stream head"
                )
            body = {
                "event_id": event_id,
                "stream_id": stream_id,
                "kind": kind,
                "subject_sha256": subject_sha256,
                "payload_sha256": payload_sha256,
                "created_at": timestamp,
                "previous_event_sha256": head,
            }
            event_sha256 = _sha256_bytes(canonical_json(body).encode("ascii"))
            try:
                cursor = self._conn.execute(
                    "INSERT INTO events(event_id, stream_id, kind, subject_sha256, "
                    "payload_sha256, payload_json, created_at, "
                    "previous_event_sha256, event_sha256) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        stream_id,
                        kind,
                        subject_sha256,
                        payload_sha256,
                        payload_json,
                        timestamp,
                        head,
                        event_sha256,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                duplicate = self._conn.execute(
                    "SELECT 1 FROM events WHERE event_id=? OR event_sha256=?",
                    (event_id, event_sha256),
                ).fetchone()
                if duplicate is not None:
                    raise EventReplay(
                        f"event id or digest already exists: {event_id}"
                    ) from exc
                raise EventWriteError(
                    "event append violated storage integrity"
                ) from exc
            sequence = int(cursor.lastrowid)
        return StoredEvent(
            sequence,
            event_id,
            stream_id,
            kind,
            subject_sha256,
            payload_sha256,
            json.loads(payload_json),
            timestamp,
            head,
            event_sha256,
        )

    @staticmethod
    def _decode(row: sqlite3.Row, previous: str) -> StoredEvent:
        try:
            _identifier(str(row["event_id"]), "event_id")
            _identifier(str(row["stream_id"]), "stream_id")
            _identifier(str(row["kind"]), "kind")
            _digest(str(row["subject_sha256"]), "subject_sha256")
            _digest(str(row["payload_sha256"]), "payload_sha256")
            _digest(
                str(row["previous_event_sha256"]),
                "previous_event_sha256",
            )
            _digest(str(row["event_sha256"]), "event_sha256")
            _timestamp(str(row["created_at"]))
        except ValueError as exc:
            raise EventCorrupt(
                f"event {row['event_id']} contains malformed metadata"
            ) from exc
        payload_json = str(row["payload_json"])
        try:
            payload_bytes = payload_json.encode("ascii")
        except UnicodeEncodeError as exc:
            raise EventCorrupt(
                f"event {row['event_id']} payload is not canonical ASCII JSON"
            ) from exc
        payload_sha = _sha256_bytes(payload_bytes)
        if payload_sha != row["payload_sha256"]:
            raise EventCorrupt(
                f"event {row['event_id']} payload digest mismatch"
            )
        if row["previous_event_sha256"] != previous:
            raise EventCorrupt(
                f"event {row['event_id']} breaks its stream chain"
            )
        body = {
            "event_id": row["event_id"],
            "stream_id": row["stream_id"],
            "kind": row["kind"],
            "subject_sha256": row["subject_sha256"],
            "payload_sha256": row["payload_sha256"],
            "created_at": row["created_at"],
            "previous_event_sha256": row["previous_event_sha256"],
        }
        event_sha = _sha256_bytes(canonical_json(body).encode("ascii"))
        if event_sha != row["event_sha256"]:
            raise EventCorrupt(f"event {row['event_id']} digest mismatch")
        try:
            payload = json.loads(payload_json)
            canonical = canonical_json(_validate_json(payload))
        except (json.JSONDecodeError, ValueError) as exc:
            raise EventCorrupt(
                f"event {row['event_id']} payload is invalid JSON"
            ) from exc
        if canonical != payload_json:
            raise EventCorrupt(
                f"event {row['event_id']} payload is not canonically encoded"
            )
        return StoredEvent(
            int(row["sequence"]),
            str(row["event_id"]),
            str(row["stream_id"]),
            str(row["kind"]),
            str(row["subject_sha256"]),
            str(row["payload_sha256"]),
            payload,
            str(row["created_at"]),
            str(row["previous_event_sha256"]),
            str(row["event_sha256"]),
        )

    def read_stream(self, stream_id: str) -> tuple[StoredEvent, ...]:
        stream = _identifier(stream_id, "stream_id")
        with self._lock:
            return self._read_stream_unlocked(stream)

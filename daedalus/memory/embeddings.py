"""Versioned, derived embedding projections for Daedalus events.

The append-only event journal remains authoritative.  This module stores
immutable *snapshots* of projection inputs and their derived vectors so search
results can be traced back to evidence without turning the vector database into
an event log.

Every vector belongs to an :class:`EmbeddingSpec`.  A different model,
dimension, normalization policy, model revision, or projector version creates a
different ``index_id``.  Queries only compare vectors from exactly one index;
vectors from incompatible spaces are never mixed implicitly.

Opening a schema-v1 database performs a *schema migration*, but not a vector
migration: the old ``agent_events`` table is renamed to
``legacy_agent_events_v1`` and left untouched.  Its vectors have no recorded
model identity, so they remain quarantined and excluded from search.  Re-index
from the authoritative JSONL/transport journal to create valid v2 projections.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from daedalus.adapters.events import TransportRecord
from daedalus.providers.ollama import DEFAULT_HOST

EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
EVENT_PROJECTOR_VERSION = "agent-event-v1"
SCHEMA_VERSION = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass
class AgentEvent:
    """A projection input, not the authoritative event record."""

    event_id: str
    event_type: str
    content: str
    timestamp: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentEvent:
        metadata = data.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            content=data["content"],
            timestamp=data["timestamp"],
            metadata=metadata,
        )


@dataclass(frozen=True)
class EmbeddingSpec:
    """Identity of one mutually compatible embedding coordinate system."""

    model: str
    dimension: int
    normalization: str = "l2"
    projector_version: str = EVENT_PROJECTOR_VERSION
    provider: str = "ollama"
    model_revision: str | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("embedding model must not be empty")
        if self.dimension <= 0:
            raise ValueError("embedding dimension must be positive")
        if self.normalization not in {"l2", "none"}:
            raise ValueError("normalization must be 'l2' or 'none'")
        if not self.projector_version.strip():
            raise ValueError("projector_version must not be empty")
        if not self.provider.strip():
            raise ValueError("embedding provider must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "model_revision": self.model_revision,
            "dimension": self.dimension,
            "normalization": self.normalization,
            "projector_version": self.projector_version,
        }

    @property
    def index_id(self) -> str:
        digest = hashlib.sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()
        return f"emb:{digest}"


@dataclass(frozen=True)
class ProjectionFilter:
    """Exact-match provenance filters applied before vector scoring."""

    project: str | None = None
    trust: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class OperationStatus:
    """Machine-readable status for projection and query operations."""

    code: str
    message: str
    available: bool
    index_id: str | None = None


@dataclass(frozen=True)
class IngestReport:
    status: OperationStatus
    attempted: int
    projected: int
    spec: EmbeddingSpec | None = None


@dataclass(frozen=True)
class SearchReport:
    status: OperationStatus
    matches: list[tuple[AgentEvent, float]]
    spec: EmbeddingSpec | None = None


@dataclass(frozen=True)
class IndexStatus:
    status: OperationStatus
    spec: EmbeddingSpec | None
    projection_count: int
    legacy_unversioned_count: int


class EmbeddingError(RuntimeError):
    """Base class for expected embedder failures."""


class EmbeddingUnavailableError(EmbeddingError):
    """The embedding service could not be reached."""


class EmbeddingProtocolError(EmbeddingError):
    """The embedding service returned a malformed response."""


class EmbeddingBackend(Protocol):
    """Minimal testable backend seam used by :class:`EventVectorStore`."""

    provider: str

    def embed(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Return exactly one vector per input text."""


class OllamaEmbeddingBackend:
    """Ollama's current batched ``POST /api/embed`` transport."""

    provider = "ollama"

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 10.0):
        self.host = host
        self.timeout = timeout

    def embed(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        url = self.host.rstrip("/") + "/api/embed"
        payload: dict[str, Any] = {"model": model, "input": list(texts)}
        if dimensions is not None:
            payload["dimensions"] = dimensions
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as exc:
            raise EmbeddingUnavailableError(str(exc)) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EmbeddingProtocolError("Ollama returned invalid JSON") from exc

        embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(embeddings, list):
            raise EmbeddingProtocolError("Ollama /api/embed response has no embeddings array")
        return embeddings


def _pack_embedding(embedding: list[float]) -> bytes:
    """Pack a non-empty finite vector as explicit little-endian float32."""

    vector = _coerce_vector(embedding)
    try:
        return struct.pack(f"<{len(vector)}f", *vector)
    except (OverflowError, struct.error) as exc:
        raise ValueError("embedding cannot be represented as float32") from exc


def _unpack_embedding(blob: bytes) -> list[float]:
    """Unpack an explicit little-endian float32 vector."""

    if not blob or len(blob) % 4:
        raise ValueError("embedding blob must contain one or more float32 values")
    size = len(blob) // 4
    return list(struct.unpack(f"<{size}f", blob))


def _coerce_vector(vector: Sequence[Any], *, dimension: int | None = None) -> list[float]:
    if isinstance(vector, (str, bytes)) or not isinstance(vector, Sequence):
        raise ValueError("embedding must be a numeric sequence")
    if not vector:
        raise ValueError("embedding must not be empty")
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("embedding contains a non-numeric value") from exc
    if dimension is not None and len(values) != dimension:
        raise ValueError(f"expected embedding dimension {dimension}, got {len(values)}")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding contains NaN or infinity")
    return values


def _normalize_vector(vector: Sequence[Any], normalization: str) -> list[float]:
    values = _coerce_vector(vector)
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("cannot index a zero or invalid embedding for cosine search")
    if normalization == "none":
        return values
    if normalization != "l2":
        raise ValueError(f"unsupported normalization: {normalization}")
    return [value / norm for value in values]


def _validate_batch(
    embeddings: Sequence[Sequence[Any]],
    expected_count: int,
    *,
    dimension: int | None,
    normalization: str,
) -> tuple[list[list[float]], int]:
    if len(embeddings) != expected_count:
        raise ValueError(f"expected {expected_count} embeddings, got {len(embeddings)}")
    normalized: list[list[float]] = []
    resolved_dimension = dimension
    for embedding in embeddings:
        vector = _normalize_vector(embedding, normalization)
        if resolved_dimension is None:
            resolved_dimension = len(vector)
        if len(vector) != resolved_dimension:
            raise ValueError(
                f"embedding dimension changed inside batch: "
                f"expected {resolved_dimension}, got {len(vector)}"
            )
        normalized.append(vector)
    if resolved_dimension is None:
        raise ValueError("empty embedding batch")
    return normalized, resolved_dimension


def _embed_batch(
    texts: list[str],
    host: str,
    model: str,
    backend: EmbeddingBackend | None = None,
) -> list[list[float]] | None:
    """Compatibility helper using the current batch API.

    New callers should use the report-returning :class:`EventVectorStore`
    methods so an unavailable embedder is distinguishable from an empty index.
    """

    selected = backend or OllamaEmbeddingBackend(host)
    try:
        return selected.embed(texts, model=model)
    except EmbeddingError:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity without silently truncating dimensions."""

    left = _coerce_vector(a)
    right = _coerce_vector(b)
    if len(left) != len(right):
        raise ValueError(f"cosine dimension mismatch: {len(left)} != {len(right)}")
    dot = sum(x * y for x, y in zip(left, right))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(y * y for y in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        raise ValueError("cosine similarity is undefined for a zero vector")
    return dot / (left_norm * right_norm)


def _projection_text(event: AgentEvent) -> str:
    return f"[{event.event_type}] {event.content}"


def _source_hash(event: AgentEvent) -> str:
    payload = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "content": event.content,
        "timestamp": event.timestamp,
        "metadata": event.metadata,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"src:{digest}"


def _projection_id(index_id: str, source_hash: str) -> str:
    digest = hashlib.sha256(f"{index_id}\0{source_hash}".encode("utf-8")).hexdigest()
    return f"prj:{digest}"


def _metadata_value(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, str):
            return value
        return _canonical_json(value)
    return None


class EventVectorStore:
    """Append-only, versioned event projection index backed by SQLite."""

    def __init__(
        self,
        db_path: str | os.PathLike[str] = ":memory:",
        *,
        backend: EmbeddingBackend | None = None,
    ):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._backend_override = backend
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_db()

    def _init_db(self) -> None:
        """Create schema v2 and conservatively quarantine legacy vectors.

        Schema v1 did not record the embedding model or dimension.  Assigning
        those rows to the current default model would silently mix coordinate
        systems, so the old table is retained as ``legacy_agent_events_v1`` and
        excluded from v2 search until the source events are re-ingested.
        """

        with self._conn:
            existing = self._conn.execute(
                "SELECT type FROM sqlite_master WHERE name = 'agent_events'"
            ).fetchone()
            legacy = self._conn.execute(
                "SELECT type FROM sqlite_master WHERE name = 'legacy_agent_events_v1'"
            ).fetchone()
            if existing is not None and existing["type"] == "table" and legacy is None:
                self._conn.execute(
                    "ALTER TABLE agent_events RENAME TO legacy_agent_events_v1"
                )

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projection_schema (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO projection_schema (key, value)
                VALUES ('schema_version', ?)
                """,
                (str(SCHEMA_VERSION),),
            )
            stored_version = self._conn.execute(
                """
                SELECT value FROM projection_schema
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if stored_version is None or stored_version["value"] != str(SCHEMA_VERSION):
                found = stored_version["value"] if stored_version is not None else "missing"
                raise RuntimeError(
                    f"unsupported projection schema version {found}; "
                    f"this code requires {SCHEMA_VERSION}"
                )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_indexes (
                    index_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    model_revision TEXT,
                    dimension INTEGER NOT NULL,
                    normalization TEXT NOT NULL,
                    projector_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projection_sources (
                    source_hash TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_projections (
                    projection_id TEXT PRIMARY KEY,
                    index_id TEXT NOT NULL REFERENCES embedding_indexes(index_id),
                    source_hash TEXT NOT NULL REFERENCES projection_sources(source_hash),
                    projection_text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    project TEXT,
                    trust TEXT,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(index_id, source_hash)
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_projection_index
                ON event_projections (index_id)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_projection_filters
                ON event_projections (index_id, project, trust, source)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_projection_event_time
                ON projection_sources (timestamp)
                """
            )

            compatibility = self._conn.execute(
                "SELECT type FROM sqlite_master WHERE name = 'agent_events'"
            ).fetchone()
            if compatibility is None:
                self._conn.execute(
                    """
                    CREATE VIEW agent_events AS
                    SELECT
                        s.event_id AS event_id,
                        s.event_type AS event_type,
                        s.content AS content,
                        s.timestamp AS timestamp,
                        s.metadata_json AS metadata,
                        p.embedding AS embedding,
                        p.index_id AS index_id
                    FROM event_projections AS p
                    JOIN projection_sources AS s
                      ON s.source_hash = p.source_hash
                    """
                )

    def _backend(self, host: str) -> EmbeddingBackend:
        return self._backend_override or OllamaEmbeddingBackend(host)

    @staticmethod
    def _status(
        code: str,
        message: str,
        *,
        available: bool,
        spec: EmbeddingSpec | None = None,
    ) -> OperationStatus:
        return OperationStatus(
            code=code,
            message=message,
            available=available,
            index_id=spec.index_id if spec else None,
        )

    @staticmethod
    def _resolved_spec(
        *,
        backend: EmbeddingBackend,
        model: str,
        dimension: int,
        normalization: str,
        projector_version: str,
        model_revision: str | None,
        requested: EmbeddingSpec | None,
    ) -> EmbeddingSpec:
        if requested is not None:
            if requested.provider != backend.provider:
                raise ValueError(
                    f"spec provider {requested.provider!r} does not match "
                    f"backend provider {backend.provider!r}"
                )
            if requested.model != model:
                raise ValueError(
                    f"spec model {requested.model!r} does not match request model {model!r}"
                )
            if requested.dimension != dimension:
                raise ValueError(
                    f"spec dimension {requested.dimension} does not match "
                    f"response dimension {dimension}"
                )
            if requested.normalization != normalization:
                raise ValueError("spec normalization does not match projection policy")
            if requested.projector_version != projector_version:
                raise ValueError("unsupported projector version for this projection input")
            if requested.model_revision != model_revision:
                raise ValueError("spec model revision does not match request")
            return requested
        return EmbeddingSpec(
            provider=backend.provider,
            model=model,
            model_revision=model_revision,
            dimension=dimension,
            normalization=normalization,
            projector_version=projector_version,
        )

    def _ensure_index(self, spec: EmbeddingSpec) -> None:
        now = _utc_now()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO embedding_indexes (
                    index_id, provider, model, model_revision, dimension,
                    normalization, projector_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.index_id,
                    spec.provider,
                    spec.model,
                    spec.model_revision,
                    spec.dimension,
                    spec.normalization,
                    spec.projector_version,
                    now,
                ),
            )
        stored = self._conn.execute(
            "SELECT * FROM embedding_indexes WHERE index_id = ?",
            (spec.index_id,),
        ).fetchone()
        if stored is None:
            raise RuntimeError("failed to create embedding index")
        stored_spec = self._spec_from_row(stored)
        if stored_spec != spec:
            raise RuntimeError("embedding index hash collision or corrupt index metadata")

    @staticmethod
    def _spec_from_row(row: sqlite3.Row) -> EmbeddingSpec:
        return EmbeddingSpec(
            provider=row["provider"],
            model=row["model"],
            model_revision=row["model_revision"],
            dimension=int(row["dimension"]),
            normalization=row["normalization"],
            projector_version=row["projector_version"],
        )

    def _store_batch(
        self,
        events: Sequence[AgentEvent],
        embeddings: Sequence[list[float]],
        spec: EmbeddingSpec,
    ) -> int:
        self._ensure_index(spec)
        now = _utc_now()
        inserted = 0
        with self._conn:
            for event, embedding in zip(events, embeddings):
                metadata_json = _canonical_json(event.metadata)
                source_hash = _source_hash(event)
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO projection_sources (
                        source_hash, event_id, event_type, content, timestamp,
                        metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_hash,
                        event.event_id,
                        event.event_type,
                        event.content,
                        event.timestamp,
                        metadata_json,
                        now,
                    ),
                )
                cursor = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO event_projections (
                        projection_id, index_id, source_hash, projection_text,
                        embedding, project, trust, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _projection_id(spec.index_id, source_hash),
                        spec.index_id,
                        source_hash,
                        _projection_text(event),
                        _pack_embedding(embedding),
                        _metadata_value(event.metadata, "project", "repo_root"),
                        _metadata_value(event.metadata, "trust", "trust_tier"),
                        _metadata_value(event.metadata, "source", "runtime"),
                        now,
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
        return inserted

    def ingest_events_report(
        self,
        events: Iterable[AgentEvent],
        batch_size: int = 10,
        host: str = DEFAULT_HOST,
        model: str = EMBED_MODEL,
        *,
        spec: EmbeddingSpec | None = None,
        normalization: str = "l2",
        model_revision: str | None = None,
    ) -> IngestReport:
        """Project events and return an explicit, non-throwing service report."""

        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if spec is not None:
            model = spec.model
            normalization = spec.normalization
            model_revision = spec.model_revision
        if normalization not in {"l2", "none"}:
            raise ValueError("normalization must be 'l2' or 'none'")

        backend = self._backend(host)
        pending: list[AgentEvent] = []
        attempted = 0
        projected = 0
        resolved = spec

        def process(batch: list[AgentEvent]) -> OperationStatus | None:
            nonlocal projected, resolved
            texts = [_projection_text(event) for event in batch]
            try:
                raw = backend.embed(
                    texts,
                    model=model,
                    dimensions=resolved.dimension if resolved else None,
                )
            except EmbeddingUnavailableError as exc:
                return self._status(
                    "embedder_unavailable",
                    f"embedding backend unavailable: {exc}",
                    available=False,
                    spec=resolved,
                )
            except EmbeddingProtocolError as exc:
                return self._status(
                    "invalid_embedding_response",
                    str(exc),
                    available=False,
                    spec=resolved,
                )
            try:
                vectors, dimension = _validate_batch(
                    raw,
                    len(batch),
                    dimension=resolved.dimension if resolved else None,
                    normalization=normalization,
                )
                candidate = self._resolved_spec(
                    backend=backend,
                    model=model,
                    dimension=dimension,
                    normalization=normalization,
                    projector_version=EVENT_PROJECTOR_VERSION,
                    model_revision=model_revision,
                    requested=resolved,
                )
                projected += self._store_batch(batch, vectors, candidate)
                resolved = candidate
            except (TypeError, ValueError) as exc:
                return self._status(
                    "invalid_embedding_response",
                    str(exc),
                    available=False,
                    spec=resolved,
                )
            return None

        for event in events:
            pending.append(event)
            attempted += 1
            if len(pending) >= batch_size:
                failure = process(pending)
                pending = []
                if failure is not None:
                    code = "partial" if projected else failure.code
                    status = (
                        self._status(
                            code,
                            f"{projected} projections written before failure: "
                            f"{failure.message}",
                            available=False,
                            spec=resolved,
                        )
                        if projected
                        else failure
                    )
                    return IngestReport(status, attempted, projected, resolved)

        if pending:
            failure = process(pending)
            if failure is not None:
                code = "partial" if projected else failure.code
                status = (
                    self._status(
                        code,
                        f"{projected} projections written before failure: {failure.message}",
                        available=False,
                        spec=resolved,
                    )
                    if projected
                    else failure
                )
                return IngestReport(status, attempted, projected, resolved)

        if attempted == 0:
            return IngestReport(
                self._status("empty", "no events supplied", available=True),
                attempted=0,
                projected=0,
                spec=None,
            )
        return IngestReport(
            self._status(
                "ready",
                f"stored {projected} new projections from {attempted} inputs",
                available=True,
                spec=resolved,
            ),
            attempted=attempted,
            projected=projected,
            spec=resolved,
        )

    def ingest_events(
        self,
        events: Iterable[AgentEvent],
        batch_size: int = 10,
        host: str = DEFAULT_HOST,
        model: str = EMBED_MODEL,
        *,
        spec: EmbeddingSpec | None = None,
        normalization: str = "l2",
        model_revision: str | None = None,
    ) -> int:
        """Compatibility wrapper returning the number of new projections."""

        return self.ingest_events_report(
            events,
            batch_size=batch_size,
            host=host,
            model=model,
            spec=spec,
            normalization=normalization,
            model_revision=model_revision,
        ).projected

    def ingest_transport_records_report(
        self,
        records: Iterable[TransportRecord],
        batch_size: int = 10,
        host: str = DEFAULT_HOST,
        model: str = EMBED_MODEL,
        *,
        spec: EmbeddingSpec | None = None,
        normalization: str = "l2",
        model_revision: str | None = None,
    ) -> IngestReport:
        """Project lossless shell records without replacing their event journal."""

        events = (
            AgentEvent(
                event_id=record.record_id,
                event_type=record.event_type,
                content=record.embedding_text(),
                timestamp=record.timestamp,
                metadata={
                    "session_id": record.session_id,
                    "runtime": record.runtime,
                    "direction": record.direction,
                    "sequence": record.sequence,
                    "payload": record.payload,
                    **record.metadata,
                },
            )
            for record in records
        )
        return self.ingest_events_report(
            events,
            batch_size=batch_size,
            host=host,
            model=model,
            spec=spec,
            normalization=normalization,
            model_revision=model_revision,
        )

    def ingest_transport_records(
        self,
        records: Iterable[TransportRecord],
        batch_size: int = 10,
        host: str = DEFAULT_HOST,
        model: str = EMBED_MODEL,
        *,
        spec: EmbeddingSpec | None = None,
        normalization: str = "l2",
        model_revision: str | None = None,
    ) -> int:
        """Compatibility wrapper returning the number of new projections."""

        return self.ingest_transport_records_report(
            records,
            batch_size=batch_size,
            host=host,
            model=model,
            spec=spec,
            normalization=normalization,
            model_revision=model_revision,
        ).projected

    def search_report(
        self,
        query: str,
        limit: int = 5,
        host: str = DEFAULT_HOST,
        model: str = EMBED_MODEL,
        metric: str = "cosine",
        *,
        spec: EmbeddingSpec | None = None,
        filters: ProjectionFilter | None = None,
        project: str | None = None,
        trust: str | None = None,
        source: str | None = None,
        normalization: str = "l2",
        model_revision: str | None = None,
    ) -> SearchReport:
        """Search exactly one versioned index and expose failure state."""

        if metric != "cosine":
            raise ValueError("only cosine similarity is supported")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if filters is not None and any(value is not None for value in (project, trust, source)):
            raise ValueError("pass either filters or individual provenance filters")
        selected_filters = filters or ProjectionFilter(project, trust, source)
        if spec is not None:
            model = spec.model
            normalization = spec.normalization
            model_revision = spec.model_revision

        backend = self._backend(host)
        try:
            raw = backend.embed(
                [query],
                model=model,
                dimensions=spec.dimension if spec else None,
            )
        except EmbeddingUnavailableError as exc:
            status = self._status(
                "embedder_unavailable",
                f"embedding backend unavailable: {exc}",
                available=False,
                spec=spec,
            )
            return SearchReport(status, [], spec)
        except EmbeddingProtocolError as exc:
            status = self._status(
                "invalid_embedding_response",
                str(exc),
                available=False,
                spec=spec,
            )
            return SearchReport(status, [], spec)

        try:
            vectors, dimension = _validate_batch(
                raw,
                1,
                dimension=spec.dimension if spec else None,
                normalization=normalization,
            )
            resolved = self._resolved_spec(
                backend=backend,
                model=model,
                dimension=dimension,
                normalization=normalization,
                projector_version=EVENT_PROJECTOR_VERSION,
                model_revision=model_revision,
                requested=spec,
            )
        except (TypeError, ValueError) as exc:
            status = self._status(
                "invalid_embedding_response",
                str(exc),
                available=False,
                spec=spec,
            )
            return SearchReport(status, [], spec)

        index_row = self._conn.execute(
            "SELECT 1 FROM embedding_indexes WHERE index_id = ?",
            (resolved.index_id,),
        ).fetchone()
        if index_row is None:
            status = self._status(
                "index_unavailable",
                "no projections exist for the requested embedding specification",
                available=False,
                spec=resolved,
            )
            return SearchReport(status, [], resolved)

        clauses = ["p.index_id = ?"]
        parameters: list[Any] = [resolved.index_id]
        for column, value in (
            ("project", selected_filters.project),
            ("trust", selected_filters.trust),
            ("source", selected_filters.source),
        ):
            if value is not None:
                clauses.append(f"p.{column} = ?")
                parameters.append(value)
        sql = f"""
            SELECT s.*, p.embedding
            FROM event_projections AS p
            JOIN projection_sources AS s ON s.source_hash = p.source_hash
            WHERE {' AND '.join(clauses)}
        """

        query_vector = vectors[0]
        matches: list[tuple[AgentEvent, float]] = []
        try:
            for row in self._conn.execute(sql, parameters):
                stored = _coerce_vector(
                    _unpack_embedding(row["embedding"]),
                    dimension=resolved.dimension,
                )
                score = _cosine(query_vector, stored)
                event = AgentEvent(
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    content=row["content"],
                    timestamp=row["timestamp"],
                    metadata=json.loads(row["metadata_json"]),
                )
                matches.append((event, score))
        except (ValueError, json.JSONDecodeError) as exc:
            status = self._status(
                "invalid_index",
                f"stored projection is corrupt: {exc}",
                available=False,
                spec=resolved,
            )
            return SearchReport(status, [], resolved)

        matches.sort(key=lambda item: item[1], reverse=True)
        status = self._status(
            "ready",
            f"searched {len(matches)} matching projections",
            available=True,
            spec=resolved,
        )
        return SearchReport(status, matches[:limit], resolved)

    def search(
        self,
        query: str,
        limit: int = 5,
        host: str = DEFAULT_HOST,
        model: str = EMBED_MODEL,
        metric: str = "cosine",
        *,
        spec: EmbeddingSpec | None = None,
        filters: ProjectionFilter | None = None,
        project: str | None = None,
        trust: str | None = None,
        source: str | None = None,
        normalization: str = "l2",
        model_revision: str | None = None,
    ) -> list[tuple[AgentEvent, float]]:
        """Compatibility wrapper returning only matches."""

        return self.search_report(
            query,
            limit=limit,
            host=host,
            model=model,
            metric=metric,
            spec=spec,
            filters=filters,
            project=project,
            trust=trust,
            source=source,
            normalization=normalization,
            model_revision=model_revision,
        ).matches

    def list_indexes(self) -> list[EmbeddingSpec]:
        rows = self._conn.execute(
            "SELECT * FROM embedding_indexes ORDER BY created_at, index_id"
        ).fetchall()
        return [self._spec_from_row(row) for row in rows]

    def index_status(self, spec: EmbeddingSpec) -> IndexStatus:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM event_projections
            WHERE index_id = ?
            """,
            (spec.index_id,),
        ).fetchone()
        projection_count = int(row["count"])
        legacy_count = self.legacy_unversioned_count()
        if projection_count == 0:
            status = self._status(
                "index_unavailable",
                "no projections exist for the requested embedding specification",
                available=False,
                spec=spec,
            )
        else:
            status = self._status(
                "ready",
                f"{projection_count} projections available",
                available=True,
                spec=spec,
            )
        return IndexStatus(status, spec, projection_count, legacy_count)

    def legacy_unversioned_count(self) -> int:
        exists = self._conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'legacy_agent_events_v1'
            """
        ).fetchone()
        if exists is None:
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM legacy_agent_events_v1"
        ).fetchone()
        return int(row["count"])

    def close(self) -> None:
        self._conn.close()

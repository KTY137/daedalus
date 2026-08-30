# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Project the append-only memory journal into the versioned vector index.

The journal (``memory/events.local.jsonl``) is authoritative.  The vector index
is derived.  Nothing in the operational append path is allowed to block on an
embedding call, so this worker is the *only* component that is supposed to move
the index forward -- and, because it is, it is also the component that owns
:meth:`EventVectorStore.record_journal_watermark`.  Before it existed, every
search reported ``freshness == "unanchored"``: freshness unknown.

What this module actually guarantees
------------------------------------

* **Resumable.**  Progress is a byte offset into the journal, stored as a
  :class:`JournalPosition` watermark inside the index itself.  A run starts at
  the recorded watermark, never at zero, so restarting is cheap.
* **Idempotent, and not merely by luck.**  Two independent mechanisms stack:
  the index is content-addressed (``UNIQUE(index_id, source_hash)`` with
  ``INSERT OR IGNORE``), so a replayed entry *cannot* duplicate; and this worker
  filters entries whose ``source_hash`` is already in the index *before*
  embedding them, so a replay also costs nothing.  The filter is an
  optimisation; the uniqueness constraint is the correctness guarantee.  If the
  filter were wrong in the direction of "not yet projected", the result is
  redundant embedding work, never a duplicate row and never a lost entry.
* **Never ahead of itself.**  A watermark is recorded only after the projections
  for every journal byte below it are committed.  The crash window is therefore
  one batch wide and it always fails *behind*: a killed run leaves a watermark
  that under-reports what landed, and the next run re-reads those entries, finds
  them already projected, embeds nothing, and moves the watermark up.  The
  reverse -- a watermark ahead of the vectors -- is never written, because that
  would silently drop journal entries forever.
* **Append-only-ness is checked, not assumed.**  ``content_hash`` on the
  watermark is the SHA-256 of the journal prefix ``[0, position)``.  On every
  run that prefix is re-hashed.  A journal that was rewritten, truncated, or
  replaced fails the check and the run refuses with ``journal_forked`` instead
  of projecting a history that no longer matches the index.
* **Only complete lines are consumed.**  A trailing line with no ``\\n`` is a
  writer mid-append, not a record.  The watermark stops before it.  Consuming it
  would parse a fragment and then skip the real record forever.
* **Failure is reported, not smoothed over.**  ``embedder_unavailable`` is an
  outage: the run stops, keeps the watermark it earned, and exits non-zero so a
  retry is obviously the right move.  ``model_drift`` is a correctness fault
  that survives a retry: :mod:`daedalus.memory.embeddings` refuses *before*
  writing, and this worker neither catches that refusal nor advances past it.

The spec, and why ``model_revision`` defaults to unset
------------------------------------------------------

The worker resolves its :class:`EmbeddingSpec` **without calling the backend**:
either by adopting the one index already recorded for this
(provider, model, revision, normalization, projector) identity, or from the
declared ``dimension`` (default :data:`DEFAULT_DIMENSION`).  That is what makes
"a second run over an unchanged journal does zero embedding work" true rather
than approximately true -- a probe call to discover the dimension would break it.

``model_revision`` defaults to ``None`` on purpose.  The shipped reader,
``daedalus.context_plan.latent_memory_seed_scores``, searches with no spec, so
the spec it resolves has ``model_revision=None``.  Pinning a revision here
produces a *different* ``index_id``, and ``daedalus context --latent`` would
report ``index_unavailable`` against a perfectly good index.  The worker warns
when a revision is pinned.  Drift is still caught, empirically, by the identity
anchor in :mod:`daedalus.memory.embeddings` -- which is the control that works
regardless of what the declaration claims.

STATED LIMITS - promises this module does NOT keep
--------------------------------------------------

* **The pending backlog is held in memory.**  One run reads every unprojected
  complete line before batching.  ``--limit`` is the bound for a journal that
  has grown far beyond what one run should chew through; there is no streaming
  path.
* **Position is a byte offset, and only compares to byte offsets.**  A caller
  that measures the same journal in line counts and passes that as a
  :class:`JournalPosition` will get a meaningless freshness answer.  Use
  :func:`journal_position` on both sides.
* **A malformed or blank line is stepped over, not retried.**  Both are counted
  and named in the report, and the watermark advances past them, because the
  journal is append-only and a broken line will never become valid.  A silent
  ``skipped_malformed`` in a monitored run is a real finding, not noise.
* **Nothing here schedules anything.**  The index goes stale the moment the next
  event is appended.  Freshness is now *answerable*; keeping it fresh is a
  scheduling decision this module does not make.

Run it::

    python -m daedalus.memory.projection_worker --json
    python -m daedalus.memory.projection_worker --dry-run
    python -m daedalus.memory.projection_worker --limit 200
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.providers.ollama import DEFAULT_HOST

from . import EVENTS_PATH, VECTOR_DB_PATH, projection_event_from_record
from .embeddings import (
    EMBED_MODEL,
    EVENT_PROJECTOR_VERSION,
    AgentEvent,
    EmbeddingBackend,
    EmbeddingSpec,
    EventVectorStore,
    JournalPosition,
    OllamaEmbeddingBackend,
)
from .embeddings import _source_hash as projection_source_hash

#: Stable identity of the journal this index is derived from.  One journal_id
#: must always use one position measure; ours is a byte offset.
JOURNAL_ID = "memory/events.local.jsonl"

#: Output width of ``nomic-embed-text``, measured on both hosts.  Only used when
#: no index exists yet and the caller declared nothing; a backend that disagrees
#: fails loudly in ``_validate_batch`` rather than being padded or truncated.
DEFAULT_DIMENSION = 768

DEFAULT_BATCH_SIZE = 32

_HASH_CHUNK = 1 << 20
_TAIL_CHUNK = 1 << 16


class ProjectionWorkerError(RuntimeError):
    """Base class for refusals raised before any vector is written."""


class SpecConflictError(ProjectionWorkerError):
    """The declared spec disagrees with an index already in this database."""


# --------------------------------------------------------------------------
# Journal reading
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class JournalEntry:
    """One newline-terminated journal line and the byte offset just past it."""

    line_number: int
    start_offset: int
    end_offset: int
    raw: bytes
    record: Mapping[str, Any] | None
    error: str | None = None


def _prefix_hasher(path: Path, position: int) -> "hashlib._Hash | None":
    """Stream ``[0, position)`` into a live SHA-256, or ``None`` if it is short.

    The hasher is returned *live* so the caller can keep feeding it the lines it
    consumes.  That turns "hash of the journal prefix at this watermark" into an
    O(journal) cost for a whole run instead of O(journal x batches).
    """

    hasher = hashlib.sha256()
    remaining = position
    if remaining == 0:
        return hasher
    with path.open("rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(_HASH_CHUNK, remaining))
            if not chunk:
                # The journal is shorter than the watermark: truncated, rotated
                # or replaced.  Refusing is the only sound answer.
                return None
            hasher.update(chunk)
            remaining -= len(chunk)
    return hasher


def complete_prefix_end(path: Path) -> int:
    """Byte offset just past the last newline-terminated line.

    Bytes after this point are a partial line -- a writer mid-append -- and are
    deliberately not journal content yet.
    """

    size = path.stat().st_size
    if size == 0:
        return 0
    with path.open("rb") as handle:
        position = size
        while position > 0:
            read_at = max(0, position - _TAIL_CHUNK)
            handle.seek(read_at)
            chunk = handle.read(position - read_at)
            index = chunk.rfind(b"\n")
            if index >= 0:
                return read_at + index + 1
            position = read_at
    return 0


def journal_position(
    path: str | Path = EVENTS_PATH,
    journal_id: str = JOURNAL_ID,
) -> JournalPosition:
    """The journal's current position, in the measure this worker records.

    Callers that want an honest ``freshness`` out of
    :meth:`EventVectorStore.search_report` must pass *this* value: a watermark
    and an observation only compare if they use the same measure.
    """

    resolved = Path(path)
    if not resolved.exists():
        return JournalPosition(journal_id, 0, hashlib.sha256(b"").hexdigest())
    end = complete_prefix_end(resolved)
    hasher = _prefix_hasher(resolved, end)
    if hasher is None:  # pragma: no cover - the file shrank between two calls
        return JournalPosition(journal_id, 0, hashlib.sha256(b"").hexdigest())
    return JournalPosition(journal_id, end, hasher.hexdigest())


def scan_journal(
    path: Path,
    start: int,
    limit: int | None = None,
) -> list[JournalEntry]:
    """Read complete lines from ``start``, at most ``limit`` of them."""

    entries: list[JournalEntry] = []
    offset = start
    line_number = 0
    with path.open("rb") as handle:
        handle.seek(start)
        for raw in handle:
            if not raw.endswith(b"\n"):
                break  # partial trailing line: not a record yet
            line_number += 1
            end = offset + len(raw)
            record: Mapping[str, Any] | None = None
            error: str | None = None
            text = ""
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                error = f"undecodable line: {exc}"
            if error is None and text.strip():
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    error = f"malformed JSON: {exc}"
                else:
                    if isinstance(parsed, dict):
                        record = parsed
                    else:
                        error = "journal line is not a JSON object"
            entries.append(
                JournalEntry(
                    line_number=line_number,
                    start_offset=offset,
                    end_offset=end,
                    raw=raw,
                    record=record,
                    error=error,
                )
            )
            offset = end
            if limit is not None and len(entries) >= limit:
                break
    return entries


# --------------------------------------------------------------------------
# Read-only view of the index
# --------------------------------------------------------------------------
#
# These read the schema owned by ``embeddings.py`` through a separate read-only
# connection rather than reaching into ``EventVectorStore._conn``.  They exist
# because there is no public "has this event already been projected?" API, and
# because ``--dry-run`` must be able to answer that question without creating
# the database.


def _ro_connect(db_path: str | Path) -> sqlite3.Connection | None:
    if str(db_path) == ":memory:":
        return None
    resolved = Path(db_path)
    if not resolved.exists():
        return None
    try:
        conn = sqlite3.connect(resolved.absolute().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _stored_specs(conn: sqlite3.Connection | None) -> list[EmbeddingSpec]:
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT provider, model, model_revision, dimension, normalization,
                   projector_version
            FROM embedding_indexes ORDER BY created_at, index_id
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    specs: list[EmbeddingSpec] = []
    for row in rows:
        try:
            specs.append(
                EmbeddingSpec(
                    provider=row["provider"],
                    model=row["model"],
                    model_revision=row["model_revision"],
                    dimension=int(row["dimension"]),
                    normalization=row["normalization"],
                    projector_version=row["projector_version"],
                )
            )
        except ValueError:  # pragma: no cover - corrupt metadata row
            continue
    return specs


def _stored_source_hashes(conn: sqlite3.Connection | None, index_id: str) -> set[str]:
    if conn is None:
        return set()
    try:
        rows = conn.execute(
            "SELECT source_hash FROM event_projections WHERE index_id = ?",
            (index_id,),
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row["source_hash"]) for row in rows}


def _stored_watermark(
    conn: sqlite3.Connection | None,
    index_id: str,
    journal_id: str,
) -> JournalPosition | None:
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT position, content_hash FROM projection_watermarks
            WHERE index_id = ? AND journal_id = ?
            """,
            (index_id, journal_id),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return JournalPosition(
        journal_id=journal_id,
        position=int(row["position"]),
        content_hash=row["content_hash"],
    )


# --------------------------------------------------------------------------
# Spec resolution
# --------------------------------------------------------------------------


def resolve_spec(
    stored: Sequence[EmbeddingSpec],
    *,
    model: str,
    dimension: int | None,
    normalization: str = "l2",
    model_revision: str | None = None,
    provider: str = "ollama",
    projector_version: str = EVENT_PROJECTOR_VERSION,
) -> EmbeddingSpec:
    """Pick the index to write to without asking the backend anything.

    ``dimension=None`` means "adopt whatever this database already uses for this
    identity", which is what keeps a repeat run free of backend calls.  An
    explicitly declared dimension that disagrees with a stored index is a
    refusal, not a second index: silently forking the coordinate system is the
    failure this whole module exists to avoid.
    """

    identity = (provider, model, model_revision, normalization, projector_version)
    siblings = [
        spec
        for spec in stored
        if (
            spec.provider,
            spec.model,
            spec.model_revision,
            spec.normalization,
            spec.projector_version,
        )
        == identity
    ]
    if dimension is None:
        if not siblings:
            return EmbeddingSpec(
                provider=provider,
                model=model,
                model_revision=model_revision,
                dimension=DEFAULT_DIMENSION,
                normalization=normalization,
                projector_version=projector_version,
            )
        if len(siblings) == 1:
            return siblings[0]
        widths = sorted({spec.dimension for spec in siblings})
        raise SpecConflictError(
            f"this database holds {len(siblings)} indexes for provider={provider!r} "
            f"model={model!r} model_revision={model_revision!r} that differ only in "
            f"dimension ({widths}); pass --dimension to say which one to extend"
        )
    conflicting = [spec for spec in siblings if spec.dimension != dimension]
    if conflicting:
        widths = sorted({spec.dimension for spec in conflicting})
        raise SpecConflictError(
            f"declared dimension {dimension} conflicts with the existing index for "
            f"provider={provider!r} model={model!r} model_revision={model_revision!r}, "
            f"which is {widths}; writing anyway would fork the coordinate system "
            "under one model name"
        )
    return EmbeddingSpec(
        provider=provider,
        model=model,
        model_revision=model_revision,
        dimension=dimension,
        normalization=normalization,
        projector_version=projector_version,
    )


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerReport:
    """Everything a reader needs to tell "did nothing" from "could not"."""

    status: str
    message: str
    ok: bool
    journal_id: str
    journal_path: str
    db_path: str
    live_position: int
    start_position: int
    watermark_position: int
    entries_scanned: int = 0
    entries_projected: int = 0
    entries_already_projected: int = 0
    entries_skipped_blank: int = 0
    entries_skipped_malformed: int = 0
    embed_calls: int = 0
    spec: Mapping[str, Any] | None = None
    index_id: str | None = None
    projection_count: int = 0
    identity_anchor: str = "missing"
    freshness: str = "unanchored"
    elapsed_seconds: float = 0.0
    warnings: tuple[str, ...] = ()
    malformed_lines: tuple[int, ...] = ()

    @property
    def behind_bytes(self) -> int:
        return max(0, self.live_position - self.watermark_position)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "ok": self.ok,
            "journal": {
                "journal_id": self.journal_id,
                "path": self.journal_path,
                "live_position": self.live_position,
                "start_position": self.start_position,
                "watermark_position": self.watermark_position,
                "behind_bytes": self.behind_bytes,
            },
            "entries": {
                "scanned": self.entries_scanned,
                "projected": self.entries_projected,
                "already_projected": self.entries_already_projected,
                "skipped_blank": self.entries_skipped_blank,
                "skipped_malformed": self.entries_skipped_malformed,
                "malformed_lines": list(self.malformed_lines),
            },
            "index": {
                "db_path": self.db_path,
                "index_id": self.index_id,
                "spec": dict(self.spec) if self.spec else None,
                "projection_count": self.projection_count,
                "identity_anchor": self.identity_anchor,
                "freshness": self.freshness,
            },
            "embed_calls": self.embed_calls,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------
# The worker
# --------------------------------------------------------------------------


@dataclass
class _Progress:
    scanned: int = 0
    projected: int = 0
    already: int = 0
    blank: int = 0
    malformed: int = 0
    embed_calls: int = 0
    malformed_lines: list[int] = field(default_factory=list)


class ProjectionWorker:
    """Move the derived vector index forward to match the authoritative journal."""

    def __init__(
        self,
        *,
        journal: str | Path = EVENTS_PATH,
        db_path: str | Path = VECTOR_DB_PATH,
        journal_id: str = JOURNAL_ID,
        host: str = DEFAULT_HOST,
        model: str = EMBED_MODEL,
        dimension: int | None = None,
        normalization: str = "l2",
        model_revision: str | None = None,
        backend: EmbeddingBackend | None = None,
        timeout: float = 60.0,
    ):
        self.journal = Path(journal)
        self.db_path = db_path
        self.journal_id = journal_id
        self.host = host
        self.model = model
        self.dimension = dimension
        self.normalization = normalization
        self.model_revision = model_revision
        # A batch is one HTTP request.  ``EventVectorStore``'s implicit backend
        # times out at 10s, which a batch of 32 real journal entries can exceed
        # on a cold model -- and a timeout is reported as ``embedder_unavailable``,
        # i.e. an outage that never happened.  Own the backend so the timeout is
        # a stated parameter rather than an accident of batch size.
        self.backend = backend or OllamaEmbeddingBackend(host, timeout=timeout)

    # -- helpers ---------------------------------------------------------

    def _provider(self) -> str:
        return str(getattr(self.backend, "provider", "ollama"))

    def _warnings(self, spec: EmbeddingSpec) -> tuple[str, ...]:
        warnings: list[str] = []
        if spec.model_revision:
            warnings.append(
                "model_revision is pinned, so this index_id differs from the one "
                "`daedalus context --latent` searches (that reader resolves a spec "
                "with model_revision=None). The latent half will report "
                "index_unavailable against this index."
            )
        return tuple(warnings)

    def _report(
        self,
        status: str,
        message: str,
        *,
        ok: bool,
        started: float,
        live: JournalPosition,
        start: int,
        watermark: int,
        progress: _Progress | None = None,
        spec: EmbeddingSpec | None = None,
        projection_count: int = 0,
        identity_anchor: str = "missing",
        freshness: str = "unanchored",
        warnings: tuple[str, ...] = (),
    ) -> WorkerReport:
        counts = progress or _Progress()
        return WorkerReport(
            status=status,
            message=message,
            ok=ok,
            journal_id=self.journal_id,
            journal_path=str(self.journal),
            db_path=str(self.db_path),
            live_position=live.position,
            start_position=start,
            watermark_position=watermark,
            entries_scanned=counts.scanned,
            entries_projected=counts.projected,
            entries_already_projected=counts.already,
            entries_skipped_blank=counts.blank,
            entries_skipped_malformed=counts.malformed,
            embed_calls=counts.embed_calls,
            spec=spec.to_dict() if spec else None,
            index_id=spec.index_id if spec else None,
            projection_count=projection_count,
            identity_anchor=identity_anchor,
            freshness=freshness,
            elapsed_seconds=time.perf_counter() - started,
            warnings=warnings,
            malformed_lines=tuple(counts.malformed_lines),
        )

    # -- the run ---------------------------------------------------------

    def run(
        self,
        *,
        limit: int | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dry_run: bool = False,
    ) -> WorkerReport:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        started = time.perf_counter()
        empty = JournalPosition(self.journal_id, 0, hashlib.sha256(b"").hexdigest())

        if not self.journal.exists():
            return self._report(
                "journal_missing",
                f"journal does not exist: {self.journal}",
                ok=False,
                started=started,
                live=empty,
                start=0,
                watermark=0,
            )

        live = journal_position(self.journal, self.journal_id)

        store: EventVectorStore | None = None
        if not dry_run:
            store = EventVectorStore(self.db_path, backend=self.backend)
        try:
            conn = _ro_connect(self.db_path)
            try:
                stored_specs = _stored_specs(conn)
                try:
                    spec = resolve_spec(
                        stored_specs,
                        model=self.model,
                        dimension=self.dimension,
                        normalization=self.normalization,
                        model_revision=self.model_revision,
                        provider=self._provider(),
                    )
                except SpecConflictError as exc:
                    return self._report(
                        "spec_conflict",
                        str(exc),
                        ok=False,
                        started=started,
                        live=live,
                        start=0,
                        watermark=0,
                    )
                watermark = _stored_watermark(conn, spec.index_id, self.journal_id)
                projected_hashes = _stored_source_hashes(conn, spec.index_id)
            finally:
                if conn is not None:
                    conn.close()

            warnings = self._warnings(spec)
            start = watermark.position if watermark is not None else 0

            # Append-only check.  The recorded content_hash covers the journal
            # prefix below the watermark; if that prefix no longer reproduces,
            # the index was derived from a history this file no longer has.
            hasher = _prefix_hasher(self.journal, start)
            if hasher is None:
                return self._report(
                    "journal_forked",
                    f"journal {self.journal_id!r} is only {live.position} bytes but "
                    f"the index is watermarked at {start}; it was truncated, rotated "
                    "or replaced. Re-index this spec instead of appending to a "
                    "history that no longer exists.",
                    ok=False,
                    started=started,
                    live=live,
                    start=start,
                    watermark=start,
                    spec=spec,
                    warnings=warnings,
                )
            if (
                watermark is not None
                and watermark.content_hash is not None
                and hasher.hexdigest() != watermark.content_hash
            ):
                return self._report(
                    "journal_forked",
                    f"journal {self.journal_id!r} does not reproduce the content hash "
                    f"recorded at position {start}; the authoritative journal was "
                    "rewritten, so the projections below that point no longer "
                    "describe it. Re-index this spec.",
                    ok=False,
                    started=started,
                    live=live,
                    start=start,
                    watermark=start,
                    spec=spec,
                    warnings=warnings,
                )

            entries = scan_journal(self.journal, start, limit)
            progress = _Progress()
            watermark_position = start
            failure: str | None = None
            failure_message = ""

            for index in range(0, len(entries), batch_size):
                chunk = entries[index : index + batch_size]
                pending_hasher = hasher.copy()
                for entry in chunk:
                    pending_hasher.update(entry.raw)

                batch_events: list[AgentEvent] = []
                batch_hashes: list[str] = []
                for entry in chunk:
                    if entry.record is None:
                        progress.malformed += 1
                        progress.malformed_lines.append(entry.line_number)
                        continue
                    event = projection_event_from_record(entry.record)
                    if not str(event.content).strip():
                        progress.blank += 1
                        continue
                    source_hash = projection_source_hash(event)
                    if source_hash in projected_hashes:
                        progress.already += 1
                        continue
                    batch_events.append(event)
                    batch_hashes.append(source_hash)

                if batch_events and not dry_run:
                    assert store is not None
                    progress.embed_calls += 1
                    ingest = store.ingest_events_report(
                        batch_events,
                        batch_size=len(batch_events),
                        host=self.host,
                        spec=spec,
                    )
                    if not ingest.status.available:
                        # Stop here.  Everything below ``watermark_position`` is
                        # committed and recorded; this batch is not, and the
                        # watermark must not claim otherwise.
                        failure = ingest.status.code
                        failure_message = ingest.status.message
                        break
                    progress.projected += ingest.projected
                    projected_hashes.update(batch_hashes)
                elif batch_events and dry_run:
                    progress.projected += len(batch_events)

                progress.scanned += len(chunk)
                hasher = pending_hasher
                watermark_position = chunk[-1].end_offset
                if not dry_run:
                    assert store is not None
                    store.record_journal_watermark(
                        spec,
                        JournalPosition(
                            self.journal_id,
                            watermark_position,
                            hasher.hexdigest(),
                        ),
                    )

            if dry_run:
                return self._report(
                    "dry_run",
                    (
                        f"would project {progress.projected} of {progress.scanned} "
                        f"journal entries from position {start} and would move the "
                        f"watermark to {watermark_position} of {live.position}"
                    ),
                    ok=True,
                    started=started,
                    live=live,
                    start=start,
                    watermark=watermark_position,
                    progress=progress,
                    spec=spec,
                    # Read from the index, not defaulted: a dry run reporting
                    # "0 projections" against an index holding thousands reads
                    # as a broken index rather than as an unasked question.
                    projection_count=len(projected_hashes),
                    identity_anchor="not_checked",
                    warnings=warnings,
                )

            assert store is not None
            status_report = store.index_status(spec, live)
            if failure is not None:
                return self._report(
                    failure,
                    (
                        f"stopped after {progress.projected} projections: "
                        f"{failure_message}"
                    ),
                    ok=False,
                    started=started,
                    live=live,
                    start=start,
                    watermark=watermark_position,
                    progress=progress,
                    spec=spec,
                    projection_count=status_report.projection_count,
                    identity_anchor=status_report.identity_anchor,
                    freshness=status_report.freshness,
                    warnings=warnings,
                )

            if progress.scanned == 0:
                return self._report(
                    "up_to_date",
                    (
                        f"index already reflects journal {self.journal_id!r} at "
                        f"position {watermark_position}"
                    ),
                    ok=True,
                    started=started,
                    live=live,
                    start=start,
                    watermark=watermark_position,
                    progress=progress,
                    spec=spec,
                    projection_count=status_report.projection_count,
                    identity_anchor=status_report.identity_anchor,
                    freshness=status_report.freshness,
                    warnings=warnings,
                )

            return self._report(
                "ready",
                (
                    f"projected {progress.projected} new entries "
                    f"({progress.already} already projected, {progress.blank} blank, "
                    f"{progress.malformed} malformed) and moved the watermark to "
                    f"{watermark_position} of {live.position}"
                ),
                ok=True,
                started=started,
                live=live,
                start=start,
                watermark=watermark_position,
                progress=progress,
                spec=spec,
                projection_count=status_report.projection_count,
                identity_anchor=status_report.identity_anchor,
                freshness=status_report.freshness,
                warnings=warnings,
            )
        finally:
            if store is not None:
                store.close()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _format_human(report: WorkerReport) -> str:
    spec = report.spec or {}
    revision = spec.get("model_revision") or "<unpinned>"
    lines = [
        f"PROJECTION WORKER  {report.status}",
        f"  {report.message}",
        (
            f"  journal   {report.journal_id}  start={report.start_position} "
            f"watermark={report.watermark_position} live={report.live_position} "
            f"behind={report.behind_bytes}B ({report.freshness})"
        ),
        (
            f"  index     {report.index_id}  "
            f"{spec.get('provider')}/{spec.get('model')} rev={revision} "
            f"dim={spec.get('dimension')} norm={spec.get('normalization')} "
            f"anchor={report.identity_anchor} projections={report.projection_count}"
        ),
        (
            f"  entries   scanned={report.entries_scanned} "
            f"projected={report.entries_projected} "
            f"already={report.entries_already_projected} "
            f"blank={report.entries_skipped_blank} "
            f"malformed={report.entries_skipped_malformed}"
        ),
        f"  embed     {report.embed_calls} backend calls in "
        f"{report.elapsed_seconds:.2f}s",
    ]
    for warning in report.warnings:
        lines.append(f"  WARNING   {warning}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    # THE BOUNDARY COMES FIRST -- above parse_args, the c67fd116 shape, so
    # both doors pass it: `daedalus project-memory` through cli.main's
    # dispatch and `python -m daedalus.memory.projection_worker` around it.
    # Above --dry-run too, deliberately: a run that only starts centrally on
    # some argument vectors is guarded by its caller, not by this function.
    #
    # The projection writes a versioned sqlite index and POSTs journal text to
    # an embedding host. The POST has its own row (memory.embeddings) taking
    # the endpoint-admission decision at the socket; this is the START of the
    # run above it, not a second copy of that decision.
    from ..budget import process_guard_boundary_decision
    from ..spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.project_memory",
        REGISTRY_BY_ID["cli.project_memory"].effects,
        (process_guard_boundary_decision(),),
    )

    parser = argparse.ArgumentParser(
        prog="python -m daedalus.memory.projection_worker",
        description=(
            "Project the append-only memory journal into the versioned vector "
            "index and record the journal watermark that makes search freshness "
            "answerable."
        ),
    )
    parser.add_argument("--journal", default=str(EVENTS_PATH))
    parser.add_argument("--db", default=str(VECTOR_DB_PATH))
    parser.add_argument("--journal-id", default=JOURNAL_ID)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--model", default=EMBED_MODEL)
    parser.add_argument(
        "--dimension",
        type=int,
        default=None,
        help=(
            "declare the embedding width; default adopts the existing index or "
            f"{DEFAULT_DIMENSION} for a new one"
        ),
    )
    parser.add_argument(
        "--model-revision",
        default=None,
        help=(
            "pin a model digest. WARNING: this changes index_id, and the shipped "
            "`daedalus context --latent` reader searches with no revision"
        ),
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="per-batch HTTP timeout in seconds; one batch is one request",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many journal entries; the run stays resumable",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be projected; touches no backend and creates no database",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    worker = ProjectionWorker(
        journal=args.journal,
        db_path=args.db,
        journal_id=args.journal_id,
        host=args.host,
        model=args.model,
        dimension=args.dimension,
        model_revision=args.model_revision,
        timeout=args.timeout,
    )
    report = worker.run(
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_format_human(report))
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

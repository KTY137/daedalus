# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Adversarial tests for the memory -> vector-index projection worker.

Every embedding in this file comes from a deterministic fake -- either an
in-process backend object or, for the subprocess kill test, a tiny local HTTP
stub that speaks Ollama's ``/api/embed`` shape.  Nothing here touches a real
model or the network.  The live demonstration is run separately by hand.

The tests are written around the failure modes, not the happy path: a worker
that only works when nothing goes wrong is a worker that silently loses journal
entries the first time something does.
"""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from daedalus.memory.embeddings import (
    EmbeddingSpec,
    EmbeddingUnavailableError,
    EventVectorStore,
    JournalPosition,
)
from daedalus.memory.projection_worker import (
    DEFAULT_DIMENSION,
    JOURNAL_ID,
    ProjectionWorker,
    SpecConflictError,
    complete_prefix_end,
    journal_position,
    resolve_spec,
    scan_journal,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL = "fake-embed"
DIMENSION = 8


# --------------------------------------------------------------------------
# Deterministic fakes
# --------------------------------------------------------------------------


def _deterministic_vector(weights: str, text: str, dimension: int) -> list[float]:
    """A pure function of (weights, text).  ``weights`` stands in for the model."""

    digest = hashlib.sha256(f"{weights}\0{text}".encode("utf-8")).digest()
    values = [(digest[i] / 255.0) - 0.5 for i in range(dimension)]
    if not any(values):  # pragma: no cover - a zero vector cannot be indexed
        values[0] = 1.0
    return values


class FakeBackend:
    """Counts every call, so "did no embedding work" is an assertion."""

    provider = "ollama"

    def __init__(
        self,
        *,
        weights: str = "v1",
        dimension: int = DIMENSION,
        fail_from: int | None = None,
    ):
        self.weights = weights
        self.dimension = dimension
        self.fail_from = fail_from
        self.calls = 0
        self.embedded: list[str] = []

    def embed(self, texts, *, model, dimensions=None):
        self.calls += 1
        if self.fail_from is not None and self.calls >= self.fail_from:
            raise EmbeddingUnavailableError("connection refused (test)")
        self.embedded.extend(texts)
        return [_deterministic_vector(self.weights, text, self.dimension) for text in texts]


class ConstantBackend(FakeBackend):
    """Every text lands on the same unit vector, so every event matches."""

    def embed(self, texts, *, model, dimensions=None):
        self.calls += 1
        self.embedded.extend(texts)
        return [[1.0] + [0.0] * (self.dimension - 1) for _ in texts]


class _EmbedHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        texts = payload.get("input") or []
        self.server.served += 1  # type: ignore[attr-defined]
        if self.server.delay:  # type: ignore[attr-defined]
            time.sleep(self.server.delay)  # type: ignore[attr-defined]
        body = json.dumps(
            {
                "embeddings": [
                    _deterministic_vector("v1", text, DIMENSION) for text in texts
                ]
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: A003 - silence the stdlib access log
        return


class StubEmbedServer:
    """A local Ollama-shaped ``/api/embed`` stub.  No model, no network."""

    def __init__(self, delay: float = 0.0):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _EmbedHandler)
        self.httpd.served = 0  # type: ignore[attr-defined]
        self.httpd.delay = delay  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def served(self) -> int:
        return self.httpd.served  # type: ignore[attr-defined]

    def set_delay(self, delay: float) -> None:
        self.httpd.delay = delay  # type: ignore[attr-defined]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


def make_record(index: int, *, paths=(), summary: str | None = None) -> dict:
    return {
        "time": f"2026-07-29T00:00:{index:02d}+00:00",
        "kind": "manual",
        "source": "test",
        "repo_root": None,
        "project": None,
        "trust": None,
        "task_id": None,
        "status": "open",
        "summary": f"journal entry number {index}" if summary is None else summary,
        "todos": [],
        "paths": list(paths),
        "payload": {},
    }


def write_journal(path: Path, records) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def append_journal(path: Path, records) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def projection_rows(db_path: Path) -> tuple[int, int]:
    """(total rows, distinct source hashes) -- they must be equal, always."""

    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM event_projections").fetchone()[0]
        distinct = conn.execute(
            "SELECT COUNT(DISTINCT source_hash) FROM event_projections"
        ).fetchone()[0]
    finally:
        conn.close()
    return int(total), int(distinct)


def index_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM embedding_indexes").fetchone()[0])
    finally:
        conn.close()


@pytest.fixture()
def journal(tmp_path: Path) -> Path:
    path = tmp_path / "events.local.jsonl"
    write_journal(path, [make_record(i) for i in range(1, 7)])
    return path


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return tmp_path / "vectors.db"


def make_worker(journal: Path, db: Path, backend, **kwargs) -> ProjectionWorker:
    options = {
        "journal": journal,
        "db_path": db,
        "model": MODEL,
        "dimension": DIMENSION,
        "backend": backend,
    }
    options.update(kwargs)
    return ProjectionWorker(**options)


# --------------------------------------------------------------------------
# Journal reading
# --------------------------------------------------------------------------


def test_journal_position_ignores_a_partial_trailing_line(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    write_journal(path, [make_record(1), make_record(2)])
    complete = journal_position(path).position
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"time": "2026-07-29T00:00:03+00:00", "kind": "man')
    assert path.stat().st_size > complete
    assert journal_position(path).position == complete
    assert complete_prefix_end(path) == complete


def test_scan_journal_reports_offsets_and_malformed_lines(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(make_record(1)) + "\n" + "{not json\n" + json.dumps(make_record(2)) + "\n",
        encoding="utf-8",
    )
    entries = scan_journal(path, 0, None)
    assert [entry.line_number for entry in entries] == [1, 2, 3]
    assert entries[1].record is None and "malformed JSON" in entries[1].error
    assert entries[-1].end_offset == path.stat().st_size


# --------------------------------------------------------------------------
# Happy path, incrementality, and the reader contract
# --------------------------------------------------------------------------


def test_first_run_projects_every_entry_and_records_the_watermark(journal, db):
    backend = FakeBackend()
    report = make_worker(journal, db, backend).run(batch_size=2)

    assert report.status == "ready" and report.ok
    assert report.entries_scanned == 6
    assert report.entries_projected == 6
    assert report.freshness == "fresh"
    assert report.watermark_position == journal_position(journal).position
    assert projection_rows(db) == (6, 6)

    # The watermark is what makes freshness answerable at all.
    store = EventVectorStore(db, backend=backend)
    try:
        spec = EmbeddingSpec(model=MODEL, dimension=DIMENSION)
        recorded = store.journal_watermark(spec, JOURNAL_ID)
        assert recorded is not None
        assert recorded.position == journal_position(journal).position
        assert recorded.content_hash == journal_position(journal).content_hash
        assert store.journal_freshness(spec, journal_position(journal)).code == "fresh"
    finally:
        store.close()


def test_second_run_over_an_unchanged_journal_does_no_embedding_work(journal, db):
    make_worker(journal, db, FakeBackend()).run(batch_size=2)

    fresh_backend = FakeBackend()
    report = make_worker(journal, db, fresh_backend).run(batch_size=2)

    # GUARD: incrementality.  Two independent assertions, because they fail for
    # different reasons -- ``scanned == 0`` proves the watermark start offset is
    # honoured, ``calls == 0`` proves nothing was embedded by any other route.
    assert report.entries_scanned == 0
    assert fresh_backend.calls == 0
    assert report.status == "up_to_date" and report.ok
    assert report.freshness == "fresh"
    assert projection_rows(db) == (6, 6)


def test_appending_to_the_journal_makes_a_search_report_stale_until_the_worker_runs(
    journal, db
):
    backend = ConstantBackend()
    make_worker(journal, db, backend).run(batch_size=3)
    spec = EmbeddingSpec(model=MODEL, dimension=DIMENSION)

    append_journal(journal, [make_record(7)])
    store = EventVectorStore(db, backend=backend)
    try:
        stale = store.search_report(
            "anything", model=MODEL, spec=spec, journal=journal_position(journal)
        )
        assert stale.freshness == "stale"
        assert stale.status.code == "stale"
    finally:
        store.close()

    make_worker(journal, db, ConstantBackend()).run(batch_size=3)
    store = EventVectorStore(db, backend=backend)
    try:
        after = store.search_report(
            "anything", model=MODEL, spec=spec, journal=journal_position(journal)
        )
        assert after.freshness == "fresh"
        assert after.status.code == "ready"
    finally:
        store.close()


def test_the_worker_writes_the_index_the_context_planner_actually_searches(
    tmp_path: Path, db
):
    """The whole point: `daedalus context --latent` must find this index.

    ``latent_memory_seed_scores`` searches with no ``EmbeddingSpec``, so the spec
    it resolves has ``model_revision=None``.  A worker that pinned a revision
    would build a perfectly good index the shipped reader cannot see.
    """

    from daedalus.context_plan import latent_memory_seed_scores
    from daedalus.structcore import build_index, build_knowledge_forest

    repo = tmp_path / "repo"
    (repo / "daedalus").mkdir(parents=True)
    (repo / "daedalus" / "widget.py").write_text(
        "def widget():\n    return 1\n", encoding="utf-8"
    )
    (repo / "daedalus" / "other.py").write_text("x = 2\n", encoding="utf-8")

    journal = tmp_path / "events.jsonl"
    write_journal(
        journal,
        [
            make_record(1, summary="fixed the widget", paths=["daedalus/widget.py"]),
            make_record(2, summary="unrelated bookkeeping"),
        ],
    )

    report = make_worker(journal, db, ConstantBackend()).run()
    assert report.status == "ready"

    forest = build_knowledge_forest(build_index(repo))
    latent = latent_memory_seed_scores(
        forest,
        "what happened to the widget",
        db_path=db,
        model=MODEL,
        backend=ConstantBackend(),
    )
    assert latent.status == "ready", latent.message
    assert latent.index_id == report.index_id
    assert "daedalus/widget.py" in latent.scores


# --------------------------------------------------------------------------
# GUARD: resumability across a crash
# --------------------------------------------------------------------------


def test_a_crash_between_embedding_and_the_watermark_neither_duplicates_nor_skips(
    journal, db, monkeypatch
):
    """The interesting window, hit exactly.

    The first batch's vectors are committed and then the process dies before its
    watermark is recorded.  A correct worker must re-read those entries, notice
    they are already projected, embed none of them again, and finish the rest.
    """

    original = EventVectorStore.record_journal_watermark
    state = {"calls": 0}

    def killed_before_recording(self, spec, position):
        state["calls"] += 1
        if state["calls"] == 1:
            raise KeyboardInterrupt("hard kill between embed and record")
        return original(self, spec, position)

    monkeypatch.setattr(
        EventVectorStore, "record_journal_watermark", killed_before_recording
    )
    with pytest.raises(KeyboardInterrupt):
        make_worker(journal, db, FakeBackend()).run(batch_size=2)

    # Committed vectors, no watermark: the index under-reports itself.
    assert projection_rows(db) == (2, 2)
    monkeypatch.undo()

    resumed_backend = FakeBackend()
    report = make_worker(journal, db, resumed_backend).run(batch_size=2)

    assert report.entries_already_projected == 2
    assert report.entries_projected == 4
    # 1 identity-anchor re-embed on reopening the index + one call per batch that
    # still had work.  The already-projected batch costs ZERO calls.
    assert resumed_backend.calls == 3
    assert projection_rows(db) == (6, 6)
    assert report.watermark_position == journal_position(journal).position
    assert report.freshness == "fresh"


def test_a_killed_worker_process_resumes_without_loss_or_duplication(tmp_path: Path):
    """Same invariant, but the interruption is a real process kill."""

    server = StubEmbedServer(delay=0.15)
    try:
        journal = tmp_path / "events.jsonl"
        records = [make_record(i) for i in range(1, 21)]
        write_journal(journal, records)

        killed_db = tmp_path / "killed.db"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "daedalus.memory.projection_worker",
                "--journal",
                str(journal),
                "--db",
                str(killed_db),
                "--host",
                server.url,
                "--model",
                MODEL,
                "--dimension",
                str(DIMENSION),
                "--batch-size",
                "1",
                "--json",
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.time() + 30
            while server.served < 3 and time.time() < deadline:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            proc.kill()
        finally:
            proc.wait(timeout=30)

        committed, distinct = projection_rows(killed_db)
        assert committed == distinct
        assert 0 < committed < len(records), (
            f"the kill did not land mid-run (committed {committed} of {len(records)})"
        )

        server.set_delay(0.0)
        report = ProjectionWorker(
            journal=journal,
            db_path=killed_db,
            model=MODEL,
            dimension=DIMENSION,
            host=server.url,
        ).run(batch_size=4)

        assert report.status == "ready" and report.ok
        assert projection_rows(killed_db) == (len(records), len(records))
        assert report.watermark_position == journal_position(journal).position
        assert report.freshness == "fresh"

        # A clean run from scratch must land in exactly the same place.
        reference_db = tmp_path / "reference.db"
        ProjectionWorker(
            journal=journal,
            db_path=reference_db,
            model=MODEL,
            dimension=DIMENSION,
            host=server.url,
        ).run(batch_size=4)
        assert projection_rows(reference_db) == projection_rows(killed_db)
    finally:
        server.close()


# --------------------------------------------------------------------------
# GUARD: honest failure
# --------------------------------------------------------------------------


def test_a_backend_outage_stops_and_leaves_a_watermark_for_what_landed(journal, db):
    entries = scan_journal(journal, 0, None)
    backend = FakeBackend(fail_from=2)
    report = make_worker(journal, db, backend).run(batch_size=2)

    assert report.status == "embedder_unavailable"
    assert report.ok is False
    assert report.entries_projected == 2
    # GUARD: the watermark names what actually landed -- the end of batch one --
    # and never the end of the journal.
    assert report.watermark_position == entries[1].end_offset
    assert report.freshness == "stale"
    assert projection_rows(db) == (2, 2)

    healthy = FakeBackend()
    resumed = make_worker(journal, db, healthy).run(batch_size=2)
    assert resumed.status == "ready"
    assert resumed.entries_projected == 4
    assert resumed.entries_already_projected == 0
    assert projection_rows(db) == (6, 6)
    assert resumed.freshness == "fresh"


def test_model_drift_refuses_and_contributes_no_vector(journal, db):
    make_worker(journal, db, FakeBackend(weights="v1")).run(batch_size=3)
    before_rows = projection_rows(db)
    before = make_worker(journal, db, FakeBackend(weights="v1")).run()
    watermark_before = before.watermark_position

    append_journal(journal, [make_record(7)])
    drifted = FakeBackend(weights="v2")
    report = make_worker(journal, db, drifted).run(batch_size=3)

    # GUARD: a drifted backend contributes nothing, and the watermark does not
    # move -- otherwise the un-projected entry would be skipped forever.
    assert report.status == "model_drift"
    assert report.ok is False
    assert report.entries_projected == 0
    assert projection_rows(db) == before_rows
    assert report.watermark_position == watermark_before
    assert report.freshness == "stale"


def test_a_rewritten_journal_is_refused_as_forked(journal, db):
    """Isolate the content-hash check from the length check.

    The rewritten history is byte-for-byte the same *length* as the original, so
    no offset moves and the "journal is shorter than the watermark" guard cannot
    fire.  Only re-hashing the prefix can notice that the history under the
    already-projected vectors was replaced.  A seventh record is appended so the
    run has real work to do if the check is missing.
    """

    make_worker(journal, db, FakeBackend()).run(batch_size=2)
    before = projection_rows(db)

    rewritten = [
        make_record(i, summary="X" * len(f"journal entry number {i}"))
        for i in range(1, 7)
    ]
    write_journal(journal, rewritten + [make_record(7)])
    report = make_worker(journal, db, FakeBackend()).run(batch_size=2)

    assert report.status == "journal_forked"
    assert "content hash" in report.message
    assert report.ok is False
    assert projection_rows(db) == before


def test_a_truncated_journal_is_refused_as_forked(journal, db):
    make_worker(journal, db, FakeBackend()).run(batch_size=2)
    before = projection_rows(db)

    write_journal(journal, [make_record(i) for i in range(1, 3)])
    report = make_worker(journal, db, FakeBackend()).run(batch_size=2)

    assert report.status == "journal_forked"
    assert "truncated" in report.message
    assert projection_rows(db) == before


def test_a_partial_trailing_line_is_never_consumed(tmp_path: Path, db):
    journal = tmp_path / "events.jsonl"
    write_journal(journal, [make_record(i) for i in range(1, 4)])
    complete = journal_position(journal).position
    tail = json.dumps(make_record(4))
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(tail[: len(tail) // 2])  # a writer caught mid-append

    report = make_worker(journal, db, FakeBackend()).run(batch_size=2)
    # GUARD: the watermark stops at the last complete line.  Consuming the
    # fragment would parse garbage now and skip the real record forever.
    assert report.entries_scanned == 3
    assert report.entries_projected == 3
    assert report.watermark_position == complete

    with journal.open("a", encoding="utf-8") as handle:
        handle.write(tail[len(tail) // 2 :] + "\n")
    completed = make_worker(journal, db, FakeBackend()).run(batch_size=2)
    assert completed.entries_projected == 1
    assert projection_rows(db) == (4, 4)
    assert completed.freshness == "fresh"


def test_a_malformed_line_is_reported_and_does_not_wedge_the_worker(tmp_path: Path, db):
    journal = tmp_path / "events.jsonl"
    journal.write_text(
        json.dumps(make_record(1)) + "\n" + "{ not json at all\n"
        + json.dumps(make_record(2)) + "\n",
        encoding="utf-8",
    )
    report = make_worker(journal, db, FakeBackend()).run(batch_size=3)

    assert report.status == "ready"
    assert report.entries_projected == 2
    assert report.entries_skipped_malformed == 1
    assert report.malformed_lines == (2,)
    assert report.freshness == "fresh"

    rerun = make_worker(journal, db, FakeBackend()).run(batch_size=3)
    assert rerun.entries_scanned == 0


def test_blank_content_is_skipped_rather_than_embedded(tmp_path: Path, db):
    journal = tmp_path / "events.jsonl"
    write_journal(journal, [make_record(1, summary="   "), make_record(2)])
    backend = FakeBackend()
    report = make_worker(journal, db, backend).run(batch_size=4)

    assert report.entries_skipped_blank == 1
    assert report.entries_projected == 1
    assert len(backend.embedded) == 1
    assert projection_rows(db) == (1, 1)


# --------------------------------------------------------------------------
# GUARD: bounded and side-effect-free modes
# --------------------------------------------------------------------------


def test_dry_run_creates_no_database_and_calls_no_backend(journal, db):
    backend = FakeBackend()
    report = make_worker(journal, db, backend).run(batch_size=2, dry_run=True)

    assert report.status == "dry_run"
    assert report.entries_projected == 6
    # GUARD: --dry-run is a promise about side effects, not just about vectors.
    assert not db.exists()
    assert backend.calls == 0


def test_limit_bounds_the_run_and_leaves_it_resumable(tmp_path: Path, db):
    journal = tmp_path / "events.jsonl"
    write_journal(journal, [make_record(i) for i in range(1, 13)])
    entries = scan_journal(journal, 0, None)

    first = make_worker(journal, db, FakeBackend()).run(batch_size=2, limit=5)
    assert first.entries_scanned == 5
    assert first.watermark_position == entries[4].end_offset
    assert first.freshness == "stale"
    assert projection_rows(db) == (5, 5)

    second = make_worker(journal, db, FakeBackend()).run(batch_size=2)
    assert second.entries_scanned == 7
    assert second.entries_already_projected == 0
    assert projection_rows(db) == (12, 12)
    assert second.freshness == "fresh"


# --------------------------------------------------------------------------
# GUARD: one model name, one coordinate system
# --------------------------------------------------------------------------


def test_a_declared_dimension_that_conflicts_with_the_index_is_refused(journal, db):
    make_worker(journal, db, FakeBackend()).run(batch_size=3)

    report = make_worker(journal, db, FakeBackend(dimension=4), dimension=4).run()

    assert report.status == "spec_conflict"
    assert report.ok is False
    # GUARD: refuse rather than fork.  A second index under the same model name
    # is exactly the silent coordinate-system mix the index is built to prevent.
    assert index_count(db) == 1
    assert projection_rows(db) == (6, 6)


def test_resolve_spec_adopts_the_recorded_dimension_without_asking_the_backend():
    stored = [EmbeddingSpec(model=MODEL, dimension=1024)]
    assert resolve_spec(stored, model=MODEL, dimension=None).dimension == 1024
    assert resolve_spec([], model=MODEL, dimension=None).dimension == DEFAULT_DIMENSION
    with pytest.raises(SpecConflictError):
        resolve_spec(stored, model=MODEL, dimension=768)


def test_pinning_a_model_revision_warns_that_the_latent_reader_cannot_see_it(
    journal, db
):
    report = make_worker(
        journal, db, FakeBackend(), model_revision="sha256:deadbeef"
    ).run(batch_size=3)
    assert report.status == "ready"
    assert any("model_revision" in warning for warning in report.warnings)


def test_a_missing_journal_is_named_not_silently_treated_as_empty(tmp_path: Path, db):
    report = make_worker(tmp_path / "nope.jsonl", db, FakeBackend()).run()
    assert report.status == "journal_missing"
    assert report.ok is False
    assert not db.exists() or projection_rows(db) == (0, 0)

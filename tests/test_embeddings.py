import json
import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import daedalus.memory as memory
from daedalus.adapters.events import TransportRecord
from daedalus.memory.embeddings import (
    AgentEvent,
    EmbeddingSpec,
    EmbeddingUnavailableError,
    EventVectorStore,
    ProjectionFilter,
    _pack_embedding,
    _unpack_embedding,
)


class ConstantBackend:
    provider = "test"

    def __init__(self, vector=(1.0, 0.0, 0.0)):
        self.vector = list(vector)
        self.calls = []

    def embed(self, texts, *, model, dimensions=None):
        self.calls.append((list(texts), model, dimensions))
        return [list(self.vector) for _ in texts]


class UnavailableBackend:
    provider = "test"

    def embed(self, texts, *, model, dimensions=None):
        raise EmbeddingUnavailableError("offline")


def test_memory_projection_preserves_path_project_and_trust_provenance():
    record = memory.MemoryEvent(
        kind="bridge_report",
        summary="Changed the parser",
        source="codex",
        repo_root="C:/repo",
        project="daedalus",
        trust="verified",
        task_id="task-1",
        status="done",
        paths=["daedalus/parse.py"],
    ).to_record()

    with patch("daedalus.memory.embeddings.EventVectorStore") as store_type, \
            patch.dict(
                "os.environ",
                {"OLLAMA_EMBED_MODEL_REVISION": "sha256:fixed"},
                clear=False,
            ):
        report = MagicMock()
        report.status.available = True
        store_type.return_value.ingest_events_report.return_value = report

        memory._try_vector_index(record)

    call = store_type.return_value.ingest_events_report.call_args
    event = call.args[0][0]
    assert "daedalus/parse.py" in event.content
    assert event.metadata["paths"] == ["daedalus/parse.py"]
    assert event.metadata["project"] == "daedalus"
    assert event.metadata["repo_root"] == "C:/repo"
    assert event.metadata["trust"] == "verified"
    assert call.kwargs["model_revision"] == "sha256:fixed"
    store_type.return_value.close.assert_called_once()


def test_agent_event_serialization():
    event = AgentEvent(
        event_id="test-1",
        event_type="observation",
        content="Observed something.",
        metadata={"key": "value"},
    )

    restored = AgentEvent.from_dict(event.to_dict())

    assert event.event_id == restored.event_id
    assert event.content == restored.content
    assert event.metadata == restored.metadata


def test_pack_unpack_embedding_is_finite_float32():
    embedding = [0.1, 0.2, -0.3, 1.5]

    assert _unpack_embedding(_pack_embedding(embedding)) == pytest.approx(embedding)
    with pytest.raises(ValueError, match="NaN or infinity"):
        _pack_embedding([float("nan")])
    with pytest.raises(ValueError, match="float32"):
        _unpack_embedding(b"\x00")


def test_embedding_spec_index_identity_is_versioned():
    baseline = EmbeddingSpec(
        provider="ollama",
        model="nomic-embed-text",
        dimension=768,
        normalization="l2",
        projector_version="agent-event-v1",
    )

    assert baseline.index_id == EmbeddingSpec(**baseline.to_dict()).index_id
    assert baseline.index_id != EmbeddingSpec(
        model=baseline.model,
        dimension=384,
    ).index_id
    assert baseline.index_id != EmbeddingSpec(
        model="different-model",
        dimension=baseline.dimension,
    ).index_id
    assert baseline.index_id != EmbeddingSpec(
        model=baseline.model,
        dimension=baseline.dimension,
        normalization="none",
    ).index_id
    assert baseline.index_id != EmbeddingSpec(
        model=baseline.model,
        dimension=baseline.dimension,
        projector_version="agent-event-v2",
    ).index_id
    assert baseline.index_id != EmbeddingSpec(
        model=baseline.model,
        dimension=baseline.dimension,
        model_revision="sha256:resolved-local-model",
    ).index_id


@patch("urllib.request.urlopen")
def test_ollama_uses_current_embed_batch_contract(mock_urlopen):
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        requests.append((request.full_url, body, timeout))
        response = MagicMock()
        response.read.return_value = json.dumps(
            {"model": body["model"], "embeddings": [[1.0, 0.0] for _ in body["input"]]}
        ).encode("utf-8")
        response.__enter__.return_value = response
        return response

    mock_urlopen.side_effect = respond
    store = EventVectorStore(":memory:")
    spec = EmbeddingSpec(model="nomic-embed-text", dimension=2)
    events = [
        AgentEvent(event_id="e1", event_type="action", content="Listed directory"),
        AgentEvent(event_id="e2", event_type="action", content="Read file"),
    ]

    assert store.ingest_events(
        events,
        batch_size=2,
        host="http://ollama:11434",
        spec=spec,
    ) == 2
    results = store.search(
        "List dir",
        limit=1,
        host="http://ollama:11434",
        spec=spec,
    )

    assert len(results) == 1
    assert results[0][0].event_id in {"e1", "e2"}
    assert results[0][1] == pytest.approx(1.0)
    assert len(requests) == 2
    assert requests[0][0] == "http://ollama:11434/api/embed"
    assert requests[0][1] == {
        "model": "nomic-embed-text",
        "input": ["[action] Listed directory", "[action] Read file"],
        "dimensions": 2,
    }
    assert requests[1][1]["input"] == ["List dir"]
    assert requests[1][1]["dimensions"] == 2
    store.close()


@patch("urllib.request.urlopen")
def test_ingest_compatibility_wrapper_handles_embedder_failure(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
    store = EventVectorStore(":memory:")

    report = store.ingest_events_report(
        [AgentEvent(event_id="e1", event_type="action", content="Listed directory")]
    )

    assert report.projected == 0
    assert report.status.code == "embedder_unavailable"
    assert report.status.available is False
    assert store.ingest_events(
        [AgentEvent(event_id="e2", event_type="action", content="Read file")]
    ) == 0
    assert store._conn.execute("SELECT count(*) FROM agent_events").fetchone()[0] == 0
    store.close()


def test_append_only_projections_do_not_mix_models_or_replace_sources():
    backend = ConstantBackend([3.0, 4.0])
    store = EventVectorStore(":memory:", backend=backend)
    timestamp = "2026-01-01T00:00:00+00:00"
    original = AgentEvent("same-id", "action", "first", timestamp)

    first = store.ingest_events_report([original], model="model-a")
    duplicate = store.ingest_events_report([original], model="model-a")
    second_index = store.ingest_events_report([original], model="model-b")
    changed = store.ingest_events_report(
        [AgentEvent("same-id", "action", "changed", timestamp)],
        model="model-a",
    )

    assert first.projected == 1
    assert duplicate.status.code == "ready"
    assert duplicate.projected == 0
    assert second_index.projected == 1
    assert changed.projected == 1
    assert first.spec is not None
    assert second_index.spec is not None
    assert first.spec.index_id != second_index.spec.index_id
    assert store._conn.execute(
        "SELECT COUNT(*) FROM embedding_indexes"
    ).fetchone()[0] == 2
    assert store._conn.execute(
        "SELECT COUNT(*) FROM projection_sources"
    ).fetchone()[0] == 2
    assert store._conn.execute(
        "SELECT COUNT(*) FROM event_projections"
    ).fetchone()[0] == 3
    store.close()


@pytest.mark.parametrize(
    "vector, message",
    [
        ([1.0, float("nan")], "NaN or infinity"),
        ([0.0, 0.0], "zero or invalid"),
        ([1.0, 2.0, 3.0], "expected 2, got 3"),
    ],
)
def test_invalid_vectors_are_rejected_atomically(vector, message):
    backend = ConstantBackend(vector)
    store = EventVectorStore(":memory:", backend=backend)
    spec = EmbeddingSpec(provider="test", model="m", dimension=2)

    report = store.ingest_events_report(
        [AgentEvent("e", "action", "content")],
        spec=spec,
    )

    assert report.status.code == "invalid_embedding_response"
    assert report.status.available is False
    assert message in report.status.message
    assert store._conn.execute(
        "SELECT COUNT(*) FROM event_projections"
    ).fetchone()[0] == 0
    store.close()


def test_search_filters_project_trust_and_source_before_scoring():
    backend = ConstantBackend([1.0, 1.0])
    store = EventVectorStore(":memory:", backend=backend)
    events = [
        AgentEvent(
            "trusted",
            "message",
            "trusted result",
            metadata={"project": "daedalus", "trust": "verified", "source": "codex"},
        ),
        AgentEvent(
            "other-project",
            "message",
            "other result",
            metadata={"project": "other", "trust": "verified", "source": "codex"},
        ),
        AgentEvent(
            "untrusted",
            "message",
            "untrusted result",
            metadata={"project": "daedalus", "trust": "untrusted", "source": "ollama"},
        ),
    ]
    ingest = store.ingest_events_report(events, model="local")
    assert ingest.projected == 3

    report = store.search_report(
        "result",
        model="local",
        filters=ProjectionFilter(
            project="daedalus",
            trust="verified",
            source="codex",
        ),
    )

    assert report.status.code == "ready"
    assert [event.event_id for event, _ in report.matches] == ["trusted"]
    store.close()


def test_search_distinguishes_embedder_and_index_unavailability():
    unavailable = EventVectorStore(":memory:", backend=UnavailableBackend())
    unavailable_report = unavailable.search_report("query", model="m")
    assert unavailable_report.status.code == "embedder_unavailable"
    assert unavailable_report.status.available is False
    unavailable.close()

    backend = ConstantBackend([1.0, 0.0])
    store = EventVectorStore(":memory:", backend=backend)
    ingest = store.ingest_events_report(
        [AgentEvent("e", "message", "content")],
        model="model-a",
    )
    assert ingest.spec is not None

    missing = store.search_report("query", model="model-b")
    assert missing.status.code == "index_unavailable"
    assert missing.status.available is False
    status = store.index_status(
        EmbeddingSpec(provider="test", model="model-b", dimension=2)
    )
    assert status.status.code == "index_unavailable"
    assert status.projection_count == 0
    store.close()


def test_legacy_schema_is_quarantined_without_guessing_its_model(tmp_path: Path):
    db_path = tmp_path / "vectors.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE agent_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT,
            content TEXT,
            timestamp TEXT,
            metadata TEXT,
            embedding BLOB
        )
        """
    )
    connection.execute(
        """
        INSERT INTO agent_events
        (event_id, event_type, content, timestamp, metadata, embedding)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy",
            "message",
            "unknown embedding provenance",
            "2025-01-01T00:00:00+00:00",
            "{}",
            _pack_embedding([1.0, 0.0]),
        ),
    )
    connection.commit()
    connection.close()

    store = EventVectorStore(db_path, backend=ConstantBackend([1.0, 0.0]))

    assert store.legacy_unversioned_count() == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM legacy_agent_events_v1"
    ).fetchone()[0] == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM agent_events"
    ).fetchone()[0] == 0
    store.close()


def test_transport_records_project_without_losing_provenance():
    record = TransportRecord(
        record_id="s:output:00000001",
        session_id="s",
        runtime="codex",
        direction="output",
        sequence=1,
        event_type="agent_message",
        timestamp="2026-01-01T00:00:00+00:00",
        content="Changed src/core.py",
        payload={"role": "assistant"},
        metadata={"cwd": "C:/repo", "project": "daedalus", "trust": "verified"},
    )
    store = EventVectorStore(
        ":memory:",
        backend=ConstantBackend([0.5, 0.5]),
    )

    assert store.ingest_transport_records([record], model="local") == 1
    row = store._conn.execute(
        "SELECT metadata FROM agent_events WHERE event_id = ?",
        (record.record_id,),
    ).fetchone()
    metadata = json.loads(row["metadata"])
    assert metadata["session_id"] == "s"
    assert metadata["runtime"] == "codex"
    assert metadata["direction"] == "output"
    assert metadata["payload"] == {"role": "assistant"}
    store.close()

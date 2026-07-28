# Latent Projection Index v2

`EventVectorStore` is a derived retrieval index. The append-only event or
transport journal remains authoritative.

Each vector belongs to an immutable `EmbeddingSpec`:

- provider and model name;
- optional model revision/digest supplied by the caller;
- output dimension;
- normalization policy;
- projection-text version.

These fields determine `EmbeddingSpec.index_id`. Searches select exactly one
index ID, so projections from different coordinate systems are not compared.
Use `model_revision` when the local Ollama tag can be moved or overwritten.

## Context-planner API

```python
from daedalus.memory.embeddings import (
    AgentEvent,
    EmbeddingSpec,
    EventVectorStore,
    ProjectionFilter,
)

spec = EmbeddingSpec(
    provider="ollama",
    model="embeddinggemma:latest",
    model_revision="<local-model-digest>",
    dimension=768,
    normalization="l2",
    projector_version="agent-event-v1",
)

store = EventVectorStore("memory/vectors.db")
write = store.ingest_events_report(events, spec=spec, batch_size=32)
result = store.search_report(
    objective,
    spec=spec,
    filters=ProjectionFilter(
        project="daedalus",
        trust="verified",
        source="codex",
    ),
    limit=20,
)
```

Inspect `write.status.code` and `result.status.code`; do not infer service state
from an empty result list. Relevant codes are `ready`,
`embedder_unavailable`, `invalid_embedding_response`, `index_unavailable`,
`invalid_index`, `partial`, and `empty`.

Compatibility methods `ingest_events`, `ingest_transport_records`, and
`search` still return counts or match lists. New orchestration code should use
the report-returning methods.

## Schema-v1 handling

Opening an old database performs only a schema migration. The original
`agent_events` table is renamed to `legacy_agent_events_v1` and preserved
unchanged. Its vectors are quarantined from v2 search because v1 did not store
their model, dimension, normalization, or projector identity.

This is deliberately not an inferred vector migration. Re-ingest the
authoritative JSONL or transport journal to create versioned v2 projections.
`legacy_unversioned_count()` reports how many quarantined rows remain.

## Journal bridge

When `DAEDALUS_VECTOR_INDEX=1`, the current compatibility bridge projects a
new memory event after it is appended to the authoritative JSONL journal. The
projection now preserves `project`, `repo_root`, `trust`, `source`, `task_id`,
`status`, and explicit `paths`. Paths are also included in the projection text
so a retrieved memory can be mapped back to a Forest node without guessing.

Set `OLLAMA_EMBED_MODEL_REVISION` to the resolved Ollama model digest whenever
the configured model name is a movable tag.

This hook is intentionally still marked provisional: embedding happens
synchronously after append. The production design uses a separate projection
worker that consumes journal offsets/content hashes, retries independently,
and never delays the operational append path.

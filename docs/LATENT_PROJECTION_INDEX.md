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
index ID, so projections carrying **different declared identities** are not
compared.

That last sentence is the whole promise, and on its own it is weaker than it
sounds. `EmbeddingSpec` is a *declaration*. Two genuinely different coordinate
systems can share one declaration, and then one `index_id` covers both:

- an Ollama tag is repointed by `ollama pull` and the caller passed no
  `model_revision`;
- the same tag is served by two different hosts (`host` is a call argument, not
  a spec field);
- the caller passed a `model_revision` string that is simply wrong - nothing
  here resolves or authenticates a digest.

So the spec hash partitions; it does not authenticate. The control that
actually closes these cases is the identity anchor.

## Identity anchor

Every index pins one of its own stored projections as an **identity anchor**.
The first time a process touches that index, the anchor's projection text is
re-embedded and compared against the vector stored for it. If the backend no
longer reproduces that vector within `IDENTITY_DRIFT_TOLERANCE` (cosine
distance, default `1e-4`), both ingest and search refuse with `model_drift`
rather than mixing two coordinate systems.

Ingest refuses **before writing**, so a drifted backend never contributes a
vector to an index built under different weights.

Because the anchor is a real stored projection rather than a synthetic probe,
it costs no extra embedding call when an index is created - only one extra call
per process that reopens an existing index, which is exactly the moment a tag
may have moved underneath it.

Limits of the anchor, stated plainly:

- **Trust on first use.** An index written before anchors existed *adopts* an
  existing projection on first touch. Drift that happened before adoption is
  undetectable. `index_status(...).identity_anchor` reports `"created"`
  (authoritative) or `"adopted"` (retrofitted).
- **Scale-invariant.** Comparison is cosine, so a backend that rescales every
  vector by a constant is not treated as drift. Search is cosine too, so this
  does not change results.
- **Not cryptographic.** A row written directly into `event_projections` under
  the wrong `index_id` is only caught if it also fails the dimension check.

`verify_index_identity(spec)` re-checks on demand, bypassing the per-process
cache. `EmbeddingSpec.pins_model_revision` is `False` when a movable-tag
provider was given no revision; `index_status` surfaces that.

## Freshness relative to the journal

The index is derived; the journal is authoritative; nothing makes the index
keep up. A search therefore reports `freshness`, which defaults to
`"unanchored"` - meaning **freshness unknown**, never "fresh".

To get a real answer, record where the projection run got to and pass the
journal's current position at query time:

```python
from daedalus.memory.embeddings import JournalPosition

store.record_journal_watermark(
    spec, JournalPosition("events.local.jsonl", position=offset, content_hash=digest)
)

result = store.search_report(
    objective, spec=spec, journal=JournalPosition("events.local.jsonl", live_offset)
)
# result.freshness in {"fresh", "stale", "forked", "unanchored"}
```

A stale index still returns its matches - they are valid, just incomplete - but
`status.code` becomes `stale` rather than `ready`, so a caller testing for
`ready` has to make an explicit decision. A journal that moved backwards or
changed its hash at an unchanged position is a `journal_forked` refusal:
the derivation is no longer sound. `record_journal_watermark` refuses to move a
watermark backwards or to accept a changed hash at an unchanged position.

**No shipped caller records watermarks yet.** The bridge in
`daedalus/memory/__init__.py` projects events without anchoring them to a
journal offset, so production searches today report `"unanchored"`. Wiring the
watermark belongs with the projection worker described at the end of this
document. Until then: do not read `status.code == "ready"` as "the index
reflects the whole journal".

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
`invalid_index`, `partial`, `empty`, and the integrity codes `model_drift`,
`stale`, and `journal_forked`.

`model_drift` is never the same thing as `embedder_unavailable`: an unreachable
embedder is an outage, a drifted one is a correctness fault that survives a
retry. Retrying `model_drift` will not help. Either pin a `model_revision` that
distinguishes the two models and re-index, or re-index the whole spec.

Compatibility methods `ingest_events`, `ingest_transport_records`, and
`search` still return counts or match lists. They discard `status` and
`freshness`, so they cannot distinguish a healthy index from a drifted or stale
one. New orchestration code should use the report-returning methods.

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
the configured model name is a movable tag. This is a *partitioning* hint, not
an authentication one: the value is recorded verbatim and never checked against
the server. If it is stale or wrong, the identity anchor - not this variable -
is what stops the mix.

The bridge does not record a journal watermark, so indexes it builds report
`freshness == "unanchored"`.

This hook is intentionally still marked provisional: embedding happens
synchronously after append. The production design uses a separate projection
worker that consumes journal offsets/content hashes, retries independently,
and never delays the operational append path. That worker is also the right
owner for `record_journal_watermark`, which is why freshness is unanchored
until it exists.

## Integrity tests

`tests/test_latent_index_integrity.py` covers the claims above adversarially:
it builds the bad state and asserts refusal. Every guard in it was verified to
go red by actually disabling that guard in `daedalus/memory/embeddings.py` and
re-running the suite. The `_cosine` width check and the read-side dimension
check are layered - both must be removed before a mixed-width index scores
anything - which is deliberate.

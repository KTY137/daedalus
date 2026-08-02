# Knowledge-assisted coding context

Status: experimental Gate-2 extension on draft PR #47

## Purpose

`build_knowledge_assisted_context()` is the single pure integration surface for
an orchestration work item. It accepts the exact Fourfold revision, the matching
`KnowledgeForest`, an imported external knowledge corpus, work-item target paths
and the source slices already produced by DSS/context planning.

It returns the final provider `slice_texts`, a regenerable external knowledge
graph and a complete digest chain. It does not invoke a model, perform an effect,
write a repository, verify a proposed relation or close a gate.

```text
FourfoldSnapshot + matching KnowledgeForest
External KnowledgeCorpus
WorkItem target_paths
Existing DSS source slice_texts
CorrelationPolicy + KnowledgeAccessPolicy
                    |
                    v
         build_knowledge_assisted_context()
                    |
        +-----------+-------------------+
        |                               |
        v                               v
final provider slice_texts     ExternalKnowledgeGraphProjection
        |
        v
CorrelationRunReceipt
KnowledgeAttemptContextReceipt
KnowledgeSliceBridgeReceipt
KnowledgeProviderContextReceipt
```

## Example

```python
from daedalus.twin.knowledge_context_pipeline import (
    build_knowledge_assisted_context,
)

build = build_knowledge_assisted_context(
    receipt_id="attempt-42-knowledge-context",
    created_at="2026-08-02T20:00:00Z",
    objective="Rename Event.voltage to Event.bias_voltage.",
    target_paths=("src/events.py",),
    base_slice_texts={
        "src/events.py": existing_dss_slice,
    },
    snapshot=fourfold_snapshot,
    forest=knowledge_forest,
    corpus=external_knowledge_corpus,
)

provider_slice_texts = build.slice_texts
provider_context_receipt = build.provider_receipt
query_projection = build.graph_projection
```

## Hard boundaries

1. Every target path must exist as at least one node card in the exact snapshot.
2. Every target path must already have non-empty source context. Knowledge may
   enrich source context but cannot create a knowledge-only coding target.
3. Paths are normalized without hiding `..`; traversal and normalized
   collisions fail closed.
4. Correlation result and policy are produced atomically by
   `run_knowledge_correlation()`.
5. A BM25/embedding/LLM soft provider is accepted only with a bound provider
   manifest digest.
6. Access filtering happens before prompt rendering. `private` and `restricted`
   sources are excluded by default.
7. Imported claims are rendered as canonical JSON behind an explicit
   `UNTRUSTED DATA` boundary.
8. Existing DSS source text remains first. Knowledge is appended; it never
   overwrites source text.
9. Prompt and merged-slice budgets fail closed rather than silently truncating
   source context.
10. All generated graph edges remain `structural`, `proposed`,
    `source_supported` or `diagnostic`. No `verified`/`trusted` binding is
    produced.

## Autonomous correlation available now

The production-safe default consists of:

- exact symbols and identifiers;
- explicit links and repository paths;
- project-authoritative alias induction from already hard-anchored claims;
- existing verified Fourfold-neighbour expansion;
- restrained lexical matching.

An optional deterministic `BM25SoftSignalProvider` adds free-prose correlation.
Its alias lexicon and node-card set are content-addressed. Soft scores remain
bounded and cannot independently become verification-eligible.

```python
from daedalus.twin.knowledge_correlation import build_node_cards
from daedalus.twin.knowledge_soft_signals import (
    AliasGroup,
    BM25SoftSignalProvider,
    KnowledgeAliasLexicon,
)

lexicon = KnowledgeAliasLexicon(
    groups=(
        AliasGroup(
            concept_id="detector bias",
            terms=("sensor bias", "bias voltage", "voltage"),
        ),
    )
)
provider = BM25SoftSignalProvider(
    cards=build_node_cards(snapshot, forest),
    lexicon=lexicon,
)

build = build_knowledge_assisted_context(
    # ...same exact inputs...
    soft_signal_provider=provider,
    soft_signal_manifest_sha256=provider.manifest_sha256,
)
```

## What this does not prove

The implementation establishes a bounded and testable mechanism. It does not
yet prove that an LLM codes better with this context. That claim requires a
runtime A/B campaign using the same model, task, attempt count and token/cost
budget for at least:

- plain source context;
- BM25/document RAG;
- code-only graph context;
- separate plane indices;
- Fourfold correlated knowledge bundles.

The primary current product test is
`tests/twin/test_knowledge_full_stack_crucible.py`. It proves the entire data and
evidence path, not model-quality superiority. Gate closure and promotion remain
outside this module.

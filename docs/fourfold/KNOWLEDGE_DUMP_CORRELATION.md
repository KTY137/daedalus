# Knowledge dump correlation boundary

Status: experimental Gate-2 extension  
Branch: `g2/knowledge-correlation-bootstrap`

## Purpose

Daedalus may ingest exported Confluence pages, Obsidian vault files,
MediaWiki page revisions and normalized documents as a provenance-preserving
knowledge overlay. The overlay is correlated with one exact
`FourfoldSnapshot` to build evidence-labelled context for coding attempts.

This work does **not** make external prose authoritative and does not mutate the
snapshot or `KnowledgeForest`.

```text
exported source bytes
  -> KnowledgeSource
  -> Document / Section / Claim
  -> exact and soft correlation signals
  -> KnowledgeCorrelationProposal
  -> contradiction / unresolved-anchor diagnostics
  -> KnowledgeContextCapsule
```

## Authority rules

1. Git/source artifacts and the compiled `KnowledgeForest` remain authoritative.
2. A `FourfoldSnapshot` remains an immutable projection of one exact source
   revision.
3. Imported documents retain source system, item key, source revision,
   authority class, access class and exact source-byte digest.
4. `accepted_architecture`, `project_requirement`,
   `project_documentation`, `repository_documentation` and
   `operational_runbook` are project-authority classes. They are still claims,
   not source facts.
5. `personal_note`, `external_reference` and `generated_summary` can inform
   retrieval but cannot become verification-eligible project bindings.
6. The correlation engine emits only `proposed` or `source_supported`.
   It cannot emit `CrossPlaneBinding(assurance="verified")`.
7. Embedding, BM25, GNN or LLM signals may later implement
   `SoftSignalProvider`; their score is capped and never changes authority.
8. A verified Fourfold binding may expand an exact knowledge anchor to another
   plane, but the result remains a correlation proposal until a separate
   verifier accepts it.

## Current adapters

### Obsidian

`ingest_obsidian_vault()` accepts an immutable mapping of relative Markdown
paths to UTF-8 bytes/text. It preserves frontmatter aliases, headings, claims,
wikilinks, Markdown links, exact code identifiers and file-byte digests.

The adapter rejects path traversal, case-insensitive path collisions,
non-UTF-8 Markdown and configured file/byte limits.

### Confluence

`ingest_confluence_dump()` accepts the bounded normalized export schema
`daedalus-confluence-dump/1`. Each page carries page id, page version, title,
space, labels, storage-format HTML, authority and access class. HTML blocks are
converted to deterministic claims while the source digest remains the digest
of the original storage body.

Fetching a Confluence space is intentionally outside this pure module and must
later occur behind an EffectLease.

### MediaWiki

`ingest_mediawiki_dump()` accepts `daedalus-mediawiki-dump/1` with exact page
and revision ids. Headings and internal links are normalized without claiming
that templates or arbitrary MediaWiki semantics are fully understood.

Wikipedia-style sources should normally use `external_reference`.

## Correlation passes

1. **Hard anchors:** exact identifiers, explicit `daedalus://node/...` links,
   or repository paths.
2. **Alias induction:** document titles, section headings and source aliases
   are learned only from project-authoritative claims that already possess a
   hard anchor.
3. **Soft candidates:** restrained lexical overlap and an optional
   `SoftSignalProvider`.
4. **Verified-neighbour expansion:** existing verified Fourfold bindings can
   carry a hard anchor across planes.
5. **Diagnostics:** requiredness, lifecycle and existence contradictions are
   reported; unresolved explicit identifiers remain visible.
6. **Context selection:** only bundles connected to named snapshot anchors are
   rendered into a deterministic `KnowledgeContextCapsule`.

## Crucible

`tests/twin/test_knowledge_dump_crucible.py` is the primary acceptance test.

It combines:

- accepted Confluence architecture;
- private Obsidian notes containing a stale contradiction;
- public MediaWiki background;
- exact Type and Data nodes;
- an unrelated `Device.output_voltage`;
- an unresolved `CalibrationService`;
- a verified Type-to-Data binding.

The test requires:

- deterministic ingestion and correlation under reordered source corpora;
- exact `Event.voltage` matching;
- verified-neighbour expansion into the Data plane;
- no false correlation to `output_voltage`;
- detection of stale optional-vs-required knowledge;
- external and personal sources never becoming verification-eligible;
- unresolved identifiers remaining visible;
- deterministic, revision-bound context capsules;
- no trusted/verified edge creation by the correlation engine.

This is a bounded bootstrap, not a claim that arbitrary Confluence or Wikipedia
exports are already fully understood.

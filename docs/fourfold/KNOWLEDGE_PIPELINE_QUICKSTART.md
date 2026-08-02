# External knowledge pipeline quickstart

Status: experimental Gate-2 stack on PR #47

The current pipeline is local and offline. It consumes already-exported files;
it does not log in to Confluence, Obsidian Sync or a MediaWiki server. Remote
fetching must later be implemented as an authenticated, effect-leased connector.

## Obsidian vault

```bash
python -m daedalus.twin.knowledge_pipeline ingest-obsidian \
  --root /path/to/vault \
  --vault-id personal-research \
  --source-revision vault-export-2026-08-02 \
  --imported-at 2026-08-02T20:00:00Z \
  --authority personal_note \
  --access-class private \
  --output build/knowledge/obsidian.json
```

The importer reads Markdown, frontmatter aliases, headings, links, wikilinks
and exact backticked identifiers. Symlinks, path escapes, non-UTF-8 files and
configured byte/file limits are refused.

## Confluence normalized export

```bash
python -m daedalus.twin.knowledge_pipeline ingest-confluence \
  --shape normalized \
  --input exports/confluence-normalized.json \
  --instance-id institute-confluence \
  --imported-at 2026-08-02T20:00:00Z \
  --output build/knowledge/confluence.json
```

## Confluence REST response

A saved Atlassian page/search response can be normalized directly:

```bash
python -m daedalus.twin.knowledge_pipeline ingest-confluence \
  --shape rest \
  --input exports/confluence-rest.json \
  --instance-id institute-confluence \
  --imported-at 2026-08-02T20:00:00Z \
  --output build/knowledge/confluence.json
```

The adapter preserves page id, version, space, labels and storage-format body.
Labels such as `adr`, `accepted-architecture`, `requirement` and `runbook` map
to the small canonical authority vocabulary. This mapping does not make the
claim true; it only records how the project treats the source.

## MediaWiki / Wikipedia XML or XML.bz2

Do not try to materialize the complete public Wikipedia into one in-memory
Fourfold corpus. Select a bounded namespace/title slice:

```bash
python -m daedalus.twin.knowledge_pipeline ingest-mediawiki \
  --shape xml \
  --input exports/enwiki-pages-articles.xml.bz2 \
  --instance-id wikipedia-en \
  --imported-at 2026-08-02T20:00:00Z \
  --namespace 0 \
  --title-prefix "Bias voltage" \
  --max-selected-pages 1000 \
  --max-page-text-bytes 4000000 \
  --max-total-bytes 256000000 \
  --output build/knowledge/wikipedia-bias.json
```

The XML reader streams pages and rejects DTD/entity declarations. Selected page
and revision ids are preserved. Public Wikipedia remains
`external_reference`, never project authority.

## Combine sources

```bash
python -m daedalus.twin.knowledge_pipeline combine \
  --input build/knowledge/confluence.json \
  --input build/knowledge/obsidian.json \
  --input build/knowledge/wikipedia-bias.json \
  --corpus-id tct-knowledge-2026-08-02 \
  --output build/knowledge/combined.json
```

Input order does not affect the canonical corpus digest.

## Correlate with one exact Fourfold revision

```bash
python -m daedalus.twin.knowledge_pipeline correlate \
  --snapshot build/twin/fourfold.json \
  --forest build/twin/forest.json \
  --corpus build/knowledge/combined.json \
  --output build/knowledge/correlation.json
```

The command refuses a forest whose digest does not match the snapshot. Output
states are only `proposed` and `source_supported`; no verified Fourfold binding
is created.

## Build agent context

```bash
python -m daedalus.twin.knowledge_pipeline context \
  --snapshot build/twin/fourfold.json \
  --forest build/twin/forest.json \
  --corpus build/knowledge/combined.json \
  --objective "Rename Event.voltage to Event.bias_voltage" \
  --anchor type:field:src/events.py#Event.voltage \
  --allow-access public \
  --allow-access internal \
  --output build/knowledge/context.json
```

Private and restricted claims are withheld by default and remain visible only
by source/claim identity. The access-scoped capsule can then be rendered by
`build_knowledge_prompt_envelope()` into the existing `slice_texts` provider
interface. Imported prose is explicitly marked untrusted data to prevent it
from becoming a prompt instruction.

## Output policy

Outputs are atomic and immutable by default. `--force` replaces the named file
or symlink directory entry; it does not follow an output symlink to overwrite
its target. Input symlinks are refused.

## Not yet implemented

- authenticated Confluence Cloud pagination and ACL lookup;
- Obsidian Sync connector;
- full MediaWiki template/category semantics;
- CommonMark-complete Markdown parsing;
- embedding/LLM reranking in the production path;
- automatic promotion of a correlation to a verified binding;
- live coding-agent A/B evidence.

These omissions are intentional and remain visible. PR #47 does not close Gate
2 and does not claim the system already codes better than a baseline agent.

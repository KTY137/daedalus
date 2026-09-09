# ADR-001: CSV storage for the reference catalogue

## Status

Accepted for the bounded reference project.

## Decision

Use [articles.csv](../../data/articles.csv) as the durable dataset and keep the
reader in [`repository.py`](../../src/knowledge_hub/repository.py). Retain a
parallel [JSON Schema](../../schemas/article.schema.json) so the data plane has
both concrete records and an explicit constraint artifact.

## Consequences

The format is easy to inspect and deterministic, but it is not a general data
backend. Replacing it belongs to a later packet and must preserve the typed and
knowledge bindings.

# Knowledge access boundary

Status: experimental Gate-2 hardening

## Problem

Correlation and disclosure are different operations. Daedalus may index and
correlate a private Obsidian note, a restricted Confluence page and a public
MediaWiki article in one provenance-preserving corpus. A runtime that is only
authorized for `public` and `internal` knowledge must not receive the private
or restricted claim in its prompt merely because the correlation was useful.

Authority labels do not solve this. `personal_note` says how a statement may be
interpreted; `private` says who may read it. Both dimensions must survive until
the final context boundary.

## Canonical output path

```text
KnowledgeCorpus
  + KnowledgeCorrelationResult
  + exact FourfoldSnapshot
  + KnowledgeAccessPolicy
        |
        v
build_access_scoped_context()
        |
        v
AccessScopedKnowledgeContext
```

Production callers should not pass the lower-level
`build_context_capsule()` output directly to an agent. That function is a pure
ranking primitive for tests and research. The access-scoped builder is the
prompt boundary.

## Invariants

1. The supplied `KnowledgeCorpus.digest` must equal the corpus digest bound by
   `KnowledgeCorrelationResult`.
2. Every correlation bundle must resolve to a document in that exact corpus.
3. A document is filtered by `KnowledgeSource.access_class` before the
   low-level capsule builder receives it.
4. The default policy permits only `public` and `internal` sources.
5. `restricted` and `private` content requires an explicit policy grant.
6. Excluded claim digests and source identities remain visible as withheld
   metadata; their text does not enter the capsule.
7. Access permission does not increase semantic authority. A permitted private
   personal note remains ineligible for project verification.
8. Corpus substitution, unknown access classes and an empty allowlist fail
   closed.

## Current access classes

```text
public
internal
restricted
private
```

These labels are intentionally small. Mapping concrete Confluence ACLs, user
identities and group membership into them belongs to a later authenticated
connector/effect work packet. This module only enforces the already-normalized
classification.

## Regression test

`tests/twin/test_knowledge_access_scope.py` proves:

- the default agent context includes accepted internal architecture;
- a correlated private Obsidian contradiction is withheld from prompt text;
- the withheld source and claim remain auditable;
- explicit private access includes the note but does not make it authoritative;
- a foreign corpus cannot be substituted;
- malformed access policies fail closed.

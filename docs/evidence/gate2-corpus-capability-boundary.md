# Gate 2 corpus capability boundary

This work packet repairs the corpus contract matrix without changing the review state of any external repository.

## Mechanical guarantees

- `declared`, `reviewed`, and `rejected` remain distinct review states.
- A reviewed corpus entry still requires a canonical `sha256:<64 lowercase hex>` evidence reference.
- Capability claims are separate from language discovery labels.
- Every language profile must declare every canonical capability exactly once.
- `complete` and `partial` claims require content-addressed evidence.
- `partial`, `unsupported`, and `failed` claims require an explicit limitation.
- Failed capabilities become deterministic blockers.
- The capability matrix binds the exact corpus-manifest digest and has canonical bytes and deterministic identity.

## Honest boundary

This packet does not mark any corpus repository reviewed, does not claim general semantic extraction, does not close Gate 2, and does not consume owner approval. It provides the authority needed for later reviewed evidence and external Genesis binding.

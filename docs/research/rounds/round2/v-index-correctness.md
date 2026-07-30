# Verification: v-index-correctness

Cannot verify claims because the source file index-correctness.py was not provided. All claims are UNDECIDABLE without the code.

## Verdicts

- UNDECIDABLE: 1. [risk] Silent type degradation: per-file type extraction is unconditional, so a layer-off build populates the cache; a subsequent layer-on build may hit the cache and skip resolution, yielding empty type_nodes/type_edges with no error.
- UNDECIDABLE: 2. [risk] Asymmetric truncation: _collect_docs and _collect each enforce max_files independently, so a repo with many docs may have docs truncated while code is fully indexed, producing a half-built index with no warning.
- UNDECIDABLE: 3. [risk] Wiki flag may be dead code: wiki_enabled is defined but not referenced in the provided excerpt; if build_index does not use it, the flag has no effect.
- UNDECIDABLE: 4. [risk] Cache key collision: if _scope_key omits wiki flag, a wiki-on build may reuse a wiki-off cache entry, losing wiki edges silently.
- UNDECIDABLE: 5. [todo] Ensure cache key includes types flag so layer-on builds do not reuse layer-off cache entries.
- UNDECIDABLE: 6. [todo] Add warning or unified limit when documents are truncated independently of code files.
- UNDECIDABLE: 7. [todo] Confirm wiki_enabled is actually wired into build_index; if missing, integrate it.
- UNDECIDABLE: 8. [todo] Verify _scope_key includes wiki flag; if not, add it.

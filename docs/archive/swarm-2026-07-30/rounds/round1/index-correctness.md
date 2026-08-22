# Claims about `index-correctness.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Silent type degradation: per-file type extraction is unconditional, so a layer-off build populates the cache; a subsequent layer-on build may hit the cache and skip resolution, yielding empty type_nodes/type_edges with no error.
2. [risk] Asymmetric truncation: _collect_docs and _collect each enforce max_files independently, so a repo with many docs may have docs truncated while code is fully indexed, producing a half-built index with no warning.
3. [risk] Wiki flag may be dead code: wiki_enabled is defined but not referenced in the provided excerpt; if build_index does not use it, the flag has no effect.
4. [risk] Cache key collision: if _scope_key omits wiki flag, a wiki-on build may reuse a wiki-off cache entry, losing wiki edges silently.
5. [todo] Ensure cache key includes types flag so layer-on builds do not reuse layer-off cache entries.
6. [todo] Add warning or unified limit when documents are truncated independently of code files.
7. [todo] Confirm wiki_enabled is actually wired into build_index; if missing, integrate it.
8. [todo] Verify _scope_key includes wiki flag; if not, add it.
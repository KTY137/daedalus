# Claims about `forest.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] HIGH: In type_nodes loop, second and subsequent rows for the same node_id are silently skipped (line approx. after `if node_id in type_ids: continue`), discarding attributes and evidence. Concrete trigger: index with multiple type_nodes entries sharing an id but differing attributes.
2. [risk] MEDIUM: Hardcoded evidence tuples (e.g., 'structcore.type_edges') discard any per-edge provenance from the index, contradicting the docstring claim that the snapshot is evidence-preserving. This affects all edge types.
3. [risk] LOW: `_json_value` fallback to `repr()` for unknown types may produce non-deterministic output across Python runs, violating the deterministic claim if the index ever carries custom objects with unstable repr.
4. [risk] LOW: In temporal pairs deduplication, `seen_temporal` uses only file pair (a,b); later occurrences with different attributes are dropped. This could lose data if the iterable contains duplicate pairs.
5. [todo] Merge duplicate type node rows instead of skipping, combining attributes with documented conflict resolution.
6. [todo] Allow edge sources to provide an optional 'evidence' key, falling back to current hardcoded values.
7. [todo] Disallow non-JSON-serialisable attribute types or document the deterministic guarantee scope.
8. [todo] Consider temporal dedup that also compares attributes or keep last occurrence.
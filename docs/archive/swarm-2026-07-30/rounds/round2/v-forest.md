# Verification: v-forest

Verified 4 claims about forest.py: confirmed type node duplicate skipping, non-deterministic repr fallback, temporal dedup attribute loss; refuted claim about hardcoded evidence contradicting evidence-preserving.

## Confirmed / actionable

- Merge duplicate type node rows: when node_id already seen, combine attributes from new row (with conflict resolution) instead of skipping.
- Remove repr() fallback in _json_value; raise ValueError or log warning for non-serializable types, or ensure index only uses JSON-serializable attributes and document guarantee.
- In temporal deduplication, if same pair already seen, compare attributes; either merge or keep the one with later timestamp if available, or include all instances as separate edges with different evidence.

## Verdicts

- CONFIRMED: In type_nodes loop, duplicates with same node_id skip subsequent rows, discarding attributes. Trigger: multiple type_nodes entries with same id.
- REFUTED: Edge evidence tuples are hardcoded, but the index does not provide per-edge provenance to discard; no contradiction with docstring.
- CONFIRMED: _json_value fallback to repr() may produce non-deterministic output for custom objects with unstable repr.
- CONFIRMED: Temporal pairs dedup uses only (a,b); later entries with same pair but different attributes are silently dropped.

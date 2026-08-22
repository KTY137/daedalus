# Verification: v-typegraph

Verified 15 claims against provided code (file truncated at _Resolver.__init__). 6 CONFIRMED, 9 UNDECIDABLE due to missing _Resolver internals. CONFIRMED: PlainNaming.from_rels canon empty; star imports never resolve; _VOCABULARY includes non-guaranteed names; structural matching heuristic has false positives; _BUILTIN_TYPES has version-sensitive NoneType; _ORIGIN_RANK tie-break hides conflicts.

## Confirmed / actionable

- Review _VOCABULARY set for Python version sensitivity; consider dynamic determination or version-specific guards for names like 'Self' and 'TypeAlias'.
- Remove 'NoneType' from _BUILTIN_TYPES or add a version guard; dynamically add via `types.NoneType` if needed, or document version requirement.
- Add explicit conflict detection for duplicate field origins instead of silent tie-break via _ORIGIN_RANK; log warning or raise an error to preserve ambiguity information.

## Verdicts

- CONFIRMED: PlainNaming.from_rels returns empty canon dict (line: `_view=_PlainView(rel_by_dotted, {})`); callers expecting populated may break but doc says unused.
- UNDECIDABLE: Tier-2 view picking first candidate when modules share dotted name cannot be verified without full _Resolver._view code; would need complete typegraph.py.
- CONFIRMED: Star imports never produce resolved edges (doc: 'A STAR IMPORT IS NOT A TIER... it can never be the single winner'), deliberately missing potential resolutions when __all__ absent.
- CONFIRMED: _VOCABULARY includes 'Self' and 'TypeAlias' (explicit in frozenset), which are not guaranteed builtins in all Python versions, potentially masking unresolved references.
- UNDECIDABLE: Missing _Resolver.resolve() may contain tie-break or star import winner; full _Resolver code required.
- UNDECIDABLE: _Resolver._view's __init__.py aliasing behavior not visible; full code needed to assess wrong edge risk.
- CONFIRMED: Structural protocol matching is a flagged heuristic (docstring: 'FLAGGED HEURISTIC') and may produce false positives; constants mitigate but not eliminate.
- CONFIRMED: _BUILTIN_TYPES includes 'NoneType' manually (`{'None', 'NoneType'}`), which is not a builtin in all Python versions, causing version-dependent behavior.
- UNDECIDABLE: _Resolver._imports not visible; cannot confirm if transitive imports are included.
- UNDECIDABLE: Classification of 'external' vs 'unresolved' cannot be assessed without _Resolver resolution logic.
- UNDECIDABLE: _Resolver._dotted fallback for non-.py files not provided; full code needed.
- CONFIRMED: _ORIGIN_RANK tie-break (`_ORIGIN_RANK = {'annassign': 0, 'self': 1, ...}`) silently hides genuine conflicts between duplicate field origins.
- UNDECIDABLE: _Resolver._view re-export handling via __all__ not visible.
- UNDECIDABLE: Namespace package handling in _Resolver._view not provided.
- UNDECIDABLE: _Resolver._cache unbounded growth cannot be checked without full class.

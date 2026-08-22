# Claims about `typegraph.py`

Produced by 2 independent review agent(s) (deepseek-chat, deepseek-v4-pro). NONE of this is verified.

1. [risk] PlainNaming.from_rels returns empty .canon dict; callers expecting a populated mapping (from duck typing) may break, though documentation says it is unused.
2. [risk] Tier-2 view silently picks first candidate when two modules share dotted name, producing wrong edge instead of refusing (violates I5).
3. [risk] Star imports are walked but never produce resolved edges, potentially missing valid resolutions when __all__ is absent.
4. [risk] _VOCABULARY set includes names like 'Self' and 'TypeAlias' that are not always builtins, masking unresolved references.
5. [risk] Missing _Resolver.resolve() may contain a tie-break or allow star import to become a winner, violating I5.
6. [risk] _Resolver._view's __init__.py aliasing can produce wrong edges when both pkg/__init__.py and pkg.py exist.
7. [risk] Structural protocol matching heuristic may produce false positives with coincidental member overlap.
8. [risk] _BUILTIN_TYPES includes 'NoneType' which is not a builtin type in all Python versions.
9. [risk] _Resolver._imports does not include transitive imports, missing re-exported types.
10. [risk] The classification of names as 'external' versus 'unresolved' cannot be checked.
11. [risk] _Resolver._dotted fallback may produce incorrect dotted names for non-.py files.
12. [risk] _ORIGIN_RANK tie-break hides genuine conflicts between duplicate field origins.
13. [risk] _Resolver._view only considers direct imports, not re-exports via __all__.
14. [risk] _Resolver._view does not handle namespace packages (no __init__.py).
15. [risk] _Resolver._cache is unbounded and could grow large.
16. [todo] Consider using star imports to produce resolved edges when __all__ is absent (currently safe but may miss valid edges).
17. [todo] Provide full typegraph.py, especially the resolve/_resolve method and the rest of _bindings, to complete audit.
18. [todo] Fix _Resolver._view's __init__.py aliasing to refuse when both pkg/__init__.py and pkg.py exist.
19. [todo] Fix tier-2 view to refuse when multiple modules share the same dotted name (violates I5).
20. [todo] Verify _BUILTIN_TYPES includes 'NoneType' only for Python versions where it is a builtin.
21. [todo] Add explicit conflict detection for duplicate field origins instead of silent tie-break.
22. [todo] Include transitive imports in _Resolver._imports or document limitation.
23. [todo] Review structural protocol matching heuristic for false positives.
24. [todo] Review _VOCABULARY set for names that are not always builtins.
25. [todo] Ensure _Resolver._dotted handles non-.py files correctly.
26. [todo] Add support for namespace packages in _Resolver._view.
27. [todo] Add cache eviction or size limit to _Resolver._cache.
28. [todo] Consider re-exports via __all__ in _Resolver._view.
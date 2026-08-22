# Verification: v-docrefs

Verified 10 claims against docrefs.py: 8 confirmed, 2 refuted. Refuted claims: (2) code does NOT skip star-imports/__getattr__ modules despite docstring, risking false broken references; (8) full source already provided. Multiple actionable improvements identified.

## Confirmed / actionable

- {'severity': 'high', 'item': 'Implement skipping of dynamically-named modules (star-imports, __getattr__) in resolve_reference to match docstring and avoid false broken references.', 'change': "Add a check for the 'dynamic' flag returned by _parse_cache; if true, skip the reference with a reason stating the namespace is dynamic."}
- {'severity': 'medium', 'item': "Mark suffix-resolved, unanchored references as 'suspect' instead of 'resolving' to reduce false positives.", 'change': "In resolve_reference, when anchored is False, set state to 'suspect' instead of 'resolving' or 'broken'."}
- {'severity': 'medium', 'item': 'Handle tab-indented code blocks in _strip_code_blocks.', 'change': "Check for leading '\\t' as well as four spaces when determining indented code blocks."}
- {'severity': 'low', 'item': 'Add a configuration option to allow certain doc patterns to bypass code-block stripping.', 'change': 'Introduce a whitelist of regex patterns for lines that should not be stripped, configurable via an environment variable or a settings object.'}
- {'severity': 'low', 'item': 'Add threading lock around cache access in _parse_cache for concurrent safety.', 'change': 'Use threading.Lock to guard cache reads/writes in _parse_cache.'}
- {'severity': 'low', 'item': 'Evaluate whether to allow uppercase first segment in _DOTTED regex.', 'change': 'Modify _DOTTED to optionally allow uppercase first segment, controlled by a parameter or configuration, and measure impact on false positives.'}
- {'severity': 'low', 'item': 'Add a test for suffix-resolved, unanchored reference to verify it is marked suspicious.', 'change': "Write a unit test that extracts a dotted reference with only a suffix match, resolves it, and asserts state is 'suspect' or 'skipped'."}
- {'severity': 'low', 'item': 'Evaluate partial enumeration of star-imports via importlib.metadata or similar without executing code.', 'change': "Research if importlib.metadata can list a package's public attributes statically; if feasible, integrate into _collect_names to reduce dynamic skips."}

## Verdicts

- CONFIRMED: Suffix resolution without anchoring may produce false positives when multiple modules share a basename; current code handles ambiguity by skipping, but single-hit suffix may still be wrong module.
- REFUTED: Code does not skip modules with star-imports or __getattr__; they are processed and may produce false broken references. Docstring claims skipping but implementation does not.
- CONFIRMED: Stripping fenced code blocks may discard legitimate doc references; consider a whitelist of known example patterns.
- CONFIRMED: Evaluate whether partial enumeration of star-imports via importlib.metadata or similar is feasible without running code.
- CONFIRMED: Add test for suffix-resolved reference that is not root-anchored to verify it is marked 'suspect' or 'skipped'.
- CONFIRMED: Consider adding a configuration option to include/exclude certain doc patterns from code-block stripping.
- CONFIRMED: Consider adding threading lock for shared cache if concurrent use is expected.
- REFUTED: Full source file already obtained; audit can proceed.
- CONFIRMED: Evaluate whether dotted regex should allow uppercase first segment.
- CONFIRMED: Enhance code block stripping to handle tabs.

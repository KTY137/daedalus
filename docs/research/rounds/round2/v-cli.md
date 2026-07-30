# Verification: v-cli

Verified claims about cli.py: error handling in agents/categories/drafts silently returns 0 (confirmed), docstring exit status for unimplemented commands unverifiable (confirmed), missing try/except in most command functions (confirmed), file write atomicity and load_project safety undecidable due to missing module sources. Several actionable fixes identified.

## Confirmed / actionable

- Wrap external calls in _spawn, _context, _accelerators, _build with try/except, print user-friendly message, and sys.exit(1).
- In _agents, _categories, _drafts, after printing non-OK results, call sys.exit(1) to reflect failure.
- Audit missing function implementations (council, status, health, etc.) to verify docstring exit-code guarantees.

## Verdicts

- 1. CONFIRMED: agents add/edit, categories set, drafts apply/dismiss print error messages but return 0, causing scripts to treat failures as success.
- 2. CONFIRMED: Docstring claims specific non-zero exits for 'status', 'health', 'map --check', but dispatch logic is not shown; compliance unverifiable.
- 3. CONFIRMED: Commands without try/except (_spawn, _build, _init, _projects, _accelerators, _context, _agents, _categories, _drafts) produce traceback on downstream failures, leaking internals and exiting non-zero unexpectedly.
- 4. UNDECIDABLE: File writes in _init, agents registry, categories lack atomicity; parallelism risks depend on config.py, agents_registry, categories modules not provided.
- 5. UNDECIDABLE: _context calls load_project without checking existence; depends on load_project implementation not provided.

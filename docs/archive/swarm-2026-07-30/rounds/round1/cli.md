# Claims about `cli.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] 'agents add/edit', 'categories set', 'drafts apply/dismiss' print error messages but return 0, causing scripts to treat failures as success.
2. [risk] Docstring claims specific non-zero exits for 'status', 'health', 'map --check', but dispatch logic is not shown; compliance unverifiable.
3. [risk] Commands without try/except produce traceback on downstream failures, leaking internals and exiting non-zero unexpectedly.
4. [risk] File writes in _init, agents registry, categories lack atomicity; on Windows, parallel invocations may corrupt configs.
5. [risk] _context calls load_project without checking existence, causing AttributeError on missing project.
6. [todo] Wrap external calls in _spawn, _context, _accelerators, _build with try/except, print user-friendly message, and sys.exit(1).
7. [todo] Add Windows-safe file replacement (e.g., write to temp + rename) or advisory locks for init, agents registry, categories.
8. [todo] Audit missing function implementations (council, status, health, etc.) to verify docstring exit-code guarantees.
9. [todo] In _agents, _categories, _drafts, after printing non-OK results, call sys.exit(1) to reflect failure.
10. [todo] Validate project before load_project in _context (e.g., check return).
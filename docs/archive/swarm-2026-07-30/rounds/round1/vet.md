# Claims about `vet.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [todo] Address TOCTOU: either read file into memory then check size, or use a lock, or re-stat after read.
2. [todo] Consider extending binary heuristic to scan whole file or use a library like python-magic.
3. [todo] Fix docstring in scan_text about line number drift.
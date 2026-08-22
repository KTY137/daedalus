# Claims about `embeddings.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] CONCURRENCY: _init_db migration runs in a transaction without retry; parallel first opens on the same DB (common in WSGI/async workers) will hit SQLITE_BUSY and crash the process. Windows file locking makes this worse.
2. [risk] POTENTIAL CORRECTNESS: _normalize_vector rejects zero norm even when normalisation='none', which may be unexpected if callers want to store zero vectors (but docstring justifies it for cosine safety).
3. [risk] MISSING IMPLEMENTATION: Search/ingest methods (search_report, ingest_report) are referenced in docstring but not visible; their actual enforcement cannot be verified.
4. [risk] DOCSTRING MISMATCH: docstring promises record_journal_watermark enforces monotonic watermarks and hash consistency, but no such method is visible in this file.
5. [risk] ERROR SWALLOWING: _embed_batch catches EmbeddingError and returns None silently. Callers may treat None as success, leading to missing vectors.
6. [todo] Review zero-vector policy for 'none' normalisation to see if it should be allowed for pure storage use cases.
7. [todo] Confirm whether record_journal_watermark is defined; if not, remove docstring promise or implement it.
8. [todo] Consider logging or a more explicit return type in _embed_batch to prevent silent failures.
9. [todo] Add retry logic or WAL mode + busy timeout to handle concurrent _init_db safely.
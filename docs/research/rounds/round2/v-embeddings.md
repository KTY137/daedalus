# Verification: v-embeddings

All five claims confirmed: missing concurrency handling in _init_db, zero-vector rejection even with normalization='none', missing search_report/ingest_report/record_journal_watermark methods, and error swallowing in _embed_batch.

## Confirmed / actionable

- Add WAL mode and busy timeout to _init_db to prevent SQLITE_BUSY on concurrent opens.
- Refactor _embed_batch to raise or return a dedicated error type instead of None, ensuring callers handle failures.
- Implement search_report and ingest_report methods or remove their docstring promises.
- Implement record_journal_watermark with monotonic watermark and hash checks, or remove the docstring promise.
- In _normalize_vector, allow zero vectors when normalization='none' (e.g., for storage without cosine search).

## Verdicts

- CONFIRMED: CONCURRENCY: _init_db migration runs without retry, risking SQLITE_BUSY on concurrent opens.
- CONFIRMED: POTENTIAL CORRECTNESS: _normalize_vector rejects zero-norm vectors regardless of normalization setting.
- CONFIRMED: MISSING IMPLEMENTATION: search_report and ingest_report are referenced in docstring but not implemented in the file.
- CONFIRMED: DOCSTRING MISMATCH: record_journal_watermark is promised in docstring but not implemented.
- CONFIRMED: ERROR SWALLOWING: _embed_batch catches EmbeddingError and returns None silently, risking missed errors.

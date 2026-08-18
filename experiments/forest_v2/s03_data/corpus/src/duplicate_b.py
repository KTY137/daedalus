"""Corpus fixture: second declaration of `session`, flags diverge."""

SESSION_DDL = (
    "CREATE TABLE session ("
    " execution_id TEXT NOT NULL PRIMARY KEY,"
    " started_at TEXT NOT NULL"
    ")"
)

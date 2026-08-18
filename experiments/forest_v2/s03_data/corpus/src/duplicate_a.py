"""Corpus fixture: first declaration of `session`.

Mirrors the real divergence this slice found in the tree -- same column
names, same column types, different constraint flags.  In SQLite a
TEXT PRIMARY KEY column does not imply NOT NULL, so these two are not
equivalent declarations.
"""

SESSION_DDL = (
    "CREATE TABLE session ("
    " execution_id TEXT PRIMARY KEY,"
    " started_at TEXT NOT NULL"
    ")"
)

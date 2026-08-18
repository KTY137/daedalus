"""Corpus fixture: two complete tables, written the way this repository
writes DDL -- implicitly concatenated string literals, so a one-line regex
sees the statement head and never a complete body."""

ARTICLE_DDL = (
    "CREATE TABLE IF NOT EXISTS article ("
    " id TEXT PRIMARY KEY,"
    " title TEXT NOT NULL,"
    " votes INTEGER NOT NULL DEFAULT 0"
    ")"
)

ARTICLE_TAG_DDL = """
CREATE TABLE article_tag (
    article_id TEXT NOT NULL REFERENCES article(id),
    tag TEXT NOT NULL,
    UNIQUE (article_id, tag)
)
"""

"""Corpus fixture: a DDL PREFIX used as a guard predicate, not a declaration.

The extractor must mark this incomplete and give it no columns rather than
inventing a shape for it.
"""

PREDICATE = "CREATE TABLE IF NOT EXISTS session"

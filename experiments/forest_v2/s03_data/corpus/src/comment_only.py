"""Corpus fixture: the statement text appears only in a `#` comment.

A grep-based classifier calls this a declaration-carrying file.  A parse-based
one does not, because a comment is not in the syntax tree at all.

(This docstring deliberately avoids spelling the statement out: a prose
mention inside a *string* is a different case, pinned by prose_mention.py.)
"""

# CREATE TABLE ghost (id TEXT PRIMARY KEY)
VALUE = 1

"""Corpus fixture pinning a KNOWN FALSE POSITIVE of string-literal mining.

This docstring mentions CREATE TABLE ghost_table in prose.  A probe that mines
declarations out of string constants cannot tell prose from DDL, so it emits a
node -- but it emits it as `complete=false` with `no_balanced_body` and with no
columns, rather than inventing a shape.

Pinned deliberately: the limitation is real, so it is measured and published
instead of being quietly filtered out.  Anything that later suppresses this
node must also justify why it will not suppress a genuine guard predicate,
which is textually identical.
"""

VALUE = 3

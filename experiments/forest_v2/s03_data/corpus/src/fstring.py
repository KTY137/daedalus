"""Corpus fixture: DDL assembled in an f-string.

The interpolated part is not knowable statically, so the node must be marked
`f_string_partial` and never presented as a complete declaration.
"""


def ddl(suffix: str) -> str:
    return f"CREATE TABLE live_{suffix} (key TEXT PRIMARY KEY)"

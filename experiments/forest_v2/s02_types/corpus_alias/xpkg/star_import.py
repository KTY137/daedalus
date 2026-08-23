"""Wildcard import.  Decidable from declarations, but only by a resolver that
expands the exporting module's symbol table.
"""
from xpkg.base import *


def starred(a: Widget) -> Gadget:
    return a

"""mapping — the GENERATED half of the architecture artifact.

Two halves, deliberately separated:

  * MECHANICAL (here): what exists, what reaches it, what is dark, what is an
    island, and the counts. Derived on every run from the tree itself, so it
    cannot go stale between the moment it is written and the moment it is read.
  * NARRATIVE (docs/adrs/*.md, the invariants): WHY a thing is the way it is.
    No scanner derives that, and pretending otherwise is how hand-maintained
    inventories rot.

``reach.analyse`` answers the question the structural index cannot: not "X
imports Y" but "can a human or a tool get here at all".
"""
from __future__ import annotations

from .reach import CLASSES, ENTRY_KINDS, SCHEMA, EntryPoint, ModuleFacts, ReachReport, analyse

__all__ = [
    "CLASSES",
    "ENTRY_KINDS",
    "SCHEMA",
    "EntryPoint",
    "ModuleFacts",
    "ReachReport",
    "analyse",
]

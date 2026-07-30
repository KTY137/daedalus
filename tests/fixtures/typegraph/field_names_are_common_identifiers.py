"""HAZARD I2b — field names that are ordinary identifiers everywhere.

The fields here are named exactly ``path``, ``root``, ``name``, ``line``,
``source`` and ``module``. NONE of them is in ``graph._STOP`` and every one is
longer than two characters, so ``graph.identifiers`` keeps all six. If field
names ever enter ``defs_by_file``, then ``graph.callees`` -- which resolves
EVERY identifier token in a unit body -- fabricates a CALL edge for each
mention, and those edges reach the CALLEES block of ``slice_text``. A slice then
tells a model that a function calls ``line``.

Second-order effect (also silent): ``context_plan._symbol_names`` reads
``defs_by_file`` wholesale into the BM25 lexical corpus, so six generic tokens
per dataclass would re-rank the entire repository by length normalisation --
penalising exactly the dataclass-rich files.

``describe`` below mentions three of the six tokens in its body on purpose: it
is the unit whose CALLEES list would grow if the invariant broke.
"""
from dataclasses import dataclass


@dataclass
class Record:
    path: str
    root: str
    name: str
    line: int
    source: str
    module: str


def describe(record: Record) -> str:
    return f"{record.module}:{record.line} <- {record.source}"

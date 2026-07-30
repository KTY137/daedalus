"""HAZARD I5b — the same ambiguity through the OTHER mechanism: star imports.

Two ``import *`` statements, both from a module that declares ``Result``. There
is no name binding in this file's own text, so the annotation ``Result`` is a
bare name with two candidate declarations reachable through the import graph --
and, unlike the try/except case, an extractor cannot even see a ``Result`` token
in an import statement to anchor on.

Required behaviour is identical: NO EDGE, counted as ambiguous. Both mechanisms
are kept because they fail an implementation at different points -- the
try/except case fails an import-binding reader, the star case fails a
graph-walking resolver.
"""
from result_alpha import *  # noqa: F401,F403 -- the ambiguity IS the fixture
from result_beta import *  # noqa: F401,F403


def widen(outcome: Result) -> Result:  # noqa: F405
    return outcome

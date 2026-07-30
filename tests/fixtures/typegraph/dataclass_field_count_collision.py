"""HAZARD I1 — the renamed-clone explosion.

Three plain dataclasses: one with TWO fields, two with FOUR fields each.
``QuadAlpha`` and ``QuadBeta`` share a field count and differ only in the field
names, so under the Type-2 abstraction in ``clones.abstract_normalize`` they
would carry the SAME abstract fingerprint. ``renamed_clusters`` has no
similarity threshold and no ``max_cluster``, and it is published in the PRECISE
tier -- so the moment a ``ClassDef`` becomes a ``CodeUnit`` and reaches
``all_units``, every dataclass in a repo with the same field count is reported
as a full-confidence renamed clone. (Measured shape in daedalus/: 176
dataclasses.)

Today the classes are absent from ``all_units`` only because
``parse._units_from_tree`` tests ``isinstance(node, (FunctionDef,
AsyncFunctionDef))``. The type layer must keep that accident and make it
deliberate: type/field are FOREST nodes, never CodeUnits.

The functions below are deliberately under ``min_loc=4`` so that NO clone pass
can fire on this file's real units -- which makes the empty ``duplication``
block in tests/test_typegraph_fixture.py a maximally sensitive tripwire.
"""
from dataclasses import dataclass


@dataclass
class PairOnly:
    left: int
    right: int


@dataclass
class QuadAlpha:
    one: int
    two: str
    three: float
    four: bool


@dataclass
class QuadBeta:
    first: int
    second: str
    third: float
    fourth: bool


def pair_span(pair: PairOnly) -> int:
    return pair.right - pair.left


def quad_alpha_label(quad: QuadAlpha) -> str:
    return f"{quad.one}/{quad.two}"

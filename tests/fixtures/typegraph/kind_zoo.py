"""HAZARD: declaration-shape coverage.

Every Python shape that IS a type declaration, in one file, so a stage that
only understands ``@dataclass`` fails here rather than somewhere that looks
like an unrelated miss:

  * ``@dataclass``  -- annotated class-body assignments
  * plain class     -- annotated class attribute AND ``self.x`` assignment
  * ``NamedTuple``  -- fields as class-body annotations
  * ``TypedDict``   -- a dict SHAPE that is a first-class type
  * ``Enum``        -- members are VALUES, not typed fields (must NOT become
                       ``field`` nodes with an annotation)
  * ``Protocol``    -- a nominal declaration with structural meaning

``User`` is the type other fixture modules import, so it is also the target of
the cross-module annotation case.
"""
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple, Protocol, TypedDict


@dataclass
class User:
    user_id: int
    label: str


class PlainHolder:
    """No decorator, no base: an annotated class attribute plus an instance
    attribute that exists only as an assignment in ``__init__``."""

    limit: int = 10

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.tag = "plain"


class Point(NamedTuple):
    x: float
    y: float


class Config(TypedDict):
    host: str
    port: int


class Mode(Enum):
    FAST = "fast"
    SLOW = "slow"


class Sink(Protocol):
    def accept(self, payload: str) -> None: ...

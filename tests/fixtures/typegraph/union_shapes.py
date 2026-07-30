"""HAZARD: union normalisation (Pitfall-Policy 1).

Four spellings that must normalise to the same thing, deliberately WITHOUT
``from __future__ import annotations`` so these annotations are real ast
expression nodes rather than strings -- the string case lives in
future_annotations_forward_ref.py.

  * ``Optional[Alpha]``            -> one edge to Alpha (Optional stripped)
  * ``Alpha | None``               -> PEP 604, identical meaning, ast.BinOp
  * ``Union[Alpha, Beta]``         -> TWO edges sharing one ``union_id``
  * ``Optional[Union[Alpha, Beta]]`` -> still two edges, still one ``union_id``
    (nesting must not multiply the members or invent a ``NoneType`` node)

``None`` must never become a ``type`` node.
"""
from typing import Optional, Union


class Alpha:
    tag: str


class Beta:
    weight: int


def take_optional(value: Optional[Alpha]) -> None:
    del value


def take_pep604(value: Alpha | None) -> None:
    del value


def take_union(value: Union[Alpha, Beta]) -> str:
    return type(value).__name__


def take_nested(value: Optional[Union[Alpha, Beta]]) -> bool:
    return value is not None


def produce_union(flag: bool) -> Union[Alpha, Beta]:
    return Alpha() if flag else Beta()

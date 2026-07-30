"""HAZARD: the three ways an annotation carries no usable type (I5).

  * ``Any``          -- annotated, resolvable, and says nothing. Must be
                        countable SEPARATELY from "unresolved": a coverage
                        number that folds ``Any`` into either "covered" or
                        "missing" is a lie in one direction or the other.
  * unannotated      -- the honest gap. Counted, never guessed. Inferring a type
                        from the body is the scip-python sidecar's job, and that
                        is an optional enrichment, not the core.
  * unknown name     -- ``NoSuchTypeAnywhere`` is declared nowhere in this repo
                        and imported from nowhere. NO EDGE, counted into
                        ``types.coverage.unresolved``. It must NOT be minted as
                        a type node on the strength of being mentioned.

The future import is what makes the unknown name legal at runtime: annotations
are never evaluated, which is also exactly why ``typing.get_type_hints`` is
forbidden here -- it would execute imports to resolve them.
"""
from __future__ import annotations

from typing import Any


def takes_any(payload: Any) -> Any:
    return payload


def unannotated(payload):
    return payload


def phantom(payload: NoSuchTypeAnywhere) -> None:
    del payload


def phantom_container(payload: list[NoSuchTypeAnywhere]) -> int:
    return len(payload)

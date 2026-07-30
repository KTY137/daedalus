"""One of the two homonym modules for the ambiguity case (I5).

Declares a class ``Result``. Sorted first of the two by module name, which is
precisely why a resolver that walks imports in sorted order and takes the FIRST
hit would always bind to THIS one -- deterministically, reproducibly, and wrong
half the time.
"""
from dataclasses import dataclass


@dataclass
class Result:
    value: int
    ok: bool


def make_alpha(value: int) -> Result:
    return Result(value=value, ok=True)

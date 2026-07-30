"""The other homonym module for the ambiguity case (I5).

Declares a SECOND, unrelated class also named ``Result`` -- different fields,
different meaning. Nothing about the name says which of the two an importer
meant, and the answer is not recoverable from the name alone.
"""
from dataclasses import dataclass


@dataclass
class Result:
    reason: str
    retries: int
    fatal: bool


def make_beta(reason: str) -> Result:
    return Result(reason=reason, retries=0, fatal=False)

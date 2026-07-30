"""HAZARD: an annotation naming a type declared in ANOTHER module.

``User`` comes from a sibling module, ``Ticket`` from a nested package. Both are
unambiguous: exactly one imported module declares each name, so both MUST
produce a real edge. This is the positive control for invariant I5 -- I5 forbids
GUESSING, not resolving. A stage that refuses everything it did not find locally
would pass the ambiguity tests and still be useless, and this file is what
catches that.

Resolution must go through a NEW ``types_by_file`` table (I2). It must NOT reuse
``graph.SymbolResolver.defs_by_file``.
"""
from dataclasses import dataclass

from kind_zoo import User
from pkg_nested.inner_types import Ticket


@dataclass
class Assignment:
    user: User
    ticket: Ticket
    note: str


def owner(assignment: Assignment) -> User:
    return assignment.user


def ticket_of(assignment: Assignment) -> Ticket:
    return assignment.ticket

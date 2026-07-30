"""The nested-package type, imported by cross_module_annotation.py.

Nothing hazardous in itself: it exists so the cross-module case covers a DOTTED
module path (``pkg_nested.inner_types``) and not just a flat sibling.
"""
from dataclasses import dataclass


@dataclass
class Ticket:
    ticket_id: int
    summary: str


def short_ref(ticket: Ticket) -> str:
    return f"#{ticket.ticket_id}"

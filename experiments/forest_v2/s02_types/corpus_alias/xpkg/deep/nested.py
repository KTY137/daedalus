"""Relative imports at two levels."""
from ..base import Widget
from .sibling import Bracket


def deep(a: Widget) -> Bracket:
    return a

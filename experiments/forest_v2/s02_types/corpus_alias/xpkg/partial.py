"""Deliberately mixed annotation degree, plus one genuinely dangling name."""
from xpkg.base import Widget


def half(a: Widget, b):
    return a


def none_at_all(a, b):
    return a


def dangling(a: Flywheel) -> int:
    return 1

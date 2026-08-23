"""A closure-local class shadowing an imported name of the same spelling.

The annotation on ``inner`` refers to the LOCAL ``Widget``, not the imported
one.  A module-level symbol table cannot see that.
"""
from xpkg.base import Widget


def outer():
    class Widget:
        pass

    def inner(a: Widget) -> int:
        return 1

    return inner

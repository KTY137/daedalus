"""Two hops away from the definition -- the case the resolver cannot follow."""
from xpkg import Gizmo
from xpkg.reexport_hop import Cog
from xpkg.reexport_hop import Widget


def one(a: Widget) -> Widget:
    return a


def two(b: Cog) -> Cog:
    return b


def three(c: Gizmo):
    return c

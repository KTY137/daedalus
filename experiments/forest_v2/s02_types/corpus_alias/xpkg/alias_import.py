"""Aliased imports. One hop, so the resolver should get both."""
from xpkg.base import Widget as W
from xpkg.base import Gadget as G


def takes_alias(a: W) -> G:
    return a

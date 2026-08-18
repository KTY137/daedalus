"""Module bound under an alias, attribute access through it."""
import xpkg.base as bs


def via_module_alias(a: bs.Widget) -> bs.Sprocket:
    return a

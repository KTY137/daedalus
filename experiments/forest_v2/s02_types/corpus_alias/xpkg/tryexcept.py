"""Guarded import with a fallback.  At runtime the first branch wins."""
try:
    from xpkg.base import Sprocket
except ImportError:
    from xpkg.fallback import Sprocket


def fallback_typed(a: Sprocket) -> int:
    return 1

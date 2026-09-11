"""Module alias for :mod:`daedalus.kernel.events.durability`.

The historical locator exposes the exact owner module, so tests and callers
that patch its private readback seam still patch the single implementation.
"""

import sys as _sys

from daedalus.kernel.events import durability as _owner

_sys.modules[__name__] = _owner

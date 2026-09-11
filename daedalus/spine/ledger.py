"""Module alias for :mod:`daedalus.kernel.events.ledger`.

The SQLite schema, locking, replay, and digest implementation has one owner.
Replacing this locator in ``sys.modules`` also preserves legacy monkeypatch,
private-name, and pickle-global resolution semantics.
"""

import sys as _sys

from daedalus.kernel.events import ledger as _owner

_sys.modules[__name__] = _owner

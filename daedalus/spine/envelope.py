"""Module alias for :mod:`daedalus.kernel.events.envelope`.

Replacing this compatibility module in ``sys.modules`` preserves not only
object identity but also legacy monkeypatch and private-name behavior.  There
is no executable envelope implementation at this locator.
"""

import sys as _sys

from daedalus.kernel.events import envelope as _owner

_sys.modules[__name__] = _owner

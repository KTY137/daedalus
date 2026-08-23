"""The intermediate hop of a re-export chain."""
from xpkg.base import Widget
from xpkg.base import Sprocket as Cog


def identity(w: Widget) -> Widget:
    return w

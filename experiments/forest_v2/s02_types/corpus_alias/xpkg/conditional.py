"""Import behind ``TYPE_CHECKING``, referenced as a string forward ref."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xpkg.base import Sprocket


def guarded(a: "Sprocket") -> int:
    return 1

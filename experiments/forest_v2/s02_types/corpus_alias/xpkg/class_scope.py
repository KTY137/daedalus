"""A class-scope alias used as an annotation inside the same class body."""
from xpkg.base import Widget


class Holder:
    Alias = Widget

    def use(self, a: Alias) -> int:
        return 1

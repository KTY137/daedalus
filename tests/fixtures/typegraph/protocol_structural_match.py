"""HAZARD: structural match is not inheritance.

``FileEmitter`` implements every member of ``Emitter`` and inherits from
NOTHING. ``DeclaredEmitter`` says so explicitly. A structural matcher that emits
``inherits`` without marking ``structural=True`` erases the difference between a
declared contract and a coincidence of names -- and ``emit``/``flush`` are common
enough that the coincidence is the normal case, not a rarity.

Note the repeated method names WITHIN this file: three ``emit`` and three
``flush`` definitions. ``defs_by_file`` is keyed by bare name with
``setdefault``, so it holds exactly one of each -- the first. Any assertion over
that table must expect the collapse rather than one entry per definition.
"""
from typing import Protocol


class Emitter(Protocol):
    def emit(self, payload: str) -> None: ...

    def flush(self) -> int: ...


class FileEmitter:
    """Structurally identical to ``Emitter``. No base class. No declared intent."""

    def emit(self, payload: str) -> None:
        self.last = payload

    def flush(self) -> int:
        return 0


class DeclaredEmitter(Emitter):
    """The nominal case: an ``inherits`` edge that is genuinely declared."""

    def emit(self, payload: str) -> None: ...

    def flush(self) -> int: ...

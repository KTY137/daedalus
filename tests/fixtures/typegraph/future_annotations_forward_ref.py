"""HAZARD: PEP 563 is the NORMAL case, not the exception.

``from __future__ import annotations`` makes EVERY annotation in this module a
string in the ast (``ast.Constant``, not ``ast.Name``), so an extractor that
only reads ``ast.Name``/``ast.Subscript`` finds nothing here -- and reports zero
rather than an error. daedalus/ itself uses this import in most modules, so the
string path is the main path.

Also encoded:
  * a SELF reference (``Node | None`` inside ``Node``), which is only legal
    because of the future import;
  * a FORWARD reference to ``Later``, defined BELOW its first use, so an
    extractor that resolves eagerly per-statement instead of after the file is
    fully collected reports it as unresolved;
  * an explicitly QUOTED forward ref (``"Later"``), which under the future
    import is a string INSIDE a string -- the double-quoting case.

Resolution must happen against the finished per-file type table, never
incrementally while walking.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Node:
    label: str
    parent: Node | None
    child: Later | None


def take_quoted(item: "Later") -> Node | None:
    return None


def link(parent: Node, child: Later) -> None:
    del parent, child


@dataclass
class Later:
    weight: int

"""Compatibility facade for the canonical architecture-memory implementation.

The maintained implementation lives in :mod:`daedalus.interfaces.cli.arch_memory`.
This module preserves the historical ``daedalus.arch_memory`` import used by
agent hooks and older integrations without carrying a second implementation.
"""
from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TypeAlias

from .interfaces.cli import arch_memory as _impl

ARCH_MEMORY_VERSION = _impl.ARCH_MEMORY_VERSION
LAST_SHOWN_REL_PATH = _impl.LAST_SHOWN_REL_PATH
MAX_LINE_CHARS = _impl.MAX_LINE_CHARS
MAX_LINES = _impl.MAX_LINES
MEMORY_REL_PATH = _impl.MEMORY_REL_PATH
NEWLINE = _impl.NEWLINE
STATE_REL_PATH = _impl.STATE_REL_PATH
ArchMemory = _impl.ArchMemory
ArchitectureSnapshot: TypeAlias = ArchMemory
build = _impl.build
load = _impl.load
main = _impl.main
render = _impl.render
save = _impl.save


def _bounded_text(
    text: str,
    *,
    max_lines: int | None,
    max_chars: int | None,
) -> str:
    """Apply optional presentation budgets without changing stored truth."""
    if max_lines is not None:
        if type(max_lines) is not int or max_lines < 0:
            raise ValueError("max_lines must be a non-negative integer or None")
        text = NEWLINE.join(text.splitlines()[:max_lines])
    if max_chars is not None:
        if type(max_chars) is not int or max_chars < 0:
            raise ValueError("max_chars must be a non-negative integer or None")
        text = text[:max_chars]
    return text


def render_delta(
    repo_root: str | PathLike[str] = ".",
    shown_path: Path | None = None,
    *,
    silent_when_unchanged: bool = False,
    max_lines: int | None = None,
    max_chars: int | None = None,
) -> str:
    """Render the canonical session delta with optional output budgets.

    The canonical implementation records the complete rendered snapshot before
    this facade truncates presentation output. A small caller budget therefore
    never corrupts the next delta comparison.
    """
    text = _impl.render_delta(
        repo_root,
        shown_path,
        silent_when_unchanged=silent_when_unchanged,
    )
    return _bounded_text(text, max_lines=max_lines, max_chars=max_chars)


def is_stale(repo_root: str | PathLike[str] = ".") -> bool:
    """Return whether the stored architecture snapshot predates live ``HEAD``."""
    root = Path(repo_root).resolve()
    snapshot = load(root)
    live_head = _impl._git(root, "rev-parse", "HEAD")
    return bool(snapshot.head and live_head and snapshot.head != live_head)


__all__ = [
    "ARCH_MEMORY_VERSION",
    "ArchitectureSnapshot",
    "ArchMemory",
    "LAST_SHOWN_REL_PATH",
    "MAX_LINE_CHARS",
    "MAX_LINES",
    "MEMORY_REL_PATH",
    "STATE_REL_PATH",
    "build",
    "is_stale",
    "load",
    "main",
    "render",
    "render_delta",
    "save",
]


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(main(sys.argv[1:]))

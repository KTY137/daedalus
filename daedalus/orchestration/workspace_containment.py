"""Worktree-root composition for kernel Effect-Lease admission.

The kernel authorizes the resulting topology.  This module owns only the
orchestration fact that the default attempt manager plans worktrees below its
configured root; it issues no lease and retains no mutable registration.
"""

from __future__ import annotations

from pathlib import Path

from daedalus.kairos.worktree import GitWorktreeManager


def resolve_worktree_root(repository_root: Path, /) -> Path:
    """Return the exact root used by a fresh default attempt manager."""

    root = Path(repository_root).resolve()
    return GitWorktreeManager(root).worktree_root


__all__ = ["resolve_worktree_root"]

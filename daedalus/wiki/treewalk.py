"""treewalk -- what counts as this project's tree, decided once and pruned early.

Every instrument in this package walks the repository: ``plan`` to find
topics, ``verify`` to collect evidence, ``metrics`` to build the graph. Each
kept its own walker on purpose (they are standalone entrypoints), and each
learned the same lesson one marker at a time:

* a virtual environment is known by ``pyvenv.cfg``, not by being called
  ``venv`` (project_tct surveyed ``Scripts/`` and ``bin/`` as topics, 2026-08-25);
* a nested git checkout is known by its own ``.git`` entry, file or directory
  (a worktree under ``.claude/worktrees`` supplied 480 of 983 files, 2026-08-26);
* a frozen application bundle is known by PyInstaller's
  ``_internal/base_library.zip`` next to the frozen interpreter. MEASURED
  2026-09-05 on this repository: the Tauri desktop build keeps two such copies
  of ``daedalus`` under ``apps/web/src-tauri``, neither with a ``.git``, so
  ``plan`` reported 153 topics over 760k lines where the tree has 63 over 300k,
  and ``verify`` counted 6133 source modules against roughly 720 real ones,
  reporting 22% module coverage for a wiki that linked 98% of ``daedalus/``.

The three rules are structural, never a name list: a name list is always one
name behind. This module holds them in one place so a fourth marker is added
once, and it prunes at the DIRECTORY level with ``os.walk`` instead of
descending with ``rglob`` and filtering afterwards -- on this tree the
difference between reading ``node_modules`` and ``target/`` file by file and
never entering them.

Read-only by construction: nothing here opens a file for writing, spawns,
or touches the network.
"""

from __future__ import annotations

import os
import pathlib
from typing import Iterable, Iterator

VENV_MARKER = "pyvenv.cfg"
CHECKOUT_MARKER = ".git"
BUNDLE_MARKER = ("_internal", "base_library.zip")

#: reason label -> human sentence fragment, used by instruments that report
#: what they did NOT walk
FOREIGN_KINDS = {
    "venv": "own pyvenv.cfg marker, so a virtual environment, not this project's structure",
    "nested_checkout": "own .git marker, so another repository, not this project's structure",
    "frozen_bundle": ("own _internal/base_library.zip marker, so a frozen application "
                      "bundle -- a copy of the package, not this project's structure"),
}


def is_venv(directory: pathlib.Path) -> bool:
    return (directory / VENV_MARKER).is_file()


def is_nested_checkout(directory: pathlib.Path) -> bool:
    """A clone carries a ``.git`` directory, a worktree a ``.git`` file."""
    return (directory / CHECKOUT_MARKER).exists()


def is_frozen_bundle(directory: pathlib.Path) -> bool:
    """A PyInstaller one-dir bundle: ``<bundle>/_internal/base_library.zip``."""
    return directory.joinpath(*BUNDLE_MARKER).is_file()


def foreign_kind(directory: pathlib.Path) -> str | None:
    """Which structural rule makes ``directory`` not part of this project, if any."""
    if is_nested_checkout(directory):
        return "nested_checkout"
    if is_venv(directory):
        return "venv"
    if is_frozen_bundle(directory):
        return "frozen_bundle"
    return None


def walk(root: pathlib.Path, skip_dirs: Iterable[str] = (),
         excluded: Iterable[pathlib.Path] = ()
         ) -> Iterator[tuple[pathlib.Path, list[str]]]:
    """Yield ``(directory, filenames)`` for every directory that is this project.

    Prunes, in this order, before descending: names in ``skip_dirs``; any
    directory under a path in ``excluded`` (resolved, so a relative ``root``
    against absolute exclusions still matches); any directory a structural
    marker declares foreign. ``root`` itself is never marker-tested -- it is
    allowed to be a checkout, that is the point of it. Names are sorted so two
    runs over the same tree see the same order.
    """
    root = pathlib.Path(root).resolve()
    skip = frozenset(skip_dirs)
    fences = [pathlib.Path(p).resolve() for p in excluded]
    for dirpath, dirnames, filenames in os.walk(root):
        here = pathlib.Path(dirpath)
        keep: list[str] = []
        for name in sorted(dirnames):
            if name in skip:
                continue
            child = here / name
            if any(child == fence or fence in child.parents for fence in fences):
                continue
            if foreign_kind(child) is not None:
                continue
            keep.append(name)
        dirnames[:] = keep
        yield here, sorted(filenames)


def walk_files(root: pathlib.Path, skip_dirs: Iterable[str] = (),
               excluded: Iterable[pathlib.Path] = (),
               suffixes: Iterable[str] | None = None) -> Iterator[pathlib.Path]:
    """Every file of this project's tree, optionally limited to ``suffixes``.

    ``suffixes`` are compared lower-cased and include the dot (``".py"``).
    """
    wanted = None if suffixes is None else frozenset(s.lower() for s in suffixes)
    for here, filenames in walk(root, skip_dirs, excluded):
        for name in filenames:
            if wanted is not None and pathlib.PurePath(name).suffix.lower() not in wanted:
                continue
            yield here / name


def foreign_roots(root: pathlib.Path, skip_dirs: Iterable[str] = ()
                  ) -> dict[str, list[pathlib.Path]]:
    """The directories below ``root`` that a structural rule leaves out, by kind.

    Walks the same pruned tree as ``walk`` (so a bundle inside ``node_modules``
    is not listed -- it was never a candidate) and reports the outermost
    foreign directory of each kind; nothing below one is inspected.
    """
    root = pathlib.Path(root).resolve()
    skip = frozenset(skip_dirs)
    found: dict[str, list[pathlib.Path]] = {kind: [] for kind in FOREIGN_KINDS}
    for dirpath, dirnames, _ in os.walk(root):
        here = pathlib.Path(dirpath)
        keep: list[str] = []
        for name in sorted(dirnames):
            if name in skip:
                continue
            child = here / name
            kind = foreign_kind(child)
            if kind is not None:
                found[kind].append(child)
                continue
            keep.append(name)
        dirnames[:] = keep
    return found

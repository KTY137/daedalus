"""Isolated git worktrees for candidate (agent-written) code.

CONTAINMENT IS THE POINT OF THIS MODULE
---------------------------------------
``cleanup_worktree`` runs a recursive delete, unattended, in a ``finally:``
block (see :mod:`daedalus.spine.attempt`), against a directory that CANDIDATE
CODE HAS BEEN WRITING TO. That makes the directory argument attacker-influenced
data, not a trusted path, and it makes the deletion a fail-closed decision:

    A cleanup target is deleted only if the manager can prove it is the thing
    the manager itself allocated. Anything unproven raises
    :class:`WorktreeContainmentError` and nothing is removed.

The concrete attack this defends against: candidate code deletes its own
worktree directory and replaces it with a symlink -- or, on Windows, a
directory junction (``mklink /J``), which ``os.path.islink`` DOES NOT SEE --
aimed at the developer's primary checkout. Three mechanisms then destroy the
repository. Every claim below was measured on this box (Windows 11, CPython
3.10.11, git 2.38.1), and the measurement is named so the next reader can
re-run it instead of trusting this paragraph:

1. ``Path.resolve()`` before the safety check turns the link into its target,
   so the subsequent delete is handed a real directory (the primary checkout)
   and never sees a link at all. This is why nothing here resolves before it
   checks: **check no-follow first, then operate on the unresolved path.**
2. ``git worktree remove --force`` performs its own recursive delete and
   FOLLOWS a junction planted inside the worktree (measured: exit 0, empty
   stderr, target contents gone). So git's removal is not used at all any more.
3. ``shutil.rmtree`` is NOT a safe substitute either, though not for the reason
   an earlier version of this docstring gave. It DOES refuse a junction that is
   already in place when the walk starts -- CPython's ``shutil._rmtree_isdir``
   rejects ``IO_REPARSE_TAG_MOUNT_POINT`` (measured: victim intact). But that
   classification is read from ``DirEntry.stat(follow_symlinks=False)``, which
   on Windows is served from the PARENT directory's ``scandir`` cache and is
   never refreshed: measured, a ``DirEntry`` for a path that has since become a
   junction still reports ``st_reparse_tag == 0``, and ``_rmtree_isdir``
   returns True for it. So a live process that swaps an ALREADY-ENUMERATED
   sibling for a junction is followed -- measured 3/3 victims destroyed against
   the last entry of a large directory.

This module therefore owns the delete, via :func:`_remove_tree_no_follow`,
whose invariant is that every path handed to a syscall that RESOLVES it --
``os.scandir``, ``os.rmdir``, ``os.unlink``, ``os.chmod``, all four of them --
is re-classified with a FRESH ``lstat`` immediately beforehand;
``git worktree prune`` then deregisters. That narrows the window to a few
microseconds. It does not close it -- see the "WHAT IS STILL NOT CLOSED" note
on that function. Candidate code that must not even be able to TRY this needs
OS-level isolation; this module is path hygiene, and path hygiene has a floor.

WHERE THE FLOOR IS, CONCRETELY. Path hygiene cannot see an attack that uses no
path trickery at all: the candidate ``os.rename``s the primary checkout INTO its
own worktree, and every check then passes honestly, because what the walker
finds is a real directory in a place it really is entitled to delete (measured,
3/3, whole checkout gone, cleanup returned success). What exists against it is
one mitigation, not a fix -- see
:meth:`GitWorktreeManager._refuse_if_the_primary_checkout_moved`.

That mitigation is an IDENTITY check, and an earlier version of this paragraph
said it "knows the identity of exactly ONE directory". That was wrong twice
over. It was wrong about the SCOPE -- it now records the no-follow identity of
the checkout AND of every directory the checkout is reached through, because
the same attack one component higher (move the checkout's PARENT in, junction
the parent's name) went straight past a leaf-only check: measured, 40/40 work
files destroyed. And it was wrong about the STRENGTH: what it knows is not an
identity it cannot be lied to about. It read that identity with ``os.stat``,
which FOLLOWS a reparse point, so the answer came back THROUGH the attacker's
own junction and matched. It reads ``os.lstat`` now. The honest statement is:
it knows the no-follow identity of the checkout's chain as of the moment this
manager was constructed, and forging one of those identities requires an object
that does not exist yet to be handed an inode number that a live object still
holds.

Refusals RAISE. A silently skipped cleanup leaks worktrees; a silently
followed one deletes a repository. Both are loud.
"""

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from daedalus.storage import require_storage

__all__ = [
    "GitWorktreeManager",
    "WorktreeContainmentError",
    "WorktreeRemovalRace",
    "remove_tree_no_follow",
]

# Bookkeeping directory, inside the manager's own worktree root and therefore
# OUTSIDE every worktree, so it can never show up in a candidate's `git status`
# or captured patch.
#
# WHAT THAT DOES NOT BUY, said here so this comment agrees with the trust-model
# note on `reap_branches`: it is NOT hidden from candidate code. A candidate is
# handed its own worktree path, and this directory is that path's parent's
# sibling -- one `.parent` away from something the candidate is told. Assume
# every byte in here is candidate-readable AND candidate-writable; that is why
# `reap_branches` treats an on-disk record as an attacker-supplied string and
# authorises nothing on it.
ALLOC_DIRNAME = ".daedalus-alloc"
ALLOC_SCHEMA = "daedalus-worktree-alloc/1"


class WorktreeContainmentError(RuntimeError):
    """A cleanup/commit target could not be proven to be an allocated worktree.

    Subclasses :class:`RuntimeError` so existing callers that report a failed
    cleanup rather than crashing keep working; the distinct type exists so a
    test can assert the refusal happened for the containment reason and not
    because some unrelated ``rmtree`` happened to fail.
    """


class WorktreeRemovalRace(WorktreeContainmentError):
    """A reparse point appeared ABOVE a removal that was already underway.

    Distinct from every other containment refusal, and the distinction is the
    whole point: the others mean "nothing was removed", this one means "the
    walk stopped partway, on purpose". Once a directory the walk is standing on
    has been redirected, no path it is still holding can be trusted, so it
    refuses to finish rather than repairing and continuing. A partially removed
    worktree is a leak; finishing the walk through a redirected ancestor is a
    deleted repository.
    """


def _worktree_root_for(repo_path: Path) -> Path:
    """Resolve the root directory that holds candidate worktrees for a repo.

    Worktrees must live OUTSIDE the primary checkout so they never pollute
    ``git status`` or whole-repo snapshot attribution. Placement, in order:

    1. ``DAEDALUS_WORKTREE_ROOT`` env override (still namespaced per repo).
    2. ``<OS profile>/.daedalus/worktrees`` -- the same profile directory the
       kill switch derives its control root from (``killswitch.OS_PROFILE_DIR``,
       read from the OS, not from an environment variable), so the permit and
       the candidate checkouts sit under one parent and neither can be
       redirected by editing ``%LOCALAPPDATA%``.

    Each repo gets its own subdirectory keyed by a short digest of the
    resolved repo path so distinct checkouts never collide.

    WHY NOT ``%LOCALAPPDATA%`` ANY MORE (2026-08-23, MEASURED). Two reasons,
    both found by the first armed loop run after the lease hand-down landed:
    the Microsoft-Store python virtualises ``%LOCALAPPDATA%`` into
    ``Packages/PythonSoftwareFoundation.Python.3.10_.../LocalCache/Local``
    (Odysseus F1 -- the control root left for the same reason), and the old
    root was 62 characters before the attempt directory even began:
    ``git worktree add`` then failed on this repository's own tracked paths
    (``runs/gates/write-surface-classification/<40 hex>/cas/<64 hex>.json``,
    154 characters) with Windows ``Filename too long`` -- every attempt ended
    ``worktree_failed``. The profile root is 15 characters shorter; the git
    side is additionally told ``core.longpaths=true`` (see ``_run_git``).
    """
    override = os.environ.get('DAEDALUS_WORKTREE_ROOT')
    if override:
        base = Path(override)
    else:
        # Lazy: killswitch is imported by the spine at a different layer, and
        # this module must stay importable on its own.
        from daedalus.spine.killswitch import OS_PROFILE_DIR
        base = OS_PROFILE_DIR / '.daedalus' / 'worktrees'
    digest = hashlib.sha256(str(repo_path).encode('utf-8')).hexdigest()[:12]
    return base / digest


# --------------------------------------------------------------------------- #
# path predicates -- all of these are NO-FOLLOW and purely lexical             #
# --------------------------------------------------------------------------- #
def _lexical(path: Path) -> Path:
    """Absolute-and-normalised WITHOUT touching the filesystem.

    ``os.path.normpath`` collapses ``..`` textually; unlike ``resolve()`` it
    cannot be redirected by a symlink, which is exactly the property needed
    before a containment decision.
    """
    return Path(os.path.normpath(os.path.abspath(str(path))))


def _key(path: Path) -> str:
    """Comparison form: case-folded on Windows, normalised everywhere."""
    return os.path.normcase(os.path.normpath(str(path)))


def _is_within(child: Path, parent: Path) -> bool:
    """True if ``child`` is ``parent`` or lies under it, lexically."""
    c, p = _key(child), _key(parent)
    if c == p:
        return True
    p = p.rstrip('\\/') or p
    return c.startswith(p + os.sep) or (os.altsep is not None and c.startswith(p + os.altsep))


def _is_reparse_point(path: Path) -> bool:
    """True for a symlink OR a Windows directory junction / mount point.

    ``os.path.islink`` is NOT sufficient on Windows: a junction created with
    ``mklink /J`` has reparse tag ``IO_REPARSE_TAG_MOUNT_POINT``, not
    ``...SYMLINK``, so ``islink`` returns False for it (measured on this
    machine). The ``FILE_ATTRIBUTE_REPARSE_POINT`` bit on ``lstat`` catches
    every reparse kind, including tags that do not exist yet.

    THE FIRST LINE IS THE ONLY ONE THAT EXISTS OFF WINDOWS, and it is worth
    saying because the two Windows-specific answers below it are what the
    junction tests exercise. ``st_file_attributes`` and ``st_reparse_tag`` are
    not members of a ``stat_result`` on Linux/macOS at all, so on those
    platforms both ``getattr`` calls yield the default and deleting the
    ``S_ISLNK``/``islink`` line turns this whole function into ``return False``
    -- every symlink followed, every guard in this file silently open. That
    mutation SURVIVED the suite until 2026-07-28; it is killed now by
    ``test_reparse_detection_off_windows_rests_on_the_symlink_branch``, which
    simulates the POSIX stat SHAPE rather than skipping off Windows.
    """
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return False
    if stat.S_ISLNK(st.st_mode) or os.path.islink(path):
        return True
    attrs = getattr(st, 'st_file_attributes', 0)
    if attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
        return True
    # Belt and braces: any non-zero reparse tag is a redirection of some kind.
    return bool(getattr(st, 'st_reparse_tag', 0))


def _path_identity(path: Path):
    """``(st_dev, st_ino)`` for ``path`` ITSELF, or ``None`` if it is not there.

    NO-FOLLOW, and that is the whole point. It reads ``os.lstat``, not
    ``os.stat``. An earlier version used ``os.stat``, which FOLLOWS a reparse
    point, and that made the identity FORGEABLE by the one primitive this
    module exists to defend against -- measured on this box, against the
    manager's own ``repo_path``:

        os.stat  (real directory)   ino=7318349396973012
        os.stat  (junction to it)   ino=7318349396973012   -> identity MATCHES
        os.lstat (junction to it)   ino=7318349396973013   -> identity DIFFERS

    So a candidate that renamed the checkout aside and hung a ``mklink /J``
    junction on its name was answering the "is the checkout still the directory
    I was created for?" question THROUGH its own decoy. Measured end to end
    before this was changed: 40/40 tracked work files, ``SENTINEL.txt`` and
    ``.git`` destroyed, with the containment layer never refusing (the
    ``RuntimeError`` that came back was ``git worktree prune`` noticing
    afterwards that the repository was gone).

    Measured on this box (Windows 11, CPython 3.10.11): ``lstat`` populates
    both fields for a DIRECTORY, ``os.rename`` PRESERVES them (same NTFS record
    under a new name -- so a renamed directory keeps its record and a fresh
    object cannot be handed that record while the renamed one still holds it),
    and a fresh directory OR JUNCTION created at the vacated name gets a
    different ``st_ino``. So this distinguishes "the same directory, still
    there" from "moved away", from "replaced by something wearing its name",
    and now from "replaced by a link TO ITSELF wearing its name" -- none of
    which path text can.

    ``st_ino`` is 0 on filesystems that do not expose one (FAT, some network
    mounts). Callers must treat a zero ``st_ino`` as NO identity rather than as
    a comparable value; see :meth:`GitWorktreeManager._refuse_if_the_primary_checkout_moved`,
    which is why that method also has a check that does not depend on inodes.
    """
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return None
    return (getattr(st, 'st_dev', 0), getattr(st, 'st_ino', 0))


def _lexists(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except (OSError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# removal that cannot escape the directory it was given                        #
# --------------------------------------------------------------------------- #
# NOTE ON ALL FOUR PRIMITIVES BELOW. ``os.chmod``, ``os.unlink`` and
# ``os.rmdir`` resolve their path ARGUMENT through a reparse point in any
# intermediate component, exactly as ``os.scandir`` does. (What they do NOT do
# is follow a reparse point that is the FINAL component -- rmdir removes the
# junction, unlink removes the link.) So none of them is safe on the strength
# of a check that happened earlier: every caller here re-verifies the whole
# chain immediately before calling them. An earlier version believed
# ``os.scandir`` was the only follower, and the rmdir drain that belief
# licensed was measured deleting 3000 directories inside a stand-in primary
# checkout, 3/3, while reporting success.
def _clear_readonly(path: Path) -> None:
    """Drop the read-only bit git sets on loose objects, best effort."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _unlink_reparse_point(path: Path) -> None:
    """Remove the LINK itself. Never touches what it points at.

    A directory symlink / junction is removed with ``rmdir``, a file symlink
    with ``unlink``; which one applies differs by platform and link kind, so
    both are tried.
    """
    try:
        os.rmdir(path)
        return
    except OSError:
        pass
    try:
        os.unlink(path)
    except OSError:
        _clear_readonly(path)
        os.unlink(path)


def _force_unlink(path: Path) -> None:
    try:
        os.unlink(path)
    except PermissionError:
        _clear_readonly(path)
        os.unlink(path)


def _force_rmdir(path: Path) -> None:
    try:
        os.rmdir(path)
    except PermissionError:
        _clear_readonly(path)
        os.rmdir(path)


def _chain_between(root: Path, target: Path) -> List[Path]:
    """``[root, ..., target]``: every component ``target`` is reached THROUGH.

    Walked upward by comparison KEY rather than with ``relative_to``, which is
    case-sensitive and would raise on Windows for a differently-cased spelling.
    An uncaught ``ValueError`` is not a refusal, so the callers translate this
    one deliberately.

    Raises ``ValueError`` if ``root`` is not on ``target``'s path.
    """
    chain = [target]
    current = target
    while _key(current) != _key(root):
        parent = current.parent
        if parent == current:
            raise ValueError(f"{root} is not on the path of {target}")
        current = parent
        chain.append(current)
    chain.reverse()
    return chain


def _remove_tree_no_follow(root: Path,
                           guarded_ancestors: Sequence[Path] = ()) -> None:
    """Recursively delete ``root`` without ever traversing a reparse point.

    THE INVARIANT, written so it can be checked rather than believed:

        EVERY path handed to a syscall that RESOLVES it -- ``os.scandir``,
        ``os.rmdir``, ``os.unlink``, ``os.chmod`` -- is re-classified with a
        FRESH ``lstat`` IMMEDIATELY beforehand, together with every component
        above it, up to and including ``guarded_ancestors``. There are exactly
        three such sites (the scan, the per-child unlink, the rmdir drain) and
        all three verify. No path in this function is acted on twice on the
        strength of one check.

    That re-check is the entire fix, and its absence was a live repository-
    deletion bug -- twice, in the same function, for the same reason.
    Classifying a path and acting on it later is wrong no matter how the queue
    is ordered, because the gap is however long the rest of the traversal
    takes. Three shapes of the same defect, all measured on this box with a
    live process in the tree swapping an already-classified directory for a
    junction, three trials each:

        this walker, no pop-time re-check, victim = FIRST entry   destroyed 3/3
          (a LIFO queue walks the first subdirectory of a parent LAST)
        this walker, WITH the pop-time re-check                   destroyed 0/3
        ``shutil.rmtree``, victim = LAST entry                    destroyed 3/3
          (its check reads the Windows ``scandir`` stat cache, never refreshed)
        this walker, pop-time re-check but UNVERIFIED rmdir drain,
          junction renamed over an already-drained subdirectory   destroyed 3/3
          (3000 empty directories inside a stand-in primary checkout, end to
          end through ``cleanup_worktree``, which RETURNED SUCCESS: no
          exception, prune run, allocation record stamped removed)

    So the bespoke walker earns its place -- but only with the re-check at all
    three sites, and not for the reason first claimed. ``shutil.rmtree`` is
    safe against a junction that is already in place and unsafe against one
    that appears mid walk; this function is safe against both.

    WHAT IS STILL NOT CLOSED
    ------------------------
    The few microseconds between each fresh ``lstat`` and the ONE syscall that
    follows it. Closing even that needs handle-relative traversal
    (``openat``/``O_NOFOLLOW``), which CPython does not expose on Windows --
    ``shutil`` only gets it on platforms where ``_use_fd_functions`` is True,
    and that is False here.

    Note what that sentence does NOT say. It is "one verification, one
    syscall", repeated N times -- not "two adjacent syscalls", which is what an
    earlier version of this note claimed while the code was in fact doing
    "verify once, then act N times": N unlinks per directory after a single
    verification of the parent, and M rmdirs per tree after none at all. Those
    are windows of milliseconds to seconds, not microseconds, and the second
    one was exploited end to end.

    THE EXCEPTIONS TO "ONE VERIFICATION, ONE SYSCALL", NAMED PRECISELY, because
    an earlier version of this note named only half of one of them. Both are
    RETRY paths, and on both the window is the retry, not just the ``chmod``:

    * :func:`_force_unlink` / :func:`_force_rmdir` on ``PermissionError``:
      ``unlink`` -> ``chmod`` -> ``UNLINK AGAIN`` (resp. ``rmdir``). The chmod
      is not the only thing that runs after the verification -- the SECOND
      REMOVING SYSCALL does too. This path is not exotic: it exists because git
      sets the read-only bit on loose objects, so a worktree removal takes it
      routinely.
    * :func:`_unlink_reparse_point`: ``rmdir`` -> ``unlink`` -> ``chmod`` ->
      ``unlink``, up to four syscalls on one verification.

    The window on those is two to three syscalls wide instead of one -- still
    microseconds, still one object, but it is not what the headline sentence
    says, so it is written down. Re-verifying inside the retry was CONSIDERED
    AND NOT DONE this round: ``_verify_reachable`` is a closure over the walk's
    ``root`` and ``guarded_ancestors``, so threading it into these four
    module-level helpers is a signature change to the primitives, and a guard
    added without a test that can kill it is exactly what this file has been
    punished for. It is follow-up #2 behind the hoisting below.

    WHAT IT COSTS, MEASURED, so the next reader is not guessing
    -----------------------------------------------------------
    THE COST SCALES WITH DEPTH, and an earlier version of this note did not say
    so: it measured depth 2 and 3, saw "roughly doubles", and generalised that
    to "noise where it lands". That generalisation is false for deep trees.

    At depth 2-3, verifying before every syscall roughly doubles the walk.
    Median of 3, this box, alternating runs on freshly built identical trees:

        1280 files / 128 dirs, depth 3   724 ms -> 1661 ms   (+130%)
        3000 empty dirs, depth 2        2411 ms -> 5023 ms   (+108%)

    Against DEPTH, 400 files at the leaf, median of 3, baseline = this same
    walker with the verification stubbed out entirely, so the only difference
    measured is the verification:

        depth  2    103 ms ->   320 ms    3.1x
        depth  6    101 ms ->   521 ms    5.2x
        depth 12    107 ms ->   874 ms    8.2x
        depth 20    129 ms ->  1380 ms   10.7x

    (An independent measurement with a weaker baseline -- the pre-verification
    walker, which still classified once -- got 2.2x / 3.0x / 4.3x / 5.9x for the
    same four depths. The multiplier depends on where the baseline is drawn;
    the DEPENDENCE ON DEPTH is what both measurements agree on, and it is the
    part that matters.)

    So the claim is scoped: at the shallow depths measured, and for a worktree
    of ordinary source files, the cost is noise against a model call and a
    pytest gate. It is NOT noise for a worktree containing ``node_modules`` or
    a ``.venv`` -- 30k-200k files at depth 8-15 -- where this puts an
    unattended cleanup into tens of seconds to minutes INSIDE A ``finally:``.
    A cleanup slow enough to be killed, or to look hung, is its own hazard.

    The cost is NOT dominated by the ``lstat`` calls (roughly 5k of them in the
    1280-file case, tens of milliseconds) but by rebuilding the lexical chain in
    Python for every child, which is O(depth) per child -- hence the scaling
    above. The available optimisation, named rather than taken: the chain is
    PURE TEXT, so hoisting ``_chain_between`` out of the per-child loop would
    recover most of it WITHOUT weakening the invariant, because the fresh
    ``lstat`` per component per syscall is what the invariant is, not the chain
    construction. It was not taken here on purpose: this function has now
    shipped two live repository-deletion bugs, and the round that fixes them is
    the wrong round to add a caching layer to it. Stated plainly for whoever
    picks this up: that hoist is now the TOP follow-up on this file.

    Raises ``OSError`` on failure and :class:`WorktreeRemovalRace` if a reparse
    point appears above ANY step -- the scan, the unlinks, or the drain. A
    partial delete is reported, never swallowed. That sentence was false as
    written until 2026-07-28: the drain had no verification, so a partial
    delete THROUGH a swapped ancestor was neither detected nor reported, and
    ``cleanup_worktree`` returned normally on top of it.
    """
    root = Path(root)
    guarded = [Path(p) for p in guarded_ancestors]

    def _verify_reachable(target: Path) -> None:
        """Re-classify, FRESHLY, everything ``target`` will be read through.

        A reparse point strictly above ``target`` redirects it wholesale, and
        unlinking that ancestor would delete a link the manager does not own,
        so this refuses instead of repairing.
        """
        try:
            above = _chain_between(root, target)[:-1]
        except ValueError as e:
            raise WorktreeRemovalRace(
                f"refusing to continue removing {root}: {e}") from e
        for component in [*guarded, *above]:
            if _is_reparse_point(component):
                raise WorktreeRemovalRace(
                    f"refusing to continue removing {root}: {component} became "
                    f"a symlink or Windows junction (reparse point) DURING the "
                    f"removal, which redirects every path beneath it. The tree "
                    f"is PARTIALLY REMOVED.")

    # Does it exist at all? That is the only question answered here. Whether a
    # path is a reparse point, a file, or a directory is decided in exactly ONE
    # place -- when it is POPPED, immediately before it is opened -- and the
    # root is not special-cased. An earlier version classified the root here as
    # well as in the loop; mutation testing showed the extra branch could be
    # deleted without any test noticing, because the pop-time check already
    # covers it. A second classification site is a second thing to keep right.
    os.lstat(root)               # raises FileNotFoundError if it vanished

    pending: List[Path] = [root]
    directories: List[Path] = []
    while pending:
        current = pending.pop()
        # RE-CHECK 1 OF 3 (the others are in the entry loop and the drain, and
        # each one is separately load-bearing -- see the mutation notes). What-
        # ever put `current` on the queue classified it when its parent was
        # enumerated; by now that classification is arbitrarily old, and a live
        # process in the tree has had the whole intervening traversal to
        # invalidate it. What this one specifically stops, measured: a swap of
        # an ancestor AFTER `current` was queued, which sends the
        # not-a-directory branch below into an os.unlink outside the tree.
        _verify_reachable(current)
        if _is_reparse_point(current):
            _unlink_reparse_point(current)
            continue
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            continue             # it went away on its own; nothing to remove
        if not stat.S_ISDIR(st.st_mode):
            # It was a directory when it was queued and is a file now. Unlink
            # it rather than handing a non-directory to scandir.
            _force_unlink(current)
            continue
        directories.append(current)
        with os.scandir(current) as it:
            entries = list(it)   # materialise before mutating the directory
        for entry in entries:
            child = Path(entry.path)
            # RE-VERIFIED PER CHILD, not once per directory. `entries` can be
            # thousands long, and `current` can be renamed aside and a junction
            # renamed into its place between any two iterations -- a rename does
            # not require the directory to be empty, so that swap is available
            # to a live candidate at every moment of this loop. os.unlink
            # resolves the path argument it is given through a reparse point in
            # an intermediate component, so an unlink here that trusts the
            # verification done when `current` was popped deletes FILE CONTENT
            # outside the tree, which is strictly worse than the drain defect
            # below. One verification, one syscall.
            _verify_reachable(child)
            # A FRESH lstat, deliberately not entry.stat(): on Windows the
            # DirEntry's stat is served from this scandir's cache (measured),
            # so asking the DirEntry would re-introduce the stale read.
            #
            # HONEST NOTE ON THIS BRANCH: mutation testing shows the suite does
            # NOT go red if it is deleted, and that is not an oversight in the
            # tests -- it is redundant on this platform, measured both ways. A
            # junction is reported as a directory by is_dir(follow_symlinks=
            # False), so it would be queued and then unlinked by the pop-time
            # check; a directory symlink is NOT, so it would fall to
            # _force_unlink, and os.unlink removes a Windows directory symlink
            # without following it (measured: link gone, target intact). It is
            # kept because both of those are platform behaviours rather than
            # guarantees, and because it makes the intent explicit at the point
            # of the decision. It is documented here rather than claimed as
            # tested, because an untested branch presented as a guard is how
            # the previous round of this file shipped green over a live bug.
            if _is_reparse_point(child):
                _unlink_reparse_point(child)
            elif entry.is_dir(follow_symlinks=False):
                # Cached, and allowed to be: nothing is traversed on the
                # strength of it -- `child` is re-classified when it is popped.
                pending.append(child)
            else:
                # Also cached, also safe: os.unlink removes a link rather than
                # following it, so the worst case is a loud failure.
                _force_unlink(child)
    for directory in reversed(directories):
        # Children before parents: a parent is always popped before its
        # children are queued, so its index is lower.
        #
        # RE-VERIFIED PER DIRECTORY. Every entry here was classified when it was
        # POPPED, which for the first one drained is the ENTIRE walk ago, and
        # os.rmdir resolves its path argument through a reparse point in an
        # intermediate component exactly as os.scandir does. An unverified drain
        # therefore lets a junction renamed over an already-drained
        # subdirectory redirect every remaining rmdir out of the tree. Measured,
        # 3/3, end to end through cleanup_worktree: 3000 empty directories
        # removed inside a stand-in primary checkout, reported as success.
        _verify_reachable(directory)
        if _is_reparse_point(directory):
            # Not repaired by unlinking the link: this directory was emptied by
            # the walk above, so whatever is here now is not what was emptied,
            # and the link is not the manager's to delete. Refuse, and report
            # the tree as partially removed.
            raise WorktreeRemovalRace(
                f"refusing to continue removing {root}: {directory} became a "
                f"symlink or Windows junction (reparse point) between being "
                f"walked and being removed, so it is no longer the directory "
                f"this walk emptied. The tree is PARTIALLY REMOVED.")
        _force_rmdir(directory)


def _effect_boundary():
    """The spine's effect boundary, imported at call time.

    LAZY, and not because of a cycle -- ``daedalus.spine.effect_boundary``
    imports nothing but the standard library, so a module-level import would
    work. It is lazy for weight: that module is a 3.5k-line registry with an
    AST scanner in it, and this manager is imported by callers that only want
    to read a worktree root. ``reap_branches`` already paid for it this way;
    the three doors migrated on 2026-08-25 share the same call rather than
    repeating the import block four times.

    Returns:
        ``(REGISTRY_BY_ID, GuardDecision, begin_effect)``. The callers bind
        ``begin_effect`` to a local name on purpose: the registry's guard
        anchor is a mechanical AST check for a literal ``begin_effect`` call
        in the migrated method, so hiding the call behind a wrapper here would
        silently move the anchor off the boundary it is meant to pin.
    """
    from daedalus.spine.effect_boundary import (
        REGISTRY_BY_ID,
        GuardDecision,
        begin_effect,
    )
    return REGISTRY_BY_ID, GuardDecision, begin_effect


def remove_tree_no_follow(root: Path,
                          guarded_ancestors: Sequence[Path] = ()) -> None:
    """Public name for :func:`_remove_tree_no_follow`.

    Exists so other modules that must delete a directory candidate code could
    have reached do not have to import a private, and do not reach for
    ``shutil.rmtree`` because the safe thing looked internal. The one caller
    outside this module today is the default pytest gate's scratch directory
    (:mod:`daedalus.spine.attempt`), which is created in ``%TEMP%`` under a
    predictable ``daedalus-gate-`` prefix while candidate code is running as
    this same user.

    Deliberately delegates rather than being aliased, so a test that
    monkeypatches ``_remove_tree_no_follow`` also intercepts this path.
    """
    _remove_tree_no_follow(root, guarded_ancestors=guarded_ancestors)


class GitWorktreeManager:
    """Manages isolated Git worktrees for agent execution."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        # The ONLY thing :meth:`reap_branches` is allowed to act on. In memory
        # on purpose: the on-disk allocation directory is candidate-writable
        # (a candidate is handed its worktree path, and the alloc dir is its
        # parent's sibling), so a record on disk is an attacker-supplied
        # string, not evidence. Process memory is the one store the candidate
        # cannot reach -- see the trust-model note on reap_branches.
        self._allocations: Dict[str, dict] = {}
        # What the primary checkout WAS when this manager was made, NO-FOLLOW.
        # Compared again before every unattended recursive delete -- see
        # _refuse_if_the_primary_checkout_moved.
        self._repo_identity = _path_identity(self.repo_path)
        # ...and what every directory the checkout is REACHED THROUGH was. A
        # leaf-only check is bypassed by moving the checkout's PARENT instead of
        # the checkout (measured: 40/40 work files destroyed, leaf identity
        # still matching, because the leaf was being read through the junction
        # that had replaced its parent).
        #
        # CALIBRATED AT CONSTRUCTION, deliberately: it records whatever is there
        # and later demands only that it be UNCHANGED. It must never refuse a
        # machine's layout -- checkouts legitimately live under redirected
        # profile folders, OneDrive placeholders and developer junctions -- so
        # "is a reparse point" is not the question asked of an ancestor. "Is it
        # the same object it was" is.
        self._repo_ancestor_identity = [
            (parent, _path_identity(parent))
            for parent in reversed(list(_lexical(self.repo_path).parents))
        ]

    @property
    def worktree_root(self) -> Path:
        """Directory (outside the repo) where this repo's worktrees are placed."""
        return _worktree_root_for(self.repo_path)

    def _run_git(self, *args, cwd: Optional[Path] = None) -> str:
        """Executes a git command in the specified directory.

        On Windows every call carries ``-c core.longpaths=true``: a candidate
        checkout lands under a root plus a 57-character attempt name, and this
        repository tracks paths 154 characters deep, so without it
        ``worktree add`` fails with ``Filename too long`` and no attempt can
        run (MEASURED 2026-08-23, loop-20260823-143755-a60bad). A per-command
        ``-c`` changes nothing in the repository's or the user's git config.
        """
        cmd = ['git']
        if os.name == 'nt':
            cmd += ['-c', 'core.longpaths=true']
        cmd += list(args)
        cwd_path = cwd or self.repo_path
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git command failed: {' '.join(cmd)}\nError: {e.stderr}")

    # -- allocation bookkeeping -------------------------------------------- #
    #
    # Identity is recorded at CREATION time, because a path string is not an
    # identity -- the manager is the only party that knows what it allocated.
    # The record lives outside every worktree, so candidate code cannot forge
    # or delete its own, and it is on disk rather than in memory, so a FRESH
    # manager in a NEW process can still clean up a worktree leaked by a crash.
    def _alloc_dir(self) -> Path:
        return self.worktree_root / ALLOC_DIRNAME

    def _alloc_file(self, worktree_path: Path) -> Path:
        digest = hashlib.sha256(_key(worktree_path).encode('utf-8')).hexdigest()[:32]
        return self._alloc_dir() / f"{digest}.json"

    def _record_allocation(self, worktree_path: Path, branch_name: str,
                           **extra) -> None:
        """Written BEFORE ``git worktree add`` runs.

        Ordering matters for crash-safety: anything that can exist on disk must
        already have a record, otherwise a crash mid-``add`` leaves a directory
        that cleanup would (correctly, but uselessly) refuse forever.
        """
        record = {
            "schema": ALLOC_SCHEMA,
            "path": str(worktree_path),
            "repo": str(self.repo_path),
            "branch": branch_name,
            "created_ts": datetime.now(timezone.utc).isoformat(),
        }
        record.update(extra)
        self._write_allocation(worktree_path, record)

    def _write_allocation(self, worktree_path: Path, record: dict) -> None:
        alloc_dir = self._alloc_dir()
        alloc_dir.mkdir(parents=True, exist_ok=True)
        self._alloc_file(worktree_path).write_text(
            json.dumps(record, indent=2), encoding='utf-8')

    def _read_allocation(self, worktree_path: Path) -> Optional[dict]:
        record_file = self._alloc_file(worktree_path)
        if _is_reparse_point(record_file) or not record_file.is_file():
            return None
        try:
            record = json.loads(record_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict) or record.get("schema") != ALLOC_SCHEMA:
            return None
        if _key(Path(str(record.get("path", "")))) != _key(worktree_path):
            return None
        if _key(Path(str(record.get("repo", "")))) != _key(self.repo_path):
            return None
        return record

    def _discard_allocation(self, worktree_path: Path) -> None:
        try:
            self._alloc_file(worktree_path).unlink()
        except OSError:
            pass

    # -- the containment decision ------------------------------------------ #
    def _refuse(self, target: Path, why: str) -> "WorktreeContainmentError":
        return WorktreeContainmentError(
            f"refusing to operate on {target}: {why}. "
            f"(repo={self.repo_path}, worktree_root={self.worktree_root}) "
            f"Nothing was removed."
        )

    def _reach_chain(self, target: Path) -> List[Path]:
        """``[worktree_root, ..., target]`` -- what ``target`` is reached through.

        Step 3 of :meth:`_require_allocated_worktree` checks this chain once,
        before the decision; :func:`_remove_tree_no_follow` re-checks it on
        every directory it opens, because "checked once, before" is exactly the
        stale classification that let a repository be deleted.
        """
        try:
            return _chain_between(_lexical(self.worktree_root), _lexical(target))
        except ValueError:
            raise self._refuse(target, "the worktree root is not on its path")

    def _refuse_if_repo_adjacent(self, candidate: Path, label: str) -> None:
        if _is_within(self.repo_path, candidate) or _is_within(candidate, self.repo_path):
            raise self._refuse(
                candidate,
                f"the {label} is the primary checkout, an ancestor of it, or "
                f"inside it")

    def _refuse_if_the_primary_checkout_moved(self) -> None:
        """Refuse an unattended recursive delete if the checkout is not where it was.

        A MITIGATION, NOT A CLOSURE. The attack it is aimed at is the one no
        reparse check can ever see, because no reparse point is involved:

            candidate: os.rename(<primary checkout>, <worktree>/moved_in)

        Every containment check then passes honestly -- what the walker finds
        is a real directory, in a place it really is entitled to delete -- and
        the whole checkout is destroyed with cleanup returning success
        (measured, this box, 3/3). The real answer is OS-level isolation; this
        is the cheap thing available at this layer, and it is stated as such.

        WHAT IT CATCHES: the checkout being moved (or replaced by something
        wearing its name) between this manager being constructed and a cleanup
        running. Which is the shape of the attack above, because moving the
        checkout INTO the worktree necessarily vacates its own path.

        HOW IT ANSWERS THAT, AND HOW IT WAS DEFEATED. The question "is the
        checkout still the directory I was created for?" is answered by
        comparing ``(st_dev, st_ino)``. That answer was FORGEABLE until
        2026-07-28, by the module's own signature primitive:

            os.rename(<checkout>, <worktree>/moved_in)
            mklink /J <checkout> <worktree>/moved_in

        ``_path_identity`` read ``os.stat``, which FOLLOWS the junction, so the
        identity came back through the attacker's decoy and MATCHED. Measured
        end to end against this manager's own ``repo_path``: 40/40 tracked work
        files, ``SENTINEL.txt`` and ``.git`` destroyed, nothing refused (the
        ``RuntimeError`` the caller saw was ``git worktree prune`` complaining
        afterwards that the repository was gone). Three checks now stand where
        one did, and none of them is decoration:

        1. ``repo_path`` MUST NOT BE A REPARSE POINT. ``__init__`` calls
           ``.resolve()``, so a legitimate ``repo_path`` is a fully resolved
           real directory and can never be one; if it is one now, something put
           it there. This is the check that survives a filesystem with no
           usable ``st_ino`` (FAT, some network mounts), where 2 and 3 are
           switched off by their own zero-inode guard and would let the junction
           decoy straight through.
        2. THE LEAF IDENTITY, no-follow. Catches the decoy that is a real
           directory (a fresh ``mkdir`` at the vacated name), which check 1
           cannot see.
        3. THE ANCESTOR IDENTITIES, no-follow, calibrated at construction.
           Catches the same attack one component up -- move the checkout's
           PARENT in and junction the PARENT's name -- which defeats 1 and 2
           together, because ``repo_path`` itself is then a real directory being
           read through a junction ABOVE it. Measured before this check existed:
           40/40 work files destroyed, leaf identity matching, both stat and
           lstat agreeing, cleanup raising only ``NotADirectoryError`` after the
           damage. Calibrated rather than absolute because a checkout may
           legitimately sit under a redirected profile folder or a developer's
           own junction; what is refused is a CHANGE, not a layout.

        WHAT IT DOES NOT CATCH, so nobody reads more into it than is there:

        * anything ELSE the candidate moves in -- a sibling checkout, a
          documents folder, another worktree. This manager knows the identity of
          the checkout and of the chain above it, and of nothing else.
        * a move performed AFTER this check and before the walk reaches it. The
          window is smaller than the whole cleanup, and it is not zero.
        * a filesystem with no ``st_ino``. Checks 2 and 3 disable themselves
          there (a zero inode is not an identity, and comparing zeroes would
          make every directory equal to every other). Check 1 still holds at the
          leaf; NOTHING holds on an ancestor.
        * the case where the candidate moves the checkout in and then restores
          something at the old path with the SAME identity. It cannot do that
          with a fresh directory or a junction, because the moved directory
          still holds its NTFS record and a record in use cannot be reissued --
          measured, and that is why check 2 works at all. But "cannot on NTFS
          today" is a platform behaviour, not a guarantee, and it is exactly the
          assumption check 1 exists so as not to depend on.

        Refusing leaks the worktree (and, in the attack, leaves the checkout
        alive inside it). That is the correct direction: a leak is recoverable
        by hand, a deleted checkout is not.
        """
        # 1. no-follow, and inode-free: the one check that still works when the
        #    filesystem has no identities to compare.
        if _is_reparse_point(self.repo_path):
            raise self._refuse(
                self.repo_path,
                "the primary checkout's own path is now a symlink or Windows "
                "junction (reparse point), not the real directory this manager "
                "was created for: it was moved and a link was hung on its name, "
                "which makes every identity read through it a forgery")

        # 2. the leaf, no-follow.
        current = _path_identity(self.repo_path)
        if current is None:
            raise self._refuse(
                self.repo_path,
                "the primary checkout is no longer at its own path, so this "
                "manager cannot tell an ordinary cleanup from a recursive "
                "delete of a checkout that has been moved somewhere it is "
                "entitled to delete")
        recorded = self._repo_identity
        if recorded is not None and recorded[1] and current != recorded:
            raise self._refuse(
                self.repo_path,
                f"the primary checkout at this path is not the directory this "
                f"manager was created for (identity {recorded} -> {current}): "
                f"it was moved and something else now wears its name")

        # 3. everything the checkout is reached THROUGH. `now` is None when the
        #    component has vanished, and None never equals a recorded identity,
        #    so "gone" and "swapped" are the same refusal on purpose.
        for component, was in self._repo_ancestor_identity:
            if was is None or not was[1]:
                continue         # nothing was recorded here; nothing to compare
            now = _path_identity(component)
            if now != was:
                raise self._refuse(
                    self.repo_path,
                    f"{component}, which the primary checkout is reached "
                    f"THROUGH, is not the directory it was when this manager "
                    f"was created (identity {was} -> {now}): the checkout may "
                    f"have been moved wholesale by moving a parent, and every "
                    f"path below that component now means something else")

    def _require_allocated_worktree(self, path: str | Path) -> Path:
        """Prove ``path`` is a worktree this manager allocated, or raise.

        Ordering is the whole defect being fixed, so it is spelled out:
        every check below is lexical or no-follow, and the returned path is the
        UNRESOLVED one -- callers operate on exactly what was checked.
        """
        target = _lexical(Path(path))
        root = _lexical(self.worktree_root)

        # 1. inside the manager's own root, and never the root itself.
        if _key(target) == _key(root) or not _is_within(target, root):
            raise self._refuse(
                target, "it is not a worktree directory under this manager's "
                        "worktree root")

        # 2. never the primary checkout, an ancestor of it, or anything in it.
        self._refuse_if_repo_adjacent(target, "path")

        # 3. no symlink / junction anywhere from the worktree root down. Checked
        #    top-down and BEFORE any resolution: a reparse point at any level
        #    can redirect everything below it.
        for component in self._reach_chain(target):
            if _is_reparse_point(component):
                raise self._refuse(
                    target,
                    f"{component} is a symlink or Windows junction (reparse "
                    f"point); an allocated worktree is always a real directory")

        # 4. only now is resolution trustworthy -- nothing at or below the root
        #    can redirect it. Re-check the repo relation on the resolved form so
        #    a root that itself sits under a symlinked prefix cannot smuggle the
        #    target back into the checkout.
        try:
            resolved = Path(os.path.realpath(str(target)))
            resolved_root = Path(os.path.realpath(str(root)))
        except OSError as e:
            raise self._refuse(target, f"the path could not be examined: {e}")
        self._refuse_if_repo_adjacent(resolved, "resolved path")
        if not _is_within(resolved, resolved_root):
            raise self._refuse(
                target, f"it resolves to {resolved}, which is outside the "
                        f"worktree root {resolved_root}")

        # 5. it must actually be there, as a real directory (no-follow).
        if not _lexists(target):
            raise self._refuse(
                target, "it no longer exists -- it was renamed, moved, or "
                        "already removed, so there is nothing this manager may "
                        "safely delete")
        if not stat.S_ISDIR(os.lstat(target).st_mode):
            raise self._refuse(target, "it is not a directory")

        # 6. it must be something THIS manager allocated for THIS repo.
        if self._read_allocation(target) is None:
            raise self._refuse(
                target, "this manager has no creation-time allocation record "
                        "for it (not allocated here, or moved out from under "
                        "the manager)")
        return target

    def create_worktree(self, base_commit: str, branch_name: str) -> Path:
        """
        Creates a new git worktree branching from a specific commit.

        Args:
            base_commit: The commit hash or reference to branch from.
            branch_name: The name of the new branch to create.

        Returns:
            The path to the new worktree.

        Raises:
            WorktreeContainmentError: If the requested placement escapes the
                manager's worktree root or touches the primary checkout.
            StorageUnavailable: If the worktree root volume is missing or below
                the free-space watermark (fail-closed; never spills elsewhere).
        """
        root = self.worktree_root
        worktree_path = _lexical(root / branch_name)

        # An allocation that cannot be contained is refused before anything is
        # created: `..` in a branch name would otherwise place a candidate
        # worktree (and later, a recursive delete) outside the root.
        #
        # ORDER IS DELIBERATE, and it is what makes each of these testable on
        # its own. "Is this inside the developer's checkout?" is the worst
        # answer, so it is asked FIRST and named precisely; asking it after the
        # escape check would make it unreachable, because a path that escapes
        # the root INTO the checkout would already have been refused with the
        # generic reason. (Measured: with the escape check first, deleting the
        # allocation-path check changed nothing any test could see.)
        #
        # WHAT IS NOT HERE, and why. There used to be a second lexical call,
        # `_refuse_if_repo_adjacent(_lexical(root), "worktree root")`. It is
        # DOMINATED -- 0 counterexamples in 216,225 enumerated (root, repo,
        # branch) shapes -- but NOT for the reason an earlier version of this
        # comment gave. That version claimed the allocation-path check on the
        # line below covers everything the root check did. It does not: with the
        # RESOLVED-root check disabled, 955 of those shapes survive, every one
        # of the form "the root is a strict ANCESTOR of the checkout and the
        # allocation path is a sibling of it" (root C:/a, repo C:/a/a, branch
        # tb). The allocation path in those is repo-adjacent to nothing, so the
        # line below stays silent.
        #
        # What actually covers them is the RESOLVED-root check further down: on
        # a genuine ancestor chain with no reparse points, realpath is the
        # identity map, so the resolved root is still that strict ancestor and
        # `_refuse_if_repo_adjacent` fires on it. The removed guard is dominated
        # by the pair, not by the allocation path alone -- and its replacement
        # is not dominated in return, because it also catches the case the whole
        # lexical pair was blind to (a junction inside DAEDALUS_WORKTREE_ROOT).
        self._refuse_if_repo_adjacent(worktree_path, "allocation path")
        if _key(worktree_path) == _key(_lexical(root)) or not _is_within(worktree_path, _lexical(root)):
            raise WorktreeContainmentError(
                f"refusing to allocate a worktree at {worktree_path}: it "
                f"escapes the worktree root {root}")

        # `_worktree_root_for` is PURE TEXT -- it reads an env var and appends a
        # digest -- so a single junction anywhere in DAEDALUS_WORKTREE_ROOT
        # lands the entire worktree root inside the developer's checkout while
        # every lexical check above passes. `cleanup_worktree` catches that case
        # (step 4), but only when it is time to delete: by then the candidate
        # has already been created inside the checkout and its files are in the
        # developer's `git status`. Creation is where that has to be refused.
        try:
            resolved_root = Path(os.path.realpath(str(_lexical(root))))
        except OSError as e:
            raise WorktreeContainmentError(
                f"refusing to allocate a worktree under {root}: the worktree "
                f"root could not be examined: {e}")
        self._refuse_if_repo_adjacent(resolved_root, "resolved worktree root")

        # CENTRAL START, and this is the last line before the first byte moves.
        # Everything above is a refusal; `mkdir` below is the first effect, so
        # the receipt is written for a worktree that is ABOUT to exist, not for
        # one that already does. The evidence quotes the three checks that just
        # ran rather than asserting containment in the abstract -- a decision
        # whose evidence names no check is the thing `begin_effect` refuses.
        registry, GuardDecision, begin_effect = _effect_boundary()
        begin_effect(
            "worktree.create",
            registry["worktree.create"].effects,
            (
                GuardDecision(
                    "containment.worktree",
                    True,
                    f"allocation path {worktree_path} is not repo-adjacent, "
                    f"lies strictly under the worktree root {_lexical(root)}, "
                    f"and the resolved root {resolved_root} is not "
                    f"repo-adjacent either; all three checked before any "
                    f"directory is created",
                ),
            ),
        )

        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        require_storage(str(worktree_path.parent))

        # Identity first: a directory that exists without a record is a
        # directory nothing is allowed to delete.
        self._record_allocation(worktree_path, branch_name)

        # Create a new branch and worktree
        try:
            self._run_git('worktree', 'add', '-b', branch_name, str(worktree_path), base_commit)
        except RuntimeError:
            # A PARTIAL create. `git worktree add -b` writes the ref into the
            # shared .git first and populates the directory second, so a
            # checkout that dies half-way (MEASURED 2026-08-23: Windows
            # "Filename too long" at 70% of 2,764 files) leaves a ref, a
            # registration and a half-filled directory behind. The directory
            # and the registration are cleaned HERE, because nothing else will
            # ever be handed this path. The ref is deliberately NOT deleted
            # here (Codex, room 56): the attempt's intent was recorded before
            # this call and is resolved only after the exception reaches the
            # caller, so a synchronous delete would reopen the crash window in
            # which an OPEN intent has no findable effect key. Instead the
            # partial allocation is registered in memory exactly as a cleaned
            # worktree would be, and the ref falls to `reap_branches` after the
            # terminal ledger write, under the same two proofs as every other
            # branch (tip unchanged since allocation, still reachable).
            self._abandon_partial_create(worktree_path, branch_name)
            raise

        # Pin the branch tip as created. Later this is the ONLY thing that can
        # prove a candidate branch holds no work -- a sha comparison, not a
        # heuristic and not a locale-dependent message from `git branch -d`.
        try:
            tip = self._run_git('rev-parse', '--verify', f'refs/heads/{branch_name}')
        except RuntimeError:
            tip = None
        self._record_allocation(worktree_path, branch_name,
                                branch_tip_at_creation=tip)
        # The in-memory twin of the record. This, not the file, is what may
        # later authorise deleting a branch.
        self._allocations[_key(worktree_path)] = {
            "path": worktree_path,
            "branch": branch_name,
            "branch_tip_at_creation": tip,
            "worktree_removed": False,
        }

        return worktree_path

    def _abandon_partial_create(self, worktree_path: Path, branch_name: str) -> None:
        """Tidy what a failed ``git worktree add`` left, keeping the ref.

        Never raises: the caller is already propagating the creation error and
        a second error here would hide the first. What could not be cleaned is
        left for ``reap_branches`` to report.
        """
        tip = None
        try:
            tip = self._run_git('rev-parse', '--verify', f'refs/heads/{branch_name}')
        except RuntimeError:
            tip = None          # the ref was never written; nothing to reap
        try:
            if worktree_path.exists():
                _remove_tree_no_follow(
                    worktree_path,
                    guarded_ancestors=self._reach_chain(worktree_path)[:-1])
        except (OSError, RuntimeError):
            pass
        try:
            self._run_git('worktree', 'prune')
        except RuntimeError:
            pass
        record = {
            "path": worktree_path,
            "branch": branch_name,
            "branch_tip_at_creation": tip,
            # Through cleanup in the only sense that matters to reap: nothing
            # of this allocation is in use, and nothing on disk remains.
            "worktree_removed": True,
            "partial_create": True,
        }
        self._allocations[_key(worktree_path)] = record
        try:
            self._record_allocation(worktree_path, branch_name,
                                    branch_tip_at_creation=tip)
        except Exception:  # noqa: BLE001 - the on-disk twin is diagnostic only
            pass

    def cleanup_worktree(self, path: str | Path) -> None:
        """
        Removes a git worktree and cleans up the directory.

        The target must be PROVEN to be a worktree this manager allocated (see
        :meth:`_require_allocated_worktree`); anything else raises without
        removing a thing. The removal itself is done here rather than by
        ``git worktree remove --force``, which follows reparse points planted
        inside the tree; ``git worktree prune`` then deregisters it.

        The candidate BRANCH is deliberately left alone here -- see
        :meth:`reap_branches` for why deleting it in this call would be wrong.

        Args:
            path: The path to the worktree to remove.

        Raises:
            WorktreeContainmentError: If the target cannot be proven to be an
                allocated worktree, or if the primary checkout is no longer the
                directory this manager was created for. Nothing is removed in
                either case.
            WorktreeRemovalRace: If a reparse point appeared above the removal
                while it was underway. The tree is PARTIALLY removed and that is
                what the exception says; it is deliberately not repaired.
            RuntimeError: If the worktree directory could not be removed. A
                failed removal is never swallowed silently.
        """
        # Asked FIRST, before the target is even examined: if the primary
        # checkout has moved, nothing this method could prove about the target
        # is worth acting on. See the method for what this does and does not
        # cover -- it is a mitigation for the move-in attack, not a closure.
        self._refuse_if_the_primary_checkout_moved()

        target = self._require_allocated_worktree(path)
        record = self._read_allocation(target) or {}

        # Everything above the target that the removal will read the tree
        # THROUGH. Step 3 already checked this chain; the walk re-checks it on
        # every directory it opens, because a check that happened earlier is
        # not a check that holds now.
        guarded = self._reach_chain(target)[:-1]

        # CENTRAL START, after the proof and before the first unlink. Placing
        # it after the removal would produce a receipt only for trees that were
        # successfully deleted, which is exactly the population a receipt is
        # least needed for: a removal that dies halfway (WorktreeRemovalRace)
        # would leave a partially deleted tree with no record that anything was
        # ever authorised to touch it.
        registry, GuardDecision, begin_effect = _effect_boundary()
        begin_effect(
            "worktree.cleanup",
            registry["worktree.cleanup"].effects,
            (
                GuardDecision(
                    "containment.worktree",
                    True,
                    f"{target} passed _require_allocated_worktree (under this "
                    f"manager's root, not repo-adjacent, no reparse point in "
                    f"the reach chain lexically or resolved, a real directory, "
                    f"and holding this manager's creation-time allocation "
                    f"record); {len(guarded)} ancestor(s) are re-checked by the "
                    f"no-follow walk itself",
                ),
            ),
        )

        try:
            _remove_tree_no_follow(target, guarded_ancestors=guarded)
        except OSError as e:
            raise RuntimeError(
                f"failed to remove worktree directory {target}: {e}") from e
        # WorktreeRemovalRace is a RuntimeError, not an OSError: it passes
        # through undisguised so a caller can tell "nothing happened" from
        # "this was attacked halfway".

        # The directory is gone; deregister it. A prune failure raises
        # (RuntimeError from _run_git) rather than leaving a stale registration
        # unreported.
        self._run_git('worktree', 'prune')

        # The record is RETAINED, not discarded: it is now the only place that
        # remembers which branch this worktree left behind and what its tip was
        # at creation, which is what makes a later reap safe. The retained
        # record can never re-authorise a delete -- cleanup refuses a path that
        # does not exist, and this one no longer does.
        record["worktree_removed_ts"] = datetime.now(timezone.utc).isoformat()
        self._write_allocation(target, record)
        allocation = self._allocations.get(_key(target))
        if allocation is not None:
            # Tracked in memory as well as on disk: reap must not be steerable
            # into deleting the branch of a worktree that is still LIVE just
            # because a candidate wrote a `worktree_removed_ts` into its record.
            allocation["worktree_removed"] = True

    # -- branch reaping ----------------------------------------------------- #
    def reap_branches(self) -> List[dict]:
        """Delete candidate branches that provably hold no work. Explicit step.

        WHY THIS IS NOT PART OF ``cleanup_worktree``
        --------------------------------------------
        ``git worktree add -b`` writes a ref into the SHARED ``.git``, and
        nothing removed it, so an overnight loop leaves one ref per attempt
        forever. That leak is real and this method closes it -- but deleting the
        branch during cleanup would be wrong twice over:

        * In :mod:`daedalus.spine.attempt` the branch IS the effect key: the
          documented way to answer "did this attempt happen?" after a crash is
          ``git branch --list <effect_key>``. Cleanup runs in a ``finally:``
          that executes BEFORE the intent is resolved in the ledger, so deleting
          the branch there would open a fresh crash window in which an OPEN
          intent has no findable effect. That is a worse defect than the leak.
        * In the :mod:`daedalus.kairos.shadow_shell` flow ``commit_candidate``
          commits the candidate's work ONTO that branch, so there the branch is
          the deliverable, not scaffolding.

        So reaping is a separate act, run by whoever knows the attempt is fully
        resolved.

        THE TRUST MODEL, WHICH IS THE WHOLE OF THIS METHOD
        --------------------------------------------------
        An earlier version enumerated ``<worktree_root>/.daedalus-alloc/*.json``
        and believed what it read. That made the ATTACKER the author of the
        entire input set: candidate code is handed its own worktree path, and
        the alloc directory is one ``.parent`` away from it. Two forged records
        naming real branches at their current tips were enough to delete
        ``feature/six-months-of-work`` and ``release-2.0``, each with a printed
        reason that was false -- because both halves of "the tip matches what
        was recorded at allocation" were supplied by the same forged file.

        Candidate code runs as THIS user with THIS user's privileges, so there
        is no on-disk secret it cannot read and no on-disk file it cannot
        write. An authenticated record is therefore not available at this
        layer, and pretending otherwise would be the same defect with a MAC on
        it. What IS unavailable to the candidate is this process's memory, and
        what it cannot fake is git's own reachability graph. So a branch is
        deleted only when BOTH hold:

        1. THIS manager object allocated it, in THIS process
           (:attr:`_allocations`, written by :meth:`create_worktree`), its
           worktree has been through :meth:`cleanup_worktree`, and its tip is
           byte-identical to the sha this manager itself read from git at
           allocation time. Nothing on disk contributes to this.
        2. Some OTHER ref still contains that tip, so deleting the branch
           orphans no commit. This is git's answer, not ours, and a candidate
           can only "forge" it by genuinely making the branch redundant -- at
           which point deleting it destroys nothing, which is the property we
           actually wanted.

        The cost, stated plainly rather than hidden: a branch leaked by a
        CRASHED run is never reaped, because the process that could vouch for
        it is gone. Records left on disk are reported as ``unverifiable`` and
        acted on by nobody. A leaked ref is cheap; a deleted branch is not.

        Returns:
            One dict per allocation examined, with ``branch``, ``action``
            (``deleted`` / ``retained`` / ``absent`` / ``pending`` /
            ``unverifiable``) and ``reason``.

        Raises:
            RuntimeError: If any branch that was cleared for deletion could not
                be deleted. Every allocation is still examined first; the
                failures are reported together rather than aborting on the
                first one.
        """
        registry, GuardDecision, begin_effect = _effect_boundary()

        begin_effect(
            "worktree.reap",
            registry["worktree.reap"].effects,
            (
                GuardDecision(
                    "containment.worktree",
                    True,
                    "reap restricted to this manager's in-process allocation "
                    f"registry ({len(self._allocations)} record(s)); on-disk "
                    "records are reported unverifiable, never acted on",
                ),
            ),
        )
        report: List[dict] = []
        failures: List[str] = []

        for key in sorted(self._allocations):
            allocation = self._allocations[key]
            branch = str(allocation.get("branch") or "")
            worktree_path = Path(allocation["path"])
            entry = {"branch": branch, "path": str(worktree_path)}

            if not branch:
                report.append({**entry, "action": "retained",
                               "reason": "allocation carries no branch name"})
                continue
            if not allocation.get("worktree_removed"):
                report.append({**entry, "action": "pending",
                               "reason": "the worktree is still in use"})
                continue

            try:
                tip = self._run_git('rev-parse', '--verify', f'refs/heads/{branch}')
            except RuntimeError:
                # The ref is already gone; the allocation has nothing to guard.
                self._forget_allocation(worktree_path)
                report.append({**entry, "action": "absent",
                               "reason": "branch no longer exists"})
                continue

            expected = allocation.get("branch_tip_at_creation")
            if not expected or tip != expected:
                report.append({
                    **entry, "action": "retained",
                    "reason": (f"branch tip {tip} is not the allocation tip "
                               f"{expected}: it holds commits this manager did "
                               f"not create, and deleting it would destroy work"),
                })
                continue

            holders = self._refs_containing(tip, excluding=branch)
            if not holders:
                report.append({
                    **entry, "action": "retained",
                    "reason": (f"no other ref contains {tip}, so deleting "
                               f"{branch} would orphan it and the commits "
                               f"behind it"),
                })
                continue

            try:
                self._delete_unused_branch(branch, tip)
            except RuntimeError as e:
                failures.append(f"{branch}: {e}")
                report.append({**entry, "action": "retained",
                               "reason": f"git refused to delete it: {e}"})
                continue
            self._forget_allocation(worktree_path)
            report.append({
                **entry, "action": "deleted",
                "reason": (f"tip is unchanged since allocation and is still "
                           f"reachable from {holders[0]}; no work is lost"),
            })

        report.extend(self._report_unverifiable_records())

        if failures:
            raise RuntimeError(
                "failed to reap candidate branches: " + "; ".join(failures))
        return report

    def _forget_allocation(self, worktree_path: Path) -> None:
        self._allocations.pop(_key(worktree_path), None)
        self._discard_allocation(worktree_path)

    def _report_unverifiable_records(self) -> List[dict]:
        """Name the on-disk records nobody vouched for. Never acts on them.

        Reported rather than ignored so the leak is visible; reported WITHOUT
        any field parsed out of the file, because every byte in it is
        candidate-writable and echoing a forged branch name back at an operator
        as though it meant something is how the previous version printed false
        reasons.
        """
        alloc_dir = self._alloc_dir()
        if not alloc_dir.is_dir():
            return []
        live = {_key(self._alloc_file(Path(a["path"])))
                for a in self._allocations.values()}
        rows: List[dict] = []
        for record_file in sorted(alloc_dir.glob("*.json")):
            if _key(record_file) in live:
                continue
            rows.append({
                "branch": None,
                "path": None,
                "record": record_file.name,
                "action": "unverifiable",
                "reason": ("this manager did not allocate it in this process; "
                           "an allocation record on disk is candidate-writable "
                           "and is not evidence of anything"),
            })
        return rows

    def _refs_containing(self, sha: str, *, excluding: str) -> List[str]:
        """Refs OTHER than ``refs/heads/<excluding>`` whose history holds ``sha``.

        The one input to the reap decision that no candidate can forge. If this
        is non-empty, deleting the branch cannot orphan a commit -- every
        commit on it stays reachable from something else. If it is empty the
        branch is the only thing holding that history, and holding history is
        exactly what this method must never destroy.

        A FAILED CALL IS NOT AN ANSWER. git being missing, the repository being
        locked, ``.git`` being written by something else, a candidate that
        exhausted the handle table -- none of those is evidence that the tip is
        held elsewhere, so none of them may license a delete. Deleting the
        ``except`` below lets the ``RuntimeError`` escape ``reap_branches``
        instead of retaining; that mutation SURVIVED the suite until
        2026-07-28, and it is killed now by
        ``test_reap_retains_a_branch_when_git_cannot_say_who_contains_its_tip``.
        """
        try:
            out = self._run_git('for-each-ref', '--format=%(refname)',
                                '--contains', sha)
        except RuntimeError:
            # No answer is not a yes. Fail closed: the branch is retained.
            return []
        # Compared case-INSENSITIVELY although git refs are case-sensitive: the
        # only effect of a spurious match is that a ref is dropped from the
        # holder list, which retains the branch. Erring toward retention is the
        # correct direction for a method whose failure mode is deleting work.
        excluded = f"refs/heads/{excluding}".casefold()
        return [line.strip() for line in out.splitlines()
                if line.strip() and line.strip().casefold() != excluded]

    def _delete_unused_branch(self, branch: str, proven_tip: str) -> None:
        """Delete a branch already PROVEN to hold nothing but its base commit.

        ``-d`` is tried first so git's own merged-check applies. If git refuses
        anyway -- it compares against the current HEAD, which may have moved
        somewhere unrelated -- the sha proof (re-taken here, so the branch
        cannot have moved in between) is what authorises ``-D``. The force flag
        is never reached without that proof.
        """
        try:
            self._run_git('branch', '-d', branch)
            return
        except RuntimeError:
            pass
        tip = self._run_git('rev-parse', '--verify', f'refs/heads/{branch}')
        if tip != proven_tip:
            raise RuntimeError(
                f"refusing to force-delete {branch}: its tip moved from "
                f"{proven_tip} to {tip} while it was being reaped")
        self._run_git('branch', '-D', branch)

    def commit_candidate(self, path: str | Path, message: str, author: Optional[str] = None) -> None:
        """
        Commits all changes in the specified worktree.

        The path is proven to be an allocated worktree first: a swapped
        directory would otherwise turn ``git add -A`` + ``git commit`` into a
        commit of the developer's working tree.

        Args:
            path: The path to the worktree.
            message: The commit message.
            author: Optional author string (e.g., "Name <email>").
        """
        target = self._require_allocated_worktree(path)

        # CENTRAL START. `git add -A` is the reason this row exists at all: run
        # against a swapped directory it stages the developer's checkout, so
        # the allocation proof above and this receipt bracket the one call that
        # would turn a containment failure into a commit.
        registry, GuardDecision, begin_effect = _effect_boundary()
        begin_effect(
            "worktree.commit",
            registry["worktree.commit"].effects,
            (
                GuardDecision(
                    "containment.worktree",
                    True,
                    f"{target} passed _require_allocated_worktree, so `git add "
                    f"-A` and the commit below run inside a worktree this "
                    f"manager allocated for this repository and nowhere else",
                ),
            ),
        )

        # Stage all changes
        self._run_git('add', '-A', cwd=target)

        # Commit the changes
        commit_args = ['commit', '-m', message]
        if author:
            commit_args.extend(['--author', author])

        self._run_git(*commit_args, cwd=target)

    def has_changes(self, path: str | Path) -> bool:
        """Return whether the candidate worktree differs from its HEAD."""
        target = self._require_allocated_worktree(path)
        return bool(self._run_git("status", "--porcelain", cwd=target))

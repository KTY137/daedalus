"""WHICH TREE do these bytes land in? The primary-checkout fence.

Daedalus modifies itself. The owner's rule is that it must always do so **on a
clone of itself** -- a git worktree -- and that the primary checkout changes
only when a human promotes a candidate. Most of that was already true; this
module is the part that makes it *enforced* rather than *true by habit*.

WHAT THIS ANSWERS, AND WHAT IT DOES NOT
---------------------------------------
One question: **"does this path land inside the primary checkout?"** It is a
question about the FILESYSTEM -- numeric device/inode identity and resolved
path geometry -- and it takes no policy, no config, and no environment
variable. Nothing can declare it away.

It is emphatically NOT the question :func:`daedalus.sensitivity.path_write_blocked`
answers. That one asks *"may a weak local model write this KIND of file"* --
device drivers, secrets, high-blast-radius trees -- against repo-relative names
using substring policy that a project config can extend. Both are write fences;
they are orthogonal, they compose (a write must clear BOTH), and neither is
derivable from the other. Under ``path_write_blocked`` every repo-relative path
is "in the repo"; that fact is meaningless to it and load-bearing here.

WHY THIS IS ITS OWN MODULE, WRITTEN DOWN BECAUSE THE CHOICE WAS DELIBERATE
--------------------------------------------------------------------------
This tree's recurring defect is two predicates answering one question with
identical answers until they diverge -- five instances found in one day, the
worst of which nearly published an unauthenticated control plane because
``lane_for_host`` was answering both "may bytes leave this machine" and "may
this bind be unauthenticated". So before adding anything here, the existing
answers were enumerated. There were **two**, and they had already diverged:

* ``spine/attempt.py::_overlap_reason`` -- bidirectional (is / inside /
  contains), identity-based, and **fail-closed**: a path it cannot stat is
  refused.
* ``eval/correctness.py::_refuse_primary_checkout`` -- one-directional,
  identity-based, and **fail-OPEN**: ``except OSError: return p  # cannot
  compare identities; the lexical test stands``. A path it cannot stat is
  ALLOWED. Its own docstring says it "reuses rather than re-discovers"
  attempt.py's finding -- it reused the finding and not the code, and the
  copies now disagree on exactly the input that matters.

The choice made here, stated rather than implied:

**SPLIT the question, SINGLE-SOURCE the mechanism.** "May a mutating git
command run with this cwd?" and "do these bytes land in the checkout?" are
genuinely two questions -- they give different answers on real input (see
:func:`write_blocked_reason` on the contains direction) -- so collapsing them
into one predicate would be the same mistake in a new place. But the machinery
underneath is identical, so there is exactly one implementation of "is A the
same directory as B, or under it" (:func:`_inside`), it returns a VERDICT CODE
rather than prose, and both public predicates render that code. The
bidirectional question is literally the unidirectional one asked twice.

THE TWO PROPERTIES THAT MAKE IT A FENCE RATHER THAN A CHECK
------------------------------------------------------------
1. **It resolves before it compares.** ``..`` and symlinks are resolved, and
   identity is compared numerically (``st_dev``, ``st_ino``) rather than by
   string prefix. A fence a relative path can walk out of is not a fence, and
   ``Path.resolve()`` alone is not enough on Windows: it canonicalises neither
   DOS-device (``\\\\?\\C:\\x``) nor UNC admin-share (``\\\\localhost\\C$\\x``)
   spellings, and four such spellings of this checkout were MEASURED comparing
   unequal under ``resolve()`` and equal under ``st_dev``/``st_ino``.
2. **It refuses what it cannot resolve.** Empty input, a path that will not
   resolve, a checkout that cannot be stat'd, a target whose ground cannot be
   examined -- every one of those is a refusal, never a pass. If we cannot tell
   which tree the bytes land in, they do not get written.

THE PROBE, AND WHY THE WRITE FENCE NEEDS ONE
---------------------------------------------
``_overlap_reason`` guards a *cwd*, which by definition already exists, so it
stats the path itself. A *write target* usually does NOT exist yet -- that is
the point of writing it -- and stat'ing it would return "unexaminable" for
every new file, i.e. the fence would refuse everything, which is an outage and
not a boundary. So the write fence stats the nearest EXISTING ancestor
(:func:`nearest_existing`): the ground the bytes will land on. That ground is
what a symlink or an alias can lie about, and it is what identity examines.

This is why the probe is not a parameter of a single shared public predicate.
It is a property of the question being asked, so each public entry point pins
it and no caller can turn it into a knob.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "PRIMARY_ROOT",
    "PrimaryCheckoutWrite",
    "assert_write_allowed",
    "nearest_existing",
    "overlap_reason",
    "write_blocked_reason",
]

#: This repository's own checkout. The DEFAULT for every predicate here, on
#: purpose: a caller who forgets to say which tree they mean gets the fence,
#: not a bypass.
PRIMARY_ROOT = Path(__file__).resolve().parents[1]


class PrimaryCheckoutWrite(RuntimeError):
    """Something was about to write, or mutate, the primary checkout.

    Raised rather than returned as a state. Every place this fires is a bug in
    the caller, not a runtime condition a user can provoke, and a guard whose
    refusal can be degraded into a field somebody forgets to read is not a
    guard. ``spine/attempt.py`` re-exports this name, so it is one class and
    every existing ``except``/``pytest.raises`` keeps working.
    """


# --------------------------------------------------------------------------- #
# mechanism -- ONE implementation, returning a code rather than prose          #
# --------------------------------------------------------------------------- #
#: Verdict codes from :func:`_inside`. Prose lives in the public renderers so
#: that two callers asking different questions cannot drift into two copies of
#: the comparison itself.
_IS = "is"                      # inner IS outer
_IS_ALIASED = "is_aliased"      # inner IS outer under a different spelling
_INSIDE = "inside"              # inner is lexically under outer
_INSIDE_VIA = "inside_via"      # inner is under outer, reached through .via
_INNER_UNEXAMINABLE = "inner_unexaminable"
_OUTER_UNEXAMINABLE = "outer_unexaminable"


@dataclass(frozen=True)
class _Verdict:
    code: str
    via: Path | None = None


def _identity(path: Path) -> tuple | None:
    """``(volume, file-index)`` for ``path``, or ``None`` if it cannot be read.

    The comparison key for "are these two names the same directory?".
    ``os.stat`` follows reparse points on purpose: the question is which
    directory a name LANDS on, and a junction that lands on the checkout is
    exactly as dangerous as the checkout's own name.
    """
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_dev, st.st_ino)


def nearest_existing(path: Path) -> Path:
    """The nearest existing directory at or above ``path``.

    The ground a not-yet-created file will land on. Walks up rather than
    creating anything, so asking the question has no side effect; returns the
    volume root if nothing above the path exists at all (which then stats
    fine, or does not, and is refused).
    """
    p = Path(path)
    while not p.exists():
        if p.parent == p:
            break
        p = p.parent
    return p


def _resolve(path) -> Path | None:
    """Fully resolved absolute path, or ``None`` if it cannot be resolved.

    ``None`` is a REFUSAL upstream, never a pass. The empty string is rejected
    explicitly: ``Path("").resolve()`` is the current working directory, and
    silently rewriting "nowhere" into "wherever this process happens to be
    standing" is precisely the kind of helpfulness a fence must not offer.
    """
    if path is None:
        return None
    text = str(path)
    if not text.strip():
        return None
    try:
        return Path(text).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def _inside(inner: Path, outer: Path, *, probe: bool) -> _Verdict | None:
    """Is ``inner`` ``outer``, or under it? ``None`` means provably not.

    THE ONLY IMPLEMENTATION of that comparison in this codebase. Two means,
    both needed:

    * **Lexical**, on the resolved spellings. A fast path, NOT the guard, and
      labelled that way because a comment that reads like a guard gets trusted
      like one. It answers the common cases without touching the filesystem
      and yields a more specific message; the identity comparison below
      catches everything it catches.
    * **Identity**, which stops comparing names at all and therefore closes
      every alias at once -- including the ones nobody has thought of.

    ``probe`` selects WHAT gets stat'd: the path itself (a cwd, which exists)
    or its nearest existing ancestor (a write target, which usually does not).
    """
    if inner == outer:
        return _Verdict(_IS)
    if outer in inner.parents:
        return _Verdict(_INSIDE)

    outer_id = _identity(outer)
    if outer_id is None:
        return _Verdict(_OUTER_UNEXAMINABLE)
    ground = nearest_existing(inner) if probe else inner
    ground_id = _identity(ground)
    if ground_id is None:
        return _Verdict(_INNER_UNEXAMINABLE)
    if ground_id == outer_id:
        # When the ground IS the path, the two names are aliases of one
        # directory. When the ground is an ANCESTOR, the path is inside.
        return _Verdict(_IS if ground == inner else _INSIDE_VIA, via=ground)
    for ancestor in ground.parents:
        if _identity(ancestor) == outer_id:
            return _Verdict(_INSIDE_VIA, via=ancestor)
    return None


# --------------------------------------------------------------------------- #
# question 1 -- do these BYTES land in the primary checkout?                   #
# --------------------------------------------------------------------------- #
def write_blocked_reason(path, repo_root=None) -> str | None:
    """Why writing ``path`` would touch the primary checkout, or ``None``.

    ``None`` is the ONLY permissive answer; every failure mode returns a
    reason. A caller that wants an exception uses :func:`assert_write_allowed`.

    ONE DIRECTION, DELIBERATELY, AND THIS IS WHERE THIS PREDICATE AND
    :func:`overlap_reason` GENUINELY DIVERGE. ``overlap_reason`` also refuses a
    directory that CONTAINS the checkout, because ``git add -A`` run from an
    ancestor can stage the developer's tree. For a write that direction is
    wrong: the probe resolves a new file to its nearest existing ancestor, so
    ``<desktop>/some-new-dir/x.py`` grounds on ``<desktop>``, which contains
    this checkout -- refusing it would fence off the entire parent directory
    without protecting anything, because writing a file into a directory that
    contains the checkout does not write the checkout. Two questions, two
    answers, one shared comparison.

    A recursive DELETE aimed at an ancestor IS a hazard in the contains
    direction; that operation should ask :func:`overlap_reason`, which is why
    this function is named for writes and not for "touches".
    """
    root = _resolve(PRIMARY_ROOT if repo_root is None else repo_root)
    if root is None:
        return ("the primary checkout path could not be resolved, so it "
                "cannot be ruled out as the destination of this write")
    target = _resolve(path)
    if target is None:
        return (f"the write target {path!r} could not be resolved to a real "
                f"path, so it cannot be ruled out as being inside the "
                f"primary checkout")

    verdict = _inside(target, root, probe=True)
    if verdict is None:
        return None
    if verdict.code == _IS:
        return f"{target} IS the primary checkout {root}"
    if verdict.code == _INSIDE:
        return f"{target} is inside the primary checkout {root}"
    if verdict.code == _INSIDE_VIA:
        return (f"{target} is inside the primary checkout {root}, which it "
                f"reaches through {verdict.via}")
    if verdict.code == _OUTER_UNEXAMINABLE:
        return (f"the primary checkout {root} could not be examined, so a "
                f"write to {target} cannot be ruled out as landing in it")
    return (f"the ground under {target} could not be examined, so this write "
            f"cannot be ruled out as landing in the primary checkout {root}")


def assert_write_allowed(path, repo_root=None, what: str = "write target") -> Path:
    """Return the resolved ``path``, or raise :class:`PrimaryCheckoutWrite`.

    The form a call site should use, because it cannot be ignored: a guard
    whose return value a caller forgets to check is a comment.
    """
    reason = write_blocked_reason(path, repo_root)
    if reason is not None:
        raise PrimaryCheckoutWrite(
            f"refusing {what} {path}: {reason}. Daedalus writes only on a "
            f"clone of itself -- candidate changes belong in the isolated "
            f"worktree, and reaching the primary checkout is a promotion, "
            f"which is a human act.")
    resolved = _resolve(path)
    # Unreachable: a path that will not resolve already produced a reason.
    assert resolved is not None
    return resolved


# --------------------------------------------------------------------------- #
# question 2 -- may a MUTATING COMMAND run with this working directory?        #
# --------------------------------------------------------------------------- #
def overlap_reason(cwd, repo_root) -> str | None:
    """Why ``cwd`` touches the primary checkout, or ``None`` if it does not.

    BOTH DIRECTIONS, because asking only "is cwd inside the repo?" leaves a
    geometric hole: an ANCESTOR of the checkout is not inside it, so a
    worktree manager that handed back ``repo_root.parent`` would pass -- and
    whenever the checkout is nested inside an outer repo (a workspace, a
    vendored clone), a mutating verb run there stages the developer's tree.

    NO PROBE: a working directory that does not exist cannot be examined and
    is therefore refused, which is both the fail-closed answer and the correct
    one (no command can run there anyway).

    This is :func:`_inside` asked twice, not a second implementation of it.
    """
    cwd_path = Path(cwd)
    repo_path = Path(repo_root)

    forward = _inside(cwd_path, repo_path, probe=False)
    if forward is not None:
        if forward.code == _IS:
            return "it is the primary checkout"
        if forward.code == _IS_ALIASED:
            return "it is the primary checkout under a different spelling"
        if forward.code == _INSIDE:
            return "it is inside the primary checkout"
        if forward.code == _INSIDE_VIA:
            return (f"it is inside the primary checkout, which it reaches "
                    f"through {forward.via}")
        if forward.code == _OUTER_UNEXAMINABLE:
            return ("the primary checkout could not be examined, so overlap "
                    "with it cannot be ruled out")
        return ("this directory could not be examined, so overlap with the "
                "primary checkout cannot be ruled out")

    # The contains direction. The forward call already established that both
    # ends are examinable, so only the geometric codes can come back here.
    backward = _inside(repo_path, cwd_path, probe=False)
    if backward is None:
        return None
    if backward.code in (_IS, _IS_ALIASED, _INSIDE):
        return "it contains the primary checkout"
    if backward.code == _INSIDE_VIA:
        return (f"it contains the primary checkout, which is reached "
                f"through {backward.via}")
    return ("overlap with the primary checkout could not be ruled out "
            "because one end of the comparison could not be examined")

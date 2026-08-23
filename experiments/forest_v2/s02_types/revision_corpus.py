"""EXPERIMENT slice s02, continuation 4: read a package tree at a *named
revision* instead of at whatever the working tree happens to be today.

Why this exists
---------------
Continuations 1-3 measured the kernel package as it exists on disk and then
pinned the resulting counts exactly.  That pairing is unsound: the input moved
with every commit to the kernel, so the pin was a promise about the future of
a tree this slice does not control.  It came due on 2026-08-18, when two
unrelated kernel commits added one function and turned ``functions == 4203``
into a red check that stopped a port.  The guard was right and the pin was
wrong: *a reproducible number requires a fixed input*.

So the published numbers are now measured against
:data:`PINNED_REVISION` -- one commit, named in the write-up -- and the live
working tree is still measured, but its counts are **reported**, not asserted.

Frozen frame
------------
Same frame as the rest of the slice with one declared exception: this module
shells ``git``.  It has to; the history is the only place a past tree still
exists.  The exception is bounded three ways:

* every call goes through :func:`_run`, which refuses any verb outside
  :data:`_READ_ONLY_VERBS` (``rev-parse``, ``ls-tree``, ``cat-file``).  There
  is one door, so "read-only on the repository" is a checkable property rather
  than a promise repeated in four docstrings.  The design is lifted from
  sibling slice ``s09_eval/gitio.py``, which is the reference for reading a
  tree at a named revision without a repository handle.
* :func:`materialise` writes, on purpose, and only into a destination
  directory the caller supplies and which must not already exist.  It never
  writes into the repository it reads from.  It is the one exception, it is
  named, and it is deliberately not routed through the read-only gate --
  because it does not call git at all.
* no network, no imports of the analysed code, no writes outside the
  caller's destination.

The precise claim is therefore: **no function in this module can mutate the
repository it reads from**, and exactly one function writes at all.

What is anchored
----------------
A revision pins a repository; it does not pin what was *read*.  Two clones of
the same commit can still differ in line endings, and this repository does
rewrite them.  So the anchor is a pair: the commit, and the content digest
:func:`type_plane.corpus_pin` computes over the exact file set that was
parsed.  The digest is the load-bearing half -- it is checkable without any
history at all -- and the revision is what makes it re-derivable.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Sequence

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]

#: The revision the slice's published kernel numbers were measured against.
#: This is the tree state named in the write-up's "Measured baseline" heading.
#: It is an ancestor of both this lane and the trunk, so the anchor survives
#: the port.  Changing it means re-publishing every kernel number in the
#: write-up, which is the point: the constant and the prose move together or
#: not at all.
PINNED_REVISION = "d849c2a94d66ffb1bf892de924995645395bf2a6"

#: Content digest of the file set actually parsed at :data:`PINNED_REVISION`
#: -- ``type_plane.corpus_pin`` over ``daedalus/**/*.py``.  Line endings are
#: normalised before hashing, so this holds across checkouts that rewrite
#: CRLF.  This is the half of the anchor that needs no git history to check.
PINNED_KERNEL_DIGEST = "30ff3ffc0149eabdbdfd3b484754b7bd8ac5af2e9dcc4c96dc4dba7db9cde022"

#: Files parsed at the pin.  A digest that matched with a different file count
#: would mean the digest function lost information; asserting both is cheap.
PINNED_KERNEL_FILES = 285

_READ_ONLY_VERBS = frozenset({"rev-parse", "ls-tree", "cat-file"})


class RevisionUnavailable(RuntimeError):
    """The named revision cannot be read from this repository.

    Raised rather than swallowed: a missing anchor is a different failure from
    a moved tree, and the two must not be reported as the same thing.
    """


def _run(repo: Path, args: Sequence[str], stdin: bytes | None = None) -> bytes:
    """Run one read-only git plumbing command against ``repo``.

    The verb allowlist is the whole point.  ``stdin`` exists so
    ``cat-file --batch`` can be fed *through* the gate rather than around it.
    """
    if not args or args[0] not in _READ_ONLY_VERBS:
        raise RevisionUnavailable(f"refusing non-read-only git verb: {args[:1]}")
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            input=stdin,
            capture_output=True,
            check=False,
        )
    except OSError as exc:  # no git binary on this box
        raise RevisionUnavailable(f"git is not runnable here: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RevisionUnavailable(f"git {' '.join(args[:2])} failed: {detail}")
    return proc.stdout


def resolve(repo: Path, rev: str) -> str:
    """Resolve ``rev`` to a full commit sha, or raise :class:`RevisionUnavailable`."""
    sha = _run(repo, ["rev-parse", f"{rev}^{{commit}}"]).decode("utf-8", "replace").strip()
    if not sha:
        raise RevisionUnavailable(f"{rev!r} resolved to nothing")
    return sha


def list_python_blobs(repo: Path, rev: str, packages: Iterable[str]) -> Dict[str, str]:
    """Map ``relpath -> blob sha`` for every ``*.py`` under ``packages`` at ``rev``.

    Only ``.py`` files are listed because only ``.py`` files are what
    ``type_plane.iter_py_files`` would have walked.  Materialising more would
    make the frozen corpus a different corpus from the live one, which is the
    single comparison this module exists to support.
    """
    prefixes = tuple(f"{p.rstrip('/')}/" for p in packages)
    if not prefixes:
        return {}
    raw = _run(repo, ["ls-tree", "-r", "-z", rev, "--", *prefixes])
    out: Dict[str, str] = {}
    for entry in raw.decode("utf-8", "replace").split("\0"):
        if not entry.strip():
            continue
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) < 3 or parts[1] != "blob":
            continue
        if not path.endswith(".py"):
            continue
        out[path] = parts[2]
    return out


def read_blobs(repo: Path, shas: Iterable[str]) -> Dict[str, bytes]:
    """Fetch many blobs in one ``cat-file --batch`` process: ``sha -> bytes``."""
    wanted = list(dict.fromkeys(shas))
    if not wanted:
        return {}
    buf = _run(
        repo,
        ["cat-file", "--batch"],
        stdin=("\n".join(wanted) + "\n").encode("ascii"),
    )
    out: Dict[str, bytes] = {}
    pos, end = 0, len(buf)
    while pos < end:
        nl = buf.find(b"\n", pos)
        if nl < 0:
            break
        header = buf[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(header) < 3:  # "<sha> missing" -- nothing follows it
            continue
        sha, kind, size = header[0], header[1], int(header[2])
        payload = buf[pos : pos + size]
        pos += size + 1  # trailing newline after the payload
        if kind == "blob":
            out[sha] = payload
    return out


def materialise(repo: Path, rev: str, packages: Iterable[str], dest: Path) -> Dict[str, Any]:
    """Write the ``*.py`` tree of ``packages`` at ``rev`` into ``dest``.

    ``dest`` must not already exist.  This is the one writing function in the
    module and it never writes into ``repo``.
    """
    dest = Path(dest)
    if dest.exists():
        raise RevisionUnavailable(f"destination already exists: {dest}")
    sha = resolve(repo, rev)
    blobs = list_python_blobs(repo, sha, packages)
    if not blobs:
        raise RevisionUnavailable(
            f"no python files under {list(packages)} at {sha[:12]}"
        )
    payloads = read_blobs(repo, blobs.values())
    missing = [p for p, b in blobs.items() if b not in payloads]
    if missing:
        raise RevisionUnavailable(
            f"{len(missing)} blob(s) unreadable at {sha[:12]}, first {missing[0]!r}"
        )
    dest.mkdir(parents=True)
    for relpath, blob in sorted(blobs.items()):
        target = dest / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads[blob])
    return {"revision": sha, "files_written": len(blobs), "root": dest}


@contextmanager
def tree_at(repo: Path, rev: str, packages: Iterable[str]) -> Iterator[Dict[str, Any]]:
    """Yield a throwaway root holding ``packages`` exactly as they were at ``rev``.

    The directory is removed on exit whether or not the body raised.
    """
    holder = Path(tempfile.mkdtemp(prefix="s02-rev-"))
    dest = holder / "tree"
    try:
        yield materialise(repo, rev, packages, dest)
    finally:
        shutil.rmtree(holder, ignore_errors=True)


def measure_at_revision(
    packages: Iterable[str] = ("daedalus",),
    rev: str = PINNED_REVISION,
    repo: Path = REPO_ROOT,
) -> Dict[str, Any]:
    """Build the type plane over ``packages`` as they were at ``rev``.

    The returned report is byte-for-byte what ``type_plane`` would have
    produced had the working tree been at ``rev``, except that ``root`` names
    the revision rather than a temporary directory -- a temp path in a
    published report would make the report non-reproducible for the sake of a
    line nobody reads.
    """
    sys.path.insert(0, str(HERE))
    import type_plane as tp  # noqa: PLC0415 - deliberate: same trick as the probes

    with tree_at(repo, rev, packages) as materialised:
        report = tp.build_type_plane(materialised["root"], tuple(packages))
    report["root"] = f"git:{materialised['revision'][:12]}"
    report["revision"] = materialised["revision"]
    report["revision_is_pinned"] = True
    return report

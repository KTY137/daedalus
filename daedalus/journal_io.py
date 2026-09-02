"""Atomic appends for every append-only journal in this repository.

It lives beside :mod:`daedalus.atomic` rather than under ``memory/`` for that
module's own stated reason: the lowest-level writers must be able to use it
without an import cycle, and by now four subsystems do -- both memory journals,
``progress``, ``metrics`` and ``kairos.archive``. An append primitive is not a
memory concept.

Both journals in this package are described as append-only and authoritative,
and both were losing records.  MEASURED 2026-09-02 on this machine, six
processes appending concurrently:

    ``memory.append_event`` (buffered text)     118 of 120 records survived
    the vendor writer (buffered text)           174 of 200 at the real record
                                                size; 275 of 300 at 12 KB
    one ``os.write`` on an ``O_APPEND`` fd      276 of 300 at 12 KB
    the same write under an exclusive lock      300 of 300, every configuration

Reproduce with ``experiments/concurrency/probe_append_atomicity.py``.

THE LOSS IS SILENT, which is why it survived this long.  Overwritten bytes
leave no malformed line, so every reader -- the projection worker's
``skipped_malformed`` counter, the health probe's ``unparsable lines`` -- reports
zero while a tenth of the journal is gone.  A journal that loses records without
saying so is worse than one that corrupts them.

``O_APPEND`` alone is not enough on Windows: the C runtime implements it as
"seek to end, then write", which is two operations and therefore racy.

THE LOCK IS NOT IMPLEMENTED HERE
--------------------------------

:class:`daedalus.atomic.ExclusiveFileLock` already existed and already solved
exactly this: one fixed persistent file, never replaced or removed, kernel-held
ownership released on close or crash, ``msvcrt`` byte-range locking on Windows
and ``flock`` on POSIX, bounded timeout.

The first version of this module shipped its own copy of that.  That is the
defect ``atomic``'s own docstring describes -- *"a correct implementation
existed, in one place, and the other call sites were copies that never received
it"* -- committed while hunting the same class of defect one directory over.
It also independently rediscovered, the expensive way, the split-inode race
``ExclusiveFileLock`` documents: a create/unlink spin lock deadlocks writers on
Windows, because unlinking a file another process holds open raises
``PermissionError``.

So this module contributes exactly one thing the atomic layer does not have:
appending, as opposed to publishing.  Everything about *how* the lock works
belongs to ``atomic`` and is imported from it.
"""

from __future__ import annotations

from pathlib import Path

from .atomic import ExclusiveFileLock, FileLockUnavailable

__all__ = ["FileLockUnavailable", "ShortJournalWrite", "append_lines",
           "LOCK_TIMEOUT_SECONDS"]

#: How long a writer waits before giving up.  Longer than ``atomic``'s 5s
#: default because the contended case here is many sessions journalling at
#: once, and a dropped record is worse than a slow one -- but still bounded,
#: because a wait this long means something is wedged rather than busy.
LOCK_TIMEOUT_SECONDS = 10.0

#: Polled tighter than ``atomic``'s 50 ms default: the critical section is a
#: single ``os.write``, so a 50 ms backoff would serialise concurrent writers
#: at 20 appends per second for no reason.
LOCK_POLL_SECONDS = 0.002


class ShortJournalWrite(RuntimeError):
    """The append landed partially.  The record is torn and unrepairable."""


def append_lines(journal: Path, lines: list[str]) -> int:
    """Append complete lines atomically with respect to other appenders.

    Serialises FIRST, so the critical section holds no computation; writes ONCE
    with :func:`os.write`, so the buffering layer cannot split a record across
    two operating-system writes; and holds the lock across the open, so two
    writers cannot resolve the same end-of-file offset.  Dropping any one of the
    three reproduces the measured loss.

    Returns the number of bytes written.  Raises
    :class:`~daedalus.atomic.FileLockUnavailable` or :class:`ShortJournalWrite`
    rather than reporting a success it did not have; a caller that would rather
    continue may catch them, but it has to say so.
    """

    import os

    if not lines:
        return 0
    blob = "".join(
        line if line.endswith("\n") else line + "\n" for line in lines
    ).encode("utf-8")
    journal.parent.mkdir(parents=True, exist_ok=True)
    lock_path = journal.with_name(journal.name + ".lock")
    with ExclusiveFileLock(lock_path, timeout_s=LOCK_TIMEOUT_SECONDS,
                           poll_s=LOCK_POLL_SECONDS,
                           label=f"append lock for {journal.name}"):
        fd = os.open(
            str(journal),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0),
            0o644,
        )
        try:
            os.lseek(fd, 0, os.SEEK_END)
            written = os.write(fd, blob)
        finally:
            os.close(fd)
    if written != len(blob):
        # Not retried: appending the remainder would place it after whatever
        # another writer added in between, producing a record that reads as
        # two.  Reported instead, so the caller learns the journal has a torn
        # tail here rather than discovering it at projection time.
        raise ShortJournalWrite(f"wrote {written} of {len(blob)} bytes to {journal}")
    return written

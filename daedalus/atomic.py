"""Atomic publish, with the Windows retry that makes the claim true.

Every module in this repo that publishes a small file does the same three things:
write a sibling temp file, ``os.replace`` it over the target, and document the
result as atomic. On POSIX that is correct. On win32 it is correct *unless
somebody is reading the target*, and this repo is full of pollers that read
exactly these files.

MEASURED, and documented at :meth:`daedalus.spine.killswitch.KillSwitch._atomic_write`
before this module existed: on win32 a reader holds the file open WITHOUT
``FILE_SHARE_DELETE`` -- CPython's ``open()`` offers no way to ask for it -- so
``MoveFileEx`` over it fails with ERROR_ACCESS_DENIED. With a 50 ms poll that
raced often enough to break the operator's own stop command, i.e. the kill switch
could fail to engage *precisely because something was watching it*.

``killswitch`` and ``budget._store`` each carried a retry loop. Four other
publishers did not, and all four documented themselves as atomic anyway:

    arch_memory.save            (names the exact concurrent-reader scenario
                                 that breaks it, then does the bare replace)
    shift._write_atomic
    file_bridge._write_json_atomic
    loop.LoopLedger.save

That is the same defect shape as the write-lane guards in
:mod:`daedalus.lanes`: a correct implementation existed, in one place, and the
other call sites were copies that never received it. So this module is the one
implementation, and a publisher imports it instead of rolling its own.

Deliberately dependency-free (stdlib only, no intra-package imports) so the
lowest-level publishers can use it without an import cycle.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "ExclusiveFileLock",
    "FileLockUnavailable",
    "REPLACE_RETRY_S",
    "publish_bytes_once",
    "replace_with_retry",
    "write_text_atomic",
    "write_bytes_atomic",
]

#: How long to keep retrying a replace that a concurrent reader is blocking.
#: The contended window is one ``read_bytes`` of a file under a few KiB, so this
#: is generous by two orders of magnitude; it is a bound, not a budget. The
#: caller decides what an exhausted retry means -- this module raises.
REPLACE_RETRY_S = 1.0

#: Gap between attempts. Short enough that the common case (reader finishes
#: immediately) costs one sleep, long enough not to spin a core.
_RETRY_SLEEP_S = 0.02


class FileLockUnavailable(RuntimeError):
    """An exclusive OS-held file lock could not be obtained in time."""


class ExclusiveFileLock:
    """Bounded cross-process lock backed by one fixed, persistent file.

    The file itself is not an ownership marker and is never replaced or
    removed. Ownership belongs to the kernel and is released when the handle
    closes or the process exits, including after a crash. This makes a stale
    filename harmless and avoids the split-inode race of lock-file deletion.

    This primitive deliberately stays in the dependency-free atomic layer so
    publishers can serialize a read/decide/publish transaction without
    inventing another locking scheme. It uses ``msvcrt`` byte-range locking on
    Windows and ``flock`` on POSIX.
    """

    def __init__(self, path: str | os.PathLike[str], *, timeout_s: float = 5.0,
                 poll_s: float = 0.05, label: str = "file lock") -> None:
        self.path = Path(path)
        self.timeout_s = max(0.0, float(timeout_s))
        self.poll_s = max(0.001, float(poll_s))
        self.label = str(label)
        self._fh: Any = None

    def __enter__(self) -> "ExclusiveFileLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a+b")
        except OSError as exc:
            self._fh = None
            raise FileLockUnavailable(
                f"cannot open {self.label} '{self.path}': {exc}"
            ) from exc

        deadline = time.monotonic() + self.timeout_s
        last_error: OSError | None = None
        while True:
            try:
                self._acquire()
                return self
            except OSError as exc:
                last_error = exc
            if time.monotonic() >= deadline:
                break
            time.sleep(min(self.poll_s, max(0.0, deadline - time.monotonic())))

        self._close()
        raise FileLockUnavailable(
            f"could not acquire {self.label} '{self.path}' within "
            f"{self.timeout_s:g}s ({last_error})"
        )

    def _acquire(self) -> None:
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _close(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None

    def __exit__(self, *exc: Any) -> bool:
        if self._fh is None:
            return False
        try:
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            # Closing the descriptor below is the kernel-level release path.
            pass
        self._close()
        return False


def replace_with_retry(tmp: str | os.PathLike[str], target: str | os.PathLike[str],
                       retry_s: float = REPLACE_RETRY_S) -> None:
    """``os.replace(tmp, target)``, retrying a Windows sharing conflict.

    On the final failure the temp file is removed before the error propagates,
    so a failed publish does not litter the directory with ``*.tmp`` siblings
    that a later glob might mistake for real artefacts.

    Raises the underlying :class:`OSError` when the deadline passes. That is the
    intended contract: a publisher that cannot publish must not report success,
    and every caller here treats the exception as the failure it is.
    """
    deadline = time.monotonic() + max(0.0, retry_s)
    while True:
        try:
            os.replace(tmp, target)
            return
        except OSError:
            if time.monotonic() >= deadline:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(_RETRY_SLEEP_S)


def _tmp_sibling(target: Path) -> Path:
    """A temp path beside ``target``.

    BESIDE, not in the system temp dir: ``os.replace`` is only atomic within a
    filesystem, and a cross-device replace degrades to copy-then-delete, which
    is exactly the torn-read this function exists to prevent.

    The random suffix is load-bearing under concurrency -- a fixed ``.tmp`` name
    means two publishers racing on one target write the same scratch file and one
    of them publishes the other's half-written bytes.
    """
    return target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.tmp")


def write_text_atomic(path: str | os.PathLike[str], text: str, *,
                      encoding: str = "utf-8",
                      retry_s: float = REPLACE_RETRY_S,
                      newline: str | None = None) -> None:
    """Publish ``text`` at ``path``: a reader sees the old bytes or the new ones.

    Creates parent directories. ``newline=""`` suppresses translation, which a
    caller wants when the bytes must survive verbatim.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_sibling(target)
    # Path.write_text, NOT open()+write. Two of this repo's atomicity tests
    # (test_bridge_restart, test_bridge_signals) prove "no half-written file is
    # ever glob-visible" by monkeypatching Path.write_text and inspecting the
    # directory at the instant the bytes land. That instrumentation is
    # deliberate, and a helper that writes by another route makes those tests
    # silently vacuous rather than failing -- which is strictly worse than
    # either outcome.
    tmp.write_text(text, encoding=encoding, newline=newline)
    replace_with_retry(tmp, target, retry_s)


def write_bytes_atomic(path: str | os.PathLike[str], data: bytes, *,
                       retry_s: float = REPLACE_RETRY_S) -> None:
    """:func:`write_text_atomic` for bytes, when the caller owns the encoding."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_sibling(target)
    tmp.write_bytes(data)
    replace_with_retry(tmp, target, retry_s)


def publish_bytes_once(path: str | os.PathLike[str], data: bytes) -> bool:
    """Atomically publish immutable ``data`` without replacing ``path``.

    Returns ``True`` when this call created ``path`` and ``False`` when another
    writer had already created it.  The caller must verify an existing target;
    this helper deliberately does not decide whether those bytes are equivalent
    or corrupt.

    A normal ``os.replace`` is atomic but has the wrong contract for a
    content-addressed store: it can overwrite an object whose identity was
    already published.  Here the complete sibling temp file is hard-linked into
    place.  Link creation is one filesystem operation and refuses an existing
    destination, so readers can observe either no object or the complete
    object, never a partially written one and never a replacement.

    Hard-link support is therefore a requirement, not an optimisation.  If the
    filesystem refuses it, the error propagates and the caller fails closed
    rather than degrading to a visible in-place write.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_sibling(target)
    try:
        # Exclusive creation keeps an injected/reused temp name from becoming
        # an overwrite path.  Flush+fsync happens before publication; this
        # provides complete bytes to the link even if buffered I/O is in use.
        with tmp.open("xb") as fh:
            written = fh.write(data)
            if written != len(data):
                raise OSError(
                    f"short write for {tmp}: {written} of {len(data)} bytes")
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, target)
        except FileExistsError:
            return False
        return True
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass

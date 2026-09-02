"""Which append mechanism survives concurrent writers on THIS machine?

Not a question to settle from documentation. Windows append semantics through
the C runtime, Python's buffering layer and the filesystem interact in ways that
are easier to measure than to reason about -- and this repository already holds
one journal that lost 13% of its records under four concurrent writers.

Each variant is exercised by real processes appending to one file. The output is
records-found against records-expected; anything below expected is silent data
loss, which is worse than corruption because nothing counts it.

    .venv/Scripts/python.exe experiments/concurrency/probe_append_atomicity.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

WRITERS = 6
TURNS = 25
RECORD_PAD = 400
EXPECTED = WRITERS * TURNS * 2

WRITER_SOURCE = r'''
import json, os, sys

journal, worker, turns, variant = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]

def payload(i):
    return [json.dumps({"record_id": f"{worker}-{i}-{d}", "pad": "x" * PAD})
            for d in ("in", "out")]

PAD = int(sys.argv[5])

for i in range(turns):
    records = payload(i)
    if variant == "A":
        # Today's writer: buffered text mode, one write() per record.
        with open(journal, "a", encoding="utf-8") as handle:
            for record in records:
                handle.write(record + "\n")
    elif variant == "B":
        # One syscall, O_APPEND, no buffering layer.
        blob = "".join(record + "\n" for record in records).encode("utf-8")
        fd = os.open(journal,
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0),
                     0o644)
        try:
            os.write(fd, blob)
        finally:
            os.close(fd)
    elif variant == "C":
        # A create/unlink spin lock. Included because it is the obvious first
        # idea and it DOES NOT WORK on Windows: unlinking a file another
        # process still holds open raises PermissionError, so the lock leaks
        # and writers die instead of waiting.
        blob = "".join(record + "\n" for record in records).encode("utf-8")
        lock = journal + ".spinlock"
        while True:
            try:
                lfd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                pass
        try:
            fd = os.open(journal,
                         os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0),
                         0o644)
            try:
                os.write(fd, blob)
            finally:
                os.close(fd)
        finally:
            os.close(lfd)
            os.unlink(lock)
    elif variant == "D":
        # A PERSISTENT lock file plus a real byte-range lock. The lock file is
        # never unlinked, which is what removes C's race, and the lock is the
        # platform's own (msvcrt.locking on Windows, fcntl.flock elsewhere)
        # rather than an existence test.
        import time
        blob = "".join(record + "\n" for record in records).encode("utf-8")
        lfd = os.open(journal + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
        try:
            try:
                import msvcrt
                for attempt in range(2000):
                    try:
                        os.lseek(lfd, 0, os.SEEK_SET)
                        msvcrt.locking(lfd, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.001)
                else:
                    raise RuntimeError("could not acquire the journal lock")
                release = lambda: (os.lseek(lfd, 0, os.SEEK_SET),
                                   msvcrt.locking(lfd, msvcrt.LK_UNLCK, 1))
            except ImportError:
                import fcntl
                fcntl.flock(lfd, fcntl.LOCK_EX)
                release = lambda: fcntl.flock(lfd, fcntl.LOCK_UN)
            try:
                fd = os.open(journal,
                             os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0),
                             0o644)
                try:
                    os.lseek(fd, 0, os.SEEK_END)
                    os.write(fd, blob)
                finally:
                    os.close(fd)
            finally:
                release()
        finally:
            os.close(lfd)
'''


def run(variant: str, pad: int) -> tuple[int, int, int]:
    directory = pathlib.Path(tempfile.mkdtemp(prefix=f"append-{variant}-"))
    journal = directory / "journal.jsonl"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", WRITER_SOURCE, str(journal), f"w{n}",
             str(TURNS), variant, str(pad)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for n in range(WRITERS)
    ]
    failures = 0
    for proc in procs:
        _out, err = proc.communicate(timeout=300)
        if proc.returncode:
            failures += 1
            print(f"    writer error: {err.strip().splitlines()[-1][:120]}")
    if not journal.exists():
        return 0, 0, failures
    found = broken = 0
    for line in journal.read_bytes().split(b"\n"):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            broken += 1
            continue
        if isinstance(record, dict) and "record_id" in record:
            found += 1
        else:
            broken += 1
    return found, broken, failures


def main() -> int:
    names = {
        "A": "buffered text, write() per record (today's writer)",
        "B": "one os.write on an O_APPEND fd",
        "C": "create/unlink spin lock (the obvious idea; broken on Windows)",
        "D": "persistent lock file + platform byte-range lock",
    }
    for pad in (RECORD_PAD, 12_000):
        print(f"\n=== record padding {pad} bytes, {WRITERS} writers x {TURNS} "
              f"turns, expected {EXPECTED} records ===")
        for variant, label in names.items():
            found, broken, failures = run(variant, pad)
            verdict = "OK" if (found == EXPECTED and not broken) else "LOSS"
            print(f"  [{verdict:4s}] {variant}  {label:48s} "
                  f"found={found:3d} lost={EXPECTED - found:3d} "
                  f"corrupt={broken} writer_errors={failures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Claims about `shift-arch-memory.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Windows atomic write failure: os.replace raises if target exists on Windows, causing data loss
2. [risk] Lock steal race: two processes can both think they hold the lock
3. [risk] Dead code in remaining() second parse branch never executes
4. [risk] No test coverage for any concurrency scenario
5. [risk] arch_memory.save() not atomic on Windows
6. [todo] Add four tests: 1) concurrent note() with two processes, 2) atomic write under concurrent read, 3) lock timeout and steal, 4) Windows atomic write
7. [todo] Fix _ShiftLock.__enter__ to use os.open with O_CREAT|O_EXCL and handle steal via lock file mtime without TOCTOU
8. [todo] Fix _write_atomic to use tempfile + shutil.move for cross-platform atomicity
9. [todo] Add Windows CI or at least document known non-atomicity
10. [todo] Remove dead code in Shift.remaining() second parse
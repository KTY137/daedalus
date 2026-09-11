---
name: accelerator-probe-residual
description: The deep accelerator probe's temp-file transport has a measured, accepted disk residual that its own docstring understates — numbers and the cheap fix, so it is not re-discovered
metadata:
  type: project
---

`daedalus/foundation/accelerators.py::_run_deep_probe` bounds the child's wall
clock and the parent's memory, but nothing bounds what the child writes to its
temp file **while it runs**. Measured 2026-09-11 on PR #370 (`e535ea61`):
**1.94 GiB written in 1.17 s** under a 1.0 s bound; the parent read back exactly
`_DEEP_PROBE_OUTPUT_LIMIT` (1 MB). At the shipped 30 s bound that extrapolates to
roughly 50 GiB, against 27.5 GiB free on this host's C: (where `%TEMP%` lives).
A grandchild that outlives the kill keeps growing the file (183 -> 570 MiB over
6 s after the call returned), and the file is delete-pending, so **no process,
not even an admin, can open or truncate it** — only killing the grandchild
reclaims the space. `ThreadingHTTPServer` plus a non-atomic `lru_cache` means
concurrent first-callers of `/api/accelerators/status?deep=1` each spawn one.

**Why:** the docstring only says a surviving grandchild "costs disk", which reads
as bounded and reclaimable. It is neither. The residual was reviewed, measured
and accepted at merge because the pre-fix behaviour was strictly worse (8 GiB
pulled into the parent's RAM plus a 600 s hang of a read endpoint), and because
flooding requires an operator-configured hostile or broken
`DAEDALUS_ACCELERATOR_PYTHON`. Note the same module's env allowlist explicitly
treats that interpreter as untrusted — so the inconsistency is real, just
low-likelihood.

**How to apply:** do not re-litigate this as a new finding. If the probe is
touched again, the cheap closure is to poll `os.fstat(out.fileno()).st_size`
inside the wait loop and kill on a ceiling — that is the whole fix, no Job
object needed. Related: [[crlf-text-pin-trap]] (the touched files are *not*
`-text` pinned, checked with `git ls-files --eol`).

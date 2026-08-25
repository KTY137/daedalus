# Amendment proposal 004 — byte-exact resources must not be EOL-normalized

Status: **MOOT — never approved, subject retired.** Proposed 2026-08-17 by
Athena (coordinator) against the then-integration branch
`origin/integration/g0-consolidated-20260807`. `tools/iron_plan_guard.py (removed 2026-08-22)`,
the protected artifact this amendment would have added a `.gitattributes`
rule under, was deleted in the 2026-08-22 guard retirement before the
amendment protocol was invoked.

Severity claimed: blocks Gate 0 exit on Windows. Affected invariants: 5
(sealed promotion), 8 (bounded effects).

## What it found

On Windows with `core.autocrlf=true`, Git's checkout rewrote line endings in
nine files across three sites that pinned their content against an exact Git
blob SHA (`daedalus/kairos/_gated_writes_legacy.py.src` and eight files under
`tests/gates/` plus one schema). The rewrite broke the pinned-blob
verification, so `daedalus.kairos.gated_writes` raised at import time and 7
test modules failed to collect. Root cause: Git's clean/smudge filter
reverses CRLF before `git hash-object`, but `Path.read_bytes()` in Python does
not — so the stored blob and the on-disk bytes diverged only on
`autocrlf`-normalizing Windows checkouts. Verified reproducible and fixable in
an isolated LF worktree (collection errors 7 → 1 → 0, the last unrelated —
see below).

Proposed fix: nine `text eol=lf` rules in `.gitattributes`, one per pinned
path, rejected the alternative of normalizing bytes before hashing (would
verify one byte stream while executing another — a regression against
invariant 5) and rejected `core.autocrlf=false` locally (per-machine,
unversioned).

Two independent defects were found alongside and marked out of scope:
`tests/gates/test_gate0_release_cli.py` importing a symbol from the wrong
module (one-line fix, not protected, not blocking); and
`git_command_is_mutating` misclassifying `git merge-base`/`git branch
--merged` as mutating.

## Why it is moot rather than accepted or rejected

The retained-source strangler (`_gated_writes_legacy.py.src`) and the guard
that would have enforced this `.gitattributes` rule are both gone; current
`daedalus/kairos/gated_writes.py` and `daedalus/kernel/promotion.py` no
longer exec a pinned blob this way [MEASURED 2026-08-25: no
`AUTO_PROMOTE_LEVELS` or blob-pin symbols in the current module]. Whether the
present tree has any live CRLF/blob-pin exposure is not established by this
record and would need fresh measurement, not a replay of this one.

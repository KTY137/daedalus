# Amendment proposal 002 — guard repairability

Status: **MOOT — never approved, subject retired.** Proposed 2026-08-1x by the
repository owner's session against `tools/iron_plan_guard.py` and
`tests/test_iron_plan_guard.py`. Both files were deleted in the 2026-08-22
guard retirement (master plan revision 7); the amendment protocol was never
invoked to approve or reject this proposal, and there is nothing left to apply
it to. [MEASURED 2026-08-25: neither file exists at HEAD.]

Base plan revision: 1. Proposed result revision: 2 (superseded by the
revision-7 retirement before this proposal was acted on).

## What it proposed

Three measured defects in the guard, scoped as mechanism-only (no invariant,
prior, gate, or plan sentence would have changed):

1. The CI-history adoption test read its baseline from live `HEAD`, so it
   compared the adopted plan with itself and could never fail. Fix: a pinned
   revision-0 plan fixture, with the digest cross-checked against the ledger
   record.
2. `verify()` could print a repair command (`git add --chmod=+x
   .githooks/...`) that the guard itself then denied as a protected-path
   mutation, leaving no in-harness exit but a constitutional amendment. Fix: a
   small closed table of self-repairing commands, exempted only when every
   live error matches one exactly.
3. Every parent directory of a protected artifact (`docs/`, `tests/`,
   `tools/`, `daedalus/`, `templates/`) was locked as if it held nothing but
   policy files, so `git add docs/` and commit messages merely containing the
   word "docs" were denied while `git add -A` passed untouched. Fix: strip
   `-m`/`-F` message arguments before path extraction, and restrict the
   directory rule to directories that are policy-only in fact
   (`.agentenv`, `.githooks`, `.github/workflows`, etc.).

Also recorded, not proposed: the guard checked a commit's `Iron-Plan:` trailer
only for presence, never for correctness, and its token set diverged from the
plan's own (`adoption` was accepted but not listed in §14).

## Why it is moot rather than rejected

The guard ceremony was retired by owner decision before this proposal reached
approval. None of the three defects can be fixed or matter now — the
mechanism they describe no longer runs. The technical analysis remains
correct as history of why the guard was hard to live with, which is part of
why it was retired.

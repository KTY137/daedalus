# What 910e76dc actually contains, and who wrote it

`910e76dc` is a merge commit I (the coordinating session) made for
`lane/lease-authority-subject-split`. Resolving the conflict in
`tests/kernel/test_effect_lease_issuer_rule.py` I ran `git add <that one file>`
and then `git commit --no-edit` — and a merge commit takes THE WHOLE INDEX, not
a pathspec. The shared index already held work staged by two other live
sessions, so my merge swept in four files nobody asked me to land:

| file | author | state when swept |
| --- | --- | --- |
| `docs/inventory/2026-08-24/CANDIDATE_WRITE_FENCE.md` | the attempt-lease agent | finished, 338 lines, byte-intact |
| `daedalus/kernel/promotion_execution.py` | a third live session | complete — see below |
| `tests/kernel/test_live_promotion_seam.py` | same | complete |
| `tests/kernel/test_persisted_promotion_authorization.py` | same | complete |

Measured after the fact, at this HEAD: those three promotion files run
**25 passed, 7 xfailed** — the same suites the lease lane had measured as
19–20 failures at `11dc0195`. So the work I swept in was finished and it
repaired a red trunk. That is luck, not diligence: I did not read it before it
landed under my commit message, and had it been half-written I would have
shipped a half-fix signed as a merge.

The attempt-lease agent staged its document by explicit pathspec precisely so
it could not land anyone else's work. It did everything right; the sweep was
mine. Its four contributions are `31f69dc2`, `61f1ece3`, `272d06e8`, and the
fence document inside this merge.

**The rule this cost us:** in a tree shared with live sessions, `git add`
followed by a separate `git commit` is not safe even with a pathspec, because a
merge commit ignores the pathspec and a peer can stage between the two. Stage
and commit atomically, and run `git diff --cached --stat` immediately before
committing a merge. My own memory already carried this as the
"shared index commit trap"; carrying a rule is not the same as applying it.

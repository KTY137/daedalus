# History rewrite of 2026-09-03: what was purged, and what that did not buy

Status: STATUS (a revision-bound measurement, not timeless truth)
Authority: explicit owner decision, taken twice — once to purge, once again
after the premise behind the first decision was corrected.
Executed by: session `daedalus-80`, with measurement and refutation from
`daedalus-22`, `daedalus-29`, `daedalus-b2`, `daedalus-fc`, `daedalus-f9`.

## Why a reader is here

Because a commit SHA in some document resolves to nothing. Every SHA in this
repository from 2026-07-29 onward changed. `sha-map.tsv` beside this file maps
old to new, one pair per line, tab-separated, 1088 entries. Translate; do not
re-derive from commit subjects — same-looking identity is what caused the one
real data-loss incident described below.

## What came out

| Path | Treatment | Why |
| --- | --- | --- |
| `GUTEN_MORGEN_KAYA.md` | removed from every commit | A personal morning note addressed to the owner by name, containing a private remark about their health and a crisis phone number. The owner chose deletion over redaction. |
| `.semgrep/guardian.yml` + `.lock`, `apps/web/.semgrep/guardian.yml` + `.lock` | removed from every commit | Tool session state that had no business being tracked. See the correction below: what was committed was NOT a credential. |
| `runs/council/room.md` | one blob substituted, file kept | A council transcript cited elsewhere with line numbers. One private sentence was replaced by `[private Anmerkung entfernt]`; the surrounding question and all 370 turns survive. |

The transcript case is the reason this was a blob substitution rather than a
text rewrite: both the dirty blob (`0a89b977`) and its clean counterpart
(`81c83c7e`) already existed in the object database, so the filter swapped a
known object for a known object and could not match anything else by accident.

## Measured outcome

- 4147 commits processed, **1088 rewritten**, the rest keep their original SHA
  because their trees never held the purged paths.
- After dropping `refs/original`, expiring all reflogs and `gc --prune=now`:
  **34364 objects scanned via `cat-file --batch-all-objects` — every object in
  the database, not only the reachable ones — and 0 contain any of the three
  private strings.** A scan of the reachable set only would not have been
  evidence.
- On origin, across all **172 refs** (17 branches, 155 tags): 0 purged paths,
  0 private strings.
- 17 branches and 155 tags force-pushed **atomically**, so an interrupted run
  would have left origin untouched rather than half-purged.

## What this did NOT achieve

Three things, stated because a force-push plus a confident report is exactly
the shape that makes a partial purge look finished.

1. **GitHub still holds the old objects.** A force-push makes them unreachable,
   not absent. They stay fetchable by exact SHA and are exposed through the API
   even when the web UI hides them, until GitHub Support runs a server-side gc.
   Until that request is made and honoured, "purged from origin" is false.
2. **The exposure window is not undone.** The repository was measured public at
   11:50 and private later the same day. Whatever was fetched in between was
   fetched. This rewrite buys "not readable from here going forward", never
   "never disclosed".
3. **Two backup mirrors still contain everything**, deliberately, as the safety
   net for this operation: `daedalus-backup-20260903.git` (local, pre-rewrite)
   and `daedalus-origin-backup-20260903.git` (origin, pre-push). They must be
   deleted once the rewrite is trusted, or the purge is theatre.

## Two defects of this operation, recorded because they cost real work

**A false credential alarm.** Mid-operation this session reported that a live
Semgrep OAuth access token and refresh token had been committed and pushed to a
then-public repository, and asked the owner to rotate. That was wrong. The
error: the file was read from the WORKING COPY — which does hold a live JWT —
and the two commits returned by `git log --all -- <path>` were assumed to
contain what had just been read. The committed blobs are 140 bytes each and
hold `serial`, a pseudonymous `anonymous_user_id`, `auth_method` and `expiry`;
no token ever reached a commit. A peer session refused the claim and measured
`git show <sha>:<path>` blob by blob. A second peer had already "independently
confirmed" the alarm by verifying tracking, ignore status, token length and
push status — all true, none of them the actual claim.

> The rule both of today's errors vanish under: `Read`/`cat` answers about the
> disk, `git show <sha>:<path>` answers about history, and every claim about
> what is IN the repository needs the second.

**Two branches lost commits.** The push script resolved each origin branch name
by preferring a local branch of that name over the remote-tracking ref. Where a
lane had pushed without updating its local branch — the normal state for anyone
working in a worktree — the older local value won and was force-pushed over
newer work. `packet/g1-map-02` lost one commit (restored by its owner as a
fast-forward, now `770ecdfb`); `exp/tensor-kernel-contract-01` lost ten, rescued
additively to `rescue/tensor-kernel-contract-01-prerewrite` (`35f6a017`). The
general form is not "a stale read" but "two refs with the same-looking identity
resolved by name preference".

## The trap this leaves armed, and the one it disarms

`.gitignore` now ignores `.semgrep/`. It had to, because the Guardian rewrites
that file on every token refresh, so it is permanently dirty, and the working
copy — unlike anything ever committed — does hold a live JWT and refresh token.
Twice today a broad `git add` swept the harmless pre-login form into a commit.
That was luck.

**A stale index is the live hazard right after a force-push.** A worktree whose
index was built against the pre-rewrite HEAD sees the purged files as things to
ADD. An ordinary, correctly path-scoped `git add` in such a worktree stages
`.semgrep/*` and `GUTEN_MORGEN_KAYA.md` as additions, and committing that undoes
the purge for those paths from a lane that never touched them. One peer hit this
on its first commit after the push and caught it with `git reset` (mixed). Every
worktree carrying a stale index has the same loaded gun, and it fires on a
perfectly ordinary command.

Each lane should verify in its own worktree, and trust neither this document nor
the ref having moved:

    git ls-files | grep -Ei 'semgrep/guardian|GUTEN_MORGEN'   # expect empty
    git check-ignore -v .semgrep/guardian.yml                 # expect a hit

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

**A caveat on that rule, on this machine.** In git-bash, MSYS argument
conversion rewrites `<ref>:<path>` into a Windows path list when the ref
contains a slash and the path does not. Characterised by probe:

    git show origin/main:.gitignore          -> fatal: ambiguous argument
                                                'origin\main;.gitignore'
    git show main:.gitignore                 -> works   (ref has no slash)
    git show origin/main:docs/HANDOFF.md     -> works   (path has a slash)
    git show <sha>:.gitignore                -> works
    MSYS2_ARG_CONV_EXCL='*' git show origin/main:.gitignore  -> works

One session hit this, read the failure as "main has no .gitignore at all", and
came within a message of reporting a correct claim as false. Note what saved it
and what to generalise: this failure is LOUD. It does not return wrong content —
it refuses. That makes it a different and milder hazard than `git log <sha>` or
`cat-file -e` succeeding on an unreferenced object, which answers confidently
and wrongly. The shared lesson is only that the command you typed may not be the
command that executed; the danger differs sharply between the two cases.

The measurements in this record are unaffected: they used commit SHAs, which
contain no slash, or paths that do.

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

All nine worktrees were measured clean of the purged paths after realignment.
Two caveats on that measurement, both from the lane that found the hazard:

- `ls-files` proves the purged paths are gone from an index. It does NOT prove
  the index is current, and a stale index is dangerous for reasons beyond those
  paths — its staleness surfaces as index-vs-HEAD ADDITIONS, which that check
  cannot see. `git reset` (mixed) in each worktree is free, idempotent, and is
  the thing that actually answers freshness.
- A worktree created after the rewrite cannot have carried a pre-rewrite index,
  so its cleanliness is structural rather than evidence about the others.

## The re-pinning trap: a SHA that resolves is not a SHA that survived

Repointing pins from the map, one lane found two of its four still resolving
perfectly under `git log` in its worktree — while `git branch --contains`
returned empty for both. They were unreferenced objects awaiting garbage
collection. **A pin that resolves today only because the old objects have not
been collected yet is a pin that breaks in a fresh clone, silently and later.**
Spot-checking `git show <sha>` is the wrong test for whether a pin survived this
rewrite; presence in `sha-map.tsv` is the right one.

The same lane confirmed the predicted contrast inside one metadata block: its
`Base revision` moved, its `Effect-registry digest` re-measured byte-identical.
A content digest of what a thing IS survives a rewrite; a pointer to where it
sat does not.

## Unrelated finding this operation surfaced

The Semgrep Guardian resolves its session state RELATIVE TO THE WORKING
DIRECTORY. Measured across every tree on this machine:

    ~/.semgrep/guardian.yml            1699 B   logged in
    primary checkout                   1768 B   logged in
    apps/web/                           140 B   pre-login
    all seven linked worktrees      140-145 B   pre-login

A tool call made from a worktree finds a state that has never been logged in and
is refused with "Not logged into Semgrep Guardian"; the same call from the
primary checkout succeeds. This explains an intermittent refusal rate that three
sessions independently reported as uncorrelated with file, path depth, content
or size: the variable is the caller's cwd, not the edit.

### Settled by A-B-A replication in two independent sessions

The deciding variable is the **Bash session's persistent working directory** —
the one `cd` mutates and which survives across calls — and it governs the `Edit`
and `Write` tools too, not only `Bash`.

    cwd = worktree   ->  Edit worktree file   ->  REFUSED
    cwd = primary    ->  Edit the SAME file   ->  SUCCEEDED
    cwd = worktree   ->  Edit the SAME file   ->  REFUSED     (replication)

Identical target file in all three; only the cwd changed. A second session ran
the mirror form — 12 refusals and 3 successes across five conditions, including
a primary-checkout file edited from a worktree cwd (refused) and a worktree file
edited from the primary cwd (succeeded). Both directions measured, both
replicated, and the refusing condition was independently confirmed live at the
minute the cross-check ran, so the successes are observations rather than a
quiet machine.

**Three hypotheses died here and all three were ours.** A concurrent-write race
(refuted: `serial: 4`, no write in three and a half hours — four writes cannot
produce a 60% rate). Resolution by the edited file's location (refuted by the
table above). And the "Edit refused while Bash succeeded" pair that looked like
a tool-surface difference: those Bash calls had been `cd`-ing into a worktree to
run tests, the cwd persisted, and later Edits inherited it. Bash was not
surviving the condition — Bash was CREATING it.

The 60% figure was never a rate. It was the fraction of the day one session's
cwd happened to sit in a worktree. An earlier datapoint from 09:00 was also
retired by its owner once the login timestamp (15:17) showed it predated any
login at all.

**A proposed fix failed mechanistically, and it was this session's.** Removing a
worktree's `.semgrep/` does not fall back to `~/.semgrep`: the Guardian
RECREATES it in cwd as a fresh 140-byte pre-login stub, measured within the same
minute as the five refused edits that followed the removal. "Stop letting
per-worktree `.semgrep/` directories exist" is therefore not available — they
come back on their own. The real fix is resolving to one shared state root;
logging in per worktree, or keeping cwd in a logged-in tree, are workarounds
that every new worktree re-breaks.

**Practical consequence, worth more than the mechanism:** any session that `cd`s
into a worktree to run tests silently loses the ability to edit ANY file,
including files in the logged-in primary checkout. It presents as a broken tool
and has nothing to do with what is being edited. `cd` back and it works.

Incidental: the hook is evaluated BEFORE `Edit`'s string match, so a refused
edit never writes and a follow-up edit then fails on a missing `old_string` with
an error that looks unrelated to the hook.

### The ignore rule was on main only, and main is not where the token lives

Immediately after this record first claimed the trap closed, `git check-ignore`
across all nine worktrees returned NOT IGNORED in eight — including the primary
checkout, the one tree holding the LOGGED-IN 1768-byte guardian.yml with a live
JWT. The `.gitignore` rule had landed on `main`; the primary checkout sits on a
packet branch. The trap reported as closed was still armed in the most dangerous
tree.

Closed branch-independently by appending `.semgrep/` to `.git/info/exclude`,
which every linked worktree shares and which is not versioned, so it took effect
in all nine at once without touching any lane's branch. Re-measured: nine of
nine ignored. The tracked rule on main remains the durable fix for fresh clones,
and every branch still needs it merged — an untracked live credential beside an
unignored path is one `git add` from the same trap.

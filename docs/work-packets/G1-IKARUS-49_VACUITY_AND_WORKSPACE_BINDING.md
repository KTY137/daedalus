# G1-IKARUS-49 — the evaluator answers vacuity, not only forgery

Packet ID: `G1-IKARUS-49`
Artifact role: `primary`
Active gate: Gate 1
Classification: `ALIGNED`
Owner: repository owner (standing merge authorization of 2026-09-10, `CLAUDE.md`)
Base revision: `6fecb1340b88076b7c20bc4fc2583652bc3a9c5a`
Dependencies: G1-IKARUS-48 (the test-running evaluator, merged)

## Primary acceptance claim

A nomination requires evidence that the suite **ran and disagreed** about the
changed region, not merely that the file still loads: the arms are compared by
which tests ran and what each said, the negative control must contain a test
that the baseline PASSED and that FAILED rather than errored, and the evaluation
workspace is built from the revision's blob digests rather than compared with
its file list afterwards.

## Why this packet exists

G1-IKARUS-48 shipped with an honest account of one risk and no account of a
second. Its disclosures — `verdict_is_self_reported`, "the verdict is a
SELF-REPORT", "raises the cost of a forgery" — all protect a reader against a
candidate that **lies about** the run. An adversarial pass on the merged commit
produced three nominations in which **nothing lies**: pytest writes the report
truthfully, the counts match, `git status` is clean, and the nominated repair is
still worthless. The packet was candid about forgery and silent about vacuity.

## What was measured on the merged commit

| # | measured | consequence |
| --- | --- | --- |
| O2-1a | `LIMIT = 10` → `LIMIT = 999`, a real behaviour change, nominated although no test reads `LIMIT`. The negative control failed because the mangled file no longer parsed | the control proved the suite LOADS the file, not that it exercises the changed region |
| O2-1b | two lines in the candidate (`_pytest.python.Function.runtest = lambda self: None`) neutered every assertion while the same tests were collected and "run"; counts identical | a cardinal count cannot tell a run from a performance of a run |
| O2-2 | one line in `$GIT_DIR/info/attributes` — untracked, in no revision, invisible to `git status` — removed the guarding test from the workspace and flipped a refusal into a nomination | `git archive` honours that file; "the workspace is the pinned revision" was unchecked |
| O2-3 | this repository's own `tests/conftest.py` imports `daedalus.budget`, `daedalus.provider_router`, `daedalus.sensitivity`; all three are admissible campaign targets and all execute at conftest-import time | `SESSION_CONTROL_NAMES` is an enumeration, and the privilege it denies to `conftest.py` is reachable through ordinary modules |
| O2-4 | `('python', '-c', "import os; os.system(...)")` was admitted, as was a path outside the workspace | the packet's acceptance row claiming otherwise was false |
| O2-6 | `workspaces/attempts/<arm>/` grows six directories per campaign and is removed on no path | "every arm removes its workspace" was true of one workspace and read as both |

## What this packet changes

1. **The verdict compares identities, not cardinals.** Each arm's JUnit report
   yields sorted `classname::name=outcome` pairs. The repair must report the
   same tests with the same outcomes as the baseline, and the negative control
   must differ from it.
2. **The negative control must contain a FAILURE the baseline passed.** A test
   that errored did not run. This makes many campaigns refuse where they
   previously nominated; that is the correct direction, because those campaigns
   proved nothing. The two reasons a control can fail to discriminate are now
   distinguished, because saying the wrong one is a lie the operator acts on:
   the mutation appends an identifier to the target text, which is a syntax
   error after a number, a closing quote or a `def` name, and there even a
   covering suite errors. That case names itself and says which `before` shapes
   can produce the evidence.
3. **The workspace is BUILT from the revision, not checked afterwards.** The
   first version of this packet compared the file NAMES `git archive` handed
   over with `git ls-tree`. Review round 1 defeated that in one line:
   `git archive` also applies attribute-selected smudge filters, so the
   guarding test's body was rewritten while the file list stayed identical —
   and the filter, an arbitrary shell command from an untracked config, ran on
   the host outside the contained gate. `git archive` is gone. The workspace is
   written from blob digests through `git cat-file --batch`, each file verified
   against the digest the revision names, with no attribute, filter or
   end-of-line input anywhere in the path. That also settles the separate
   finding that `core.autocrlf` made the workspace differ from the revision on
   this host, and it makes this repository admissible as its own subject again:
   its four tracked symlinks are materialised as the paths their blobs store
   instead of being refused.
4. **The argv head is an allowlist.** The first version denylisted `-c` and
   `--command`; review round 1 defeated it with `-Ic`, because CPython bundles
   short options, and with `-Sc`, `--command=`, `-` (program on stdin),
   `-m pip install` (which writes the interpreter that judges every later
   campaign) and `--pyargs` (which runs an installed package's tests instead of
   the workspace's). A denylist of an option parser this module does not own
   cannot be closed. The command IS `python -m pytest`; its arguments are still
   held to the workspace, and `-p` may only DISABLE a plugin, never load one.

## What this packet does NOT close, measured and retained

**The in-place neutering of the suite (O2-1b) is still nominated.** It is pinned
by `test_a_repair_that_neuters_the_suite_in_place_is_still_nominated`, which
asserts the measured outcome rather than the desired one. The reason is
structural and stated in G1-IKARUS-48: the target must be a file the suite
imports, so candidate code runs inside the judging process, and no inspection of
what that process reports can distinguish a run from a performance of a run.
Comparing identities closes every case where the outcomes differ. It cannot
close this one, and claiming otherwise would be the defect this repository
blocks on.

The structural answer is a separate packet: the arms' outcomes must be observed
from outside the child, over a channel established before the candidate's code
runs. Until then, what protects the repository is unchanged — the receipt says
the verdict is self-reported, and a nomination is not a promotion.

**Also not closed here, and named because a packet whose thesis is "the last
one was silent about vacuity" cannot ship with a vacuity route of its own.**
Review round 1 measured one: any content-sensitive test — a style, lint, census
or byte-pin test that reads the source as text rather than executing it —
supplies the failing negative control without ever running the changed region.
All the new gates pass and the nomination is still vacuous. This repository has
at least twelve such tests. Closing it needs the same import trace as the
conftest surface below: the failing control test must be one that IMPORTS the
target, which the baseline arm could record and this packet does not. The cheap
half is done — the failing test must be one the baseline passed, which closes
the flaky-rerun and foreign-id variants.

Also not closed here: the conftest-import surface (O2-3). A name list cannot
express "a module the session imports before collection", and the honest fix is
either a declared, per-project allowlist of admissible targets or an import
trace taken from the baseline arm. Recorded as the next question, not patched
with a longer list of names.

## Scope

In scope: `daedalus/ariadne/campaign.py`, `tests/test_ariadne_test_evaluator.py`,
this document. Forbidden: `daedalus/spine/**`, `daedalus/kernel/policy/**`, the
master plan, its amendment chain, `AGENTS.md`.

## Contracts and behavior

- `_read_test_identities` reads the same bounded, entity-refusing report as the
  counts; an unreadable report yields an empty tuple, which fails the comparison
  closed.
- The three new refusals each name which property is missing, so a campaign that
  cannot prove coverage says so instead of failing anonymously.
- No effect, lease, write root or promotion path changes.

## Acceptance matrix

1. a change no test reads is refused, naming the control that only errored;
2. the in-place neutering is nominated, and the test says so as negative
   evidence, with the hedge present on every observation and the nomination;
   the same for a content-sensitive test supplying the control's failure;
3. an untracked `export-ignore` line is refused by the workspace comparison,
   with `git status` clean at the time;
4. an inline program, an absolute path and a `..` in the argv are refused, and
   the ordinary `-m pytest -q tests` shape is admitted;
5. the exact-match default path is unchanged;
6. the existing G1-IKARUS-48 suite still passes.

## Evidence, expected failures and review

`tests/test_ariadne_test_evaluator.py`, 23 tests. Expected failures, retained:
the neutering nomination above, and every campaign whose suite cannot produce a
failing negative control. Review: this packet exists because an adversarial pass
on a merged commit found what five review rounds had not.

## Migration and rollback

Revert the packet's commits. No stored artifact changes shape; the new
comparisons are computed from reports that were already being written.

## Review round 1 (2026-09-10, `fb7be545`)

**Cerberus: `block`, two CRITICAL, both repaired.**

| # | finding | repair |
| --- | --- | --- |
| CRITICAL 1 | the workspace comparison checked NAMES, and `git archive` applies attribute-selected SMUDGE filters: the guarding test's body was rewritten with no refusal, and the filter command ran on the host with the operator's environment | `git archive` is gone; the workspace is written from blob digests via `git cat-file --batch`, verified per file |
| CRITICAL 2 | `-Ic` bundles the inline-program switch, so a token denylist could not express the rule; `-Sc`, `--command=`, `-`, `-m pip install` and `--pyargs` were all admitted | the head is an allowlist, `python -m pytest`; `-p` may only disable a plugin |
| high 1 | a content-sensitive test supplies the control's failure without executing the changed region — a vacuity route this packet opened | cheap half fixed (the failing test must be one the baseline passed); the rest is named above rather than half-closed |
| high 2 | the refusal said the suite "only showed that the file still loads", which is FALSE for 5 of 10 realistic target shapes: the mutation appends an identifier, which is a syntax error after a number, a quote or a `def` name, so even a covering suite errors | the two situations are distinguished and each is named, and this packet's own headline test used the wrong one as its demonstration — corrected |
| medium 1 | the outcome mapping was namespace-blind and first-child-wins, and the counts and identities read the same file by different routes without ever agreeing | worst-outcome-wins at any depth, namespace-blind on the way in, and a report whose two halves disagree is discarded |
| medium 3 | the two new git calls had no environment scrub and no timeout, while the kernel's own git path has both | one bounded, scrubbed helper for every git call this module makes |

**Measured after the repairs:** this repository extracts through the object
database in 4.65 s (6378 files, 282 MiB), and the previously refusing symlinks
now materialise, so the self-Renovation strand can name its own repository as a
subject.

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
that FAILED rather than errored, and the evaluation workspace must match the
pinned revision's own tree listing.

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
2. **The negative control must contain a FAILURE.** A test that errored did not
   run. Requiring at least one `=failure` is what separates "the suite
   disagreed" from "the file did not import". This makes many campaigns refuse
   where they previously nominated; that is the correct direction, because
   those campaigns proved nothing.
3. **The workspace is checked against the revision.** `_extract_revision`
   compares what it wrote with `git ls-tree -r <revision>`, which does not read
   `info/attributes`, and refuses on any difference.
4. **The argv rule exists.** No inline program (`-c`, `--command`), no absolute
   path, no `..`. `-m pytest` remains, because that is how a test command
   starts.

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

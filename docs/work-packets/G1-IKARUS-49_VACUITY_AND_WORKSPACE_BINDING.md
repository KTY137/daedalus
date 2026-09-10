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
4. **The argv is an allowlist — head AND arguments.** The first version
   denylisted `-c` and `--command`; round 1 defeated it with `-Ic`, because
   CPython bundles short options. So the HEAD became an allowlist,
   `python -m pytest` — and round 2 defeated the ARGUMENTS exactly the same
   way, one token to the right, because the loop skipped every `-`-leading
   token that was not an *exact* member of a forbidden set. `-pevilplugin`
   imports and EXECUTES an arbitrary module before conftest, under the
   campaign's lease; `-cC:/Windows/win.ini` makes pytest read a config file
   outside the workspace whose `addopts` re-injects any option at all,
   including the plugin load. Both were admitted and both are honoured by the
   real pytest.

   Round 3 then defeated the *path* branch, which was still a denylist:
   `@C:/Windows/Temp/pwn.txt` was admitted, because it is **not a path**.
   pytest builds its parser with `fromfile_prefix_chars="@"`, so argparse opens
   the named file and splices its lines in as arguments — before pytest sees
   them, with no path restriction at all. Measured through `run_campaign`, a
   `conftest.py` outside the workspace and in no revision was imported and
   EXECUTED inside the contained gate in all three arms, after reading the
   operator's environment; only the sandbox write root stopped it leaving a
   marker.

   Three rounds, one shape: enumerating bad forms instead of admitting good
   ones. Options are admitted by name — six bare ones, `--tb=STYLE` from
   pytest's own closed set, `--maxfail=N`, and `-p no:NAME` including the
   bundled `-pno:NAME`. Path tokens go through `_admit_workspace_relative`,
   the same primitive the revision entries use, with an explicit refusal of
   argparse's prefix character on top — required rather than implied, because
   that primitive admits `@pwn.txt` on its own.

   **What this narrowing costs, in full.** Refused along with the inline
   programs: node ids (`tests/t.py::test_a`), `-k EXPR`, `-m MARKEXPR`,
   `--ignore=`, `--deselect`, `-ra`, `-v`, `--co`, `--`, a trailing separator,
   and any path spelled with a backslash. `-k` and `-m` are the two that
   matter: with no selection mechanism, every arm runs a whole directory three
   times under the 900-second ceiling, which is a real operational limit on a
   repository with a slow suite.

   It is not pure loss, and the upside should be claimed rather than
   discovered: a whole-suite run makes the cross-arm identity comparison
   *stronger*, because a selection is a place where the three arms could
   silently disagree about what ran. Adding `-k` back is an evidenced change,
   not an oversight.

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
   the same for a content-sensitive test supplying the control's failure —
   `test_a_content_sensitive_test_supplies_the_control_failure_without_executing`,
   written in round 2 after review found this row asserting a test that did not
   exist;
3. an untracked `export-ignore` line is refused by the workspace comparison,
   with `git status` clean at the time;
4. every argv option is admitted by name and every argv path through
   `_admit_workspace_relative`; an inline program, a bundled short option, an
   argparse argument file (`@…`), an absolute path, a `..`, a device segment
   and a `:` are all refused, and the ordinary `-m pytest -q tests` shape is
   admitted;
5. the exact-match default path is unchanged;
6. the existing G1-IKARUS-48 suite still passes.

## Evidence, expected failures and review

`tests/test_ariadne_test_evaluator.py`, 28 tests. Expected failures, retained:
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

## Review round 2 (2026-09-11, `c8d2496d`)

**Cerberus: `block`, one CRITICAL unrepaired.** CRITICAL 1 was attacked against
a hand-built hostile tree (`git mktree`, so the shapes `git add` refuses) and
held: a blob whose content embeds a fake `<40hex> blob <n>` frame extracted
byte-exact, because the parse is length-prefixed; `..\..\x`, drive letters,
alternate data streams, trailing dots and spaces, NTFS case collisions and
gitlinks were all refused; nothing escaped the workspace root.

| # | finding | repair |
| --- | --- | --- |
| CRITICAL 2 | **not repaired.** The head was an allowlist; the arguments were still a denylist, and the loop skipped any `-`-leading token that was not an exact member of it. `-pevilplugin` loaded and executed a module (`PLUGIN_IMPORT_EXECUTED`, measured against real pytest 9.1.1); `-cC:/Windows/win.ini` read a config outside the workspace and its `addopts` re-injected the plugin load | the arguments are an allowlist too, and the suite now carries the bundled forms rather than only spellings the code already refused |
| high 1 | `_admit_workspace_relative` promised "no device name" and had no such check: a tree of `NUL` + `ok.txt` extracted as **two files with one on disk**, because writing to `NUL` silently succeeds and the counter still says two | device names refused on every host (the workspace must be the revision on every host, not only where the name happens to be writable), plus a post-write size check that refuses whatever the enumeration misses |
| high 2 | acceptance row 2 asserted a pin for the content-sensitive vacuity route **that was never written**. The prose was honest; the matrix row was not | the test exists now and asserts the measured outcome: a suite that only reads the source as text supplies the control's failure, every gate passes, and the nomination is vacuous |
| medium 1 | three helpers defined twice, byte-identical — the later copies win, the first three are dead, and one of the dead copies is the environment scrub | deleted |
| medium 2 | `_revision_file_list` was dead **and** was the one unscrubbed, untimed git call, so round 1's "one bounded helper for every git call" was true only because nothing called it | deleted |
| low | the payload was verified against the oid git ECHOED, never against the oid the TREE named | the sha1 is bound to the tree's digest. A separate header comparison would be redundant, not defence in depth, because a substituted object is internally consistent and dies on the digest — so the binding is pinned by a test instead of duplicated by a branch |
| low | two comments described designs that no longer exist (a bounded excerpt that is now no output at all; a comparison that is now a construction) | corrected |

**Mutation table, 5/5 guards proven load-bearing:** disabling the argument
allowlist, the plugin-disable rule, the device-name refusal, the post-write size
check, or the digest binding each turns a named test red.


## Review round 3 (2026-09-11, `adfae1d9`)

**Cerberus: `block`, one CRITICAL — new, and the third instance of one shape.**

| # | finding | repair |
| --- | --- | --- |
| CRITICAL 3 | `@<any path>` admitted. pytest sets `fromfile_prefix_chars="@"`, so argparse splices the named file's lines in as arguments with no path restriction. Measured end to end: a `conftest.py` outside the workspace was imported and EXECUTED in all three arms, and all three exited zero having run a suite that is not in the workspace | path tokens go through `_admit_workspace_relative`; argparse's prefix character is refused explicitly |
| low | `str.isdigit()` is true for `²` while `int()` raises, so `--maxfail=²` escaped as a bare `ValueError` rather than an `AriadneCampaignError`, breaking the contract that every refusal here is one | ascii guard |
| low | `--plugin` was admitted and pytest has no such option (`-p` is short-only), and the suite had pinned `--plugin=no:randomly` as a GOOD campaign shape — a command that exits 4 in every arm | removed from both |
| low | untracked scratch under `runs/` turned `test_registry_new_doors.py` red, and `runs/` is a tracked directory | scratch moved out of the tree |

**Confirmed by the reviewer, independently:** the device-name refusal holds
against every spelling Windows actually resolves as a device (`NUL `, `NUL.`,
`NUL:`, `CONOUT$.log`, `aux.tar.gz`), and the spellings it admits — `com¹`,
`ＮＵＬ`, `NUL~1` — are measured **not** to be devices on this host. The
content-sensitive vacuity test demonstrates the route for the stated reason.
The three duplicate helpers and the dead file list are gone. The removal of the
header comparison was right: binding the payload to the oid the tree names is
strictly stronger, so there is no case the header check caught that the digest
check misses.

**The lesson worth keeping, and it is the reviewer's:** no mutation could have
caught CRITICAL 3, because the mutation set is drawn from the same imagination
as the rule. A mutation table proves a guard is load-bearing; it cannot prove
the guard is the right guard. What caught this three times was executing the
real tool against the admitted argv.

**Measured after round 3:** 28 tests in the packet suite; 4/4 new guards
load-bearing (removing the argparse-prefix refusal, the shared path admission,
the ascii guard or the `--plugin` removal each turns the argv test red).


## Review round 4 (2026-09-11, `02c2c527`)

**Cerberus: `pass`, `blocking: false`.** No CRITICAL stands. CRITICAL 3 is
repaired and the reviewer could not make an admitted path token reach outside
the workspace across 47 measured shapes; `@` is confirmed to be argparse's only
pre-application resolution, and the leading-character test is placed correctly.
Every admitted shape was executed against real pytest 9.1.1 — eleven commands,
no exit 4 anywhere, which is the first time this packet's *good* list has been
verified against the tool rather than against its own rule.

| # | finding | repair |
| --- | --- | --- |
| high 1 | pytest's rootdir discovery walks **upward out of the workspace**. An ini file in an ancestor becomes the configfile and its `addopts` re-injects any option — including `-p <module>`, which loads and executes arbitrary code inside the judging process. That is round 2's CRITICAL **with no hostile argv at all**, so no argv rule can close it, and the comment claiming the candidate "cannot reach any other byte" was false | the campaign appends its own `-c`, beside `--junitxml=`, pointing at a config it writes into the workspace. Pinned by a property test that booby-traps the surroundings and asserts the tripwire fires without the fence and not with it |
| low 2 | `_admit_workspace_relative` returns a normalised path and the caller discarded it, so `tests\unit` was admitted and pytest was handed the backslash spelling verbatim — validating one string and executing another | the argv IS the campaign identity, frozen into the `ExperimentSpec` digest, so normalising it would change the digest. A spelling that is not already the admitted one is refused, naming the spelling to write |

**Why high 1 was high and not CRITICAL, and what is actually holding it.** The
candidate cannot plant the ancestor config: the workspace is labelled
Low-integrity inheritably and its ancestors are not, so a Low process cannot
write up. No ancestor config exists on the measuring host — every ancestor was
scanned. **But that only holds because the workspace lives under the control
root.** Round 3 moved it to `%TEMP%`, where any same-user process could plant
one; round 4 moved it back for unrelated reasons and got this for free. That is
now written at the extraction site so the next person does not move it again.

## The argv is the wrong shape, and this packet says so

Asked directly whether this should merge at all, the reviewer argued from this
packet's own record rather than from taste, and the argument is right.

Four rounds, four breaches, each at a different token position: the head, the
option, the option's bundled tail, and a token that was neither. What survives
the fence is a directory or two, six boolean flags, one enum, one integer and
`-p no:NAME`. **The typed design already exists — it was built by attrition and
is still spelled as a string, and the string is what keeps costing review
rounds.**

The replacement is booked as the next packet: `argv: tuple[str, ...]` becomes
`paths`, `maxfail`, `tb`, `quiet`, `exitfirst`, `no_header`, `no_summary`,
`disable_plugins`, and the campaign *builds* the argv. Then there is no token a
caller can spell, so there is no parser surface to enumerate, and `-k` returns
later as an additive typed field rather than as a hole. The digest stays in the
`ExperimentSpec` exactly as it does today.

**Read the argv shape here as a scar, not as a principle.** "Options admitted
by name, paths by the same primitive" is what four rounds cost, not what anyone
would design.

## The general check that would have caught all three rounds

Also from round 4, and worth more than the fence it critiques: no mutation
could have caught any of the three CRITICALs, because a mutation set is drawn
from the same imagination as the rule it mutates. Two assertions over the
*good*-shapes list are enough, and cost about eight seconds:

1. **every admitted shape must be a shape the tool accepts** — run it, require
   exit ∈ {0,1,5} and a JUnit report. This catches `--plugin=no:randomly`
   (exit 4) and round 1's `-Ic`, the latter not by recognising the option but
   because the child was not pytest and wrote no report;
2. **every admitted shape must run in a canary workspace whose surroundings are
   booby-trapped**, with no tripwire firing. This is a *property* — "nothing
   outside the workspace was read or executed" — rather than an enumeration,
   which is why it survives the author's imagination running out. It would have
   caught rounds 2 and 3, and it catches high 1 for free, with no argv
   involved.

The contained half of (2) is in this packet as
`test_a_config_in_an_ancestor_cannot_reach_into_the_workspace`. The full
version, driven through `run_campaign`, goes with the typed-knob packet.

**Measured after round 4:** 30 tests in the packet suite.

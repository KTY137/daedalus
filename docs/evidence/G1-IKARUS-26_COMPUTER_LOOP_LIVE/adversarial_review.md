# G1-IKARUS-26 (stage 13) — independent adversarial verification

Reviewer: Claude, lane 9 of the owner's 2026-09-05 parallel fleet.
Subject: commit `cfe8d34b8ef1438156e6fa3e6982f5a30d91696f`, packet
`docs/work-packets/G1-IKARUS-26_COMPUTER_LOOP_LIVE.md`.
Worktree: `.claude/worktrees/lane9-adversarial-stage13`, branch
`loop/lane9-adversarial-stage13`, stacked on `loop/stage3-failed-receipt`.
Interpreter: worktree-local `uv venv` (CPython 3.13.14) with `pip install -e ".[computer]"`;
the main checkout's editable install was deliberately not used.
Role: master-plan §10 step 6 (adversarial verification). Read-only on `daedalus/`
and on the two existing test modules. Nothing merged, nothing promoted.

This review is evidence, not a gate. It does not close the packet and does not
overrule the owner.

## What was attacked

The packet's two claims:

- **(A)** `ComputerService.capabilities()` records every release-locked tool in
  `unavailable` with the lock reason, and the loop summary and the
  `/computer status` sentence name "configured but every tool unavailable"
  apart from "no policy".
- **(B)** Three consecutive identical advisory plans end the mission as
  `stalled` under every execution-limit mode, with resets on a different plan,
  a tool or finish proposal, or an invalid response; all proposals stay
  retained; the rule holds under `unbounded_execution`.

Method: a 20-case behavioural probe against the real loop with an adapter
double; a 9-mutant matrix on an isolated scratch copy of the commit
(`git archive cfe8d34b | tar -x`, its own venv) recording which existing tests
notice each disabled guard; static reads of the policy, parser, prompt and
status paths; and a digest/leak audit of the evidence directory.

Both claims are **substantially true as stated**. The findings below are two
untested contract properties, one scope limit that the packet does not name,
and an evidence-integrity defect in the manifest.

## Baseline

```
.venv/Scripts/python.exe -m pytest tests/test_ikarus_computer_loop.py \
    tests/runtimes/test_computer_service.py -q
-> 56 passed in 98.42s
```

The packet's "4 fail without the change, 2 guard the resets" reproduces exactly
in the mutation matrix: reverting defect 1 fails 2 tests (M1, M2), removing the
stall break fails 2 (M3), and the two reset lines are guarded by one test each
(M5, M6).

## Findings, ranked

### F1 — CONFIRMED (medium). Every MANIFEST digest fails on a Windows checkout, and the repo's own byte-pin census does not notice

The 19 digests are taken over the committed LF bytes. `core.autocrlf` is `true`
in this repository (the `.gitattributes` header documents that as this host's
setting), `docs/evidence/**` carries no `-text` pin, and the files are checked
out CRLF. A reviewer who hashes the files gets 19 mismatches out of 19.

```
$ python  # in docs/evidence/G1-IKARUS-26_COMPUTER_LOOP_LIVE
MISMATCHES: 19/19   (e.g. measure_script_bounded.py
                     want f833457417291a20e73ca95e6ba62ece29b105250d6a31fc06cd162f4bc64483
                     got  a8c520a694f6d70be58639e025a99a5491ed8df4d49ac2d9f72da73c32cbe08d)

$ python  # same files, compared against the committed blob
matches against the git blob (LF as committed): 19 / 19
matches against worktree bytes with CRLF->LF:   19 / 19
first file has CRLF on disk: True

$ git show cfe8d34b:.gitattributes | grep -n "docs/evidence\|MANIFEST"
(no output; only docs/IKARUS_ARIADNE_MASTER_PLAN.md and .amendments.jsonl are pinned)
```

This is precisely the recurrence the `.gitattributes` "BYTE-PIN SUBJECTS" header
predicts ("it recurs because the protection was a hand-maintained per-file list
and every new byte-pin subject arrives unlisted"). The paired durability guard
does not fire:

```
$ .venv/Scripts/python.exe -m pytest tests/test_byte_pin_eol_durability.py -q
17 passed in 141.41s
```

Cause: `_census()` in that module walks only `daedalus/`, `tests/` and `tools/`
for `*.py` and detects three code shapes (`*SOURCE_PATH` constants,
`_RETAINED_SOURCE_NAME`, self-`__file__` hashing). A JSON manifest under
`docs/evidence/` that pins 19 sibling files is invisible to all three. This is
the first `MANIFEST.json` under `docs/evidence/` (`find docs/evidence -name
MANIFEST.json` returns exactly this one), so the census has never had to cover
the shape before.

Not fixed here (`.gitattributes` and the census test are outside this lane's
write scope). Remedy is one of: add `docs/evidence/**/*.* -text` beside the
existing pins and extend `_census()` with a manifest detector, or state in the
packet that the digests are over committed LF bytes and give the `git cat-file`
verification command.

This review file is deliberately **not** added to `MANIFEST.json`: it postdates
the manifest, it is not packet evidence, and rewriting the packet author's
digest set from a review lane would be the wrong direction. A manifest check
will therefore report it as an unlisted file; that is expected.

### F2 — CONFIRMED (medium). Two properties the packet states as contract had no test; both mutants survived the full focused suite

Mutation matrix on the scratch copy, `tests/test_ikarus_computer_loop.py` +
`tests/runtimes/test_computer_service.py` (baseline 56 passed):

| Mutant | Guard disabled | Result | Noticed by |
| --- | --- | --- | --- |
| M1 | drop `unavailable[tool] = PATH_IO_RELEASE_REFUSAL` | 1 failed | `test_release_locked_tools_are_reported_unavailable_not_silently_dropped` |
| M2 | revert `_unavailable_summary` to the fixed string | 1 failed | `test_release_locked_policy_is_reported_as_locked_not_as_missing` |
| M3 | remove the identical-plan stall break | 2 failed | the two stall tests |
| M4 | threshold 3 → 4 | 2 failed | the two stall tests |
| M5 | remove the tool/finish reset line | 1 failed | `test_a_different_plan_or_a_tool_step_resets_...` |
| M6 | remove the invalid-response reset line | 1 failed | `test_an_invalid_response_between_plans_resets_...` |
| M7 | `steps = [s.strip() for s in proposal["steps"]]` (whitespace-normalised compare) | **56 passed** | **NOBODY** |
| M8 | evaluate the stall before the plan progress event / revision bump | 1 failed | `test_three_identical_plans_stall_even_under_unbounded_execution` |
| M9 | revert the `/computer status` sentence to its single pre-stage-13 form | **56 passed** | **NOBODY** |

M7 contradicts the packet's stated contract and Codex's named counter-case
("exact comparison of the parsed ordered `steps` list — no whitespace
normalisation, which could equate different literals"). M9 contradicts the
packet's primary acceptance claim, which explicitly includes the
`/computer status` sentence. The code is correct at `cfe8d34b`; only the pins
were missing.

Fixed in this lane: `tests/test_ikarus_computer_loop_adversarial.py` (new file;
the existing modules were not touched — another lane owns them). Verified in the
scratch copy that the new tests kill both survivors and pass on unmutated source:

```
baseline:                          5 passed
M7_whitespace_normalised_compare:  1 failed  (test_a_whitespace_only_difference_is_a_different_plan)
M9_revert_status_sentence:         1 failed  (test_computer_status_sentence_distinguishes_...[capabilities0])
restored:                          5 passed
```

M8 deserves a note: retention is only *partly* pinned. Moving the check earlier
is caught by `result["plan"]["revision"] == 3`, not by a direct assertion that
the third proposal artifact was stored — `len(result["proposals"]) == 3` still
holds under M8 because the artifact is written before the parse. Adequate, but
the retention claim rides on the revision number.

### F3 — CONFIRMED (medium). The rule bounds a 1-cycle only; under `unbounded_execution` the measured failure class survives for any planner that varies its output

The stall rule ends a run that repeats *one* plan. It does not bound the loop.
Under the owner's `unbounded_execution` policy neither `attempts` nor
`wall_time` is enforced, and the `consecutive_repairs >= _MAX_CONSECUTIVE_REPAIRS
-> blocked` branch is itself gated on `limit_policy.enforces("attempts")`, so
nothing terminates these:

| Probe | Planner behaviour | Measured |
| --- | --- | --- |
| A6 | two valid plans, alternating | 61 planner calls, 59 replans, no stall (stopped only because the fixture ran out of scripted turns at 60) |
| A5 | a valid plan alternating with a plan whose step contains `\n` (parser-invalid) | 41 planner calls, 20 repair calls, no stall, no block |
| A7 | 50 *distinct* invalid responses | 51 planner calls, 50 repair calls, no stall, no block |

A7 is pre-existing, not introduced by stage 13; A5 and A6 are the direct
analogues of the failure the live `computer-loop-measure-03` mission exposed
(a loop that only the kill switch ended). The packet's claim is literally true —
three *consecutive identical* plans do stall — but the sentence in the commit
message, "identical advisory plans were no stall … three consecutive identical
plans now end the mission as stalled", reads as if the measured class is closed.
It is closed for the exact planner behaviour observed on that host, not for the
class. The packet's own "Review questions" ask whether 3 is the right threshold
but do not name this gap.

No new subsystem is needed to close it; the honest options are a bounded
no-progress budget (planner calls since the last tool observation) as a progress
criterion beside the existing three, or an explicit statement that under
`unbounded_execution` the kill switch remains the only terminator for a
non-repeating planner. Not built here — it is a Work Packet, not a review edit.

### F4 — CONFIRMED (low). Trivial variations defeat the rule; the parsed-steps comparison is nevertheless the right level

Measured, all under `unbounded_execution`, all ending only because the fixture
ran out of turns:

| Probe | Variation | Planner calls before the scripted finish |
| --- | --- | --- |
| A1 | the same two steps, reordered | 7, no stall |
| A2 | one trailing space in one step | 6, no stall |
| A3 | one Cyrillic `а` homoglyph in one step | 6, no stall |

The packet names paraphrase as a known limitation; whitespace, ordering and
homoglyphs are the cheaper end of the same axis and are not named. Against that:
comparing the *parsed* `steps` rather than the raw response is what made the fix
work on the live run at all — `measure-03_planner_proposals.json` shows the 7B
planner varied its JSON indentation and line breaks between semantically
identical plans, which a response-hash rule would have missed. That design
choice is correct and is now pinned by
`test_a_whitespace_only_difference_is_a_different_plan` plus its counterpart.

### F5 — CONFIRMED (low). A configured policy that grants zero tools is still reported as "no policy"

`_unavailable_summary` distinguishes "no policy" from "everything unavailable"
by whether `unavailable` is non-empty. A policy with `tools: []` is valid
(`ComputerPolicy.__post_init__` accepts an empty tuple) and produces
`available: []`, `unavailable: {}`, `enabled: False`:

```
C3 empty policy: Computer assistance needs an owner-configured computer policy.
```

That is the same conflation the packet fixed for the release-locked case, left
unfixed for the empty-grant case. Low severity: an owner who configured a policy
granting nothing is told to configure a policy, which is not wrong advice, only
imprecise about the cause. A `configured: true` flag on the capability payload
would settle both cases; the current two-way inference from `unavailable` will
keep producing this class.

### F6 — CONFIRMED (low). The new service test fails, rather than skips, without the optional `daedalus[computer]` extra

On a clean `uv pip install -e . pytest` venv (no `[computer]`):

```
FAILED tests/runtimes/test_computer_service.py::test_release_locked_tools_are_reported_unavailable_not_silently_dropped
    assert caps["enabled"] is True  ->  assert False is True
FAILED tests/runtimes/test_computer_service.py::test_unavailable_release_capability_refuses_before_lease_or_state
2 failed, 53 passed, 1 skipped in 73.07s
```

The mixed-policy half asserts `enabled is True` for `browser.read`, which
requires `importlib.util.find_spec("playwright")`. The second failure is
pre-existing and needs `cv2`, so the new test matches an existing repo
convention rather than introducing a pattern — but the acceptance-matrix row
"six new tests with the change: 6 passed" is host-conditional and should say so.
With the extra installed the row reproduces (56 passed, above).

### F7 — CONFIRMED as a latent hazard, not a leak (low). Unavailability reasons reach a persisted artifact verbatim

`_unavailable_summary` interpolates each reason into the final report `summary`,
which is stored as a canonical JSON artifact. Probe C4 shows the interpolation is
literal (a planted `C:\Users\someone\secret-token-AKIA1234` reaches the summary
unchanged). No live path produces such a string today: every branch of
`_release_unavailable_reason` returns a fixed constant, and the one dynamic
source, `WindowsOCR.availability()["reason"]`, returns one of three constants.
Recorded so a future host-derived reason is not added without a filter.

## Refuted attacks (the guard holds; each executed)

| # | Attack | Result |
| --- | --- | --- |
| R1 | a plan proposal after a finish proposal in the same run | unreachable; `finish` breaks the loop (1 planner call, `no_actions`) |
| R2 | a tool returning `ok: False` between plans | `blocked`, "no uncertain effect was repeated", `ledger.open_intents() == []` |
| R3 | the stall firing while the ledger has a pending intent | none pending: mission intent `COMPLETED`/closed, all three proposal intents `COMPLETED`, `open_intents() == []` |
| R4 | `mission_id` reuse against a stalled mission | returns the stored stalled report with `replayed: True`; **zero** new planner calls, no re-execution |
| R5 | proposal retention under the stall | all 3 proposals retained, `plan.revision == 3`, three `phase: plan` progress events emitted before the break (mutant M8 is caught) |
| R6 | a policy listing a tool twice, or a tool name not in `TOOL_SPECS` | refused at `ComputerPolicy.__post_init__`: "tools must be unique known computer tools". `capabilities()` can neither `KeyError` nor double-report |
| R7 | mixed policy (`enabled: True` with a non-empty `unavailable`) | never reaches `_unavailable_summary`; `/computer status` opens with "Computer assistance is configured." and still renders "Unavailable: file.read: …" |
| R8 | a plan step ending in a newline | refused by `_parse_proposal` before any counter: "plan requires 1-12 nonempty single-line steps of at most 240 characters" |
| R9 | locked tools leaking into the planner's context | `_prompt` serialises only `available_tools`; `unavailable` has no consumer in `daedalus/interfaces` or `apps/web/src` |
| R10 | the stall and the bounded `max_steps` coinciding | `max_steps=2`: `step_limit` at 2 calls. `max_steps=3`: `stalled` at 3. Deterministic, one terminal state, no ambiguity |
| R11 | leaked home paths, user names or credentials in the evidence directory | none. `<SCRATCH>` placeholders throughout; the only `token=` hits are the kill-switch `token='RUN'` and the prose "observation token" |

`/computer status` sentences, all three cases, as rendered:

```
mixed:     Computer assistance is configured. Use /computer followed by your task.
locked:    Computer assistance is configured, but every configured tool is unavailable on this host; see Unavailable below.
no policy: Computer assistance is unavailable until its owner policy is configured. Use /computer setup to create a separate local workspace.
```

## Verdict

Claim (A): **upheld**, with F5 (the empty-grant case remains conflated) and F2/M9
(the `/computer status` half was unpinned until this review).
Claim (B): **upheld as literally stated**, with F3 — the rule bounds a repeated
plan, not a non-progressing planner, so under `unbounded_execution` the kill
switch is still the only terminator for a planner that varies its output at all.
F1 is independent of both claims and is the finding a later reader is most
likely to trip over.

Nothing in the diff bypasses policy, adds an effect path, a second event store,
an artifact identity, a graph authority or a promotion path; nothing gives a
candidate access to its evaluator. The stall is a progress criterion evaluated
outside `ExecutionLimitPolicy`, so Revision 10 is untouched, as the packet says.

## Reproduction

```
cd .claude/worktrees/lane9-adversarial-stage13
uv venv .venv --python 3.13
uv pip install --python .venv/Scripts/python.exe -e ".[computer]" pytest
.venv/Scripts/python.exe -m pytest tests/test_ikarus_computer_loop.py \
    tests/test_ikarus_computer_loop_adversarial.py \
    tests/runtimes/test_computer_service.py \
    tests/runtimes/test_computer_service_files.py \
    tests/test_byte_pin_eol_durability.py -q
-> 78 passed, 7 xfailed in 73.14s
```

The 20-case probe and the mutation driver ran from a scratch copy outside the
repository (`git archive cfe8d34b | tar -x` into the session scratchpad, own
venv) and are not committed: they mutate `daedalus/` source, which this lane is
read-only on. The mutation table above records their complete output.

## Not verified

- No live host run. Every result here uses adapter doubles or the real policy
  objects; the packet's live Ollama/Playwright missions (`measure-02` … `05`)
  were **not** reproduced and are taken on the packet's word.
- The claimed wider run (417 passed, 1 failed, 855 s) was not repeated; only the
  focused suites plus the byte-pin durability module were executed.
- `docs/FOURFOLD_V2_EXECUTION_PLAN.md` and the three renamed work-packet
  headings in the commit were not reviewed.
- Whether the packet's `test_declining_queues_nothing` order-dependence is
  genuinely unattributed was not investigated.

Iron Plan: **ALIGNED** (verification of an existing packet; one new test file,
no production source change)

Iron Gate: **1**

Automatic merge/promotion: **forbidden**

# G1-IKARUS-48 — a campaign evaluator that runs the project's tests

Packet ID: `G1-IKARUS-48`
Active gate: Gate 1
Classification: `ALIGNED`
Owner: repository owner (standing merge authorization of 2026-09-10, `CLAUDE.md`)
Base revision: `a05f4b266471e09fbfcafd3302ee18e146c8d720`
Dependencies: G1-IKARUS-47 (the campaign door), G1-ARIADNE-10 (the leakage boundary)

## Primary acceptance claim

A campaign arm passes only when a **frozen, project-declared test command**,
run in the existing contained gate against an evaluation workspace built from
the pinned source revision plus that arm's candidate file, exits zero within a
declared timeout — and the candidate can neither choose the command nor change
what it asserts.

## Why this packet exists

The evaluator today is a SHA-256 comparison
(`daedalus/ariadne/campaign.py:86-91`): it checks that the candidate file equals
`before.replace(before_fragment, after_fragment)`. That proves the edit landed.
It proves nothing about whether the project still works, which is exactly why
this repository must not call the current campaign "self-improvement". This
packet replaces the verdict source, and nothing else.

## What this packet does not claim

- **Not improvement.** A green run says the declared tests still pass. Whether
  the change is an improvement is not measured, and no receipt says it is.
- **Not promotion.** Invariant 5 is untouched: a nomination stays a nomination
  and still needs a one-use `OwnerApproval` bound to the candidate.
- **Not a new sandbox.** The run uses the existing contained gate (Low-Integrity
  token plus Job Object on Windows, rootless OCI on Linux, refusal elsewhere).
  This packet adds no containment and claims none.
- **Not a research result.** Gate-3 obligations (frozen tasks, budget-equal
  baselines, seeds, uncertainty) are untouched.
- **Not a general test runner.** One command, one workspace, one timeout, no
  network grant, no dependency installation.

## The three properties that make it an evaluator rather than a formality

1. **The candidate cannot pick its judge.** The command and its timeout are
   caller-supplied, frozen into the `ExperimentSpec` before any arm runs, and
   recorded in every trial's evidence. They never come from the candidate tree.
2. **The candidate cannot weaken the judge.** The evaluation workspace is built
   from the pinned `source_revision` by `git archive`, and exactly one file —
   the campaign's declared target — is overwritten per arm. Every other byte,
   including every test, is the base revision's. A target path inside a declared
   test root is refused before the runner.
3. **A judge that cannot tell the difference is reported, not hidden.** The
   negative-control arm exists to fail. If the command passes on the negative
   control too, the evidence says the suite is blind to this file and the
   campaign nominates nothing.

## What the arms mean under a test-running evaluator

The exact-match evaluator and a test run disagree about the baseline, and the
difference is the point:

| arm | file content | exact-match verdict (today) | test-command verdict (this packet) |
| --- | --- | --- | --- |
| baseline | the base revision's bytes | **fails** (no `after` text) | **must pass** — otherwise the suite was already red and nothing can be attributed |
| negative-control | `before` plus a corrupting suffix | fails | **must fail** — otherwise the suite cannot see this file |
| repair | `before` replaced by `after` | passes | **must pass** |

Nomination therefore requires `baseline passed AND negative-control failed AND
repair passed`. Any other shape ends the campaign without a nomination and says
which arm broke the pattern.

## Scope

In scope:

- `daedalus/ariadne/campaign.py` — the evaluator mode, the workspace builder,
  the arm-shape rule, the evidence fields, the frozen components.
- `daedalus/runtimes/computer_ariadne.py` — passing the project's declared test
  command and timeout through the tool door.
- `daedalus/ariadne/__main__.py`, `daedalus/interfaces/http/web_api.py` — the
  same two arguments at the CLI and HTTP doors.
- `tests/` — the packet's acceptance matrix.

Forbidden paths: `daedalus/spine/**`, `daedalus/kernel/policy/**`,
`docs/IKARUS_ARIADNE_MASTER_PLAN.md`, the amendment chain, `AGENTS.md`.
No new entrypoint, no new event store, no change to containment.

## Contracts and behavior

- `run_campaign(..., evaluator=...)` gains one frozen argument. Its default is
  the existing exact-match evaluator, so no existing caller changes behavior.
- The test evaluator is described by an immutable record: the argv tuple, the
  working directory relative to the workspace, the timeout, and the digest of
  all three. That digest replaces `EVALUATOR_SHA256` in the spec's frozen
  components for this mode.
- The evaluation workspace is built per arm from `git archive <source_revision>`
  and removed after the arm. Peak disk is one tree; the receipt, not the
  workspace, is the evidence.
- The trial observation records the command digest, the exit code, wall time,
  containment, and a **bounded, gated** excerpt of the output. Test output can
  carry host paths, so it goes through the same redaction the observation
  adapter uses, and the excerpt is capped.
- Budgets: the arm's `ResourceBudget.max_wall_time_s` becomes the test timeout,
  identical for all three arms, and the outer lease and the spec expiry are
  widened to fit three arms plus workspace construction.

## Acceptance matrix

Deterministic tests, all offline:

1. the default is unchanged: an existing call runs the exact-match evaluator and
   produces the same receipt shape;
2. a green fixture project nominates: baseline passes, negative control fails,
   repair passes;
3. a suite blind to the target file (its tests never import it) does NOT
   nominate, and the receipt says the negative control passed;
4. a suite that is already red does NOT nominate, and the receipt says the
   baseline failed;
5. the target path inside a declared test root is refused before the runner;
6. the workspace's test files equal the base revision's after the overlay;
7. the command comes from the caller, never from the candidate tree: a candidate
   that writes a `conftest.py` or a `pytest.ini` cannot change what runs
   (it cannot: only one file is overwritten, and the test asserts the digest of
   every other file);
8. a timeout is a failure with `timed_out` recorded, not a crash;
9. the output excerpt is bounded and carries no host path;
10. cancellation through the kill switch stops between arms;
11. refusal tests: unknown mode, empty argv, an argv naming an absolute path,
    a timeout outside the allowed range.

Plus a real end-to-end run against a scratch subject, recorded as evidence.

## Migration and rollback

Rollback is reverting the packet's commits. No stored artifact changes shape:
receipts written by the exact-match evaluator keep their fields, and the new
fields are additive. A campaign started under one evaluator never switches mode
mid-run, because the mode is frozen in the spec.

## Measured before implementation (baseline, 2026-09-10)

- The contained gate runs a real test command and separates pass from fail:
  `python -I -S -m unittest discover` on a green tree passes and on a broken
  tree fails; `python -m pytest` reading pytest from the parent environment
  behaves the same while the tree itself is Low-Integrity.
- A timeout returns `passed=False` after the budget with the terminated exit
  code, so the timeout path is already the gate's.
- `git archive` plus in-process extraction of this repository's pinned revision:
  4.5 s, 6371 files, 284 MiB, and byte-identical across two runs.
- A bounded pytest selection inside that extracted tree: 2.25 s, 48 passed.
- **Negative evidence retained:** the gate's "exit zero with empty output is not
  a pass" rule is inert on this host — the launcher always writes
  `warning: Making stdin inheritable failed` to the child's output, so the
  output is never empty. This evaluator therefore does not rely on that rule; it
  requires the exit code and records the excerpt. Reported to the kernel owners
  on the coordination board.

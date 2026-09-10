# G1-IKARUS-48 — a campaign evaluator that runs the project's tests

Packet ID: `G1-IKARUS-48`
Artifact role: `primary`
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
- **Not a new sandbox, and the existing one is narrower than it sounds.** The
  run uses the existing contained gate (Low-Integrity token plus Job Object on
  Windows, rootless OCI on Linux, refusal elsewhere). Its environment is a
  DENYLIST of three prefixes, not an allowlist, and it has no network fence.
  Measured by Cerberus on 2026-09-10: a candidate that prints its environment
  sees the operator's provider API key, and a socket to a public address
  connects. The approval secret is scrubbed; nothing else is. This packet does
  not fix that — it belongs to the kernel owners — but it is what makes it
  reachable from candidate-authored code, so: the command's output is no longer
  retained at all (it carried a live key into content-addressed storage), and
  every trial observation states `child_environment: inherited-except-denylist`
  and `child_network: unrestricted` instead of implying a fence.
- **Not a research result.** Gate-3 obligations (frozen tasks, budget-equal
  baselines, seeds, uncertainty) are untouched.
- **Not a general test runner.** One command, one workspace, one timeout, no
  network grant, no dependency installation.

## The four properties that make it an evaluator rather than a formality

1. **The candidate cannot pick its judge.** The command and its timeout are
   caller-supplied, frozen into the `ExperimentSpec` before any arm runs, and
   recorded in every trial's evidence. They never come from the candidate tree.
2. **The candidate cannot rewrite the test files or the session
   configuration.** The evaluation workspace is built from the pinned
   `source_revision` by `git archive`, and exactly one file — the campaign's
   declared target — is overwritten per arm. A target inside a declared test
   root is refused, and so is one whose NAME configures a session
   (`conftest.py` at any depth, `pytest.ini`, `pyproject.toml`, `setup.cfg`,
   `setup.py`, `tox.ini`, `sitecustomize.py`, `usercustomize.py`, `*.pth`).
   **It is not true that the overwritten file cannot influence the run**, and
   the first version of this packet claimed it was: the file must be one the
   suite exercises, or the negative control could never fail. Cerberus round 1
   proved the difference by targeting `conftest.py` with a collection hook that
   skipped every item — the arms read green, red, green and the campaign
   nominated a candidate whose winning arm ran zero assertions.
3. **An exit code is not a verdict.** The campaign appends its own JUnit
   report to the command and reads the counts: a trial passes only when tests
   were actually EXECUTED (`tests` minus `skipped` above zero) with no failures
   and no errors, and the repair arm must not execute fewer tests than the
   baseline did. A suite that was switched off cannot pass any more. The report
   is hostile input — a candidate influenced the process that wrote it — so it
   is size-bounded and a doctype or entity declaration is refused before parsing.

4. **A judge that cannot tell the difference is reported, not hidden.** The
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
  timeout, the declared test roots, and their digest. That digest replaces
  `EVALUATOR_SHA256` in the spec's frozen components for this mode. It carries
  no working directory: the kernel's command gate requires `gate_cwd="."` and
  runs at the workspace root, so offering one would be a promise the kernel
  refuses.
- The evaluation workspace is built per arm from `git archive <source_revision>`
  and removed after the arm, with `workspace_removed` recorded. Peak disk is one
  tree; the receipt, not the workspace, is the evidence. The first version of
  this packet claimed the removal before implementing it: three trees of this
  repository are about 852 MiB per campaign, retained under the user's home.
- The trial observation records the command digest, the exit code, wall time,
  containment, the report counts, and the digest of the output. It does **not**
  record the output itself. The first version stored a bounded excerpt and
  claimed it was redacted; no redaction existed, and the excerpt carried the
  operator's API key into content-addressed storage.
- The campaign's identity binds its judge. The evaluator digest is part of the
  operation digest, so a replay of the same id and edit under a different
  evaluator is a different campaign. Without that, the permissive judge's
  nomination answered the strict judge's request.
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
7. a target that configures the session is refused by name at any depth, and a
   run in which nothing executed cannot pass;
8. a timeout is a failure with `timed_out` recorded, not a crash;
9. the output is not retained at all, and the observation states the child's
    environment and network reach rather than implying a fence;
10. cancellation through the kill switch stops between arms;
11. refusal tests: unknown mode, empty argv, an argv naming an absolute path,
    a timeout outside the allowed range.

Plus a real end-to-end run against a scratch subject, recorded as evidence.

## Migration and rollback

Rollback is reverting the packet's commits. No stored artifact changes shape:
receipts written by the exact-match evaluator keep their fields, and the new
fields are additive. A campaign started under one evaluator never switches mode
mid-run, because the mode is frozen in the spec.

## Evidence, expected failures and review

Evidence: `tests/test_ariadne_test_evaluator.py` (13 tests, including the
end-to-end campaigns on real fixture repositories and the pinned reproduction of
the round-1 attack); the Ariadne, campaign-door and contract suites for
regression; the measurements recorded above and in the review-round section.

Expected failures, retained rather than hidden: a suite blind to the target
file, a suite that is already red, a target that configures the session, a
report that declares an entity, and a run in which nothing executed. Each has a
named refusal and a test.

Review: Cerberus round 1 blocked this packet with two CRITICAL findings, both
introduced by it, and both are repaired above. The doors that would let a
planner or an HTTP caller reach this evaluator are deliberately still unbuilt.

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

## Review round 1 (2026-09-10, `e387fcfd`)

**Cerberus: `block`, two CRITICAL, both introduced by this packet.**

CRITICAL 2 was the one that made the evidence a lie. A candidate whose target
was `conftest.py` — outside every declared test root — installed a collection
hook that skipped every item. The arms read baseline-passed, control-failed,
repair-passed, the arm-shape rule held perfectly, and the campaign nominated a
candidate whose winning arm ran **zero assertions**. Two repairs, because one is
not enough: the session-configuring file names are refused as targets, and the
verdict now reads a JUnit report the campaign appends itself, requiring that
tests actually executed and that the repair arm did not shrink the suite.

CRITICAL 1: the retained observation carried the operator's API key, because the
contained child inherits the environment and a candidate can print it. Cerberus
also opened a socket from inside the "contained" child. The environment denylist
and the missing network fence are pre-existing kernel properties and not this
packet's to fix, but this packet is what makes them reachable from
candidate-authored code. The output is no longer retained, and the reach is
stated in every observation.

Also repaired: the campaign identity now binds the evaluator digest (a replay
returned the other judge's receipt); the evaluation workspace is removed after
each arm; the interpreter provenance is verified on replay, not only recorded.
Still open and named rather than claimed away: the doors at
`daedalus/runtimes/computer_ariadne.py`, `daedalus/ariadne/__main__.py` and
`daedalus/interfaces/http/web_api.py` are **not built**, so no planner and no
HTTP caller can reach this evaluator yet. That is the largest mitigating fact
today and the packet no longer reads as if those doors existed.

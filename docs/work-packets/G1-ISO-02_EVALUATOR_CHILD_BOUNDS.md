# G1-ISO-02 — the evaluator that decides the gate gets the same bounds

Packet ID: `G1-ISO-02`
Active gate: Gate 1
Classification: `ALIGNED`
Owner: repository owner
Base revision: `5ac06193` (stacked on G1-ISO-01, green and adversarially reviewed)
Branch: `packet/g1-iso-02`

## 1. Why this packet exists

The independent adversarial review of G1-ISO-01 returned **NARROWED**: the
behavior probe was hardened, but `checks.pytest_check` — *the evaluator whose
verdict IS the attempt gate* — was left strictly weaker. It is called on the
candidate at `gate1.py:464` (data/knowledge gate) and `gate1.py:1080`
(composed candidate).

## 2. Two defects, both measured before the change

### 2.1 The candidate's suite was handed the verifier's environment

`env = dict(os.environ)`. The review read a planted credential out of it from
inside this gate, and used the inherited `PYTHONPATH` to reach the evaluator's
own package in two lines of candidate code.

### 2.2 `timeout_s` was not an upper bound

`capture_output=True` means PIPEs. **The candidate writes the test file this
gate runs**, so it can ask pytest for `capfd`, call `capfd.disabled()`, and
hand a spawned descendant the evaluator's real stdout handle.

```text
declared timeout: 3.0s
actual wall     : 45.6s
VERDICT         : DEFEATED - not an upper bound
```

**A negative result is kept rather than deleted.** The first version of this
test used a plain `subprocess.Popen` inside the pytest test and it **passed**
against the broken code — pytest's own capture layer redirects fd 1 to a temp
file, so the descendant inherited that, not the evaluator's pipe. Only the
`capfd.disabled()` variant reaches the defect.

## 3. Decision

- environment: an explicit allowlist, `checks.EVALUATOR_CHILD_ENV_KEYS`, via
  `checks.evaluator_child_env()`. **One definition**, imported by
  `runner._behavior` too.
- transcript: `stdout` to a file in the system temp directory (never under the
  judged tree, which `_post_gate_artifact_stable` would refuse),
  `stderr=STDOUT`, `stdin=DEVNULL`.

## 4. Round two — the second adversarial review, and what it refuted

A second independent verifier attacked `5eda3aba`. **The two fixes held
against every executed attack**; the defects it found were in the claims made
*around* them, one of which was false.

### 4.1 BLOCKING — I asserted a limitation that does not exist

Three artifacts said a change to `daedalus/spine/envelope.py` was invisible to
the bundle tripwire: this document, the commit message, and a test named
`test_the_bundle_does_not_cover_what_the_evaluators_import`.

**It is false.** `bundle.import_closure` walks every in-repo module reachable
from the six roots and `bundle_digest_from_body` folds that digest into the
identity. Re-measured independently on this tree:

```text
closure size           : 198
envelope.py in closure : True
EVALUATOR_MODULES      : 6
```

End-to-end, appending one comment to `envelope.py` during a live run makes the
receipt carry *"an evaluator changed while the slice was running"*.

Worse than the wrong claim: the test that "pinned" it asserted
`"envelope.py" not in EVALUATOR_MODULES` and `len(EVALUATOR_MODULES) == 6` —
both true, neither the stated proposition. A **green test documenting a false
fact** is what `AGENTS.md` calls an unverifiable claim, and it would have told
the next engineer that closing a closed gap was outstanding work.

Replaced by `test_the_bundle_digest_moves_when_any_judging_module_changes`,
which mutates three modules — one declared root, one reachable *only* through
the closure — and requires the digest to move, plus
`test_the_closure_reaches_past_the_declared_roots`.

### 4.2 The allowlist was too narrow, and failed silently

Without a home variable, win32 `os.path.expanduser("~")` returns the **literal**
`~` rather than raising. A target suite doing
`Path(expanduser("~/.cache/x")).mkdir(parents=True)` then creates a directory
named `~` inside the judged tree, and
`kernel.attempt_execution._post_gate_artifact_stable` refuses the **green**
verdict over the untracked file. POSIX falls back to `pwd`; win32-only.

Added `USERPROFILE`, `HOME`, `HOMEDRIVE`, `HOMEPATH`, `LC_CTYPE`.

### 4.3 The tests pinned the allowlist's ceiling and never its floor

Mutations that **nothing** caught across all 135 ignition tests: dropping
`PATH`; dropping `TEMP`/`TMP`/`TMPDIR`; dropping `stderr=STDOUT`; dropping
`stdin=DEVNULL`. Narrowing an allowlist breaks other people's boxes exactly as
silently as widening it leaks. `EVALUATOR_CHILD_ENV_REQUIRED` plus four new
tests close all four.

### 4.4 A claim of mine was vacuous

`test_a_timed_out_suite_still_carries_its_output` asserted only
`"timed out" in report.output` — it would have passed with the transcript
dropped entirely, which is what actually happens on the ordinary path: pytest
buffers test output in its own capture and writes it at report time, so a
killed run has flushed nothing. Renamed to `test_a_timed_out_suite_names_its_bound`
and now asserts the half that is true (output flushed *outside* pytest's
capture does survive).

### 4.5 A regression the change accidentally FIXED

Reimplementing the old body beside the new one over eight scenarios showed the
previous `capture_output=True` path **crashed the evaluator** on
candidate-controlled non-UTF-8 bytes (`IndexError` out of subprocess's reader
thread) and mojibaked real UTF-8. The file transcript decodes with
`errors="replace"`. One narrow true regression: cp1252-legible-but-not-UTF-8
bytes now become `U+FFFD`.

## 5. What this does NOT fix, named rather than implied

1. **The write capability.** The child reaches this repository through
   `site-packages` at the operator's privilege level. Measured detail worth
   keeping: it resolves to the **primary checkout**, not the worktree the gate
   runs from — so under a worktree layout the bundle hashes one tree while the
   child can write another. Needs containment or filesystem permissions.
2. **The transcript is addressable by path.** `TEMP` must be in the allowlist,
   so a candidate can glob `%TEMP%/daedalus-pytest-*/pytest.log` and append to
   it. Measured: forged text reaches `report.output` and the stored evidence
   blob. It does **not** reach `passed`, which comes from the returncode — so
   the verdict is not flippable, but the transcript a human reads for a refused
   candidate is candidate-influenced. A PIPE was not addressable this way; this
   surface is created by this packet.
3. **Every timed-out gate leaks its temp directory permanently**
   (`ignore_cleanup_errors=True` is what stops a descendant's inherited handle
   turning cleanup into a win32 `PermissionError`). Measured 42 → 43 → 44.
4. **Orphaned descendants** still outlive the gate.
5. **Nonce forgery costs four lines, not frame walking.** `_nonce` and `_out`
   are ordinary `__main__` attributes under `python -I -c`. The G1-ISO-01
   docstring overstated the cost and is corrected. A full slice still cannot be
   won this way (composed `pytest_check` and `_old_symbol_occurrences` both go
   red), but the residue is a fabricated `gate1-behavior` EvidenceItem carrying
   `assurance="deterministic"`.
6. ~~**CI does not run this packet's acceptance matrix.**~~ **ADDRESSED**, and
   it was worse than the review found: the workflow triggered on pull requests
   to `g0/sealed-promotion-runtime-sandbox` and pushes to `g1/ignition-slice`,
   and **neither branch exists on origin**. The whole Gate-1 ignition job was
   inert except via `workflow_dispatch`, and its test list ran the 2026-08-17
   rehearsal rather than the slice. Now triggers on PRs to `main` and runs the
   measured set. Measured CI-safe first, because adding a suite that needs
   operator-local state turns everyone else's build red for a reason that is
   not theirs: with `DAEDALUS_KILLSWITCH` pointed at a nonexistent path and
   `runs/spine/spine.sqlite3` moved aside — the two things a fresh box lacks —
   the full intended set is **189 passed, 1 skipped**.
   The POSIX behaviour of the allowlist remains **UNVERIFIED** until that job
   runs green on `ubuntu-latest`; the first green run IS the measurement.
7. **`bundle.py`'s `import_closure` docstring still says "124 modules"**;
   measured 198. Out of this packet's declared scope (`bundle.py` is not an
   in-scope path) and left as a one-line follow-up rather than silently widened
   into.

## 6. Acceptance

| # | Claim | Test | Failed before |
| --- | --- | --- | --- |
| 1 | no credential, no `PYTHONPATH` reaches the child | `test_pytest_child_does_not_inherit_the_verifier_environment` | yes |
| 2 | the child still gets what it cannot work without | `test_the_child_receives_the_variables_it_cannot_work_without` | yes (M9/M10) |
| 3 | a home-relative suite does not pollute the judged tree | `test_a_home_relative_suite_does_not_pollute_the_judged_tree` | yes |
| 4 | `timeout_s` is an upper bound under capture escape | `test_the_pytest_timeout_is_an_upper_bound` | yes (45.8 s vs 3.0 s) |
| 5 | green suite passes and reports | `test_a_normal_suite_still_passes_and_still_reports` | no |
| 6 | red suite carries its failure text | `test_a_failing_suite_still_reports_its_failure` | no |
| 7 | stderr reaches the transcript | `test_stderr_reaches_the_transcript` | yes (M7) |
| 8 | the child cannot block on inherited stdin | `test_the_child_cannot_block_on_inherited_stdin` | yes (M4) |
| 9 | a timed-out run names its bound and keeps flushed output | `test_a_timed_out_suite_names_its_bound` | no |
| 10 | the bundle digest moves for any judging module | `test_the_bundle_digest_moves_when_any_judging_module_changes` | **replaces a false test** |
| 11 | the closure reaches past the declared roots | `test_the_closure_reaches_past_the_declared_roots` | n/a |

## 7. Rollback

Revert the commits on `packet/g1-iso-02`. No schema, artifact, ledger, receipt
contract or promotion path changes shape. The evaluator bundle digest moves
because `checks.py` and `runner.py` move, so the first run after a revert is
legitimately not a replay — the same two-run cost as adopting it.

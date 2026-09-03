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

```
E   AssertionError: the candidate's own conformance suite was handed a
    credential held by the process that judges it
E   assert 'DAEDALUS_TEST_FAKE_SECRET' not in {...109 vars...}
```

### 2.2 `timeout_s` was not an upper bound

`capture_output=True` means PIPEs. **The candidate writes the test file this
gate runs**, so it can ask pytest for `capfd`, call `capfd.disabled()`, and
hand a spawned descendant the evaluator's real stdout handle. `communicate()`
then waits for that descendant instead of the child it killed.

```
declared timeout: 3.0s
actual wall     : 45.6s
VERDICT         : DEFEATED - not an upper bound
```

**A negative result is kept rather than deleted.** The first version of this
test used a plain `subprocess.Popen` inside the pytest test and it **passed**
against the broken code — pytest's own capture layer redirects fd 1 to a temp
file, so the descendant inherited that, not the evaluator's pipe. Only the
`capfd.disabled()` variant reaches the defect. Both are recorded in the test
module's docstring so nobody re-derives the dead end.

## 3. Decision

- environment: an explicit allowlist, `checks.EVALUATOR_CHILD_ENV_KEYS`, via
  `checks.evaluator_child_env()`. **One definition**, imported by
  `runner._behavior` too — two allowlists for one concept would drift apart
  exactly once and then stay wrong.
- transcript: `stdout` to a file in the system temp directory (never under the
  judged tree, which `_post_gate_artifact_stable` would refuse),
  `stderr=STDOUT`, `stdin=DEVNULL`. No pipe means nothing a descendant
  inherits is something this process must drain.
- a timed-out run still carries its partial transcript. A refusal that drops
  what the suite already said is a refusal nobody can act on.

## 4. What this does NOT fix, stated rather than implied

1. **The write capability.** The review wrote a file into the evaluator's own
   package from inside this child. Neither an env allowlist nor a flag closes
   that: the child runs at the operator's privilege level and reaches this
   repository through `site-packages`. Closing it needs containment or
   filesystem permissions.
2. **Orphaned descendants** still outlive the gate. The parent is bounded now;
   the descendant is not.
3. **The bundle tripwire's blind spot.** `gate1` re-reads the evaluator bundle
   after the run and turns a difference into a blocker — real detection, and
   `test_the_evaluator_bundle_notices_a_changed_evaluator` pins it. But
   `EVALUATOR_MODULES` is an explicit six-file list, and those six import many
   others (`daedalus/spine/envelope.py` supplies `canonical_sha` to both
   `checks` and `runner`). A change there moves no digest.
   `test_the_bundle_does_not_cover_what_the_evaluators_import` **expects** this
   gap, so closing it is a deliberate decision against a failing test rather
   than a silent one.

## 5. Acceptance

| # | Claim | Test | Failed before |
| --- | --- | --- | --- |
| 1 | the candidate's suite gets no credential and no `PYTHONPATH` | `test_pytest_child_does_not_inherit_the_verifier_environment` | yes |
| 2 | `timeout_s` is an upper bound under capture escape | `test_the_pytest_timeout_is_an_upper_bound` | yes (45.8 s vs 3.0 s) |
| 3 | a green suite still passes and still reports | `test_a_normal_suite_still_passes_and_still_reports` | no |
| 4 | a red suite still carries its failure text | `test_a_failing_suite_still_reports_its_failure` | no |
| 5 | a timed-out suite still carries its output | `test_a_timed_out_suite_still_carries_its_output` | no |
| 6 | the bundle tripwire fires on a changed evaluator | `test_the_evaluator_bundle_notices_a_changed_evaluator` | no |
| 7 | the tripwire's blind spot is pinned | `test_the_bundle_does_not_cover_what_the_evaluators_import` | no |

Integration: `tests/ignition/ + test_ignition_gate1 + bundle` **143 passed**;
`python -m daedalus.ignition` ×3 → runs 2 and 3 exit 0 with `blockers: []`,
run 3 `replay_demonstrated: true`; slice wall time 14/15/14 s, unchanged.

## 6. Rollback

Revert the single commit on `packet/g1-iso-02`. No schema, artifact, ledger,
receipt contract or promotion path changes shape. The evaluator bundle digest
moves because `checks.py` and `runner.py` move, so the first run after a revert
is legitimately not a replay — the same two-run cost as adopting it.

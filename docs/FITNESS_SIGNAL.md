# The fitness signal

*What would have to be true before a number is allowed to PROMOTE work.*

Status: **prototype + argument, measured on this repository 2026-07-29.** The
tool is `tools/mutation_score.py`; its own tests are
`tests/test_mutation_score.py`. Nothing here is wired to any promotion path. It
promotes nothing.

Headline numbers, both over **green** baselines:
`daedalus/sensitivity.py` **75.8 %** (62 seeded, 15 survived);
`daedalus/interfaces/cli/token_monitor.py` **45.0 %** (20 seeded, 11 survived).
Eight of the fifteen survivors in the safety core sit in one function whose own
docstring calls itself *"the enforcement point"* — and which **no test in this
repository calls at all**.

Do not read those numbers as trust. Three of the five falsification criteria in
§7 are green, one cannot be measured yet, and **F1 — the one that decides the
question — is now partially measured, on the `worktree.py` arm, and it
confirmed the predicted blind spot rather than refuting it.** See
[Falsification](#7-falsification-under-what-measurement-would-this-signal-also-be-untrustworthy)
before wiring this to anything.

---

## 1. The problem, stated as measurement rather than opinion

The self-improvement loop is closed: pick → attempt → record → reap → re-pick,
demonstrated on this repository. The missing piece is not autonomy machinery.
It is a **fitness signal that can be trusted to promote**.

"Tests pass" is not that signal, and this repo has the receipts:

| Measured event | What was green while it happened |
| --- | --- |
| A repository deletion, an out-of-tree delete reported as success, seven gate bypasses — three live escapes in one day | three fully green test suites |
| A task queue silently dropped tasks when two arrived in the same second | 1756 unit tests |
| An A/B run produced two implementations that **contained no tests at all** | the gate, which was `tsc --noEmit && vite build` |
| 18 of 61 mutants in a security-critical file survived — guards that survive their own deletion | that file's suite |

These four have exactly one shape in common, and it is not "the tests were bad".
It is: **the check could not fail.** A compile gate cannot fail for a
wrong-but-compiling implementation. A unit suite that never enqueues twice in
one second cannot fail when the queue drops the second one. A guard nobody
drives cannot fail when it is deleted.

So the question a promotion gate has to answer is not *"did it pass?"* It is
*"is this evidence?"* — and those are different questions with different
measurements.

## 2. The property this repo has already been buying, twice, by hand

Both of the following exist in the tree already, written independently, for
different subjects, in different languages:

- **`runs/ab/oracle_check.py`** — seeds exactly one defect into a real A/B arm's
  TypeScript and requires *the specific conformance test that covers that rule*
  to go red. The committed receipt (`runs/ab/receipts/oracle_check.json`) shows
  **11 seeded, 11 caught, 0 survived — over a baseline that already had 2
  failing tests**, which is exactly why the rule is "*newly* red", not "red".
  Written because Codex's ruling after the first A/B was *"fix the gate first —
  a repair loop is meaningless when its oracle accepts wrong implementations."*
- **`tools/self_test.py`** — seeds one defect into a **disposable clone** of
  this repository and requires the named acceptance check to report FAIL.
  17 mutations across 15 checks, and it names the 2 checks it deliberately does
  *not* mutate rather than letting a reader discover the gap by counting.

They are the same idea reached twice: **a check is trusted not because it passes
but because a known-bad input makes it fail, verified by actually breaking one.**
That idea has a name — mutation testing — and the two files above are two
hand-rolled instances of it.

`tools/mutation_score.py` is the third instance *generalised*, not invented. It
carries over every invariant those two paid for, including the two that each
cost a round:

1. **Nothing touches the working repository.** One disposable snapshot per run.
2. **The baseline must be green.** `self_test.py`: *"A check that was already
   FAIL or UNAVAILABLE before the defect was seeded tells you nothing when it
   comes back red."* A red baseline makes the whole run `INCONCLUSIVE`, never a
   score.
3. **A mutation that does not apply proves nothing.** `self_test.py`'s first run
   scored five "SURVIVED" results that were every one of them a defect in the
   *mutation* — a no-op edit, a patch to dead code, a patch to the wrong class.
   Here, a mutant that fails to anchor, changes no bytes, or does not compile is
   `NOT_APPLICABLE`: never a survivor, never hidden.
4. **The delta is what counts, and a named test is stronger than any test.**
   `oracle_check.py`'s rule. A mutant is `CAUGHT` when a test goes red that was
   green at baseline; with `expect_test`, it must be *the* test that claims the
   rule. An unrelated test tripping over a mutant is detection by accident, not
   coverage.
5. **A survivor is the headline.** *An unfalsifiable rule is worse than a missing
   one, because it reads as covered.* Survivors are named with file and line;
   the process exits non-zero.

## 3. What the signal is

For a module `M`, a test selection `T`, and a set of seeded defects `D`:

> **mutation score** = killed / (killed + survived), over `D`, against `T`,
> where a mutant is *killed* iff a test that was green at baseline goes red.

`NOT_APPLICABLE` and `INCONCLUSIVE` mutants are excluded from **both** the
numerator and the denominator, and reported separately. Nothing scoreable
yields `None`, never 100%.

The generated defect population is five single-token operators, each chosen
because it corresponds to a defect class this repository has actually shipped:

| operator | seeds | the defect class |
| --- | --- | --- |
| `comparison` | `==`↔`!=`, `<`↔`>=`, `is`↔`is not`, `in`↔`not in` | an inverted or off-by-one boundary in a fence |
| `boolop` | `and`↔`or` | conditions that should have been joined the other way (seven gate bypasses) |
| `bool_const` | `True`↔`False` | a flag flipped to the permissive value |
| `drop_not` | `not x` → `x` | an inverted predicate — "allow" where "deny" was meant |
| `guard_never_fires` | the test of a pure guard → `False` | **the guard is deleted outright** — the operator behind "18 guards survive their own deletion" |

The tool also accepts hand-written find/replace mutations
(`Mutation.patch(...)`), which is exactly the shape `oracle_check.py` and
`self_test.py` use — so their tables are expressible here rather than being a
separate dialect.

## 4. What it measured on this repository

All numbers below are from `tools/mutation_score.py` on this tree, on
2026-07-29. Every run took its own snapshot; the working tree was not written
to. Reproduce with the command printed under each table.

### 4.1 A module with GOOD tests: `daedalus/sensitivity.py`

The fail-closed safety core — 27,798 bytes, imported by 11 test files, the
module that decides what leaves this machine. Scored against the eight
safety-focused suites that exercise it:

```bash
python tools/mutation_score.py --module daedalus/sensitivity.py \
  --tests tests/test_hardening.py tests/test_fence_anchoring.py \
          tests/test_safety_reachability.py tests/test_slice_egress_gate.py \
          tests/test_slice_secret_value_shape.py tests/test_host_predicate.py \
          tests/test_egress_lane_by_host.py tests/test_dctx_policy_egress.py
```

| | |
| --- | --- |
| baseline | **GREEN** — 258 tests, 0 failures, 29.4 s |
| seeded | **62** mutants |
| caught | **47** |
| **survived** | **15** |
| not applicable / inconclusive | 0 / 0 |
| **mutation score** | **75.8 %** |

Survivors by operator: `guard_never_fires` 5, `bool_const` 3, `boolop` 3,
`drop_not` 3, `comparison` 1.

**Eight of the fifteen survivors are in one function**, and it is not a
peripheral one. `read_inlined_context` (sensitivity.py:506–545) carries this
docstring:

> *"When `allow_sensitive` is False (untrusted external provider) sensitive
> files are skipped by both path and content — **this is the enforcement
> point**."*

Every one of these is undetectable by the suite above:

| line | mutant | what it does |
| --- | --- | --- |
| 510 | `allow_sensitive: bool = False` → `True` | **the fail-closed default becomes fail-open** |
| 525 | `not allow_sensitive` → `allow_sensitive` | the path-based sensitivity skip is inverted |
| 536 | `not allow_sensitive` → `allow_sensitive` | the content-based sensitivity skip is inverted |
| 525, 536 | `and` → `or` | either condition alone now suppresses the skip |
| 519 | `policy or DEFAULT_POLICY` → `and` | the policy fallback |
| 529 | `not candidate.is_absolute()` → `candidate.is_absolute()` | path resolution |
| 541 | `budget <= len(header)` → `>` | the truncation boundary |

The reason is checkable in one command and is worse than "weakly tested":
`read_inlined_context` is called by `daedalus/providers/ollama.py` and
`daedalus/providers/deepseek.py`, and **no test file anywhere in this
repository mentions it.** A `grep` for the name across the whole tree returns
two callers, the module itself, and two generated HTML maps. Zero tests.

The other seven survivors, adjudicated by hand (this adjudication is itself one
of the falsification criteria — see F3):

| line | mutant | verdict |
| --- | --- | --- |
| 301 | `if not c: raise …` → `if False:` | **REAL, and high severity.** The guard whose own message says a failed secret-floor pattern *"would be silently absent"*. Deleting it makes that silence happen, and nothing goes red. |
| 498, 499 | the per-project `policy.deny_substrings` check | **REAL.** The *generic* deny list one line above (491) is killed by `test_simulated_suffix_bypasses_deny`. The per-project one is not tested in this function. |
| 187 | `@dataclass(frozen=True)` → `frozen=False` | **REAL, low severity.** No test asserts `Policy` is immutable. |
| 411, 422, 424 | the three `lane_for_host` guards | **EQUIVALENT MUTANTS — not holes.** Each is masked by the next: with 411 deleted, `""` still fails 422; with 422 deleted, `ipaddress.ip_address("")` raises and returns `"untrusted"`; with 424 deleted, `127.0.0.1` and `::1` are still caught by the `is_loopback` check four lines below, and `"[::1]"` can never reach it because `urlsplit().hostname` strips brackets. |

Those last three are the point of the caveat, not an exception to it. The tool
called them survivors. Deciding they were equivalent took a human reading four
lines of context. **Measured equivalent-mutant rate on this sample: 3/15 =
20 %** (n=15, one adjudicator) — under the 30 % threshold in F3, but only just,
and the sample is small.

### 4.2 F5, the self-control, on real code

Mutant `guard_never_fires:daedalus/sensitivity.py:258` (the allow-exception
check in the fence) is killed by **exactly one** test in the whole selection:
`test_hardening.py::SensitivityPolicyTests::test_allow_exception_beats_deny_and_default_deny`.
Remove that one test and re-score the same two mutants on the same line:

| run | baseline | caught | survived | score |
| --- | --- | --- | --- | --- |
| full suite | GREEN, 20.5 s | 2 | 0 | **100.0 %** |
| `--drop-test test_allow_exception_beats_deny_and_default_deny` | GREEN, 18.9 s | 0 | **2** | **0.0 %** |

The baseline stays green in both runs — removing the test did not break the
suite, it removed the *evidence*, and the score moved from 100 % to 0 %
accordingly. That is the scorer being falsified in the direction that proves it
works. Had the score not moved, everything in §4.1 would be void.

### 4.3 A module with WEAK tests: `daedalus/interfaces/cli/token_monitor.py`

A module referenced by only two test files, one of which reaches it by
**mocking out the function under test**. Same tool, same rules, an evenly
spread 20 of its 47 mutants:

```bash
python tools/mutation_score.py --module daedalus/interfaces/cli/token_monitor.py \
  --tests tests/test_agent_env.py tests/test_hardening.py --sample 20
```

| | |
| --- | --- |
| baseline | **GREEN** — 0 failures, 29.5 s |
| seeded | **20** of 47 (deterministic even spread) |
| caught | **9** |
| **survived** | **11** |
| **mutation score** | **45.0 %** |

Named survivors that matter:

- **`should_checkpoint`, line 135** — `if summary["total_fresh_tokens"] >=
  fresh_threshold: return True, …` deleted outright, and nothing goes red. The
  *rate-limit* trigger one branch above (133) and the *cached* boundary one
  branch below (137) are both killed. **One of the three checkpoint triggers is
  undetectable while its two siblings are covered** — precisely the kind of gap
  a suite-level pass/fail cannot express.
- **`checkpoint_if_needed`, line 161** — `if triggered and previous.get(
  "trigger_key") != trigger_key:` → `or`. The duplicate-event suppression can
  be broken silently.
- **`watch`, line 186** — `reason != last_reason` → `==`. The de-duplication of
  checkpoint prints inverts, and nothing notices.
- **`_iter_project_logs`, lines 39–42** — the `project_dir.exists()` guard and
  the sort order. `test_hardening.py` reaches this module by
  `patch("daedalus.interfaces.cli.token_monitor._iter_project_logs", return_value=[log])` —
  it mocks the function away, so its body has no coverage at all. The mutation
  score says so; the green suite does not.

Hand-adjudicated equivalents in this batch: lines 179 and 183
(`print(..., flush=True)` → `False`, a buffering change with no observable
effect on the assertions) and probably 151 (`mkdir(parents=True)` where the
parent always exists). **~3/11 ≈ 27 % equivalent** — again near the F3 line.

### 4.4 The contrast, which is the whole point

| module | suite | baseline | mutation score |
| --- | --- | --- | --- |
| `daedalus/sensitivity.py` | 8 safety suites, 258 tests | GREEN | **75.8 %** |
| `daedalus/interfaces/cli/token_monitor.py` | 2 suites | GREEN | **45.0 %** |

Both baselines are green. "Tests pass" assigns these two modules the same
value. The mutation score separates them by 31 points and, more usefully,
hands back a list of file:line pairs where the difference lives. That
separation is the entire claim being made for this signal — and §4.1 shows it
is a claim about the *tests*, since the worst hole it found
(`read_inlined_context`) is a function with no test anywhere in the tree.

### 4.5 F4, stability — measured

The same command run twice against `daedalus/sensitivity.py`
(`--sample 10`, lines 37 / 199 / 261 / 280 / 410 / 424 / 470 / 475 / 497 / 519):

| | run A | run B |
| --- | --- | --- |
| mutant set selected | identical (10) | identical (10) |
| caught / survived | 8 / 2 | 8 / 2 |
| mutation score | 80.0 % | 80.0 % |
| **status disagreements** | **0** | |
| **killing-test-set disagreements** | **0** | |
| baseline wall time | 87.3 s | 70.3 s |

Not one mutant changed status, and not one changed *which* test killed it. The
wall times differ by 20 % because the machine was under load — which is a
reminder that **wall time from this tool is not a measurement**, only the
statuses are. F4 is therefore *measured and passing on n=10*, which is a much
weaker statement than "this suite is deterministic": it is one repetition of a
ten-mutant subset of one module. F4 should be re-run at full width before any
number here is used to decide anything.

## 5. The argument: should mutation survival be a first-class fitness input?

### For — and the case is strong

1. **It is the only candidate that measures the failure mode this repo actually
   has.** All four documented escapes were checks that could not fail. Mutation
   survival is a direct measurement of "can this check fail". No other proposed
   signal measures that at all.
2. **It grades the evidence, not the artifact.** A promotion gate needs to
   answer *"is this evidence?"*. Coverage answers "was this line executed"
   (which the 61-mutant file passed while 18 guards were undetectable). A test
   count answers nothing. Mutation survival is the only one of the three that
   asks whether the tests can distinguish right from wrong.
3. **It is per-item, and this repo already knows why that matters.**
   `harness.run_gate` compares per task, never on a mean, *"because a mean hides
   one task collapsing while another improves."* A survivor list is per-item by
   construction: it names the line.
4. **It is cheap to falsify, which almost nothing else here is.** `--drop-test`
   removes a covering test and the score must move. One command. A signal with a
   one-command self-check is a different kind of object from a signal you have to
   trust.
5. **It would have caught the specific A/B failure that motivated all of this.**
   Two implementations that passed a gate while containing **no tests at all**
   score `None` — not 100%, not "pass". There is nothing to kill a mutant with.

### Against — and these are not quibbles

1. **Equivalent mutants are undecidable.** A survivor may be a mutant that
   changes no observable behaviour (`> 0` → `>= 0` on a value that is never
   zero). The tool cannot tell that from a real hole. **Every survivor is a
   question for a human, never a verdict.** A gate that treats survivors as
   defects will be wrong some fraction of the time and cannot know which.
2. **Goodhart, and it is the *same disease one level up*.** The moment mutation
   score gates promotion, the cheapest way to raise it is to assert on
   representation instead of behaviour — pin `repr()`, pin internal dict shapes,
   pin the code to what the code already is. That kills mutants beautifully and
   certifies nothing. This is precisely the pathology of the `tsc --noEmit`
   gate, moved up one level of sophistication.
3. **The operator population is not the defect population — and this is the
   sharpest objection.** The three live escapes in one day were a repository
   deletion, an out-of-tree delete reported as success, and gate bypasses. Those
   are **missing-guard and wrong-architecture defects.** You cannot mutate a line
   that does not exist. A module can score 100% and still delete your
   repository. *Mutation score would not have prevented the escape that
   motivated the sprint that discovered mutation score.*
4. **Cost is real, and measured here, not estimated.** `sensitivity.py`: 62
   mutants against 258 tests = **17.2 minutes** of test-run time (16.6 s per
   mutant). `token_monitor.py`: 20 mutants against a heavier selection =
   **10.8 minutes** (32.5 s per mutant). That is *two modules of forty-nine* in
   `daedalus/` alone, at partial width. Whole-repo mutation scoring is hours,
   and it cannot sit inside a per-attempt promotion loop at full width. This is
   the arithmetic that forces the diff-scoped form below.
5. **It sees only what the selection runs.** Score a module against a suite that
   never imports it and you get a truthful 0% that is not information about the
   module. The number is meaningless without its test selection printed beside
   it — which is why `render()` prints them together and why the JSON carries
   `tests` as a first-class field.

### The verdict

**Yes — as a first-class input, and specifically NOT as a scalar gate.**

The strong form, and the only one I would wire to a promotion path:

> **Diff-scoped mutation admission.** For a candidate diff, generate mutants
> *only on the lines the candidate changed or added*, and require each one to be
> killed by the selection the candidate ships. Report whole-module scores as
> information; gate on the diff.

Why this form and not "mutation score ≥ X%":

- It **matches the demonstrated failure exactly.** Two arms shipped no tests and
  passed. Under diff-scoped admission, a diff with no test that kills its own
  mutants is not admissible. That is a floor, and it is the floor that was
  missing.
- It is **affordable.** A diff touches tens of lines, not thousands. Minutes,
  not hours.
- It is **per-item, never a mean.** Same rule `run_gate` already enforces for
  recall: one mutant surviving is a named finding, not 1/62 of a percentage.
- It **cannot be farmed as easily**, because the mutants are chosen by the diff,
  not by the author.
- It is **honest about scope**: it certifies the *diff's tests*, and claims
  nothing about the module, the architecture, or the absence of a guard.

And the discipline that has to travel with it, or it becomes the next
`tsc --noEmit`:

- **Survivors are questions.** A survivor opens an adjudication, it does not
  auto-block. The adjudication outcome (real hole / equivalent mutant) is
  recorded, because the equivalent-mutant rate is itself one of the
  falsification criteria below.
- **It is a floor, never a ceiling.** Mutation admission passing means "the
  tests can distinguish *these* wrong implementations from this one". It does
  not mean the change is correct, safe, or wanted. The acceptance run
  (`tools/system_check.py`, falsified by `tools/self_test.py`) stays the thing
  that finds the defect classes mutation cannot represent — it found the queue
  drop in its first attempt while 1756 unit tests were green, and no mutation
  operator would have.
- **Never blend it into one number with anything else.** Same rule
  `harness.py` applies to label provenance: a blended score re-hides exactly the
  weakness the components exist to expose.

## 6. What this signal can and cannot certify

**It can certify, and only this:**

> For module `M`, against test selection `T`, at snapshot `S`: these `k` specific
> single-token defects are detected by a test that was green before them, and
> these `m` are not, and here are the `m` by file and line.

Note what that sentence is about. It is a statement about **the tests**. It is
not a statement about the code.

**It cannot certify:**

- That the code is correct. A 100% mutation score on a module that does the
  wrong thing correctly is 100%.
- That a survivor is a defect. Equivalent mutants are undecidable; a survivor is
  a question.
- That a defect class outside the five operators would be caught. Missing
  guards, absent features, wrong algorithms, races, resource leaks, deletion of
  a whole function, anything cross-module — none are in the population.
- Anything about code the selection never executes.
- Anything non-Python. `runs/ab/oracle_check.py` remains the instance for
  TypeScript.
- That the suite is deterministic. A flaky test can kill a mutant by luck; see
  the stability criterion below.
- That the numbers are comparable across time if the operator set, the test
  selection, or the sampling changes. All three are recorded in the JSON for
  exactly this reason.

## 7. Falsification: under what measurement would this signal ALSO be untrustworthy?

The point of this section is that the previous six do not earn trust. This one
is the only part that could.

Five criteria. Any one of them firing means mutation survival must not gate
promotion, and I am recording the predictions **before** running them so the
result cannot be reinterpreted afterwards.

### F1 — The escape test (decisive)

**Measurement.** Reconstruct the pre-fix state of the defects this repo has
already shipped: the `worktree.py` repository deletion, the out-of-tree delete
reported as success, the seven gate bypasses, and the `file_bridge.py` queue
collision (`if path.exists():` → the colliding-name overwrite that
`self_test.py` reseeds as `m_enqueue_collides`). Run diff-scoped mutation
admission against the suite as it stood at that commit.

**Falsifier.** If the signal is GREEN on a commit that shipped a live escape,
then it does not detect this repository's actual defect class.

**Prediction, recorded in advance: it will be green on at least the `worktree.py`
deletion, and probably on the gate bypasses.** Those defects are *missing
guards*, and no operator can mutate a line that is not there. If that prediction
holds, the result is not "the signal is useless" — it is the hard proof that the
signal is **necessary but not sufficient**, and that anyone treating it as
sufficient is repeating the `tsc --noEmit` mistake with better tooling. If it
were somehow green on the *queue collision* too — a defect that IS a
single-token guard — that would be far worse, and would kill the proposal.

**MEASURED, 2026-07-29, the `worktree.py` arm.** `1b629af` ("fix(kairos): close
three measured deletion paths in worktree cleanup") is the fix; its own message
records four adversarial review rounds, the first of which — "Round 1 shipped
with 29 green tests; the reviewer deleted the primary repository through it,
3/3" — is the repository-deletion escape this criterion is about. `1b629af`'s
sole parent, `b2de339` ("feat(kairos): add isolated candidate worktrees"), is
the commit that shipped it: at that commit `daedalus/kairos/worktree.py` has no
`_refuse_if_the_primary_checkout_moved` method, no allocation bookkeeping, no
reparse-point detection, and no identity check of any kind — `cleanup_worktree`
is nine lines, `git worktree remove --force` then a bare `shutil.rmtree`
fallback, and it opens with `path = Path(path).resolve()`, which *follows* a
junction before anything is checked. Confirmed textually: `grep -c
_refuse_if_the_primary_checkout_moved` against `b2de339`'s copy of the file
returns `0`.

Reproduced:

```bash
tmp=$(mktemp -d) && git archive b2de339 | tar -x -C "$tmp"
python tools/mutation_score.py --repo "$tmp" \
    --module daedalus/kairos/worktree.py --tests tests/test_worktree.py \
    --json f1_prefix_score.json
```

| | |
| --- | --- |
| baseline | GREEN — 9 tests (`tests/test_worktree.py` as of `b2de339`), 5.6 s |
| seeded | **8** mutants (the entire population `generate_mutations` finds in this 124-line, pre-fix file) |
| caught | 4 |
| **survived** | 4 |
| **mutation score** | **50.0 %** |

Not a clean 100 %, so the prediction as literally worded ("it will be green")
is not what ran. **The result confirms the underlying claim anyway, more
precisely than a flat green would have.** All 8 mutants are in code that has
nothing to do with the vulnerability: `_run_git`'s `cwd or self.repo_path`
(boolop), three `subprocess.run` boolean keyword arguments
(`capture_output`/`text`/`check`), `mkdir`'s `parents`/`exist_ok` flags, and the
two `git_error is not None` checks around the `shutil.rmtree` fallback. Zero of
the 8 — not one — touch worktree identity, reparse-point detection, or
checkout containment, because **no such code exists at this commit for an
operator to mutate.** A reviewer reading this exact report (50 %, four named
survivors, all in argument plumbing) would get precisely zero signal, positive
or negative, about the defect that actually shipped: fixing every survivor
listed here to 100 % would not have touched the moved-checkout attack, because
that attack was never represented in the seeded population to begin with. That
is the sharper form of "you cannot mutate a guard that was never written" —
not "the score lies", but "the score has nothing to say", which is more
dangerous because a non-zero, partially-red report reads as due diligence
already done.

The out-of-tree delete, the seven gate bypasses, and the `file_bridge.py` queue
collision arms of this criterion are **not yet measured** — this run covers only
the named `worktree.py` case. F1 is therefore **partially measured**: decisive
evidence on the one arm that was run, in the predicted direction, not yet run on
the other three.

### F2 — The Goodhart test

**Measurement.** After N promotion cycles under diff-scoped admission, track two
series together: (a) mutation admission pass rate, and (b) the number of real
defects found by the acceptance run (`tools/system_check.py`) and by production
use, per cycle.

**Falsifier.** Mutation admission climbing while acceptance-found defects stay
flat or rise. That is the signature of a score being farmed rather than earned —
tests written to kill mutants rather than to state behaviour. A supporting
measurement: the ratio of assertions on *behaviour* to assertions on
*representation* (`repr`, exact dict shapes, internal ordering) in newly added
tests. A rising representation ratio is the tell.

### F3 — The equivalent-mutant rate

**Measurement.** Human-adjudicate a random sample of survivors: real hole, or
behaviourally equivalent mutant?

**Falsifier.** If more than roughly **30%** of survivors are equivalent mutants,
the survivor list is mostly noise. The signal is then not *wrong*, but it is not
*actionable*, and a gate built on it will spend more attention than it returns.
Record the adjudications; the rate is a measured property of this repo's code
style, not a constant to be assumed from the literature.

**Status: partially measured, and uncomfortably close to the line.** Of the 15
survivors in `sensitivity.py`, 3 were adjudicated equivalent (**20 %**, §4.1);
of the 11 in `token_monitor.py`, ~3 were (**~27 %**, §4.3). Both under 30 %,
both n<20, both adjudicated by a single reviewer who also wrote the tool — which
is the weakest possible form of this measurement. A second, independent
adjudicator is the obvious next step, and if the rate crosses 30 % the survivor
list stops being worth the attention it costs.

### F4 — The stability test

**Measurement.** Run the identical command twice against the identical snapshot.

**Falsifier.** Any mutant whose status differs between the two runs. That means
the suite is order-, time-, or state-dependent, and *every number produced from
it is noise* — including the ones in §4. This is the cheapest criterion and it
should run before any other number is quoted.

**Status: measured on n=10, passing (§4.5).** Zero status disagreements, zero
disagreements in *which* test did the killing. That is one repetition of a
ten-mutant subset of one module — enough to say the tool is not obviously
noise, nowhere near enough to say this suite is deterministic.

### F5 — The self-control (the scorer's own oracle check)

**Measurement.** `--drop-test <name>`: remove a covering test and re-score.

**Falsifier.** If removing the test that kills mutant `M` does **not** flip `M`
to `SURVIVED`, the tool is not measuring the suite, and its outputs are void.

This is the same move `oracle_check.py` makes on the conformance suite and
`self_test.py` makes on the acceptance run, turned back on the mutation scorer
itself — and it is the reason `drop_test()` raises rather than returning quietly
when nothing matched. A control that silently did nothing would read as "the
score did not move", i.e. as evidence *against* the tool, which would be exactly
backwards.

**Status: measured on real code, passing (§4.2).** 100 % → 0 % when the single
covering test was removed, with the baseline green in both runs.

### Where the five criteria stand

| | criterion | status |
| --- | --- | --- |
| F1 | escape test — would it have caught this repo's real escapes? | **PARTIALLY MEASURED — `worktree.py` arm confirmed blind (50.0%, 4/8 survived, none touching the actual defect); 3 arms (out-of-tree delete, gate bypasses, queue collision) still unmeasured** |
| F2 | Goodhart — is the score being farmed? | unmeasured; needs N promotion cycles, so it cannot be measured yet |
| F3 | equivalent-mutant rate | partially measured: 20 % and ~27 %, n<20, single adjudicator |
| F4 | stability | measured n=10, passing |
| F5 | the scorer's own control | **measured on real code, passing** |

Note what that table says about §4. Three (now four) green-or-confirmed
criteria do not make the signal trustworthy — that is the exact inference this
whole document exists to refuse. F1's `worktree.py` arm is measured, and it
asked whether the signal detects the defect class that has actually escaped in
this repository. It does not, on that arm, and the honest summary is:

> Mutation survival is the best-evidenced fitness input available in this
> repository, it is the only one with a one-command self-check, it separates
> two green-suite modules by 31 points and hands back file:line pairs — and on
> the one escape it has been checked against, it produced a report (50.0%,
> four named survivors) that contained no signal at all about the defect that
> actually shipped, because that defect was a missing guard and no operator
> can mutate a line that does not exist. The prediction was recorded in
> advance, for exactly this case, and it held: not as a clean "green", which
> would have been the easier finding to explain away, but as a populated,
> partially-red report that was structurally incapable of representing the
> vulnerability. **That is the stronger and more uncomfortable version of the
> same conclusion.** Three arms of this criterion — the out-of-tree delete, the
> seven gate bypasses, and the `file_bridge.py` queue collision — remain
> unmeasured, and the queue collision is the one arm where a GREEN result would
> still kill the proposal (it IS a single-token guard, so mutation testing has
> no excuse to miss it).

Nothing in this repository should gate on this signal on the strength of F1
alone. It should gate even less on the strength of F1 being incomplete: one
confirmed arm is not three, and this document should not be read as though the
question were closed.

---

## Appendix: using the tool

```bash
# list the mutants without running anything (fast)
python tools/mutation_score.py --module daedalus/sensitivity.py --list

# score a module against a test selection
python tools/mutation_score.py --module daedalus/sensitivity.py \
    --tests tests/test_hardening.py tests/test_fence_anchoring.py \
    --json receipts.json

# a deterministic, evenly-spread subset (NOT a prefix -- the guards are not at
# the top of the file)
python tools/mutation_score.py --module M --tests T --sample 20

# F5, the self-control: weaken the suite on purpose and require the score to move
python tools/mutation_score.py --module M --tests T --drop-test test_foo

# re-run one specific mutant -- --only is a substring match on the id
# (ids are "operator:path:line:col", and are in the JSON)
python tools/mutation_score.py --module daedalus/sensitivity.py --tests T --only ':258:'
```

Exit codes: `0` no survivor and a green baseline; `1` at least one survivor;
`2` the measurement itself did not happen (red baseline, collection error,
sandbox failure). **`2` is not `1`** — a run that could not be performed must
never be reportable as a run that found nothing.

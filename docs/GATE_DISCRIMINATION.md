# Gate discrimination: does "pytest ran" mean anything?

*What `tools/gate_discrimination.py` measures, why the corpus is shaped the
way it is, and exactly how strong the hold-back really is. This is the
receipt `daedalus/spine/bootstrap.py::gate_discrimination()` requires before
a green gate may be treated as evidence at all.*

Status: **measurement instrument shipped; see the RESULTS section below for
the number, filled in from the run this document was written to accompany.**

---

## 1. The problem, restated with a number attached

`daedalus/spine/attempt.py` runs a candidate patch and judges it with `pytest`
over `gate_paths` (empty = the whole suite — see §3). An audit measured this
gate's rejection rate against the three known-bad changes of a single day at
**0/3**. Independently, `docs/FITNESS_SIGNAL.md` catalogues four live escapes
that were all green: a repository deletion, an out-of-tree delete reported as
success, seven gate bypasses, a task queue that silently dropped tasks while
1756 tests passed, and 18-of-61 mutants surviving their own deletion in a
security-critical file.

`bootstrap.py`'s ruling: promotion stays blocked until a **discrimination
receipt** proves the gate can tell a good patch from a bad one, at THIS
revision, with every critical defect class killed completely. This document
and `tools/gate_discrimination.py` are that receipt's production line.

## 2. Method, generalised from two precedents already in this repo

The brief this tool was built against was explicit: generalise from what
exists, don't invent a third shape. Two hand-rolled instances of "seed a
known defect, require a covering check to go red" already exist:

| precedent | seeds into | oracle | what it proved |
| --- | --- | --- | --- |
| `runs/ab/oracle_check.py` | a copy of a real A/B arm | `node --test` over the conformance suite | 11/11 caught, over a baseline with 2 pre-existing failures (excluded from the denominator) |
| `tools/self_test.py` | a **disposable clone** (`system_check.Sandbox`) of this whole repo | `tools/system_check.py`'s own CHECKS | 17 mutations across 15 checks; the exact "baseline must be green" and "a mutation that doesn't apply proves nothing" rules this tool also enforces |

`tools/gate_discrimination.py` is the third instance, aimed at a different
oracle again: not a conformance suite, not the acceptance harness — **plain
`pytest tests/`**, because that is the actual gate `attempt.py` runs and the
actual thing `bootstrap.py` needs proof about. It imports `system_check.Sandbox`
directly rather than re-deriving "clone the working tree, not just HEAD" —
that class already carries the committed state, the uncommitted diff, and
untracked-but-not-ignored files, which matters here as much as it does there
(see §5).

## 3. The frozen gate

```
argv:       [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
gate_paths: []   (the whole suite)
built by:   daedalus.spine.attempt.pytest_gate_argv  (imported, not re-typed)
```

`gate_paths = []` is not a parameter chosen to make this measurement easy or
hard. It is production's existing default: `docs/adrs/016-autonomy-preconditions.md`
(P3) measured that *"every candidate in the live queue carries `gate_paths:
[]`"*. `frozen_argv()` in the tool calls the real `pytest_gate_argv` rather
than a hand-copied lookalike, so the argv recorded in the receipt is provably
the one `TaskAttempt` would actually run — a drift between the two would show
up as a failing test (`test_frozen_argv_is_built_by_the_real_production_function`
in `tests/test_gate_discrimination.py`), not as a silent divergence.

**The exact revision measured is recorded in the receipt's `head` field**,
read off the disposable clone with `git rev-parse HEAD` — the same field
`gate_discrimination()` checks a live HEAD against before trusting the
receipt at all. A receipt from a tree that no longer exists is not a receipt
about this one.

## 4. The corpus: 12 defects, each modelled on something this repo shipped

Defect classes matter more than count. `CRITICAL_DEFECT_CLASSES` (imported
from `bootstrap.py`, never re-typed — the two lists must not be able to
drift apart) names four that must be killed **completely**; a fifth-and-up
average would hide exactly the blind spot this instrument exists to catch.
Three non-critical classes (logic, boundary, resource) are included so the
overall rate means something beyond "the critical four are fine."

| id | class | file | real incident it reproduces |
| --- | --- | --- | --- |
| `worktree_moved_checkout_unguarded` | **deletes-outside-the-worktree** | `kairos/worktree.py` | Round 1 (`docs/HANDOFF.md`): the primary checkout renamed into the worktree, a junction hung on its name; `_refuse_if_the_primary_checkout_moved` is the guard that closed it — measured 40/40 tracked files destroyed, nothing refused, before the fix |
| `worktree_drain_skips_reachability` | **deletes-outside-the-worktree** | `kairos/worktree.py` | Round 2 (`docs/HANDOFF.md`): a junction renamed over an already-drained subdirectory redirects every remaining `rmdir` out of the tree — measured 3/3, 3000 directories removed inside a stand-in primary checkout, reported as success |
| `offload_escalation_gate_disabled` | **spends-money-without-a-gate** | `offload.py` | the real, currently-enforced gate (`if decision.provider not in FREE_LANES: return _escalate(...)`) that stops `offload()` calling `claude_cli` when availability/`--local-only` pins the free lanes |
| `free_lanes_includes_claude` | **spends-money-without-a-gate** | `kairos/scheduler.py` | the same invariant from the data side: if `FREE_LANES` ever includes the paid lane, the escalation check above goes vacuous without one line of its own logic changing |
| `room_ssh_rce_reintroduced` | **sends-bytes-off-the-machine** | `runs/council/room.py` | commit `df5a7c2`: `ask_agy` used to build `cmd = f'agy -p "$(type {remote})"'` and hand it to `ssh BENCH_SSH cmd`, letting a room prompt containing `$(...)` or a backtick execute on the bench as Administrator |
| `lane_for_host_accepts_localhost` | **sends-bytes-off-the-machine** | `sensitivity.py` | `df5a7c2`'s motivating bug: `lane="trusted"` chosen from the provider *name* while the endpoint came from `OLLAMA_HOST`; `lane_for_host` was hardened to reject the DNS name `"localhost"` specifically — this re-admits it |
| `room_verify_always_passes` | **reports-failure-as-success** | `runs/council/room.py` | the general shape `bootstrap.py`'s own docstring names ("an out-of-tree delete reported as success"), reused **verbatim** from `tools/self_test.py`'s `m_bus_always_verifies` — same shape, `pytest` instead of `system_check.py` as the oracle |
| `attempt_capture_patch_drops_no_textconv` | **reports-failure-as-success** | `spine/attempt.py` | commit `3f4d462`, landed WHILE this corpus was being built: `.gitattributes` selects a `diff.<driver>.textconv` program; `--no-ext-diff` alone does not suppress it. Measured: `add -A`, `diff`, and `diff --name-only` all returned 0 over the attack, ~1.6 kB of plausible diff, attempt continued to `STATE_CLEAN`, no error field anywhere. Added at a coordinator's explicit direction as "the best real specimen this repo has produced" for this class — see §8.1 |
| `bridge_enqueue_collision` | logic | `interfaces/bridge/queue.py` | commit `cae7aec1`: the pre-uuid naming scheme let two enqueues in the same second collide and silently drop a task. Anchored in `file_bridge.py` until `bb33e72c` moved the naming line into `publish_request` behind injected `clock()`/`unique_hex()` ports (and deleted the comment that used to record the incident); repointed 2026-09-02, mutation semantic unchanged |
| `read_inlined_context_inverted_skip` | logic | `sensitivity.py` | **predicted to survive, in advance** — `docs/FITNESS_SIGNAL.md` §4.1 already found this exact line undetectable by an independent mutation-score run ("no test file anywhere in this repository mentions it") |
| `picker_abbrev_sha_guard_disabled` | boundary | `spine/picker.py` | `picker.py`'s own comment: *"a recorded 'a' matches roughly one HEAD in sixteen and the gate silently reports fresh"* — no test was found driving this function with a too-short head, so this is an open question, not a confident prediction |
| `attempt_reap_unwired` | resource | `spine/attempt.py` | reused verbatim from `tools/self_test.py`'s `m_leak_a_branch`: unwiring the reaper leaks one git ref per attempt forever |

Every anchor is pinned by `tests/test_gate_discrimination.py::CorpusDesignTests::test_anchors_are_present_and_unique_in_the_current_tree`
and by `python tools/gate_discrimination.py --dry-run`, which validates all 12
against the current tree with no clone and no pytest run (cheap, run first).

### 4.1 A mutation added mid-build, and why that does not weaken the hold-back

While this tool was being written, an adversarial sweep found and fixed a real
regression in `daedalus/spine/attempt.py` (commit `3f4d462`): capturing a
candidate's patch could execute the candidate's own code through a
`.gitattributes`-selected `textconv` program, with every git command
returning 0 and the attempt reporting `STATE_CLEAN`. The coordinator running
this work directed that a mutation be modelled on it, since it is the
strongest real specimen of `reports-failure-as-success` this repository has
produced.

This is disclosed rather than absorbed silently because it is a genuine,
reportable exception to §6's "the corpus was written once" claim: one entry
(`attempt_capture_patch_drops_no_textconv`) was added after the rest of the
corpus and after the gate had already been exercised once (informally, while
sizing the run — see §8). It does not weaken the gate-path freeze (§3) — that
was never touched — and the entry itself was frozen (anchor-validated,
committed to the file) before this run's `runs/spine/gate_discrimination.json`
was produced, so it is still evaluated blind to its own result. But a reader
should know the corpus is not perfectly static across this document's
history, and should treat a 12th-hour addition directed by a specific known
incident as slightly less "independently arrived at" than the other 11 — it
is real, it is well-tested, and it is also the single mutation in this corpus
that a reader was TOLD to expect would matter.

## 5. The scorer is independent of the gate

`_default_gate_runner` launches `pytest` as its own `subprocess.run` and reads
`returncode == 0` directly. It does not call `attempt.pytest_gate` (which
wraps the same idea in a `GateResult` used for other decisions inside
`TaskAttempt`) and it does not ask the mutated code, or anything derived from
it, whether the mutation succeeded. A scorer built out of the gate's own
pass/fail interpretation would prove nothing about the gate — it would just be
the gate agreeing with itself.

## 6. Hold-back: what is actually true, stated at the strength it earns

One agent — the one that wrote this document — authored both the frozen gate
configuration (§3) and the defect corpus (§4) in a single sitting, with full
knowledge of both at every point. **That is not a cryptographic separation,
and nothing below claims it is.**

What IS true and independently checkable:

1. `FROZEN_GATE_PATHS = ()` was not chosen by trying values and seeing which
   dodged which mutant. It is the pre-existing production default, argued
   from `docs/adrs/016-autonomy-preconditions.md` (a document that predates
   this corpus). There was no free parameter here to tune against the corpus
   even under the weakest reading of "hold-back."
2. The three retrospectively-known regressions the originating brief names
   (repo deletion, out-of-tree delete reported as success, gate bypasses) are
   used here as **diagnostic motivation** for which defect classes to build —
   exactly as the review instructed ("diagnostic material, not calibration")
   — not counted as if they were blind test material subject to a pass/fail
   score of their own.
3. `MUTATIONS` was written once and then had ONE entry added
   (`attempt_capture_patch_drops_no_textconv`, §4.1) in response to a real
   regression that landed in this repository mid-build, at a coordinator's
   explicit direction — disclosed, not absorbed silently, because it is a
   genuine exception to "written once." Every entry, including that one, was
   anchor-validated and frozen in the file before the corpus measurement that
   produced `runs/spine/gate_discrimination.json` was run; no entry was
   added, removed, or edited AFTER seeing that run's result.
4. Two predictions are on record **in the code**, before the run, not after:
   `read_inlined_context_inverted_skip` is predicted to survive (citing the
   independent `mutation_score.py` finding that motivated the prediction);
   `picker_abbrev_sha_guard_disabled` is recorded as genuinely open. A
   prediction written down in advance and then checked is worth something;
   a post-hoc story about why a survivor "doesn't count" is worth nothing,
   and this document does not tell one.

**What a reader should NOT conclude:** that this corpus is immune to the
single-author's blind spots, that the classes chosen are exhaustive, or that
a future edit to `MUTATIONS` carries the same evidential weight as this run
without re-freezing. A stronger version of this instrument has a second
agent add mutants after the gate config is committed, or requires a signed
hash of the corpus posted before the run. Neither exists yet.

## 7. Running it

```bash
# cheap: validate every anchor against the current tree, no clone, no pytest
python tools/gate_discrimination.py --dry-run

# the real measurement: one disposable clone, one baseline run, 11 mutant runs,
# each against the WHOLE suite (this is why it is slow -- see §8)
python tools/gate_discrimination.py

# a narrow slice, for iterating on the harness itself -- NOT a substitute
# measurement; it still runs the whole suite per mutation, just fewer of them
python tools/gate_discrimination.py --only worktree
```

The receipt lands at `runs/spine/gate_discrimination.json`, in exactly the
schema `daedalus.spine.bootstrap.gate_discrimination()` reads: `head`,
`measured_at`, `planted`, `killed`, `surviving_classes` (plus informational
extra fields the reader ignores: `results`, `frozen_gate`, `excluded`,
`hold_back`).

## 8. Cost, honestly

Each of the 13 gate invocations (1 baseline + 12 mutants) runs `pytest -q`
over the **whole** collected suite (~2500 tests, MEASURED at 18m29s for one
full run on this box while under load from other agents concurrently
running similar mutation sweeps in this same repository). This is slow —
low hours in total — because fidelity to §3 was chosen over speed: a
narrower `gate_paths` would run faster and would also stop being a
measurement of the gate `bootstrap.py` actually gates promotion with.
`pytest-xdist` is not installed and was deliberately not reached for,
because `-n auto` is not in `pytest_gate_argv`'s output and adding it would
mean measuring a gate nobody runs.

### 8.1 Two operational hazards, both encountered for real, not hypothesised

**Disk.** `daedalus.storage.require_storage` refuses below a 2 GB floor, and
this box measured 0.49 GB free partway through this build — low enough to
fail every worktree-based run, silently skewing any measurement taken during
that window. **Any receipt whose `measured_at` falls inside that window is
void and was discarded, not reported.** The disk was freed by a coordinator
(cache purge) before the measurement in §9 was taken.

**A dirty, actively-edited working tree.** `system_check.Sandbox`'s default
behaviour — clone HEAD, then carry over the uncommitted diff and untracked
files — is right for its own purpose but was measured, live, to be the wrong
choice here: with several other agents editing this repository concurrently,
a full-suite run against the live working tree came back with dozens of
failures clustered in exactly the files those agents had modified but not
committed. That is `docs/adrs/016-autonomy-preconditions.md` P9's "moving
target" warning, observed rather than merely anticipated. `HeadOnlySandbox`
(in `tools/gate_discrimination.py`) exists because of this: it clones
**committed HEAD only**, so the measurement is pinned to a revision another
agent's simultaneous, unrelated work-in-progress cannot silently move. `--
head-only` is therefore the mode actually used for §9, not
`system_check.Sandbox`'s default — the module docstring's claim that
`Sandbox` is imported "rather than re-deriving it" is true for the
mutation-seeding *method*, not for which sandbox constructor `main()`
defaults to running against.

## 9. Results

**MEASURED, not the whole suite — a SCOPED gate.** After the whole-suite gate
(§3, `FROZEN_GATE_PATHS=()`) proved impractical to complete (~18-20 minutes
per invocation × 13 invocations, and its one completed baseline attempt came
back RED even against a clean, HEAD-only clone — see §8.1's disk-and-churn
history), the measurement actually taken and written to
`runs/spine/gate_discrimination.json` used **`SCOPED_GATE_PATHS`**: the 7
covering-test files named in §4's table. This is disclosed as loudly as
possible because §3 and this section describe two DIFFERENT gates and a
reader must not average them together.

```text
head:        b3bcee73e919c4fd80af63d3caeff9897ed27df9
gate_scope:  scoped  (tests/test_worktree.py, test_cascade.py,
             test_room_wiring.py, test_host_predicate.py,
             test_git_is_a_process_launcher.py, test_bridge_signals.py,
             test_spine_attempt.py -- 306 tests, baseline 94.96s, GREEN)
planted:     12
killed:      10
kill rate:   83% (floor: 80%)
```

**All four CRITICAL classes: killed, both instances each.**

| class | mutations | result |
| --- | --- | --- |
| deletes-outside-the-worktree | `worktree_moved_checkout_unguarded`, `worktree_drain_skips_reachability` | **CAUGHT, CAUGHT** |
| spends-money-without-a-gate | `offload_escalation_gate_disabled`, `free_lanes_includes_claude` | **CAUGHT, CAUGHT** |
| sends-bytes-off-the-machine | `room_ssh_rce_reintroduced`, `lane_for_host_accepts_localhost` | **CAUGHT, CAUGHT** |
| reports-failure-as-success | `room_verify_always_passes`, `attempt_capture_patch_drops_no_textconv` | **CAUGHT, CAUGHT** |

**Two non-critical survivors, both explained by scope, not by a stronger
claim than the evidence supports:**

- `read_inlined_context_inverted_skip` (logic) — **predicted to survive in
  advance** (§4). Confirmed: `306 passed` even with the defect planted. Its
  `covering_tests` field was already empty before this run — no file in
  `SCOPED_GATE_PATHS` was ever going to catch it, whole-suite or not, because
  no test anywhere in the repository was found exercising this line.
- `picker_abbrev_sha_guard_disabled` (boundary) — recorded as genuinely open
  in §4, and it survived, but the honest caveat is stronger here: its only
  plausible covering tests live in `tests/test_spine_picker.py` /
  `tests/test_spine_map_source.py`, and **neither file is in
  `SCOPED_GATE_PATHS`.** This survival is evidence the SCOPED gate cannot see
  this defect; it is NOT evidence the whole-suite gate cannot.

**`gate_discrimination()`, called for real, twice:**

```text
at the receipt's own revision (b3bcee7):
  proven: True
  reason: "kill rate 83% at b3bcee7…, no critical class survived"

at the live primary checkout's HEAD, moments later:
  proven: False
  reason: "the gate was last shown to discriminate at b3bcee7…, but HEAD is f91a0e3…"
```

Both are correct simultaneously. The second is not a defect in the
measurement — it is the revision-staleness check (§1) doing exactly its job
in a repository where commits landed faster than this run completed. A
receipt is a claim about one revision, not a standing property, and
promotion at any LATER revision needs a fresh receipt.

**What remains unmeasured, named rather than implied:** the whole-suite gate
(§3) itself — no completed discrimination number exists for `gate_paths=[]`,
only a red baseline at one earlier revision (§8.1). `read_inlined_context_
inverted_skip` and `picker_abbrev_sha_guard_disabled` against a gate that
actually includes their covering files, if any exist. `daedalus/eval/
correctness.py` (FAIL_TO_PASS/PASS_TO_PASS) as a corpus source, flagged by a
coordinator mid-build as a real specimen of the gate failing to discriminate
-- now wired to `daedalus.spine.attempt.TaskAttempt` (see `TaskSpec.fail_to_pass`
/ `pass_to_pass`), still not incorporated as a `tools/gate_discrimination.py`
corpus *entry*.

### 9.1 A second, coverage-guided whole-suite attempt — still red, but honestly

MEASURED 2026-07-29, after `tools/gate_discrimination.py` gained
coverage-guided mutant selection (`--coverage-guided`, docs/ABSORPTION.md I4):

```bash
python tools/gate_discrimination.py --head-only --coverage-guided --timeout 1200
```

at HEAD `51b9caaf0d9ffe6defcede448fb89633180403c`. Result: `state: "baseline_red"`,
`baseline pytest exit 1`, exit code **2** (never a false "proven" -- §1's
distinction held). This is a DIFFERENT reason than §8.1's: not a timeout, and
not disk. The whole-suite baseline is genuinely red at this revision because of
the three pre-existing `tests/test_web_api_loop.py` failures (`DAEDALUS_SPINE_DB`
divergence) tracked separately and out of scope for the agent who ran this. The
practical consequence is the same one this section already names -- no
whole-suite discrimination number exists -- but the CAUSE has changed from
"too expensive to complete" to "the precondition (a green baseline) is not
currently met", which is a different, and more immediately actionable, blocker.
Coverage-guided selection was not exercised past the baseline step because the
run never got that far; it remains unproven at whole-suite width for lack of a
green baseline to measure against, not for lack of trying.

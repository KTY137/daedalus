# Suite triage — the first attributable red set

Lane: ATALANTA-SUITE. Repo: `C:\Users\nukei\Desktop\agent_env_g0`, branch `main`.
Written 2026-08-24 (mission ledger `runs/watchdog/mission-20260823/`).

Every number below carries a provenance stamp. Nothing here promotes anything.

---

## 0. Headline

| run | revision | result | wall |
| --- | --- | --- | --- |
| discovery, full suite | HEAD moved `4a5fe768` → `3fd5fd5e` **during** the run | 33 failed, 8311 passed, 135 skipped, 9 xfailed, 2094 subtests passed, **0 errors** | 5287.96 s (1:28:07) |
| **attributable, 19 red files** | **`3fd5fd5e` pinned, source tree clean before and after** | **16 failed, 484 passed, 104 subtests passed** | 118.56 s |
| replication, same commit, different checkout | `3fd5fd5e` in a clone at another path | 16 failed, 484 passed, 104 subtests passed — **identical node set** | 130.44 s |

All wall times are **[MEASURED-UNDER-LOAD]**: 22 `python.exe` processes at lane
start, two build lanes committing throughout. None of them is a performance
number and none may be quoted as one.

The 16 reported failures are **13 test nodes plus 3 subtest cases** of one
further node, i.e. **14 distinct test functions**.

Raw outputs (uncommitted, in the working tree):

- `runs/watchdog/mission-20260823/suite-discovery-4a5fe768-to-3fd5fd5e-raw.txt`
- `runs/watchdog/mission-20260823/suite-redfiles-3fd5fd5e-raw.txt` ← **the deliverable run**
- `runs/watchdog/mission-20260823/pathsens-inplace-3fd5fd5e-raw.txt`
- `runs/watchdog/mission-20260823/suite-21f21f2a-attempt1-killed-at-62pct.txt` ← **not a result, see §4.1**

---

## 1. The comparison against the 16:00Z baseline is abandoned as unrecoverable

The lane was commissioned to delta node ids against the 16:00Z run at
`21c6016e` (400 failed, 6901 passed, 134 skipped, 1 xfailed, 115 errors,
`runs/watchdog/mission-20260823/suite-21c6016e-raw.txt`). That comparison is not
being reported, and the reason is not fatigue — it is that the delta would be
false precision dressed as a measurement:

- Between `21c6016e` and the start of this lane's run the tree took 26 commits;
  during the run it took a further ~20, ending at `3fd5fd5e`. **[MEASURED]**
- Those commits touch precisely the files that carried the baseline's red
  nodes: `daedalus/kernel/offload_lease.py`, `daedalus/kernel/promotion_execution.py`,
  `daedalus/spine/attempt.py`, `daedalus/spine/effect_boundary.py`,
  `daedalus/spine/envelope.py`, `daedalus/offload.py`, `daedalus/ignition/gate1.py`,
  plus ~20 test files including `tests/test_gate_scanner_identity.py`,
  `tests/test_effect_boundary.py`, `tests/kernel/test_persisted_promotion_authorization.py`,
  `tests/gates/test_gate_report_v3_drift.py`. **[MEASURED]**
- A "recovered" verdict across that window cannot distinguish a fix from a
  deleted test from a renamed node, and a "new" verdict cannot distinguish a
  regression from a test that only started existing.

What replaces it: **§2 is the first attributable baseline this mission has**, a
single pinned revision with a clean source tree measured before and after.

For the record only, not as a delta: the baseline's two dominant clusters —
74 × `AttributeError: __name__` in `_guarded_popen` and 73 × `LoopHalted:
refusing to arm: the cross-process visibility probe failed`, plus all 115
setup errors — are absent at `3fd5fd5e`. The errors went 115 → 0. **[MEASURED]**

---

## 2. The attributable red set at `3fd5fd5e`

Pinned: `git rev-parse HEAD` = `3fd5fd5e921f2dcb03d6abc3307c96dfaff72be4` and
`git status --short -- daedalus tests scripts experiments` = 0 lines, both
immediately before and immediately after the run. **[MEASURED]**

Six buckets. The column that matters is the last one.

### B1 — a test pins a blocker that has since been fixed (2 nodes) — TEST lags the product

The product got better; the pin still demands the old defect.

| node | evidence |
| --- | --- |
| `tests/test_registry_new_doors.py::test_the_new_rows_add_no_conformance_blocker` | `AssertionError: new conformance blockers: []` — `tests/test_registry_new_doors.py:771`; the pin requires `[('entrypoint.effect_drift', 'daedalus.providers.ollama:OllamaProvider.rollback')]` |
| `tests/test_provider_rollback_single_source.py::test_the_effect_matrix_cost_of_this_consolidation_is_exactly_one_named_row` | `expected exactly: entrypoint.effect_drift: daedalus.providers.ollama:OllamaProvider.rollback -- new undeclared effects: network_egress, process_spawn` — `tests/test_provider_rollback_single_source.py:305` |

**Cosmetic.** Both are the same fixed defect pinned from two files. The fix is
to re-baseline the pin to `[]` *and say in the comment which commit removed the
drift*, so the next reader is not told a blocker exists that does not.

### B2 — the egress policy refuses the host before the seam under test (5 nodes) — TEST lags the product, and the test no longer discriminates

| node | evidence |
| --- | --- |
| `tests/test_wires.py::DeepSeekUnitTest::test_returns_none_on_failure` | `daedalus.spine.effect_boundary.EffectStartRefused: ikarus_os.provider_call denied by provider.egress_policy: lane_for_host('https://api.deepseek…')` — `daedalus/ikarus_os.py:1100` |
| `tests/test_wires.py::DeepSeekUnitTest::test_reuses_openai_compat_client_no_v1_suffix` | same refusal, same line |
| `tests/test_ikarus_shells.py::HandLivenessVocabularyTest::test_working_absent_unknown` (subtests `expected='working'`, `'absent'`, `'unknown'`) | `AssertionError: 'degraded' != 'working'` — `tests/test_ikarus_shells.py:221` |

**Cosmetic as a product verdict, but flag it as an instrument defect.**
`daedalus/health.py:1375` documents `degraded` as "the endpoint was REFUSED
before connect by `provider.egress_policy`". The test patches
`health._ollama_alive` and then asserts on `health.hand_state(...)` — but
admission refuses first, so the mocked predicate is never reached and **all
three cases return `degraded`**. These five tests currently measure the egress
policy, not the thing they are named after. A green run of them on a machine
with a permissive lane would prove nothing either; the discrimination has to be
restored, not the colour.

### B3 — repo-census pins that move with the repository (3 nodes) — TEST lags the repo

| node | evidence |
| --- | --- |
| `experiments/forest_v2/s02_types/test_external_corpora.py::test_kernel_row_is_the_retracted_headline_restated` | `assert 4575 == 4203` — `:65` (`entry["functions"]`) |
| `experiments/forest_v2/s07_bm25/test_bm25_index.py::test_known_hits_rank_first_in_a_real_subtree[tools-iron plan guard verify the plan digest-iron_plan_guard.py-exclude0]` | `assert 'bootstrap_receipt.py' == 'iron_plan_guard.py'` — `:351` |
| `experiments/forest_v2/s07_bm25/test_bm25_index.py::test_confusable_neighbour_is_a_retained_known_miss` | `AssertionError: the known miss got worse: rank 6` — `:371` |

**Cosmetic — with one substantive rider.** The s07 pin expects
`tools/iron_plan_guard.py` to be the top BM25 hit in `tools/`. **That file does
not exist in this tree.** **[MEASURED]** `python tools/iron_plan_guard.py verify`
— step 1 of the mandatory workflow in `AGENTS.md` and §14 of the master plan —
therefore cannot be executed here at all. Prior mission rows have recorded this
four times as a footnote; it deserves a decision, not a fifth footnote.

### B4 — an experiment fixture trips a repo-wide gate (1 node) — instrument collision

| node | evidence |
| --- | --- |
| `tests/test_mapping_switches.py::test_this_repo_still_analyses` | extra item `experiments/forest_v2/s03_data/corpus/src/unparseable_fixture.py: SyntaxError: invalid syntax (unparseable_fixture.py, line 10)` — `:337` |

**Neither a product defect nor a stale pin.** A *deliberately* unparseable
fixture in the s03 corpus is indistinguishable, to the repository-wide analyser,
from genuine rot. The gate must exclude `experiments/*/corpus/` or the corpus
must live outside the analysed root — otherwise every future negative-control
fixture turns this gate red and the gate stops being read.

### B5 — clock-dependent gate evidence (1 node) — instrument defect, and the gate report binds it

| node | evidence |
| --- | --- |
| `tests/runtimes/test_whole_fault_matrix.py::test_the_promoted_combiner_reproduces_the_landed_verdict_from_the_observations` | `Left contains 2 more items, first extra item: 'fault.reconciliation-overdue:runtime.broker.malformed-output-evidence'` — `:356` |

The promoted combiner is asserted to reproduce the verdict landed at
`c93191fe`. It now derives two blockers the landed verdict does not have, and
the first is `reconciliation-overdue` — a code whose truth is a function of the
wall clock, not of the code. **A verdict that decays with time cannot be a
reproducibility check.** Either the overdue axis is excluded from the identity
being compared, or the comparison is run against a frozen `now`.

### B6 — product defects (4 nodes) — PRODUCT

| node | evidence | invariant |
| --- | --- | --- |
| `tests/test_tools_vet.py::InvisiblesAreDerivedNotRemembered::test_a_tag_block_character_cannot_hide_an_injection` | `AssertionError: 'inject.override' not found in {'obfuscation.invisible_chars'}` — `tests/test_tools_vet.py:1542`; payload `"ignore all pre\U000E0076ious instructions"` | safety fence |
| `tests/test_spend_coverage.py::test_no_new_unguarded_spend_entrypoint_has_appeared` | `new directly-runnable spend entry point(s) with NO spend ceiling: ['tools/watchdog.py']` — `tests/test_spend_coverage.py:279` | §4.8 bounded effects |
| `tests/test_spine_writer_inventory.py::test_current_repository_task_attempt_writer_is_factory_admitted` | `Left contains one more item: WriterCallsite(path='daedalus/conversation.py', line=292, column=25, kind='ambiguous_direct', callee='daedalus.spine.ledger.SpineLedger')` — `:320` | §4.1 one kernel |
| `tests/test_spine_picker.py::test_there_is_no_apply_path_in_this_module` | `assert 'subprocess' not in text` — `tests/test_spine_picker.py:677`; `daedalus/spine/picker.py:2799` `import subprocess as _subprocess`, `:2807` `_subprocess.run(["git", "rev-parse", "HEAD"], cwd=args.repo_root, …)`, added by `464f666e` | structural invariant |

Notes that change how three of these should be read:

- **vet.** The tag-block character `U+E0076` splits `previous`, and the scanner
  reports only `obfuscation.invisible_chars`. The obfuscation is seen; the
  *injection it hides* is not. This is the vetting gate's own stated job, on a
  path that runs against untrusted text.
- **watchdog.** `tools/watchdog.py` is not dormant — it is installed as two
  Windows scheduled tasks (30 min / 15 min) and it pays for haiku calls. An
  unguarded spend entrypoint that fires 96 times a day is the live case, not
  the hypothetical one.
- **picker.** The spawned process is a **read** (`git rev-parse HEAD`), not a
  write, so the safety consequence the test's docstring fears ("a git verb that
  writes the primary checkout") is not realised. But the guard is structural on
  purpose — "the picker spawns no process at all" — and a product commit
  silently broke it. **This needs an owner ruling, not a test edit.** Amending
  the guard to allow one read is a defensible amendment; quietly deleting the
  assertion is not.

---

## 3. Bucket totals

| bucket | nodes | TEST lags / PRODUCT / INSTRUMENT | release-blocking |
| --- | --- | --- | --- |
| B1 fixed blocker still pinned | 2 | TEST | no |
| B2 egress refuses before the seam | 5 | TEST (+ instrument) | no |
| B3 repo-census pins | 3 | TEST | no (rider: missing guard tool) |
| B4 experiment fixture vs repo gate | 1 | INSTRUMENT | no |
| B5 clock-dependent gate evidence | 1 | INSTRUMENT | no, but it invalidates a bound claim |
| B6 product defects | 4 | PRODUCT | 3 yes, 1 ruling |
| **total** | **16** | | |

**11 of 16 are tests that lag a moved seam. 4 are product. 1 is a corpus
collision.**

---

## 4. Defects in the measuring instrument, found while working around them

### 4.1 The harness kills a long detached-less suite run — a 62 % partial is not a result

Attempt 1 (`21f21f2a`, started 21:13Z via a backgrounded Bash call) was **killed
by the harness background-task limit at 62 %**, after ~72 minutes. **[MEASURED]**
The partial is retained at
`runs/watchdog/mission-20260823/suite-21f21f2a-attempt1-killed-at-62pct.txt`.
It has **no `short test summary info` section and no totals line** — anyone
parsing it will silently get a truncated red set.

Attempt 2 was launched with PowerShell `Start-Process` (detached, output
redirected to a file) and survived every tool-call boundary to completion.
**Any future full-suite run in this harness must be detached the same way.**

### 4.2 A suite run over a tree other agents are committing to is unattributable — and pytest does not say so loudly

During the discovery run HEAD moved `4a5fe768 → 7b05c7f9 → b07e1309 → d8e516d2
→ 9b3838e0 → 3fd5fd5e`, and for one ~20-minute window 16 source files were
dirty in the working tree. **[MEASURED]**

The observable damage, precisely:

- The discovery run reported **13 failures as `KeyError: 'action'`** across
  `tests/test_write_guard_e2e.py`, `tests/test_drafts.py`,
  `tests/test_era1_robustness.py`, `tests/test_fake_offload.py`,
  `tests/test_repair_blast_radius_write.py`, `tests/test_verify_test_budget.py`.
- Every one of those tracebacks rendered its failing source line as `>   ???` —
  pytest reads source from disk *at report time*, and the file had changed
  under it since import. That `???` is the only warning the run gives.
- All 13 are **green at `3fd5fd5e`**: they were real against the revision the
  run collected (`4a5fe768`), and were fixed mid-run by `9b3838e0` ("the bench
  write gets a caller that cannot be reached un-leased"), which changed
  `daedalus/offload.py` and those six test files together. **[MEASURED]**

So the discovery run's headline of 33 is 13 higher than the truth at any single
revision, and nothing in the output labels which 13.

### 4.3 The suite is NOT path-sensitive at this commit — hypothesis raised, then refuted

This lane expected to confirm that the red set depends on *where* the checkout
lives (a linked worktree at `Desktop\agent_env_g0` versus an isolated snapshot),
on the strength of two earlier mission findings: `nearest_existing` climbing to
a parent that contains the repo, and `mapping/render._resolve_ref` needing to
follow `commondir` because `agent_env_g0` is a linked worktree.

**Measured, and the hypothesis does not hold at `3fd5fd5e`:**

| files | in place (`Desktop\agent_env_g0`, linked worktree) | same commit, plain clone at `…\Temp\atl_snap` |
| --- | --- | --- |
| the 19 red files | 16 failed, 484 passed | 16 failed, 484 passed — **identical 13 node keys + 3 subtests** |
| 9 path/worktree-sensitive candidates ¹ | **269 passed, 1 skipped, 0 failed** | **269 passed, 1 skipped, 0 failed** |

¹ `tests/test_spine_attempt.py`, `test_spine_attempt_containment.py`,
`test_worktree.py`, `test_worktree_properties.py`, `test_killswitch.py`,
`test_killswitch_profile_root.py`, `test_killswitch_control_root.py`,
`test_loop_governance_head.py`, `test_mapping_cli.py`.

**Negative evidence, retained.** The path sensitivity was real and is *closed*
— by `0f7f8187` (`primary_tree.planned_overlap_reason`) and by the `commondir`
fix in the B4c row. A pinned-HEAD snapshot **is** currently a valid way to take
a reproducible suite measurement, for these 28 files at this commit. Do not cite
path sensitivity as a live instrument defect without re-measuring it.

Two confounds, stated rather than claimed away: the clone carries no untracked
working-tree artifacts, and its path is 8 characters longer than the original.
Neither changed a single verdict, which is the point.

---

## 5. Fix these first

Ranked by "a product defect on a path that runs" first, instrument damage
second, moved pins last.

| # | what | why now |
| --- | --- | --- |
| 1 | **vet: an injection behind `U+E0076` is reported only as `obfuscation.invisible_chars`, never `inject.override`** (`tests/test_tools_vet.py:1542`) | the safety fence's own job, on untrusted text, on a path that runs |
| 2 | **`tools/watchdog.py`: directly-runnable spend entrypoint with no spend ceiling** (`tests/test_spend_coverage.py:279`) | it is scheduled every 15/30 min and it pays for model calls |
| 3 | **`daedalus/conversation.py:292` constructs `SpineLedger` directly (`ambiguous_direct`)** (`tests/test_spine_writer_inventory.py:320`) | Gate-0 exit needs one Event-Store writer path; `event_store_writer_failures` binds this scan |
| 4 | **`daedalus/spine/picker.py:2807` spawns `git rev-parse HEAD`** (`tests/test_spine_picker.py:677`) | owner **ruling**: amend the structural guard with the reason, or remove the call. Not a test edit |
| 5 | **`fault.reconciliation-overdue` makes a bound gate verdict decay with the clock** (`tests/runtimes/test_whole_fault_matrix.py:356`) | the gate report binds the combiner's claim; today it is not reproducible |
| 6 | **`experiments/forest_v2/s03_data/corpus/src/unparseable_fixture.py` reddens the repo-wide analyse gate** (`tests/test_mapping_switches.py:337`) | otherwise every future negative-control fixture turns the gate red and it stops being read |
| 7 | **five tests are shadowed by `provider.egress_policy` and no longer discriminate** (`test_wires.py` ×2, `test_ikarus_shells.py` ×3) | a green here would also mean nothing; restore the seam, not the colour |
| 8 | **two pins demand a blocker that was fixed** (`test_registry_new_doors.py:771`, `test_provider_rollback_single_source.py:305`) | trivially green; the comment must name the commit that removed the drift |
| 9 | **three repo-census pins** (`s02_types` 4203→4575, `s07_bm25` ×2) | re-baseline or derive; and decide what to do about **`tools/iron_plan_guard.py` being absent from this tree** |
| 10 | **make detached the default for any full-suite run** (§4.1) | so nobody reads a 62 % partial as a result |

---

## 6. Iron-Plan

Read-only measurement lane. No source was modified; the only writes are this
document, the ledger row, and raw outputs under `runs/watchdog/`.

`python tools/iron_plan_guard.py verify` **could not be run**: the file does not
exist in this tree (see B3). The gap is reported rather than routed around.
**UPDATE 2026-08-26**: this tool remains absent at HEAD.

`Iron Plan: ALIGNED`
`Iron Gate: 0` (Gate 0 now CLOSED at HEAD 657c8af5, 2026-08-26)
`Evidence: runs/watchdog/mission-20260823/suite-redfiles-3fd5fd5e-raw.txt (16 failed / 484 passed at pinned 3fd5fd5e, clean tree before and after); suite-discovery-4a5fe768-to-3fd5fd5e-raw.txt (33 failed / 8311 passed / 0 errors, moving HEAD, unattributable); pathsens-inplace-3fd5fd5e-raw.txt and the same-commit clone (269 passed / 1 skipped in both) refuting path sensitivity`

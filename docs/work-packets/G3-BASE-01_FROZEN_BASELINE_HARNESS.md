# G3-BASE-01 - Frozen baseline harness (Gate-3 prework)

Packet ID: `G3-BASE-01`
Artifact role: `primary`
Status: `built; independently reviewed; six contract defects found and fixed; NOT sealed`
Active gate: `1`
Classification: `EXPERIMENT`
Owner: `repository owner`
Base revision: `1ba5b66f3a95f215f905fe4b46e3db9d3ec26be0`
Dependencies: `none`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion, and Gate transition are
forbidden. This packet cannot open, enter, or satisfy Gate 3.
Expiry: `2026-12-06`, or immediately if the task corpus gains non-code-plane
tasks (which would change the central measured finding below)

## 0. Why this is EXPERIMENT and not ALIGNED

Plan §11: *"Work advances in order. A later-gate experiment may be prototyped
only when it does not create a competing kernel and is explicitly labelled
experimental."*

The active delivery gate is **Gate 1** (Renovation, owner-directed Genesis, and
— since revision 12/13 — general computer assistance and hardware targets /
self-Renovation). Gate 2 is undelivered: `experiments/forest_v2/` is by its own
README a read-only pre-study that **no production import may reference**, and
`daedalus/twin/` runs its four-plane compiler against a single hand-declared
10-file fixture (`examples/fourfold_wiki_app/`).

Therefore this packet **cannot** and **does not** claim to open, enter, or
satisfy Gate 3. It builds the measurement instrument that Gate 3 will require,
under the isolation rules for later-gate prototyping. It is owner-directed work
(session of 2026-09-06) to advance the Gate-3 harness in parallel with Gate-1
delivery.

Three claims this packet is forbidden from making:

1. that Gate 3 is open, entered, or closed;
2. that any measurement it produces is Gate-3 baseline evidence — the harness
   must be **sealed** first (plan §11, Gate 3, sentence 1) and sealing is an
   owner act, not a builder act;
3. that any number it produces supports a comparative claim against AlphaEvolve
   or any other system (plan §11 Gate 5, §4 invariant 9).

## Primary acceptance claim

**One** claim: *the six Gate-3 freeze obligations are represented as typed,
digest-bound, testable artifacts, and every one of the eleven required baselines
is a runnable arm under a single budget-equal protocol.*

Plan §11 Gate 3, sentence 1 (the freeze obligations):

> freeze public tasks, evaluator versions, budgets, model/hardware reporting,
> seed policy, and statistical reporting

Plan §11 Gate 3, sentence 2 (the eleven baselines):

> Random Search, Best-of-N, a single-LLM loop, simple local mutation, BM25,
> embeddings, code-only graph, four separate indices, evaluator-only selection,
> archive/MAP-Elites, and a transparent AlphaEvolve-like proxy

Plan §11 Gate 3, sentence 3 (the nine measures):

> success rate, best-so-far AUC, wall time, tokens, compute, variance,
> diversity, regressions, and human intervention

Producing the *Genesis research slice* (Gate 3, paragraph 2) is explicitly
**out of scope** for this packet and belongs to a later `G3-GEN-*`.

## 2. Extend, never duplicate

Plan §5 (one canonical path) and `AGENTS.md` ("Prefer wiring, consolidation, and
deletion over a new subsystem"). `daedalus/eval/` already contains the honest
core this packet extends, and it must not be forked:

| Existing asset | File | Reused for |
| --- | --- | --- |
| Per-provenance-tier aggregation, never blended | `daedalus/eval/harness.py:111-124` | statistical reporting |
| Quarantine tier excluded from go/no-go | `daedalus/eval/harness.py:89-94` | task freezing |
| Errored/focus-withheld rows absent, not zero | `daedalus/eval/harness.py:127-201` | every arm's failure semantics |
| Okapi BM25, deterministic tie-break | `daedalus/eval/harness.py:429-458` | baseline (e) BM25 |
| Budget-equal arm C (`token_budget_C == tokens_A`) | `daedalus/eval/harness.py:553` | the budget-equality primitive |
| Untruncated baseline B measured at true size | `daedalus/eval/harness.py:545-550` | anti-starvation rule |
| Advisory regression ratchet, per-task not mean | `daedalus/eval/harness.py:757-854` | measure: regressions |
| Tokenizer identity reported per run | `daedalus/eval/harness.py:52-59,339` | measure: tokens |

**Forbidden:** a second BM25, a second aggregation path, a second task store, a
second tokenizer, a second gate. A baseline that needs different behaviour
extends the existing function or declares why in its module docstring.

## 3. The starvation rule (binding, learned from measured failure)

`docs/GATE2_FOREST_V2_TRIAGE.md:109-131` records the most serious defect this
repository has produced: slice s08 concluded "four separate indices are strictly
inferior (432 vs 491)" by splitting **one shared hit budget round-robin across
four indices** while 100% of gold labels were code documents. The code index
effectively received only ranks 1, 5, 9. Given its own budget the same baseline
scored 491 — exactly the pure code index. The headline was an artifact of the
measurement, and the README booked it as evidence *for* the hypothesis anyway.

Binding rules for every arm in this packet:

- **R1 — Own budget.** Each arm receives the full declared budget. Budget is
  never divided across an arm's internal components. A composite arm declares
  its internal split in its result row.
- **R2 — Named comparator.** The frozen spec names the comparator; results
  report against *that* comparator. Substituting a weaker one is a defect, not
  a finding.
- **R3 — Label-plane disclosure.** Every task set reports the plane distribution
  of its gold labels. A task set whose labels are 100% one plane **may not** be
  used to test a cross-plane hypothesis, and the harness must refuse it rather
  than report a structurally impossible comparison.
- **R4 — Denominator declared before the run.** The counting rule is part of the
  frozen spec and is hashed into the run manifest.
- **R5 — Adverse results are headline results.** An arm that ties or beats the
  product arm is reported at the same prominence, following the existing
  `c_beats_a` tie-inclusive precedent (`harness.py:571-579`).

## Contracts and behavior

New package `daedalus/eval/gate3/`. All contracts frozen dataclasses, canonically
serialized, digest-bound — matching `daedalus/kernel/contracts/genesis.py`.

| Contract | Purpose | Freeze obligation |
| --- | --- | --- |
| `FrozenTaskSet` | task ids + counting rule + label-plane census + digest | public tasks |
| `EvaluatorVersion` | evaluator identity, version, digest of its scoring code | evaluator versions |
| `ArmBudget` | tokens / wall time / money / calls, per arm, equal by construction | budgets |
| `RunEnvironment` | model id, provider, host, CPU/RAM, tokenizer, OS | model/hardware reporting |
| `SeedPolicy` | seed list, repetition count, determinism declaration | seed policy |
| `TrialResult` | one arm × one task × one seed | — |
| `ArmSummary` | the nine measures with variance and interval | statistical reporting |
| `RunManifest` | binds all of the above + base revision + plan digest | the seal |

`RunManifest` is the sealing unit: a run without a complete manifest produces
results marked `sealed=false`, and unsealed results are refused as Gate-3
evidence by construction.

## Acceptance matrix

Deterministic, offline, no model calls unless an arm explicitly declares one.

### 5a. Freeze obligations

| # | Test | Passes when |
| --- | --- | --- |
| A1 | `test_frozen_taskset_digest_is_stable` | same tasks → same digest; any task text change → different digest |
| A2 | `test_taskset_reports_label_plane_census` | census present; sums to task count |
| A3 | `test_single_plane_taskset_refused_for_crossplane` | R3 refusal fires, loudly |
| A4 | `test_evaluator_version_binds_scoring_code_digest` | editing the scorer changes the recorded digest |
| A5 | `test_unsealed_run_is_marked_unsealed` | missing manifest field → `sealed=false`, never silently true |
| A6 | `test_seed_policy_repeats_are_independent` | N seeds → N distinct trial rows, no reuse |
| A7 | `test_environment_records_model_and_host` | model id, tokenizer, OS, CPU present |

### 5b. Budget equality (R1)

| # | Test | Passes when |
| --- | --- | --- |
| B1 | `test_every_arm_receives_equal_budget` | all arms' `ArmBudget` equal for one comparison |
| B2 | `test_composite_arm_declares_internal_split` | four-indices arm reports its per-index budget |
| B3 | `test_round_robin_split_is_refused` | the exact s08 defect is refused by construction |
| B4 | `test_budget_overrun_is_reported_not_clipped` | an arm exceeding budget is flagged, not silently truncated |

### 5c. The eleven baselines

Each arm: runs, produces `TrialResult`, respects budget, is deterministic under
a fixed seed (or declares itself stochastic and is run under `SeedPolicy`).

| # | Arm | Test |
| --- | --- | --- |
| C1 | Random Search | `test_arm_random_search` |
| C2 | Best-of-N | `test_arm_best_of_n` |
| C3 | Single-LLM loop | `test_arm_single_llm_loop` (provider-gated, skips cleanly) |
| C4 | Simple local mutation | `test_arm_local_mutation` |
| C5 | BM25 | `test_arm_bm25_delegates_to_harness` (must reuse `_bm25_scores`) |
| C6 | Embeddings | `test_arm_embeddings` (offline deterministic embedder) |
| C7 | Code-only graph | `test_arm_code_only_graph` |
| C8 | Four separate indices | `test_arm_separate_indices_each_full_budget` (R1) |
| C9 | Evaluator-only selection | `test_arm_evaluator_only` |
| C10 | Archive / MAP-Elites | `test_arm_map_elites_archive` |
| C11 | AlphaEvolve-like proxy | `test_arm_alphaevolve_proxy_is_transparent` |

C11's "transparent" obligation: the proxy documents exactly which AlphaEvolve
mechanisms it does and does not reproduce. AlphaEvolve is closed (plan §11
Gate 5), so this arm is a **declared proxy**, never a replication claim.

### 5d. The nine measures

| # | Test | Measure |
| --- | --- | --- |
| D1 | `test_measure_success_rate` | success rate |
| D2 | `test_best_so_far_auc_is_monotone` | best-so-far AUC |
| D3 | `test_wall_time_excludes_setup` | wall time |
| D4 | `test_tokens_use_declared_tokenizer` | tokens |
| D5 | `test_compute_recorded` | compute |
| D6 | `test_variance_reported_with_interval` | variance |
| D7 | `test_diversity_metric_defined` | diversity |
| D8 | `test_regressions_per_task_not_mean` | regressions |
| D9 | `test_human_intervention_counted` | human intervention |

D8 inherits the existing mean-preserving-swap test precedent
(`tests/test_eval_oracle.py`) — a mean must never hide one task collapsing.

### 5e. Refusal and fault injection

| # | Test | Refuses |
| --- | --- | --- |
| E1 | `test_arm_cannot_read_evaluator` | invariant 3 — candidate access to its evaluator |
| E2 | `test_arm_cannot_mutate_taskset` | frozen set is immutable at runtime |
| E3 | `test_stale_base_revision_refused` | manifest revision ≠ tree revision |
| E4 | `test_missing_seed_refused_for_stochastic_arm` | no silent single-seed run |
| E5 | `test_partial_run_is_not_reported_as_complete` | killed run → explicit partial |
| E6 | `test_no_network_in_deterministic_arms` | offline arms stay offline |

## Scope

**In scope (this packet writes only here):**

- `daedalus/eval/gate3/**` (new)
- `tests/eval/gate3/**` (new)
- `docs/work-packets/G3-BASE-01_FROZEN_BASELINE_HARNESS.md` (this file)

**Forbidden (this packet must not touch):**

- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, its amendment chain, `AGENTS.md`
- `daedalus/kernel/**`, `daedalus/spine/**` — the trust kernel
- `daedalus/eval/harness.py` and siblings — **reuse, do not edit**; if an
  extension point is genuinely required, that is a separate reviewed change
- `experiments/forest_v2/**` — frozen pre-study, and its README forbids
  production reference
- anything under `daedalus/twin/**`

## 7. Budgets

Deterministic arms: offline, no model calls, no network, no spend. Provider-gated
arms (C3, and C6 if a live embedder is chosen): skip cleanly when no provider is
reachable, exactly as `detect_provider` already does (`harness.py:650-674`).
Default monetary ceiling unchanged. This packet requests **no** cap widening.

## 8. Expected failures (recorded before the build)

1. Existing eval tasks are likely code-plane-dominated. If so, **R3 will refuse
   them for cross-plane comparison** — that refusal is a correct result and must
   be reported, not engineered around.
2. The four-separate-indices arm needs four real indices; only the code index is
   substantially built. The honest outcome may be that C8 cannot run yet.
3. "compute" (D5) has no accepted unit here. Expect a declared proxy, explicitly
   labelled, not a fabricated FLOP count.
4. Diversity (D7) is underdetermined by the plan. Expect one declared definition
   with its limitations stated.

## Migration and rollback

Additive-only: a new package plus new tests. Rollback = delete
`daedalus/eval/gate3/` and `tests/eval/gate3/`. No migration, no schema change,
no existing caller touched. Branch `packet/g3-base-01` is not merged without
owner approval (plan §10.9).

## Evidence, expected failures and review

1. Does any arm obtain a budget advantage — including an internal split (R1)?
2. Is any denominator chosen after seeing a result (R4)?
3. Can any arm read its evaluator, the frozen task set, or another arm's state?
4. Is any counter structurally guaranteed rather than measured? (The s06 defect:
   "0 rejected / 0 violations" that could not have been non-zero.)
5. Does any test pass against dead code (a vacuum test)?
6. Is any result presented as sealed Gate-3 evidence without a complete
   `RunManifest` and an owner seal?
7. Does anything here import `experiments/forest_v2/` or create a second
   evaluation authority?

## Measured findings (2026-09-06, base revision `1ba5b66f`)

These are measurements, not status claims. Each is reproducible with the command
given. `[MEASURED]` means it was executed at this revision.

### F1 — The task corpus cannot support a cross-plane comparison today

`[MEASURED]` via `daedalus.eval.gate3.taskset` over `harness.all_tasks()`:

| quantity | value |
| --- | ---: |
| tasks in corpus | 27 (10 hand-authored + 17 minted) |
| primary tier (enter the frozen set) | 10 |
| quarantine tier (excluded, reported) | 17 |
| census, all 27 | code=27, type=0, data=0, knowledge=0 |
| planes present | `("code",)` |
| `require_cross_plane()` | **REFUSES** |

Every task targets a `.py` or `.tsx` file with identifier-shaped gold labels.
This is exactly the shape that produced the s08 false verdict: a label set
entirely in one plane, against which any cross-plane arm loses structurally
rather than empirically. Rule R3 fires and no number is produced.

**Consequence for Gate 3:** the cross-plane baselines cannot be honestly run
until the corpus gains type-, data- and knowledge-plane tasks. That is corpus
work, not harness work, and no amount of further harness code removes it. It
confirms this packet's own §8 expected-failure #1, written before the run.

### F2 — Every token count in this repository is currently a heuristic

`[MEASURED]` `harness.tokenizer_name()` returns `chars/4 (heuristic)` on this
host: `tiktoken` is not installed, so `daedalus.eval.harness` is running its
documented degrade path (`harness.py:52-59`).

Gate 3 requires frozen **budgets** and a **tokens** measure. A budget denominated
in a chars/4 approximation is not comparable to one denominated in a real
tokenizer, so this must be resolved (or explicitly declared in the frozen spec)
before any budget-equal claim is made. `measures.token_usage` already records
the tokenizer identity with every count so the two can never be silently mixed.

### F3 — Real provider token usage is discarded before it reaches the harness

`[MEASURED]` by reading `daedalus/eval/tier2.py` and its `_openai_compat`
helper: the chat path returns only the message string and drops the provider's
`usage` block. The single-LLM-loop arm therefore reports
`notes["tokens_estimated"] = True` and counts locally rather than presenting an
estimate as measured usage. Wiring real usage through is a separate change to
`tier2.py`, outside this packet's scope.

### F4 — Sealing has no mechanism, and this package must not pretend otherwise

`RunManifest.sealed` is hard-wired `False`. Gate 3's first sentence requires a
**sealed** harness before any baseline evidence counts, and sealing means an
authenticated one-use `OwnerApproval` (plan §7.1) bound to the manifest digest
and verified by the kernel. That binding does not exist here. Building a
looser check would have re-created the forgery an independent reviewer already
demonstrated. Wiring it is a prerequisite for Gate 3 and belongs to a packet
that may touch `daedalus/kernel`.

### F5 — Scope extension, recorded rather than done quietly

This packet's §"Scope" forbids touching anything outside `daedalus/eval/gate3`,
`tests/eval/gate3` and this document. Adding 24 modules necessarily moved two
repository-wide census pins, so the following files were edited outside the
declared scope:

- `tests/contracts/test_import_scc_hierarchy.py` — `CENSUS_MODULES` 483 → 507,
  `CENSUS_EDGES` 1926 → 1988. The non-trivial-component count stayed at **14**:
  an earlier draft did add a 15th (a real import cycle via the package
  `__init__`), which this test caught and which was fixed rather than re-pinned.
- `tests/contracts/test_work_packet_index.py` — tracked files 427 → 428,
  packet ids 361 → 362, and `G3-BASE-01` added to the expected primary set.
- `docs/work-packets/index.json` — regenerated with `tools/index_work_packets.py
  --render`.

### F6 — What is NOT proven

- No baseline has been run against the real corpus; only fixture repositories.
- No arm has been compared against another. The harness can run a comparison;
  nobody has.
- `single_llm_loop` has never executed against a live provider.
- The five retrieval/search arms that need non-code planes (`separate_indices`
  in cross-plane mode, and any four-plane comparison) are blocked by F1.
- Nothing here is Gate-3 baseline evidence, and cannot be until F4 is resolved.

## Re-landing (2026-09-08, rebased onto main `24e229c0`)

- The four retained commits were rebased onto `main` after PR #318 and #319
  landed; the branch's fifth commit (the first edge-census re-measure) became
  empty against the new base and was dropped, not squashed.
- Census re-measured at this revision `[MEASURED 2026-09-08]`: modules
  485 -> 509, edges 1931 -> 1997, still 14 non-trivial components with maximum
  19 -- the package adds modules and edges, not a cycle. Registry: tracked
  files 472 -> 473, packet ids 406 -> 407, `G3-BASE-01` in the primary set.
- `tests/eval/gate3/test_arm_embeddings.py::test_hashing_vector_stable_across_pythonhashseed`
  now pins `PYTHONPATH` to the tree under test. In a linked worktree the probe
  otherwise imported `daedalus` from the venv's editable install (which has no
  `daedalus.eval.gate3`) and failed for a reason unrelated to hashing:
  1 failed / 300 passed before the pin, 328 passed / 2 skipped after it
  (`tests/eval/gate3` plus the two contract suites) `[MEASURED 2026-09-08]`.
- F1-F4 were **not** re-measured; their base remains `1ba5b66f`. `tiktoken`
  is still absent on this host `[MEASURED 2026-09-08: ModuleNotFoundError]`.
  The four blockers are being designed as separate packets, not folded in
  here.

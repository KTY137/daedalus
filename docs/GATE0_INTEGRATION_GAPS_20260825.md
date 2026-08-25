# Gate-0 integration gaps — what is built but not wired at HEAD

**Revision bound:** `2de997efe73f417f2cb82260ab944c2ff9562efa` (main, 2026-08-25).
Every code and reachability measurement below is pinned to that commit. This
lane modified no `daedalus/` source file and staged nothing.

**Concurrency caveat — the tree moved underneath this survey.** At the start,
the working tree was dirty in `vault/Sessions/2026-08-25.md` only. By the end,
concurrent lanes had also modified `docs/HANDOFF.md`, `docs/STATUS.md`,
`daedalus/ignition/gate1.py`, `daedalus/hooks/tools.py`, `daedalus/skills.py`
and others, and had moved
`docs/decisions-pending/promotion_allowed_signers.proposed` into
`docs/decisions-taken/2026-08-25/`. The code measurements are unaffected — they
were taken against committed HEAD, not the dirty tree — but §6 is explicitly
dual-stamped for committed-HEAD state versus working-tree state, because that
is precisely where the movement landed.

**Classification:** `ALIGNED` — read-only inventory. No production path changed.

**Provenance rule used throughout:** `[MEASURED]` = run by this lane at the
revision above. `[INHERITED]` = someone else's run, with the source named.
`[ASSUMED]` = derived by reading, not by executing. No timing numbers are
reported: ten lanes were running concurrently and the box was under load, so
every wall-clock figure this session would have been noise.

**Instrument:** the repository's own reachability engine
(`daedalus/mapping/reach.py`, consumed by `daedalus/mapping/drift.py`), not an
ad-hoc scan. That engine's own doctrine is why: a hand-written inventory once
claimed 136 features / 8 islands where a deep read of the same tree found
827 / 55 (`daedalus/mapping/reach.py:11-14`). This document is therefore a
*snapshot of a generated answer*, and it carries the revision that produced it.

---

## 0. Read this before trusting any number below — the baseline is broken

`docs/architecture-state.json`, the committed baseline the drift gate compares
against, **fails its own integrity check at HEAD** `[MEASURED]`:

```text
INVALID SNAPSHOT (2)
  ! counts.modules
      snapshot says 520, its own 'modules' list has 521
  ! digest
      the mechanical lists do not match the digest written with them:
      something was hand-edited
```

The hand-edit is identified. Merge `9831ddae` (the unification merge) resolved
this **generated, digest-covered** file by hand:

```diff
git diff 9831ddae^1 9831ddae -- docs/architecture-state.json
-    "file": ""
+    "file": "de1f022b7b6667a6"
+    "daedalus/crew_hook.py (replaced by daedalus/hooks/, 2026-08-23)",
```

It took parent-2's `ignore.file` digest and added one module name to the census
— without updating `counts.modules` (still `520`) and without recomputing
`digest`. That is exactly the 520-vs-521 split and the digest failure.
`daedalus/crew_hook.py (replaced by daedalus/hooks/, 2026-08-23)` does not exist on disk at HEAD `[MEASURED]`, so the
merge added a census entry for a file that is not there.

Second, compounding: the snapshot records `ignore.file = de1f022b7b6667a6`, but
**`.daedalusignore` does not exist in the working tree and is not tracked at
HEAD** `[MEASURED]` — `git ls-files --error-unmatch .daedalusignore` fails,
though the file was added in ancestor commit `0c294ba8`. The gate says so
itself and refuses to compare:

> the baseline was taken under DAEDALUS_IGNORE unset, .daedalusignore
> de1f022b7b6667a6. A run that looks at less of the tree than the baseline did
> cannot be compared with it

This is the single most important finding for any lane that plans to *rank work
out of this snapshot*, because `daedalus/mapping/inventory.py:6-11` records that
`docs/FEATURE_INVENTORY.json` feeds the self-improvement picker: "the thing that
chooses what gets worked on next was reasoning about a tree that no longer
existed." Treat every snapshot-derived number as `[INHERITED, UNTRUSTED]` until
it is re-baselined.

**Credit where due:** the instrument did *not* fail silently toward less
coverage. It printed `INVALID SNAPSHOT`, named the ignore-config change, and
exited 1. It can say "could not measure" distinguishably from "measured,
nothing found." That is the property this repo has previously lost.

---

## 1. The census at HEAD `[MEASURED]`

Scoped to `daedalus/` (the mission's scope). Produced by calling
`daedalus.mapping.reach.analyse(Path('.'))` read-only at HEAD.

| Class | Count | Meaning |
| --- | --- | --- |
| `reachable` | 194 | an entry point leads here |
| `entry` | 54 | is itself an entry point |
| `unknown` | 22 | only a string literal / non-proving import names it |
| `island` | 17 | no entry point reaches it |
| `shim` | 6 | re-export nothing reaches by name |
| `orphan` | 1 | imports nothing, nothing imports it |
| **total** | **294** | `daedalus/` Python modules |

**Islands found: 18** (`island` 17 + `orphan` 1).
**Total unreached under `daedalus/`: 46** (islands + `unknown` + `shim`).
Whole-tree module count at HEAD: 2248 `[MEASURED]`.

For contrast, the untrusted committed baseline claimed `islands: 68`,
`unreached: 101`, `modules: 520` whole-tree at `94eb3515`
`[INHERITED, UNTRUSTED — digest fails]`. A fresh whole-tree run at HEAD reports
`islands=78, unreached=115, modules=1637` `[MEASURED]`, but that number is **not
comparable** to the baseline: the missing `.daedalusignore` means the fresh run
walked `vault/`, `docs/recovery/` and more `experiments/` subtrees that the
baseline excluded. Ten of the fresh run's "new islands" are recovery kits under
`docs/recovery/` and `vault/docs/recovery/`, which are scripts-on-disk by
design, not integration gaps.

---

## 2. 46 unreached modules are not 46 problems — they are 9 clusters

The unreached set is a small number of connected subgraphs hanging off single
root causes. `daedalus/runtimes/provider_invocation_authority.py` alone has
seven non-test importers, **all of which are themselves unreached** `[MEASURED]`.
Closing one root cause moves a whole cluster.

| # | Cluster | Modules | Root cause | Verdict |
| --- | --- | --- | --- | --- |
| C1 | `runtimes/provider_*` | ~26 (11 island + 15 unknown) | no production caller mints a `RuntimeBoundEffectAuthorization` | **(b) real gap — rank 1** |
| C2 | `kernel/effect_recovery` + `runtimes/recovery` | 2 | unknown-effect reconciliation never invoked in production | **(b) real gap — rank 2** |
| C3 | `gates/repository_write_*`, `gates/fault_matrix` | 6 | reached only by dynamic string dispatch; classification cannot resolve | (b/c) mixed — see §5 |
| C4 | `twin/extractors/*` (+ shim) | 5 | consumed only by `tests/` and `scripts/fourfold_*_probe.py` | **(c) dormant — Gate 2** |
| C5 | `kairos/{evolution,archive,shadow_shell}` + `eval/provenance` | 4 | Ariadne evolution layer, no Gate-0/1 consumer | **(c) dormant — Gate 3+** |
| C6 | `wiki/{links,vault}` (+ shim) | 3 | Knowledge-plane surface, no consumer | **(c) dormant — Gate 2** |
| C7 | `observe/shape` (+ shim) | 2 | reached only via its own package `__init__` | (c) dormant |
| C8 | `decompose.py`, `drafts.py`, `mission_control.py` | 3 | re-export shims with **zero** importers | **(a) deletable** |
| C9 | `langgraph_adapter.py` | 1 | explicit `NotImplementedError` | **(c) dormant by declaration** |

---

## 3. RANKED TOP 3 — what other lanes should act on

Ranked strictly by whether closing the gap unblocks **Gate-0 closure** or the
**Gate-1 ignition slice**.

**A load-bearing negative first:** *no island blocks Gate 1.* Every module on
the ignition path — `daedalus/ignition/{__init__,bundle,checks,gate1,runner}.py`
— classifies `reachable` or `entry` at HEAD `[MEASURED]`. The only unreached
neighbour is `daedalus/twin/extractors/*`, which is Gate-2 material per the
master plan §11. All three gaps below are therefore Gate-0 gaps.

### Rank 1 — Nothing in production mints a `RuntimeBoundEffectAuthorization`

**This is the keystone.** It is one missing caller, and it is why cluster C1
(~26 modules, the largest island cluster in the tree) is unreachable.

Evidence `[MEASURED at HEAD]`:

- `grep -rn "RuntimeBoundEffectAuthorization(" --include=*.py daedalus` →
  **0 files**. The class is constructed at 6 sites, all under `tests/`:
  `tests/fixtures/runtime_trust_contention_fault_executor.py:402`,
  `tests/kernel/test_runtime_effect_admission.py:242`,
  `tests/kernel/test_runtime_effect_replay_projection.py:194`,
  `tests/kernel/test_runtime_terminal_capability.py:35`,
  `tests/providers/test_claude_runtime_broker.py:253`,
  `tests/runtimes/test_runtime_terminal_fence_release.py:247`.
- The chain it feeds **exists and is complete**: `daedalus/kernel/runtime_effects.py:401`
  defines it; `daedalus/runtimes/broker.py:515` `run_runtime_provider` consumes
  it; `daedalus/providers/claude_cli.py:378` already calls that seam.
- The registry states the consequence itself, at
  `daedalus/spine/effect_boundary.py:962` — and dates its own measurement:

  > CONDITION UNDER WHICH IT FALLS, both halves required: (1) caller injection
  > — some production caller actually mints a `RuntimeBoundEffectAuthorization`.
  > MEASURED 2026-08-18: zero such callers outside tests/, so the lane is
  > unreachable and flipping the row would only remove a counted blocker
  > without enabling a single real start; (2) exact-head verification.

  **That 2026-08-18 measurement still holds at HEAD 2de997ef** — re-measured by
  this lane `[MEASURED]`, not inherited.

**Why it blocks Gate-0 closure:** master plan Revision 3 item 2 makes
"content-addressed runtime-conformance observations" a *required* Gate-0
evidence input, and item 4 names "live runtime receipts" as a remaining closure
requirement. No production caller mints the authorization → the runtime-bound
lane never starts in production → no live runtime receipt can be produced at
all. `daedalus/runtimes/broker.py:449` refuses non-`CENTRAL` rows, so
`provider.claude` cannot go `CENTRAL` first.

**Handover precision — what to do and what NOT to do.** Do **not** flip the
`provider.claude` registry row to `CENTRAL`. `effect_boundary.py:962` calls that
"routing around a guard, not wiring a door," and
`tests/providers/test_claude_bypass_inventory.py::test_canonical_registry_activation_remains_an_explicit_blocker`
pins the current value on purpose. The work is **caller injection**: give one
real production caller a minted authorization. `daedalus/claude_bridge.py:215`
already accepts `runtime_authorization: RuntimeBoundEffectAuthorization | None`
and `daedalus/providers/claude_cli.py:333` already accepts the same parameter —
both currently default to `None` and no caller supplies it. That parameter is
the seam. Both halves of the stated condition (caller injection **and**
exact-head verification) are required before the row moves.

### Rank 2 — Exactly one door in the tree holds a lease; 411 of 442 write surfaces are unclassified

`python scripts/declare_write_surfaces.py --dry-run` at HEAD `[MEASURED]`:

```text
revision   2de997efe73f417f2cb82260ab944c2ff9562efa
inventory  surfaces=442 digest=76b11aa024c9450141b8592d7c6b999b54c80a4333fc5b9af8e1d874a6834e05
declared   31 (unclassified after: 411)
door modules hold 150 blocking surfaces no anchor dominates
```

Of the 21 doors the derivation reports, **exactly one — `python.offload` — has
`lease_dominated: 1`.** Every other door reports `lease_dominated: 0` with the
same single refusal string:

> `anchor function contains no <authorization>.begin_effect(...) call, so
> nothing it does happens inside a leased execution`

That includes `python.command_gate` (`daedalus/spine/attempt.py`, `declared: 2`,
`lease_dominated: 0`), `worktree.create`, `adapter.subprocess`, `cli.loop`, and
all three `file_bridge.*` doors. `python.attempt` does not appear in the
per-door list at all — consistent with `scripts/declare_write_surfaces.py:167-170`,
which records that it "declares 0 surfaces" because its `begin_effect` sits
inside a `try` whose `else` branch carries the whole attempt, and the dominance
rule counts only statements *after* the holder.

**This independently confirms — at HEAD, by execution — the claim
`docs/decisions-pending/B5_HANDOFF_COMMIT4.md:28-29` makes:** *"exactly one door
in the system can hold a lease at all. No amount of producer work moves a
counter until that changes."* I inherited that sentence and then measured it;
it holds.

**The same subsystem's consumer half is also unwired.**
`harvest_effect_lease_terminal_records` — the function that turns retained lease
records into terminal receipts — has **zero production callers** `[MEASURED]`:

- Defined `daedalus/kernel/offload_lease.py:830`, exported `:2284`; it calls
  `emit_effect_lease_terminal_record` (`:752`) at `:869`.
- **Producer half is wired**: `record_effect_lease_execution` at
  `daedalus/kernel/offload_lease.py:1361`, `record_effect_lease_subject` at
  `:2153`, both in production paths.
- **Consumer half is not**: its only 8 call sites are
  `tests/kernel/test_write_evidence_records.py:214,228,249,273,377`,
  `tests/gates/test_write_surface_lease_dominance.py:213`,
  `tests/gates/test_write_evidence_producer.py:95,188`.

So production writes `lease-subject/*.json` and `lease-execution/*.json` and
never harvests them into terminal records. Gate 0 requires a signed/traceable
receipt (master plan §8 step 9); the machinery exists, runs green in tests, and
the product never invokes it. This is the exact failure shape
`daedalus/spine/attempt.py:1685-1688` warns about in its own comment: *"A guard
that is built and not connected is indistinguishable from a guard, right up
until it is measured through the product."*

Grouped here, same subsystem: `daedalus/kernel/effect_recovery.py`
("Authenticated reconciliation for externally acknowledged unknown effects") is
an **island** whose only non-test importer is `daedalus/runtimes/recovery.py` —
itself `unknown` `[MEASURED]`. The unknown-effect recovery path is a closed loop
of two unreached modules.

**Handover precision:** the refusal string is the specification. A door becomes
lease-dominated when its anchor function calls
`<authorization>.begin_effect(...)` — the authorization-bound method — rather
than the bare module-level `begin_effect`. `daedalus/offload.py` is the one
worked example in the tree; `python.offload`'s entry also shows the shape for
private callees (`private_callees: ['_leased_bench_cascade']`). Re-run the
dry-run after each door; the `declared` / `unclassified after` pair is the
progress counter.

### Rank 3 — Re-baseline the architecture snapshot before any lane ranks work from it

Full evidence in §0. Summary `[MEASURED]`: `docs/architecture-state.json` fails
its digest and its own `counts.modules` (520) contradicts its own module list
(521), because merge `9831ddae` hand-resolved a generated file;
`.daedalusignore` is absent at HEAD so the gate cannot compare at all; the run
exits 1 with 22 blocking items, of which 12 are recovery kits that only appear
because the ignore file vanished.

**Why it ranks second:** it is not itself a Gate-0 exit criterion, but it is the
precondition for *trusting the ranking of everything else*, including this
document. It is also the cheapest item here — restore or re-author
`.daedalusignore`, then `python -m daedalus.mapping.drift --refresh`, then
**review the committed diff**, which is the entire point of the design
(`daedalus/mapping/drift.py:14-18`: `"islands": 6 -> 7` in a diff is a question
somebody has to answer out loud). Note that `--refresh` goes through the central
effect boundary (`cli.mapping_drift`), so it is a guarded write, not a free one.

**Do not** simply `--refresh` and bank the numbers: four modules are `VANISHED`
(in the snapshot, not on disk), including `daedalus/crew_hook.py`, which the bad
merge inserted. Confirm each deletion was intended before baking it in.

---

## 4. The effectful-entrypoint migration — the real Gate-0 number `[MEASURED]`

Master plan §11 Gate 0 requires "centralized start/guard path for every
effectful runtime entrypoint," and Revision 3 item 4 names "the remaining
effectful-entrypoint migration" as a closure requirement. Measured from
`daedalus.spine.effect_boundary.ENTRYPOINTS` at HEAD:

| Wiring | Count |
| --- | --- |
| `CENTRAL` | 83 |
| `LOCAL_GUARDS` | 7 |
| `INVENTORY_ONLY` | 8 |
| `ABSENT` | 1 |
| `UNGUARDED` | **0** |
| **total** | **99** |

**83 of 99 central; 16 rows remain.** `UNGUARDED = 0` is the good news and
should be stated as such: no effectful entrypoint is entirely unguarded.

The 16 rows, and — importantly — **which are gaps and which are deliberate**:

| Row | Wiring | Verdict |
| --- | --- | --- |
| `provider.claude` | `INVENTORY_ONLY` | **(c) deliberate blocker**, pinned by a test; falls when Rank 1 closes |
| `provider.codex` | `INVENTORY_ONLY` | **(b) gap** — `codex_cli` imports nothing from kernel/broker; `run()` takes no authorization |
| `provider.deepseek` | `INVENTORY_ONLY` | **(b) gap** — "busiest paid lane"; `contracts: []`; declares `SPEND`+`SECRETS`. Mitigated: its process-boundary CLI door *is* central |
| `provider.deepseek.rollback` | `INVENTORY_ONLY` | **(c) deliberate** — undo path; `begin_effect` refuses exactly when rollback is needed |
| `provider.ollama.rollback` | `INVENTORY_ONLY` | **(c) deliberate** — identical reason |
| `provider.ollama` | `LOCAL_GUARDS` | (c) guards exist locally |
| `provider.ollama_native` | `INVENTORY_ONLY` | **(c) deliberate** — the lane decision lives in the caller |
| `mcp.runtime` | `ABSENT` | (c) no MCP runtime boundary is implemented at all |
| `kernel.attempt.begin` / `.complete` / `.prepare` | `LOCAL_GUARDS` | (b) staged — blocked on persisted `EffectLease` + runtime-conformance authority + Docker sandbox |
| `python.promote_candidates` | `LOCAL_GUARDS` | (b) staged — Invariant 5 path; blocked on routing through a persisted `EffectLease` |
| `cli.daedalus`, `web.server` | `LOCAL_GUARDS` | (c) local guards documented |
| `runtimes.fault_attestation_issuer` | `INVENTORY_ONLY` | (b) reads a signing key from env; `contracts: []` |
| `runs.gate0_matrix.verify_whole_matrix` | `INVENTORY_ONLY` | **(b) seam rot** — target names a *dated* run directory; the row self-declares this "KNOWN FRAGILITY" |

Four of the eight `INVENTORY_ONLY` rows are **deliberate and reasoned in the
registry itself**. Any lane that "closes the gap" by flipping them to `CENTRAL`
would weaken the boundary, not strengthen it. The registry rows carry their own
migration conditions; read `notes` and `migration` before touching one.

A second, precise Gate-0 seam is recorded in
`scripts/declare_write_surfaces.py:165-170`: `daedalus/spine/attempt.py` **has
left** `LIVE_LANE_EXCLUSIONS` (only `daedalus/spine/receipts.py` remains), but

> `python.attempt` declares 0 surfaces (the `begin_effect` sits inside a `try`
> whose `else` branch carries the whole attempt, and the dominance rule counts
> only the statements AFTER the holder) and `python.command_gate` declares 2.
> Neither is lease-dominated.

Executed at HEAD `[MEASURED]`, that comment holds: `python.attempt` does not
appear in the per-door derivation at all, and `python.command_gate` reports
`declared: 2, lease_dominated: 0`. The door is wired and still declares nothing,
for a structural code-shape reason. Full numbers in Rank 2 above.

---

## 5. Full island / unreached table, `daedalus/` only `[MEASURED]`

Verdict key: **(a)** dead and deletable · **(b)** real unwired gap ·
**(c)** intentionally dormant per the master plan.

| Module | Class | Non-test importers | Meant to connect to | Verdict |
| --- | --- | --- | --- | --- |
| `runtimes/provider_invocation_authority.py` | island | 7, all unreached | broker / runtime receipts | (b) C1 |
| `runtimes/provider_invocation_registry.py` | island | — | broker | (b) C1 |
| `runtimes/provider_invocation_resolution.py` | island | — | broker | (b) C1 |
| `runtimes/provider_observation_store.py` | island | — | observation ledger | (c) additive strangler, see below |
| `runtimes/provider_observation_store_contract.py` | island | — | observation ledger | (c) additive strangler |
| `kernel/effect_recovery.py` | island | `runtimes/recovery.py` (unknown) | unknown-effect reconciliation | (b) C2 |
| `twin/extractors/contracts.py` | island | 4 (0 tests) | Forest v2 extraction | (c) Gate 2 |
| `twin/extractors/registry.py` | island | 1 (0 tests) | Forest v2 extraction | (c) Gate 2 |
| `twin/extractors/root_file_adapter.py` | island | 1 (0 tests) | Forest v2 extraction | (c) Gate 2 |
| `twin/extractors/tree_sitter_adapter.py` | island | — | Forest v2 extraction | (c) Gate 2 |
| `kairos/evolution.py` | island | none | Ariadne evolution | (c) Gate 3+ |
| `kairos/archive.py` | island | none | Ariadne archive | (c) Gate 3+ |
| `kairos/shadow_shell.py` | island | `kairos/evolution.py` (island) | Ariadne | (c) Gate 3+ |
| `eval/provenance.py` | island | `kairos/evolution.py` (island) | Ariadne evidence | (c) Gate 3+ |
| `wiki/links.py` | island | `wiki/__init__.py` (shim) | Knowledge plane | (c) Gate 2 |
| `wiki/vault.py` | island | `wiki/__init__.py` (shim) | Knowledge plane | (c) Gate 2 |
| `observe/shape.py` | island | `observe/__init__.py` (shim) | observation | (c) |
| `langgraph_adapter.py` | **orphan** | none | durable executor (plan §9.2) | (c) explicit `NotImplementedError` at `:26` |
| `decompose.py` | shim | **none** | — | **(a) deletable** |
| `drafts.py` | shim | **none** | — | **(a) deletable** |
| `mission_control.py` | shim | **none** | — | **(a) deletable** |
| `observe/__init__.py`, `wiki/__init__.py`, `twin/extractors/__init__.py` | shim | 1–4 | package facades | (c) keep while cluster dormant |
| `gates/fault_matrix.py` | unknown | — | Gate-0 exit matrix | (b/c) see below |
| `gates/repository_head_revision.py` | unknown | — | write-evidence gate | (c) dynamic dispatch |
| `gates/repository_write_artifact_{admission,cas,verifier}.py` | unknown | — | write-evidence gate | (c) dynamic dispatch |
| `gates/repository_write_evidence.py` | unknown | — | write-evidence gate | (c) dynamic dispatch |
| `runtimes/faults.py`, `runtimes/recovery.py` | unknown | — | fault matrix | (b) C2 |
| `runtimes/provider_target_receipt_retention_*` (7) | unknown | — | receipt retention | (c) staged packets |
| `runtimes/provider_target_verification{,_contracts}.py` | unknown | — | target verification | (c) staged packets |
| `runtimes/provider_executable_{structure,targets}.py` | unknown | — | target resolution | (c) staged packets |
| `runtimes/provider_invocation{,_identity}.py` | unknown | — | broker | (b) C1 |
| `structcore/artifacts.py` | unknown | 1 | structcore | (c) |

**On the `provider_*` cluster being labelled (c) rather than (b):** the
`unknown` classification here is largely honest, not a defect.
`daedalus/runtimes/provider_observation_store.py:10-13` states its own status:

> The historical auto-initializing ledger remains available for compatibility.
> Canonical effect registration, guard composition and broker migration are
> **separate reviewed packets**. Nothing in this module grants an Effect Lease,
> executes a provider, mutates a checkout, promotes, or closes a Gate.

These modules have their own Work Packets (`docs/work-packets/G0-RTC-06Y…`,
`…-06Z…`) and their own CI workflows (`.github/workflows/g0-provider-*.yml`),
so they *are* exercised — through pytest, which `reach.py` correctly refuses to
count as an entry point (`daedalus/mapping/reach.py:44-46`). They are staged,
not abandoned. What is genuinely missing is only the Rank-1 caller.

**`gates/fault_matrix.py` deserves a second look** by whoever owns the fault
matrix: Gate 0's stated exit condition is "a fault-injection matrix demonstrates
fail-closed protected effects," and both this module (`unknown`) and its CLI row
`runs.gate0_matrix.verify_whole_matrix` (`INVENTORY_ONLY`, with a self-declared
dated-directory fragility) sit outside the reachable set.

---

## 6. Owner decisions, not code gaps — and a correction to `docs/HANDOFF.md`

### 6.1 Genuinely pending owner actions `[MEASURED — directory listed at HEAD]`

`docs/decisions-pending/` contained exactly four files at committed HEAD. **In
the working tree it now contains three**: a concurrent lane moved
`promotion_allowed_signers.proposed` into `docs/decisions-taken/2026-08-25/`
during this survey `[MEASURED — working tree, uncommitted]`. That move is not
yet committed, so a reader of HEAD alone still sees four.

| File | What it decides | Blocks |
| --- | --- | --- |
| `promotion_allowed_signers.proposed` | which SSH keys may authorize promotion | **RESOLVED mid-survey** — moved to `docs/decisions-taken/2026-08-25/`, uncommitted. At HEAD it is still deliberately empty, so every promotion refuses; that was the correct state. |
| `AMENDMENT_DRAFT_classification_rung.md` | add a `central_started` disposition to the classification vocabulary | **owner** — touches the classification contract; "Ordinary sessions must not land this" |
| `B5_HANDOFF_COMMIT4.md` | wire the `attempt.py` door for effect leases | **partly superseded — see 6.3** |
| `b5_evidence_authentication_draft.patch` | make `evidence_authenticated` a composed boolean rather than constant `false` | **owner** — schema change |

Plus, from `docs/HANDOFF.md:27`: **pending owner action 4** — delete the 125
archived remote branches; kit at `docs/recovery/cleanup_2026-08-23/README.md`.
`[INHERITED — HANDOFF.md, dated 2026-08-23]` Not re-verified by this lane.

These four are **owner decisions, not integration gaps.** No lane should try to
"close" them today.

### 6.2 Every item in the `docs/HANDOFF.md` pending list is now stale

Drift, both sides cited `[MEASURED]`:

- **Doc side:** `docs/HANDOFF.md:22-25` still presents a three-item pending list.
  `:23` — "`promotion_allowed_signers.proposed` — signed approval root for
  promotion decisions." `:24` — "`control_root_migration.md` — the control-root
  migration; **loop refuses to arm until this runs**." `:25` —
  "`gated_writes_lease_handdown.patch` — sealed source pin bump for promotion
  seam." Repeated at `docs/HANDOFF.md:29`: "Control-root migration and sealed
  lease hand-down patch remain pending owner actions in
  `docs/decisions-pending/`."
- Item 1 (`:23`) went stale **during this survey** — see §6.1. Items 2 and 3
  went stale on 2026-08-23.
- **Truth side:** both files are in `docs/decisions-taken/2026-08-23/`, not
  `docs/decisions-pending/`.
  `docs/decisions-taken/2026-08-23/control_root_migration.md:1` opens
  "> TAKEN 2026-08-23 12:25Z (Athena, owner order 'arbeite weiter ans backend')"
  and carries MEASURED evidence: "`killswitch status` now reports the new path",
  "`git hash-object` = e7acc630… (matches the reviewed pin)",
  "test_loop_governance_head 12/12, test_loop_lease 15/15 (MEASURED)". Landed in
  commits `aa5923d4` and `21c6016e`.

The most alarming line in the handoff — **"loop refuses to arm until this
runs"** — is false at HEAD. A lane reading `HANDOFF.md` top-down today would
conclude the loop cannot be armed and would not attempt it.

**Recommended remedy (not applied — `docs/HANDOFF.md` is being edited by a
concurrent lane right now, and two writers in one block is how the next drift
gets made):** delete lines 23, 24, 25 and the trailing sentence of line 29
entirely, leaving pending action 4 (the 125 remote branches) plus the three
files that genuinely remain in `docs/decisions-pending/`. Deletion, not a
correction footnote — every resolution is preserved in
`docs/decisions-taken/2026-08-23/`, `docs/decisions-taken/2026-08-25/`, and
commits `aa5923d4` / `21c6016e`. Whoever owns `HANDOFF.md` this shift should
make this edit in the same beat as their current one.

### 6.3 `B5_HANDOFF_COMMIT4.md` is partly stale — its Commit-4 wiring has landed

`[MEASURED at HEAD]` The pending handoff instructs a future lane to (a) call
`record_primary_checkout_disjointness`, and (b) drop
`daedalus/spine/attempt.py` from `LIVE_LANE_EXCLUSIONS`
(`docs/decisions-pending/B5_HANDOFF_COMMIT4.md:40,53`). Both are already done:

- `daedalus/spine/attempt.py:1647-1657` imports and calls
  `record_primary_checkout_disjointness(...)` inside the lease-start path.
- `scripts/declare_write_surfaces.py:171-175`: `LIVE_LANE_EXCLUSIONS` now
  contains **only** `daedalus/spine/receipts.py`, and `:167` records that
  "`daedalus/spine/attempt.py` left this set when its lane released it."

What has **not** been superseded is the harder half, now restated more precisely
by the code than by the handoff: the attempt door declares **0 surfaces** for the
structural reason quoted in §4. A lane picking up this file should read
`scripts/declare_write_surfaces.py:165-175` first — it is newer than the handoff.

The handoff's headline claim — *"exactly one door in the system can hold a lease
at all"* — **was** re-verified by this lane and holds at HEAD `[MEASURED]`:
`scripts/declare_write_surfaces.py --dry-run` reports `lease_dominated: 1` for
`python.offload` and `lease_dominated: 0` for every other door. See Rank 2.
So `B5_HANDOFF_COMMIT4.md` is stale in its *instructions* (§6.3 above) and
accurate in its *diagnosis*. Do not discard the file; correct the two completed
steps and keep the diagnosis.

---

## 7. What this lane did not measure

Stated so the gaps in the inventory are legible rather than implied:

- **No test suite was run.** Nothing here claims a test passes or fails.
- **No write was performed by any instrument.** `drift` ran in compare mode
  (not `--refresh`) and `declare_write_surfaces.py` ran with `--dry-run`, so no
  declaration directory or CAS blob was produced.
- **No timing, throughput, or cost number is reported.** Ten lanes ran
  concurrently; every such figure would have been noise.
- **The `unknown` class was not individually adjudicated.** 22 modules are
  `unknown` because a string literal or a non-proving import names them.
  `reach.py` deliberately refuses to guess (`daedalus/mapping/reach.py:50-53`:
  "A gap is recoverable; a false accusation is not"). Resolving them one by one
  is separate work from wiring them.
- **`docs/HANDOFF.md:27` pending action 4** (125 remote branches) is inherited,
  not re-counted.

---

## Iron Plan footer

`Iron Plan: ALIGNED`
`Iron Gate: 0`
`Evidence:` read-only analysis at `2de997efe73f417f2cb82260ab944c2ff9562efa` —
(1) `daedalus.mapping.reach.analyse`: 294 `daedalus/` modules, 18 islands, 46
unreached, and the whole Gate-1 ignition path `reachable`/`entry`;
(2) `daedalus.spine.effect_boundary.ENTRYPOINTS`: 99 rows — 83 `CENTRAL`,
7 `LOCAL_GUARDS`, 8 `INVENTORY_ONLY`, 1 `ABSENT`, 0 `UNGUARDED`;
(3) `scripts/declare_write_surfaces.py --dry-run`: 442 surfaces, 31 declared,
411 unclassified, 150 undominated in door modules, exactly 1 of 21 doors
(`python.offload`) `lease_dominated`;
(4) `python -m daedalus.mapping.drift`: exit 1, `INVALID SNAPSHOT` (digest
mismatch; `counts.modules` 520 vs a 521-entry list) traced by `git diff` to
hand-resolution of a generated file in merge `9831ddae`, plus a missing
`.daedalusignore` that makes the baseline incomparable;
(5) zero `daedalus/` construction sites for `RuntimeBoundEffectAuthorization`
against 6 under `tests/`; zero production callers of
`harvest_effect_lease_terminal_records` against 8 test call sites;
(6) `docs/HANDOFF.md:24,25,29` contradicted by
`docs/decisions-taken/2026-08-23/control_root_migration.md:1` and commits
`aa5923d4`, `21c6016e`.
No `daedalus/` source file was modified. Nothing staged or committed.

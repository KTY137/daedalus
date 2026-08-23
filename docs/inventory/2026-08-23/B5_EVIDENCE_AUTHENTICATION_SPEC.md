# B5 — `evidence_authenticated` becomes derived (design, no code)

Lane HERACLES-B5-SPEC, 2026-08-23, worktree `b5-evidence-authentication`, HEAD `26a8b5eb`. Design only: no edits, tests or commits.
`tools/iron_plan_guard.py` **does not exist in this tree** (`find . -name iron_plan_guard*` → 0 hits) `[MEASURED]`; the mandated verify step could not
run, and the gap is reported rather than routed around. `ALIGNED`, Gate 0, invariants 4 / 7 / 9. Follows Codex room turn 54: "Konjunktion aller
anwendbaren, verifizierten Stufen; keine Sprosse."

## 0. Starting state

410 syntactic surfaces, 29 declared under 18 doors, 381 undeclared (`runs/gates/write-surface-classification/4fd2daa7…/derivation.json`) `[MEASURED]`;
142 undominated (`WRITE_SURFACE_CLOSURE.md` §9.3) `[INHERITED]`. Literal `"evidence_authenticated": False` in **8** modules: `classification.py:477`,
`effect_lease.py:392`, `evidence_materialization.py:174`, `origin.py:470`, `guard_structure.py:436`, `runtime_conformance.py:451`,
`source_anchor_semantics.py:495`, `guard_implementation_manifest.py:427` `[MEASURED]`. Only **6** runners pin it (§4). `report_v3.py:619` reads the flag
off the classification payload, and `report_v3.py:52-59` imports *only* `repository_write_classification` — none of the six downstream verifiers
`[MEASURED]`. That is Codex objection 2.

## 1. The derivation rule

**R1 — strict conjunction, per surface, over the applicable verified stages.** `authenticated(s) = ⋀ stage ∈ APPLICABLE(s) : verdict(stage, s) ==
verified`, with `APPLICABLE(s) ⊆ {materialization, origin, anchor, guard, conformity, lease}`. Never module-wide: a stage report says only that *its*
stage ran. An empty applicable set is **false**, never vacuously true.

**R2 — applicability is typed, derived from the row, never declared.** materialization / origin / anchor: always applicable (every row carries ≥1
`source_anchor`). guard: applicable iff `row.guard_contracts` is non-empty. conformity: applicable iff the retained execution replays runtime-bound;
`not_applicable` iff it replays as `NonRuntimeEffectAuthorization` (`effect_lease.py:642`). lease: applicable iff `row.production_reachable`; a
`RETIRED` row needs a retirement receipt instead (`classification.py:288`). `not_applicable` has exactly that one binding, and it is a **replay fact** —
`project_classification_input` has no key for it, so writing JSON can never mint one.

**R3 — no rung for "centrally started, no write contract".** That surface stays `inventory_only` (`WRITE_SURFACE_CLOSURE.md:358`). Mechanically: such a
row has no `guard_contracts` and no lease evidence, so its applicable `lease` stage is absent → conjunction false, and `production-write-inventory_only`
stays in `candidate_blockers` (`classification.py:300-308`). The overclaim is refused by construction, not by review.

## 2. The three producers

### 2.1 `effect_lease_receipt` — two phases; the draft gets phase B wrong

**Phase A (grant time)**, as the draft has it: after `authorization.grant()` in `acquire_wave_offload_lease` (`offload_lease.py:1042-1051`), persist the
grant record — `lease.receipt()` plus `source_revision`, `mission_id`, `attempt_id`, `request_sha256`, `positions`, `granted_at`, `record_sha256` — via
`daedalus.atomic.publish_bytes_once` into `control_root(repo_root)/effect-lease-receipts/<source_revision>/<sha>.json`. Outside the checkout, so the
candidate the lease bounds cannot reach the evidence about it (invariant 3). Emission failure is recorded on the lease (`receipt_error`) and never
revokes a granted capability.

**Phase B (termination)** is what the chain consumes, and the draft omits it. `verify_repository_write_effect_leases` demands `payload.receipt_schema ==
"daedalus-effect-lease-receipt/1"` (`effect_lease.py:60`, checked `:786`) and a **terminal** state (`:793-797`). The draft mints
`daedalus-effect-lease-grant-receipt/1` and says so in its own comment — the verifier rejects it. `daedalus-effect-lease-receipt/1` occurs nowhere as a
produced id: only `effect_lease.py:60` and two test fixtures `[MEASURED]`.

Evidence object, exact key sets (`effect_lease.py:740-748` envelope, `:766-769` payload): `{schema:"daedalus-gate0-repository-write-evidence-object/1",
kind:"effect_lease_receipt", source_revision, surface_sha256: surface_binding_sha256(rev,surface), guard_contract:"", subject_sha256:
evidence_subject_sha256(binding), payload_sha256, payload:{receipt_schema:"daedalus-effect-lease-receipt/1", receipt_sha256:
EffectTerminalReceipt.receipt_sha256 (`effects.py:182-192`), entrypoint_id: the dominating door's `EntrypointSpec.id`, terminal_state: outcome.lower()}}`.
Lowercase is load-bearing: the kernel stores `{"COMPLETED","FAILED","CANCELLED"}` (`effects.py:45`) while the gate compares `replay.state.lower()`
against the lowercase set (`effect_lease.py:65`, `:568`) `[MEASURED]`. Nothing new is minted — the terminal receipt exists and is already projected by
`inspect_effect_execution` (`effect_replay.py:577`); the missing producer is the **binding of it to a surface**. Verifier: `effect_lease.py:414`, which
also needs one `EffectLeaseReplaySubject` per `receipt_sha256`, all already durable in the effect ledger.

### 2.2 `primary_checkout_disjointness_receipt` — recorded, never re-derived

Predicate: `primary_tree.planned_overlap_reason` (`daedalus/primary_tree.py:356`, 0f7f8187). Its two decision points are `attempt.py:2468`
(`GuardDecision("containment.worktree", overlap is None, …)`, `:2470`) and `offload_lease.py:383`. The producer **records that decision object**; calling
the predicate a second time attests a different moment than the guard that allowed the write.

Record: `{receipt_schema:"daedalus-primary-checkout-disjointness-receipt/1", decided_at, predicate:"primary_tree.planned_overlap_reason",
primary_checkout_realpath, target_root_realpath, overlap_reason:null, disjoint:true, decision_reason, receipt_sha256}`, stored beside the lease receipts
under `control_root(...)/disjointness-receipts/<source_revision>/`. Evidence payload, exact keys (`evidence_materialization.py:436-458`):
`{receipt_schema, receipt_sha256, primary_checkout_sha256, target_root_sha256, disjoint:true}`. The two fingerprints must be **pinned by definition** —
proposal `sha256(canonical_json(<resolved absolute path string>))` — because the verifier checks only 64-hex shape (`materialization.py:450-455`) and two
producers disagreeing would never be caught `[MEASURED]`.

Honest boundary: `primary_checkout_disjointness_verified` stays `False` in five modules (`effect_lease.py:389`, `runtime_conformance.py:448`,
`guard_structure.py:444`, `source_anchor_semantics.py:503`, `guard_implementation_manifest.py:435`) `[MEASURED]`. This receipt does **not** clear
`primary-checkout-disjointness-semantic-verification-missing`, and `closed` stays `False`. B5 raises `evidence_authenticated`; it does not close Gate 0.

### 2.3 the conformity variant — typed `not_applicable`, honestly relaxed

Option (a), minting a repo-write `runtime_conformance_receipt` per surface, is **rejected**: its payload demands a non-empty `runtime_id` and
`conformant:true` (`evidence_materialization.py:420-433`), and a CLI door writing a file has no adapter runtime. Filling that field is fabrication.

Option (b), taken: typed `not_applicable` bound to `NonRuntimeEffectAuthorization` (`effect_lease.py:642`). That branch already yields `runtime_id=None,
trust_sha=None`, and `effect_lease.py:603-606` already *refuses* a non-runtime subject that carries runtime authority — the fail-closed half exists; only
the record shape is missing.

The one-receipt-per-surface rule is **relaxed, not satisfied**. `runtime_conformance.py:549-556` today: "every production classification requires exactly
one runtime receipt". New rule: *exactly one, unless the surface's retained execution replays as `NonRuntimeEffectAuthorization`, in which case exactly
zero and the report carries a `not_applicable` record naming the `execution_id` it replayed.* Wire consequence: bump
`daedalus-gate0-repository-write-runtime-conformance/1 → /2` (one-id-one-shape), and `effect_lease.py:585-590` ("runtime predecessor record is missing for
effect surface") must accept that record.

**Blocking precondition, measured:** `runtime_conformance.py:542` and `effect_lease.py:482` both refuse the whole run when *any* production-reachable row
is not `CENTRAL`. The chain is all-or-nothing per report — it runs only over a classification whose every production row is already `CENTRAL`. §5 is
written around that.

## 3. The terminal chain result

New module `daedalus/gates/repository_write_chain_result.py`, new wire id `daedalus-gate0-repository-write-chain-result/1`: `source_revision`,
`inventory_digest`, `classification_digest`, the six `stage_digests`, and per surface `{surface_sha256, path, line, column, origin, stages:{lease,
materialization, origin, anchor, guard, conformity} → verified | not_applicable | absent, not_applicable_binding, authenticated}`, plus
`authenticated_surface_count`, `applicable_surface_count`, `evidence_authenticated` (the R1 conjunction over all classified rows) and `digest`.

`report_v3.py:619` stops reading the classification payload. It gains a `repository_write_chain_result_input=` **locator** (the pattern
`repository_write_classification_input=` already uses), refuses it unless the chain result's `classification_digest` equals the digest of the
classification report `report_v3` itself projected (`chain-result-refused`, clears nothing), and only then reads the flag. No locator → today's aggregate
blocker fires unchanged. `report_v3` never touches keyrings, subjects or ledgers.

Composed kinds grow **3 → 6**. The draft's `AUTHENTICATED_EVIDENCE_KINDS` names only `EFFECT_LEASE_RECEIPT`, `PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT`,
`RUNTIME_CONFORMANCE_RECEIPT` (Codex objection 1). The terminal object must also name `SOURCE_ANCHOR` (authenticated by `source_anchor_semantics.py:519`
against exact source bytes), `GUARD_CONTRACT` (by `guard_structure.py:460` against the signed manifest) and `RETIREMENT_RECEIPT`
(`classification.py:288`); materialization and origin authenticate all six. The draft's `SurfaceEvidenceAuthentication` and
`surface_evidence_authenticated` are kept and moved into the new module; `required_authenticated_kinds` is replaced by R2's table. The draft's change to
`classification.py`'s own payload flag is **dropped** — the early classification keeps its literal `False`, which stays true and stays pinned.

## 4. Commit shape — the six runners and the new anchors

Pinning `('"evidence_authenticated": False', '"evidence_authenticated": True')` today `[MEASURED]`:
`run_repository_write_classification_mutations.py:20-21` (`classification.py:477`), `run_repository_write_evidence_origin_mutations.py:23-24`
(`origin.py:470`), `run_repository_write_guard_structure_mutations.py:21-22` (`guard_structure.py:436`),
`run_repository_write_runtime_conformance_mutations.py:21-22` (`runtime_conformance.py:451`),
`run_repository_write_source_anchor_semantics_mutations.py:21-22` (`source_anchor_semantics.py:495`),
`run_guard_implementation_manifest_mutations.py:21-22` (`guard_implementation_manifest.py:427`).

**Two literals are unpinned.** `effect_lease.py:392` has no runner anchor at all, and `run_repository_write_evidence_materialization_mutations.py:20-21`
pins `origin_authenticated`, not `evidence_authenticated`, so `evidence_materialization.py:174` is unguarded `[MEASURED]`. The commit adds both pins or it
leaves the hole it was written to close.

All six keep their existing anchor (their literal is unchanged and still means "this stage alone does not authenticate"). New anchors, same commit:
`run_repository_write_classification_mutations.py` +2 (required-stage loop → `pass`; unbound-authentication `raise` → `if False`); new
`scripts/run_repository_write_chain_result_mutations.py` +4 (`'"evidence_authenticated": authenticated,'` → `True`; conjunction body → `return True`;
empty-set guard `return False` → `return True`; applicability table → every stage `not_applicable`); `run_repository_write_runtime_conformance_mutations.py`
+1 (relaxed rule → accept zero receipts unconditionally); `run_gate_report_v3_mutations.py` +1 (chain-result binding check → `if False`). Every anchor must
resolve **exactly once**, the house rule already governing the classification runner's nine.

## 5. Scope cap — and why the Gate-1 doors are the wrong slice

Gate-1 slice doors, from `derivation.json:per_door` `[MEASURED]`: `cli.loop` → `daedalus/loop.py:1632:13` (`driver.run()`); `cli.picker` →
`daedalus/spine/picker.py:2970:13` (`run(top, args)`); `cli.eval` → `daedalus/eval/__main__.py:49:8` and `50:8` (`sys.stdout.buffer.write`). Three doors,
four surfaces of the 29.

Resolving all 29 through the AST `[MEASURED]`: 6 dispatch `.run()` handles; 6 `file_bridge` `mkdir`s on `OUTBOX/INBOX/ARCHIVE`, all defined as `ROOT / …`
with `ROOT = Path(__file__).resolve().parents[1]`, i.e. **inside** the primary checkout (`file_bridge.py:20-23`); 13 caller-supplied
`Path(args.X).write_text` / `out.write_text`; 3 stdout writes; 1 `create_subprocess_exec`. Every row is `target=unknown, guard=inventory_only`
(`classification-input.json`).

**Zero of the 29 can reach `central` in B5**: `central` is refused for a `primary_checkout` or `unknown` target (`classification.py:265-268`), and the
chain refuses to run while any production row is non-`central` (§2.3). The Gate-1 doors' four surfaces sit in the three worst categories.

Recommendation: cap B5 at the **two `daedalus/spine/attempt.py` doors skipped at `4fd2daa7`** (§9.3, "held by another lane"). Attempt writes land in a
`TaskAttempt` worktree — exactly the target `planned_overlap_reason` proves disjoint and exactly the effect the lease covers, so all six stages have a
real subject. Declare them on a clean commit (`scripts/declare_write_surfaces.py`), run the chain over that scoped report only, leave the other 408
surfaces `unclassified`/blocked. Projection: the remaining 27 declared surfaces each need a `TargetDisposition` per calling door before they are
eligible; 381 undeclared and 142 undominated are untouched by B5.

## 6. Kill criteria — what would show the derivation is vacuous

1. A surface authenticates after one byte of its retained evidence changes (the `sha256`/`surface_sha256` binding did not bite). 2. `not_applicable`
covers a surface whose execution replayed runtime-bound — a runtime writer excused by the conformity stage. 3. `evidence_authenticated` is `True` on a
report with zero classified rows, or with an empty applicable set for any row. 4. An `inventory_only` or `unguarded` row authenticates (R3 breached).
5. Deleting any one stage leaves every surface's verdict unchanged (the conjunction is not load-bearing). 6. The chain result authenticates against a
foreign `classification_digest`, or a hand-written JSON passed as `repository_write_chain_result_input` flips `report_v3` with no verifier run. 7. Any of
the four new runner anchors survives its mutation.

## 7. Tests the build lane must write (node ids)

`tests/gates/test_repository_write_chain_result.py::` → `test_conjunction_is_false_when_one_applicable_stage_is_absent`,
`test_empty_projection_is_not_vacuously_authenticated`, `test_not_applicable_requires_a_non_runtime_replay_binding`,
`test_inventory_only_row_never_authenticates`, `test_tampered_evidence_byte_breaks_the_surface_binding`,
`test_authentication_naming_unretained_evidence_is_refused`.
`tests/gates/test_repository_write_chain_result_review.py::` → `test_flag_is_not_a_literal_in_either_direction`,
`test_schema_does_not_pin_evidence_authenticated_to_a_const`.
`tests/gates/test_gate_report_v3_chain_result.py::` → `test_report_reads_the_terminal_result_not_the_classification`,
`test_chain_result_bound_to_a_foreign_classification_is_refused`, `test_absent_chain_result_keeps_the_unauthenticated_aggregate`.
`tests/gates/test_repository_write_runtime_conformance.py::` → `test_zero_runtime_receipts_allowed_only_for_a_non_runtime_replay`,
`test_runtime_bound_replay_still_requires_exactly_one_receipt`.
`tests/kernel/test_effect_lease_grant_receipt.py::` → `test_grant_receipt_is_published_once_outside_the_checkout`,
`test_receipt_emission_failure_never_revokes_a_granted_lease`.
`tests/gates/test_repository_write_effect_lease.py::` → `test_grant_schema_is_not_accepted_as_chain_evidence`,
`test_terminal_state_is_lowercased_from_the_kernel_receipt`.
`tests/gates/test_primary_checkout_disjointness_receipt.py::` → `test_receipt_records_the_guard_decision_without_re_deriving_it`,
`test_fingerprints_are_the_pinned_path_digest`.

Each must go red when its guard is disabled; §4's anchors are the mechanical proof.

## 8. Open questions for Momus

1. **Scope.** Is moving the cap off the Gate-1 doors onto the two skipped `attempt.py` doors a scope change the mission's B5 forbids, or the only honest
   reading of "the Gate-1 slice's doors first" given §5's measurement that none of their surfaces is eligible?
2. **stdout.** `sys.stdout.buffer.write` is `NON_REPOSITORY`, which `classification.py:247-251` says needs a disjointness receipt — but that payload
   demands a `target_root_sha256` and stdout has no root. New evidence kind, or is stdout simply not a repository-write surface and the scanner
   over-collects?
3. **Wire.** Separate `…-chain-result/1`, or bump `classification/1 → /2` and drop the now-ambiguous `evidence_authenticated` key so one name never
   carries two meanings?
4. **Relaxation.** Loosening `runtime_conformance.py:549-556` weakens a fail-closed rule. Is the `NonRuntimeEffectAuthorization` binding enough, or must
   the `not_applicable` record also be collector-signed like every other stage?
5. **Hole.** The two unpinned literals are pre-existing. Fix inside B5, or split out so B5's diff stays one packet?

---

`Iron Plan: ALIGNED` · `Iron Gate: 0` ·
`Evidence: design only — no edits, no tests, no commits. Measured at HEAD 26a8b5eb: 8 literal sites, 6 runner pins, 2 unpinned literals; all 29 declared surfaces resolved through the AST (0 eligible for central); report_v3 imports only the classification module. tools/iron_plan_guard.py absent from this tree, so the mandated verify step could not run.`

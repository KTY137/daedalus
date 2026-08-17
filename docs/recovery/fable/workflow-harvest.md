# Workflow harvest — 20-lane repair workflow wf_1e718951-0ff

Lane: workflow-harvest (Fable long-context analysis, 2026-08-17)
Classification: ALIGNED (read-only harvest; this report file is the only write)

Sources read in full:
- Journal: `C:/Users/nukei/.claude/projects/c--Users-nukei-Desktop-agent-env/ce2c55b7-b294-4fd7-bf94-ab23c51850fb/subagents/workflows/wf_1e718951-0ff/journal.jsonl` (37 lines at harvest time, all read)
- Recon synthesis: `.../tasks/wid5h0od3.output` (417 KB JSON; verdict, 17 work items, 10 lane headlines, counts extracted)
- `docs/recovery/WINDOWS_PORTABILITY_FINDINGS_20260817.md` (full)
- `docs/recovery/fix_fsync_readonly_windows.patch` (full)

## 0. Journal status — the workflow is NOT finished

- 20 lanes started (`type:"started"` lines 1–34), **17 results** returned, **3 lanes still running** at harvest (their agent logs were last written 12:31, after the journal's last write 12:28):

| missing lane | agentId | started | log size at harvest |
| --- | --- | --- | --- |
| gates-repository-write | a7972f5df36227d26 | 11:53 | 713 KB (still growing) |
| windows-crlf-sweep | a073093b139d2fec4 | 11:58 | 422 KB (still growing) |
| vet-review | a95f1288c0c7d1e1b | 12:16 | 368 KB (still growing) |

These are RUNNING, not dead — do **not** re-dispatch yet; re-read the journal before landing anything in their likely territories (repository-write inventory scanner tests, the `Path.write_text` CRLF file list, `daedalus/tools/vet.py`).

- **The journal contains NO review-verdict records.** Only `started` and `result` line types exist. The "review verdicts" this harvest was told to expect are absent from the journal. Every `safe_to_land?` below is therefore MY assessment derived from the lane's own evidence and cross-lane corroboration, explicitly marked as such — it is not an independent reviewer's verdict. (ASSUMED: reviews may exist in the three unfinished agents or elsewhere; not found in this journal.)

- Lanes worked in per-lane worktrees (e.g. `C:/Users/nukei/Desktop/wt_misc-red`, `wt_boundary-inventory`). Diffs live in the journal and those worktrees; **nothing is committed** — the trunk rejects commits because `python tools/iron_plan_guard.py verify` exits 1 (see §5.1).

## 1. Consolidated ledger

Verdict column: my assessment (no journal reviews exist). "prod?" = production_code_touched as self-reported.

| # | lane | outcome | measured before → after | prod? | safe_to_land? (harvest assessment) |
| --- | --- | --- | --- | --- | --- |
| 1 | artifact-fixture | fixed | 11F/7P → 18P (2 gates test files); dependent chain 20P | no | YES — test-only, tightens an assertion (ValueError→Gate0ReleaseBlocked, same match) |
| 2 | effectscope-question | diagnosed-not-fixed | 25F/41P → 25F/41P (unchanged by design) | no | n/a — investigation lane; wiring proposal is future work |
| 3 | faultmatrix-evidence | fixed | tests/gates 118F/607P → 117F/610P; lane 7F/66P → 6F/69P | **yes** (`daedalus/gates/fault_matrix.py`) | YES with 2 decisions: matrix_sha256=receipt digest (judgment call), required `executed_at` kwarg. Must co-land with #5 (same file) |
| 4 | kernel-scope-writable | fixed | tests/kernel 69F/351P → 45F/375P; deterministic pair 25F → 25P | no | YES — test-only; note scope overrun (3 clusters in one diff, cleanly separable hunks) |
| 5 | faultmatrix-exact-state | fixed | tests/gates 118F/607P → 116F/609P | **yes** (fault_matrix.py + wire schema JSON) | YES with decision: schema gains REQUIRED field under unchanged id `/1` — breaking for externally archived receipts (none found in-repo) |
| 6 | runtimes-obsstore | fixed | 16F/11P → 27P (obsstore files) | **yes** (`_fsync_file` O_RDWR) | PARTIAL — take its 2 test hunks; REPLACE its fsync hunk with `docs/recovery/fix_fsync_readonly_windows.patch` (O_WRONLY-on-nt, adversarially Codex-reviewed, least-privilege, identical measured effect 8 fixes) |
| 7 | runtimes-retention | fixed | lane 19F/13P → 32P; tests/runtimes 57F/679P → 38F/698P | no | YES — test-only, mutation-tested all 3 drift fences |
| 8 | runtimes-recovery | partially-fixed | 7F/16P → 6F/17P | no | YES for its 1 test fix (AST raise assertion, mutation-tested). Its REFUSED cluster (dead `inspect_runtime_effect_execution`) is superseded by lane 10, which fixed it |
| 9 | kernel-scope-cost | fixed | 33F/1P → 7F/27P (3 files) | no | YES — test-only, 3× `max_cost_microusd=0`; remaining 7 = separate `fixture.guard` registry cluster (unowned) |
| 10 | inspect-readonly | fixed | lane 22F/1P → 14F/9P; kernel+gates+runtimes 245F/1636P → 230F/1651P (14 real fixes, 0 regressions, flake accounted) | **yes** (effect_replay.py, runtime_effect_replay.py + review-test rewrite) | YES — recon blocking work item 2; needs second reader on the review-test rewrite (lane argued it convincingly; no guard weakened, authorization.py untouched) |
| 11 | guard-tests | diagnosed-not-fixed | 7F/41P → 7F/41P (unchanged by design) | no | n/a — all 7 failures = one root cause in `tools/iron_plan_guard.py` (protected; repair needs owner). Simulated repair: 47/1 with adjacent-blob read, 48/0 with canonical-blob fallback |
| 12 | runtimes-conformance | fixed | 9F/2P → 11P; runtimes+kernel 126–127F → 117F, zero new fails | no | PARTIAL — take `test_runtime_terminal_fence.py` rewrite (uncontested, mutation-tested). `test_runtime_conformance_profiles.py` CONFLICTS with lane 14 — pick one (see §3) |
| 13 | gates-stdlib-delta | fixed | lane 6F/9P → 15P; tests/gates 118F → 112F, zero regressions | **yes** (`_safe_relative_posix` platform-independent) | YES — owns `test_repository_write_stdlib_delta_cli_schema.py` outright (its version also fixes the gzip/zipfile fixture defect lane 14 left red) |
| 14 | windows-exec | fixed | 11F/3P → 1F/13P; tests/runtimes 57F → 52F | no | PARTIAL — take `test_repository_write_inventory_cli.py` hunk; DROP its stdlib_delta_cli_schema hunk (subsumed by 13); conformance_profiles hunk conflicts with 12 |
| 15 | ignition-slice | diagnosed-not-fixed | 4P → 4P (unchanged by design) | no | n/a — Gate-1 gap analysis (no MissionContract/WorkItem/isolation/replay); ordered path A–E recorded; post-Gate-0 work |
| 16 | misc-red | fixed | 4 files 4F/52P → 56P; kernel+dotenv 69F/367P → 68F/368P | no | YES — test-only; the SpineLedger-substring review-test rewrite is the one judgment call (refutation-tested 5 ways) and deserves a second reader |
| 17 | boundary-inventory | fixed (doc) | 20P → 20P (doc-only lane) | no | YES as documentation — new untracked `docs/GATE0_EFFECT_BOUNDARY_INVENTORY.md` in `wt_boundary-inventory` (374 lines, sha256 cd21c3cd…); copy into trunk docs/ |
| 18 | gates-repository-write | **NO RESULT — still running** | — | — | re-check journal |
| 19 | windows-crlf-sweep | **NO RESULT — still running** | — | — | re-check journal |
| 20 | vet-review | **NO RESULT — still running** | — | — | re-check journal |

Aggregate honesty note: per-lane numbers overlap in scope (several lanes measured tests/gates or tests/kernel wholesale) and the kernel suite is measurably flaky (69/70/71 on identical trees — lane 4; a named order-dependent flake in test_isolated_attempt_lifecycle.py seen by lanes 4, 10, 12). Do NOT sum the deltas. The only sound statement: every landing lane demonstrated a strictly shrinking failure-name set in its own scope with zero verified regressions.

## 2. Production changes in the batch (the review surface)

1. `daedalus/gates/fault_matrix.py` — TWO lanes (3, 5), interlocking edits, land as one commit:
   - lane 5: `verify_fault_matrix_run` subset → exact tuple equality; `exact_durable_states_verified` claim in to_dict/from_dict + wire schema `configs/schemas/fault-matrix-contract.schema.json` (REQUIRED field, id unchanged — decide `/1`→`/2`).
   - lane 3: `to_fault_matrix_evidence` un-broken (was TypeError on 100% of calls — recon blocking item 3): `matrix_sha256=self.digest`, required keyword `executed_at`, real ContractProvenance.
   - Both edited `tests/gates/test_fault_matrix_contract_review.py` at different assertions — merge both; the pins are compatible (lane 5 replaced the issubset pin; lane 3 replaced the failure_count pin with 11 stricter pins).
2. `daedalus/kernel/effect_replay.py` + `runtime_effect_replay.py` (lane 10) — new `PersistedEffectLeaseSubject`, shared `_project_persisted_execution`; kills the born-dead `inspect_runtime_effect_execution` (recon blocking item 2). authorization.py untouched; both public signatures and isinstance gates preserved; review test re-anchored and strengthened (forbids the NonRuntimeEffectAuthorization downgrade by AST).
3. `daedalus/runtimes/provider_observation_store.py` `_fsync_file` (lane 6 + recovery patch) — one-line flag fix; **decision: land the `docs/recovery/fix_fsync_readonly_windows.patch` version** (`O_WRONLY if os.name == "nt" else O_RDONLY`): least privilege, POSIX path byte-identical to today, independently reviewed; lane 6's `O_RDWR` is functionally equivalent (both measured 8 fixes) but broader and changes POSIX behavior too.
4. `daedalus/gates/repository_write_stdlib_delta.py` `_safe_relative_posix` (lane 13) — PurePosixPath+PureWindowsPath; strictly stronger on both platforms (also rejects `C:a.py`, UNC). Lane flagged that daedalus/gates sits in guarded territory; classified ALIGNED bug-fix, not policy change.

No lane touched protected policy artifacts. No guard, validator, or assertion was weakened anywhere in the batch per self-report + refutation runs; the two review-test rewrites (lanes 10, 16) are the items needing a second reader to confirm that claim.

## 3. Conflict map (must be resolved at landing)

| file | lanes | resolution |
| --- | --- | --- |
| `daedalus/gates/fault_matrix.py` + `tests/gates/test_fault_matrix_contract_review.py` | 3 + 5 | co-land as one commit; merge both review-test edits (disjoint assertions) |
| `daedalus/runtimes/provider_observation_store.py:436` | 6 vs recovery patch | take the patch (O_WRONLY nt-branch); keep lane 6's two test hunks |
| `tests/runtimes/test_runtime_conformance_profiles.py` | 12 vs 14 | full-file conflict, both green in isolation. Recommend lane 14 (windows-exec): it uses the canonical kernel primitive `daedalus.spine.cancel.ManagedProcess` instead of shelling to `taskkill /F /T` — the one-kernel-aligned choice — and it surfaced the `ManagedProcess.cancel()` sharp edge (win32 tree not guaranteed dead until `close()`, measured with a live grandchild). Lane 12's version is the fallback (its mutations were killed 1:1). Whichever is picked, keep lane 12's `test_runtime_terminal_fence.py` rewrite — separate file, no conflict |
| `tests/gates/test_repository_write_stdlib_delta_cli_schema.py` | 13 vs 14 | take lane 13 wholesale (its PYTHONPATH hunk + zipfile fixture fixes the test fully; lane 14's version leaves it red); drop lane 14's hunk for this file only |
| `tests/kernel/test_effect_replay_projection.py` | 9 feeds 10 | dependency, not conflict: lane 9's `max_cost_microusd=0` un-reds the fixture lane 10's verification runs through — land 9 before or with 10 |
| runtimes-recovery refusal vs inspect-readonly fix | 8 vs 10 | lane 10 supersedes lane 8's refused cluster and already rewrote the review test lane 8 said blocked the fix; lane 8's own delivered test fix is independent and lands cleanly |

## 4. Landing order (for when the trunk becomes committable)

**Gate: the trunk is not committable today.** `python tools/iron_plan_guard.py verify` exits 1 ("daedalus/kairos/gated_writes.py exposes automatic promotion") — reported independently by lanes 5, 7, 11, 16, and recon work item 1. Repairing the guard is step 0 and is OUTSIDE this workflow's results (protected artifact; guard-tests lane delivered the exact repair spec: read the exec'd blob adjacent to gated_writes.py AND fall back to the canonical blob, else its 7th test stays red; adding `_gated_writes_legacy.py.src` to PROTECTED_PATHS is a protected-artifact change needing owner sign-off).

Environment prerequisites for every landing measurement (from WINDOWS_PORTABILITY findings + lanes 13/14): the user-site editable install (`__editable__.daedalus-0.1.0.pth`) pins `daedalus` to the stale primary checkout — run `pip install -e .` from the trunk worktree or export `PYTHONPATH` for every subprocess-spawning test; and keep LF worktrees (`-c core.autocrlf=false -c core.eol=lf`).

Then, in order:

- **Wave 1 — test-only, conflict-free (any order, small commits):**
  1. kernel-scope-cost (9) — unlocks wave 2's verification
  2. kernel-scope-writable (4)
  3. artifact-fixture (1)
  4. runtimes-retention (7)
  5. runtimes-recovery's single test fix (8)
  6. misc-red (16) — flag the durability-review rewrite for a second reader in the commit message
- **Wave 2 — production, review-first:**
  7. fsync patch (recovery version) + runtimes-obsstore test hunks (6)
  8. inspect-readonly (10) — after 9; second reader on the review-test rewrite
  9. gates-stdlib-delta (13)
  10. windows-exec (14) minus the two conflicted files, per §3
  11. conformance-profiles decision + runtimes-conformance terminal-fence rewrite (12/14, per §3)
- **Wave 3 — fault-matrix pair, one commit:**
  12. faultmatrix-exact-state (5) + faultmatrix-evidence (3) merged; decide schema `/2` and matrix_sha256 semantics in the commit message
- **Wave 4 — docs/evidence:**
  13. copy `GATE0_EFFECT_BOUNDARY_INVENTORY.md` from `wt_boundary-inventory` into docs/
  14. retain the three diagnosis reports (2, 11, 15) as evidence artifacts

## 5. Lanes returning nothing / blocked / needing NEW dispatch

**Still running (await, then harvest again):** gates-repository-write, windows-crlf-sweep, vet-review (§0).

**No lane owned these — every one was independently reported by ≥2 lanes and none fixed them; each needs a fresh dispatch:**
1. `tests/gates/test_gate0_release_cli.py` collection ImportError (`load_gate_evidence_index` missing from `daedalus.gates.evidence`) — aborts bare `pytest tests/gates`; reported by lanes 1, 3, 5, 9, 10, 12, 13, 14.
2. `tools/iron_plan_guard.py` sealed-promotion repair (guard-tests handoff spec; protected — owner/amendment path).
3. Mutation-harness shadowing defect: `scripts/run_fault_matrix_exact_durable_mutations.py` never imports its sandbox mutant (cwd shadows PYTHONPATH under `python -m` on 3.10; editable install is a second route back); PROVEN by lane 5 with a raise-only sandbox module reporting 9 passed. All sibling mutation scripts suspect. Every green mutation verdict from these harnesses is currently unreliable.
4. `fixture.guard` unknown guard-contract cluster (7 remaining failures in `test_repository_write_effect_lease.py`, lane 9).
5. CLI hermeticity class fix — shared conftest/bootstrap for all subprocess CLI tests (lanes 13/14 fixed 3 files; `test_gate_baseline_cli.py`, `test_gate_report_v3_cli.py`, `test_provider_observation_persistence_inventory_cli.py` still non-hermetic).
6. CRLF `Path.write_text` sweep — lane 7 measured `tests/gates/test_repository_head_revision.py` at 11F for this cause alone and listed 8 more files; likely the running windows-crlf-sweep lane's territory — check before dispatching.
7. `RETENTION_ENTRYPOINT` (`provider.target-receipt.retain`) not in the effect-boundary registry — that runtime family refuses in production (effectscope-question secondary finding; intentional-staging-vs-defect undecided).
8. Cross-file private-helper chain in tests/gates (3-level `spec_from_file_location`) — consolidation lane proposed by lane 1.
9. `ManagedProcess.cancel()` win32 semantics decision (lane 14: cancel() alone can leave a live grandchild; contract vs. verify-empty-before-success).
10. Base repository-write inventory scanner defect: `_open_mode(method=True)` reads the FILENAME as the mode (lane 13) — and per the portability findings the receiver-type gap (`Path('x').write_text` unresolvable without inference) is the platform-independent core of the largest (~112 ValueError) cluster; likely the running gates-repository-write lane's territory — check before dispatching.
11. Effect-broker composition root (effect_policy.py + effect_broker.py + kill-switch generation counter) — effectscope-question's full proposal; a deliberate Gate-0 design decision with stated security risks, not a bug fix.

## 6. Cross-checks against the recon plan (wid5h0od3)

Recon's four "real distance" items vs. this workflow's output:
- guard red + lost promotion check → DIAGNOSED with repair spec (lane 11), not fixed (protected).
- `inspect_runtime_effect_execution` raises on 100% of inputs → **FIXED** (lane 10).
- fault-matrix→evidence projection TypeError → **FIXED** (lane 3).
- 52/53 entrypoints not CENTRAL → POPULATION ESTABLISHED as 165 targets/114 unregistered, floor not total (lane 17); migration itself untouched (recon item 8, large).

Also closed from recon's list: exact durable-state equality (item 4 → lane 5), the four-schema-drift test debt (item 5 → lanes 1/4/9 covered its named files). Untouched recon items: 6, 7, 12–17 (incl. locator drift in RUNTIME_FAULT_CATALOG, schema deliverable decision, CI workflow pointing, doc re-stamps).

Portability doc cross-check: the ~240 genuine failures at the pristine tip remain the baseline reality; this workflow's 14 landing lanes attack exactly those clusters. The fsync (8) and PYTHONPATH (6) environment failures are both now covered by wave-1/2 items. Defect 1 (byte-exact resources vs EOL, 9 pinned files, 6 uncollectable modules) requires AMENDMENT_PROPOSAL_004 (`.gitattributes` is protected) and no lane could touch it.

---
Iron Plan: ALIGNED
Iron Gate: 0
Evidence: journal wf_1e718951-0ff read in full (37 lines, 20 started/17 results); recon JSON structure + plan extracted; 3 unfinished agents identified by name from their own logs; all before/after numbers quoted verbatim from lane results, none re-measured here (this lane is read-only).

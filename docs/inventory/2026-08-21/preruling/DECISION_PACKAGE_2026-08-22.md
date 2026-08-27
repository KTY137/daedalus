# DECISION PACKAGE 2026-08-22 -- owner ruling D1 (which chain is canonical)

Assembled 2026-08-22T07:41:53.832112+00:00 (UTC) by `preruling_package.py` from the Phase-0 preruling receipts. Iron Plan: ALIGNED (read-only measurement; no repo edits, no commits, no protected artifact touched). Iron Gate: 0. Every number below carries the receipt it was read from as `[file@sha256-prefix]` (full sha256 of each receipt file in the legend at the end) and the source tree sha it was measured at. Stamps: MEASURED = produced by a command in that receipt on that tree; INHERITED = taken from a task brief, finding text, or under shared load; MISSING = no receipt or no field, not invented.

Kill criteria are cited as 'sec. 13 (Rev 2) / sec. 14 (Rev 5-6)' because the trunk renumbered sections.

## 0. Pins, ancestry, worktrees

| item | CHECKPOINT | TRUNK | receipt |
|---|---|---|---|
| branch | `checkpoint/2026-07-20-session` | `work/g0-trunk-20260817` | config |
| pinned comparison head | `3e758392845d9faf7877977d5ae8806973ed62e6` | `93f11adfb08efa713711fd62e9be7b46d8957166` | config |
| branch tip at ancestry run (2026-08-22T06:32:26.200596+00:00) | `77e7498a762aa96c436d367dc35ff3431c0fcfa8` | `93f11adfb08efa713711fd62e9be7b46d8957166` | [ancestry.json@56c9b554] |
| pin is branch tip | False (pin is ancestor of tip: True; tip-only commits at ancestry run: 3) | True | [ancestry.json@56c9b554] [chain_report.json@a3826fe5] |
| merge-base (pins) | `8647091fbd5114c2020b2c0fb8e97278a6699e5d` (8647091f 2026-07-31 fix(funnel): the upper tiers were reading three runs as one) | same | [ancestry.json@56c9b554] MEASURED |
| `git merge-base --is-ancestor` L->R / R->L (pins) | False / False (DIVERGENT, not 'behind') | same | [ancestry.json@56c9b554] MEASURED |
| `git rev-list --left-right --count` (pins) | checkpoint-only 37 | trunk-only 1228 (check 1228) | [ancestry.json@56c9b554] MEASURED |
| same at branch tips | checkpoint-only 40 | trunk-only 1228 | [ancestry.json@56c9b554] MEASURED |
| checkpoint tip at harvest run (2026-08-22T07:10:12.208251+00:00) | `aede2fc7f91ab58efac4319f484ea6393661a657` (tip moved during Phase 0; checkpoint-only total 43 = 37 within pin + 6 beyond pin) | tip unchanged `93f11adfb08efa713711fd62e9be7b46d8957166` | [harvest_manifest.json@18fd6b3b] MEASURED |
| primary worktrees at trust-root run (2026-08-22T06:56:25+00:00) | `C:/Users/nukei/Desktop/agent_env` head `14238a300a7a6e4aefabe09a102ed504529be741`, dirty entries 27 (other agents' work, none attributable to Phase 0) | `C:/Users/nukei/Desktop/agent_env_g0` head `93f11adfb08efa713711fd62e9be7b46d8957166`, dirty entries 0 | [trust_root_report.json@77468761] MEASURED |
| disposable worktree (checkpoint) | `C:/Users/nukei/Desktop/agent_env.worktrees/preruling-cp` head `3e758392845d9faf7877977d5ae8806973ed62e6` porcelain lines 0 worktree-add rc 0 | | [worktrees.json@329f9599] MEASURED |
| disposable worktree (trunk) | `C:/Users/nukei/Desktop/agent_env.worktrees/preruling-g0` head `93f11adfb08efa713711fd62e9be7b46d8957166` porcelain lines 0 worktree-add rc 0 | | [worktrees.json@329f9599] MEASURED |
| iron_plan_guard verify at setup | Iron Plan OK: revision 2, Gate 0 - Canonical Kernel, sha256 d0756fa3772b2153d03a6c8b8bbeef6e487fc5830c3ccb62d9978bd5a22b27fd | | [setup.json@59643f9e] MEASURED |

## 1. Receipt inventory

| receipt | present | sha256 | task field |
|---|---|---|---|
| ancestry.json | yes | `56c9b554d05974c4995a54fa4b17a91ca6cc7cacf97b0dbd0ef7f2719b8e1a51` | preruling SETUP step 3/4: ancestry CHECKPOINT vs TRUNK |
| chain_report.json | yes | `a3826fe5239b2d3eeabf85a64e44b86093d0e3b75079f44a78855b86192ca54f` | preruling CHAINS: amendment-ledger chain audit on CHECKPOINT and TRUNK (read-only) |
| census_trunk.json | yes | `c80cdad235f57fbae859147732252cf1a5146269d92ee33b71504a552143a539` | CENSUS-TRUNK |
| census_trunk_counters.json | yes | `179a44f1a5c921c0260792e1c65decb6f017e3d2d164d3feef6119fdac272101` | CENSUS-TRUNK counters |
| census_trunk_import_contamination.json | yes | `ce450417139e8f5b941418f70469ec14888c1c63e6bf733c47b2cb10ac177a79` | CENSUS-TRUNK import contamination |
| census_trunk_guard_crosstree.json | yes | `e663d39e4dcc7c2cda52cf0cdacfccff9ee13c42860f1647917d4e2a4f672861` | CENSUS-TRUNK guard cross-tree resolution |
| census_checkpoint.json | yes | `a4798ce9cdf6aa27d532a284046ae96eaeae378d6d96cf2ec59bf8553f324960` | CENSUS-CHECKPOINT |
| reachability.json | yes | `5faa9a02c3e3336dc4c6d8396a3094930be10091ccad5cba7cc924cfaf9dd843` | ONE-KERNEL / reachability.json - static entrypoint->authority closure at TRUNK 93f11adf and CHECKPOINT 3e75839 |
| trust_root_report.json | yes | `774687610715823404b112b4052dac62d62d16a034dd7c9f957c885d0113a43c` | TRUST-ROOT (giga plan Phase 0 preruling, test-only) |
| trust_root_mutation_report.json | yes | `0487a6d613c8c2e13500e692cb2043d5d4ff8707fb0092752d5ba2a85b84f774` | TRUST-ROOT discriminating-power check (guard mutation) |
| loop_trace.json | yes | `621aca9fad518878adccd7c869250990370803c59013583b2abe5ac913db2521` | LOOP-TRACE (giga plan Phase 0 preruling, CHECKPOINT tree) |
| harvest_manifest.json | yes | `18fd6b3bdd92a203bc0f0e3de58609ab8db8d418b1e328beff3cdf53c9dd0304` | preruling Phase 0: HARVEST MANIFEST (checkpoint-only commits -> trunk port viability) + REVERSE manifest (trun |
| research_census.json | yes | `fcae26a7410bce0c89dff6ebe561e859b34793fc7ad6957c6b28bee930196e3f` | preruling RESEARCH-ASSET CENSUS: research assets per line (path, presence, blob/sha256, tests present+green, a |
| setup.json | yes | `59643f9ef49af7069d04e1db141cb662c9b96d3944804a7446ccc05d7630fd4b` | preruling SETUP (steps 1-4): config, disposable worktrees, ancestry, clean-check |
| worktrees.json | yes | `329f9599f4d6535b3d9a393b6214ec73d51114df3ab5d9cb959d1efa54384d45` | preruling SETUP step 2/4: disposable detached worktrees |
| fence.json | **MISSING** | - | - |

The task brief named nine receipts; all nine are present. The giga plan's Phase-0 'done when' additionally names a **fence receipt** (one protected-file write attempt per PRIMARY worktree via the ordinary agent path, denial verbatim); no such receipt exists under the preruling folder -> **MISSING**. The many guard denials recorded below all fired on read-only commands or on scratchpad heredocs, mostly in the disposable worktrees; none is a write attempt on a primary worktree.

## 2. State table per line

| row | CHECKPOINT @ 3e758392 | TRUNK @ 93f11adf | receipt / stamp |
|---|---|---|---|
| chain valid (every record_sha256 recomputed, previous link, sequence, revision step, plan digest at acceptance commit) | True (2 records) | True (6 records) | [chain_report.json@a3826fe5] MEASURED |
| record 1 byte-identical across chains | True (line sha256 `4766b9dec6efe995...`, common prefix 1 line) | same | [chain_report.json@a3826fe5] MEASURED |
| first divergence | seq 2: record 2 = `proposal-003-serena-first-owner-approved-2026-08-05; owner-executed-2026-08-21` -> plan `d0756fa3772b` v1.0.0 (accepted 2026-08-21T21:18:13+02:00, commit 3e758392) | record 2 = `conversation-2026-07-31-owner-fold-genesis-dual-layer-build-review-plan-and-continue` -> plan `ab8bb7fcdba8` v1.1.0 (accepted 2026-08-01T00:47:00+02:00, commit 105a48f9) | [chain_report.json@a3826fe5] MEASURED |
| both record-2s share base_plan_sha256 | `a47d84ee736f` (= record-1 result) | `a47d84ee736f` | [chain_report.json@a3826fe5] MEASURED |
| plan digest at pin matches latest record result | True (`d0756fa3772b2153d03a6c8b8bbeef6e487fc5830c3ccb62d9978bd5a22b27fd`, header rev 2 v1.0.0) | True (`4dc60d932b8e6233658486607565c8ca21a13e835afd3f57c94c8b41000e30e1`, header rev 6 v1.2.3) | [chain_report.json@a3826fe5] MEASURED |
| `tools/iron_plan_guard.py verify` in disposable worktree | rc 0: Iron Plan OK: revision 2, Gate 0 — Canonical Kernel, sha256 d0756fa3772b2153d03a6c8b8bbeef6e487fc5830c3ccb62d9978bd5a22b27fd | rc 0: Iron Plan OK: revision 6, Gate 0 — Canonical Kernel, sha256 4dc60d932b8e6233658486607565c8ca21a13e835afd3f57c94c8b41000e30e1 | [chain_report.json@a3826fe5] MEASURED |
| ledger identical pin vs branch tip | True (plan identical: True) | n/a (pin is tip) | [chain_report.json@a3826fe5] MEASURED |
| ledger line sha256 snapshot (Phase-1 byte-identity check) | 2 lines recorded | 6 lines recorded | [chain_report.json@a3826fe5] MEASURED |
| full suite `python -m pytest -q -p no:cacheprovider --color=no` | 3 failed, 4627 passed, 1 skipped, 1 xfailed, 2018 subtests passed in 1544.52s (0:25:44) (collected 4632, collect errors 0) | 3 failed, 7190 passed, 114 skipped, 1 xfailed, 1992 subtests passed in 2608.47s (0:43:28) | [census_checkpoint.json@a4798ce9] [census_trunk.json@c80cdad2] MEASURED; wall times INHERITED-under-load |
| suite counts (passed / failed / skipped / xfailed) | 4627 / 3 / 1 / 1 | 7190 / 3 / 114 / 1 | same |
| failing test ids | `tests/test_dotenv.py::test_every_example_key_is_cleared_by_the_suite_conftest`<br>`tests/test_iron_plan_guard.py::IronPlanContractTests::test_ci_history_check_accepts_adoption_and_rejects_rewrite`<br>`tests/test_iron_plan_guard.py::IronPlanContractTests::test_ledger_seals_current_plan` | `tests/runtimes/test_whole_fault_matrix.py::test_the_promoted_combiner_reproduces_the_landed_verdict_from_the_observations`<br>`tests/test_envelope_coverage.py::test_no_new_record_producer_has_appeared_undeclared`<br>`tests/test_mapping_switches.py::test_this_repo_still_analyses` | [census_checkpoint.json@a4798ce9] [census_trunk.json@c80cdad2] MEASURED |
| failure causes | F2/F3: `test_dotenv` red only in the full suite (16 passed alone): two modules named `conftest`, second evicts first; `runs/higher_twin_nc/tests/conftest.py` is the twin (mechanism INFERRED; decisive isolation run DENIED by guard); fix exists unapplied in `docs/recovery/lane_diffs/misc-red.patch` (F4). F5: `test_ledger_seals_current_plan` pins result_revision==1 while ledger records 2 (deterministic staleness). `test_ci_history_check_accepts_adoption_and_rejects_rewrite` was the 1 expected red per task brief (INHERITED) | (1) `test_whole_fault_matrix`: promoted combiner tuple has 2 extra rows vs landed verdict (first extra `fault.reconciliation-overdue:runtime.broker.malformed-output-evidence`); (2) `test_envelope_coverage`: undeclared record producer `runs/gate0-matrix-2026-08-17/verify_whole_matrix.py`; (3) `test_mapping_switches`: `experiments/forest_v2/s03_data/corpus/src/unparseable_fixture.py` SyntaxError (a deliberate corpus fixture the repo-wide analyser trips on) | [census_checkpoint.json@a4798ce9] findings F1-F5; [census_trunk.json@c80cdad2] raw_trunk/pytest.stdout.txt MEASURED |
| task-brief expectation vs measured | brief expected 1 red (INHERITED), measured 3 | brief's last-known 35 failed / 6428 passed at 7c88f72 (INHERITED); measured 3 / 7190 at 93f11adf. Whether the 3 fall inside the 'documented 20 named lines' is **MISSING** (no receipt carries that list) | [census_checkpoint.json@a4798ce9] [census_trunk.json@c80cdad2] |
| `tools/effect_boundary_check.py` | rc 2; BLOCKER lines 15 = 12 `tools.* entrypoint.unregistered` (expected 12, INHERITED) + 3 other (`effect_drift` OllamaProvider.rollback; `gate0.unguarded_entrypoint` python.offload; `gate0.unguarded_entrypoint` python.promote_candidates); structurally_conformant False; gate0_closed False | rc 0; diagnostic classes: review:entrypoint.harness 87, gap:gate0.not_central 22, review:entrypoint.not_rediscovered 3, blocker:fault_matrix.unbound 1, blocker:runtime_conformance_receipts 1, info:runtime_conformance.canonical_persistence 1, info:runtime_conformance.canonical_producer 1, info:runtime_conformance.gap 1, review:scan.static_scope 1; pinned rerun (PYTHONPATH=worktree) stdout byte-identical: True | [census_checkpoint.json@a4798ce9] [census_trunk.json@c80cdad2] [census_trunk_import_contamination.json@ce450417] MEASURED |
| `tools/run_gate_checks.py` | not run in census_checkpoint -> MISSING | `run_gate_checks.py` (no profile) rc 2 (usage: profile required); `run_gate_checks.py g0` first run rc 1 with `ImportError: cannot import name 'process_guard_boundary_decision' from 'daedalus.budget'` = CROSS-TREE CONTAMINATION (editable .pth maps `daedalus` -> `C:/Users/nukei/Desktop/agent_env/daedalus`, the CHECKPOINT primary); pinned rerun with PYTHONPATH=worktree: rc 0, tail `87 passed in 97.90s (0:01:37)` | [census_trunk.json@c80cdad2] [census_trunk_import_contamination.json@ce450417] MEASURED |
| `tools/system_check.py --json` | rc 1; 18 CORE checks: PASS 14, FAIL 2 (map.drift_gate_is_green; bridge.enqueue_watch_report_archive), UNAVAILABLE 2 (eval.replays_a_task_and_scores_it: secret floor; gui cockpit: @playwright/test not installed) | not run in census_trunk -> MISSING | [census_checkpoint.json@a4798ce9] MEASURED |
| `tools/gate_host_preflight.py` | rc 0 fit=True | not run -> MISSING | [census_checkpoint.json@a4798ce9] MEASURED |
| `tools/gate_discrimination.py` | NOT RUN deliberately (receipt producer, ~18 min per mutation x 12, mutating) | NOT RUN | [census_checkpoint.json@a4798ce9] not_run |
| **five Gate-0 counters** (from `python -m daedalus.gates report --gate 0 --source-revision <pin>`) | **N/A on this line**: `daedalus/gates` and `daedalus/kernel` do not exist at 3e758392 (authority_dirs_present gates=False, kernel=False); the closest instrument is effect_boundary_check above | see five rows below | [reachability.json@5faa9a02] [census_trunk_counters.json@179a44f1] |
| 1. executed fault lines | N/A | gate0-matrix-2026-08-17: 18; gate0-matrix-20260818-closure: 18; gate0-matrix-20260818-head: 18; gate0-matrix-20260818-morning: 18 -- binding to trunk head: NONE - no archived verdict cites 93f11adf | [census_trunk_counters.json@179a44f1] MEASURED (from archived verdicts) |
| 2. declared-blocked lines | N/A | gate0-matrix-2026-08-17: 4; gate0-matrix-20260818-closure: 6; gate0-matrix-20260818-head: 4; gate0-matrix-20260818-morning: 4 (brief expected 18/6, INHERITED) | [census_trunk_counters.json@179a44f1] MEASURED (from archived verdicts) |
| 3. inventory_only doors | N/A | **10** (brief expected 13, INHERITED): provider.claude, provider.codex, provider.deepseek, provider.deepseek.rollback, provider.ollama.rollback, provider.ollama_native, runs.gate0_matrix.verify_whole_matrix, runtimes.fault_attestation_issuer, tools.iron_plan_guard, tools.iron_plan_hook_runner; every justification reads '... is inventory_only; Gate 0 is not closed' | [census_trunk_counters.json@179a44f1] MEASURED (live report at 93f11adf) |
| 4. security_boundary_claimed | N/A | False | [census_trunk_counters.json@179a44f1] MEASURED (live report at 93f11adf) |
| 5. scanner_error | N/A | 0 in the emitted v2 report (schema has no such field; tokens searched ['scanner_error', 'scan.error', 'scanner.error', 'scan_failed', 'entrypoint.scan_error'] -> git grep rc 1, 0 hits); v3 reporter reachable from shipped CLI: False; archived v3 artifact at 1e681b9b (not bound to head): repository_write_files_scanned 282, failures_len 377, scanner_refused_rows 0 | [census_trunk_counters.json@179a44f1] MEASURED (absence): the shipped CLI emits schema v2, which h... |
| `assert_gate_report.py --require-closed` | N/A | rc 1 (closed=false); without `--require-closed` rc 0 -> the tool fails because the report is open, not always | [census_trunk.json@c80cdad2] MEASURED |
| gate-0 report blockers (schema daedalus-gate-report/2, source_revision `93f11adf`, report sha256 `7bca9c9da277`) | N/A | 13 blockers: 1 `fault_injection_failures:whole-matrix:unbound:no-verdict-at-cited-revision` + 10 `inventory_only_production_entrypoints:*` + 1 `runtime_conformance_failures:...:no-persisted-receipt-bundle` + 1 `security_boundary_claimed:false`; owner_approval_enforced True; missing_guard_contracts 0 | raw_trunk/gate0_report.json MEASURED |
| archived fault matrices | N/A | 4 matrices (2026-08-17, 20260818-morning/head/closure), each catalog 24 scenarios; observations 22/22/22/24; the closure matrix is production-signed (3 columns incl. live-runtime, 2 attestations); all cite other revisions (c93191fe, 1e681b9b, 4fb2251d, bcc0feaf) -> none binds 93f11adf | [census_trunk_counters.json@179a44f1] MEASURED (from archived verdicts) |
| entrypoints indexed (registry / console / cli subcommand / __main__) | 99 (18 / 1 / 34 / 46); modules 174; all indexed files byte-identical to pin: True | 176 (84 / 1 / 37 / 54); modules 285; all indexed files byte-identical to pin: True | [reachability.json@5faa9a02] MEASURED (ast parse, nothing executed) |
| entrypoints reaching spine AND (kernel or gates): file-closure M / import-time L / invocation F | 0 / 0 / 0 of 97 (spine reached by 68/48/46; kernel 0; gates 0) | 76 / 21 / 34 of 146 (spine reached by 141/83/115; kernel 76/20/36; gates 1 in all modes = its own `python -m daedalus.gates report`) | [reachability.json@5faa9a02] MEASURED |
| authority package reachability (reachable / modules) | spine 11/13 (unreachable: daedalus.spine, daedalus.spine.promotion_approval); kernel 0/0; gates 0/0 | spine 13/14; kernel 14/23; gates 5/35 | [reachability.json@5faa9a02] MEASURED |
| modules reachable from NO entrypoint | 27/174 | 101/285 (30 of 35 gates modules, 9 of 23 kernel modules among them) | [reachability.json@5faa9a02] MEASURED |
| `promote_candidates` approval-shaped parameters | 0 of 8 params (daedalus.kernel.promotion:authorize_persisted_promotion NOT FOUND) | 4 (consumed_approval, evidence_packet, approval_ledger, owner_keyring) of 13 params; reaches `daedalus.kernel.approvals` in mode M/L: True/True via daedalus.kairos.gated_writes -> daedalus.kernel.promotion -> daedalus.kernel.approvals; mode F (conservative invocation closure): False (reaches some kernel module: True); retired legacy body `_gated_writes_legacy.py.src` deleted at import: True | [reachability.json@5faa9a02] MEASURED |
| **one-kernel verdict (Invariant 1, from reachability, NOT from ls)** | no kernel/gates packages; one spine reached by 68/97 entrypoints; BUT the sealed-promotion path has 0 approval parameters and `daedalus.spine.promotion_approval` is reachable from 0 entrypoints (Lens A claim 2 CONFIRMED here) | Lens A claim 1 ('three competing kernels because ls shows gates+kernel+spine') **REFUTED as stated**: 76 entrypoints reach spine AND kernel on one call path (layers, not rival planes); gates is reached by exactly 1 entrypoint (its own reporter) and 0 effect-boundary rows target it; Lens A claim 2 **REFUTED** here. Residue: dead-weight/test-only surface (101/285 modules), not an Invariant-1 violation | [reachability.json@5faa9a02] verdicts MEASURED; determinism: 3 runs byte-identical |
| reachability known unsoundness | intra-package only (`tools.*` 19 rows, `runs.council.*` 6 rows, `mcp.runtime` absent row unresolved); importlib sites enumerated, no edges synthesised (1 sites) | same; 5 dynamic import sites | [reachability.json@5faa9a02] INHERITED gap |
| trust root (test-only adversarial suite) | `daedalus/spine/promotion_approval.py` (asymmetric, git-signed tag verified against committed allowed-signers; blob 23c40480, 599 lines): PASS 23 / FAIL 0 / N/A 2 of 25 | `daedalus/kernel/approvals.py` (symmetric HMAC-SHA256, secret from env; blob e0bb1ff8, 808 lines): PASS 19 / FAIL 5 / N/A 4 of 28 | [trust_root_report.json@77468761] MEASURED; case table in section 3 |
| trust-root guard discriminating power (in-memory source mutation) | CHECKPOINT: 6 of 7 mutations flip refused->accepted (C5 redundantly guarded by C5b) | TRUNK: 5 of 5 | [trust_root_mutation_report.json@0487a6d6] MEASURED: 12 mutations, 11 demonstrated, 1 redundant, 0 not demonstrated |
| loop trace: effects-before-guard | `daedalus.loop --dry-run --max-iterations 1 --json --arm`: 23 audited effects (open_write 8, os_replace 1, getaddrinfo 7, socket_connect 7), first effect seq 1, guard first seen seq 1, guard active at first effect True -> **effects before guard = 0**; `daedalus.cli map`: 23 effects, guard active at first True -> 0; unarmed loop: exit 3 stop_reason killswitch, 0 effects | not run on this line -> MISSING | [loop_trace.json@621aca9f] MEASURED (finding F2 text says '24 recorded effects'; raw audit says 23 -- raw is authoritative). Caveat F2: `_load_dotenv()` runs before `install_process_guard()` at loop.py:1232 -- a READ-open precedes the guard on a tree with `.env`; not exercised here |
| loop trace: freshness-refusal | stale map (head mismatch, digest valid) withholds 23->0 map candidates (100% of map-sourced work), queue 46->23 = 23/46 withheld; negative control (fresh) ranks 23; committed snapshot already stale at pin per raw data: False (finding F4 text states 11->0 / 16->5 and 'already stale, recorded head 7955317' against the committed file; the raw picker data in the receipt was taken on an already-regenerated working copy -> the F4 numbers are INHERITED from finding text, raw data not in receipt) | MISSING | [loop_trace.json@621aca9f] |
| loop trace: other findings | F3 governance verdict computed against `C:/Users/nukei/Desktop/agent_env` @ 77e7498a while loop repo_root is the disposable worktree @ 3e758392 (same_tree=False; verdict 'promotion is REFUSED: the gate was last shown to discriminat...'; failed CLOSED here) -- touches Invariants 6 and 9; F5 stale map selects the free ollama lane, fresh map the paid claude_cli lane (dry-run, 0 vendor calls); F6 `docs/architecture-state.json` written non-atomically (drift.py:1069 `write_text`), killswitch permit atomic; F7 two sinks outside repo root by design (%TEMP% tokenizer cache, %LOCALAPPDATA%/daedalus/control/<digest>/killswitch); F8 4 of 6 git spawns in map run carry no `-C`; F9 process guard patches subprocess.run/Popen/urlopen only, not raw sockets; tripwire selftest: 3 probes BLOCKED + benign control ALLOWED, paid-provider events 0 | MISSING | [loop_trace.json@621aca9f] MEASURED |
| harvest (checkpoint-only -> trunk) | 43 commits at run time = 37 within pin + 6 beyond pin; within pin: port-clean 26 / port-needs-rework 10 / drop-with-reason 1; all 43: 32 / 10 / 1; identical patch-id hits on trunk 0; 0 rows unclassified | (reverse) trunk-only 1228 commits (1217 with patch-id, 11 without); 82 research assets: 78 trunk-only, 3 diverged, 1 identical, 0 missing from trunk | [harvest_manifest.json@18fd6b3b] MEASURED; table in section 4 |
| research assets | higher_twin_nc present (85 tracked files, 63 tests green), LAYER2 doc present; forest_v2 absent | forest_v2 present (78 tracked files, 442 tests green, slices s02/s07/s09 exist only as mentions); higher_twin_nc + LAYER2 absent | [research_census.json@fcae26a7] MEASURED; table in section 5 |
| cross-tree import contamination hazard | editable install target = `C:/Users/nukei/Desktop/agent_env/daedalus` (this line's primary) | a script run BY PATH from the trunk worktree imports the CHECKPOINT's `daedalus` unless PYTHONPATH names the worktree (probe: by-path -> agent_env/daedalus; `-c` with cwd -> worktree; PYTHONPATH -> worktree). `python -m` runs (pytest, gates report) are unaffected. `run_gate_checks.py g0` ImportError above is this hazard, not a trunk defect | [census_trunk_import_contamination.json@ce450417] MEASURED |
| guard resolution by cwd | `iron_plan_guard.py verify` from agent_env: rc 0 rev 2 `d0756fa3...` | from the trunk worktree (unpinned / PYTHONPATH-pinned): rc 0 / 0 rev 6 `4dc60d93...` -> the guard resolves the plan by cwd, both answers correct for their tree | [census_trunk_guard_crosstree.json@e663d39e] MEASURED |

## 3. Trust-root case table (D5 input; test-only, disposable worktrees and scratch fixtures)

Source: [trust_root_report.json@77468761] generated 2026-08-22T06:56:25+00:00; TRUNK module `daedalus/kernel/approvals.py` @ 93f11adf; CHECKPOINT module `daedalus/spine/promotion_approval.py` @ 3e758392. Stamp legend: {"INCONCLUSIVE-live": "the live probe did not execute; no claim made", "MEASURED": "observed in this run on this box", "N/A": "recorded but not scored (precondition, informational, or a documented design separation present on both trees)"}

| suite | case | family | expected | observed | verdict | stamp | description |
|---|---|---|---|---|---|---|---|
| TRUNK | A0 | positive-control | accept (positive control) | accepted | **PASS** | MEASURED | a correctly signed, in-window, fully bound approval verifies |
| TRUNK | A1 | unsigned | fail-closed (refuse) | refused | **PASS** | MEASURED | signature field zeroed (an unsigned approval presented as signed) |
| TRUNK | A2 | wrong-signer | fail-closed (refuse) | refused | **PASS** | MEASURED | approval signed with a foreign secret, verified against the owner key |
| TRUNK | A3 | wrong-signer | fail-closed (refuse) | refused | **PASS** | MEASURED | approval from an owner/key pair absent from the keyring |
| TRUNK | A4 | revoked-signer | fail-closed (refuse) | refused | **PASS** | MEASURED | key removed from the keyring after the approval was issued |
| TRUNK | A5a | replay | accept (positive control) | accepted | **PASS** | MEASURED | first consumption of a valid approval through the ledger |
| TRUNK | A5b | replay | fail-closed (refuse) | refused | **PASS** | MEASURED | the SAME approval consumed a second time, new promotion id |
| TRUNK | A5c | replay | fail-closed (refuse) | refused | **PASS** | MEASURED | a freshly minted approval reusing the spent nonce |
| TRUNK | A5d | replay | not scored (precondition/informational) | accepted | **N/A** | MEASURED | does verify_owner_approval still approve an already-consumed approval |
| TRUNK | A6a | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | approval signed for candidate A, promotion presents candidate B |
| TRUNK | A6b | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | candidate swapped inside the approval, old signature retained |
| TRUNK | A6c | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | approval signed against strong evidence, weaker evidence presented |
| TRUNK | A6d | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | target head moved between approval and promotion |
| TRUNK | A7a | stale | fail-closed (refuse) | refused | **PASS** | MEASURED | approval verified after its expires_at |
| TRUNK | A7b | stale | fail-closed (refuse) | refused | **PASS** | MEASURED | approval verified before its issued_at (clock rolled back) |
| TRUNK | A7c | stale | fail-closed (refuse) | refused | **PASS** | MEASURED | standing authorisation: TTL beyond the 24h Gate-0 maximum |
| TRUNK | A8a | revoked-signer | fail-closed (refuse) | refused | **PASS** | MEASURED | persisted consumption receipt re-verified after key revocation |
| TRUNK | A8b | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | consumption receipt with a hand-edited promotion id |
| TRUNK | A12 | replay | fail-closed (refuse) | accepted | **FAIL** | MEASURED | spent approval re-authenticated against a SECOND, caller-supplied ledger holding a copied consumption row |
| TRUNK | A9a | canary-env | fail-closed (refuse) | accepted | **FAIL** | MEASURED | plain child of the verifier reads the approval-secret env var |
| TRUNK | A9b0 | canary-env | fail-closed (refuse) | refused | **PASS** | MEASURED | sandbox policy accepts a floating (unpinned) image tag |
| TRUNK | A9b | canary-env | accept (positive control) | accepted | **PASS** | MEASURED | canonical attempt path (run_in_docker_sandbox) forwards no env var |
| TRUNK | A9c0 | canary-env | not scored (precondition/informational) | refused | **N/A** | MEASURED | is the Docker engine reachable on this box (precondition for A9c) |
| TRUNK | A9c | canary-env | not scored (precondition/informational) | refused | **N/A** | INCONCLUSIVE-live | live sandbox spawn: does the container see the canary |
| TRUNK | A9c1 | canary-env | fail-closed (refuse) | accepted | **FAIL** | MEASURED | attempt path classifies an unreachable Docker engine as a COMPLETED attempt rather than refused-before-start |
| TRUNK | A10 | ordinary-mint | fail-closed (refuse) | accepted | **FAIL** | MEASURED | an ordinary subprocess holding the secret mints an approval for an artifact no owner reviewed; the verifier accepts it |
| TRUNK | A10b | ordinary-mint | fail-closed (refuse) | accepted | **FAIL** | MEASURED | the self-minted approval is consumed through the real ledger |
| TRUNK | A11 | canary-env | not scored (precondition/informational) | accepted | **N/A** | MEASURED | spawn sites in the trunk kernel that pass an explicit env= |
| CHECKPOINT | B0 | positive-control | accept (positive control) | accepted | **PASS** | MEASURED | owner-signed tag, key in the COMMITTED allowed-signers file |
| CHECKPOINT | B1a | unsigned | fail-closed (refuse) | refused | **PASS** | MEASURED | lightweight tag (a name pointing at a commit; nothing is signed) |
| CHECKPOINT | B1b | unsigned | fail-closed (refuse) | refused | **PASS** | MEASURED | annotated but UNSIGNED tag carrying a well-formed approval body |
| CHECKPOINT | B2 | wrong-signer | fail-closed (refuse) | refused | **PASS** | MEASURED | tag signed by a real key that is NOT in the committed allowed-signers |
| CHECKPOINT | B2b | wrong-signer | fail-closed (refuse) | refused | **PASS** | MEASURED | git verify-tag TEXT vs EXIT CODE for an unauthorised signer |
| CHECKPOINT | B3a | revoked-signer | fail-closed (refuse) | refused | **PASS** | MEASURED | attacker key appended to the WORKING COPY of allowed-signers, never committed |
| CHECKPOINT | B3b | revoked-signer | fail-closed (refuse) | refused | **PASS** | MEASURED | owner key REMOVED from allowed-signers by a commit; the previously good tag re-verified |
| CHECKPOINT | B3c | positive-control | accept (positive control) | accepted | **PASS** | MEASURED | after restoring the owner key by commit, the same tag verifies again |
| CHECKPOINT | B4a | replay | accept (positive control) | accepted | **PASS** | MEASURED | first claim of a verified approval |
| CHECKPOINT | B4b | replay | fail-closed (refuse) | refused | **PASS** | MEASURED | the SAME verified approval claimed a second time |
| CHECKPOINT | B4c | replay | not scored (precondition/informational) | accepted | **N/A** | MEASURED | does verify_promotion_approval still approve an already-spent approval |
| CHECKPOINT | B5a | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | promotion presents candidate B; only candidate A has a signed tag |
| CHECKPOINT | B5b | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | tag NAME says one candidate, signed BODY names another |
| CHECKPOINT | B5c | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | approval signed against strong evidence, weaker evidence presented |
| CHECKPOINT | B5d | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | approval signed on one base, promotion attempted on a moved base |
| CHECKPOINT | B5e | artifact-substituted | fail-closed (refuse) | refused | **PASS** | MEASURED | candidate regenerated after approval (voided_by_regeneration) |
| CHECKPOINT | B6a | stale | fail-closed (refuse) | refused | **PASS** | MEASURED | owner-signed approval whose expires_at has passed |
| CHECKPOINT | B6b | stale | fail-closed (refuse) | refused | **PASS** | MEASURED | standing authorisation: signed approval with NO expires_at field |
| CHECKPOINT | B6c | stale | fail-closed (refuse) | refused | **PASS** | MEASURED | expires_at without a UTC offset (ambiguous instant) |
| CHECKPOINT | B7a | canary-env | accept (positive control) | accepted | **PASS** | MEASURED | the verifier needs no secret in its environment at all |
| CHECKPOINT | B7b | canary-env | not scored (precondition/informational) | accepted | **N/A** | MEASURED | candidate-shaped child inherits env, but env grants no minting power |
| CHECKPOINT | B8a | ordinary-mint | fail-closed (refuse) | refused | **PASS** | MEASURED | an ordinary process mints its own signed tag with its own key |
| CHECKPOINT | B8b | ordinary-mint | accept (positive control) | accepted | **PASS** | MEASURED | a process that can READ the owner private key file mints a valid approval |
| CHECKPOINT | B9a | unsigned | fail-closed (refuse) | refused | **PASS** | MEASURED | verification against a repository that does not exist |
| CHECKPOINT | B9b | unsigned | fail-closed (refuse) | refused | **PASS** | MEASURED | no allowed-signers file committed at HEAD (no trust root at all) |

| family | CHECKPOINT PASS/FAIL/N/A | TRUNK PASS/FAIL/N/A |
|---|---|---|
| artifact-substituted | 5/0/0 | 5/0/0 |
| canary-env | 1/0/1 | 2/2/3 |
| ordinary-mint | 2/0/0 | 0/2/0 |
| positive-control | 2/0/0 | 1/0/0 |
| replay | 2/0/1 | 3/1/1 |
| revoked-signer | 2/0/0 | 2/0/0 |
| stale | 3/0/0 | 3/0/0 |
| unsigned | 4/0/0 | 1/0/0 |
| wrong-signer | 2/0/0 | 2/0/0 |

Differentiator (receipt text): The secret's LOCATION and SYMMETRY, not the binding quality. TRUNK verifies with the same secret it signs with, and that secret is read from an environment variable (_cli_issue/_cli_verify: os.environ.get(secret_env)). Any process that can read the variable can mint an approval that the real verifier accepts and the real ledger consumes (A10, A10b). CHECKPOINT verifies with a public key read from the COMMITTED tree while the signing key is a private key file, so an ordinary process holding the environment mints nothing (B7a, B8a); forging requires the owner's private key file, which plan section 1 already excludes from scope (B8b).

Not claimed by the receipt: No live containerised canary measurement was taken: the Docker engine was unreachable on this box (A9c0, A9c). The trunk sandbox's env isolation is asserted from argv shape only (A9b).; No wall-clock or performance number is reported; the box was under load.; Neither module was tested as wired into a promotion callable. The CHECKPOINT module states in its own docstring that it is not wired in; that claim was not independently re-verified here.

Prior art: `docs/GATE0_PROMOTION_TRUST_ROOT_FINDING.md (TRUNK, dated 2026-08-18, binding for lane grind/sealed-approval)` -- This task did NOT discover that TRUNK's HMAC root is symmetric. That document already states it ('Wer verifizieren kann, kann faelschen'), already calls the approval_assurance='authenticated' label on an env-var root a section 4.9 honesty violation, and already names Option B (git-signed tags) as the fix -- which is what CHECKPOINT's module implements. What this receipt adds is EXECUTION-level confirmation of claims that were previously review-level: A10/A10b mint and consume a real approval from an ordinary child process, A12 reproduces the named Slice-8 cross-ledger replay, and B2b measures the 'Good git signature is meaningless' claim directly (rc=1 while stdout says Good).

Consequence stated by the receipt: The two trees are not two candidate designs of equal standing. TRUNK's own binding review already prescribes CHECKPOINT's mechanism. The open question is therefore migration and wiring, not which trust root is sounder.

Canary visibility: A9a (plain child reads the approval-secret env var) FAIL on TRUNK; A9b canonical sandbox argv forwards no env var (PASS, argv shape only); A9c live container canary **INCONCLUSIVE-live** (Docker engine unreachable, A9c0); A9c1 unreachable engine classified as COMPLETED attempt (FAIL). CHECKPOINT B7a verifier needs no secret (PASS), B7b child inherits env but env grants no minting power (N/A).

## 4. Harvest manifest (both directions)

Source: [harvest_manifest.json@18fd6b3b] at 2026-08-22T07:10:12.208251+00:00; pins checkpoint `3e758392`, trunk `93f11adf`; checkpoint tip at run `aede2fc7`. Dry apply = `git apply --check [--3way]` in a throwaway worktree at the trunk pin (nothing committed); sequential pass applied in commit order then `reset --hard`. State/reason are DERIVED from measured fields by the script's rules; the owner rules.

| direction | rows | port-clean | port-needs-rework | drop-with-reason | notes |
|---|---|---|---|---|---|
| checkpoint-only -> trunk, within pin (ruling set) | 37 | 26 | 10 | 1 | rework root causes: {"trunk-divergence": 4, "new-file-already-identical-on-trunk": 1, "blocked-by-skipped-dependency": 5}; port modes: {"none": 9, "isolated": 17, "sequential-after-deps": 15, "n/a": 1, "sequential-minus-identical-files": 1} |
| checkpoint-only -> trunk, beyond pin (tip moved during Phase 0) | 6 | 6 | 0 | 0 | not part of the pinned ruling set |
| trunk-only -> checkpoint (reverse, commits) | 1228 | not classified per commit (by design: reverse manifest is per research ASSET) | - | - | 1217 with patch-id, 11 without (merges/empty); identical patch-id hits 0 |
| trunk-only research assets (reverse manifest) | 82 | 78 trunk-only (port = copy) | 3 diverged (ceiling.py, graph_delta.py: +8/-0 lines each = effect-boundary `begin_effect` wiring; gate_discrimination.py) | 1 identical (mutate.py) | missing from trunk 0; non-test .py 50, with tests 32, importing daedalus 3; `pytest --collect-only` over 28 targets: 808 items, 0 errors |

Class x state (all 43): {"other": {"port-needs-rework": 1, "port-clean": 1}, "constitution": {"port-clean": 11, "port-needs-rework": 2}, "docs": {"port-clean": 17, "drop-with-reason": 1, "port-needs-rework": 3}, "research": {"port-clean": 3, "port-needs-rework": 3}, "safety": {"port-needs-rework": 1}}

Sequential pass: 34 applied in order, 9 skipped (a83db1f5a6, accd251323, 886e877cda, 65effb8168, e0c44fd0af, fb48a30692, 6ec7d2cb8c, c264f5dd22, 3e75839284); working tree after chain: 174 files changed, 29662 insertions(+), 11063 deletions(-), 219 status lines; after restore 0.

### 4a. Rows needing rework or dropped (pinned set)

| commit | date | priority class | state | root cause | touches protected policy artifact | reason (receipt text) |
|---|---|---|---|---|---|---|
| `a83db1f5a6` feat(spine): promotion gets a signed approval it cannot grant itself | 2026-08-17 | promotion-verifier | port-needs-rework | ['trunk-divergence'] | True | trunk divergence: daedalus/spine/attempt.py differs on trunk (context mismatch); trunk divergence: daedalus/spine/effect_boundary.py differs on trunk (context mismatch); isolated 3-way check leaves conflict markers in: daedalus/spine/attempt.py (rework = manua |
| `3a10e46069` plan: the Gesamtplan lands verbatim as the working guide | 2026-08-17 | docs | drop-with-reason | - | False | post-image already on trunk: all 1 touched path(s) byte-identical at trunk pin |
| `e289b4c6b3` vault: two days enter the journal -- 265 failures to a production-sign | 2026-08-18 | constitution | port-needs-rework | ['new-file-already-identical-on-trunk'] | True | applies in commit order only after excluding file(s) whose post-image is already byte-identical on trunk: docs/recovery/gate0_production_attest.ps1 (rework = git apply --exclude / drop those hunks) |
| `accd251323` experiment: chemlab proves the detector can stay silent | 2026-08-21 | research | port-needs-rework | ['trunk-divergence'] | False | trunk divergence: tools/agent_findings.py differs on trunk (context mismatch); trunk divergence: tools/audit_triage.py differs on trunk (context mismatch) |
| `886e877cda` experiment: textlab finds the words the footprint language lacks | 2026-08-21 | research | port-needs-rework | ['blocked-by-skipped-dependency'] | False | blocked: context of runs/higher_twin_nc/SPEC.md last changed by skipped commit(s) accd251323; blocked: context of vault/Sessions/2026-08-21.md last changed by skipped commit(s) accd251323 |
| `65effb8168` experiment: one gluing assay finds what fifteen pairs were hunting | 2026-08-21 | research | port-needs-rework | ['blocked-by-skipped-dependency'] | False | blocked: context of runs/higher_twin_nc/SPEC.md last changed by skipped commit(s) accd251323, 886e877cda; blocked: context of vault/Sessions/2026-08-21.md last changed by skipped commit(s) accd251323, 886e877cda |
| `e0c44fd0af` vault: the night the gardener, the falsifier and the watchdog worked a | 2026-08-21 | docs | port-needs-rework | ['blocked-by-skipped-dependency'] | False | blocked: context of vault/Sessions/2026-08-21.md last changed by skipped commit(s) accd251323, 886e877cda, 65effb8168 |
| `fb48a30692` vault: the guard blocker is measured, not guessed, and vet goes to Min | 2026-08-21 | docs | port-needs-rework | ['blocked-by-skipped-dependency'] | False | blocked: context of vault/Sessions/2026-08-21.md last changed by skipped commit(s) accd251323, 886e877cda, 65effb8168, e0c44fd0af |
| `6ec7d2cb8c` safety(vet): the vetting gate scans the frontmatter and MCP egress can | 2026-08-21 | safety | port-needs-rework | ['trunk-divergence'] | False | trunk divergence: daedalus/tools/vet.py differs on trunk (context mismatch); trunk divergence: tests/test_tools_vet.py differs on trunk (context mismatch); isolated 3-way check leaves conflict markers in: daedalus/tools/vet.py, tests/test_tools_vet.py (rework  |
| `c264f5dd22` vault: the vetting gate is hardened and the fence held under Cerberus | 2026-08-21 | docs | port-needs-rework | ['blocked-by-skipped-dependency'] | False | blocked: context of vault/Sessions/2026-08-21.md last changed by skipped commit(s) accd251323, 886e877cda, 65effb8168, e0c44fd0af, fb48a30692 |
| `3e75839284` amendment(003): the serena-first hook is wired and the ledger carries  | 2026-08-21 | constitution | port-needs-rework | ['trunk-divergence'] | True | trunk divergence: docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl differs on trunk (context mismatch); trunk divergence: docs/IKARUS_ARIADNE_MASTER_PLAN.md differs on trunk (context mismatch); isolated 3-way check leaves conflict markers in: docs/IKARUS_ARIAD |

Rows touching a protected policy artifact (any state): 15 -- a83db1f5a6, 5ad7267dfa, c07f4dd48e, 2e7dc1ba0c, 7f487a3378, 06e260a425, d4d200d914, 92b24699f7, d7ce0d0829, 4a885c89b5, e289b4c6b3, 49263fc3c0, 3e75839284, 8bd2b9a68f, aede2fc7f9. Of these, port-needs-rework: a83db1f5a6, e289b4c6b3, 3e75839284. Every such row is an AMENDMENT-class port on the survivor (plan sec. 15), not a crew patch.

### 4b. All 43 rows

| commit | date | pinned | class | state | port mode | subject |
|---|---|---|---|---|---|---|
| `a83db1f5a6` | 2026-08-17 | True | promotion-verifier | port-needs-rework | none | feat(spine): promotion gets a signed approval it cannot grant itself |
| `5ad7267dfa` | 2026-08-17 | True | constitution | port-clean | isolated | chore(proposals): two amendment requests and the branch-recovery record |
| `a7d4d0c695` | 2026-08-17 | True | docs | port-clean | isolated | chore(proposal): the sealed-promotion guard lost the module it was watching |
| `e206de6308` | 2026-08-17 | True | docs | port-clean | isolated | chore(gate0): sealed promotion is implemented twice, with opposite trust roots |
| `8d78186be5` | 2026-08-17 | True | docs | port-clean | isolated | chore(gate0): what actually fails on the consolidated trunk, measured |
| `7c2dd7e3cd` | 2026-08-17 | True | docs | port-clean | sequential-after-deps | fix(proposal): correct proposal 005 -- the sealed constant does exist |
| `ade84786e9` | 2026-08-17 | True | docs | port-clean | isolated | chore(gate0): ten-lane reconnaissance, adversarially verified |
| `c07f4dd48e` | 2026-08-17 | True | constitution | port-clean | sequential-after-deps | chore(recovery): amendment 005 becomes a one-command kit, mutation-verified |
| `2e7dc1ba0c` | 2026-08-17 | True | constitution | port-clean | isolated | chore(recovery): the 66 recovered checks survive as a portable patch |
| `3a10e46069` | 2026-08-17 | True | docs | drop-with-reason | n/a | plan: the Gesamtplan lands verbatim as the working guide |
| `7f487a3378` | 2026-08-17 | True | constitution | port-clean | sequential-after-deps | chore(archive): fourteen superseded documents move to the archive folder |
| `06e260a425` | 2026-08-17 | True | constitution | port-clean | isolated | chore(konkordanz): five long-context lanes map plan, trunk, and harvest |
| `d4d200d914` | 2026-08-17 | True | constitution | port-clean | isolated | chore(harvest): twenty repair lanes complete, diffs and verdicts preserved |
| `92b24699f7` | 2026-08-17 | True | constitution | port-clean | sequential-after-deps | fix(recovery): the amendment kit stops assuming it knows the revision |
| `2c39cb6ff3` | 2026-08-17 | True | docs | port-clean | isolated | env: obsidian vault brain, filesystem MCP lane, statusline+hook proposals, vault skills |
| `d7ce0d0829` | 2026-08-17 | True | constitution | port-clean | isolated | chore(recovery): serena-first wiring ships as an owner-run command |
| `4a885c89b5` | 2026-08-17 | True | constitution | port-clean | isolated | chore(recovery): the beast settings file, ready to copy |
| `95107d232f` | 2026-08-17 | True | docs | port-clean | sequential-after-deps | vault: session journal, gate log and amendment ledger reflect the landing day |
| `b8e3d26356` | 2026-08-17 | True | docs | port-clean | sequential-after-deps | vault: the clean full-suite baseline enters the gate journal |
| `1a76ea4040` | 2026-08-17 | True | docs | port-clean | sequential-after-deps | vault: the authoritative record surfaces inside Obsidian through a junction |
| `4ef4ff79ce` | 2026-08-17 | True | docs | port-clean | sequential-after-deps | chronicle: the handoff stops pointing at a tree that moved |
| `e289b4c6b3` | 2026-08-18 | True | constitution | port-needs-rework | sequential-minus-identical-files | vault: two days enter the journal -- 265 failures to a production-signed matrix |
| `49263fc3c0` | 2026-08-18 | True | constitution | port-clean | sequential-after-deps | vault: the crew workflow catches the gate's most dangerous piece |
| `ef9cd22b31` | 2026-08-20 | True | research | port-clean | isolated | experiment: the intervention algebra takes its first measurements |
| `8350954c01` | 2026-08-20 | True | docs | port-clean | sequential-after-deps | vault: the day the algebra was measured and the liar was caught |
| `e901afcf74` | 2026-08-21 | True | research | port-clean | sequential-after-deps | experiment: pumplab catches the coupling nobody declared |
| `accd251323` | 2026-08-21 | True | research | port-needs-rework | none | experiment: chemlab proves the detector can stay silent |
| `886e877cda` | 2026-08-21 | True | research | port-needs-rework | none | experiment: textlab finds the words the footprint language lacks |
| `f9fab99c7a` | 2026-08-21 | True | research | port-clean | sequential-after-deps | experiment: sixteen steps of drift and the commutator stays silent |
| `65effb8168` | 2026-08-21 | True | research | port-needs-rework | none | experiment: one gluing assay finds what fifteen pairs were hunting |
| `0c294ba8ce` | 2026-08-21 | True | structcore-distillates | port-clean | sequential-after-deps | distill: the gardener's weeds come out and the engine sees itself once |
| `e0c44fd0af` | 2026-08-21 | True | docs | port-needs-rework | none | vault: the night the gardener, the falsifier and the watchdog worked as one |
| `5295c36f44` | 2026-08-21 | True | docs | port-clean | sequential-after-deps | vault: the vetting gate is itself vetted, and found half-open |
| `fb48a30692` | 2026-08-21 | True | docs | port-needs-rework | none | vault: the guard blocker is measured, not guessed, and vet goes to Minos |
| `6ec7d2cb8c` | 2026-08-21 | True | safety | port-needs-rework | none | safety(vet): the vetting gate scans the frontmatter and MCP egress can BLOCK |
| `c264f5dd22` | 2026-08-21 | True | docs | port-needs-rework | none | vault: the vetting gate is hardened and the fence held under Cerberus |
| `3e75839284` | 2026-08-21 | True | constitution | port-needs-rework | none | amendment(003): the serena-first hook is wired and the ledger carries it |
| `afd2968db3` | 2026-08-22 | False | docs | port-clean | isolated | archive: the 2026-07-30 swarm output leaves the research shelf, history intact |
| `1bf3fcf5c1` | 2026-08-22 | False | docs | port-clean | isolated | inventory: the 2026-08-21 full-tree inventory lands in the tree, map refreshed |
| `77e7498a76` | 2026-08-22 | False | docs | port-clean | isolated | plan: the giga plan draft lands beside the inventory, pending codex round 2 |
| `14238a300a` | 2026-08-22 | False | docs | port-clean | isolated | plan: the giga plan gets a plain-language companion for the owner |
| `8bd2b9a68f` | 2026-08-22 | False | constitution | port-clean | isolated | recovery: the unify, guard-retirement and house-cleanup kits, plus the docs watchdog |
| `aede2fc7f9` | 2026-08-22 | False | constitution | port-clean | sequential-after-deps | recovery: the unify kit also carries the docs-sweep prompt across |

## 5. Research asset table

Source: [research_census.json@fcae26a7] (2026-08-22T06:58:09.440176+00:00 .. 2026-08-22T07:12:07.442265+00:00); pytest commands `python -m pytest -q -p no:cacheprovider --color=no <targets>` in the disposable worktrees; counts MEASURED, wall INHERITED-under-load.

| line | sha | asset | path | present | tests present | tests green | anchor | note |
|---|---|---|---|---|---|---|---|---|
| checkpoint | 3e758392 | higher_twin_nc | `runs/higher_twin_nc/` | True | 9 | True | docs/research/HIGHER_TWIN_NC_LAYER2_2026-08-20.md;runs/higher_twin_nc/receipts/priorart-sw | spec_rev=2 (Schicht 2: Descent/Geometrie; Revision 1 = 30-Pass-Design vom 2026-08-18) collected=63 passed=63 failed=None |
| checkpoint | 3e758392 | layer2_doc | `docs/research/HIGHER_TWIN_NC_LAYER2_2026-08-20.md` | True | 0 | None |  | sha256=5130e981cdd9 bytes=9957 |
| checkpoint | 3e758392 | latent_ceiling_doc | `docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md` | True | 0 | None |  | sha256=0f8e4b4b8d40 bytes=5865 |
| checkpoint | 3e758392 | type_graph_plan | `docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md` | True | 8 | True |  | sha256=1e8dd1f9cf5c bytes=49811 |
| checkpoint | 3e758392 | type_graph_plan | `docs/research/TYPE_GRAPH_IMPLEMENTATION_REPORT.md` | True | 8 | True |  | sha256=22e4df6e3157 bytes=37189 |
| checkpoint | 3e758392 | forest_v2 | `experiments/forest_v2/` | False | 0 | None |  | slices= missing_dirs=s01,s02,s03,s04,s05,s06,s07,s08,s09,s10 collected=None passed=None failed=None |
| checkpoint | 3e758392 | eval_ceiling | `daedalus/eval/ceiling.py` | True | 1 | True | docs/research/rounds/round1/ceiling-vs-graphdelta.md;docs/research/rounds/round2/v-ceiling | test_files=tests/test_temporal_ceiling.py passed=16 failed=0 |
| checkpoint | 3e758392 | graph_delta | `daedalus/eval/graph_delta.py` | True | 1 | True | docs/research/GRAPH_DELTA_CALIBRATION.md;runs/eval/graph_delta.json;runs/eval/graph_delta_ | test_files=tests/test_graph_delta.py passed=25 failed=0 |
| checkpoint | 3e758392 | mutate | `daedalus/eval/mutate.py` | True | 1 | True | runs/eval/deepseek_impl20/v01-verify-mutate-operators.json;runs/eval/deepseek100/x09-graph | test_files=tests/test_mutation_score.py passed=26 failed=0 |
| checkpoint | 3e758392 | gate_discrimination | `tools/gate_discrimination.py` | True | 1 | True |  | test_files=tests/test_gate_discrimination.py passed=44 failed=0 |
| checkpoint | 3e758392 | gate_discrimination | `docs/GATE_DISCRIMINATION.md` | True | 1 | True |  | test_files=tests/test_gate_discrimination.py passed=44 failed=0 |
| trunk | 93f11adf | higher_twin_nc | `runs/higher_twin_nc/` | False | 0 | None |  | spec_rev=None collected=None passed=None failed=None |
| trunk | 93f11adf | layer2_doc | `docs/research/HIGHER_TWIN_NC_LAYER2_2026-08-20.md` | False | 0 | None |  | sha256= bytes=None |
| trunk | 93f11adf | latent_ceiling_doc | `docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md` | True | 0 | None |  | sha256=0f8e4b4b8d40 bytes=5865 |
| trunk | 93f11adf | type_graph_plan | `docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md` | True | 8 | True |  | sha256=1e8dd1f9cf5c bytes=49811 |
| trunk | 93f11adf | type_graph_plan | `docs/research/TYPE_GRAPH_IMPLEMENTATION_REPORT.md` | True | 8 | True |  | sha256=22e4df6e3157 bytes=37189 |
| trunk | 93f11adf | forest_v2 | `experiments/forest_v2/` | True | 12 | True | experiments/forest_v2/README.md;docs/GATE2_FOREST_V2_TRIAGE.md | slices=s01,s03,s04,s05,s06,s08,s10 missing_dirs=s02,s07,s09 collected=442 passed=442 failed=None |
| trunk | 93f11adf | eval_ceiling | `daedalus/eval/ceiling.py` | True | 1 | True | docs/research/rounds/round1/ceiling-vs-graphdelta.md;docs/research/rounds/round2/v-ceiling | test_files=tests/test_temporal_ceiling.py passed=16 failed=0 |
| trunk | 93f11adf | graph_delta | `daedalus/eval/graph_delta.py` | True | 1 | True | docs/research/GRAPH_DELTA_CALIBRATION.md;runs/eval/graph_delta.json;runs/eval/graph_delta_ | test_files=tests/test_graph_delta.py passed=25 failed=0 |
| trunk | 93f11adf | mutate | `daedalus/eval/mutate.py` | True | 1 | True | runs/eval/deepseek_impl20/v01-verify-mutate-operators.json;runs/eval/deepseek100/x09-graph | test_files=tests/test_mutation_score.py passed=26 failed=0 |
| trunk | 93f11adf | gate_discrimination | `tools/gate_discrimination.py` | True | 1 | True |  | test_files=tests/test_gate_discrimination.py passed=44 failed=0 |
| trunk | 93f11adf | gate_discrimination | `docs/GATE_DISCRIMINATION.md` | True | 1 | True |  | test_files=tests/test_gate_discrimination.py passed=44 failed=0 |

| asset | CHECKPOINT pytest | TRUNK pytest |
|---|---|---|
| runs/higher_twin_nc | 63 passed in 123.17s (0:02:03) (9 test files) | absent |
| experiments/forest_v2 | absent | 442 passed in 38.38s (collected 442) |
| eval assets combined (gate_discrimination, graph_delta, mutation_score, temporal_ceiling) | 111 passed in 111.10s (0:01:51) | 111 passed in 60.18s (0:01:00) |
| type-graph tests (8 files) | green True | green True |

Byte identity across lines (blob ids):

| path | checkpoint blob | trunk blob | identical |
|---|---|---|---|
| `daedalus/eval/ceiling.py` | c139806629 | f738380925 | False (8 0 daedalus/eval/ceiling.py) |
| `daedalus/eval/graph_delta.py` | 4fa9250c28 | a6823c47c2 | False (8 0 daedalus/eval/graph_delta.py) |
| `daedalus/eval/mutate.py` | 14a596cee4 | 14a596cee4 | True  |
| `docs/GATE2_FOREST_V2_TRIAGE.md` | None | 56293f986c | None  |
| `docs/GATE_DISCRIMINATION.md` | 8e2ba0a3e7 | 8e2ba0a3e7 | True  |
| `docs/research/GRAPH_DELTA_CALIBRATION.md` | 04ecac085c | 04ecac085c | True  |
| `docs/research/HIGHER_TWIN_NC_LAYER2_2026-08-20.md` | 434d8ef672 | None | None  |
| `docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md` | 65790360fc | 65790360fc | True  |
| `docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md` | 6aa2b4773a | 6aa2b4773a | True  |
| `docs/research/TYPE_GRAPH_IMPLEMENTATION_REPORT.md` | 01b537839e | 01b537839e | True  |
| `docs/research/rounds/round1/ceiling-vs-graphdelta.md` | f4bb3e94a2 | f4bb3e94a2 | True  |
| `docs/research/rounds/round2/v-ceiling-vs-graphdelta.md` | ea4b353cd5 | ea4b353cd5 | True  |
| `experiments/forest_v2/README.md` | None | 562df46e04 | None  |
| `runs/eval/deepseek100/x09-graphdelta-vs-mutate.json` | ff8d77ba31 | ff8d77ba31 | True  |
| `runs/eval/deepseek_impl20/v01-verify-mutate-operators.json` | bf91d13e32 | bf91d13e32 | True  |
| `runs/eval/deepseek_lab/w09-typegraph-ceiling.json` | a76f4c9903 | a76f4c9903 | True  |
| `runs/eval/deepseek_r2/v-ceiling-vs-graphdelta.json` | 9d7c443c7e | 9d7c443c7e | True  |
| `runs/eval/graph_delta.json` | 2da3428c1b | 2da3428c1b | True  |
| `runs/eval/graph_delta_held_out.json` | 2913ee2b41 | 2913ee2b41 | True  |
| `runs/eval/graph_delta_specificity.json` | f889483295 | f889483295 | True  |
| `runs/higher_twin_nc/SPEC.md` | 4518e6db3b | None | None  |
| `runs/higher_twin_nc/WATCHDOG_MISSION.md` | aef52d024e | None | None  |
| `runs/higher_twin_nc/receipts/priorart-sweep-20260820.json` | 93b775d297 | None | None  |
| `tools/gate_discrimination.py` | da22482017 | 25e9275d7f | False (10 0 tools/gate_discrimination.py) |

Ceiling corpus: `docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md` names a corpus file: False (status line: 'Written 2026-07-30. **Not yet run** — it must not run concurrently wit'); doc rows [{"source": "write-lane substitutions", "n": 3}, {"source": "invented first-party imports", "n": 3}, {"source": "wrong-assumption test failures", "n": 4}, {"source": "UNWIRED false positives", "n": "147 of 154"}, {"source": "fan-out claims with no corroboration", "n": 1226}]; UNWIRED marker under runs/funnel: 0 files (both lines); whole-worktree scan (checkpoint): 124 files carry the marker of 3942 scanned; resolved sources on disk on both lines: runs/eval/census300/ (301 files), runs/eval/research40/_all.json, q26-fan-out-without-corroboration.json. LATENT_CEILING doc byte-identical on both lines -> Phase 0b is line-neutral for that doc; `runs/higher_twin_nc/SPEC.md` exists on exactly one line (checkpoint).

Measured discrepancies recorded by the census: regex count of 'def test_' in test_mutation_score.py = 35 on both lines; pytest collected/passed = 26 (nested/helper defs or skipped-by-marker cases); both numbers MEASURED, pytest is authoritative. | slices s02, s07, s09 exist only as mentions in README.md / GATE2_FOREST_V2_TRIAGE.md on the trunk, not as directories at 93f11adf. | LATENT_CEILING_SHARED_REPRESENTATION.md names no corpus file; it lists five rows and says they are 'on disk'. See whole_worktree_scan for what was found.

## 6. Options for D1 with measured cost rows

### Option A -- TRUNK canonical; CHECKPOINT frozen to read-only harvest; amendment 003 replayed

| cost row | measured value | receipt |
|---|---|---|
| harvest rows to port (pinned set) | 37 = 26 clean + 10 rework + 1 drop; plus 6 beyond-pin rows (all port-clean) if the owner admits them | [harvest_manifest.json@18fd6b3b] |
| manual merges (3-way leaves conflict markers) | 3: `a83db1f5` promotion_approval + spine/attempt.py + effect_boundary.py (8 files, protected); `6ec7d2cb` vet.py + tests/test_tools_vet.py (2 files); `3e758392` amendment 003 itself (plan + ledger + .claude/settings.json, protected -> NOT a patch, a ledger replay) | [harvest_manifest.json@18fd6b3b] |
| higher_twin_nc research chain blocked by trunk divergence in `tools/agent_findings.py` + `tools/audit_triage.py` | 3 commits (`accd2513`, `886e877c`, `65effb81`) + 3 vault-session rows blocked behind them; alternative = blob port of `runs/higher_twin_nc/` (85 tracked files, 63 tests green on checkpoint) | [harvest_manifest.json@18fd6b3b] [research_census.json@fcae26a7] |
| ledger records appended to the winning chain | 1 reconciliation record (rev 7) + 1 serena-first replay (rev 8) via `docs/recovery/amendment_003_serena_first_kit.py` (row `d7ce0d08`, port-clean) -- owner's hand, sec. 15 | plan Phase 1; [harvest_manifest.json@18fd6b3b] |
| trunk debts inherited by the survivor | 3 suite failures (self-consistency: landed-verdict tuple, undeclared record producer, unparseable corpus fixture); fault-matrix verdict unbound to 93f11adf (blocker); 10 inventory_only doors; runtime-conformance receipts unbound; security_boundary_claimed false; 101/285 modules unreachable | [census_trunk.json@c80cdad2] [census_trunk_counters.json@179a44f1] [reachability.json@5faa9a02] |
| trust root on the survivor | TRUNK HMAC root: 5 FAIL (A9a, A9c1, A10, A10b, A12) -> D5 migration to the CHECKPOINT mechanism (0 FAIL) is prescribed by the trunk's own `docs/GATE0_PROMOTION_TRUST_ROOT_FINDING.md`; the mechanism ports as row `a83db1f5` (rework) | [trust_root_report.json@77468761] |
| operational hazard to fix before any by-path tool run on the survivor | editable `.pth` points at `C:/Users/nukei/Desktop/agent_env/daedalus` (checkpoint primary); re-point or always set PYTHONPATH | [census_trunk_import_contamination.json@ce450417] |
| what is NOT lost | docs-class rows (all 43) are 17 clean + 3 rework (vault/Sessions/2026-08-21.md chain) + 1 drop (GESAMTPLAN already byte-identical on trunk); LATENT_CEILING, TYPE_GRAPH docs, GATE_DISCRIMINATION.md, GRAPH_DELTA_CALIBRATION.md already byte-identical on both lines | [harvest_manifest.json@18fd6b3b] [research_census.json@fcae26a7] |

### Option B -- CHECKPOINT canonical; TRUNK scopes re-proposed as amendments

| cost row | measured value | receipt |
|---|---|---|
| trunk-only commits that become non-canonical history | 1228 (1217 with patch-id) | [ancestry.json@56c9b554] [harvest_manifest.json@18fd6b3b] |
| trunk ledger records that become non-canonical and must be re-proposed | 5 (seq 2-6: Genesis + dual-layer execution chain v1.1.0; sealed promotion + bounded Gate-1 rehearsal v1.2.0; guard strangler v1.2.1; Gate-0 closure package v1.2.2; Gesamtplan authority v1.2.3) -- plan names the scopes fourfold-project-twin / repository-atlas / genesis / llm-proposal-operators | [chain_report.json@a3826fe5] |
| kernel surface absent on the survivor | `daedalus/kernel` (23 modules) and `daedalus/gates` (35 modules) do not exist; effect-boundary registry 18 rows vs 84; entrypoints 99 vs 176; `promote_candidates` has 0 approval parameters (Invariant 5 sealed promotion not wired); `promotion_approval.py` has 0 callers | [reachability.json@5faa9a02] |
| reverse research assets to port | 82 assets (forest_v2 78 files / 442 tests green; ceiling.py + graph_delta.py +8 lines each; gate_discrimination.py diverged) | [harvest_manifest.json@18fd6b3b] [research_census.json@fcae26a7] |
| checkpoint debts inherited by the survivor | 3 suite failures (conftest shadowing, fix unapplied; 2 stale iron_plan_guard tests); effect_boundary_check rc 2 with 15 BLOCKERs (12 unregistered tools.*, 1 effect drift, 2 unguarded entrypoints incl. promote_candidates); no `daedalus.gates` reporter -> the five Gate-0 counters cannot be measured on this line; system_check 14/18; loop governance verdict bound to another tree (F3) | [census_checkpoint.json@a4798ce9] [loop_trace.json@621aca9f] |
| trust root on the survivor | CHECKPOINT asymmetric git-tag root: 0 FAIL of 23 scored, but 0 production callers -> wiring work (not measured) | [trust_root_report.json@77468761] [reachability.json@5faa9a02] |

### Option C -- neither, until a named gap is fixed

| candidate named gap | measured state | cost to close | receipt |
|---|---|---|---|
| C1 fence receipt (one denied protected write per PRIMARY worktree, verbatim) | **MISSING** -- the plan lists it as the precondition codex seats 1-5 demand before any ruling | two denied write attempts + one JSON receipt; ruling-invariant; minutes | receipt inventory (section 1) |
| C2 trunk fault-matrix verdict bound to exact head | no archived verdict cites 93f11adf; 4 verdicts cite c93191fe / 1e681b9b / 4fb2251d / bcc0feaf | re-run the whole matrix at the survivor head (production-signed closure matrix took 3 columns / 24 observations); ruling-invariant: must happen on whichever survivor | [census_trunk_counters.json@179a44f1] |
| C3 cross-tree import contamination | editable .pth -> checkpoint primary; by-path tools on the trunk import the wrong tree | re-point the editable install or pin PYTHONPATH; ruling-invariant hygiene | [census_trunk_import_contamination.json@ce450417] |
| C4 trust root (D5) | TRUNK 5 FAIL; CHECKPOINT 0 FAIL but unwired | migration already prescribed by trunk's own finding; not a D1 discriminator because the checkpoint module is portable (row a83db1f5) | [trust_root_report.json@77468761] |
| C5 symmetric measurements not taken | loop trace, system_check, run_gate_checks, gate_host_preflight each exist on ONE line only | re-run on the other line if the owner wants symmetry before ruling; none of them changes the kernel or chain rows | sections 1-2 |
| cost of waiting | the checkpoint tip moved +6 commits during Phase 0 (77e7498a -> aede2fc7), all docs/recovery/inventory (port-clean); the trunk tip did not move; every day of C adds harvest rows on the checkpoint side only | [harvest_manifest.json@18fd6b3b] [ancestry.json@56c9b554] |

## 7. Recommendation written from the table

Row-by-row, which line the table favours (tie = no information for D1):

| row | favours | why (numbers above) |
|---|---|---|
| chain valid | tie | both chains validate end-to-end; record 1 byte-identical; both record-2s build on the same base plan digest |
| plan digest at pin | tie | both match their latest record result; guard verify rc 0 on both |
| suite | tie on count (3 vs 3); lean TRUNK on kind | checkpoint reds are 1 order-dependent conftest collision + 2 stale guard tests; trunk reds are 3 self-consistency drifts of landed evidence/fixtures. Neither set is a kernel defect. Whether trunk's 3 are inside the 'documented 20 named lines' is MISSING |
| Gate-0 instrumentation | TRUNK | the five counters are measurable only on the trunk (reporter exists, blockers explicit, 10 doors named, assert_gate_report discriminates); the checkpoint has no gates package and effect_boundary_check exits 2 with 15 BLOCKERs incl. an unguarded promote_candidates |
| one kernel (Invariant 1) | TRUNK | 76/21/34 entrypoints reach spine AND kernel on one call path; Lens A's 'three kernels' refuted as stated; checkpoint has one spine but no approval-bearing promotion path (0 approval params, promotion_approval unreachable) -- Invariant 5 is wired on the trunk and not on the checkpoint |
| trust root (D5) | CHECKPOINT mechanism, TRUNK wiring | 0 FAIL vs 5 FAIL, and the trunk's own binding finding prescribes the checkpoint's mechanism; the mechanism is one rework row (a83db1f5) -> this row decides D5, not D1 |
| harvest cost | TRUNK | A = 37 rows (26 clean / 10 rework / 1 drop, 3 manual merges, 1 kit replay); B = 1228 commits + 5 ledger scopes re-proposed + 82 reverse assets + the absent kernel/gates packages |
| research assets | tie | each line holds one exclusive green asset (higher_twin_nc 63/63 on checkpoint; forest_v2 442/442 on trunk); both port as blobs; shared docs byte-identical |
| loop trace | no information | measured on the checkpoint only; its findings (F3 cross-tree governance verdict, F6 non-atomic snapshot, F9 socket blind spot) are code facts to carry onto the survivor, not a line discriminator |
| Phase-0 'done when' | incomplete | fence receipt MISSING; zero rows 'declared' otherwise satisfied; loop trace names effects-before-guard = 0 and a freshness fraction |

**Recommendation: Option A (TRUNK canonical, CHECKPOINT frozen to read-only harvest, amendment 003 replayed), with the ruling itself deferred until the fence receipt exists (gap C1, minutes), and with C2 (fault-matrix rebind at the survivor head), C3 (editable-install re-point) and D5 (trust-root migration to the checkpoint's asymmetric mechanism, row a83db1f5) recorded as named debts on the survivor.** This follows from the Gate-0 instrumentation row, the one-kernel row and the harvest-cost row; it does not follow from the 1228-commit count, which is a cost row for B, not evidence for A. The plan's four preconditions for the trunk default read against the table: chain validates (yes); reporter runs at exact head (yes, `--source-revision 93f11adf` rc 0, but its fault-injection evidence is NOT bound to that head -> C2); census shows no real suite failures beyond the documented lines (3 failures, none a kernel defect; membership in the documented 20 is MISSING); reachability shows one live kernel (yes). Option B is not supported by any row except the trust-root mechanism, which is portable. Option C is the correct state for exactly as long as C1 is missing; the other C-gaps are ruling-invariant and should not hold the ruling.

## 8. Tasks that came back partial, blocked, or not run -- with every denial verbatim

| task | status | what is missing or inconclusive |
|---|---|---|
| fence (plan Phase-0 action `preruling_fence`) | **MISSING** | no receipt; no protected-write attempt on either primary worktree was recorded |
| census_checkpoint | partial | F3 conftest-shadowing mechanism INFERRED: the decisive isolation run (`pytest runs/higher_twin_nc/tests tests/test_dotenv.py`) was DENIED (denial 4 below); `tools/gate_discrimination.py` deliberately NOT RUN; `run_gate_checks.py`, `system_check` only here (not on trunk) |
| census_trunk | partial | `run_gate_checks.py g0` first run contaminated (ImportError), pinned rerun 87 passed; `system_check.py`, `gate_host_preflight.py` not run on this line; probe copy into worktree tools/ DENIED (measured from outside instead) |
| trust_root | partial | A9c live container canary INCONCLUSIVE-live (Docker engine unreachable, A9c0); sandbox env isolation asserted from argv shape only (A9b); neither module tested as wired into a promotion callable |
| loop_trace | partial | CHECKPOINT only; TRUNK not traced; F4 committed-snapshot numbers (11->0, 16->5) live in finding text, raw picker data in the receipt was taken on a regenerated working copy (23->0, 46->23); `.env` read-before-guard ordering not exercised |
| reachability | complete with declared unsoundness | intra-package only; dynamic imports not edged; static reachability is not execution |
| harvest_manifest | complete | checkpoint tip moved during the run (43 rows instead of 37; the 6 extra are flagged beyond-pin) |
| research_census | complete | ceiling corpus: the doc names no corpus file; sources resolved on disk by scan |

### Denials verbatim (guard / classifier), grouped by receipt

| # | receipt | command / step (receipt wording) | denial verbatim | handled |
|---|---|---|---|---|
| 1 | setup.json | PreToolUse:Bash hook, direct shell invocations (5 denials total) | Protected Iron Plan artifact(s) cannot change in ordinary work: <repository policy bundle>. Follow the owner-approved amendment protocol. | Every denied Bash command contained the substring 'git merge-base'. The identical read-only calls succeeded when issued by preruling_ancestry.py via subprocess  |
| 2 | chain_report.json | inline bash: git show <pin>:<ledger_rel> / python -c ... (read-only listing of ledger records) | Protected Iron Plan artifact(s) cannot change in ordinary work: docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl. Follow the owner-approved amendment protocol. | PreToolUse guard fired on the protected path string appearing in the Bash command line; the command was read-only. Not worked around: the prescribed method (scr |
| 3 | chain_report.json | inline bash: cat > scratchpad/preruling_chains_config.json <<EOF (heredoc whose content named the three protected relative paths) | Protected Iron Plan artifact(s) cannot change in ordinary work: docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl, docs/IKARUS_ARIADNE_MASTER_PLAN.md, tools/iron_plan_guard.py. Follow the owner-approved amendment protocol. | Guard matched the path strings inside the heredoc body; the write target was the scratchpad. The config was written with the Write tool (target path in scratchp |
| 4 | census_checkpoint.json | ls tools/ ... (read-only listing) | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: tools>. Follow the owner-approved amendment protocol. | - |
| 5 | census_checkpoint.json | find . -name '*.py' / xargs grep -l ... (read-only search) | Protected Iron Plan artifact(s) cannot change in ordinary work: daedalus/config.py, daedalus/kairos/gated_writes.py, daedalus/sensitivity.py, tools/iron_plan_guard.py, tools/iron_plan_hook_runner.py, tests/test_iron_plan_guard.py, <directory: .git>. Follow the owner-approved amendment protocol. | - |
| 6 | census_checkpoint.json | ls conftest.py tests/conftest.py; grep -rn _OPERATOR_DECLARATIONS (read-only) | Protected Iron Plan artifact(s) cannot change in ordinary work: daedalus/config.py, daedalus/kairos/gated_writes.py, daedalus/sensitivity.py, tools/iron_plan_guard.py, tools/iron_plan_hook_runner.py, tests/test_iron_plan_guard.py. Follow the owner-approved amendment protocol. | - |
| 7 | census_checkpoint.json | pytest runs/higher_twin_nc/tests tests/test_dotenv.py (shadowing isolation experiment) | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: tests>. Follow the owner-approved amendment protocol. | - |
| 8 | census_checkpoint.json | git ls-files runs/higher_twin_nc/tests/ (read-only) | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: tests>. Follow the owner-approved amendment protocol. | - |
| 9 | census_checkpoint.json | python -c rglob conftest.py + git ls-files --error-unmatch (read-only) | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: .git>. Follow the owner-approved amendment protocol. | - |
| 10 | census_trunk.json | attempting to copy a probe script into the worktree's tools/ directory to measure import resolution | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: daedalus>, <directory: tools>. Follow the owner-approved amendment protocol. | Not worked around. The same resolution was measured with a probe script kept outside the worktree, which reproduces the identical sys.path[0] condition. |
| 11 | reachability.json | cd <preruling-cp> && git rev-parse HEAD && ls -d daedalus/*/ && for d in spine kernel gates kairos; do ...; done | Protected Iron Plan artifact(s) cannot change in ordinary work: daedalus/config.py, daedalus/kairos/gated_writes.py, daedalus/sensitivity.py, <directory: daedalus>. Follow the owner-approved amendment protocol. | - |
| 12 | reachability.json | cd <preruling-cp> && git rev-parse HEAD && python -c "import os; ... os.path.join('daedalus', d) ..." | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: daedalus>. Follow the owner-approved amendment protocol. | - |
| 13 | reachability.json | python -c "...rows for 'cli.daedalus', 'console:daedalus'..." | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: daedalus>. Follow the owner-approved amendment protocol. | - |
| 14 | trust_root_report.json | git ls-files 'daedalus/**' / grep ... (CHECKPOINT worktree) | Protected Iron Plan artifact(s) cannot change in ordinary work: daedalus/config.py, daedalus/kairos/gated_writes.py, daedalus/sensitivity.py, <directory: daedalus>. Follow the owner-approved amendment protocol. | read-only listing refused; no write was attempted |
| 15 | trust_root_report.json | git ls-files / grep -iE 'sandbox/attempt/...' / grep -v tests/ | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: tests>. Follow the owner-approved amendment protocol. | read-only listing refused; no write was attempted |
| 16 | trust_root_report.json | git ls-files -- daedalus / grep -iE 'sandbox/attempt/...' | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: daedalus>. Follow the owner-approved amendment protocol. | read-only listing refused; no write was attempted |
| 17 | loop_trace.json | cd <preruling-cp> && grep -n "install_process_guard" daedalus/*.py daedalus/**/*.py / head -30 && sed -n '1050,1120p' daedalus/cli.py | Protected Iron Plan artifact(s) cannot change in ordinary work: daedalus/config.py, daedalus/kairos/gated_writes.py, daedalus/sensitivity.py. Follow the owner-approved amendment protocol. | READ-ONLY grep + sed |
| 18 | loop_trace.json | cd <preruling-cp> && ls daedalus/kairos/ / head -40; find . -name "picker*.py" -not -path "./.git/*" | Protected Iron Plan artifact(s) cannot change in ordinary work: .git/config, <directory: .git/iron-plan-hook-state>, <directory: daedalus/kairos>, <directory: .git>. Follow the owner-approved amendment protocol. | READ-ONLY ls + find |
| 19 | loop_trace.json | cd <preruling-cp> && grep -rn "architecture-state" --include=*.py . | Protected Iron Plan artifact(s) cannot change in ordinary work: daedalus/config.py, daedalus/kairos/gated_writes.py, daedalus/sensitivity.py, tools/iron_plan_guard.py, tools/iron_plan_hook_runner.py, tests/test_iron_plan_guard.py, <directory: .git>. Follow the owner-approved amendment protocol. | READ-ONLY recursive grep |
| 20 | loop_trace.json | cd <preruling-cp> && grep -n "environ.get/getenv" daedalus/budget.py; grep -rn "DAEDALUS_OFFLINE/..." --include=*.py daedalus/ | Protected Iron Plan artifact(s) cannot change in ordinary work: daedalus/config.py, daedalus/kairos/gated_writes.py, daedalus/sensitivity.py, tools/iron_plan_guard.py, tools/iron_plan_hook_runner.py, tests/test_iron_plan_guard.py, <directory: daedalus>. Follow the owner-approved amendment protocol. | READ-ONLY grep |
| 21 | loop_trace.json | Grep pattern 'MARKER/def stopped/STOP_REL/_marker_path/KILL_REL' over daedalus/spine/killswitch.py | Serena is running and this Grep ('MARKER/def stopped/STOP_REL/_marker_path/KILL_REL') is a symbol lookup: the pattern names the declaration keyword 'def'. Use mcp__serena__find_symbol (name_path, optionally relative_path) instead -- it resolves through the language server, so it returns the definition with its body and location and does not miss declarations the regex fails to match. For call sites use mcp__serena__find_referencing_symbols. If you genuinely want a text search, drop the declaration keyword from the pattern. | READ-ONLY content search |
| 22 | harvest_manifest.json | Bash heredoc writing this very config file into the scratchpad | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: .agentenv>, <directory: docs>. Follow the owner-approved amendment protocol. | denial recorded; the scratchpad config was written with the dedicated Write tool instead (no protected artifact touched; the guard matched path-name strings ins |
| 23 | harvest_manifest.json | Bash heredoc (python - <<EOF) patching the scratchpad measurement script; the heredoc text contained the glob string tests/test_*.py | Protected Iron Plan artifact(s) cannot change in ordinary work: tests/test_iron_plan_guard.py, <repository policy bundle>, <directory: tests>. Follow the owner-approved amendment protocol. | denial recorded; the same scratchpad-script edits were applied with the dedicated Edit tool (no repository file touched) |
| 24 | research_census.json | git ls-tree -r --name-only <sha> / grep -E '^tests/...' (read-only listing of test files on both pins) | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: tests>. Follow the owner-approved amendment protocol. | - |
| 25 | research_census.json | git grep -l UNWIRED <sha> -- runs docs (read-only search for the ceiling corpus) | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: docs>. Follow the owner-approved amendment protocol. | - |
| 26 | research_census.json | cd <disposable cp worktree> && grep -rl UNWIRED runs/funnel (read-only search in the disposable worktree) | Protected Iron Plan artifact(s) cannot change in ordinary work: .agentenv/agentenv.json, .agentenv/tool-allowances.json, .claude/settings.json, .codex/hooks.json, templates/agentenv.json, .claude/settings.local.json, docs/IKARUS_ARIADNE_MASTER_PLAN.md, AGENTS.md, CLAUDE.md, .agents/skills/enforce-iron-plan/SKILL.md, docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl. Follow the owner-approved amendment protocol. | - |
| 27 | research_census.json | cat > <scratchpad>/preruling_research_census_config.json <<EOF (heredoc body contained the glob 'runs/higher_twin_nc/tests/') | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: tests>. Follow the owner-approved amendment protocol. | - |
| 28 | research_census.json | python - <<EOF (inline printer of the receipt; heredoc body contained the string 'tests=') | Protected Iron Plan artifact(s) cannot change in ordinary work: <directory: tests>. Follow the owner-approved amendment protocol. | - |

Total denial entries recorded across receipts: 28 (setup.json folds its 5 denials into one entry, so individual denial events = 32). Per the receipts, every one fired on a read-only command, a scratchpad heredoc, or a probe copy; none blocked a write to a protected artifact; none was worked around (the prescribed by-path script method was used instead). The one measurement lost to a denial is the conftest isolation run (census_checkpoint denial 4). The pattern -- the guard matches protected path tokens and `git merge` as a prefix of `git merge-base` in read-only payloads -- is the D6 input the plan already names (guard match rule on write intent).

Packaging task itself: no denial was raised while building this package.

## 9. Receipt legend (full sha256 of each receipt file as read by this script)

| key | path | sha256 |
|---|---|---|
| ancestry | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/ancestry.json` | 56c9b554d05974c4995a54fa4b17a91ca6cc7cacf97b0dbd0ef7f2719b8e1a51 |
| chain_report | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/chain_report.json` | a3826fe5239b2d3eeabf85a64e44b86093d0e3b75079f44a78855b86192ca54f |
| census_trunk | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/census_trunk.json` | c80cdad235f57fbae859147732252cf1a5146269d92ee33b71504a552143a539 |
| census_trunk_counters | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/census_trunk_counters.json` | 179a44f1a5c921c0260792e1c65decb6f017e3d2d164d3feef6119fdac272101 |
| census_trunk_import_contamination | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/census_trunk_import_contamination.json` | ce450417139e8f5b941418f70469ec14888c1c63e6bf733c47b2cb10ac177a79 |
| census_trunk_guard_crosstree | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/census_trunk_guard_crosstree.json` | e663d39e4dcc7c2cda52cf0cdacfccff9ee13c42860f1647917d4e2a4f672861 |
| census_checkpoint | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/census_checkpoint.json` | a4798ce9cdf6aa27d532a284046ae96eaeae378d6d96cf2ec59bf8553f324960 |
| reachability | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/reachability.json` | 5faa9a02c3e3336dc4c6d8396a3094930be10091ccad5cba7cc924cfaf9dd843 |
| trust_root_report | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/trust_root_report.json` | 774687610715823404b112b4052dac62d62d16a034dd7c9f957c885d0113a43c |
| trust_root_mutation_report | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/trust_root_mutation_report.json` | 0487a6d613c8c2e13500e692cb2043d5d4ff8707fb0092752d5ba2a85b84f774 |
| loop_trace | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/loop_trace.json` | 621aca9fad518878adccd7c869250990370803c59013583b2abe5ac913db2521 |
| harvest_manifest | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/harvest_manifest.json` | 18fd6b3bdd92a203bc0f0e3de58609ab8db8d418b1e328beff3cdf53c9dd0304 |
| research_census | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/research_census.json` | fcae26a7410bce0c89dff6ebe561e859b34793fc7ad6957c6b28bee930196e3f |
| setup | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/setup.json` | 59643f9ef49af7069d04e1db141cb662c9b96d3944804a7446ccc05d7630fd4b |
| worktrees | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/worktrees.json` | 329f9599f4d6535b3d9a393b6214ec73d51114df3ab5d9cb959d1efa54384d45 |
| fence | `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/preruling/fence.json` | MISSING |

Source tree shas: CHECKPOINT `3e758392845d9faf7877977d5ae8806973ed62e6` (checkpoint/2026-07-20-session), TRUNK `93f11adfb08efa713711fd62e9be7b46d8957166` (work/g0-trunk-20260817). Disposable worktrees: `C:/Users/nukei/Desktop/agent_env.worktrees/preruling-cp`, `.../preruling-g0`. No primary worktree was read for numbers or written by this package builder.

Iron Plan: ALIGNED  
Iron Gate: 0 (now CLOSED at HEAD 657c8af5, 2026-08-26; this package's evidence and D1 ruling predate closure)
Evidence: the receipts in the legend; this package is a projection of them and adds no measurement of its own.
**UPDATE 2026-08-26**: Gate 0 closure via owner decision (GATE0_CLOSURE_DECISION_20260826.md) sealed the phase described herein. The document's recommendations (Option A) have been canonicalized into the active gate. This record remains authoritative for the measured cost/evidence at 2026-08-22.

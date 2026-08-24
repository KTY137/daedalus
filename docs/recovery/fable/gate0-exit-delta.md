# Lane report: gate0-exit-delta

Lane: gate0-exit-delta (Fable long-context analysis, read-only)
Date: 2026-08-17
Trunk under measurement: `C:/Users/nukei/Desktop/agent_env_g0`, branch `work/g0-trunk-20260817`,
HEAD `60b2bfeb83d3886e4c1e8547e2481a8972e729a3` (worktree dirty in `runs/budget/ledger.json` +
4 files under `tests/gates/` — pre-existing, untouched by this lane).
Gesamtplan: `C:/Users/nukei/Desktop/agent_env/docs/DAEDALUS_GESAMTPLAN.md` (read completely, 1583 lines).
Constitution: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` revision 1 (Gate 0 active).

Method: every claim below is measured (file:line or a command actually run in the worktree).
Anything not measured is marked ASSUMED. No file in either checkout was modified except this report.

---

## (a) Schema comparison: Gesamtplan `daedalus-gate-report/1` vs trunk implementation

### Gesamtplan reference shape (12 fields)

Defined at DAEDALUS_GESAMTPLAN.md:291-306 and re-asserted verbatim in the exit test at :1126-1139:

```
schema, gate, closed, security_boundary_claimed,
unregistered_effectful_entrypoints, unguarded_entrypoints,
inventory_only_production_entrypoints, missing_guard_contracts,
runtime_conformance_failures, fault_injection_failures,
primary_checkout_mutations, owner_approval_enforced
```

### Trunk shapes

| Schema ID | Where | Field count | Delta vs Gesamtplan/1 |
|---|---|---:|---|
| `daedalus-gate-report/1` (trunk legacy) | `daedalus/gates/report.py:40-60` (`_V1_FIELDS`) | 17 | all 12 present + 5 extra: `source_revision`, `registry_sha256`, `diagnostics`, `blockers`, `report_sha256` |
| `daedalus-gate-report/2` (CLI default) | `report.py:23`, `_V2_FIELDS` :61-67 | 19 | v1 + `event_store_writer_inventory_sha256`, `event_store_writer_failures` (7 extra total) |
| `daedalus-gate-report/3` | `report_v3.py:28`, `_V3_FIELDS` :48-61 | 24 | v2 + `repository_write_inventory_sha256`, `repository_write_scan_input_sha256`, `repository_write_files_scanned`, `repository_write_inventory_generation`, `repository_write_failures` |

**Missing fields: none.** Every one of the Gesamtplan's 12 fields exists in all three trunk shapes.

**Extra fields:** 5 (trunk-v1) / 7 (v2) / 12 (v3), listed above.

### Structural deltas beyond field lists (all measured)

1. **Schema-ID collision on `daedalus-gate-report/1`.** The trunk reuses the exact Gesamtplan
   schema string for a 17-field shape. `GateReport.from_dict` enforces
   `set(payload) != expected_fields → ValueError` (report.py:320-322), so a literal
   Gesamtplan-example JSON (12 fields) claiming `daedalus-gate-report/1` is **rejected** by the
   trunk loader. The two documents mean different things by the same identifier.
2. **The Gesamtplan's own exit assertion would fail against the real artifact.** The CLI emits
   schema `/2` (measured output below); the plan's test asserts
   `report["schema"] == "daedalus-gate-report/1"` (GESAMTPLAN:1127).
3. **CLI signature mismatch.** Gesamtplan CI (GESAMTPLAN:1087-1091) invokes
   `python -m daedalus.gates report --gate 0 --format json --output gate0.json`.
   Actual `daedalus/gates/__main__.py:13-17` accepts only `--gate {0}`, `--repo-root`,
   and a **required** `--source-revision`; there is no `--format` and no `--output`.
   The documented invocation fails at argparse. The trunk's real CI uses the real signature
   (`.github/workflows/g0-gate-report-writer-inventory.yml:66-69, 85-89`).
4. **`closed` semantics are stronger in the trunk.** In the Gesamtplan `closed` is a plain field;
   in the trunk it is a derived property (report.py:203-209:
   `security_boundary_claimed AND owner_approval_enforced AND not blockers`) and both loaders
   verify the serialized value against the derivation (report.py:384-400, release.py:320-333).
   A hand-set `closed:true` is rejected. This is a favorable delta.
5. **v3 is wired to a separate script + workflow, not the module CLI.** `__main__.py` builds only
   the v2 report; v3 is produced by `scripts/report_gate0_v3.py` (workflow
   `g0-gate-report-repository-write-v3.yml`) and the release verifier `release.py:44`
   pins `_REPORT_SCHEMA = "daedalus-gate-report/2"` — the release path cannot consume v3 yet.

**Verdict (a): PARTIAL match — trunk is a validating superset; no Gesamtplan field is missing,
but the `/1` identifier is incompatible, the documented CLI call fails, and the plan's exit
assertion block is stale relative to the shipped artifact.**

---

## (b) Actual blocker list at HEAD (measured by running the CLI)

Command run (read-only, output captured to scratchpad):

```
python -m daedalus.gates report --gate 0 --repo-root . \
  --source-revision 60b2bfeb83d3886e4c1e8547e2481a8972e729a3
```

Result: `schema=daedalus-gate-report/2`, `closed=false`, **60 blockers** (confirms the
self-reported figure), `owner_approval_enforced=true`, `unguarded_entrypoints=[]`,
`missing_guard_contracts=[]`, `primary_checkout_mutations=[]`,
`registry_sha256=b8cab096e4bf...`, `report_sha256=ed510ec82193...`,
`event_store_writer_inventory_sha256=6c76bbf6c779...`.

Blocker composition (60 = 40 + 15 + 2 + 3):

| Bucket | Count | Rows |
|---|---:|---|
| `inventory_only_production_entrypoints` | 40 | `adapter.subprocess{,.interrupt,.send,.terminate}`; `cli.{arch_memory,bookkeeper,claude_bridge,dctx,doctor,enforce,eval_ceiling,eval_correctness,eval_graph_delta,file_bridge,gui_lint,mapping_drift,mapping_inventory,mapping_render,memory,runbook,selftest,shift,status,structcore,structcore_slice,token_monitor,web_api}` (23); `file_bridge.{enqueue,process,watch}`; `provider.{claude,codex,deepseek,deepseek.rollback,ollama.rollback,ollama_native}`; `python.command_gate`; `web.mutations`, `web.mutations_put`; `worktree.reap` |
| `unregistered_effectful_entrypoints` | 15 | `tools.{agent_findings,audit_swarm,audit_triage,bootstrap_receipt,funnel,funnel_report,gate_discrimination,gate_host_preflight,gui_check,iron_plan_guard,iron_plan_hook_runner,lane_invariants,mutation_score,operability_drill,run_gate_checks}:main` |
| `event_store_writer_failures` | 2 | `daedalus/spine/attempt.py:1661:16` and `:1662:54` — `legacy_direct:daedalus.spine.ledger.SpineLedger` |
| status sentinels | 3 | `fault_injection_failures:fault-matrix:not-yet-bound`; `runtime_conformance_failures:runtime-conformance-receipts:not-yet-bound`; `security_boundary_claimed:false` |

Non-blocking diagnostics in the same report: **52 × `gap:gate0.not_central:<id>`**,
`review:entrypoint.not_rediscovered:daedalus.claude_bridge:main`,
`review:scan.static_scope:python-ast`.

### New measured defect: the v3 report cannot be built at HEAD

`build_gate0_report_v3(Path("."), source_revision=HEAD)` raises
`ValueError: callsites must be unique` from
`daedalus/gates/repository_write_inventory.py:221`, reached via
`repository_write_inventory_v2.py:229` and `report_v3.py:340`. The duplicate rows are seven
`path_mutation:<expression>.replace:replace` callsites each emitted twice:

```
daedalus/budget.py:1013:24        daedalus/context_plan.py:78:15
daedalus/conversation.py:163:12   daedalus/mapping/render.py:698:7
daedalus/spine/ledger.py:147:12   daedalus/spine/ledger.py:606:23
daedalus/wiki/vault.py:241:11
```

(duplicated identically — a scanner double-visit of `.replace` expressions, not dirty-worktree
noise: none of the affected files is modified in the worktree).
`scripts/report_gate0_v3.py` catches this and exits 2 with an error JSON
(`daedalus-gate-report-v3-error/1`) — designed fail-closed, but it means **repository-write
inventory evidence is currently unobtainable on the trunk** and the
`g0-gate-report-repository-write-v3.yml` workflow cannot go green.

---

## (c) Reconciliation with the verified findings

1. **"52/53 entrypoints not CENTRAL" — CONFIRMED.** Measured from `REGISTRY_BY_ID`:
   53 rows; wiring counts `INVENTORY_ONLY=40, LOCAL_GUARDS=11, CENTRAL=1, ABSENT=1`.
   The single CENTRAL row is `python.offload`. The 52 non-central rows surface only as
   `gap`-severity diagnostics, **not** blockers. Consequence: the report's `closed` predicate
   can reach `true` while 11 LOCAL_GUARDS rows and 1 ABSENT row never migrate to CENTRAL —
   weaker than Gesamtplan Schritt 15 ("alle Registry-Zeilen schrittweise auf `CENTRAL`
   migrieren") and the master plan's Gate-0 deliverable ("centralized start/guard path for
   every effectful runtime entrypoint"). This divergence must be resolved explicitly
   (either blocker-ize non-CENTRAL rows or amend the plan to accept LOCAL_GUARDS at exit).
2. **"Discovery finds 66 vs 53-row registry" — CONFIRMED and fully explained.**
   `discover_entrypoints(".")` returns 66 entries. 51 map onto registry targets;
   15 discovered-but-unregistered are exactly the `tools.*:main` blocker rows;
   2 registry rows are not discovered: `mcp.runtime` (declared target `<absent>`, by design)
   and `daedalus.claude_bridge:main` (surfaced as `review:entrypoint.not_rediscovered` —
   a stale registry row or a discovery blind spot). Arithmetic closes: 66 = 53 − 2 + 15.
   **No hidden unregistered path exists beyond the 15 already reported.**
3. **"Effect.SECRETS claimed by zero rows" — CONFIRMED.** The `Effect` enum defines `SECRETS`;
   zero of 53 rows claim it, while provider rows (claude/codex/deepseek/ollama) demonstrably
   handle API credentials. The gate report is **silent** about this (no blocker, no diagnostic),
   so `closed=true` would assert "no production gap in the registry" (Gate-0 list item 9,
   GESAMTPLAN:287) over a registry that models zero secret effects — contradicting master-plan
   invariant 8 (secrets enforced at effect boundaries). True blocker, currently invisible to
   the tool.
4. **"mcp.runtime ABSENT" — CONFIRMED, and it is NOT a true blocker.** The row exists with
   `wiring=ABSENT`, target `<absent>`, effects `PROCESS_SPAWN, NETWORK_EGRESS,
   FILESYSTEM_WRITE`, guard `runtime.adapter_profile`. Gesamtplan Schritt 16 explicitly
   permits exactly this state ("MCP entweder als `ABSENT` mit klarem Nicht-Support belassen
   oder als vollständig geleasten Adapter implementieren"). Two footnotes: (i) it still counts
   toward the 52 not-central gap diagnostics — noise worth suppressing for ABSENT rows;
   (ii) master-plan Gate 0 demands "policy coverage tests for … MCP/File Bridge" — coverage
   proving the ABSENT stance (no MCP effect path exists) should be cited in exit evidence.
   ASSUMED (not exhaustively verified): no daedalus production code invokes an MCP client today.

---

## (d) Prioritized true-blocker list for Gate-0 exit

Step numbers refer to the Gesamtplan's "Geordnete Claude-Ausführung" (Schritte 6-22) and, in
parentheses, the 9-item Gate-0 closure list (GESAMTPLAN:277-287).

| # | True blocker | Evidence | Gesamtplan step |
|---|---|---|---|
| P0-1 | **No sandbox → `security_boundary_claimed:false`** hard-blocks `closed` | report row; `build_gate0_report(..., security_boundary_claimed=False)` default, report.py:433 | Schritt 20 (item 8) |
| P0-2 | **Fault-injection matrix not bound** (`fault-matrix:not-yet-bound` sentinel — no real fault results ever passed) | report.py:470-471 | Schritt 21 (item 8) |
| P0-3 | **Runtime conformance receipts not bound** (`not-yet-bound` sentinel; no manifests/receipts wired) | report.py:468-469 | Schritte 17-19 (item 7) |
| P0-4 | **40 INVENTORY_ONLY production entrypoints** (adapters, 23 CLIs, file-bridge, 6 providers, web mutations, worktree.reap, command_gate) — largest bucket | report blocker list; registry wiring counts | Schritte 13, 15 (item 6) |
| P0-5 | **15 unregistered effectful `tools.*` mains** — incl. `iron_plan_guard` and `run_gate_checks` themselves | report blocker list; discovery reconciliation | Schritte 6, 15 (item 9) |
| P0-6 | **2 legacy direct Event-Store writes** at `daedalus/spine/attempt.py:1661-1662` (`SpineLedger` bypassing the canonical writer path) | `event_store_writer_failures` rows | Schritte 11, 13 (items 3, 6) |
| P0-7 | **Repository-write scanner broken at HEAD** — duplicate `.replace` callsites crash `build_gate0_report_v3`; v3 lane red, repository-write evidence unobtainable | reproduced crash, 7 duplicated sites listed in (b) | Schritt 6 (item 1) — the machine-readable report itself |
| P0-8 | **SECRETS effect unmodeled** — 0/53 rows claim it; gate report cannot see the gap | registry measurement | Schritt 15 (item 9); master-plan invariant 8 |
| P1-9 | **11 LOCAL_GUARDS rows never reach CENTRAL yet don't block closure** — report predicate weaker than plan text; resolve by blocker-izing or by amendment | 52 `gap:gate0.not_central` diagnostics vs closed-predicate report.py:203-209 | Schritt 15 (item 6) |
| P1-10 | **Stale registry row `daedalus.claude_bridge:main` not rediscovered** — registry/discovery bijection broken by one row | `review:entrypoint.not_rediscovered` diagnostic | Schritte 6, 15 |
| P1-11 | **Adoption baseline + monotonic CI missing**: no `configs/gates/gate0-adoption-baseline.json` anywhere in the worktree; CI calls `assert_gate_report.py` with **no** `--baseline/--require-monotonic/--require-closed` (workflow :91), so monotonicity is unenforced | `ls configs/gates` (only the fault-matrix json); `g0-gate-report-writer-inventory.yml:91`; the tool itself supports all three flags | Schritte 7-8 |
| P1-12 | **Plan/implementation doc drift**: schema-ID `/1` collision, `--format/--output` CLI mismatch, stale exit assertion — must be reconciled inside the plan/revision-2 amendment, not silently | section (a) items 1-3 | Schritt A 3-5, Schritt 9 |

**Explicit non-blockers** (to prevent wasted work): `mcp.runtime` ABSENT (Schritt 16 satisfied);
`owner_approval_enforced=true` already (promotion guard `promotion.owner_approval` implemented
and bound — Schritte 10/14 at report level); `unguarded_entrypoints=[]` and
`missing_guard_contracts=[]` (the historical UNGUARDED rows are gone; `python.offload` is the
one CENTRAL row); `primary_checkout_mutations=[]`.

### Suggested closure order

P0-7 first (the measurement instrument must work before anything it measures is trusted),
then P0-5/P0-6 (cheap registry+writer closures), then P0-4 in surface-sized batches
(providers → worktree → file-bridge/web → CLIs), P0-8 alongside the provider batch,
then P0-3, then P0-1/P0-2 as the final Linux-Docker deliverable, with P1-9/P1-11/P1-12
folded into the plan/revision-2 amendment and the release PR.

---

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: live CLI run at 60b2bfe (60 blockers, schema /2, digests recorded above);
registry introspection (53 rows, wiring counts, SECRETS=0, mcp.runtime=ABSENT);
discovery run (66 entries, 66 = 53 − 2 + 15); reproduced v3 crash with duplicate-callsite list;
file:line citations for every schema/CLI claim. Read-only throughout; only this report written.

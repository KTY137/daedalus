# Fable lane: legacy-matrix — Gesamtplan Legacy-Entscheidungsmatrix vs. Gate-0-Trunk

Date: 2026-08-17
Lane: legacy-matrix (1 of 5 Fable analysis lanes)
Audited trunk: `C:/Users/nukei/Desktop/agent_env_g0`, branch `work/g0-trunk-20260817` at
`60b2bfeb83d3886e4c1e8547e2481a8972e729a3` (verified: `git log --oneline -1` = `60b2bfe merge(probe): #56 g0/claude-provider-broker`).
Matrix source: `docs/DAEDALUS_GESAMTPLAN.md` lines 1335–1364 (read in full, both pages).
Mode: READ-ONLY on both checkouts; only this file was written.

## Method and one tooling block

- Serena MCP could **not** be used on the trunk: `get_symbols_overview` on
  `../agent_env_g0/daedalus/spine/effect_boundary.py` failed with
  `ValueError: Path ... is outside of configured workspaces. Configured workspaces: ['C:\\Users\\nukei\\Desktop\\agent_env']`.
  Fallback: an ast-based symbol-overview script (scratchpad `ast_overview.py`) giving the same
  per-module class/function/line view without reading whole files. This is a reported deviation,
  not a guess-substitute.
- The decisive measurement is the trunk's own machine-readable Gate-0 report, run read-only:
  `python -m daedalus.gates report --gate 0 --source-revision 60b2bfe…` (stdout only, no `--output`).
  Full JSON retained in the session scratchpad (`gate0.json`); key numbers quoted below.

## Measured Gate-0 report (trunk, schema `daedalus-gate-report/2`)

```
closed: False                       security_boundary_claimed: False
blockers: n=60                      owner_approval_enforced: True
unguarded_entrypoints: n=0          primary_checkout_mutations: n=0
inventory_only_production_entrypoints: n=40
unregistered_effectful_entrypoints: n=15   (all tools/*.py scripts)
event_store_writer_failures: n=2   (daedalus/spine/attempt.py:1661 and :1662, legacy_direct SpineLedger)
fault_injection_failures: n=1      (fault-matrix:not-yet-bound)
runtime_conformance_failures: n=1  (runtime-conformance-receipts:not-yet-bound)
registry_sha256: b8cab096e4bf…     report_sha256: ed510ec82193…
```

Category items sum to 59 of the 60 listed blockers; the full list is in the retained JSON.
Headline: **no UNGUARDED entrypoint remains** — the Gesamtplan's Gate-0 premise ("`python.offload`
und `python.promote_candidates` werden als UNGUARDED geführt") is already stale on this trunk.
The blocker mass is now inventory migration (40), unregistered tools (15), and the two
not-yet-bound suites (fault matrix, runtime conformance).

Registry wiring on the trunk (`daedalus/spine/effect_boundary.py`, `ENTRYPOINTS` L164–516 +
`_LEGACY_ENTRYPOINT_ROWS` L517–700): 1× CENTRAL (`python.offload`), 11× LOCAL_GUARDS
(`cli.daedalus`, `web.server`, `python.attempt`, `kernel.attempt.begin/complete/prepare`,
`python.promote_candidates`, `provider.ollama`, `worktree.create/commit/cleanup`),
8+32=40× INVENTORY_ONLY, 1× ABSENT (`mcp.runtime` — exactly the Schritt-C-16 "ABSENT" option),
0× UNGUARDED.

---

## The 15 rows

### 1. `daedalus.schemas` — „erweitern, nicht duplizieren"
**State:** `daedalus/schemas.py` (1872 lines) is the canonical contract family:
`CanonicalContract` L217, `MissionContract` L520, `AttemptContract` L579, `EvidencePacket` L769,
`CampaignContract` L1011, `PolicyDecision` L1125, `RuntimeManifest` L1184, `AttemptReceipt` L1318,
`NominationReceipt` L1451, `PromotionReceipt` L1524, `RuntimeConformanceReceipt` L1675.
`daedalus/twin/contracts.py` **extends** it (`from ..schemas import …` L20):
`PlaneSnapshot` L58, `CrossPlaneBinding` L154, `FourfoldSnapshot(CanonicalContract)` L248.
No parallel Pydantic/contract family found.
**Verdict: DONE** (the prescribed pattern is being followed).
**Remains:** the Gesamtplan's later contracts — `GraphProposal`, `CampaignReceipt`, `ProductSpec`,
`TargetFourfoldSpec` — exist nowhere in `daedalus/` (repo-wide grep: zero hits). Correct for
Gate 0; they are Gate-2/3 deliverables and must land as further `schemas.py`-family extensions.

### 2. `daedalus.structcore` — „behalten; Extractor- und Forest-Basis"
**State:** package intact in trunk, 23 modules incl. `forest.py`, `typegraph.py`, `index.py`,
`imports.py`, `lpg.py`; consumed live by `web_api.py` L34–38 (`structcore.index/churn/report/slice/topology`);
`tests/test_typegraph_forest.py`, `tests/test_forest.py` present.
**Verdict: DONE.** **Remains:** nothing for this row at Gate 0; Tree-sitter/SCIP layering is Gate 2 (Schritt F 32–34).

### 3. `daedalus.structcore.forest` — „über Adapter in `FourfoldSnapshot` einbetten"
**State:** `structcore/forest.py` `KnowledgeForest` L143 (deterministic, `content_sha256`);
adapter exists: `daedalus/twin/legacy_forest.py` — docstring "Conservative adapter from the
existing KnowledgeForest to FourfoldSnapshot", `fourfold_from_knowledge_forest` L50; exported in
`twin/__init__.py:16`; tests `tests/twin/test_fourfold_contracts.py`, `test_legacy_assurance.py`.
This is Schritt E-24 („FourfoldSnapshot zunächst als Adapter um den aktuellen Forest") already built.
**Verdict: DONE (adapter), PARTIAL (wiring).**
**Remains:** no production caller beyond the package export — the Gate-1 ignition slice will be
the first real consumer; nothing further needed inside Gate 0.

### 4. `daedalus.storage` — „als CAS-Basis behalten und härten"
**State:** `storage.py` (653 lines) `ArtifactStore` L392 with `_assert_confined`, `_verify_file`,
`_publish_immutable`, `put_bytes/get_bytes/verify`; typed corruption errors L67–75; free-space
guard `check_storage` L174. `kernel/artifacts.py` shared content-addressed identities
(`ArtifactRef` L26, `digest_file_tree` L78). Gate-side hardening evidence:
`gates/repository_write_artifact_cas.py`, `…_verifier.py`; tests `test_artifact_store.py`, `test_artifacts.py`.
**Verdict: DONE.** **Remains:** nothing blocking found at this seam.

### 5. `daedalus.spine.attempt` — „kanonischer Attempt-Pfad"
**State:** `spine/attempt.py` (1669 lines) `TaskAttempt` L1072 (isolated worktree, gates,
persist-to-store, ledger), `offload_runner` L1041, `run_attempt` L1666; containment tests
`test_spine_attempt.py`, `test_spine_attempt_containment.py`. Registry: `python.attempt` and
`kernel.attempt.begin/complete/prepare` = LOCAL_GUARDS. It IS the path other rows are routed onto
(offload refuses writes outside it, see row 9).
**Verdict: LARGELY DONE — and it hosts 2 of the 60 blockers.**
**Remains:** the only two `event_store_writer_failures` in the whole gate report are here —
`attempt.py:1661` and `:1662` (`_get_ledger` constructing `SpineLedger` directly,
classified `legacy_direct`); plus raising the four attempt rows from LOCAL_GUARDS to CENTRAL.

### 6. `daedalus.spine.effect_boundary` — „zur echten Lease erweitern"
**State:** the lease itself is built and real: `kernel/effects.py` (969 lines,
"Persisted, scope-bounded Effect Leases for the Gate-0 trust kernel") — `issue_effect_lease` L337,
`verify_effect_lease` L443, sqlite `EffectLeaseLedger` L525 (grant/revoke/begin/finish),
`LeasedEffectAuthorization.begin_effect` L898, TTL cap L44, signature/replay/scope error taxonomy
L48–76. Proven end-to-end on `python.offload` (row CENTRAL; `offload.py` L777 `begin_effect`,
L797–810 `finish_effect`, entrypoint-binding check L754). `effect_boundary.py` remains the
registry + conformance scanner (`check_conformance` L1389, `discover_entrypoints` L1185).
**Verdict: DONE (mechanism), PARTIAL (coverage).**
**Remains:** migrate 40 INVENTORY_ONLY rows and 11 LOCAL_GUARDS rows onto the lease path
(Schritt C-15 „alle Registry-Zeilen schrittweise auf CENTRAL"), and register/classify the
15 unregistered `tools.*` entrypoints. This is 55 of the 60 blockers.

### 7. `daedalus.loop` — „als Orchestration-Consumer migrieren"
**State:** `loop.py` (1304 lines) already drives the canonical spine — imports
`spine.attempt` (L86), `spine.envelope` (L87), `spine.killswitch` (L97), uses `spine.picker`.
But `LoopLedger` L206 persists its own JSON run state under `runs/loop/` (L740).
**Verdict: PARTIAL.**
**Remains:** either fold `LoopLedger` state into the spine ledger/event projections or declare it
explicitly a regenerable projection; no registry blocker names `loop` directly (it runs through
attempt), so this is consolidation, not gate-arithmetic.

### 8. `daedalus.kairos.evolution` — „zunächst Legacy-Adapter, später durch `evolution/` ersetzen"
**State:** `kairos/evolution.py` is 178 lines (`EvolutionaryOrchestrator`: generate/evaluate/select);
**zero callers repo-wide** (grep for `EvolutionaryOrchestrator|kairos.evolution` outside the file: empty).
`daedalus/evolution/` does not exist (trunk package listing).
**Verdict: DONE for the „zunächst" phase** — frozen, dead, isolated; nothing routes through it.
**Remains:** build `evolution/` at Gate 3+, then delete under the matrix's six deletion conditions
(replacement, golden match, callers migrated, no effect entrypoint, replay, rollback).

### 9. `daedalus.offload` — „direkte Writes entfernen, auf Attempts routen"
**State:** both halves measured as done. `offload.py` L450–466: a live write outside the granted
TaskAttempt worktree returns `action="isolated_attempt_required"` and instructs
"use daedalus.spine.attempt.offload_runner()"; L724–810: a `LeasedEffectAuthorization` bound to
entrypoint `python.offload` is mandatory (`begin_effect` L777, `finish_effect` on all exits).
Registry wiring: the **only CENTRAL row**. Tests: `test_offload_write_failclose.py`,
`test_fake_offload.py`, `test_offload_automint.py`, `test_offload_slice_context.py`.
**Verdict: DONE.**
**Remains:** nothing structural; the `_auto_mint` env toggle (L159–163) deserves an audit-lane
glance but is outside this row's prescription.

### 10. `daedalus.kairos.gated_writes` — „ausschließlich mit OwnerApproval"
**State:** rewritten as a "Compatibility strangler for the sealed Kairos promotion seam".
`promote_candidates` L144 now **requires** `consumed_approval`, `evidence_packet`, `target_ref`,
`approval_ledger`, `owner_keyring`; refuses before any effect
(L125–141: "persisted ApprovalLedger and owner keyring are mandatory before any promotion effect");
candidate material snapshotted before authentication (docstring L177–180); retained legacy source
pinned by git-blob SHA (L16–17, `_gated_writes_legacy.py.src`). Backing kernel:
`kernel/approvals.py` (one-use signed `VerifiedOwnerApproval`/`ConsumedOwnerApproval`,
`ApprovalLedger.consume` L425+), `kernel/promotion.py` (`authorize_promotion` L292 binding
candidate batch sha + live target revision). Gate report: `owner_approval_enforced: True`.
Test: `test_promotion_forgery.py`.
**Verdict: DONE at the seam.**
**Remains:** row `python.promote_candidates` is LOCAL_GUARDS, not CENTRAL; docstring records the
intentionally frozen single-candidate limitation until promotion consumes one combined CAS tree.

### 11. File Bridge — „Event-/Mission-Adapter, kein eigener Workflowstatus"
**State: NOT satisfied — the clearest open row.** `file_bridge.py` (1027 lines) still owns a full
parallel workflow state: outbox/inbox/archive L21–23, journal `_journal_dir` L160, quarantine
L166/`quarantine_request` L456, heartbeat `write_heartbeat` L664, own report/read-marks. Zero
effect-boundary usage (grep `begin_effect|effect_boundary|lease` in the file: empty). Four
registry rows are INVENTORY_ONLY (`file_bridge.enqueue/process/watch`, `cli.file_bridge`).
**Verdict: ABSENT (prescribed shape does not exist yet).**
**Remains:** the entire adaptation — enqueue→MissionContract/AttemptContract, journal/heartbeat →
spine-ledger events or a declared projection, all four rows through the lease entry.

### 12. Council/Coffee/Agent Network — „einfrieren; nur als stateless Recipes"
**State:** mixed. "Coffee": zero hits in `daedalus/` — gone. Council: **not frozen** — recent
trunk commits touch it (`1a0c391 feat(council): the publish path was 763 lines no runnable command
could reach`, `346391a fix(safety) …`, `c94557a fix(council): two commands spent real money…`);
`council/publish.py` spawns subprocesses (L64, L133, L143) and no `council` row exists in the
effect registry (grep: none) — the gate report does not flag it, so the discovery heuristics do
not currently see this surface. Agent network remnant `agents_registry.py` exists (not audited deeper).
**Verdict: PARTIAL, with one measured gap** (effectful publish path outside the registry).
**Remains:** either register `council.publish` as an entrypoint row or structurally freeze it;
document council/room as stateless recipes.

### 13. Memory-Systeme — „Produkt-/Research-Memory trennen; keine Workflowautorität"
**State:** three stores, all discipline-marked: `memstore.py` (616 lines, append-only hash-chained
"memory that cannot silently lie"), `memory/embeddings.py` (1688 lines, "Versioned, **derived**
embedding projections for Daedalus events"), `memory/projection_worker.py` (journal → vector
index projection), `arch_memory.py` (repo-architecture digest). No workflow authority found:
`spine/envelope.py` references to memstore are docstring inventory only (L7, L135, L675);
`conversation.py` L28 deliberately re-implements the two-SHA discipline rather than importing state.
**Verdict: PARTIAL.**
**Remains:** the product-vs-research split exists nowhere as two *named* stores — research
adaptive memory simply does not exist yet (defensible before Gate 3, but the split must be named
the day it appears, per constitution §7 and Gesamtplan row).

### 14. Web UI — „Projektion aus canonical events und receipts"
**State:** `web_api.py` (1865 lines) is a mixed projection: canonical reads exist
(`SpineLedger` import L345, `spine.picker` L262/344/413) alongside legacy reads
(`file_bridge.stream_state` L31, `kairos.drafts` L16, direct structcore L34–38). Write path
`web.mutations` (`DaedalusHandler.do_POST`) is INVENTORY_ONLY; `web.server` LOCAL_GUARDS
(loopback-bind refusal `NonLoopbackBindRefused` L1719, auth-token env L1733).
**Verdict: PARTIAL.**
**Remains:** route `do_POST`/`do_PUT` mutations through the lease boundary; retarget the
file_bridge-backed panels once row 11 is adapted. Read-only projection direction is right.

### 15. MLflow/Kùzu/LangGraph — „regenerierbare Backends, keine Source of Truth"
**State:** trivially satisfied by absence. Repo-wide grep: **zero** `mlflow`/`kuzu` imports;
LangGraph confined to `langgraph_adapter.py` — a 27-line optional stub (`langgraph_available` L6,
`build_graph` L14). No projection can be an authority because none exists.
**Verdict: DONE (vacuously).**
**Remains:** when Gate 2/3 introduces them, enforce the prescribed interfaces
(`GraphProjectionStore`, receipt-only MLflow, LangGraph as executor only) from day one.

---

## Scoreboard

| # | Row | Verdict |
|---|---|---|
| 1 | schemas | DONE (later-gate contracts absent, correctly) |
| 2 | structcore | DONE |
| 3 | structcore.forest | DONE adapter / PARTIAL wiring |
| 4 | storage | DONE |
| 5 | spine.attempt | LARGELY DONE — hosts the 2 event-store blockers |
| 6 | spine.effect_boundary | DONE mechanism / PARTIAL coverage (55/60 blockers) |
| 7 | loop | PARTIAL (own runs/loop state) |
| 8 | kairos.evolution | DONE for "zunächst" (frozen, 0 callers) |
| 9 | offload | DONE |
| 10 | kairos.gated_writes | DONE at seam |
| 11 | File Bridge | ABSENT — not begun |
| 12 | Council/Coffee/Agent Network | PARTIAL (unregistered effect surface) |
| 13 | Memory-Systeme | PARTIAL (no named product/research split) |
| 14 | Web UI | PARTIAL (mixed projection, unguarded POST) |
| 15 | MLflow/Kùzu/LangGraph | DONE (by absence) |

Notable drift the other direction: the Gesamtplan's Gate-0 premise (offload/promote UNGUARDED,
approval guard unimplemented) is **stale** — the trunk has `unguarded: n=0` and
`owner_approval_enforced: true`. Schritt C items 10–14 are substantially done; items 15–21
(registry migration, runtime manifests/conformance receipts, sandbox fault matrix) are the open mass.

## The three rows where acting NOW unblocks the most

1. **Row 6 — effect_boundary coverage migration.** 55 of the 60 measured blockers (40
   INVENTORY_ONLY + 15 unregistered `tools.*`) are precisely "rows not yet at the boundary".
   The dependency argument: the lease mechanism is finished, persisted, and proven on
   `python.offload` — every other row's migration is now mechanical repetition of a pattern that
   exists, and rows 11 and 14 *cannot* comply until this entry is where they land. Nothing else
   reduces the blocker set at comparable rate per change.

2. **Row 5 — spine.attempt.** Everything effectful is being funneled here by design (offload
   already refuses non-attempt writes and names `offload_runner` as the door), so any defect at
   this seam is inherited by every migrated row. The only two `event_store_writer_failures` in
   the entire report live at `attempt.py:1661–1662`; fixing that write path and raising the four
   attempt rows to CENTRAL clears a whole blocker class and is a hard precondition for Gate 1
   restart/replay — the next product proof after Gate 0.

3. **Row 11 — File Bridge.** Dependency, not size: it is the last *production* subsystem holding
   a parallel workflow state store (journal/quarantine/heartbeat), i.e. a live tension with
   invariant 1 ("one kernel") — and row 14 (Web UI) reads `file_bridge.stream_state` directly, so
   the Web UI cannot become a pure canonical projection until this row moves. Adapting it removes
   four registry blockers and unblocks a second matrix row downstream in the same stroke.

---

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: read-only audit; `python -m daedalus.gates report --gate 0 --source-revision 60b2bfe…`
on the trunk (report_sha256 ed510ec8…, closed=false, 60 blockers); ast symbol overviews +
line-anchored greps per module as cited above; Serena blocked outside its configured workspace
(reported); no file outside this report was created or modified.

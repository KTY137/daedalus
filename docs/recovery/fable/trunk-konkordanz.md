# Lane: trunk-konkordanz — Gesamtplan Gate-0/Schritt-B/C/D gegen den konsolidierten Trunk

**UEBERHOLT 2026-08-26.** Gemessen gegen `work/g0-trunk-20260817`
(`closed=false`, 60 Blocker). Gate 0 ist seither (gescoped) geschlossen,
Masterplan Revision 8 — siehe `docs/GATE0_CLOSURE_DECISION_20260826.md`. Der
Text bleibt unveraendert als datierte Evidenz stehen.

Datum: 2026-08-17 · Lane: Fable trunk-konkordanz · Klassifikation: ALIGNED (read-only Analyse, Gate 0)

Gemessener Stand: Worktree `C:/Users/nukei/Desktop/agent_env_g0`, Branch `work/g0-trunk-20260817`,
HEAD `60b2bfeb83d3886e4c1e8547e2481a8972e729a3` ("merge(probe): #56 g0/claude-provider-broker").
Zentrale Messung: `python -m daedalus.gates report --gate 0 --source-revision 60b2bfe…` live ausgeführt →
`schema=daedalus-gate-report/2`, `closed=false`, `security_boundary_claimed=false`,
`owner_approval_enforced=true`, `registry_sha256=b8cab096…`, **60 Blocker**
(2× event_store_writer_failures in `daedalus/spine/attempt.py:1661/1662` legacy_direct SpineLedger;
`fault_injection_failures:fault-matrix:not-yet-bound`;
`runtime_conformance_failures:runtime-conformance-receipts:not-yet-bound`;
44× inventory_only_production_entrypoints; 15× unregistered `tools.*:main`).

Methode: direkte Datei-Reads/Greps auf dem Worktree plus eine Live-Report-Ausführung. Serena wurde
bewusst nicht benutzt (Projekt-Root zeigt auf den stale Main-Checkout, nicht auf den Worktree —
Symbolantworten wären irreführend gewesen). Kein Guard-Block trat auf.

---

## A. Gate-0-Liste des Gesamtplans (Abschnitt "Gate 0", Punkte 1–9)

| # | Punkt | Verdikt | Evidenz |
|---|---|---|---|
| 1 | Maschinenlesbarer Gate-Report | **done** (voraus) | `daedalus/gates/report.py:23` `_SCHEMA="daedalus-gate-report/2"` (Legacy `/1` akzeptiert, :24); `gates/report_v3.py:28` `"daedalus-gate-report/3"`; CLI `gates/__main__.py:10-22`; JSON-Schemata `configs/schemas/gate-report-v2.schema.json`, `gate-report-v3.schema.json`. Abweichung: CLI verlangt `--source-revision`, kennt kein `--format/--output` (stdout-JSON) — anders als das Gesamtplan-Beispiel `python -m daedalus.gates report --gate 0 --format json --output gate0.json`. |
| 2 | `OwnerApproval` kanonisch, kandidaten-/evidenzgebunden | **done** | `daedalus/kernel/approvals.py`: `issue_owner_approval`:298, `verify_owner_approval`:345, `VerifiedOwnerApproval`:101, `ConsumedOwnerApproval`:177, `ApprovalLedger` (SQLite, one-use, Replay-Schutz) :425/:498/:628, CLI `main`:783. `ApprovalExpectation`:60 bindet Candidate/Evidence/Base/Target. Live-Report: `owner_approval_enforced=true`. |
| 3 | `begin_effect` als echte, persistierte Lease | **done** | Zwei Schichten: reine fail-closed Validierung `spine/effect_boundary.py:723-831` (nur CENTRAL-Zeilen, :746-749) + persistierte Lease `kernel/effects.py`: `issue_effect_lease`:337, `verify_effect_lease`:443, `EffectLeaseLedger` (SQLite) :525, TTL max 24 h :44/:393, Scope-Pflichten (writable_paths/egress/tools/secrets/max_cost/kill_switch/timeout) :254-276, Kill-Switch-Generationsprüfung :311/:468-469, Concurrency-Kappe :761, Idempotenz-/Replay-Sperre :751, `LeasedEffectAuthorization`:898. |
| 4 | `offload` schreibt nur in isolierten Attempts | **done** | `daedalus/offload.py:712-808`: live nur mit persistierter, an `python.offload` gebundener Lease (:743-760), vollständiges deklariertes Effekt-Set (:763-775), Replay-Verweigerung (:777-785), Terminal-Receipts bei FAILED/CANCELLED (:793-808). Write-Mode nur im gewährten TaskAttempt-Worktree (:450-465: "refusing live write outside TaskAttempt"). |
| 5 | `promote_candidates` an OwnerApproval-Digest + Ziel-HEAD | **done** (Lease-Zentralisierung offen) | `kairos/gated_writes.py:144` `promote_candidates`: ohne persistierten Ledger+Keyring fail-closed (:202-203), Kandidaten versiegelt (:214-219), `authorize_persisted_promotion` vor jedem Effekt (:231-243); zweite In-Lock-Reauthentifizierung gegen frisch gelesenen HEAD lt. Docstring :165-168 (**ASSUMED** — zweiten Aufruf hinter :259 nicht gelesen). `kernel/promotion.py`: Bindungs-Matrix candidate/evidence/base/target_ref/target_head :322-346; `authorize_persisted_promotion` verlangt authentifizierte persistierte Konsumtion :363-419. Registry-Zeile bleibt `LOCAL_GUARDS`, Migration "Route … through a persisted EffectLease" (`effect_boundary.py:363/:380-383`). |
| 6 | Alle Pfade (Web, Bridge, CLI, Adapter, Provider, Worktree, MCP) durch denselben Eintritt | **partial** | Gemessen: nur `python.offload` CENTRAL (`effect_boundary.py:338`). Live-Report: 44 inventory_only-Blocker (web.mutations :202, file_bridge.* :212/:226/:240, adapter.subprocess :391, provider.claude :405, provider.codex :420, provider.ollama_native :446, 24 Legacy-CLI-Zeilen :541-682) + 15 unregistrierte `tools.*`-Entrypoints + 2 legacy Event-Store-Writer (`spine/attempt.py:1661-1662`). MCP als ABSENT-Zeile :496-508. |
| 7 | Runtime Manifests + Conformance Receipts | **partial** | Verträge real: `schemas.py:1184` `RuntimeManifest`, `RUNTIME_CONFORMANCE_CHECKS` `schemas.py:29-40` (**8** Checks — dem Gesamtplan-Manifest fehlt gegenüber: `process-tree-kill`, das nur als Fault-Szenario existiert, `runtimes/fault_matrix.py:495`); `kernel/runtime_conformance.py`: `assemble_recorded_conformance`:59, `verify_current_conformance`:125 (Manifest-/Revisions-/Stale-Bindung); `runtimes/profiles.py`: `RuntimeProfile`:93, `materialize_runtime_manifest`:220, `RuntimeProbeIdentity`:263, `RuntimeConformanceEnvelope`:392, `verify_runtime_envelope`:517; `configs/runtimes/gate0-runtime-profiles-v1.json`. **Aber**: Live-Report-Blocker `runtime-conformance-receipts:not-yet-bound` — Receipts sind noch nicht in den Gate-Report eingebunden. |
| 8 | Docker-Sandbox + Fault-Injection-Matrix | **partial** | Sandbox gebaut: `kernel/sandbox.py` `DockerSandboxPolicy`:58 — digest-gepinntes Image :71-72, Netz none/Proxy-only :77-78, non-root :79-80, ro-Referenz-Mounts :83-85, Docker-Socket verboten :86-89, argv `--read-only --cap-drop ALL --no-new-privileges --pids-limit --memory/--memory-swap/--cpus --tmpfs noexec` :97-110; `run_in_docker_sandbox`:213 mit fail-closed Exit-125-Klassifikation :147-168; Tests `tests/kernel/test_docker_sandbox_*`. Fault-Katalog `gate0-runtime-faults-v1` mit **24 Szenarien** `runtimes/fault_matrix.py:476-506` + Executors/Fixtures (`tests/runtimes/*fault_executor*`, `tests/fixtures/*`), Host-Runner `runtimes/host_fault_runner.py`, Verifikation `gates/fault_matrix.py:815`. **Aber**: Blocker `fault-matrix:not-yet-bound`; Sandbox noch nicht Pflicht im Attempt-Pfad (Migrationsnoten `effect_boundary.py:269-272/:291-294/:317-320`). |
| 9 | Gate 0 erst ohne Produktionslücke schließen | **done als Mechanik, Gate offen** | Verfrühtes Schließen strukturell verweigert: `gates/release.py` `issue_gate0_release_receipt` verweigert `closed!=true`/Blocker/fehlende Claims :511-521; `closed` muss ableitbar sein :322-323. Ist-Zustand korrekt offen: `closed=false`, 60 Blocker (Messung oben). |

## B. Schritt B — Gate-Reporting (Punkte 6–9)

| # | Punkt | Verdikt | Evidenz |
|---|---|---|---|
| 6 | `daedalus.gates` + JSON-Report-Schema | **done** (voraus: v2+v3) | wie A.1; zusätzlich `build_gate0_report` `gates/report.py:426`, Writer-Inventory im v2-Report (`_V2_FIELDS` :61-67, `event_store_writer_inventory_sha256` live gefüllt). |
| 7 | Registry-Befunde als revisionsgebundene Adoption-Baseline exportieren | **partial** | Werkzeug fertig: `gates/baseline.py` (`daedalus-gate-baseline/2` :22, digest-gepinnt, Gate-0-only :60, `create_gate0_baseline` per Wheel-Smoke belegt), `gates/baseline_verifier.py`, CLI `scripts/gate0_baseline.py`. **Kein committetes Baseline-Artefakt gefunden**: `configs/gates/` enthält nur `g0-provider-target-receipt-retention-fault-matrix.json`; die im Gesamtplan geforderte `configs/gates/gate0-adoption-baseline.json` existiert nicht. |
| 8 | CI-Monotonieprüfung | **partial** | Mechanik: `assert_monotonic` `gates/report.py:540`; `GateMonotonicityReceipt`/`assess_gate0_monotonicity` `gates/baseline.py:165ff` (disjunkte Blocker-Partitionen :234). CI: `.github/workflows/g0-gate-baseline-v2.yml` existiert, triggert aber nur auf enge `g0/*`-Branches/Pfade (:4-25) — keine repo-weite Pflichtprüfung je PR auf die Integrationsbranch. Ob Branch-Protection sie verlangt, ist lokal nicht prüfbar (**ASSUMED unbekannt**). |
| 9 | Release- von Fortschrittsprüfung trennen | **done** | Getrennte Module und Workflows: Release fail-closed + signiert `gates/release.py:526/:606` (verlangt `closed:true`), Fortschritt über Baseline/Monotonie (`gates/baseline.py`), Workflows `g0-release-assessment.yml` vs. `g0-gate-baseline-v2.yml`. |

## C. Schritt C — Trust Kernel schließen (Punkte 10–16)

| # | Punkt | Verdikt | Evidenz |
|---|---|---|---|
| 10 | OwnerApproval + PromotionReceipt an Candidate/Evidence/Base-HEAD/Target-HEAD binden | **done** (voraus) | Bindungsmatrix `kernel/promotion.py:322-346` (candidate_approval, candidate_packet, evidence_approval, source_revision=base, target_ref, target_head=live, evaluation_status, candidate_locator, candidate_base_revision); zusätzlich vom Plan gar nicht verlangt: `kernel/promotion_execution.py` `PromotionExecutionStart`:195, `PromotionExecutionReceipt`:281, `PromotionExecutionLedger`:575 + Reader; CI `g0-persisted-promotion-authorization.yml`, `g0-promotion-execution-event-spine.yml`, `g0-live-promotion-seam.yml`. |
| 11 | `begin_effect` → persistierte Lease mit TTL, Scope, Budget, Kill-Switch | **done** | wie A.3 (`kernel/effects.py`; Budget = `max_cost_microusd` Pflicht bei SPEND :270, Narrowing je Ausführung :284-312). |
| 12 | `offload` über AttemptContract + isolierten Worktree | **done** | wie A.4; Attempt-Seite: `kernel/attempt_workspace.py` `IsolatedAttemptCoordinator.prepare` (Registry-Anker `effect_boundary.py:296-321`: checkout-externe Workspace nach Topologie-Preflight + durablem Attempt-Start), `kernel/attempt_contracts.py`, `kernel/attempt_ledger.py` (:252-295). |
| 13 | Direkte Primary-Checkout-Writes aus Providern/Legacy-Orchestratoren verweigern | **partial** | Offload-Write nur im TaskAttempt (:450-465); Promotion versiegelt (C.14); Ollama mit lokalen resolved-path Write-Checks (`effect_boundary.py:436-438`); Report-Feld `primary_checkout_mutations` (leer im Live-Report) + `repository_write_*`-Gate-Familie (18 Module in `daedalus/gates/`) + `primary_tree.py`. **Offen**: provider.claude/codex Write-Modi INVENTORY_ONLY "unleased path" (:405/:428), provider.deepseek(.rollback) nur inventarisiert (:637-649) — deckt sich mit dem offenen CRITICAL "routed-codex/deepseek write w/o rollback" aus der Validierung. |
| 14 | `promote_candidates` ohne gültige OwnerApproval strukturell unmöglich | **done** | `kairos/gated_writes.py`: Modul versiegelt den Namen (`del promote_candidates` :54, kontrollierte Re-Exports :86-94); public Callable verweigert ohne persistierte Autorität vor jedem Prozess/Lock/Worktree (:199-203), genau ein Kandidat (:207-213), `authorize_persisted_promotion` (:231-243). Legacy-Quelle nur noch als `.py.src` (`_gated_writes_legacy.py.src`), nicht importierbar. |
| 15 | Alle Registry-Zeilen auf CENTRAL migrieren | **partial (früh)** | Gemessen: 1× CENTRAL (python.offload), ~12× LOCAL_GUARDS, 44× INVENTORY_ONLY, 1× ABSENT; 15 unregistrierte `tools.*` zusätzlich. Der Live-Report zählt jede Zeile einzeln als Blocker — die Migrationsschuld ist vollständig maschinenlesbar. |
| 16 | MCP: ABSENT mit klarem Nicht-Support ODER voll geleaster Adapter | **done (Variante ABSENT)** | `effect_boundary.py:496-508`: `mcp.runtime`, `wiring=ABSENT`, `target="<absent>"`, Note "inventories/vets MCP config but does not implement an MCP runtime boundary", `discoverable=False`. Kein halbproduktiver MCP-Pfad in `daedalus/runtimes/` gefunden. |

## D. Schritt D — Runtime und Sandbox (Punkte 17–22)

| # | Punkt | Verdikt | Evidenz |
|---|---|---|---|
| 17 | Runtime-Manifest-Schema + Conformance Receipt | **done** (Verträge; Abweichung: 8 statt 9 Checks) | wie A.7; `RuntimeConformanceReceipt` importiert in `gates/report.py:11`; fehlender 9. Check `process-tree-kill` nur als Fault-Szenario (`fault_matrix.py:495`). |
| 18 | Recorded Fixtures für normale PR-CI | **done** | `kernel/runtime_conformance.py` `RecordedObservation`:32 + exakte Fixture-Abdeckungspflicht :70-76; Workflow `g0-runtime-conformance-fixtures.yml`; deterministic-fixture-Szenarien im Katalog (:477-489); `configs/runtimes/gate0-runtime-profiles-v1.json`. |
| 19 | Nightly/manuelle Live-Conformance für Claude, Codex, Ollama | **absent** (Verträge vorhanden, Workflows fehlen) | Einziger Cron im Repo: `fourfold-polyglot-probe.yml` (`17 3 * * 1`). Kein scheduled Live-Conformance-Workflow für die drei Provider. Live-Vertragsseite existiert: `RuntimeConformanceEnvelope`/`verify_runtime_envelope` (`profiles.py:392/:517`), live-runtime-Szenarien `runtime.live-envelope.expiry`/`binary-drift` (`fault_matrix.py:492-493`). |
| 20 | Docker-Sandbox (ro-Root, begrenzte Mounts, Limits, Prozessbaum-Kill) | **done als Baustein, partial als Pflicht** | `kernel/sandbox.py` deckt die Gesamtplan-Referenzflags nahezu 1:1 und die Verbotsliste (kein Socket-Mount :86-89, non-root :79-80, keine rw-Referenzen :83-85, Image-Digest-Pflicht :71-72). Prozessbaum-Kill als Host-Fault-Executor (`runtime.process.ignored-sigterm` :495; `g0-linux-process-fault-executors.yml`). Noch nicht verpflichtend im Attempt-Pfad (Migrationsnoten der kernel.attempt.*-Zeilen). Sicherheitsvalidierung ist Linux-CI-Sache — hier auf Windows nicht messbar (**ASSUMED**). |
| 21 | Fault Tests (9 benannte Fälle) | **partial** | Abdeckung im Katalog `runtimes/fault_matrix.py:476-501`: Netzwerk ohne Egress-Lease → :498; Secret-Enumeration → :499; Timeout → :494; Child-Prozess nach Cancellation → :495; darüber hinaus OOM :496, Sandbox-Ausfall :497, Unknown-Outcome-Replay :500 und 13 Broker/Trust/Ledger-Szenarien, die der Plan nicht kennt. **Kostenüberschreitung** und **Kill-Switch während Laufzeit** sind als Lease-Verträge erzwungen (`effects.py:270/:311/:468`; Tests `tests/kernel/test_effect_authorization.py`, `tests/test_gate0_faults_atalanta.py`), nicht als Host-Fault-Szenarien. **Nicht als Szenario gefunden**: Schreiben außerhalb Workspace (Containment-Tests `tests/test_gate_containment.py` existieren — Zuordnung ASSUMED), Mutation des Primary Checkout (stattdessen Report-Feld + `repository_write_*`-Familie), **Evaluator-Manipulation (kein Treffer — absent)**. Plus: Matrix noch nicht in den Report gebunden (Blocker `fault-matrix:not-yet-bound`). |
| 22 | Gate 0 schließen + Promotion-PR nach `main` | **absent (korrekt blockiert)** | Live gemessen `closed=false`, `security_boundary_claimed=false`, 60 Blocker. Fail-closed Release-Maschinerie steht bereit (`gates/release.py`). |

---

## E. Stale-Check: Gesamtplan-Behauptungen vs. Trunk (wo der Trunk VORAUS ist — Gold)

1. **"`python.offload` … als `UNGUARDED` geführt"** → STALE. Trunk: `wiring=CENTRAL`, "every live call consumes a persisted Effect Lease", Migration "complete" (`effect_boundary.py:338/:342-347`; Konsumtion `offload.py:743-785`).
2. **"`python.promote_candidates` … `UNGUARDED`"** → STALE. Trunk: `LOCAL_GUARDS` mit mechanischen Ankern `authorize_promotion` + `resolve_live_target_revision` (`effect_boundary.py:363-373`); public Callable fail-closed ohne persistierte Owner-Autorität (`gated_writes.py:202-243`). Offen bleibt nur die Effect-Lease-Zentralisierung (:380-383) — genau so in der Zeile dokumentiert.
3. **"der Owner-Approval-Guard ist noch nicht implementiert"** → STALE. `GUARD_CONTRACT_IMPLEMENTED["promotion.owner_approval"]=True` (`effect_boundary.py:150`), voll implementiert in `kernel/approvals.py` (Ledger, One-Use-Konsumtion, HMAC-Signatur, CLI); Live-Report `owner_approval_enforced=true`.
4. **Gate-Report-Schema `daedalus-gate-report/1`** → Trunk ist bei **/2** (mit Event-Store-Writer-Inventar) und **/3** in Arbeit (`report.py:23`, `report_v3.py:28`, `scripts/report_gate0_v3.py`); /1 nur noch als Legacy lesbar. Die Gesamtplan-Feldliste ist eine echte Teilmenge der v2-Felder.
5. **"Gate 0 zunächst mit einer kleinen eigenen Docker-Sandbox-Abstraktion schließen"** → die Abstraktion existiert bereits vollständig inkl. Verbotsliste (`kernel/sandbox.py`), mit Launch-State-Klassifikation, die der Plan nicht fordert.
6. **OwnerApproval/PromotionReceipt-Bindung (Schritt C 10)** → nicht nur gebunden, sondern mit persistiertem `PromotionExecutionLedger` + Event-Spine-Anbindung über Plan-Soll hinaus (`kernel/promotion_execution.py:195/:281/:575`).
7. **Fault-Matrix** → 24 Szenarien statt der 9 geplanten Fälle; zusätzliche Klassen (Broker-Replay, Foreign Authority, Trust-Fence-Races, Ledger-Contention, Unknown-Outcome-Reconciliation) mit eigenen CI-Workflows (`g0-*-fault.yml`).
8. **Adoption-Baseline** → der Plan wollte eine statische `configs/gates/gate0-adoption-baseline.json`; der Trunk hat den stärkeren digest-gepinnten `GateBaseline`-Vertrag (`gates/baseline.py`) — allerdings ist **kein Baseline-Artefakt committet** (der eine Rest, in dem der Plan noch Recht hat).
9. **Wo der Plan NICHT stale ist** (bestätigt durch Live-Messung): Web-/Bridge-/Adapter-/Provider-Pfade weiterhin INVENTORY_ONLY; Gate 0 offen; MCP kein Runtime-Boundary.

## F. Offene Restschuld auf dem Trunk (kondensiert, aus dem Live-Report)

1. 44 INVENTORY_ONLY-Zeilen + 15 unregistrierte `tools.*`-Entrypoints + 2 legacy SpineLedger-Writer in `spine/attempt.py:1661-1662` → Punkte 6/15.
2. Runtime-Conformance-Receipts und Fault-Matrix-Ergebnisse noch nicht in den Gate-Report gebunden (`not-yet-bound`-Blocker) → Punkte 7/8/17/21.
3. Kein committetes Adoption-Baseline-Artefakt; Monotonie-CI nicht als repo-weite Pflichtprüfung verdrahtet → Punkte 7/8 (Schritt B).
4. Keine nightly Live-Conformance-Workflows für Claude/Codex/Ollama → Punkt 19.
5. Kein Evaluator-Manipulations-Fault-Szenario; Workspace-Escape/Primary-Mutation nur indirekt abgedeckt → Punkt 21.
6. Docker-Sandbox noch nicht Pflicht des Attempt-Pfads (kernel.attempt.*-Migrationsnoten) → Punkte 8/20.

## G. Unsicherheiten (ASSUMED)

- Zweite In-Lock-Reauthentifizierung in `promote_candidates` nur per Docstring belegt (Body hinter `gated_writes.py:259` nicht gelesen).
- Branch-Protection/Required-Checks auf GitHub lokal nicht prüfbar.
- Linux-Sicherheitsverhalten der Sandbox/Faults auf diesem Windows-Host nicht ausführbar; Evidenz sind Verträge + Workflows + Fixtures.
- Zuordnung `tests/test_gate_containment.py` ↔ "Schreiben außerhalb Workspace" nicht im Detail verifiziert.

Iron Plan: ALIGNED · Iron Gate: 0 · Evidence: Live-`daedalus.gates report` auf 60b2bfe (60 Blocker, closed=false) + file:line-Belege oben.

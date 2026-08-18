# Watchdog mission status — gw_watchdog-mission2 (cc304878)

Append-only. One paragraph per slice, with commit SHA and RAW test lines.

## Slice 1 — Phase 1 Batch 1: paid external-call doors registered (2026-08-17)

Commit `ab078b3` "fix(g0): register the paid external-call doors -- boundary:
115 -> 113 unregistered (widened)". Registered `tools.guarded_call` (B1, the
external-model door; statically invisible cross-module sink → shows up as an
`entrypoint.not_rediscovered` review finding, by design), `tools.audit_swarm`
(A1) and `tools.funnel` (A2) as `inventory_only` rows with hand-declared
spend/secrets/egress and `fan_out`/`budget_verdict` anchors; corrected the
`provider.deepseek` legacy row from filesystem_write-only to
fs_write+egress+spend+secrets (ground truth: `DEEPSEEK_API_KEY` read at
`daedalus/providers/deepseek.py:178`, priced `chat_completion` →
`_guarded_urlopen`). New test
`test_paid_tools_doors_are_registered_with_spend_and_secrets`.
Counter provenance [MEASURED on this tree]: widened discovery (all six
python-bearing top-level dirs) pre-batch 115 unregistered, post-batch 113; the
inventory's floor of 114 was measured @`60b2bfe` and the tree has drifted by
one discovery (166 vs 165 targets) since. Narrow scan: 13 unregistered
`tools.*` targets remain.
RAW: `pytest tests/test_effect_boundary.py -q` → `21 passed in 19.94s`.
RAW: `PYTHONUTF8=1 python tools/run_gate_checks.py g0` → `75 passed in 76.53s (0:01:16)`.
Environment note: Serena MCP tools absent this session (known startup race);
`long_horizon_work_state` is maintained directly at
`.serena/memories/long_horizon_work_state.md`.
Guard note (for later lanes): the shell guard also blocks freestanding
`daedalus`/`tests`/`tools` words in commit texts, not only `docs` — and also
bare `tools/` / `tests/` followed by whitespace; use dotted module names or
full slashed file paths.

## Slice 2 — Phase 1 Batch 2: repo-mutating tool entrypoints (2026-08-17)

Commit `812ca60`. Registered `tools.iron_plan_guard` (protected artifact —
registry row only, target untouched), `tools.gate_discrimination`,
`tools.bootstrap_receipt`, `tools.operability_drill`,
`tools.gate_host_preflight` with hand-declared `repository_mutation` (git is
argv; §5 of the inventory: never statically inferable) plus `tools.gui_check`
as discovered. New test
`test_repo_mutating_tools_declare_repository_mutation_by_hand`.
RAW: `pytest tests/test_effect_boundary.py -q` → `22 passed in 19.26s`.
RAW: `run_gate_checks g0` → `76 passed in 71.04s (0:01:11)`.
Counter [MEASURED]: widened 113 → 107.

## Slice 3 — Phase 1 Batch 3: scanned packages fully inventoried (2026-08-17)

Commit `f04e46c`. Registered the last seven `tools/` targets (mutation_score,
audit_triage, agent_findings, lane_invariants, funnel_report, run_gate_checks,
iron_plan_hook_runner [protected — row only]) plus `tools.system_check` (B2,
CHECKS-table dispatch, all five effects hand-declared); deleted the stale
`cli.claude_bridge` row (target is a fail-closed stub; the row was the
registry's only staleness finding). **Narrow scan now structurally conformant:
0 blockers.** The two red-state test pins were rewritten (not weakened): scan
reach into `tools/` is pinned via discoveries; `--require-gate0` pinned to
still exit 3; the two invisible doors pinned as named `not_rediscovered`
review findings. RAW: `pytest tests/test_effect_boundary.py -q` → `23 passed
in 21.36s`. RAW: `run_gate_checks g0` → `77 passed in 65.28s (0:01:05)`.
Counter [MEASURED]: widened 107 → 100 (remaining: scripts/ 74, tests/ 17,
runs/ 9).

## Slice 4 — Phase 1 Batch 4: scan widened to runs/, money doors registered (2026-08-17)

Commit `41c3cf3`. `SCAN_PACKAGES` += `runs` (BILLABLE_SITES prices five of its
functions; the scan never opened the directory). All ten `runs/` entrypoints
registered in the same commit — zero blockers left behind:
`runs.council.room` (5 vendors, spend+secrets), `runs.council.summarize`,
`runs.ab.run_arm` (spend+repo-mutation), `runs.council.room_server` (C4
subclass evasion — `ThreadingHTTPServer` subclass defeats the literal sink
match, `listen_socket` hand-declared, pinned as named review finding),
`room_server.post`, `stream_hook`, `dead_letter_replay`, `score`,
`oracle_check`, `blind`. scripts/tests exclusion now documented at
`SCAN_PACKAGES` instead of silent. New test
`test_runs_package_is_scanned_and_its_billable_doors_are_registered`.
RAW: `pytest tests/test_effect_boundary.py -q` → `24 passed in 27.65s`.
RAW: `run_gate_checks g0` → `78 passed in 79.67s (0:01:19)`.
Counter [MEASURED]: widened 100 → 91 (remaining: 74 script runners, 17 test
fixtures — the Tier-5 "classify, do not migrate" population).

## Slice 5 — Phase 1 Batch 5: harness classification, Phase 1 complete (2026-08-17)

Commit `74c10b0`. `HARNESS_PACKAGES = ("scripts", "tests")` added to the
canonical boundary module; `check_conformance` reads the harness dirs with the
same discovery and emits `entrypoint.harness` REVIEW findings (91 today, each
carrying inferred effects) instead of blockers or silence. Harness scan cached
per process+root (`_harness_scan`, lru_cache; staleness bound stated in
docstring; production packages never cached). Console-script resolution
excluded from the harness pass (`_console_scripts=False`) to avoid spurious
blockers. **Phase-1 endstate: every python-bearing top-level dir is enforced
(SCAN_PACKAGES), classified (HARNESS_PACKAGES), or entrypoint-free; 0 silently
unscanned effectful entrypoints.** New test
`test_harness_entrypoints_are_classified_not_silent_and_never_blockers` incl.
minimal-repo mechanism check.
RAW: `pytest tests/test_effect_boundary.py -q` → `25 passed in 109.05s (0:01:49)`.
RAW: `run_gate_checks g0` → `79 passed in 254.62s (0:04:14)` (profile cost up
from ~80s pre-widening — the price of reading ~550 harness files once per
subprocess; measured 363.48s without the cache, 254.62s with it).

## Slice 6 — Phase 3: ignition fault suite + G1 activation checklist (2026-08-17)

Commit `05d5ba3`. Five new fault cases in
`tests/ignition/test_voltage_ignition_faults.py` pin the rehearsal's refusal
semantics (restart-over-debris refusal + digest-identical fresh-root replay;
nested/self candidate refusal; layered tamper defense — claim verification at
compile [layer 1], exact-count rename precondition [layer 2]; mid-run
source-mutation tripwire via injected fault). Finding en route: the layered
defense means a models.py tamper is caught by `ReferenceCompileError` at Twin
compile before the rename precondition can even fire — the precondition layer
is only reachable through a claim-unbound site (repository.py expression).
`docs/work-packets/G1_ACTIVATION_CHECKLIST.md` written: rehearsal→authoritative
gaps (no MissionContract/WorkItem artifacts/Event-Store spine; synthetic
revisions, no CAS; in-process behavior probe = evaluator/candidate separation
gap; missing test/schema/link evaluators; no failed-evidence retention;
resume-from-event-spine unproven; sealed-stack dry-run open) + activation
preconditions (Gate-0 closure, 4 owner decisions untouched). NO activation
performed.
RAW: `pytest tests/ignition/ -q` → `9 passed in 4.60s`.
RAW: `run_gate_checks g1` → `45 passed in 9.45s`.
Phase 2 suite (kernel/gates/runtimes) still running in background
(task bz0a1y781).

## Slice 7 — Phase 2: suite measured, all failures classify into parked clusters (2026-08-17)

RAW: `pytest tests/kernel tests/gates tests/runtimes -q` →
`22 failed, 1868 passed, 48 skipped in 390.69s (0:06:30)`.
Classification (each family sampled and diagnosed, not guessed):
**v3 family (3)** — `test_gate_report_v3{,_cli,_review}` → owner decision 2 /
lane `grind/v3-scanner-owner-prep`. **Review-pin drift** —
`test_fault_matrix_wire_type_review` (pins exact source substring
`type(payload[field]) is not bool` that the landed `from_dict` no longer
contains), `test_repository_head_revision_integration_review` ("ports exact
reviewed blobs"), `*_counter_review does not claim ... authority` family,
`provider_target_{verification,receipt_ledger}_review`,
`provider_observation_persistence_inventory_review`,
`gate_baseline_v2_review`, `test_isolated_attempt_effect_inventory`
(IndentationError in its own pinned-source extraction helper) → blob-pin
cluster (owner decision 3) / K1–K13 wording rebase (owner decision 4).
**Refusal-order drift (still fail-closed)** —
`provider_executable_targets` substitution now refuses earlier with
"not registered exactly once" instead of "differs from authenticated
identity"; `isolated_attempt_spine_wire_review` unknown-terminal-state now
refuses earlier with "persisted attempt start is not an object";
`isolated_attempt_lifecycle` restart case refuses with "trusted attempt start
time follows its Event-Store start event" (clock-authority ordering,
amendment-005 environment) → CENTRAL/K1–K13 cluster (owner decision 4).
**Cross-check:** only ONE failing file imports anything my commits touched
(`test_isolated_attempt_effect_inventory` imports ENTRYPOINTS), and its
failure is in its own source-extraction helper over `daedalus/kernel/` sources
this mission never modified; its three ENTRYPOINTS-consuming tests pass.
Conclusion: zero non-lane failures found to fix; refusal-message rebases are
owner/lane territory and weakening refusals to match old pins is forbidden.
Negative result retained here instead of "fixed".

## Slice 8 — Phase 4: Forest-v2 pre-study as labeled EXPERIMENT (2026-08-17)

`experiments/forest_v2/` created: README with frozen hypothesis, scope,
budget (≤2h, no spend), expiry (2026-10-31), kill-criterion linkage and "no
production promotion / no production import" declaration; plus the read-only
probe `probe_call_resolution.py` (stdlib AST only — no repo imports, writes,
network, subprocess; prints one JSON object).
RAW [MEASURED @05d5ba3]: 307 files, 0 unparseable, 42,725 call sites; 6,616
same-module resolvable (**15.5%**); gap upper bound **84.5%** (caveat in the
README: includes stdlib/instance calls — the later resolver must be graded
against the same counting rule). The three hand-registered invisibility
classes (guarded_call, system_check, room_server) are named as the ready-made
acceptance cases for a future resolver. Boundary note recorded: the probe's
print-only `main` is correctly read-only; any future effectful entrypoint
under `experiments/` must be registered or the dir added to HARNESS_PACKAGES.

## Mission summary

All four phases executed. Phase 1: 5 batches, widened boundary counter
115 → 91-classified/0-silent, narrow scan structurally conformant (0
blockers), scan widened to the run dir, dev harness explicitly classified.
Phase 2: suites measured (22/1868/48), every failure classified into the four
owner-parked clusters with sampled diagnoses; zero non-lane failures; nothing
weakened. Phase 3: G1 activation checklist + 5 fault tests pinning the
rehearsal's refusal semantics (9/9 green). Phase 4: bounded read-only
EXPERIMENT with measured baseline. Commits: ab078b3, 812ca60, f04e46c,
41c3cf3, 74c10b0, 05d5ba3, + final experiment/status commit. Gate 0 remains
open (78 not-central gaps, live receipts, fault matrix, owner decisions) —
by design, not by omission.

---

# Watchdog mission 3 — grind/watchdog-mission3 (base 4fb2251), Nachtschicht 2026-08-17/18

Iron Plan: ALIGNED · Iron Gate: 0. Serena workspace umfasst nur agent_env;
Memory-Tools für long_horizon_work_state, Code-Arbeit mit Built-in-Tools.
(Korrektur: dieser Abschnitt hat beim ersten Landen 8e5b3023 die Mission-2-
Historie überschrieben; hier wiederhergestellt und angehängt — append-only
verletzt, gemessen an 182 Deletions, sofort repariert.)

## Slice 1 — Phase 1: Conformance-Receipt-Persistenz (a515bf7)

persist_conformance_receipt im kanonischen Produzenten: Receipt landet als
<digest>.json (kanonische Bytes, idempotent, Kollision → Refusal). Binding
_load_bundle verweigert jede Bundle-Datei, deren Bytes nicht mehr auf den
eigenen Namen hashen (receipt-bundle:digest-mismatch); Exec-Mutant-Probe
belegt, dass der Digest-Check allein die Manipulation abfängt. Gap-Diagnose
umbenannt (Persistenzpfad existiert jetzt), UNBOUND_ROW unverändert.
Vertragsverschärfung: Bundle-Dateien MÜSSEN digest-benannt sein; der alte
one.json-Test wurde zum Refusal-Test (strenger, nichts abgeschwächt).
RAW: `1 failed, 20 passed in 51.42s` (Erstlauf; Mutant brauchte
sys.modules-Registrierung für dataclass-exec) → danach
`16 passed in 55.43s` (Binding-Suite). Report-Ebene: produce→persist→bind→
UNBOUND_ROW verschwindet, getestet gegen echten build_gate0_report.

## Slice 2 — Phase 2: FaultMatrixEvidence-Brücke (9937e33)

fault_matrix_evidence_from_verdict in daedalus/gates/fault_matrix_binding.py:
Verdikt → bestehende FaultMatrixEvidence-Zeile, kein neues Subsystem.
Katalog-Digest wird gegen verdict.catalog_sha256 geprüft (Mismatch → Refusal
vor jeder Zeile); matrix_sha256 = Digest aus dem Verdikt-Contract, läuft
exakt in den trusted_fault_matrix_sha256s-Check des strikten Verifiers;
Dev-Key-Verdikt → status="failed" + Origin-Markierung
(runtimes.whole-fault-matrix.<key-class>), mechanisch kein Closure-Claim
(fault-matrix:<id>:status-failed). Negativbefund: Verdikt-from_dict verlangt
kanonische Payloads — Timestamps brauchen Mikrosekunden.
RAW: `6 passed in 2.58s` (Brücke) · `35 passed in 448.98s`
(fault_matrix_binding + gate_report_matrix_binding, exit 0).

## Slice 3 — Phase 3 (Memo) + Phase 4 (Crash-Probe) (7e950d44)

docs/GATE0_LIVE_RUNTIME_DECISION.md: Entscheidungsvorlage für die zwei
live-runtime-Zeilen — was ein Collector konkret bräuchte (Live-Host,
Owner-Key-Zeremonie für Produktions-Signatur-Autorität, zwei Probe-Treiber,
dritte Spalte), Option A/B mit Wortlaut nach Docker-Präzedenz, Empfehlung
(B kurzfristig, A Zielzustand), Rollback. Nichts entschieden, nichts gebaut.
G1-Checkliste §2.5: fehlende Mid-Write-Crash-Probe ergänzt
(test_crash_between_rename_writes_leaves_no_evaluable_candidate) —
gemischter Kandidat nie evaluierbar, Quelle byte-identisch,
Fresh-Root-Replay digest-identisch. RAW: `10 passed in 6.85s`.

## Slice 4 — Status-Ledger + G1-TOCTOU-Bewertung (8e5b3023, repariert hier)

G1-Checkliste TOCTOU-Zeile annotiert: nicht vorziehbar, weil
IsolatedAttemptCoordinator.prepare AttemptContract + CAS-StoredSourceTree
verlangt (= Checklisten-Schritte 1–2 "once unblocked"); Platzhalter-Verträge
wären genau das, was §2.1 beseitigen soll.

## Regressionssignal nach allen Slices

`python -m pytest tests/gates/ tests/kernel/ tests/runtimes/test_runtime_conformance_profiles.py -q`
→ RAW: `1221 passed, 2 skipped in 1030.91s (0:17:10)`, exit 0.

## Slice 5 — Phase 5: Forest-v2-Experiment-Fortsetzung (e4734dd7)

Im deklarierten Experiment-Rahmen (read-only, stdlib-AST, kein Repo-Import,
kein Spend, Budget ≤2h, gleiche Zählregel): zweite Sonde
probe_cross_module_resolution.py misst, was Import-Binding-Auflösung über
den Same-Module-Fixpunkt hinaus attribuiert. Baseline an diesem HEAD neu
gemessen (44,115 Sites, 15.5%). Ergebnis: Attribution 15.5% → 30.3%
(2,413 repo-verifiziert + 4,098 extern attribuiert); alle drei gemessenen
Invisibility-Klassen mechanisch detektierbar — room_server-Subclass-Basen
lösen nach http.server auf, system_check-Registry-Decorator (@check→CHECKS,
18 Funktionen) strukturell gefunden, und guarded_call ist entgegen der
Pre-Study-Erwartung attributierbar (Sink-Importe sind function-level,
Zeilen 62/68): "statically invisible" heißt gemessen nur "invisible für den
Same-Module-Fixpunkt". Korrektur im Experiment-README festgehalten;
Inventory-Pin-Revision ist Gate-2-Produktionsarbeit, nicht Sache dieses
Experiments. Keine Produktionsverdrahtung.
RAW: Sonde druckt ein JSON (attributed_pct 30.3, cross_module_repo 2413).

## Abschlussverifikation (nach e4734dd7)

Plan-Guard verify → `Iron Plan OK: revision 5, Gate 0 … ce4335e1…`, exit 0.
`python -m pytest tests/test_effect_boundary.py -q` → RAW:
`26 passed in 115.65s (0:01:55)` (experiments/-Zugang bleibt boundary-sauber).

## Mission 4, Slice 1: adapter.subprocess-Familie zentral verdrahtet (3716d4e9)

Vier Entrypoints (create_session/send/interrupt/terminate) starten jetzt nur
noch durch `begin_effect` mit echter runtime.adapter_profile-Entscheidung
(verified-profile vs explicit-config, gebundener repo_root); Start-Receipt
wird pro Session einbehalten, refusierter terminate lässt die Session
getrackt. Registry: 4 Zeilen auf Wiring.CENTRAL mit begin_effect-Ankern;
inventory_only 70 -> 66.
RAW: tests/test_adapters.py `12 passed in 1.00s`; tests/test_effect_boundary.py
`26 passed in 51.88s`. Mutationsprobe RAW: Schleuse deaktiviert ->
`FAILED tests/test_adapters.py::test_create_session_is_refused_fail_closed_without_the_guard_contract`,
restauriert -> `1 passed`.

## Mission 4, Slices 2-8: CENTRAL-Verdrahtung 66 -> 12 inventory_only

Owner-Direktive umgesetzt: echte `begin_effect`-Pfade mit ausgefuehrten
Guard-Entscheidungen, kein Registry-Umdeklarieren. Commits (je Batch, mit
Zaehlerstand, Familientests + Mutationsprobe RAW in der Commit-Message):

- 3716d4e9 adapter.subprocess-Familie (4): runtime.adapter_profile-Entscheidung
  (verified-profile vs explicit-config), Receipt pro Session. 70->66.
- (Batch 2) 8 cli.* via budget.process_guard: process_guard_boundary_decision()
  in daedalus/budget.py installiert das echte Spend-Netz und liefert die
  Entscheidung; read-only-Pfade bleiben fail-open. 66->58.
- b9dfec91 8 weitere cli.* (arch_memory, bookkeeper, dctx, doctor, eval_*,
  memory). Mutationsprobe bookkeeper: Schleuse aus -> Test rot UND der
  ungeschuetzte Lauf ueberschrieb docs/architecture.html (restauriert) --
  der Beweis, wozu die Schleuse da ist. 58->50.
- 32eeaafe file_bridge.enqueue/process/watch (crash_journal-Entscheidung
  verifiziert das durable Journal; enqueue-Refusal hinterlaesst keine Datei)
  + cli.file_bridge/mapping_*/status. RAW: bridge+mapping 197 passed. 50->42.
- 6269c53e 8 tool-runner mains; Pinning-Loops tragen jetzt SOLL-Wiring pro
  Zeile (CENTRAL fuer verdrahtete, INVENTORY_ONLY fuer protected). 42->34.
- ddc4ad9b bezahlte/git-anfassende Tool-Tueren inkl. guarded_call (echte
  provider.egress_policy-Entscheidung: secret_floor_rule ueber den Outbound-
  Payload; Refusal als JSON exit 0 nach Prozess-Protokoll). 34->27.
- 26a8ab5a runs/-Tueren (Council-Room, Summariser, Room-Server inkl.
  per-POST-Start, Stream-Hook schreibt bei Refusal NICHTS, Dead-Letter,
  4x A/B). 27->17.
- 251d350c web.mutations/put (per-Request-Start nach Auth, Bind-Klasse als
  Entscheidung), cli.web_api (echter _resolve_bind-Verdict), command_gate,
  worktree.reap. Nebenwirkung gefangen: Proben mit echtem Netz resetteten
  runs/budget/ledger.json -> aus HEAD restauriert. 17->12.

Rest (12) ausnahmslos mit REASONED-REMAINDER-Notiz in der Registry:
2 protected Plan-Guard-Artefakte, 3 runtimes-Kollektoren + gate0-matrix-
Verifier (parallele live-runtime-Lane grind/live-column), 6 Provider-
Lifecycle-Zeilen (zentral nur ueber die runtime-gebundene Lease/Broker-
Kette; eine zweite plain-Schleuse waere eine schwaechere Parallel-Tuer).

Gate-Report RAW bei HEAD 251d350c (mission4-gate-report-final.json):
inventory_only 12, blockers 73 -> 15 (58 geloest, 0 NEUE), unregistered 0,
unguarded 0, missing_guard_contracts 0, registry_sha256 b947fe55f15998fe...
Suiten RAW: tests/test_cli_effect_boundary.py `49 passed in 8.02s`;
tests/test_effect_boundary.py `26 passed in 51.62s`; tests/test_adapters.py
`12 passed`; bridge+mapping `197 passed, 2 subtests passed in 50.70s`;
web+worktree `72 passed in 25.76s`; spine attempt `40 passed in 14.41s`.
Mutationsproben RAW je Familie: adapter/create_session, cli.enforce,
cli.bookkeeper, file_bridge.enqueue, lane_invariants, guarded_call,
stream_hook, cli.web_api -- jeweils Schleuse deaktiviert -> benannter Test
FAILED, restauriert -> passed. Plan-Guard verify: Iron Plan OK (ce4335e1...).

## Mission 4, Abschlussverifikation (nach 7cea2d24)

Breite Regression (detached, voller Baum) RAW:
`7 failed, 6686 passed, 109 skipped, 1 xfailed, 17 warnings, 1992 subtests passed in 3147.86s (0:52:27)`.
Triage der 7:
- test_spend_coverage (Installer-Pin): ECHT durch die Mission -- daedalus/budget.py
  installiert das Netz jetzt in process_guard_boundary_decision(). Pin bewusst
  erweitert (7cea2d24), Test danach gruen.
- test_killswitch latency-gate: Last-Flake unter der 52-min-Suite; standalone
  RAW gruen im Re-Run-Batch.
- 4x tests/gates/test_gate_report_matrix_binding + test_envelope_coverage:
  VORBESTEHENDE Baseline-Fehler bei Basis 35172501, separat benannt:
  drei getrackte Matrix-Laeufe (runs/gate0-matrix-2026-08-17, -20260818-head,
  -20260818-morning) machen die Whole-Matrix-Evidenz ambivalent
  (`whole-matrix:unbound:ambiguous-evidence:3`), und
  runs/gate0-matrix-2026-08-17/verify_whole_matrix.py fehlt im
  Producers-Ledger. Beweis: `git diff 35172501..HEAD` beruehrt weder
  daedalus/gates/, daedalus/kernel/, tests/gates/, envelope noch runs/gate0-*
  (nur die Sluice-Zeilen in runs/ab+council-Skripten, die das Binding nicht
  liest) -- die Test-Inputs sind byte-identisch zur Basis. Beide Bereiche
  gehoeren der parallelen live-runtime-Lane (grind/live-column) und sind fuer
  diese Mission ausdruecklich tabu; Reparatur liegt dort.
Re-Run-Batch RAW nach Pin-Fix: gates-binding+spend+killswitch+envelope
`5 failed, 87 passed in 350.94s` -- die 5 sind exakt die benannten
Baseline-Fehler. runs/budget/ledger.json wurde von Suite-Laeufen erneut
zurueckgesetzt und aus HEAD restauriert (bekannte Nebenwirkung, s.o.).
Mission-Ziel erreicht: inventory_only 70 -> 12, alle 12 mit begruendeter
Registry-Notiz; 0 neue Gate-Report-Blocker; 58 geloest.

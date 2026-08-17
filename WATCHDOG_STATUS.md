# Watchdog mission 3 — status ledger (append-only)

Worktree `gw_watchdog-mission3`, branch `grind/watchdog-mission3`, base 4fb2251.
Iron Plan: ALIGNED · Iron Gate: 0. Serena workspace covers only `agent_env`;
memory tools used for `long_horizon_work_state`, code work via built-in tools.

## Slice 1 — Phase 1: Conformance-Receipt-Persistenz (a515bf7)

`persist_conformance_receipt` im kanonischen Produzenten: Receipt landet als
`<digest>.json` (kanonische Bytes, idempotent, Kollision → Refusal). Binding
`_load_bundle` verweigert jede Bundle-Datei, deren Bytes nicht mehr auf den
eigenen Namen hashen (`receipt-bundle:digest-mismatch`); Exec-Mutant-Probe
belegt, dass der Digest-Check allein die Manipulation abfängt. Gap-Diagnose
umbenannt (Persistenzpfad existiert jetzt), UNBOUND_ROW unverändert.
Vertragsverschärfung: Bundle-Dateien MÜSSEN digest-benannt sein; der alte
`one.json`-Test wurde zum Refusal-Test (strenger, nichts abgeschwächt).
RAW: `1 failed, 20 passed in 51.42s` (Erstlauf; Mutant brauchte
sys.modules-Registrierung für dataclass-exec) → danach
`16 passed in 55.43s` (Binding) und Harness-Persistenztests grün im
Kombilauf. Report-Ebene: produce→persist→bind→`UNBOUND_ROW` verschwindet,
getestet gegen echten `build_gate0_report`.

## Slice 2 — Phase 2: FaultMatrixEvidence-Brücke (9937e33)

`fault_matrix_evidence_from_verdict` in `daedalus/gates/fault_matrix_binding.py`:
Verdikt → bestehende `FaultMatrixEvidence`-Zeile, kein neues Subsystem.
Katalog-Digest wird gegen `verdict.catalog_sha256` geprüft (Mismatch →
Refusal vor jeder Zeile); `matrix_sha256` = Digest aus dem Verdikt-Contract,
läuft exakt in den `trusted_fault_matrix_sha256s`-Check des strikten
Verifiers; Dev-Key-Verdikt → `status="failed"` + Origin-Markierung
(`runtimes.whole-fault-matrix.<key-class>`), mechanisch kein Closure-Claim
(`fault-matrix:<id>:status-failed`). Negativbefund festgehalten: Verdikt-
`from_dict` verlangt kanonische Payloads — Timestamps brauchen Mikrosekunden.
RAW: `6 passed in 2.58s` (Brücke) · `35 passed in 448.98s`
(fault_matrix_binding + gate_report_matrix_binding, exit 0).

## Slice 3 — Phase 3 (Memo) + Phase 4 (Crash-Probe) (7e950d44)

`docs/GATE0_LIVE_RUNTIME_DECISION.md`: Entscheidungsvorlage für die zwei
`live-runtime`-Zeilen — was ein Collector konkret bräuchte (Live-Host,
Owner-Key-Zeremonie für Produktions-Signatur-Autorität, zwei Probe-Treiber,
dritte Spalte), Option A/B mit Wortlaut nach Docker-Präzedenz, Empfehlung
(B kurzfristig, A Zielzustand), Rollback. Nichts entschieden, nichts gebaut.
G1-Checkliste §2.5: fehlende Mid-Write-Crash-Probe ergänzt
(`test_crash_between_rename_writes_leaves_no_evaluable_candidate`) —
gemischter Kandidat nie evaluierbar, Quelle byte-identisch, Fresh-Root-Replay
digest-identisch. RAW: `10 passed in 6.85s` (Ignition-Suite).

## Regressionssignal nach allen drei Slices

`python -m pytest tests/gates/ tests/kernel/ tests/runtimes/test_runtime_conformance_profiles.py -q`
→ RAW: `1221 passed, 2 skipped in 1030.91s (0:17:10)`, exit 0.

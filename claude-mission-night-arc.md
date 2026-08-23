# Mission 2: Gate-0-Restarbeit und Gate-1-Vorbereitung (Nachtschicht 2026-08-17/18)

Iron Plan: ALIGNED. Aktives Gate: 0 (Canonical Kernel), Trunk-Verfassung
Revision 5. Lies zuerst `docs/IKARUS_ARIADNE_MASTER_PLAN.md` und `AGENTS.md`
vollständig — sie sind die Autorität über allem hier.

## Arbeitsumgebung und harte Grenzen

- Du arbeitest AUSSCHLIESSLICH in diesem Worktree
  (`C:\Users\nukei\Desktop\gw_watchdog-mission3`, Branch `grind/watchdog-mission3`,
  Basis 4fb2251).
- Parallel läuft eine Lane `grind/head-collection` (frische Matrix-Sammlung
  unter runs/) — deren Themen (runs/gate0-matrix-*, Gate-Report-Erzeugung)
  NICHT anfassen. Die Koordinatorin (Athena) portet und merged alles.
- Kein Merge, kein Push, keine Branch-Wechsel, keine Worktree-Operationen.
- Protected (niemals ändern): `docs/IKARUS_ARIADNE_MASTER_PLAN.md`,
  `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`, `tools/iron_plan_guard.py`,
  `tools/iron_plan_hook_runner.py`, `AGENTS.md`, `CLAUDE.md`, `.agentenv/`,
  `.claude/`, `.githooks/`, `.github/`, `daedalus/config.py`,
  `daedalus/kairos/gated_writes.py`, `daedalus/sensitivity.py`,
  `tests/test_iron_plan_guard.py`, `templates/agentenv.json`, `.gitattributes`.
- Commit-Trailer `Iron-Plan: aligned` + `Iron-Gate: 0` sind Pflicht.
- Der Guard blockt Shell-Befehle mit FREISTEHENDEN Wörtern "docs"/"tests"/
  "tools"/"daedalus" (auch in Commit-Messages; Pfade mit Slash sind ok) und
  broad verbs (merge/cherry-pick/stash pop). `git add` nie mit
  iron_plan_guard-verify in einem Befehl kombinieren.
- Scratch-Dateien IMMER mit `mission3-` prefixen; nach jedem `commit -F` die
  gelandete Message mit `git log -1 --format=%B` gegenlesen.
- Nie eine Assertion abschwächen, Fail-closed bleibt fail-closed. Negative
  Ergebnisse festhalten.

## Phase 1 — Conformance-Receipt-Persistenz

`daedalus/gates/runtime_conformance_binding.py` (frisch gelandet) bindet den
Blocker `runtime-conformance-receipts:unbound:no-persisted-receipt-bundle`,
weil der kanonische Produzent
(`daedalus.kernel.runtime_conformance.assemble_recorded_conformance`) Receipts
nur in-process zurückgibt. Baue den Persistenzpfad: Receipts als
content-addressierte Artefakte ablegen (dem Muster der anderen Evidence-Bündel
folgend, z. B. der Matrix-Receipts), sodass die Binding-Seite ihr
`receipt_dir=` bekommt. Tests: Erzeugen→Persistieren→Binden→Report zeigt den
Blocker nicht mehr; manipuliertes Receipt → Refusal. Mutationsprobe auf den
Digest-Check.

## Phase 2 — FaultMatrixEvidence-Brücke

`daedalus/gates/evidence.py` hat die Release-Pfad-Zeile `FaultMatrixEvidence`
(`matrix_id`, `matrix_sha256`, `scenario_ids`, `status`), und
`strict_mechanical_blockers` nimmt `trusted_fault_matrix_sha256s`. Verdrahte
das Gesamt-Matrix-Verdikt (`daedalus/runtimes/whole_fault_matrix.py`, Digest
aus dem Verdikt-Contract) in genau diese bestehende Zeile — KEIN neues
Subsystem, nur die Brücke plus Tests (gültiges Verdikt → Zeile akzeptiert;
Digest-Mismatch → Blocker; Dev-Key-Verdikt → als solches markiert, kein
Closure-Claim).

## Phase 3 — live-runtime-Zeilen: Entscheidungsvorlage (docs-only)

Die 2 letzten fault.missing-Zeilen (`runtime.live-envelope.expiry`,
`runtime.live-envelope.binary-drift`) brauchen eine dritte Collector-Spalte
gegen eine echte Signatur-Autorität, die im Repo nicht existiert. Schreibe
`docs/GATE0_LIVE_RUNTIME_DECISION.md`: was ein live-envelope-Collector
konkret bräuchte (welche Autorität, welcher Aufwand), Option A (bauen) vs.
Option B (Scoping-Entscheidung wie bei den Docker-Zeilen, mit Wortlaut-
Vorschlag), Empfehlung, Rollback. NICHT selbst entscheiden, NICHT bauen.

## Phase 4 — Gate-1-Aktivierungs-Preflight

Arbeite `docs/work-packets/G1_ACTIVATION_CHECKLIST.md` ab — NUR die maschinell
erledigbaren Punkte (fehlende Tests, fehlende Verdrahtung, Replay-Nachweise).
Die authoritative Aktivierung selbst ist owner-gated und bleibt aus. Ziel:
Nach dieser Phase ist die Ignition ein Ein-Befehl-Start plus Owner-Stempel.

## Phase 5 — Forest-v2-Experiment (nur wenn 1–4 erschöpft)

Weiterarbeit ausschließlich unter `experiments/forest_v2/` im deklarierten
Experiment-Rahmen (README dort: Hypothese, Budget, Expiry, no production
promotion). Lesen ja, verdrahten nein.

## Arbeitsdisziplin

- Serena-Memory `long_horizon_work_state` nach jedem kohärenten Slice pflegen.
- `WATCHDOG_STATUS.md` im Worktree-Root append-only führen (ein Absatz pro
  Slice, Commit-SHA + RAW-Testzeilen).
- Verifikation in Proportion zum Risiko; RAW-Ausgaben, keine Behauptungen.

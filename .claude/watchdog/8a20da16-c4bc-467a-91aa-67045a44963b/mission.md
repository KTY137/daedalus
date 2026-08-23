# Mission 2: Gate-0-Restarbeit und Gate-1-Vorbereitung (Nachtschicht 2026-08-17/18)

Iron Plan: ALIGNED. Aktives Gate: 0 (Canonical Kernel), Trunk-Verfassung
Revision 5. Lies zuerst `docs/IKARUS_ARIADNE_MASTER_PLAN.md` und `AGENTS.md`
vollstÃ¤ndig â€” sie sind die AutoritÃ¤t Ã¼ber allem hier.

## Arbeitsumgebung und harte Grenzen

- Du arbeitest AUSSCHLIESSLICH in diesem Worktree
  (`C:\Users\nukei\Desktop\gw_watchdog-mission3`, Branch `grind/watchdog-mission3`,
  Basis 4fb2251).
- Parallel lÃ¤uft eine Lane `grind/head-collection` (frische Matrix-Sammlung
  unter runs/) â€” deren Themen (runs/gate0-matrix-*, Gate-Report-Erzeugung)
  NICHT anfassen. Die Koordinatorin (Athena) portet und merged alles.
- Kein Merge, kein Push, keine Branch-Wechsel, keine Worktree-Operationen.
- Protected (niemals Ã¤ndern): `docs/IKARUS_ARIADNE_MASTER_PLAN.md`,
  `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`, `tools/iron_plan_guard.py`,
  `tools/iron_plan_hook_runner.py`, `AGENTS.md`, `CLAUDE.md`, `.agentenv/`,
  `.claude/`, `.githooks/`, `.github/`, `daedalus/config.py`,
  `daedalus/kairos/gated_writes.py`, `daedalus/sensitivity.py`,
  `tests/test_iron_plan_guard.py`, `templates/agentenv.json`, `.gitattributes`.
- Commit-Trailer `Iron-Plan: aligned` + `Iron-Gate: 0` sind Pflicht.
- Der Guard blockt Shell-Befehle mit FREISTEHENDEN WÃ¶rtern "docs"/"tests"/
  "tools"/"daedalus" (auch in Commit-Messages; Pfade mit Slash sind ok) und
  broad verbs (merge/cherry-pick/stash pop). `git add` nie mit
  iron_plan_guard-verify in einem Befehl kombinieren.
- Scratch-Dateien IMMER mit `mission3-` prefixen; nach jedem `commit -F` die
  gelandete Message mit `git log -1 --format=%B` gegenlesen.
- Nie eine Assertion abschwÃ¤chen, Fail-closed bleibt fail-closed. Negative
  Ergebnisse festhalten.

## Phase 1 â€” Conformance-Receipt-Persistenz

`daedalus/gates/runtime_conformance_binding.py` (frisch gelandet) bindet den
Blocker `runtime-conformance-receipts:unbound:no-persisted-receipt-bundle`,
weil der kanonische Produzent
(`daedalus.kernel.runtime_conformance.assemble_recorded_conformance`) Receipts
nur in-process zurÃ¼ckgibt. Baue den Persistenzpfad: Receipts als
content-addressierte Artefakte ablegen (dem Muster der anderen Evidence-BÃ¼ndel
folgend, z. B. der Matrix-Receipts), sodass die Binding-Seite ihr
`receipt_dir=` bekommt. Tests: Erzeugenâ†’Persistierenâ†’Bindenâ†’Report zeigt den
Blocker nicht mehr; manipuliertes Receipt â†’ Refusal. Mutationsprobe auf den
Digest-Check.

## Phase 2 â€” FaultMatrixEvidence-BrÃ¼cke

`daedalus/gates/evidence.py` hat die Release-Pfad-Zeile `FaultMatrixEvidence`
(`matrix_id`, `matrix_sha256`, `scenario_ids`, `status`), und
`strict_mechanical_blockers` nimmt `trusted_fault_matrix_sha256s`. Verdrahte
das Gesamt-Matrix-Verdikt (`daedalus/runtimes/whole_fault_matrix.py`, Digest
aus dem Verdikt-Contract) in genau diese bestehende Zeile â€” KEIN neues
Subsystem, nur die BrÃ¼cke plus Tests (gÃ¼ltiges Verdikt â†’ Zeile akzeptiert;
Digest-Mismatch â†’ Blocker; Dev-Key-Verdikt â†’ als solches markiert, kein
Closure-Claim).

## Phase 3 â€” live-runtime-Zeilen: Entscheidungsvorlage (docs-only)

Die 2 letzten fault.missing-Zeilen (`runtime.live-envelope.expiry`,
`runtime.live-envelope.binary-drift`) brauchen eine dritte Collector-Spalte
gegen eine echte Signatur-AutoritÃ¤t, die im Repo nicht existiert. Schreibe
`docs/GATE0_LIVE_RUNTIME_DECISION.md`: was ein live-envelope-Collector
konkret brÃ¤uchte (welche AutoritÃ¤t, welcher Aufwand), Option A (bauen) vs.
Option B (Scoping-Entscheidung wie bei den Docker-Zeilen, mit Wortlaut-
Vorschlag), Empfehlung, Rollback. NICHT selbst entscheiden, NICHT bauen.

## Phase 4 â€” Gate-1-Aktivierungs-Preflight

Arbeite `docs/work-packets/G1_ACTIVATION_CHECKLIST.md` ab â€” NUR die maschinell
erledigbaren Punkte (fehlende Tests, fehlende Verdrahtung, Replay-Nachweise).
Die authoritative Aktivierung selbst ist owner-gated und bleibt aus. Ziel:
Nach dieser Phase ist die Ignition ein Ein-Befehl-Start plus Owner-Stempel.

## Phase 5 â€” Forest-v2-Experiment (nur wenn 1â€“4 erschÃ¶pft)

Weiterarbeit ausschlieÃŸlich unter `experiments/forest_v2/` im deklarierten
Experiment-Rahmen (README dort: Hypothese, Budget, Expiry, no production
promotion). Lesen ja, verdrahten nein.

## Arbeitsdisziplin

- Serena-Memory `long_horizon_work_state` nach jedem kohÃ¤renten Slice pflegen.
- `WATCHDOG_STATUS.md` im Worktree-Root append-only fÃ¼hren (ein Absatz pro
  Slice, Commit-SHA + RAW-Testzeilen).
- Verifikation in Proportion zum Risiko; RAW-Ausgaben, keine Behauptungen.

## Watchdog completion protocol

This mission is supervised by a restart watchdog. Maintain Serena memory
long_horizon_work_state after every coherent slice and before exiting.

Only after the entire mission is implemented and verified, write a completion
report to: C:\Users\nukei\Desktop\gw_watchdog-mission3\.claude\watchdog\8a20da16-c4bc-467a-91aa-67045a44963b\MISSION_COMPLETE
If all useful work is blocked by something only the user can resolve, write the
blocker and required action to: C:\Users\nukei\Desktop\gw_watchdog-mission3\.claude\watchdog\8a20da16-c4bc-467a-91aa-67045a44963b\BLOCKED
Do not create either marker for an intermediate milestone, context compaction,
quota interruption, or temporary tool failure. Continue automatically after each
completed task.

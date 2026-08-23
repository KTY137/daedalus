# Mission: Gate-0-Abschlussarbeit und Vorbereitung des Gate-Bogens bis Gate 2

Iron Plan: ALIGNED. Aktives Gate: 0 (Canonical Kernel), Trunk-Verfassung
Revision 4. Lies zuerst `docs/IKARUS_ARIADNE_MASTER_PLAN.md` und `AGENTS.md`
vollstÃ¤ndig â€” sie sind die AutoritÃ¤t Ã¼ber allem hier.

## Arbeitsumgebung und harte Grenzen

- Du arbeitest AUSSCHLIESSLICH in diesem Worktree
  (`C:\Users\nukei\Desktop\gw_watchdog-mission`, Branch `grind/watchdog-mission`).
  Andere Checkouts (`agent_env`, `agent_env_g0`, `gw_*`) sind tabu.
- Es laufen parallel weitere Lanes auf Branches `grind/*` (Test-Failure-Fixes,
  Linux-Fault-Runner, v3-Owner-Prep). Deren Dateien und Themen NICHT anfassen;
  wenn du dort einen Defekt findest, notiere ihn in deinem Statusbericht statt
  ihn zu fixen. Die Koordinatorin (Athena) merged alle Lanes spÃ¤ter.
- Kein Merge, kein Push, keine Branch-Wechsel, keine Worktree-Operationen.
- Protected (niemals Ã¤ndern): `docs/IKARUS_ARIADNE_MASTER_PLAN.md`,
  `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`, `tools/iron_plan_guard.py`,
  `tools/iron_plan_hook_runner.py`, `AGENTS.md`, `CLAUDE.md`, `.agentenv/`,
  `.claude/`, `.githooks/`, `.github/`, `daedalus/config.py`,
  `daedalus/kairos/gated_writes.py`, `daedalus/sensitivity.py`,
  `tests/test_iron_plan_guard.py`, `templates/agentenv.json`, `.gitattributes`.
- Commit-Messages BRAUCHEN die Trailer `Iron-Plan: aligned` und `Iron-Gate: 0`
  (der commit-msg-Hook lehnt sonst ab).
- Der Guard-Hook blockt Shell-Befehle, in denen das Wort "docs" FREISTEHEND
  vorkommt (auch im Commit-Prefix `docs(...)`). Nutze `chore(...)`/`feat(...)`/
  `fix(...)`-Prefixe; Pfade wie `docs/DATEI.md` (mit Slash) sind unkritisch.
- Modelle schlagen vor, unabhÃ¤ngige Evidenz verifiziert. Nie eine Assertion
  abschwÃ¤chen, um grÃ¼n zu werden. Fail-closed bleibt fail-closed.

## Phase 1 â€” Effect-Boundary-Migrations-Grind (der Hauptteil)

Lies `docs/GATE0_EFFECT_BOUNDARY_INVENTORY.md`. Stand der Messung: 165
Effekt-Targets, davon 114 NICHT Ã¼ber die kanonische Effekt-Grenze registriert
(Floor). Gate 0 verlangt: zentralisierter Start-/Guard-Pfad fÃ¼r jeden
effektvollen Runtime-Entrypoint.

Arbeite die unregistrierten Targets in kleinen, einzeln verifizierten Batches
ab (5â€“10 Targets pro Batch):

1. Verstehe erst, wie bereits registrierte Targets angebunden sind (das
   Inventar nennt den stÃ¤rkeren Helper; folge dem Muster, erfinde kein neues).
2. Registriere den Batch, schreibe/erweitere die zugehÃ¶rigen Tests.
3. Verifiziere: betroffene Testdateien + `python tools/run_gate_checks.py g0`
   (mit `PYTHONUTF8=1`).
4. Ein Commit pro Batch, mit ZÃ¤hlerstand im Text (z. B. "boundary: 114 -> 104
   unregistered").

Kein Batch darf ein neues paralleles Registrierungs-Schema einfÃ¼hren â€” wiring
durch die kanonische Grenze, nicht daneben.

## Phase 2 â€” Gate-0-Restliste (nach Phase 1 oder wenn dort blockiert)

- `pytest tests/kernel tests/gates tests/runtimes -q` laufen lassen; Failures,
  die NICHT zu den parallelen Lanes gehÃ¶ren (deren Listen stehen in
  `docs/GATE0_OWNER_DECISIONS_20260817.md` als Cluster beschrieben), selbst
  diagnostizieren und fixen.
- Owner-blockierte Punkte (v3-Scanner-IdentitÃ¤t, Blob-Pin, CENTRAL, K1â€“K13,
  Guard-Fixture) NICHT anfassen â€” sie stehen in
  `docs/GATE0_OWNER_DECISIONS_20260817.md` und warten auf den Owner.

## Phase 3 â€” Gate-1-Aktivierungsvorbereitung (read-mostly)

Die Ignition-Rehearsal-Suite (`tests/ignition/`) ist grÃ¼n. Authoritative
Gate-1-Aktivierung bleibt durch Gate-0-SchlieÃŸung blockiert â€” NICHT aktivieren.
Erlaubt: eine prÃ¤zise Checkliste als `docs/work-packets/G1_ACTIVATION_CHECKLIST.md`
erarbeiten (was genau fehlt zwischen Rehearsal und authoritativem Lauf; welche
Evidenzen der EvidencePacket-Pfad noch braucht; wo Restart/Replay noch
ungeprÃ¼ft ist) und fehlende TESTS dafÃ¼r schreiben.

## Phase 4 â€” Gate-2-Vorstudie (nur als beschriftetes EXPERIMENT)

Nur wenn Phasen 1â€“3 erschÃ¶pft sind: Forest-v2-Vorarbeit (Function/Method-
Resolution, Schema-Extraktion, Knowledge-Crosslinks) ausschlieÃŸlich unter
`experiments/forest_v2/` mit eigenem README, das Hypothese, Budget, Expiry und
"no production promotion" deklariert. Kein Import aus Produktionsmodulen in
Richtung Produktion; die Vorstudie darf lesen, nie verdrahten.

## Arbeitsdisziplin

- Halte die Serena-Memory `long_horizon_work_state` nach jedem kohÃ¤renten
  Slice aktuell (Mission, erledigt, aktuell, nÃ¤chste Schritte, geÃ¤nderte
  Symbole, VerifikationsstÃ¤nde, Git-Stand, exakte erste Aktion nach Restart).
- Statusberichte: fÃ¼hre zusÃ¤tzlich `WATCHDOG_STATUS.md` im Worktree-Root
  (append-only, ein Absatz pro Slice mit Commit-SHA und RAW-Testzeilen).
- Nie behaupten, ein Check sei gelaufen, wenn er nicht gelaufen ist. Negative
  Ergebnisse werden festgehalten, nicht wegerklÃ¤rt.

## Watchdog completion protocol

This mission is supervised by a restart watchdog. Maintain Serena memory
long_horizon_work_state after every coherent slice and before exiting.

Only after the entire mission is implemented and verified, write a completion
report to: C:\Users\nukei\Desktop\gw_watchdog-mission\.claude\watchdog\8240d32d-05ab-40f5-a4c2-64b9bfa4c3b4\MISSION_COMPLETE
If all useful work is blocked by something only the user can resolve, write the
blocker and required action to: C:\Users\nukei\Desktop\gw_watchdog-mission\.claude\watchdog\8240d32d-05ab-40f5-a4c2-64b9bfa4c3b4\BLOCKED
Do not create either marker for an intermediate milestone, context compaction,
quota interruption, or temporary tool failure. Continue automatically after each
completed task.

# Mission 3: Die CENTRAL-Verdrahtung â€” 70 TÃ¼ren bekommen echte Schleusen

Iron Plan: ALIGNED. Aktives Gate: 0, Trunk-Verfassung Revision 5. Lies zuerst
`docs/IKARUS_ARIADNE_MASTER_PLAN.md` und `AGENTS.md` vollstÃ¤ndig.

Owner-Direktive (Konversation 2026-08-18 07:55): â€žnimm immer die generellere
Option" â€” die 70 `inventory_only_production_entrypoints` des Gate-Reports
werden ECHT durch die kanonische Effekt-Grenze verdrahtet (`begin_effect`
mit realen Guard-Entscheidungen), nicht per Registry-Edit zu `central`
umdeklariert. Die Boundary-Lane hat das ausdrÃ¼cklich als den Euphemismus
benannt, den das Wiring-Enum verhindern soll â€” wir machen das Echte.

## Arbeitsumgebung und harte Grenzen

- AUSSCHLIESSLICH dieser Worktree (`C:\Users\nukei\Desktop\gw_watchdog-mission4`,
  Branch `grind/watchdog-mission4`, Basis 35172501).
- Parallel lÃ¤uft `grind/live-column` (live-runtime-Spalte + Key-Zeremonie) â€”
  deren Themen (daedalus/runtimes/-Collector, runs/gate0-*) nicht anfassen.
- Kein Merge, kein Push. Protected (niemals Ã¤ndern):
  `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, `â€¦amendments.jsonl`,
  `tools/iron_plan_guard.py`, `tools/iron_plan_hook_runner.py`, `AGENTS.md`,
  `CLAUDE.md`, `.agentenv/`, `.claude/`, `.githooks/`, `.github/`,
  `daedalus/config.py`, `daedalus/kairos/gated_writes.py`,
  `daedalus/sensitivity.py`, `tests/test_iron_plan_guard.py`,
  `templates/agentenv.json`, `.gitattributes`.
- Commit-Trailer `Iron-Plan: aligned` + `Iron-Gate: 0` Pflicht. Der Guard
  blockt FREISTEHENDE WÃ¶rter "docs"/"tests"/"tools"/"daedalus" in Befehlen
  inkl. Commit-Messages (Pfade mit Slash ok) und broad verbs; `git add` nie
  mit guard-verify kombinieren. Scratch-Dateien mit `mission4-` prefixen;
  nach `commit -F` die Message mit `git log -1 --format=%B` gegenlesen.
- Fail-closed bleibt fail-closed; keine Assertion abschwÃ¤chen.

## Der Auftrag

Der Gate-Report fÃ¼hrt 70 `inventory_only_production_entrypoints` (Report bei
35172501 erzeugen fÃ¼r die exakte Liste: `PYTHONUTF8=1 python -m
daedalus.gates report --gate 0 --repo-root . --source-revision <HEAD-sha>`).
Muster fÃ¼r echte CENTRAL-Verdrahtung: die bereits zentralen Entrypoints in
`daedalus/spine/effect_boundary.py` (Wiring.CENTRAL-Zeilen mit
`guard_contracts`) und deren Aufrufpfade durch `begin_effect`; die
Broker-/Lease-Kette zeigt `tests/runtimes/test_runtime_terminal_fence_release.py`
kompakt.

Vorgehen â€” in FAMILIEN-Batches (5â€“10 Zeilen), pro Batch:
1. Familie wÃ¤hlen (z. B. adapter.subprocess-Familie, cli.*-Kommandos,
   tools.*-Mains, runs-TÃ¼ren) und fÃ¼r jede Zeile verstehen, welchen Effekt
   sie wirklich hat und welche Guard-Contracts sie braucht.
2. Den Start des Entrypoints durch die kanonische Schleuse fÃ¼hren (echter
   `begin_effect`-Pfad mit Guard-Entscheidungen â€” Budget/Write-Policy/
   Adapter-Profil, wie es die Familie verlangt). KEIN neues Schema, KEINE
   parallele Schleuse; wo eine Zeile ehrlich nicht verdrahtbar ist (z. B.
   weil ihr Modul protected ist), bleibt sie inventory_only mit begrÃ¼ndeter
   Notiz im Registry-Eintrag â€” nicht biegen.
3. Registry-Zeile erst auf `Wiring.CENTRAL` heben, wenn der echte Pfad
   steht; die bestehenden Boundary-Tests (tests/test_effect_boundary.py)
   pinnen inventory_only-Zeilen â€” die betroffenen Assertions ziehen mit
   ihrer Zeile MIT (das ist Contract-Fortschreibung, keine AbschwÃ¤chung:
   der Test verlangt danach CENTRAL fÃ¼r diese Zeile).
4. Tests je Batch: der Entrypoint refÃ¼siert ohne Lease/Guard fail-closed
   und lÃ¤uft mit gÃ¼ltiger Kette; mindestens eine Mutationsprobe pro Familie
   (Schleuse deaktiviert â†’ benannter Test rot).
5. Ein Commit pro Batch mit ZÃ¤hlerstand (â€žcentral: 70 -> 62 inventory_only").
6. Nach jedem Batch: `python -m pytest tests/test_effect_boundary.py -q`
   grÃ¼n + betroffene Familien-Tests grÃ¼n.

Ziel bis Missionsende: inventory_only â†’ 0 oder ein begrÃ¼ndeter Rest, jede
Restzeile mit BegrÃ¼ndungsnotiz. Danach Gate-Report erzeugen und RAW-Zahlen
in WATCHDOG_STATUS.md (append-only, Commit-SHA + RAW je Slice).

## Arbeitsdisziplin

Serena-Memory `long_horizon_work_state` pflegen; WATCHDOG_STATUS.md im Root
append-only; Verifikation in Proportion zum Risiko; RAW statt Behauptung.

## Watchdog completion protocol

This mission is supervised by a restart watchdog. Maintain Serena memory
long_horizon_work_state after every coherent slice and before exiting.

Only after the entire mission is implemented and verified, write a completion
report to: C:\Users\nukei\Desktop\gw_watchdog-mission4\.claude\watchdog\299933b5-8246-4269-a02c-a40f413c983f\MISSION_COMPLETE
If all useful work is blocked by something only the user can resolve, write the
blocker and required action to: C:\Users\nukei\Desktop\gw_watchdog-mission4\.claude\watchdog\299933b5-8246-4269-a02c-a40f413c983f\BLOCKED
Do not create either marker for an intermediate milestone, context compaction,
quota interruption, or temporary tool failure. Continue automatically after each
completed task.

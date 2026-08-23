# Mission 3: Die CENTRAL-Verdrahtung — 70 Türen bekommen echte Schleusen

Iron Plan: ALIGNED. Aktives Gate: 0, Trunk-Verfassung Revision 5. Lies zuerst
`docs/IKARUS_ARIADNE_MASTER_PLAN.md` und `AGENTS.md` vollständig.

Owner-Direktive (Konversation 2026-08-18 07:55): „nimm immer die generellere
Option" — die 70 `inventory_only_production_entrypoints` des Gate-Reports
werden ECHT durch die kanonische Effekt-Grenze verdrahtet (`begin_effect`
mit realen Guard-Entscheidungen), nicht per Registry-Edit zu `central`
umdeklariert. Die Boundary-Lane hat das ausdrücklich als den Euphemismus
benannt, den das Wiring-Enum verhindern soll — wir machen das Echte.

## Arbeitsumgebung und harte Grenzen

- AUSSCHLIESSLICH dieser Worktree (`C:\Users\nukei\Desktop\gw_watchdog-mission4`,
  Branch `grind/watchdog-mission4`, Basis 35172501).
- Parallel läuft `grind/live-column` (live-runtime-Spalte + Key-Zeremonie) —
  deren Themen (daedalus/runtimes/-Collector, runs/gate0-*) nicht anfassen.
- Kein Merge, kein Push. Protected (niemals ändern):
  `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, `…amendments.jsonl`,
  `tools/iron_plan_guard.py`, `tools/iron_plan_hook_runner.py`, `AGENTS.md`,
  `CLAUDE.md`, `.agentenv/`, `.claude/`, `.githooks/`, `.github/`,
  `daedalus/config.py`, `daedalus/kairos/gated_writes.py`,
  `daedalus/sensitivity.py`, `tests/test_iron_plan_guard.py`,
  `templates/agentenv.json`, `.gitattributes`.
- Commit-Trailer `Iron-Plan: aligned` + `Iron-Gate: 0` Pflicht. Der Guard
  blockt FREISTEHENDE Wörter "docs"/"tests"/"tools"/"daedalus" in Befehlen
  inkl. Commit-Messages (Pfade mit Slash ok) und broad verbs; `git add` nie
  mit guard-verify kombinieren. Scratch-Dateien mit `mission4-` prefixen;
  nach `commit -F` die Message mit `git log -1 --format=%B` gegenlesen.
- Fail-closed bleibt fail-closed; keine Assertion abschwächen.

## Der Auftrag

Der Gate-Report führt 70 `inventory_only_production_entrypoints` (Report bei
35172501 erzeugen für die exakte Liste: `PYTHONUTF8=1 python -m
daedalus.gates report --gate 0 --repo-root . --source-revision <HEAD-sha>`).
Muster für echte CENTRAL-Verdrahtung: die bereits zentralen Entrypoints in
`daedalus/spine/effect_boundary.py` (Wiring.CENTRAL-Zeilen mit
`guard_contracts`) und deren Aufrufpfade durch `begin_effect`; die
Broker-/Lease-Kette zeigt `tests/runtimes/test_runtime_terminal_fence_release.py`
kompakt.

Vorgehen — in FAMILIEN-Batches (5–10 Zeilen), pro Batch:
1. Familie wählen (z. B. adapter.subprocess-Familie, cli.*-Kommandos,
   tools.*-Mains, runs-Türen) und für jede Zeile verstehen, welchen Effekt
   sie wirklich hat und welche Guard-Contracts sie braucht.
2. Den Start des Entrypoints durch die kanonische Schleuse führen (echter
   `begin_effect`-Pfad mit Guard-Entscheidungen — Budget/Write-Policy/
   Adapter-Profil, wie es die Familie verlangt). KEIN neues Schema, KEINE
   parallele Schleuse; wo eine Zeile ehrlich nicht verdrahtbar ist (z. B.
   weil ihr Modul protected ist), bleibt sie inventory_only mit begründeter
   Notiz im Registry-Eintrag — nicht biegen.
3. Registry-Zeile erst auf `Wiring.CENTRAL` heben, wenn der echte Pfad
   steht; die bestehenden Boundary-Tests (tests/test_effect_boundary.py)
   pinnen inventory_only-Zeilen — die betroffenen Assertions ziehen mit
   ihrer Zeile MIT (das ist Contract-Fortschreibung, keine Abschwächung:
   der Test verlangt danach CENTRAL für diese Zeile).
4. Tests je Batch: der Entrypoint refüsiert ohne Lease/Guard fail-closed
   und läuft mit gültiger Kette; mindestens eine Mutationsprobe pro Familie
   (Schleuse deaktiviert → benannter Test rot).
5. Ein Commit pro Batch mit Zählerstand („central: 70 -> 62 inventory_only").
6. Nach jedem Batch: `python -m pytest tests/test_effect_boundary.py -q`
   grün + betroffene Familien-Tests grün.

Ziel bis Missionsende: inventory_only → 0 oder ein begründeter Rest, jede
Restzeile mit Begründungsnotiz. Danach Gate-Report erzeugen und RAW-Zahlen
in WATCHDOG_STATUS.md (append-only, Commit-SHA + RAW je Slice).

## Arbeitsdisziplin

Serena-Memory `long_horizon_work_state` pflegen; WATCHDOG_STATUS.md im Root
append-only; Verifikation in Proportion zum Risiko; RAW statt Behauptung.

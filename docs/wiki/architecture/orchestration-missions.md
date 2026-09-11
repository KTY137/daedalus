---
title: Orchestration Missions
type: module
status: living
updated: 2026-09-05
covers: daedalus/orchestration/missions
---
# Orchestration Missions

`daedalus/orchestration/missions` ist der **eine interne Einstiegspunkt fuer
eine zugelassene Build-Mission**. Im Kernel/Ikarus/Ariadne-Bild (Masterplan
Abschnitt 3 und 7) liegt das Paket bei Ikarus: es uebersetzt die vorhandene
`BuildSession`-Sicht in den kanonischen `MissionContract` und uebergibt die
Ausfuehrung an den bestehenden `WaveExecutor`. Es definiert bewusst **keinen**
eigenen Mission-, WorkItem-, Effect-, Attempt-, Evidence- oder Scheduler-Typ.
Der Executor bleibt alleiniger Besitzer von Scheduling, Effect Leases,
Attempt-Lebenszyklen und Evidence-Produktion; `run_mission` nimmt keinen
Callback und keinen Scheduler entgegen, damit ein Aufrufer die kanonische Kette
nicht durch eine parallele Implementierung ersetzen kann (Masterplan
Invariante 1, Abschnitt 13 gegen die parallele Control-Plane).

Gemessen 2026-09-05: 4 `.py`-Dateien, 766 Zeilen.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/orchestration/missions/__init__.py) | Exportiert genau eine Funktion: `run_mission`. | `run_mission` |
| [`service.py`](../../../daedalus/orchestration/missions/service.py) | Der Einstieg. Bindet WorkItems neu, prueft die `EffectBounds`-Bindung, baut den `MissionContract`, validiert optionale One-Shot-Subjekte, projiziert den Supervisor-Zustand und ruft `WaveExecutor.run`. | `run_mission` |
| [`one_shot.py`](../../../daedalus/orchestration/missions/one_shot.py) | Fail-closed Kompositionsnaht fuer bereits gebaute Ikarus-One-Shot-Subjekte. Prueft, dass fuenf exakte Subjekte genau ein Work Item benennen -- und verweigert danach, weil Gate 1 keinen zentral zugelassenen Konsumenten hat. | `OneShotEffectSubjects`, `validate_one_shot_effects` |
| [`supervisor_projection.py`](../../../daedalus/orchestration/missions/supervisor_projection.py) | Wegwerfbare Projektion des Missionszustands in das `StateLedger`-Verzeichnis eines `MissionSupervisor`. Konsultiert nie eine Role-Harness und startet nie einen `TaskAttempt`. | `begin_supervisor_projection`, `finish_supervisor_projection` |

### `run_mission` im Detail

Reihenfolge in [`service.py`](../../../daedalus/orchestration/missions/service.py):

1. Exakte Typpruefung (`type(session) is not BuildSession`, dito `WaveExecutor`
   und optionaler `MissionSupervisor`) -- Subklassen werden abgelehnt.
2. `session.bind_work_items()` leitet die WorkItem-Identitaeten neu ab; ein
   geaendertes Ziel, ein geaenderter Pfad oder ein anderer Owner faellt hier
   auf, bevor der Executor irgendetwas klassifizieren kann.
3. `_validate_effect_binding` verlangt, dass `executor.effect_bounds` -- wenn
   gesetzt -- exakt ein `EffectBounds` ist und in `mission_id`,
   `source_revision` und `trace_id` zur Mission passt.
4. `_mission_budget` spiegelt die konfigurierten Fallbacks des Lease-Ausstellers:
   `max_cost_microusd` aus `max_spend_usd` (0 wenn unkonfiguriert),
   `max_wall_time_s` aus `timeout_s` (3600 als Default).
5. `mission_contract_for_build_session` aus
   [`daedalus/spine/receipts.py`](../../../daedalus/spine/receipts.py) baut den
   Vertrag inklusive der `execution_limit_policy` des Executors.
6. Optional: `validate_one_shot_effects` -- vor jedem Projektionsschreibvorgang
   und vor jeder Wave.
7. Optional: `begin_supervisor_projection`, danach `executor.run(...)`, danach
   `finish_supervisor_projection`. Projektionsfehler landen ueber
   `_projection_error` in `supervisor.projection_errors` und ersetzen das
   kanonische Ergebnis **nicht**.
8. Rueckgabe `(MissionContract, BuildRunReport)`; ein `BuildRunReport` mit
   abweichender `mission_id` ist ein `ValueError`.

### Die One-Shot-Naht

`validate_one_shot_effects` verlangt pro Work Item ein exaktes Fuenf-Tupel:
`OneShotRequest`, `OneShotRuntimeEvidenceBinding`, `IkarusToolScopeProjection`,
`EffectLeaseRequest`, `EffectExecutionRequest` (siehe
[Orchestration Ikarus](orchestration-ikarus.md)). Geprueft wird, dass alle fuenf
dieselbe Mission, dasselbe Work Item, dieselbe Runtime-Identitaet und dieselben
Digests benennen, dass jede Budgetachse durch das Missionsbudget nach oben
begrenzt ist, dass kein `operation_sha256` gesetzt ist, und dass sich
`EffectLeaseRequest` und `EffectExecutionRequest` byte-genau aus
`build_oneshot_effect_lease_request` bzw.
`build_oneshot_effect_execution_request` rekonstruieren lassen. Danach muss der
`entrypoint_id` in `REGISTRY_BY_ID` stehen und `Wiring.CENTRAL` sein.

Am Ende steht unbedingt ein `OneShotRuntimeRefused` mit der Begruendung, dass
kein zentral zugelassener One-Shot-Konsument des `WaveExecutor` installiert
ist. Die Funktion kann in dieser Revision also **nie** erfolgreich
zurueckkehren; sie ist ein vollstaendig geprueftes, aber nicht angeschlossenes
Kontrakt-Gerippe.

### Die Supervisor-Projektion

`begin_supervisor_projection` schreibt vor der Ausfuehrung eine
`planned`-Revision, `finish_supervisor_projection` danach eine Revision mit dem
tatsaechlichen Ergebnis. Beide sind idempotent gegen Absturz-Replay: eine
terminale Revision (`landed`, `bounced`, `refused`) faellt nie auf `planned`
zurueck. `_mission_file` publiziert `<run_dir>/mission.json` genau einmal ueber
`publish_bytes_once`; ein zweiter Lauf mit abweichendem `created_at`, aber
sonst identischer Substanz (`_projection_identity` entfernt genau dieses Feld)
wird akzeptiert, jede andere Abweichung ist `SupervisorRefused`.

`_result_rows` liest die `WaveResult`-Eintraege des `BuildRunReport` und
verlangt fuer jedes Ergebnis einen kanonischen Work-Item-Stempel mit passender
`mission_id`; fehlende oder doppelte Identitaeten sind `SupervisorRefused`.

## Trust-Grenzen / Effekte

* **Kein Registry-Eintrag, kein `begin_effect`.** Dieses Paket ist keine Tuer.
  Effekte entstehen im `WaveExecutor` und in den `python.attempt`-Tueren, die
  er startet; siehe [Spine](spine.md).
* **Writer:** Die einzigen Schreibvorgaenge sind Projektionen unter dem vom
  Aufrufer gelieferten `run_dir` des Supervisors: `<run_dir>/mission.json` (via
  `publish_bytes_once` aus [`daedalus/atomic.py`](../../../daedalus/atomic.py))
  und die `StateLedger`-Revisionen. Beide sind Ansichten, keine Fakten --
  Loeschen des Verzeichnisses verliert nichts Autoritatives.
* **Kein Ersatz des Ergebnisses.** `_projection_error` faengt jede Ausnahme aus
  der Projektion ab; ein kaputter Supervisor kann den kanonischen
  `BuildRunReport` weder unterdruecken noch herabstufen.
* **Fail-closed One-Shot.** Solange kein zentral zugelassener Konsument
  existiert, verweigert `validate_one_shot_effects` -- *nach* vollstaendiger
  Pruefung, damit ein spaeteres Paket nur den Konsumenten ergaenzen muss.
* **Keine Promotion.** Nichts hier importiert `daedalus.kernel.promotion`.

## Tests

| Testdatei | Deckt ab |
| --- | --- |
| [`tests/orchestration/test_run_mission.py`](../../../tests/orchestration/test_run_mission.py) | `run_mission`: Typpruefungen, Budget-Spiegelung, Effect-Bounds-Bindung, Report-Identitaet. |
| [`tests/orchestration/test_ikarus_mission_integration.py`](../../../tests/orchestration/test_ikarus_mission_integration.py) | Zusammenspiel von Supervisor-Projektion, Session und Mission. |
| [`tests/test_ikarus_effect_bridge.py`](../../../tests/test_ikarus_effect_bridge.py) | Die Lease- und Execution-Projektionen, die `one_shot.py` rekonstruiert. |
| [`tests/test_ikarus_supervisor.py`](../../../tests/test_ikarus_supervisor.py) | `MissionSupervisor` und `StateLedger`, die Traeger der Projektion. |
| [`tests/interfaces/test_bridge_dispatch_strangler.py`](../../../tests/interfaces/test_bridge_dispatch_strangler.py) | Der File-Bridge-Aufrufer von `run_mission`. |

## Verwandt

* [Orchestration](orchestration.md) -- das umgebende Paket und der `WaveExecutor`.
* [Orchestration Ikarus](orchestration-ikarus.md) -- Herkunft von
  `MissionSupervisor`, `StateLedger` und den One-Shot-Subjekten.
* [Orchestration Execution](orchestration-execution.md) -- die Ports, an denen
  die Attempts komponiert werden.
* [Orchestration Genesis](orchestration-genesis.md) -- der zweite Missionstyp
  aus Masterplan Abschnitt 7.1.
* [Kernel Contracts](kernel-contracts.md) -- `MissionContract`,
  `EffectLeaseRequest`, `ResourceBudget`.
* [Spine](spine.md) -- Effekt-Registry und `mission_contract_for_build_session`.
* [Ignition](ignition.md) -- die Gate-1-Slice, die dieselbe Kette als Fixture
  vorgefuehrt hat.
* [Wiki-Index](../index.md)

## Ungeklaert

* **Ungeklaert:** Wann und durch welches Work Packet der zentral zugelassene
  One-Shot-Konsument kommen soll. Der Docstring sagt nur "a future packet".
* **Ungeklaert:** Ob `run_mission` ausserhalb der File-Bridge und der Tests
  produktive Aufrufer hat.

---
title: Orchestration Execution
type: module
status: living
updated: 2026-09-05
covers: daedalus/orchestration/execution
---
# Orchestration Execution

`daedalus/orchestration/execution` ist die **Kompositionsschicht** zwischen dem
kanonischen Kernel und den konkreten Implementierungen, die ein Attempt braucht:
Workspace (Git-Worktree), Evaluator (Gates), Offload-Workload. Im
Kernel/Ikarus/Ariadne-Bild (Masterplan Abschnitt 3 und 4) gehoert das Paket zu
Ikarus/Orchestrierung, nicht zum Kernel: es definiert keinen Vertrag, keinen
Effekt und keine Policy, sondern bindet vorhandene Implementierungen an die
neutralen Ports, die der kernel-eigene Attempt-Lebenszyklus konsumiert. Die
Richtungsumkehr ist der Punkt -- der Kernel importiert keine Workload mehr,
sondern *nimmt* sie als Capability entgegen. Jeder Aufruf erzeugt frische
Adapter; es gibt keine prozessweite mutable Registry und keinen impliziten
Kernel-Default.

Gemessen 2026-09-05: 3 `.py`-Dateien, 281 Zeilen.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/orchestration/execution/__init__.py) | Re-Export der Kompositionsfunktionen; `__all__` haelt die Menge klein und explizit. | `__all__` |
| [`attempts.py`](../../../daedalus/orchestration/execution/attempts.py) | Bindet Workspace-, Evaluator- und Offload-Implementierung an die Attempt-Tueren aus `daedalus.spine.attempt` und reicht sie als explizite Capabilities weiter. | `AttemptEvaluatorAdapter`, `attempt_workspace_port`, `attempt_evaluator_port`, `attempt_ports`, `compose_task_attempt`, `run_attempt`, `command_gate`, `pytest_gate`, `remove_gate_tmpdir`, `offload_port` |
| [`evaluation.py`](../../../daedalus/orchestration/execution/evaluation.py) | Bindet `load_baseline` und `run_gate` aus `daedalus.eval.harness` an die neutralen `EvaluationPorts` fuer einen CLI-Aufruf. | `picker_evaluation_ports` |

### Was genau komponiert wird

* `attempt_workspace_port` erzeugt einen `GitWorktreeManager` aus
  [`daedalus/kairos/worktree.py`](../../../daedalus/kairos/worktree.py) mit
  aufgeloestem Repository-Root; ohne Argument faellt es auf
  `daedalus.kernel.attempt_execution.ROOT` zurueck.
* `AttemptEvaluatorAdapter` stellt drei Gate-Fabriken bereit: `command_gate`,
  `correctness_gate` (aus `daedalus.eval.correctness`) und `pytest_gate`. Die
  Evaluator-Autoritaet bleibt bei ihren bisherigen Besitzern; hier wird nur
  gebunden.
* `command_gate`, `pytest_gate` und `remove_gate_tmpdir` reichen zusaetzlich
  `remove_tree_no_follow` als `scratch_cleanup` durch -- der gehaertete
  Verzeichnis-Walker, der Symlinks nicht folgt.
* `compose_task_attempt` und `run_attempt` sind duenne Huellen um die
  registrierten Ziele in `daedalus.spine.attempt`; `_composed_kwargs` fuellt nur
  dann Ports auf, wenn der Aufrufer keine uebergeben hat.
* `offload_port` gibt die `OffloadCapability` der Workload selbst zurueck, nicht
  einen hier definierten Forwarder. Der Docstring nennt zwei Gruende: spaete
  Bindung (Monkeypatch auf `daedalus.offload.offload` bleibt wirksam) und die
  Effekt-Ableitung, die jede lokale Klasse mit `run_offload` als Implementierung
  von `OffloadPort` aufloest -- ein zweiter Forwarder wuerde die abgeleitete
  Effektmenge zweier Tueren verbreitern statt sie zu beschreiben.

## Trust-Grenzen / Effekte

Dieses Paket ist **selbst kein Effektpunkt**. Es enthaelt kein `begin_effect`,
keinen Registry-Eintrag und keinen Writer. Was es tut, ist Autoritaet
*weiterreichen*:

* Der Effekt entsteht erst in der registrierten Tuer `python.attempt`
  (`daedalus.spine.attempt`), die Lease, Containment und Write-Fence
  durchsetzt -- siehe [Spine](spine.md) und [Kernel](kernel.md).
* Die Gates fuehren Kandidaten-Code aus (`executes_candidate=True` als Default
  bei `command_gate`/`pytest_gate`); die Isolation dafuer liegt beim
  Attempt-Pfad, nicht hier.
* `remove_gate_tmpdir` loescht Scratch-Verzeichnisse ausschliesslich ueber den
  Kairos-Walker; `shutil.rmtree` kommt in diesem Paket nicht vor.
* Der Evaluator bleibt vom Kandidaten getrennt (Masterplan Invariante 3 und 4):
  `AttemptEvaluatorAdapter` konstruiert die Gate-Callables ausserhalb des
  Kandidatenbaums.

## Tests

| Testdatei | Deckt ab |
| --- | --- |
| [`tests/orchestration/test_attempt_composition_hierarchy.py`](../../../tests/orchestration/test_attempt_composition_hierarchy.py) | Die Kompositionsrichtung: Orchestrierung darf Workload nennen, der Kernel nicht. |
| [`tests/kernel/test_attempt_execution_hierarchy.py`](../../../tests/kernel/test_attempt_execution_hierarchy.py) | Der Kernel-seitige Gegentest zur selben Grenze. |
| [`tests/kernel/test_evaluation_port_boundary.py`](../../../tests/kernel/test_evaluation_port_boundary.py) | `picker_evaluation_ports` und die `EvaluationPorts`-Grenze. |
| [`tests/contracts/test_uncomposed_gate_callers.py`](../../../tests/contracts/test_uncomposed_gate_callers.py) | Aufrufer, die ein Gate ohne Komposition bauen. |
| [`tests/contracts/test_import_scc_hierarchy.py`](../../../tests/contracts/test_import_scc_hierarchy.py) | Import-Zyklen und Schichtordnung. |
| [`tests/test_spine_attempt.py`](../../../tests/test_spine_attempt.py), [`tests/test_attempt_boundary.py`](../../../tests/test_attempt_boundary.py), [`tests/test_attempt_undeclared_scope.py`](../../../tests/test_attempt_undeclared_scope.py) | Die Attempt-Tuer, an die hier komponiert wird. |
| [`tests/kernel/test_attempt_lease.py`](../../../tests/kernel/test_attempt_lease.py) | Lease-Erwerb im komponierten Attempt. |
| [`tests/test_gate_containment.py`](../../../tests/test_gate_containment.py), [`tests/test_containment_scope.py`](../../../tests/test_containment_scope.py) | Containment der Gate-Kinder. |

## Verwandt

* [Orchestration](orchestration.md) -- das umgebende Paket.
* [Orchestration Missions](orchestration-missions.md) -- der Missions-Einstieg,
  der denselben kanonischen Ausfuehrungspfad benutzt.
* [Kernel](kernel.md) und [Kernel Contracts](kernel-contracts.md) -- Besitzer
  von `AttemptWorkspacePort`, `AttemptEvaluatorPort`, `OffloadPort` und
  `EvaluationPorts`.
* [Spine](spine.md) -- die registrierte Attempt-Tuer und die Effektgrenze.
* [Kairos](kairos.md) -- Worktree-Manager und Scratch-Walker.
* [Eval](eval.md) -- Baseline, Correctness-Gate und Harness.
* [Wiki-Index](../index.md)

## Ungeklaert

* **Ungeklaert:** Ob `attempt_ports` ausserhalb der Tests produktiv benutzt
  wird; die Aufrufer im Baum verwenden ueberwiegend `compose_task_attempt` oder
  `run_attempt` direkt.
* **Ungeklaert:** Die zweite Stelle, die `offload_port` komponiert. Der
  Docstring spricht von "einer der beiden Stellen", nennt die andere aber nicht.

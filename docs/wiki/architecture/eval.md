---
title: Eval
type: module
status: living
updated: 2026-09-05
covers: daedalus/eval
---
# Eval

`daedalus/eval` ist die private, evidenzbewusste Distillations- und
Korrektheits-Evaluation dieses Repositories. Dreizehn `.py`-Dateien, 6655
Zeilen (gemessen 2026-09-05), plus drei Datenartefakte im selben Verzeichnis
(`baseline.json`, `correctness_tasks.json`, `minted_tasks.json`) und ein
Fixture-Repo unter `fixtures/`. Im Kernel/Ikarus/Ariadne-Bild ist das die
Evidenzgrenze aus Masterplan Invariante 4: Modelle schlagen vor, hier wird
deterministisch oder unabhaengig kontrolliert entschieden. Das Paket beschreibt
sich selbst ausdruecklich als **private direktionale Evaluation, nicht als
SWE-bench** -- diese Formulierung steht im Paket-Docstring und als Kopfzeile
jedes gerenderten Berichts.

Der rote Faden des Pakets ist Ehrlichkeit ueber die Herkunft eines Labels. Ein
`must_include`-Label, das ein Mensch ausgesucht **und** durch Ausfuehren
desselben Slicers verifiziert hat, ist zirkulaer; ein Label, das aus einem
Byte-Diff stammt, ist es nicht. Deshalb wird nie ueber Provenienzen hinweg
gemittelt.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/eval/__init__.py) | Paketfassade. Reicht `TASKS`, `resolve_task_repo`, `harness`, `report`, `tier2` durch und definiert `run_tier1`/`run_tier2` als duenne Weiterleitungen. | `TASKS`, `resolve_task_repo`, `run_tier1`, `run_tier2` |
| [`__main__.py`](../../../daedalus/eval/__main__.py) | Der CLI-Einstieg `python -m daedalus.eval`. Tier 1 laeuft immer; `--arms` ergaenzt den A/B/C-Vergleich, `--tier2` verlangt einen erreichbaren Provider. `--mint-commit` und `--confirm-mint` sind die **einzigen** Einstiege, die in den Mint-Store schreiben. Ausgabe ist bewusst ASCII-only. | `main`, `_select`, `_print_ascii` |
| [`tasks.py`](../../../daedalus/eval/tasks.py) | Der beschriftete Aufgabensatz plus die beiden Aufgabenformate. Enthaelt die Provenienz-Definitionen und die Trennung zwischen Slicer- und Korrektheits-Aufgaben. | `TASKS`, `resolve_task_repo`, `is_correctness_task`, `task_project_label`, `AGENT_ENV_ROOT`, `SUNNY_GARDEN_FIXTURE` |
| [`harness.py`](../../../daedalus/eval/harness.py) | Tier 1 und die deterministischen Arme A/B/C. Misst Recall und Kompression je Provenienz-Tier und vergleicht den distillierten Slice gegen Ganz-Repo-Konkatenation und eine BM25-Top-k-Abfrage. Enthaelt ausserdem das beratende Gate gegen `baseline.json`. | `run_tier1`, `run_arms`, `run_gate`, `all_tasks`, `eval_task_tier1`, `eval_task_arms`, `load_baseline`, `snapshot_baseline`, `write_baseline`, `detect_provider`, `DEFAULT_BASELINE_PATH` |
| [`report.py`](../../../daedalus/eval/report.py) | ASCII-Tabellen, cp1252-sicher: nur Plus, Minus und der senkrechte Strich, keine Unicode-Rahmen. Druckt zu jedem `hand_reachable`-Bucket den Provenienz-Hinweis, der die Zahl einordnet. | `render`, `render_tier1`, `render_arms`, `render_tier2`, `render_gate`, `HEADER` |
| [`tier2.py`](../../../daedalus/eval/tier2.py) | Die einzige Spur, die generierten Text bewertet -- und deshalb fail-closed. Trennt Provider-Ausfuehrung, lexikalische Abdeckung, semantische Validierung und Audit-Evidenz, statt "erwartetes Token erschien" als Erfolg zu lesen. | `run_tier2`, `render_tier2`, `builtin_validator_coverage` |
| [`_text_integrity.py`](../../../daedalus/eval/_text_integrity.py) | Zwei enge fail-closed-Waechter fuer Tier 2: ein erwartetes Token gilt nur als behauptet, wenn kein Vorkommen negiert, relativiert, gefragt oder spaeter widerlegt wird; Terminal-Metadaten werden auf eine begrenzte, druckbare ASCII-Zeile gerendert, waehrend die aufbewahrten Ergebnis-Dicts die Originalzeichenketten behalten. | `expected_asserted`, `safe_ascii_field` |
| [`correctness.py`](../../../daedalus/eval/correctness.py) | Groesste Datei (1841 Zeilen): der FAIL_TO_PASS/PASS_TO_PASS-Evaluator im SWE-bench-Muster, gebaut aus dem eigenen pytest, dem eigenen Git und dem gehaerteten Worktree-Manager. | `evaluate_change`, `correctness_gate`, `judge_before_state`, `judge_after_state`, `run_node_ids`, `parse_pytest_output`, `pytest_node_argv`, `freeze_selection`, `Selection`, `BeforeState`, `CorrectnessResult`, `PytestRun`, `disposable_worktree`, `apply_patch`, `apply_test_overlay`, `reference_patch`, `derive_task_from_commit`, `seed_task_from_commit`, `run_corpus`, `resolve_revision`, `validate_task`, `PrimaryCheckoutTouch`, `OverlayEscape`, `DEFAULT_CORPUS_PATH` |
| [`mint.py`](../../../daedalus/eval/mint.py) | Praegt `must_include`-Labels aus einer Quelle, die keine Meinung zum Importgraphen hat: einem byte-genauen Diff einer gelandeten Offload-Bearbeitung oder eines echten Git-Commits. | `mint_from_commit`, `mint_task_from_landed_edit`, `confirm_task`, `confirm_minted_task`, `add_minted_task`, `load_minted_tasks`, `save_minted_tasks`, `DEFAULT_MINT_STORE_PATH` |
| [`mutate.py`](../../../daedalus/eval/mutate.py) | Mechanischer, unvoreingenommener Defektkorpus fuer die Validierung auf zurueckgehaltenen Daten. AST-Operatoren auf echten Funktionen dieses Repositories, beliebig viele, ohne Marker-Kommentar, deterministisch ueber einen Seed. | `generate`, `covered_lines`, `trivially_equivalent`, `Mutant` |
| [`graph_delta.py`](../../../daedalus/eval/graph_delta.py) | Misst, ob das Delta im mehrschichtigen Graphen ein Signal ueber einen Patch traegt, das die Testsuite nicht hat -- verfuegbar **bevor** die Tests laufen. | `measure`, `run`, `render`, `held_out`, `specificity`, `measure_commit`, `commit_shas`, `function_deltas`, `load_mutations`, `DeltaResult`, `LayerDelta`, `DELTA_VERSION` |
| [`ceiling.py`](../../../daedalus/eval/ceiling.py) | Misst die **Obergrenze** der temporalen Co-Change-Hypothese, bevor irgendeine Slice-Anreicherung gebaut wird: ist eine verfehlte Label-Quelle ueberhaupt ein Co-Change-Partner der Fokusdatei? | `temporal_ceiling`, `render_ceiling`, `main`, `CLASSES`, `REOPEN_MIN_SHARE`, `REOPEN_MIN_TASKS` |
| [`provenance.py`](../../../daedalus/eval/provenance.py) | Prueft, ob der Evaluator wirklich den Code des Kandidaten bewertet hat -- nicht den Host gegen sich selbst. | `check_import_provenance`, `ProvenanceCheck` |

## Die beiden Aufgabenformate

**Slicer-Aufgaben** tragen `must_include` und werden per Teilzeichenketten-
Enthaltensein gegen den distillierten Slice gewertet. Ihre Provenienz ist eine
von drei:

- `hand_reachable` -- zirkulaer: der Slicer hat mitbestimmt, woran er gemessen
  wird. Als Obergrenze und Plausibilitaetspruefung brauchbar, nie als Beweis.
- `independent_diff` -- aus dem, was ein Diff woertlich geaendert hat, ohne
  Graphlauf.
- `temporal_churn` -- aus Git-Co-Change, also aus Kanten, die der statische
  Importgraph nicht hat.

`tier` trennt `primary` von `quarantine`: frisch gepraegte Aufgaben landen in
Quarantaene und zaehlen erst nach `confirm_task` in eine Kennzahl.
`run_tier1` schliesst sie aus jeder Kopfzahl aus und berichtet sie getrennt,
damit das Label-Schwungrad (praegen, quarantaenisieren, bestaetigen,
uebernehmen) sichtbar bleibt.

**Korrektheitsaufgaben** tragen `base_revision`, `test_overlay`,
`fail_to_pass` und `pass_to_pass` und bewerten die **Aenderung**. Die beiden
Formate duerfen nicht in einem Korpus gemischt werden, und das wird erzwungen,
nicht erbeten: eine Korrektheitsaufgabe hat kein `must_include`, ihr Recall
waere die inhaltsleere 1.0 -- eine Aufgabe, die nicht fehlschlagen kann.
`is_correctness_task` ist das einzige Praedikat, das entscheidet, und
`eval_task_tier1` verweigert eine solche Aufgabe laut als Fehlerzeile.

### Mitgelieferte Fixtures

`daedalus/eval/fixtures/` ist der eingebaute `sunny_garden`-Korpus fuer
deterministische Slice-Recall-Tests (`tasks.py` zeigt mit dem Repo-Label
`sunny_garden` dorthin). Drei winzige Module, absichtlich trivial, damit die
Aufgaben ohne fremdes Repository laufen:

| Datei | Zweck | Symbole |
| --- | --- | --- |
| [fixtures/__init__.py](../../../daedalus/eval/fixtures/__init__.py), [sunny_garden/__init__.py](../../../daedalus/eval/fixtures/sunny_garden/__init__.py), [garden/__init__.py](../../../daedalus/eval/fixtures/sunny_garden/garden/__init__.py) | Paketmarker mit je einem Docstring-Satz. | -- |
| [garden/plants.py](../../../daedalus/eval/fixtures/sunny_garden/garden/plants.py) | Giessintervalle je Pflanze. | `PLANTS` |
| [garden/care.py](../../../daedalus/eval/fixtures/sunny_garden/garden/care.py) | Entscheidet aus `PLANTS` und dem letzten Giessdatum, was heute Wasser braucht. | `needs_water`, `watering_plan` |
| [garden/cli.py](../../../daedalus/eval/fixtures/sunny_garden/garden/cli.py) | Druckt den Giessplan. | `main` |

## Trust-Grenzen / Effekte

- **Schreibende Pfade sind eng und explizit.** In den Mint-Store schreiben nur
  `add_minted_task`/`save_minted_tasks`, aufgerufen ausschliesslich ueber
  `--mint-commit` bzw. `--confirm-mint`. `baseline.json` schreibt nur
  `write_baseline`, und nur bei explizitem `--update-baseline`. Der
  Korrektheitskorpus wird von `save_correctness_tasks` geschrieben.
- **Prozess-Effekte.** `correctness.py` spawnt pytest (`_spawn_pytest`) und
  Git (`_git_read`, `_git_in_worktree`), `graph_delta`, `mutate` und `ceiling`
  lesen Git-Historie. Die Ausfuehrung findet in einem
  `disposable_worktree` statt.
- **Der Primaer-Checkout ist tabu.** `_refuse_primary_checkout` und
  `PrimaryCheckoutTouch` verweigern jeden Schreibversuch am Haupt-Checkout,
  `_safe_join` und `OverlayEscape` verweigern ein Test-Overlay, das aus dem
  Worktree ausbricht.
- **Der Evaluator muss den Kandidaten sehen.** `provenance.py` existiert, weil
  ein frueherer Runner ein blankes `pytest` aufrief und damit den Host gegen
  sich selbst benotete -- die editierbare Installation pinnt `daedalus` per
  absolutem Pfad auf den Primaer-Checkout, sodass die Bearbeitungen des
  Kandidaten fuer seine eigenen Tests unsichtbar waren. Der heutige Runner
  benutzt `sys.executable -m pytest` mit `cwd` im Worktree. Das ist ein
  *Mechanismus*, keine *Verifikation* -- deshalb prueft
  `check_import_provenance` das Argument bei jedem Lauf nach.
- **Das Gate ist beratend.** `run_gate` ist ausdruecklich eine lokale
  Regressionspruefung gegen `baseline.json` und in nichts Automatisches
  verdrahtet. Ein LLM-Urteil ist hier nie ein hartes Korrektheits- oder
  Promotionsgate (Masterplan Abschnitt 13).
- **Tier 2 ist die einzige Modellspur** und faellt fail-closed: Transportfehler,
  abgeschnittene Ausgaben und fehlende Validatoren duerfen nicht wie eine
  gewoehnlich falsche Modellantwort aussehen.

## Gemessenes, das im Code steht

- Der Grund fuer `correctness.py`: die Rueckweisungsquote des eingefrorenen
  Gates gegen die drei bekannt-schlechten Aenderungen eines einzigen Tages
  wurde mit **0/3** gemessen; drei gruene Suiten sassen ueber drei
  Live-Ausbruechen, und ein A/B-Experiment ging mit zwei bestandenen Armen
  durch ein Gate, das keine Tests ausfuehrte.
- Der Grund fuer `mutate.py`: `graph_delta` erreichte 12/12 auf dem
  handgeschriebenen Korpus in `tools/gate_discrimination.py` -- aber erst,
  nachdem zwei Schichten genau fuer die dort verfehlten Defekte ergaenzt und
  dann an denselben zwoelf validiert wurden. Eine Erkennungsrate, gemessen an
  den Beispielen, die sie motiviert haben, ist kein Beleg.
- Der Grund fuer `ceiling.py`: die Zahl waere eine Tautologie, wenn der
  Mint-Commit selbst mitgezaehlt wuerde -- er hat Fokus und Label-Quellen ja
  gemeinsam geaendert. Der saubere Arm rechnet deshalb ueber die Historie
  strikt **vor** `minted_at_sha`; der undichte Arm wird absichtlich daneben
  berechnet, damit die Luecke zwischen beiden die Groesse der Leckage nennt.
- Die Regel in `mint.py`, die nicht verhandelbar ist: ein gepraegtes
  `must_include` darf **nie** durch den Importgraphen erweitert werden, auch
  nicht um einen einzigen Hop. In dem Moment, in dem ein Label ueber denselben
  Graphen erreichbar ist, den der Slicer laeuft, hoert es auf, unabhaengig zu
  sein.

## Tests

- [`tests/test_eval.py`](../../../tests/test_eval.py) -- Tier 1, Arme, Gate
- [`tests/test_eval_correctness.py`](../../../tests/test_eval_correctness.py) und [`tests/test_eval_oracle.py`](../../../tests/test_eval_oracle.py)
- [`tests/test_eval_mint.py`](../../../tests/test_eval_mint.py) und [`tests/test_mint_label_hygiene.py`](../../../tests/test_mint_label_hygiene.py)
- [`tests/test_eval_provenance.py`](../../../tests/test_eval_provenance.py)
- [`tests/test_eval_tier2_integrity.py`](../../../tests/test_eval_tier2_integrity.py) und [`tests/test_eval_tier2_text_evidence_nemesis.py`](../../../tests/test_eval_tier2_text_evidence_nemesis.py)
- [`tests/test_graph_delta.py`](../../../tests/test_graph_delta.py)
- [`tests/test_temporal_ceiling.py`](../../../tests/test_temporal_ceiling.py)
- [`tests/test_offload_automint.py`](../../../tests/test_offload_automint.py)
- [`tests/test_benchmark_authority.py`](../../../tests/test_benchmark_authority.py)
- [`tests/kernel/test_evaluation_port_boundary.py`](../../../tests/kernel/test_evaluation_port_boundary.py)
- [`tests/test_loop_terminal_rendering.py`](../../../tests/test_loop_terminal_rendering.py)
- [`tests/test_worktree_properties.py`](../../../tests/test_worktree_properties.py)

## Verwandt

- [Gates](gates.md) -- der Gate-Bericht, in den diese Evidenz einfliesst
- [Ariadne](ariadne.md) -- die Kampagnenschicht, die dieselbe Evidenzgrenze respektiert
- [Structcore](structcore.md) -- der Slicer, der hier benotet wird
- [Twin](twin.md) und [Type-Graph](type-graph.md) -- die Ebenen, deren Delta `graph_delta.py` misst
- [Graph delta as fitness](../graph-delta-as-fitness.md) -- die Messung vom 30. Juli, aus der `graph_delta.py` entstanden ist
- [Spine](spine.md) -- Worktree-Manager, Attempt-Tueren, Gate-Diskriminierung
- [Tools](../tooling/tools.md) -- `tools/gate_discrimination.py` und `tools/mutation_score.py` sind die Werkzeugseite derselben Frage
- [Forest v2, Slice s09 (Eval)](../experiments/forest-v2-s09-eval.md) -- die Experimentseite zur Evaluationsfrage
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** ob es heute einen automatischen Aufrufer fuer das Minten
  gibt. Der Docstring von `__main__.py` sagt ausdruecklich, dass es keinen gibt
  ("offload.py does not invoke this today"), waehrend
  `tests/test_offload_automint.py` existiert -- welcher Zustand aktuell ist,
  war aus dem Paket allein nicht zu entscheiden.
- **Ungeklaert:** wie `graph_delta.load_mutations` und die Mutationen aus
  `tools/gate_discrimination.py` heute zusammenhaengen; das Modul liest den
  Korpus, ohne den Erzeuger zu benennen.
- **Ungeklaert:** ob `harness.run_tier2` und `tier2.run_tier2` noch
  unterschiedliche Verhalten haben. `harness` traegt weiterhin eigene
  `_ask`/`_score`-Helfer, `tier2` importiert `harness` als `_legacy`.
- **Ungeklaert:** ob `ceiling.REOPEN_MIN_SHARE`/`REOPEN_MIN_TASKS` je einen
  Track wieder eroeffnet haben oder nur als Schwelle dokumentiert sind.

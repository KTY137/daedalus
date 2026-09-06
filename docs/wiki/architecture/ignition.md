---
title: Ignition
type: module
status: living
updated: 2026-09-05
covers: daedalus/ignition
---
# Ignition

`daedalus/ignition` ist die **Gate-1-Zuendungs-Slice** aus Masterplan
Abschnitt 11: `Event.voltage` -> `bias_voltage` ueber Python, Markdown und CSV
propagieren, mit **einem** `MissionContract`, **zwei** typisierten WorkItems aus
den vier Ebenen, isolierten Attempts, Restart/Replay, drei Checks, **einem**
`EvidencePacket` -- und keiner Promotion. Im Kernel/Ikarus/Ariadne-Bild ist das
Paket ein Renovation-Workload: es mintet keinen eigenen Vertrag, keinen Store,
kein Ledger und keinen Promotionspfad, sondern besitzt genau die **Reihenfolge**
und die Quittung, die sie festhaelt.

Das Fixture-Projekt ist immer eine vorbereitete Kopie
(`tests/fixtures/ignition/voltage`), nie das Fixture selbst: `prepare_ignition_repo`
kopiert es in ein Scratch-Verzeichnis, saet die Konformanz-Suite ein und macht
**einen** Commit mit eingefrorenem Autor, Committer und Datum
(`FROZEN_GIT_ENV`), sodass `base_revision` eine reine Funktion des Baums ist und
ein Replay auf jeder Maschine denselben 40-Hex-SHA erzeugt.

Gemessen 2026-09-05: 6 `.py`-Dateien, 3864 Zeilen; `gate1.py` allein 2357.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/ignition/__init__.py) | Re-Export der Runner-Symbole und die Abgrenzung zwischen `gate1` (die Slice wie der Plan sie formuliert) und `runner` (die aeltere In-Process-Probe, aus der sie gewachsen ist). | `IgnitionError`, `IgnitionResult`, `IgnitionWorkItem`, `IgnitionGraphDelta`, `materialize_voltage_rename`, `run_voltage_ignition` |
| [`__main__.py`](../../../daedalus/ignition/__main__.py) | `python -m daedalus.ignition` -- die registrierte Kommandozeilen-Tuer. Fuehrt die Slice einmal aus und druckt den Kopf der Quittung. Der Exit-Code berichtet, ob ein sauberes, paket-tragendes Ergebnis erreicht wurde, nicht ob etwas gemergt werden darf. | `main`, `RECEIPT_HEAD_KEYS` |
| [`gate1.py`](../../../daedalus/ignition/gate1.py) | Die Slice selbst: Planung aus dem Vier-Ebenen-Manifest, Session, Mission, vorbereitetes Ziel-Repo, zwei Gates, Kandidaten-Komposition, Evidence-Bindung, Replay-Vergleich, Diskriminations-Messung und Quittung. | `PlannedWorkItem`, `plan_work_items`, `ignition_session`, `ignition_mission`, `prepare_ignition_repo`, `rename_operator`, `code_type_gate`, `data_knowledge_gate`, `compose_candidate`, `check_evidence_item`, `old_symbol_occurrences`, `IgnitionSliceResult`, `run_gate1_ignition`, `measure_anchored_node_roles`, `measure_subject_coverage`, `criterion_discrimination_blockers`, `write_receipt`, `DEFAULT_FIXTURE`, `DEFAULT_RECEIPT_ROOT`, `RETIRED_SYMBOL`, `RENAMED_SYMBOL`, `SESSION_SLUG`, `SESSION_MISSION_ID`, `FROZEN_GIT_ENV` |
| [`runner.py`](../../../daedalus/ignition/runner.py) | Die deterministische In-Process-Probe: zwei WorkItems in einem kopierten Kandidatenbaum, Beweis der Byte-Gleichheit des Quell-Fixtures, echter `FourfoldSnapshot`, Graph-Delta, Verhaltensmessung, ein `EvidencePacket`. Verbraucht keine Approval und promotet nichts. | `IgnitionError`, `IgnitionWorkItem`, `IgnitionGraphDelta`, `IgnitionResult`, `WORK_ITEMS`, `materialize_voltage_rename`, `run_voltage_ignition`, `tree_digest`, `candidate_behavior`, `fourfold_graph_delta` |
| [`checks.py`](../../../daedalus/ignition/checks.py) | Die drei Gate-1-Evaluatoren: pytest (Code/Type), Schema (Data gegen sich selbst), Links (Knowledge). Jeder ist **ausserhalb** des Kandidaten verfasst. | `CheckReport`, `pytest_check`, `schema_check`, `link_check`, `check_manifest`, `render_reports`, `CONFORMANCE_TEST_PATH`, `CONFORMANCE_TEST_SOURCE`, `CONFORMANCE_TEST_SHA256`, `CODE_TYPE_NODE_IDS`, `DATA_KNOWLEDGE_NODE_IDS` |
| [`bundle.py`](../../../daedalus/ignition/bundle.py) | Das Evaluator-Bundle: alles, was entscheidet, benannt durch seine Bytes -- Kriteriumsquelle, geforderte Node-IDs, Evaluator-Module per Git-Blob-Digest **und** ausgefuehrten Rohbytes, Toolchain, conftest-Kette, pytest-Plugins. | `evaluator_bundle`, `bundle_digest_from_body`, `write_bundle_artifact`, `load_bundle_artifact`, `bundle_blockers`, `import_closure`, `EVALUATOR_MODULES`, `SCHEMA` |

## Warum es zwei Laeufe gibt

`runner.py` ist die aeltere Probe und wird bewusst behalten: sie ist der
billigste Weg, das Fourfold-Delta und die Verhaltensmessung zu ueben. `gate1.py`
kopiert diese drei Messungen nicht, sondern importiert sie als `tree_digest`,
`candidate_behavior` und `fourfold_graph_delta` -- ein zweiter Baum-Digest oder
ein zweites Graph-Delta waere genau die Drift, die das Fourfold-Delta erkennen
soll.

Ein weiterer Unterschied ist die WorkItem-Herkunft. `runner.WORK_ITEMS` nennt
sechs Pfade als Literale. `gate1.plan_work_items` leitet dieselbe Aufteilung aus
`fourfold.json` ab: eine Datei tritt einem Work Item bei, wenn sie das
zurueckgezogene Symbol tatsaechlich enthaelt, und eine Ebene, deren Dateien das
Symbol tragen, die aber kein Work Item erzeugt hat, ist ein `IgnitionError`.
Das Manifest selbst gehoert zum Data/Knowledge-Item, weil seine `claims` das
Symbol als Feld benennen.

## Die drei Checks

| Check | Ebenen-Paar | Was er misst |
| --- | --- | --- |
| `pytest_check` | Code/Type | Fuehrt die eingesaete Konformanz-Suite `CONFORMANCE_TEST_PATH` im Zielprojekt aus. |
| `schema_check` | Data gegen sich selbst | Vergleicht den CSV-Header mit dem JSON-Schema, das ihn einschraenkt -- eine halb fertige Umbenennung, die kein Import-Test sieht. |
| `link_check` | Knowledge | Loest jeden relativen Markdown-Link gegen den Baum auf; die Ebene ohne Laufzeit hat sonst keine Moeglichkeit, laut falsch zu sein. |

Jeder `CheckReport` ist eine **Messung** mit aufbewahrter Rohausgabe. Ob daraus
Evidence wird und mit welcher Assurance, entscheidet der Aufrufer gegen die
Attempt-Records -- nie das Check-Modul.

Die einzige benannte Ausnahme zur "Evaluator ausserhalb des Kandidaten"-Regel
ist bewusst: `pytest_check` **fuehrt** eine Testdatei aus, und diese Datei wird
von `gate1.py` aus `CONFORMANCE_TEST_SOURCE` in die Basisrevision des
Zielprojekts gesaet. Sie liegt also im Baum, aber kein Work Item darf sie
schreiben, und die Target-Scope-Containment des Attempt-Spine setzt das durch.

## Das Evaluator-Bundle

Zwei Codex-Reviews der Slice (2026-08-23) endeten aus demselben strukturellen
Grund `INCONCLUSIVE`: das Siegel authentifiziert einen **Pfad**, keine Aussage,
und `report_sha256` liess die Revision des Evaluators aus -- Evaluator-Drift
konnte sich als Stabilitaet tarnen. `bundle.py` schliesst das, ohne mehr zu
behaupten, als es kann: es loest das Halteproblem nicht, aber es macht jeden
Austausch **sichtbar** und jeden Vergleich auf eine Identitaet begrenzt.

Das Bundle bindet Kriteriumsquelle (Digest und Laenge), die Node-IDs, die jedes
Gate gruen bekommen muss, die Evaluator-Module per Git-Content-Digest
(checkout-stabil) **neben** dem committeten Blob **und** neben den Rohbytes, die
tatsaechlich ausgefuehrt wurden (als plattformabhaengig markiert), sowie die
Toolchain. Der Bundle-Digest geht in die Quittung und in den Replay-Vergleich
ein: zwei Laeufe sind nur unter einem Bundle ein Replay. Ein geaendertes Bundle
wird wie ein geaendertes Kriterium gemeldet -- benannt und als Replay
abgelehnt -- statt zu "stabil" gemittelt.

## Trust-Grenzen / Effekte

* **Registrierte Tuer:** `cli.ignition` in
  [`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py),
  Ziel `daedalus.ignition.__main__:main`, Effekte `FILESYSTEM_WRITE`,
  `PROCESS_SPAWN`, `PROCESS_CONTROL`, Guard-Contract `budget.process_guard`,
  `wiring=CENTRAL`, Anchor `begin_effect`. Diese aeussere Grenze liegt **vor**
  dem Argument-Parsing; die inneren `python.attempt`-Grenzen autorisieren und
  leasen weiterhin jeden einzelnen `TaskAttempt`.
* **Was geschrieben wird:** das Quittungsverzeichnis samt inhaltsadressiertem
  Store und -- seit G1-LEASE-01 (Owner-Entscheidung 2026-08-27, Option A) --
  das Effect-Lease-Ledger und der Write-Evidence-Store des Betreibers unter dem
  Control-Root der Installation. Diese Konsequenz wird im Docstring von
  `gate1.py` ausdruecklich genannt statt versteckt: ein Lauf der Slice ist
  gegenueber dem Control-Root des Betreibers **nicht** read-only. Der
  Repository-Checkout selbst wird nie geschrieben.
* **Lease pro Attempt:** `acquire_attempt_lease` aus
  [`daedalus/kernel/offload_lease.py`](../../../daedalus/kernel/offload_lease.py)
  bekommt den Installations-Checkout als Authority-Root und den
  Scratch-Kandidaten-Checkout als Subjekt, dessen Dateien nicht mutiert werden
  duerfen. Eine verweigerte Lease ist ein lauter Blocker, nie ein stiller
  ungeleaster Lauf; die Attempt-Zeilen der Quittung tragen `lease_id`,
  `lease_outcome` und `lease_error`.
* **`_reset_evidence_store`** loescht ein Store-Root nur, wenn es ausschliesslich
  die zwei erlaubten Verzeichnisnamen aus `_STORE_ENTRIES` enthaelt.
* **Keine Promotion.** Die Quittung sagt "nominated, not promoted"; das Modul
  importiert nichts aus `daedalus.kernel.promotion`, und es gibt keinen Pfad,
  der einen Patch auf etwas anderes als den selbst gebauten Scratch-Baum
  anwendet.
* **Fixture-Unversehrtheit** wird gemessen: `tree_digest` vor und nach dem Lauf,
  `IgnitionResult.primary_unchanged` als Praedikat.

## Tests

| Testdatei | Deckt ab |
| --- | --- |
| [`tests/ignition/test_voltage_ignition.py`](../../../tests/ignition/test_voltage_ignition.py) | Der Runner-Pfad: Rename, Graph-Delta, Evidence, Fixture-Unversehrtheit. |
| [`tests/ignition/test_voltage_ignition_faults.py`](../../../tests/ignition/test_voltage_ignition_faults.py) | Fehlerinjektion gegen denselben Pfad. |
| [`tests/test_ignition_gate1.py`](../../../tests/test_ignition_gate1.py) | `run_gate1_ignition`, Planung, Gates, Quittung, Replay. |
| [`tests/test_ignition_bundle.py`](../../../tests/test_ignition_bundle.py) | `evaluator_bundle`, `bundle_digest_from_body`, `bundle_blockers`, `import_closure`. |
| [`tests/test_ignition_bundle_gitattributes.py`](../../../tests/test_ignition_bundle_gitattributes.py) | Checkout-Stabilitaet der Blob-Digests gegen Zeilenende-Umschreibung. |
| [`tests/test_assurance_hardening.py`](../../../tests/test_assurance_hardening.py) | `_derive_assurance` und die Diskriminations-Blocker. |
| [`tests/test_criterion_imports_declaration.py`](../../../tests/test_criterion_imports_declaration.py) | Die deklarierte Import-Oberflaeche des Kriteriums. |
| [`tests/test_cli_effect_boundary.py`](../../../tests/test_cli_effect_boundary.py), [`tests/test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py) | Die `cli.ignition`-Registry-Zeile. |
| [`tests/test_fourfold_snapshot_locator.py`](../../../tests/test_fourfold_snapshot_locator.py) | Die Snapshot-Lokatoren, die die Slice erzeugt. |
| [`tests/test_canonical_execution_limit_policy.py`](../../../tests/test_canonical_execution_limit_policy.py) | Die Ausfuehrungslimit-Policy im Ignition-Pfad. |
| [`tests/test_kernel_contracts_have_producers.py`](../../../tests/test_kernel_contracts_have_producers.py) | Dass die Vertraege, die die Slice erzeugt, einen Produzenten haben. |

## Verwandt

* [Twin](twin.md) und [Twin Extractors](twin-extractors.md) --
  `compile_reference_project` und der `FourfoldSnapshot`, den die Slice neu baut.
* [Kernel](kernel.md) -- `assemble_fourfold_evidence_packet`, Attempt-Lease.
* [Spine](spine.md) -- `TaskAttempt`, `GateResult`, `RunnerContext`,
  Effekt-Registry, Kill-Switch.
* [Orchestration Missions](orchestration-missions.md) -- derselbe
  Missions-Kompilierpfad, produktiv statt als Fixture.
* [Orchestration Ikarus](orchestration-ikarus.md) -- der Supervisor, dessen
  wiederverwendbare Haelfte aus dieser Slice hervorging.
* [Gates](gates.md) -- die Gate-Berichte, in denen die Ignition-Evidenz auftaucht.
* [Graph-Delta als Fitness](../graph-delta-as-fitness.md) -- warum das Delta
  gemessen und nicht als Fitness benutzt wird.
* [Wiki-Index](../index.md)

## Ungeklaert

* **Ungeklaert:** Ob `runner.run_voltage_ignition` noch produktiv aufgerufen
  wird oder nur noch als Messwerkzeug fuer `gate1.py` und die Tests dient.
  `runner.WORK_ITEMS` ist laut `gate1.plan_work_items`-Docstring die
  "vorherige" Konstante, wird aber weiterhin als Default von
  `IgnitionResult.work_items` gefuehrt.
* **Ungeklaert:** Wie oft und von wem `python -m daedalus.ignition` in der
  Praxis ausgefuehrt wird; das Verzeichnis `runs/ignition` ist nicht Teil dieses
  Wikis.
* **Ungeklaert:** Die genaue Liste in `EVALUATOR_MODULES` und ob sie den
  vollstaendigen Entscheidungspfad abdeckt -- `import_closure` erweitert sie zur
  Laufzeit, aber ob die Wurzelmenge vollstaendig ist, laesst sich aus dem Modul
  allein nicht belegen.

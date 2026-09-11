---
title: Mapping — das generierte Architekturartefakt
type: module
status: living
updated: 2026-09-05
covers: daedalus/mapping
---
# Mapping — das generierte Architekturartefakt

`daedalus/mapping/` erzeugt die *mechanische* Hälfte des Architekturartefakts:
was existiert, was es erreicht, was dunkel ist, was eine Insel ist, und die
Zahlen dazu. Der Paket-Docstring trennt das ausdrücklich von der *narrativen*
Hälfte (ADRs, Invarianten, `docs/architecture-narrative.md`), die
handgeschrieben bleibt: kein Scanner leitet ab, *warum* etwas so ist, und ein
Generator, der so täte, würde erfinden.

Der Anlass steht in vier der sieben Modul-Docstrings wörtlich: ein
handgeschriebenes Feature-Inventar zählte 136 Features, 8 Inseln und 2 dunkle
Schalter; ein tiefer Lesedurchgang über denselben Baum sechs Stunden später fand
827, 55 und 51. Das Artefakt war beim Schreiben nicht falsch — es veraltete
sofort, und niemand konnte es merken. Weil `daedalus/spine/picker.py` genau
diese Datei als die zwei höchstpriorisierten Bänder der
Selbstverbesserungs-Queue liest, war das kein Dokumentationsproblem, sondern ein
Steuerungsproblem.

Einordnung: Mapping ist Beobachtung und Evidenz über den eigenen Baum, kein
Twin-Plane und keine zweite Graph-Autorität. `reach.analyse` beantwortet die
Frage, die der Struktur-Index von [Structcore](structcore.md) *nicht*
beantwortet: nicht "X importiert Y", sondern "kommt ein Mensch oder ein Werkzeug
hier überhaupt an".

## Module

| Datei | Zweck | Öffentliche Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/mapping/__init__.py) | Schmale Fassade; exportiert nur den Erreichbarkeitsteil. | `analyse`, `EntryPoint`, `ModuleFacts`, `ReachReport`, `CLASSES`, `ENTRY_KINDS`, `SCHEMA` |
| [reach.py](../../../daedalus/mapping/reach.py) | Die Erreichbarkeits-Engine. Entdeckt Einstiegspunkte (statt sie zu verdrahten), sammelt Importe auf jeder Scope-Tiefe, ordnet sie dem Branch-Literal zu, unter dem sie stehen, und klassifiziert jedes Modul. | `analyse`, `EntryPoint`, `ModuleFacts`, `ReachReport`, `CLASSES`, `ENTRY_KINDS`, `SCHEMA` |
| [switches.py](../../../daedalus/mapping/switches.py) | Mechanisches Inventar jedes Schalters, der ein gebautes Feature ausschalten kann: gelesene Umgebungsvariablen samt Default und Lesestelle, öffentliche Boolean-Parameter mit Default *off*, Konfigschlüssel in `projects/*.json` mit off-förmigem Wert, und Namen, die die Doku verspricht und der Code nie liest (sowie umgekehrt). | `analyse`, `SwitchReport`, `SwitchCounts`, `EnvSwitch`, `EnvSite`, `ParamSwitch`, `ConfigSwitch`, `DocDrift`, `SCHEMA` |
| [drift.py](../../../daedalus/mapping/drift.py) | Das Gate: vergleicht den aktuell generierten Zustand mit einem committeten Snapshot (`docs/architecture-state.json`) und schlägt fehl, wenn sie sich unterscheiden. Leitet selbst nichts ab — Inseln kommen aus `reach.analyse`, Schalter aus `switches.analyse`. | `check`, `refresh`, `scan`, `main`, `DriftReport`, `DriftItem`, `ScanResult`, `Acceptance`, `parse_acceptances`, `DocIndex`, `snapshot_bytes`, `load_snapshot`, `write_snapshot`, `digest_ok`, `repo_state`, `snapshot_freshness`, `ignore_config` |
| [inventory.py](../../../daedalus/mapping/inventory.py) | Die generierte Feature-Volkszählung, die das handgetippte `docs/FEATURE_INVENTORY.json` ersetzt. Trennt konsequent zwischen ableitbaren Feldern (Status, Einstiegspunkte, Importeure, Tests, CLI-/HTTP-Tabellen, Schalter, zwei Sorten `stale`) und nicht ableitbaren, die aus dem alten Dokument *geerntet* statt erfunden werden. | `build`, `refresh`, `check`, `harvest`, `main`, `load`, `write_inventory`, `inventory_bytes`, `render_text`, `digest_ok`, `annotation_overreach` |
| [render.py](../../../daedalus/mapping/render.py) | Das Kommando `daedalus map`: führt Erreichbarkeits- und Schalter-Engine genau einmal aus (`analyse_once`), baut daraus die HTML-Seite mit dem narrativen Teil aus separater Datei, schreibt Karte, Snapshot und Inventar und nimmt Ausnahmen (`accept`) entgegen. | `analyse_once`, `build`, `render_html`, `write_map`, `accept`, `main`, `git_stamp`, `Stamp`, `Narrative`, `NarrativeSection`, `parse_narrative`, `load_narrative`, `esc` |
| [spectral.py](../../../daedalus/mapping/spectral.py) | Vier spektrale Messgrößen über den *Erreichbarkeits*graphen, die eine Frage beantworten: passt die deklarierte Paketstruktur zur tatsächlichen? Baut selbst keinen Graphen, sondern adaptiert den von `reach.analyse`. | `analyse`, `spectral_evidence`, `graph_from_reach`, `graph_from_edges`, `declared_partition`, `fiedler_report`, `modularity_report`, `conductance_report`, `eigengap_report` |

Mit 7475 Zeilen über sieben Dateien (gemessen 2026-09-05) ist `render.py` (1657)
knapp vor `drift.py` (1567) der größte Teil.

### Was `reach.py` als Einstiegspunkt zählt

Sechs Sorten, alle entdeckt statt hartkodiert: `script` (ein
`[project.scripts]`-Eintrag in `pyproject.toml`), `module_main` (eine
`__main__.py`), `main_guard` (ein `if __name__ == "__main__":`), `cli` (ein
Subkommando-Branch in einer Dispatch-Kette), `http` (dieselbe Form, aber die
Literale sind URL-Pfade) und `bus` (eine Poll-Schleife in einem Einstiegsmodul).

Zwei Entscheidungen daraus sind bemerkenswert und im Code begründet:

- **Testdateien sind keine Einstiegspunkte.** Ein Modul, das nur von seinem
  eigenen Test erreicht wird, ist genau eine Insel; Tests als Wurzeln
  zuzulassen würde das wertvollste Signal löschen. Testabdeckung wird separat
  pro Modul geführt (`tested_by`).
- **Ein Import ist nicht automatisch ein Beweis.** Drei Formen werden
  ausdrücklich abgelehnt und getrennt als `weak` gesammelt: ein Import in einem
  toten Branch, ein Import in einem `try`, dessen `ImportError` geschluckt
  wird, und ein Konsolenskript, dessen Ziel nicht existiert. Ein Modul, dessen
  einzige Importeure schwach sind, wird `unknown` mit Begründung — nicht
  `island`. Die Begründung im Code: eine Lücke ist reparierbar, eine
  Falschbeschuldigung nicht.

`ReachReport` ist bewusst deterministisch: keine Uhrzeit, kein absoluter Pfad
außerhalb der Wurzel, keine Set-Iteration. Zwei Läufe über einen unveränderten
Baum liefern byte-identische `to_dict()`-Ausgaben — erst das macht ein Diff des
Reports zur Aussage "die Architektur hat sich bewegt" statt "der Scanner lief".

Kanten, die der Struktur-Index trägt und dieser Walk nicht, landen in
`index_extra_edges` und werden **gemeldet, nie gemergt**: zwei Engines, die über
denselben Importgraphen uneins sind, sind selbst ein Befund.

### Eine Engine, eine Antwort

`drift.py` und `render.py` teilen sich einen einzigen Lauf. Der Docstring von
`drift.py` nennt den Grund als Korrektheitseigenschaft, nicht als Aufräumen:
Solange Gate und Seite eigene Scans fuhren, sah das Gate 11 Inseln, wo die Seite
6 sah — ohne einen einzigen gemeinsamen Eintrag —, und die dunkle Hälfte des
Gates meldete 0, wo die Schalter-Engine 15 meldete. Ein Gate, das der Seite
widerspricht, die es bewacht, bringt dem Leser bei, beiden nicht zu glauben.
`analyse_once` in `render.py` ist heute der eine Lauf, dessen zwei Reports an
Seite, Gate und Re-Baseline gehen.

`drift.py` leitet nur zwei Dinge selbst ab, und beide stehen im Docstring, damit
man mit ihnen streiten kann: die Definition von *unreached* (`UNREACHED_CLASSES`)
und deren Aufteilung in drei Listen — `islands` (Insel plus Waise: verdrahten
oder löschen), `unknown` (Mehrdeutigkeit auflösen) und `shims` (den Forward
löschen) —, weil die Abhilfen drei verschiedene Sätze sind.

### Spektral: Evidenz, kein Gate

`spectral.py` sagt seine Abgrenzung zu `daedalus/structcore/topology.py` im
Docstring: `spectral_partition` dort erzeugt *einen* Schnitt des
structcore-Index-Graphen für die Web-UI, also ein Bild; hier entstehen
*Messungen über eine bereits deklarierte Partition* (das Paketlayout auf der
Platte) über den *Erreichbarkeits*graphen. Anderer Graph, andere Ausgabe,
anderer Konsument. Der Fiedler-Vektor taucht in beiden auf, weil beide den
zweiten Laplace-Eigenvektor brauchen; in keinem Fall wird ein Eigensolver von
Hand geschrieben.

Nichts in `spectral.py` liefert einen Exit-Code, blockiert eine Lane oder
verschiebt ein Picker-Band. Der Docstring begründet: eine Strukturmetrik, die
blockieren kann, ist eine Strukturmetrik, die gespielt wird. Es gibt in der
Datei absichtlich keine Schwellwertkonstante. Der Graph wird ungerichtet
projiziert, weil die verwendete Spektraltheorie für ungerichtete Graphen
definiert ist; dieser Handel steht als `graph_type` in jedem Report-Dict.

> **Extern:** Fiedler-Vektor und algebraische Konnektivität sind der zweite
> Eigenvektor beziehungsweise der zweitkleinste Eigenwert der Graph-Laplace-Matrix;
> Modularität und Conductance messen Partitionsgüte. Das Modul rechnet sie über
> networkx/scipy statt eigenem Eigensolver.
> Quelle: https://en.wikipedia.org/wiki/Algebraic_connectivity

## Trust-Grenzen / Effekte

Drei der sieben Module sind registrierte CLI-Türen der Effekt-Registry
(gemessen 2026-09-05 in `daedalus/spine/effect_boundary.py`):

| Registry-ID | Ziel | Effekte |
| --- | --- | --- |
| `cli.mapping_drift` | `daedalus.mapping.drift:main` | Dateisystem-Schreiben |
| `cli.mapping_inventory` | `daedalus.mapping.inventory:main` | Dateisystem-Schreiben |
| `cli.mapping_render` | `daedalus.mapping.render:main` | Dateisystem-Schreiben, Prozess-Spawn |

Alle drei sind `Wiring.CENTRAL` mit einem `GuardAnchor` auf `begin_effect` in
`main` und dem Guard-Contract `budget.process_guard`. Die Aufrufe sind
*bedingt* und darin einheitlich: `begin_effect` läuft nur, wenn der Aufruf
tatsächlich schreibt.

- `render.main`: `begin_effect` nur wenn *nicht* `--json` und *nicht* `--check`.
- `inventory.main`: `begin_effect` nur bei `--refresh`; `--check` und `--json`
  bleiben fail-open.
- `drift.main`: `begin_effect` nur bei `--refresh` oder `--init`; das
  Vergleichs-Gate bleibt read-only.

Damit erfüllt das Paket die Regel aus Masterplan §11 Gate 0 wörtlich:
fail-closed für geschützte Effekte, fail-open für read-only Inspektion.

Die tatsächlichen Writer sind `write_map` und `accept` (`render.py`),
`write_snapshot` und `refresh` (`drift.py`) sowie `write_inventory` und
`refresh` (`inventory.py`). `reach.py`, `switches.py` und `spectral.py`
schreiben nichts, spawnen nichts und öffnen kein Netz; sie lesen den Baum mit
dem stdlib-`ast` und Textlesungen.

Eine bewusst fail-closed gestellte Ecke steht in `drift.main`: ein erster Lauf
ohne Snapshot gibt 1 zurück. Der Kommentar erklärt den Grund — vorher schrieb er
den Baseline und beendete mit 0, wodurch `rm docs/architecture-state.json` ein
grüner Durchlauf durch eine Tür wurde, die `reach.py` selbst als Einstiegspunkt
klassifiziert.

`switches.py` beschreibt außerdem, was es *nicht* sehen kann: zur Laufzeit
zusammengesetzte Umgebungsnamen landen in `dynamic_reads` statt geraten zu
werden, nur modulweite `NAME = "LITERAL"`-Konstanten werden aufgelöst, und
"dokumentiert" heißt, dass der Token in env-förmiger Gestalt in einem Dokument
vorkommt — nicht, dass die Prosa drumherum stimmt.

## Tests

Gemessen 2026-09-05 berühren 20 Testdateien dieses Paket. Die unmittelbar
zuständigen:

| Test | Deckt ab |
| --- | --- |
| [tests/test_mapping_reach.py](../../../tests/test_mapping_reach.py) | die Erreichbarkeitsklassifikation und Einstiegspunkt-Entdeckung |
| [tests/test_mapping_reach_facades.py](../../../tests/test_mapping_reach_facades.py) | Shim-/Fassaden-Erkennung |
| [tests/test_mapping_reach_weak_reasons.py](../../../tests/test_mapping_reach_weak_reasons.py) | die `weak`-Kanten und ihre Begründungen |
| [tests/test_mapping_switches.py](../../../tests/test_mapping_switches.py) | Schalterinventar, Defaults, Doku-Drift |
| [tests/test_mapping_drift.py](../../../tests/test_mapping_drift.py) | Gate, Snapshot, Akzeptanzen |
| [tests/test_mapping_spectral.py](../../../tests/test_mapping_spectral.py) | die vier spektralen Reports |
| [tests/test_mapping_cli.py](../../../tests/test_mapping_cli.py) | die CLI-Oberflächen aller drei Türen |
| [tests/test_generated_inventory.py](../../../tests/test_generated_inventory.py) | die generierte Volkszählung und die Ernte aus dem alten Dokument |
| [tests/test_cli_effect_boundary.py](../../../tests/test_cli_effect_boundary.py), [tests/test_registry_new_doors.py](../../../tests/test_registry_new_doors.py) | die drei Registry-Zeilen |
| [tests/test_picker_spectral_enrichment.py](../../../tests/test_picker_spectral_enrichment.py) | die Anreicherung der Picker-Kandidaten durch `spectral_evidence` |
| [tests/test_spine_map_source.py](../../../tests/test_spine_map_source.py) | dass der Picker seine Bänder aus dem generierten Artefakt zieht |
| [tests/test_architecture_boundaries.py](../../../tests/test_architecture_boundaries.py) | Importrichtungen |

## Verwandt

- [Structcore](structcore.md) — der Struktur-Index, dessen Frage eine andere ist
- [Spine](spine.md) — Effekt-Registry, `begin_effect`, der Picker als Konsument
- [Interfaces CLI](interfaces-cli.md) — die Tür `daedalus map`
- [Interfaces HTTP](interfaces-http.md) — die UI-Seite, die Struktur und Topologie ausliefert
- [Observe](observe.md) — verwandte Beobachtungsartefakte
- [Tools](../tooling/tools.md) — die Regel für schreibende Einstiegspunkte
- [Gates](gates.md) — das Gate-Vokabular, in das der Drift-Check gehört
- [Daedalus-Paketwurzel](daedalus-package-root.md), [Wiki-Index](../index.md)
- [Graph-Delta als Fitness](../graph-delta-as-fitness.md), [Feature-Backlog](../feature-backlog.md)

## Ungeklärt

- **Ungeklärt:** Wer außer `daedalus/spine/picker.py` das generierte Inventar
  liest. Die Docstrings nennen den Picker als Konsumenten; weitere habe ich
  nicht verfolgt.
- **Ungeklärt:** Wie aktuell `docs/architecture-narrative.md` und
  `docs/architecture-state.json` sind. Beide existieren (gemessen 2026-09-05);
  ob ihr Inhalt zum heutigen Baum passt, sagt erst ein Lauf des Gates. Der Code
  behandelt beide als optional und rendert bei fehlender Narrative einen
  expliziten ABSENT-Marker.
- **Ungeklärt:** Die genaue Semantik der Akzeptanzen (`Acceptance`,
  `parse_acceptances`, `accept`) — insbesondere, wie `until`/`since` das Gate
  beeinflussen. Ich habe die Datumslogik nicht vollständig gelesen.
- **Ungeklärt:** `render.py` ist als einzige Tür mit `PROCESS_SPAWN` registriert;
  welcher Aufruf den Prozess startet (vermutlich Git für den Staleness-Stempel),
  habe ich nicht bis zur Aufrufstelle verfolgt.

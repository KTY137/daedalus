---
title: Forest v2 s10 kill
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s10_kill
---
# Forest v2 s10 kill

`experiments/forest_v2/s10_kill` ist der Kill-Kriterien-Evaluator fuer die
Forest-v2-Prioren. Der Paket-Docstring nennt die Klassifikation selbst:
eingefroren, isoliert, read-only, Vorarbeit zu Gate 2, nichts davon ist
produktionsfaehig, nichts im Kernel importiert es, und es promotet, gated und
blockiert nichts. Plan §14 sagt, ein Kill-Ergebnis loesche den Plan nicht still,
sondern archiviere Evidenz, stoppe die Spur und schlage ein Amendment vor.
Dieses Paket macht den mechanisch pruefbaren Teil dieses Urteils zu Code, damit
ein KILL ein *berechneter Vorschlag mit angegebener Unsicherheit* ist und keine
Stimmung.

Die zentrale Design-Beschraenkung steht ebenfalls im Docstring: das Paket
importiert nie die Messumgebung, die seine Eingabe erzeugt hat (Slice s09 oder
spaeter). Es liest serialisierte Ergebnisse. Dass der Evaluator nicht in das
hineingreifen kann, was er benotet, ist dieselbe Trennung, die Plan §4
(Invarianten 3 und 4) zwischen Kandidat und Evaluator verlangt — eine Ebene
hoeher angewandt.

Gemessen 2026-09-05: 12 `.py`-Dateien im Verzeichnis (10 Module, 2 Testdateien),
4999 Zeilen insgesamt; die 10 Module tragen 3847.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../experiments/forest_v2/s10_kill/__init__.py) | Klassifikation, Layout-Uebersicht und die einzige Paket-Konstante. | `SCHEMA_ID` (`"forest_v2.s10.kill-input/1"`) |
| [`schema.py`](../../../experiments/forest_v2/s10_kill/schema.py) | Der Ergebnis-Datenvertrag, den der Evaluator liest — absichtlich ein JSON-Vertrag, kein Python-Vertrag. | `ResultSet`, `Arm`, `Corpus`, `Retriever`, `SchemaError`, `roles_present`, `dump`, `iter_paired`, `SCHEMA_ID`, `FUSION_MECHANISM` |
| [`stats.py`](../../../experiments/forest_v2/s10_kill/stats.py) | Gepaarte Bootstrap-Konfidenzintervalle und ein Aequivalenztest, reine Standardbibliothek, deterministisch. | `Paired`, `compare`, `bootstrap_ci`, `stable_seed`, `DEFAULT_MARGIN`, `DEFAULT_CONFIDENCE`, `DEFAULT_RESAMPLES` |
| [`plane_range.py`](../../../experiments/forest_v2/s10_kill/plane_range.py) | Die Dynamikbereich-Vorbedingung: verweigert eine Metrik, deren Daten nie anders haetten ausfallen koennen. | `crosstab`, `CrossTab`, `CrossTabRow`, `render_crosstab`, `gold_counts`, `range_refusal`, `Refusal`, `RangeRefused`, `fusion_arm`, `cross_plane_edge_refusal`, `planes_never_targeted` |
| [`criteria.py`](../../../experiments/forest_v2/s10_kill/criteria.py) | Die Plan-§14-Punkte als Praedikate ueber einem `ResultSet`, plus das Register. | `evaluate`, `Finding`, `EvalConfig`, `Registered`, `register_entries`, `KEEP`, `KILL`, `INCONCLUSIVE`, `UNDECIDABLE`, `NOT_EVALUABLE`, `PRIOR_TWIN`, `PRIOR_LATENT`, `PRIOR_GRAPH_CTX`, `PRIOR_GENESIS`, `PRIOR_CORPUS`, `PRIOR_ORCH`, und die neun `c_*`-Praedikate |
| [`plan_register.py`](../../../experiments/forest_v2/s10_kill/plan_register.py) | Leitet das Register zur Pruefzeit aus dem *lebenden* Plan ab und vergleicht es woertlich mit der Kopie im Code. | `load_section`, `extract_section`, `find_plan`, `compare`, `verify`, `verify_quietly`, `RegisterCheck`, `PlanSection`, `PlanBullet`, `PlanRegisterError`, `normalise` |
| [`report.py`](../../../experiments/forest_v2/s10_kill/report.py) | Die Zusammenfassung pro Prior: Findings zu einem Verdikt, mit Banner, JSON- und Textprojektion. | `build`, `render`, `to_json`, `Report`, `PriorVerdict`, `roll_up`, `BANNER` |
| [`measured_inputs.py`](../../../experiments/forest_v2/s10_kill/measured_inputs.py) | Ergebnismengen, rekonstruiert aus Messungen, die wirklich auf Platte liegen (Slice s08). | `MEASURED_RUNS`, `build`, `Contingency`, `pair`, `program_plane_census`, `planes_never_a_retrieval_target`, `s08_graph_structure`, `s08_plane_routing`, `QUERY_SETS`, `S08_COMMIT`, `S08_QUERIES`, `S08_SOURCE`, `S08_CAVEAT`, `S08_PLANE_ORDER`, `NO_FUSION_ARM_EXISTS`, `GOLD_PLANE_JOINT_CAVEAT` |
| [`synth.py`](../../../experiments/forest_v2/s10_kill/synth.py) | Synthetische Ergebnismengen mit konstruierter Grundwahrheit fuer den Selbsttest; jede Punktzahl wird zur Laufzeit aus einem geseedeten PRNG gezogen. | `SCENARIOS`, `build`, `make_run`, `ArmSpec`, `PLANES`, `WIN`, `SMALL`, `FUSION_RETURNS`, die 13 `scenario_*`-Funktionen |
| [`cli.py`](../../../experiments/forest_v2/s10_kill/cli.py) | `python -m experiments.forest_v2.s10_kill.cli` — liest und druckt. | `main` |

### Fuenf Verdikte, die nicht ineinander uebersetzbar sind

`criteria.py` und `plane_range.py` halten fuenf Zustaende bewusst auseinander:

- `KEEP` — jedes entscheidbare Kriterium fuer diesen Prior ist bestanden.
- `KILL` — mindestens ein Kriterium hat gefeuert; nach der Rollup-Regel schlaegt
  ein gefeuertes Kriterium beliebig viele Bestandene, weil Plan §14 sagt, dass
  *irgendeines* der Ergebnisse die Spur stoppt.
- `INCONCLUSIVE` — die Daten haetten entscheiden koennen und taten es nicht (zu
  wenige Faelle, zu breites Intervall). Mehr von denselben Daten wuerde helfen.
  Der Docstring nennt es ausdruecklich eine echte Antwort, kein weiches KEEP.
- `UNDECIDABLE` — die Daten koennen es bei *keiner* Stichprobengroesse
  entscheiden, weil die unterscheidende Beobachtung darin nicht vorkommt. Mehr
  Daten aendern nichts und verkleinern nur das Intervall.
- `NOT_EVALUABLE` — dieser Lauf hat den Arm nicht mitgeliefert, oder das
  Eingabeformat kann die Evidenz gar nicht tragen.

### Die drei Waechter vor jedem Verdikt

1. **Dynamikbereich.** Vor jeder Vergleichsmetrik muss die Kreuztabelle
   Gold-Label-Ebene x tatsaechliche Reichweite des Arms zeigen, dass der
   Vergleich anders haette ausfallen koennen. Der Waechter sitzt in
   `_compare_arms`, damit ein Kriterium einen Vergleich nicht dadurch melden
   kann, dass es zu fragen vergisst. `plane_range.py` nennt drei in diesem
   Programm gemessene Defekte derselben Art: s08s eingefrorene 600 Gold-Labels
   sind alle Code-Dokumente; s08s Graph hat 992 Kanten, davon 0 ebenenkreuzend
   (Endpunkt-Zaehlung `{code: 1984}`), waehrend Kriterium 14.2 ausdruecklich von
   *cross-plane*-Kanten spricht; s02s Annotationsdecke lag bei 100%, und eine
   Kontrolle am oberen Skalenrand kann nicht verlieren.
2. **Power.** Weniger als `min_cases` gepaarte Faelle ergibt `INCONCLUSIVE`,
   egal was das Intervall sagt. Der Plan verlangt 5-10 Seeds, wo Varianz zaehlt;
   eine Kill-Entscheidung auf vier verrauschten Faellen ist keine Messung.
3. **Budget-Symmetrie.** Bei ungleichen Budgets fragt `_budget_favour`, wem die
   Asymmetrie genutzt hat — Plan §14 verlangt identische Compute-/Token-Budgets.

### Nicht-Signifikanz ist keine Aequivalenz

Der methodische Kern von `stats.py`: mehrere §14-Punkte feuern auf *Aequivalenz*
("degree-preserving randomised cross-plane edges perform equivalently", "four
independent indices perform equivalently"). Waeren sie als "der Unterschied war
nicht signifikant" implementiert, wuerde ein winziger, unterpowerter,
verrauschter Lauf den Prior automatisch killen — je weniger man misst, desto
mehr killt man. Deshalb liefert jeder Vergleich drei separierbare Zustaende
gegen eine vorab erklaerte praktische Marge `delta`: `superior` (CI ganz ueber
0), `inferior` (CI ganz unter 0), `equivalent` (CI ganz in (-delta, +delta)).
Keiner ist die Negation eines anderen. Ein breites CI ist keiner der drei und
wird ehrlich als inconclusive gemeldet; ein sehr enges CI kann gleichzeitig
`superior` und `equivalent` sein (ein realer, aber praktisch irrelevanter
Gewinn), und der Report zeigt beides statt das schmeichelhafte auszuwaehlen.
Das Intervall ist ein Perzentil-Bootstrap ueber die gepaarten Fall-Differenzen,
weil Recall@k und MRR beschraenkt, diskret und sichtbar nicht-normal sind.
Defaults gemessen 2026-09-05: `DEFAULT_MARGIN` 0.02, `DEFAULT_CONFIDENCE` 0.95,
`DEFAULT_RESAMPLES` 10 000.

### Das Register gegen den lebenden Plan

`plan_register.py` existiert wegen eines konkreten, im Docstring dokumentierten
Fehlers: die erste Fassung dieses Slices hatte "fuenfzehn Kill-Kriterien" in
Docstring, README-Zeile, Deckungsprozent und Testkonstante fest verdrahtet,
waehrend der lebende Plan sechzehn auflistet. Ein Punkt — Corpus-Lizenzierung und
Provenienz — fehlte im Code ganz, und weil die restlichen Punkte von Hand
nummeriert waren, trug das Kriterium nach der Luecke den *freien* Index: wer
"14.15" im Plan nachschlug, landete bei einem anderen Kriterium als der Report
meinte. Der Nenner war schmeichelhaft (9/15 = 60%); neun von sechzehn sind
56,3%.

Die Konsequenz: der Plantext wird zur Pruefzeit geparst (Ueberschrift, Punkte und
die Abschnitts*nummer*, die sich schon einmal von 13 auf 14 bewegt hat), das
Register im Code wird woertlich eins zu eins verglichen, inklusive des
`plan_ref`-Index jedes Eintrags, und die Deckung im Report ist
`n_decided / n_extracted`, nie ein Literal. Ein Plan, der einen Punkt hinzufuegt,
entfernt, umnummeriert oder umformuliert, macht die Pruefung rot — das ist der
ganze Zweck: dieses Modul existiert, um zu scheitern.

Gemessen 2026-09-05: 16 `Registered`-Eintraege in `criteria.py`, davon 7 mit
`out_of_scope_reason` (behavioural outcomes, Snapshot-Kosten-Telemetrie,
Verifier-Praezision, Genesis-Konformitaet, Corpus-Lizenzierung und -Provenienz)
und 9 mit einem echten Praedikat.

### Gemessene gegen synthetische Eingaben

`synth.py` baut Laeufe mit konstruierter Grundwahrheit ("hier ist die Behandlung
wirklich um 0.15 besser", "hier ist die Kontrolle wirklich identisch") und
prueft, ob die Verdikte so herauskommen, wie der Plan es verlangt. Kein Wert ist
eine Fixture-Tabelle; jede Punktzahl wird zur Laufzeit gezogen. Gemessen
2026-09-05: 13 Szenarien in `SCENARIOS`.

`measured_inputs.py` stellt die Gegenfrage: *koennen die Messungen, die dieses
Projekt heute hat, ueberhaupt ein Kriterium feuern lassen — oder ist der
Evaluator strukturell ausserstande, KILL zu sagen?* Provenienz ist Slice s08,
Branch `grind/f2-s08` bei `a0c8fabd`, ausdruecklich der **korrigierte** Lauf;
s08s erster Bericht wurde am 2026-08-18 wegen zweier Defekte zurueckgezogen, die
beide zugunsten der Vier-Ebenen-Hypothese verzerrten, und die zurueckgezogenen
Tabellen werden hier nicht wiederverwendet. Drei ehrliche Grenzen begleiten
jedes daraus abgeleitete Verdikt:

- **Der vom Kriterium benannte Vergleichspartner existiert in s08 nicht.** Es
  gibt keinen Cross-Plane-*Fusion*-Retriever, also ist 14.3 hier gar nicht
  entscheidbar; das naechstliegende messbare System ist *ein* gemeinsamer
  BM25-Index ueber die Dokumente aller vier Ebenen, und ein gemeinsamer Index ist
  keine Fusion. Ihn `fusion` zu nennen, um ein Verdikt herauszubekommen, waere
  Substitution des Vergleichspartners — genau der Defekt, den s08 zurueckziehen
  musste, wiedergeboren im Instrument, das ihn erkennen soll. Die Arme heissen
  deshalb `bm25`.
- **s08s eingefrorene Query-Menge traegt nur Code-Gold-Labels**, siehe oben.
- **Fehlende Paarungen** werden deterministisch gefuellt, und die betroffenen
  Vergleiche werden von keinem Kriterium konsumiert; die Luecken sind pro Lauf
  benannt (`GOLD_PLANE_JOINT_CAVEAT`).

## Trust-Grenzen / Effekte

- **Keine Effekte, kein Writer.** `cli.py` sagt es woertlich: das Modul liest und
  druckt, oeffnet keine Netzwerkverbindung, startet keinen Subprozess und
  **schreibt keine Datei** — absichtlich, damit dieses Verzeichnis die
  Read-only-Eigenschaft behaelt, auf die die Grenznotiz der
  `experiments/forest_v2/README.md` sich stuetzt. Ein effektbehafteter
  Entrypoint unter `experiments/` muesste erst in der kanonischen Effekt-Registry
  registriert werden (siehe [Spine](../architecture/spine.md)). Wer den Report
  auf Platte will, leitet stdout um; die Entscheidung zu schreiben ist dann die
  des Aufrufers, ausserhalb des Experiments.
- **Der Exit-Code meldet, ob die Auswertung lief, nie was sie fand.** 0 =
  ausgewertet, 2 = die Eingabe war keine Ergebnismenge, die dieser Evaluator
  benotet. Ein KILL aendert den Exit-Code nicht, weil ein Exit ungleich 0 die Art
  ist, wie Werkzeuge Dinge gaten — und dieser Evaluator gated nichts.
- **Der Report traegt ein Banner.** `report.BANNER`: "ADVISORY — this report
  gates nothing, promotes nothing and blocks nothing. A KILL is a proposal to
  open an amendment (plan section 15), not an action."
- **Keine Import-Kante zur Produktion, in keine Richtung.**
  `test_s10_boundary.py` erzwingt genau das per stdlib-AST ueber den eigenen
  Quelltext: `FORBIDDEN_ROOTS` enthaelt u. a. `daedalus`, `tools`, `runs`,
  `subprocess`, `socket`, `urllib`. Der Docstring begruendet es: ein Versprechen
  in einem Docstring verfaellt.
- **`plan_register.py` liest genau eine Markdown-Datei und hasht sie**; es
  schreibt nichts und importiert nichts ausserhalb der Standardbibliothek.

## Tests

Gemessen 2026-09-05 liegen die Tests dieses Slices *im Paket*, nicht unter
`tests/` — konsequent zur Isolationsregel, weil die Testdateien sonst aus dem
Produktions-Testbaum in das Experiment importieren muessten:

- [test_s10_kill.py](../../../experiments/forest_v2/s10_kill/test_s10_kill.py) —
  1030 Zeilen: der Selbsttest ueber die synthetischen Szenarien, das Register und
  die Verdikt-Logik.
- [test_s10_boundary.py](../../../experiments/forest_v2/s10_kill/test_s10_boundary.py)
  — 122 Zeilen: die Isolationszusagen (kein Produktionsimport in beide
  Richtungen, kein effektbehafteter Entrypoint) als AST-Pruefung.

Die Gegenrichtung liegt beim Erzeuger: `experiments/forest_v2/s09_eval/to_s10.py`
und [test_to_s10.py](../../../experiments/forest_v2/s09_eval/test_to_s10.py)
schreiben bzw. pruefen das Eingabeformat, ohne dass eine Import-Kante zwischen
den Slices entsteht.

## Verwandt

- [Forest v2](forest-v2.md) — die gemeinsame README-Grenznotiz aller Slices
- [Forest v2 s09 eval](forest-v2-s09-eval.md) — der Erzeuger der Ergebnismengen
- [Forest v2 s08 graph baselines](forest-v2-s08-graph-baselines.md) — Quelle von `measured_inputs`
- [Forest v2 s11 fusion](forest-v2-s11-fusion.md) — der fehlende Fusion-Arm, den 14.3 braucht
- [Forest v2 s07 bm25](forest-v2-s07-bm25.md) — die Cheap-Retrieval-Baseline aus 14.1
- [Forest v2 s02 types](forest-v2-s02-types.md) — die 100%-Annotationsdecke aus `plane_range`
- [Graph-Delta als Fitness](../graph-delta-as-fitness.md) — die verwandte Frage, ob Graphbewegung Verhalten vorhersagt
- [Twin](../architecture/twin.md), [Type graph](../architecture/type-graph.md), [Data layer](../architecture/data-layer.md), [Knowledge layer](../architecture/knowledge-layer.md) — die vier Ebenen, ueber die die Prioren urteilen
- [Gates](../architecture/gates.md) — die produktive, effektfreie Berichtsschicht (dieselbe Disziplin, andere Domaene)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ob je ein Kriterium auf echten Daten gefeuert hat.** `measured_inputs.py`
  stellt die Frage explizit, aber das Ergebnis ist ein Laufzeitartefakt der CLI
  und liegt nicht als Datei im Baum. Aus dem Code allein ist nicht ablesbar,
  welches Verdikt die s08-Rekonstruktion heute erzeugt.
- **`FUSION_MECHANISM`** ist in `schema.py` als Konstante
  (`"cross_plane_score_fusion"`) definiert; wie streng ein Arm sie belegen muss,
  um als Fusion zu gelten, geht aus dem Modul allein nicht hervor.
- **Die Prior-Konstanten `PRIOR_LATENT`, `PRIOR_GENESIS`, `PRIOR_CORPUS` und
  `PRIOR_ORCH`** existieren, aber die zugehoerigen Kriterien sind ueberwiegend die
  sieben `NOT_EVALUABLE`-Eintraege. Welches Eingabeformat sie entscheidbar machen
  wuerde, ist pro Eintrag als Grund benannt, aber nirgends als Vertrag
  spezifiziert.
- **Plan-Revisionsdrift.** `criteria.py` verweist auf "Plan-Revision 5" fuer die
  Umnummerierung von §13 auf §14; der Plan steht heute bei Revision 12 (Stand
  2026-09-05). Die §14-Ueberschrift ist unveraendert, sodass
  `plan_register.extract_section` weiter greift — ob der *Wortlaut* der sechzehn
  Punkte seither identisch blieb, laesst sich nur durch Ausfuehren von
  `plan_register.verify` feststellen, was diese Seite nicht getan hat.

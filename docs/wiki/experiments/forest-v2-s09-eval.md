---
title: Forest v2 s09 — Eval-Harness
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s09_eval
---
# Forest v2 s09 — Eval-Harness

Slice s09 ist das Messgeruest des Forest-v2-Vorprogramms: ein eingefrorener,
isolierter, lesender Harness, der **irgendeinen** Retriever auf einem
eingefrorenen Aufgabensatz unter **einem** Budget misst. Der Paket-Docstring
sagt die Abgrenzung in einem Satz: nichts hier ist produktionsfaehig, nichts
im Kernel importiert es, und es promoviert nichts (Masterplan Abschnitt 1,
Abschnitt 10 als Gate-2-Vorarbeit, Abschnitt 13 als Ehrlichkeitsregel).

Im Bild von Kernel/Ikarus/Ariadne gehoert s09 zur **Ariadne-Evaluationsseite**:
es ist die Instanz von "unabhaengige Evaluatoren entscheiden, ob Evidenz gilt"
(Invariante 4) fuer die Retrieval-Frage. Die Slices s07 (BM25), s08
(Graph-Baselines), s10 (Kill-Kriterien) und s11 (Fusion) haengen als
Produzenten oder Konsumenten daran, ohne dass s09 sie importiert — der
Abhaengigkeitspfeil zeigt immer auf den Harness.

Gemessen 2026-09-05: 23 `.py`-Dateien, 6009 Zeilen; davon 12
Implementierungsdateien mit 3688 Zeilen und 11 Testdateien mit 2321 Zeilen.
Die Tests liegen **im Slice selbst**, nicht unter `tests/`.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../experiments/forest_v2/s09_eval/__init__.py) | Nur Docstring: Isolationsaussage und Modulkarte. | — |
| [`contract.py`](../../../experiments/forest_v2/s09_eval/contract.py) | Der Adaptervertrag, den jeder gemessene Retriever erfuellt. | `Candidate`, `QueryView`, `Retriever`, `Budget`, `ContractViolation`, `validate_ranking`, `load_retriever` |
| [`gitio.py`](../../../experiments/forest_v2/s09_eval/gitio.py) | Lesende Git-Plumbing-Schicht: `log`, `rev-parse`, `ls-tree`, `cat-file`. | `Commit`, `GitError`, `rev_parse`, `read_history`, `list_tree`, `read_blobs`, `log_name_only`, `read_rename_stats`, `make_preimage_clone`, `contains_commit` |
| [`taskset.py`](../../../experiments/forest_v2/s09_eval/taskset.py) | Baut und friert den ersten Aufgabensatz aus der echten Repository-Historie ein. | `SCHEMA`, `SELECTION`, `Case`, `plane_of`, `PLANE_BY_SUFFIX`, `scrub`, `scrub_basename`, `digest_of`, `build`, `load`, `main`, `DEFAULT_PATH` |
| [`taskset_xplane.py`](../../../experiments/forest_v2/s09_eval/taskset_xplane.py) | Baut und friert einen **zweiten** Satz ein, ausgewaehlt so, dass die Vier-Ebenen-Frage ueberhaupt stellbar wird. | `SCHEMA`, `ANCHOR`, `SELECTION`, `SELECTION_RULES`, `STRUCTURAL_GUARDS`, `RULE_REASONS`, `RULES_DROPPED`, `TWIN_PLANES`, `XCase`, `twin_planes`, `seam_stems`, `digest_of`, `build`, `load`, `main` |
| [`tokens.py`](../../../experiments/forest_v2/s09_eval/tokens.py) | Ein Tokenizer, geteilt von Scrubber und jedem Retriever. | `word_tokens`, `path_tokens`, `TokenCache` |
| [`metrics.py`](../../../experiments/forest_v2/s09_eval/metrics.py) | Recall@k und MRR ueber den eingefrorenen Gold-Satz, makro **und** mikro. | `CaseScore`, `Aggregate`, `score_case`, `aggregate`, `raw_table` |
| [`stats.py`](../../../experiments/forest_v2/s09_eval/stats.py) | Unsicherheit fuer zwanzig Faelle: Perzentil-Bootstrap, gepaarte Vergleiche. | `Interval`, `PairedDelta`, `bootstrap_mean`, `paired_delta`, `comparison_table`, `DEFAULT_RESAMPLES`, `DEFAULT_SEED` |
| [`retrievers.py`](../../../experiments/forest_v2/s09_eval/retrievers.py) | Die fuenf Baselines, die der Slice selbst mitbringt. | `RandomUniform`, `PathLexical`, `Bm25`, `Bm25ContentOnly`, `RecencyPrior`, `default_suite`, `BM25_K1`, `BM25_B` |
| [`harness.py`](../../../experiments/forest_v2/s09_eval/harness.py) | Der Runner: misst jeden Retriever auf dem eingefrorenen Satz unter einem Budget. | `BlobStore`, `PreimageIsolation`, `build_universe`, `comparison_payload`, `run`, `main`, `RESULTS_DIR`, `VARIANTS`, `EXTRA_VARIANTS`, `TIMING_DISCLAIMER` |
| [`run_xplane_harness.py`](../../../experiments/forest_v2/s09_eval/run_xplane_harness.py) | Duenne Sicht, die denselben `harness.run` auf den Cross-Plane-Korpus zeigen laesst. | `main`, `RESULTS_DIR`, `VARIANTS` |
| [`to_s10.py`](../../../experiments/forest_v2/s09_eval/to_s10.py) | Adapter: aus einem fertigen s09-Lauf ein s10-Kill-Input machen. | `SCHEMA_ID`, `PRIMARY_METRIC`, `INCLUDED_ARMS`, `EXCLUDED_ARMS`, `FUSION_MECHANISM`, `FUSION_RETRIEVER_ROLES`, `FUSION_RETRIEVER_ATTESTATION`, `AdapterError`, `build_arm`, `build_fusion_arm`, `gold_planes_for_cases`, `build_kill_input`, `main` |

Nicht-Python im Verzeichnis: `taskset.json` und `taskset_xplane.json` (die
beiden eingefrorenen Korpora) sowie `results/` mit `raw.json` und
`s10_adapter_runs/`.

## Der Vertrag: budgetgleich, und der Kandidat sieht seinen Schluessel nicht

`contract.py` erzwingt zwei Eigenschaften strukturell statt in Prosa:

1. **Der Retriever kommt nicht an seinen Loesungsschluessel.** `rank()`
   bekommt eine `QueryView` und ein Kandidatenuniversum; keins von beiden
   traegt den Gold-Satz. Gold lebt nur im eingefrorenen Aufgabensatz, den der
   Harness haelt. Das ist die Evidenzgrenze des Masterplans (Invarianten 3
   und 4) im Kleinen.
2. **Jeder Retriever bekommt dasselbe Budget.** Dasselbe
   Kandidatenuniversum-Objekt, dieselbe Byte-Deckelung pro Datei, dieselben
   Cutoffs. `Candidate.raw` haelt die gespeicherten Bytes, `Candidate.text`
   dekodiert und **kuerzt auf das Budget** — ein Retriever, der mehr liest als
   erlaubt, kann es schlicht nicht.

Ein Retriever ist jedes Objekt mit `name` und `rank`. Fremde Slices haengen
ueber `module:factory`-Pfade an (`load_retriever`); das Paket importiert sie
nie.

## Der Runner

`harness.run` macht "budgetgleich" konkret, weil die Formulierung leicht zu
behaupten und leicht zu faelschen ist:

- ein Universum pro Fall, einmal gebaut, von allen Retrievern **als dasselbe
  Objekt** gesehen;
- dieselbe Byte-Deckelung pro Datei (`Budget.content_budget_bytes`);
- dieselben Cutoffs, und das Ranking wird vor dem Scoren auf den groessten
  gekuerzt;
- Tokenisierung **einmal pro Fall vorgewaermt** und als geteilte
  Indexierungskosten ausgewiesen, damit Zeiten nicht von der Laufreihenfolge
  abhaengen;
- ein Ranking, das einen Pfad ausserhalb des Universums nennt oder einen Pfad
  wiederholt, **bricht den Lauf ab**, statt still zu punkten
  (`validate_ranking` → `ContractViolation`);
- ein ueber `--retriever` geladener Retriever wird standardmaessig gegen einen
  **Pre-Image-Bare-Clone** gemessen (`PreimageIsolation`, abschaltbar mit
  `--no-isolate-preimage`), sodass der Commit, dessen Diff der Loesungs-
  schluessel ist, im lesbaren Objektspeicher nicht nur unreferenziert, sondern
  **abwesend** ist.

**Zeiten sind hier keine validierte Eigenschaft.** `rank_seconds` und
`wall_seconds_total` sind Wanduhr auf einer geteilten Entwicklerbox; ein
Wiederholungslauf identischer Arbeit mass `bm25` mit 6,5 s gegen gespeicherte
26,8 s — Faktor 4,1, und das ist Last, nicht Algorithmus (Angaben aus dem
Modul-Docstring). `TIMING_DISCLAIMER` reist deshalb in der Nutzlast mit.

## Die beiden Korpora

### taskset.json — der erste Satz

Ein Fall ist ein Nicht-Merge-Commit. Die Query ist die Commit-Nachricht (was
ein Mensch in eigenen Worten wollte), das Gold sind die Dateien, die der
Commit geaendert hat **und** die im Elternbaum schon existierten. Das
Suchuniversum ist der Elternbaum — das Pre-Image, damit nichts aus der Zukunft
sichtbar ist.

Vier Ehrlichkeitsregeln stecken im Format statt in Prosa:

- **Eingefroren vor der Messung.** `build` schreibt einen sha256-Digest ueber
  die kanonische Fallliste; der Harness rechnet ihn nach und verweigert das
  Scoren eines Satzes mit abweichendem Digest.
- **Pfade ausserhalb des durchsuchbaren Universums fallen aus dem Gold**,
  statt still als Fehltreffer zu zaehlen. Das Feld heisst
  `gold_created_dropped` — laut Docstring ein aus Digest-Gruenden behaltener
  Fehlname, denn es sammelt alles ausserhalb des **zulaessigen** Universums;
  `dropped_breakdown` trennt die beiden Faelle ehrlich.
- **Jede Ablehnung wird gezaehlt.** `acceptance` haelt Nenner, Rate und Grund
  fest, weil die abgelehnte Population **nicht** zufaellig ist: sie wird von
  dateierzeugenden Commits dominiert.
- **Das Leck wird gemessen, nicht versteckt.** Commit-Nachrichten nennen sehr
  oft die Datei, die sie anfassen; jeder Fall traegt deshalb eine zweite,
  gescrubbte Query. `scrub` entfernt **alle** Gold-Pfad-Token inklusive
  Verzeichnisnamen und loescht damit jedes Pfadsignal; `scrub_basename` ist
  die Variante, die das Dateinamen-Echo **isoliert**. Nur die zweite erlaubt
  die Aussage "das war der Dateiname".

`SELECTION` ist die eingefrorene Auswahlregel (`history_limit` 1200,
`case_count` 20, `multi_file_target` 8, `require_python_change` True,
Reihenfolge `sha256(commit_sha)` aufsteigend). Der Kommentar daneben
korrigiert eine frueher dort stehende Behauptung ausdruecklich: die
Mehrdatei-Schicht sei "durch das Angebot gedeckelt" gewesen — tatsaechlich
stehen 18 zulaessige Mehrdatei-Commits einer Quote von 8 gegenueber. Die
8/12-Teilung ist eine **Wahl**, keine Decke, und `selection_census` im Record
haelt Angebot gegen Quote, damit die Behauptung nicht wieder driftet.

### taskset_xplane.json — der zweite Satz

Der erste Korpus **kann** ueber Cross-Plane-Struktur nichts entscheiden, und
das ist eine Messung, keine Meinung: von seinen 35 Gold-Slots sind 32 `.py`,
3 von 20 Faellen spannen mehr als eine Project-Twin-Ebene, genau einer beruehrt
die Knowledge-Ebene, keiner die Type-Ebene, und die Gate-1-Form (Python,
Markdown und CSV bewegen sich zusammen) hat keinen Vertreter. Ein
Cross-Plane-Arm gegen diesen Korpus lieferte ein gepaartes MRR-Delta von
exakt +0,000000 mit Bootstrap-CI [0, 0] — ein Instrument, das seine eigene
Blindheit meldet (alle Zahlen aus dem Modul-Docstring).

`taskset_xplane.py` ist **additiv**: es liest, baut, friert oder nummeriert
`taskset.json` nicht neu, weil Slice s07 diesen Korpus per Inhalt pinnt. Der
neue Korpus hat eigenes Schema, eigenen Digest, eigene Auswahlregel und einen
festen `ANCHOR`-Commit. Bemerkenswert an der Regelmenge:

- `SELECTION_RULES` sind drei disjunkte Ablehnungsgruende, in fester
  Reihenfolge angewandt; `RULE_REASONS` legt zu jedem den gemessenen Grund
  bei, weil "ein Schwellwert ohne Begruendung eine Zahl ist, die jemand
  tunen wird, bis das Ergebnis besser aussieht".
- `STRUCTURAL_GUARDS` fuehrt `parent_tree_unreadable` **ausdruecklich nicht**
  als Regel: sie feuert in dieser Historie null Mal und kann damit keine
  Ablehnung demonstrieren. Sie bleibt als I/O-Zweig, weil "git konnte den
  Elternbaum nicht lesen" und "der Elternbaum enthaelt kein Gold" zwei sehr
  verschiedene Tatsachen sind.
- `RULES_DROPPED` haelt `min_message_chars>=24` als getestet-und-entfernt
  fest: 0 Ablehnungen bei 770 gold-tragenden Commits. Eine Regel, die nicht
  ablehnen kann, ist keine Regel — und wird entfernt statt bei null belassen.
- `require_python_change` fehlt **absichtlich**: die Regel des ersten Korpus
  loeschte still die gesamte `{data, knowledge}`-Schicht, also genau die
  reinste Cross-Plane-Form der Historie.

Der Docstring nennt die Grenze des Instruments selbst: der Korpus macht die
Vier-Ebenen-Frage **stellbar**, nicht die Antwort **interpretierbar**, solange
die Cross-Plane-Kanten dieses Repositories laut derselben Stelle alle eine
hartkodierte Evidenzkonstante tragen und eine absichtlich gefaelschte Kante
dasselbe `assurance='verified'`-Label bekam wie eine echte. Bis dieser
Verifier repariert ist, ist ein Gewinn auf diesem Korpus ein Gewinn fuer ein
Label, nicht fuer eine Ebene. Vergleiche [Twin](../architecture/twin.md) und
[Type-Graph](../architecture/type-graph.md).

## Baselines, Metriken, Unsicherheit

`retrievers.py` begruendet jede Baseline damit, welche Art getaeuscht zu
werden sie ausschliesst: `RandomUniform` ist der Boden; `PathLexical` matcht
**nur** Pfad-Token (gewinnt es, ist die Aufgabe Dateinamen-Echo, nicht
Retrieval); `Bm25` ist der klassische Fall; `Bm25ContentOnly` ist derselbe
ohne Pfad-Token, und die Luecke zu `Bm25` ist genau der Anteil, der Dateiname
statt Datei war; `RecencyPrior` ignoriert die Query vollstaendig (kann ein
query-bewusstes Verfahren ein query-blindes nicht schlagen, tut die Query
nicht die Arbeit). Alle deterministisch, reine Stdlib.

`metrics.py` berichtet Recall@k **makro und mikro**, weil beide verschiedene
Fragen beantworten und nur die schmeichelhafte zu zitieren die Gewohnheit ist,
gegen die der Harness existiert. MRR ist durch den groessten Cutoff begrenzt:
eine Gold-Datei, die im gemessenen Fenster nie auftaucht, traegt 0 bei, nicht
einen kleinen Schwanzwert, den der Lauf gar nicht angesehen hat.

`stats.py` haengt an jede Kopfzahl ein Perzentil-Bootstrap-Intervall
(`DEFAULT_RESAMPLES` 2000, fester `DEFAULT_SEED`), und jeder Vergleich zweier
Retriever ist **gepaart** — ueber dieselben Faelle resampelt, weil die Faelle
sich weit staerker unterscheiden als die Retriever auf einem Fall. Der
Docstring grenzt die Aussage selbst ab: die Intervalle quantifizieren
Stichprobenrauschen ueber *diese* Faelle aus *diesem* Repository und sagen
nichts ueber Transfer.

## Der Weg nach s10

`to_s10.py` schliesst die Luecke, die s10 selbst in seinen "Honest caveats"
benannt hat. Die Richtung ist einseitig und begruendet: `s10_kill` erzwingt
mechanisch, dass jede Datei unter ihm **nur** die Standardbibliothek
importiert, also kann der Adapter nicht dort liegen. Auf dieser Seite haelt er
dieselbe Disziplin in der Richtung, die er waehlen kann: er importiert
`experiments.forest_v2.s10_kill` nicht, sondern fuehrt Schema-ID und
Rollenstrings als handgepflegte Konstanten. Genau eine Stelle bricht das
offengelegt — `test_to_s10.py` importiert das echte Schema, um die emittierte
JSON gegen den **echten** Evaluator-Vertrag zu validieren statt gegen eine
handkopierte Kopie.

Was der Adapter **verweigert**: einen `full`- oder `fusion`-Arm aus einer
ehrlichen Baseline zu erfinden, und eine Baseline in eine Rolle zu zwingen,
die ihren Mechanismus falsch beschreibt. Von den fuenf mitgelieferten
Baselines haben nur zwei eine s10-Rolle, die benennt, was sie messen
(`bm25` lexikalisch, `random_uniform` als Zufallskontrolle); die anderen drei
stehen namentlich mit Grund in `EXCLUDED_ARMS`.

## Trust-Grenzen / Effekte

- **Read-only als Regel, mit zwei benannten Ausnahmen.** In `gitio.py` geht
  jeder Aufruf gegen ein fremdes Repository durch `_run`, das jedes Verb
  ausserhalb `{log, rev-parse, ls-tree, cat-file}` verweigert. Der Docstring
  korrigiert dabei seine eigene frueher zu starke Behauptung in zwei
  Richtungen: `read_blobs` ging fruehe an der Schranke vorbei (es braucht
  stdin) und geht jetzt hindurch, und `make_preimage_clone` **schreibt** —
  absichtlich, nur in ein vom Aufrufer benanntes, noch nicht existierendes
  Zielverzeichnis, nie in das Quell-Repository. Die praezise Aussage lautet:
  keine Funktion dieses Moduls kann das Repository mutieren, aus dem sie
  liest.
- **Zwei effektbehaftete Einstiegspunkte, beide unabgedeckt.** `harness.main`
  schreibt `results/raw.json` (ausser mit `--no-write`), `run_xplane_harness.
  main` schreibt `results/raw_xplane.json`. Beide Docstrings sagen selbst,
  dass `experiments/` **nicht** im `HARNESS_PACKAGES`-Scan von
  [`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py)
  liegt, dieser Schreibvorgang also ungescannt ist. Die Luecke ist als
  Eskalation vermerkt, nicht hier geschlossen — sie zu schliessen hiesse
  Kernel-Policy zu aendern, und das ist Owner-Arbeit. Kein Netz-Egress, kein
  Spend, kein Modellaufruf; gelesen werden Git-Plumbing und Dateiinhalt.
- **Kein Kernel-Import.** Nichts unter `daedalus/` importiert diesen Slice.

## Tests

Elf Testdateien liegen im Slice selbst (gemessen 2026-09-05: 2321 Zeilen).

| Testdatei | Deckt ab |
| --- | --- |
| [`test_contract.py`](../../../experiments/forest_v2/s09_eval/test_contract.py) | Die beiden strukturellen Garantien des Vertrags |
| [`test_gitio.py`](../../../experiments/forest_v2/s09_eval/test_gitio.py) | Die Git-Schicht; entstanden aus Mutationstests (M15: `read_blobs` an der Schranke vorbei) |
| [`test_harness.py`](../../../experiments/forest_v2/s09_eval/test_harness.py) | Budgetgleichheit und die Anti-Schummel-Regeln, gegen ein synthetisches Universum |
| [`test_metrics.py`](../../../experiments/forest_v2/s09_eval/test_metrics.py) | Die Scoring-Regeln, besonders die leicht schoenzurechnenden |
| [`test_retrievers.py`](../../../experiments/forest_v2/s09_eval/test_retrievers.py) | Determinismus, Vertragstreue, und was jede Baseline zur Kontrolle macht |
| [`test_stats.py`](../../../experiments/forest_v2/s09_eval/test_stats.py) | Bootstrap-Eigenschaften — ein still zu enges Intervall ist schlimmer als keins |
| [`test_taskset.py`](../../../experiments/forest_v2/s09_eval/test_taskset.py) | Dass der Freeze wirklich bindet |
| [`test_taskset_xplane.py`](../../../experiments/forest_v2/s09_eval/test_taskset_xplane.py) | Verhalten von Artefakt und Builder, ausdruecklich **nicht** Textsuche im Quelltext |
| [`test_tokens.py`](../../../experiments/forest_v2/s09_eval/test_tokens.py) | Die drei Regeln des geteilten Tokenizers, alle drei zuvor mutationstest-blind |
| [`test_to_s10.py`](../../../experiments/forest_v2/s09_eval/test_to_s10.py) | Der Adapter; bricht an genau einer offengelegten Stelle die eigene Importdisziplin |
| [`test_published_numbers.py`](../../../experiments/forest_v2/s09_eval/test_published_numbers.py) | Pinnt jede veroeffentlichte Zahl an das Artefakt, aus dem sie stammt: liest `results/raw.json` und die Census-Felder von `taskset.json` und vergleicht mit den in der README zitierten Zahlen |

Ausserhalb des Slices deckt nichts unter `tests/` dieses Verzeichnis ab
(gemessen 2026-09-05: `grep -rl "s09_eval" tests/` liefert nichts).

## Verwandt

- [Forest v2 (Uebersicht)](forest-v2.md)
- [Forest v2 s07 — BM25-Baseline](forest-v2-s07-bm25.md) — pinnt `taskset.json`
  per Inhalt und misst denselben Korpus mit eigenem Index
- [Forest v2 s08 — Graph-Baselines](forest-v2-s08-graph-baselines.md)
- [Forest v2 s10 — Kill-Kriterien](forest-v2-s10-kill.md) — der Konsument von
  `to_s10.py`
- [Forest v2 s11 — Fusion](forest-v2-s11-fusion.md) — der Grund fuer
  `build_fusion_arm` und die Pre-Image-Isolation
- [Forest v2 s02 — Type-Plane](forest-v2-s02-types.md)
- [Twin](../architecture/twin.md), [Type-Graph](../architecture/type-graph.md),
  [Data-Layer](../architecture/data-layer.md),
  [Knowledge-Layer](../architecture/knowledge-layer.md) — die vier Ebenen, die
  `twin_planes` auf Dateisuffixe abbildet
- [Eval](../architecture/eval.md) — die Produktionsseite der Evaluation
- [Ariadne](../architecture/ariadne.md)
- [Graph-Delta als Fitness](../graph-delta-as-fitness.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Was genau in `results/s10_adapter_runs/` liegt und ob es der
  aktuelle Stand ist; ich habe die Verzeichnisliste gesehen, aber die
  Inhalte nicht gelesen.
- **Ungeklaert:** Ob `harness.main` je gegen den Cross-Plane-Korpus gelaufen
  ist. `run_xplane_harness.py` existiert genau deshalb, weil `harness.main`
  `taskset.load` hartkodiert und `XCase` die von `harness.run` erwartete
  `Case.query(variant)`-Methode nicht hat; ob der Lauf stattfand, sagt der
  Code nicht.
- **Ungeklaert:** `EXTRA_VARIANTS` (`scrubbed_basename`) existiert im Harness,
  aber ob dieser Variantenlauf in `results/raw.json` enthalten ist, habe ich
  nicht geprueft.
- **Abweichung Code/Doku:** Zwei Docstrings dieses Slices korrigieren
  ausdruecklich frueher dort stehende falsche Aussagen —
  `gitio.py:9-23` (die "kein Kommando kann mutieren"-Behauptung) und
  `taskset.py:100-107` (die "durch das Angebot gedeckelte" Mehrdatei-Schicht).
  Wer aeltere Notizen oder Berichte zu s09 liest, findet dort noch die alten
  Formulierungen.

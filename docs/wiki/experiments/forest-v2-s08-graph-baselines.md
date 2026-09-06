---
title: Forest v2 s08 - Graph-Baselines
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s08_graph_baselines
---
# Forest v2 s08 - Graph-Baselines

`experiments/forest_v2/s08_graph_baselines` ist der **EXPERIMENT**-Slice, der
zwei der von Masterplan Gate 3 geforderten Baselines implementiert und zwei der
Kill-Kriterien aus Abschnitt 14 messbar macht:

* **(a) Code-only-Graph-Retrieval** -- `CodeGraphRetriever`. BM25 ueber die
  Code-Ebene setzt Saatpunkte, von denen aus die Import-/Call-Nachbarschaft
  gelaufen wird; ein Modul, das kein Query-Token beruehrt, kann trotzdem
  auftauchen, weil es neben einem liegt, das eines beruehrt. Die Kontrolle ist
  `LexicalRetriever` ueber dieselbe Code-Ebene mit abgeschaltetem Graphen, damit
  jeder Unterschied der Graph ist und nichts sonst.
* **(b) Vier getrennte Einzel-Ebenen-Indizes ohne Fusion** -- zwei Arme, weil
  "keine Fusion" nicht festlegt, wie die Antwortplaetze geteilt werden.
  `FourPlaneNoFusionRetriever` teilt **ein** Budget von k Plaetzen im
  Round-Robin auf; `UnionNoFusionRetriever` gibt jeder Ebene ihr eigenes Top-k
  und konkateniert. Keiner der beiden vergleicht einen Score ueber Ebenen
  hinweg -- das ist die Invariante der Baseline.

`SinglePlaneOracleRetriever` bekommt das Gold-Label gereicht und meldet die
unerreichbare Obergrenze dieses Designs: ein Massstab, kein System.
`CodeGraphRetriever(rewire=True)` liefert den degree-preserving randomisierten
Graphen, den Masterplan Abschnitt 14 als Kill-Kriterium nennt -- ein Graph-Gewinn,
der die Verkabelungs-Randomisierung ueberlebt, ist keiner.

Alles hier ist reine Standardbibliothek, read-only, ohne Schreibvorgang,
Subprozess, Netz oder Modellaufruf. `s08_api.py` importiert bewusst **keinen**
Repository-Code.

Gemessen 2026-09-05: 5 Modul-Dateien mit 1941 Zeilen plus
`test_s08_graph_baselines.py` (759 Zeilen) im selben Verzeichnis.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`s08_api.py`](../../../experiments/forest_v2/s08_graph_baselines/s08_api.py) | Der geteilte Retrieval-Vertrag, dem jede Baseline dieses Slices gehorcht: ebenen-getaggtes Dokument, Treffer mit eigener Begruendung, `Retriever`-Protokoll, Rangmetriken. Macht s07 und s08 vergleichbar, weil beide dieselbe Signatur beantworten. | `Document`, `Hit`, `Retriever`, `Query`, `EvalResult`, `rank_of`, `evaluate`, `idf`, `PLANES` |
| [`s08_corpus.py`](../../../experiments/forest_v2/s08_graph_baselines/s08_corpus.py) | Baut vier Einzel-Ebenen-Dokumentmengen und den Code-only-Graphen. Der Umfang ist ausdruecklich deklariert, weil ein undeklariertes Korpus jede Retrieval-Zahl unfalsifizierbar macht. | `Corpus`, `ModuleFacts`, `build_corpus`, `corpus_digest`, `cross_plane_edge_census`, `parse_module`, `module_name`, `tokenize`, `split_identifier`, `data_document_text` |
| [`s08_queries.py`](../../../experiments/forest_v2/s08_graph_baselines/s08_queries.py) | Ein mechanisch abgeleiteter Query-Satz mit je einem Gold-Dokument. Jede Familie hat eine **benannte** Verzerrung, damit die Zahlen richtig gelesen statt geglaubt werden. | `build_queries`, `build_non_code_queries`, `build_extended_queries`, `by_family`, `gold_plane_mix`, `leakage_note`, `QUERY_SEED`, `NONCODE_QUERY_SEED`, `MAX_PER_FAMILY` |
| [`s08_retrievers.py`](../../../experiments/forest_v2/s08_graph_baselines/s08_retrievers.py) | Die zwei geforderten Baselines plus ihre Kontrollen. | `Bm25Index`, `LexicalRetriever`, `CodeGraphRetriever`, `FourPlaneNoFusionRetriever`, `UnionNoFusionRetriever`, `SinglePlaneOracleRetriever` |
| [`s08_selftest.py`](../../../experiments/forest_v2/s08_graph_baselines/s08_selftest.py) | Der RAW-Selbsttest: ein JSON-Objekt auf stdout, nichts geschrieben. Druckt das gebaute Korpus, den Query-Satz mit Leakage-Notiz und die rohen Trefferzahlen jedes Retrievers pro Query-Familie. Bruchteile stehen **neben** den Zaehlungen, nie statt ihrer. | `main`, `rank_vector`, `crosstab`, `crosstabs_by_cutoff`, `reachable_planes`, `informative_queries`, `KS`, `STARVATION_KS`, `SENSITIVITY_ALPHAS` |
| [`test_s08_graph_baselines.py`](../../../experiments/forest_v2/s08_graph_baselines/test_s08_graph_baselines.py) | Die Testsuite des Slices, im Experimentverzeichnis statt unter `tests/`. | (pytest-Funktionen) |

## Das Korpus, so wie es deklariert ist

| Ebene | Quelle | Reduktion |
| --- | --- | --- |
| `code` | `*.py` unter `daedalus`, `tools`, `runs` | ein Dokument pro Modul |
| `type` | dieselben Module | deklarierte Parameter-/Rueckgabe-Annotationen, annotierte Zuweisungen, Klassenbasen |
| `data` | `.json`, `.csv`, `.toml`, `.yaml` unter `daedalus`, `docs` und im Repository-Root | nur **Form**: JSON-Key-Pfade, CSV-Header, YAML/TOML-Schluessel -- nie Werte |
| `knowledge` | `*.md` unter `docs`, `runs` und im Root | Volltext |

Zwei Ehrlichkeitsklauseln stehen im Docstring von `s08_corpus.py`:

* Die Type-Ebene ist ein **Proxy** aus Quell-Annotationen, keine eigenstaendige
  Artefaktklasse -- der Baum traegt keine `.pyi`.
* `runs/**/*.json` ist ausgeschlossen (der Docstring nennt 3329 Receipt-Dateien):
  das sind Evidenzartefakte, nicht die Data-Ebene. Die Werte-Freiheit der
  Data-Dokumente hat einen zweiten Grund: ein wertefreier Index kann kein
  Geheimnis versehentlich in ein Experimentartefakt tragen.

`corpus_digest` macht das gebaute Korpus reproduzierbar identifizierbar,
`cross_plane_edge_census` zaehlt die Kanten, die ueber Ebenengrenzen laufen.

## Die Query-Familien und ihre benannten Verzerrungen

| Familie | Query | Gold | Verzerrung |
| --- | --- | --- | --- |
| `symbol` | ein eindeutig definierter Funktions-/Klassenname, in Woerter zerlegt | die definierende Code-Datei | maximal lexikalisch-freundlich; das Gold-Dokument enthaelt die Query woertlich. Sanity-Boden. |
| `docstring` | erster Satz des Docstrings dieses Symbols, ohne die Symbol-Tokens | dieselbe Code-Datei | noch aus dem Gold-Text, aber die staerkste lexikalische Bruecke ist gekappt |
| `knowledge_ref` | eine Prosazeile aus einer Markdown-Datei, die ein eindeutiges Code-Symbol in Backticks nennt, ohne dieses Symbol | die definierende **Code**-Datei | die einzige echt ebenenuebergreifende Familie: Query aus der Knowledge-Ebene, Antwort in der Code-Ebene |

Die Stichprobe ist deterministisch (`QUERY_SEED = 20260818`, sortierte
Kandidatenreihenfolge, `MAX_PER_FAMILY = 200`); derselbe Selbsttest auf
derselben Revision reproduziert denselben Query-Satz exakt.
`build_non_code_queries` (`NONCODE_QUERY_SEED = 20260819`) ergaenzt spaeter
Familien mit Gold **ausserhalb** der Code-Ebene, damit Ebenen-Routing
ueberhaupt etwas richtig machen kann; die eingefrorenen 600 Queries bleiben
davon unberuehrt und werden daneben berichtet.

## Was der Selbsttest berichtet

`s08_selftest.main` schreibt ein einziges JSON-Objekt auf stdout mit
`classification: EXPERIMENT` und `measurement: RAW`. Enthalten sind unter
anderem: Korpus-Statistik und Digest, Query-Satz mit `leakage_note`,
Graph-Kennzahlen (Module, Kanten, isolierte Module, mittlerer Grad, `alpha`,
`hops`, `seeds`), pro Retriever und Query-Familie die `EvalResult`-Zeilen bei
den Cutoffs `KS = (1, 5, 10)`, die Oracle-Obergrenze, die Pro-Ebenen-Recall des
No-Fusion-Arms, sowie drei ausdrueckliche **Korrekturen**:

1. **Round-Robin-Aushungerung.** Round-Robin ueber vier Ebenen gibt dem
   Code-Index bei k=10 die Plaetze 1, 5 und 9. Weil in den eingefrorenen 600
   jedes Gold ein Code-Dokument ist, kann dieser Arm nie besser sein als das
   Top-3 des Code-Index. Beide Seiten dieser Identitaet werden gedruckt, damit
   die Behauptung pruefbar und nicht nur behauptet ist. Die zusaetzlichen
   Cutoffs stehen in `STARVATION_KS`.
2. **Hypothese (b) gegen den benannten Vergleichspunkt.** Die eingefrorene
   Teilspezifikation nennt "einen Index ueber denselben Dokumenten"
   (`bm25_single_index_all_planes`), der gelandete Report hatte aber gegen
   `bm25_code_only` verglichen. Die Korrektur berichtet beides und deklariert
   ihre Materialitaetsregel offen als **nachtraeglich** gesetzt:
   `|delta hits@10| >= 5 %` des Query-Satzes **und** gleiches Vorzeichen bei
   k=1, 5 und 10. Die Richtung ist Teil der Behauptung, also gibt es drei
   Verdikte -- `CONFIRMED`, `REFUTED` (materiell, aber entgegengesetzt) und
   `NULL`.
3. **Gold-Labels ausserhalb der Code-Ebene** als Ergaenzung neben den
   eingefrorenen 600.

`SENSITIVITY_ALPHAS` variiert das Mischungsgewicht des Graph-Retrievers, damit
ein Ergebnis nicht an einem einzelnen Hyperparameter haengt.

## Trust-Grenzen / Effekte

Keine. Das Verzeichnis enthaelt keinen Schreibpfad, keinen `begin_effect`, keine
Registry-Zeile, keinen Subprozess und keinen Netzaufruf. `s08_corpus.py` oeffnet
Dateien lesend und schliesst sie. Der Selbsttest druckt und schreibt nichts.
Der Vergleich ist per Konstruktion budgetgleich: identischer Query-Satz,
identische Cutoffs, identischer Tokenizer, ein Prozess, keine Modellaufrufe,
kein Spend -- die Bedingung, die Masterplan Abschnitt 14 fuer jede vergleichende
Kampagne verlangt.

Als `EXPERIMENT` im Sinne von Masterplan Abschnitt 1 und 15 gilt: keine
Promotion, kein Produktionspfad, negatives Ergebnis wird aufbewahrt.

## Tests

Die Testsuite liegt **im Experimentverzeichnis**, nicht unter `tests/`:

| Testdatei | Deckt ab |
| --- | --- |
| [`test_s08_graph_baselines.py`](../../../experiments/forest_v2/s08_graph_baselines/test_s08_graph_baselines.py) | Korpusbau, Tokenizer, Query-Ableitung, alle Retriever-Arme, Rangmetriken und die Determinismus-Zusagen. |

Ausserhalb dieses Verzeichnisses (gemessen 2026-09-05) referenziert keine Datei
unter `tests/` den Slice; er wird ueber seinen eigenen Selbsttest gefahren.

## Verwandt

* [Forest v2](forest-v2.md) -- der uebergeordnete Experimentbaum.
* [Forest v2 s07 - BM25](forest-v2-s07-bm25.md) -- die lexikalische Baseline,
  mit der s08 denselben `Retriever`-Vertrag teilt.
* [Forest v2 s11 - Fusion](forest-v2-s11-fusion.md) -- der Fusions-Arm, gegen
  den die No-Fusion-Baselines hier den Kontrast liefern.
* [Forest v2 s06 - Cards](forest-v2-s06-cards.md) -- Node Cards als
  Retrieval-Einheit.
* [Fourfold Hybrid Retrieval](fourfold-hybrid-retrieval.md) -- der
  Hybrid-Retrieval-Slice.
* [Twin](../architecture/twin.md) -- die vier Ebenen, die das Korpus nachbaut.
* [Type-Graph](../architecture/type-graph.md),
  [Data-Layer](../architecture/data-layer.md),
  [Knowledge-Layer](../architecture/knowledge-layer.md),
  [Observation-Layer](../architecture/observation-layer.md) -- die
  Ebenen-Seiten des Wikis.
* [Graph-Delta als Fitness](../graph-delta-as-fitness.md)
* [Wiki-Index](../index.md)

## Ungeklaert

* **Ungeklaert:** Die tatsaechlichen Zahlen. Diese Seite beschreibt, **was**
  gemessen wird; der Selbsttest wurde fuer diese Seite nicht ausgefuehrt, also
  steht hier kein Ergebnis und kein Kill-Verdikt.
* **Ungeklaert:** Wo der "landed report" liegt, gegen den Korrektur 2 sich
  richtet. Der Docstring nennt ihn, aber keinen Pfad.
* **Ungeklaert:** Ob die Korpus-Deklaration ("3329 Receipt-Dateien unter
  `runs/`") heute noch stimmt -- diese Zahl stammt aus dem Docstring und wurde
  hier nicht nachgemessen.

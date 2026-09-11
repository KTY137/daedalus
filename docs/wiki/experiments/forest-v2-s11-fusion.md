---
title: Forest v2 — s11 Fusion
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s11_fusion
---
# Forest v2 — s11 Fusion

Slice s11 ist der erste echte Cross-Plane-Score-Fusion-Retriever dieses
Programms. Bis dahin war jeder gemessene Arm in `forest_v2` entweder ein
einzelner Index, ein Ein-Ebenen-Index oder eine Verkettung von Ergebnissen pro
Ebene, die nie einen Score einer Ebene gegen den einer anderen hält -- s08
sagt das in seinen eigenen Klassennamen (`FourPlaneNoFusionRetriever`,
`UnionNoFusionRetriever`). Im Kernel/Ikarus/Ariadne-Bild ist das ein isoliertes
Experiment neben der Produktionslinie: reines stdlib, keine Schreibpfade,
keine Modellaufrufe, kein Import aus `daedalus/` und kein Import aus
`daedalus/` hierher. Der Zweck ist ein Messinstrument für zwei Kill-Kriterien
des Masterplans -- 14.1 (`full` schlägt `code_only`/BM25) und 14.3 (vier
getrennte Indizes verhalten sich wie Fusion) --, die vorher mangels Arm gar
nicht entscheidbar waren.

Der Slice ist bewusst klein: zwei Python-Module plus eine Testdatei,
gemessen 2026-09-05 insgesamt 594 Zeilen, davon 339 im Retriever-Modul.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../experiments/forest_v2/s11_fusion/__init__.py) | Paket-Docstring: verweist auf die eingefrorene Teilspezifikation im `forest_v2`-README und hält fest, dass die Kontrakt-Typen von `s09_eval` wiederverwendet und nicht neu implementiert werden. | -- |
| [fusion_retrievers.py](../../../experiments/forest_v2/s11_fusion/fusion_retrievers.py) | Der Mechanismus: pro Ebene ein eigener BM25-Pass, danach Reciprocal Rank Fusion über die Rangpositionen. Enthält außerdem die beiden Vergleichsarme. | `FusionRetriever`, `CodeOnlyRetriever`, `SeparateIndicesRetriever`, `BM25_K1`, `BM25_B`, `RRF_K`, `RETURN_K`, `FUSION_PLANES` |
| [test_fusion_retrievers.py](../../../experiments/forest_v2/s11_fusion/test_fusion_retrievers.py) | Zehn Prüfungen des Mechanismus, siehe Abschnitt Tests. | -- |

Nicht öffentlich, aber tragend sind die vier internen Schritte in
`fusion_retrievers.py`: `_partition` (Kandidatenuniversum in Ebenen-Buckets
zerlegen), `_document` (Tokenzählung aus Inhalt plus Pfad-Token),
`_score_plane` (Lehrbuch-BM25 über genau einen Bucket, Rückgabe als
`(path, score)`-Paare) und `_rrf_combine` (die Kombination, die nie einen
`Candidate` sieht).

## Der Mechanismus

1. **Wirklich getrennte Indizes.** `_partition` teilt in `FUSION_PLANES`
   (`code`, `data`, `knowledge`), `_score_plane` fährt über jeden Bucket einen
   unabhängigen BM25-Pass mit eigener Term-Frequenz, eigener
   Dokumentfrequenz-Tabelle und eigener IDF. Ein Term, der in der
   Knowledge-Ebene selten und in der Code-Ebene häufig ist, bekommt zwei
   verschiedene IDF-Werte -- genau das, was ein gemeinsamer Index nicht kann,
   weil er pro Term nur eine IDF über das ganze Korpus hat.
2. **Ranglisten pro Ebene in der Hand.** `FusionRetriever.rank` baut
   `plane_scores` als echte, bewertete Listen je Ebene und legt sie vor jeder
   Kombination auf `last_plane_scores` ab. Die Behauptung "der Retriever
   hält Scores pro Ebene, bevor er kombiniert" ist damit prüfbar statt nur
   behauptet.
3. **Reciprocal Rank Fusion.** `_rrf_combine` summiert
   `1 / (RRF_K + rank_p(d))` über alle Ebenen, die ein Dokument zurückgeben,
   mit `RRF_K = 60`. RRF kombiniert *Ränge*, nicht Rohscores -- s08 hält selbst
   fest, dass vier BM25-Skalen nicht kommensurabel sind. Ein Pfad, der in einer
   Ebene fehlt, trägt aus dieser Ebene nichts bei; er wird nicht als
   Rang-Unendlich bestraft.

> **Extern:** RRF und der Standardwert `k = 60` stammen aus Cormack, Clarke &
> Buettcher, "Reciprocal Rank Fusion outperforms Condorcet and individual Rank
> Learning Methods", SIGIR 2009. Der Wert wird im Code unverändert übernommen
> und ausdrücklich nicht auf ein günstiges Ergebnis hin durchprobiert.
> Quelle: https://dl.acm.org/doi/10.1145/1571941.1572114

`BM25_K1` (1.5) und `BM25_B` (0.75) sind dieselben Konstanten wie in
`s09_eval.retrievers.Bm25`; der Slice ist also kein anderer Ranker, sondern
nur ein engerer Dokumentbereich plus Fusion. Jeder Unterschied zur
Gesamtkorpus-Baseline ist damit Ebenen-Routing, nicht ein anderes
Scoring.

## Die drei Arme

| Klasse | Rolle im Kill-Register | Verhalten |
| --- | --- | --- |
| `FusionRetriever` (`name = "fusion_rrf"`) | `full` und `fusion` | drei Ebenen-Indizes, RRF-Kombination; zählt in `returned_plane_counts` je Query-Variante mit, wie viele der obersten `RETURN_K` Treffer in welcher Ebene lagen |
| `CodeOnlyRetriever` (`name = "code_only_bm25"`) | `code_only` | derselbe `_score_plane`-Pass, aber nur über die Code-Ebene; keine zweite Rangliste zum Kombinieren |
| `SeparateIndicesRetriever` (`name = "separate_indices_bm25"`) | `separate_indices` | baut dieselben drei Indizes und hängt die besten Treffer jeder Ebene in fester, deklarierter Reihenfolge aneinander; kein Score wird je über Ebenen hinweg verglichen |

Die Reihenfolge in `SeparateIndicesRetriever` ist ein Konstruktorargument und
ein offen genannter Prior, kein verstecktes Detail: s08 hat für den eigenen
Union-Arm 491/600 mit Code zuerst und 4/600 mit Code zuletzt gemessen.

## Was ausdrücklich nicht erreicht wird

- **Type.** Kein Slice dieses Programms hat je ein Type-Ebenen-Artefakt auf
  Dateigranularität erzeugt (s02, s08, die s09-Fortsetzung und
  `s09_eval/to_s10.py` protokollieren dieselbe Lücke unabhängig voneinander).
  Es gibt nichts zu indizieren.
- **Presentation** (`.html`/`.css`). In `s10_kill/schema.py` überhaupt keine
  der vier Ebenen, also nicht deklarierbar. Es wird auch nicht heimlich in
  `code` oder `knowledge` gefaltet: das würde `combines_planes` und
  `returned_plane_counts` falsch berichten. Der offen bezahlte Preis steht im
  Modul-Docstring (13 von 483 Gold-Slots im Cross-Plane-Korpus) und im
  `forest_v2`-README (13 von 475). **Ungeklärt:** die beiden Zahlen für die
  Größe des Gold-Sets widersprechen einander; welche die aktuelle ist, geht
  aus dem Code nicht hervor.
- **Falsifikator.** Zeigen die gemessenen `returned_plane_counts` weniger als
  zwei Ebenen mit Rückgaben, verweigert der Adapter den Arm und
  14.3 bleibt `UNDECIDABLE`. Der Mechanismus muss real sein, nicht deklariert.

## Gemessenes Ergebnis

Der Lauf vom 2026-08-24 (Zahlen aus `experiments/forest_v2/README.md`, nicht
von mir nachgemessen) schickte alle drei Arme durch dieselbe
s09-Harness- und s10-Evaluator-Kette, nur die Variante `raw`:

| | Cross-Plane (88 Fälle) | Primär (20 Fälle) |
| --- | --- | --- |
| Abdeckung | 2 von 16 | 1 von 16 |
| 14.1 `full_beats_code_only_and_bm25` | INCONCLUSIVE | UNDECIDABLE |
| 14.3 `four_indices_equal_fusion` | INCONCLUSIVE | INCONCLUSIVE |

Der Fortschritt ist, dass beide Kriterien von "Arm fehlt" auf "Arm da, Evidenz
reicht nicht" gewandert sind -- die erste von null verschiedene Abdeckung, die
ein realer Lauf in diesem Programm erzeugt hat. Es ist kein Gewinn für den
Vier-Ebenen-Prior: `INCONCLUSIVE` ist ausdrücklich kein Bestehen, der Lauf
deklariert einen Seed statt der vom Plan verlangten 5--10, und auf dem primären
Korpus verweigert 14.1, weil die Ebenen, die Fusion von `code_only`
unterscheiden, dort null Gold-Labels tragen.

## Trust-Grenzen / Effekte

Keine. Beide Module sind reines stdlib, ohne Schreibpfad, Netzwerk,
Subprozess oder Modellaufruf; `begin_effect` kommt hier nicht vor. Geschrieben
wird nur von den aufrufenden Harness-Einstiegen in `s09_eval`, und deren
Schreibziel bleibt `experiments/forest_v2/s09_eval/results/`. Kein Modul unter
`daedalus/` importiert diesen Slice; er kann also weder Policy noch Evaluator
noch Promotion berühren.

## Tests

[test_fusion_retrievers.py](../../../experiments/forest_v2/s11_fusion/test_fusion_retrievers.py)
enthält gemessen 2026-09-05 zehn Testfunktionen, die genau die Behauptungen
oben angreifen: die RRF-Arithmetik von Hand nachgerechnet, das Ignorieren
einer Ebene ohne Treffer, der Unterschied zwischen Pro-Ebene-IDF und einem
gemeinsam gepoolten Index, Fusion nach Konfidenz gegen Verkettung nach fester
Reihenfolge, `CodeOnlyRetriever` gibt nie einen Nicht-Code-Pfad zurück, die
Gruppierung von `SeparateIndicesRetriever`, die Akkumulation und die Kappung
von `returned_plane_counts`, das Halten echter Pro-Ebenen-Scores vor der
Kombination, und dass Type und Presentation nie indiziert werden. Unter
`tests/` existiert keine Datei, die diesen Slice nennt (geprüft per
`grep -rln "s11_fusion" tests/`); die Absicherung liegt vollständig im
Experimentverzeichnis, dazu ein Test in `s10_kill`, der eine
Fehletikettierung eines Arms als "fusion" abfängt.

## Verwandt

- [Forest v2](forest-v2.md) -- die Experimentlinie und ihr README, das die
  eingefrorene Teilspezifikation und die Rohausgaben hält.
- [s09 eval](forest-v2-s09-eval.md) -- Kontrakt-Typen (`Candidate`,
  `QueryView`), Tokenizer und die Harness, die diese Arme lädt.
- [s10 kill](forest-v2-s10-kill.md) -- das Kill-Register, das 14.1 und 14.3
  bewertet.
- [s07 BM25](forest-v2-s07-bm25.md) und
  [s08 graph baselines](forest-v2-s08-graph-baselines.md) -- die Arme, die
  ausdrücklich keine Fusion sind.
- [Forest v2 — tensor embeddings](forest-v2-tensor-embeddings.md) -- das
  Experiment, das seine RRF-Baseline aus genau diesem Mechanismus kopiert.
- [Structcore](../architecture/structcore.md) und
  [Twin](../architecture/twin.md) -- die produktive Repräsentation, gegen die
  diese Linie misst.
- [Graph delta as fitness](../graph-delta-as-fitness.md),
  [Wiki-Index](../index.md).

## Ungeklärt

- Ob `fusion_rrf` je mit mehr als einem Seed oder mit der Variante `scrubbed`
  gelaufen ist, geht aus dem Code nicht hervor; das README nennt nur den
  Ein-Seed-Lauf über `raw`.
- Der Kommentar an `RETURN_K` sagt, die Konstante müsse mitwandern, wenn
  sich das eingefrorene Budget in `s09_eval.contract` ändert. Eine
  mechanische Kopplung dafür habe ich nicht gefunden.

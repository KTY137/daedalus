# Arme J und K — schlägt der Twin normale Verifikation?

Datum: 2026-08-25. Substrat: `project_tct` (`liquid-shell @5037471`), 411
Quelldateien, 37 an diesem Tag erzeugte Wiki-Seiten.
Artefakte: `arm_j.json`, `arm_k.json`, `bench_tct_after.json`, `graph_tct_*.json`.

---

## 1. Antwort

**Ja — aber nicht als Tensor.**

| Verfahren | R@1 | R@10 | R@25 | Training nötig |
| --- | --- | --- | --- | --- |
| Zufall | — | 0,024 | — | — |
| `grep` (exact token) | 0,012 | 0,042 | 0,119 | nein |
| **Tensor (ComplEx, gelernt)** | 0,007 | **0,022** | 0,052 | ja |
| Struktur allein (`doc_neighbour`) | 0,059 | 0,333 | 0,470 | nein |
| **BM25** | **0,167** | 0,482 | 0,643 | nein |
| **BM25 + Struktur (RRF)** | 0,095 | **0,601** | **0,768** | nein |

168 Anfragen, identisch für alle Verfahren. Aufgabe: eine Wiki-Seite verlinkt
die Quelldatei, die sie beschreibt — finde sie, ohne den Dateinamen zu kennen.
Ground Truth sind von Menschen geschriebene Markdown-Links, **nicht**
Namensgleichheit. Aus der Anfrage sind alle Backtick-Spans, Linkziele und
Dateinamen-Wortbestandteile entfernt.

**Der Gewinn ist +24,7 % relativ bei R@10 und +19,4 % bei R@25**, ohne ein
trainiertes Gewicht, ohne Hyperparameter, ohne Tuning (RRF mit dem
Standardwert k=60).

**Der Verlust an der Spitze ist real:** R@1 fällt von 0,167 auf 0,095. Wer genau
einen Treffer braucht, nimmt BM25 allein; wer eine kurze Liste zum Durchsehen
will, nimmt die Fusion.

## 2. Was `doc_neighbour` wirklich ist

Ein **anfrageunabhängiger Prior**. Es liest den Fragetext nicht, sondern rangiert
Dateien danach, von wie vielen *anderen* Seiten sie verlinkt werden. Die eigene
Seite ist ausgeschlossen, es gibt also keinen Durchgriff auf die
zurückgehaltene Kante.

Das ist ein legitimes und in der Informationssuche übliches Mittel (dieselbe
Rolle wie ein PageRank-Prior), aber es ist **kein Verstehen**. Die Fusion ist
„lexikalische Relevanz × strukturelle Wahrscheinlichkeit". Wer sie als
semantische Leistung des Twins verkauft, überzeichnet.

## 3. Warum der Tensor verliert

Nicht wegen der Implementierung — Arm J benutzt PyKEEN, nicht eigenen Code, und
die Aufgabe ist fair gestellt: der Holdout ist eine **Kante**, kein Knoten;
20 % der `documents_file`-Kanten bleiben im Training, damit das Modell die
gefragte Relation kennt; alle Zielknoten behalten ihre Code-Kanten.

Der Grund ist struktureller Art:

1. **BM25 liest Evidenz, die unabhängig vom Graphen existiert** — die Wörter.
   Der Tensor kann nur Struktur benutzen.
2. **Die strukturelle Verbindung ist zwei Hops lang** (Seite → Konzept → Code),
   und ein bilineares Modell bewertet Tripel einzeln; es läuft keine Pfade.
3. **33 Trainingsbeispiele** der gefragten Relation sind wenig. Aber BM25
   brauchte null und erreichte das Zwanzigfache. Eine Lücke dieser Größe
   schließt kein Hyperparameter.

## 4. Der Weg dorthin — vier eigene Modellierungsfehler

Die Cross-Plane-Überlebensrate im 3-Kern, dieselbe Messung, viermal korrigiert:

| Stand | Überlebensrate | was falsch war |
| --- | --- | --- |
| erste Fassung | **0,0 %** | Erwähnungen **pro Datei** modelliert → jede hat genau zwei Kanten und stirbt zwangsläufig |
| konzeptbasierte Knoten | 26,0 % | — |
| + 37 Wiki-Seiten | 31,5 % | — |
| + Links zeigen auf `code:module` statt auf einen eigenen `knowledge:file`-Knoten | **38,3 %** | der bewussteste Cross-Plane-Akt eines Autors verband die Ebenen gar nicht |

Die erste Zahl stand als Befund über das Repository in `RESULTS_ARM_FGHI.md`.
Sie war eine Aussage über meinen Knotenentwurf. Korrigiert und dort vermerkt.

## 5. Was das Wiki messbar bewirkt hat

| | ohne Wiki | mit Wiki |
| --- | --- | --- |
| Doku → Quelldatei-Kanten | 47 | **542** |
| `documents` (Konzept → Code) | 1 153 | **1 499** |
| Wissensebene im 3-Kern | 968 | **1 437** |
| **auswertbare Benchmark-Anfragen** | **0** | **168** |

Die letzte Zeile ist die wichtigste: vor dem Wiki war die Frage nicht messbar.
Es gab in `project_tct` **keinen einzigen** Markdown-Link auf eine Quelldatei.

## 6. Wo der Wert des Twins wirklich liegt

Nach allem Gemessenen, in dieser Reihenfolge:

1. **Der Verifizierer** (`daedalus/wiki/verify.py`). Deterministische Prüfung
   jeder Doku-Behauptung gegen den Baum. Fand in der *bestehenden* Doku 84 tote
   Links und Verweise auf Dateien, die es nicht gibt; fing in der neuen Doku zwei
   erfundene Symbolnamen, die kein Korrekturlesen gefunden hatte.
2. **Die Struktur als Prior** — +25 % über BM25, kostenlos.
3. **Der Generierungslauf** — er hat die Wissensebene überhaupt erst erzeugt und
   dabei als Nebenertrag echte Codedefekte gefunden (u. a. ein grünes
   „Applied" für ein Kommando, das das Gerät nie erreicht).

**Nicht** in einem gelernten Embedding. Das ist gemessen und nicht knapp.

## 7. Was das Urteil umstoßen würde

- Ein Modell, das **Pfade** benutzt (R-GCN, NodePiece, pfadbasierte Verfahren)
  statt ein bilineares Tripel-Modell. Die Zwei-Hop-Diagnose in §3.2 ist der
  konkrete Angriffspunkt.
- Ein **dichterer** Twin: 58,3 % der Knoten kommen genau einmal vor. Der Hebel
  ist Extraktion (Aufrufgraph, Typinferenz, SQL-Lineage), nicht das Modell.
- Ein **Korpus über viele Repositories**, wo dieselben Motive wiederkehren.
  Innerhalb eines Repositories gibt es für ein Embedding wenig zu verallgemeinern.

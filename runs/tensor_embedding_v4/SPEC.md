# EXPERIMENT `tensor-embedding-v4` — Leap of Faith: das Gewinn-Regime suchen

Datum der Einfrierung: 2026-08-25, vor jeder Messung.
Klassifikation: `EXPERIMENT` (§1, §15 des Masterplans). Gate 0. `PRIOR` §6.
Owner-Entscheidung: „trust of faith — nimm an, dass Tensor-Embedding worth ist,
geh full nuts", 2026-08-25. Vorgänger: v1–v3 (Arm A–K), Endstand dort:
gelernter Tensor R@10 = 0,022 gegen BM25 0,474 auf identischen Anfragen.

**Umkehrung der Beweislast, ausdrücklich:** v1–v3 versuchten zu widerlegen.
v4 nimmt an, dass es ein Gewinn-Regime gibt, und sucht es. Das ist legitim,
solange die Zahlen berichtet werden, wie sie fallen — und die Win-Conditions
VOR dem Lauf feststehen. Sie stehen hier.

## Win-Conditions (eine genügt)

- **A** Ein Tensor-Familien-Verfahren schlägt BM25 allein: R@10 > 0,474 auf den
  135 zurückgehaltenen (Seite → Quelldatei)-Paaren.
- **B** Fusion mit Tensor schlägt Fusion mit roher Struktur: R@10 > 0,601 auf
  den 168 Benchmark-Anfragen.
- **C** Im Abkürzungs-Regime (vokal-gestrippte Bezeichner, wo jede lexikalische
  Methode laut v1 auf Zufall fällt) erreicht der struktur-trainierte
  Text-Encoder mindestens das Dreifache der Trigramm-Baseline UND mindestens
  R@10 = 0,15.

Trifft keine: die ehrliche Antwort bleibt „deterministischer Twin + BM25", und
das wird so geschrieben.

## Arme

- **L (+O):** Text-informierter Tensor. `e = tanh(W·φ_trigramm)`, geteiltes W,
  relations-diagonale Modulation, InfoNCE über alle Trainingskanten. Eval 1:
  die 135 Paare, Kandidaten = die 411 realen Quelldateien (dieselben wie BM25 —
  Kandidatenmengen-Symmetrie ist Pflicht). Eval 2 (=O): Abkürzungs-Retrieval
  auf echten Symbolnamen des Twins, Encoder gegen rohes Trigramm.
  Leckage-Regel: die Stem-Tokens der Seite werden aus ihrem eigenen
  Feature-Vektor entfernt (Spiegel des Bench-Scrubs); beide Varianten berichten.
- **M:** Pfad-Materialisierung. `mentions∘documents`- und Symbol→Modul-Ketten
  als direkte Kanten, dann exakt das Arm-J-Protokoll (ComplEx, seed 17,
  Split-Seed 31, 20 % keep). Misst nur den Zwei-Hop-Effekt.
- **N:** Personalized PageRank vom Anfrageknoten (anfrage-ABHÄNGIG, im
  Unterschied zu `doc_neighbour`), allein und in RRF mit BM25, auf denselben
  Anfragen wie Arm K.

## Konstanten

Split identisch zu Arm J: `numpy.default_rng(31)`, Permutation über die 168
`documents_file`-Kanten in Dateireihenfolge, erste 20 % im Training.
Substrat: `runs/tensor_embedding_v3/triples_tct_after2.tsv` +
`experiments/tensor_embedding/bench_crossplane.py`. Budget je Arm: < 15 min,
dim ≤ 128, Epochen ≤ 60. Isolation wie gehabt: neue Dateien, kein Import aus
`daedalus/`, keine Promotion, Fixture unberührt.

## Verifikation

Jedes Ergebnis wird von einem unabhängigen Prüfer adversarial gelesen, mit der
Fehlerliste dieses Tages als Checkliste: Split nicht repliziert,
Kandidatenmengen-Asymmetrie, Dateinamen-Leckage in Features, zurückgehaltene
Kanten im Training, anfrageunabhängiger Prior als Verstehen verkauft,
Zufallsniveau nicht ausgewiesen, gesättigte Tabellen.

## Addendum (2026-08-25, vor Arm-Q-Messung eingefroren): Arm Q — Feld-Expansion

Owner-Idee: „field expansion, aber fuer Code". Drei Lesarten; Lesart 1
(Potenzreihe) deckt Arm N/P bereits, Lesart 2 (spektral) bleibt unter dem
Ceiling-Vorbehalt zurueckgestellt, Lesart 3 wird Arm Q:

**Arm Q — graphgestuetzte Anfrage-Expansion.** Anfragetokens im Twin verankern,
Namen struktureller Nachbarn gedaempft in die BM25-Anfrage einspeisen, kein
Lernen. Leckage-Verriegelung: der Knoten der Anfrage-Seite und ALLE seine
Kanten werden vor der Expansion aus dem Graphen entfernt.

**Win-Condition Q (jetzt eingefroren, eine genuegt):**
- Q1: BM25+Expansion schlaegt BM25 allein bei R@10 auf den 168 Anfragen
  (> 0,482) — Win-Condition A ueber Expansion statt Fusion.
- Q2: BM25+Expansion hebt R@1 ueber BM25 allein (> 0,167) — was die
  Popularitaets-Fusion nachweislich NICHT konnte (0,095).

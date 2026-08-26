# EXPERIMENT `tensor-embedding-v2` — Stelligkeit

Datum der Einfrierung: 2026-08-25, vor jeder Messung
Klassifikation: `EXPERIMENT` (§1, §15). Aktives Gate: 0. `PRIOR` §6.
Vorgänger: `runs/tensor_embedding_v1/` — dort feuerte K1, Rang 1 des Surveys
wurde widerlegt. Rang 2 (n-äre Tensoren) blieb ungetestet. Das ist v2.
Owner-Entscheidung: „experimentier solange bis sich das lohnt", 2026-08-25.

**Was diese Anweisung hier heißt:** weiterlaufen, bis die Frage entschieden ist,
nicht bis sie positiv ausfällt. Die Kill-Kriterien unten sind vor dem Lauf
festgeschrieben und werden nicht nachverhandelt.

---

## 1. Die eine Frage

v1 zeigte: für einen **festen Rollensatz** schlägt Slot-Konkatenation die
Bindung überall. Konkatenation hat aber eine Grenze, die v1 nicht berührt hat:
sie vergleicht immer **paarweise**. Eine Aussage über drei Dinge gleichzeitig
kann sie nur als Summe von drei Zweier-Aussagen bilden.

> Gibt es Cross-Plane-Bindungen, bei denen paarweise Evidenz systematisch in die
> Irre führt und nur die gemeinsame Übereinstimmung aller Beteiligten die
> richtige Antwort gibt? Und wenn ja: wie häufig sind sie in echten Daten?

Die zweite Hälfte der Frage ist die wichtigere. Ein Tensor, der auf konstruierten
3-Wege-Fällen gewinnt, ist wertlos, wenn echte Bindungen paarweise zerlegbar
sind.

## 2. Verfahren im Vergleich

Keines wird trainiert. Alle arbeiten auf denselben kompositionellen
Trigramm-Vektoren aus v1.

| Name | Bewertung eines Kandidatentripels (q, c₁, c₂) |
| --- | --- |
| `exact` | Namensgleichheit, Zufallsniveau als Referenz |
| `pairwise_sum` | `cos(q,c₁) + cos(q,c₂) + cos(c₁,c₂)` — was Slots leisten |
| `pairwise_min` | `min` derselben drei — strengster paarweiser Aggregator |
| `trilinear` | `Σ_r q_r·c₁_r·c₂_r` — die n-äre Verallgemeinerung des Kosinus |

`pairwise_min` ist ausdrücklich dabei, damit `trilinear` nicht gegen einen
absichtlich schwachen Gegner antritt. Ein Minimum bricht ebenfalls ein, sobald
ein Paar nicht passt. Wenn `pairwise_min` genügt, kauft die trilineare Form
nichts, und das ist ein eigenständiges Kill-Kriterium.

## 3. Substrat

Synthetischer Korpus, N Konzepte, jedes realisiert in drei Ebenen (Typ-Feld,
CSV-Spalte, Schema-Property) mit Name und Datentyp. Ground Truth ist die
Konstruktion.

Zwei Regime, als Dynamikbereich:

- **`decomposable`** — Namen eindeutig, paarweise Evidenz genügt. Hier darf
  `trilinear` *nicht* gewinnen. Gewinnt es doch, ist der Aufbau verzerrt.
- **`joint`** — Ablenker, bei denen genau **eine** der beiden Kandidatenseiten
  zum Namen der Anfrage passt und die andere nicht. Paarweise Summe bleibt hoch,
  gemeinsame Übereinstimmung nicht. Das ist der halb ausgeführte Rename.

Ablenkeranteil wird von 0 bis 0,8 durchgefahren. Zusätzlich der Rename-Fall aus
v1 (Präfix/Suffix auf der Anfrage), weil er der reale Gate-1-Defekt ist.

## 4. Kill-Kriterien, vor dem Lauf festgeschrieben

- **K5** `trilinear` schlägt `pairwise_sum` im Regime `joint` nicht (Abstand
  kleiner als 5 Prozentpunkte bei höchstem Ablenkeranteil).
- **K6** `pairwise_min` erreicht, was `trilinear` erreicht. Dann ist der Gewinn
  ein Aggregator-Effekt, kein Stelligkeits-Effekt, und braucht keinen Tensor.
- **K7** `trilinear` gewinnt auch im Regime `decomposable`. Dann misst der
  Aufbau nicht Stelligkeit, sondern einen Artefakt.
- **K8** Der Anteil echter, nicht paarweise zerlegbarer Bindungen in den
  vorhandenen `fourfold.json`-Claims des Repositories ist null. Dann ist der
  Effekt, falls vorhanden, für Daedalus gegenstandslos. **Dieses Kriterium wird
  gegen echte Daten geprüft, nicht gegen den synthetischen Korpus.**

K8 ist das Kriterium, das die Spur wirklich beendet, und es ist unabhängig
davon, wie K5–K7 ausgehen.

## 5. Budget und Isolation

numpy und Standardbibliothek. Kein Netz, kein Modell, keine Kosten. Schreibt nur
nach `runs/tensor_embedding_v2/`. Code unter `experiments/tensor_embedding/`,
importiert nichts aus `daedalus/`. Zielzeit unter 120 s. Feste Seeds; zweimaliger
Lauf muss identische Ergebnisse liefern, Wanduhr-Felder ausgenommen (Mangel M4
aus v1).

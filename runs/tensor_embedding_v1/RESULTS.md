# EXPERIMENT `tensor-embedding-v1` — Ergebnisse

Datum: 2026-08-25
Spec: `SPEC.md` daneben, eingefroren vor der Ausführung
Artefakte: `arm_a.json`, `arm_b.json`
Substrat Arm B: `tests/fixtures/ignition/voltage`, Baum-Digest `c15c3bfdf0514522`
(aus `arm_b.json`, nicht abgeschrieben — die erste Fassung dieser Zeile trug
eine erfundene Ziffernfolge und wurde gegen das Artefakt korrigiert)
Umgebung: Python 3.10, numpy 1.26.4, Windows
Determinismus: beide Arme zweimal gelaufen, Ergebnisse identisch
(`arm_a` `0275f96052ff2d49`, `arm_b` `d1c435721a4a7766`, jeweils ohne das
Wanduhr-Feld — siehe Mangel M4)

**Alle Zahlen unten sind `MEASURED` auf dieser Maschine an diesem Tag.**
Arm B/Fixture hat vier Anfragen und neun Knoten. Das ist eine Demonstration.
Die einzige Zahl mit Dynamikbereich steht im synthetischen Sweep und in der
Erweiterung von Arm A.

---

## 1. Urteil in drei Sätzen

1. **Die Tensor-Algebra verliert gegen schlichte Felder.** Slot-Konkatenation
   schlägt oder egalisiert HRR-Binding an **allen 45 gemessenen Punkten**. Nicht
   knapp: an den engen Punkten steht HRR bei 0,04 und Slot bei 1,00.
2. **Der eine echte Gewinn gehört nicht dem Tensor.** Gegen exakten
   String-Vergleich gewinnen die Vektor-Repräsentationen den Gate-1-Rename-Fall
   mit 1,00 gegen 0,00 — aber die naive gepoolte Variante ohne jede Rollen-
   struktur gewinnt genauso hoch. Der Gewinn kommt von **Zeichen-Trigrammen**,
   nicht von Bindung.
3. **Rang 1 meiner eigenen Empfehlung ist damit widerlegt.** Der Survey
   (`docs/research/TENSOR_EMBEDDING_SURVEY_2026-08-25.md` §4) stufte
   TPR/HRR-Binding für Node Cards als „echtes Potenzial" ein. Entbindbarkeit ist
   real (100 % Revisions-Rückgewinnung), aber Konkatenation liefert sie
   kostenlos und verlustfrei mit.

---

## 2. Arm A — Bindungstreue gegen Slots

### 2.1 Eingefrorenes Gitter (200 Versuche, Vokabular 1000)

HRR erreicht 1,0000 in 28 von 30 Zellen. Die zwei Ausnahmen: `d=256, k=6` →
0,9975 und `d=256, k=8` → 0,9819. Slot-Konkatenation erreicht 1,0000 in **allen
30** Zellen.

**Das Gitter war gesättigt und damit nicht lesbar.** Eine Tabelle ohne
Dynamikbereich trägt keine Information. Deshalb der Erweiterungs-Sweep.

### 2.2 Erweiterungs-Sweep (50 Versuche, nach der Sättigung ergänzt)

Nicht Teil der eingefrorenen Spec; ausdrücklich als Ergänzung markiert, weil er
nach dem Blick auf das gesättigte Gitter entworfen wurde.

| Slot-Breite `d/k` | HRR-Genauigkeit | Slot-Genauigkeit |
| --- | --- | --- |
| 128 | 1,0000 | 1,0000 |
| 64 | 1,0000 | 1,0000 |
| 32 | 0,9825 – 0,9919 | 1,0000 |
| 16 | 0,7425 – 0,7538 | 1,0000 |
| 8 | 0,3377 – 0,3500 | 1,0000 |
| 4 | 0,1181 – 0,1186 | 1,0000 |
| 2 | 0,0403 | 0,9997 |

HRR-Genauigkeit hängt sauber an `d/k` und ist dimensionsübergreifend
reproduzierbar (bei `d/k = 16` liefern d=256/k=16, d=512/k=32 und d=1024/k=64
0,7425 / 0,7538 / 0,7462). Slot bleibt bis zur Breite 2 bei 1,0000.

**K1 feuert.** Erste Klausel eindeutig: gleiche Treue bei gleicher oder
kleinerer Breite, an jedem Punkt. Zweite Klausel („Bindung kann nichts, was
Konkatenation nicht kann") ist **ungetestet** — variable Stelligkeit,
Überlagerung einer unbekannten Zahl von Elementen und holistische Operationen
ohne Dekodierung wurden nicht gemessen. Für den Node-Card-Fall wie in §6 des
Masterplans spezifiziert (fester Rollensatz, k ≈ 5–8) ist die erste Klausel
entscheidend.

---

## 3. Arm B — Cross-Plane auf dem echten Fixture

### 3.1 Fixture, vier Anfragen, Zufallsniveau 0,50

| Szenario | `exact` | `pooled` | `concat` | `bound` |
| --- | --- | --- | --- | --- |
| `aligned` (wie auf Platte) | 1,00 | 1,00 | 1,00 | 1,00 |
| `renamed` (halber Gate-1-Rename) | **0,50** | 1,00 | 1,00 | 1,00 |

`aligned` diskriminiert nichts — die Namen stimmen dort per Konstruktion
überein, was schon vor dem Lauf notiert wurde (SPEC §6a). `renamed` ist der
Fall, für den Gate 1 existiert, und exakter Vergleich fällt dort auf
Zufallsniveau.

Aus dem gebundenen Vektor zurückgewonnen, über alle neun Knoten:
**Ebene 9/9, Revision 9/9** (gegen 99 Ködern). H-A und B4 bestätigt — aber
`concat` liest dieselben Felder trivial aus dem Slice.

### 3.2 Synthetischer Sweep (n = 200, Zufallsniveau 0,005)

Die einzige Zahl in Arm B mit Dynamikbereich.

| Namensstörung | `exact` | `pooled` | `concat` | `bound` |
| --- | --- | --- | --- | --- |
| keine | 1,000 | 1,000 | 1,000 | 1,000 |
| Präfix (`bias_x`) | 0,000 | 1,000 | 1,000 | 1,000 |
| Suffix (`x_v2`) | 0,000 | 1,000 | 1,000 | 1,000 |
| Abkürzung (Vokale weg) | 0,000 | 0,040 | 0,045 | 0,030 |
| fremder Name | 0,000 | 0,010 | 0,005 | 0,015 |

Drei Ablesungen:

- **Präfix/Suffix ist vollständig gelöst** — und zwar von allen drei
  Vektorvarianten gleich gut. Das ist der Gate-1-Rename-Fall.
- **`pooled ≈ concat ≈ bound` überall.** Die vor dem Lauf notierte Vorhersage
  (SPEC §6a) trifft zu. Rollenstruktur kauft für Retrieval nichts.
- **Abkürzung und Fremdname sind ungelöst**, bei allen Verfahren, auf oder
  knapp über Zufallsniveau. Trigramm-Ähnlichkeit ist der gesamte Mechanismus.
  Semantik ist hier nirgends im Spiel.

---

## 4. Kill-Kriterien gegen die Zahlen

| | Kriterium | Ergebnis |
| --- | --- | --- |
| **K1** | Slot erreicht gleiche Treue bei gleicher/kleinerer Dimension | **FEUERT** (45/45 Punkte), zweite Klausel ungetestet |
| **K2** | `bound` schlägt `exact` bei B3 nicht | feuert nicht — 1,00 gegen 0,00 unter Rename |
| **K3** | Revision nicht ≥ 99 % rückgewinnbar | feuert nicht — 100 % bei k=4, d=1024, 99 Köder |
| **K4** | `pooled` erreicht B1 und B2 bereits gemeinsam | **feuert für Retrieval**, nicht für Dekodierbarkeit: `pooled` gleicht `bound` in jeder Retrieval-Zeile, kann aber Ebene und Revision überhaupt nicht zurückgeben |

## 5. Was das für die Spur bedeutet

- **Rang 1 des Surveys ist widerlegt.** TPR/HRR-Binding für Node Cards bringt
  gegenüber getrennten Feldern nichts und kostet Treue. Kein Grund, es zu bauen.
- **Rang 2 (n-äre Tensoren für Cross-Plane) ist unberührt.** Dieses Experiment
  hat Stelligkeit nicht getestet. Der Survey-Eintrag bleibt bedingt offen.
- **Die einzige gemessene Lücke ist die Abkürzung.** Alle Verfahren fallen dort
  auf Zufallsniveau. Genau dort — und nur dort — müsste eine *gelernte*
  Repräsentation ihren Preis rechtfertigen. Das ist eine schärfere Frage als
  die, mit der das Experiment begann, und sie ist billig zu stellen.
- **Der Bucket-(b)-Ceiling-Lauf bleibt die Vorbedingung** für jede Fortsetzung.
  Er ist weiterhin nicht gelaufen.

## 6. Mängel dieses Experiments, alle eigene

Aufbewahrte Negativevidenz. Jeder wurde von einer Kontrolle gefunden, keiner
vom Autor beim Nachdenken.

- **M1 — Namensvorrat zu klein.** Der erste Generator zog zwei Silben aus zwölf
  = 144 mögliche Namen für 200 Felder. Dubletten machten `concat` und `bound` zu
  0,525. Gefunden, weil die Kontrolle `exact` im Modus „keine Störung" 0,210
  statt 1,000 zeigte. Behoben auf drei Silben mit erzwungener Eindeutigkeit.
- **M2 — der Pfad verriet die Antwort.** Kandidatenpfade waren `data/t{i}.csv`,
  Anfragepfade `src/m{i}.py`. Das gemeinsame Trigramm des Index gab `pooled`
  0,975, ohne dass ein Name verglichen wurde. Behoben: Pfade tragen nur noch die
  Ebene.
- **M3 — Budget gerissen.** Das Füller-Codebook wurde pro Versuch neu gezogen
  statt einmal pro Dimension: 6000 Ziehungen, die größte 32 MB. Der Lauf wurde
  nach 300 s abgeschossen und lieferte **gar nichts**, bei einem Spec-Budget von
  120 s. Nach der Korrektur: 21 s.
- **M4 — die Spec forderte, was das Artefakt nicht halten kann.** §5 verlangte
  byte-gleiche Ergebnisse bei zweimaligem Lauf, das Artefakt enthält aber ein
  Wanduhr-Feld. Determinismus ist ohne dieses Feld geprüft und bestätigt; die
  Forderung war falsch formuliert, nicht das Ergebnis.
- **M5 — das eingefrorene Gitter war gesättigt.** 28 von 30 Zellen auf 1,0000.
  Ohne den nachträglichen Erweiterungs-Sweep wäre aus Arm A gar keine Aussage
  ableitbar gewesen.

## 7. Was dieses Experiment nicht sagt

- Nichts über realen Korpus. Neun Knoten, ein Fixture, ein Rechner.
- Nichts über gelernte Embeddings. Hier wurde kein Modell trainiert und keines
  aufgerufen.
- Nichts über n-äre Zerlegung, Tucker, GETD oder temporale Tensoren.
- Nichts über Retrieval-Qualität unter Verifikationskosten.
- Es promoviert nichts und verändert keine Policy, keinen Evaluator, kein
  Ledger.

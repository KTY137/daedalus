# EXPERIMENT `tensor-embedding-v3` — Ergebnisse

Datum: 2026-08-25. Spec: `SPEC.md` daneben. Artefakte: `arm_d.json`, `arm_e.json`.
numpy 1.26.4, Python 3.10.

**Zwei Arme, zwei sehr verschiedene Ergebnislagen.** Arm D ist entschieden und
positiv. Arm E ist **nicht entschieden**, und der Grund liegt bei mir, nicht bei
der Sache. Beides steht hier gleichrangig, weil das Vermischen von „gemessen"
und „nicht zum Laufen gebracht" der teuerste Fehler wäre, den dieses Dokument
machen könnte.

---

## 1. Arm D — entschieden: die Welt ist nicht binär, das Schema ist es

Gemessen am echten Fixture `tests/fixtures/ignition/voltage`, gegen dessen
eigenes `fourfold.json`.

| Messung | Ergebnis |
| --- | --- |
| reale Feld-Manifestationen | 9 |
| davon im binären Claim-Vokabular **unbenennbar** | **3** |
| — konkret | `knowledge:wiki/Event.md#voltage`, `code:repository.py#parse_event.voltage`, `…#parse_event.id` |
| Ebenen, die auf Feldebene erreichbar sind | nur `type` und `data` |
| wahre Paare insgesamt | 16 |
| davon behauptet | 4 |
| nicht behauptet, ohne Berührung des Typ-Hubs | **9** |
| echte Stelligkeit der beiden Konzepte | **4 und 5** |

Das Vokabular kennt `type_field`, `csv_field`, `schema_field`. Code und Wissen
werden ausschließlich auf **Dateiebene** gebunden. Zwei von vier Ebenen sind
damit auf Feldebene strukturell ausgeschlossen, und `csv ↔ schema` ist nicht
aussprechbar — jede Aussage muss über den Typ-Hub laufen.

**Rename-Erkennung**, halber Gate-1-Rename (Python `bias_voltage`, CSV und
Schema `voltage`):

| Modell | gefundene Inkonsistenzen | Join nötig |
| --- | --- | --- |
| n-är | 1 (lokal, im Claim selbst) | nein |
| binär | 2 getrennte Paartreffer | **ja** |

Die Frage „ist dieser Rename vollständig?" ist im n-ären Modell eine Frage an
**einen** Claim. Im binären ist sie ein Join über mehrere, außerhalb der Claims.

**Damit ist v2s Schluss korrigiert.** v2 maß „alle zehn Claims sind binär,
also gibt es keine Stelligkeit". Richtig gemessen, falsch geschlossen: die
Claims sind binär, weil das Vokabular nichts anderes zulässt. Die Sachverhalte
haben Stelligkeit 4 und 5.

## 2. Der n-äre Claim (Vorschlag, nicht implementiert)

Ein Claim trägt beliebig viele Slots mit Rolle, Ebene und Knoten; Details in
`SPEC.md` §2. Drei Eigenschaften, die das heutige Vokabular nicht hat: kein
privilegierter Hub, lokale Konsistenzprüfung, offene Stelligkeit. Die
Invarianten bleiben unberührt — ein Claim ist `proposed`, bis ein unabhängiger
Verifier ihn prüft.

**Das ist ein Vorschlag zur Änderung am Twin.** Er ist hier nicht umgesetzt und
berührt kein Produktionsartefakt. Umsetzung wäre ein eigenes Work Packet.

## 3. Arm E — NICHT entschieden

Die Frage war: schlägt ein gelernter Tensorraum über n-ären Claims die
ungelernte Zeichenähnlichkeit beim Retrieval?

**Sie ist unbeantwortet.** Vier Implementierungsversuche, jeder mit einer
anderen, real gefundenen Ursache, keiner über Zufallsniveau.

| Modus | `exact` R@10 | `trigram` R@10 | `cp_binary` R@10 | `cp_nary` R@10 |
| --- | --- | --- | --- | --- |
| `none` | 1,000 | 1,000 | 0,007 | 0,013 |
| `mild` | 0,323 | 0,990 | 0,010 | 0,013 |
| `scramble` | 0,007 | 0,005 | 0,000 | 0,005 |

Zufallsniveau R@10 bei 1791 Knoten: 0,0056.

**Der Beweis, dass das Instrument schuld ist, nicht die Sache:**

```
ORACLE (kennt Container und Rolle, nicht das Konzept):  R@1 = 0,1868   R@10 = 1,0000
gelerntes Modell, bestes Ergebnis:                      R@1 = 0,007    R@10 = 0,013
```

Im Modus `scramble` tragen die Namen **kein** Signal; alles Erreichbare kommt
aus der Struktur. Aus der Struktur allein sind R@10 = 1,000 verfügbar. Mein
Modell erreicht 0,013.

**Deshalb wird hier kein Kill-Kriterium ausgewertet.** K9 bis K12 bleiben offen.
Zu sagen „K9 ist gefeuert, der Tensor schlägt Trigramme nicht" wäre eine
Behauptung über Tensoren auf Basis einer Messung, die nichts gemessen hat. Das
ist genau der Fehler, den dieses Projekt an anderen Instrumenten kritisiert.

## 4. Die vier Fehlversuche, aufbewahrt

Jeder hat eine echte Ursache und jede ist lehrreich:

- **M9 — Skalenkollaps.** Margin-Verlust auf dem rohen multilinearen Score. Bei
  Rang 48 und Init 0,1 ist das Produkt über fünf Slots ~1e-5, die Margin also
  konstant. Behoben durch Normalisierung des Kontextprodukts und InfoNCE.
- **M10 — die Aufgabe war induktiv.** Jeder Knoten gehörte zu genau einem
  Claim; das Zurückhalten eines Slots entfernte den Zielknoten vollständig aus
  dem Training. Sein Embedding blieb Zufallsinitialisierung. **Kein
  Embedding-Modell kann abrufen, was es nie gesehen hat** — Trigramme schon,
  weil sie den Oberflächennamen lesen. Behoben durch Container-Claims.
- **M11 — numerische Vergiftung.** Container-Claims haben ~27 Slots; das
  elementweise Produkt über 26 Faktoren der Größe ~0,14 ist ~1e-23 und nach der
  Normalisierung reines Gleitkommarauschen. Es verdarb jeden Gradienten.
  Behoben durch einen begrenzten, gezogenen Kontext.
- **M12 — die Aufgabe war fast unlösbar, und zwar durch meinen Zuschnitt.**
  Zunächst als „Ursache nicht gefunden" notiert; am selben Tag aufgeklärt durch
  den Test, der zuerst hätte laufen müssen: **kann der Trainer memorieren, was
  er trainiert hat?**

  | Aufbau (nichts zurückgehalten) | TRAIN R@1 | R@10 | Zufall@10 |
  | --- | --- | --- | --- |
  | Stelligkeit 3, 20 Konzepte | 0,950 | 1,000 | 0,167 |
  | Stelligkeit 3, 100 Konzepte | 0,830 | 1,000 | 0,033 |
  | Stelligkeit 4, 100 Konzepte | 0,383 | 0,985 | 0,025 |
  | Stelligkeit 4 + Container | 0,400 | 0,930 | 0,025 |

  Der Optimierer funktioniert. Es war nie ein Trainingsfehler, sondern ein
  **Generalisierungsfehler durch Aufgabenzuschnitt**: mein Holdout entfernte die
  einzige konzeptidentifizierende Kante. Übrig blieb die Container-Zugehörigkeit,
  und die bestimmt das Konzept nicht — sie grenzt nur auf sechs ein. Ich hatte
  eine nahezu unlösbare Aufgabe gebaut und ihr Scheitern für eine Aussage über
  Tensoren gehalten.

  **Lehre, die über den Fall hinausgeht:** der Memorierungstest kostet zwei
  Minuten und hätte drei Iterationen erspart. Ein Lernverfahren, das seine
  eigenen Trainingsdaten nicht wiederfindet, darf gar nicht erst auf die echte
  Aufgabe. Ein Lernverfahren, das sie wiederfindet und trotzdem versagt, hat ein
  Aufgabenproblem — und dann ist die Aufgabe zu prüfen, nicht das Modell.

  Konsequenz: Arm F (`arm_f_pykeen.py`) mit einem Korpus in der Form eines
  echten Twins — Realisierung **und** Lineage **und** Testabdeckung, so dass das
  Konzept nach dem Holdout identifizierbar bleibt — und mit PyKEEN statt
  eigenem Code.

**M10 ist über den Fehlversuch hinaus wichtig:** ein gelernter Tensorraum kann
nur wiederfinden, was er schon gesehen hat. Ein Twin wird pro Revision neu
gebaut; jedes neue Symbol, jede neue Spalte, jede neue Doku-Erwähnung ist ein
Kaltstart. Zeichenähnlichkeit hat dieses Problem nicht. Das ist ein struktureller
Nachteil gelernter Repräsentationen in genau diesem System und gilt unabhängig
davon, ob mein Trainer je läuft.

## 5. Was Arm E entscheiden würde

1. **Nicht selbst implementieren.** Der Survey sagte das in §7 — „PyKEEN …
   nicht selbst implementieren" — und ich habe es ignoriert und vier
   Iterationen darauf verwendet, den Grund für diesen Satz nachzustellen.
   PyKEEN braucht `torch` und einen Netzzugriff; das ist eine
   Owner-Entscheidung, keine, die ich still treffe.
2. **Vorher ein Gradienten-Check auf einer Aufgabe mit bekannter Antwort.** Ein
   Trainer, der eine triviale Aufgabe nicht löst, darf gar nicht erst auf die
   echte gelassen werden. Dieser Schritt hat gefehlt.
3. **Der Bucket-(b)-Ceiling-Lauf** bleibt unverändert die Vorbedingung dafür,
   dass die Frage überhaupt gestellt werden muss.

## 6. Was dieses Dokument nicht behauptet

- Nicht, dass gelernte Tensor-Embeddings für Retrieval nichts taugen. Das wurde
  hier **nicht** gemessen.
- Nicht, dass der n-äre Claim das Retrieval verbessert. Auch das wurde nicht
  gemessen — nur, dass das binäre Schema nachweislich Fakten verliert.
- Es promoviert nichts, ändert kein Produktionsartefakt und fasst das Fixture
  nicht an.

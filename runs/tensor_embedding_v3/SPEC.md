# EXPERIMENT `tensor-embedding-v3` — n-äre Claims und der Tensorraum

Datum: 2026-08-25. Klassifikation: `EXPERIMENT` (§1, §15). Gate 0. `PRIOR` §5, §6.
Vorgänger: v1 (Bindung verliert gegen Slots), v2 (Stelligkeit kauft nichts —
weil es keine gibt).
Owner-Richtung: „das fourfold graph model in einen high dimensional tensor space
embedden für knowledge retrieval", 2026-08-25.

---

## 1. Warum v2 die falsche Frage beantwortet hat

v2 maß: alle zehn Cross-Plane-Claims des Fixtures sind binär, also hat ein
n-ärer Tensor kein Objekt. Das stimmte — und war irreführend. Arm D hat
nachgemessen, ob das Modell binär ist, **weil die Welt es ist**:

| Messung (Arm D, `arm_d.json`) | Ergebnis |
| --- | --- |
| reale Feld-Manifestationen im Fixture | 9 |
| davon im binären Claim-Vokabular **unbenennbar** | **3** |
| Ebenen, die auf Feldebene erreichbar sind | nur `type` und `data` |
| wahre Paare, nicht behauptet | 12 von 16 |
| davon ohne Berührung des Typ-Hubs | 9 |
| echte Stelligkeit der beiden Konzepte | **4 und 5** |

Das Vokabular kennt `type_field`, `csv_field`, `schema_field`. Code und Wissen
werden nur auf Dateiebene gebunden. Zwei von vier Ebenen sind damit auf
Feldebene strukturell ausgeschlossen, und `csv ↔ schema` ist nicht aussprechbar.

**Die Welt ist nicht binär. Das Schema ist es.** Das ist die Änderung am Twin,
nicht an der Repräsentation.

## 2. Der n-äre Claim

Ein Claim trägt beliebig viele Slots, jeder mit Rolle, Ebene und Knoten:

```json
{
  "claim_id": "realization:Event.voltage@rev-…",
  "kind": "concept_realization",
  "revision": "rev-…",
  "arity": 5,
  "slots": [
    {"role": "type_field",       "plane": "type",      "node": "type:models.py#Event.voltage"},
    {"role": "data_column",      "plane": "data",      "node": "data:events.csv#voltage"},
    {"role": "schema_property",  "plane": "data",      "node": "data:event.schema.json#voltage"},
    {"role": "doc_mention",      "plane": "knowledge", "node": "knowledge:wiki/Event.md#voltage"},
    {"role": "code_use",         "plane": "code",      "node": "code:repository.py#parse_event.voltage"}
  ],
  "status": "proposed | verified",
  "evidence": {"verifier": "…", "locator": "…"}
}
```

Drei Eigenschaften, die das binäre Vokabular nicht hat:

1. **Kein privilegierter Hub.** Kein Slot ist Subjekt. `csv ↔ schema` ist
   dieselbe Aussage wie `type ↔ csv`.
2. **Lokale Konsistenz.** „Ist dieser Rename vollständig?" ist eine Frage an
   **einen** Claim, kein Join über mehrere.
3. **Offene Stelligkeit.** Neue Ebenen oder Rollen erweitern die Slot-Liste,
   nicht das Vokabular.

Die Invarianten bleiben unberührt: ein Claim ist `proposed`, bis ein
unabhängiger Verifier ihn prüft (§4.4). Stelligkeit ändert daran nichts.

## 3. Der Tensorraum — die Formulierung

Der Claim-Satz ist ein **dünn besetzter Tensor variabler Ordnung**. Statt pro
Stelligkeit einen eigenen Tensor zu führen (unbrauchbar), wird die
CP-/GETD-Form benutzt, die jede Stelligkeit mit **einer** Embedding-Tabelle
trägt:

> `score(κ, n₁…n_a) = Σ_r  G[κ, r] · Π_i ( E[n_i, r] · R[role_i, r] )`

- `E ∈ ℝ^{N×d}` — ein Vektor je Knoten, über alle vier Ebenen hinweg;
- `R ∈ ℝ^{|roles|×d}` — eine rollenspezifische Modulation;
- `G ∈ ℝ^{|kinds|×d}` — ein Gewicht je Claim-Art;
- das **Produkt** über die Slots erzwingt gemeinsame Übereinstimmung; eine
  Summe könnte das nicht (v2, §3).

Retrieval ist eine Kontraktion: sind einige Slots bekannt, ergibt das Produkt
über die bekannten einen Vektor, dessen Skalarprodukt mit `E` alle Kandidaten
für den fehlenden Slot bewertet. Genau eine Matrixmultiplikation.

Das ist der „high dimensional tensor space" in ausführbarer Form. `d` ist die
Dimension dieses Raums; die vier Ebenen leben darin gemeinsam, unterschieden
durch `R`, nicht durch getrennte Indizes.

## 4. Arm E — die Messung

**Aufgabe (knowledge retrieval, nicht Link-Prediction-Benchmark):** Gegeben ein
Teil eines Konzepts — etwa nur die CSV-Spalte — finde die übrigen
Manifestationen über die anderen Ebenen.

**Korpus:** synthetisch, aber mit den in Arm D **gemessenen** Formparametern:
Stelligkeit 4–5, Namensdrift zwischen Ebenen, fehlende Slots. Ausdrücklich
synthetisch; das Fixture hat zwei Konzepte und trägt keine Statistik.

**Verglichene Modelle, gleiches Parameterbudget:**

| Modell | was es ist |
| --- | --- |
| `trigram` | Zeichen-Trigramm-Ähnlichkeit, ungelernt — der Sieger aus v1/v2 |
| `exact` | Namensgleichheit — die Untergrenze |
| `cp_binary` | dieselbe gelernte Form, aber nur auf **hub-gerouteten Paaren**, also dem heutigen Modell |
| `cp_nary` | die Form aus §3 auf den vollen n-ären Claims |

**Metrik:** Recall@k des fehlenden Slots. Zusätzlich, und wichtiger:
**Recall@k auf den Ebenen, die das binäre Modell nicht benennen kann** (Code,
Wissen). Dort ist `cp_binary` per Konstruktion blind — das ist keine Schwäche
des Baselines, sondern der gemessene Preis des heutigen Schemas, und es wird
getrennt ausgewiesen.

## 5. Kill-Kriterien, vor dem Lauf festgeschrieben

- **K9** `cp_nary` schlägt `trigram` nicht. Dann kauft der gelernte Tensorraum
  nichts über ungelernte Zeichenähnlichkeit hinaus, und die Spur endet
  endgültig.
- **K10** `cp_nary` schlägt `cp_binary` auf den Ebenen `type`/`data` nicht.
  Dann ist der Gewinn reine Abdeckung, kein Struktureffekt.
- **K11** Der Vorsprung verschwindet bei starker Namensdrift. Dann lernt das
  Modell die Namen, nicht die Struktur — prüfbar durch einen Lauf mit
  **randomisierten Namen**, in dem nur die Struktur Signal trägt.
- **K12** Das Training ist nicht reproduzierbar (zwei Läufe, gleiche Seeds,
  abweichende Zahlen).

K11 ist das schärfste: es trennt „der Tensor hat die Struktur gelernt" von
„der Tensor hat Trigramme nachgebaut". Ohne diesen Kontrollarm ist jede Zahl
aus Arm E wertlos.

## 6. Budget und Isolation

numpy und Standardbibliothek. Kein Netz, kein Modell, keine Kosten. Schreibt nur
nach `runs/tensor_embedding_v3/`. Importiert nichts aus `daedalus/`, verändert
das Fixture nicht (Rename nur in einer Kopie im Speicher). Zielzeit unter 180 s.
Feste Seeds, Determinismus wird geprüft (Wanduhrfeld ausgenommen).
Promoviert nichts.

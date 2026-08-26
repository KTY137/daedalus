# EXPERIMENT `tensor-embedding-v2` — Ergebnisse

Datum: 2026-08-25. Spec: `SPEC.md` daneben, eingefroren vor der Messung.
Artefakt: `arm_c.json`. numpy 1.26.4, Python 3.10, Laufzeit 20,2 s.
Vorgänger: `runs/tensor_embedding_v1/`.

---

## 1. Urteil

**Stelligkeit kauft hier nichts, und der Grund ist strukturell, nicht empirisch.**

Drei Kill-Kriterien feuern, eines davon gegen echte Daten:

| | Kriterium | Ergebnis |
| --- | --- | --- |
| **K5** | `trilinear` schlägt `pairwise_sum` im Regime `joint` nicht | **FEUERT** — beide am Anschlag; `trilinear` ist mit 0,990–1,000 sogar marginal schlechter als 1,000 |
| **K6** | `pairwise_min` erreicht, was `trilinear` erreicht | **FEUERT** — 1,000 in allen 20 Zellen |
| **K7** | `trilinear` gewinnt auch im zerlegbaren Regime | feuert nicht — es gewinnt nirgends |
| **K8** | kein echter Cross-Plane-Claim ist n-är | **FEUERT** — **10 von 10 binär**, Histogramm `{2: 10}`, arity ≥ 3: **null** |

K8 ist das Kriterium, das die Spur beendet, und es hängt an keinem synthetischen
Aufbau: das Datenmodell dieses Repositories kennt keine dreistellige
Cross-Plane-Bindung. `type_matches_csv_field`, `type_matches_schema_field`,
`code_declares_type`, `wiki_documents_node` — jeder Claim verbindet **zwei**
Ebenen. Es gibt nichts, worauf ein n-ärer Tensor angesetzt werden könnte.

## 2. Zahlen

Zufallsniveau 0,025 (40 Kandidatenpaare), N = 200 Konzepte.

| Regime | `exact` | `pairwise_sum` | `pairwise_min` | `trilinear` |
| --- | --- | --- | --- | --- |
| `decomposable`, kein Rename | 1,000 | 1,000 | 1,000 | 0,990–1,000 |
| `joint`, kein Rename | 1,000 | 1,000 | 1,000 | 0,995–1,000 |
| `decomposable`, Präfix-Rename | **0,000** | 1,000 | 1,000 | 0,990–1,000 |
| `joint`, Präfix-Rename | **0,000** | 1,000 | 1,000 | 0,990–1,000 |

Über alle Ablenkeranteile von 0,0 bis 0,8 unverändert. Bestätigt v1 an einem
zweiten Aufbau: exakter Vergleich fällt beim Rename auf null, jede
vektorbasierte Variante löst ihn vollständig — und keine Ordnung des Vergleichs
macht dabei einen Unterschied.

## 3. Der strukturelle Grund, und warum er wichtiger ist als die Zahlen

Der Aufbau hat das Regime `joint` **nicht erzeugt**, das er erzeugen wollte:
`pairwise_sum` bleibt auch bei 80 % Ablenkeranteil bei 1,000 (Mangel M6). Der
Versuch, es härter zu machen, führt auf eine Einsicht statt auf eine Zahl:

> Wenn die richtige Bindung diejenige ist, bei der alles am besten
> zusammenpasst, dann **ist** sie per Konstruktion die paarweise beste. Eine
> Aggregation über Paare findet sie. Stelligkeit kann nur dort etwas ändern, wo
> die Wahrheit **nicht** die ähnlichste Option ist.

Das ist genau der Fall, in dem die Bindung *relational* statt *ähnlichkeits-
getrieben* ist — ein Fremdschlüssel, dessen Endpunkte nichts gemeinsam haben.
Dort versagt aber jede ungelernte Repräsentation: v1 hat das im Modus
`foreign` gemessen, alle Verfahren auf Zufallsniveau.

**Damit schließt sich der Kreis.** Ein Tensor gewinnt nur auf gelernten
relationalen Scores. Gelernte relationale Scores sind genau das, was der Survey
als Commodity und als unkalibriert unter Open-World-Annahme belegt hat, mit
einem offenen Kill-Kriterium bei Precision nach Verifikationskosten. Der Weg
führt zurück auf die Kosten, die er umgehen sollte.

## 4. Mängel dieses Experiments, alle eigene

- **M6 — das schwierige Regime war nicht schwierig.** Ablenker paarten die
  richtige CSV-Seite mit einer falschen Schema-Seite. Das wahre Tripel dominiert
  dann auf jedem Term. `pairwise_sum` blieb bei 1,000. Der beabsichtigte
  Unterschied wurde nie erzeugt; §3 erklärt, warum er mit
  Ähnlichkeitssignalen auch nicht erzeugbar ist.
- **M7 — die trilineare Form war auf den v1-Vektoren keine Ähnlichkeit.** Auf
  nullzentrierten Zufallsprojektionen reduziert sich `Σ q·c₁·c₂` für das wahre
  Tripel auf eine Summe von Kuben einer symmetrischen Verteilung, also ≈ 0. Der
  erste Lauf zeigte 0,09 gegen Zufall 0,025 in **jedem** Regime. Korrigiert auf
  nicht-negative Trigramm-Histogramme. Das ist zugleich ein Befund: die CP-Form
  ist ohne Training oder Nicht-Negativität kein Ähnlichkeitsmaß.
- **M8 — meine erste K8-Messung war ein Artefakt.** Sie leitete die Ebene aus
  dem Schlüsselpräfix ab und zählte `link_target` und `target_node_id` als zwei
  Ebenen. Ergebnis war „5 von 10 mit arity ≥ 3". Nach expliziter
  Ebenen-Zuordnung: **0 von 10**. Die falsche Zahl hätte die Spur am Leben
  gehalten.

M8 ist der dritte Fall an einem Tag, in dem eine falsche Messung in die
Richtung zeigte, die mehr Arbeit erzeugt hätte.

## 5. Was die Spur wiederbeleben würde

Nicht „mehr Tensor", sondern eine dieser drei Bedingungen, jede messbar:

1. **Der Bucket-(b)-Ceiling-Lauf liefert ≥ 20 %.** Ohne Nachfrage kein Angebot.
   Weiterhin nicht gelaufen.
2. **Das Datenmodell bekommt echte n-äre Claims.** Solange `fourfold.json` nur
   binäre Relationen kennt, gibt es für Stelligkeit kein Objekt. Das wäre eine
   Änderung am Twin, keine an der Repräsentation.
3. **Die Abkürzungslücke wird geschlossen werden müssen.** v1 maß alle Verfahren
   dort auf Zufallsniveau (0,030–0,045 gegen 0,005). Das ist die einzige
   gemessene Lücke, und sie verlangt ein *gelerntes* Modell — womit die
   Kostenfrage des Surveys wieder aufgeht, diesmal mit einer konkreten Aufgabe
   statt einer Vermutung.

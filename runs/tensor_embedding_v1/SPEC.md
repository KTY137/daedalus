# EXPERIMENT `tensor-embedding-v1` — eingefrorene Spezifikation

Datum der Einfrierung: 2026-08-25
Klassifikation: `EXPERIMENT` (§1, §15 des Masterplans)
Aktives Gate: 0. Berührter `PRIOR`: §6 (Latent Atlas, Cross-Plane-Discovery)
Autor: Session `agent-env-30`
Owner-Entscheidung: „lets go full experimental", 2026-08-25
Vorlage-Recherche: `docs/research/TENSOR_EMBEDDING_SURVEY_2026-08-25.md`

**Diese Datei ist ab Einfrierung unveränderlich.** Änderungen an Hypothese,
Metrik, Kill-Kriterium oder Budget erzeugen `tensor-embedding-v2` mit eigener
Spec. Ergebnisse werden in `RESULTS.md` daneben geschrieben, niemals hier hinein.

---

## 1. Warum dieses Experiment und nicht das naheliegende

Die naheliegende Fassung wäre eine HRR-Kapazitätskurve. Die wäre wertlos: sie
leitet Plate 1995 neu her. Ebenso wertlos wäre ein TuckER-Lauf auf einem
Benchmark — die PyKEEN-Großevaluation zeigt, dass die Architektur nicht der
dominante Faktor ist (§3.1 der Recherche).

Die Frage, die **nicht** in der Literatur steht, ist projektspezifisch:

> Derselbe Oberflächen-Token erscheint in mehreren Ebenen des Project Twin.
> Kollabiert eine gelernte Repräsentation ihn zu einem Punkt (und verliert damit
> die Ebene), oder trennt sie ihn (und verliert damit die Beziehung)?
> Kann eine Bindungs-Repräsentation **beides** — trennen und verbinden — und
> dabei die Revision entbindbar halten?

Genau dafür existiert im Repo bereits ein Fixture mit Ground Truth.

## 2. Hypothesen

- **H-A (Bindungstreue).** Identität, Ebene, Revision und Provenienz einer Node
  Card lassen sich in EINEN Vektor fester Breite binden, so dass jedes Feld per
  Unbinding mit Cleanup zurückgewonnen werden kann. Insbesondere die Revision
  mit >= 99 % bei der Rollenzahl und Vokabulargröße, die der Twin braucht.
- **H-B (Cross-Plane-Trennung ohne Trennung der Beziehung).** Auf dem
  Gate-1-Voltage-Fixture unterscheidet eine ebenen-gebundene Repräsentation die
  vier `voltage`-Knoten nach Ebene UND hält sie einander ähnlicher als
  unbeteiligten Knoten. Eine naive gepoolte Repräsentation kann höchstens eines
  von beidem.
- **H-C (Nutzen über den trivialen Baseline hinaus).** Die Rangfolge der
  wahren Cross-Plane-Bindungen aus `fourfold.json` ist im gebundenen Raum
  besser als bei exakter String-Gleichheit des Namens.

**H-C ist die Hypothese, an der das Experiment vermutlich stirbt**, und sie ist
absichtlich so gestellt. Exakte String-Gleichheit findet auf diesem Fixture alle
vier Vorkommen. Wenn Binding das nicht schlägt, kauft es nichts.

## 3. Arme

### Arm A — Bindungstreue (synthetisch, skalierend)

HRR: Binding = zirkuläre Faltung, Unbinding = zirkuläre Korrelation mit der
Involution, Bündelung = Summe, Cleanup = Kosinus-Nächster-Nachbar im Codebook.

- Dimensionen `d ∈ {256, 512, 1024, 2048, 4096}`
- Rollenzahl `k ∈ {2, 3, 4, 5, 6, 8}`
- Vokabulargröße pro Rolle `V = 1000`
- Wiederholungen: 200 Ziehungen je (d, k), Seeds `0..199`, deterministisch

Gemessen: Unbind-Genauigkeit je Rolle nach Cleanup.

**Pflicht-Baseline: Slot-Konkatenation.** Dieselben Felder in disjunkte
Abschnitte eines Vektors gleicher Gesamtbreite geschrieben. Rückgewinnung ist
dort exakt per Konstruktion. Berichtet wird die **minimale Dimension bei
gleicher Treue** für beide Verfahren. Binding gewinnt nur, wenn es billiger ist
oder etwas kann, das Konkatenation nicht kann.

### Arm B — Cross-Plane auf dem echten Fixture

Substrat: `tests/fixtures/ignition/voltage`, Baum-Digest wird im Ergebnis
festgehalten. Vier Ebenen, ein gemeinsamer Token, Ground Truth in
`fourfold.json`.

Repräsentationen im Vergleich:

1. `exact` — exakte String-Gleichheit des Namens (trivialer Baseline)
2. `pooled` — gemitteltes Zeichen-Trigramm-Profil von Name und Pfad (naiv)
3. `bound` — `Σ rolle ⊛ füller` über {name, plane, kind, path, revision}

Gemessen:

- **B1** Trennbarkeit nach Ebene: paarweise Kosinus-Ähnlichkeit der vier
  `voltage`-Knoten je Repräsentation.
- **B2** Beziehungserhalt: sind die vier einander ähnlicher als unbeteiligten
  Knoten desselben Fixtures?
- **B3** Precision@k der wahren Bindungen aus `fourfold.json`.
- **B4** Revisions-Rückgewinnung aus dem gebundenen Vektor.

## 4. Kill-Kriterien

Das Experiment ist gescheitert und wird als Negativevidenz archiviert, wenn:

- **K1** Slot-Konkatenation erreicht die gleiche Treue bei gleicher oder
  kleinerer Dimension und die Bindung kann nichts, was sie nicht kann.
- **K2** `bound` schlägt `exact` bei B3 nicht.
- **K3** Die Revision ist bei der benötigten Rollenzahl nicht mit >= 99 %
  rückgewinnbar.
- **K4** `pooled` erreicht B1 und B2 bereits gemeinsam — dann ist die Bindung
  überflüssig.

Ein gefeuertes Kill-Kriterium beendet den betroffenen Arm. Das Ergebnis wird
behalten und in `RESULTS.md` benannt, nicht gelöscht.

## 5. Fähigkeiten und Budget

- **Abhängigkeiten:** ausschließlich `numpy` (vorhanden, 1.26.4) und die
  Standardbibliothek. Kein Netz, kein Modell, kein LLM-Aufruf, keine Kosten.
- **Schreibrechte:** ausschließlich `runs/tensor_embedding_v1/`. Der Code unter
  `experiments/tensor_embedding/` importiert nichts aus `daedalus/` und wird von
  nichts in `daedalus/` importiert.
- **Laufzeit:** Zielbudget unter 120 s für beide Arme zusammen.
- **Determinismus:** alle Seeds fest, zweimaliger Lauf muss byte-gleiche
  Ergebnisse liefern. Das wird geprüft und im Ergebnis vermerkt.

## 6. Was dieses Experiment ausdrücklich NICHT tut

- Es promoviert nichts. Kein Ergebnis verändert Policy, Evaluator, Ledger,
  Evidence oder den Promotionspfad.
- Es baut keinen Vektorspeicher, kein Trainings-Setup, keine Produktionsroute.
- Es beantwortet **nicht** die Frage nach dem Bucket-(b)-Ceiling. Diese Frage
  bleibt offen und ist die eigentliche Vorbedingung für alles, was auf ein
  positives Ergebnis hier folgen würde
  (`docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md`).
- Es misst **keine** Retrieval-Qualität auf realem Korpus. Das Fixture hat sieben
  Dateien. Jede Zahl aus Arm B ist eine Aussage über dieses Fixture und über
  nichts sonst. Wer sie verallgemeinert, macht den Fehler, der in diesem Projekt
  am 25.08. dreimal an einem Vormittag gemacht wurde.

## 6a. Vor-Ausführungs-Korrektur (2026-08-25, vor jeder Messung)

Beim Lesen des Fixtures fiel ein Konstruktionsfehler in §3/Arm B auf. Er wird
hier benannt statt still behoben. **Zu diesem Zeitpunkt war nichts gemessen**,
kein Code ausgeführt, keine Zahl erzeugt.

**Der Fehler:** `id` und `voltage` heißen in Typ-, Daten- und Schema-Ebene
*exakt gleich*. Damit ist `exact` auf diesem Fixture ein perfektes Orakel, und
B3 kann zwischen den Repräsentationen nicht unterscheiden. Die Hypothese H-C
wäre auf einem Substrat getestet worden, das sie nicht testen kann.

**Die Korrektur, dreiteilig:**

1. **Zwei Szenarien statt einem.** `S1 aligned` = Fixture wie auf Platte.
   `S2 renamed` = der halb ausgeführte Gate-1-Rename: das Python-Feld heißt
   `bias_voltage`, CSV und Schema weiterhin `voltage`. S2 ist der Fall, für den
   Gate 1 überhaupt existiert, und exakter Vergleich scheitert dort per
   Konstruktion. Nur S2 testet H-C.
2. **Namen werden kompositionell dargestellt**, als Summe von
   Zeichen-Trigramm-Vektoren, nicht als atomare Zufallsvektoren. Sonst ist
   `bias_voltage` von `voltage` genauso weit entfernt wie von `id`, und keine
   Repräsentation könnte S2 lösen.
3. **`concat` wird vierte Repräsentation, auch in Arm B.** Slot-Konkatenation
   ist der ehrliche Rivale: wenn schlichte getrennte Felder das Problem lösen,
   ist das das wertvollste Ergebnis dieses Experiments, und es darf nicht
   wegdefiniert werden.

**Vorhersage, vor dem Lauf notiert, damit sie falsifizierbar bleibt:** Unter HRR
gilt `cos(bind(r,a), bind(r,b)) ≈ cos(a,b)` bei verschwindenden Kreuztermen.
`bound` und `concat` sollten daher in der Ähnlichkeitsstruktur **nahezu
identisch** abschneiden. Wenn das eintritt, kauft Binding gegenüber Slotting
nichts für Retrieval — sein einziger verbleibender Vorteil wäre feste Breite bei
variabler Struktur plus Entbindbarkeit (B4). Ich erwarte, dass K1 feuert.

**Zusätzlicher Arm B-skaliert.** Das Fixture hat neun Knoten und vier Anfragen.
Das ist eine Demonstration, keine Statistik. Deshalb zusätzlich ein
synthetischer Lauf mit N = 200 Feld-Tripeln und kontrolliert gestörten Namen
(Präfix, Suffix, Abkürzung, Fremdwort), um einen Dynamikbereich zu erzeugen.
Ohne Dynamikbereich ist keine Zahl aus Arm B interpretierbar.

## 7. Ablauf

1. Spec einfrieren (diese Datei).
2. `experiments/tensor_embedding/hrr.py` — Primitive.
3. `experiments/tensor_embedding/arm_a_capacity.py` — Arm A inklusive Baseline.
4. `experiments/tensor_embedding/arm_b_fixture.py` — Arm B inklusive Ground Truth.
5. Beide zweimal laufen lassen, Determinismus prüfen.
6. `RESULTS.md` schreiben, Kill-Kriterien explizit gegen die Zahlen halten.

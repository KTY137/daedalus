# Tensor Embedding: Recherche und Potenzialurteil

Datum: 2026-08-25
Klassifikation: `ALIGNED` — read-only Recherche, keine Produktionsberührung
Aktives Gate: 0. Berührter Gegenstand: `PRIOR` §6 (Latent Atlas, Cross-Plane-Discovery)
Autor: Session `agent-env-30`

**Provenienz-Regel für dieses Dokument:** Jede Prozentzahl unten ist `INHERITED`
aus der zitierten Arbeit. Keine davon ist auf diesem Repository reproduziert.
Es wurde für dieses Dokument **nichts gemessen**. Wer eine Zahl von hier
weiterverwendet, erbt diesen Status mit.

---

## 0. Kurzurteil

Der Engpass in Daedalus ist nicht das Erzeugen von Vorschlägen, sondern das
Verifizieren. Tensor-Embedding ist eine Vorschlagsmaschine. Einem System, dessen
Flaschenhals die Verifikation ist, mehr Vorschlagskapazität zu geben, macht es
langsamer, nicht besser. Das ist der Hauptgrund gegen die Familie als
Forschungsrichtung, und er ist unabhängig von jeder Benchmark.

Zwei Ausnahmen mit echtem Potenzial, beide nicht das, wofür die Literatur
bekannt ist:

1. **TPR/HRR-Binding für Node Cards** (§1.6) — Repräsentations-Hygiene statt
   Retrieval, bedient Invariante 7 statt einer Metrik, entbindbar, billig,
   trivial falsifizierbar.
2. **N-äre Tensoren für Cross-Plane-Bindungen** (§1.2) — die einzige gefundene
   Formalisierung, die Stelligkeit nativ trägt.

Ohne Potenzial heute: TT-Kompression (kein Skalenproblem vorhanden) und
TuckER/ComplEx als Link-Prädiktor über den Twin (Commodity, unkalibriert, der
deterministische Extraktor kennt die meisten Kanten bereits).

Vorbedingung für alles: der Bucket-(b)-Ceiling-Lauf aus
`docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md`. Er ist nicht gelaufen.

---

## 1. Begriffsklärung — sechs Familien unter einem Namen

### 1.1 Tensor-Faktorisierung als KG-Embedding

Ein Multi-Relationsgraph als binärer Tensor 3. Ordnung `X ∈ {0,1}^(N × R × N)`;
Embedding = Low-Rank-Zerlegung.

| Modell | Zerlegung | Kernpunkt |
| --- | --- | --- |
| RESCAL (2011) | Relation = Matrix `R_k ∈ ℝ^(d × d)` | erstes; quadratisch pro Relation, skaliert schlecht |
| DistMult | diagonale Relationsmatrix | nur symmetrische Relationen |
| ComplEx | CP im Komplexen | löst Antisymmetrie; Spezialfall von TuckER |
| TuckER (2019) | Tucker: Kern-Tensor `W ∈ ℝ^(de × dr × de)` + 3 Faktormatrizen | Kern wird über alle Relationen geteilt; beweisbar *fully expressive*; RESCAL/DistMult/ComplEx/SimplE sind Spezialfälle |

Architektonisch interessant ist nicht die Genauigkeit, sondern der **geteilte
Kern-Tensor**: seltene Relationen borgen Struktur von häufigen. Das ist genau
die Lage im Twin — Cross-Plane-Kanten sind selten, Intra-Plane-Kanten häufig.

Stand 2026: TuckER/ComplEx sind weiterhin Standard-Baselines, nicht abgelöst.
Neuere Arbeit geht in Sparsity (SparseMult 2026) und in Hybride mit GNN/LLM.

### 1.2 N-äre Relationen — der Teil, der auf Cross-Plane passt

Eine verifizierte Cross-Plane-Bindung ist oft nicht binär: (Funktion, Typ,
Schema-Feld, Revision) ist ein vierstelliger Fakt. Klassische KGE zerlegt das in
Tripel und verliert die gemeinsame Bedingung.

**GETD** (2020) macht daraus einen Tensor n-ter Ordnung. Naives Tucker auf n-är
wächst exponentiell in der Parameterzahl; GETD fixt das, indem der Tucker-Kern
selbst per **Tensor-Ring** zerlegt wird. Beweis auf volle Expressivität;
laut Abstract >15 % über dem damaligen n-ären SOTA [INHERITED].

Das ist die einzige Familie hier, die die n-äre Natur einer Cross-Plane-Bindung
nativ trägt. Alles andere — BM25, dense Retrieval, GNN über binäre Kanten —
zerlegt sie in Paare.

### 1.3 Revision als vierter Modus

Der Twin ist revisionsgebunden, also `X ∈ ℝ^(N × R × N × T)`. Literatur
existiert fertig: **TuckERT** (Tucker mit Zeitmodus), **ConT** (verallgemeinert
RESCAL/Tucker auf episodische Tensoren, pro Zeitscheibe ein eigener Kern), zwei
Surveys zu Temporal-KGC.

**Der Kostenkiller:** vollständiges Refit pro Revision ist unbezahlbar.
Streaming-Verfahren existieren — Online CP für sparse Tensoren (bis 250×
schneller, 100× weniger Speicher bei vergleichbarer Qualität [INHERITED]),
BS-CP, Online TT-ALS mit inkrementeller Orthogonalisierung (2026). Wenn diese
Spur je produktiv würde, hängt sie an dieser Zeile, nicht an der Modellwahl.

### 1.4 Tensor-Netzwerke als Kompression

**Tensor-Train / MPS** zerlegt die *Embedding-Tabelle*. TT-Rec (Meta): 117× /
112× Modellgrößen-Kompression ohne Genauigkeits- oder Trainingszeitverlust
[INHERITED]; FBTT-Embedding als Library. TensorGPT macht dasselbe für
LLM-Embedding-Layer.

Kein Repräsentationsgewinn, ein Speichertrick. Relevant erst bei
Korpus-Ingestion (Gate 2) jenseits von Millionen Node Cards. Heute nicht.

### 1.5 „Tensor" = Multi-Vektor / Late Interaction

Vektor-DBs (Vespa, Infinity, Qdrant, Weaviate) nennen Multi-Vektor-Embeddings
„Tensoren": ein Dokument ist eine Matrix von Token-Vektoren statt eines Vektors;
Ähnlichkeit = MaxSim (ColBERT/ColPali). Preis ist Speicher und Latenz; die
aktuelle Forschung ist fast nur Pruning (DocPruner, Voronoi-Token-Pruning 2026);
ECIR 2026 hat einen eigenen Workshop dafür (LIR).

Für Node Cards die billigste Form von „Tensor": Karte → mehrere Vektoren
(Identität, Nachbarschaft, Inhalt), Retrieval per MaxSim, statt alles in einen
Vektor zu mitteln. **Sollte als Retrieval bewertet werden, nicht als Forschung.**

### 1.6 Tensor-Produkt-Repräsentation (Binding)

Smolensky 1990: Rolle ⊗ Filler per äußerem Produkt; die VSA-Familie
(HRR/Plate, MAP/Gayler, Binary Spatter Code) macht dasselbe bei fester Dimension
via zirkulärer Faltung. 2025/26 lebendig, u. a. „Attention as Binding: A
Vector-Symbolic Perspective on Transformer Reasoning".

Konzeptuell die sauberste Antwort auf ein konkretes Twin-Problem: **wie bindet
man Identität + Ebene + Revision + Provenienz in einen Vektor, ohne sie zu
verschmieren?** Die Node-Card-Spezifikation in §6 des Masterplans ist faktisch
ein Rollen-Filler-Bündel. Anders als eine Faktorisierung ist TPR/HRR
**entbindbar**: man kann fragen, welche Revision in einem Vektor steckt.

---

## 2. Zwei mögliche Tensorisierungen des Twins

Sie sind nicht dasselbe und beantworten verschiedene Fragen:

- **(A) Multiplex:** `N × N × L`, Ebene = Layer-Modus (vgl. MvTuckER 2024).
  Fragt: „welche Ebene sagt was über dieselben Knoten?"
- **(B) Multi-Relational:** `N × R × N`, Ebene = Knotenattribut, R = Relationstyp
  inkl. Cross-Plane. Fragt: „welche typisierte Kante fehlt?"

(B) passt zur Verifier-Pipeline in §6, weil sie typisierte Bindungsvorschläge
ausgibt. (B) + Revision als 4. Modus + GETD für die n-ären Bindungen wäre die
technisch kohärente Vollversion.

---

## 3. Evidenzlage gegen die Familie

Drei Befunde, gewichtiger als jede Modellwahl:

1. **Die Architektur ist nicht der dominante Faktor.** Die große PyKEEN-Studie
   (21 Modelle, einheitliches Framework, tausende Läufe) sagt wörtlich, die
   Leistung sei durch die *Kombination* aus Architektur, Trainingsansatz, Loss
   und explizitem Modellieren inverser Relationen bestimmt; „several
   architectures can obtain results competitive to the state of the art when
   configured carefully"; kein starker Zusammenhang zwischen Modellgröße und
   Güte. Ruffinelli et al. („You CAN teach an old dog new tricks") unabhängig
   dasselbe: getuntes DistMult schlägt aufwendigere Modelle. **Ein Tensor-Modell
   zu wählen ist fast keine Entscheidung; die Trainings- und
   Evaluationspipeline ist die Entscheidung.**
2. **Die Scores sind unkalibriert, genau dort wo wir sind.** Platt-Scaling und
   isotonic regression wirken unter Closed-World-Annahme; unter der realistischen
   **Open-World-Annahme deutlich schlechter** (EMNLP 2020). Der Twin ist strikt
   Open World. Das trifft frontal das Kill-Kriterium des Masterplans:
   *„embedding proposals cannot achieve useful precision after verification
   cost"*.
3. **Reproduzierbarkeit ist ein aktives Problem.** Unterschiedliche
   Ranking-Implementierungen erzeugten für SimplE „fast 0 %" (realistic) gegen
   deutlich höhere Werte (optimistic). Ohne vorher festgelegte Ranking-Semantik
   ist keine Zahl aus dieser Literatur vergleichbar.

**Schwaches Negativ, ausdrücklich als solches markiert:** Eine Suche nach
Tensor-Faktorisierung auf *Code*-Graphen (API-Usage, Defect Prediction,
Code-Embedding) fand nichts Tensorielles — dort dominieren doc2vec, CNN/BiLSTM,
CodeBERT und GNNs. Das ist kein Beweis der Abwesenheit. Es heißt: es gibt keinen
fertigen Präzedenzfall zum Abschreiben, und das ist an dieser Stelle eine
Kostenposition, keine Chance.

---

## 4. Potenzialurteil, geordnet

| Rang | Spur | Urteil |
| --- | --- | --- |
| 1 | TPR/HRR-Binding für Node Cards (§1.6) | **Echtes Potenzial.** Bedient Invariante 7 statt einer Metrik. Kein Training. Trivial falsifizierbar. Unabhängig von jeder Benchmark. |
| 2 | N-äre Tensoren für Cross-Plane (§1.2) | **Bedingtes Potenzial.** Einzige nicht-Commodity-Stelle. Nur als Gate-4-förmiges Experiment, nur nach dem Ceiling-Lauf. |
| 3 | Multi-Vektor/MaxSim (§1.5) | **Nützlich, aber kein Forschungsgegenstand.** Als Retrieval-Baseline bewerten, nicht als Beitrag. |
| 4 | TuckER/ComplEx als Link-Prädiktor (§1.1) | **Kein Potenzial als Beitrag.** Commodity, unkalibriert, Extraktor kennt die Kanten. Taugt nur als harter Gegner in einer Messung. |
| 5 | TT-Kompression (§1.4) | **Heute null.** Löst ein Skalenproblem, das nicht existiert. |

---

## 5. Das billigste entscheidende Experiment

Nicht bauen, sondern klassifizieren — die Reihenfolge steht schon in
`LATENT_CEILING_SHARED_REPRESENTATION.md` und ist unverändert richtig:

1. Bucket-(b)-Ceiling-Lauf über den bestehenden Fehlerkorpus: welcher Anteil
   der Fehler brauchte Information, die *im Repo vorhanden, aber nicht als
   Symbol, Import-Kante oder Doc-Link ausdrückbar* war? Kostet einen
   Klassifikationspass, keinen Vektorspeicher.
2. Bei 2–3 %: Spur geschlossen, dieses Dokument ist Archiv.
3. Bei ≥20 %: erst Multi-Vektor/MaxSim über Node Cards als Baseline (kein
   Training), dann getuntes ComplEx-N3 **und** TuckER als harte Gegner, erst
   dann GETD n-är + Revisions-Modus als der einzige Teil, der nicht anderswo
   gelöst ist. Streaming-Update ist Produktionsvorbedingung, nicht Kür.

**Metrik in allen Fällen: Precision nach Verifikationskosten**, nicht
MRR/Hits@10 — sonst misst man die Literatur nach, nicht das Problem. Die
Ranking-Semantik (realistic vs. optimistic) ist vor dem ersten Lauf
festzuschreiben, sonst ist das Ergebnis wertlos (§3.3).

---

## 6. Kill-Kriterien für diese Spur

Zusätzlich zu den Kriterien in §14 des Masterplans, spezifisch hier:

- Der Bucket-(b)-Anteil liegt unter 10 %.
- Multi-Vektor/MaxSim ohne Training fängt den Bucket-(b)-Anteil bereits ein —
  dann kauft die Faktorisierung nichts.
- Die Precision nach Verifikationskosten liegt unter der eines getunten
  Commodity-Baselines bei gleichem Budget.
- Das Refit pro Revision überschreitet das Budget, und kein
  Streaming-Verfahren hält die Qualität.
- Die entbundene Revision aus einem TPR/HRR-Vektor ist nicht zuverlässig
  rekonstruierbar — dann fällt Rang 1 und mit ihm das Provenienz-Argument.

---

## 7. Werkzeuge, falls es dazu kommt

- **PyKEEN** — einheitliche Modelle und Evaluation; genau das Framework der
  Studie aus §3.1. Nicht selbst implementieren.
- **TensorLy / TensorLy-Torch** — Tucker, CP, Tensor-Train, sparse via
  PyData-sparse, PyTorch-Backend.
- **FBTT-Embedding** — nur für den Kompressionsfall aus §1.4.

Adapter-Vertrag, Failure Mode und Ersetzungspfad sind vor Adoption zu deklarieren
(§9.2 des Masterplans).

---

## 8. Quellen

- TuckER: <https://arxiv.org/abs/1901.09590>
- GETD (n-är): <https://arxiv.org/pdf/2007.03988>
- PyKEEN-Großevaluation: <https://arxiv.org/html/2006.13365>
- KGE-Kalibrierung (EMNLP 2020): <https://aclanthology.org/2020.emnlp-main.667/>
- Probability Calibration for KGE: <https://arxiv.org/pdf/1912.10000>
- KGE-Survey (Relationseigenschaften): <https://arxiv.org/pdf/2410.14733>
- SparseMult (2026): <https://onlinelibrary.wiley.com/doi/10.1111/coin.70097>
- Tucker-basierte temporale KGC: <https://arxiv.org/pdf/2011.07751>
- Survey Temporal KGC: <https://arxiv.org/pdf/2308.02457>
- MvTuckER (Multi-View): <https://www.sciencedirect.com/science/article/abs/pii/S1566253524000277>
- TT-Rec: <https://arxiv.org/abs/2101.11714>
- FBTT-Embedding: <https://github.com/facebookresearch/FBTT-Embedding>
- Multi-Vektor / Late Interaction: <https://huggingface.co/blog/multi-vector-encoder>
- LIR-Workshop ECIR 2026: <https://arxiv.org/pdf/2511.00444>
- DocPruner: <https://arxiv.org/pdf/2509.23883>
- Attention as Binding (2025): <https://arxiv.org/html/2512.14709>
- Holographic Reduced Representations: <https://arxiv.org/pdf/2109.02157>
- Online CP für sparse Tensoren: <https://shuozhou.github.io/papers/shuo18icdm_long.pdf>
- Online TT-ALS (2026): <https://arxiv.org/abs/2606.31061>
- TensorLy: <https://github.com/tensorly/tensorly>
- Hyperparameterstudie (Ruffinelli et al., Nachfolgearbeit): <https://link.springer.com/chapter/10.1007/978-3-031-26390-3_9>

## 9. Verwandte Dokumente im Repo

- `docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md` — der Ceiling-Lauf, der
  dieser Spur vorausgeht. Nicht gelaufen.
- `docs/research/HIGHER_TWIN_NC_LAYER2_2026-08-20.md` — Node-Card-Algebra.
- `docs/IKARUS_ARIADNE_MASTER_PLAN.md` §5, §6, §14.

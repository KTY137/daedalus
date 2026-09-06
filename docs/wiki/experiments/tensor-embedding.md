---
title: Experiment tensor-embedding
type: experiment
status: living
updated: 2026-09-05
covers: experiments/tensor_embedding
---
# Experiment `tensor-embedding`

`experiments/tensor_embedding` ist der isolierte Falsifikationslauf gegen den
staerksten offenen `PRIOR` des Masterplans: §6, *Latent Atlas und
Cross-Plane-Discovery*. Die Frage, die der Survey aufwarf und die hier
gemessen wird, ist projektspezifisch und steht so nicht in der Literatur:

> Derselbe Oberflaechen-Token erscheint in mehreren Ebenen des Project Twin.
> Kollabiert eine gelernte Repraesentation ihn zu einem Punkt (und verliert
> damit die Ebene), oder trennt sie ihn (und verliert damit die Beziehung)?

Klassifikation nach `AGENTS.md`: `EXPERIMENT`, nicht `ALIGNED`. Das Verzeichnis
ist deshalb hart vom Kernel getrennt. `hrr.py` sagt es explizit: *"this module
imports nothing from `daedalus` and nothing in `daedalus` imports it"*. Die
einzige Ausnahme in Gegenrichtung ist der Test
[`test_tensor_latent_ceiling.py`](../../../tests/test_tensor_latent_ceiling.py),
der Arm O per `importlib.util.spec_from_file_location` laedt statt per Import —
also ohne das Experiment auf den Modulpfad des Kernels zu heben.

Gemessen 2026-09-05: 17 Python-Dateien, 4 155 Zeilen, verteilt auf vier
eingefrorene Spezifikationen (`v1` bis `v4`). Die Specs und Ergebnisse liegen
nicht hier, sondern unter `runs/tensor_embedding_v1` bis `runs/tensor_embedding_v4`; jede `SPEC.md`
ist ab Einfrierung unveraenderlich, Ergebnisse gehen daneben in `RESULTS.md`.

## Der Bogen in vier Revisionen

Das Verzeichnis liest sich als eine Kette widerlegter Vermutungen. Die
Ergebnisdateien sind der Grund, warum die Skripte stehenbleiben duerfen: der
Masterplan (§1, §14) verlangt, negative Evidenz aufzubewahren.

| Spec | Frage | Ausgang laut `runs/…/RESULTS.md` |
| --- | --- | --- |
| `v1` | Kauft HRR-Binding Breite gegenueber schlichter Slot-Konkatenation? | Nein. Slot-Konkatenation schlaegt oder egalisiert HRR an allen 45 gemessenen Punkten. Der eine echte Gewinn (Gate-1-Rename, 1,00 gegen 0,00 fuer exakten String-Vergleich) gehoert den **Zeichen-Trigrammen**, nicht der Bindung. |
| `v2` | Zahlt sich Stelligkeit (n-aer statt binaer) aus? | Nein, und der Grund ist strukturell: alle 10 Cross-Plane-Claims der Ground Truth sind binaer (Histogramm `{2: 10}`). Ein n-aerer Tensor hat kein Objekt. |
| `v3` | Ist das Datenmodell binaer, weil die Welt es ist, oder weil das Schema es ist? Und schlaegt ein gelerntes Tensorfeld BM25? | Das Schema kostet messbar (Arm D). Gelernte Modelle verlieren deutlich: ComplEx erreicht R@10 = 0,022, wo BM25 0,474 erreicht (Arm J). |
| `v4` | Wenn Lernen verliert — traegt die **Algebra** ueber demselben Graphen etwas? | Ja. Arm P (typisierte Kontraktion, kein Lernen) erreicht R@10 = 0,643, RRF mit BM25 0,667, gegen BM25 0,482. Zwei der drei eingefrorenen Win-Conditions erfuellt, die dritte nicht gelaufen. |

Die v4-Ergebnisse tragen im Dokument selbst den Vorbehalt, dass die von der
SPEC verlangte unabhaengige adversariale Gegenlesung **aussteht**. Diese Seite
uebernimmt den Vorbehalt und ersetzt sie nicht.

## Module

### Substrat

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`hrr.py`](../../../experiments/tensor_embedding/hrr.py) | Vektoralgebra-Primitiven (Holographic Reduced Representations): Binding = zirkulaere Faltung, Unbinding = zirkulaere Korrelation mit der Involution, Buendelung = Summe, Cleanup = Kosinus-Naechster-Nachbar. Bewusst nichts Neues — das Substrat, *auf* dem gemessen wird. | `codebook`, `bind`, `unbind`, `involution`, `bundle`, `normalise`, `cosine`, `cleanup`, `trigram_book`, `text_vector`, `atom`, `TRIGRAM_BOOK_SIZE` |
| [`bench_crossplane.py`](../../../experiments/tensor_embedding/bench_crossplane.py) | Der Cross-Plane-Retrieval-Benchmark, gegen den ab v3 alles gemessen wird. Ground Truth sind **von Menschen geschriebene Markdown-Links** von einer Doku-Seite auf eine Quelldatei. | `collect`, `BM25`, `exact_token_rank`, `doc_neighbour_rank`, `recall_at`, `split_identifier`, `tokenise`, `usable`, `main` |

`hrr.py` haelt zwei Determinismus-Entscheidungen fest, die leicht zu uebersehen
sind: jeder Zufallszug laeuft ueber einen explizit geseedeten
`numpy.random.Generator`, und das Trigramm-Hashing nutzt `zlib.crc32` statt
`hash()`, weil CPython String-Hashing pro Prozess randomisiert — sonst waeren
zwei Laeufe desselben Experiments uneinig.

`bench_crossplane.py` haelt die wichtigste methodische Falle des ganzen
Verzeichnisses fest: die `documents`-Kanten des Extraktors sind aus
"Backtick-Span == Symbolname" **gebaut**, also erreicht jede lexikalische
Methode darauf 100 % per Konstruktion, und der Vergleich sagt nichts. Ein
Markdown-Link ist dagegen eine unabhaengige, absichtliche Aussage eines Autors.
Die Anfrage ist die Prosa der Seite **ohne** Linkziele, deren Basenamen und
jeden Backtick-Span — was uebrigbleibt, ist die Fachsprache, die ein Entwickler
tatsaechlich hat.

### v1 — Bindungstreue und Cross-Plane-Trennung

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`arm_a_capacity.py`](../../../experiments/tensor_embedding/arm_a_capacity.py) | Arm A: Bindungstreue gegen Slot-Konkatenation ueber ein eingefrorenes Gitter (`DIMENSIONS`, `ROLE_COUNTS`, 200 Versuche). Der Punkt ist nicht die Kapazitaetskurve (Plate 1995), sondern die verpflichtende Baseline daneben. | `hrr_accuracy`, `slot_accuracy`, `main`, `DIMENSIONS`, `ROLE_COUNTS`, `VOCAB`, `TRIALS` |
| [`arm_b_fixture.py`](../../../experiments/tensor_embedding/arm_b_fixture.py) | Arm B: Cross-Plane-Bindung auf zwei Substraten — dem echten Gate-1-Voltage-Fixture (neun Knoten, vier Anfragen, Demonstration) und einem synthetischen Sweep (der einzige Teil mit Dynamikbereich). Zwei Szenarien: `aligned` und `renamed`. | `Representations`, `run_fixture`, `run_synthetic`, `fixture_nodes`, `fixture_digest`, `synth_name`, `unique_names`, `perturb`, `FIXTURE_QUERIES`, `PLANES`, `KINDS` |

Das `renamed`-Szenario ist kein Kunstgriff: es ist der halb vollzogene
Gate-1-Rename — Python sagt `bias_voltage`, CSV und Schema sagen noch
`voltage`. Genau der Renovation-Defekt, fuer dessen Reparatur Gate 1 existiert,
und exakter Stringvergleich scheitert daran per Konstruktion.

### v2 — Stelligkeit

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`arm_c_arity.py`](../../../experiments/tensor_embedding/arm_c_arity.py) | Arm C: kostet es etwas, dass Konkatenation nur **paarweise** vergleicht? Kein Modell wird trainiert; die n-aere Verallgemeinerung des Kosinus ist die trilineare Form `sum_r a_r b_r c_r`. Zusaetzlich wird die Stelligkeit der *echten* Bindungen gezaehlt. | `Corpus`, `score`, `build_candidates`, `run_regime`, `real_binding_arity`, `unique_names`, `main`, `DISTRACTOR_SHARES`, `N_CONCEPTS`, `CANDIDATES` |

`real_binding_arity` ist die Funktion, an der die Spur endet: sie liest
`tests/fixtures/ignition/voltage/fourfold.json` und zaehlt. Ein Produkt
kollabiert, sobald **ein** Faktor widerspricht, wo eine Summe paarweiser
Aehnlichkeiten hoch bleibt, wenn zwei von drei uebereinstimmen — nur gibt es im
Datenmodell dieses Repositories nichts Dreistelliges, worauf man das ansetzen
koennte.

### v3 — Ist das Schema schuld? Und lernt ein Tensor ueberhaupt?

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`arm_d_nary_model.py`](../../../experiments/tensor_embedding/arm_d_nary_model.py) | Arm D: zwei Modelle **derselben** Fakten (`binary` wie `fourfold.json` sie heute definiert, `nary` als ein Claim pro Konzept mit einem Slot je Ebene) und drei Messungen dessen, was das binaere Modell verliert. Schreibt nichts ins Fixture; der Rename laeuft auf einer In-Memory-Kopie. | `manifestations`, `binary_claims`, `nary_claims`, `measure_coverage`, `measure_hub_bias`, `measure_rename_detection`, `main` |
| [`arm_e_tensor_space.py`](../../../experiments/tensor_embedding/arm_e_tensor_space.py) | Arm E: der Fourfold-Graph in einem Tensorraum, vier Modelle bei gleichem Parameterbudget. Die entscheidende Kontrolle ist `scramble` — Namen durch signalfreie Zufallstoken ersetzt, sodass nur Struktur bleibt. | `build_corpus`, `train_cp`, `evaluate`, `make_queries`, `trigram_matrix`, `drift`, `unique_names`, `main`, `ROLES`, `ROLE_PLANE`, `HUB_ROLE`, `BINARY_REACHABLE` |
| [`arm_f_pykeen.py`](../../../experiments/tensor_embedding/arm_f_pykeen.py) | Arm F: dieselbe Frage mit fremdem, geprueftem Code (PyKEEN) und einem Korpus, der wie ein echter Twin geformt ist. Zwei Kodierungen derselben Fakten: `binary_hub` und `reified`. | `build_corpus`, `encode`, `run_pykeen`, `trigram_baseline`, `trigram_vec`, `unique_names`, `main`, `ROLES`, `EMB_DIM`, `EPOCHS` |
| [`arm_h_real_fourfold.py`](../../../experiments/tensor_embedding/arm_h_real_fourfold.py) | Arm H: der **echte** vier-Ebenen-Graph, flach und deterministisch extrahiert (`ast`, `json`, Regex ueber Markdown). Ausdruecklich kein Forest, sondern der billigste ehrliche Stellvertreter. | `build_graph`, `describe`, `k_core`, `usable`, `main`, `CROSS_PLANE_RELATIONS`, `MD_LINK`, `MD_CODE` |
| [`arm_j_tensor_vs_bm25.py`](../../../experiments/tensor_embedding/arm_j_tensor_vs_bm25.py) | Arm J: der gelernte Tensorraum gegen BM25 und grep auf identischen Fragen. Der Holdout ist eine **Kante**, kein Knoten; 20 % der `documents_file`-Kanten bleiben im Training. | Skript ohne Top-Level-Funktionen; Konstanten `REPO`, `OUT`, `TAG`, `ROOT`, `DIM`, `EPOCHS`, `KS` |
| [`arm_k_fusion.py`](../../../experiments/tensor_embedding/arm_k_fusion.py) | Arm K (55 Zeilen): schlaegt die Fusion aus BM25 und reiner deterministischer Struktur BM25 allein? Reciprocal Rank Fusion, keine Parameter, kein Training. | Skript; `methods = ("exact_token", "bm25", "doc_neighbour", "rrf_bm25_struct")`, `K_RRF`, `KS` |

Zwei Selbstkorrekturen stehen hier ausformuliert im Code. Arm F begruendet den
Vendor-Wechsel damit, dass vier handgeschriebene Trainer nicht ueber
Zufallsniveau kamen, waehrend ein Orakel R@10 = 1,000 zeigte — der spaetere
Check ergab, dass der Trainer sehr wohl memoriert (TRAIN R@1 0,83–0,95 bei
Stelligkeit 3), es also nie ein Optimierer-Bug war, sondern die Aufgabe: der
Holdout entfernte die **einzige** konzept-identifizierende Kante. Arm J nennt
denselben Fehler beim Namen: *"Getting this wrong is what made arms E and F
unanswerable."*

### v4 — Algebra statt Lernen

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`arm_l_text_tensor.py`](../../../experiments/tensor_embedding/arm_l_text_tensor.py) | Arm L: text-informierter Tensor. Jeder Entitaetsvektor ist eine gelernte Funktion der Zeichen-Trigramme des Knotennamens statt eines freien Parameters. Enthaelt zusaetzlich das Abkuerzungs-Regime von Arm O (Vokal-Strippen: `config` → `cnfg`). | `node_name_tokens`, `doc_own_stem_pieces`, `trigram_counts`, `phi_dense`, `build_phi_sparse`, `entity_tokens`, `train_model`, `encode_tokens`, `eval_pairs`, `strip_vowels`, `rank_recall`, `arm_o`, `main` |
| [`arm_m_path_materialize.py`](../../../experiments/tensor_embedding/arm_m_path_materialize.py) | Arm M: die 2–3-Hop-Kette Seite → Konzept → Symbol → Modul wird als direkte Kanten materialisiert, dann laeuft das Arm-J-Protokoll unveraendert. | `module_of`, `rank_of`, `count_rank`, `_LinkFilter`, `KS`, `TAG` |
| [`arm_n_ppr.py`](../../../experiments/tensor_embedding/arm_n_ppr.py) | Arm N: Personalized PageRank — die anfrage**abhaengige** Version von `doc_neighbour`. Restart am `knowledge:doc:`-Knoten der fragenden Seite, PPR-Masse auf den 411 Kandidatenmodulen. | `make_ppr`, `cand_scores`, `pessimistic_rank`, `stable_order`, `agg`, `ALPHA`, `MAX_IT`, `TOL`, `METHODS`, `K_RRF` |
| [`arm_p_contraction.py`](../../../experiments/tensor_embedding/arm_p_contraction.py) | Arm P: der Twin als Tensor `X[h,r,t]`; das Produkt zweier Relationsscheiben ist die typisierte 2-Hop-Pfadzahl. Vier Features je (Seite, Modul), alle `log1p`-gedaempft, ohne jedes Lernen. Das ist der Arm, der gewinnt. | `contract_features`, `damp`, `rank_of`, `norm`, `rrf`, `module_of`, `M1`, `M2`, `M4`, `M5`, `C2M`, `K_RRF` |
| [`arm_q_field_expansion.py`](../../../experiments/tensor_embedding/arm_q_field_expansion.py) | Arm Q: graphgestuetzte Query-Expansion. Anker sind `knowledge:concept:`-Knoten, deren saemtliche Wortstuecke in der Anfrage vorkommen; dann gewoehnliches BM25. Kein Lernen. | `Graph`, `symbol_name_tokens`, `expansion_terms`, `build_postings`, `weighted_rank`, `rrf`, `rank_pos`, `main`, `STRUCT_RELS`, `SWEEP`, `REFERENCE_BM25` |
| [`arm_o_latent_ceiling.py`](../../../experiments/tensor_embedding/arm_o_latent_ceiling.py) | Arm O: baut absichtlich **keinen** Index und kein Tensor-Backend, sondern beantwortet die billigere Vorfrage — wie viele gemessene Fehlschlaege enthalten Repository-Evidenz, die der deterministische Fourfold-Brief nicht ausdruecken kann? | `Corpus`, `Row`, `CeilingCorpusError`, `load`, `evaluate`, `main`, `SCHEMA`, `REPORT_SCHEMA`, `BUCKETS`, `STATUSES`, `FROZEN_SOURCE_REVISION`, `FROZEN_EXPECTED_TOTAL` |

## Leck-Disziplin

Der auffaelligste Zug des Verzeichnisses ist, wie viel Code darin auf
*Leckvermeidung* entfaellt — Masterplan §14, letzter Absatz. Vier Beispiele im
Wortlaut des Codes:

- **Arm M.** Die Ableitungen lesen ausschliesslich `mentions`- und
  `documents`-Kanten sowie Entitaets-IDs, **nie** eine `documents_file`-Kante,
  damit die 135 zurueckgehaltenen Testkanten in keine Ableitung geraten koennen.
- **Arm P.** Der Leck-Audit steht vor der Messung: `links_to` hat null
  `.py`-Ziele und null Ueberschneidung mit `documents_file`-Paaren, `M5`
  kodiert also keine zurueckgehaltene Kante. Zusaetzlich laeuft eine
  Leck-**Kontrolle** mit dem vollen `M4` als Feature, damit sichtbar wird, wie
  ein Leck aussaehe.
- **Arm Q.** Der `LEAKAGE LOCK` entfernt vor jeder Anfrage den Knoten
  `knowledge:doc:<page>` samt allen Kanten aus dem Arbeitsgraphen, sonst
  speisten die `mentions`-Kanten der Seite die geschrubbten Backtick-Spans als
  Echo in die Anfrage zurueck.
- **Arm L.** Fuer `knowledge:doc`-Knoten werden die Stamm-Token des eigenen
  Dateinamens aus `phi` entfernt — Spiegelbild des Bench-Schrubbens, das
  Ziel-Basenamen aus der Anfrageprosa entfernt. Beide Varianten werden
  trainiert und berichtet; nur die geschrubbte ist die vergleichbare Zahl.
- **Arm N.** Kontrollen als Pflichtteil: eine Null-Kontrolle (isolierter
  Restart-Knoten muss bei pessimistischer Rangvergabe null Treffer bei jedem k
  liefern) und eine Ziel-Restart-Kontrolle (Seeding am Zielmodul muss das Ziel
  ~zuerst ranken), die Knoten↔Datei-Abbildung und Recall-Verrohrung end-to-end
  prueft.

## Arm O: die Regel, dass ein Teilergebnis nichts lizenziert

`arm_o_latent_ceiling.py` ist das einzige Modul des Verzeichnisses, das ein
striktes Vertragsverhalten implementiert statt zu messen, und es ist deshalb
auch das einzige mit einem Test im Kernel-Testbaum.

Der Korpus (`arm_o_latent_ceiling_corpus.json`) ist auf eine Quellrevision und
eine erwartete Zeilenzahl eingefroren (`FROZEN_SOURCE_REVISION`,
`FROZEN_EXPECTED_TOTAL = 1383`). Jede Zeile traegt einen `status`
(`prediction` oder `measured`) und einen `bucket` (`already_covered`,
`present_not_expressible`, `absent`). Nur `measured`-Zeilen zaehlen; eine
`prediction` bleibt als Provenienz erhalten und wird **nie** still zu Evidenz
aufgewertet.

`evaluate` gibt `ceiling` nur zurueck, wenn der Korpus vollstaendig **und**
revisionsgleich ist; sonst bleibt `ceiling = None` und die Entscheidung lautet
`INCOMPLETE`. Die vier Entscheidungen:

| Zustand | Entscheidung |
| --- | --- |
| unvollstaendig | `INCOMPLETE` — erst klassifizieren, dann ueber Infrastruktur reden |
| `ceiling <= 0.03` | `CLOSE` — keine latente/Tensor-Retrieval-Infrastruktur bauen |
| `0.03 < ceiling < 0.20` | `AMBIGUOUS` — Evidenz/Ablation ausweiten |
| `ceiling >= 0.20` | `LICENSE_ONE_EXPERIMENT` — genau einen budgetgleichen Versuch mit latenter Variable einfrieren |

Der Report traegt zusaetzlich eine explizite `claim_boundary`, in der vier
Dinge hart auf `False` stehen: `predictions_are_evidence`,
`partial_subset_can_license_infrastructure`, `embedding_or_tensor_backend_built`,
`production_promotion_authorized`. Das ist Invariante 4 und 5 in Datenform.

## Trust-Grenzen / Effekte

Das Verzeichnis hat **keine** Kernel-Effekte: kein `begin_effect`, keine Policy,
keine EffectLease, kein Promotionspfad, kein Import aus `daedalus`. Seine
einzigen Effekte sind Dateischreibvorgaenge in den vier Verzeichnissen `runs/tensor_embedding_v1` bis `runs/tensor_embedding_v4`
(jedes `main()` schreibt sein `arm_*.json` bzw. `triples_*.tsv`) und, in Arm F,
J und L, das Trainieren von Modellen im Prozess (PyKEEN/PyTorch).

Kein Ergebnis dieses Verzeichnisses darf ein Gate schliessen, einen Kandidaten
promoten oder Infrastruktur lizenzieren. Arm O sagt das als einziges Modul
maschinenlesbar; fuer die uebrigen gilt es ueber `AGENTS.md` und Masterplan
§1/§15 (isoliertes Experiment, keine Produktions-Promotion).

Drei Skripte lesen einen Pfad ausserhalb dieses Repositories:
`arm_l_text_tensor.py`, `arm_m_path_materialize.py` und `arm_p_contraction.py`
zeigen per Default auf einen lokalen Ordner `project_tct` im Desktop-Verzeichnis
des Owners, `arm_q_field_expansion.py` ebenso. Das Substrat der v4-Zahlen ist
also ein **zweites** Repository, nicht Daedalus selbst — was fuer die Frage
"haelt das auf gehaltenen Repositories?" (Masterplan §14) ein Vorteil ist, aber
bedeutet, dass die Skripte auf einer fremden Maschine ohne Argument nicht
laufen.

## Tests

Gemessen 2026-09-05: genau **eine** Datei unter `tests/` beruehrt dieses
Verzeichnis — [`test_tensor_latent_ceiling.py`](../../../tests/test_tensor_latent_ceiling.py)
fuer Arm O. Das ist konsistent damit, dass ein Experiment kein Produktionspfad
ist: die uebrigen Arme sind einmalige Messungen, deren Evidenz die JSON-Artefakte
unter `runs/` sind, nicht wiederholte Regressionstests. Arm O hat einen Test,
weil er ein Vertragsverhalten hat (Vollstaendigkeitsregel, `claim_boundary`),
das versehentlich aufgeweicht werden koennte.

## Verwandt

- [Wissensebene](../architecture/knowledge-layer.md),
  [Datenebene](../architecture/data-layer.md),
  [Typgraph](../architecture/type-graph.md),
  [Beobachtungsebene](../architecture/observation-layer.md) — die vier Ebenen,
  ueber denen hier gemessen wird
- [Project Twin](../architecture/twin.md) und
  [StructCore](../architecture/structcore.md) — die produktive Seite desselben
  Graphen
- [Forest v2](forest-v2.md) und insbesondere
  [Forest v2: BM25-Baseline](forest-v2-s07-bm25.md),
  [Forest v2: Fusion](forest-v2-s11-fusion.md),
  [Forest v2: Tensor-Embeddings](forest-v2-tensor-embeddings.md),
  [Forest v2: semantisches Tensor-Komposit](forest-v2-tensor-semantic-composite.md)
  — die parallel laufende Messreihe mit derselben Baseline-Disziplin
- [Hybrides Fourfold-Retrieval](fourfold-hybrid-retrieval.md) — der
  Retrieval-Vergleich, aus dem `bench_crossplane` seine Methodik teilt
- [Kontextplanung in der Orchestrierung](../architecture/orchestration.md) —
  `context_plan.py` ist der Ort, an dem ein positives Ergebnis landen wuerde
- [Speicher](../architecture/memory.md) — Embeddings und Vektorspeicher im
  Produktivpfad
- [Graph-Delta als Fitness](../graph-delta-as-fitness.md),
  [Tool-Vetting](../tool-vetting.md), [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Arm G und Arm I haben Ergebnisartefakte
  (`runs/tensor_embedding_v3/arm_g.json`, `arm_i.json`,
  `RESULTS_ARM_FGHI.md`), aber **kein Skript** in diesem Verzeichnis. Ob sie
  geloescht, umbenannt oder nie als eigene Datei existiert haben, ist aus dem
  Verzeichnis nicht ablesbar.
- **Ungeklaert:** Arm M (`arm_m_path_materialize.py`) ist laut
  `runs/tensor_embedding_v4/RESULTS.md` **nicht gelaufen** — "Skript existiert,
  kein Artefakt". Dasselbe gilt fuer die Win-Condition C, die Arm L/O braucht.
  Beide Skripte stehen also fertig da, ohne dass ein Ergebnis dazu existiert.
- **Ungeklaert:** `arm_j_tensor_vs_bm25.py` und `arm_k_fusion.py` haben keine
  `main()`-Funktion und fuehren ihre Messung auf Modulebene aus. Ob das Absicht
  ist (Einmalskript) oder ein Rest, habe ich nicht klaeren koennen.
- **Ungeklaert:** Im Verzeichnis liegen zwei Nicht-Quell-Artefakte, die wie
  Reste aussehen: ein Verzeichnis `.arm_m_ckpt` und eine Datei
  `bash.exe.stackdump`. Beides sieht tot aus; ich habe nichts geloescht.
- **Ungeklaert:** Ob und wann die von `runs/tensor_embedding_v4/SPEC.md`
  verlangte unabhaengige adversariale Gegenlesung der v4-Zahlen stattgefunden
  hat. Das Ergebnisdokument sagt selbst, dass sie aussteht.

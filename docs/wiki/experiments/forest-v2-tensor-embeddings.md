---
title: Forest v2 — Tensor-Embeddings
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/tensor_embeddings
---
# Forest v2 — Tensor-Embeddings

Dieses Verzeichnis testet eine einzige falsifizierbare Frage: bringt eine
*eingefrorene Struktur über Ebene und Rolle* etwas gegenüber gewöhnlichem
Kosinus über denselben Zahlen? Das getestete Objekt ist ein `4 x 4 x 32`
Tensor `T[plane, role, feature]` -- die vier Ebenen des Project Twin
(`code`, `type`, `data`, `knowledge`), vier Rollen (`path`, `symbol`,
`content`, `neighbor`) und ein 32-dimensionaler, vorzeichenbehafteter
lexikalischer Hash-Sketch als Filler. Der Paket-Docstring sagt die Einordnung
selbst: `CLASSIFICATION = "EXPERIMENT"`, `ACTIVE_GATE = 0`,
`AUTOMATIC_PROMOTIONS = 0`. Nichts hier ist Produktionsautorität; jedes
Suchergebnis trägt das Etikett `unverified-retrieval-proposal`. Im
Kernel/Ikarus/Ariadne-Bild sitzt das Paket als isoliertes Experiment neben der
Latent-Atlas-Hypothese aus Plan §6: es *schlägt* Kandidaten vor, es entscheidet
nichts.

Gemessen 2026-09-05: 14 Implementierungsmodule mit 8589 Zeilen plus 12
Testmodule mit 4947 Zeilen; kein Modul unter `daedalus/`, `tools/` oder
`tests/` importiert dieses Paket (geprüft per `grep -rln`).

Die zentrale Ehrlichkeit des README steht auch hier: der strukturierte Zähler
ist exakt `vec(Q)^T (K_plane ⊗ K_role ⊗ I_feature) vec(D)`. Die eingefrorenen
Kerne sind symmetrisch positiv definit, der Zähler ist also nach einer festen
linearen Transformation ein gewöhnliches Skalarprodukt über einen 512-Vektor.
Getestet wird ein **Struktur-Prior gegen flachen Kosinus**, nicht die
Behauptung, Tensoren seien Vektoren überlegen.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../experiments/forest_v2/tensor_embeddings/__init__.py) | Die Einordnung als isoliertes Gate-0-Experiment, als auslesbare Konstanten. | `CLASSIFICATION`, `ACTIVE_GATE`, `AUTOMATIC_PROMOTIONS` |
| [__main__.py](../../../experiments/forest_v2/tensor_embeddings/__main__.py) | Sechs Zeilen: `python -m experiments.forest_v2.tensor_embeddings` ruft die CLI und beendet mit deren Code. | -- |
| [contracts.py](../../../experiments/forest_v2/tensor_embeddings/contracts.py) | Die strikten, inhaltsadressierten Kontrakte. Reines stdlib und inert: kein Dateisystem, kein Netz, kein Subprozess. Die Bezeichner binden Repräsentationsbytes, sie verleihen keine Beweisautorität. | `TensorSpec`, `SeparableKernel`, `CPTerm`, `CPTensor`, `DenseTensor`, `TensorTrain`, `ContractError`, `canonical_json_bytes`, `canonical_digest`, `PLANES`, `ROLES`, `NORMALIZATION` |
| [algebra.py](../../../experiments/forest_v2/tensor_embeddings/algebra.py) | Die Referenzalgebra, bewusst als explizite Gleichung statt als Bibliotheksaufruf. Dense, CP und Tensor-Train beschreiben denselben Rang-3-Tensor und gelten nie als getrennte Evidenzquellen. Enthält auch die vorbereiteten (gecachten) Query-Formen und die Erklärkomponenten. | `AlgebraError`, `cp_to_dense`, `tt_to_dense`, `to_dense`, `flattened_cosine`, `flattened_dot`, `frobenius_norm`, `dense_separable_contraction`, `cp_separable_contraction`, `tt_separable_contraction`, `separable_contraction`, `operator_norm_upper_bound`, `normalized_structured_score`, `identity_contraction`, `identity_contraction_equivalent`, `fiber_maxsim`, `PreparedFlattenedBilinearQuery`, `prepare_flattened_bilinear_query`, `normalized_prepared_flattened_bilinear_score`, `normalized_flattened_bilinear_score`, `PreparedFeatureFiber`, `PreparedFiberMaxSimQuery`, `prepare_fiber_maxsim_query`, `prepared_fiber_maxsim`, `ContractionContribution`, `ContractionExplanation`, `contraction_contributions`, `explain_contraction` |
| [encoding.py](../../../experiments/forest_v2/tensor_embeddings/encoding.py) | Der deterministische Rollen-/Filler-Encoder. Enthält ausdrücklich keinen Modellclient: das Referenz-Backend ist vorzeichenbehaftetes Feature-Hashing, damit der komplette Lauf offline wiederholbar bleibt. Dazu die Adapter für s09-Kandidaten, Queries und Node Cards sowie die Prüfung der Quell-Evidenz. | `FillerBackend`, `HashingFillerBackend`, `PrecomputedFillerBackend`, `RoleFields`, `EncodedArtifact`, `TensorProductEncoder`, `default_spec`, `infer_plane`, `extract_symbols`, `word_tokens`, `fields_from_candidate`, `fields_from_query`, `fields_from_node_card`, `canonical_source_digest`, `node_card_source_evidence`, `validate_source_binding_evidence`, `HASH_BACKEND_ID`, `HASH_FEATURE_FAMILY`, `MAX_ROLE_FIELD_BYTES`, `MAX_SOURCE_EVIDENCE_BYTES`, `ROLE_WEIGHTS`, `SOURCE_BINDINGS` |
| [index.py](../../../experiments/forest_v2/tensor_embeddings/index.py) | Der manipulationssichtbare Index. `canonical_bytes()` ist das vollständige Persistenzformat -- das Modul hat bewusst keine `save`/`open`-Hilfe: ein autorisierter Aufrufer darf die Bytes ablegen, das Experiment selbst bleibt stdout-/lesend. | `TensorIndex`, `IndexDocument`, `SearchHit`, `IndexContractError`, `AUTHORITY`, `MAX_INDEX_DOCUMENTS` |
| [storage.py](../../../experiments/forest_v2/tensor_embeddings/storage.py) | Gemessene Skalar- und Byte-Quittungen für die drei exakten Speicherformen. Zählt persistierte Fließkommawerte ohne Form-/JSON-Metadaten. | `StorageReceipt`, `storage_receipt`, `representation_name`, `numeric_scalar_count`, `compare_exact_storage`, `STORAGE_RECEIPT_SCHEMA` |
| [retrievers.py](../../../experiments/forest_v2/tensor_embeddings/retrievers.py) | Die acht Tensor-/Kontroll-Arme als goldfreie s09-Retriever, jeder mit Eingabe- und Score-Quittung. Die strukturierten Matrizen sind wörtliche Kopien aus `EXPERIMENT_SPEC.json`, damit das nullargumentige s09-Laden keine undeklarierte Dateisystemabhängigkeit bekommt. | `FlatCosineRetriever`, `IdentityContractionRetriever`, `TensorContractionRetriever`, `FlattenedBilinearRetriever`, `TensorLateInteractionRetriever`, `PlanePermutationControl`, `RolePermutationControl`, `UniformKernelControl`, `CandidateTensorCache`, `CandidateTensorCacheInfo`, `CandidateInputReceipt`, `ScoreReceipt`, `frozen_kernel`, `FROZEN_HASH_SEEDS` |
| [baseline_retrievers.py](../../../experiments/forest_v2/tensor_embeddings/baseline_retrievers.py) | Die fünf lokalen, quittungstragenden Baselines mit demselben budgetsichtbaren Eingabematerial wie die Tensor-Arme. | `Bm25Baseline`, `RandomUniformBaseline`, `PathLexicalBaseline`, `RecencyPriorBaseline`, `FusionRrfBaseline`, `BaselineCandidateCache`, `BaselineCandidateInputReceipt`, `BaselineScoreReceipt`, `baseline_query_key`, `BASELINE_BACKEND_ID`, `BASELINE_RECEIPT_SCHEMA` |
| [arm_census.py](../../../experiments/forest_v2/tensor_embeddings/arm_census.py) | Nur Namen: der eingefrorene 13-Arm-Zensus plus die verlangte Vergleichsmatrix. Bewusst unabhängig von Rankern und Report-Validator, damit keine Abhängigkeit von Kandidatencode in den versiegelten Evaluator führt. | `TENSOR_ARM_NAMES`, `BASELINE_ARM_NAMES`, `REQUIRED_ARM_NAMES`, `REFERENCE_ARM_NAME`, `PRIMARY_ARM_NAME`, `NEGATIVE_CONTROL_NAMES`, `REQUIRED_COMPARISON_KEYS` |
| [stats.py](../../../experiments/forest_v2/tensor_embeddings/stats.py) | Metriken, gepaarte Bootstrap-Unsicherheit und die strikte Report-Validierung. Effektfrei; unvollständige oder nicht-endliche Messungen verweigern. | `reciprocal_rank`, `recall_at_k`, `first_hit_coverage`, `BootstrapDifference`, `paired_bootstrap_difference`, `validate_report`, `report_from_bytes`, `canonical_report_bytes`, `report_digest`, `ReportValidationError`, `REPORT_SCHEMA`, `PACKET_ID`, `SPEC_DIGEST`, `EVALUATION_PROTOCOL_DIGEST`, `FROZEN_SEEDS`, `BOOTSTRAP_RESAMPLES`, `QUERY_VARIANTS` |
| [benchmark.py](../../../experiments/forest_v2/tensor_embeddings/benchmark.py) | Die In-Process-Harness mit gleichen Eingaben über fünf Seeds. Der Evaluator besitzt die Gold-Labels und legt sie nie in eine `QueryView` oder eine Retriever-Quittung; nach jedem Aufruf werden die Quittungen der Arme verglichen, bevor ein Score angenommen wird. | `BenchmarkCase`, `run_benchmark`, `benchmark_case_key`, `corpus_digest`, `synthetic_role_binding_construct` |
| [sealed_eval.py](../../../experiments/forest_v2/tensor_embeddings/sealed_eval.py) | Die Datengrenze: nimmt nur inhaltsadressierte JSON-Werte entgegen, importiert keinen Retriever, akzeptiert keinen Callback. Prüft Zensus und Budgets und verbindet Rankings erst danach mit einem separat versiegelten Gold-Manifest. | `seal_manifest`, `manifest_from_bytes`, `evaluate_sealed_rankings`, `validate_sealed_report`, `validate_sealed_report_bundle`, `sealed_report_from_bytes`, `canonical_sealed_report_bytes`, `sealed_report_digest`, `candidate_manifest_digest`, `source_manifest_digest`, `SealedEvaluationError` |
| [cli.py](../../../experiments/forest_v2/tensor_embeddings/cli.py) | Die stdout-only-Schnittstelle. Jeder Befehl liest kanonisierbares JSON von stdin und schreibt genau einen kompakten JSON-Wert nach stdout. Es gibt bewusst kein `--out` und keinen Dateisystem-Writer in diesem Modul. | `build_parser`, `main`, `CLIInputError`, `ENCODE_SCHEMA`, `SEARCH_SCHEMA` |

Daneben liegen vier Dokumente, die nicht Code sind, aber den Vertrag halten:
`EXPERIMENT_SPEC.json` (die eingefrorene Repräsentation, deren Digest in
`SPEC_DIGEST` einbetoniert ist), `EVALUATION_PROTOCOL_V2.json` (die
`/2`-Vergleichssemantik, Digest in `EVALUATION_PROTOCOL_DIGEST`),
`WORK_PACKET.md` (Anspruch, Budget, Kontrollen, Kill-Kriterien) und
`RESEARCH.md` (die Abgrenzung gegen Tensor Product Representations,
ColBERT-artige Late Interaction, tensorisierte Graph-Embeddings und
Tensor-Train-Kompression).

## Die 13 Arme

`arm_census.py` friert sie ein. Referenzarm ist
`flattened_cosine_same_scalars`, primärer Arm `structured_contraction`;
`REQUIRED_COMPARISON_KEYS` verlangt jeden Arm gegen die Referenz und den
primären Arm zusätzlich gegen jede der drei Negativkontrollen.

| Arm | Klasse | Was er prüft |
| --- | --- | --- |
| `flattened_cosine_same_scalars` | `FlatCosineRetriever` | die Referenz: Kosinus über exakt dieselben 512 normalisierten Einträge |
| `identity_contraction` | `IdentityContractionRetriever` | muss algebraisch genauso ranken wie die Referenz -- der A4-Gleichheitstest |
| `structured_contraction` | `TensorContractionRetriever` | der eigentliche Struktur-Prior mit den eingefrorenen Ebenen- und Rollenmatrizen |
| `flattened_bilinear_same_kernel` | `FlattenedBilinearRetriever` | Null-Kontrolle: derselbe Kern als gewöhnliche Kronecker-Bilinearform über den flachen Vektor |
| `tensor_late_interaction` | `TensorLateInteractionRetriever` | zweiter Arm: faserweises Mean-MaxSim über denselben Tensor |
| `plane_label_permutation` | `PlanePermutationControl` | Negativkontrolle: die Ebenen-Labels der Dokumentseite sind zyklisch gegen den Kern verschoben |
| `role_label_permutation` | `RolePermutationControl` | Negativkontrolle: dasselbe für die Rollen |
| `uniform_kernel` | `UniformKernelControl` | Negativkontrolle: alle Ebenen und Rollen gleich kompatibel, die benannten Achsen kollabieren |
| `bm25` | `Bm25Baseline` | lexikalische Baseline über Inhalt plus Pfad-Token |
| `random_uniform` | `RandomUniformBaseline` | deterministische, inhaltsblinde Permutation je Fall |
| `path_lexical` | `PathLexicalBaseline` | reine Pfad-Token-Überlappung |
| `recency_prior` | `RecencyPriorBaseline` | eine vom Aufrufer behauptete Reihenfolge |
| `fusion_rrf` | `FusionRrfBaseline` | die s11-Mechanik: Partition nach Ebene, unabhängiges BM25, RRF |

Zwei dieser Baselines tragen eine ausdrücklich benannte Schwäche.
`recency_prior` bekommt seine Reihenfolge vom Evaluator zugesteckt, weil ein
`Candidate` keine Historie trägt und "Aktualität" aus Pfad, Blob-Hash oder
aktuellem Checkout abzuleiten die Kontrolle entweder erfinden oder die
Pre-Image-Grenze verletzen würde; der Korpus-Digest beweist, *was* benutzt
wurde, nicht dass es jemand unabhängig ausgestellt hat. Und die
BM25-/RRF-Konstanten sind wörtliche Kopien der geprüften s09/s11-Kontrollen,
nicht Importe der lebenden Konstanten -- sonst könnte eine spätere Revision
jener Module die Ergebnisse still verschieben, während `BASELINE_BACKEND_ID`
gleich bliebe.

## Trust-Grenzen / Effekte

- **Kein Writer im Paket.** `cli.py` hat kein `--out` und keinen
  Dateisystem-Writer; stdout-Bytes sind der Transport, und ein autorisierter
  Aufrufer entscheidet, ob sie gespeichert werden. `index.py` hält dieselbe
  Linie: `canonical_bytes()` ist das vollständige Format, aber es gibt keine
  Speicherfunktion. `contracts.py`, `stats.py` und `sealed_eval.py` erklären
  sich im Docstring ausdrücklich für effektfrei. `begin_effect` kommt im
  ganzen Paket nicht vor, weil es keine Effekt-Tür gibt.
- **Der Evaluator ist von den Kandidaten getrennt.** `benchmark.py` besitzt
  die Gold-Labels und gibt sie weder in die `QueryView` noch in eine Quittung.
  `sealed_eval.py` geht einen Schritt weiter und importiert überhaupt keine
  Retriever-Implementierung; es nimmt nur fertige, inhaltsadressierte
  Rankings entgegen. Das ist die Invariante 3/4 des Plans, hier auf
  Modulebene durchgezogen: der Kandidat kommt an seinen Evaluator nicht heran.
- **Kein Modellclient.** `encoding.py` sagt es im Docstring: das
  Referenz-Backend ist Feature-Hashing, damit der Lauf offline replaybar ist.
  Ein späteres semantisches Backend müsste `FillerBackend` erfüllen und
  dieselben Dimensions-, Digest- und Skalarbudgets einhalten.
- **Grenzen als Zahlen.** Rollenfelder sind auf `MAX_ROLE_FIELD_BYTES`
  (65 536 Bytes) begrenzt, Quell-Evidenz auf `MAX_SOURCE_EVIDENCE_BYTES`
  (262 144), ein Index oder Evaluationsfall auf `MAX_INDEX_DOCUMENTS`
  (65 536 Dokumente).
- **Keine Entscheidungs-API.** Der Docstring von `sealed_eval.py` listet
  sechs Voraussetzungen, die *vor* dem Lesen gemessener Ergebnisse existieren
  müssten, bevor `ADVANCE`/`KILL` überhaupt erwogen werden dürfte -- unter
  anderem eine extern verifizierte Signatur- oder Ledger-Vertrauenskette und
  eine vom Eigentümer beschlossene Work-Packet-Änderung. Solange die fehlen,
  ist selbst ein strukturell vollständiger Satz nur
  `STRUCTURALLY_VALID_UNANCHORED` mit `NO_SCIENTIFIC_VERDICT`, und jedes
  `superiority_claim`-Feld wird auf falsch gezwungen. Ein Aufrufer kann das
  Modul nicht durch Setzen boolescher Quittungsfelder in eine
  Entscheidungsinstanz verwandeln.

## Gemessene Evidenz (aus dem README des Verzeichnisses)

Die folgenden Zahlen stehen im README und in `results/`; ich habe sie nicht
selbst nachgerechnet.

- `results/s09_c00_smoke.json` -- ein historischer negativer Smoke-Lauf des
  abgelösten v1-Hashing-Backends. Beide Arme verfehlten die Top-20. Der
  heutige Validator lehnt die Datei absichtlich ab, weil ihr Spec-Digest vor
  dem gemeinsamen, rollenunabhängigen Filler-Raum liegt.
- `results/s09_c00_smoke_v2_invalid.json` -- der erste vollständige
  13-Arm-Versuch auf der aktuellen Spec. Seine zehn Fehlschläge legten einen
  überstrengen Validator offen, der ganze scoresortierte Tupel positionell
  verglich, obwohl die Scores je Pfad innerhalb von `1e-10` übereinstimmten.
  Der ungültige Lauf und seine Kosten von 753,704 Sekunden bleiben sichtbar.
- `results/s09_c00_smoke_v2.json` -- der korrigierte Lauf mit allen 13 Armen,
  fünf Seeds und beiden Query-Varianten ohne Laufzeitfehler. Sein
  Vergleichszensus behandelte allerdings `raw` und `scrubbed` desselben
  Basisfalls als zwei unabhängige Fälle; der `/2`-Report-Vertrag lehnt diese
  Pseudoreplikation ab und mittelt erst innerhalb eines Basisfalls.
- `results/project_tct_analysis_physics_report_v2.json` -- eine rein lokale
  Diagnose auf einem echten Repository, 127 Kandidaten und drei Gold-Dateien,
  alle 13 Arme, fünf Seeds, beide Query-Sichten, null Laufzeitfehler.
  Ausdrücklich unschmeichelhaft: mittlerer MRR `1.0` für BM25 und Fusion,
  `0.7208` für Late Interaction, `0.6579` für die strukturierte Kontraktion,
  `0.6450` für flachen Kosinus -- und `plane_label_permutation` erreichte
  ebenfalls `0.6579`. Dieser Fall liefert also keinerlei Evidenz, dass die
  benannten Ebenen-Labels die Arbeit getan haben. Bei einem einzigen Basisfall
  ist zudem jedes Bootstrap-Intervall entartet.

Zusammengefasst: das Paket ist ein vollständig ausführbarer 13-Arm-Vergleich,
aber die vorliegenden Ergebnisse sind algebraisch-strukturelle oder
historisch-diagnostische Evidenz mit `NO_SCIENTIFIC_VERDICT`. Ein vollständig
isolierter Held-out-Lauf und ein Transfer auf ein zweites Repository fehlen.

## Tests

Die Tests liegen neben dem Code im Experimentverzeichnis, nicht unter
`tests/`; ein `grep -rln "tensor_embeddings" tests/ tools/ scripts/ daedalus/`
findet nichts. Gemessen 2026-09-05 sind es 12 Dateien mit 211
Testfunktionen:

- [test_algebra.py](../../../experiments/forest_v2/tensor_embeddings/test_algebra.py)
  (34) -- CP-/Dense-/TT-Äquivalenz über 100 gesetzte Fälle, Identität gegen
  Kosinus, Konditionierung.
- [test_boundaries.py](../../../experiments/forest_v2/tensor_embeddings/test_boundaries.py)
  (6) -- die Isolationsgrenzen des Pakets: kein Writer, kein Modellclient,
  kein Import aus `daedalus/`.
- [test_encoding.py](../../../experiments/forest_v2/tensor_embeddings/test_encoding.py)
  (16) und
  [test_evidence.py](../../../experiments/forest_v2/tensor_embeddings/test_evidence.py)
  (7) -- Encoder, Node-Card-Adapter, Quell-Evidenz.
- [test_index.py](../../../experiments/forest_v2/tensor_embeddings/test_index.py)
  (16) und
  [test_storage.py](../../../experiments/forest_v2/tensor_embeddings/test_storage.py)
  (2) -- Index-Mutation, kanonische Bytes, Speicherquittungen.
- [test_retrievers.py](../../../experiments/forest_v2/tensor_embeddings/test_retrievers.py)
  (28) und
  [test_baseline_retrievers.py](../../../experiments/forest_v2/tensor_embeddings/test_baseline_retrievers.py)
  (7) -- Arme, Caches, Eingabe- und Score-Quittungen.
- [test_stats.py](../../../experiments/forest_v2/tensor_embeddings/test_stats.py)
  (35) und
  [test_benchmark.py](../../../experiments/forest_v2/tensor_embeddings/test_benchmark.py)
  (24) -- Metriken, Bootstrap, Report-Nachrechnung, Fehlerinjektion gegen den
  Scoring-Seam.
- [test_sealed_eval.py](../../../experiments/forest_v2/tensor_embeddings/test_sealed_eval.py)
  (28) -- Manifest-Bündel, verweigerte und blockierte Eingaben.
- [test_cli.py](../../../experiments/forest_v2/tensor_embeddings/test_cli.py)
  (8) -- die stdin/stdout-Grenze.

## Verwandt

- [Forest v2](forest-v2.md) -- die Experimentlinie insgesamt.
- [s09 eval](forest-v2-s09-eval.md) -- `Candidate`, `QueryView`, `plane_of`
  und die Harness, deren Kontrakt hier wiederverwendet wird.
- [s11 Fusion](forest-v2-s11-fusion.md) -- der Mechanismus hinter
  `FusionRrfBaseline`.
- [Tensor-Embedding](tensor-embedding.md) und
  [Tensor Semantic Composite](forest-v2-tensor-semantic-composite.md) -- die
  benachbarten Tensor-Spuren.
- [s10 kill](forest-v2-s10-kill.md) -- das Kill-Register, dessen
  Ebenen-Vokabular dieses Paket teilt.
- [Twin](../architecture/twin.md),
  [Type graph](../architecture/type-graph.md),
  [Data layer](../architecture/data-layer.md),
  [Knowledge layer](../architecture/knowledge-layer.md) -- die vier Ebenen,
  die hier zu einer Tensorachse werden.
- [Structcore](../architecture/structcore.md) -- die produktive Quelle der
  Node Cards.
- [Graph delta as fitness](../graph-delta-as-fitness.md),
  [Wiki-Index](../index.md).

## Ungeklärt

- Ob `PrecomputedFillerBackend` außerhalb der Tests einen Aufrufer hat, konnte
  ich nicht feststellen; das Referenz-Backend im gesamten gemessenen
  Lauf ist `HashingFillerBackend`.
- Der Docstring von `baseline_retrievers.py` sagt, Tests pinnten die kopierten
  BM25-/RRF-Konstanten an die kanonischen Implementierungen. Welcher Test das
  genau tut, habe ich nicht ausgemessen.
- `PERFORMANCE_NOTE.md` hält abgebrochene langsame Pfade und nicht validierte
  Kostenformen fest. Ob eine dieser Messungen noch dem heutigen Code
  entspricht, geht aus der Datei nicht hervor.
- Das Paket trägt `ACTIVE_GATE = 0`, während der Masterplan seit 2026-08-26
  Gate 1 als aktives Lieferungstor führt. Ob das eine bewusste Einfrierung des
  Freeze-Zeitpunkts oder Rückstand ist, sagt der Code nicht.

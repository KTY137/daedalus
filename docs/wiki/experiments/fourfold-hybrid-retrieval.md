---
title: Fourfold Hybrid Retrieval (Experiment)
type: experiment
status: retired
updated: 2026-09-06
covers: experiments/fourfold_hybrid_retrieval
---
# Fourfold Hybrid Retrieval (Experiment)

`experiments/fourfold_hybrid_retrieval` war ein eingegrenztes EXPERIMENT nach
`AGENTS.md` ("Scientific freedom") und Masterplan Abschnitt 1: eingefrorener
Spezifikationsrahmen, keine Produktionsschreibpfade, keine Promotion. Es
beantwortete eine einzige Architekturfrage: **wie sieht die Naht zwischen der
logischen Vier-Ebenen-Anfrage und den physischen Indizes aus, wenn BM25 nicht
der Gegner der Fourfold-Algebra ist, sondern ihr Zugriffspfad?**

G1-GARDEN-HYBRID-02 hat den zweiten Planner/Retriever-Stack nach der
Integrationspruefung aus dem Live-Baum entfernt. Das Verzeichnis enthaelt heute
nur den [Evidenz-Tombstone](../../../experiments/fourfold_hybrid_retrieval/README.md),
der PR #311, Experiment-Head, Merge-Commit und jeden Originalblob pinnt. Die
folgenden Architektur- und Messangaben beschreiben das wiederherstellbare
Experiment, nicht einen aktiven Produktionspfad.

Der Vorlaeufer -- die Tensor-Experimente -- hatte gemessen, dass der scheinbare
Gewinn einer Tensor-Repraesentation groesstenteils aus dem Vorindizieren kam,
waehrend ein simpler Relationsindex schneller blieb (siehe
[`G1-EXP-FOURFOLD-HYBRID-01.json`](../../work-packets/G1-EXP-FOURFOLD-HYBRID-01.json),
Feld `finding`). Die daraus abgeleitete, noch nicht widerlegte Hypothese ist die
Schichtung:

```text
natural-language query
  -> BM25 + exakte Identitaets-Treffer      (physischer Seed-Index)
  -> typisierte Relationspfade              (logische Anfrage)
  -> Forward/Reverse-Hash-Adjazenz          (physische Ausfuehrung)
  -> evidenztragende Graph-Expansion
  -> Reciprocal-Rank-Fusion
  -> unverifizierte Retrieval-Vorschlaege
```

Im Daedalus/Ikarus/Ariadne-Bild sitzt das Paket auf der Ariadne-Seite: es ist
Suchmaschinerie ueber dem [Project Twin](../architecture/twin.md), kein
Kernel-Pfad. Der Masterplan-Satz "Models and embeddings propose. Independent
evidence verifies" gilt hier woertlich -- die Ausgabe traegt
`authority = "unverified-retrieval-proposal"` und `proposal_only = True`.

Historischer Stand, gemessen 2026-09-05: 4 `.py`-Dateien, 1549 Zeilen, eine
`README.md`, eine Testdatei mit 5 Tests, zwei GitHub-Workflows. Aktueller Stand:
ein Tombstone und ein Gardening-Vertrag, keine ausfuehrbare Experimentdatei.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| `__init__.py` (retired blob `2bf6f03f...`) | Re-Export der oeffentlichen Namen; der Docstring hielt die Schichtung und den Satz "Nothing here mutates Forest/Fourfold authority or participates in promotion" fest. | -- |
| `relations.py` (retired blob `cc08a2f9...`) | Der Compiler von autoritativem `KnowledgeForest` + `FourfoldSnapshot` zu deterministischen, regenerierbaren Adjazenzbloecken. Ein Block pro `(source_plane, relation, target_plane)`. | `compile_relation_blocks`, `RelationBlockCatalog`, `TypedRelationBlock`, `RelationSignature`, `RelationCell`, `ProjectionSubject`, `MAX_RELATION_BLOCKS`, `MAX_RELATION_ENTRIES`, `MAX_AXIS_LABELS` |
| `planner.py` (retired blob `3bf58f11...`) | Die logische Anfragesprache (Schritt, Pfad, Plan) und ihre Uebersetzung auf physische Hash-Indizes plus einen deterministischen Referenz-Executor. | `RelationStep`, `PathExpression`, `ContractionPlan`, `PhysicalPlanner`, `PhysicalContractionPlan`, `PhysicalRelationIndex`, `CompiledPath`, `CompiledStep`, `IndexedHop`, `ReferenceContractionExecutor`, `ContractionResult`, `ContractionHit`, `EvidenceDerivation`, `MAX_PLAN_PATHS`, `MAX_PLAN_STEPS`, `MAX_EXECUTION_STATES`, `MAX_DERIVATIONS_PER_TARGET` |
| `retrieval.py` (retired blob `c0ec9891...`) | Der Hybrid selbst: Node-Card-Dokumente in einem BM25-Index, Seeds in der Startebene, Plan-Ausfuehrung je Seed, RRF-Fusion, quittierter Vorschlag. | `NodeDocument`, `NodeDocumentIndex`, `LexicalHit`, `HybridRequest`, `HybridRetriever`, `HybridHit`, `HybridRetrievalReceipt`, `MAX_NODE_DOCUMENTS`, `MAX_SEED_HITS`, `MAX_RESULT_HITS` |
| [`README.md`](../../../experiments/fourfold_hybrid_retrieval/README.md) | Aktiver Evidenz-Tombstone mit exakten Commit- und Blob-Identitaeten. | -- |

Fremde Abhaengigkeiten sind genau drei, alle rein rechnend:
`canonical_sha` aus [`daedalus/spine/envelope.py`](../../../daedalus/spine/envelope.py)
(ein Alias-Modul, das auf
[`daedalus/kernel/events/envelope.py`](../../../daedalus/kernel/events/envelope.py)
zeigt -- siehe [Spine](../architecture/spine.md) und
[Kernel-Events](../architecture/kernel-events.md)), `KnowledgeForest`/`ForestEdge`
aus [Structcore](../architecture/structcore.md), sowie `BM25Index`,
`IndexConfig` und `tokenize` aus dem eingefrorenen Slice
[s07 BM25](forest-v2-s07-bm25.md).

## Die drei Schichten im Detail

### 1. Relationsbloecke (relations.py)

`compile_relation_blocks(forest, snapshot, include_relations=None)` ist die
einzige Eintrittstuer. Sie verweigert vor jeder Arbeit, wenn
`forest.content_sha256` nicht zu `snapshot.source_forest_sha256` passt, und
ebenso, wenn der Snapshot Forest-Knoten auslaesst ("refusing a lossy relation
projection"). Jeder erzeugte Block bindet ueber `ProjectionSubject`
Repository-ID, Quellrevision, Forest-Digest und Fourfold-Digest; `digest` ist
jeweils ein `canonical_sha` des `to_dict`.

Vier Eigenschaften, die der Code ausdruecklich durchsetzt:

- **Many-to-many bleibt erhalten.** Zellen sind `RelationCell`-Tupel, kein
  Dictionary Quelle-zu-Ziel; ein Quellknoten mit zwei Dokumenten verliert
  keines.
- **Ungerichtete Forest-Kanten** werden in beide Richtungen eingetragen
  (`add_forest_edge` zweimal, ausser bei Selbstschleifen).
- **Evidenz wird vereinigt, Gewicht nicht doppelt gezaehlt.** Der interne
  `_CellAccumulator` fuehrt eine Menge von Beitraegern; ein zweites Vorkommen
  derselben semantischen Kante (identischer Kanten-Digest, oder ein Binding auf
  einem bereits vorhandenen Endpunktpaar) addiert Evidenzdigests, aber kein
  Gewicht.
- **Achsen sind vollstaendige Ebenen.** `source_labels` und `target_labels`
  sind die kompletten `node_ids` der jeweiligen Ebene aus dem Snapshot,
  sortiert und duplikatfrei -- nicht nur die tatsaechlich belegten Knoten.

`TypedRelationBlock.neighbors` ist bewusst ein linearer Scan und im Docstring
als "reference lookup" markiert; die brauchbaren Indizes baut erst der Planner.

### 2. Logische Pfade und physischer Plan (planner.py)

Ein `RelationStep` traegt eine `RelationSignature` und eine Richtung
(`forward` oder `reverse`), woraus sich `input_plane` und `output_plane`
ergeben. `PathExpression` prueft im Konstruktor die Ebenenkompatibilitaet
aufeinanderfolgender Schritte; `ContractionPlan` erzwingt, dass alle Pfade
*eine* Startebene und *eine* Zielebene teilen, und kombiniert sie ueber
`union` oder `intersection`. Das Beispiel aus der README ist die
Cross-Plane-Konsistenzfrage

```text
(imports @ declares) INTERSECT (documents @ mentions_type)
```

also: welcher Typ wird von einem importierten Modul deklariert *und* in der
Dokumentation desselben Ausgangsmoduls erwaehnt.

`PhysicalPlanner.compile` baut je Signatur genau einmal einen
`PhysicalRelationIndex` (Forward- und Reverse-Hashmap aus `IndexedHop`-Tupeln,
eingefroren) und benennt die verwendeten Strategien: immer
`adjacency_lookup`, bei Mehrschrittpfaden zusaetzlich `sparse_hash_join`, und
abschliessend `set_union` oder `set_intersection`.

`ReferenceContractionExecutor.execute` expandiert Zustaende Schritt fuer
Schritt. Bemerkenswert:

- Der Executor lehnt einen Plan ab, dessen `catalog_digest` nicht zum
  uebergebenen Katalog passt -- Drift zwischen Kompilat und Index ist ein
  Fehler, keine Warnung.
- Seeds ausserhalb der Startebene werden abgelehnt (`plane_of`).
- Gewichte werden entlang des Pfades multipliziert; ein nicht-endliches oder
  nicht-positives Zwischenergebnis ist ein Fehler.
- Der Zustandsraum ist hart begrenzt (`max_states`, Default
  `MAX_EXECUTION_STATES` = 100000; `max_derivations_per_target`, Default 128).
- Jeder Treffer behaelt seine `EvidenceDerivation`-Pfade: Seed, vollstaendige
  Knotenfolge, vereinigte Evidenzdigests, Gewicht. `branch_coverage` ist der
  Anteil der Planpfade, die das Ziel erreichen -- bei `intersection` also stets
  1.0, bei `union` das Rangsignal.

Die Sortierung der Treffer ist vollstaendig deterministisch: absteigend nach
`branch_coverage`, dann `derivation_count`, dann `max_weight`, zuletzt
aufsteigend nach `node_id`.

### 3. Hybrid-Retrieval (retrieval.py)

`NodeDocument` ist die Node-Card-Sicht: Knoten-ID, Ebene, Text, optionaler
Locator. `index_text` faltet ID und Locator mit in den indizierten Text -- der
Kommentar begruendet das damit, dass exakte Namen legitime Retrieval-Evidenz
sind. `NodeDocumentIndex` baut daraus einen `BM25Index` mit `path_weight` 0,
weil die Pfadgewichtung von s07 hier durch das explizite Identitaetssignal
ersetzt wird: die Trefferliste wird primaer nach `exact_identity_matches`
sortiert, erst danach nach BM25-Score und Knoten-ID. Exakte
Identitaetstreffer schlagen also jeden Score.

`HybridRetriever.search` fuehrt drei Schritte aus:

1. Seeds in der Startebene des Plans (`seed_top_k`, Default 12).
2. Direkte Kandidaten in der Zielebene -- hier praktisch ohne Begrenzung
   (`k` = Indexgroesse, gedeckelt durch `MAX_RESULT_HITS`), damit ein rein
   lexikalischer Treffer nicht durch ein zu kleines `k` verlorengeht.
3. Fuer **jeden** Seed einzeln eine Plan-Ausfuehrung; die Graph-Treffer werden
   pro Seed in die Aggregation gefaltet.

Die Fusion ist zweistufiges RRF ohne Skalenmischung:

```text
direct_rrf = direct_weight / (rrf_k + direct_rank)
graph_rrf += graph_weight * branch_coverage / (rrf_k + seed_rank + graph_rank - 1)
```

Rohe BM25-Scores und Kantengewichte gehen also nie in dieselbe Summe ein; nur
Raenge und die Verzweigungsabdeckung. `HybridRetrievalReceipt` traegt Query,
`ProjectionSubject`, `plan_digest`, `catalog_digest`, die Strategienamen, die
Seeds, die direkten Kandidaten und die fusionierten Treffer inklusive
Evidenzdigests -- und ist selbst ueber `canonical_sha` digestierbar. Das
Schema-Feld lautet `daedalus-fourfold-hybrid-retrieval/1`.

## Trust-Grenzen / Effekte

Das Paket hat **keinen** Effektpfad. Es gibt kein `begin_effect`, keinen
Dateischreiber, keinen Netzwerkaufruf, keinen Provider, keinen Scheduler, keinen
Store. Alle vier Module sind reine Funktionen und eingefrorene Dataclasses; der
einzige Zustand ist der im Speicher gehaltene Index eines `HybridRetriever`.

Die relevanten Grenzen sind Autoritaetsgrenzen, nicht Effektgrenzen:

- **Forest und FourfoldSnapshot bleiben autoritativ.** Die Bloecke sind
  regenerierbare Indizes; Masterplan Invariante 2 ("a graph delta is not
  candidate identity") gilt entsprechend fuer Relationsbloecke.
- **Kein Verifier.** Das Paket verifiziert keine neuen Cross-Plane-Kanten; es
  liest nur die bereits verifizierten Bindings des Snapshots und die
  Forest-Kanten. Masterplan Abschnitt 6 ("the evaluator is the truth boundary")
  bleibt ausserhalb.
- **Vorschlagsstatus im Datenmodell verankert.** `authority` und
  `proposal_only` sind Felder der Quittung, nicht Prosa. Das Paket kennt keinen
  Weg, sie umzuschalten.
- **Refusals vor Arbeit**: Digest-Mismatch, ausgelassene Forest-Knoten,
  Katalog-Drift, Seed in der falschen Ebene, Ebenenkonflikt zwischen Dokument
  und Katalog.
- **Budgets statt Vertrauen**: `MAX_RELATION_BLOCKS` 4096,
  `MAX_RELATION_ENTRIES` 1000000, `MAX_AXIS_LABELS` 250000,
  `MAX_NODE_DOCUMENTS` 250000, `MAX_PLAN_PATHS` 32, `MAX_PLAN_STEPS` 16,
  `MAX_SEED_HITS` 1000.

## Tests

Historisch gemessen 2026-09-05: eine Testdatei, 295 Zeilen, 5 Tests --
`test_fourfold_hybrid_retrieval_experiment.py`, im Tombstone als Blob
`88dcbdc69a0586cc955e2ca02747d5442019d5d3` erhalten. Sie baute ihre Fixtures
aus einem echten `KnowledgeForest` und
`fourfold_from_knowledge_forest`, nicht aus handgeschriebenen Bloecken:

- `test_compiler_preserves_many_to_many_edges_and_is_deterministic`
- `test_logical_intersection_compiles_to_indices_and_keeps_evidence`
- `test_hybrid_uses_bm25_as_seed_index_then_graph_expands_and_reranks`
- `test_compiler_refuses_snapshot_from_another_forest`
- `test_executor_rejects_seed_from_the_wrong_plane`

Der Lauf, den das Work Packet verlangt:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/twin/test_fourfold_hybrid_retrieval_experiment.py
```

Die beiden dedizierten Workflows `fourfold-hybrid-retrieval.yml` und
`fourfold-hybrid-retrieval-evidence.yml` wurden zusammen mit den doppelten
Stacks entfernt. Der aktive [`fourfold-v2.yml`](../../../.github/workflows/fourfold-v2.yml)
prueft den erhaltenen kanonischen Relations-Compiler;
[`test_hybrid_retrieval_gardening.py`](../../../tests/twin/test_hybrid_retrieval_gardening.py)
pinnt die Abwesenheit der beiden alten Workflows und die Wiederherstellbarkeit
der retired Blobs.

## Status und Kill-Kriterien

Das Work Packet
[`G1-EXP-FOURFOLD-HYBRID-RETRIEVAL-01.json`](../../work-packets/G1-EXP-FOURFOLD-HYBRID-RETRIEVAL-01.json)
haelt fest: Klassifikation EXPERIMENT, Gate 1,
`changes_production_runtime` false, `automatic_promotion` false, und im Feld
`evidence.status` ausdruecklich "author-side smoke only; exact-head repository
evidence remains required". Die Behauptung des Pakets ist eine
*Architektur*behauptung, keine Benchmark-Ueberlegenheit -- letztere ist im
Objekt `authority_boundary` explizit auf false gesetzt, zusammen mit
`owner_approval_minted`, `promotion_receipt_minted`, `gate_transition` und
`merge_requested`.

Die eingefrorenen Kill-Kriterien (Feld `kill_or_redesign`) sind sinngemaess:
kein Gewinn gegen BM25 plus vier unabhaengige Indizes; Gewinn verschwindet bei
permutierten Graphpfaden oder entfernter Evidenz; Gewinn vollstaendig durch
mehr Kontext erklaerbar; kein Break-Even der Bau- und Aktualisierungskosten
ueber wiederholte Anfragen; eine simplere deterministische
Relationsindex-Anfrage liefert dasselbe. Das deckt sich mit den Kill-Kriterien
in Masterplan Abschnitt 14 und mit dem Zweck der Baseline in
[s07 BM25](forest-v2-s07-bm25.md).

Das naechste laut README zulaessige Experiment ist eine eingefrorene
Benchmark-Matrix (direktes BM25, vier unabhaengige Indizes, dieser Hybrid,
derselbe Hybrid mit semantischen Multi-Vektor-Node-Cards) unter gleichen
Kontext-Token-Budgets -- also Gate-3-Arbeit, nicht Gate-1-Arbeit.

## Verwandt

- [Twin](../architecture/twin.md) -- `FourfoldSnapshot`, `FOURFOLD_PLANES` und
  die in den Baum portierte Schwester-Implementierung.
- [Structcore](../architecture/structcore.md) -- `KnowledgeForest`,
  `ForestEdge`, `content_sha256`.
- [s07 BM25](forest-v2-s07-bm25.md) -- der eingefrorene lexikalische
  Zugriffspfad und die Gate-3-Pflichtbaseline.
- [Forest v2](forest-v2.md) -- das Slice-Programm, aus dem s07 stammt.
- [Tensor Semantic Composite](forest-v2-tensor-semantic-composite.md) -- die
  Tensor-Linie, deren Messung diese Umkehrung ausgeloest hat.
- [Spine](../architecture/spine.md) und
  [Kernel-Events](../architecture/kernel-events.md) -- Herkunft von
  `canonical_sha`.
- [Type graph](../architecture/type-graph.md),
  [Knowledge layer](../architecture/knowledge-layer.md),
  [Data layer](../architecture/data-layer.md) -- die Ebenen, zwischen denen die
  Pfade laufen.
- [Graph delta as fitness](../graph-delta-as-fitness.md) -- die aeltere Notiz
  darueber, warum ein Graph-Delta kein Fitnesswert ist.
- [Agents hold no state](../decisions/agents-hold-no-state.md),
  [Tool vetting](../tool-vetting.md), [Feature backlog](../feature-backlog.md),
  [Wiki-Index](../index.md).

## Retained historical questions and resolution

- **Geklaert durch G1-GARDEN-HYBRID-01/02:** der paketierte Hybrid-Retriever und
  der separate Experiment-Stack waren zwei Implementierungswahrheiten und sind
  beide entfernt. [`relation_compiler.py`](../../../daedalus/twin/relation_compiler.py)
  bleibt der aktive Relations-Compiler; der
  [Tombstone](../../../experiments/fourfold_hybrid_retrieval/README.md) haelt die
  zweite Implementierung als reproduzierbare Git-Evidenz statt als Live-Code.
- **Ungeklaert:** ob `HybridRetriever.search` bewusst *pro Seed* einen eigenen
  `execute`-Lauf macht. Der Kommentar begruendet nur die RRF-Formel, nicht die
  Schleife; ein einziger Lauf mit allen Seeds waere billiger, wuerde aber den
  Seed-Rang als Signal verlieren. Die Kosten wachsen so linear mit
  `seed_top_k`.
- **Ungeklaert:** warum `direct_candidates` in der Quittung ungekuerzt
  mitgefuehrt wird, waehrend `hits` auf `result_limit` beschnitten ist. Bei
  einem grossen Index wird die Quittung dadurch sehr gross.
- **Ungeklaert:** ob `RelationBlockCatalog.node_plane_map` und
  `TypedRelationBlock.entry_count` ausserhalb der Tests noch Aufrufer haben.
- **Ungeklaert:** ob die Namen in `PhysicalContractionPlan.strategies` je an
  eine echte Ausfuehrungsentscheidung gekoppelt werden sollen. Heute sind sie
  Beschriftungen: der Executor macht in allen Faellen dasselbe.

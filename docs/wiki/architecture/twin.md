---
title: Twin
type: module
status: living
updated: 2026-09-07
covers: daedalus/twin
---
# Twin

`daedalus/twin` haelt die revisionsgebundenen Vertraege des vierebenigen
Project Twin (Masterplan Abschnitt 5) und die rechnerischen Projektionen
darueber. Vier Ebenen, fest verdrahtet als `FOURFOLD_PLANES = ("code", "type",
"data", "knowledge")`. Der Twin ist gemeinsames Substrat, kein viertes
oeffentliches Produkt: Quellen und inhaltsadressierte Kandidatenbaeume bleiben
autoritativ, `KnowledgeForest` aus [Structcore](structcore.md) bleibt die
kompilierte Graph-IR, und alles hier ist eine regenerierbare Projektion daraus.
Der Paket-Docstring sagt es direkt: Import erzeugt keinen Store, plant keine
Arbeit, gewaehrt kein Vertrauen und promotet nichts.

Gemessen 2026-09-06: 15 direkte `.py`-Dateien, 3846 Zeilen. Die Extraktoren, die die
Ebenen erst befuellen, liegen daneben in
[Twin-Extractors](twin-extractors.md).

## Module

### Vertraege und Forest-Anbindung

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/twin/__init__.py) | Re-Export-Oberflaeche des Pakets (eager, kein Lazy-Loader). | `__all__` |
| [`contracts.py`](../../../daedalus/twin/contracts.py) | Die kanonischen Twin-Vertraege. Eine `PlaneSnapshot` traegt `status` aus `complete`/`partial`/`absent` und muss bei `absent` einen Grund nennen -- ein fehlender Extraktor darf sich nicht als erfolgreich leere Ebene tarnen. `CrossPlaneBinding` nimmt nur unabhaengig verifizierte Kanten auf; LLM- oder Embedding-Vorschlaege gehoeren ausdruecklich nicht in `bindings`. | `FOURFOLD_PLANES`, `PlaneSnapshot`, `CrossPlaneBinding`, `FourfoldSnapshot`, `parse_fourfold_snapshot` |
| [`legacy_forest.py`](../../../daedalus/twin/legacy_forest.py) | Konservativer Adapter `KnowledgeForest` -> `FourfoldSnapshot`. Projiziert Evidenz, hebt ihre Zusicherung aber nicht an: die heutige Data-Plane bleibt `absent`, unvollstaendige Ebenen bleiben `partial`. | `fourfold_from_knowledge_forest` |
| [`projection_verifier.py`](../../../daedalus/twin/projection_verifier.py) | Mechanischer Nachweis, dass ein `FourfoldSnapshot` eine *exakte* Projektion eines gegebenen `KnowledgeForest` ist. Liefert Befunde statt eines Booleans. | `verify_forest_projection`, `require_forest_projection`, `ProjectionFinding`, `ProjectionVerificationReport` |
| [`read_projection.py`](../../../daedalus/twin/read_projection.py) | Read-only-Formung eines Forest/Fourfold-Ausschnitts fuer einen interaktiven Renderer. Hyperkanten bleiben Hyperkanten: das Lesemodell zaehlt sie, expandiert eine Klongruppe aber nie zu erfundenen Paarrelationen. | `fourfold_read_projection`, `READ_SCHEMA` |

### Sparse-Algebra und Kontraktionen

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`relation_blocks.py`](../../../daedalus/twin/relation_blocks.py) | Kanonische typisierte Sparse-Bloecke (bounded stdlib-CSR) als ausfuehrbares Orakel fuer optionale spaetere Backends. | `TypedRelationBlock`, `TypedAxis`, `RelationSignature`, `ProjectionSubject`, `MAX_REFERENCE_OPERATIONS` |
| [`semiring.py`](../../../daedalus/twin/semiring.py) | Deterministische Semiring-Referenzsemantik. Reine Beobachter: verifizieren keine Evidenz, mutieren keinen Snapshot, promoten nichts. | `Semiring`, `BooleanSemiring`, `NaturalSemiring`, `TropicalSemiring`, `EvidenceDagSemiring`, `EvidenceValue`, `MAX_NATURAL_BITS`, `MAX_EVIDENCE_ALTERNATIVES`, `MAX_EVIDENCE_TERM_ATOMS` |
| [`relation_compiler.py`](../../../daedalus/twin/relation_compiler.py) | Alleiniger Implementierungsowner der Forest/Fourfold-Relationsprojektion: prueft Admission/Completeness/Retention, kompiliert autoritative Forest-Kanten und verifizierte Snapshot-Bindings und materialisiert typisierte Bloecke. Jede Achse ist die *vollstaendige* Ebenenzugehoerigkeit aus dem Snapshot, nicht die in einer Relation beobachteten Labels -- nur so sind unabhaengig kompilierte Relationen exakt komponierbar. | `compile_relation_blocks`, `CompiledRelationBlocks`, `relation_block_name` |
| [`relation_projection.py`](../../../daedalus/twin/relation_projection.py) | Erhaltene Public-Compatibility-Fassade fuer die historische einzelne Boolean-Relation. Delegiert direkt an `compile_relation_blocks(..., BooleanSemiring(), signatures=(signature,))` und besitzt keine eigene Admission-, Diagnose- oder Materialisierungssemantik. | `boolean_relation_block_from_fourfold` |
| [`tensor.py`](../../../daedalus/twin/tensor.py) | Deterministische Sparse-Tensor-Sicht eines exakten Fourfold/Forest-Subjekts, als kanonischer Vertrag mit `status` und Provenienz. | `TensorView`, `TensorAxis`, `SparseTensorEntry`, `parse_tensor_view`, `TENSOR_STATUSES`, `MAX_TENSOR_AXES` |
| [`two_category.py`](../../../daedalus/twin/two_category.py) | Minimale evidenztragende Doppelkategorie fuer Twin-Evolution: Objekte sind typisierte Grenzen, horizontale Pfeile offene Komponenten, vertikale Pfeile Grenz-Migrationen, Quadrate Transformations-2-Zellen. Verifiziert keine Quittung, plant keinen Effekt. | `TypedBoundary`, `BoundaryPort`, `BoundaryMap`, `OpenFourfoldComponent`, `Transformation2Cell`, `VerificationStatus`, `MAX_BOUNDARY_PORTS`, `MAX_CELL_REFERENCES` |

Der zusaetzliche Kontraktionsplan-Interpreter wurde mit G1-TENSOR-01CV als
parallele Ausfuehrungs- und Budgetwahrheit entfernt. Die erhaltenen
Multi-Hop-/Hadamard-Regressionen rufen `TypedRelationBlock.matmul()` und
`hadamard()` direkt auf; der
[Kernel-Vertrag](../../FOURFOLD_TENSOR_KERNEL_CONTRACT.md#contraction-plan-experiment-pruned-g1-tensor-01cv)
enthaelt die Retirementsbegruendung.

### Referenz-Compiler

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`reference_compiler.py`](../../../daedalus/twin/reference_compiler.py) | Kompiliert *eine* beschraenkte Wiki-Anwendung in einen evidenzgebundenen Twin. Das Manifest deklariert eine endliche Quellmenge und semantische Claims -- die Claims werden nicht geglaubt, sondern aus Python-AST, deklariertem JavaScript, CSV, JSON-Schema und Markdown reproduziert. | `compile_reference_project`, `ReferenceCompileResult`, `ReferenceLimits`, `DEFAULT_REFERENCE_LIMITS`, `REFERENCE_SCHEMA`, `ReferenceCompileError` |
| [`_reference_claims.py`](../../../daedalus/twin/_reference_claims.py) | Deterministische Pruefung der deklarierten Cross-Plane-Claims; erzeugt daraus `CrossPlaneBinding`-Records mit Beweis-Digests. | `verify_claims` |
| [`_reference_common.py`](../../../daedalus/twin/_reference_common.py) | Strikte gemeinsame Helfer: Pfad-Confinement, Objekt-Whitelists, JSON-Laden, Groessengrenzen, Digest-Bildung. `CLAIM_KEYS` benennt die erlaubten Claim-Arten (`code_declares_type`, `type_matches_csv_field`, `type_matches_schema_field`, `wiki_documents_node`). | `ReferenceLimits`, `ReferenceCompileError`, `REFERENCE_SCHEMA`, `MANIFEST_KEYS`, `CLAIM_KEYS`, `safe_relpath`, `strict_object`, `strict_path_list`, `strict_json_loads`, `resolve_regular_file`, `read_file`, `decode_text`, `sha256_bytes` |
| [`_reference_inventory.py`](../../../daedalus/twin/_reference_inventory.py) | Deterministische AST-, Datenschema- und Markdown-Inventare; baut `ForestNode`/`ForestEdge` aus Python, JavaScript, CSV, JSON-Schema und Markdown-Links. | `Inventory`, `build_inventory`, `normalized_link` |

Beide eigenstaendigen Hybrid-Retriever-Stacks wurden nach der
Integrationspruefung als doppelte Implementierungswahrheiten entfernt. Der
[retained experiment tombstone](../../../experiments/fourfold_hybrid_retrieval/README.md)
pinnt PR, Commit und Originalblobs; `relation_compiler.py` bleibt der aktive,
unabhaengig getestete Relations-Compiler.

## Trust-Grenzen / Effekte

`daedalus/twin` **startet keine Effekte** und ruft `begin_effect` nirgends auf.
Es gibt keinen Provider-Call, keinen Netzzugriff, keine Datenbank. Der einzige
Dateizugriff im Paket ist lesend und liegt im Referenz-Compiler-Pfad:
`read_file` und `resolve_regular_file` in `_reference_common.py` loesen einen
Pfad relativ zu einem Wurzelverzeichnis auf, verlangen eine regulaere Datei und
schneiden bei `max_bytes` ab; `safe_relpath` verweigert Ausbrueche.
`build_inventory` liest die so aufgeloesten Dateien.

Die drei Autoritaetsgrenzen, die das Paket bewusst nicht ueberschreitet:

1. **Kein zweiter Graph.** Bloecke, Tensoren, 2-Zellen und Read-Projektionen sind
   regenerierbare Projektionen. `verify_forest_projection` ist der Test dafuer,
   dass ein Snapshot exakt aus einem Forest faellt; `require_forest_projection`
   macht daraus einen harten Aufrufer-Check.
2. **Kein Vorschlag wird Fakt.** `CrossPlaneBinding` nimmt nur verifizierte
   Kanten; der Referenz-Compiler beweist jeden Claim, bevor er ein Binding baut.
   Das ist Masterplan-Invariante 4 (Evidence-Grenze) an der Twin-Kante.
3. **Kein Closed-World-Bluff.** `compile_relation_blocks` verweigert die
   Materialisierung einer ausgewaehlten Relation, wenn eine Endpunkt-Ebene nicht
   `complete` ist, statt fehlende Beobachtung als Sparse-Null auszugeben.
   `boolean_relation_block_from_fourfold` erbt diese Regel nur ueber seine
   direkte Delegation und besitzt keine zweite Prueflogik. Analog bleibt
   `PlaneSnapshot.status` `absent` mit Grund, wo ein Extraktor fehlt.

Alle Konstruktoren sind budgetiert: `MAX_REFERENCE_OPERATIONS`,
`MAX_TENSOR_AXES`, `MAX_BOUNDARY_PORTS`, `MAX_CELL_REFERENCES`,
`MAX_NATURAL_BITS`, `MAX_EVIDENCE_ALTERNATIVES`, `MAX_EVIDENCE_TERM_ATOMS`. Eine
Anfrage kann damit nicht unbeschraenkt Rechenzeit ziehen.

## Tests

Gemessen 2026-09-06: 39 Testmodule unter `tests/twin/`, plus Fourfold-Evidenz-
Tests unter `tests/kernel/`. Auswahl:

- Vertraege und Projektion: [`test_fourfold_contracts.py`](../../../tests/twin/test_fourfold_contracts.py),
  [`test_projection_verifier.py`](../../../tests/twin/test_projection_verifier.py),
  [`test_legacy_assurance.py`](../../../tests/twin/test_legacy_assurance.py),
  [`test_fourfold_read_projection.py`](../../../tests/twin/test_fourfold_read_projection.py),
  [`test_fourfold_node_id_canonicalization.py`](../../../tests/twin/test_fourfold_node_id_canonicalization.py),
  [`test_fourfold_snapshot_locator.py`](../../../tests/test_fourfold_snapshot_locator.py)
- Relationsbloecke und Semiringe: [`test_relation_block_roundtrip.py`](../../../tests/twin/test_relation_block_roundtrip.py),
  [`test_relation_axis_lookup.py`](../../../tests/twin/test_relation_axis_lookup.py),
  [`test_relation_contractions.py`](../../../tests/twin/test_relation_contractions.py),
  [`test_relation_semiring_retention.py`](../../../tests/twin/test_relation_semiring_retention.py),
  [`test_semiring_reference.py`](../../../tests/twin/test_semiring_reference.py),
  [`test_hadamard_streaming.py`](../../../tests/twin/test_hadamard_streaming.py),
  [`test_fourfold_relation_projection.py`](../../../tests/twin/test_fourfold_relation_projection.py)
- Tensor: [`test_tensor_kernel.py`](../../../tests/twin/test_tensor_kernel.py),
  [`test_tensor_state_contract.py`](../../../tests/twin/test_tensor_state_contract.py),
  [`test_tensor_scalar_contract.py`](../../../tests/twin/test_tensor_scalar_contract.py),
  [`test_tensor_axis_canonicalization.py`](../../../tests/twin/test_tensor_axis_canonicalization.py),
  [`test_tensor_construction_bounds.py`](../../../tests/twin/test_tensor_construction_bounds.py),
  [`test_tensor_evidence_bounds.py`](../../../tests/twin/test_tensor_evidence_bounds.py),
  [`test_tensor_index_coordinate_lookup.py`](../../../tests/twin/test_tensor_index_coordinate_lookup.py),
  [`test_tensor_select_lookup.py`](../../../tests/twin/test_tensor_select_lookup.py),
  [`test_tensor_heldout_csr_probe.py`](../../../tests/twin/test_tensor_heldout_csr_probe.py),
  [`test_tensor_heldout_multihop_probe.py`](../../../tests/twin/test_tensor_heldout_multihop_probe.py),
  [`test_tensor_forest_cost_probe.py`](../../../tests/twin/test_tensor_forest_cost_probe.py)
- Gardening der entfernten Hybrid-Pfade:
  [`test_hybrid_retrieval_gardening.py`](../../../tests/twin/test_hybrid_retrieval_gardening.py)
  und [`test_fourfold_gardening.py`](../../../tests/twin/test_fourfold_gardening.py)
  pinnen Abwesenheit, kanonischen Compiler und wiederherstellbare Evidenz.
- Referenz-Compiler: [`test_wiki_reference.py`](../../../tests/twin/test_wiki_reference.py),
  [`test_reference_hardening.py`](../../../tests/twin/test_reference_hardening.py),
  [`test_reference_audit.py`](../../../tests/test_reference_audit.py)
- Zwei-Kategorie: [`test_two_category_contract.py`](../../../tests/twin/test_two_category_contract.py)
- Evidenz-/Owner-Bindung im Kernel: [`test_fourfold_evidence.py`](../../../tests/kernel/test_fourfold_evidence.py),
  [`test_fourfold_evidence_adversarial.py`](../../../tests/kernel/test_fourfold_evidence_adversarial.py),
  [`test_fourfold_evidence_owner_binding.py`](../../../tests/kernel/test_fourfold_evidence_owner_binding.py),
  [`test_fourfold_evidence_outer_ports.py`](../../../tests/kernel/test_fourfold_evidence_outer_ports.py),
  [`test_fourfold_approval_integration.py`](../../../tests/kernel/test_fourfold_approval_integration.py)

## Verwandt

- [Twin-Extractors](twin-extractors.md) -- die Extraktoren, die die vier Ebenen
  fuellen.
- [Structcore](structcore.md) -- `KnowledgeForest`, `ForestNode`, `ForestEdge`,
  `ForestHyperedge`, die autoritative kompilierte IR.
- [Type graph](type-graph.md), [Data layer](data-layer.md),
  [Knowledge layer](knowledge-layer.md) -- die aelteren Seiten zu den einzelnen
  Ebenen.
- [Kernel-Contracts](kernel-contracts.md) -- `CanonicalContract` und
  `ContractProvenance`, von denen `FourfoldSnapshot` und `TensorView` erben.
- [Spine](spine.md) -- liefert `canonical_sha` und `canonical_json` ueber die
  Alias-Fassade `daedalus.spine.envelope`, die fast jedes Modul hier importiert.
- [Fourfold Hybrid Retrieval](../experiments/fourfold-hybrid-retrieval.md) --
  die Retirementsnotiz mit dem wiederherstellbaren Experiment-Tombstone.
- [Graph delta as fitness](../graph-delta-as-fitness.md),
  [Wiki-Index](../index.md).

## Ungeklaert

- **Geklaert durch G1-GARDEN-HYBRID-01/02:** beide konkurrierenden
  Hybrid-Retriever wurden zurueckgebaut. Der aktive
  [`relation_compiler.py`](../../../daedalus/twin/relation_compiler.py) bleibt;
  der [Tombstone](../../../experiments/fourfold_hybrid_retrieval/README.md)
  behaelt PR-, Commit- und Blob-Evidenz des separaten Experiments.
- **Ungeklaert:** ob `read_projection.fourfold_read_projection` heute noch von
  einem Renderer aufgerufen wird oder nur noch vom Test.
- **Ungeklaert:** ob die Data-Plane inzwischen aus einem Extraktor `complete`
  werden kann. `legacy_forest.py` kennt in `_KIND_TO_PLANE` keine Data-Kinds,
  `projection_verifier.py` dagegen schon (`data_table`, `data_field`,
  `data_schema`, `data_schema_field`) -- die beiden Tabellen sind
  unterschiedlich weit. Siehe
  [`legacy_forest.py:19`](../../../daedalus/twin/legacy_forest.py) gegen
  [`projection_verifier.py:12`](../../../daedalus/twin/projection_verifier.py).
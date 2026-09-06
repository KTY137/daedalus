---
title: Structcore
type: module
status: living
updated: 2026-09-05
covers: daedalus/structcore
---
# Structcore

`structcore` ist der abgeleitete, mehrsprachige Strukturkern von Daedalus: ein
Index, der nie von Hand gepflegt, sondern regeneriert wird. Er beantwortet, aus
welchen Dateien ein Repository besteht, welche Einheiten (Funktionen/Methoden)
darin liegen, welche Module einander importieren, wo Duplikate und Hotspots
sitzen, und -- optional zuschaltbar -- welche Dokumente, Typen und Wiki-Kanten
es gibt. Im Kernel/Ikarus/Ariadne-Bild ist er ein Beobachter der Code-Ebene des
Project Twin, kein Effektpfad: er liest, misst und liefert Datenstrukturen; er
verändert keine Quelle, entscheidet keine Policy und nominiert keinen
Kandidaten. Der Forest-Snapshot in
[forest.py](../../../daedalus/structcore/forest.py) ist die Stelle, an der aus
dem Index eine unveränderliche, inhaltsadressierte Momentaufnahme wird, aus der
[Twin](twin.md) und [Eval](eval.md) weiterarbeiten.

Der Designvertrag steht im Paket-Docstring: stdlib-first (Python über `ast`,
alles andere über einen universellen Fenster-Normalisierungs-Pass), sauber
degradierend (`tree_sitter_language_pack` und `lizard` schärfen, sind aber nie
Pflicht), und "derive, don't maintain".

Gemessen 2026-09-05: 24 Python-Module, 11450 Zeilen.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/structcore/__init__.py) | Paketfassade; re-exportiert Index, Forest, Typen, Zyklen und DSS. `semantic_slice`/`estimate_tokens` werden über ein faules `__getattr__` nachgeladen, damit `python -m daedalus.structcore.slice` keine Import-Warnung auslöst. | `__all__` |
| [__main__.py](../../../daedalus/structcore/__main__.py) | CLI `python -m daedalus.structcore <repo>`: baut den Index, druckt eine Zusammenfassung, schreibt optional `--json` und die LPG-Projektion `--lpg`. | `print_summary`, `main` |
| [artifacts.py](../../../daedalus/structcore/artifacts.py) | Die DATEN-Ebene: Pfad-Literale je Sprache extrahieren, gegen die bekannte Dateimenge auflösen, Schemata aus CSV/JSON/NPY lesen und mit den im Code deklarierten Feldern vergleichen. Eigener Knoten-Namensraum `artifact:`. | `PathLiteral`, `extract_literals`, `ArtifactEdge`, `ResolveReport`, `resolve_literals`, `Column`, `ArtifactSchema`, `read_schema`, `SchemaComparison`, `compare_schema`, `chain_from`, `artifact_family`, `artifact_node_id`, `is_artifact_node_id`, `literal_language` |
| [cache.py](../../../daedalus/structcore/cache.py) | Persistenter Per-Datei-Cache in SQLite. Schlüssel ist ein Hash aus Dateiinhalt, Pfad, Sprache und `ANALYSIS_VERSION` -- bewusst nicht Größe plus Mtime, damit Veralten nicht darstellbar ist. Reine Optimierung: jeder SQLite-Fehler degradiert zu "kein Cache". | `FileCache`, `file_key`, `cache_root`, `enabled` |
| [churn.py](../../../daedalus/structcore/churn.py) | Git-Änderungsfrequenz je Datei (das CodeScene-Signal) plus temporale Kopplung. Degradiert vollständig: kein Git, kein PATH, Timeout ergibt ein leeres Ergebnis. | `git_churn`, `co_change_pairs`, `temporal_misses` |
| [clones.py](../../../daedalus/structcore/clones.py) | Klon-Erkennung in vier Stufen: exakt (`unit_clusters`), umbenannt (`renamed_clusters`), Near-Miss (`near_clusters`) und parserfrei über Zeilenfenster (`window_clusters`). Jeder Cluster wird sicherheitsannotiert; Fundstellen in SAFETY-Pfaden gelten als `do_not_collapse`. | `normalize_source`, `fingerprint`, `abstract_normalize`, `abstract_fingerprint`, `token_bag`, `CloneMemo`, `unit_clusters`, `window_runs`, `window_clusters_from_runs`, `window_clusters`, `renamed_clusters`, `near_clusters` |
| [cycles.py](../../../daedalus/structcore/cycles.py) | Gerichtete Zyklenstruktur des Importgraphen, iterativ und stdlib-only. Existiert, weil `spectral_partition` die Richtung wegprojiziert und die Besuchsmenge in `graph.py` nur eine Abbruchbedingung ist, kein Detektor. | `strongly_connected_components`, `self_loops`, `nontrivial_components`, `component_edges`, `cycle_report` |
| [dss.py](../../../daedalus/structcore/dss.py) | Deterministisches semantisches Super-Sampling über einen `KnowledgeForest`: Hierarchie bauen, Seed-Relevanz nach oben restringieren, über wenige hochbewertete Zweige prolongieren, je Evidenzrelation in einem eigenen Kanal diffundieren, alte Scores per ID oder Umbenennungs-Evidenz übertragen und das Ergebnis in ein Token-Budget packen. Abhängigkeitsfrei und read-only. | `HierarchyNode`, `ForestHierarchy`, `build_forest_hierarchy`, `restrict_scores`, `Prolongation`, `prolongate_scores`, `TemporalEvidence`, `TemporalCarry`, `carry_temporal_scores`, `RelationChannel`, `diffuse_relation_scores`, `DSSConfig`, `ContextItem`, `ContextPlan`, `build_context_plan`, `DSSReceipt`, `DSSResult`, `semantic_super_sample` |
| [forest.py](../../../daedalus/structcore/forest.py) | Der Code-Knowledge-Forest: ein deterministischer Multiplex-Graph mit expliziten Hyperkanten. Knoten sind Dateien und -- wenn der Index sie trägt -- Dokumente sowie Typen und Felder; Kantenschichten halten Importe, Dokumentlinks, Typstruktur und temporale Co-Change-Evidenz getrennt. Klongruppen bleiben Hyperkanten statt zu falschen Cliquen expandiert zu werden. | `ForestNode`, `ForestEdge`, `ForestHyperedge`, `KnowledgeForest`, `build_knowledge_forest` |
| [graph.py](../../../daedalus/structcore/graph.py) | Namensbasierter Symbolreferenz-Graph (Call-Graph-Näherung) mit optionaler Import- und Scope-Auflösung: gleiche Datei vor importiertem Modul vor globalem Namensfallback. Trägt außerdem die Fence-Auswertung (Erreichbarkeit und Dominanz gesperrter Pfade). | `identifiers`, `name_index`, `SymbolResolver`, `build_resolver`, `callees`, `callers`, `fenced_fragment`, `canonical_node`, `fenced_reachability`, `fenced_dominance` |
| [ignore.py](../../../daedalus/structcore/ignore.py) | Die Regeln aus `.daedalusignore` und der Projekt-Scope (`center`). Eine ignorierte Datei bleibt für die Import-Auflösung sichtbar, wird aber aus Metriken, Hotspots, Klon-Pässen und der Sprachstatistik zurückgehalten. | `IgnoreRules`, `load_ignore_rules`, `env_extra_patterns`, `ProjectScope`, `env_center`, `expand_presets`, `project_scope`, `effective_rules` |
| [imports.py](../../../daedalus/structcore/imports.py) | Import-Extraktion für alle Sprachen außer Python (das behält den präzisen `parse`-Pfad) plus Best-Effort-Auflösung gegen die bekannte Dateimenge. Unauflösbare Kanten werden verworfen, nie geraten. | `extract_imports`, `resolve_internal` |
| [index.py](../../../daedalus/structcore/index.py) | Der Orchestrator: Repo begehen, Per-Datei-Pass (parallel und cachefähig) fahren, Importe auflösen, Klon-Pässe und Churn im Elternprozess rechnen, ein Dict ausliefern. Enthält die drei Opt-in-Schalter und den prozessweiten Single-Flight-Cache. | `build_index`, `cached_index`, `backend_status`, `documents_enabled`, `types_enabled`, `wiki_enabled`, `resolution_context`, `score_modules` |
| [languages.py](../../../daedalus/structcore/languages.py) | Deklarative Sprach-Registry nach Dateiendung. Eine Sprache hinzufügen ist Daten, nicht Code. Die Felder speisen den lexikalischen Pfad, den tree-sitter-Pfad und den Safety-Zaun. | `LanguageSpec`, `spec_for`, `DocumentSpec`, `doc_spec_for` |
| [lpg.py](../../../daedalus/structcore/lpg.py) | Projektion des Forests auf das Labeled-Property-Graph-Modell. Wegwerfbar, pro Revision neu erzeugt, nie ein Speicher. Hyperkanten werden reifiziert statt expandiert; eine ungerichtete Kante ist genau eine Beziehung mit einem `directed`-Property. | `to_lpg`, `lpg_sha256`, `write_lpg` |
| [markdown.py](../../../daedalus/structcore/markdown.py) | Der zweite Parser: Markdown-Dokumente als Knotenart. Überschriftenebenen sind der Baum, Abschnitte sind die Einheiten, repo-interne Links und Wikilinks sind eigene Relationsschichten. | `is_document`, `code_modules`, `document_modules`, `DocSection`, `DocLink`, `DocumentParse`, `slugify`, `resolve_link`, `wiki_lookup`, `resolve_wiki_target`, `resolve_wiki_links`, `KnowledgeLinks`, `knowledge_links`, `parse_document`, `internal_links`, `DocSkeleton`, `document_skeleton` |
| [metrics.py](../../../daedalus/structcore/metrics.py) | Per-Datei-Gesundheitsmetriken, kommentar-bewusst je Sprache. Mit `lizard` kommt echte zyklomatische Komplexität dazu. | `file_metrics`, `lizard_available` |
| [parse.py](../../../daedalus/structcore/parse.py) | Extraktionsschicht: Code-Einheiten je Sprache (Python über `ast`, andere über tree-sitter, sonst gar nicht) und der rohe, unaufgelöste Typ-Extraktor. Der Typ-Extraktor liegt bewusst hier, weil `file_key` einen SHA-256 genau dieser Datei in jeden Cache-Schlüssel mischt. | `CodeUnit`, `extract_units`, `tree_sitter_available`, `python_units_and_imports`, `python_import_records`, `resolve_python_imports`, `python_imports`, `TypeDecl`, `FieldDecl`, `ParamDecl`, `SignatureDecl`, `AliasImport`, `PyTypeFacts`, `Annotation`, `annotation_text`, `normalize_annotation`, `flatten_union`, `split_generic`, `is_any_annotation`, `union_id`, `python_units_imports_and_types`, `python_type_facts` |
| [perfile.py](../../../daedalus/structcore/perfile.py) | Die reine, picklebare Hälfte von `build_index`: alles, was nur von den Bytes einer Datei abhängt. Läuft in einem `ProcessPoolExecutor` und ist inhaltsbasiert memoisierbar. Importiert bewusst nie `index`. | `FileAnalysis`, `analyze_file`, `analyze_chunk` |
| [report.py](../../../daedalus/structcore/report.py) | Formt ein volles `build_index`-Ergebnis in die begrenzte Nutzlast, die das Cockpit-Blatt "Structure" rendert. | `structure_summary` |
| [slice.py](../../../daedalus/structcore/slice.py) | "Distill this": eine semantische Scheibe eines Ziels statt Ganz-Repo-Konkatenation -- Fokus vollständig, Abhängigkeiten und Aufrufer als Signatur-Skelette, Rest weggelassen. Misst die Token-Reduktion gegen den vollständigen Dump. | `semantic_slice`, `estimate_tokens`, `main` |
| [tokens.py](../../../daedalus/structcore/tokens.py) | Token-Zählung für den Distill-Benchmark: echtes BPE über `tiktoken`, sonst eine Zeichen-durch-vier-Heuristik. `tokenizer_name` unterscheidet beide ehrlich. | `count_tokens`, `tokenizer_name` |
| [topology.py](../../../daedalus/structcore/topology.py) | Optionale, read-only Spektralanalyse des Importgraphen. Der Docstring sagt selbst, dass ein niedriger Schnitt keine Schreibsicherheit beweist. Ohne `networkx`, `numpy` und `scipy` degradiert das Modul. | `spectral_partition` |
| [typegraph.py](../../../daedalus/structcore/typegraph.py) | Stufe 2 der Typ-Ebene: Ganz-Repo-Auflösung der rohen Annotations-Strings aus `parse.py` zu Kanten über einen eigenen Knoten-Namensraum, plus Bericht darüber, was nicht aufgelöst wurde. | `TypeGraph`, `resolve_type_graph`, `types_by_file`, `PlainNaming`, `type_node_id`, `field_node_id`, `function_ref`, `is_type_node_id` |

## Die drei Opt-in-Schalter

`build_index` liefert per Voreinstellung genau das, was es vor Dokumenten,
Typen und Wiki-Kanten lieferte. Drei Flags erweitern das, jeweils zusätzlich
über eine Umgebungsvariable:

| Flag | Umgebungsvariable | Was dazukommt | Warum aus |
| --- | --- | --- | --- |
| `documents` | `DAEDALUS_INDEX_DOCUMENTS` | Dokumentknoten und ihre Linkschicht; `modules` trägt zusätzlich Einträge der Art Dokument | verschiebt `total_tokens`, den Nenner der Distill-Quote |
| `types` | `DAEDALUS_INDEX_TYPES` | Typ- und Feldknoten samt eigener Kantenschicht, additiv; kein bestehender Schlüssel bewegt sich | sobald der Forest Typknoten liest, ändert sich sein Inhaltsdigest, und jeder Konsument, der ihn hasht, bewegt sich mit |
| `wiki` | `DAEDALUS_INDEX_WIKI` | aufgelöste Wikilinks als eigene Schicht; setzt Dokumente voraus | eine Kantenmenge, die sich ohne bewusste Handlung ändert, verschiebt Rankings ohne nennbaren Grund |

Der Typ-Schalter deckt bewusst nicht die Per-Datei-Extraktion ab: die läuft
unbedingt, weil ein Gate vor dem inhaltsgeschlüsselten Plattencache eine
Zeile aus einem Lauf ohne Typ-Ebene als Treffer an einen Lauf mit Typ-Ebene
liefern würde -- ein leerer Typblock ohne Fehler und ohne Logzeile.

## Trust-Grenzen / Effekte

- **Read-only im Normalfall.** `build_index`, `cached_index`, `semantic_slice`,
  `build_knowledge_forest`, `semantic_super_sample`, `cycle_report` und
  `structure_summary` lesen Dateien und geben Daten zurück. Kein Schreibpfad,
  keine Policy-Entscheidung, kein Modellaufruf.
- **Zwei registrierte Effekt-Türen.** Beide sind CLI-Einstiegspunkte und
  betreten den kanonischen Boundary erst, wenn tatsächlich ein Artefakt
  geschrieben wird.
  [__main__.py](../../../daedalus/structcore/__main__.py):152 ruft
  `begin_effect` für die Zeile `cli.structcore` genau dann, wenn `--json` oder
  `--lpg` gesetzt ist; die Writer sind danach der JSON-Dump und `write_lpg`.
  [slice.py](../../../daedalus/structcore/slice.py):627 ruft `begin_effect`
  für die Zeile `cli.structcore_slice` genau dann, wenn `--out` oder `--json`
  gesetzt ist. Der Index-Aufbau und die gedruckte Zusammenfassung bleiben in
  beiden Fällen fail-open lesende Inspektion; die Registry beschreibt
  [Spine](spine.md).
- **Subprozess.** `git_churn` und `co_change_pairs` starten `git` mit hartem
  Timeout und ersetzenden Dekodierfehlern. Ein fehlendes Git ist kein Fehler,
  sondern ein leeres Ergebnis.
- **Persistenter Cache.** `FileCache` schreibt eine SQLite-Datei unter
  `cache_root()`. Das ist ein Leistungs-, kein Korrektheitspfad.
- **Prozess-Parallelität.** Der Per-Datei-Pass verteilt auf einen
  `ProcessPoolExecutor`; die Arbeiter importieren `index` nicht und können den
  Single-Flight-Build-Lock daher nicht erneut betreten.
- **Sicherheitszaun.** Die Klon-Pässe markieren Cluster in SAFETY-Pfaden als
  nicht zusammenlegbar; `fenced_reachability` und `fenced_dominance` messen,
  wie weit gesperrte Pfade in den Graphen hineinreichen. Beides ist Messung,
  keine Durchsetzung -- die liegt bei [Kernel-Policy](kernel-policy.md).

## Tests

Gemessen 2026-09-05 nennen 73 Testdateien unter `tests/` den Namen
`structcore`. Die direkt zuständigen:

- [tests/test_structcore.py](../../../tests/test_structcore.py),
  [test_structcore_api.py](../../../tests/test_structcore_api.py),
  [test_structcore_coverage.py](../../../tests/test_structcore_coverage.py) --
  Index-Grundvertrag und öffentliche Oberfläche.
- [test_structcore_parallel.py](../../../tests/test_structcore_parallel.py) --
  Unabhängigkeit von der Begehungsreihenfolge; pinnt dabei die Signatur des
  internen Sammelschritts.
- [test_structcore_ignore.py](../../../tests/test_structcore_ignore.py),
  [test_structcore_center_naming.py](../../../tests/test_structcore_center_naming.py),
  [test_structcore_cnames.py](../../../tests/test_structcore_cnames.py) --
  Scope, Ignore-Regeln, Namensvergabe.
- [test_structcore_graph.py](../../../tests/test_structcore_graph.py),
  [test_imports_graph.py](../../../tests/test_imports_graph.py),
  [tests/contracts/test_import_scc_hierarchy.py](../../../tests/contracts/test_import_scc_hierarchy.py),
  [test_topology.py](../../../tests/test_topology.py) -- Referenzgraph,
  Importkanten, Zyklen, Spektralschnitt.
- [test_clones_precision.py](../../../tests/test_clones_precision.py),
  [test_clones_string_literals.py](../../../tests/test_clones_string_literals.py) --
  Klon-Pässe.
- [test_forest.py](../../../tests/test_forest.py),
  [test_structcore_lpg.py](../../../tests/test_structcore_lpg.py) -- Snapshot
  und LPG-Projektion.
- [test_dss.py](../../../tests/test_dss.py),
  [test_context_plan.py](../../../tests/test_context_plan.py),
  [test_context_plan_latent.py](../../../tests/test_context_plan_latent.py),
  [test_temporal_ceiling.py](../../../tests/test_temporal_ceiling.py) -- DSS.
- [test_typegraph_parse.py](../../../tests/test_typegraph_parse.py),
  [test_typegraph_resolve.py](../../../tests/test_typegraph_resolve.py),
  [test_typegraph_index.py](../../../tests/test_typegraph_index.py),
  [test_typegraph_forest.py](../../../tests/test_typegraph_forest.py),
  [test_typegraph_determinism.py](../../../tests/test_typegraph_determinism.py),
  [test_typegraph_star_imports.py](../../../tests/test_typegraph_star_imports.py),
  [test_typegraph_regression.py](../../../tests/test_typegraph_regression.py),
  [test_typegraph_fixture.py](../../../tests/test_typegraph_fixture.py) --
  Typ-Ebene.
- [test_markdown_nodes.py](../../../tests/test_markdown_nodes.py),
  [test_markdown_wikilinks.py](../../../tests/test_markdown_wikilinks.py),
  [test_index_wiki_layer.py](../../../tests/test_index_wiki_layer.py) --
  Dokumente und Wiki-Kanten.
- [test_artifacts.py](../../../tests/test_artifacts.py) -- Daten-Ebene.
- [test_churn.py](../../../tests/test_churn.py) -- Git-Churn und Co-Change.
- [test_structcore_slice.py](../../../tests/test_structcore_slice.py),
  [test_slice_include_focus.py](../../../tests/test_slice_include_focus.py),
  [test_slice_egress_gate.py](../../../tests/test_slice_egress_gate.py),
  [test_slice_secret_value_shape.py](../../../tests/test_slice_secret_value_shape.py),
  [test_fenrir_slice_attack.py](../../../tests/test_fenrir_slice_attack.py) --
  Slice inklusive Angriffsfälle.
- [test_cli_effect_boundary.py](../../../tests/test_cli_effect_boundary.py),
  [test_registry_new_doors.py](../../../tests/test_registry_new_doors.py) --
  die beiden Effekt-Türen.
- [test_tokenizer_cache_identity.py](../../../tests/test_tokenizer_cache_identity.py),
  [test_honest_denominator.py](../../../tests/test_honest_denominator.py) --
  Tokenizer-Identität und der ehrliche Nenner der Reduktionsquote.
- [test_fence_anchoring.py](../../../tests/test_fence_anchoring.py),
  [test_safety_reachability.py](../../../tests/test_safety_reachability.py) --
  Fence-Metriken.

## Verwandt

- [Type graph](type-graph.md) -- die Typ-Ebene, die `typegraph.py` auflöst.
- [Data layer](data-layer.md) -- die Artefakt-Ebene aus `artifacts.py`.
- [Knowledge layer](knowledge-layer.md) und [Wiki](wiki.md) -- Dokumente und
  Vault.
- [Observation layer](observation-layer.md) -- was `structcore` bewusst nicht
  tun darf: ein Objekt zur Laufzeit ansehen.
- [Twin](twin.md), [Twin-Extraktoren](twin-extractors.md) -- die vier Ebenen
  über dem Index.
- [Eval](eval.md), [Graph delta as fitness](../graph-delta-as-fitness.md) --
  was aus Forest-Deltas gemessen wird.
- [Mapping](mapping.md), [Spine](spine.md), [Kernel-Policy](kernel-policy.md).
- [Forest v2](../experiments/forest-v2.md) und
  [s01 resolution](../experiments/forest-v2-s01-resolution.md) -- die
  Experimentlinie, die diese Repräsentation gegen einfachere prüft.
- [Wiki-Index](../index.md).

## Ungeklärt

- **`artifacts.py` hat im Paket keinen Aufrufer.** Ein Grep über `daedalus/`
  findet genau eine Nutzung, in
  [graph_delta.py](../../../daedalus/eval/graph_delta.py):436, und
  `__init__.py` exportiert nichts daraus. `build_index` baut also keine
  Artefaktknoten; ob das Absicht (noch nicht verdrahtete Ebene) oder Rückstand
  ist, geht aus dem Code nicht hervor.
- Ob `spectral_partition` noch einen produktiven Konsumenten hat oder nur von
  [tests/test_topology.py](../../../tests/test_topology.py) getragen wird, habe
  ich nicht ausgemessen.
- Die konkreten Zahlen in den Docstrings von `ignore.py` (Parsezeit gegen
  warmen Scan) und `cycles.py` (Erreichbarkeitsverlust je Modul) stammen aus
  einem Audit vom 2026-07-30 und wurden hier nicht nachgemessen.

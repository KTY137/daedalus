---
title: Type graph
type: spec
status: implemented
updated: 2026-09-05
---

# Type graph

Typen als Knoten, Felder als ihre Kinder, Funktionen als Kanten dazwischen:
`consumes` für einen Parameter, `produces` für einen Rückgabewert. Die
Extraktion ist statisch -- ein `ast.parse`, nie `typing.get_type_hints`, das
Importe ausführen würde. Es ist die Type-Ebene des vierteiligen Project Twin
(Plan §5) und ausdrücklich kein universelles Korrektheitsorakel.

Die Spur hat zwei Stufen in zwei Modulen:

- **Stufe 1, Extraktion:**
  [parse.py](../../../daedalus/structcore/parse.py) liefert je Datei rohe,
  unaufgelöste Fakten (`PyTypeFacts`: Deklarationen, Felder, Signaturen,
  Import-Bindungen). Sie liegt dort und nirgends sonst, weil `cache.file_key`
  einen SHA-256 genau dieser Datei in jeden Cache-Schlüssel mischt -- ein
  Extraktor im Nachbarmodul bekäme von neuem Code alte Cache-Zeilen serviert,
  ohne Fehler.
- **Stufe 2, Auflösung:**
  [typegraph.py](../../../daedalus/structcore/typegraph.py) macht aus den rohen
  Annotationsstrings Kanten über einen eigenen Knoten-Namensraum und berichtet,
  was es nicht auflösen wollte. Die Auflösung braucht die ganze Dateimenge,
  ist billig, läuft seriell im Elternprozess und hängt an keinem Plattencache.

Aus per Voreinstellung; `DAEDALUS_INDEX_TYPES=1` beziehungsweise das
`types`-Flag von `build_index` schaltet die Ebene zu. Die Per-Datei-Extraktion
läuft dagegen unbedingt -- ein Gate davor würde dem inhaltsgeschlüsselten
Cache erlauben, eine Zeile aus einem Lauf ohne Typebene an einen Lauf mit
Typebene zu liefern.

Wichtige Symbole: `TypeGraph`, `resolve_type_graph`, `types_by_file`,
`PlainNaming`, `type_node_id`, `field_node_id`, `function_ref`,
`is_type_node_id`, `RELATIONS`, `DEFAULT_HUB_CAP`, `TYPE_GRAPH_VERSION`,
`TYPE_FACTS_VERSION`.

## Die Auflösungsleiter: drei Stufen, dann nichts

Für einen Nominalnamen, den eine Annotation in Datei F nennt:

1. ein in F **deklarierter** Typ, getroffen über seinen vollen In-Datei-
   `qualname` -- `Outer.Inner` löst auf, ein bloßes `Inner` nicht;
2. ein Typ, der über F's **eigene explizite Import-Bindung** erreichbar ist.
   Die Modul-zu-Datei-Auflösung filtert dabei die Importkanten, die `index.py`
   ohnehin schon gerechnet hat, statt Importe erneut aufzulösen -- eine
   Typkante kann dem Importgraphen also nie widersprechen. **Ein Stern-Import
   ist keine Stufe:** `from m import *` wird nur begangen, um eine
   Mehrdeutigkeit zu *erkennen*, und kann nie alleiniger Gewinner sein.
3. nichts. Builtins und Typing-Vokabular werden in eigenen Töpfen gezählt statt
   als Fehlschläge -- 1722 Erwähnungen von `str` in `daedalus/` sind keine 1722
   Lücken. Ein Name, dessen Modul außerhalb dieses Repositories liegt, ist
   `external`, nicht `unresolved`: "woanders deklariert" und "nirgends
   deklariert" sind verschiedene Tatsachen.

## Die Invarianten

Der Modul-Docstring nennt sie durchnummeriert; der Index veröffentlicht sie als
prüfbare `excluded_from`-Liste. Die zwei tragenden:

- **I2 -- der Symbolresolver wird nicht angefasst.** Die Auflösung benutzt die
  separate Tabelle `types_by_file`; das Modul importiert `graph` nie und ruft
  `build_resolver` nie. Der Grund ist nicht Ordnung: `SymbolResolver.resolve`
  nimmt den ersten Treffer auf einen nackten Namen, eine Klasse `Foo` würde
  also eine Funktion `Foo` verdrängen; und `callees` löst jeden Bezeichner in
  einem Rumpf auf, sodass Feldnamen wie `path`, `root`, `name`, `line`,
  `source`, `module` zu erfundenen Aufrufkanten würden.
- **I5 -- nicht raten.** Die Auflösung ist zweistufig: erst wird jede
  Typdeklaration des Repositories registriert, dann werden Annotationen gegen
  die fertige Tabelle aufgelöst. Null Kandidaten heißt keine Kante und
  `unresolved` hoch; mehr als einer heißt keine Kante und `ambiguous` hoch. Es
  gibt in der ganzen Datei keinen Tie-Break. Deterministisch ist nicht
  dasselbe wie richtig: zwei Module, die beide `Result` deklarieren, ergäben
  über "erster sortierter Import" eine stabil reproduzierte **falsche** Kante,
  und ein Determinismus-Test würde sie danach schützen.

Ergänzend hält I6 die Ebene zu einer Linse statt zu einem Diffusionskanal:
nichts hier registriert eine Relation bei `dss` oder wandert in
`DEFAULT_RELATION_WEIGHTS`.

Typknoten betreten außerdem nie `all_units` -- sonst würden die Dataclasses des
Repositories zu einem einzigen Umbenennungs-Cluster in der präzisen
Klon-Stufe. Die vom Index veröffentlichte `excluded_from`-Liste nennt heute
`all_units`, `defs_by_file`, `dss_diffusion`, `duplication`, `fan_in`,
`hotspots`, `import_edges`, `module_heat`, `modules`, `n_files` und
`safety_graph_nodes` (gemessen 2026-09-05).

## Der Hub-Cap ist gemessen, nicht geraten

`DEFAULT_HUB_CAP` ist 64 und deckelt die Fan-in von `consumes`/`produces`;
`has_field`, `inherits` und `alias_of` sind Deklarationsstruktur und werden
nicht gedeckelt. Die Zahl stammt aus einer Messung auf `daedalus/`, *bevor* das
Modul existierte: ungedeckelt liegen zwei Funktionen, die denselben Typ nennen,
zwei Hops auseinander -- 1 276 024 von 2 379 471 möglichen Funktionspaaren,
53,6 % des vollständigen Graphen, allein `str` macht 939 135 davon aus. Die
sortierte Fan-in-Verteilung hat ein leeres Band zwischen Rang 8 und Rang 9,
also wurde der Cap von einem Plateau abgelesen statt beurteilt. Beide
Kantenzahlen -- behalten und unterdrückt -- werden veröffentlicht, damit
niemand die behaltene Menge für die ganze Wahrheit hält.

## Verwandt

- [Structcore](structcore.md) -- der Index, `parse.py` und `typegraph.py`
  im Zusammenhang, samt der acht Testdateien der Typspur.
- [Data layer](data-layer.md) -- die Ebene, die getragene statt deklarierter
  Formen beschreibt.
- [Knowledge layer](knowledge-layer.md),
  [Observation layer](observation-layer.md) -- die übrigen Ebenen und die
  orthogonale Beobachtung.
- [Twin](twin.md), [Twin-Extraktoren](twin-extractors.md).
- [Graph delta as fitness](../graph-delta-as-fitness.md) -- was aus
  Forest-Deltas gemessen wird.
- [Forest v2 — s02 Types](../experiments/forest-v2-s02-types.md) -- die
  Experimentspur, die diese Ebene prüft.
- [Forest v2 — Tensor-Embeddings](../experiments/forest-v2-tensor-embeddings.md)
  und [s11 Fusion](../experiments/forest-v2-s11-fusion.md) -- beide
  protokollieren, dass für `type` bis heute kein dateigranulares Artefakt
  existiert, das man indizieren könnte.
- [Wiki-Index](../index.md).

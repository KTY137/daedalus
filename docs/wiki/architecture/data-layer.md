---
title: Data layer
type: spec
status: partial
updated: 2026-09-05
---

# Data layer

Artefakte, die zwischen Programmen wandern: welches Skript liest welche
`.root`-Datei, welches schreibt welche Abbildung, welches Paper bindet sie ein.
Ein Pfad-Literal ist in LaTeX, C++, Python, Fortran, Verilog und einem Makefile
dasselbe -- deshalb verallgemeinert diese Ebene dort, wo der
[Type graph](type-graph.md) es nicht kann. Sie ist die Data-Ebene des
vierteiligen Project Twin (Plan §5) und nichts darüber hinaus: sie beschreibt
bewegte Dateien, nicht die im Code deklarierten Formen.

Implementiert in
[daedalus/structcore/artifacts.py](../../../daedalus/structcore/artifacts.py).

## Der Punkt ist der Join, nicht die Kante

Eine Kante sagt nur "dieses Skript berührt jene Datei". Interessant ist, ob das
**im Code deklarierte Schema** und das **von der Datei getragene Schema**
übereinstimmen. Eine umbenannte Branch, eine geänderte Einheit, eine still
verschobene Spalte -- das sind die Defekte, die jede Testsuite überleben und
dann in einer Doktorarbeit auftauchen. Deshalb extrahiert das Modul
`ArtifactSchema` als eigenes Datum und bietet `compare_schema` an, damit eine
spätere Lane die *Abweichung* melden kann.

## Drei Stufen, und was jede kostet

| Stufe | Was | Stand |
| --- | --- | --- |
| 0 | Pfad-Literale zu Artefaktkanten: `extract_literals`, dann `resolve_literals`. Keine Datei wird geöffnet. | implementiert, für jede Sprache mit Muster |
| 1 | Schema, wie im Code deklariert (`TTree::Branch("voltage", …)`, `read_csv(names=[…])`). | nicht implementiert; der Haken heißt `SCHEMA_FROM_CODE` und meldet `not_supported` |
| 2 | Schema, aus dem Artefakt gelesen: `read_schema`, stdlib-only für CSV, JSON und NPY. | implementiert; ROOT/HDF5/Parquet brauchen optionale Leser und melden sonst `not_supported`, nie ein leeres Schema |

Der letzte Halbsatz ist die eigentliche Regel: "wir konnten nicht nachsehen"
und "es gibt keine Spalten" dürfen nicht gleich aussehen.

## Vier Invarianten

1. **Nicht raten.** Ein Literal, das auf keine bekannte Datei zeigt, wird
   verworfen und gezählt, nie an einen Beinahe-Treffer gebunden. Passt es auf
   mehrere Kandidaten, ist es mehrdeutig und erzeugt gar keine Kante --
   dieselbe Regel, die `markdown.py` auf Dokumentlinks anwendet.
2. **Nur Metadaten, nie die Nutzlast.** Eine `.root`-Datei ist Gigabytes groß,
   ihre Branch-Liste Kilobytes. Schema-Lesen ist durch `MAX_SCHEMA_BYTES`
   begrenzt und hört am Header auf.
3. **Lesen ist nicht Ausführen.** Keine Datei wird importiert, gestartet oder
   ausgewertet. Ein feindliches Binärformat bleibt trotzdem Angriffsfläche,
   also ist jeder Leser begrenzt und ein Fehlschlag heißt `unreadable`.
4. **Artefakte sind kein Code.** Artefaktknoten bekommen einen eigenen
   ID-Namensraum (`artifact_node_id`, `is_artifact_node_id`) und betreten nie
   `modules`, `import_edges`, `all_units` oder den Symbolresolver -- dieselbe
   Ausnahme, die die Typ-Ebene in ihrer `excluded_from`-Liste veröffentlicht.

Wichtige Symbole: `PathLiteral`, `extract_literals`, `ArtifactEdge`,
`ResolveReport`, `resolve_literals`, `Column`, `ArtifactSchema`, `read_schema`,
`SchemaComparison`, `compare_schema`, `chain_from`, `artifact_family`,
`literal_language`.

## Stand 2026-09-05

Die Ebene ist implementiert, aber **nicht in den Index verdrahtet**. Ein Grep
über `daedalus/` findet genau eine Nutzung, in
[graph_delta.py](../../../daedalus/eval/graph_delta.py):436, und
`daedalus/structcore/__init__.py` exportiert nichts daraus. `build_index` baut
also keine Artefaktknoten. Ob das eine noch nicht verdrahtete Ebene oder
Rückstand ist, geht aus dem Code nicht hervor. Abgedeckt ist sie von
[tests/test_artifacts.py](../../../tests/test_artifacts.py).

## Verwandt

- [Structcore](structcore.md) -- der Index, in dem diese Ebene lebt.
- [Type graph](type-graph.md) -- die andere Ebene, die Formen beschreibt, aber
  deklarierte statt getragene.
- [Knowledge layer](knowledge-layer.md),
  [Observation layer](observation-layer.md) -- die beiden übrigen Ebenen des
  Twin und die orthogonale Beobachtungslinie.
- [Twin](twin.md), [Twin-Extraktoren](twin-extractors.md) -- die Ebenen über
  dem Index.
- [Eval](eval.md), [Graph delta as fitness](../graph-delta-as-fitness.md) --
  der einzige heutige Konsument.
- [Forest v2 — Tensor-Embeddings](../experiments/forest-v2-tensor-embeddings.md)
  und [s11 Fusion](../experiments/forest-v2-s11-fusion.md) -- Experimente, in
  denen `data` eine eigene Achse beziehungsweise ein eigener Index ist.
- [Wiki-Index](../index.md).

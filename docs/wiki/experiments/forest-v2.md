---
title: Forest v2 — Vorstudie und Slice-Wurzel
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2
---
# Forest v2 — Vorstudie und Slice-Wurzel

`experiments/forest_v2/` ist die Wurzel einer als `EXPERIMENT` klassifizierten
Vorstudie zu Gate 2 (Masterplan §11). Sie misst, wie viel eine echte
Funktions-/Methodenauflösung über den heutigen Same-Module-Fixpunkt hinaus
bringt, bevor ein Resolver gebaut wird — damit das spätere Experiment seine
eigene Hausaufgabe nicht selbst benotet. Die Wurzel selbst enthält nur zwei
Read-only-Probes und die `README.md` mit der eingefrorenen Spezifikation; die
eigentliche Arbeit liegt in den Slice-Unterverzeichnissen `s01_resolution` bis
`s11_fusion` sowie `tensor_embeddings` und `tensor_semantic_composite`, die
eigene Wiki-Seiten haben.

Einordnung: Die Vorstudie gehört zum Code/AST-Plane des
[Project Twin](../architecture/twin.md) und liefert die Baseline, gegen die
spätere Repräsentationsforschung antreten muss. Die `README.md` verbietet
explizit jeden Produktionsimport aus diesem Verzeichnis: die Studie darf
Produktionscode lesen, nie in ihn verdrahtet werden.

## Module

| Datei | Zweck | Öffentliche Symbole |
| --- | --- | --- |
| [probe_call_resolution.py](../../../experiments/forest_v2/probe_call_resolution.py) | Baseline-Probe: parst `daedalus`, `tools` und `runs` mit dem stdlib-`ast` und zählt pro Paket, wie viele Call-Sites ein Same-Module-Fixpunkt auflöst und wie viele cross-module/dynamisch bleiben. Gibt genau ein JSON-Objekt auf stdout aus, Schema `forest-v2-call-resolution-probe/1`. | `probe`, `main`, `PACKAGES` |
| [probe_cross_module_resolution.py](../../../experiments/forest_v2/probe_cross_module_resolution.py) | Fortsetzung 1: fügt pro Datei Import-Bindings hinzu (`import x`, `import x as y`, `from x import f`, relative Formen), löst Klassenbasen und Registry-Dekoratoren mit auf und teilt damit den `cross_module_or_dynamic`-Bucket der Baseline in `cross_module_repo` und `cross_module_external`. Schema `forest-v2-cross-module-resolution-probe/1`. | `probe`, `main`, `PACKAGES`, `ACCEPTANCE_FILES` |

Beide Probes definieren zusätzlich private Helfer (`_call_name`, im zweiten
Modul außerdem `_module_name`, `_collect_symbols`, `_bindings`,
`_registry_decorators`). `main()` liest optional einen Repository-Root als
`sys.argv[1]`, sonst `Path(__file__).resolve().parents[2]`.

Die Zählregel ist zwischen beiden Probes bewusst identisch gehalten: eine
Call-Site, die die großzügige Same-Module-Regel bereits beansprucht, bleibt in
`same_module_resolvable`; die neuen Buckets spalten nur die Restmasse. Ohne
diese Regel wäre ein "Gewinn" nur ein verschobener Nenner.

### s03 Data und s04 Knowledge (ohne eigene Seite)

Beide Slices bestehen aus einer Sonde, einem Test und einem winzigen
Fixture-Korpus; der Seitenplan fasst sie deshalb hier zusammen.

| Datei | Zweck | Symbole |
| --- | --- | --- |
| [s03_data/probe_data_plane.py](../../../experiments/forest_v2/s03_data/probe_data_plane.py) | EXPERIMENT s03, Gate-2-Vorarbeit "data/schema extraction": hebt deklarierte Datenartefakte (`sqlite.table` aus AST-gefalteten CREATE-TABLE-Strings, `json.schema` samt `$defs`, `csv.table` aus Kopfzeilen) mit Locator in Datenknoten und schlaegt CSV-nach-Schema-Bindungen vor. Nur lesend, kein Produktionsimport erlaubt. | `Scope`, `Field`, `DataNode`, `DataEdge` |
| [s03_data/corpus/src/*.py](../../../experiments/forest_v2/s03_data/corpus/src/plain.py) | Fixture-Korpus der Sonde: [plain.py](../../../experiments/forest_v2/s03_data/corpus/src/plain.py), [tables.py](../../../experiments/forest_v2/s03_data/corpus/src/tables.py), [fstring.py](../../../experiments/forest_v2/s03_data/corpus/src/fstring.py), [fragment.py](../../../experiments/forest_v2/s03_data/corpus/src/fragment.py), [comment_only.py](../../../experiments/forest_v2/s03_data/corpus/src/comment_only.py), [prose_mention.py](../../../experiments/forest_v2/s03_data/corpus/src/prose_mention.py), [duplicate_a.py](../../../experiments/forest_v2/s03_data/corpus/src/duplicate_a.py), [duplicate_b.py](../../../experiments/forest_v2/s03_data/corpus/src/duplicate_b.py) und die absichtlich unparsbare [unparseable_fixture.py](../../../experiments/forest_v2/s03_data/corpus/src/unparseable_fixture.py) -- letztere ist die eine "python file unparsable"-Zeile, die `daedalus.wiki.metrics` fuer diesen Baum meldet. | -- |
| [s04_knowledge/probe_knowledge_crosslinks.py](../../../experiments/forest_v2/s04_knowledge/probe_knowledge_crosslinks.py) | EXPERIMENT s04: wie viele der Querverweise, die die Prosa schon enthaelt, zeigen noch auf etwas Existierendes? Drei Kantenklassen (Link, Backtick-Symbol, Wikilink) mit je eigener Aufloesungsregel; stdlib, keine Schreibvorgaenge, ein JSON-Objekt auf stdout. | `strip_fences`, `slugify`, `mask_inline_code`, `iter_markdown`, `build_corpus_index` |
| [s04_knowledge/corpus/pkg/*.py](../../../experiments/forest_v2/s04_knowledge/corpus/pkg/s04_solo.py) | Fixture-Korpus: [s04_solo.py](../../../experiments/forest_v2/s04_knowledge/corpus/pkg/s04_solo.py), [one/s04_report.py](../../../experiments/forest_v2/s04_knowledge/corpus/pkg/one/s04_report.py), [two/s04_report.py](../../../experiments/forest_v2/s04_knowledge/corpus/pkg/two/s04_report.py) (Namenskollision fuer die Mehrdeutigkeitsregel), [a/s04mod/s04_thing.py](../../../experiments/forest_v2/s04_knowledge/corpus/pkg/a/s04mod/s04_thing.py), [b/s04mod/s04_thing.py](../../../experiments/forest_v2/s04_knowledge/corpus/pkg/b/s04mod/s04_thing.py), [spine/s04_attempt.py](../../../experiments/forest_v2/s04_knowledge/corpus/pkg/spine/s04_attempt.py). | -- |

## Trust-Grenzen / Effekte

Keine. Beide Module sind ausdrücklich read-only und tragen `"read_only": True`
im Ausgabeobjekt:

- kein Import von Repository-Code (nur `ast`, `json`, `sys`, `pathlib`);
- keine Schreibpfade, kein Netz, kein Subprozess;
- Ausgabe ausschließlich `print(json.dumps(...))` auf stdout.

Der Docstring von `probe_call_resolution.py` hält fest, dass ein `main`, das
nur druckt, bewusst *kein* Effekt-Entrypoint ist und daher nicht in der
Effekt-Registry steht (vgl. [tools](../tooling/tools.md) und
[Kernel-Policy](../architecture/kernel-policy.md)). Die Probes lesen den Baum
per `rglob("*.py")`, parsen Text und führen nichts aus, was sie parsen.

## Tests

Für die beiden Wurzel-Probes existiert unter `tests/` keine Abdeckung
(gemessen 2026-09-05: `grep -rl "probe_call_resolution\|probe_cross_module_resolution" tests/`
liefert nichts). Getestet wird stattdessen slice-lokal, z. B.
[s01_resolution/test_s01_resolver.py](../../../experiments/forest_v2/s01_resolution/test_s01_resolver.py),
[s03_data/test_probe_data_plane.py](../../../experiments/forest_v2/s03_data/test_probe_data_plane.py),
[s04_knowledge/test_probe_knowledge_crosslinks.py](../../../experiments/forest_v2/s04_knowledge/test_probe_knowledge_crosslinks.py)
und [s07_bm25/test_bm25_index.py](../../../experiments/forest_v2/s07_bm25/test_bm25_index.py).
`s01_measure` importiert die Baseline-Probe und bricht mit einem Paritätsfehler
ab, wenn ein Replikat ihrer Regeln die Bucket-Zahlen nicht exakt reproduziert —
das ist die schärfste vorhandene Prüfung dieser Wurzel-Module.

## Retention negativer Evidenz

Die `README.md` behält zwei Korrekturen ausdrücklich im Text:

1. Die Vorstudie hatte `tools/guarded_call.py` als "statisch unsichtbar"
   gepinnt. Der Import-Binding-Probe zeigt, dass die Sink-Importe dort
   funktionslokal sind und ein Whole-Tree-Walk sie attribuiert. Die
   Unsichtbarkeitsklasse ist enger als dokumentiert: "unsichtbar für den
   Same-Module-Fixpunkt", nicht "statisch unsichtbar".
2. Die Schlagzeile von Slice s01 ("+7.92 pp") ist als gegen eine dominierte
   Kontrolle gemessen zurückgezogen; auf einem Held-out-Korpus ist der
   Anteilsgewinn negativ. Der Text bleibt wörtlich stehen und wird im
   Abschnitt *Retraction* beantwortet. Details auf
   [Slice s01](forest-v2-s01-resolution.md).

## Verwandt

- [Slice s01 — Resolution](forest-v2-s01-resolution.md)
- [Slice s02 — Type-Plane](forest-v2-s02-types.md)
- [Slice s05 — Snapshot](forest-v2-s05-snapshot.md)
- [Slice s06 — Node Cards](forest-v2-s06-cards.md)
- [Slice s07 — BM25](forest-v2-s07-bm25.md)
- [Slice s08 — Graph-Baselines](forest-v2-s08-graph-baselines.md)
- [Slice s09 — Eval](forest-v2-s09-eval.md)
- [Slice s10 — Kill-Kriterien](forest-v2-s10-kill.md)
- [Slice s11 — Fusion](forest-v2-s11-fusion.md)
- [Tensor-Embeddings](forest-v2-tensor-embeddings.md)
- [Tensor Semantic Composite](forest-v2-tensor-semantic-composite.md)
- [Project Twin](../architecture/twin.md), [Type-Graph](../architecture/type-graph.md),
  [Knowledge-Layer](../architecture/knowledge-layer.md)
- [Graph-Delta als Fitness](../graph-delta-as-fitness.md), [Wiki-Index](../index.md)

## Ungeklärt

- **Ungeklärt:** Ob die in der `README.md` genannte Expiry (2026-10-31 für die
  Vorstudie, 2026-09-15 für s01) inzwischen durch eine Neumessung ersetzt
  wurde; im Baum steht nur der ursprüngliche Text.
- **Geklaert (2026-09-05):** `experiments/forest_v2/s03_data` und `s04_knowledge`
  haben im Seitenplan keine eigene Seite (eine Sonde plus Fixtures je Slice);
  ihre Module sind oben in einem eigenen Abschnitt aufgefuehrt.
---
title: Twin-Extraktoren
type: module
status: living
updated: 2026-09-05
covers: daedalus/twin/extractors
---
# Twin-Extraktoren

`daedalus/twin/extractors` ist die Zulieferer-Schicht des [Project Twin](twin.md):
sie verwandelt unveraenderliche Quell-Artefakte in *gestufte* Beobachtungen ueber
die vier Ebenen Code/AST, Type, Data und Knowledge. Der entscheidende Satz steht
in jedem der vier Docstrings und ist die Trust-Grenze des Verzeichnisses:
Extraktor-Ausgabe ist **nicht** autoritativ. `contracts.py` formuliert es als
"publication into a KnowledgeForest or FourfoldSnapshot remains a separate
verification boundary", `tree_sitter_adapter.py` als "Tree-sitter establishes
syntax structure, not semantic truth". Das ist die Umsetzung von
Masterplan-Invariante 4 (Evidence-Boundary) auf der Extraktionsseite: Adapter
schlagen vor, ein Verifier entscheidet.

Gemessen 2026-09-05: 5 `.py`-Dateien, 1114 Zeilen. Beide Adapter haengen an
optionalen Fremdbibliotheken und sind so gebaut, dass ihr Fehlen eine eigene
Ausnahme ist (`TreeSitterUnavailable`, `RootReaderUnavailable`) und kein
stiller Leerbefund.

## Module

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/twin/extractors/__init__.py) | Re-Export-Fassade. Buendelt Vertraege, Registry und beide Adapter zu einer alphabetisch sortierten `__all__`-Liste. | `__all__` |
| [`contracts.py`](../../../daedalus/twin/extractors/contracts.py) | Sprachneutrale, eingefrorene Dataclasses fuer Extraktor-Ein- und -Ausgabe. Jede validiert im `__post_init__` und wirft `ValueError`, statt einen kaputten Datensatz weiterzureichen. | `LanguageSpec`, `SourceArtifact`, `ExtractorCapabilities`, `ExtractorDiagnostic`, `ExtractorResult` |
| [`registry.py`](../../../daedalus/twin/extractors/registry.py) | Deterministische pfadbasierte Sprach- und Formaterkennung. Kein Inhalts-Sniffing, kein Rateverfahren. | `LANGUAGE_SPECS`, `LanguageDetection`, `detect_language`, `registered_language_ids` |
| [`tree_sitter_adapter.py`](../../../daedalus/twin/extractors/tree_sitter_adapter.py) | Optionaler Tree-sitter-Parser fuer Rust, Java und C/C++ (inklusive ROOT-Makros). Liefert Symbole mit Byte-Bereichen und pro Symbol einen Evidenz-Digest. | `parse_artifact`, `StructuralSymbol`, `StructuralParseReport`, `ParseLimits`, `DEFAULT_PARSE_LIMITS`, `TreeSitterUnavailable` |
| [`root_file_adapter.py`](../../../daedalus/twin/extractors/root_file_adapter.py) | Optionaler Uproot-Reader, der ROOT-Dateien nur inventarisiert: Objektklassen und Feldschemata, ohne Event-Payload zu lesen. | `inspect_root_artifact`, `RootObjectRecord`, `RootFieldRecord`, `RootDataReport`, `RootReadLimits`, `DEFAULT_ROOT_READ_LIMITS`, `RootReaderUnavailable` |

## Die Vertraege

`SourceArtifact` ist der einzige zulaessige Eingang: `repository_id`,
`source_revision`, ein normalisierter POSIX-Pfad, `content_sha256`,
`size_bytes`, `language_id`, `artifact_kind` und optionale
`framework_hints`. Absolute Pfade, Backslashes und Punkt-Segmente werden
abgelehnt; damit kann ein Artefakt-Datensatz nicht aus dem Repository
herauszeigen.

`ExtractorResult` ist der einzige zulaessige Ausgang. Sein Statusfeld kennt
`complete`, `partial`, `unsupported` und `failed`, und die Nachbedingungen sind
im Konstruktor hart verdrahtet:

- `complete` verlangt zurueckbehaltene Evidenz und verbietet Diagnosen der
  Schwere `error`;
- `partial` verlangt Evidenz **und** mindestens eine Diagnose, die die
  Einschraenkung erklaert;
- `unsupported` und `failed` duerfen ueberhaupt keinen semantischen Inhalt
  publizieren — `node_ids`, `relation_sha256s` und `evidence_sha256s` muessen
  leer sein — und muessen ihren Zustand begruenden.

Das ist der Ort, an dem "der Parser hat nichts gefunden" und "der Parser konnte
nicht laufen" strukturell unterscheidbar bleiben.

`LanguageSpec.semantic_planes` ist auf die Menge `code`, `type`, `data`,
`knowledge` beschraenkt — eine fuenfte Ebene laesst sich hier nicht anmelden,
passend zu Masterplan Abschnitt 5 und der dort verbotenen Default-Richtung
"new graph planes without demonstrated marginal evidence".

## Erkennung

`LANGUAGE_SPECS` fuehrt 21 Eintraege (gemessen 2026-09-05), von `python` und
`rust` ueber `typescript` und `markdown` bis `parquet` und `hdf5`. Der
Suffix-Index ist nach absteigender Suffixlaenge sortiert, damit die laengere
Schema-Endung vor der kuerzeren JSON-Endung greift. Zusaetzlich existiert eine
Tabelle exakter Build-Dateinamen (Cargo, Maven, Gradle, CMake, Make), die mit
Confidence `exact` statt `suffix` zurueckkommt; `registered_language_ids`
vereinigt beide Quellen.

Der Docstring von `detect_language` haelt eine bewusste Entscheidung fest: die
binaere ROOT-Endung ist ein Datenformat, ROOT-C++-Quelltext bleibt C++, und die
grossgeschriebene Makro-Endung bleibt die konventionelle ROOT/Cling-Makroform.
Die Erkennung ist ausdruecklich schwaecher als Extraktion — sie sagt nur,
welcher Adapter ein Artefakt anfassen darf.

## Trust-Grenzen / Effekte

Das Verzeichnis enthaelt **keinen** Writer, keinen Prozess-Spawn, keinen
Netzzugriff und keinen Provider-Aufruf. Es gibt keinen `begin_effect`-Aufruf,
weil es keinen registrierungspflichtigen Effekt gibt: beide Adapter bekommen
den Inhalt als Bytes uebergeben und oeffnen selbst keine Datei. Der
ROOT-Adapter wickelt den Puffer in einen Speicher-Stream, statt Uproot einen
Pfad zu geben — auch das ist kein Dateisystemzugriff.

Die Integritaetspruefung laeuft vor jeder Arbeit: beide Einstiegsfunktionen
verifizieren, dass der SHA-256 des uebergebenen Inhalts genau
`artifact.content_sha256` ergibt und dass die Laenge zu `size_bytes` passt. Ein
Inhalt, der nicht zu seinem Digest gehoert, wird nicht geparst.

Ressourcengrenzen sind Datensaetze, keine Konstanten im Code: `ParseLimits`
(4 MB Quelle, 500 000 Syntaxknoten, 100 000 Symbole) und `RootReadLimits`
(512 MB Datei, 100 000 Objekte, 100 000 Felder pro Objekt, 500 000 Felder
gesamt). Ueberschreitung erzeugt einen `failed`-Report mit den Codes
`source-too-large`, `node-limit-exceeded`, `symbol-limit-exceeded`,
`root-file-too-large` oder `root-object-limit-exceeded` — nicht eine Exception,
die den Aufrufer zum Raten zwingt.

Determinismus ist gewollt und sichtbar: Symbole werden nach Startbyte, Endbyte
und Knoten-ID sortiert, Objektpfade sortiert durchlaufen, und jeder Report
bekommt ueber `canonical_sha` aus
[`daedalus/spine/envelope.py`](../../../daedalus/spine/envelope.py) einen
stabilen Digest. Die Schema-Bezeichner sind versioniert
(`daedalus-tree-sitter-report/1`, `daedalus-root-data-report/1`,
`daedalus-root-relation/1` und weitere).

Der ROOT-Adapter faengt Feld-Metadatenfehler pro Objekt ab und degradiert den
Gesamtstatus auf `partial` mit der Diagnose `root-field-metadata-failed`, statt
den Lauf abzubrechen. Das Dateihandle wird in einem `finally`-Block geschlossen.

> **Extern:** Tree-sitter ist ein inkrementeller Parser-Generator; die
> Grammatiken liegen als eigene Pakete vor, weshalb der Adapter sie per
> `importlib` laedt und ihr Fehlen als eigenen Fehlerfall behandelt.
> Quelle: https://tree-sitter.github.io/tree-sitter/

> **Extern:** Uproot liest ROOT-Dateien in reinem Python und erlaubt es, nur
> Verzeichnis- und Branch-Metadaten zu inspizieren, ohne Arrays zu
> materialisieren — genau das nutzt der Adapter.
> Quelle: https://uproot.readthedocs.io/

## Tests

Gemessen 2026-09-05, drei Dateien mit zusammen 15 Testfunktionen:

- [`tests/twin/test_extractor_contracts.py`](../../../tests/twin/test_extractor_contracts.py)
  (8 Tests) — Validierung der Dataclasses und der Statusnachbedingungen.
- [`tests/twin/test_tree_sitter_extractors.py`](../../../tests/twin/test_tree_sitter_extractors.py)
  (4 Tests) — Parserpfad inklusive Verhalten bei fehlender Grammatik.
- [`tests/twin/test_root_file_extractor.py`](../../../tests/twin/test_root_file_extractor.py)
  (3 Tests) — ROOT-Inventar ohne Payload-Lesung.

Ausserhalb von `tests/` benutzen drei Sonden das Paket:
[`scripts/fourfold_repo_probe.py`](../../../scripts/fourfold_repo_probe.py),
[`scripts/fourfold_tree_sitter_probe.py`](../../../scripts/fourfold_tree_sitter_probe.py)
und
[`scripts/fourfold_root_file_probe.py`](../../../scripts/fourfold_root_file_probe.py).

## Verwandt

- [Project Twin](twin.md) — der Konsument dieser Beobachtungen.
- [Kernel](kernel.md) — wo Evidenz zu einem Evidence-Paket wird.
- [Kernel-Vertraege](kernel-contracts.md) — die kanonischen Fourfold-Schemata.
- [Datenebene](data-layer.md) und [Typgraph](type-graph.md) — die Ebenen, die
  der ROOT- beziehungsweise der Tree-sitter-Adapter beliefern.
- [Wissensebene](knowledge-layer.md) — die Ebene, fuer die hier noch kein
  Adapter existiert.
- [Beobachtungsebene](observation-layer.md) — warum Beobachtung und Behauptung
  getrennt bleiben.
- [Skripte](../tooling/scripts.md) — die drei Fourfold-Sonden.
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** `ExtractorCapabilities` wird von keinem Modul in diesem
  Verzeichnis erzeugt oder geprueft; die Klasse ist ein Vertrag ohne Aufrufer
  im Paket. Wer sie fuellen soll, steht nirgends im Code.
- **Ungeklaert:** Kein Adapter fuer Python, TypeScript, Markdown, CSV oder SQL
  existiert hier, obwohl `LANGUAGE_SPECS` diese Sprachen kennt. Ob die
  Extraktion dieser Sprachen anderswo liegt oder offen ist, laesst sich aus
  diesem Verzeichnis nicht entscheiden.
- **Ungeklaert:** `ExtractorResult.node_ids` erzwingt Eindeutigkeit, waehrend
  der ROOT-Adapter die Knoten-IDs aus einem auf 20 Zeichen gekuerzten
  Pfad-Digest bildet. Ob eine Kollision praktisch auftreten kann, ist nicht
  gemessen.
- **Ungeklaert:** Der Tree-sitter-Adapter deckt nur fuenf Sprach-IDs ab; fuer
  alle anderen wirft der Grammatik-Loader. Ob stattdessen ein
  `unsupported`-Result gedacht war, geht aus dem Code nicht hervor.

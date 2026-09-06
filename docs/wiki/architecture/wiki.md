---
title: Wiki
type: module
status: living
updated: 2026-09-05
covers: daedalus/wiki
---
# Wiki

`daedalus/wiki` ist die Wissensebene als Werkzeug: die eine Haelfte liest einen
Vault im Obsidian-Format, die andere plant und prueft ein automatisch
erzeugtes Projekt-Wiki. Im Bild des Masterplans gehoert das Paket zur
Knowledge-Ebene des Project Twin (Dokumentation, ADRs, Begriffe) und dabei
ausdruecklich auf die Evidenzseite: `verify` ist ein deterministischer Pruefer,
der entscheidet, ob eine Seite ueber den Baum die Wahrheit sagt. Modelle
schlagen Text vor, dieser Code entscheidet. Das ist dieselbe Grenze wie
ueberall sonst im Kernel — siehe [Knowledge-Layer](knowledge-layer.md).

Das Paket zerfaellt in zwei bewusst getrennte Haelften, so beschrieben im
Paket-Docstring:

- **Lesen** — [__init__.py](../../../daedalus/wiki/__init__.py) re-exportiert
  nur `vault` und `links`. Beides ist read-only konstruiert; der Schreibpfad
  fuer einen menschlichen Editor ist bewusst nicht gebaut, weil er eine eigene
  Gate-Liste und eine Sicherheitsreview braucht.
- **Erzeugen und messen** — `plan` zerlegt einen Baum in Themen mit fertigen
  Auftragsprompts, `verify` prueft die entstandenen Seiten gegen denselben
  Baum, `metrics` misst die Struktur des Ergebnisses, `qml_index` liest
  QML-Namen fuer das Vokabular, `treewalk` entscheidet, was nicht zum Baum
  gehoert. Keines davon ruft ein Modell, oeffnet das Netz oder schreibt
  ausserhalb seiner deklarierten Ausgabe. Alle werden als Submodule
  importiert, nicht re-exportiert, damit ein Paketimport ihre Baumlaeufe nicht
  bezahlt. (Der Docstring nannte bis G1-WIKI-01 nur `plan` und `verify`.)

Gemessen 2026-09-05 nach G1-WIKI-01: 9 Python-Dateien, 2434 Zeilen. Groesste
Datei ist [metrics.py](../../../daedalus/wiki/metrics.py) mit 474 Zeilen.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/wiki/__init__.py) | Paket-Docstring plus Re-Export der Lese-Haelfte. `plan`, `verify`, `metrics` und `qml_index` werden absichtlich **nicht** re-exportiert. | `Vault`, `Page`, `WikiLink`, `LinkIndex`, `VAULT_VERSION`, `LINKS_VERSION`, `PAGE_SUFFIX`, `PROJECT_VAULT_DIR` |
| [__main__.py](../../../daedalus/wiki/__main__.py) | CLI mit drei Unterbefehlen (`plan`, `verify`, `health`), die jeweils an das Modul delegieren, das die Arbeit schon besitzt. Submodule werden erst im Handler importiert. | `build_parser`, `main`, `EPILOG` |
| [vault.py](../../../daedalus/wiki/vault.py) | Was ein Vault auf der Platte ist, wie Seiten gelesen werden — und der Pfad-Validator, der ganz oben in der Datei steht, bevor es einen Endpunkt gibt, der ihn braucht. Enthaelt einen eigenen, absichtlich unvollstaendigen Frontmatter-Parser. | `Vault`, `Page`, `VaultPathError`, `vault_rel`, `read_page`, `discover_pages`, `discover_vaults`, `page_tree`, `parse_frontmatter`, `MAX_PAGES`, `MAX_PAGE_BYTES`, `RESERVED_TOP_LEVEL` |
| [links.py](../../../daedalus/wiki/links.py) | Wikilinks parsen, Vorwaerts- und Rueckwaertskanten bauen, unverlinkte Erwaehnungen finden, den **lokalen** Graphen um eine Seite ziehen. Ein globaler Graph wird gar nicht erst gebaut. | `WikiLink`, `LinkIndex`, `extract_wikilinks`, `build_index`, `backlinks`, `unlinked_mentions`, `local_graph`, `MAX_LINKS_PER_PAGE`, `MAX_LOCAL_NODES`, `MAX_MENTIONS_PER_PAGE` |
| [plan.py](../../../daedalus/wiki/plan.py) | Die deterministische Haelfte der Wiki-Erzeugung: Baum vermessen, nach Verzeichnissen in Themen buendeln, per Zeilenzahl gleichmaessig auf Autoren verteilen, je Autor einen Prompt fuellen. | `Topic`, `survey`, `assign`, `build_plan`, `main`, `PROMPT`, `SKIP_DIRS`, `MIN_BUCKET_FILES`, `MIN_BUCKET_LOC` |
| [verify.py](../../../daedalus/wiki/verify.py) | Der Pruefer. Fuenf Befunde, drei davon verdikt-relevant. Baut das Vokabular aus AST-Definitionen, Config-Keys und einem Wort-Scrape ueber den Baum — und schliesst dabei die Baeume aus, die nicht fuer sich selbst buergen duerfen. | `Finding`, `verify`, `exclusions`, `index_symbols`, `tree_vocabulary`, `main`, `SYMBOL_SHAPE`, `EXTERNAL_MARK`, `FILE_SUFFIXES`, `BUILTIN_NAMES` |
| [metrics.py](../../../daedalus/wiki/metrics.py) | Strukturelle Qualitaet statt Prosa-Qualitaet: Tripel aus dem Baum ziehen, auf den k-Core reduzieren und melden, welcher Anteil der Doku-nach-Quelle-Kanten das ueberlebt. | `wiki_health`, `extract_graph`, `k_core`, `main`, `METRICS_VERSION`, `CROSS_PLANE_RELATIONS`, `MAX_BYTES`, `UNREAD_SUFFIXES` |
| [qml_index.py](../../../daedalus/wiki/qml_index.py) | Strukturelles Lesen von `.qml`/`.js`: ids, `property`, `signal`, `objectName`, Inline-Komponenten, qualifizierte Enum-Namen. Deterministische Regexe, kein Parser. | `ScanReport`, `scan`, `qml_vocabulary`, `main`, `BLOCK_COMMENT`, `LINE_COMMENT`, `OBJECT_NAME`, `INLINE_COMPONENT`, `TOO_LARGE`, `MINIFIED`, `UNREADABLE` |
| [treewalk.py](../../../daedalus/wiki/treewalk.py) | Seit G1-WIKI-01 (2026-09-05): entscheidet einmal und strukturell, was NICHT zum Baum gehoert -- venv (`pyvenv.cfg`), verschachtelter Checkout (eigenes `.git`), eingefrorenes Anwendungsbundle (`_internal/base_library.zip`) -- und liefert den auf Verzeichnisebene beschnittenen `os.walk`, den `plan`, `verify`, `metrics` und `qml_index` benutzen. Nur lesend. | `walk`, `walk_files`, `foreign_roots`, `foreign_kind`, `is_venv`, `is_nested_checkout`, `is_frozen_bundle`, `FOREIGN_KINDS`, `BUNDLE_MARKER` |

### Die fuenf Befunde von `verify`

| Befund | Bedeutung | Blockiert das Verdikt |
| --- | --- | --- |
| `unknown_symbol` | Ein Bezeichner in Backticks, den es im Baum nirgends gibt. | ja |
| `broken_link` | Ein relativer Markdown-Link, dessen Ziel nicht existiert oder ausserhalb des Baums liegt. | ja |
| `unsourced_claim` | Ein mit `> **Extern:**` markierter Block ohne URL in den ersten 600 Zeichen. | ja |
| `uncovered_module` | Ein Quellmodul, das keine Seite per relativem Link erreicht. | nein |
| `thin_concept` | Ein Backtick-Begriff, der nur auf einer einzigen Seite vorkommt. | nein |
| `missing_file_reference` | Ein Dateiname in Backticks, den es im Baum nicht gibt. | nein |

`thin_concept` ist kein Stilhinweis, sondern ein gemessenes Resultat: ein
Begriff, der genau einmal faellt, hat Grad 2 und stirbt in jedem k-Core, traegt
also nichts zur Wissensebene bei. Die Zahlen dazu stehen im Docstring von
[metrics.py](../../../daedalus/wiki/metrics.py) (Messung 2026-08-25 an einem
Fremdprojekt, nicht an diesem Baum).

### Wikilink-Formen, die `links.py` kennt

`[[Note]]`, `[[Note#Heading]]`, `[[Note|Alias]]`, `![[Note]]` (Embed, eine
andere Relation), sowie drei typisierte Praefixe: `code:` (Kante Dokument nach
Quelldatei bzw. Symbol), `type:` (wird geparst und gezaehlt, aber hier nie
aufgeloest — das gehoert zur [Typ-Ebene](type-graph.md)) und `vault:`
(vault-uebergreifend; geparst, Aufloesung ausdruecklich zurueckgestellt).

Die Aufloesungsregel ist streng: ein Ziel ohne Treffer wird als `unresolved`
gezaehlt und nie auf einen aehnlichen Namen gebogen; ein Ziel mit mehr als
einem Treffer landet in `ambiguous` und erzeugt gar keine Kante. Ein Selbstlink
ist keine Kante.

## Trust-Grenzen / Effekte

**Zwei Tueren, beide registriert.** `plan.main` und `verify.main` sind die
einzigen Stellen im Paket, die schreiben: beide legen `<root>/runs` an und
schreiben dort ihre JSON-Datei. Das Schreibziel ist argument-kontrolliert (die
Wurzel kommt von der Kommandozeile), deshalb steht `begin_effect` in beiden
Funktionen **ueber** der Argumentbehandlung, oberhalb der `--help`-Verzweigung,
sodass keine Argumentform am Boundary vorbei zur Schreiboperation kommt.

Die zugehoerigen Registry-Zeilen in
[effect_boundary.py](../../../daedalus/spine/effect_boundary.py) heissen
`cli.wiki_plan` und `cli.wiki_verify`, tragen beide genau
`Effect.FILESYSTEM_WRITE`, den Guard-Vertrag `budget.process_guard` und
`Wiring.CENTRAL`. Kein Subprozess, kein Socket, kein Secret-Lesen ist von
diesen Tueren erreichbar. Details zur Grenze selbst stehen auf
[Spine](spine.md).

**Der Rest ist lesend.** `survey`, `build_plan`, `verify` (die Funktion, nicht
`main`), `index_symbols`, `tree_vocabulary`, `scan`, `wiki_health`,
`extract_graph` und der gesamte Vault-Leser lesen nur. `metrics.main` und
`qml_index.main` drucken nach stdout und legen keine Datei an; sie sind
deshalb keine registrierten Tueren. [__main__.py](../../../daedalus/wiki/__main__.py)
ist ebenfalls keine Effekt-Grenze, weil es keine eigenen Effekte hat: der
`health`-Unterbefehl schreibt gar nichts, `plan` und `verify` delegieren an die
Funktionen, die die Grenze selbst oeffnen.

**Der Vault-Pfadvalidator.** `vault_rel` ist fail-closed und wurde geschrieben,
bevor es einen Endpunkt gibt, der ihn braucht — genau damit der Endpunkt nicht
ohne ihn geschrieben werden kann. Abgelehnt werden: absolute Pfade und
Laufwerksbuchstaben, jedes `..`-Segment **vor** der Aufloesung, ein aufgeloester
Pfad ausserhalb des Vaults, Symlinks irgendwo in der Kette, `:` in einem
Segment (NTFS Alternate Data Streams), reservierte Windows-Geraetenamen sowie
abschliessende Punkte und Leerzeichen, und jede Endung ausser `.md`. Jede
Ablehnung liefert `None` plus einen Grund; es gibt keinen Pfad, der eine
verdaechtige Schreibweise in etwas Plausibles aufloest.

**Der geprueft Baum darf nicht fuer sich selbst buergen.** `exclusions`
liefert die Baeume, die keine Evidenz liefern duerfen: das Wiki selbst,
`<root>/runs` (dort liegt der eigene Bericht des Pruefers) und — strukturell
erkannt, nicht per Namensliste — jedes Git-Checkout unterhalb der Wurzel. Ohne
den ersten Ausschluss traegt sich ein von einer Seite erfundener Name selbst
ins Vokabular ein, das ihn beurteilen soll; ohne den zweiten zitiert der
Bericht des letzten Laufs jeden Befund als Evidenz zurueck. Derselbe Ausschluss
gilt in allen drei Evidenzquellen (`index_symbols`, `tree_vocabulary`,
Config-Keys), weil eine Regel, die in einer von drei Quellen gilt, keine Regel
ist.

**Kein Schreibpfad fuer Seiten.** Die effektvolle Haelfte der Wiki-Erzeugung —
Auftraege ausfaechern, Modelle rufen lassen, Seiten schreiben — liegt
absichtlich nicht in diesem Paket. Der Paket- und der `__main__`-Docstring
nennen den Grund: ein `generate`-Unterbefehl wuerde einen Modellaufruf und eine
Schreibwurzel hinter ein Doku-Kommando legen, also genau den Bypass, gegen den
die Effekt-Grenze existiert.

**Exit-Codes von `__main__`.** `0` = Erfolg bzw. Verdikt PASS, `1` = Verdikt
FAIL oder kein Wiki am angegebenen Pfad, `2` = Nutzungsfehler oder Wurzel ist
kein Verzeichnis, `3` = `health` konnte nicht messen. Die `3` ist bewusst von
der `0` getrennt: "ich konnte nicht messen" und "ich habe gemessen und nichts
gefunden" sind verschiedene Aussagen.

## Tests

Gemessen 2026-09-05 (`grep -c "def test_"`):

| Datei | Deckt ab | Tests |
| --- | --- | --- |
| [test_wiki.py](../../../tests/test_wiki.py) | `vault` und `links`: der Pfadvalidator, die Frontmatter-Untermenge, die Regel "nie raten" bei nicht aufloesbaren und mehrdeutigen Links. | 38 |
| [test_wiki_plan.py](../../../tests/test_wiki_plan.py) | `plan`, mit Seitenblick auf `verify`: die Partitionsregel, virtuelle Umgebungen, verschachtelte Checkouts und eingefrorene Bundles, die als Quelle vermessen wurden -- jeweils mit Positivkontrolle (Marker entfernt, Kopie taucht wieder auf). | 20 |
| [test_wiki_verify.py](../../../tests/test_wiki_verify.py) | `verify`: dass der Rueckgang von tausenden Befunden auf null nicht daher kommt, dass das Instrument aufgehoert hat hinzusehen; seit G1-WIKI-01 auch, dass weder ein Bundle noch ein Artefaktbaum (`build`, `dist`, ...) Evidenz liefert oder Seiten verlangt. | 20 |
| [test_wiki_metrics.py](../../../tests/test_wiki_metrics.py) | `metrics`: Berichtsform auf einem kleinen Baum, fehlende Wurzel ist kein leerer Baum, verschachtelter Checkout und Bundle werden ausgelassen **und** in `could_not_measure` benannt. | 4 |
| [test_wiki_cli.py](../../../tests/test_wiki_cli.py) | `__main__`: Exit 2 bei Usage-Fehler und Nicht-Verzeichnis, Argv-Vertrag zu `plan.main`/`verify.main` (Delegaten durch Rekorder ersetzt, keine Effektgrenze ueberschritten), `health` druckt JSON mit dem dokumentierten `k`, Exit 3 statt 0 ohne messbares `wiki_health`. | 6 |
| [test_registry_new_doors.py](../../../tests/test_registry_new_doors.py) | Leitet die Effekte von `cli.wiki_plan` und `cli.wiki_verify` in beide Richtungen neu ab: sowohl Unterdeklaration als auch aufgemaltes Label fallen durch. | -- |

Bis zum Vormittag des 2026-09-05 hatten [metrics.py](../../../daedalus/wiki/metrics.py),
[qml_index.py](../../../daedalus/wiki/qml_index.py) und
[__main__.py](../../../daedalus/wiki/__main__.py) keine eigenen Tests (gemessen:
kein Treffer fuer `wiki_health`, `qml_index`, `daedalus.wiki.__main__` unter
`tests/`). G1-WIKI-01 hat `test_wiki_metrics.py` und `test_wiki_cli.py`
nachgezogen; der Arity-Fall aus dem `__main__`-Docstring (ein Pfad landete im
Parameter `k`) ist jetzt gepinnt. `qml_index` wird weiter nur ueber
`verify`-Tests mitgefuehrt.

## Verwandt

- [Knowledge-Layer](knowledge-layer.md) und [Typ-Ebene](type-graph.md) — die
  Ebenen, aus denen die `code:`- und `type:`-Kanten kommen.
- [Spine](spine.md) — wo `begin_effect` und die Registry wohnen.
- [Daedalus-Paketwurzel](daedalus-package-root.md) — die Nachbarschaft, aus der
  `budget` und `spine` importiert werden.
- [Twin](twin.md) und [Twin-Extraktoren](twin-extractors.md) — die
  Vier-Ebenen-Sicht, deren Wissensebene dieses Paket bedient.
- [Gates](gates.md) — der Report, der die beiden Wiki-Tueren zuerst als
  `entrypoint.unregistered` gemeldet hat.
- [Lanes](lanes.md) — dort liegen die Namens-Checks, die einen erfundenen
  Modulpfad wie `daedalus.wiki_vault` abfangen.
- [Forest v2 s05 — Revisionsatomare Snapshots](../experiments/forest-v2-s05-snapshot.md)
  — dieselbe Denkweise (Evidenz statt Behauptung), eine Ebene tiefer.
- [Tool-Vetting](../tool-vetting.md) und [Wiki-Index](../index.md).

## Ungeklaert

- **Ungeklaert:** ob `metrics.py` heute von irgendetwas ausser dem
  `health`-Unterbefehl aufgerufen wird. Ein Produktionsaufrufer war
  2026-09-05 nicht auffindbar.
- **Der eigene Docstring von `qml_index` sagt, dass das Modul heute nichts
  einbringt:** jeder Name, den der strukturelle Leser liefert, ist auch ein
  Token des Wort-Scrapes in `tree_vocabulary`, gemessen 0 zusaetzliche Namen
  (2026-08-25, Fremdprojekt). Es wird als "gemessen und wartend" behalten, fuer
  den Fall, dass der Scrape spaeter verengt wird. **Ungeklaert:** ob dieser
  Fall in einem Work Packet steht.
- **Geklaert durch G1-WIKI-01:** `verify.SKIP_DIRS` fuehrt jetzt dieselben
  Artefaktnamen wie `plan` und `metrics` (`runs`, `artifacts*`, `scratchpad`,
  `build`, `dist`, `htmlcov`, `.tox`, `spikes`). Gemessen 2026-09-05: von 4661
  `source_modules` lagen 3084 unter dem gitignorierten `build/` (sechs
  Wheel- und Smoke-Kopien des Pakets). Einzige gewollte Differenz: `docs`
  bleibt fuer `verify` drin, weil Formatspezifikationen die einzige Heimat
  echter Feldnamen sind. **Ungeklaert bleibt:** die getrennten
  Groessengrenzen (400 KB in `metrics` und `index_symbols`, 2 MB im
  Wort-Scrape von `tree_vocabulary`, 200 KB fuer Config-Keys) und ob
  Testmodule (777 im Baum) als `uncovered_module` zaehlen sollen.
- **Ungeklaert:** `discover_vaults` kennt einen globalen Vault als
  Opt-in-Argument, aber im Baum war 2026-09-05 kein Aufrufer sichtbar, der ihn
  setzt. Der Docstring nennt die offenen Fragen (Index, Schreibbegrenzung,
  Egress-Lane) als Grund fuer das Opt-in.
- **Ungeklaert:** die Zahlen in den Docstrings von `metrics`, `plan`, `verify`
  und `qml_index` stammen saemtlich vom 2026-08-25 und aus einem anderen
  Repository (`project_tct`). Sie sind hier zitiert, nicht nachgemessen.

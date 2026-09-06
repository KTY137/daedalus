---
title: Forest v2 s02 — Type-Plane
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s02_types
---
# Forest v2 s02 — Type-Plane

Slice s02 baut die **Type-Ebene** des Project Twin (Masterplan Abschnitt 5) aus
dem AST heraus und misst dann, ob das Ergebnis etwas taugt. "Type-Ebene" heisst
hier: deklarierte und direkt ableitbare Typen — Annotationen, Signaturen,
Dataclass-/TypedDict-/NamedTuple-Felder, Klassenbasen, Typaliase — als typisierte
Knoten und typisierte Kanten.

Der Slice sitzt auf der Ariadne-/Messseite, nicht im Kernel: er ist read-only,
nur Stdlib, importiert keinen Repository-Code, schreibt nichts, oeffnet kein
Netz, startet keinen Subprozess und gibt genau ein JSON-Objekt auf stdout aus.
Jede Kante hier ist **Deklarationsevidenz**, keine latente Hypothese: sie
existiert, weil eine Quell-Annotation es sagt. Das Verifier-Problem aus
Masterplan Abschnitt 6 stellt sich damit nicht. Was sich sehr wohl stellt: ob
der Name in der Annotation einer echten Definition zugeordnet werden kann — und
genau das messen die drei Fortsetzungen dieses Slices.

Gemessen 2026-09-05: 7 `.py`-Dateien mit 2928 Zeilen, davon 4
Implementierungsdateien mit 1802 Zeilen und 3 Testdateien mit 1126 Zeilen.
Dazu der Fixture-Baum `corpus_alias/xpkg/` (15 Module plus ein
`deep/`-Unterpaket mit drei weiteren) und die handgerechnete
`ground_truth.json`.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`type_plane.py`](../../../experiments/forest_v2/s02_types/type_plane.py) | Der Extraktor: AST → Typknoten, Symbolknoten, Cross-Plane- und Intra-Plane-Kanten, plus die Deckungsmetriken. | `SCHEMA`, `Graph`, `Resolver`, `TypeExprWalker`, `FileExtractor`, `build_type_plane`, `summary`, `main`, `iter_py_files`, `module_name_of`, `top_level_symbols`, `import_bindings`, `builtins_only_bucket`, `dotted_of`, `corpus_pin`, `git_revision`, `TOTAL_KEYS`, `BUILTIN_NAMES`, `TYPING_ROOTS`, `STDLIB_ROOTS`, `RESOLVED_BUCKETS`, `UNRESOLVED_BUCKETS`, `REPO_BUCKETS`, `VALUE_ARG_HEADS`, `FIRST_ARG_ONLY_HEADS`, `FIELD_BASE_HINTS`, `DEFAULT_PACKAGES` |
| [`resolver_accuracy.py`](../../../experiments/forest_v2/s02_types/resolver_accuracy.py) | Fortsetzung 2: laeuft **dieselbe** Maschinerie ueber einen handbeantworteten Fixture-Korpus und meldet Treffer, Ueberdehnungen und Auslassungen. | `grade`, `summary`, `resolve_sites`, `load_truth`, `verdict_for`, `main`, `CORPUS_DIR`, `GROUND_TRUTH`, `CORPUS_PACKAGES` |
| [`probe_external_corpora.py`](../../../experiments/forest_v2/s02_types/probe_external_corpora.py) | Fortsetzung 3: dieselben Metriken auf Korpora, die **nicht** dieses Repository sind. | `CORPORA`, `measure`, `run`, `table`, `main`, `stdlib_packages`, `HERE`, `REPO_ROOT`, `STDLIB`, `SITE`, `USER_SITE` |
| [`mutation_probe.py`](../../../experiments/forest_v2/s02_types/mutation_probe.py) | Beschaedigt den Resolver auf benannte Weisen und meldet, welche Wachen anschlagen. | `GUARDS`, `FAST_GUARDS`, `MUTANTS`, `probe`, `run_guards`, `main`, `CORPUS` |

## Was gebaut wird

- **Typknoten** `type:<bucket>:<kanonischer Name>` in Ebene `type`.
- **Symbolknoten** `sym:<modul>.<qualname>` (und `...#<param>`) in Ebene
  `code`. Sie sind Anker, keine zweite Code-Ebene: der Slice leitet die
  Code-Ebene nicht neu her, er benennt nur die Endpunkte, die seine Kanten
  brauchen.
- **Cross-Plane-Kanten** (code → type): `param_type`, `return_type`,
  `field_type`, `var_type`, `subtype_of`.
- **Intra-Plane-Kanten** (type → type): `type_arg`, `alias_of`.

`TypeExprWalker` behandelt zwei Sonderformen explizit: `Literal[...]`-Argumente
sind Werte und keine Typen (`VALUE_ARG_HEADS`), und `Annotated[T, ...]` bindet
nur sein erstes Argument als Typ (`FIRST_ARG_ONLY_HEADS`).

## Die Aufloesungs-Buckets

Ein Typname landet in genau einem Bucket:

| Bucket | Bedeutung |
| --- | --- |
| `builtin` | ein Name in `builtins` (`int`, `None`, ...) |
| `typing` | `typing`/`typing_extensions` zugeordnet |
| `repo` | **verifiziert**: die Symboltabelle des besitzenden Repo-Moduls hat ihn |
| `repo_unverified` | einem Repo-Modul zugeordnet, Symbol dort nicht gefunden |
| `stdlib` | einer Stdlib-Wurzel zugeordnet (`sys.stdlib_module_names`) |
| `third_party` | einer anderen importierbaren Wurzel zugeordnet |
| `unresolved` | keine Bindung, keine lokale Definition, kein Builtin |
| `structural` | ueberhaupt kein Name (unparsbare Forward-Ref, seltsame Form) |

Die Ehrlichkeitsklausel steht im Docstring: `stdlib`, `third_party` und
`repo_unverified` sind **Namenszuordnungen, keine Existenzbeweise**. Nur
`repo` ist gegen eine Symboltabelle verifiziert, die der Probe selbst gebaut
hat. `special` deckt vollstaendig bestimmte Nicht-Namen-Formen ab (`...` in
`Callable[..., T]`) und zaehlt als aufgeloest.

## Metriken, und was jede falsifizieren kann

Der Docstring von `type_plane.py` ist ungewoehnlich streng mit den eigenen
Zahlen und benennt die urspruengliche Kopfzahl als untauglich:

- **`sig_resolved`** (die urspruengliche Kopfzahl) verlangt, dass jeder
  Parameter (implizite `self`/`cls` ausgenommen) und der Rueckgabewert
  annotiert **und** jeder referenzierte Typname zuordenbar ist. Sie ist
  **per Konstruktion an die Annotationsdeckung gekoppelt** — eine fehlende
  Annotation setzt beide Flags auf falsch — sodass immer
  `sig_resolved <= sig_annotated` gilt und die Rate im Wesentlichen misst, wie
  gut das Korpus annotiert ist. Sie bleibt aus Kontinuitaetsgruenden erhalten
  und ist **nicht** die Metrik, auf der eine Aussage ueber Aufloesbarkeit
  ruhen darf.
- **`annotation_only`** (`sig_annotated`) ist die korrekte Kontrolle: "ist die
  Signatur syntaktisch vollstaendig?". Der marginale Beitrag der gesamten
  Import-Bindungs- und Symboltabellen-Maschinerie ist die Differenz
  `sig_annotated - sig_resolved` und nichts Groesseres — die Maschinerie kann
  von der Kontrolle immer nur **abziehen**.
- Der **`builtins_only`-Resolver** ist als **zurueckgezogene** Negativevidenz
  erhalten, nicht als Kontrolle: er kann per Konstruktion keine einzige
  Import-Anweisung lesen, also misst die Differenz zu ihm "verwendet dieses
  Korpus nicht-eingebaute Typen", was niemand bezweifelte.
- Zwei **entkoppelte** Metriken tragen die eigentliche Frage und duerfen als
  Falsifikator feuern: `type_name_resolution` (aufgeloeste / alle
  Typnamen-Vorkommen) und `sig_present_annotations_resolve` (unter Funktionen
  mit mindestens einer Annotation: der Anteil, dessen **vorhandene**
  Annotationen alle zuordnen, ohne Vollstaendigkeitsforderung).

`TOTAL_KEYS` fixiert die 32 Zaehlerschluessel des Reports; `corpus_pin` haengt
an jeden Lauf einen Inhalts-Digest ueber `<relpfad>\0<sha256>` **jeder**
gelesenen Datei — auch der unparsbaren, denn die gehoeren zum Korpus. Zeilenenden
werden vor dem Hashen auf `\n` normalisiert, weil ein CRLF-umschreibender
Checkout sonst jeden Pin bewegen wuerde, ohne dass sich ein Zeichen Inhalt
geaendert hat.

## Fortsetzung 2: bekommt der Resolver Namen **richtig**?

Die Deckungsprobe in `type_plane.py` beantwortet "war jeder Name dieser Signatur
zuordenbar". Sie kann nicht beantworten "war die Zuordnung korrekt", weil auf
dem Kernel-Paket nichts existiert, wogegen man vergleichen koennte — die Ausgabe
des Extraktors ist dort der einzige Bericht ueber die Wahrheit.

`resolver_accuracy.py` liefert den fehlenden Vergleich: dieselbe Maschinerie
(`Resolver`, `import_bindings`, `top_level_symbols`) laeuft ueber den kleinen
Fixture-Korpus `corpus_alias/`, dessen **jede** Annotationsstelle eine
handgerechnete Antwort in `ground_truth.json` hat. Deren Schema-Feld nennt die
Methode ausdruecklich: handgerechnet, geschrieben **bevor** der Resolver ueber
den Korpus lief — die fehlschlagenden Zeilen wurden **vorhergesagt**, nicht
entdeckt.

Warum ein Fixture-Korpus und nicht das Kernel-Paket: das Kernel ist stark
annotiert, nutzt fast keine Re-Export-Ketten und hat keine Wildcard-Importe.
Die beiden Fehlermodi, auf die es ankommt — mehrstufiger Re-Export und
Scope-Shadowing — kommen dort nicht in messbarer Menge vor, und ein Korpus, in
dem der Resolver nicht scheitern **kann**, ist kein Beleg dafuer, dass er
funktioniert.

### Der Fixture-Korpus `corpus_alias/xpkg/`

Jedes Modul ist **Fixture-Daten**: nie importiert, nie ausgefuehrt, nur
geparst. Jedes isoliert genau eine Bindungsform.

| Modul | Die Form, die es stellt |
| --- | --- |
| [`__init__.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/__init__.py) | Re-Export-Oberflaeche auf Paketebene (das `attrs`/`anyio`-Muster) |
| [`base.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/base.py) | Die Definitionen, auf die alle anderen zeigen (`Widget`, `Gadget`, `Sprocket`) |
| [`alias_import.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/alias_import.py) | Aliasierte Importe, ein Hop — beide sollten aufloesen |
| [`aliased_module.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/aliased_module.py) | Modul unter Alias gebunden, Attributzugriff darueber |
| [`module_attr.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/module_attr.py) | Voll qualifizierter Modul-Attributzugriff |
| [`local_def.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/local_def.py) | Definition im selben Modul — gar kein Import zu folgen |
| [`reexport_hop.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/reexport_hop.py) | Die Zwischenstufe einer Re-Export-Kette |
| [`reexport_consumer.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/reexport_consumer.py) | Zwei Hops von der Definition entfernt — der Fall, dem der Resolver nicht folgen kann |
| [`shadow.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/shadow.py) | Eine closure-lokale Klasse verdeckt einen gleichnamigen Import; eine Symboltabelle auf Modulebene kann das nicht sehen |
| [`class_scope.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/class_scope.py) | Klassen-Scope-Alias, im selben Klassenkoerper als Annotation benutzt |
| [`star_import.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/star_import.py) | Wildcard-Import: aus Deklarationen entscheidbar, aber nur mit expandierter Symboltabelle des Exporteurs |
| [`conditional.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/conditional.py) | Import hinter `TYPE_CHECKING`, als String-Forward-Ref referenziert |
| [`tryexcept.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/tryexcept.py) | Bewachter Import mit Fallback; zur Laufzeit gewinnt der erste Zweig |
| [`fallback.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/fallback.py) | Der nie genommene Zweig des obigen `try`/`except` |
| [`partial.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/partial.py) | Absichtlich gemischter Annotationsgrad plus ein echt baumelnder Name |
| [`deep/__init__.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/deep/__init__.py) | Leeres Unterpaket, damit relative Importe zwei Ebenen tief moeglich sind |
| [`deep/nested.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/deep/nested.py) | Relative Importe auf zwei Ebenen (`..base`, `.sibling`) |
| [`deep/sibling.py`](../../../experiments/forest_v2/s02_types/corpus_alias/xpkg/deep/sibling.py) | Eine Definition ein Verzeichnis tiefer (`Bracket`) |

Das Verdikt-Vokabular trennt Praezision von Recall:

| Verdikt | Bedeutung |
| --- | --- |
| `hit` | Bucket und kanonischer Name stimmen mit der Handantwort ueberein |
| `miss` | die Handantwort nennt eine echte Definition; der Resolver hat sie nicht verifiziert — Recall-Fehler |
| `overclaim` | der Resolver lieferte eine **verifizierte** `repo`-Zuordnung auf eine andere Definition als die gemeinte — Praezisionsfehler, und der gefaehrliche: nachgelagerte Konsumenten koennen ihn nicht von einem Treffer unterscheiden |
| `abstain_ok` | Handantwort ist "keine Definition existiert", Resolver sagte `unresolved` |
| `abstain_bad` | Handantwort ist "keine Definition existiert", Resolver ordnete trotzdem etwas zu |

## Fortsetzung 3: andere Korpora

Die urspruengliche Kopfzahl wurde auf **einem** Korpus gemessen, und der
marginale Beitrag der Maschinerie ueber die Annotation-Only-Kontrolle lag dort
laut Docstring bei 0,119 Prozentpunkten. Diese Zahl sagt etwas ueber
`daedalus`, nicht ueber Type-Plane-Konstruktion. Ob die Maschinerie etwas
einbringt, ist eine Eigenschaft des Korpus — also muss sie auf Korpora mit
anderer Annotationshaltung gemessen werden.

`CORPORA` deklariert sechs Korpora, und **jedes deklarierte wird berichtet,
anwesend oder abwesend**; nichts faellt weg, nachdem seine Zahlen gesehen
wurden: `kernel` (dieses Repository), `fixture_alias` (der handbeantwortete
Korpus aus Fortsetzung 2), `stdlib` (alle reinen Python-Pakete dieses
Interpreters), `third_party_typed` (`fastapi`, `anyio` — `py.typed`,
annotationsreich), `third_party_reexport` (`attr`/`attrs`, das kanonische
Re-Export-Paar) und `third_party_untyped` (`bs4`, `click` — kein `py.typed`,
weitgehend unannotiert). Die Auswahl nach **Typisierungshaltung** wurde
erklaertermassen getroffen, **bevor** eines der Korpora gemessen wurde.

Auszulesen sind laut Docstring vier Groessen: `annotation_only_pct` (die
Kontrolle), `marginal_pp` (was die Maschinerie darueber hinaus bringt —
subtraktiv per Konstruktion, und das ist zugleich ihre Obergrenze),
`type_name_resolution_pct` (von den Typnamen, die geschrieben **sind**: wie
viele ordnen ueberhaupt zu) und `verified_share_of_internal_pct` (von den dem
Korpus selbst zugeordneten Namen: wie viele wurden gegen eine Symboltabelle
verifiziert). Die letzte ist die, die sich zwischen Korpora bewegt — und die,
bei der `corpus_alias` zeigt, dass sie optimistisch ist.

Jedes Korpus traegt einen Inhalts-Pin; Drittanbieter-Korpora sind, was dieser
Interpreter installiert hat, und der Pin — nicht eine Versionsnummer — macht
einen Wiederholungslauf vergleichbar. **Ablaufdatum: 2026-09-15** (wie der
gesamte Slice); vor Wiederverwendung neu messen.

## Die Mutationssonde

`mutation_probe.py` stellt die Frage, ohne die eine Metrik keine Evidenz ist:
**merkt ueberhaupt etwas, wenn der Resolver luegt?** Der Slice restatet seine
berichteten Zahlen als ausfuehrbare Praedikate (`GUARDS`) — dieselben
Funktionen, auf die auch die Testsuite assertiert, damit es **eine** Definition
von "die Zahlen gelten noch" gibt statt zweier, die auseinanderdriften koennen.
Die Wachen heissen u. a. `accuracy_headline`, `failure_classes`,
`no_silent_overclaim`, `corpus_coverage_rates`,
`guard_marginal_is_bounded_by_the_control`, `falsifier_can_fire`,
`retracted_control_stays_weak` und `retracted_control_composition`
(letztere ist nicht in `FAST_GUARDS`).

`MUTANTS` beschaedigt den Resolver auf sechs benannte Weisen — Bindungen
ignorieren `as`-Namen, die Symboltabelle laesst Klassen fallen, die relative
Import-Basis ist um eins daneben, der Resolver behauptet alles, die
Zaehlung meldet alles als aufgeloest, die Builtins-Kontrolle akzeptiert alles.
Mutationen wirken auf In-Memory-Modulattribute und werden in einem `finally`
zurueckgenommen; auf der Platte wird nichts angefasst. Ein Mutant, den nichts
bemerkt, ist eine Metrik, die nicht misst, was ihr Name sagt.

## Trust-Grenzen / Effekte

Der Slice hat **keine**. Der eingefrorene Rahmen — read-only, nur Stdlib, keine
Importe des analysierten Codes, keine Schreibvorgaenge, kein Netz, kein
Subprozess, ein JSON-Objekt auf stdout — gilt fuer alle vier
Implementierungsdateien und ist in ihren Docstrings jeweils wiederholt.
`mutation_probe.py` haelt ihn zusaetzlich fuer den In-Process-Fall aufrecht.
Kein Modul dieses Verzeichnisses ist in
[`effect_boundary.py`](../../../daedalus/spine/effect_boundary.py) registriert,
und es muss auch keins sein: es gibt keinen Schreiber. Nichts unter
`daedalus/` importiert diesen Slice.

Einzige Einschraenkung, die man kennen muss: `probe_external_corpora.py` liest
die installierten Site-Packages dieses Interpreters. Die Ergebnisse sind damit
maschinenabhaengig, weshalb die Tests die externen Korpora nur auf
versionsunabhaengige Eigenschaften assertieren.

## Tests

Drei Testdateien liegen im Slice selbst (gemessen 2026-09-05: 1126 Zeilen).

| Testdatei | Deckt ab |
| --- | --- |
| [`test_type_plane.py`](../../../experiments/forest_v2/s02_types/test_type_plane.py) | Der Extraktor, gegen jeweils frisch gebaute Wegwerf-Quellbaeume mit handgerechneter Erwartung — nicht gegen die eigene Ausgabe auf dem Repository |
| [`test_resolver_accuracy.py`](../../../experiments/forest_v2/s02_types/test_resolver_accuracy.py) | Bewertung und Mutationssonde; jede assertierte Zahl wurde vor dem Resolverlauf von Hand aus `corpus_alias/` gerechnet, der Korpus ist per Inhalts-Digest gepinnt |
| [`test_external_corpora.py`](../../../experiments/forest_v2/s02_types/test_external_corpora.py) | Die Cross-Korpus-Sonde; trennt bewusst zwei Assertionsarten: die beiden repo-internen Korpora exakt gepinnt, die externen nur auf installationsunabhaengige Eigenschaften |

Ausserhalb des Slices deckt nichts unter `tests/` dieses Verzeichnis ab
(gemessen 2026-09-05).

## Verwandt

- [Forest v2 (Uebersicht)](forest-v2.md)
- [Forest v2 s01 — Call-Resolution](forest-v2-s01-resolution.md) — der
  Vorgaenger unter demselben eingefrorenen Rahmen
- [Forest v2 s09 — Eval-Harness](forest-v2-s09-eval.md) — die Messseite, die
  denselben Ehrlichkeitsregeln folgt
- [Forest v2 s10 — Kill-Kriterien](forest-v2-s10-kill.md) — dort landen
  Falsifikatoren wie "eine Ebene hat keinen marginalen Beitrag"
- [Type-Graph](../architecture/type-graph.md) — die Produktionsseite derselben
  Ebene
- [Twin](../architecture/twin.md) und
  [Twin / Extraktoren](../architecture/twin-extractors.md)
- [Data-Layer](../architecture/data-layer.md),
  [Knowledge-Layer](../architecture/knowledge-layer.md),
  [Observation-Layer](../architecture/observation-layer.md) — die uebrigen
  Ebenen bzw. Lineage-Dimensionen
- [Ariadne](../architecture/ariadne.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Ob die Ergebnisse dieses Slices irgendwo als Artefakt
  abgelegt sind. Anders als s09 hat s02 kein `results/`-Verzeichnis; die
  Module geben JSON auf stdout aus, und wohin das geschrieben wurde, sagt der
  Code nicht.
- **Ungeklaert:** Die konkreten Kopfzahlen in
  `mutation_probe.guard_accuracy_headline` (verifizierte Praezision und Recall
  auf `corpus_alias`) sind im Code als Assertions fixiert. Ich habe die Sonde
  nicht ausgefuehrt und gebe sie deshalb hier nicht als gemessene Zahlen
  wieder.
- **Ungeklaert:** `probe_external_corpora.SITE` und `USER_SITE` werden beide
  auf `sysconfig.get_paths()["purelib"]` gesetzt — also auf denselben Pfad.
  Ob das Absicht (ein Alias) oder ein Rest ist, geht aus dem Code nicht
  hervor; `CORPORA` benutzt nur `USER_SITE`.
- **Abgelaufen:** Der Slice traegt ein explizites Ablaufdatum 2026-09-15. Zum
  Stand dieser Seite ist es noch nicht erreicht, aber jede Zahl daraus ist ab
  dann neu zu messen.

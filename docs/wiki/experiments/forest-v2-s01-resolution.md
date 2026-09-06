---
title: Forest v2 Slice s01 Resolution
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s01_resolution
---
# Forest v2 Slice s01 Resolution

Slice s01 ist der Code-Ebenen-Teil der Forest-v2-Vorstudie: ein
scope-bewusster Aufloeser fuer Aufrufstellen, der die Buchstabier-Regel der
Vorstudie ersetzen sollte. Vier Produktionsdateien plus eine Testdatei, 2670
Zeilen zusammen (gemessen 2026-09-05; der Arbeitsplan zaehlt die vier ohne
Tests mit 1856 Zeilen). Rahmen, vor dem Lauf eingefroren: nur
Standardbibliothek und `ast`, read-only, kein Import von Produktionscode, keine
Schreibvorgaenge, kein Netz, kein Subprozess, keine Modellaufrufe, keine
Ausgaben. Nichts unter `s01_resolution/` importiert `daedalus`, und nichts in
`daedalus` verweist darauf.

Im Kernel/Ikarus/Ariadne-Bild ist das ein isoliertes `EXPERIMENT` nach
Masterplan Abschnitt 1 und 15: es fordert einen Forschungs-Prior heraus und
darf ausdruecklich nichts promoten. Es beruehrt die Code-/AST-Ebene des
Project Twin (Abschnitt 5), siehe [Twin](../architecture/twin.md).

> **Das Kopfergebnis dieses Slices ist zurueckgezogen.** Die Retraktion vom
> 2026-08-18 steht ausfuehrlich in
> [`experiments/forest_v2/README.md`](../../../experiments/forest_v2/README.md)
> und ist unten zusammengefasst. Wer eine Zahl aus diesem Slice zitiert, muss
> vorher die Retraktion gelesen haben.

## Hypothese und Verdikt

**Hypothese (falsifizierbar).** Ersetzt man die Regel der Vorstudie -- das
letzte gepunktete Segment gegen eine flache Menge aller Funktions- *und*
Methodennamen der Datei abgleichen -- durch einen scope-bewussten Aufloeser mit
Import-Bindung samt Re-Export-Ketten, `self`/`super`/`cls`-Dispatch ueber die
Klassenhierarchie und Empfaengertypisierung aus Konstruktoren, Annotationen und
Instanzattributen, dann steigt der Anteil der Aufrufstellen, die an eine
**benannte Definition im Baum** gebunden sind, und zwar aus strukturellen
Gruenden statt durch Namenszufall.

**Verdikt 2026-08-18: die erste Teilaussage ist FALSIFIZIERT.** Gegen die
reparierte Kontrolle betraegt der Anstieg zu Hause +0,44 Prozentpunkte und auf
einem zurueckgehaltenen Korpus **-6,12 Prozentpunkte**. Die zweite Teilaussage
haelt: die randomisierte Kontrolle zerstoert die import-abgeleitete
Verifikation tatsaechlich. Was uebrig bleibt, ist eine Aussage ueber
**Praezision**, nicht ueber Anteil.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`s01_index.py`](../../../experiments/forest_v2/s01_resolution/s01_index.py) | Read-only-Projektindex der Code-Ebene: Modulsymbole, Re-Export-Ketten, Klassenhierarchie, Instanzattribut-Typen. Jedes Ergebnis ist ein `Target` mit `status` `repo` (Datei und Zeile im Baum), `external` (ein benanntes Modul -- eine Behauptung) oder `unknown` (verweigert das Raten). Eine *Repraesentation*, nie eine Autoritaet. | `ProjectIndex`, `Target`, `ClassInfo`, `ModuleInfo`, `build_index`, `dotted_name`, `module_name_for`, `import_bindings`, `DEFAULT_PACKAGES`, `INERT_BASES` |
| [`s01_resolver.py`](../../../experiments/forest_v2/s01_resolution/s01_resolver.py) | Eine `Resolution` je `ast.Call`: verifiziert mit Datei und Zeile, extern, oder ungeloest **mit benanntem Grund**. Die Gruende sind der eigentliche Ertrag -- ein Aufloeser, der ehrlich sagt, *warum* er scheiterte, liefert Gate 2 eine Arbeitsliste statt eines Slogans. | `CallResolver`, `Resolution`, `Scope`, `Options`, `FULL`, `resolve_module`, `resolve_tree`, `VERIFIED_KINDS`, `EXTERNAL_KINDS`, `BUILTIN_NAMES` |
| [`s01_measure.py`](../../../experiments/forest_v2/s01_resolution/s01_measure.py) | Die Messgeraet-Datei. Ein JSON-Objekt auf stdout, Schema `forest-v2-s01-resolution/1`. Importiert die Vorstudien-Probe und vergleicht auf **einem** Nenner. | `measure`, `main`, `ParityError`, `DeadSwitchError`, `ABLATIONS`, `BASELINE_ARMS`, `DEFAULT_ARM`, `arm_b0`, `arm_b1`, `arm_b2`, `arm_b3`, `audit_definition`, `rotation_map`, `verified_count`, `BASELINE_BUCKETS` |
| [`s01_heldout.py`](../../../experiments/forest_v2/s01_resolution/s01_heldout.py) | Dieselben vier Arme gegen einen Korpus, an dem hier niemand justiert hat: die Standardbibliothek des laufenden Interpreters. Schema `forest-v2-s01-heldout/1`. Ergaenzt 2026-08-18, weil das Kill-Kriterium fuer zurueckgehaltene Repositories nie ausgefuehrt worden war. | `held_out`, `main`, `PACKAGES`, `EXCLUDED_PATH_PARTS`, `REPO_BUCKETS` |
| [`test_s01_resolver.py`](../../../experiments/forest_v2/s01_resolution/test_s01_resolver.py) | Die Tests des Slices. Jede Vorrichtung ist ein Wegwerfbaum unter `tmp_path`; nichts liest oder schreibt das Repository, importiert Produktionscode oder fuehrt die Vorrichtungen aus. Der Aufloeser parst nur Text. | `Tree`, `build`, `measured_root` |

## Das Messgeraet und seine Totmann-Schalter

`s01_measure` beantwortet vier Fragen mit Rohzahlen auf demselben Nenner und
weigert sich zu publizieren, wenn das Geraet defekt ist:

- **`ParityError`** -- die Basislinie wird nicht neu abgetippt. Die Probe der
  Vorstudie wird importiert und ausgefuehrt, und eine Replik pro Aufrufstelle
  muss deren Summen in allen fuenf `BASELINE_BUCKETS` exakt reproduzieren.
  Sonst fliegt die Ausnahme und **kein Byte** landet auf stdout. Bis
  2026-08-18 wurde die Paritaet zwar berechnet und ins Ergebnis geschrieben,
  aber von nichts geprueft.
- **`DeadSwitchError`** -- eine Ablation, die nichts aendert, beweist nichts.
  `ablated <= full` erfuellt auch ein Schalter, der gar nichts tut. Gefordert
  ist die staerkere Eigenschaft: jeder Schalter muss auf dem gemessenen Korpus
  sichtbar lebendig sein. Ein Null-Grenzbeitrag wird als kaputtes Instrument
  gemeldet, nicht als stiller Nuller.
- **`ABLATIONS`** entfernt jeweils genau einen Mechanismus (`no_imports`,
  `no_hierarchy`, `no_receiver_types`). Die separate randomisierte Kontrolle
  laesst alle Mechanismen an und laesst nur die Bindungen auf das *falsche*
  Modul zeigen; was darunter noch verifiziert, ist Namenszufall, nicht
  Bindungsverfolgung. Die Rotation wird auf **jede** gelernte Bindung
  angewandt, auch auf funktionslokale -- eine Kontrolle, die nur die
  Modulebenen-Tabelle umschreibt, leckt, weil Inline-Importe den wahren Wert
  nachsaeen.
- `audit_definition` prueft nach, dass jedes verifizierte Ziel tatsaechlich auf
  einem `def`/`class` in der genannten Datei und Zeile landet.

## Die Retraktion in Kurzform

Der Fehler lag in der Kontrolle, nicht im Aufloeser: die Namensmenge der
Basislinie lief `ast.ClassDef`-Knoten nur nach ihren *Methoden* ab und fuegte
den Klassennamen nie hinzu. Ein Aufruf einer im selben Modul definierten Klasse
war der Kontrolle damit **konstruktionsbedingt** nicht zuschreibbar. 3.368 der
3.567 "gewonnenen" Stellen (94,4 %) sind dieses Loch.

Die reparierte Kurve, ein Durchlauf, ein Nenner (45.005 Aufrufstellen, 318
Module, Paritaet erfuellt) [MESSUNG uebernommen aus
`experiments/forest_v2/README.md`, Basis `16fab41e`]:

| Arm | Namensmenge | repo-beansprucht | Anteil | s01-Zugewinn |
| --- | --- | ---: | ---: | ---: |
| B0 (die gewaehlte Kontrolle) | Modulfunktionen + Methoden | 9.557 | 21,24 % | +7,92 pp |
| **B1 (reparierte Kontrolle, heute Standard)** | B0 + Klassennamen desselben Moduls | 12.925 | 28,72 % | **+0,44 pp** |
| B2 | jedes `def`/`class` im Modul | 13.311 | 29,58 % | -0,42 pp |
| B3 | B2 + Zuweisungsziele auf Modulebene | 13.324 | 29,61 % | -0,45 pp |
| s01-Aufloeser | -- | 13.124 | 29,16 % | -- |

Die Verteidigung "mehr Abdeckung, erkauft mit Falschpositiven" wurde getestet
und fiel durch: von den 3.368 Stellen, die B1 gegenueber B0 gewinnt, verifiziert
s01 **alle 3.368** selbst, und B1s Widerspruchspopulation ist mit 109 Stellen
identisch zu B0. B1 dominiert B0 strikt.

Auf dem zurueckgehaltenen Korpus (CPython 3.10.11, 21 Pakete, 201 Module,
18.683 Aufrufstellen) kippt das Vorzeichen sogar gegen B0: B0 32,58 %, B1
35,85 %, s01 29,73 % -- also -2,85 bzw. -6,12 Prozentpunkte.

**Die Metrik ist monoton im Raten.** "Anteil der Aufrufstellen, die an eine
benannte Definition im Baum gebunden sind" steigt, sobald eine Regel mehr
raet. Ein Zugewinn darin ist nur zwischen Armen gleicher oder besserer
Praezision ein Beleg. Auf der Standardbibliothek liegt B0s Widerspruchsrate bei
6,79 % gegen 1,56 % zu Hause -- die beiden Arme sind dort gar nicht
praezisions-vergleichbar, und genau deshalb haette der Anteil nie die Kopfzahl
sein duerfen.

**Was die Evidenz stuetzt:** s01 liefert eine *auditierte Zielidentitaet* --
Modul, Symbol, Datei und Zeile, 13.124 von 13.124 auf einem echten
`def`/`class` --, wo die Basislinie nur einen Namenstreffer ohne Ziel liefert.
Es verweigert dort, wo die Basislinie raet, und erreicht immer noch 616 Stellen,
die die reparierte Kontrolle verfehlt.

**Kill-Kriterium.** Das Kriterium *"benefits disappear on held-out
repositories"* **feuert**. Der Track "Attributionsanteil auf der Code-Ebene"
ist gestoppt, nicht getunt; ein Amendment, das den Prior "Aufloesung erhoeht
Attribution" ersetzt, ist geschuldet. Der Slice selbst schlaegt dieses
Amendment nicht vor und fasst den Plan nicht an -- er protokolliert den Treffer.

**Folge fuer Schwester-Slices:** jeder Slice, der einen Zugewinn gegen den
21,24-%-Arm zitiert, erbt den Dominierte-Kontrolle-Defekt und muss gegen den
28,72-%-Arm neu formuliert werden. Vergleichsarm ist heute `DEFAULT_ARM`, also
B1.

## Trust-Grenzen / Effekte

Keine. Kein `begin_effect`, kein Writer, kein Subprozess, kein Netz. Beide
ausfuehrbaren Dateien (`s01_measure.py`, `s01_heldout.py`) drucken genau ein
JSON-Objekt auf stdout und schreiben keine Datei. Der einzige aussergewoehnliche
Import ist `probe_cross_module_resolution` aus dem Elternverzeichnis, den
`sys.path` in beiden Skripten explizit sichtbar macht. Der Aufloeser parst Text
und fuehrt nie aus, was er parst.

## Tests

- [`experiments/forest_v2/s01_resolution/test_s01_resolver.py`](../../../experiments/forest_v2/s01_resolution/test_s01_resolver.py) -- die einzige Testdatei; sie liegt im Slice-Verzeichnis, nicht unter `tests/`. Aufruf: `python -m pytest experiments/forest_v2/s01_resolution/test_s01_resolver.py -q`.
- Unter `tests/` deckt **keine** Datei diesen Slice ab (gemessen 2026-09-05 per Suche nach `s01_` in `tests/`). Das ist Absicht des eingefrorenen Rahmens: der Slice haengt nicht an der Produktionssuite.
- Die Mutationsquittungen des Slices (Guard abschalten, benannten Test rot werden sehen, Guard zurueckstellen) stehen in
  [`experiments/forest_v2/README.md`](../../../experiments/forest_v2/README.md);
  die Suite ging dabei von 29 auf 41 bestandene Tests.

## Verwandt

- [Forest v2](forest-v2.md) -- der Dach-Slice-Plan und die vollstaendige Retraktion
- [Forest v2 Slice s02 (Types)](forest-v2-s02-types.md) -- die Typ-Ebene desselben Twin
- [Forest v2 Slice s06 (Cards)](forest-v2-s06-cards.md) -- konsumiert s01 als echten Upstream
- [Forest v2 Slice s09 (Eval)](forest-v2-s09-eval.md) und [Forest v2 Slice s07 (BM25)](forest-v2-s07-bm25.md) -- die Vergleichsbasislinien
- [Twin](../architecture/twin.md) und [Twin-Extractors](../architecture/twin-extractors.md) -- die Produktionsseite der Code-Ebene
- [Type-Graph](../architecture/type-graph.md), [Data layer](../architecture/data-layer.md), [Knowledge layer](../architecture/knowledge-layer.md) -- die uebrigen Ebenen
- [Structcore](../architecture/structcore.md) -- der produktive Slicer, den s01 nicht ersetzt
- [Eval](../architecture/eval.md) -- die Evidenzgrenze, an der ein solcher Anspruch gemessen wuerde
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** ob die im README genannte Expiry **2026-09-15** noch gilt und
  ob vor einer Wiederverwendung neu gemessen wurde. Die Zahlen stammen aus
  Laeufen vom 2026-08-18 gegen die Basen `d849c2a9` und `16fab41e`; dieser
  Baum steht heute auf einem anderen Commit.
- **Ungeklaert:** ob das geschuldete Amendment inzwischen eingereicht wurde.
  Die Amendment-Kette ist nicht Teil dieses Verzeichnisses.
- **Abweichung Code gegen Doku:** die Docstrings von `s01_heldout.py`
  (Zeilen 15-19) und `s01_measure.py` verweisen auf ein `README.md` "hier",
  aber `experiments/forest_v2/s01_resolution/README.md` existiert nicht
  (gemessen 2026-09-05); gemeint ist
  `experiments/forest_v2/README.md`, Abschnitt "Slice s01".
- **Abweichung Code gegen Doku:** derselbe Docstring zitiert das Kill-Kriterium
  als "section 14 in the revision checked out on this branch, section 13 in
  revision 1"; der Masterplan steht heute auf Revision 12, wo die Kill-Kriterien
  in Abschnitt 14 stehen. Die Anweisung des Slices, das Kriterium beim Namen
  statt bei der Nummer zu zitieren, ist damit weiter richtig.

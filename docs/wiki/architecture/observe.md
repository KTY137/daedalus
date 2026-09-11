---
title: Observe
type: module
status: living
updated: 2026-09-05
covers: daedalus/observe
---
# Observe

`daedalus/observe` ist die Verhaltensachse des Baums: was ein Objekt zur Laufzeit
*war*, nicht was der Quelltext ueber es deklariert. Das Paket liegt bewusst
ausserhalb von [Structcore](structcore.md) — ein lebendes Objekt zu bekommen
heisst, dass das Programm gelaufen ist, und der statische Pass laeuft per
Konstruktion ohne Ausfuehrung. Im Plan-Bild ist das eine Beobachtungs-Linie
(Plan §5: Beobachtung, Provenienz, Evidenz und Zeit sind orthogonale
Lineage-Dimensionen, keine fuenfte Ebene). Jede erzeugte Kante traegt
`provenance="observed"`; sie ist nie Teil eines Index-Builds und laeuft nur auf
Baeumen, die der Betreiber besitzt.

Gemessen 2026-09-05: 2 `.py`-Dateien, 407 Zeilen (`__init__.py` 12,
`shape.py` 395). Das Paket hat keine Abhaengigkeit ausserhalb der Standardbibliothek;
numpy, pandas, h5py und uproot werden ausschliesslich per Attribut abgetastet,
nie importiert.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/observe/__init__.py) | Re-Export der Shape-Namen und die Begruendung, warum das Paket nicht in `structcore` liegt. Kein eigener Code. | `describe`, `Shape`, `ShapeConflict`, `compare_declared`, `SHAPE_VERSION` |
| [`shape.py`](../../../daedalus/observe/shape.py) | Beschreibt ein lebendes Objekt als Metadaten und vergleicht diese Beobachtung gegen deklarierte Feldnamen. | `describe`, `Shape`, `ShapeConflict`, `compare_declared`, `SHAPE_VERSION`, `MAX_NAMES`, `MAX_NAME_CHARS`, `MAX_DEPTH`, `ARRAY`, `TABLE`, `RECORD`, `SEQUENCE`, `TREE`, `SCALAR`, `TEXT`, `BINARY`, `OPAQUE` |

### Was `describe` aufzeichnet

`describe(obj, *, depth=0, redact=None) -> Shape` klassifiziert in genau eine der
neun Familien und faellt am Ende ehrlich auf `OPAQUE` zurueck statt zu raten. Die
Reihenfolge der Zweige ist im Code fest:

1. **Array-artig** (`dtype` und `shape`, aber kein `columns`) — `dtype`, `dims`,
   `nbytes`, `layout`; ein strukturierter `dtype` wird wie ein Schema behandelt und
   seine Feldnamen werden ausgegeben (`note="structured dtype"`).
2. **Tabelle** (`columns`) — Spaltennamen als Schema, unterschiedliche `dtypes`
   auf maximal sechs eindeutige Werte gekuerzt, Groesse bevorzugt aus
   `memory_usage(deep=False)`.
3. **Baum** (`keys` plus `num_entries`/`GetEntries` oder Modul `h5py`/`uproot`) —
   Schluessel und Eintragszahl mit dem Vermerk, dass die Zahl Metadatum ist und
   kein Eintrag gelesen wurde.
4. **Mapping** — nur Schluessel, plus eine Sonde auf den ersten Wert bis
   `MAX_DEPTH`.
5. **Dataclass / `__slots__`** — Feldnamen aus der Klasse.
6. **Sequenz** — Laenge plus *eine* Elementsonde, ausdruecklich vermerkt als
   moeglicherweise heterogen.
7. **Text / Binaer** — nur Laenge.
8. **Skalar**, sonst **`OPAQUE`**.

`Shape` ist ein eingefrorener Dataclass mit `to_dict()`, `signature()` (eine
stabile, seed-unabhaengige Einzeilenform zum Joinen) und `render()` (die
Debug-Konsolenzeile, fuer die der Datensatz steht).

### Die Regel: Shape, nie Value

`shape.py` liest nirgends ein Element, eine Zelle, eine Zeile oder eine
Skalar-Nutzlast. Der Docstring nennt drei Gruende: ein Wert kann Gigabytes gross
sein, ein Wert kann ein Geheimnis sein, und der Graph will den Wert ohnehin nicht.
Auch Namen sind nicht automatisch harmlos — eine Spalte `patient_id` ist bereits
eine Offenlegung. Deshalb nimmt `describe` einen `redact`-Hook, der auf jeden
Schluessel- und Spaltennamen angewandt wird, *bevor* er gespeichert wird. Das Modul
besitzt keine Policy darueber, was sensibel ist; diese Zustaendigkeit liegt laut
Docstring bei `daedalus.sensitivity` und wird absichtlich getrennt gehalten.

Die Grenzen sind hart und klein: `MAX_NAMES = 64`, `MAX_NAME_CHARS = 80`,
`MAX_DEPTH = 3`. `_names_of` behaelt bei Kuerzung die *wahre* Anzahl in `n_names`
und setzt `truncated`, damit ein Konsument nicht eine geklippte Liste fuer
vollstaendig haelt.

### Beobachtung gegen Deklaration

`compare_declared(shape, declared_names, *, subject="", declared_from="")` gibt
einen `ShapeConflict` zurueck. Zwei Asymmetrien sind bewusst:

- `missing_in_observation` ist das schwache Signal — diese Eingaben haben das Feld
  nicht angefasst. Bei `shape.truncated` wird es auf leer gesetzt und die
  Begruendung als `notes` mitgefuehrt, weil "fehlt" bei geklippter Namensliste
  nicht belegbar ist.
- `undeclared_in_observation` ist das scharfe Signal — das Objekt traegt etwas,
  das der Code nie deklariert hat. Nur dieses Feld geht in `agrees` ein.

Statt Befunde zu erfinden verweigert die Funktion den Vergleich: ohne Deklaration
oder ohne Namen in der Beobachtung kommt `comparable=False` mit `reason` zurueck.

## Trust-Grenzen / Effekte

- **Keine Effekte.** Kein Modul in diesem Verzeichnis schreibt Dateien, startet
  Prozesse oder oeffnet Netzwerkverbindungen; es gibt hier kein `begin_effect`
  und keinen Writer. Das Paket ist eine reine Funktion vom uebergebenen Objekt auf
  Metadaten.
- **Der Effekt liegt beim Aufrufer.** Ein lebendes Objekt zu haben heisst, dass
  jemand vorher Code ausgefuehrt hat. `__init__.py` und der Modul-Docstring
  formulieren die Bedingung explizit: nur auf Baeumen, die der Betreiber besitzt,
  und nie als Teil eines Index-Builds. Die Gegenregel steht in
  [Tool vetting](../tool-vetting.md) und in `daedalus/tools/vet.py`: man fuehrt
  keinen unvertrauten Code aus, um etwas ueber ihn zu entscheiden.
- **Redaction ist Aufruferpflicht.** `describe` ohne `redact` speichert
  Klarnamen. Wer die Beobachtung Richtung Modell oder aus der Maschine heraus
  schickt, muss den Hook setzen; das Paket erzwingt das nicht.
- **Eine Beobachtung ist eine Stichprobe, kein Beweis.** `(1000, 3)` ist die Form,
  die *diese* Eingabe erzeugt hat, nicht die Form, die die Funktion verlangt. Ein
  nie gesehenes Feld ist kein unmoegliches Feld. `provenance="observed"` ist
  Default auf jedem `Shape`; ein Konsument, der das als Faktum meldet, verletzt
  die Evidenzgrenze aus Plan §4 (Invariante 4).

## Tests

Gemessen 2026-09-05 per `grep -rl` nach `daedalus.observe` unter `tests/`:

- [test_observe_shape.py](../../../tests/test_observe_shape.py) — die direkte
  Abdeckung von `describe`, `Shape` und `compare_declared`.
- [test_reference_audit.py](../../../tests/test_reference_audit.py) — nennt das
  Paket nur im Rahmen des Baum-weiten Referenz-Audits, ist keine
  Verhaltensabdeckung.

Ein eigenes Testverzeichnis `tests/observe/` existiert nicht.

## Verwandt

- [Structcore](structcore.md) — der statische Gegenpol; `observe` liegt genau
  deshalb ausserhalb davon
- [Observation layer](observation-layer.md) — die Ebenenbeschreibung, in die
  beobachtete Kanten einlaufen
- [Type graph](type-graph.md) — die deklarierte Seite, gegen die
  `compare_declared` joint
- [Data layer](data-layer.md) — Spalten- und Schemanamen als Datenebene
- [Twin](twin.md), [Twin extractors](twin-extractors.md) — die statischen
  Extraktoren des Project Twin
- [Tool vetting](../tool-vetting.md) — warum Ausfuehrung eine eigene Entscheidung ist
- [Wiki-Index](../index.md)

## Ungeklaert

- **Kein Aufrufer im Baum.** Gemessen 2026-09-05 importiert ausser
  `tests/test_observe_shape.py` (und dem Referenz-Audit) kein Modul unter
  `daedalus/`, `tools/`, `scripts/` oder `experiments/` dieses Paket. Der einzige
  weitere Treffer ist ein Namensvorkommen in
  `experiments/forest_v2/s09_eval/taskset_xplane.json`, also Daten, kein Import.
  Ob `observe` bereits an eine Graph-Ingestion angeschlossen werden sollte oder
  bewusst als eigenstaendige, opt-in Lane bereitliegt, ist aus dem Code nicht
  ablesbar.
- **`daedalus.sensitivity` als Policy-Besitzer.** Der Docstring verweist darauf,
  dass die Sensitivitaets-Policy dort liegt. Welche konkrete Funktion als
  `redact`-Hook gedacht ist, wird nirgends im Paket festgelegt.
- **`_human_bytes` fuer Einheiten oberhalb B.** Der Zweig formatiert
  `f"{n / 1:.1f} {unit}"`, also den bereits durch die Schleife geteilten Wert;
  die Division durch `1` ist wirkungslos und liest sich wie ein Rest einer
  frueheren Fassung (`daedalus/observe/shape.py:103-113`). Das Ergebnis ist
  trotzdem korrekt, weil `n` in der Schleife skaliert wird — der Ausdruck ist nur
  irrefuehrend.

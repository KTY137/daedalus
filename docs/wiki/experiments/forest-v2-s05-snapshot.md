---
title: Forest v2 s05 — Revisionsatomare Snapshots
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s05_snapshot
---
# Forest v2 s05 — Revisionsatomare Snapshots

Slice s05 baut das kleinste Ding, an dem sich Invariante 6 des Masterplans
("atomare Revisionen: partielle Graphzustaende geben sich nicht als Revision
aus") mechanisch widerlegen laesst: einen Builder, der vier Ebenen-Extraktionen
an **eine** Quellrevision bindet, sie content-adressiert und beim Wiederholen
denselben Digest liefert. Im Ariadne/Gate-Bild ist das Gate-2-Vorarbeit — kein
Produktionspfad. Der Rahmen des Slices ist im Modul-Docstring eingefroren:
reine Stdlib, read-only ueber den Quellbaum, keine Repository-Importe, kein
Netz, kein Subprozess, keine Schreibvorgaenge ausserhalb eines vom Aufrufer
gelieferten Puffers. Nichts unter `daedalus/` darf diesen Slice importieren
(nachgeprueft 2026-09-05: kein Import von `forest_v2` in `daedalus/`).

Der Slice ist der Ort, an dem eine fruehere Version dieses Projekts **widerlegt**
wurde und das dokumentiert stehen blieb. Vertrag `/1` band die vier Ebenen ueber
**String-Gleichheit** des Feldes `revision`. Ein Arbeitsbaum, der zwischen zwei
Extraktionen mutiert wurde, digestete damit als eine "atomare" Revision — fuer
einen Baumzustand, den es in keinem Augenblick gab. Vertrag `/2` ersetzt die
Behauptung durch Evidenz in zwei Schichten.

Gemessen 2026-09-05: 3 Implementierungsdateien mit 1676 Zeilen, dazu
[test_snapshot.py](../../../experiments/forest_v2/s05_snapshot/test_snapshot.py)
mit 697 Zeilen und 48 Testfunktionen (drei davon parametrisiert; die
README-Zeile nennt 63 eingesammelte Faelle).

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [snapshot.py](../../../experiments/forest_v2/s05_snapshot/snapshot.py) | Der Vertrag und der Builder: normalisieren, verweigern, digestieren. Kennt keine Dateien und keinen Baum — er bekommt vier Dokumente und eine Scope-Klammer und entscheidet. | `ContractError`, `build_snapshot`, `normalize_plane_document`, `normalize_scope`, `plane_digest`, `scope_digest`, `snapshot_digest`, `canonical_bytes`, `digest_bytes`, `digest_object`, `load_plane_documents`, `main`, `CONTRACT`, `SNAPSHOT_SCHEMA`, `SCOPE_SCHEMA`, `PLANE_DIGEST_DOMAIN`, `SNAPSHOT_DIGEST_DOMAIN`, `PLANES` |
| [reference_planes.py](../../../experiments/forest_v2/s05_snapshot/reference_planes.py) | Die billigsten Extraktoren, die den Vertrag erfuellen — Platzhalter fuer s01 bis s04, damit der Builder gegen den echten Baum gemessen werden kann statt gegen Fixtures. Enthaelt ausserdem den einzigen Einstieg, der die Reihenfolge Scan/Extraktion/Scan richtig macht. | `extract_code`, `extract_type`, `extract_data`, `extract_knowledge`, `extract_all`, `build_atomic_snapshot`, `scan_scope`, `read_source_text`, `text_digest`, `read_git_revision`, `EXTRACTORS`, `PLANE_ORDER`, `CODE_ROOTS`, `DATA_ROOTS`, `KNOWLEDGE_ROOTS`, `SCOPE_ROOTS`, `SCOPE_SUFFIXES`, `WITNESS_DOMAIN` |
| [probe_replay_identity.py](../../../experiments/forest_v2/s05_snapshot/probe_replay_identity.py) | Die Messung: zweimal bauen, Unabhaengigkeit pruefen, jeweils genau ein Feld mutieren, Strukturloeschungen getrennt zaehlen, die Verweigerungsmatrix durchspielen. Ein JSON-Objekt auf stdout, Zeiten pro Phase. | `probe`, `main`, `Skip`, `FIELD_MUTATIONS`, `STRUCTURE_MUTATIONS`, `REFUSAL_CASES`, `SHUFFLE_SEED`, `CHANGED`, `UNCHANGED` |
| [test_snapshot.py](../../../experiments/forest_v2/s05_snapshot/test_snapshot.py) | Die Checks des Slices, direkt mit pytest auf der Datei auszufuehren. Sie behaupten ausdruecklich nichts ueber Extraktionsqualitaet. | `test_an_untouched_tree_still_builds`, `test_mutation_between_plane_extractions_is_refused`, `test_mutation_reverted_before_the_build_is_still_refused`, `test_a_missing_scope_bracket_is_not_an_option` |

Das Verzeichnis ist flach und kein Paket: `reference_planes` und der Probe
importieren `snapshot` als Geschwistermodul und legen dafuer notfalls das
eigene Verzeichnis auf `sys.path`.

## Der Vertrag `forest-v2-plane-extraction/2`

Eine Ebenen-Extraktion ist ein JSON-Objekt mit genau den Schluesseln `schema`,
`plane`, `revision`, `producer`, `nodes`, `edges`, `witness`. **Ein unbekannter
Schluessel ist eine Verweigerung**, kein still ignoriertes Feld — sonst koennte
ein Produzent eine Wanduhr oder einen absoluten Pfad in den digestierten Inhalt
schmuggeln und die Replay-Identitaet stuerbe leise.

Regeln an einen Produzenten: Knoten-IDs innerhalb der Ebene eindeutig; Locators
relativ, posix, nie absolut; `end_line >= start_line`; `attrs` JSON-faehig mit
String-Schluesseln; **Kanten nur innerhalb einer Ebene** — ein Extraktor, der
eine Cross-Plane-Relation behauptet, wird mit eigenem Code abgelehnt, weil
Masterplan §6 solche Kanten einem Verifier gibt und nicht einem Extraktor; und
jeder Knoten-Locator muss auf eine Datei zeigen, die dieselbe Ebene bezeugt hat.

`producer` steht bewusst **ausserhalb** des Digests. Genau das erlaubt es s01
bis s04, die Platzhalter-Extraktoren zu ersetzen, ohne den Digest zu bewegen,
solange die Extraktion identisch ist.

### Digest-Algebra

Domaenen-separiert, sortiert, ordnungs- und pfadunabhaengig:

- `node_digest` und `edge_digest` = SHA-256 ueber die kanonische Form des
  Objekts (`canonical_bytes`: JSON, sortierte Schluessel, keine Leerzeichen,
  UTF-8, kein ASCII-Escaping).
- `plane_digest` = SHA-256 ueber Domaene, Ebene, Revision, sortierte
  Knoten- und Kanten-Digests **und** die sortierten Zeugen-Eintraege.
- `snapshot_digest` = SHA-256 ueber Domaene, Vertrag, Revision und die vier
  festen Ebenen-Digests.

Zwei Entscheidungen tragen hier: der Zeuge liegt **innerhalb** des
Ebenen-Digests, sonst beschriebe der Digest nur die extrahierte *Sicht* — eine
Quelltextaenderung, die kein Extraktor anschaut, liesse den Digest eines
"revisionsatomaren Snapshots" unbewegt. Die Scope-Klammer liegt **ausserhalb**
des Snapshot-Digests, denn sie ist Evidenz ueber den Bau, nicht Inhalt des
Snapshots: eine Datei im Scope, die keine Ebene liest, darf die Identitaet des
Extrahierten nicht aendern.

## Wie die Revision heute gebunden wird

**Schicht 1 — der Zeuge pro Ebene.** Jeder Extraktor liest ueber die eine
Funktion `read_source_text`, die den Digest des gerade zurueckgegebenen Textes
mitschreibt. Der Zeuge ist ein Nebenprodukt genau des Lesevorgangs, der die
Extraktion fuettert — nie ein zweites Lesen, das einen anderen Baumzustand
sehen koennte. Zwei Ebenen, die dieselbe Datei lesen, muessen denselben Digest
bezeugen (`witness_conflict`).

**Schicht 2 — die Scope-Klammer.** Der Aufrufer scannt den deklarierten Scope
vor der ersten und nach der letzten Extraktion und uebergibt beide Lesungen.
Sie muessen gleich sein (`scope_drift`), und jeder Zeugeneintrag muss dem
geklammerten Zustand dieser Datei entsprechen (`witness_scope_mismatch`,
`witness_outside_scope`).

Keine Schicht genuegt allein: Schicht 1 sieht eine Datei nicht, die nur eine
Ebene liest; Schicht 2 sieht keine Mutation, die vor dem schliessenden Scan
zurueckgenommen wurde. Zusammen weisen sie beides zurueck. Das `scope`-Argument
von `build_snapshot` ist **pflicht und hat keinen Default** — ein
Atomaritaetsgatter, das der Aufrufer weglassen darf, ist kein Gatter, und
`test_a_missing_scope_bracket_is_not_an_option` haelt das zu.

Der Scope ist *deklariert*, nicht aus dem abgeleitet, was die Extraktoren
zufaellig gelesen haben — ein von seinen eigenen Lesern definierter Scope
bewiese nichts. `build_atomic_snapshot` ist der eine Einstieg, der die
Reihenfolge scannen/extrahieren/scannen richtig macht; diese Reihenfolge ist die
ganze Garantie, deshalb liegt sie in einer Funktion statt in vier Aufrufstellen,
die sie je einzeln falsch machen koennen.

Was **nicht** abgedeckt ist, offen genannt: eine Datei, die innerhalb des
Fensters mutiert und zurueckgenommen wird, waehrend keine Ebene die mutierten
Bytes gelesen hat — dann haengt kein Ebeneninhalt am transienten Zustand.
Zweiter Vorbehalt: Zeugen und Scope-Eintraege sind vom Produzenten
selbstberichtet. Sie besiegen einen konkurrierenden Schreiber, nicht einen
luegenden Extraktor.

## Verweigerungscodes

`ContractError` traegt einen maschinenlesbaren `code`. Im Builder vorhanden
(gemessen 2026-09-05 an den Aufrufstellen in
[snapshot.py](../../../experiments/forest_v2/s05_snapshot/snapshot.py)):

- Vertragsform: `bad_schema`, `bad_document`, `bad_revision`, `bad_node`,
  `bad_edge`, `bad_locator`, `bad_attrs`, `bad_scope`, `unknown_key`,
  `unknown_plane`, `absolute_locator`, `duplicate_node_id`.
- Ebenensatz: `missing_plane`, `duplicate_plane`, `revision_mismatch`.
- Atomaritaet: `scope_drift`, `witness_conflict`, `witness_scope_mismatch`,
  `witness_outside_scope`, `unwitnessed_locator`, `nodes_without_witness`.
- Graphform: `dangling_edge`, `cross_plane_edge`.

Es gibt kein Teilergebnis: eine Verweigerung liefert gar keinen Digest.

## Was der Probe misst

`probe` liefert ein JSON-Objekt mit dem Schema
`forest-v2-s05-replay-identity-probe/2` und misst fuenf Dinge:

1. **Replay-Identitaet** — zweimal extrahieren und bauen in einem Prozess.
2. **Unabhaengigkeit** — der Digest darf sich nicht bewegen, wenn die Wurzel
   anders geschrieben wird, wenn Knoten- und Kantenreihenfolge gemischt wird
   (Seed `SHUFFLE_SEED`), oder wenn die Dokumente einen JSON-Rundlauf machen.
3. **Feld-Sensitivitaet** — genau ein Feld eines Objekts mutieren. Drei
   Ausgaenge sind legitim und pro Mutator vorher deklariert: der Digest bewegt
   sich (das Feld ist digestiert), er haelt (das Feld ist Provenienz), oder der
   Bau wird mit benanntem Code verweigert (das Feld ist bewacht). Ein Mutator,
   der sich nicht als ein Feld ausdruecken laesst, wirft `Skip` und wird als
   uebersprungen gezaehlt statt die Quote still aufzupolstern.
4. **Struktur-Sensitivitaet** — Loeschungen sind keine Feldmutationen und
   werden getrennt berichtet.
5. **Verweigerungsmatrix** — jede Art, einen partiellen, inkonsistenten oder
   unbezeugten Ebenensatz anzubieten, mit dem erwarteten Code.

Zeiten werden **pro Phase** berichtet (oeffnender Scan, Extraktion, Bau,
schliessender Scan), weil eine fruehere Fassung Extraktion und Bau unter einer
Zahl fuehrte und den Bau dadurch etwa viermal teurer aussehen liess, als er ist.
Prozessuebergreifende Identitaet (verschiedene `PYTHONHASHSEED`) misst der Probe
absichtlich nicht — ein Probe, der einen Subprozess startet, ist nicht mehr
read-only; der README nennt stattdessen das manuelle Verfahren.

`read_git_revision` loest HEAD **ohne Subprozess** auf: gewoehnliches
`.git`-Verzeichnis, Worktree-Datei mit `gitdir:`, detached HEAD, symbolische Ref
im gitdir oder im `commondir`, sowie `packed-refs`. Ist der Baum kein
Git-Checkout, liefert die Funktion `None` und der Aufrufer setzt sein eigenes
Revisions-Label.

## Ergebnislage (aus dem Slice-README, nicht nachgemessen)

Die Zahlen stehen in
[experiments/forest_v2/README.md](../../../experiments/forest_v2/README.md),
Abschnitt "Slice s05", und sind dort mit `[MEASURED]` gestempelt: zweimal bauen
liefert identische Digests und byte-gleiche Manifeste; drei Prozesse mit
verschiedenem Hash-Seed ebenso; alternative Wurzelschreibweise, gemischte
Reihenfolge und JSON-Rundlauf aendern nichts; Feld-Sensitivitaet 18 von 18 wie
erwartet bei 0 uebersprungenen, Struktur-Sensitivitaet 3 von 3, Verweigerungs-
matrix 17 von 17 mit exakt dem erwarteten Code. Der Preis der Atomaritaets-
bindung wird als +18 % Gesamtlaufzeit gegenueber Vertrag `/1` angegeben, wobei
das Bezeugen waehrend der Extraktion fast gratis ist und die beiden
zusaetzlichen Vollscans die eigentlichen Kosten sind.

Das Gate wurde **erst rot gesehen, dann gruen**: unter Vertrag `/1` produzierten
die drei Mutationsszenarien genau den Digest, den der Builder nie haette liefern
duerfen. Und jede Wache ist an mindestens einen Check gebunden — beim
einzelweisen Abschalten einer Verweigerung wurde jeweils mindestens ein Test
rot.

Diese Zahlen sind Eigenschaften *dieses* Baums zum Messzeitpunkt, nicht
Konstanten; der README nennt 2026-09-15 als Verfallsdatum, nach dem vor
Wiederverwendung neu zu messen ist.

## Verwandt

- [Forest v2 (Programm)](forest-v2.md) — der Rahmen, in dem s01 bis s11 stehen.
- [Forest v2 s01 — Aufloesung](forest-v2-s01-resolution.md) und
  [Forest v2 s02 — Typen](forest-v2-s02-types.md) — die Slices, die die
  Platzhalter-Extraktoren dieses Slices ersetzen sollen.
- [Forest v2 s06 — Node Cards](forest-v2-s06-cards.md) — der naechste Konsument
  einer Ebenen-Extraktion.
- [Forest v2 s07 — BM25-Baseline](forest-v2-s07-bm25.md) — derselbe
  Experimentrahmen, andere Frage.
- [Twin](../architecture/twin.md) und
  [Twin-Extraktoren](../architecture/twin-extractors.md) — die
  Produktionsseite der vier Ebenen.
- [Kernel](../architecture/kernel.md) und [Spine](../architecture/spine.md) —
  wo Artefaktidentitaet und Effektgrenze in der Produktion liegen.
- [Wiki](../architecture/wiki.md) — dieselbe Trennung "Modell schlaegt vor,
  deterministische Pruefung entscheidet", eine Ebene hoeher.
- [Graph-Delta als Fitness](../graph-delta-as-fitness.md) und
  [Wiki-Index](../index.md).

## Ungeklaert

- **Ungeklaert:** ob die im README genannten Zahlen noch auf den heutigen Baum
  passen. Der Probe wurde fuer diese Seite **nicht** ausgefuehrt; die
  Extraktionswurzeln (`CODE_ROOTS`, `DATA_ROOTS`, `KNOWLEDGE_ROOTS`) haben seit
  der Messung vom 2026-08-18 sicher Dateien dazugewonnen, womit sich jeder
  Digest und jede Knotenzahl bewegt haben duerfte.
- **Ungeklaert:** die Verfallsfrist 2026-09-15 aus dem README wird nach allem,
  was im Code sichtbar ist, nirgends mechanisch geprueft.
- **Ungeklaert:** ob s01 bis s04 die Platzhalter in
  [reference_planes.py](../../../experiments/forest_v2/s05_snapshot/reference_planes.py)
  inzwischen ersetzen koennen. Der Docstring sagt "wenn diese Slices landen";
  eine Verdrahtung war 2026-09-05 nicht sichtbar, `EXTRACTORS` verweist weiter
  auf die vier lokalen Funktionen.
- **Ungeklaert:** `SCOPE_SCHEMA` ist definiert, taucht in der von
  `build_snapshot` zurueckgegebenen Manifeststruktur aber nicht auf; wo dieses
  Schema-Label konsumiert wird, liess sich aus dem Slice nicht ablesen.
- **Abweichung Doku/Code:** der Modul-Docstring von
  [reference_planes.py](../../../experiments/forest_v2/s05_snapshot/reference_planes.py)
  (Zeile 3) nennt `forest-v2-plane-extraction/1` als den Vertrag, den die
  Extraktoren erfuellen, waehrend das Modul `CONTRACT` aus
  [snapshot.py](../../../experiments/forest_v2/s05_snapshot/snapshot.py)
  (Zeile 83) importiert und der dort auf `/2` steht. Der uebrige Docstring
  beschreibt bereits die `/2`-Mechanik mit Zeugen und Klammer, es sieht also
  nach einer nicht nachgezogenen Zeile aus.
- **Ungeklaert:** die Testdatei liegt im Slice, nicht unter `tests/`; ob sie in
  einem CI-Lauf mitlaeuft, war 2026-09-05 nicht erkennbar (kein Treffer fuer
  `s05_snapshot` unter `tests/`).

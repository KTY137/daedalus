---
title: Forest v2 s06 cards
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s06_cards
---
# Forest v2 s06 cards

`experiments/forest_v2/s06_cards` baut und misst den Node-Card-Vertrag aus Plan
§6. Ein Node Card ist der schemaleichte Datensatz, den ein Embedding konsumieren
darf: stabile Knoten-Identitaet, Revision, Ebene, Quell-Locator, kompakter
Inhalt, lokale Nachbarschaft und Provenienz — genau diese sieben Felder, nie ein
buchstaeblich schemafreier Graph. Der Slice ist ein isoliertes Experiment
(Plan §1): read-only, reine Standardbibliothek, keine Repository-Importe, keine
Schreibvorgaenge, kein Netzwerk, kein Subprozess. Ein Card ist ein
*Vorschlagstraeger*, nie Evidenz, und dieses Verzeichnis promotet nichts
(Plan §4, Invarianten 4 und 5).

Gemessen 2026-09-05: 10 `.py`-Dateien im Verzeichnis (5 Module, 5 Testdateien),
3653 Zeilen; die 5 Module tragen 1954.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`node_cards.py`](../../../experiments/forest_v2/s06_cards/node_cards.py) | Die Vertragshaelfte: verwandelt Knoten-Records in Node Cards, validiert beide Richtungen und zaehlt. | `build_card`, `validate_record`, `validate_card`, `node_id`, `tally`, `size_stats`, `card_size_bytes`, `to_jsonl`, `ProvenanceBook`, `provenance_ref`, `canonical_bytes`, `sha256_of`, `sha256_text`, `CARD_SCHEMA`, `RECORD_SCHEMA`, `PLANES`, `CODE_NODE_KINDS`, `REQUIRED_RECORD_FIELDS`, `REQUIRED_CARD_FIELDS`, `DEFAULT_CONTENT_BUDGET`, `DEFAULT_NEIGHBOR_BUDGET`, `DEFAULT_DOC_BUDGET` |
| [`standin_source.py`](../../../experiments/forest_v2/s06_cards/standin_source.py) | Ein Ersatz-Knotenquell, damit der Vertrag heute messbar ist: Code-Ebene per stdlib-AST, Knowledge-Ebene per Ueberschriften-Walk. | `iter_records`, `code_records`, `knowledge_records`, `resolve_revision`, `file_digest`, `module_name`, `CODE_PACKAGES`, `KNOWLEDGE_DIRS` |
| [`s01_upstream.py`](../../../experiments/forest_v2/s06_cards/s01_upstream.py) | Die echte Verdrahtung an Slice s01, mit benannter Luecke, wenn s01 nicht auffindbar ist. | `load_upstream`, `Upstream`, `find_s01`, `s01_input_digest`, `S01_RELATIVE`, `S01_ENV_VAR`, `S01_INPUT_MODULES`, `UPSTREAM_GAP_ID` |
| [`negative_fixtures.py`](../../../experiments/forest_v2/s06_cards/negative_fixtures.py) | Der negative Pfad: Eingaben, die die Null-Zaehler tatsaechlich bewegen. | `counter_liveness`, `run_fixture`, `Fixture`, `FIXTURE_PROVENANCE` |
| [`probe_node_cards.py`](../../../experiments/forest_v2/s06_cards/probe_node_cards.py) | Read-only-Sonde: baut ein Card fuer jeden Record ueber einem Baum und druckt *ein* JSON-Objekt mit Rohzahlen. | `probe`, `main` |

### Zwei Identitaeten, absichtlich getrennt

- `node_id` ist die *stabile* Identitaet: Ebene, Pfad, Art, Qualname (plus eine
  Ordnungszahl, wenn eine Datei denselben Qualname zweimal deklariert). Sie
  ueberlebt eine Zeilenverschiebung, eine Neuformatierung oder eine
  Docstring-Aenderung.
- `card_id` ist die *Inhaltsadresse des Cards an einer Revision*: ein SHA-256
  ueber das gesamte Card ausser `card_id` selbst. Sie aendert sich, sobald
  Locator, Inhalt, Nachbarschaft oder Provenienz sich aendern.

Der Docstring nennt den Grund fuer die Trennung: §6 will Embeddings ueber
Revisionen hinweg vergleichbar machen, §5s Revisions-Atomizitaet will ein Card,
das nicht still behaupten kann, eine Revision zu beschreiben, aus der es nicht
gebaut wurde. Ein Feld kann nicht beides; zwei koennen es. `build_card` hasht
ausdruecklich keinen Wanduhr-Zeitstempel ins Card — ein Card, das bei jedem Lauf
seine Identitaet aenderte, koennte nicht ueber Revisionen verglichen werden, und
das ist der einzige Grund seiner Existenz.

### Provenienz per Referenz

`card["provenance"]` ist eine `sha256:`-Inhaltsadresse, kein Block. Der Build
gibt jeden distinkten Block genau einmal in einer `ProvenanceBook` aus. Die
gemessene Begruendung steht im Docstring: den Block stattdessen einzubetten
kostete 281 kanonische Bytes in *jedem* Card — bei einem Korpus von 8466 Cards
2,3 MB eines einzigen wiederholten Literals, und es blaehte die Zahl "was
berechnet §6 vor dem ersten nuetzlichen Zeichen" um ein Drittel auf. Eine
Referenz, die nicht aufloest, ist ein Vertragsbruch (`dangling_provenance`,
siehe unten), damit die Kompression sich nicht mit einem baumelnden Zeiger
selbst bezahlt.

### Der negative Pfad

`negative_fixtures.py` existiert wegen eines konkreten, im Docstring
eingestandenen Fehlers: die erste Fassung des Slices meldete
`records_rejected = 0` und `contract_violations = 0` und praesentierte das als
Ergebnis. Das waren keine Ergebnisse — die Sonde fuetterte nur wohlgeformte
Records in `build_card`, und `build_card` wirft, bevor ein defekter Record ein
Card werden kann. Ein Zaehler, der sich nicht bewegen kann, ist keine Messung,
sondern eine Umformulierung des Kontrollflusses.

Die Reparatur ist keine bessere Assertion, sondern eine zweite Eingabe. Jede
Fixture verletzt genau eine Bedingung und laeuft durch `node_cards.tally` —
**dieselbe Funktion wie der Korpuslauf**, kein parallel geschriebener Pruefer,
der ihr zustimmt — und meldet den Zaehler davor und danach. Eine Null ueber dem
echten Korpus traegt dann Information. Die Bedingungen (der Docstring nennt sie
"die fuenf", zaehlt aber sechs auf, gemessen 2026-09-05):
`malformed_record`, `duplicate_node_id`, `budget_overrun`, `missing_plane`,
`missing_revision`, `dangling_provenance`.

### Zwei Ebenen, damit es kein Code-Format wird

`standin_source.py` gibt bewusst zwei Ebenen aus. Ein Card-Vertrag, der nur je
Python gesehen haette, waere still zu einem Code-Ebenen-Format geworden, und §5
verbietet ausdruecklich eine fuenfte AST-Ebene, die aus einer herauswaechst.
Knowledge-Ebenen-Abschnitte durch denselben Builder zu schicken ist die
billigste verfuegbare Falsifikation der Behauptung "diese Cards sind heimlich
code-only".

### Die benannte Kopplung an s01

`s01_upstream.py` ersetzt einen frueheren `s01_adapter.py`, der geraten hatte,
s01 werde einen JSONL-Strom von Knoten-Dicts ausgeben, und dafuer eine
Alias-Tabelle fuer Schluesselnamen anbot. Der Docstring sagt, warum das nicht
reparabel war: die Vermutung war in der *Form* falsch, nicht nur in der
Benennung — s01 gibt gar keinen Strom aus, sein Vertrag ist ein Python-Vertrag
(`build_index(root) -> ProjectIndex`, `resolve_module(index, module)` mit
`Resolution`-Objekten). Eine Alias-Tabelle ueber JSON-Schluesseln haette das nie
absorbieren koennen.

Was die Verdrahtung erzeugt: Code-Ebene aus s01 (ein Record je Modul, je
modulweiter Funktion/Klasse/Zuweisung und je Methode, Zeilenbereiche aus s01s
eigenem geparsten Baum, damit ein Locator nie geraten ist); Kanten aus s01s
`Resolution`-Objekten (eine Aufrufstelle wird der Definition zugeordnet, deren
Zeilenbereich sie enthaelt, was `calls`-Kanten mit echten Zielen ergibt;
Klassenbasen werden zu `derives_from`; **unaufgeloeste Aufrufe werden gezaehlt,
nicht erfunden**); Knowledge-Ebene weiterhin aus `standin_source`, weil s01 ein
Code-Ebenen-Resolver ist und keine Knowledge-Ebene anzubieten hat — und dieser
Split wird pro Ebene im Provenance-Book berichtet statt in Prosa behauptet.

s01 liegt in einem Schwester-Worktree. `find_s01` sucht in dieser Reihenfolge:
explizites `--s01-path`, Umgebungsvariable `F2_S01_PATH`, dann eine Suche in
Schwester-Worktrees. Findet nichts davon s01, degradiert der Lauf **nicht
still**: er faellt auf den Stand-in zurueck und meldet eine strukturierte Luecke
(`UPSTREAM_GAP_ID` = `"s06-upstream-s01-unreachable"`) einmal pro Build. Der
vorige Slice trug dieselbe Tatsache als 55-Byte-Prosafussnote in allen 8466
Cards; eine benannte Luecke an einer Stelle ist dieselbe Information, ehrlich, zu
einem 8466stel der Kosten.

## Trust-Grenzen / Effekte

- **Keine Effekte, kein Writer.** Alle fuenf Modul-Docstrings sagen es
  gleichlautend: read-only, reine stdlib, keine Repository-Importe, keine
  Schreibvorgaenge, kein Netzwerk, kein Subprozess. `probe_node_cards.py` druckt
  ein JSON-Objekt nach stdout; wer es auf Platte will, leitet um, und die
  Entscheidung zu schreiben liegt dann ausserhalb des Experiments. Ein
  effektbehafteter Entrypoint unter `experiments/` muesste erst in der
  kanonischen Effekt-Registry stehen — siehe [Spine](../architecture/spine.md).
- **Der einzige Import ausserhalb der stdlib ist s01**, und zwar dessen
  read-only Module, geladen ueber `_import_s01` aus einem explizit gesuchten
  Pfad. Es gibt keine Import-Kante zu `daedalus/`.
- **Fail-loud statt fail-quiet.** `build_card` wirft `ValueError` bei einem
  vertragsbrechenden Record, statt ein defektes Card zu erzeugen. `tally`
  benutzt durchgehend `.get`, weil die negativen Fixtures ihm absichtlich Cards
  mit entfernten Feldern uebergeben und der Zaehler ueberleben muss, um sie zu
  zaehlen.
- **Ein Card empfaengt nie einen schemafreien Graphen.** Ebene, Revision,
  Identitaet und Provenienz sind Pflicht und werden validiert — genau die
  Mindestvertragsgrenze aus Plan §6.
- **Budgets sind erklaert und ihre Ueberschreitung wird gemeldet.**
  `DEFAULT_CONTENT_BUDGET` 800, `DEFAULT_NEIGHBOR_BUDGET` 8, `DEFAULT_DOC_BUDGET`
  200 (gemessen 2026-09-05); die Nachbarschaft traegt `edge_total`, `truncated`
  und `budget` mit, sodass eine Kuerzung sichtbar bleibt statt zu verschwinden.

## Tests

Gemessen 2026-09-05 liegen die Tests im Paket, nicht unter `tests/` — konsequent
zur Isolationsregel. Eine Suche nach `s06_cards` unter `tests/` findet nichts.

- [test_node_cards.py](../../../experiments/forest_v2/s06_cards/test_node_cards.py) — 397 Zeilen, der Kartenvertrag
- [test_negative_paths.py](../../../experiments/forest_v2/s06_cards/test_negative_paths.py) — 266 Zeilen, die Zaehler-Lebendigkeit
- [test_edge_join.py](../../../experiments/forest_v2/s06_cards/test_edge_join.py) — 380 Zeilen, der Kanten-Join aus s01s Resolutions
- [test_upstream_pin.py](../../../experiments/forest_v2/s06_cards/test_upstream_pin.py) — 358 Zeilen, die Anbindung und die benannte Luecke
- [test_probe_node_cards.py](../../../experiments/forest_v2/s06_cards/test_probe_node_cards.py) — 298 Zeilen, die Sonde

## Verwandt

- [Forest v2](forest-v2.md) — die gemeinsame Grenznotiz aller Slices
- [Forest v2 s01 resolution](forest-v2-s01-resolution.md) — der eigentliche Erzeuger der Knoten-Records
- [Forest v2 s05 snapshot](forest-v2-s05-snapshot.md) — Revisions-Atomizitaet, die `card_id` bindet
- [Forest v2 s07 bm25](forest-v2-s07-bm25.md), [Forest v2 s11 fusion](forest-v2-s11-fusion.md) — Konsumenten einer Card-artigen Repraesentation
- [Forest v2 s10 kill](forest-v2-s10-kill.md) — die Kriterien, an denen der Latent-Atlas-Prior scheitern darf
- [Forest v2 tensor embeddings](forest-v2-tensor-embeddings.md) — die Embedding-Seite derselben Frage
- [Twin](../architecture/twin.md), [Twin extractors](../architecture/twin-extractors.md) — die produktive Extraktion der vier Ebenen
- [Knowledge layer](../architecture/knowledge-layer.md), [Type graph](../architecture/type-graph.md), [Data layer](../architecture/data-layer.md) — die Ebenen, die ein Card benennen kann
- [Memory](../architecture/memory.md) — der produktive Embedding-Index
- [Wiki-Index](../index.md)

## Ungeklaert

- **Die 8466 Cards und die 281 Bytes** sind Messungen aus einem frueheren Lauf
  auf Basis `d849c2a9`, im Docstring zitiert. Ob sie fuer den heutigen Baum noch
  gelten, hat diese Seite nicht nachgemessen.
- **Ob s01 heute auffindbar ist.** `find_s01` sucht Schwester-Worktrees und
  `F2_S01_PATH`; ob eine dieser Quellen auf dieser Maschine existiert, ist eine
  Umgebungsfrage. Bei Fehlschlag laeuft der Slice auf dem Stand-in und meldet
  `UPSTREAM_GAP_ID`.
- **`CODE_PACKAGES = ("daedalus", "tools", "runs")`** in `standin_source.py`
  benennt Verzeichnisse als Textpfade, nicht als Importe — der Stand-in liest
  Quelldateien mit dem AST-Modul. Warum `runs` als Code-Paket gefuehrt wird, geht
  aus dem Modul nicht hervor.
- **Der Docstring von `negative_fixtures.py` sagt "die fuenf Bedingungen",
  listet aber sechs** (`experiments/forest_v2/s06_cards/negative_fixtures.py:28-38`).
  Der Code hat sechs Fixture-Funktionen; die Ueberschrift ist die veraltete
  Zahl.
- **Ob `s01_upstream.load_upstream` oder `standin_source.iter_records` der
  Default-Pfad der Sonde ist**, haengt vom Fund von s01 ab;
  `probe_node_cards.py` importiert `load_upstream`, das intern zurueckfaellt.

---
title: Forest v2 s07 — BM25-Baseline
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/s07_bm25
---
# Forest v2 s07 — BM25-Baseline

Slice s07 ist die billigste ehrliche Retrieval-Baseline des Programms: ein
reines Stdlib-BM25 ueber die Dateien des Repositories, eingefroren **bevor**
irgendein graph-konditionierter Retriever existierte. Der Masterplan nennt BM25
zweimal — als Pflicht-Baseline in Gate 3 und als Kill-Kriterium ("die volle
Repraesentation schlaegt code-only oder BM25-Retrieval nicht"). Ein
Kill-Kriterium ohne Implementierung kann nicht ausloesen; dieses Verzeichnis
ist die Implementierung. Im Ariadne-Bild ist s07 kein Produktionspfad, sondern
der Messboden, gegen den spaetere Retriever antreten muessen: Es gehoert zum
Ariadne-Evaluationsteil, nicht zum Kernel.

Rahmen des Slices (aus den Modul-Docstrings): read-only, nur Stdlib, keine
Importe von Repository-Code, kein Netzwerk, keine Schreibvorgaenge — und kein
Subprozess, mit **einer** offen deklarierten Ausnahme (siehe unten).

## Module

Gemessen 2026-09-05: 7 `.py`-Dateien mit 2385 Zeilen, davon 4
Implementierungsdateien mit 1538 Zeilen. Die Selbsttests liegen im Slice selbst,
nicht unter `tests/`.

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`bm25_index.py`](../../../experiments/forest_v2/s07_bm25/bm25_index.py) | Der Index: identifier-bewusste Tokenisierung, Okapi-BM25, optionaler Pfad-Token-Boost, CLI-Ausgabe als JSON. | `BM25Index`, `IndexConfig`, `SearchHit`, `BuildReport`, `tokenize`, `token_counts`, `iter_documents`, `search_repository`, `main`, `SCHEMA`, `DEFAULT_EXTENSIONS`, `CODE_DOC_EXTENSIONS`, `DEFAULT_SKIP_DIRS` |
| [`contamination.py`](../../../experiments/forest_v2/s07_bm25/contamination.py) | Die Kontaminationsregel pro (Query, Dokument)-Paar samt Mutanten-Schaltern. | `EvidenceRule`, `ContaminationMap`, `scan`, `normalise`, `ADOPTED_RULE`, `QUERY_QUOTE_ONLY`, `REASON_QUERY_QUOTE`, `REASON_GOLD_PATH_CITATION`, `ALL_REASONS` |
| [`measure_bm25.py`](../../../experiments/forest_v2/s07_bm25/measure_bm25.py) | Die RAW-Messung ueber den eingefrorenen, handgeschriebenen 12-Query-Satz; ein JSON-Objekt auf stdout. | `QUERY_SET`, `pair_query_set`, `evaluate`, `build_contamination_maps`, `run`, `main`, `SCHEMA`, `RANK_LIMIT`, `LEGACY_QUERY_CARRIERS` |
| [`s09_anchor.py`](../../../experiments/forest_v2/s07_bm25/s09_anchor.py) | Derselbe Index, gemessen am unabhaengig eingefrorenen Taskset von Slice s09; rekonstruiert historische Baeume ueber Git-Plumbing. | `AnchorError`, `load_taskset`, `list_tree`, `read_blobs`, `score_case`, `aggregate`, `run`, `main`, `TASKSET_PATH`, `VARIANTS` |
| [`test_bm25_index.py`](../../../experiments/forest_v2/s07_bm25/test_bm25_index.py) | Hermetische Scoring-Tests plus ein "known hit"-Selbsttest ueber echte Teilbaeume. | — |
| [`test_evidence_rule.py`](../../../experiments/forest_v2/s07_bm25/test_evidence_rule.py) | Pinnt die Kontaminationsregel, inklusive Mutationssonde: jede abgeschwaechte Regel muss von einer Assertion getoetet werden. | `MUTANTS`, `CORE_ASSERTIONS` |
| [`test_s09_anchor.py`](../../../experiments/forest_v2/s07_bm25/test_s09_anchor.py) | Prueft Digest-Freeze, Metrikdefinitionen und die Aequivalenz des Token-Count-Schnellpfades. | `S09_FROZEN_CONTENT_SHA256` |

Nicht-Python im Verzeichnis: `s09_taskset.json`, eine Byte-Kopie des von s09
eingefrorenen Tasksets (20 Faelle, Anker-Commit `d849c2a9`).

### Der Index

`IndexConfig` friert die Stellschrauben ein: `k1` 1.2, `b` 0.75, `path_weight`
3, `min_token_len` 2, `max_file_bytes` 512 KiB, dazu `extensions`, `skip_dirs`,
`max_files` und `exclude_paths`. `path_weight` haengt die tokenisierte
repo-relative Pfadangabe n-mal an das Dokument; `path_weight=0` ist die
Content-only-Ablation.

`BM25Index` wird ueber `build` (Dateibaum), `from_documents` (Mapping) oder
`from_counted_documents` (vorgezaehlte Token) gebaut. `search` liefert
`SearchHit`-Objekte mit dichtem, 1-basiertem `rank`; Gleichstand bricht
aufsteigend nach Pfad, was das Ranking auf einem festen Baum byte-identisch
reproduzierbar macht. `rank_of` ist der eine Aufruf, den eine
Gold-Datei-Evaluation braucht. `with_scoring` gibt eine Sicht auf **dieselben**
Postings mit anderem `k1`/`b` zurueck, damit eine Scoring-Ablation nicht
versehentlich ein anderes Korpus indiziert. `idf` verwendet Lucenes
nicht-negative Variante.

`iter_documents` ist laut Docstring *die* Korpusdefinition: sowohl der Index
als auch der Kontaminationsscanner konsumieren sie, damit die Evidenzregel nicht
ueber ein anderes Korpus urteilt als das gemessene. `BuildReport` fuehrt RAW-
Zaehler (`files_seen`, `files_indexed`, die vier Skip-Zaehler,
`bytes_indexed`, `build_seconds`), ohne zu glaetten.

### Die Kontaminationsregel

Die erste Fassung des Slices schloss drei ganze Dateien aus *jeder* Query aus.
Das ist der Defekt, den `contamination.py` ersetzt: Kontamination ist eine
Eigenschaft eines **Paares**, nie einer Datei. Ein Dokument D wird aus Query Q
zurueckgehalten, wenn (C1) D den Query-String woertlich enthaelt oder (C2) D
einen der Gold-Pfade von Q woertlich zitiert — es sei denn, D ist selbst ein
Gold-Dokument von Q. `normalise` casefoldet, vereinheitlicht Pfadtrenner und
kollabiert Whitespace-Laeufe; weiter geht die Normalisierung bewusst nicht,
weil `from daedalus.budget import Ledger` sonst als Zitat von
`daedalus/budget.py` gezaehlt wuerde und die Regel damit den eigenen Callgraph
des Repositories aus dem Korpus loeschte.

`EvidenceRule` traegt die Abschwaechungs-Schalter (`token_level_query_match`,
`query_independent`) ausdruecklich als *Mutanten*, damit die Mutationssonde in
`test_evidence_rule.py` pruefen kann, dass die Assertions ueberhaupt beissen.
`ContaminationMap` haelt `withheld[query] -> {pfad: gruende}` und liefert
`excluded_for`, `pair_count`, `reason_counts`.

### Die zwei Query-Saetze

`measure_bm25.py` fuehrt einen am 2026-08-18 eingefrorenen Satz von 12 Queries
mit je einer Gold-Datei, handgeschrieben vom selben Autor wie der Retriever.
Der Docstring nennt die Grenze selbst und `s09_anchor.py` behebt sie: derselbe
`BM25Index`, gemessen an den 20 Faellen des s09-Tasksets, dessen Queries
Commit-Betreffs sind, dessen Gold die geaenderten Dateien des Commits sind und
dessen Kandidatenuniversum der Baum am Eltern-Commit ist. `load_taskset`
rechnet den Digest nach s09s eigener Regel neu; eine editierte Kopie faellt laut
mit `AnchorError` aus, statt zu scoren. `_eligible` reproduziert s09s
Eligibility-Praedikat, und `universe_size` aus dem eingefrorenen Record wird pro
Fall gegen das hier rekonstruierte Universum geprueft.

Gefiltert wird **nach** dem Ranking, nicht im Index: Korpusstatistiken (N, idf,
mittlere Dokumentlaenge) bleiben ueber alle Filter-Arme identisch, sodass eine
Metrikdifferenz zwischen Armen der Filter ist und nichts sonst.

## Ergebnisse (uebernommen, nicht selbst gemessen)

Die folgenden Zahlen stehen in
[`experiments/forest_v2/README.md`](../../../experiments/forest_v2/README.md)
und sind dort auf 2026-08-18 datiert; sie sind hier **zitiert**, nicht neu
gemessen. Der Slice erklaert eine **Verfallsfrist 2026-09-15** fuer diese
Zahlen: eine Baseline aus einem bewegten Baum ist keine Baseline.

- Primaerarm (volles Korpus, `path_weight=3`): h@1 5 von 12, h@10 12 von 12,
  MRR@10 0.6169.
- Nur Code und Prosa (ohne JSON): h@1 9 von 12, MRR@10 0.8611.
- Am s09-Taskset, ungefiltert, Variante `raw`: MRR 0.1383 bei 20 Faellen.

Die inhaltlich wichtigste Aussage des Slices ist das dritte Ergebnis: derselbe
Retriever ist auf dem fremd eingefrorenen Satz rund viermal schlechter als auf
dem selbst geschriebenen. Der Slice zieht daraus die Regel, im Vergleich stets
die verankerte Zahl zu zitieren.

Ausserdem als negatives Ergebnis festgehalten: die Begruendung, mit der die
Blanket-Regel zurueckgezogen wurde, war fuer dieses Korpus falsch — die
Ueber-Ausschluss-Komponente war laut README exakt 0.0000 MRR wert; der reale
Fehler der alten Regel war **Unter**-Ausschluss.

## Trust-Grenzen / Effekte

- Kein Modul dieses Slices schreibt. `measure_bm25.py`, `s09_anchor.py` und
  `bm25_index.py` geben ihre Ergebnisse als JSON auf stdout aus; ein
  Konsument leitet um.
- Nichts unter `daedalus/` darf diesen Slice importieren; das Verzeichnis hat
  bewusst kein `__init__.py`, und die Skripte laden einander ueber
  `sys.path.insert`.
- **Deklarierte Ausnahme:** die "kein Subprozess"-Klausel ist ausschliesslich
  fuer `s09_anchor.py` gelockert, und nur auf lesendes Git-Plumbing
  (`rev-parse`, `cat-file`, `ls-tree`). Der README haelt fest, warum eine still
  gelockerte Spezifikation nie eingefroren war.
- Es gibt keine Policy-, Lease- oder Evidence-Anbindung an den Kernel; die
  Ergebnisse sind Messungen, kein `EvidencePacket`, und promoten nichts.

## Tests

Alle Selbsttests liegen im Slice-Verzeichnis (gemessen 2026-09-05 per
`grep -rln` ueber `tests/`, `tools/`, `scripts/`, `daedalus/`, `experiments/`:
unter `tests/` referenziert nichts diesen Slice):

- [`test_bm25_index.py`](../../../experiments/forest_v2/s07_bm25/test_bm25_index.py)
- [`test_evidence_rule.py`](../../../experiments/forest_v2/s07_bm25/test_evidence_rule.py)
- [`test_s09_anchor.py`](../../../experiments/forest_v2/s07_bm25/test_s09_anchor.py)

Aufruf laut README: `python -m pytest experiments/forest_v2/s07_bm25/ -q`.

Einziger externer Konsument im Baum:
[`experiments/fourfold_hybrid_retrieval/retrieval.py`](../../../experiments/fourfold_hybrid_retrieval/retrieval.py)
baut seine lexikalischen Seeds auf `BM25Index.from_documents`.

## Verwandt

- [Forest v2](forest-v2.md) — der Slice-Rahmen und der gemeinsame README.
- [s09 Eval](forest-v2-s09-eval.md) — das Taskset, gegen das s07 verankert wird.
- [s08 Graph-Baselines](forest-v2-s08-graph-baselines.md) — der Gegenspieler auf der Graph-Seite.
- [s11 Fusion](forest-v2-s11-fusion.md) und
  [Fourfold Hybrid Retrieval](fourfold-hybrid-retrieval.md) — Konsumenten dieser Baseline.
- [Tensor-Embedding](tensor-embedding.md) — der Arm, der Tensor-Retrieval gegen BM25 stellt.
- [Wiki-Index](../index.md), [Graph delta as fitness](../graph-delta-as-fitness.md).

## Ungeklaert

- **Zwei der zwoelf eingefrorenen Gold-Pfade existieren im Baum nicht mehr**
  (gemessen 2026-09-05): `tools/iron_plan_guard.py` (mit dem Guard am
  2026-08-22 entfernt) und `daedalus/verifier.py`. Was `measure_bm25.py` heute
  ausgibt, ist damit nicht mehr die Zahl in der README-Tabelle. **Ungeklaert:**
  ob der Slice deshalb als abgelaufen gilt oder ob der Query-Satz nach seiner
  eigenen Freeze-Regel unveraendert bleiben muss.
- **Ungeklaert:** der README nennt `"schema": "forest-v2-s07-bm25-measure/1"` im
  Ausgabekontrakt, waehrend `measure_bm25.py` heute `SCHEMA` auf
  `forest-v2-s07-bm25-measure/2` setzt; die spaeteren README-Abschnitte
  beschreiben die /2-Arme. Ob der Kontrakt-Abschnitt nur nachzuziehen ist,
  liess sich aus dem Code nicht entscheiden.
- **Ungeklaert:** der README schreibt, das Verzeichnis sei "deliberately not a
  package"; `experiments/fourfold_hybrid_retrieval/retrieval.py` importiert es
  dennoch als `experiments.forest_v2.s07_bm25.bm25_index`. Ob das ueber
  Namespace-Packages absichtlich funktioniert, steht nirgends.
- **Ungeklaert:** ob die im README genannte Verfallsfrist 2026-09-15 irgendwo
  mechanisch geprueft wird.

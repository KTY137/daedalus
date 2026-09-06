---
title: Forest v2 — Semantic-Composite-Tensor
type: experiment
status: living
updated: 2026-09-05
covers: experiments/forest_v2/tensor_semantic_composite
---
# Forest v2 — Semantic-Composite-Tensor

Ein isoliertes Gate-0-Experiment (Packet-ID `EXPERIMENT-SEMANTIC-COMPOSITE-002`,
eingefroren 2026-08-24, Verfall 2026-10-31) zu genau einer Architekturfrage:
Lassen sich mehrere **eingefrorene** semantische Encoder kombinieren, ohne ein
neues Modell zu trainieren? Die Antwort des Packets ist eine direkte Summe —
jeder Encoder bekommt einen eigenen, geordneten Block auf der Feature-Achse des
bereits vorhandenen Tensor-Konstrukts, und verglichen werden nur Koordinaten
desselben Encoders.

Das Paket enthaelt **keine** Modellausfuehrung. Es gibt bewusst kein
`embed(text)`: das wuerde Modellausfuehrung, Egress, Tower-Auswahl und Kosten
verstecken. Ein berechtigter Aufrufer laesst jeden Encoder ausserhalb dieses
Pakets laufen, behaelt eigene Ausfuehrungs- und Kostenevidenz und uebergibt pro
Block einen `VectorReceipt`, den Quellvektor und den Ausgabevektor der
Identitaetsprojektion. Im Ariadne-Bild ist das eine Kontrakt- und
Konstrukt-Studie ohne wissenschaftliches Verdikt, ohne Produktionspfad und ohne
Promotion: die Konstanten `CLASSIFICATION` (`EXPERIMENT`), `ACTIVE_GATE` (0) und
`AUTOMATIC_PROMOTIONS` (0) stehen dafuer im Code selbst.

## Module

Gemessen 2026-09-05: 5 `.py`-Dateien mit 3253 Zeilen, davon 3
Implementierungsdateien mit 2124 Zeilen. Die Tests liegen im Paket, nicht unter
`tests/`.

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../experiments/forest_v2/tensor_semantic_composite/__init__.py) | Re-Export der Kontrakte und des Backends; der Docstring nennt das Paket "proposal-only, precomputed-vector". | `CLASSIFICATION`, `ACTIVE_GATE`, `AUTOMATIC_PROMOTIONS`, `PACKET_SPEC_DIGEST` |
| [`contracts.py`](../../../experiments/forest_v2/tensor_semantic_composite/contracts.py) | Strikte, unveraenderliche, stdlib-only Kontrakte: Encoder-Identitaet, Identitaetsprojektion, lueckenloser Blockraum, raumgebundene Vektor-Digests, redigierte Kosten-/Ausfuehrungsquittungen. | `EncoderManifest`, `ProjectionManifest`, `CompositeBlock`, `CompositeSpaceSpec`, `VectorReceipt`, `CompositeVector`, `CompositeReceipt`, `SemanticContractError`, `text_digest`, `vector_digest` |
| [`backend.py`](../../../experiments/forest_v2/tensor_semantic_composite/backend.py) | Der reine Offline-Komponierer: prueft vollstaendiges, vorberechnetes Vektormaterial fail-closed, legt die gewichteten Bloecke in ihre eingefrorenen Offsets und bewertet nur passende Bloecke. | `DirectSumBackend`, `CompositionRequest`, `VectorMaterial`, `ComposedSemanticVector`, `BACKEND_SCHEMA`, `EXECUTION_MODE` |
| [`test_contracts.py`](../../../experiments/forest_v2/tensor_semantic_composite/test_contracts.py) | Adversariale Kontrakttests: kanonische Round-Trips, Digest-Bindung, mehrdeutige Identitaetsfelder, nicht-endliche Zahlen, negatives Null. | — |
| [`test_backend.py`](../../../experiments/forest_v2/tensor_semantic_composite/test_backend.py) | Algebraische Identitaet, Substitutions-/Tower-Swap-/Cross-Space-Refusals, kanonisches Null, Laufzeit-Inertheit. | — |

Nicht-Python im Paket: `EXPERIMENT_SPEC.json` (das eingefrorene Protokoll),
`README.md` und `WORK_PACKET.md`.

### Der Kontraktstapel

`EncoderManifest` bindet eine vollstaendige Encoder-Identitaet: Provider,
Modellname und -revision, getrennte Checkpoint-Digests fuer Query- und
Document-Tower, Tokenizer-Identitaet, Template- und Preprocessing-Digests,
Pooling, Truncation, Ausgabedimension und -normalisierung, Lizenz-SPDX plus
Lizenzevidenz. Die daraus abgeleitete `encoder_id` ist eine Inhaltsadresse; ein
geaendertes Feld ergibt eine andere Identitaet.

`ProjectionManifest` ist in diesem Packet auf `kind == "identity"` beschraenkt.
Gelernte Projektionskoepfe brauchen laut Kontrakt ausdruecklich ein neues Schema
und ein eigenes Work Packet; sie unter dem Identitaetsschema abzubilden ist eine
harte Ablehnung.

`CompositeBlock` verbindet Encoder und Projektion mit `offset`,
`output_dimension` und `amplitude_weight`; `CompositeSpaceSpec` ordnet die
Bloecke lueckenlos und ohne Ueberlappung, bindet `experiment_spec_digest` und
leitet daraus eine `space_id` ab. Die Obergrenzen stehen als Konstanten fest:
`MAX_ENCODERS` 8, `MAX_COMPONENT_DIMENSION` 8192, `MAX_TOTAL_DIMENSION` 16384,
`MAX_TEXT_FIELD_LENGTH` 4096, `UNIT_NORM_TOLERANCE` 1e-6.

`VectorReceipt` ist die **redigierte** Quittung fuer einen extern erzeugten
Blockvektor: sie traegt Quelle, Revision, Eingabe-Digest und -groesse, Rolle,
Tower, Encoder- und Projektions-ID, Digests von Quell- und Ausgabevektor,
Token-Zahl sowie die Digests der Producer-, Ausfuehrungs- und Kostenquittung —
aber nie den Text und nie die Rohwerte. `authority` steht fest auf
`caller_supplied_unverified`, `purpose` auf `retrieval_proposal_only`.
`CompositeVector` und `CompositeReceipt` sind die aggregierten Inhaltsadressen
darueber; beide tragen die Egress-Klassifikation und den Digest der
Egress-Policy-Quittung ihrer Quellen weiter.

### Das Backend

`DirectSumBackend` ist an genau einen `CompositeSpaceSpec` gebunden.
`VectorMaterial` haelt eine `VectorReceipt` zusammen mit den ephemeren Quell-
und Ausgabewerten; `CompositionRequest` buendelt das Material eines Inputs samt
`source_id`, `revision`, `text`, `role`, `tower` und Egress-Bindung und ist
absichtlich nicht serialisierbar.

`compose` verlangt **jeden** geforderten Block; fehlende, zusaetzliche oder aus
einer anderen Quelle stammende Bloecke machen die Komposition ungueltig, und es
gibt kein Fallback-Backend. `compose_request` schickt einen exakt leeren Text an
`canonical_null` — eine leere Rolle wird explizit als kanonisches Null
dargestellt, statt als Fehlen, und praegt dabei keine Encoder-Aufrufe. `score`
revalidiert beide vollstaendigen Inputs, erzwingt die Tower-Reihenfolge
(Query gegen Document) und summiert danach die Blockprodukte;
Cross-Space-Scoring ist verboten.

`weighted_score_fusion` ist die vorregistrierte algebraische Null zu `score`:
dieselbe gewichtete Fusion, aus fertigen Blockprodukten berechnet. Der
Work-Packet-Text ist an dieser Stelle deutlich — Direct Sum gegen gewichtete
Score-Fusion ist ein **Null- beziehungsweise Bug-Test**, keine Wirkbehauptung;
eine Abweichung oberhalb 1e-10 invalidiert die Implementierung.

`ROLES` sind `path`, `symbol`, `content`, `neighbor`; `TOWERS` sind `query` und
`document`; `EGRESS_CLASSIFICATIONS` sind `local_only`, `trusted_only`,
`untrusted_allowed`.

## Trust-Grenzen / Effekte

- Kein Writer, kein Netzwerk, kein Dateizugriff, kein Modellclient. Die
  Kontrakte sind laut Docstring "deliberately inert and stdlib-only" und
  verleihen keine Beweiskraft: jeder Vektor bleibt ein Retrieval-Vorschlag aus
  vom Aufrufer geliefertem, ungepruefetem Material.
- Die einzige externe Abhaengigkeit ist das Schwester-Experiment
  [`tensor_embeddings`](../../../experiments/forest_v2/tensor_embeddings/contracts.py)
  fuer `canonical_digest` und `canonical_json_bytes`. Nichts unter `daedalus/`
  importiert dieses Paket (gemessen 2026-09-05 per `grep -rln` ueber
  `daedalus/`, `tests/`, `experiments/`).
- Egress ist eine **vererbte** Eigenschaft: ein zusammengesetzter Vektor, der
  seine Egress-Bindung verliert, wird in `ComposedSemanticVector` abgelehnt.
- `PACKET_SPEC_DIGEST` bindet den kanonischen Digest von
  `EXPERIMENT_SPEC.json`. Ein `CompositeSpaceSpec` muss genau diesen Digest
  binden; ein geaendertes Protokoll kann die alte `space_id` nicht still
  weiterverwenden.
- Plan-Bezug: Invariante 3 (Isolation), 4 (Evidenzgrenze) und 5 (versiegelte
  Promotion) bleiben unberuehrt, weil das Paket weder Evaluator noch Policy noch
  Promotionspfad anfasst. Siehe [Kernel-Contracts](../architecture/kernel-contracts.md).

## Tests

Im Paket selbst (gemessen 2026-09-05; unter `tests/` referenziert nichts dieses
Verzeichnis):

- [`test_contracts.py`](../../../experiments/forest_v2/tensor_semantic_composite/test_contracts.py)
- [`test_backend.py`](../../../experiments/forest_v2/tensor_semantic_composite/test_backend.py)

Aufruf laut README:
`python -B -m pytest experiments/forest_v2/tensor_semantic_composite -q`.
Es wird kein reales Modell geladen; die Testvektoren sind kleine synthetische
Fixtures im Prozess. `test_backend.py` enthaelt ausserdem einen
Laufzeit-Grenztest, der prueft, dass die Module inert bleiben und keine
Autoritaets-API exportieren.

## Verwandt

- [Tensor-Embeddings (s-Slice)](forest-v2-tensor-embeddings.md) — Packet 001,
  das Konstrukt, auf dem dieses Packet aufsetzt.
- [Tensor-Embedding-Arme](tensor-embedding.md) — die messenden Arme derselben
  Hypothesenfamilie.
- [Forest v2](forest-v2.md) — der Slice-Rahmen.
- [s07 BM25](forest-v2-s07-bm25.md) und [s11 Fusion](forest-v2-s11-fusion.md) —
  die lexikalische Baseline und die Fusionsseite, gegen die ein semantischer
  Raum irgendwann antreten muss.
- [Kernel-Contracts](../architecture/kernel-contracts.md),
  [Wiki-Index](../index.md), [Typgraph](../architecture/type-graph.md).

## Ungeklaert

- **Ungeklaert:** ob dieses Packet je mit echten Encoder-Vektoren gefahren
  wurde. Im Baum finden sich nur synthetische Fixtures in den beiden Testdateien;
  der README nennt ausdruecklich "no scientific verdict".
- **Ungeklaert:** wer der berechtigte Aufrufer waere, der die Encoder ausserhalb
  des Pakets ausfuehrt und die `VectorReceipt`-Objekte erzeugt — im Baum gibt es
  keinen solchen Produzenten.
- **Ungeklaert:** der `README.md` von `experiments/forest_v2` erwaehnt diesen
  Unterordner nicht; das Packet dokumentiert sich ausschliesslich in seinem
  eigenen `README.md` und `WORK_PACKET.md`.
- **Ungeklaert:** was nach dem im Work Packet genannten Verfall (2026-10-31) mit
  dem Verzeichnis geschehen soll; ein mechanischer Ablaufcheck war nicht
  auffindbar.

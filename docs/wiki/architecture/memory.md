---
title: Memory
type: module
status: living
updated: 2026-09-05
covers: daedalus/memory
---
# Memory

`daedalus/memory` ist das Produktgedaechtnis: ein append-only-Ereignisjournal
plus eine daraus abgeleitete, versionierte Vektorprojektion. Im Masterplan-Bild
gehoert es zu Ikarus (Abschnitt 7: "Product memory ... and research adaptive
memory are separate, versioned, provenance-bearing stores"), nicht zu Ariadne
und nicht zum Effekt-Ledger des Kernels. Die Trennung ist eine harte Grenze aus
`AGENTS.md`: Produktgedaechtnis und Ariadne-Adaptivgedaechtnis teilen keinen
Speicher. Das Intent-Ledger unter [Kernel-Events](kernel-events.md) ist
seinerseits ein anderes Ding -- dort steht, was *getan* werden sollte, hier,
was *gelernt* wurde.

Die Rollenverteilung ist explizit: **das Journal
(`memory/events.local.jsonl`) ist autoritativ, der Vektorindex ist abgeleitet.**
Nichts im operativen Append-Pfad darf auf einen Embedding-Call warten.

Gemessen 2026-09-05: 4 `.py`-Dateien, 3413 Zeilen -- zwei davon
(`embeddings.py`, `projection_worker.py`) tragen 3078.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/memory/__init__.py) | Der Append-Pfad und die CLI. `ROOT` zeigt bewusst auf `parents[2]`, damit der Betriebszustand im Repo-Verzeichnis `memory/` landet und nicht in `daedalus/memory/` -- ein frueherer Fehler, der im Kommentar festgehalten ist. `_try_vector_index` ist der best-effort-Anschluss an die Projektion. | `MemoryEvent`, `append_event`, `load_events`, `refresh_todo_snapshot`, `projection_event_from_record`, `record_from_bridge_report`, `main`, `ROOT`, `MEMORY_DIR`, `EVENTS_PATH`, `TODO_PATH`, `VECTOR_DB_PATH` |
| [`__main__.py`](../../../daedalus/memory/__main__.py) | Sieben Zeilen: der Einstiegspunkt fuer `python -m daedalus.memory`, delegiert an `main`. | -- |
| [`embeddings.py`](../../../daedalus/memory/embeddings.py) | Der versionierte Vektorstore auf SQLite plus der Ollama-Embedding-Transport. Jeder Vektor gehoert zu einer `EmbeddingSpec`; ein anderes Modell, eine andere Dimension, eine andere Normalisierung, eine andere Modellrevision oder eine andere Projektorversion ergibt eine andere `index_id`. | `EventVectorStore`, `EmbeddingSpec`, `AgentEvent`, `JournalPosition`, `ProjectionFilter`, `IngestReport`, `SearchReport`, `IndexStatus`, `OperationStatus`, `EmbeddingBackend`, `OllamaEmbeddingBackend`, `EmbeddingError`, `EmbeddingUnavailableError`, `EmbeddingProtocolError`, `EmbeddingEgressRefused`, `index_identity` |
| [`projection_worker.py`](../../../daedalus/memory/projection_worker.py) | Der einzige Komponent, der den Index vorwaerts bewegen soll -- und deshalb auch der Besitzer von `record_journal_watermark`. Resumierbar per Byte-Offset, idempotent, faellt bei Crash immer *hinter* den Stand zurueck, nie davor. | `ProjectionWorker`, `WorkerReport`, `ProjectionWorkerError`, `SpecConflictError`, `JournalEntry`, `resolve_spec`, `scan_journal`, `journal_position`, `complete_prefix_end`, `main` |

## Was der Code tatsaechlich garantiert

Die Docstrings der beiden grossen Module listen ihre Zusagen als *durchgesetzt*,
nicht als beabsichtigt. Die wichtigsten:

**Egress wird vor dem Socket entschieden.** `OllamaEmbeddingBackend.embed` legt
die Host-Admission (`ollama_endpoint_admission` aus
[Providers](providers.md)) und den kanonischen Effektstart
`begin_effect` (Registry-Zeile `memory.embeddings`) *vor* den Bau des
Request-Objekts. Ein abgelehnter Host kostet null Verbindungen; die Ablehnung
kommt als `EmbeddingEgressRefused` mit inhaltsadressierter Deny-Quittung, die
Host, Lane und den ablehnenden Vertrag benennt.

**Der Endpunkt ist an den Index gebunden.** `embedding_indexes` merkt sich den
`egress_host`, der den Index zuerst geschrieben hat. Ein spaeterer Ingest oder
eine Suche ueber einen *anderen* Endpunkt wird mit `host_drift` verweigert,
bevor eine Projektion geschrieben oder bewertet wird -- zwei Endpunkte sind kein
gemeinsames Koordinatensystem, unabhaengig davon, worauf sie re-embedden.

**Eine Suche, ein Index.** `search_report` loest genau eine `index_id` auf und
filtert darauf. Eine nie geschriebene Spec liefert `index_unavailable` statt
still auf einen anderen Index auszuweichen.

**Dimensionen werden dreimal geprueft** -- beim Ingest, beim Lesen und beim
Scoring. Kein Broadcast, kein Truncate, kein Zero-Padding; eine
Breitenabweichung erscheint als `invalid_index`.

**Der Watermark ist nie voraus.** Der Fortschritt des Workers ist ein
Byte-Offset ins Journal, gespeichert als `JournalPosition` im Index selbst. Er
wird erst nach dem Commit aller Projektionen unterhalb dieses Offsets
geschrieben. Ein abgebrochener Lauf hinterlaesst also einen zu *niedrigen*
Watermark; der naechste Lauf liest die Eintraege erneut, findet sie bereits
projiziert und schiebt den Watermark hoch. Der umgekehrte Fall wuerde
Journaleintraege dauerhaft verlieren und wird deshalb nie geschrieben.

**Append-only wird geprueft, nicht angenommen.** Der `content_hash` des
Watermarks ist der SHA-256 des Journal-Praefix `[0, position)` und wird bei
jedem Lauf neu gebildet. Ein umgeschriebenes, abgeschnittenes oder ersetztes
Journal faellt mit `journal_forked` durch, statt eine nicht mehr passende
Historie weiterzuprojizieren. `complete_prefix_end` sorgt zusaetzlich dafuer,
dass eine angefangene Zeile ohne Zeilenumbruch als Schreiber-in-Arbeit gilt und
nicht als Datensatz.

**Idempotenz doppelt.** Der Index ist inhaltsadressiert
(`UNIQUE(index_id, source_hash)` mit `INSERT OR IGNORE`) -- das ist die
Korrektheitsgarantie. Zusaetzlich filtert der Worker bereits vorhandene
`source_hash`-Werte vor dem Embedden -- das ist nur eine Optimierung.

**Ausfall wird gemeldet, nicht geglaettet.** `embedder_unavailable` stoppt den
Lauf, behaelt den erreichten Watermark und endet mit Exit-Code ungleich null.
`model_drift` ist ein Korrektheitsfehler, den ein Retry nicht heilt: der Store
verweigert *vor* dem Schreiben, und der Worker faengt diese Verweigerung nicht
ab.

## Trust-Grenzen / Effekte

| Grenze | Ort |
| --- | --- |
| Egress-Tuer | `_authorize_egress` in `embeddings.py`, aufgerufen aus `OllamaEmbeddingBackend.embed`. Registry-Zeile `memory.embeddings`, `Wiring.CENTRAL`, Effekt `NETWORK_EGRESS`, Guard-Contract `provider.egress_policy`. Zwei `GuardAnchor` pinnen beide Haelften: `embed` muss den Guard rufen, der Guard muss `begin_effect` starten. |
| Lauf-Start | `main` in `projection_worker.py`. Registry-Zeile `cli.project_memory`, `Wiring.CENTRAL`, Effekte `FILESYSTEM_WRITE` und `NETWORK_EGRESS`, Guard-Contract `budget.process_guard`. Die Grenze liegt bewusst *ueber* dem `--dry-run`-Flag: ein Start, der nur auf manchen Argumentvektoren bewacht ist, ist vom Aufrufer bewacht, nicht von der Funktion. |
| Schreiber | `EventVectorStore.__init__` legt das Elternverzeichnis an und oeffnet die SQLite-Datei (`VECTOR_DB_PATH`, also `memory/vectors.db`) lese/schreibbar; `record_journal_watermark`, `ingest_events` und `_store_batch` schreiben. `append_event` in `__init__.py` haengt an `EVENTS_PATH` an, `refresh_todo_snapshot` schreibt `TODO_PATH`. |
| Read-only | `load_events`, `search`, `search_report`, `list_indexes`, `index_status`, `journal_watermark`, `journal_freshness`, `anchor_provenance`, `verify_index_identity`, `scan_journal`, `journal_position`, `complete_prefix_end`. `_ro_connect` im Worker oeffnet den Index ausdruecklich lesend. |

Der Vektorindex ist eine *Projektion*, kein Event-Log. Er trifft keine
Entscheidung, gewaehrt kein Vertrauen und hat keinen Promotionspfad. Das ist
die Twin-Analogie von [Twin](twin.md): Embeddings schlagen vor, unabhaengige
Evidenz entscheidet (Masterplan-Invariante 4).

## Tests

Gemessen 2026-09-05:

- [`test_embeddings.py`](../../../tests/test_embeddings.py) -- Vektorstore,
  Spec-Identitaet, Dimensions- und Index-Regeln.
- [`test_memory_embeddings_egress.py`](../../../tests/test_memory_embeddings_egress.py)
  -- Egress-Admission vor dem Socket, Deny-Quittung.
- [`test_projection_worker.py`](../../../tests/test_projection_worker.py) --
  Watermark, Resume, `journal_forked`, Idempotenz.
- [`test_journal_append_concurrency.py`](../../../tests/test_journal_append_concurrency.py)
  -- gleichzeitige Anhaenge ans Journal.
- [`test_latent_index_integrity.py`](../../../tests/test_latent_index_integrity.py)
  -- Identitaetsanker des Index.
- [`test_context_plan.py`](../../../tests/test_context_plan.py),
  [`test_context_plan_latent.py`](../../../tests/test_context_plan_latent.py)
  -- Nutzung der Projektion in der Kontextplanung.
- [`test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py),
  [`test_token_monitor_write_roots.py`](../../../tests/test_token_monitor_write_roots.py),
  [`test_cli_token_verb.py`](../../../tests/test_cli_token_verb.py),
  [`test_health_surface.py`](../../../tests/test_health_surface.py),
  [`test_agent_env.py`](../../../tests/test_agent_env.py)
  -- Registry-Zeilen, Schreibwurzeln und Oberflaechen, die Memory beruehren.

## Verwandt

- [Kernel-Events](kernel-events.md) -- das *andere* append-only-Log; Intents
  statt Erinnerungen, und mit ganz anderem Vertrag.
- [Spine](spine.md) -- `begin_effect`, die Registry-Zeilen `memory.embeddings`
  und `cli.project_memory`.
- [Providers](providers.md) -- `ollama_endpoint_admission`, der die
  Host-Entscheidung faellt.
- [Twin](twin.md) -- Node Cards und die vier Ebenen, auf die ein spaeterer
  Latent Atlas aufsetzen wuerde (Masterplan Abschnitt 6).
- [Ariadne](ariadne.md) -- das ausdruecklich *getrennte* Adaptivgedaechtnis.
- [Agents hold no state](../decisions/agents-hold-no-state.md) -- warum das
  Journal und nicht der Agent der Traeger ist.
- [Knowledge layer](knowledge-layer.md), [Feature backlog](../feature-backlog.md),
  [Wiki-Index](../index.md).

## Ungeklaert

- **Ungeklaert:** ob `_try_vector_index` im Append-Pfad heute noch aktiv ist
  oder nur historisch. Der Docstring von `projection_worker.py` sagt, der Worker
  sei "the *only* component that is supposed to move the index forward";
  `_try_vector_index` in [`__init__.py:124`](../../../daedalus/memory/__init__.py)
  schreibt aber ebenfalls in den Index. Das ist die auffaelligste Spannung
  zwischen Doku und Code in diesem Verzeichnis -- moeglicherweise aufgeloest
  dadurch, dass `_try_vector_index` best-effort und fehlertolerant ist, aber der
  Code sagt es nicht.
- **Ungeklaert:** welche Backends ausser `OllamaEmbeddingBackend` das
  `EmbeddingBackend`-Protokoll implementieren. Im Verzeichnis ist es das
  einzige.
- **Ungeklaert:** ob `ingest_transport_records` und
  `ingest_transport_records_report` noch Aufrufer haben; sie tauchen im
  Worker-Pfad nicht auf.
- **Ungeklaert:** ob `legacy_unversioned_count` noch etwas zaehlen kann oder ein
  Migrationsrest ist.

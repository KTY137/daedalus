---
title: Kernel-Events
type: module
status: living
updated: 2026-09-05
covers: daedalus/kernel/events
---
# Kernel-Events

`daedalus/kernel/events` besitzt den kanonischen Event-Spine des Daedalus-
Kernels: die Korrelations- und Statement-Huellen, das dauerhafte Intent-Ledger
und das Gate-0-Durability-Profil dieses Ledgers. Masterplan-Invariante 1 ("One
kernel") verlangt genau *einen* Event-Spine; dieses Paket ist er. Der
historische Locator [`daedalus.spine`](spine.md) bleibt als Fassade bestehen --
seine `ledger.py`, `envelope.py` und `durability.py` ersetzen sich in
`sys.modules` durch die Module hier, damit alte Monkeypatches und private Namen
weiter funktionieren.

Gemessen 2026-09-05: 4 `.py`-Dateien, 2231 Zeilen. Das Paket ist bewusst lazy --
`__getattr__` in `__init__.py` importiert `envelope` ohne die SQLite-Maschinerie
mitzuziehen.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/kernel/events/__init__.py) | Lazy Owner-Paket. `_SUBMODULES` erlaubt `durability`, `envelope`, `ledger`; `_EXPORTS` bildet jeden oeffentlichen Namen auf sein Submodul ab, `__all__` ist daraus abgeleitet. | `__getattr__`, `__dir__`, `__all__` |
| [`envelope.py`](../../../daedalus/kernel/events/envelope.py) | Ein Korrelationsfeld (`trace_id`) und die in-toto-ITE-6-Statement-Form. Fuegt ein Feld hinzu und benennt nichts um: die sechs bestehenden lokalen ID-Schemata behalten ihre Bedeutung. | `canonical_json`, `canonical_sha`, `new_trace_id`, `current_trace_id`, `bind_trace_id`, `trace_context`, `adopt_trace`, `stamp`, `subject_for`, `statement`, `is_statement`, `unwrap`, `trace_of`, `TRACE_KEY`, `TRACE_ID_ENV`, `IN_TOTO_STATEMENT_TYPE`, `PREDICATE_SPINE_INTENT`, `PREDICATE_LOOP_LEDGER`, `PREDICATE_BRIDGE_REQUEST`, `PREDICATE_BRIDGE_REPORT`, `GEN_AI`, `gen_ai_attributes`, `LOCAL_TO_GEN_AI`, `CONVERTED_PRODUCERS`, `UNCONVERTED_PRODUCERS` |
| [`ledger.py`](../../../daedalus/kernel/events/ledger.py) | Das dauerhafte Intent-Ledger auf SQLite. Kein Missions-Zustandsautomat, keine Leases, keine Heartbeats -- nur crash-sichere Intent-vor-Effekt-Aufzeichnung. | `SpineLedger`, `Intent`, `IntentEvent`, `SpineError`, `UnknownIntent`, `IntentAlreadyResolved`, `SCHEMA_VERSION`, `STATE_INTENDED`, `STATE_COMPLETED`, `STATE_FAILED`, `TERMINAL_STATES`, `DEFAULT_DB_PATH`, `DEFAULT_BUSY_TIMEOUT_MS`, `default_db_path` |
| [`durability.py`](../../../daedalus/kernel/events/durability.py) | Haertet genau die bestehende schreibbare Ledger-Verbindung auf das Gate-0-Profil und liest die Einstellungen aus SQLite zurueck. Fuehrt kein zweites Ledger ein. | `Gate0DurabilityStatus`, `Gate0DurabilityError`, `inspect_gate0_durability`, `enforce_gate0_durability`, `open_gate0_spine_writer` |

## Der Ledger-Vertrag

**Intent vor Effekt.** `SpineLedger.record_intent` schreibt eine
`INTENDED`-Zeile und committet sie, *bevor* der Aufrufer den externen Effekt
ausfuehrt. Damit kann das Ledger nie hinter der Realitaet zurueckliegen: jeder
Effekt, der passiert ist, hat eine Zeile.

**Das Crash-Fenster schliesst die Identifikation, nicht der Schluessel.** Das
Ledger kann der Realitaet *voraus* sein -- ein Crash nach dem Effekt und vor
`mark_completed` hinterlaesst eine `INTENDED`-Zeile fuer einen bereits
geschehenen Effekt. Dagegen hilft nur ein `effect_key`, den der Aufrufer
hinterher in der Welt *suchen* kann (ein Patch-SHA256, ein Commit-Trailer, ein
Worktree-Branch). `open_intents` liefert die offenen Zeilen beim Start,
`resolve_by_effect` ist die Ledger-Haelfte des Handshakes. Der Schluessel
liefert keine Idempotenz -- wer seinen Effekt nachher nicht identifizieren kann,
bekommt hier keine Crash-Sicherheit.

**Append-only im Geist.** `intents`-Zeilen werden einmal geschrieben und nie
per UPDATE geaendert; jeder Zustandsuebergang haengt eine Zeile an
`intent_events` an, der aktuelle Zustand wird aus dem letzten Event abgeleitet.
Es gibt kein UPDATE-Statement im Modul. Das Schema (`SCHEMA_VERSION` = 2,
gemessen 2026-09-05) besteht aus `spine_meta`, `intents` und `intent_events`
plus vier Indizes (Effect-Key, Intent, Terminal-Event, Trace).

**Doppelte Aufloesung wird abgelehnt, nicht absorbiert.** `mark_completed` und
`mark_failed` auf einem bereits terminalen Intent werfen
`IntentAlreadyResolved`. Stille Idempotenz waere hier schlechter: eine zweite
Completion mit *anderer* `effect_id` bedeutet, dass der Aufrufer etwas glaubt,
was das Ledger nicht glaubt. Die Pruefung laeuft in derselben
`BEGIN IMMEDIATE`-Transaktion wie das Anhaengen und ist damit nicht rennbar.

**Weitere Leser.** `get`, `events`, `recent_intents`, `intents_matching_payload`,
`intents_by_effect_key`, `effect_key_groups`, `ordinal_by_effect` und
`intents_for_trace` sind lesende Abfragen; `record_fact` schreibt einen bereits
terminalen Datensatz (etwas, das schon geschehen ist).

## Envelope: ein Feld, kein Umbau

`new_trace_id` mintet genau eine Korrelations-ID pro Lauf. Sie wird *ambient*
propagiert -- ueber eine `contextvars`-Variable plus `TRACE_ID_ENV`
(`DAEDALUS_TRACE_ID`) in der Umgebung, damit ein Kindprozess sie erbt. Ambient
statt Parameter, weil die zu stempelnden Produzenten aus Modulen aufgerufen
werden, die diese Aenderung nicht anfassen durfte. Ohne laufenden Trace gibt
`current_trace_id` `None` zurueck und das Feld entfaellt -- ein ungetracter
Datensatz ist byte-identisch zu vorher.

`statement` baut die in-toto-ITE-6-Form (`_type`, `subject`, `predicateType`,
`predicate`) mit `IN_TOTO_STATEMENT_TYPE` als `_type` und den vier lokalen
Praedikat-URIs (`PREDICATE_SPINE_INTENT`, `PREDICATE_LOOP_LEDGER`,
`PREDICATE_BRIDGE_REQUEST`, `PREDICATE_BRIDGE_REPORT`). `subject_for` erzeugt das
Subjekt mit Digest, `is_statement`/`unwrap`/`trace_of` lesen zurueck.
`Intent.to_statement` ist die Anwendung im Ledger.

> **Extern:** Die in-toto-Attestation-Statement-Form v1 und die OpenTelemetry-
> GenAI-Semantic-Conventions sind externe Spezifikationen. Der `GEN_AI`-Block in
> `envelope.py` uebernimmt bewusst nur die *Schreibweisen* der Attributnamen,
> importiert kein OpenTelemetry-SDK und beansprucht keine Konformitaet -- mit der
> im Docstring genannten Begruendung, dass die GenAI-Konventionen zum
> Messzeitpunkt kein stabiles, getaggtes Release hatten. `latency_ms` und
> `cost_usd` bleiben absichtlich lokale Namen, weil es dafuer keine stabilen
> Attribute gibt.
> Quelle: https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md
> Quelle: https://opentelemetry.io/docs/specs/semconv/gen-ai/

`gen_ai_attributes` benennt ein lokales `meta`-Dict ueber `LOCAL_TO_GEN_AI` um.
`CONVERTED_PRODUCERS` und `UNCONVERTED_PRODUCERS` halten fest, welche
Produzenten im Baum die Umbenennung schon anwenden und welche nicht.

## Trust-Grenzen / Effekte

- **Der einzige Writer.** `SpineLedger.__init__` oeffnet die SQLite-Datei
  (`DEFAULT_DB_PATH` = `runs/spine/spine.sqlite3`). Welche Aufrufstellen im
  Produktionsbaum einen Writer konstruieren, inventarisiert
  `scan_event_store_writers` aus [Spine](spine.md); das Inventar ist
  syntaxbasiert und fail-closed.
- **Durability-Profil.** `enforce_gate0_durability` verlangt
  `journal_mode=wal`, `synchronous=FULL` (2) und `foreign_keys=1` und liest die
  Werte per PRAGMA zurueck; `inspect_gate0_durability` liest nur.
  `open_gate0_spine_writer` ist die Fabrik, die einen Produktions-Writer in
  `synchronous=FULL` bringt, *bevor* die generische Schema-Migration laeuft.
  Der Default des Ledgers selbst ist `synchronous=NORMAL` -- die WAL-Paarung,
  die Prozess-Crashes ueberlebt, aber bei Stromausfall die letzten Commits
  verlieren kann.
- **`envelope.py` hat keine Effekte.** Es liest hoechstens `TRACE_ID_ENV` und
  setzt es in einem Scope; keine Datei, kein Socket, keine Datenbank.
- **Kein Promotionspfad.** Das Ledger zeichnet Entscheidungen auf; es trifft
  keine. Promotion bleibt beim versiegelten Owner-Pfad (Masterplan Invariante
  5), siehe [Gates-Repository](gates-repository.md).

## Tests

Gemessen 2026-09-05:

- [`test_spine_ledger.py`](../../../tests/test_spine_ledger.py) -- Ledger-
  Lebenszyklus, Intent-vor-Effekt, doppelte Aufloesung.
- [`test_spine_ledger_failed_open_lifetime.py`](../../../tests/kernel/test_spine_ledger_failed_open_lifetime.py)
  -- Verhalten bei fehlgeschlagenem Oeffnen.
- [`test_spine_gate0_durability.py`](../../../tests/test_spine_gate0_durability.py),
  [`test_spine_gate0_durability_review.py`](../../../tests/test_spine_gate0_durability_review.py),
  [`test_spine_gate0_writer_factory.py`](../../../tests/test_spine_gate0_writer_factory.py),
  [`test_spine_gate0_writer_factory_review.py`](../../../tests/test_spine_gate0_writer_factory_review.py)
  -- Durability-Profil und Writer-Fabrik.
- [`test_envelope_join.py`](../../../tests/test_envelope_join.py),
  [`test_envelope_coverage.py`](../../../tests/test_envelope_coverage.py)
  -- Trace-Propagation und Produzenten-Abdeckung.
- [`test_event_hierarchy.py`](../../../tests/kernel/test_event_hierarchy.py),
  [`test_kernel_lazy_facade.py`](../../../tests/kernel/test_kernel_lazy_facade.py),
  [`test_registry_facade_order.py`](../../../tests/test_registry_facade_order.py)
  -- Besitzverhaeltnis Owner-Paket gegen Fassade, Lazy-Import, stabile
  `__all__`-Reihenfolge.
- [`test_budget_ledger_hierarchy.py`](../../../tests/kernel/test_budget_ledger_hierarchy.py),
  [`test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py)
  -- Abgrenzung gegen das Budget-Ledger und die Effect-Registry.

## Verwandt

- [Spine](spine.md) -- die historische Fassade und die Effekt-/Prozessgrenze,
  die dieses Ledger benutzt.
- [Kernel](kernel.md), [Kernel-Contracts](kernel-contracts.md) -- der Rest des
  kanonischen Vertragssatzes.
- [Memory](memory.md) -- der zweite append-only-Journal-Pfad im Baum, bewusst
  getrennt vom Intent-Ledger (Produktgedaechtnis statt Effekt-Buchfuehrung).
- [Observation layer](observation-layer.md) -- Form eines Objekts, nie sein
  Wert; verwandte Trennung von Beobachtung und Autoritaet.
- [Agents hold no state](../decisions/agents-hold-no-state.md) -- warum der
  Zustand im Ledger und nicht im Agenten liegt.
- [Wiki-Index](../index.md).

## Ungeklaert

- **Ungeklaert:** ob `CONVERTED_PRODUCERS` und `UNCONVERTED_PRODUCERS` heute noch
  vollstaendig sind; die Listen sind handgepflegt und ein Test wurde nicht
  gelesen, der sie gegen den Baum prueft.
- **Ungeklaert:** ob `ROOT` (nur ueber `_EXPORTS` des Pakets exportiert, nicht in
  `daedalus.spine.__all__`) noch aktive Aufrufer hat.
- **Abweichung Code/Doku:** Der Modul-Docstring von
  [`ledger.py:1`](../../../daedalus/kernel/events/ledger.py) beginnt mit
  `kernel/events/ledger.py -- ...`, beschreibt aber durchgehend "die
  Selbstverbesserungs-Schleife" als einzigen Nutzer. Tatsaechlich ist
  `SpineLedger` inzwischen Ledger fuer Computer-Assistant-, Genesis- und
  Provider-Pfade (siehe die Guard-Contract-Zeile `spine.intent_ledger` in der
  Effect-Registry). Der Docstring ist enger als der Code.

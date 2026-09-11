---
title: Interfaces bridge
type: module
status: living
updated: 2026-09-05
covers: daedalus/interfaces/bridge
---
# Interfaces bridge

`daedalus/interfaces/bridge` ist der Implementierungs-Eigentuemer der File Bridge:
eines dateibasierten Auftragswegs zwischen Agenten (Outbox-Request -> Watcher ->
Inbox-Report). Die registrierte Effektfassade bleibt das Altmodul
[`daedalus/file_bridge.py`](../../../daedalus/file_bridge.py); die sieben Module
hier besitzen die deterministische Logik dahinter und bekommen jede
Umgebungsautoritaet — Pfad, Uhr, Zufall, Sperre, Publisher, Ausnahmetypen — als
expliziten Port uebergeben. Genau das ist der Punkt der Aufteilung: wer einen
Eigentuemer importiert, kann keinen zweiten Event-, Retry-, Effekt- oder
Persistenz-Autoritaet erzeugen. Im Ikarus/Ariadne-Bild ist das eine
Ikarus-Schnittstelle, kein Orchestrierungszustand — Chat und Dateiverkehr sind
Interface, die Wahrheit liegt im Kernel (Plan §7).

Gemessen 2026-09-05: 8 `.py`-Dateien, 2614 Zeilen; `dispatch.py` traegt 734,
`projection.py` 598.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/interfaces/bridge/__init__.py) | Importiert die sieben Eigentuemer als Untermodule; kein eigener Code. | `cli`, `conversation`, `dispatch`, `journal`, `projection`, `queue`, `watcher` |
| [`queue.py`](../../../daedalus/interfaces/bridge/queue.py) | Request-Normalisierung, kollisionsfreie Benennung, atomare Veroeffentlichung, und die Verbraucher-Lebendigkeitspruefung *vor* der Veroeffentlichung. | `WatcherNotRunning`, `admit_enqueue`, `publish_request`, `read_request`, `codex_inline_brief_warning`, `ClockPort`, `TraceStampPort`, `UniqueHexPort`, `WriteTextPort` |
| [`journal.py`](../../../daedalus/interfaces/bridge/journal.py) | Request-Identitaeten und das kleine durable Crash-Journal hinter der Fassade. | `request_key`, `request_sha256`, `raw_request_sha256`, `report_request_binding`, `effect_identity_for`, `journal_dir`, `journal_path`, `request_lock_path`, `mission_projection_dir`, `read_journal`, `write_journal`, `write_json_atomic`, `completed_report`, `crash_journal_state` |
| [`dispatch.py`](../../../daedalus/interfaces/bridge/dispatch.py) | Der crash-sichere Zustandsautomat eines geclaimten Requests: OS-Claim, Identitaetspruefung, Quarantaene, Archivierung, terminale Buchhaltung. | `claim_and_dispatch_request`, `process_claimed_request`, `RequestIdentityConflict`, `TerminalReportPreserved`, `QuarantineMovePending`, `TerminalBookkeepingPending`, `quarantine_request`, `quarantine_request_identity_conflict`, `move_quarantined_request`, `archive_request_once`, `finish_terminal_report`, `memory_already_recorded`, `ClaimedDispatchPorts`, `IdentityConflictPorts`, `QuarantinePorts`, `TerminalBookkeepingPorts` |
| [`watcher.py`](../../../daedalus/interfaces/bridge/watcher.py) | OS-Claim des Watchers, Heartbeat-Projektion und die Polling-Schleife inklusive Poison-Behandlung. | `watch_loop`, `WatcherOwnershipBusy`, `PoisonHandlingPorts`, `write_heartbeat`, `heartbeat_status`, `restart_hint`, `watcher_lock_path`, `current_process_identity`, `looks_unfinished`, `handle_poison_request` |
| [`conversation.py`](../../../daedalus/interfaces/bridge/conversation.py) | Projektion eines terminalen Reports auf den kanonischen Conversation-Store, mit Unterscheidung transient/dauerhaft. | `project_report`, `ConversationProjectionPending`, `ConversationProjectionFailed`, `is_transient_projection_failure`, `prepare_reconciliation`, `finish_reconciliation`, `requeue_for_projection` |
| [`projection.py`](../../../daedalus/interfaces/bridge/projection.py) | Lesezustand (`.seen`), Statusprojektionen, und die Rekonstruktion der Anwendungs-Wahrheit aus zurueckbehaltener Schreib-Evidenz. | `seen_dir`, `latest_log`, `note_report_arrival`, `reported_result`, `report_application_truth`, `conversation_report_fields`, `unread_reports`, `mark_read`, `quarantined_requests`, `report_brief`, `project_report_briefs`, `bridge_status`, `stream_state` |
| [`cli.py`](../../../daedalus/interfaces/bridge/cli.py) | Parser, Dispatch und Textprojektion der Fassaden-CLI (`watch`, `enqueue`, `once`, `status`, `mark-read`). | `build_parser`, `dispatch`, `print_status`, `BridgeCliPorts` |

### Der Weg eines Requests

1. **Enqueue.** `admit_enqueue` faellt *vor* der Veroeffentlichung geschlossen aus,
   wenn kein Verbraucher lebt: bei Heartbeat-Zustand `stale` oder `none` wirft es
   `WatcherNotRunning` (ausser der Aufrufer setzt `--force`), bei `wedged` warnt es
   mit dem laufenden Task und dem ueberschrittenen Busy-Budget. `publish_request`
   baut daraus einen kollisionsfreien Dateinamen aus Zeitstempel, Objective-Slug
   (48 Zeichen) und acht Hex-Zeichen und schreibt das Dokument atomar.
2. **Claim.** `claim_and_dispatch_request` sperrt ueber den vom Dateinamen
   abgeleiteten Schluessel prozessuebergreifend. Ist die Quelldatei nach dem
   Warten weg, aber ein vollstaendiger Report da, gewinnt der Report — das ist die
   Crash-Race-Aufloesung, die der Modul-Docstring nennt.
3. **Identitaet.** `process_claimed_request` vergleicht `request_sha256` gegen
   Journal *und* gegen die im Report gebundene Identitaet. Ein wiederverwendeter
   Dateiname mit anderen kanonischen Bytes ist `RequestIdentityConflict`: das alte
   Journal und der alte Report bleiben unangetastet, nur die neue widersprechende
   Datei wandert in eine digest-suffigierte Quarantaene.
4. **Zustandsautomat.** Journal-Zustaende sind u. a. `new`, `quarantine_pending`,
   `quarantine_move_pending`, `quarantined`, `bookkeeping_pending`,
   `projection_failed`, `done_with_projection_error`. Jeder wird beim naechsten
   Durchlauf idempotent fortgesetzt statt neu begonnen.
5. **Report und Projektion.** `finish_terminal_report` archiviert genau einmal;
   `conversation.project_report` schreibt das Ergebnis auf den kanonischen Spine.
6. **Lesen.** `unread_reports`/`mark_read` fuehren den Lesezustand in
   `inbox/.seen/`, `bridge_status` und `stream_state` liefern die Projektionen fuer
   CLI, HTTP-SSE und Desktop.

### Fehler, die kein Fehler sind

`ConversationProjectionPending` ist ausdruecklich *kein* Poison-Input und darf laut
Docstring weder Quarantaene noch einen weiteren Provider-Call ausloesen: der Report
bleibt die autoritative terminale Tatsache, und der Request unarchiviert zu lassen
sorgt dafuer, dass der Watcher beim naechsten Durchgang nur die idempotente
Spine-Projektion wiederholt. `is_transient_projection_failure` entscheidet das
anhand einer expliziten Errno-Menge (`EAGAIN`, `EBUSY`, `EINTR`, `ETIMEDOUT`, und
`ESTALE` wo vorhanden). Dieselbe Trennung fuehrt `watch_loop`: Ausnahmen aus
`pending_exceptions` werden nur protokolliert, alles andere geht an
`handle_poison`.

## Trust-Grenzen / Effekte

- **Der Writer ist die Fassade, nicht dieses Paket.** In
  `daedalus/spine/effect_boundary.py` sind drei Zeilen mit `Wiring.CENTRAL`
  registriert, alle mit Ziel `daedalus.file_bridge:*` und dem Guard-Contract
  `file_bridge.crash_journal`:

  | Entrypoint-ID | Ziel | Effekte |
  | --- | --- | --- |
  | `file_bridge.enqueue` | `enqueue` | `FILESYSTEM_WRITE` |
  | `file_bridge.process` | `process_request` | `FILESYSTEM_WRITE`, `PROCESS_SPAWN`, `NETWORK_EGRESS`, `SPEND` |
  | `file_bridge.watch` | `watch` | `FILESYSTEM_WRITE`, `PROCESS_SPAWN`, `NETWORK_EGRESS`, `SPEND` |

  Dazu kommt `cli.file_bridge` fuer `daedalus.file_bridge:main`. `file_bridge.watch`
  fuehrt zusaetzlich den Contract `budget.process_guard`, weil die Schleife das
  prozessweite Ausgabennetz tatsaechlich installiert — die Notiz im Boundary sagt,
  dass ein direktes `python -m` des Watchers dadurch nicht mehr ungepreist laufen
  kann.
- **`begin_effect` steht in keinem Modul dieses Verzeichnisses** (gemessen
  2026-09-05). Die Eigentuemer schreiben Dateien, aber nur ueber uebergebene
  Publisher-Ports und unterhalb einer bereits gestarteten Effekt-Autoritaet.
- **Zwei OS-Claims.** Ein Watcher-Claim pro Bridge (`WatcherOwnershipBusy`, mit
  `owner_token` und `process_identity` im Heartbeat) und ein Request-Claim pro
  Schluessel (`request_lock_path`). Beide sind Dateisperren, keine Prozess-
  Isolation.
- **Fail-closed bei Quarantaene-Bewegung.** Kann die Datei nicht verschoben
  werden, wirft `QuarantineMovePending`, statt den Zustand als `quarantined` zu
  behaupten. Analog `TerminalBookkeepingPending`, wenn ein
  `bookkeeping_pending`-Journal keinen terminalen Report hat.
- **Lane- und Strategie-Grenzen stehen in der CLI-Hilfe:** `auto`/`local` laufen
  ueber den geleasten Executor ohne direkten Claude-Fallback, `local_only` gibt nur
  vertrauenswuerdiges lokales Ollama frei, `claude`/`codex` werden abgelehnt, bis
  der Queue-Aufrufer Broker-Autoritaet haelt; `--strategy spawn` ist abgelehnt, bis
  ein geleaster Multi-Task-Adapter existiert.
- **Read-only:** `projection.py` (bis auf die `.seen`-Marker und `LATEST.log`, die
  ueber Ports laufen) und die Statusfunktionen sind Projektionen.
  `report_application_truth` rekonstruiert, ob eine Aenderung wirklich im Checkout
  landete, aus zurueckbehaltener Schreib-Evidenz — nicht aus einer Behauptung des
  Reports; ein gesetztes `mutation_blocked` gewinnt sofort mit `False`.
- **Scheduler-Wiedernutzung.** `watch_loop` nimmt einen optionalen
  `scheduled_tick` und fuehrt ihn im selben zugelassenen Watcher aus. Der
  Kommentar begruendet das ausdruecklich: keinen zweiten Daemon starten, und der
  Heartbeat meldet die Zeit ehrlich als busy. Das entspricht Plan §7.2
  ("kein separater Assistenz-Scheduler").

## Tests

Gemessen 2026-09-05. Direkt auf die Eigentuemer gerichtet (Strangler-Suite unter
`tests/interfaces/`):

- [test_bridge_queue_strangler.py](../../../tests/interfaces/test_bridge_queue_strangler.py)
- [test_bridge_journal_strangler.py](../../../tests/interfaces/test_bridge_journal_strangler.py)
- [test_bridge_dispatch_strangler.py](../../../tests/interfaces/test_bridge_dispatch_strangler.py)
- [test_bridge_watcher_strangler.py](../../../tests/interfaces/test_bridge_watcher_strangler.py)
- [test_bridge_conversation_strangler.py](../../../tests/interfaces/test_bridge_conversation_strangler.py)
- [test_bridge_projection_strangler.py](../../../tests/interfaces/test_bridge_projection_strangler.py)
- [test_bridge_cli_owner.py](../../../tests/interfaces/test_bridge_cli_owner.py)
- [test_computer_watcher.py](../../../tests/interfaces/test_computer_watcher.py) — der `scheduled_tick`-Pfad

Auf die Fassade `daedalus.file_bridge` gerichtet (Auswahl aus 30 Dateien, die den
Namen nennen): [test_bridge_enqueue_guard.py](../../../tests/test_bridge_enqueue_guard.py),
[test_bridge_restart.py](../../../tests/test_bridge_restart.py),
[test_bridge_signals.py](../../../tests/test_bridge_signals.py),
[test_comms.py](../../../tests/test_comms.py),
[test_conversation_on_canonical_spine.py](../../../tests/test_conversation_on_canonical_spine.py),
[test_cli_effect_boundary.py](../../../tests/test_cli_effect_boundary.py),
[test_envelope_coverage.py](../../../tests/test_envelope_coverage.py),
[test_spend_coverage.py](../../../tests/test_spend_coverage.py),
[test_hardening.py](../../../tests/test_hardening.py),
[test_imports_graph.py](../../../tests/test_imports_graph.py),
[test_spine_outer_ports.py](../../../tests/contracts/test_spine_outer_ports.py),
[test_import_scc_hierarchy.py](../../../tests/contracts/test_import_scc_hierarchy.py).

## Verwandt

- [Spine](spine.md) — `begin_effect`, die drei `file_bridge.*`-Zeilen und der Envelope
- [Daedalus package root](daedalus-package-root.md) — die Fassade `file_bridge.py` selbst
- [Interfaces CLI](interfaces-cli.md), [Interfaces HTTP](interfaces-http.md), [Interfaces desktop](interfaces-desktop.md) — die anderen Schnittstellen, die `bridge_status`/`stream_state` konsumieren
- [Runtimes](runtimes.md) — der Executor hinter `lane=auto/local`
- [Adapters](adapters.md) — der andere zentral verdrahtete Prozess-Spawn
- [Memory](memory.md) — `record_from_bridge_report` als Konsument des terminalen Reports
- [Agents hold no state](../decisions/agents-hold-no-state.md), [Wiki-Index](../index.md)

## Ungeklaert

- **Wo die Ports gebunden werden.** Jede Funktion hier nimmt ihre Autoritaet als
  Argument; welche konkrete Uhr, Sperre und welcher Publisher produktiv gesetzt
  sind, steht in `daedalus/file_bridge.py`, nicht in diesem Verzeichnis. Die
  Wiki-Seite beschreibt deshalb die Vertraege, nicht die produktive Bindung.
- **`effect_identity_for` und `mission_projection_dir`** existieren in
  `journal.py`, ihre Rolle in der Missions-Projektion ist aus dem Modul allein
  nicht ablesbar — die Aufrufer sitzen in der Fassade.
- **`codex_inline_brief_warning`** heisst nach einem konkreten Vendor. Ob die
  Warnung generisch gemeint ist oder an Codex-Verhalten gebunden bleibt, geht aus
  dem Code nicht hervor.
- **Heartbeat-Schwellen.** `stale_after_s`, `busy_budget_s` und
  `IDLE_BEAT_EVERY_S` werden als Parameter durchgereicht; die Werte und ihre
  Begruendung (Codex-Realtask-Budget 8-20 min, Provider-Timeout 1500 s) stehen im
  Fassadenmodul, nicht hier.

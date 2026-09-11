---
title: Adapters
type: module
status: living
updated: 2026-09-05
covers: daedalus/adapters
---
# Adapters

`daedalus/adapters` ist die Prozess- und Event-Normalisierung fuer explizit
konfigurierte, nicht-interaktive Agent-CLIs. Der Modul-Docstring von
`subprocess_adapter.py` sagt selbst, was es *nicht* ist: kein universelles
Agentenprotokoll. Jede CLI braucht weiterhin ein verifiziertes Kommandoprofil und
einen anbieterspezifischen Event-Parser. Im Ikarus/Ariadne-Bild sitzt das
Paket unter Ikarus als eine von zwei Prozess-Spawn-Strecken; die andere ist der
Provider-Broker in [Runtimes](runtimes.md). Alle vier effektbehafteten Methoden
sind im zentralen Effekt-Boundary aus [Spine](spine.md) registriert.

Gemessen 2026-09-05: 5 `.py`-Dateien, 805 Zeilen; `subprocess_adapter.py` traegt
davon 504.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/adapters/__init__.py) | Re-Export der oeffentlichen Namen und die drei Konstruktionswege (Profil, `from_name`, eigene `RuntimeConfig`). | `AgentAdapter`, `SubprocessAdapter`, `RuntimeConfig`, `RUNTIME_PROFILES`, `TransportRecord`, `TransportSink` |
| [`base.py`](../../../daedalus/adapters/base.py) | Abstrakte Schnittstelle einer Agent-Runtime: acht `async`-Methoden, keine Implementierung. | `AgentAdapter` mit `capabilities`, `create_session`, `send`, `events`, `approve`, `reject`, `interrupt`, `terminate` |
| [`events.py`](../../../daedalus/adapters/events.py) | Typisierte Event-Union plus der verlustfreie Transport-Umschlag, aus dem Downstream-Konsumenten (u. a. Embeddings) lesen. | `AgentEvent`, `AgentCapabilities`, `SessionStarted`, `SessionEnded`, `TextDelta`, `ToolRequested`, `ToolCompleted`, `FileRead`, `CommandOutput`, `AgentMessage`, `TransportRecord`, `event_to_transport_record` |
| [`transport.py`](../../../daedalus/adapters/transport.py) | Drei Senken fuer normalisierte Records: In-Memory, append-only JSONL, Fan-out. | `TransportSink`, `InMemoryTransportSink`, `JsonlTransportSink`, `CompositeTransportSink` |
| [`subprocess_adapter.py`](../../../daedalus/adapters/subprocess_adapter.py) | Startet eine konfigurierte CLI in einem begrenzten Arbeitsverzeichnis, normalisiert deren Ausgabe zu `AgentEvent` und faehrt sie kontrolliert herunter. | `SubprocessAdapter`, `RuntimeConfig`, `RUNTIME_PROFILES`, `PromptMode` |

### `RuntimeConfig` und die verifizierten Profile

`RuntimeConfig` ist ein eingefrorener Vertrag fuer *einen* Prozessstart:
`command`, `default_args`, `output_format` (`jsonl` oder `text`), `prompt_mode`
(`argument`, `stdin`, `none`), optionaler `stdin_prompt_marker`, `cwd_arg`,
`model_arg`, `close_stdin_after_prompt`, `env` und `timeout_s` (Default 600).

`RUNTIME_PROFILES` enthaelt gemessen 2026-09-05 genau zwei Eintraege:

- `claude` — `--print --verbose --input-format text --output-format stream-json
  --permission-mode dontAsk`, Prompt ueber stdin, Modell per `--model`.
- `codex` — `exec --json --ask-for-approval never --sandbox workspace-write`,
  Prompt ueber stdin mit Marker `-`, Arbeitsverzeichnis per `-C`.

Der Kommentar ueber dem Dict begruendet eine Auslassung ausdruecklich: Antigravity
fehlt, weil auf dieser Maschine weder ein `agy`-Executable noch ein stabiles
JSON-Protokoll existiert und eine Desktop-/IDE-Sitzung keinen aufrufbaren
CLI-Vertrag impliziert. `from_name` verweigert jeden unbekannten Namen und nennt
in der Fehlermeldung die verifizierten Profile.

### Event-Normalisierung

`_parse_line` faellt bei ungueltigem JSON auf `TextDelta` zurueck statt zu werfen.
`_parse_typed_event` bildet Anbieter-Ereignistypen auf die neutrale Union ab
(`tool_use`/`tool_call`/`tool_requested` -> `ToolRequested`, `bash`/`command`/
`shell`/`command_execution` -> `CommandOutput` usw.). Der Default-Zweig ist
bewusst konservativ: ein unbekanntes Lifecycle-Event wird als
`AgentMessage(role="system")` gefuehrt und nicht als vom Modell erzeugter Text
ausgegeben.

`event_to_transport_record` verpackt ein Event verlustfrei: `payload` ist der
vollstaendige `asdict(event)`, `content` eine je Typ gewaehlte Textprojektion,
`record_id` deterministisch `"{session}:{direction}:{sequence:08d}"`. Die
`direction` ist auf `input`, `output`, `system` beschraenkt und wirft sonst.
`TransportRecord.embedding_text()` ist die stabile Projektion fuer einen
optionalen Embedding-Index — der Docstring haelt fest, dass Embeddings aus diesem
Record *abgeleitet* werden und nie seine Nutzlast oder Provenienz ersetzen. Der
einzige Konsument im Baum ist [Memory](memory.md)
(`daedalus/memory/embeddings.py:121`).

## Trust-Grenzen / Effekte

Vier Methoden von `SubprocessAdapter` sind in `daedalus/spine/effect_boundary.py`
als `Wiring.CENTRAL` registriert, alle mit dem Guard-Contract
`runtime.adapter_profile`:

| Entrypoint-ID | Methode | Deklarierte Effekte |
| --- | --- | --- |
| `adapter.subprocess` | `create_session` | `PROCESS_SPAWN`, `NETWORK_EGRESS`, `FILESYSTEM_WRITE` |
| `adapter.subprocess.send` | `send` | `PROCESS_CONTROL` |
| `adapter.subprocess.interrupt` | `interrupt` | `PROCESS_CONTROL` |
| `adapter.subprocess.terminate` | `terminate` | `PROCESS_CONTROL` |

- **Der Writer ist der Spawn.** `create_session` ruft `begin_effect` *vor*
  `asyncio.create_subprocess_exec`; die Quittung wird pro Session in
  `_effect_receipts` gehalten. Ein abgelehnter Start bedeutet: kein Prozess.
- **`_adapter_profile_decision` ist die reale Entscheidung**, nicht ein
  Platzhalter. Sie unterscheidet exakt zwei Provenienzen —
  `verified-profile:<name>` bei Identitaetstreffer gegen `RUNTIME_PROFILES`,
  sonst `explicit-config:<command>` — und erfindet laut Docstring keine dritte.
  `allowed` verlangt ein nichtleeres `command` und ein existierendes,
  aufgeloestes `repo_root`.
- **Fail-closed beim Herunterfahren.** Der Kommentar in `terminate` sagt es
  ausdruecklich: eine abgelehnte Terminierung laesst die Session *getrackt*, statt
  den Prozess ohne Boundary-Quittung zu beenden. `interrupt` startet den Effekt
  nur, wenn die Session existiert und noch laeuft.
- **Kein Approval-Protokoll.** `approve` und `reject` werfen
  `NotImplementedError` mit der Begruendung, dass One-Shot-CLI-Profile kein
  portables Freigabeprotokoll anbieten. Wer Freigaben braucht, geht ueber den
  Kernel, nicht ueber diesen Adapter.
- **Schreibpfad in `transport.py`:** `JsonlTransportSink.publish` legt
  Elternverzeichnisse an und haengt an eine Datei an, unter einem
  `asyncio.Lock`. Diese Senke ist *nicht* im Effekt-Boundary registriert; sie ist
  ein vom Aufrufer uebergebener Journal-Pfad. Siehe "Ungeklaert".
- **Read-only:** `base.py`, `events.py` und die beiden Nicht-JSONL-Senken fassen
  keine Effektgrenze an. `capabilities()` gibt `hidden_state_access` hart als
  `False` zurueck, unabhaengig von der Konfiguration.
- **Timeout ist hart.** `events()` rechnet die Restzeit gegen
  `session.timeout_s` und ruft bei Ueberschreitung `_stop_process`
  (terminate, 5 s Gnadenfrist, dann kill) und wirft `TimeoutError`. `stderr` wird
  auf die letzten 4000 Zeichen gekuerzt in `SessionEnded` gefuehrt.

## Tests

Gemessen 2026-09-05 per Suche nach `daedalus.adapters` unter `tests/`:

- [test_adapters.py](../../../tests/test_adapters.py) — die direkte Abdeckung
  (246 Zeilen): Profile, `from_name`-Refusal, Event-Parsing, `TransportRecord`,
  Senken.
- [test_council_vendors.py](../../../tests/test_council_vendors.py) — liest
  `RUNTIME_PROFILES`, um die Vendor-Kommandos des Councils gegen dieselbe
  Profilquelle zu pruefen.
- [test_kairos_evolution.py](../../../tests/test_kairos_evolution.py) — nutzt
  `AgentAdapter` und `SessionEnded` fuer die Shadow-Shell aus
  [Kairos](kairos.md).
- [test_embeddings.py](../../../tests/test_embeddings.py) — baut
  `TransportRecord` als Eingabe des Embedding-Index.
- [test_promotion_execution_review.py](../../../tests/kernel/test_promotion_execution_review.py)
  und [test_fourfold_evidence_outer_ports.py](../../../tests/kernel/test_fourfold_evidence_outer_ports.py)
  — nennen das Paket in kernelseitigen Struktur- und Portpruefungen.

## Verwandt

- [Spine](spine.md) — `begin_effect`, `REGISTRY_BY_ID`, die vier Entrypoint-Rows
- [Runtimes](runtimes.md) — der andere Prozess-/Provider-Weg, mit Lease und Trust-Ledger
- [Runtimes provider](runtimes-provider.md) — Provider-Vertraege oberhalb dieser Schicht
- [Kairos](kairos.md) — `shadow_shell.py` konsumiert `AgentAdapter`
- [Memory](memory.md) — `embeddings.py` konsumiert `TransportRecord`
- [Council](council.md) — prueft seine Vendor-Kommandos gegen `RUNTIME_PROFILES`
- [Kernel policy](kernel-policy.md), [Tool vetting](../tool-vetting.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **`JsonlTransportSink` schreibt ohne registrierten Effekt.** Der Pfad kommt vom
  Aufrufer, der Schreibvorgang laeuft ausserhalb `begin_effect`. Ob das als
  Aufrufer-Verantwortung gemeint ist (der Spawn deklariert bereits
  `FILESYSTEM_WRITE`) oder eine offene Zeile im Effekt-Boundary ist, geht aus dem
  Code nicht hervor.
- **`FileRead` wird nie erzeugt.** Das Event ist Teil der `AgentEvent`-Union und
  wird in `event_to_transport_record` behandelt, aber `_parse_typed_event` bildet
  keinen Anbieter-Ereignistyp darauf ab (gemessen 2026-09-05). Entweder fehlt ein
  Parser-Zweig oder das Event ist fuer einen anderen Adapter reserviert.
- **`CompositeTransportSink` propagiert Fehler.** Der Docstring sagt "failures
  remain visible"; ein Fehler in einer Senke bricht die Schleife ab, sodass
  spaetere Senken den Record nicht sehen. Ob das die beabsichtigte Semantik ist
  oder nur die Sichtbarkeit gemeint war, ist nicht spezifiziert.
- **`RuntimeConfig.resume` und `hidden_state_access`** existieren als Felder, sind
  in beiden Profilen unbenutzt, und `capabilities()` ueberschreibt
  `hidden_state_access` ohnehin mit `False`.

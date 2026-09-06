---
title: Orchestration Ikarus
type: module
status: living
updated: 2026-09-05
covers: daedalus/orchestration/ikarus
---
# Orchestration Ikarus

`daedalus/orchestration/ikarus` ist die **Assistenz-Oberflaeche**: Absicht
hinein, typisierter Vorschlag heraus. Im Kernel/Ikarus/Ariadne-Bild
(Masterplan Abschnitt 3 und 7) ist das genau die Ikarus-Schicht -- sie
uebersetzt Nutzerabsicht in Missionen, WorkItems, Runtime-Rollen und
Werkzeug-Projektionen, und sie **autorisiert nichts**. Policy, Budget, Effect
Lease, Evidence und Promotion bleiben beim Kernel und bei den Spine-Vertraegen,
in die diese Module hineinrufen. Der Paket-Docstring zitiert den Plan dazu
woertlich: Modelle erhalten keine Autoritaet dadurch, dass sie als sprechende
Stimme ausgewaehlt wurden.

Das Paket entstand aus neun flachen `ikarus_*`-Modulen unter
`daedalus/orchestration/`. Der Praefix ist beim Umzug weggefallen -- mit einer
bewussten Ausnahme: aus `ikarus_os` wurde `shell.py` statt `os.py`, weil
letzteres die Standardbibliothek fuer jeden Prozess beschatten wuerde, dessen
`sys.path[0]` daneben landet.

Gemessen 2026-09-05: 14 `.py`-Dateien, 8499 Zeilen; `shell.py` allein 3336,
`supervisor.py` 1101, `computer_loop.py` 805.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/orchestration/ikarus/__init__.py) | Nur Dokumentation: warum das Paket existiert, was hineingehoert und was ausdruecklich nicht (Policy, Budget, Lease, Evidence, Promotion). Re-exportiert nichts. | (kein Code) |
| [`shell.py`](../../../daedalus/orchestration/ikarus/shell.py) | Der deterministische Intent-Router und die vendor-neutrale Stimme. Drei nach Faehigkeit getrennte Shells (`deterministic`, `hand`, `voice`), Provider-Fence, Projektkontext, Streaming. | `classify`, `ask`, `ask_stream`, `ProviderStartRefused`, `SHELL_DETERMINISTIC`, `SHELL_HAND`, `SHELL_VOICE`, `ASK_ENTRYPOINT_ID`, `ASK_STREAM_ENTRYPOINT_ID`, `PROVIDER_ENTRYPOINT_ID`, `SYSTEM` |
| [`act.py`](../../../daedalus/orchestration/ikarus/act.py) | Das zweite Praedikat: darf diese Nachricht einen werkzeugtragenden Executor erreichen? Bewusst getrennt von `classify`, weil beide Fragen entgegengesetzte Fehlerkosten haben. | `ActDecision`, `may_act`, `pending_offer`, `ACT_VERBS` |
| [`chat.py`](../../../daedalus/orchestration/ikarus/chat.py) | Deterministischer Netzwerk-Designer: macht aus einer Betreiber-Nachricht einen pruefbaren Agenten-Netz-Entwurf und wendet ihn nur auf ausdrueckliche Anforderung an. | `draft`, `chat`, `BLUEPRINTS` |
| [`oneshot.py`](../../../daedalus/orchestration/ikarus/oneshot.py) | Zustandsloser One-Shot-Request-Port: unveraenderliches Request-Objekt plus Bindung an vorhandene Runtime-Konformanz-Evidenz. Effektfrei -- kein Modellaufruf, keine Verbindung, kein Werkzeug. | `OneShotMessage`, `OneShotRequest`, `OneShotRuntimeEvidenceBinding`, `bind_oneshot_runtime_evidence`, `OneShotContractError`, `OneShotRuntimeRefused` |
| [`tool_scope.py`](../../../daedalus/orchestration/ikarus/tool_scope.py) | Reine Projektion ueber vier vorhandene Subjekte (Request, Runtime-Evidenz, `RuntimeManifest`, `PolicyDecision`). Leeres `requested_tools` heisst keine Werkzeuge; Wildcards sind verboten. | `IkarusToolScopeProjection`, `project_oneshot_tool_scope`, `IkarusToolScopeRefused` |
| [`effect_bridge.py`](../../../daedalus/orchestration/ikarus/effect_bridge.py) | Uebersetzt eine bereits begrenzte One-Shot-Absicht in die kanonische Kernel-Sprache `EffectLeaseRequest` / `EffectExecutionRequest`. Stellt keine Policy-Entscheidung aus und ruft keinen Provider. | `build_oneshot_effect_lease_request`, `build_oneshot_effect_execution_request`, `IkarusEffectBridgeRefused` |
| [`runtime_role.py`](../../../daedalus/orchestration/ikarus/runtime_role.py) | Unveraenderliche Runtime-Rollen-Bindungen als Dispatch-Port. Aufrufer-lokal, kollisionsfeindlich, ohne I/O. Nur `fixture`-Bindungen sind ausfuehrbar; alles andere ist `source-only`. | `RuntimeRoleBinding`, `RuntimeRoleSnapshot`, `RuntimeRoleRegistry`, `RuntimeRoleRegistryError`, `runtime_role_harness_key`, `INPROCESS_RUNTIME_ID`, `FIXTURE_EXECUTION_MODE` |
| [`runtime_events.py`](../../../daedalus/orchestration/ikarus/runtime_events.py) | Verlustbewusste, provider-neutrale Projektion von Runtime-Callbacks. Bindet `call_id` an einen deklarierten Plan-Eintrag; speichert nur SHA-256-Digests von Beobachtungen. | `RuntimeToolPlanEntry`, `RuntimeToolEvent`, `RuntimeToolProjectionRow`, `RuntimeEventProjection`, `RuntimeEventProjector`, `RuntimeEventProjectionError`, `ROW_STATUSES`, `TERMINAL_STATUSES`, `EVENT_KINDS` |
| [`supervisor.py`](../../../daedalus/orchestration/ikarus/supervisor.py) | Eine Mission, ein geteiltes State-Ledger, Rollen-Attempts. Das Ledger ist eine verkettete, inhaltsadressierte **Projektion**, kein zweiter Event Store. | `MissionSupervisor`, `StateLedger`, `PlannedItem`, `RoleHarness`, `plan_mission`, `verify_state_ledger`, `SupervisorRefused`, `StateLedgerBroken` |
| [`computer_loop.py`](../../../daedalus/orchestration/ikarus/computer_loop.py) | Der allgemeine Computer-Loop aus Amendment 012 (Masterplan 7.2): Ein-Werkzeug-Vorschlaege ueber kanonische Mission-, Event- und Artefakt-Vertraege. Besitzt keine Werkzeugerlaubnis und keinen Scheduler. | `computer_events`, `run_computer_task`, `conversation_events`, `is_computer_command`, `ComputerLoopRefused`, `MISSION_KIND`, `STEP_KIND`, `PROPOSAL_KIND` |
| [`computer_schedule.py`](../../../daedalus/orchestration/ikarus/computer_schedule.py) | Owner-begrenztes Einreihen und Faelligkeits-Dispatch ueber den kanonischen Event Store und CAS. Der bestehende Watcher besitzt das Ticken. | `schedule_computer`, `enqueue_computer`, `cancel_computer_schedule`, `list_scheduled_computer`, `dispatch_due_computer`, `SCHEDULE_KIND`, `CLAIM_KIND`, `CANCEL_KIND`, `CONTINUATION_KIND` |
| [`computer_context.py`](../../../daedalus/orchestration/ikarus/computer_context.py) | Begrenzter Owner-Produktkontext, projiziert aus kanonischen Spine-Fakten. Notizen und ausgewaehlte Skills sind untrusted Input, nie Policy- oder Evaluator-Autoritaet. | `context`, `remember`, `forget`, `use_skill`, `ENTRYPOINT`, `FACT_KIND`, `MAX_NOTES`, `MAX_NOTE_CHARS`, `NOTICE` |
| [`computer_history.py`](../../../daedalus/orchestration/ikarus/computer_history.py) | Read-only, autoritaets-gebundene Sicht auf Computer-Tasks ueber Spine und CAS. Anzeigeseiten treiben nie Scheduling oder Replay. | `list_computer_tasks`, `computer_task`, `MAX_ARTIFACT_BYTES` |

## Die drei Shells

`shell.py` hat einen Klassifikator und drei Executoren; getrennt wird nicht nach
Modell, sondern nach Faehigkeit:

* **`deterministic`** -- Status, Distill, Design. Lokal berechnet, kein Spend,
  kein Egress, kein Modell.
* **`hand`** -- die werkzeugtragende Shell. Erreichbar nur fuer Nachrichten, die
  das getrennte Praedikat `may_act` aus
  [`act.py`](../../../daedalus/orchestration/ikarus/act.py) freigegeben hat.
  Innerhalb des Moduls **schlaegt** sie nur einen bestaetigungspflichtigen Task
  **vor**; ausgefuehrt wird spaeter und asynchron ueber die kanonische
  File-Bridge. Eine bestaetigte `local_only`-Route verlangt zusaetzlich, dass
  der lokale Executor gemessen `working` ist, und verweigert in Worten statt auf
  "weiss nicht" hin zu committen.
* **`voice`** -- konversationell, keine Werkzeuge, nur Text. Jeder Zweig von
  `_llm` lebt hier.

Jedes `start`-Event, jedes Envelope und jeder persistierte Turn traegt die
antwortende Shell, damit "welche der drei hat gesprochen" eine aufgezeichnete
Tatsache ist und keine Ableitung aus dem Providernamen.

### Warum `may_act` nicht `classify` ist

`classify` beantwortet, *welcher Intent* vorliegt, damit die UI eine Affordanz
waehlen kann -- mit einer breiten zweisprachigen Stichworttabelle. `may_act`
beantwortet, ob eine Nachricht etwas erreichen darf, das Dateien schreibt. Die
Fehlerkosten sind entgegengesetzt, also gibt es zwei Funktionen, zwei
Testsuiten und keinen gemeinsamen Rueckgabewert: `may_act` ruft `classify` nie
auf, und das Label wird auf `ActDecision` nur zum **Berichten** mitgefuehrt,
damit eine Divergenz sichtbar wird statt still aufgeloest.

Die Erlaubnisregel ist eng: das erste signifikante Wort (nach Abzug von
Hoeflichkeits- und Fuellwoertern) muss ein exaktes englisches oder deutsches
imperatives Handlungsverb sein, und die Nachricht darf nicht interrogativ sein.
Alles andere ist bestenfalls `suspect`.

## Der One-Shot-Pfad

Vier Module bilden eine Kette, die vollstaendig effektfrei ist und trotzdem
alles benennt, was der Kernel spaeter braucht:

1. [`oneshot.py`](../../../daedalus/orchestration/ikarus/oneshot.py) baut den
   unveraenderlichen `OneShotRequest` und bindet ueber
   `bind_oneshot_runtime_evidence` (das
   `verify_current_conformance` aus `daedalus.kernel.runtime_conformance`
   nutzt) eine `OneShotRuntimeEvidenceBinding`.
2. [`tool_scope.py`](../../../daedalus/orchestration/ikarus/tool_scope.py)
   projiziert daraus zusammen mit `RuntimeManifest` und `PolicyDecision` eine
   `IkarusToolScopeProjection`. Ein Werkzeug muss sowohl von der Runtime
   deklariert als auch von der Policy gewaehrt sein, sonst schliesst die
   Projektion.
3. [`effect_bridge.py`](../../../daedalus/orchestration/ikarus/effect_bridge.py)
   uebersetzt die drei Subjekte in `EffectLeaseRequest` und -- danach
   verengt -- `EffectExecutionRequest`.
4. [`missions/one_shot.py`](../../../daedalus/orchestration/missions/one_shot.py)
   (siehe [Orchestration Missions](orchestration-missions.md)) verifiziert das
   Buendel gegen die Mission und verweigert, weil Gate 1 keinen zugelassenen
   Konsumenten hat.

## Trust-Grenzen / Effekte

**Registrierte Tueren mit `begin_effect` in diesem Paket:**

| Entrypoint-ID | Ziel | Effekte |
| --- | --- | --- |
| `ikarus_os.ask` | `shell:ask` | Provider-Start nur nach Registry-Pruefung |
| `ikarus_os.ask_stream` | `shell:ask_stream` | wie oben, streamend |
| `ikarus_os.provider_call` | `shell:_provider_start` | der eigentliche Transport-Start |
| `python.computer_context` | `computer_context:remember` | `FILESYSTEM_WRITE` |
| `python.computer_schedule` | `computer_schedule:schedule_computer` | `FILESYSTEM_WRITE` |
| `python.computer_dispatch_due` | `computer_schedule:dispatch_due_computer` | `FILESYSTEM_WRITE` |

Die Zeilen stehen in
[`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py);
`begin_effect` prueft die Registry-Zeile, die angeforderten Effekte und die
Guard-Contracts, bevor irgendetwas startet.

Weitere Grenzen:

* **Provider-Fence.** `_provider_start` in `shell.py` faellt in zwei Schritten:
  `_spend_decision` und `_egress_decision` produzieren `GuardDecision`s, erst
  danach entscheidet `begin_effect`. Eine Ablehnung wird als
  `ProviderStartRefused` mit einem Deny-Receipt geworfen und in
  `_refusal_envelope` fuer die UI gerendert. Fuer `chat`-Intents darf der
  Client die Stimme waehlen; die **Hand** waehlt immer die konfigurierte Lane
  des Projekts, nie der Chat-Provider.
* **Der Loop besitzt keine Werkzeugerlaubnis.** `computer_loop.py` laesst die
  `ComputerService` aus [`daedalus/runtimes/computer.py`](../../../daedalus/runtimes/computer.py)
  jedes tatsaechliche Werkzeug zulassen; das Modell liefert nur einen
  Vorschlag, der ueber `_parse_proposal` und `_validate_tool_proposal` geprueft
  wird. Unterbrochene Effekte sind sichtbare Abgleicharbeit, nie ein
  automatischer Retry.
* **Kontext ist untrusted.** `computer_context.NOTICE` sagt es explizit:
  Owner-Praeferenzen und ausgewaehlte Skills gewaehren keine Werkzeuge, Pfade,
  Netzzugriffe, Policy-Aenderungen oder Evaluator-Autoritaet. Mutation nur mit
  `owner_confirmed`. Schreibpfade laufen ueber `ExclusiveFileLock`,
  `store_canonical_json` und `open_gate0_spine_writer`.
* **Read-only per Konstruktion.** `computer_history.py` schreibt nichts; es
  liest CAS-Artefakte mit Digest-Pruefung, `MAX_ARTIFACT_BYTES`-Bound und
  Symlink-Refusal.
* **Das State-Ledger ist kein Event Store.** `StateLedger` schreibt pro
  Zustandsaenderung eine unveraenderliche Datei `<seq>-<digest12>.json` mit
  vollem Snapshot und `previous_ledger_sha256`. Die Wahrheit bleibt im
  `MissionContract`, in den `AttemptReceipt`s und im Spine-Ledger; das
  Verzeichnis komplett zu loeschen verliert eine bequeme Sicht und keine
  Tatsache. `verify_state_ledger` rechnet jeden Digest nach und laeuft die
  Kette ab; ein leeres Verzeichnis heisst "nicht verifizierbar", nie
  "verifiziert, nichts da".
* **Runtime-Rollen sind Deklaration, nicht Autoritaet.** In
  `runtime_role.py` ist nur `FIXTURE_EXECUTION_MODE` ausfuehrbar; eine echte
  Runtime bleibt `source-only`, bis ein spaeteres Paket Manifest, Lease,
  Beobachtungsautoritaet und ausfuehrbares Ziel ueber den kanonischen Broker
  verbindet.
* **Chat ist Interface, nicht Orchestrierungszustand** (Masterplan Abschnitt 7):
  Der Supervisor nimmt kein Transkript entgegen und speichert keines.

## Tests

Gemessen 2026-09-05, Testdateien mit direktem Bezug auf dieses Paket:

| Testdatei | Deckt ab |
| --- | --- |
| [`tests/test_ikarus_os.py`](../../../tests/test_ikarus_os.py), [`tests/test_ikarus_shells.py`](../../../tests/test_ikarus_shells.py) | `classify`, `ask`, Shell-Auswahl. |
| [`tests/test_ikarus_os_boundary.py`](../../../tests/test_ikarus_os_boundary.py) | Die drei `ikarus_os.*`-Registry-Zeilen und `begin_effect`. |
| [`tests/test_ikarus_act.py`](../../../tests/test_ikarus_act.py) | `may_act`, `ActDecision`, das False-Positive-Budget. |
| [`tests/test_ikarus_llm_voice.py`](../../../tests/test_ikarus_llm_voice.py), [`tests/test_ikarus_stream.py`](../../../tests/test_ikarus_stream.py) | Voice-Zweige und `ask_stream`. |
| [`tests/test_ikarus_context.py`](../../../tests/test_ikarus_context.py), [`tests/test_ikarus_project_grounding.py`](../../../tests/test_ikarus_project_grounding.py) | Projektkontext und Projektzustands-Kontext. |
| [`tests/test_ikarus_chat_shim_argv.py`](../../../tests/test_ikarus_chat_shim_argv.py) | Der Shim-Refusal fuer Provider-Kommandos. |
| [`tests/test_ikarus_oneshot.py`](../../../tests/test_ikarus_oneshot.py), [`tests/test_ikarus_tool_scope.py`](../../../tests/test_ikarus_tool_scope.py), [`tests/test_ikarus_effect_bridge.py`](../../../tests/test_ikarus_effect_bridge.py) | Die One-Shot-Kette. |
| [`tests/test_ikarus_runtime_role.py`](../../../tests/test_ikarus_runtime_role.py), [`tests/test_ikarus_runtime_events.py`](../../../tests/test_ikarus_runtime_events.py) | Rollen-Registry und Event-Projektion. |
| [`tests/test_ikarus_supervisor.py`](../../../tests/test_ikarus_supervisor.py) | `plan_mission`, `MissionSupervisor`, `StateLedger`, `verify_state_ledger`. |
| [`tests/test_ikarus_computer_loop.py`](../../../tests/test_ikarus_computer_loop.py), [`tests/test_ikarus_computer_autonomy.py`](../../../tests/test_ikarus_computer_autonomy.py) | Der Computer-Loop und seine Autonomiegrenzen. |
| [`tests/test_ikarus_computer_schedule.py`](../../../tests/test_ikarus_computer_schedule.py), [`tests/test_ikarus_computer_schedule_autonomy.py`](../../../tests/test_ikarus_computer_schedule_autonomy.py) | Planen, Abbrechen, Faelligkeits-Dispatch, Fortsetzungs-Reparatur. |
| [`tests/test_ikarus_computer_context.py`](../../../tests/test_ikarus_computer_context.py), [`tests/test_ikarus_computer_history.py`](../../../tests/test_ikarus_computer_history.py) | Produktkontext und Read-only-Historie. |
| [`tests/test_ikarus_autonomy_review.py`](../../../tests/test_ikarus_autonomy_review.py) | Review-Sicht auf die Autonomie-Regeln. |
| [`tests/orchestration/test_ikarus_mission_integration.py`](../../../tests/orchestration/test_ikarus_mission_integration.py) | Supervisor gegen den kanonischen Missionspfad. |
| [`tests/test_conversation_on_canonical_spine.py`](../../../tests/test_conversation_on_canonical_spine.py), [`tests/test_conversation_requests.py`](../../../tests/test_conversation_requests.py), [`tests/test_conversation_legacy_entrypoint_binding.py`](../../../tests/test_conversation_legacy_entrypoint_binding.py) | Konversations-Persistenz auf dem kanonischen Spine. |
| [`tests/test_egress_lane_by_host.py`](../../../tests/test_egress_lane_by_host.py), [`tests/test_killswitch.py`](../../../tests/test_killswitch.py) | Egress-Entscheidung und Kill-Switch im Provider-Pfad. |

## Verwandt

* [Orchestration](orchestration.md) -- das umgebende Paket.
* [Orchestration Missions](orchestration-missions.md) -- konsumiert
  `MissionSupervisor`, `StateLedger` und die One-Shot-Subjekte.
* [Orchestration Genesis](orchestration-genesis.md) -- der Genesis-Strang aus
  Masterplan 7.1.
* [Runtimes](runtimes.md) und [Runtimes Provider](runtimes-provider.md) --
  `ComputerService` und der Broker, der die Provider-Effekte tatsaechlich
  ausfuehrt.
* [Spine](spine.md) -- Effekt-Registry, `begin_effect`, `GuardDecision`.
* [Kernel Events](kernel-events.md) -- `SpineLedger`, `canonical_sha`.
* [Memory](memory.md) -- die Trennung von Produktgedaechtnis und
  Forschungsgedaechtnis, die `computer_context.py` einhaelt.
* [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md)
* [Tool-Vetting](../tool-vetting.md) -- die Vetting-Seite der Skills, die
  `use_skill` auswaehlen darf.
* [Wiki-Index](../index.md)

## Ungeklaert

* **Ungeklaert:** `chat.py` referenziert in `BLUEPRINTS` Pfade wie
  `vscode-agent-env/DESIGN.md` und Rollen wie `network-architect`. Ob diese
  Blueprint-Tabelle noch zum aktuellen Agentenbestand passt, laesst sich aus
  dem Modul allein nicht entscheiden.
* **Ungeklaert:** Ob `chat.draft`/`chat.chat` heute noch von einer UI aufgerufen
  werden; im Baum finden sich vor allem Tests und die HTTP-Schicht.
* **Ungeklaert:** Der genaue Uebergang von `RuntimeEventProjector` zu einem
  echten Provider-Adapter -- das Modul beschreibt das Bindungsprotokoll, aber
  kein Adapter im Baum ist eindeutig als Erzeuger dieser Events erkennbar.
* **Abweichung Code/Doku:** Die Modul-Docstrings tragen weiterhin die
  Vor-Umzug-Namen: `daedalus/orchestration/ikarus/act.py:1` beginnt mit
  `ikarus_act`, `daedalus/orchestration/ikarus/shell.py:1` mit `ikarus_os`.
  Die Querverweise im selben Docstring (`shell.py:32`) nennen bereits den neuen
  Pfad `daedalus.orchestration.ikarus.act`, die Ueberschriften nicht.

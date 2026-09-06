---
title: Opus Fleet Watchdog
type: experiment
status: living
updated: 2026-09-05
covers: experiments/opus_fleet_watchdog
---
# Opus Fleet Watchdog

Ein einmaliger, rein beratender Review-Lauf: mehrere Council-Sitze bekommen je
eine Rolle und eine ausdrücklich aufgelistete Dateimenge, sagen etwas dazu, und
das war es. Das Paket erzeugt keine Agenten mit Repository-Werkzeugen, kennt
keinen `TaskAttempt`, keinen Patch, keinen Commit, keinen Merge, keine
Promotion und keinen Evaluator. Es steht damit ausdrücklich neben der
Produktionslaufzeit -- im Kernel/Ikarus/Ariadne-Bild ist es weder Kernel noch
Orchestrator, sondern ein isoliertes Gate-0-Experiment, das vorhandene
Council-Transkripte als einzige Landefläche für Modellausgabe benutzt. Die
Effekt-Tür ist nicht hier, sondern die bereits registrierte
[tools/watchdog.py](../../../tools/watchdog.py); dieses Paket liefert nur den
Ablauf dahinter.

Die Arbeitsteilung ist im Docstring von `core.py` benannt: **LangGraph rechnet
einen reinen Slot-Plan, dieses Modul besitzt die begrenzten Effekte und den
operativen Zustand.** Der Planer darf keine Autorität gewinnen -- er darf
weder ein Ziel umschreiben noch eine unkonfigurierte Rolle noch mehr Slots als
`max_agents` erzeugen; `_validate_plan` prüft jede dieser Bedingungen und
verwirft den ganzen Plan bei der ersten Abweichung.

Gemessen 2026-09-05: 4 Python-Module, 2934 Zeilen, davon 1747 in `core.py`.
Das README des Verzeichnisses nennt ein ausdrückliches Verfallsdatum -- das
Paket samt seiner dünnen Watchdog-Verdrahtung soll gelöscht werden, sobald die
kanonischen vermittelten Claude- und Codex-Laufzeiten Live-Konformitätsbelege
auf exakter Revision haben; Überprüfung spätestens 2026-09-30.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../experiments/opus_fleet_watchdog/__init__.py) | Paketfassade und die Einordnung in einem Satz: beratend, ohne Checkout-Schreibrecht, ohne Attempt-, Merge-, Promotion- oder Evaluator-Pfad. | `__all__` |
| [core.py](../../../experiments/opus_fleet_watchdog/core.py) | Konfiguration, Planvalidierung, Sperren, Zustandsspeicher, Budget-Klammer, Sitz-Dispatch und Statusabfrage. | `ConfigError`, `CampaignBusy`, `CampaignCorrupt`, `ProjectConfig`, `FleetConfig`, `FleetSlot`, `ClaudeJsonWrapper`, `SessionProbeResult`, `StructuredClaudeAdapter`, `ExecutableCodexAdapter`, `load_config`, `dry_plan`, `run_campaign`, `campaign_status`, `parse_claude_json_wrapper`, `fallback_provider`, `STATE_SCHEMA`, `FALLBACK_API_STATUSES`, `TERMINAL_SLOT_STATUSES`, `COUNCIL_CANCELLATION_MARGIN_S`, `DEFAULT_RUNS_ROOT` |
| [scheduler.py](../../../experiments/opus_fleet_watchdog/scheduler.py) | Der Windows-Task-Scheduler-Adapter: nur das Betriebssystem-Aufwecken. Kommandobau und XML-Auswertung sind rein, damit der Vertrag ohne Registrierung einer echten Aufgabe prüfbar ist. | `SchedulerPaths`, `PowerShellInvocation`, `TaskExport`, `SchedulerStatus`, `SchedulerCommandError`, `build_install`, `build_uninstall`, `build_status`, `install`, `uninstall`, `status`, `parse_status_output`, `parse_exported_task_xml`, `TASK_FULL_NAME`, `INTERVAL_MINUTES`, `EXECUTION_LIMIT_HOURS` |
| [session_probe.py](../../../experiments/opus_fleet_watchdog/session_probe.py) | Die fail-closed Beobachtung des Hosts: Windows-Prozesszensus plus Hook-Aktivität der registrierten Projekte plus Mtimes der Codex-Rollout-Dateien. Legt keine PID-, Heartbeat-, Lease- oder Sessiondatei an und liest keinen Rollout-Inhalt. | `fleet_session_probe`, `RECENT_ACTIVITY_S`, `PROCESS_TIMEOUT_S`, `MAX_PROCESS_OUTPUT_BYTES` |

## Die vier Sicherungen

1. **Die Kampagnen-ID ist das Scharfmachen.** Ein erneuter Lauf einer
   terminalen Kampagne ruft keinen Anbieter mehr auf; `run_campaign` gibt den
   gespeicherten Zustand zurück. `TERMINAL_SLOT_STATUSES` listet die sechs
   Endzustände. Es gibt keine rollende Zeitstempel-ID, kein implizites
   Nachladen und keine automatische Ausgabeschleife -- mehr Arbeit verlangt ein
   bewusst neues Work Packet mit neuer ID. Ändert sich die Konfiguration oder
   der Plan unter einer bestehenden ID, verweigert der Zustandsspeicher mit
   `CampaignCorrupt`, statt weiterzulaufen.
2. **Ein Slot wird als `in_flight` markiert und sein Anrufversuch persistiert,
   bevor er losgeschickt wird.** Stirbt der Prozess, markiert der nächste Lauf
   diesen Slot als `unknown` und wiederholt ihn nie automatisch.
3. **Zwei Sperren, beide vom Betriebssystem freigegeben.** `_CampaignLock` ist
   ein `msvcrt.locking`- beziehungsweise `flock`-Advisory-Lock auf einer Datei;
   ein toter Prozess kann die Kampagne nicht blockieren. Die äußere Sperre
   liegt maschinenglobal am Watchdog-Wurzelverzeichnis, damit nicht zwei
   verschiedene Kampagnen-IDs gleichzeitig eine leere Maschine beobachten und
   parallel starten; die innere ist kampagnenlokal. Es gibt bewusst keine
   PID-Datei, die nach einem Absturz lügen könnte.
4. **Die Sitzgrenze überlebt die Abbruchleiter.** `COUNCIL_CANCELLATION_MARGIN_S`
   ist so bemessen, dass Council einen Sitz nicht aufgeben und die Fleet-Sperre
   freigeben kann, während dieser Sitz noch ein Kind abbricht -- gerechnet über
   zwei vollständige `ManagedProcess`-Abbruchleitern plus Aufräumen.

## Der Fallback ist eng, nicht großzügig

Claude/Opus wird genau einmal geprüft, bevor die übrigen Slots starten. Codex
kommt nur infrage, wenn die Claude-CLI ein JSON-Objekt mit `is_error: true`
und einem numerischen `api_error_status` aus `FALLBACK_API_STATUSES`
(429, 503, 529) zurückgab. `fallback_provider` prüft dafür sogar
`type(observation) is ClaudeJsonWrapper` statt `isinstance` -- eine Unterklasse
soll die Route nicht erben können. Ausdrücklich **kein** Fallback lösen aus:
Text, in dem "429" vorkommt; Authentifizierungsfehler; Timeouts; kaputtes
JSON; ein gewöhnlicher Exit ungleich null; Budget-Verweigerungen; Policy- oder
Secret-Floor-Verweigerungen. Ändert eine künftige CLI ihr stdout-Schema,
scheitert das Parsen geschlossen und Codex startet nicht.

## Der Idle-Gate

`run_campaign` verlangt eine vom Supervisor injizierte `session_probe`, die
`{"ok", "active_sessions", "sources", "reason"}` liefert. Fehlt sie, wirft sie
oder ist ihr Ergebnis unförmig, ist das ein Fehlschlag, kein Weiterlaufen. Eine
positive Beobachtung wird festgehalten, und die Kampagne wartet mit allen Slots
auf `pending`; der nächste 20-Minuten-Tick darf erneut prüfen. Die ausgewählte
Evidenz wird erst gelesen und eingefroren, wenn dieses Gate zum ersten Mal
"leer" meldet -- sonst würde eine aktive Session die wartende Kampagne mit
einem veralteten Digest vergiften.

`fleet_session_probe` sagt seine eigenen Grenzen im Docstring: Hook-Zustand
kennt kein Session-Ende, ein frisches Hook-Artefakt heißt also "Aktivität
innerhalb des Kulanzfensters" (`RECENT_ACTIVITY_S`, 30 Minuten), nicht
"nachweislich lebendig". Langlebige VS-Code-Dienste blockieren nicht allein
durch ihre Anwesenheit, weil das die Flotte aushungern würde, solange ein
Editor offen ist; direkte CLI-Aufrufe blockieren dagegen für ihre volle
Prozesslaufzeit. Und das Ganze ist eine Vorabbeobachtung, keine Sperre gegen
Menschen: eine CLI kann nach dem Zensus starten, und ein einzelner stiller Zug
jenseits des Kulanzfensters kann leer aussehen. Diese TOCTOU-Lücke wird
benannt, nicht wegdefiniert.

## Trust-Grenzen / Effekte

- **Kein Schreibpfad ins Repository.** Nur `runs/watchdog/mission-<id>/` wird
  beschrieben: hash-verkettete, append-only Council-Transkripte und
  `state.json`. Der Zustand enthält keine Modellprosa. Der einzige Writer ist
  `_StateStore._write` über `write_text_atomic`.
- **Die registrierte Effekt-Tür liegt außerhalb.** `scheduler.py` besitzt nur
  das Aufwecken; die geplante Aktion betritt wieder
  [tools/watchdog.py](../../../tools/watchdog.py), das bereits als
  Effekt-Boundary registriert ist. Das Modul führt selbst kein Modell aus und
  verändert kein Repository.
- **Evidenz ist auflistungspflichtig.** Nur die in der JSON-Konfiguration
  ausdrücklich genannten Dateien landen in `Evidence`; der Secret-Floor des
  Council prüft jeden Pfad und jede Datei vor dem Egress, und
  `max_evidence_bytes` deckelt die Menge.
- **Jeder Sitz ist ein frisches Ein-Personen-Council.** Claude läuft mit dem
  Council-Profil, jedem Werkzeug verweigert und einer exakt leeren nativen
  `--tools`-Menge; Codex mit der Read-only-Sandbox des Council-Profils, ohne
  Nutzerkonfiguration und -regeln und mit flüchtigem Sitzungszustand.
- **Budget.** `max_spend_usd` und `max_calls` werden über ein kampagnenlokales
  Daedalus-Budget-Ledger *und* einen dauerhaften Anrufzähler durchgesetzt; das
  maschinenweite Budget darf am äußeren Rand strenger bleiben. Ein
  `KillSwitch.watch()` liegt um den gesamten Lauf.
- **Subprozesse.** `session_probe.py` und `scheduler.py` starten PowerShell mit
  festen, statischen Skripten; aufrufergesteuerte Werte werden über die
  Prozessumgebung des Kindes gelesen und nie in PowerShell-Quelltext
  interpoliert. Ausgabe ist auf `MAX_PROCESS_OUTPUT_BYTES` begrenzt, die
  Laufzeit auf `PROCESS_TIMEOUT_S`.

## Tests

Gemessen 2026-09-05 decken vier Dateien unter `tests/` das Paket ab, zusammen
62 Testfunktionen:

- [tests/test_opus_fleet_watchdog.py](../../../tests/test_opus_fleet_watchdog.py)
  (23) -- Konfiguration, Planvalidierung, Wiederaufnahme, Sperren,
  Budgetklammer, Fallback-Route.
- [tests/test_opus_fleet_session_probe.py](../../../tests/test_opus_fleet_session_probe.py)
  (23) -- Prozesszensus, Hook-Alter, Codex-Rollouts, fail-closed Verhalten.
- [tests/test_opus_fleet_scheduler.py](../../../tests/test_opus_fleet_scheduler.py)
  (11) -- Kommandobau und XML-Auswertung ohne Registrierung einer Aufgabe.
- [tests/test_opus_fleet_cli.py](../../../tests/test_opus_fleet_cli.py)
  (5) -- die `fleet`-Unterbefehle von `tools/watchdog.py`.

Die exakte vollständige Form des Claude-JSON-Wrappers ist laut README in
diesen Unit-Tests festgenagelt, weil die ursprünglichen stdout-Bytes nicht
aufbewahrt wurden.

## Verwandt

- [Council](../architecture/council.md) -- die Sitzungen, Adapter und der
  Secret-Floor, die dieses Paket benutzt statt sie neu zu bauen.
- [Orchestrierung](../architecture/orchestration.md) und
  [Kairos](../architecture/kairos.md) -- der LangGraph-Adapter, der den reinen
  Slot-Plan rechnet, und der kanonische Scheduler.
- [Runtimes](../architecture/runtimes.md) und
  [Runtimes — Provider](../architecture/runtimes-provider.md) -- die
  vermittelten Claude-/Codex-Laufzeiten, deren Live-Konformitätsbelege dieses
  Experiment ablösen sollen.
- [Runtimes — Providers](../architecture/runtimes-providers.md) -- Katalog,
  Vertrauensflags und Budget-Zulassung der Anbieter.
- [Spine](../architecture/spine.md) -- Effekt-Registry, Abbruchleiter und
  Kill-Switch.
- [Tools (CLI)](../tooling/tools.md) und
  [Agents hold no state](../decisions/agents-hold-no-state.md).
- [Wiki-Index](../index.md).

## Ungeklärt

- Ob je eine Live-Kampagne mit `live: true` gelaufen ist, geht aus dem Code
  nicht hervor; unter `runs/watchdog/` habe ich nicht nachgesehen.
- `session_probe.py` liest Codex-Rollout-Mtimes und Hook-Artefakte
  registrierter Projekte. Welche Projekte das auf dieser Maschine sind, hängt
  von `daedalus.foundation.projects` ab und ist nicht im Paket festgelegt.
- Das Paket trägt ein Löschdatum (2026-09-30) und eine Bedingung dafür. Ob die
  Bedingung inzwischen erfüllt ist, habe ich nicht gemessen.

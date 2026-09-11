---
title: Interfaces CLI
type: module
status: living
updated: 2026-09-05
covers: daedalus/interfaces/cli
---
# Interfaces CLI

`daedalus/interfaces/cli` sind die **Konsolen-Eintrittspunkte**: die Befehle,
die ein Mensch tippt. Der Paket-Docstring nennt das Aufnahmekriterium
ausdruecklich -- ein Modul gehoert hierher, wenn sein Leser an einem Terminal
sitzt, es einen `argparse`-Parser und ein `main()` besitzt und das Produkt es
ueber ein Console-Script oder `python -m` erreicht, nicht ueber einen Import.
**Null Importeure ist die erwartete Form**, deshalb greift das uebliche
Insel-Signal hier nicht; geprueft wird stattdessen, dass ein dokumentierter
Aufruf existiert.

Im Kernel/Ikarus/Ariadne-Bild ist dieses Paket eine Oberflaeche, keine
Autoritaet: es entscheidet nichts selbst, sondern ruft in Kernel-, Spine- und
Ikarus-Module hinein. Geschwister unter `daedalus.interfaces` sind
[`bridge`](interfaces-bridge.md) (File-Bridge-Transport),
[`desktop`](interfaces-desktop.md) (Desktop-Runtime-Oberflaeche) und
[`http`](interfaces-http.md) (lokale Web-API).

Gemessen 2026-09-05: 9 `.py`-Dateien, 3173 Zeilen; `entry.py` allein 1399.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/interfaces/cli/__init__.py) | Nur Dokumentation des Aufnahmekriteriums und der Geschwisterpakete. Kein Code. | (kein Code) |
| [`entry.py`](../../../daedalus/interfaces/cli/entry.py) | Der vereinheitlichte `daedalus`-Befehl: ein Einstieg fuer die gesamte Harness, der auf ueber 40 Unterbefehle verteilt. Installiert `.env` und die Ausgabesperre, bevor irgendein Unterbefehl ausgefuehrt wird. | `main`, `_USAGE` |
| [`arch_memory.py`](../../../daedalus/interfaces/cli/arch_memory.py) | Die komprimierte Architektur, die ein Agent in jeden Turn mitnimmt: Frische zuerst, dann Paketrollen, Hubs, Inseln/Shims und Doc-Drift. | `ArchMemory`, `build`, `save`, `load`, `render`, `render_delta`, `main` |
| [`bookkeeper.py`](../../../daedalus/interfaces/cli/bookkeeper.py) | Haelt das lebende Architektur-Artefakt synchron: rendert `docs/ARCHITECTURE.md` nach `docs/architecture.html` und legt bei inhaltlicher Aenderung einen zeitgestempelten Snapshot mit Git-Hash ab. Stdlib-only, eigener kleiner Markdown-Konverter. | `render_markdown`, `update`, `main` |
| [`enforce.py`](../../../daedalus/interfaces/cli/enforce.py) | Schreibt einen markierten Block mit den zugelassenen File-Bridge-Aufrufen in die Instruktionsdateien eines Ziel-Repositories (zwischen `BEGIN`/`END`-Markern, idempotent). | `enforce_repo`, `main`, `BEGIN`, `END` |
| [`selftest.py`](../../../daedalus/interfaces/cli/selftest.py) | Live-Selbsttest: ein **echter** Ollama-Round-Trip in einem Wegwerf-Repo, getrennt von der Unit-Suite. Prueft nur modell-agnostische Tatsachen (echte Byte-Aenderung, Datei kompiliert, Verifier akzeptiert, null Claude-Tokens) und ueberspringt sauber, wenn die Bench nicht bereit ist. | `run`, `main` |
| [`shift.py`](../../../daedalus/interfaces/cli/shift.py) | Ein deklariertes Arbeitsfenster, damit ein Agent die Uhr nicht verliert: Ziel, Start, Deadline, Definition von "fertig". Vier Fakten, atomar geschrieben, unter Datei-Lock. | `Shift`, `load`, `start`, `note`, `end`, `main` |
| [`shift_ticker.py`](../../../daedalus/interfaces/cli/shift_ticker.py) | Die Ansicht fuer den **Menschen**: Uhrzeit, Ziel, Restfenster, Checkpoints, in tmux/screen laufend. Erzwingt nichts -- ein Ticker, der auf einer Deadline Arbeit toetet, waere schlimmer als ein spaeter Abschluss. | `render`, `main` |
| [`token_monitor.py`](../../../daedalus/interfaces/cli/token_monitor.py) | `daedalus tokens`: was die Session verbrannt hat, und sonst nichts. Ausdruecklich Observability, keine Durchsetzung. | `UsageSample`, `read_usage_samples`, `summarize_usage`, `should_checkpoint`, `checkpoint_if_needed`, `watch`, `main` |

## `daedalus` -- ein Befehl, viele Unterbefehle

`entry.py:main` liest `sys.argv[1]` als Unterbefehl, schreibt `sys.argv` neu
(damit Sub-Parser ein sauberes `argv` sehen) und dispatcht per
`if/elif`-Kette. Die Unterbefehle decken Diagnose (`doctor`, `health`,
`status`, `drill`), Ausfuehrung (`offload`, `spawn`, `build`, `improve`,
`ikarus`), Kontext und Gedaechtnis (`context`, `dctx`, `project-memory`,
`map`), Governance (`governance`, `approvals`, `fault-attestation`),
Produkt-Straenge (`genesis`, `ariadne`, `web`, `dashboard`) und
Werkzeuge (`council`, `canary`, `claude-crew`, `drafts`, `selftest`, `tokens`,
`bookkeeper`, `enforce`, `init`, `agents`, `categories`, `projects`,
`accelerators`, `models`, `squads`, `watcher`, `review-diff`, `metrics`,
`benchmark`) ab.

Zwei Dinge passieren **vor** jedem Unterbefehl, und der Kommentar im Code
begruendet beide:

1. `.env` wird ueber `daedalus.foundation.dotenv.load` geladen -- **vor** dem
   Guard, weil die Guard-Konfiguration (Ceiling, Call-Cap, deklarierte
   Subscription-Vendoren) genau dorthin gehoert. Ein getracktes `.env` ist ein
   Refusal, der die ganze CLI stoppt: es waere ein bereits im Repository
   liegendes Geheimnis.
2. `install_process_guard()` aus [`daedalus/budget.py`](../../../daedalus/budget.py)
   installiert die Ausgabesperre an der Syscall-Grenze. Der Kommentar nennt den
   Grund fuer diese Platzierung: bezahlte Aufrufe verlassen das Repository aus
   vier Subsystemen ohne gemeinsamen Dispatch-Pfad, und eine Sperre, an die man
   sich erinnern muss, fehlt genau dort, wo jemand sie vergessen hat.
   Nicht-Vendor-Spawns werden klassifiziert und unveraendert durchgereicht, also
   sind `git` und `pytest` nicht betroffen.

### Direkt unter `daedalus/interfaces/`

Zwei Dateien liegen nicht in einem der vier Unterpakete und haben deshalb im
Seitenplan keinen eigenen Platz:

| Datei | Zweck | Symbole |
| --- | --- | --- |
| [interfaces/__init__.py](../../../daedalus/interfaces/__init__.py) | Paketmarker: "stable application interfaces layered above the canonical kernel". | -- |
| [computer_configuration.py](../../../daedalus/interfaces/computer_configuration.py) | Explizites Bearbeiten der Computer-Policy durch den Owner, ausdruecklich **kein** modellaufrufbares Werkzeug. Registrierte Tuer `python.ikarus_computer_configure` (`ENTRYPOINT`), `begin_effect` vor dem Schreiben, Kandidat wird ueber `ComputerPolicy.from_dict` und eine Groessenschranke geprueft, geschrieben unter `ExclusiveFileLock` als kanonisches JSON. Einziger Aufrufer im Baum ist `computer_loop.py` in [Orchestration Ikarus](orchestration-ikarus.md). | `configure_computer`, `ENTRYPOINT` |

## Trust-Grenzen / Effekte

Registrierte Zeilen in
[`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py)
fuer dieses Paket:

| Entrypoint-ID | Ziel | Effekte | Wiring |
| --- | --- | --- | --- |
| `cli.daedalus` | `entry:main` | `FILESYSTEM_WRITE`, `PROCESS_SPAWN`, `NETWORK_EGRESS`, `REPOSITORY_MUTATION`, `SPEND` | `LOCAL_GUARDS`, Anchor `install_process_guard` |
| `cli.council` | `entry:_council` | mehrere, inkl. Spend/Egress | `CENTRAL`, Anchor `begin_effect` |
| `cli.enforce` | `enforce:main` | `FILESYSTEM_WRITE` | `CENTRAL` |
| `cli.selftest` | `selftest:main` | `FILESYSTEM_WRITE`, `NETWORK_EGRESS` | `CENTRAL` |
| `cli.shift` | `shift:main` | `FILESYSTEM_WRITE` | `CENTRAL` |
| `cli.token_monitor` | `token_monitor:main` | `FILESYSTEM_WRITE` | `CENTRAL` |
| `cli.arch_memory` | `arch_memory:main` | `FILESYSTEM_WRITE`, `PROCESS_SPAWN` | `CENTRAL` |
| `cli.bookkeeper` | `bookkeeper:main` | `FILESYSTEM_WRITE`, `PROCESS_SPAWN` | `CENTRAL` |

`cli.daedalus` ist die einzige Zeile mit `Wiring.LOCAL_GUARDS` statt
`CENTRAL`: der Console-Script-Kopf installiert die Ausgabesperre und dispatcht
dann an lokale Unterbefehle, von denen jeder seine eigene registrierte Tuer hat.

Weitere Grenzen:

* **`token_monitor.py` entscheidet nichts ueber Geld.** `should_checkpoint`
  nimmt genau ein Argument -- die aus den lokalen Claude-Logs abgeleitete
  Token-Zusammenfassung. `_budget_view` und `_spine_view` werden in `main`
  **nach** der Entscheidung zusammengesetzt, damit keine spaetere Aenderung eine
  Spend-Zahl in ein Checkpoint-Urteil fliessen lassen kann, ohne diese Signatur
  im Diff zu aendern; ein Test pinnt das. Der Spine wird `read_only=True`
  geoeffnet, sodass SQLite selbst den Schreibzugriff verweigert. Geschrieben
  wird nur der eigene Report unter `memory/`.
* **`selftest.py` importiert bewusst kein `shutil`.** Der einzige rekursive
  Loeschvorgang -- das Scratch-Repo, in das gerade ein **Live**-Modell
  geschrieben hat -- laeuft ueber `remove_tree_no_follow`; das Weglassen des
  Imports macht ein Wiedereinfuehren von `shutil.rmtree` zu einer sichtbaren
  Zeile im Diff.
* **`shift.py` schreibt atomar und unter Lock** (`_write_atomic`, `_ShiftLock`),
  weil parallele Agenten-Sessions dieselbe Datei anfassen.
* **`shift_ticker.py` erzwingt nichts** und hat keine Registry-Zeile: es liest
  und druckt (kein Spawn, kein Netz, kein Schreibaufruf), ist nach der
  Scanner-Definition also keine Tuer. Wenn das Fenster vorbei ist, sagt es
  das laut, einmal pro Tick, und laeuft weiter.
* **`enforce.py` schreibt in ein fremdes Repository** -- deshalb die eigene
  zentrale Tuer. Der geschriebene Block ist zwischen `BEGIN` und `END`
  markiert, sodass wiederholtes Ausfuehren ersetzt statt anhaengt.
* **`arch_memory.py` und `bookkeeper.py` starten Prozesse** (`git`), daher
  `PROCESS_SPAWN` in beiden Zeilen.

## Tests

| Testdatei | Deckt ab |
| --- | --- |
| [`tests/test_cli_effect_boundary.py`](../../../tests/test_cli_effect_boundary.py) | Dass jede CLI-Tuer ihre Registry-Zeile und ihren Anchor hat. |
| [`tests/test_cli_token_verb.py`](../../../tests/test_cli_token_verb.py), [`tests/test_token_monitor_write_roots.py`](../../../tests/test_token_monitor_write_roots.py) | `daedalus tokens`, die Entscheidungssignatur und die deklarierten Schreibwurzeln. |
| [`tests/test_bookkeeper.py`](../../../tests/test_bookkeeper.py) | `render_markdown`, `update`, Snapshot-Historie. |
| [`tests/test_selftest.py`](../../../tests/test_selftest.py) | Der Live-Selbsttest inklusive sauberem Skip. |
| [`tests/test_agent_env.py`](../../../tests/test_agent_env.py) | `enforce_repo` und der markierte Block. |
| [`tests/contracts/test_ui_named_commands_resolve.py`](../../../tests/contracts/test_ui_named_commands_resolve.py) | Dass jeder von der UI benannte Unterbefehl aufloest. |
| [`tests/test_budget_is_installed.py`](../../../tests/test_budget_is_installed.py), [`tests/test_spend_coverage.py`](../../../tests/test_spend_coverage.py), [`tests/test_uncapped_budget_consumers.py`](../../../tests/test_uncapped_budget_consumers.py) | `install_process_guard` im CLI-Kopf und die Spend-Abdeckung. |
| [`tests/test_council_publish_cli.py`](../../../tests/test_council_publish_cli.py), [`tests/test_council_livewire.py`](../../../tests/test_council_livewire.py), [`tests/test_canary_livewire.py`](../../../tests/test_canary_livewire.py) | Die `council`- und `canary`-Unterbefehle. |
| [`tests/interfaces/test_genesis_cli.py`](../../../tests/interfaces/test_genesis_cli.py) | Der `genesis`-Unterbefehl. |
| [`tests/test_registry_shadowing.py`](../../../tests/test_registry_shadowing.py), [`tests/test_write_surface_coverage.py`](../../../tests/test_write_surface_coverage.py) | Registry-Beschattung und Schreiboberflaechen-Abdeckung. |
| [`tests/test_hooks_v2.py`](../../../tests/test_hooks_v2.py), [`tests/test_hooks_review_20260825.py`](../../../tests/test_hooks_review_20260825.py) | Die Hook-Seite der Shift-Uhr. |
| [`tests/test_lanes_checks.py`](../../../tests/test_lanes_checks.py), [`tests/test_lanes_fanout.py`](../../../tests/test_lanes_fanout.py) | Lane-Auswahl hinter `daedalus offload`/`spawn`. |

## Verwandt

* [Interfaces Bridge](interfaces-bridge.md), [Interfaces Desktop](interfaces-desktop.md),
  [Interfaces HTTP](interfaces-http.md) -- die Geschwister-Oberflaechen.
* [Spine](spine.md) -- Effekt-Registry und `begin_effect`.
* [Orchestration Ikarus](orchestration-ikarus.md) -- die Chat-Oberflaeche, die
  dieselben Lanes benutzt.
* [Council](council.md) -- der Unterbefehl `daedalus council`.
* [Gates](gates.md) -- `daedalus governance`, `daedalus approvals`.
* [Tools](tools.md) und [Tooling: tools/](../tooling/tools.md) -- die
  Werkzeugseite neben den Konsolenbefehlen.
* [Tooling: scripts/](../tooling/scripts.md) -- die Dev-Harness-Runner, die
  ausdruecklich **keine** CLI-Oberflaeche sind.
* [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md) --
  warum `shift.py` und `arch_memory.py` ueberhaupt existieren.
* [Wiki-Index](../index.md)

## Ungeklaert

* **Docstring-Drift:** `shift_ticker.py` verweist auf einen bis 2026-08-23
  existierenden `shift_hook.py`, der nicht mehr an dieser Stelle liegt. Die
  fehlende Registry-Zeile ist korrekt (keine Tuer: kein Spawn, kein Netz,
  kein Schreibaufruf; Messung der Review-Session 2026-09-05).
* **Ungeklaert:** Die Registry fuehrt zusaetzlich `cli.shift_compat` mit Ziel
  `daedalus.shift:main`. Ob dieses Kompatibilitaetsmodul noch Aufrufer hat,
  gehoert nicht in dieses Verzeichnis und ist hier nicht gemessen.
* **Ungeklaert:** `entry.py` traegt in seinem `_USAGE`-Text mehr Unterbefehle,
  als die `if/elif`-Kette behandelt bzw. umgekehrt; ein vollstaendiger Abgleich
  von Hilfetext und Dispatch wurde nicht durchgefuehrt.

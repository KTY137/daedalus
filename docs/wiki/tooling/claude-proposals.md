---
title: Claude-Proposals — Statusline und User-Level-Hooks
type: tooling
status: living
updated: 2026-09-05
covers: .claude/proposals
---
# Claude-Proposals — Statusline und User-Level-Hooks

`.claude/proposals` ist die **Quelle der Wahrheit** fuer drei kleine
Claude-Code-Erweiterungen, die nicht im Repository laufen koennen, sondern als
Kopie unter `~/.claude/hooks/` bzw. in der User-Einstellungsdatei leben: die
Statusline, ein Windows-Notification-Toast und der Orientierungs-Hook, der
sagt, ob eine Sitzung im aktiven oder im archivierten Baum steht. Das
Verzeichnis gehoert zu keiner Produktachse (weder Kernel noch Ikarus noch
Ariadne) — es ist Werkzeugumgebung fuer die Agenten, die an diesem Repository
arbeiten.

Der Name "Proposals" ist historisch. Die
[README](../../../.claude/proposals/README.md) haelt seit 2026-08-23 fest,
dass das Verzeichnis **verdrahtet** ist: `statusline.py` und
`hook_notification_toast.py` laufen als Kopien unter `~/.claude/hooks/`
(user-global, damit sie nicht von einem archivierbaren Repo-Pfad abhaengen),
`orient.py` ebenso. Nach einer Aenderung hier muss die Kopie nachgezogen
werden — es gibt keinen Mechanismus, der das erzwingt. Die
Merge-Anleitung in der README ist ausdruecklich als Geschichte markiert.

Gemessen 2026-09-05: 3 Python-Dateien mit 218 Zeilen, dazu drei JSON-Dateien
und die README.

## Warum user-level und nicht Repo-Hook

Die Begruendung steht im Docstring von `orient.py` und ist der interessanteste
Teil des Verzeichnisses: **die eigenen Hooks eines Repositories koennen nicht
davor warnen, dass dieses Repository archiviert ist** — die Einstellungen des
archivierten Baums sind mit ihm eingefroren (Codex-Review B3, 2026-08-23). Die
Liste der Baumwurzeln ist ausserdem eine Tatsache ueber *diese Maschine*, nicht
ueber ein Repository, und gehoert deshalb zum Benutzer. Dasselbe Argument
traegt die Statusline: sie soll auch dann funktionieren, wenn die Sitzung gar
nicht in Daedalus steht.

Die Abgrenzung zu [Hooks](../architecture/hooks.md) ist damit scharf: was
**ueber diesen Baum** spricht, gehoert in das Paket `daedalus/hooks` und laeuft
ueber dessen registrierten Dispatcher; was **ueber die Maschine** spricht oder
den Baum ueberleben muss, liegt hier.

## Dateien

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`README.md`](../../../.claude/proposals/README.md) | Stand der Verdrahtung, Inhaltstabelle, historische Merge-Anleitung, Kurzfassung der Recherche zu PreCompact- und Notification-Hooks. | — |
| [`statusline.py`](../../../.claude/proposals/statusline.py) | Die Statuszeile: `[Modell] Verzeichnis \| Branch \| ctx nn% \| $Kosten`. Liest das Session-JSON von stdin. Reine Stdlib, kein `jq` (auf dieser Box nicht installiert). Faellt weich: jeder Fehler druckt trotzdem eine minimale Zeile, die UI stuerzt nie ab. | `git_branch`, `main`, `DIM`, `YELLOW`, `RED`, `RESET` |
| [`orient.py`](../../../.claude/proposals/orient.py) | User-Level-Hook fuer SessionStart (`startup\|resume\|clear\|compact\|fork`) und CwdChanged: sagt **eine** Sache, wenn das Repository der Sitzung in `~/.claude/hooks/roots.json` gelistet ist — aktiver Baum oder archivierter Baum (mit Nennung des aktiven). Fuer jedes andere Verzeichnis schweigt er, denn die meisten Projekte sind nicht Daedalus. | `classify`, `main`, `ROOTS_FILE` |
| [`hook_notification_toast.py`](../../../.claude/proposals/hook_notification_toast.py) | Notification-Hook: Windows-Popup ueber `WScript.Shell` (kein Zusatzmodul, schliesst sich nach 6 s) bei `permission_prompt`, `agent_needs_input`, `agent_completed` — fuer unbeaufsichtigte lange Laeufe. Notification-Hooks koennen nichts blockieren; das ist rein additive UX. | `main`, `INTERESTING` |
| [`roots.example.json`](../../../.claude/proposals/roots.example.json) | Vorlage fuer `~/.claude/hooks/roots.json`: `live` als Liste, `archived` als Abbildung Pfad → Archiv-Tag. | — |
| [`settings.hooks.snippet.json`](../../../.claude/proposals/settings.hooks.snippet.json) | Zu mergendes `hooks`-Objekt: PreCompact ueber `daedalus/hooks/__main__.py`, plus optionaler `Notification`-Eintrag mit Matcher. | — |
| [`settings.statusline.snippet.json`](../../../.claude/proposals/settings.statusline.snippet.json) | Das `statusLine`-Objekt zum Mergen. | — |

## Verhalten im Detail

`statusline.py` liest `model.display_name`, `workspace.current_dir` (bzw.
`cwd`), ruft `git rev-parse --abbrev-ref HEAD` mit 2 s Timeout auf und wertet
`context_window.used_percentage` sowie `cost.total_cost_usd` aus. Die
Kontextanzeige wechselt bei 60 % auf gelb und bei 85 % auf rot; Kosten werden
nur gezeigt, wenn sie groesser null sind.

`orient.classify(cwd, roots)` normalisiert Pfade (Backslashes zu Slashes,
Kleinschreibung unter Windows) und loest zuvor das Git-Toplevel auf, damit ein
Unterverzeichnis dieselbe Antwort erhaelt wie die Wurzel. Bei einem
archivierten Baum nennt die Zeile den Archiv-Tag, verweist auf den aktiven
Baum **und** warnt ausdruecklich, dass Serena/MCP-Server dieser Sitzung den
archivierten Baum indizieren — dieselbe Vorfallklasse, gegen die
`daedalus/hooks/tools.py` die Serena-Schreibsperre stellt. Bei SessionStart
geht die Zeile als reines stdout in den Kontext, sonst als JSON mit
`systemMessage` und `hookSpecificOutput.additionalContext`.

Alle drei Skripte enden auf jedem Pfad mit 0 und fangen ihre Ausnahmen
selbst — dieselbe Regel wie im Paket `daedalus/hooks`: ein Hook, der wirft,
kostet einen Turn, und nichts hier ist einen Turn wert.

## Trust-Grenzen / Effekte

- **Kein registrierter Einstiegspunkt.** Keine Datei dieses Verzeichnisses
  steht in
  [`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py),
  und keine ruft `begin_effect`. Das ist kein Versaeumnis, sondern folgt aus
  ihrem Ort: sie laufen als Kopien im Home-Verzeichnis unter der
  Claude-Code-Harness, nicht als Prozesse dieses Repositories. Was **in**
  diesem Baum laeuft, geht ueber den registrierten Dispatcher `daedalus.hooks`.
- **Prozessstart.** `statusline.py` und `orient.py` starten `git`
  (Timeout 5 s bzw. 2 s), `hook_notification_toast.py` startet
  `powershell -NoProfile -WindowStyle Hidden` (Timeout 8 s). Kein Netzwerk,
  kein Schreibvorgang, keine Secrets.
- **Read-only auf dem Repository.** Keine Datei schreibt irgendetwas; `orient.py`
  liest genau eine Datei (`ROOTS_FILE`, also `roots.json` neben sich selbst im
  Home-Verzeichnis) und schweigt still,
  wenn sie fehlt oder unparsbar ist.
- **Der Preis der Kopie.** Weil die laufenden Instanzen Kopien unter
  `~/.claude/hooks/` sind, kann dieses Verzeichnis von dem abweichen, was
  tatsaechlich laeuft. Es gibt keinen Test und keinen Mechanismus, der die
  Gleichheit prueft.

## Tests

Es gibt keinen Test, der diese Skripte ausfuehrt. Eine einzige Assertion im
Baum bezieht sich auf dieses Verzeichnis:

| Testdatei | Was sie prueft |
| --- | --- |
| [`tests/test_hooks_precompact.py`](../../../tests/test_hooks_precompact.py) | Zeile 93: dass `.claude/proposals/hook_precompact_vault.py` **nicht mehr existiert** — der PreCompact-Hook ist in `daedalus/hooks/events.py:pre_compact` gewandert, und die alte Vorschlagskopie darf nicht als zweiter Pfad zurueckkommen |

Die README nennt zum Handtest der Statusline:
`echo {"model":{"display_name":"Test"}} | python .claude/proposals/statusline.py`.

## Verwandt

- [Hooks](../architecture/hooks.md) — der registrierte Dispatcher, in den der
  PreCompact-Hook gewandert ist, und die Serena-Falschbaum-Sperre, deren
  Vorfall `orient.py` von der anderen Seite adressiert
- [Tooling / Tools](tools.md) und [Tooling / Scripts](scripts.md) — die
  uebrigen Werkzeugflaechen des Repositories
- [Spine](../architecture/spine.md) — die Effektgrenze, an der dieses
  Verzeichnis bewusst nicht haengt
- [Lanes](../architecture/lanes.md) — parallele Sitzungen, fuer die die
  Baumorientierung ueberhaupt eine Frage ist
- [Tool-Vetting](../tool-vetting.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Ob die Kopien unter `~/.claude/hooks/` mit dem Stand dieses
  Verzeichnisses uebereinstimmen. Ich habe ausserhalb des Repositories nichts
  gelesen.
- **Abweichung Doku/Konfiguration:** Die README beschreibt
  `settings.statusline.snippet.json` und den `Notification`-Block aus
  `settings.hooks.snippet.json` als zu mergende Vorschlaege. In
  `.claude/settings.json` dieses Baums steht (gemessen 2026-09-05) **kein**
  `statusLine`-Schluessel und **kein** `Notification`-Hook; PreCompact
  dagegen ist verdrahtet, allerdings mit einer anderen `statusMessage` als im
  Snippet. Die Statusline laeuft laut README ohnehin user-global, aber der
  Notification-Toast ist damit in diesem Baum nicht aktiv.
- **Abweichung Doku/Code:** Die Inhaltstabelle der README fuehrt eine Zeile
  `daedalus/hooks/events.py` — also eine Datei, die gar nicht in diesem
  Verzeichnis liegt. Das ist als Verweis gemeint (der PreCompact-Hook lebt
  dort), liest sich in einer Tabelle ueber `.claude/proposals` aber wie ein
  Verzeichniseintrag.

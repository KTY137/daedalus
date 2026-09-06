---
title: Hooks — der Kontextkanal der Sitzung
type: module
status: living
updated: 2026-09-05
covers: daedalus/hooks
---
# Hooks — der Kontextkanal der Sitzung

`daedalus/hooks` ist der eine Prozess, der auf jedes Claude-Code-Hook-Ereignis
dieses Repositories antwortet: Sitzungsstart, Prompt, Tool-Aufruf, Subagent,
Konfigurationsaenderung, Kompaktierung. Er sagt der Sitzung, in welchem Baum
sie steht, was sich seit dem letzten Mal geaendert hat, wer sonst noch
arbeitet — und er verweigert genau eine Sache: Serena-**Schreib**-Tools, wenn
Serenas konfiguriertes Projekt-Root nicht der Baum ist, in dem die Sitzung
arbeitet.

Im Bild von Kernel/Ikarus/Ariadne gehoert das Paket zu keiner der drei
Produktachsen: es ist Werkzeugumgebung fuer die Agenten, die am Repository
arbeiten. Es ist aber ein **registrierter effektbehafteter Einstiegspunkt**
(siehe unten), weil es Zustand und ein Ledger schreibt, `git` startet, einen
Loopback-Port sondiert und — nur bei gesetztem Schalter — `gh` gegen
github.com startet.

Warum ein Paket und ein Prozess pro Ereignis: bis 2026-08-23 liefen vier
getrennte Skripte bei jedem Prompt. Jedes kostete einen Python-Start (75 ms
auf dieser Box), und die Crew-Zaehlung scannte den kompletten
`%TEMP%/claude`-Baum — 129.434 Dateien, 7,7 s pro Prompt, gemessen. Ausserdem
loesten sie das Repository aus ihrem eigenen `__file__` auf, sodass eine
Sitzung im aktiven Baum die Daten des archivierten Baums vorgesetzt bekam. Der
Dispatcher behebt beides: ein Einstieg (`python -m daedalus.hooks <event>`),
und das Repository ist immer das Git-Toplevel des `cwd`, den die Harness
uebergibt.

Gemessen 2026-09-05: 7 `.py`-Dateien, 2343 Zeilen.

## Was ein Hook sagen darf — und was nie

Hook-Ausgabe landet im Kontext des Modells und konkurriert mit der Aufgabe um
Aufmerksamkeit. Zwei Transformer-Eigenschaften uebertragen sich woertlich auf
diesen Kanal, und beide sind im Design verankert:

- **Softmax-Konkurrenz.** Jedes injizierte Token konkurriert mit
  Aufgaben-Token, also ist die Ausgabe pro Turn budgetiert
  (`TURN_BUDGET_CHARS` = 1500 Zeichen) und wird gemessen
  (`runs/hooks/ledger.jsonl`).
- **Positionsbias.** Der gecachte Prefix (SessionStart) und der letzte Turn
  (UserPromptSubmit) werden beachtet, die Mitte nicht. Also steht die
  Orientierungskarte vorne und wird bei Kompaktierung neu gesetzt, die
  Zielzeile hinten, und selten Wechselndes wird nicht wiederholt: **Schweigen
  heisst unveraendert**, und die SessionStart-`LEGEND` sagt das einmal.

Verboten ist: einen Turn zu brechen (jeder Pfad endet mit Exit 0), den
Masterplan zu erzwingen (der Owner hat die mechanische Durchsetzung am
2026-08-22 zurueckgezogen) oder Lesen zu blockieren. `AGENTS.md` nennt "ein
Guard, der Lesen oder Messen blockiert" ausdruecklich einen
release-blockierenden Defekt.

## Module

| Modul | Aufgabe | Wichtige oeffentliche Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/hooks/__init__.py) | Nur Docstring: Begruendung des Pakets, Kontextbudget-Regeln, Effektgrenze. Kein Code. | — |
| [`__main__.py`](../../../daedalus/hooks/__main__.py) | Der eine Einstieg `python -m daedalus.hooks <event>`: Payload von stdin, Antwort auf stdout, Exit immer 0, eine Ledger-Zeile pro dispatchtem Aufruf. | `HANDLERS`, `ENTRYPOINT_ID`, `dispatch`, `start_effect`, `main` |
| [`_common.py`](../../../daedalus/hooks/_common.py) | Gemeinsame Mechanik: Payload, Repository-Root, Sitzungszustand mit Dateisperre, Ledger, Budgets, Deadline-Wrapper, `git`-Aufruf. Reine Stdlib; jede Funktion faellt Richtung "tue nichts". | `HookResult`, `GitOut`, `Timing`, `payload_is_usable`, `read_payload`, `git`, `with_deadline`, `repo_root`, `safe_session_id`, `hooks_dir`, `display_name`, `state_path`, `load_state`, `update_state`, `ledger_append`, `trim_lines`, `trim_to_budget`, `clip_block`, `sha256_text`, `now_iso`, `TURN_BUDGET_CHARS`, `LOCK_TIMEOUT_S`, `LOCK_STALE_S`, `LOCK_POLL_S`, `GIT_TIMEOUT_S`, `LEDGER_MAX_BYTES`, `HOOKS_DIR_REL` |
| [`_tree.py`](../../../daedalus/hooks/_tree.py) | Fakten ueber den Baum, in dem die Sitzung steht — alles aus `git`, `.mcp.json` und dem Sweeps-Log abgeleitet, nichts aus einer Uhr. | `TreeFacts`, `tree_facts`, `dirty_summary`, `archived_tag`, `last_sweep`, `source_fingerprint`, `fingerprint_diff`, `serena_configured_root`, `serena_root_mismatch`, `SERENA_WRITE_TOOLS`, `SOURCE_SCOPES`, `SWEEPS_LOG_REL`, `UNREADABLE_KEY` |
| [`events.py`](../../../daedalus/hooks/events.py) | Die kontexttragenden Ereignisse: SessionStart, UserPromptSubmit, SessionEnd, SubagentStart/Stop, ConfigChange, PreCompact. | `session_start`, `user_prompt`, `session_end`, `subagent_start`, `subagent_stop`, `config_change`, `pre_compact`, `MIN_PARALLEL`, `AGENT_STALE_S`, `ARCH_DELTA_CHARS`, `SHIFT_BUDGET_S`, `ARCH_BUDGET_S`, `CREW_TARGETS`, `LEGEND`, `COMPACTION_SECTION` |
| [`tools.py`](../../../daedalus/hooks/tools.py) | Tool-Ereignisse: PreToolUse (Serena-Routing, Falschbaum-Schreibsperre) und PostToolUse (Testlauf-Fingerabdruck, Docs-Drift-Erinnerung). | `pre_tool`, `post_tool`, `serena_mode`, `serena_is_reachable`, `transcript_mentions`, `line_count`, `grep_nudge`, `read_nudge`, `SERENA_HOST`, `PROBE_TIMEOUT_S`, `WHOLE_FILE_LINE_THRESHOLD`, `SOURCE_SUFFIXES`, `DEFINITION_PATTERN`, `TEST_COMMAND`, `COMMIT_COMMAND`, `SHELL_TOOLS`, `DOCS_DRIFT_REMINDER`, `ADVISED_CAP` |
| [`crosstalk.py`](../../../daedalus/hooks/crosstalk.py) | Der einzige Ort, der mit GitHub spricht: parallele Sitzungen kuendigen sich in GitHub Discussions an und lesen einander zurueck. Traegt die gesamte Redaktion. | `Channel`, `Note`, `TransportError`, `enabled`, `gh_graphql`, `render`, `redact_paths`, `announce`, `report`, `poll`, `threads_for`, `dirty_paths`, `short_sid`, `now_iso`, `main`, `ENV_ENABLE`, `ENV_PUBLIC`, `ENV_CATEGORY`, `ENV_REPO`, `GLOBAL_THREAD`, `CROSSTALK_BUDGET_S`, `TURN_BUDGET_S`, `GH_TIMEOUT_S`, `POLL_TTL_S`, `WITHHELD`, `SECRET_PAT`, `ABS_PAT` |

### Der Dispatcher

`dispatch(event, payload, receipt)` ist **nicht ohne Effekt-Beleg aufrufbar**:
`receipt.entrypoint_id` muss `daedalus.hooks` sein, sonst `PermissionError`.
Das ersetzt ein frueheres freies `run()`, das eine produktiv aufrufbare Naht
um die Grenze herum war. Ein Handler-Fehler kostet keinen Turn — die Exception
wird als `note` protokolliert, nicht geworfen. `HANDLERS` bildet die neun
Ereignisnamen auf die Funktionen in `events.py` und `tools.py` ab; ein
unbekanntes Ereignis erzeugt `unknown-event:<name>`.

Jeder **dispatchte** Aufruf haengt eine Ledger-Zeile an: Zeitstempel, Session,
Prompt-ID, Ereignis, injizierte Zeichen, Millisekunden, Notiz. Auch eine
unbrauchbare Payload bekommt eine Zeile — aber nur dort, wo die Hooks ohnehin
schon Zustand halten, denn `runs/hooks/` in irgendeinem fremden Verzeichnis
anzulegen waere der Hook, der ausserhalb seines Repositories Zustand erfindet.
Der eine Aufruf, der **keine** Zeile hinterlassen kann, ist eine
Grenz-Verweigerung: die Zeile zu schreiben waere selbst der
`filesystem_write`, der gerade verweigert wurde. Eine Verweigerung meldet sich
nach stderr und nirgends sonst.

### Baumfakten

`tree_facts` liefert `TreeFacts` mit `name`, `branch`, `head`, `dirty_count`,
`dirty_dirs`, `archived_tag`, `serena_mismatch`, `serena_configured` und
`unreadable`. `tree_line()` rendert die ASCII-Zeile, die eine Sitzung als
erstes sieht. `unreadable` ist der ehrliche Teil: ein `git`-Aufruf, der nicht
gelesen werden konnte, wird **in der Zeile selbst genannt** ("those facts are
MISSING, not absent"), weil ein Schnappschuss, der den Dirty-Count leise
verschluckt, exakt wie ein sauberer, nicht archivierter Baum aussieht — und
das ist die Lesart, die etwas kostet. Die `GitOut`-Klasse in `_common.py`
traegt diese Unterscheidung auf Aufrufebene.

`source_fingerprint` bildet die Scopes `daedalus`, `tools`, `tests`, `scripts`
auf Digests ab; `fingerprint_diff` liefert daraus die "was hat sich seit
Sitzungsbeginn geaendert"-Zeile. `UNREADABLE_KEY` (`~git-unreadable`) ist als
**Schluessel im Fingerabdruck** kodiert und nicht als zweiter Rueckgabewert,
weil `tools.post_tool` Fingerabdruecke woertlich speichert und
`sorted(fp.items())` hasht.

### Serena-Routing und die Falschbaum-Sperre

`tools.pre_tool` hat zwei getrennte Mechanismen:

1. **Routing-Nudge**, geschaltet ueber `DAEDALUS_SERENA_HOOK`. `advise`
   (Default): ein Grep, der in Wahrheit eine Symbolsuche ist
   (`DEFINITION_PATTERN`), oder ein Ganzdatei-`Read` einer grossen Quelldatei
   (`WHOLE_FILE_LINE_THRESHOLD` = 120 Zeilen, `SOURCE_SUFFIXES`), die Serena
   noch nicht beschrieben hat, geht **unveraendert** durch und bekommt eine
   einzeilige Serena-Empfehlung als `additionalContext` mitgegeben — einmal
   pro Datei/Muster pro Sitzung, damit sie nicht zur Tapete wird. `deny`: der
   Aufruf wird mit demselben Text als Grund verweigert (das Verhalten von
   Amendment 003, 2026-08-21). `off`: gar kein Nudge. Der Default ist `advise`,
   weil `AGENTS.md` vom 2026-08-22 einen lesenden Guard als Defekt fuehrt.
   Fail-open per Konstruktion: der Nudge feuert nur, wenn Serenas
   Dashboard-Port auf `127.0.0.1` antwortet (`PROBE_TIMEOUT_S` = 0,15 s);
   gezielte Reads mit `offset`/`limit`, kleine Dateien und Dateien, die ein
   Serena-Tool in dieser Sitzung schon angefasst hat, passieren immer.
2. **Die Falschbaum-Schreibsperre.** Unabhaengig vom Modus und ohne
   beratenden Zwischenmodus: wenn `serena_root_mismatch(root)` ein anderes
   Root meldet, werden die Tools in `SERENA_WRITE_TOOLS` (elf Namen:
   `replace_symbol_body`, `insert_after_symbol`, `insert_before_symbol`,
   `replace_content`, `replace_in_files`, `rename_symbol`,
   `safe_delete_symbol`, `write_memory`, `edit_memory`, `delete_memory`,
   `rename_memory`) verweigert. Das ist der Vorfall vom 2026-08-22, bei dem
   vier Edits im archivierten Baum landeten. Die Sperre blockiert
   **Schreiben**, nie Lesen.

`tools.post_tool` reagiert auf `Bash`/`PowerShell`: nach einem erkannten
Testlauf (`TEST_COMMAND`, inklusive `cd ... &&`- und `uv run`-Praefix) wird der
Quell-Fingerabdruck gespeichert; vor einem `git commit` (`COMMIT_COMMAND`)
erinnert `DOCS_DRIFT_REMINDER` an die Dokumentation.

### Crosstalk

`crosstalk.py` ist der einzige Ort mit Transport nach aussen und der einzige,
der entscheidet, was die Maschine verlassen darf. Zwei Regeln bestimmen alles:

- **Fail-open.** Das ist eine Anzeigeflaeche, keine Vertrauensgrenze. Ein
  GitHub-Ausfall darf eine Notiz im injizierten Text kosten, nie einen
  verweigerten Tool-Aufruf.
- **Redaktion ist ein Netz, keine Gewohnheit.** `render` saeubert jeden
  Koerper auf dem Weg nach draussen (`SECRET_PAT`, `ABS_PAT`, `PATH_SHAPED`;
  entfernte Pfade werden durch `WITHHELD` ersetzt). Unterdruecktes wird
  **gezaehlt und im Koerper genannt** — ein Bericht, der leise schrumpft, ist
  von einem sauberer gewordenen Baum nicht zu unterscheiden.

Der Kanal ist **aus**, solange nicht `DAEDALUS_CROSSTALK=on` gesetzt ist, und
verweigert das Posten in ein nicht-privates Repository ohne
`DAEDALUS_CROSSTALK_PUBLIC=1` (`Channel._may_post`). `Channel` spricht ueber
`gh` GraphQL; `announce` postet einmal pro Sitzung (auch `compact` feuert
SessionStart, und eine bei jeder Kompaktierung neu ankuendigende Sitzung
wuerde den Thread begraben, den sie lesbar machen will), waehrend die
**Rueckleseoperation bei jedem Start laeuft** — genau dann ist der Kontext,
den sie ersetzt, gerade weggeworfen worden.

### Zeitbudgets

Jeder externe Aufruf hat eine Deckelung, und die Deckelungen sind gemessen
entstanden: `GIT_TIMEOUT_S` 5 s pro `git`-Aufruf, `SHIFT_BUDGET_S` 2 s und
`ARCH_BUDGET_S` 3 s fuer die beiden Python-seitigen Abhaengigkeiten
(Kommentar in `events.py:39-43`: eine Turn-Zeile las 139.592 ms, und ein
direkter `render_delta`-Aufruf ueberschritt 120 s auf diesem Baum),
`CROSSTALK_BUDGET_S` 6 s beim Start, `TURN_BUDGET_S` 3 s pro Prompt,
`GH_TIMEOUT_S` 6 s pro `gh`-Aufruf, `POLL_TTL_S` 300 s Cache fuer den
Rueckleseweg. `with_deadline` ist der gemeinsame Wrapper; er liefert bei
Ablauf einen Default statt einer Exception. Der Architektur-Delta hat mit
`ARCH_DELTA_CHARS` (600) ein **eigenes** Zeichenbudget, weil ein Block ohne
eigenes Budget um das ganze Turn-Budget konkurriert und der Trimmer diesen
Streit durch Loeschen entscheidet.

## Trust-Grenzen / Effekte

- **Registrierte Einstiegspunkte.** In
  [`effect_boundary.py`](../../../daedalus/spine/effect_boundary.py) stehen
  zwei Zeilen fuer dieses Paket:
  - `daedalus.hooks` → `daedalus.hooks.__main__:main`, Effekte
    `FILESYSTEM_WRITE`, `PROCESS_SPAWN`, `NETWORK_EGRESS`, Guard-Contract
    `budget.process_guard`, `Wiring.CENTRAL`, Anker
    `daedalus.hooks.__main__:main` mit `begin_effect`. Die Notiz haelt fest,
    dass der Egress seit 2026-09-03 **nicht mehr loopback-only** ist, statt die
    alte Begruendung stehen zu lassen.
  - `daedalus.hooks.crosstalk` → `daedalus.hooks.crosstalk:main`, Effekte
    `NETWORK_EGRESS`, `PROCESS_SPAWN`. Kein `SECRETS`-Effekt: das Token haelt
    `gh`, dieses Paket fasst keins an.
- **`begin_effect` ist das Erste.** `start_effect()` holt den Beleg ueber
  `spine.effect_boundary.begin_effect` mit
  `daedalus.budget.process_guard_boundary_decision()`. Schlaegt das fehl —
  Verweigerung, unbekannte Zeile oder Importfehler — wird das nach stderr
  gemeldet und der Prozess endet trotzdem mit 0.
- **Die Schreiber.** `_common.ledger_append` (Ledger, mit
  `LEDGER_MAX_BYTES`-Rotation), `_common.update_state` /
  `_common._write_atomic` (Sitzungszustand unter `runs/hooks/`, atomar, unter
  `_Lock` mit `LOCK_TIMEOUT_S`/`LOCK_STALE_S` und gejittertem Polling — 20 ms
  festes Polling liess gemessen am 2026-08-23 einen von acht Prozessen ueber
  2 s verhungern) und `events._append_compaction_marker` (Marker in die
  heutige Vault-Daily-Note unter `vault/Sessions/`). Sonst schreibt nichts.
- **Read-only.** `_tree.py` ist vollstaendig lesend; `tools.serena_is_reachable`
  oeffnet nur einen TCP-Socket auf `127.0.0.1` und liest nichts.
- **Der einzige Deny.** Die Serena-Schreibsperre. Alles andere in diesem Paket
  ist beratend oder still.
- **Kein Sicherheitsversprechen.** Der Masterplan (Abschnitt 1) sagt, dass
  kein Modell-Prompt und kein lokaler Hook eine Sicherheitsgrenze ist. Diese
  Hooks verhindern gewoehnliche versehentliche Drift; sie decken keinen
  externen Client, kein `--no-verify` und keinen direkten Dateisystem-Schreiber
  ab.

## Tests

Gemessen 2026-09-05: 6 Testdateien mit 3088 Zeilen importieren
`daedalus.hooks`.

| Testdatei | Deckt ab |
| --- | --- |
| [`tests/test_hooks_v2.py`](../../../tests/test_hooks_v2.py) | Der Hauptteil: Dispatcher, Handler, Zustand, Ledger, Trimmen, Serena-Routing und -Sperre |
| [`tests/test_hooks_review_20260825.py`](../../../tests/test_hooks_review_20260825.py) | Die Befunde des Reviews vom 2026-08-25 als Regressionen (u. a. Zeitbudgets, `unreadable`) |
| [`tests/test_hooks_precompact.py`](../../../tests/test_hooks_precompact.py) | PreCompact-Marker in der Vault-Daily-Note; prueft ausserdem, dass das alte Vorschlagsskript `.claude/proposals/hook_precompact_vault.py` **nicht** mehr existiert |
| [`tests/test_crosstalk.py`](../../../tests/test_crosstalk.py) | Redaktion, Schalter, GraphQL-Transport ueber ein injiziertes Transport-Objekt, Zaehlung unterdrueckter Pfade |
| [`tests/test_watchdog.py`](../../../tests/test_watchdog.py) | Die Watchdog-Anomalien, die `events.user_prompt` als Delta einblendet |
| [`tests/contracts/test_import_scc_hierarchy.py`](../../../tests/contracts/test_import_scc_hierarchy.py) | Importgraph-Vertrag; haelt das Paket von Zyklen frei |

## Verwandt

- [Spine](spine.md) — `effect_boundary`, `begin_effect`, die Registry-Zeilen
- [Tooling / Claude-Proposals](../tooling/claude-proposals.md) — die
  Vorschlagskopien (`statusline.py`, Notification-Toast, `orient.py`), aus
  denen der PreCompact-Hook in dieses Paket gewandert ist
- [Council](council.md) — die andere Stelle mit Prozessstart und Egress, dort
  aber fail-closed
- [Tooling / Tools](../tooling/tools.md) — `tools/watchdog.py` und die uebrigen
  registrierten Werkzeug-Einstiege
- [Interfaces / CLI](interfaces-cli.md) — `arch_memory.render_delta`, das der
  UserPromptSubmit-Handler aufruft
- [Memory](memory.md) — Architektur-Gedaechtnis und Vault, in die die Hooks
  hineinschreiben bzw. aus denen sie lesen
- [Lanes](lanes.md) — parallele Sitzungen, die Crosstalk sichtbar macht
- [Agents hold no state](../decisions/agents-hold-no-state.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** `CREW_TARGETS` in `events.py` ist eine Konstante, deren
  Inhalt ich nicht vollstaendig gelesen habe; sie steuert die Zeile "where
  work goes", die erscheint, sobald mindestens `MIN_PARALLEL` (4) Agenten
  leben.
- **Ungeklaert:** Ob `crosstalk.main` (`python -m daedalus.hooks.crosstalk
  say "..."`) ausser von Hand noch von etwas anderem aufgerufen wird; im
  Verzeichnis selbst ruft ihn nichts auf.
- **Abweichung Code/Konfiguration:** `.claude/settings.json` verdrahtet neun
  Ereignisse gegen `daedalus/hooks/__main__.py`; die
  `Notification`-Verdrahtung aus
  [`.claude/proposals/settings.hooks.snippet.json`](../../../.claude/proposals/settings.hooks.snippet.json)
  ist dort **nicht** eingetragen (gemessen 2026-09-05), obwohl die
  Proposals-README das Snippet als merge-fertig beschreibt.
- **Ungeklaert:** `_common.trim_lines` und `_common.trim_to_budget` existieren
  beide; welcher der beiden der kanonische Trimmer ist, geht aus den
  Docstrings nicht eindeutig hervor — `events.session_start` benutzt
  `trim_lines`.

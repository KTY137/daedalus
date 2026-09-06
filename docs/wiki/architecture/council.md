---
title: Council — der vendoruebergreifende Rat
type: module
status: living
updated: 2026-09-05
covers: daedalus/council
---
# Council — der vendoruebergreifende Rat

`daedalus/council` ist die Stelle, an der mehrere unabhaengige Modell-Anbieter
dieselbe Frage ueber derselben Evidenz beantworten und jedes Wort davon in ein
manipulationsevidentes Protokoll geschrieben wird. Das Paket produziert
**Evidenz, kein Urteil**. Der Paket-Docstring in
[`__init__.py`](../../../daedalus/council/__init__.py) sagt es als Satz, den
das ganze Paket strukturell durchhaelt: *THE GATE DECIDES, NOT A MODEL*.

Im Bild des Masterplans sitzt das Paket auf der Ikarus-Seite (Abschnitt 7:
"Modelle erhalten keine Autoritaet dadurch, dass sie als Stimme ausgewaehlt
werden") und liefert dem Kernel nichts, was der Kernel als Entscheidung lesen
koennte. Invariante 4 (Evidenzgrenze) und die Verbotsliste in Abschnitt 13
("ein LLM-Urteil als harte Korrektheits- oder Promotion-Schranke") sind hier
nicht als Kommentar, sondern als **Abwesenheit von Feldern** umgesetzt: weder
`VendorReply` noch `CouncilRecord` noch `Claim` tragen ein approve/reject/
score/majority/consensus/confidence-Feld, und ein Test laeuft jedes Feld jeder
verschachtelten Dataclass ab, damit keins nachwaechst. Das Produkt eines Rats
ist eine **Warteschlange von Checks** fuer das bestehende deterministische
Gate.

Das Paket traegt sein eigenes Falsifikationsprotokoll im Docstring: Arm A sind
vier Vendors mit je einer Runde, Kontrollarm B ist *ein* Vendor zweimal unter
zwei Rollen-Prompts, Ground Truth sind `GateResult.passed` und
`AttemptResult.state` aus dem Spine. Liegt die Uebereinstimmung zwischen
Vendors im Rauschen der Uebereinstimmung innerhalb eines Vendors, soll das
Modul geloescht werden. Der Docstring von
[`session.py`](../../../daedalus/council/session.py) stellt selbst fest, dass
diese Messung **noch nicht gelaufen** ist: "`--live` buys transcripts, not
evidence."

Gemessen 2026-09-05: 6 `.py`-Dateien, 5847 Zeilen.

## Module

| Modul | Aufgabe | Wichtige oeffentliche Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/council/__init__.py) | Paket-Docstring mit Falsifikationsprotokoll; re-exportiert ausschliesslich die Bus-API. | `ENTRY_VERSION`, `TURN_STATUS`, `actor_id`, `append_roster`, `append_round`, `append_turn`, `council_store_path`, `evidence_ref`, `load_transcript`, `transcript_head`, `verify_chain` |
| [`bus.py`](../../../daedalus/council/bus.py) | Das Transkript: append-only, hash-verkettetes JSONL unter `runs/council/<council_id>.jsonl`, offline verifizierbar. Enthaelt ausserdem den Secret-Floor beim Schreiben. | `ENTRY_VERSION`, `ANCHOR_VERSION`, `TURN_STATUS`, `UNAVAILABLE_REASONS`, `ANOMALY_REASONS`, `PARTICIPANT_OUTCOMES`, `MAX_CONTENT_CHARS`, `canonical_body`, `canonical_body_json`, `actor_id`, `evidence_ref`, `council_store_path`, `anchor_path`, `append_round`, `append_turn`, `append_roster`, `load_transcript`, `transcript_head`, `read_anchor`, `verify_chain` |
| [`vendors.py`](../../../daedalus/council/vendors.py) | Vier uniforme Adapter (`anthropic`, `openai`, `google`, `local`) mit derselben `ask`-Form, plus Secret-Floor, Prozessfuehrung und die Profile, die einen Reviewer zu einer Completion statt zu einem Agenten machen. | `STATUSES`, `LANES`, `UNAVAILABLE_REASONS`, `PROMPT_DATA_NOTICE`, `VendorReply`, `FloorRefusal`, `RunResult`, `floor_check`, `council_env`, `council_cwd`, `run_managed`, `CouncilProfile`, `COUNCIL_PROFILES`, `FORBIDDEN_ARG_FRAGMENTS`, `CouncilAdapter`, `ClaudeAdapter`, `CodexAdapter`, `AntigravityAdapter`, `OllamaAdapter`, `VendorAvailability`, `available_vendors`, `actor_id`, `model_family`, `reply_field_names` |
| [`session.py`](../../../daedalus/council/session.py) | Der eine Einstiegspunkt `convene`: Rollen, Runden, Budgets, Live-Sperre, Claim-Extraktion, `CouncilRecord`. | `convene`, `dry_run_plan`, `new_council_id`, `Evidence`, `Claim`, `TurnRef`, `ParticipantRecord`, `CouncilRecord`, `default_participants`, `live_egress_seats`, `LiveCouncilRefused`, `MAX_ROUNDS_CAP`, `DEFAULT_ROUNDS`, `DEFAULT_PER_CALL_TIMEOUT_S`, `DEFAULT_WALL_CLOCK_S`, `DEFAULT_TOKEN_CEILING`, `DEFAULT_ROLES`, `ROLE_BRIEFS`, `END_REASONS`, `VENDOR_KEYS` |
| [`canary.py`](../../../daedalus/council/canary.py) | Der Vendor-Canary: billige, wiederholbare Gesundheitspruefung jeder Modell-Spur mit vier deterministischen Sonden. | `CANARY_STATUSES`, `SEVERITIES`, `FAILING_STATUSES`, `SCHEMA_VERSION`, `PROBES`, `ProbeSpec`, `ProbeResult`, `Comparison`, `CanaryRun`, `Lane`, `probes_for`, `default_lanes`, `live_egress_lanes`, `LiveCanaryRefused`, `grade`, `run_canary`, `dry_run_plan`, `load_history`, `append_history`, `compare_to_history`, `render_table`, `new_nonce`, `build_arrival`, `check_arrival`, `build_instruction`, `check_instruction`, `build_anchoring`, `check_anchoring`, `build_comprehension`, `check_comprehension`, `resolve_exe` |
| [`publish.py`](../../../daedalus/council/publish.py) | Die GitHub-PR-Bruecke: rendert ein gespeichertes Transkript als Markdown-Kommentar und liest den PR-Thread zurueck. Schreibt nie in den Bus. | `STATUSES`, `PUBLISH_STATUSES`, `READ_STATUSES`, `STATUS_PUBLISHED`, `STATUS_DRY_RUN`, `STATUS_READ_OK`, `STATUS_REFUSED_SECRET`, `STATUS_UNSAFE_ARGUMENT`, `STATUS_NO_TRANSCRIPT`, `RunResult`, `PublishResult`, `PRTurn`, `ThreadResult`, `render_markdown`, `screen_egress`, `gh_reference_refusal`, `load_for_publish`, `publish_to_pr`, `read_pr_thread`, `DEGRADED_QUORUM_MARKER` |

### Der Bus: ein Transkript, das nicht leise luegen kann

`bus.py` schreibt pro Zeile zwei SHAs. `body_sha` deckt den Datensatz **ohne**
die vier Positions-/Identitaetsfelder `ts`, `prev`, `entry_sha`, `id` ab;
`entry_sha` ist `sha256(prev + NUL + body_sha + NUL + ts)` und bildet die
Kette. Eine geflippte Byte-Folge oder eine geloeschte **innere** Zeile bricht
die Kette, und `verify_chain` nennt die 1-basierte Zeilennummer. Abschneiden
am Ende faellt nur gegen den separat gespeicherten Anker
(`anchor_path`, Version `dcouncil-anchor/1`) auf, der Kopf und Zeilenzahl
festhaelt.

Zwei Eigenschaften sind bewusst so und nicht anders:

- **Kein Dedupe.** Die Turn-`id` ist `entry_sha[:16]`, nicht `body_sha[:16]`.
  Zwei Teilnehmer duerfen byte-identisch antworten; das zweite Vorkommen zu
  entfernen wuerde eine Stimme aus dem Protokoll loeschen.
- **Verkettung ist seriell, auch wenn Dispatch parallel ist.**
  `append_round` nimmt die Turns einer Runde in beliebiger Fertigstellungs-
  reihenfolge, sortiert sie nach der vendor-praefixierten Actor-ID, vergibt
  `seq` erst beim Verketten und stempelt **einen** Ketten-Zeitstempel pro
  Runde. Dieselben Fixture-Antworten in umgekehrter Reihenfolge ergeben
  denselben Kettenkopf. Echte Wanduhr liegt in `meta.latency_ms` /
  `meta.started_ts`, also im Koerper, nicht in der Position.

Der Store ist bewusst **getrennt vom Memory-Ledger**: `_resolve_store` weist
jeden Pfad unterhalb von `<repo>/memory/` laut zurueck. Begruendung im
Docstring: Rats-Transkripte sind Modell-Geschwaetz, und drei uebereinstimmende
Turns als drei Bestaetigungen in zertifizierte Erinnerung zu befoerdern ist
genau der Fabrikationsfehler, den dieses Repository als den schlimmsten
behandelt. **Council-Records sind nie Eingabe fuer Memory-Recall** — siehe
[Memory](memory.md).

### Vendors: vier Adapter, eine Form

`vendors.py` gibt jedem Anbieter dieselbe Signatur
`ask(prompt, *, role, timeout_s, model=None) -> VendorReply`. `status` ist
dabei ein **Transport**-Status ("kamen die Bytes hin und zurueck"), kein Urteil
ueber die Arbeit.

`COUNCIL_PROFILES` sind absichtlich **nicht** die Runtime-Profile aus
`adapters.subprocess_adapter`: die tragen `--sandbox workspace-write` und
`--permission-mode dontAsk`. Ein Reviewer soll eine Completion sein, kein
Agent. Konkret: Codex laeuft als `exec --sandbox read-only` mit
`--ask-for-approval never`, Claude als `-p` mit explizit verweigerten Tools
(die `=`-Form, weil das variadische `--allowed-tools` sonst das naechste Flag
schlucken wuerde) und `--strict-mcp-config`. `FORBIDDEN_ARG_FRAGMENTS` verbietet
`workspace-write`, `danger-full-access`, `dontAsk`, `acceptEdits`,
`bypassPermissions` und die beiden `--dangerously-*`-Flags irgendwo in einem
Council-argv; `_assert_profile_safe` prueft das. Jeder Subprozess startet in
einem **frischen leeren Temp-Verzeichnis** (`council_cwd`), das weder das
Repository noch ein Worktree ist; Evidenz erreicht ein Modell ueber den Prompt
oder gar nicht.

`council_env` baut die Subprozess-Umgebung und **entfernt `OLLAMA_HOST`**.
Der Host wird stattdessen pro Aufruf explizit uebergeben, und ob er als
`local` zaehlt, entscheidet `sensitivity.lane_for_host` — die eine
Implementierung der Frage "verlassen die Bytes diese Maschine". Der Docstring
begruendet das mit einer konkreten Falsifikation: eine andere Stelle im Baum
rechtfertigt `lane="trusted"` (Tier-2-Egress aus, voller Repo-Quelltext
inline) mit "ollama ist lokal", und diese Behauptung war eine Eigenschaft
einer Umgebungsvariablen, die niemand gesetzt hatte.

### Session: Runden, Rollen, Grenzen

`convene` ist der einzige Einstiegspunkt. Runde 1 ist **blind und
verpflichtend** — jeder Teilnehmer sieht nur Frage und Evidenz, nichts von
anderen. Ab Runde 2 wird das bisherige Transkript gezeigt und **Widerlegung**
verlangt, nie Konsens; Konvergenz ist der Fehlermodus, gegen den der Rat
existiert. Prior Turns werden **aus der Kette** nachgelesen, nicht aus der
In-Memory-Antwort, damit vom Secret-Floor verweigerte Inhalte nicht in den
naechsten Prompt zurueckwandern. Rollen (`DEFAULT_ROLES`: falsifier, security,
maintainer, measurement) rotieren zwischen Runden, damit ein Vendor nicht
dauerhaft die "Security"-Stimme ist. `MAX_ROUNDS_CAP` ist 3, Default 2.

Evidenz gilt als **untrusted data**: sie wird nie in den Rollen-/
Instruktionsteil eines Prompts interpoliert. Die Rollenzeile ist
session-eigener Konstanttext, danach kommt `PROMPT_DATA_NOTICE`, und erst dann
erscheinen fremde Bytes in einem vom Adapter gerenderten Block
(`CouncilAdapter.assemble`). Meldet ein Teilnehmer Text, der an ihn adressiert
ist, wird das als erstklassiger Turn-Status `ANOMALY: instruction_in_evidence`
verkettet.

Antworten werden ueber drei Zeilenpraefixe geparst: `CLAIM:`, `CITE:`,
`CHECK:`. `Claim.checkable` ist nur wahr, wenn der Autor einen konkreten
deterministischen Check geliefert hat; eine Liste von Nicht-Checks ("none",
"n/a", "tbd", ...) faellt raus.

Harte, fail-closed und protokollierte Grenzen: Wanduhr pro Aufruf, Wanduhr pro
Rat und eine **vor dem Dispatch verrechnete** Prompt-Token-Decke
(`DEFAULT_TOKEN_CEILING`), weil Transkript-Token mit O(V^2 R^2) wachsen und ein
Aufruf-Timeout Tokenausgaben nicht begrenzt. Ein gesprengtes Budget erzeugt
einen verketteten `budget_exhausted`-Turn und beendet den Rat; eine Runde wird
nie stillschweigend gekuerzt. Jeder **angeforderte** Teilnehmer erzeugt pro
Runde genau einen verketteten Turn — Inhalt, Verweigerung, `unavailable` mit
Maschinengrund oder `budget_exhausted`. Schweigen ist nie eine Abwesenheit;
`degraded` steht im Record, sobald weniger geantwortet als angefragt wurden,
und `CouncilRecord.render` druckt das **neben** die Befunde, nicht in eine
Fussnote.

### Canary: liegt die Leitung, oder luegt sie

`canary.py` existiert wegen eines Vorfalls (2026-07-28), bei dem zwei von vier
Vendor-Spuren still kaputt waren und beide von einer Liveness-Pruefung auf
"Exit 0"/"HTTP 200" als gruen gemeldet worden waeren. Die Regel hier lautet:
jede Sonde ist ein Paar (Prompt, Checker), und **der Checker ist
deterministisches Python**. Kein Modell bewertet die Antwort eines anderen
Modells.

Vier Sonden: `arrival` (kamen die Bytes ungekuerzt an — die Sonde, die den
abgeschnittenen Prompt durch einen npm-`.cmd`-Shim faengt), `instruction`
(antwortet die Spur in der vorgegebenen Form), `anchoring` (haengt das Modell
an seinem eigenen vorigen Turn), `comprehension` (Leseverstaendnis).
`arrival`/`instruction` sind **Liveness**, `anchoring`/`comprehension` sind
**Qualitaet** — eine Qualitaets-Regression wird laut gemeldet, setzt aber den
Exit-Code nicht. Ebenso strikt getrennt: `unavailable` ("wir konnten nicht
fragen") ist kein Fehlschlag und ist nicht dasselbe wie `wrong_answer` ("wir
haben gefragt, die Antwort war falsch"); `CANARY_STATUSES` ist geschlossen und
`CanaryRun.summary` berichtet beide Gruppen getrennt.

Jeder Sondenkoerper ist **synthetisch** (generierter Fuelltext, Obstnamen,
erfundene Einzeiler). Es gibt keinen Codepfad, der eine Repository-Datei
liest — eine Canary ist nicht der Ort, an dem Quelltext die Maschine verlaesst.
Nur `127.0.0.1`/`localhost` zaehlt als lokal; die Bench ist eine andere Kiste
im Tailnet, und eine dorthin gesendete Nutzlast hat diese Maschine verlassen.
Historie liegt unter `runs/canary/history.jsonl`; `compare_to_history` bildet
das Delta gegen ein nachlaufendes Fenster.

### Publish: der Bus ist kanonisch, der PR ist eine Darstellung

`publish.py` schreibt **nie** in den Bus und leitet aus GitHub keine
Autoritaet ab. `render_markdown` traegt in jeder Darstellung den Bus-Pfad und
den Kettenkopf-Digest mit, damit ein Leser offline gegen die Datei pruefen
kann statt dem Kommentar zu glauben. Der Advisory-Banner wird
**bedingungslos** ausgegeben — auch wenn ein Aufrufer ein Verdikt ohne
`advisory`-Marker uebergibt, was laut rendert statt honoriert zu werden.
`DEGRADED_QUORUM_MARKER` macht ein degradiertes Quorum in der Darstellung
sichtbar.

`verdict` und `transcript` werden **strukturell** gelesen (Attribut oder
Dict-Key, mit toleranten Alias-Feldern) statt aus `bus.py`/`session.py`
importiert; die einzige harte Abhaengigkeit ist der Secret-Floor. `gh` wird
nur ueber ein injizierbares `runner(argv, stdin_text) -> RunResult` erreicht,
der Kommentartext geht ueber stdin (`--body-file -`), nie ueber argv.

## Trust-Grenzen / Effekte

- **Kein Write-Path, per Konstruktion.** Nichts in diesem Paket schreibt,
  editiert, wendet an oder promoviert. Die einzigen Schreiber sind
  `bus._chain_records` (Transkript unter `runs/council/`),
  `bus._write_anchor` (Anker) und `canary.append_history`
  (`runs/canary/history.jsonl`). Es gibt keinen Apply-Pfad, ueber den man
  streiten koennte.
- **Secret-Floor, zwei Kanaele, getrennt gespeist.** `sensitivity.
  secret_floor_rule` hat einen PATH- und einen CONTENT-Kanal. `bus._scan_paths`
  prueft **jeden Evidenzpfad einzeln** (dort wird ein Diff gefangen, der eine
  `.env` hinzufuegt — Content-Regexe sehen keinen Dateinamen),
  `bus._scan_texts` prueft Turn-Inhalt, jeden Ref und jeden Metadaten-String
  **je einzeln**, nie ueber den zusammengesetzten Turn. Das laeuft auf
  ausgehende Turns **und** auf eingehende Vendor-Antworten, **bevor** sie
  verkettet werden: was einmal in einer hash-verketteten Zeile steht, kann
  nicht mehr redigiert werden, ohne `verify_chain` zu brechen. Ein Treffer
  **verweigert** den Turn; an seiner Stelle wird ein `status="refused"`-Beleg
  verkettet, der **nur** das Regel-Label nennt, nie den getroffenen Text.
  In `vendors.floor_check` laeuft derselbe Boden pro Datei, bevor Bytes den
  Prozess verlassen; in `publish.screen_egress` pro Kanal, bevor `gh`
  ueberhaupt angefasst wird — auch im Dry-Run, denn ein Dry-Run ist eine
  Probe des Live-Aufrufs, kein Bypass.
- **Live-Sperre.** `convene` nimmt `live` und der Default ist `False`. Wird ein
  Adapter gesetzt, der noch einen **ausgelieferten Transport** traegt
  (`vendors.run_managed` oder `providers._ollama_native.native_chat`, beim
  Import in `_SHIPPED_TRANSPORTS` eingefroren, damit die Sperre nicht durch
  spaeteres Rebinding entwaffnet wird), wirft `LiveCouncilRefused` — bevor das
  Roster verkettet ist und bevor ein Byte verschickt wurde.
  `live_egress_seats` klassifiziert **fail-closed**: ein Sitz gilt als live,
  solange nicht gezeigt werden kann, dass der Aufrufer den Transport ersetzt
  hat. `canary.live_egress_lanes` / `LiveCanaryRefused` sind dieselbe Sperre
  fuer die Sonden. Auf der CLI ist die Zustimmung `daedalus council --live`;
  `--live --dry-run` zusammen wird als **mehrdeutig verweigert** statt ueber
  eine Praezedenzregel aufgeloest.
- **Effect-Boundary-Registrierung.** Der CLI-Einstieg ist als `cli.council`
  in [`effect_boundary.py`](../../../daedalus/spine/effect_boundary.py)
  registriert, mit den Effekten `FILESYSTEM_WRITE`, `NETWORK_EGRESS`,
  `PROCESS_SPAWN`, `PROCESS_CONTROL`, `SPEND`, Guard-Contract
  `budget.process_guard` und `Wiring.CENTRAL`; der Anker ist
  `daedalus.interfaces.cli.entry:_council` mit `begin_effect`. Auch `--dry-run`
  startet an der Grenze, weil der Start unbedingt sein muss. Siehe
  [Spine](spine.md) und [Interfaces / CLI](interfaces-cli.md).
- **Argv-Gate in `publish.py`.** `pr`-Referenz und `repo`-Slug muessen
  `_GH_REFERENCE_RE` genuegen (Beginn alphanumerisch, damit ein Wert nicht als
  Option gelesen werden kann) und werden hinter einem `--`-Trenner emittiert.
  Eine Verweigerung ist ein Status (`unsafe_argument`), keine Exception, und
  greift auch im Dry-Run.
- **Die Canary hat keine eigene zentrale Zeile.** `daedalus canary`
  ([`entry.py:861`](../../../daedalus/interfaces/cli/entry.py)) startet ueber
  `run_canary` echte Vendor-Prozesse, sendet Nutzlast an nicht-loopback-Spuren
  und schreibt `runs/canary/history.jsonl` (`append_history`, `entry.py:1023`) —
  aber es gibt weder eine `cli.canary`-Zeile in `effect_boundary.py` noch einen
  `begin_effect`-Aufruf in `_canary` (gemessen 2026-09-05). Der Aufruf liegt
  unter der Sammel-Zeile `cli.daedalus` (Ziel `entry:main`, Effekte
  `FILESYSTEM_WRITE`, `PROCESS_SPAWN`, `NETWORK_EGRESS`,
  `REPOSITORY_MUTATION`, `SPEND`; Anker `install_process_guard`; Wiring
  `LOCAL_GUARDS`): **lokal geguarded, noch nicht zentral** -- die bekannte
  Gap-Klasse `gate0.not_central` des Konformitaetsberichts, ein "gap", kein
  "blocker" und keine Umgehung der Policy. `_council` hat seine zentrale
  Zeile `cli.council` erst mit G1-COUNCIL-01 bekommen; eine analoge Zeile
  `cli.canary` mit `begin_effect` waere ein kleines Folgepacket. Was in
  `_canary` selbst steht, ist die **Spend-Sperre** (`--live` verpflichtend,
  `--live --dry-run` verweigert), nicht die Effektgrenze.
- **Fail-open ist es hier nicht.** Anders als bei den
  [Hooks](hooks.md) ist der Rat kein Anzeigeflaeche: eine Budget- oder
  Floor-Verletzung beendet oder verweigert, statt zu degradieren.

## Tests

Gemessen 2026-09-05: 8 Testdateien mit 4254 Zeilen decken das Paket direkt ab.

| Testdatei | Deckt ab |
| --- | --- |
| [`tests/test_council_bus.py`](../../../tests/test_council_bus.py) | Hash-Kette, Anker, Reihenfolge-Unabhaengigkeit, Secret-Floor beim Schreiben, Memory-Pfad-Verweigerung |
| [`tests/test_council_vendors.py`](../../../tests/test_council_vendors.py) | Adapterform, Profil-Sicherheit, `OLLAMA_HOST`-Strippen, Floor, Abwesenheit von Verdikt-Feldern |
| [`tests/test_council_session.py`](../../../tests/test_council_session.py) | Der Offline-Replay-Harness: Fake-Adapter, kein Netz, keine Vendor-CLI; Runden, Rollen, Budgets, Claim-Parsing |
| [`tests/test_council_livewire.py`](../../../tests/test_council_livewire.py) | Die Live-Sperre selbst — treibt das Gate, statt den Kommentar zu lesen |
| [`tests/test_council_canary.py`](../../../tests/test_council_canary.py) | Sonden und Checker, Status-Trennung liveness/quality, Historie |
| [`tests/test_canary_livewire.py`](../../../tests/test_canary_livewire.py) | Die Live-/Egress-Sperre der Canary |
| [`tests/test_council_publish.py`](../../../tests/test_council_publish.py) | Rendering, Egress-Screening, Statusklassifikation, injizierter Runner |
| [`tests/test_council_publish_cli.py`](../../../tests/test_council_publish_cli.py) | Die `--pr`-Unterbefehle der CLI |

Peripher beruehren das Paket ausserdem
[`tests/test_cli_effect_boundary.py`](../../../tests/test_cli_effect_boundary.py)
und [`tests/test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py)
(Registrierung von `cli.council`),
[`tests/test_host_predicate.py`](../../../tests/test_host_predicate.py)
(lokal-vs-remote-Entscheidung),
[`tests/test_budget.py`](../../../tests/test_budget.py) (Kosten eines Sitzes)
sowie [`tests/test_room_wiring.py`](../../../tests/test_room_wiring.py).

## Verwandt

- [Spine](spine.md) — Effekt-Grenze, `begin_effect`, `GateResult`
- [Memory](memory.md) — der getrennte Store, in den der Bus nie schreibt
- [Providers](providers.md) und [Runtimes / Providers](runtimes-providers.md) —
  der Anbieterkatalog, aus dem `_ollama_native` stammt
- [Runtimes / Provider](runtimes-provider.md) — die Beweiskette fuer
  Provider-Aufrufe im Kernel; der Rat geht bewusst **nicht** durch sie
- [Interfaces / CLI](interfaces-cli.md) — `daedalus council`, `daedalus canary`
- [Hooks](hooks.md) — die andere Stelle, an der dieses Repository fremde
  Prozesse startet, dort aber fail-open
- [Adapters](adapters.md) — die Runtime-Profile, von denen sich
  `COUNCIL_PROFILES` absetzt
- [Tool-Vetting](../tool-vetting.md) — verwandte Frage: was darf ueberhaupt
  aufgerufen werden
- [Agents hold no state](../decisions/agents-hold-no-state.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Ob die im Paket-Docstring beschriebene Falsifikation je
  gelaufen ist. Der Code sagt nein ("still UNRUN"), und im Baum findet sich
  kein Ergebnisartefakt dazu; ich habe nicht ausserhalb von `daedalus/` und
  `tests/` danach gesucht.
- **Ungeklaert:** Der `google`-Sitz (`AntigravityAdapter`) laeuft laut
  Docstring ueber ssh auf eine Bench-Maschine. Ob dieser Sitz auf dieser Box
  jemals geantwortet hat, ist aus dem Code nicht ablesbar; das Work-Packet
  G1-COUNCIL-02 nennt nur Claude, Codex und den lokalen Ollama-Sitz als live
  verifiziert.
- **Ungeklaert:** `bus.py` haelt einen `_APPEND_CACHE`; welche
  Invalidierungsregel er unter mehreren Prozessen hat, habe ich nicht
  vollstaendig gelesen — `_file_sig`/`_chain_state` deuten auf eine
  Signatur aus Dateimetadaten hin.
- **Abweichung Code/Doku:** Der Docstring von `session.py` korrigiert eine
  frueher dort stehende Behauptung ausdruecklich: der Offline-Replay-Harness
  sei "das Einzige, was das ausfuehrt", war ab dem Tag falsch, an dem
  `daedalus council` ausgeliefert wurde. Die Korrektur steht im Code
  (`session.py:104-131`); wer aeltere Notizen liest, findet die alte Aussage.

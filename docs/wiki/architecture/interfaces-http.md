---
title: HTTP-Interface
type: module
status: living
updated: 2026-09-05
covers: daedalus/interfaces/http
---
# HTTP-Interface

`daedalus/interfaces/http/` ist die lokale HTTP-Oberfläche des Daedalus Agent
OS: eine `ThreadingHTTPServer`-Instanz, die die gebaute Web-App statisch
ausliefert, eine JSON-API für Leseprojektionen und Mutationen bereitstellt und
Live-Updates als Server-Sent Events streamt. Im Kernel/Ikarus/Ariadne-Bild ist
sie ein *Interface*, keine Orchestrierung: sie liest kanonische Projektionen und
löst über `begin_effect` bewachte Mutationen aus. Die Zustandshoheit bleibt beim
Spine und beim kanonischen Kernel (Masterplan §4, Invariante 1; §7 "Chat is an
interface, not the workflow database").

Das Paket ist mitten in einer Strangler-Umformung. Der Paket-Docstring sagt es
ausdrücklich: die *registrierten* Effekt-Ziele bleiben absichtlich in
`web_api.py`, während die Implementierungsmodule darunter Routenparsing,
Leseprojektionen, Mutationen, SSE-Auslieferung und Host-Bind-Admission besitzen.
`__init__.py` exportiert die alten Namen nur lazy über `__getattr__` — der
Kommentar dort nennt den Grund: "Resolve legacy exports without creating a
second HTTP authority".

## Module

| Datei | Zweck | Öffentliche Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/interfaces/http/__init__.py) | Kompatibilitätsfassade. Hält `_COMPAT_EXPORTS` als eingefrorene Menge und löst jeden dieser Namen bei Zugriff aus `web_api` auf. Legt zur Importzeit nichts an. | `__getattr__`, `__dir__`, `__all__` |
| [router.py](../../../daedalus/interfaces/http/router.py) | Reines Parsing des Request-Targets. Der Pfad bleibt bewusst prozentkodiert, weil PUT und POST historisch vor der Dekodierung gesplittet haben — das erhält das Verhalten kodierter Schrägstriche. | `RequestTarget`, `parse_request_target` |
| [server.py](../../../daedalus/interfaces/http/server.py) | Host-Bind-Admission: entscheidet, ob Bytes die Maschine verlassen dürfen, und validiert die Desktop-Startup-Nonce. Erzeugt selbst keinen Socket und hat zur Importzeit keinen Prozess-, Ledger-, Provider- oder Netzeffekt. | `NonLoopbackBindRefused`, `resolve_bind`, `refusal`, `desktop_startup_nonce`, `ALLOW_REMOTE_ENV`, `AUTH_TOKEN_ENV`, `DESKTOP_STARTUP_NONCE_ENV`, `MIN_AUTH_TOKEN_CHARS` |
| [bootstrap_prompt.py](../../../daedalus/interfaces/http/bootstrap_prompt.py) | Baut den Sitzungs-Bootstrap-Text für externe Runtimes (Harness-Wurzel, Projekt, Repository-Wurzel, nützliche CLI-Kommandos, aktive Agenten, Sicherheitshinweise). | `claude_bootstrap_prompt`, `HARNESS_ROOT` |
| [read.py](../../../daedalus/interfaces/http/read.py) | Read-only-Routendispatch. `handle_get` ist eine große Fallunterscheidung über den Pfad; alle Legacy-Helfer kommen als Port-Dataclass herein, damit die Naht monkeypatchbar bleibt. | `ReadPorts`, `handle_get`, `RoutePort` |
| [effects.py](../../../daedalus/interfaces/http/effects.py) | Mutationsdispatch hinter der registrierten Legacy-Fassade: Body-Lesen, Origin-Prüfung, begrenztes JSON-Parsing, Preflight für sensible POST-Routen und die eigentlichen PUT-/POST-Handler. | `EffectPorts`, `handle_put`, `handle_post`, `preflight_post`, `read_body`, `same_origin_request`, `mutation_route_wired`, `MUTATION_MAX_BODY_BYTES` |
| [sse.py](../../../daedalus/interfaces/http/sse.py) | Server-Sent-Event-Auslieferung: Snapshot-Vergleich, Frame-Kodierung, Keep-Alive und vier Stream-Endpunkte (Bridge-Events, Ikarus-Stream, Task-Events, Conversation-Request-Events). | `snapshot_events`, `event_changes`, `encode_event`, `stream_events`, `handle_events`, `handle_ikarus_stream`, `handle_task_events`, `handle_conversation_request_events`, `EVENT_STREAM_MAX_S`, `TASK_EVENTS_MAX_S` |
| [web_api.py](../../../daedalus/interfaces/http/web_api.py) | Der registrierte Einstiegspunkt und die einzige Stelle mit Socket, Handler-Klasse und Effekt-Registry-Aufrufen. Enthält außerdem die Leseprojektionen (`_loop_queue`, `_loop_attempts`, `_task_snapshot`, `_conversation_view`, …), die statische Auslieferung und die Genesis-Preview-Capability. | `DaedalusHandler`, `run`, `main`, `ROOT`, `SOURCE_WEB_DIST`, `PACKAGE_WEB_DIST` |

`web_api.py` ist mit 1612 Zeilen mehr als ein Drittel des Pakets (gemessen
2026-09-05, 3996 Zeilen gesamt). Es reexportiert die Admission-Funktionen aus
`server.py` unter ihren alten Unterstrich-Namen (`_resolve_bind`,
`_desktop_startup_nonce`, `_refusal`) als "compatibility seam".

## Trust-Grenzen / Effekte

Dieses Paket ist eine echte Effektgrenze, und zwar an drei Stellen.

**1. Bind-Admission (Ingress).** `resolve_bind` in `server.py` ist der einzige
Ort, der entscheidet, ob der Server etwas anderes als Loopback bedient. Ein
numerisches Loopback-Literal liefert ein leeres Token. Alles andere braucht
*beides*: einen expliziten Opt-in (`--allow-remote-clients` oder die
Umgebungsvariable) **und** ein Bearer-Token von mindestens 32 Zeichen. Der
Refusal-Text ist bewusst ausführlich und nennt, was sonst erreichbar wäre —
Spine-Ledger, Picker-Queue, PUT-Endpunkte, die Agentenrollen umschreiben, und
POST-Endpunkte, die Arbeit einreihen und Modelle aufrufen, also *remote spend*.
Der Name `localhost` wird ausdrücklich abgelehnt: ein Name, der bei der Prüfung
auf Loopback zeigt, kann beim Verbinden woanders hinzeigen. Der Docstring hält
außerdem fest, dass Egress-Trust-Erklärungen diese Ingress-Grenze nie
aufweichen.

**2. Effekt-Registry.** Drei registrierte Einträge werden aus diesem Paket
konsumiert:

- `cli.web_api` — in `main()`, unmittelbar nach `install_process_guard()` und
  vor `run()`. Der Kommentar erklärt, warum: das Umbrella-CLI installiert das
  Spend-Netz an seiner Tür, aber der eingefrorene Desktop-Sidecar und
  `python -m ...web_api` treten hier direkt ein.
- `web.mutations_put` — in `DaedalusHandler.do_PUT`.
- `web.mutations` — in `DaedalusHandler.do_POST`, *nach* `preflight_post`.

Jeder `begin_effect`-Aufruf übergibt eine `GuardDecision` namens
`web.authenticated_bind`, die begründet, warum dieser Request die Bind-Grenze
passiert hat (Loopback ohne Token bzw. Non-Loopback-Opt-in mit verifiziertem
Token). `do_GET` ruft kein `begin_effect` — Lesen ist fail-open, Schreiben
fail-closed.

**3. Browser-Grenze für sensible POST-Routen.** `_PREFLIGHT_POST_PATHS` enthält
`/api/genesis` und `/api/ariadne`. `mutation_route_wired` ist die *eine*
Tabelle, aus der sich Preflight, Dispatch und jedes Capability-Flag speisen —
laut Docstring, damit eine Route nicht hier entfernt und anderswo weiter
angekündigt werden kann. `preflight_post` prüft der Reihe nach: Client- und
Server-Host müssen Loopback sein; für Ariadne ist genau ein exakter numerischer
`Origin` und `Sec-Fetch-Site: same-origin` Pflicht, für Genesis wird ein
vorhandener Origin geprüft; danach wird der Body längenbegrenzt (64 KiB) und
mit einem Parser gelesen, der doppelte JSON-Felder ablehnt. Der validierte Body
wird am Handler zwischengespeichert, und `_prepared_post_body` wirft hart, wenn
eine Route den Preflight nicht durchlaufen hat.

`same_origin_request` vergleicht nicht Strings, sondern `ip_address`-Objekte
gegen die tatsächlich gebundene Serveradresse und verlangt zusätzlich leeren
Pfad, leere Query, kein Fragment und keine Credentials im Origin.

Weitere Härtungen im Lesepfad: `/api/genesis/*` ist loopback-only, verlangt
genau einen `Host`-Header, der der numerischen Bindung entspricht, und baut
daraus den CSP-Origin der Preview. `_contained_web_path` verhindert das
Ausbrechen aus der statischen Wurzel (Nullbyte, Backslash, `resolve` plus
`relative_to`).

**Read-only bleibt read-only:** `read.py`, `router.py` und `sse.py` rufen kein
`begin_effect`. `sse.py` importiert allerdings `_header_values` und
`same_origin_request` aus `effects.py` — die Origin-Prüfung ist also auch für
Streams verfügbar.

## Tests

Gemessen 2026-09-05 nennen 44 Testdateien `interfaces.http` oder `web_api`. Die
unmittelbar zuständigen:

| Test | Deckt ab |
| --- | --- |
| [tests/interfaces/test_http_strangler_architecture.py](../../../tests/interfaces/test_http_strangler_architecture.py) | dass die Zerlegung keine zweite HTTP-Autorität erzeugt |
| [tests/interfaces/test_http_server_admission_owner.py](../../../tests/interfaces/test_http_server_admission_owner.py) | `resolve_bind` als alleiniger Eigentümer der Bind-Admission |
| [tests/interfaces/test_http_sse_owner.py](../../../tests/interfaces/test_http_sse_owner.py) | Eigentum am SSE-Pfad |
| [tests/interfaces/test_http_genesis.py](../../../tests/interfaces/test_http_genesis.py) | Genesis-Routen, Preview-Capability, Loopback-Zwang |
| [tests/interfaces/test_http_ariadne.py](../../../tests/interfaces/test_http_ariadne.py) | Ariadne-Kampagnenroute und ihre Origin-Bedingungen |
| [tests/interfaces/test_desktop_http_csrf.py](../../../tests/interfaces/test_desktop_http_csrf.py) | die CSRF-/Origin-Grenze aus Sicht des Desktops |
| [tests/interfaces/test_http_response_disconnect.py](../../../tests/interfaces/test_http_response_disconnect.py) | Verbindungsabbrüche und das Draining abgelehnter Bodies |
| [tests/interfaces/test_http_fourfold_purity.py](../../../tests/interfaces/test_http_fourfold_purity.py) | dass die Fourfold-Leseprojektion rein bleibt |
| [tests/test_desktop_startup_nonce.py](../../../tests/test_desktop_startup_nonce.py) | `desktop_startup_nonce` und sein Format |
| [tests/test_web_api.py](../../../tests/test_web_api.py), [tests/test_web_api_loop.py](../../../tests/test_web_api_loop.py), [tests/test_web_api_health.py](../../../tests/test_web_api_health.py), [tests/test_web_api_catalogue.py](../../../tests/test_web_api_catalogue.py) | die API-Oberfläche im Ganzen |
| [tests/test_effect_boundary.py](../../../tests/test_effect_boundary.py), [tests/test_cli_effect_boundary.py](../../../tests/test_cli_effect_boundary.py), [tests/test_spend_coverage.py](../../../tests/test_spend_coverage.py) | die Registry-Einträge `cli.web_api`, `web.mutations`, `web.mutations_put` |
| [tests/contracts/test_import_scc_hierarchy.py](../../../tests/contracts/test_import_scc_hierarchy.py), [tests/contracts/test_spine_outer_ports.py](../../../tests/contracts/test_spine_outer_ports.py) | Importrichtung und Portgrenzen |

## Verwandt

- [Interfaces Desktop](interfaces-desktop.md) — der Sidecar, der `main()` startet
- [Interfaces CLI](interfaces-cli.md) — die Schwester-Tür
- [Interfaces Bridge](interfaces-bridge.md) — der File-Bus, dessen Zustand die SSE-Snapshots spiegeln
- [Spine](spine.md) — `begin_effect` und die Effekt-Registry
- [Orchestration Genesis](orchestration-genesis.md) — Ziel der `/api/genesis`-Routen
- [Ariadne](ariadne.md) — Ziel der `/api/ariadne`-Route
- [Structcore](structcore.md) — Quelle der Struktur-, Churn- und Topologie-Projektionen
- [Twin](twin.md) — `fourfold_read_projection`
- [Kairos](kairos.md) — `drafts` im Lese- und Mutationspfad
- [GUI](gui.md) — die ausgelieferte Web-App
- [Kernel-Policy](kernel-policy.md), [Wiki-Index](../index.md), [Tool-Vetting](../tool-vetting.md)

## Ungeklärt

- **Ungeklärt:** Welche Routen `handle_get` genau bedient. Die Funktion ist eine
  lange Pfad-Fallunterscheidung; ich habe sie nicht vollständig aufgelistet.
  Eine belastbare Routentabelle müsste aus `read.py` generiert werden, nicht
  abgeschrieben.
- **Ungeklärt:** Ob `mutation_route_wired` außerhalb von `effects.py`
  tatsächlich von allen Capability-Projektionen benutzt wird, wie der Docstring
  behauptet. Ich habe die Aufrufstellen nicht verfolgt.
- **Ungeklärt:** Der Zusammenhang zwischen `daedalus_desktop_startup_nonce` am
  Server-Objekt und dem Autorisierungspfad in `DaedalusHandler._authorized`.
  Beide existieren; wie sie zusammenspielen, ist aus den gelesenen Ausschnitten
  nicht eindeutig.
- **Ungeklärt:** `bootstrap_prompt.py` verweist auf `outbox`, `inbox` und
  `memory/todos.local.md` relativ zu `HARNESS_ROOT`. Ob diese Pfade heute noch
  die tatsächlichen Ablageorte sind, habe ich nicht geprüft — der Text ist ein
  Prompt, keine Konfiguration.

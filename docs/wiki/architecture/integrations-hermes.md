---
title: Hermes-Integration
type: module
status: living
updated: 2026-09-05
covers: daedalus/integrations/hermes
---
# Hermes-Integration

`daedalus/integrations/hermes/` fährt einen gepinnten fremden Agenten — das
Upstream-Projekt `NousResearch/hermes-agent` — als *Userspace*-Runtime hinter
der Daedalus-Kernel-Autorität. Der Paketname sagt die Rolle: eine Integration,
kein viertes Subsystem. Hermes schlägt vor und arbeitet; Policy, EffectLease,
Werkzeugkatalog, Kontext und Speicher kommen von Daedalus, und das Ergebnis ist
eine Beobachtung, kein Prüfergebnis (Masterplan §4, Invarianten 3 und 4).

Der Paket-Docstring nennt die Importgrenze zuerst: der Import dieses Pakets
macht kein I/O, öffnet keine Modellverbindung und registriert keine
Provider-Operation. Wer Hermes benutzen will, muss exakte Quell-, Containment-,
Gateway- und Broker-Subjekte selbst konstruieren.

## Module

| Datei | Zweck | Öffentliche Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/integrations/hermes/__init__.py) | Reexport-Fassade ohne Seiteneffekte. | 23 Namen in `__all__` |
| [configuration.py](../../../daedalus/integrations/hermes/configuration.py) | Gepinnte Herkunft und Containment: Upstream-Identität mit Commit-, Tree- und Datei-Digests, Sandbox-Profil mit unveränderlichen Grenzen, Laufzeitkonfiguration, Checkout-Verifikation, Disjunktheitsprüfung der Wurzeln und der Umgebungs-Sanitizer. | `HermesPinnedSource`, `DEFAULT_HERMES_SOURCE`, `HermesCheckoutEvidence`, `HermesSandboxProfile`, `HermesRuntimeConfig`, `HermesConfigurationError`, `verify_hermes_checkout`, `ensure_disjoint_roots`, `build_sanitized_environment`, `canonical_environment_names`, `file_sha256`, `HERMES_RUNTIME_ID`, `HERMES_ADAPTER_ID`, `HERMES_ADAPTER_VERSION`, `HERMES_OPERATION_ID`, `HERMES_PROTOCOL_SCHEMA` |
| [protocol.py](../../../daedalus/integrations/hermes/protocol.py) | Strikter JSONL-Vertrag zwischen Adapter und Worker: exakte Feldmengen je Nachrichtentyp, Zeilen-, Tiefen- und Knotengrenzen, kanonische Serialisierung und Digest. | `validate_message`, `encode_message`, `write_message`, `read_message`, `message_stream`, `canonical_json`, `canonical_sha256`, `HermesProtocolError`, `MAX_LINE_BYTES`, `MAX_DEPTH`, `MAX_NODES` |
| [context_provider.py](../../../daedalus/integrations/hermes/context_provider.py) | Expliziter, vom Aufrufer gelieferter Kontext. Keine ambiente Dateisuche; jedes Fragment trägt Name, Inhalt und Medientyp, die Gesamtlänge ist begrenzt. | `ContextFragment`, `ExplicitContextProvider`, `HermesContextError` |
| [memory_provider.py](../../../daedalus/integrations/hermes/memory_provider.py) | Read-only, begrenzter Speicher-Schnappschuss vom Aufrufer. Jeder Datensatz führt eine SHA-256-Quellherkunft. | `MemoryRecord`, `ReadOnlyMemoryProvider`, `HermesMemoryError` |
| [tool_provider.py](../../../daedalus/integrations/hermes/tool_provider.py) | Der von Daedalus besessene Werkzeugkatalog mit eigener JSON-Schema-Validierung für Argumente und Ergebnisse sowie die begrenzte Aufrufprojektion. | `ToolSpec`, `ToolOutcome`, `ToolInvoker`, `DaedalusToolProvider`, `HermesToolError` |
| [tool_gateway.py](../../../daedalus/integrations/hermes/tool_gateway.py) | Einmal-Loopback-Brücke von der versiegelten Operation zu den Daedalus-Werkzeugen: signierter Deskriptor, Server im Aufrufer-Prozess, Client im Worker. | `HermesGatewayDescriptor`, `HermesToolGatewayServer`, `HermesToolGatewayClient`, `HermesToolGatewayError`, `GATEWAY_SCHEMA` |
| [event_adapter.py](../../../daedalus/integrations/hermes/event_adapter.py) | Verlustbewusste Normalisierung der Worker-Beobachtungen zu einer geordneten Ereignisfolge mit offenen/geschlossenen Aufrufen und einem Terminalzustand. | `HermesRuntimeEvent`, `HermesEventLedger`, `HermesEventError` |
| [runtime_adapter.py](../../../daedalus/integrations/hermes/runtime_adapter.py) | Der eigentliche Prozessadapter: verifiziert den Checkout, baut das Worker-Kommando hinter dem Sandbox-Prefix, spricht JSONL über stdin/stdout, begrenzt stderr, erzwingt Zeit- und Ausgabegrenzen und terminiert die Prozessgruppe. Größtes Modul (546 Zeilen, gemessen 2026-09-05). | `HermesRuntimeAdapter`, `HermesRuntimeRequest`, `HermesRuntimeResult`, `HermesRuntimeError`, `execute_from_metadata`, `RUNTIME_REQUEST_SCHEMA`, `RUNTIME_RESULT_SCHEMA` |
| [kernel_provider.py](../../../daedalus/integrations/hermes/kernel_provider.py) | Bindet die feste Provider-Operation an die belegbasierte ausführbare Registry und stellt die schmale Aufruferfassade. Nimmt bewusst keinen Callback entgegen. | `HermesKernelProvider`, `register_hermes_runtime_operation`, `build_hermes_runtime_metadata`, `HermesKernelProviderError` |
| [session.py](../../../daedalus/integrations/hermes/session.py) | Ein Kontextmanager, der Gateway-Server und Anfrage zusammen aufspannt und wieder abbaut — der Aufrufer besitzt den Lebenszyklus. | `hermes_runtime_session` |
| [conformance.py](../../../daedalus/integrations/hermes/conformance.py) | Statische und evidenzgetriebene Konformitätsprüfung: scannt den Adapterbaum auf verbotene Direktimporte und baut daraus zusammen mit Checkout-Evidenz eine Quittung. | `scan_forbidden_imports`, `build_conformance_receipt`, `HermesConformanceReceipt`, `HermesAdmissionEvidence`, `HermesConformanceError`, `FORBIDDEN_DIRECT_IMPORTS` |
| [worker.py](../../../daedalus/integrations/hermes/worker.py) | Der Kindprozess. Lädt das Upstream-Modul aus dem verifizierten Checkout, ersetzt dessen Werkzeuge durch die JSONL-Brücke zurück zum Adapter, konstruiert und ruft den Agenten und meldet das Ergebnis. | `main`, `HermesWorkerError` |

Der Paketmarker eine Ebene hoeher,
[integrations/__init__.py](../../../daedalus/integrations/__init__.py), besteht aus
einem Satz: "Optional, replaceable integrations for Daedalus userspace
runtimes" -- Hermes ist heute die einzige.

## Trust-Grenzen / Effekte

Dieses Paket ist die schärfste Vertrauensgrenze meines Bereichs: es führt
fremden Code aus. Die Verteidigung liegt in sechs voneinander unabhängigen
Schichten.

**1. Gepinnte Herkunft.** `HermesPinnedSource.__post_init__` akzeptiert genau
ein Repository (`NousResearch/hermes-agent`), verlangt explizite Release- und
Tag-Angaben, prüft Commit und Tree als 40-Hex und drei Datei-Digests als 64-Hex
und lehnt jede Lizenz außer MIT ab ("only the provenance-reviewed MIT upstream
is accepted"). `DEFAULT_HERMES_SOURCE` pinnt Release, Tag, Commit, Tree sowie
die Digests von Agent-Skript, Lizenz und Archiv. `verify_hermes_checkout`
vergleicht den Arbeitsbaum gegen diese Pins und liefert `HermesCheckoutEvidence`
mit einem `clean`-Flag.

**2. Äußeres Containment.** `HermesSandboxProfile` verlangt ein nichtleeres
`command_prefix` — ohne äußeres Sandbox-Kommando verweigert das Profil die
Produktion; nur das ausdrückliche Feld `test_only_uncontained` hebt das für
Tests auf. `network_mode` kennt genau drei Werte (`none`, `loopback-only`,
`declared-egress`), Vorgabe ist `loopback-only`. Iterationen, Wanduhrzeit,
Werkzeugaufrufe und Ausgabebytes sind mit expliziten Ober- *und* Untergrenzen
belegt, alle als unveränderliche Felder eines eingefrorenen Dataclass.

**3. Sanitisierte Umgebung.** `build_sanitized_environment` baut das
Kindprozess-Environment aus einer *Allowlist* auf, nicht durch Filtern:
übernommen werden nur die Namen aus `ordinary_env_allowlist` und
`secret_env_allowlist`. Danach werden `HOME`, `USERPROFILE`, `HERMES_HOME`,
`TMP`, `TEMP` und `TMPDIR` auf Unterverzeichnisse einer frisch angelegten
Laufzeitwurzel umgebogen und sechs Upstream-Fähigkeiten hart ausgeschaltet
(Memory, Learning, Gateway, Cron, Checkpoints; dazu `HERMES_EPHEMERAL`).
`ensure_disjoint_roots` erzwingt, dass Checkout, Laufzeit-`HOME` und
Task-Workspace sich weder gleichen noch ineinander liegen.

**4. Der Prozess.** `HermesRuntimeAdapter._worker_command` setzt das Kommando
als `[*command_prefix, python, "-I", "-c", bootstrap]` zusammen — `-I` ist der
isolierte Interpretermodus, der Umgebungsvariablen und User-Site-Verzeichnisse
des Interpreters ignoriert, und der Bootstrap startet ausschließlich
`daedalus.integrations.hermes.worker`. `_terminate` beendet plattformabhängig:
auf POSIX über die Prozessgruppe (`os.killpg` mit `SIGTERM`, dann `SIGKILL`),
unter Windows über `terminate`/`kill`. stderr wird über `_BoundedStderr`
begrenzt.

**5. Werkzeuge nur über ein authentifiziertes Loopback-Gateway.** Der Worker
bekommt keinen Callback in den Elternprozess. Stattdessen trägt die
Provider-Nutzlast einen `HermesGatewayDescriptor`, dessen `__post_init__`
prüft: Host ist ein Loopback-*Literal* (`is_loopback_literal` mit
`allow_bracketed_ipv6=False`, also kein Name), Port und maximale Aufrufzahl
liegen in Schranken, Identität ist vollständig, und der `digest` ist der
kanonische SHA-256 über alle übrigen Felder — ein manipulierter Deskriptor
fällt beim Konstruieren durch. Der Deskriptor läuft ab (`expires_at_ns`), ist
auf `max_calls` begrenzt und bindet einen `tool_scope_digest`. Das Token liegt
in einer Datei unter der Kontrollwurzel, nicht in der Umgebung.

**6. Keine Callback-Autorität in der Kernel-Operation.**
`HermesKernelProvider.invoke_authenticated` lehnt die Argumente `invoke`,
`callback`, `output_digests` und `tool_invoker` explizit ab und verlangt eine
`ProviderInvocationPayload` exakten Typs (`type(payload) is not ...`, also keine
Unterklasse). `register_hermes_runtime_operation` verlangt ebenso exakt eine
`ProviderExecutableObjectRegistry` und einen
`ProviderExecutablePreAdmissionReceipt`, dessen `entrypoint_id` genau
`provider.hermes_agent.oneshot.v1` sein muss — der Docstring sagt, dass dieser
Helfer den Beleg bewusst nicht herstellen und keinen Callback einschleusen kann.

**Konformität als Evidenz.** `scan_forbidden_imports` durchsucht den
Adapterbaum per `ast` nach direkten Importen von `anthropic`, `openai`,
`requests`, `httpx`, `urllib.request`, `websocket` und `websockets`. Der Adapter
darf also nicht selbst zum Modellanbieter oder HTTP-Client werden.
`HermesAdmissionEvidence` führt vier Flags (versiegelter Broker, Containment,
Gateway-Fehlermatrix, Unknown-Outcome), die alle standardmäßig falsch sind — die
Quittung behauptet nichts, was nicht belegt wurde.

**Wo `begin_effect` steht:** nirgends in diesem Paket (gemessen 2026-09-05).
Der Effekt läuft über die kanonische Provider-Kette
(`daedalus.runtimes.broker.run_runtime_provider` und die ausführbare
Objekt-Registry unter `daedalus/runtimes/provider/`), nicht über eine eigene
Tür. Das ist genau die Konstruktion, die Masterplan §4 Invariante 1 verlangt:
ein Kernel, kein zweiter Effektpfad.

## Tests

Gemessen 2026-09-05 nennen 13 Testdateien Hermes; die zuständigen liegen unter
`tests/integrations/`:

| Test | Deckt ab |
| --- | --- |
| [tests/integrations/test_hermes_runtime_adapter.py](../../../tests/integrations/test_hermes_runtime_adapter.py) | Prozessadapter, Protokoll, Grenzen, Terminierung |
| [tests/integrations/test_hermes_tool_gateway.py](../../../tests/integrations/test_hermes_tool_gateway.py) | Deskriptor-Digest, Loopback-Zwang, Aufrufbudget |
| [tests/integrations/test_hermes_kernel_provider.py](../../../tests/integrations/test_hermes_kernel_provider.py) | die Callback-Verweigerung und die exakten Typprüfungen |
| [tests/integrations/test_hermes_conformance.py](../../../tests/integrations/test_hermes_conformance.py) | verbotene Direktimporte und die Konformitätsquittung |
| [tests/test_ikarus_tool_scope.py](../../../tests/test_ikarus_tool_scope.py), [tests/test_ikarus_oneshot.py](../../../tests/test_ikarus_oneshot.py), [tests/test_ikarus_runtime_role.py](../../../tests/test_ikarus_runtime_role.py), [tests/test_ikarus_effect_bridge.py](../../../tests/test_ikarus_effect_bridge.py) | die Ikarus-Seite: Werkzeug-Scope, One-Shot-Rolle, Effektbrücke |
| [tests/orchestration/test_ikarus_mission_integration.py](../../../tests/orchestration/test_ikarus_mission_integration.py) | Einbettung in eine Mission |
| [tests/contracts/test_import_scc_hierarchy.py](../../../tests/contracts/test_import_scc_hierarchy.py), [tests/test_architecture_boundaries.py](../../../tests/test_architecture_boundaries.py) | Importrichtung und Schichtgrenzen |

## Verwandt

- [Runtimes-Provider](runtimes-provider.md) — Broker, ausführbare Registry, Pre-Admission
- [Runtimes](runtimes.md), [Runtimes-Contracts](runtimes-contracts.md) — der Runtime-Vertrag, in den Hermes sich einfügt
- [Runtimes-Admission](runtimes-admission.md) — die Zulassungsseite
- [Orchestration Ikarus](orchestration-ikarus.md) — der Aufrufer
- [Kernel-Policy](kernel-policy.md) — die Autorität, die Hermes nicht besitzt
- [Providers](providers.md) — die anderen Vendor-Adapter
- [Tools](tools.md) — der Werkzeugkatalog hinter `DaedalusToolProvider`
- [Memory](memory.md) — Abgrenzung zum read-only Speicher-Schnappschuss
- [Interfaces HTTP](interfaces-http.md) — `is_loopback_host` als verwandte Loopback-Prüfung
- [Tool-Vetting](../tool-vetting.md), [Wiki-Index](../index.md), [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md)

## Ungeklärt

- **Ungeklärt:** Ob der gepinnte Upstream-Checkout im Baum vorhanden ist oder
  vom Betreiber separat beschafft werden muss. `HermesRuntimeConfig` nimmt einen
  `checkout_root` entgegen; wo dieser üblicherweise liegt, steht nicht im Code
  dieses Pakets.
- **Ungeklärt:** Welches konkrete `command_prefix` in der Praxis benutzt wird
  (Docker, bubblewrap, etwas anderes). Das Profil verlangt nur, dass eines
  existiert.
- **Ungeklärt:** Ob `register_hermes_runtime_operation` heute irgendwo
  tatsächlich aufgerufen wird oder ob die Operation vorbereitet, aber nicht
  aktiviert ist. Ich habe die Aufrufstellen nicht verfolgt.
- **Ungeklärt:** Der genaue Umgang mit `unknown_outcome_verified` — das Flag existiert in
  `HermesAdmissionEvidence`, die Semantik habe ich aus `runtime_adapter.py`
  nicht vollständig gelesen.
- **Ungeklärt:** `tool_provider.py` enthält einen Fallback für
  `canonical_sha256`, falls `protocol.py` fehlt ("landed independently"). Ob
  dieser Fallback heute noch nötig ist, obwohl beide Module im selben Paket
  liegen, geht aus dem Kommentar nicht hervor — er wirkt wie ein Rest aus der
  Landephase.

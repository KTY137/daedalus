---
title: Providers
type: module
status: living
updated: 2026-09-05
covers: daedalus/providers
---
# Providers

`daedalus/providers` ist die **Effekt- und Kompatibilitaetstuer** zu den
konkreten Modell-Backends. Zehn Dateien, 3724 Zeilen (gemessen 2026-09-05).
Der Paket-Docstring sagt die Arbeitsteilung klar: Provider-*Vertraege*,
Metadaten und Health-Projektion gehoeren inzwischen
`daedalus.runtimes.providers` (siehe [Runtimes Providers](runtimes-providers.md)
und [Runtimes Provider](runtimes-provider.md)); die konkrete Konstruktion und
die vier Adapter bleiben hier, weil die registrierten Effekt-Zeilen ihre
historischen Modulpfade behalten. Im Kernel/Ikarus/Ariadne-Bild sind das
Werkzeuge der Orchestrierungsschicht: Modelle *schlagen vor*, sie entscheiden
nichts (Masterplan Abschnitt 8, Invariante 4).

Vier Provider sind konstruierbar: `claude_cli`, `codex_cli`, `deepseek`,
`ollama`. Sie unterscheiden sich in genau den Achsen, die
`ProviderCapabilities` festhaelt -- schreibfaehig, lokal, mit
Firmengeheimnissen betraubar, agentisch -- und diese Achsen sind Aussagen ueber
den *Namen*, nicht ueber die Laufzeit; `OllamaProvider.egress_lane` sagt das
ausdruecklich und liefert stattdessen die Host-Antwort.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/providers/__init__.py) | Die stabile Effekttuer. `get_provider` konstruiert genau einen Provider aus einem Namen und importiert sein Modul erst dann; `provider_health` und `available_providers` projizieren den Katalog aus der Runtime-Schicht. | `get_provider`, `provider_health`, `available_providers`, `list_providers`, `Provider`, `ProviderCapabilities`, `ProviderMetadata` |
| [`base.py`](../../../daedalus/providers/base.py) | Sechszeilige Kompatibilitaetsfassade: `Provider` und `ProviderCapabilities` gehoeren `daedalus.runtimes.providers.contracts`. | `Provider`, `ProviderCapabilities` |
| [`personas.py`](../../../daedalus/providers/personas.py) | Elfzeilige Fassade auf den runtime-eigenen Persona-Katalog. | `culture`, `persona_for`, `roster` |
| [`_report.py`](../../../daedalus/providers/_report.py) | Kompatibilitaets- und Kontextfassade. Bindet die Sensitivitaets- und Graph-Ports zur Aufrufzeit in die runtime-eigenen Kontext-Besitzer ein, statt sie dort zu importieren. Haelt das Kontextbudget von 24.000 Zeichen fuer nicht-agentische Provider. | `MAX_CONTEXT_CHARS`, `read_provider_context`, `render_provider_brief`, plus Reexporte wie `blocked_report`, `coerce_report`, `build_prompt`, `bounded_execution_limit_policy`, `provider_http_timeout` |
| [`_openai_compat.py`](../../../daedalus/providers/_openai_compat.py) | Minimaler OpenAI-kompatibler Chat-Client auf der Standardbibliothek, absichtlich ohne `requests` oder `openai`. | `ProviderHTTPError`, `chat_raw`, `chat_completion`, `chat_stream`, `server_reachable` |
| [`_ollama_native.py`](../../../daedalus/providers/_ollama_native.py) | Zweiter Client fuer Ollamas natives `/api/chat`. Existiert, weil der OpenAI-kompatible `/v1`-Shim einen `options`-Block ignoriert (gemessen 2026-07-26 auf dieser Maschine) und damit weder `num_ctx` noch `format` noch `keep_alive` durchreicht. | `native_chat`, `num_ctx_value`, `effective_input_window`, `DEFAULT_NUM_CTX`, `OUTPUT_RESERVE_TOKENS` |
| [`claude_cli.py`](../../../daedalus/providers/claude_cli.py) | Der agentische Claude-CLI-Adapter, dessen oeffentlicher Ausfuehrungspunkt ueber den persistierten Runtime-Provider-Broker laeuft. Die versiegelte Subprozess-Umsetzung bleibt privat in `daedalus/claude_bridge.py`. | `ClaudeCLIProvider`, `claude_invocation_sha256`, `claude_idempotency_key` |
| [`codex_cli.py`](../../../daedalus/providers/codex_cli.py) | Externe, agentische, schreibfaehige Lane: `codex exec` gegen ein Zielrepo. Baut den Prompt und erzwingt das Egress-Gate vor dem Spawn. | `CodexCLIProvider`, `build_prompt`, `cmd_shim_refusal` |
| [`deepseek.py`](../../../daedalus/providers/deepseek.py) | Billige externe Lane, nicht-agentisch, standardmaessig beratend. Schreibfaehig nur, wenn zwei unabhaengige Bedingungen gleichzeitig gelten. | `DeepSeekProvider`, `DEFAULT_BASE_URL`, `DEFAULT_MODEL`, `MAX_REWRITE_FILES`, `MAX_REWRITE_CHARS` |
| [`ollama.py`](../../../daedalus/providers/ollama.py) | Groesste Datei des Pakets (1538 Zeilen): lokale Lane mit agentischer Schleife, Schema-Rettung, Voll-Rewrite und fenstriger Bearbeitung, plus die Host-Admission der Ollama-Lane. | `OllamaProvider`, `ollama_endpoint_admission`, `remote_endpoint_consented`, `ollama_http_base_url`, `keep_alive_value`, `warm_model`, `warm_model_async`, `DEFAULT_HOST`, `DEFAULT_MODEL`, `REMOTE_CONSENT_VAR`, `DEFAULT_KEEP_ALIVE`, `MAX_AGENT_STEPS` |

## Trust-Grenzen / Effekte

**Claude ist die strengste Tuer.** `ClaudeCLIProvider.run` kann Claude nicht
aus ambienter Autoritaet aufrufen. Verlangt werden -- sonst
`ClaudeProviderAuthorizationRequired` -- genau eine
`RuntimeBoundEffectAuthorization`, eine verengte `EffectExecutionRequest`, eine
`ClaudeWorkspaceGrant`, die an dieselbe Anfrage, Ausfuehrung, Attempt-Id,
Quell-Revision und Aufruf-Nutzlast gebunden ist, sowie die signierte
Beobachtungs-Autoritaet mit ihrem Bindungs-Ledger, die Aufruf-ABI, die
Executable-Registry und die Vor-Admissions-Quittung. Der generische Broker
persistiert Grant- und Startzustand, unterdrueckt exakte Wiederholungen,
prueft Runtime-Trust erneut und schreibt den Endzustand fest, **bevor** ein
Provider-Wert freigegeben wird. `claude_invocation_sha256` und
`claude_idempotency_key` sind die Identitaeten, an denen das haengt. Der
private Helfer in `daedalus/claude_bridge.py` ist kein unterstuetzter
Produktions-Einstieg. Siehe [Runtimes Admission](runtimes-admission.md) fuer
die Praegung dieser Autoritaet.

**Codex und DeepSeek: hartes Egress-Gate vor dem Spawn.** Beide sind
ausdruecklich `trusted_with_ip=False`. `CodexCLIProvider.run` ruft
`classify_data` mit den deklarierten Pfaden und dem Ziel auf und liefert bei
einem sensiblen Verdikt einen `blocked_report`, **bevor** die CLI gespawnt
wird -- ein abgelehnter Pfad erreicht `codex` nie. Das Restrisiko steht
dokumentiert im Modul-Docstring statt versteckt zu sein: Codex ist agentisch
und kann nach dem Dispatch Dateien jenseits der deklarierten Pfade lesen; nur
die Vor-Dispatch-Verweigerung ist eine harte Garantie.

DeepSeek darf nur schreiben, wenn **zwei unabhaengige** Dinge zugleich wahr
sind: das Repository nennt die Lane in seiner Policy, und der Aufrufer uebergibt
`writable=True` (Voreinstellung `False`, damit ein Aufrufer ohne Kenntnis des
Features es nicht ausloesen kann). Keine der beiden Bedingungen lockert den
Egress-Zaun: der Rewrite-Prompt traegt ganze Dateiinhalte an eine externe API,
also wird jede Datei einzeln neu klassifiziert -- das Lauf-Verdikt ist kein
Freibrief je Datei. Schreibvorgaenge sind zusaetzlich durch
`path_write_blocked` begrenzt, und jede beruehrte Datei wird byte-genau
gesichert, damit `rollback` funktioniert.

**Ollama ist nur so lokal wie sein Host.** `caps` behauptet `local=True` und
`trusted_with_ip=True` -- das sind statische Aussagen ueber einen *Namen*. Der
Host kommt aus `OLLAMA_HOST`, dieselbe Klasse spricht also mit `127.0.0.1`
oder mit einer Bench-Maschine im Tailnet. `ollama_endpoint_admission` ist der
`provider.egress_policy`-Vertrag fuer alles, was den Ollama-Transport spricht,
und faellt fail-closed: ein leerer, unparsbarer oder unbekannter Host ist
`untrusted` und ohne exakte Zustimmung abgelehnt. `REMOTE_CONSENT_VAR` haelt
**den Host selbst**, nie ein Boolean -- ein `=1` waere Zustimmung zu jedem
kuenftigen Endpunkt, auch zu einem, den eine Konfigurationsaenderung
stillschweigend einsetzt. Zustimmung macht die Lane nicht vertrauenswuerdig:
`lane_for_host` bleibt die einzige Umsetzung von "verlaesst das die Maschine",
und darunter laufen die Default-Deny-Allowlist und der Secret-Floor weiter.

**Was diese Provider nicht duerfen.** Keiner von ihnen aendert Policy,
Evaluator, Ledger, Evidence oder Promotion; das ist Invariante 3 und 5 des
Masterplans. `daedalus/providers` schreibt keinen Ledger-Eintrag selbst -- die
Verbuchung passiert am Prozess-Interposer in
[Runtimes Execution](runtimes-execution.md), der `providers/codex_cli.py` und
`providers/_openai_compat.py` explizit in seinem Ausgabenregister fuehrt.

## Gemessene Eigenheiten, die im Code stehen

- **Strukturierte Ausgabe ist keine Groessenfrage.** Gemessen 2026-07-29 auf
  einer RTX 5080, drei Durchlaeufe mal zwei agentische Aufgaben je Modell:
  `qwen2.5-coder` in 1.5b, 7b und 14b sowie `devstral` lieferten 0 % korrekte
  strukturierte Werkzeugaufrufe, ein 36B-MoE-Modell 100 %. Alle vier bewerben
  die Faehigkeit. Die Voreinstellung ist nur vertretbar, weil `_schema_rescue`
  die Aufrufform am Sampler erzwingt und die drei Nuller auf 100 % bringt --
  ohne das ist der Fehlermodus ein erfolgreicher Zug, der nichts aendert.
- **Kontextfenster.** Ollamas `/v1`-Shim ignoriert `options`, eine
  ueberbudgetierte Anfrage wurde bei 4096er Default auf etwa 2050 Token am Kopf
  abgeschnitten. Deshalb der zweite, native Client mit `num_ctx_value` und
  `effective_input_window`.
- **Warmhaltezeit.** `DEFAULT_KEEP_ALIVE` steht auf 30 Minuten statt Ollamas
  fuenf, weil ein kalter Start etwa 44 Sekunden bis zum ersten Token kostete
  gegenueber etwa 1,4 Sekunden warm.
- **Fenstriges Umschreiben statt Neudruck.** Gemessen 2026-07-29 endeten drei
  Docref-Attempts gegen eine 2496-Zeilen-Datei ohne Aenderung, weil 148 KB das
  Sechsfache von `MAX_REWRITE_CHARS` sind. Ein groesserer Deckel loest das
  nicht; ein 7B-Modell, das 2500 Zeilen nachdrucken soll, echot oder kuerzt.
  Stattdessen sieht das Modell nur ein Fenster um jede fehlerhafte Zeile, und
  alles ausserhalb bleibt **konstruktionsbedingt** byte-identisch.
- **Timeout gegen Wirklichkeit.** `CodexCLIProvider` hat 1500 Sekunden
  Voreinstellung, weil live gemessene Repo-Aufgaben 8 bis 20 Minuten brauchten
  und 300 Sekunden den Wrapper toeteten, waehrend Codex weiterarbeitete.

## Tests

- [`tests/providers/test_claude_runtime_broker.py`](../../../tests/providers/test_claude_runtime_broker.py) und [`tests/runtimes/test_claude_provider_strangler_architecture.py`](../../../tests/runtimes/test_claude_provider_strangler_architecture.py)
- [`tests/test_codex_provider.py`](../../../tests/test_codex_provider.py) und [`tests/test_codex_shim_argv.py`](../../../tests/test_codex_shim_argv.py)
- [`tests/test_ollama_native.py`](../../../tests/test_ollama_native.py), [`tests/test_ollama_remote_lane.py`](../../../tests/test_ollama_remote_lane.py), [`tests/test_ollama_rescue_reason.py`](../../../tests/test_ollama_rescue_reason.py)
- [`tests/test_deepseek_substitution_guard.py`](../../../tests/test_deepseek_substitution_guard.py) und [`tests/test_deepseek_write_toggle.py`](../../../tests/test_deepseek_write_toggle.py)
- [`tests/test_providers_report.py`](../../../tests/test_providers_report.py), [`tests/test_provider_execution_limit_policy.py`](../../../tests/test_provider_execution_limit_policy.py), [`tests/test_provider_rollback_single_source.py`](../../../tests/test_provider_rollback_single_source.py)
- [`tests/test_egress_lane_by_host.py`](../../../tests/test_egress_lane_by_host.py), [`tests/test_health_admission.py`](../../../tests/test_health_admission.py), [`tests/test_write_guard_e2e.py`](../../../tests/test_write_guard_e2e.py)
- [`tests/runtimes/test_provider_catalogue_hierarchy.py`](../../../tests/runtimes/test_provider_catalogue_hierarchy.py), [`tests/runtimes/test_provider_contracts_hierarchy.py`](../../../tests/runtimes/test_provider_contracts_hierarchy.py), [`tests/runtimes/test_provider_helper_hierarchy.py`](../../../tests/runtimes/test_provider_helper_hierarchy.py)
- [`tests/runtimes/test_provider_invocation_abi.py`](../../../tests/runtimes/test_provider_invocation_abi.py), [`tests/runtimes/test_provider_executable_object_registry.py`](../../../tests/runtimes/test_provider_executable_object_registry.py), [`tests/runtimes/test_provider_executable_pre_admission.py`](../../../tests/runtimes/test_provider_executable_pre_admission.py)
- [`tests/test_rewrite.py`](../../../tests/test_rewrite.py), [`tests/test_repair_blast_radius_write.py`](../../../tests/test_repair_blast_radius_write.py), [`tests/test_offload_write_failclose.py`](../../../tests/test_offload_write_failclose.py)

## Verwandt

- [Runtimes Providers](runtimes-providers.md) und [Runtimes Provider](runtimes-provider.md) -- Vertraege, Katalog, Personas, Reporting
- [Runtimes](runtimes.md) -- der Broker, der `ClaudeCLIProvider.run` bedient
- [Runtimes Admission](runtimes-admission.md) -- die Praegung der verlangten Autoritaet
- [Runtimes Execution](runtimes-execution.md) -- Bepreisung der hier ausgeloesten Spawns und HTTP-Aufrufe
- [Kernel-Policy](kernel-policy.md) -- `ExecutionLimitPolicy`, `Estimate`, `Ledger`
- [Lanes](lanes.md) -- `run_checks`, `WriteAttempt`, `graph_brief`, die Schreib-Gates dieser Provider
- [Council](council.md) -- eine zweite, unabhaengige Vendor-Oberflaeche
- [Orchestration](orchestration.md) und [Orchestration Ikarus](orchestration-ikarus.md) -- die Aufrufer
- [Tools](../tooling/tools.md) -- `tools/guarded_call.py`, `tools/funnel.py` sprechen dieselben Lanes von aussen an
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** wie viele der `caps`-Felder von Aufrufern tatsaechlich als
  Autorisierung statt als Beschreibung gelesen werden. `OllamaProvider` und
  `DeepSeekProvider` dokumentieren beide, dass ihr Klassenflag die Laufzeit
  nicht beschreibt; ob jeder Konsument das beachtet, ist aus diesem Paket nicht
  ablesbar.
- **Ungeklaert:** ob `deepseek.py` weiterhin `daedalus.limit_policy` statt
  `daedalus.kernel.policy.limits` importieren soll. Beide Pfade existieren im
  Baum; welcher der kanonische ist, entscheidet die Fassaden-Regel des Kernels,
  nicht dieses Paket.
- **Ungeklaert:** ob `chat_stream` aus `_openai_compat` heute noch einen
  Produktionsaufrufer hat.

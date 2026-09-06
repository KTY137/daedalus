---
title: Orchestrierung (Paketwurzel)
type: module
status: living
updated: 2026-09-05
covers: daedalus/orchestration
---
# Orchestrierung (Paketwurzel)

`daedalus/orchestration` ist die Ikarus-Seite des Systems: die Schicht, die aus
Absicht eine Aufgabe, aus einer Aufgabe einen Auftrag und aus einem Auftrag
eine Reihe von Attempts macht. Der Paket-Docstring formuliert die Grenze in
zwei Saetzen: *"The package owns composition only. Mission, work-item, effect,
attempt and evidence authority remains in the existing kernel contracts and
execution ports."* Das ist Masterplan §7 in Code: Ikarus beantwortet, **wer**
mit **welchem Runtime**, **welchem Kontext**, **welchem Budget** und **welcher
Review-Kette** arbeitet — die Autoritaet ueber Effekte bleibt im Kernel.

Diese Seite deckt die **Wurzel** des Pakets ab, also die 21 Module direkt in
`daedalus/orchestration/`. Die vier Unterpakete haben eigene Seiten:

- [`missions/`](orchestration-missions.md) — der kanonische Missions-Ablauf
- [`execution/`](orchestration-execution.md) — Attempt-Ausfuehrung
- [`genesis/`](orchestration-genesis.md) — die Genesis-Produktionsstrecke
- [`ikarus/`](orchestration-ikarus.md) — die Assistenten-Naht (`shell.ask()`)

Gemessen 2026-09-05: 21 Dateien in der Wurzel, 9 704 Zeilen.

Das [`__init__.py`](../../../daedalus/orchestration/__init__.py) exportiert genau **einen** Namen, und den nur lazy: `run_mission`
aus `.missions`, aufgeloest ueber ein `__getattr__`. Alles andere muss explizit
importiert werden. Damit bleibt `import daedalus.orchestration` billig und ohne
Drittabhaengigkeit.

## Was hier wirklich liegt

Die Wurzel ist kein einzelnes Subsystem, sondern fuenf Gruppen:

**1. Routing und Rollen.** Wer bearbeitet eine Aufgabe?

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`agents_registry.py`](../../../daedalus/orchestration/agents_registry.py) | Laufzeit-CRUD fuer Agent-Rollen — dieselbe JSON, die der Router ueber `load_agents` liest. Schreibt ausschliesslich nach `<repo_root>/.agentenv/agents/<name>.json`; ohne `repo_root` wird abgelehnt, weil die gepackten Defaults read-only sind. | `role_path`, `validate_role`, `normalize_role`, `list_roles`, `get_role`, `create_role`, `update_role`, `delete_role`, `MODEL_TIERS` |
| [`categories.py`](../../../daedalus/orchestration/categories.py) | Rein additive Taxonomie ueber Rollen (Icon/Farbe/Lane/Tier-Presets fuer die GUI). Trifft **nie** eine Routing-Entscheidung; `preset_for` liefert nur einen Vorschlag. | `validate`, `normalize`, `load`, `get`, `update`, `preset_for`, `get_categories_joined`, `LANES`, `CATEGORIES_PATH` |
| [`semantic_route.py`](../../../daedalus/orchestration/semantic_route.py) | Stufe-1-Routing per Embedding-Aehnlichkeit gegen ein lokales Ollama-Modell, mit hartem Fallback auf den Keyword-Router. | `semantic_route`, `semantic_route_explained`, `LatentRouteResult` |
| [`fallback.py`](../../../daedalus/orchestration/fallback.py) | Entscheidet, wie es weitergeht, wenn Claude verfuegbar, blockiert oder abwesend ist. Der Docstring korrigiert sich selbst: die erste Verzweigung behandelt den *Erfolgsfall*, nicht nur den Ausfall. | `fallback_decision`, `DEFAULT_POLICY` |
| [`hierarchy.py`](../../../daedalus/orchestration/hierarchy.py) | Hierarchie-Graph (Knoten/Kanten) fuer die Agent-OS-Weboberflaeche, plus validiertes Schreiben der Team-Konfiguration. | `capabilities`, `hierarchy`, `save_team`, `CAPABILITIES`, `MAX_WORKERS_CEILING`, `TEAM_FIELD_VALIDATORS` |
| [`control_plane.py`](../../../daedalus/orchestration/control_plane.py) | Projektion "was ist konfiguriert": Claude- und Codex-Oberflaeche eines Projekts, vereinheitlichte Agentenprofile, Autonomiestufe je Capability. | `claude_surface`, `codex_surface`, `unified_profiles`, `resolve_autonomy`, `save_autonomy`, `AUTONOMY_MODES`, `CAPABILITY_GATES` |

**2. Runtimes und Modelle.** Womit wird gearbeitet?

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`runtime_registry.py`](../../../daedalus/orchestration/runtime_registry.py) | Stabile Status-/Test-Oberflaeche fuer CLI-Runtimes (Claude Code CLI, Codex CLI, Ollama HTTP/CLI …), statt verstreuter Subprozess-Aufrufe. Enthaelt die Kommando-Aufloesung inklusive VS-Code-Extension-Kandidaten. | `RuntimeSpec`, `runtime_status`, `all_status`, `test_runtime`, `cached_runtime_status`, `reset_status_cache`, `resolve_runtime_command`, `runtime_subprocess_env` |
| [`llm_client.py`](../../../daedalus/orchestration/llm_client.py) | Vendor-neutrale Auswahl- und Aufrufpolitik. Besitzt *Selektion*, nicht *Effekt* — die Transporte bleiben in `orchestration/ikarus/shell.py` hinter der Provider-Effektgrenze. `auto` heisst "nimm ein verfuegbares LLM", nie "falle still auf deterministischen Hilfetext zurueck". | `IkarusLLMClient`, `LLMRequest`, `LLMResponse`, `LLMSelection`, `LLMToolCall`, `LLMUnavailable`, `normalize_provider` |

**3. Kontext.** Was bekommt das Modell zu sehen?

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`context_plan.py`](../../../daedalus/orchestration/context_plan.py) | Hybride, evidenztragende Kontextplanung ueber den Knowledge Forest: BM25 ueber Pfad- und Symbolnamen, optional eine latente Suche ueber versionierte Agent-Event-Projektionen, dann Fusion und deterministische Propagation. | `plan_context`, `ContextPlanningResult`, `LexicalSeedResult`, `LatentSeedResult`, `HybridSeedResult`, `lexical_seed_scores`, `latent_memory_seed_scores`, `latent_not_requested`, `fuse_seed_scores` |
| [`editor_context.py`](../../../daedalus/orchestration/editor_context.py) | Begrenzter Editor-Kontext (Datei, Selektion, Diagnosen) als content-adressiertes Artefakt, plus prozess-lokale, kurzlebige Editor-Sessions. | `create_context`, `get_context`, `materialize_capsule`, `EditorSessionRegistry`, `EditorContextError`, `EditorContextRefused`, `UnknownEditorContext`, `UnknownEditorSession` |
| [`gui_catalogue.py`](../../../daedalus/orchestration/gui_catalogue.py) | Ein Katalog verfuegbarer GUI-Bausteine als StructCore-foermige Knotenart. Reine **Daten**: kein Runtime, kein npm-Paket, kein zweiter Ranking-Motor. | `Catalogue`, `CatalogueEntry`, `PropSpec`, `Provenance`, `RejectedEntry`, `CatalogueError`, `SearchHit`, `SearchResult`, `parse_entry`, `load_catalogue`, `search`, `render_for_prompt`, `use_mode_for_licence` |

**4. Gespraech und Anfragen.** Was hat der Nutzer eigentlich gewollt?

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`conversation.py`](../../../daedalus/orchestration/conversation.py) | Lese-/Schreibfassade des Chat-Seams ueber die kanonische Spine. **Kein Store**: jeder Schreibvorgang ist ein typisiertes Intent auf `SpineLedger`. Drei Event-Arten: `conversation.turn`, `conversation.dispatch`, `conversation.dispatch.report`. | `ConversationStore`, `Turn`, `DispatchLink`, `DispatchEvent`, `ConversationProjectBinding`, `ConversationError`, `UnknownConversation`, `UnknownTurn`, `UnknownDispatch`, `DuplicateDispatchRef`, `ConflictingDispatchEvent`, `ConversationProjectConflict`, `conversation_effect_key`, `new_conversation_id`, `default_store`, `default_db_path`, `recent_turns_context`, `is_project_binding_conflict` |
| [`conversation_requests.py`](../../../daedalus/orchestration/conversation_requests.py) | Idempotente, beobachtbare Generierungsanfragen. Die offene Absicht wird aufgezeichnet, **bevor** Provider-Arbeit startet; ein Reconnect kann den Aufruf daher nicht wiederholen. Nach Serverneustart gilt eine unaufgeloeste Anfrage als `unknown` und wird nie automatisch nachgespielt. | `ConversationRequestManager`, `ConversationRequestError`, `UnknownConversationRequest`, `ConflictingConversationRequest`, `ConflictingConversationProject`, `default_manager`, `new_client_request_id`, `KIND_GENERATION`, `KIND_CANCELLATION` |

**5. Ausfuehrung, Pruefung, Messung.**

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`runbook.py`](../../../daedalus/orchestration/runbook.py) | Komponiert genau ein Run-Brief und schreibt es nach `runs/<run_id>.json`. `_write_brief` ist der einzige Writer beider Engines. | `create_run`, `main`, `RUN_DIR` |
| [`langgraph_adapter.py`](../../../daedalus/orchestration/langgraph_adapter.py) | Dieselben vier Schritte von `create_run` als LangGraph-Graph ueber dieselben State-Keys, plus die beratende Flottenplanung. Rein, opt-in, ohne eigenen Zustand. | `run_brief`, `build_graph`, `build_advisory_fleet_graph`, `plan_advisory_fleet`, `BriefState`, `AdvisoryFleetState`, `LangGraphUnavailable`, `langgraph_available`, `tracing_is_pinned_off`, `MAX_ADVISORY_FLEET_CAPACITY` |
| [`loop.py`](../../../daedalus/orchestration/loop.py) | Der Loop-Treiber: `pick -> attempt -> gate -> nominate -> re-pick`, bis eine Abbruchbedingung greift. Groesstes Modul der Wurzel (1 727 Zeilen), und fast alles davon sind Fehlermodi. | `LoopDriver`, `LoopBounds`, `LoopLedger`, `LoopReport`, `IterationResult`, `LoopMisconfigured`, `render`, `main`, `read_spend` |
| [`verifier.py`](../../../daedalus/orchestration/verifier.py) | Das Qualitaetstor der Kaskade: billige deterministische Checks (Report-Schema, Python-Syntax, JS/HTML/Config, Prosa-Erhalt), optional die Projekt-Testsuite. | `verify`, `VerifyResult`, `prose_before_images`, `DEFAULT_TEST_TIMEOUT_S` |
| [`benchmark.py`](../../../daedalus/orchestration/benchmark.py) | Legacy-Kostenschaetzer fuer Routing-Formen. Mechanisch als `planning_estimate` gelabelt und ausdruecklich **nicht** als Vergleichsevidenz zulaessig. | `run`, `run_live`, `main`, `Task`, `LiveBenchmarkRetired`, `ESTIMATE_SCHEMA`, `ESTIMATE_CLASSIFICATION`, `LIVE_BENCHMARK_RETIREMENT`, `POSTURE` |
| [`legacy_reports.py`](../../../daedalus/orchestration/legacy_reports.py) | Legacy-Task- und Run-Projektionen. Drahtkompatible Exporte aus `daedalus.schemas`, aber **keine** Kernel-Vertraege: keine Evidenz-Identitaet, keine Promotion. | `AgentTask`, `RunState`, `AgentReport`, `validate_report`, `REPORT_KEYS` |
| [`workspace_containment.py`](../../../daedalus/orchestration/workspace_containment.py) | 22 Zeilen: die eine Orchestrierungs-Tatsache, dass der Default-Attempt-Manager Worktrees unter seiner konfigurierten Wurzel plant. Stellt keine Lease aus. | `resolve_worktree_root` |

## Der LangGraph-Adapter: warum genau ein Ablauf

Der Adapter ist der interessanteste Grenzfall des Pakets, weil er eine
Bibliothek einlaesst, die leicht zu einer zweiten Control Plane werden koennte.
Masterplan §13 verbietet das, §9.2 laesst externe Bibliotheken nur "behind
adapters" zu. Der Docstring nennt vier Eigenschaften, die genau das absichern:

1. Der Graph ist **rein** — er berechnet das Payload und schreibt nichts.
   Einziger Writer bleibt `create_run` bzw. dessen `_write_brief`.
2. Der Graph traegt **keinen eigenen Zustand** — sein Schema ist `RunState`
   plus der Task, nichts Erfundenes.
3. Er ist **opt-in** — `create_run` nimmt `engine="langgraph"` nur, wenn ein
   Aufrufer ihn beim Namen nennt; Default ist `"stdlib"`.
4. Nichts unter `daedalus/` importiert das Modul auf Modulebene, das Paket
   importiert also weiter mit null Drittabhaengigkeiten.

Der Vertrag: fuer identische Eingaben — inklusive `run_id`, den der Aufrufer
liefert statt der Graph ihn zu praegen — gibt `run_brief(...)` ein Payload
zurueck, das dem stdlib-Payload gleicht, ausser den beiden Feldern, die eine
Uhr lesen (`state.created_at` und der Zeitstempel im ersten Event). Genau das
prueft [`test_langgraph_adapter.py`](../../../tests/test_langgraph_adapter.py),
und zwar gegen den echten Router statt gegen einen Stub.

`engine="langgraph"` kennt bewusst **keinen** stillen Fallback: fehlt das
optionale `orchestration`-Extra, fliegt `LangGraphUnavailable`. Damit hat die
Frage "welche Engine hat dieses Brief erzeugt?" immer eine Antwort.
`plan_advisory_fleet` nutzt einen zweiten reinen Graph im selben Adapter: er
plant Rollenzuordnungen (Kapazitaet global gedeckelt durch
`MAX_ADVISORY_FLEET_CAPACITY = 20`), startet aber keinen Provider, reserviert
kein Budget, fasst keinen Workspace an und erinnert sich an keinen Zyklus.

## Der Loop und seine vier Grenzen

`loop.py` ist der einzige Einstiegspunkt im Baum, der mehr als einen Attempt
laeuft. `LoopBounds` haelt drei "Wieviel"-Grenzen, von denen **jede einzelne**
den Loop anhaelt: `max_iterations`, `max_wall_clock_s`, `max_spend_usd`. Die
vierte, `max_attempts_per_candidate`, ist eine Konvergenzgrenze — sie
verhindert, dass das gesamte Budget in einen Kandidaten fliesst, der nie
besteht.

Es gibt **kein Sentinel fuer "unbegrenzt"**. `__post_init__` verlangt positive
Ganzzahlen fuer die Zaehlgrenzen und positive endliche Gleitkommazahlen fuer
Dauer und Ausgabe, damit IEEE-754 `NaN`/`Infinity` keinen Vergleich dauerhaft
falsch machen kann. Ein unbegrenzter Loop ist genau der Fehler, gegen den das
Modul existiert.

Der Loop implementiert nichts davon selbst: `build_queue` aus
`daedalus.spine.picker` sagt, woran gearbeitet wird; `WaveExecutor.run_wave`
macht Attempt, Gate und versiegelte Kandidatenuebergabe; `KillSwitch` ist der
Stop; `daedalus.budget` die Decke. Er ruft weder `run_attempt` noch
`promote_candidates` direkt auf — er *kann* also nicht auto-promoten
(Invariante 5).

Ein Detail, das leicht als Fehler gelesen wird: **Laufen bei roter Governance
ist der Normalfall, kein Fehler.** Meldet `get_governance()`
`promotion_allowed: False`, picked, attemptet und gated der Loop weiter — und
promotet nichts. Jeder Kandidat, der sein Gate besteht, bleibt als
persistiertes Patch-Artefakt fuer die Owner-Pruefung liegen.

## Trust-Grenzen / Effekte

Die Wurzel ist **nicht** effektfrei; sie enthaelt aber nur wenige, benannte
Schreibpfade:

- `runbook._write_brief` — der einzige Writer beider Run-Brief-Engines,
  schreibt nach `runs/<run_id>.json`.
- `agents_registry.create_role` / `update_role` / `delete_role` — schreiben
  ausschliesslich unter `<repo_root>/.agentenv/agents/`. `_write_dir_for`
  wirft ohne `repo_root`, damit die gepackten Templates unter
  `templates/agents/` nie mutiert werden.
- `categories.update` — dieselbe Konstruktion nach
  `<repo_root>/.agentenv/categories.json`; die ausgelieferte globale
  `agents/categories.json` bleibt unveraendert.
- `hierarchy.save_team` und `control_plane.save_autonomy` — schreiben
  Projektzeilen ueber `foundation.projects.rewrite_project_team` bzw. die
  Autonomie-Konfiguration.
- `conversation.ConversationStore` und `conversation_requests.ConversationRequestManager`
  — schreiben ausschliesslich als typisierte Intents auf `SpineLedger`, den
  kanonischen Event Store. Kein eigenes Schema, keine eigene Datei.
- `editor_context.create_context` / `materialize_capsule` — legen
  content-adressierte Artefakte ueber `kernel.artifacts.store_canonical_json`
  ab; die Editor-Sessions selbst sind prozesslokal und koennen weder Dateien
  schreiben noch Shells starten noch Policy aendern noch promoten.
- `verifier.verify` und `runtime_registry` starten Subprozesse
  (`py_compile`, Linter, Testsuite, `--version`-Aufrufe). `verifier` hat mit
  `DEFAULT_TEST_TIMEOUT_S = 120` eine Runaway-Bremse, ausdruecklich als
  Runaway-Guard und nicht als Performance-Budget dokumentiert.
- `loop.LoopDriver.run` verursacht die groessten Effekte des Pakets, aber
  ausschliesslich mittelbar ueber `WaveExecutor` und die dortigen Leases.

Read-only bzw. rein: `fallback`, `legacy_reports`, `langgraph_adapter`
(Graph rein), `benchmark.run`, `workspace_containment`, `context_plan`,
`gui_catalogue`, `hierarchy.hierarchy`, `control_plane.unified_profiles`.

Drei Stellen, die *aussehen*, als traefen sie eine Autoritaetsentscheidung, es
aber ausdruecklich nicht tun:

- `categories.preset_for` liefert nur ein vorgeschlagenes `{lane, tier}`. Die
  fail-closed Lane-Logik in `provider_router` bleibt autoritativ.
- `llm_client` waehlt ein Modell aus; Auswahl gewaehrt niemals Datei-, Tool-,
  Policy-, Evaluator- oder Promotionsrechte (Masterplan §7, letzter Absatz).
- `benchmark` hatte historisch einen `--live`-Pfad, der `offload` direkt rief
  und "MEASURED"-Ersparnisse druckte. Das war eine zweite Evaluationsschleife
  neben [`daedalus/eval`](eval.md) ohne eingefrorene Aufgaben, gleiche Budgets,
  Modell-/Hardware-Identitaet, wiederholte Seeds, aufbewahrte Fehlschlaege oder
  Unsicherheit. Der Pfad ist zurueckgezogen (`LiveBenchmarkRetired`), nicht
  ausgebaut.

## Ehrlichkeitsvertraege im Code

Mehrere Module dokumentieren einen *gemessenen* Fehler statt ihn zu tilgen —
das ist die Regel "negative Evidenz aufbewahren" aus `AGENTS.md` in Praxis:

- `semantic_route.py` hat einen expliziten Abschnitt `HONESTY CONTRACT`. Die
  alte Fassung gab auf jedem Pfad ein blankes Agent-Dict zurueck, sodass "die
  latente Route lief und waehlte ui-ux-dev" und "die latente Route lief nie,
  weil das Embedding-Modell fehlt" fuer den Aufrufer Byte fuer Byte
  ununterscheidbar waren. Heute traegt jede Route Provenienz
  (`LatentRouteResult` nennt Mechanismus und ggf. Fehlerart), und eine
  uebersprungene latente Route erzeugt zusaetzlich eine `logging.WARNING`.
  Drei Fehlermodi sind dort als gemessen (2026-07-29) vermerkt, darunter
  Cache-Poisoning: `_role_vectors` war `@lru_cache`d und cachte sein `None`,
  ein transienter Aussetzer beim Prozessstart deaktivierte die latente Route
  fuer die gesamte Prozesslebensdauer. Fehlschlaege werden nicht mehr gecacht.
- `fallback.fallback_decision` korrigiert seinen eigenen alten Docstring: er
  behandelt nicht nur "Claude fehlt oder ist blockiert", sondern in der ersten
  Verzweigung den Erfolgsfall — wer den alten Satz las und die Funktion auf
  dem Happy Path uebersprang, uebersprang die Verzweigung, die den Happy Path
  entscheidet.
- `verifier.VerifyResult` trennt `fail` von `inconclusive`. Ein blockierender
  Check ohne Verdikt heisst "wir konnten es nicht feststellen" und wird anders
  geroutet als "der Write ist schlecht"; `fail` schlaegt `inconclusive`, wenn
  beides vorliegt, und `inconclusive` darf nie als Erlaubnis gelesen werden.
- `gui_catalogue` haelt den Grund fest, warum es Daten und keine Abhaengigkeit
  ist, mit Verweis auf ADR-002 und ADR-017 (beide abgelehnt, weil sie einen
  zweiten Scheduler/Ledger mitbrachten) und auf das gemessene Ergebnis vom
  2026-07-29, dass shadcns `registry-item.json` weder `props` noch `api` noch
  Lizenz-/Provenienzfelder kennt.

## Tests

Gemessen 2026-09-05, je Modul der Wurzel:

| Modul | Tests |
| --- | --- |
| `loop` | [`test_loop.py`](../../../tests/test_loop.py), [`test_loop_bound_safety.py`](../../../tests/test_loop_bound_safety.py), [`test_loop_cap_policy.py`](../../../tests/test_loop_cap_policy.py), [`test_loop_entrypoint_guard.py`](../../../tests/test_loop_entrypoint_guard.py), [`test_loop_governance_head.py`](../../../tests/test_loop_governance_head.py), [`test_loop_lease_receipt.py`](../../../tests/test_loop_lease_receipt.py), [`test_loop_spend_refused.py`](../../../tests/test_loop_spend_refused.py), [`test_loop_terminal_rendering.py`](../../../tests/test_loop_terminal_rendering.py), [`test_continuous_daedalus_scheduler.py`](../../../tests/test_continuous_daedalus_scheduler.py), [`test_spine_outer_ports.py`](../../../tests/contracts/test_spine_outer_ports.py) |
| `conversation`, `conversation_requests` | [`test_conversation_on_canonical_spine.py`](../../../tests/test_conversation_on_canonical_spine.py), [`test_conversation_requests.py`](../../../tests/test_conversation_requests.py), [`test_conversation_list.py`](../../../tests/test_conversation_list.py), [`test_conversation_legacy_entrypoint_binding.py`](../../../tests/test_conversation_legacy_entrypoint_binding.py), [`test_http_sse_owner.py`](../../../tests/interfaces/test_http_sse_owner.py), [`test_observation_state_hierarchy.py`](../../../tests/contracts/test_observation_state_hierarchy.py) |
| `langgraph_adapter`, `runbook` | [`test_langgraph_adapter.py`](../../../tests/test_langgraph_adapter.py), [`test_opus_fleet_watchdog.py`](../../../tests/test_opus_fleet_watchdog.py), [`test_cli_effect_boundary.py`](../../../tests/test_cli_effect_boundary.py) |
| `verifier` | [`test_verify_gate.py`](../../../tests/test_verify_gate.py), [`test_verify_test_budget.py`](../../../tests/test_verify_test_budget.py), [`test_prose_gate.py`](../../../tests/test_prose_gate.py), [`test_cascade.py`](../../../tests/test_cascade.py), [`test_hardening.py`](../../../tests/test_hardening.py), [`test_era1_robustness.py`](../../../tests/test_era1_robustness.py), [`test_fake_offload.py`](../../../tests/test_fake_offload.py) |
| `semantic_route` | [`test_semantic_route_wired.py`](../../../tests/test_semantic_route_wired.py), [`test_semantic_route_cold_start.py`](../../../tests/test_semantic_route_cold_start.py), [`test_semantic_route_live.py`](../../../tests/test_semantic_route_live.py), [`test_health_surface.py`](../../../tests/test_health_surface.py) |
| `runtime_registry` | [`test_runtime_registry_portable.py`](../../../tests/test_runtime_registry_portable.py), [`test_trust_flags_agree.py`](../../../tests/runtimes/test_trust_flags_agree.py), [`test_ikarus_stream.py`](../../../tests/test_ikarus_stream.py), [`test_ikarus_context.py`](../../../tests/test_ikarus_context.py), [`test_ikarus_chat_shim_argv.py`](../../../tests/test_ikarus_chat_shim_argv.py), [`test_wires.py`](../../../tests/test_wires.py) |
| `context_plan` | [`test_context_plan.py`](../../../tests/test_context_plan.py), [`test_context_plan_latent.py`](../../../tests/test_context_plan_latent.py), [`test_markdown_nodes.py`](../../../tests/test_markdown_nodes.py), [`test_projection_worker.py`](../../../tests/test_projection_worker.py), [`test_typegraph_regression.py`](../../../tests/test_typegraph_regression.py) |
| `agents_registry`, `categories` | [`test_agents_registry.py`](../../../tests/test_agents_registry.py), [`test_categories.py`](../../../tests/test_categories.py), [`test_categories_integration.py`](../../../tests/test_categories_integration.py), [`test_packaged_resources.py`](../../../tests/test_packaged_resources.py) |
| `control_plane`, `hierarchy` | [`test_project_row_rewrite.py`](../../../tests/test_project_row_rewrite.py), [`test_web_api.py`](../../../tests/test_web_api.py) |
| `llm_client` | [`test_llm_client.py`](../../../tests/test_llm_client.py), [`test_ikarus_llm_voice.py`](../../../tests/test_ikarus_llm_voice.py), [`test_ikarus_computer_loop.py`](../../../tests/test_ikarus_computer_loop.py) |
| `editor_context` | [`test_editor_context.py`](../../../tests/test_editor_context.py) |
| `gui_catalogue` | [`test_gui_catalogue.py`](../../../tests/test_gui_catalogue.py) |
| `benchmark` | [`test_benchmark_authority.py`](../../../tests/test_benchmark_authority.py), [`test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py) |
| `legacy_reports` | [`test_contract_hierarchy.py`](../../../tests/kernel/test_contract_hierarchy.py), [`test_provider_report_contract_owner.py`](../../../tests/runtimes/test_provider_report_contract_owner.py) |
| `workspace_containment` | [`test_attempt_lease.py`](../../../tests/kernel/test_attempt_lease.py), [`test_effect_lease_issuer_rule.py`](../../../tests/kernel/test_effect_lease_issuer_rule.py), [`test_genesis_effect_lease.py`](../../../tests/kernel/test_genesis_effect_lease.py), [`test_lease_authority_subject_split.py`](../../../tests/kernel/test_lease_authority_subject_split.py), [`test_loop_lease.py`](../../../tests/test_loop_lease.py), [`test_loop_lease_policy.py`](../../../tests/test_loop_lease_policy.py) |
| `fallback` | [`test_agent_env.py`](../../../tests/test_agent_env.py) |
| Paketstruktur | [`test_import_scc_hierarchy.py`](../../../tests/contracts/test_import_scc_hierarchy.py) |

## Verwandt

- [Orchestrierung: Missionen](orchestration-missions.md),
  [Orchestrierung: Ausfuehrung](orchestration-execution.md),
  [Orchestrierung: Genesis](orchestration-genesis.md),
  [Orchestrierung: Ikarus](orchestration-ikarus.md) — die vier Unterpakete
- [Kernel](kernel.md) und [Kernel-Vertraege](kernel-contracts.md) — wo die
  Autoritaet ueber Mission, Attempt, Lease und Evidenz tatsaechlich liegt
- [Spine](spine.md) — `SpineLedger`, `picker`, `killswitch`
- [Runtimes](runtimes.md), [Runtimes-Provider](runtimes-provider.md),
  [Provider](providers.md) — die Transporte hinter `llm_client` und
  `runtime_registry`
- [Kairos](kairos.md) — `GitWorktreeManager`, `gated_writes`
- [Schreib-Lanes](lanes.md) — die Basispruefungen unmittelbar vor dem Schreiben
- [Eval](eval.md) — die kanonische Evaluationslinie, gegen die `benchmark`
  ausdruecklich abgegrenzt ist
- [Speicher](memory.md) und [StructCore](structcore.md) — die Quellen, aus
  denen `context_plan` seine Seeds zieht
- [Gates](gates.md) und [Repository-Gates](gates-repository.md) — die
  Schreibflaechen-Inventare, in denen die Writer dieses Pakets auftauchen
- [Rat](council.md) — der Cross-Vendor-Zweitmeinungspfad
- [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md),
  [Wiki-Index](../index.md), [Feature-Backlog](../feature-backlog.md)

## Ungeklaert

- **Ungeklaert:** `runbook.py` importiert `AgentTask` und `RunState` aus
  `daedalus.schemas`, waehrend `legacy_reports.py` dieselben Namen selbst
  definiert und als "wire-compatible exports of `daedalus.schemas`" beschreibt.
  Ob `daedalus/schemas.py` diese Klassen aus `legacy_reports` reexportiert oder
  eigene haelt, ist aus diesen beiden Dateien allein nicht entscheidbar
  (`daedalus/orchestration/runbook.py:8`, `legacy_reports.py:23`).
- **Ungeklaert:** `benchmark.run_live` existiert weiterhin als Funktion, wirft
  aber laut Modul-Docstring `LiveBenchmarkRetired`. Ob irgendein Aufrufer sie
  noch erreicht oder sie nur als sprechender Grabstein steht, habe ich nicht
  gemessen (`daedalus/orchestration/benchmark.py:182`).
- **Ungeklaert:** `fallback.py` hat keinen Modul-Docstring und wird nur von
  [`test_agent_env.py`](../../../tests/test_agent_env.py) referenziert. Wer
  `fallback_decision` produktiv aufruft, ist mir nicht klar geworden.
- **Ungeklaert:** `hierarchy.py` und `control_plane.py` bedienen beide eine
  "Agent-OS-Weboberflaeche" und ueberlappen in den Projektionen (Rollen,
  Capabilities, Autonomie). Welche der beiden die GUI heute tatsaechlich
  liest, ist aus dem Paket nicht ablesbar — siehe
  [GUI](gui.md) und [HTTP-Schnittstelle](interfaces-http.md).
- **Ungeklaert:** Der Docstring von `llm_client.py` verweist auf
  `daedalus.orchestration.ikarus.shell` als Ort der Transporte; ob dort
  tatsaechlich *alle* Provider-Aufrufe liegen oder einzelne noch anderswo,
  gehoert zur [Ikarus-Seite](orchestration-ikarus.md).

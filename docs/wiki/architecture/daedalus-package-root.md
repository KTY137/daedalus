---
title: Daedalus-Paketwurzel
type: module
status: living
updated: 2026-09-05
covers: daedalus
---
# Daedalus-Paketwurzel

Die Module direkt in `daedalus/` sind die aelteste Schicht des Repositories und
heute eine gemischte Menge aus drei Sorten: (1) **Primitive**, die tiefer liegen
als jedes Subsystem und deshalb nicht in ein Unterpaket wandern koennen
(atomares Publizieren, Append-Journal, Artefaktspeicher, Primary-Checkout-Zaun,
Sensitivitaets- und Schreib-Klassifikation); (2) **Workloads**, die der Kernel
von unten als Port entgegennimmt statt sie zu importieren (vor allem
`offload` und die Build-Wellen); (3) **Kompatibilitaetsfassaden**, die einen
historischen Importpfad erhalten, waehrend die Implementierung im kanonischen
Besitzer liegt ([Kernel](kernel.md), [Kernel-Contracts](kernel-contracts.md),
[Runtimes](runtimes.md), [Orchestration](orchestration.md)).

Im Bild des Masterplans ist das hier nicht der Kernel selbst, sondern der Ring
darum: Daedalus-Kernelvertraege liegen unter `daedalus/kernel`, die
Effekt-Buchfuehrung unter [Spine](spine.md); die Wurzelmodule rufen sie auf,
sie ersetzen sie nicht. Jede effektfaehige `main` hier oeffnet zuerst
`begin_effect` gegen die Registry der Effekt-Grenze und erst danach ihre
Argumente.

Gemessen 2026-09-05: 32 Python-Dateien direkt in `daedalus/`, zusammen 16071
Zeilen. Die Unterpakete (`kernel`, `spine`, `twin`, `runtimes`, `orchestration`
und weitere) sind eigene Wiki-Seiten und hier nur verlinkt.

## Module

### Effekt- und Speicher-Primitive

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [atomic.py](../../../daedalus/atomic.py) | Atomares Publizieren kleiner Dateien mit dem Windows-Retry, der die Behauptung erst wahr macht: ein Leser ohne Delete-Sharing laesst das Ersetzen mit einem Zugriffsfehler scheitern. | `write_text_atomic`, `write_bytes_atomic`, `publish_bytes_once`, `replace_with_retry`, `ExclusiveFileLock`, `FileLockUnavailable` |
| [journal_io.py](../../../daedalus/journal_io.py) | Atomares Anhaengen fuer jedes Append-only-Journal des Repositories; liegt bewusst neben `atomic`, damit die untersten Schreiber es ohne Importzyklus nutzen koennen. | `append_lines`, `ShortJournalWrite` |
| [storage.py](../../../daedalus/storage.py) | Zwei kleine Vertraege: die fail-closed Speicher-Wassermarke vor Worktree-Allokation und der inhaltsadressierte Artefaktspeicher (create-once, SHA-256, unveraenderlicher Locator). Kein Event Store, keine Promotion. | `ArtifactStore`, `ArtifactLocator`, `check_storage`, `require_storage`, `artifact_manifest`, `artifact_locator_uri`, `StorageStatus`, `StorageUnavailable`, `ArtifactDigestMismatch`, `ArtifactCorruption`, `ArtifactNotFound`, `ArtifactStoreError` |
| [primary_tree.py](../../../daedalus/primary_tree.py) | Der Primary-Checkout-Zaun. Beantwortet genau eine Frage rein ueber Dateisystem-Identitaet (Device/Inode, aufgeloeste Geometrie): landen diese Bytes im primaeren Checkout? Nimmt keine Policy und keine Umgebungsvariable entgegen. | `assert_write_allowed`, `write_blocked_reason`, `overlap_reason`, `planned_overlap_reason`, `nearest_existing`, `PrimaryCheckoutWrite` |
| [sensitivity.py](../../../daedalus/sensitivity.py) | Drei unabhaengige Gates mit disjunkten Konfigfeldern und unterschiedlichen Defaults: Daten-Egress (fail-closed), Schreib-Confinement und Change-Risk. Dazu der unbedingte Secret-Floor und die Loopback-Praedikate. | `Policy`, `load_policy`, `classify_data`, `DataClass`, `path_write_blocked`, `change_risk`, `secret_floor_rule`, `slice_egress_rule`, `is_loopback_host`, `is_loopback_literal`, `lane_for_host`, `declared_trusted_hosts`, `intersect_write_allow`, `resolve_write_target`, `anchor_for_policy`, `protected_artifact_reason`, `write_intent_blocked`, `mentions_protected_path`, `read_inlined_context`, `WriteIntentError` |
| [budget.py](../../../daedalus/budget.py) | Geld-Obergrenze, ledger-gestuetzt und prozessuebergreifend. Heute eine Fassade ueber [Kernel-Policy](kernel-policy.md) (Pricing, Ledger) und [Runtimes Execution](runtimes-execution.md) (Prozessnetz); der Einbau des Netzes bleibt hier. | `install_process_guard`, `process_guard_boundary_decision` |
| [limit_policy.py](../../../daedalus/limit_policy.py) | Reine Fassade auf die kanonische Limit-Policy des Kernels; enthaelt absichtlich keinen Policy-Zustand. | re-exportiert `ExecutionLimitPolicy`, `LimitAxes`, `LimitMode`, `LimitPolicyError`, `load_from_env`, `store_in_env` |

### Routing, Offload, Konfiguration

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [router.py](../../../daedalus/router.py) | Stufe 1 des Routings: welche Spezialisten-Rolle besitzt diese Aufgabe? Rollen kommen aus den wheel-gepackten Defaults oder aus dem Agenten-Verzeichnis des Zielrepos. | `route_task`, `load_agents` |
| [provider_router.py](../../../daedalus/provider_router.py) | Stufe 2: wo laeuft die Rolle? Zwei Achsen, Datensensitivitaet und Change-Risk. Sensible Daten gehen nie an einen externen Anbieter. | `select_provider`, `route_and_select`, `ProviderDecision` |
| [offload.py](../../../daedalus/offload.py) | Die einzige Naht, die Arbeit an die lokale Bench gibt, das Ergebnis verifiziert und entweder akzeptiert oder eskaliert. Plant frei, fuehrt nur hinter einer persistierten Effect Lease aus. | `offload`, `OffloadCapability` |
| [metrics.py](../../../daedalus/metrics.py) | Eskalationsmessung: zaehlt jeden Routing-Ausgang und macht eine stille Eskalation zum teuren Modell sichtbar. Append-only JSONL. | `record`, `summary` |
| [config.py](../../../daedalus/config.py) | Portable Konfigurationsaufloesung pro Repo: Registry-Eintrag, sonst repo-lokale Agentenv-Konfiguration, sonst nichts -- und damit fail-closed: lesen und beraten ja, schreiben nein. | `resolve_project`, `init_repo`, `resolve_write_wave_policy`, `resolve_external_write_lanes`, `external_write_lanes_for_repo` |

### Build-Koordination

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [build.py](../../../daedalus/build.py) | Plant ein Feature als mehrwellige Build-Session: Zerlegung ueber `decompose`, Routing ueber `route_task`, Zuordnung Frontier-Builder gegen lokale Bench. Plant nur, fuehrt nichts aus. | `plan_build`, `BuildSession`, `Wave`, `BuildTask`, `assign_builder`, `load_session`, `wave_path_conflicts`, `mission_id_for_session`, `WorkItemIdentityError` |
| [build_exec.py](../../../daedalus/build_exec.py) | Die ausfuehrende Haelfte: schickt jede Welle durch den `KairosScheduler` und sammelt die Ergebnisse zurueck an die Tasks und auf die Platte. Erzwingt die eine Regel, wegen der es existiert -- nebenlaeufige Schreib-Tasks gegen einen geteilten Checkout sind unsicher. | `WaveExecutor`, `WaveResult`, `BuildRunReport`, `EffectBounds`, `UnsafeParallelWriteError` |

### Bruecken und Laufzeitprojektionen

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [claude_bridge.py](../../../daedalus/claude_bridge.py) | Strukturierter Claude-CLI-Adapter. Prompt-Bau und Parsing sind reine Helfer; der einzige Subprozessaufruf ist privat und laeuft erst, nachdem der Runtime-Broker Grant und Start-Receipt persistiert hat. | `build_prompt`, `ask_claude` |
| [file_bridge.py](../../../daedalus/file_bridge.py) | Der Datei-Bus aus Outbox, Inbox und Journal samt Watcher: genau-einmal-Verarbeitung ueber Abstuerze hinweg, Quarantaene fuer nicht verarbeitbare Requests, Heartbeat und Statusprojektion. Delegiert an [Interfaces Bridge](interfaces-bridge.md). | `enqueue`, `process_request`, `watch`, `bridge_status`, `stream_state`, `heartbeat_status`, `write_heartbeat`, `restart_hint`, `quarantine_request`, `quarantined_requests`, `handle_poison_request`, `unread_reports`, `mark_read`, `report_application_truth`, `reconcile_conversation_report`, `current_process_identity`, `codex_inline_brief_warning` |
| [desktop_runtime.py](../../../daedalus/desktop_runtime.py) | Desktop-Projektion und der einzige gepinnte Besitzer zugelassener Desktop-Effekte. Version 0.1.6 startet kein verwaltetes Kind (Bridge, Ollama, IDE, Docker, SSH) und haelt keine Terminierungsautoritaet. | `DesktopRuntimeManager`, `normalize_config`, `install_web_integration`, `install_tunnel_egress_policy`, `DesktopRuntimeError` |
| [core.py](../../../daedalus/core.py) | Die Aggregationsschicht hinter Mission Control und der Web-API: Team-Konfiguration, Provider-Health, Queue, Squads, Quality, Governance, Dashboard. Liest fremde Besitzer und ist selbst keine Autoritaet. | `get_dashboard`, `get_governance`, `get_queue`, `get_squads`, `get_quality`, `get_categories`, `team_config`, `provider_health`, `model_resources`, `watcher_status`, `routing_summary`, `enforcement_status`, `queue_task`, `review_diff`, `plan_ikarus`, `enforce_harness`, `process_bridge_payload`, `local_only_failure_report`, `envelope`, `now_iso` |

### Beobachtung, Provenienz, Bedienung

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [health.py](../../../daedalus/health.py) | Die Kernfrage des Betreibers: arbeitet das System, oder ist es nur vorhanden? Jede Zahl traegt ihre Herkunft; ein Fakt ohne Herkunft ist ein Fehler, kein Default. | `probe`, `assess`, `verdict`, `render`, `to_payload`, `Fact`, `Report`, `ProbeSpec`, `Ctx`, `measured`, `inherited`, `assumed`, `working`, `present`, `degraded`, `absent`, `unknown`, `hand_admission`, `hand_state`, `production_importers`, `ProvenanceError` |
| [doctor.py](../../../daedalus/doctor.py) | Bereitschaftspruefung: kann ueberhaupt offgeloadet werden, oder faellt alles auf Claude zurueck? Alle Proben lesend, ein Loopback-Aufruf plus PATH-Lookups. | `check`, `codex_status` |
| [status.py](../../../daedalus/status.py) | Die Konsolenansicht: was arbeitet, was ist nur vorhanden, was hat niemand ausgefuehrt. Die alten sechs Zaehler bleiben, aber beschriftet als Zaehler, nicht als Gesundheit. | `collect_status`, `print_counters` |
| [progress.py](../../../daedalus/progress.py) | Trennt konstruktiv, was ueber laufende Arbeit beobachtet ist, von dem, was lediglich behauptet wurde. Append-only JSONL, eine Zeile pro Beobachtung. | `ProgressLog`, `ProgressEvent`, `UnitProgress`, `BatchProgress`, `open_unit`, `claim_unit`, `heartbeat`, `record_generating`, `record_tool_ran`, `record_gate_verdict`, `record_disk_change`, `record_patch_produced`, `record_done`, `snapshot`, `batch_snapshot`, `render_batch`, `default_log`, `reset_default_log`, `parse_iso`, `format_age`, `ProgressError`, `UnknownUnit` |
| [progress_sources.py](../../../daedalus/progress_sources.py) | Adapter von Signalen, die dieses Repo ohnehin erzeugt, auf das Ereignisvokabular von `progress`. Keine zweite Wahrheitsquelle: entweder Umformung eines bereits gehaltenen Ergebnisses oder ein rein lesender Poll. | `watch_stream`, `record_offload_result`, `record_attempt_result`, `track_call`, `snapshot_from_ledger`, `snapshot_from_bridge`, `snapshot_any`, `open_attempts` |
| [shift.py](../../../daedalus/shift.py) | Deklarierte Arbeitsfenster und dauerhafter Schichtkontext fuer autonome Agenten; darunter die deterministische Persistenz der urspruenglichen Laborvertraege. | `Shift`, `ShiftManager`, `WorkingWindow`, `load`, `start`, `note`, `end`, `StateCorruptError` |
| [shift_hook.py](../../../daedalus/shift_hook.py) | Hook auf das Absenden eines Prompts: legt Uhrzeit, Ziel und Restfenster in jeden Turn, weil ein Modell nicht weiss, dass es die Zeit nicht kennt. | `main` |
| [shift_ticker.py](../../../daedalus/shift_ticker.py) | Die Ansicht fuer den Menschen: ein Terminal-Pane mit Zeit, Ziel und Checkpoints. Erzwingt nichts und erreicht den Agenten nicht. | `render` |
| [arch_memory.py](../../../daedalus/arch_memory.py) | Fassade auf den kanonischen Architektur-Speicher unter [Interfaces CLI](interfaces-cli.md); haelt den historischen Importpfad fuer Hooks offen, ohne eine zweite Implementierung zu tragen. | `render_delta`, `is_stale` |
| [arch_hook.py](../../../daedalus/arch_hook.py) | Gegenstueck zu `shift_hook`: schiebt das Architektur-Delta in jeden Turn. Schweigt, wenn kein Snapshot gebaut wurde, und bricht nie den Turn ab. | kein oeffentliches Symbol, reines Skript |

### Kontext-Zertifikat und Fassaden

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [dctx.py](../../../daedalus/dctx.py) | Das zertifizierte Kontext-Artefakt: ein Slice plus ein offline pruefbarer Beweis darueber, inhaltsadressiert, commit-gebunden, secret-frei. Fuegt keine Kontextlogik hinzu, sondern ist eine duenne Huelle um den Slicer aus [Structcore](structcore.md). | `compile`, `verify` |
| [__init__.py](../../../daedalus/__init__.py) | Lazy Kompatibilitaetsfassade der Paketwurzel: Importe werden erst beim Attributzugriff aufgeloest, damit das Inspizieren eines Hierarchie-Pakets nicht Router oder Contract-Besitzer initialisiert. | `AgentTask`, `AgentReport`, `RunState`, `route_task`, `validate_report` |
| [schemas.py](../../../daedalus/schemas.py) | Fassade auf die kanonischen Kernel-, Runtime- und Orchestration-Records mit exakter Objektidentitaet; keine zweite Implementierung, kein veraenderlicher Singleton. | re-exportiert unter anderem `MissionContract`, `AttemptContract`, `EvidencePacket`, `PolicyDecision`, `RuntimeManifest`, `ProductSpec`, `DesignContract`, `TargetFourfoldSpec`, `GraphProposal`, `MaterializationPlan`, `ToolchainManifest`, `RoundTripReport`, `DeploymentPlan`, `GenesisAutonomyPolicy`, `parse_kernel_contract` |
| [orchestrate.py](../../../daedalus/orchestrate.py) | Neun Zeilen Kompatibilitaets-CLI auf die Orchestrierung in [Kairos](kairos.md). | `prepare_task` |

### `daedalus/resources/`

[resources/__init__.py](../../../daedalus/resources/__init__.py) ist der einzige
Aufloeser fuer die paketierten Kopien von `agents/`, `templates/`, `catalogue/`
und `schemas/` (plus `web_dist`), die ein installiertes Wheel braucht, weil die
Repository-Wurzelverzeichnisse dort nicht existieren; die Wurzeldateien bleiben
laut Docstring ein Kompatibilitaetsspiegel. Projektlokale `.agentenv`-Daten
liegen bewusst ausserhalb des Pakets. Nur lesend.

## Trust-Grenzen / Effekte

- **Effekt-Grenze.** Effektfaehige Einstiegspunkte dieser Schicht rufen
  `begin_effect` aus der Effekt-Grenze des [Spine](spine.md) als erste
  Anweisung ihres Einstiegs. Gemessen 2026-09-05 in
  [build_exec.py](../../../daedalus/build_exec.py),
  [dctx.py](../../../daedalus/dctx.py),
  [doctor.py](../../../daedalus/doctor.py),
  [file_bridge.py](../../../daedalus/file_bridge.py) (fuenf Aufrufstellen),
  [health.py](../../../daedalus/health.py),
  [progress.py](../../../daedalus/progress.py),
  [shift.py](../../../daedalus/shift.py) und
  [status.py](../../../daedalus/status.py).
  [offload.py](../../../daedalus/offload.py) geht den staerkeren Weg und
  startet den Effekt ueber die Autorisierung der erteilten Effect Lease.
- **Geld.** `install_process_guard` interponiert die Subprozess- und
  HTTP-Aufrufe des Prozesses und erzeugt damit den Engpass, den die
  Architektur sonst nicht hat. Eine explizite Reservierung am Aufrufort
  schaltet den Interponenten fuer ihre Dauer ab, damit nicht doppelt belastet
  wird. Ein unbekannter Preis ist nie ein freier Preis.
- **Schreiben.** Zwei getrennte Fragen, die nicht vermischt werden duerfen:
  `assert_write_allowed` ist eine Dateisystemfrage ueber den primaeren
  Checkout und kennt keine Policy; `path_write_blocked` ist die Policy-Frage,
  ob ein lokaler Schreiber hier ueberhaupt schreiben darf. Der Egress-Pfad
  ueber `classify_data` ist fail-closed, das Schreib-Confinement ausdruecklich
  nicht auf dieselbe Weise -- siehe den Modul-Docstring von
  [sensitivity.py](../../../daedalus/sensitivity.py).
- **Nur lesend.** `doctor`, `status`, `health`, `progress_sources`, `router`,
  `provider_router` und die Fassaden `schemas`, `limit_policy`, `orchestrate`,
  `arch_memory` fuehren keine externen Effekte aus. `metrics` haengt
  ausschliesslich an sein eigenes Journal an.
- **Kein Promotionspfad.** Nichts in dieser Schicht befoerdert einen
  Kandidaten. `ArtifactStore` speichert Bytes und stellt einen Locator aus;
  Ledger und versiegelte Promotion liegen in [Spine](spine.md),
  [Kernel](kernel.md) und [Kairos](kairos.md).

## Tests

Ausgewaehlt ueber eine Suche in `tests/` nach dem jeweiligen Importnamen,
gemessen 2026-09-05:

- Primitive: [test_journal_io.py](../../../tests/test_journal_io.py),
  [test_artifact_store.py](../../../tests/test_artifact_store.py),
  [test_storage_watermark.py](../../../tests/test_storage_watermark.py),
  [test_primary_tree_fence.py](../../../tests/test_primary_tree_fence.py),
  [test_journal_append_concurrency.py](../../../tests/test_journal_append_concurrency.py)
- Sensitivitaet und Egress:
  [test_sensitivity_default_policy_pins.py](../../../tests/test_sensitivity_default_policy_pins.py),
  [test_sensitivity_write_intent.py](../../../tests/test_sensitivity_write_intent.py),
  [test_egress_coverage.py](../../../tests/test_egress_coverage.py),
  [test_egress_lane_by_host.py](../../../tests/test_egress_lane_by_host.py),
  [test_host_predicate.py](../../../tests/test_host_predicate.py),
  [test_slice_egress_gate.py](../../../tests/test_slice_egress_gate.py),
  [test_write_guard_e2e.py](../../../tests/test_write_guard_e2e.py),
  [test_fence_anchoring.py](../../../tests/test_fence_anchoring.py)
- Budget und Limits: [test_budget.py](../../../tests/test_budget.py),
  [test_budget_is_installed.py](../../../tests/test_budget_is_installed.py),
  [test_spend_coverage.py](../../../tests/test_spend_coverage.py),
  [test_limit_policy.py](../../../tests/test_limit_policy.py),
  [test_canonical_execution_limit_policy.py](../../../tests/test_canonical_execution_limit_policy.py),
  [test_unbounded_security_floor.py](../../../tests/test_unbounded_security_floor.py)
- Build-Wellen: [test_build.py](../../../tests/test_build.py),
  [test_build_vocabulary.py](../../../tests/test_build_vocabulary.py),
  [test_wave_spend_reservation.py](../../../tests/test_wave_spend_reservation.py),
  [test_wave_spend_reservation_concurrency.py](../../../tests/test_wave_spend_reservation_concurrency.py),
  [test_parallel_dispatch.py](../../../tests/test_parallel_dispatch.py)
- Offload-Kaskade: [test_cascade.py](../../../tests/test_cascade.py),
  [test_fake_offload.py](../../../tests/test_fake_offload.py),
  [test_offload_automint.py](../../../tests/test_offload_automint.py),
  [test_offload_write_failclose.py](../../../tests/test_offload_write_failclose.py),
  [test_offload_lease_harness.py](../../../tests/test_offload_lease_harness.py),
  [test_offload_unleased_planner.py](../../../tests/test_offload_unleased_planner.py),
  [test_offload_slice_context.py](../../../tests/test_offload_slice_context.py)
- Bruecke und Desktop: [test_bridge_restart.py](../../../tests/test_bridge_restart.py),
  [test_bridge_enqueue_guard.py](../../../tests/test_bridge_enqueue_guard.py),
  [test_bridge_signals.py](../../../tests/test_bridge_signals.py),
  [test_desktop_runtime.py](../../../tests/test_desktop_runtime.py)
- Beobachtung: [test_health_surface.py](../../../tests/test_health_surface.py),
  [test_health_admission.py](../../../tests/test_health_admission.py),
  [test_shift.py](../../../tests/test_shift.py),
  [test_arch_memory.py](../../../tests/test_arch_memory.py),
  [test_dctx.py](../../../tests/test_dctx.py),
  [test_dctx_policy_egress.py](../../../tests/test_dctx_policy_egress.py)
- Struktur und Grenzen:
  [test_architecture_boundaries.py](../../../tests/test_architecture_boundaries.py),
  [test_effect_boundary.py](../../../tests/test_effect_boundary.py),
  [test_cli_effect_boundary.py](../../../tests/test_cli_effect_boundary.py),
  [test_registry_new_doors.py](../../../tests/test_registry_new_doors.py),
  [test_imports_graph.py](../../../tests/test_imports_graph.py)

Fuer `arch_hook`, `shift_hook`, `shift_ticker` und `orchestrate` fand die Suche
2026-09-05 keine Testdatei, die sie namentlich importiert.

## Verwandt

- [Kernel](kernel.md) und [Kernel-Contracts](kernel-contracts.md) -- die
  kanonischen Besitzer, auf die `schemas` und `limit_policy` zeigen.
- [Spine](spine.md) -- Effekt-Grenze, Ledger, Killswitch, Attempt.
- [Kairos](kairos.md) -- Scheduler, Worktrees und die versiegelte
  Promotionsnaht, die `build_exec` benutzt.
- [Orchestration Genesis](orchestration-genesis.md) -- der zweite grosse
  Konsument von `ArtifactStore` und den Kernel-Contracts.
- [Wiki-Modul](wiki.md) -- Wissensebene und der deterministische Verifier.
- [Kernel-Policy](kernel-policy.md) und
  [Runtimes Execution](runtimes-execution.md) -- die heutigen Besitzer von
  Pricing, Ledger und Prozessnetz.
- [Structcore](structcore.md) -- der Slicer hinter `dctx`.
- [Interfaces Bridge](interfaces-bridge.md), [Interfaces CLI](interfaces-cli.md),
  [Interfaces HTTP](interfaces-http.md) -- die Oberflaechen, die `core` und
  `file_bridge` bedienen.
- [Providers](providers.md) und [Runtimes Provider](runtimes-provider.md) --
  wohin `provider_router` zeigt.
- [Snapshot-Experiment s05](../experiments/forest-v2-s05-snapshot.md) -- die
  Gate-2-Vorarbeit zur revisionsatomaren Identitaet, die spaeter auf
  `ArtifactStore` trifft.
- [Beobachtungsebene](observation-layer.md) und
  [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md) -- die
  Entwurfsentscheidungen hinter `progress` und `health`.
- [Wiki-Index](../index.md).

## Ungeklaert

- **Ungeklaert:** `daedalus/resources` ist ein Unterpaket -- Quelle von
  `iter_builtin_files`, das `router` benutzt -- und in keinem Seitenplan dieses
  Wikis enthalten; es hat damit noch keine eigene Seite.
- **Ungeklaert:** `core.py` und `file_bridge.py` tragen keinen Modul-Docstring.
  Die Beschreibungen oben sind aus Importen, Konstanten und Funktionsnamen
  abgeleitet, nicht aus einer erklaerten Absicht.
- **Ungeklaert:** ob `install_tunnel_egress_policy` -- im Code als
  Kompatibilitaets-Nulloperation ohne SSH-Tunnel-Transport beschrieben -- noch
  Aufrufer ausserhalb der Tests hat.
- **Ungeklaert:** die genaue Arbeitsteilung zwischen `get_governance` und den
  Gate-Berichten unter [Gates](gates.md). Beide beantworten die Frage, ob
  gerade etwas befoerdert werden darf, aus verschiedenen Quellen.

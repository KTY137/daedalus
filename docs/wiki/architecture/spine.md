---
title: Spine
type: module
status: living
updated: 2026-09-05
covers: daedalus/spine
---
# Spine

`daedalus/spine` ist die aelteste Schicht des Daedalus-Kernels und heute zwei
Dinge gleichzeitig: (a) die Effekt- und Prozessgrenze der Selbstverbesserungs-
Schleife -- Effect-Registry, Containment, Kill-Switch, Prozessbaum-Abbruch,
Attempt-Tueren -- und (b) eine Kompatibilitaets-Fassade fuer den kanonischen
Event-Spine, dessen Implementierung inzwischen unter
[Kernel-Events](kernel-events.md) liegt. Im Kernel/Ikarus/Ariadne-Bild
(Masterplan Abschnitt 3 und 4) gehoert alles hier zum Trust- und
Runtime-Kernel: Missionen, Attempts und Evidence werden woanders komponiert,
aber jeder Effekt laeuft an dieser Grenze vorbei. Das Paket ist ausdruecklich
**keine** Sicherheitsgarantie: `EffectStartReceipt.to_dict` schreibt
`security_boundary_claimed: False` in jede Quittung, und `containment.py`
weigert sich, "Sandbox" zu heissen.

Gemessen 2026-09-05: 16 `.py`-Dateien, 17875 Zeilen; drei davon
(`ledger.py`, `envelope.py`, `durability.py`) sind reine Modul-Aliase mit
zusammen 35 Zeilen.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/spine/__init__.py) | Lazy Kompatibilitaets-Fassade. `__getattr__` loest die historischen Namen aus `daedalus.kernel.events` bzw. `writer_inventory` auf; `__all__` haelt die historische Reihenfolge als Vertrag fest. | `__all__`, `__getattr__` |
| [`ledger.py`](../../../daedalus/spine/ledger.py) | Modul-Alias: ersetzt sich selbst in `sys.modules` durch `daedalus.kernel.events.ledger`, damit alte Monkeypatches, private Namen und Pickle-Globals identisch bleiben. | (Alias, kein eigener Code) |
| [`envelope.py`](../../../daedalus/spine/envelope.py) | Modul-Alias auf `daedalus.kernel.events.envelope`. Sehr viele Aufrufer importieren `canonical_sha` und `canonical_json` weiterhin ueber diesen Pfad. | (Alias) |
| [`durability.py`](../../../daedalus/spine/durability.py) | Modul-Alias auf `daedalus.kernel.events.durability`. | (Alias) |
| [`effect_boundary.py`](../../../daedalus/spine/effect_boundary.py) | Die Registry aller effektbehafteten Runtime-Eintrittspunkte plus der deterministische Konformanz-Scan. Groesste Datei des Pakets (4093 Zeilen). | `Surface`, `Effect`, `Wiring`, `EntrypointSpec`, `GuardAnchor`, `GuardDecision`, `EffectStartReceipt`, `begin_effect`, `registry_sha256`, `ENTRYPOINTS`, `REGISTRY_BY_ID`, `GUARD_CONTRACT_IMPLEMENTED`, `POLICY_CONTRACTS`, `UnregisteredEntrypoint`, `EffectStartRefused`, `EffectBoundaryError`, `discover_entrypoints`, `check_conformance`, `ConformanceReport`, `ConformanceFinding`, `DiscoveredEntrypoint`, `human_matrix` |
| [`picker.py`](../../../daedalus/spine/picker.py) | Die messungssortierte Arbeitsschlange und der `daedalus improve`-Einstieg. Erzeugt Kandidaten aus Work-Queue, Map-State, Inventory, Docrefs, Eval-Baseline und Hotspots, rankt sie und rendert das Review-Paket. | `Candidate`, `PickedQueue`, `NoEvidence`, `WorkQueueInvalid`, `SOURCE_BANDS`, `BAND_SPAN`, `SOURCE_ORDER`, `OutcomePolicy`, `OUTCOME_POLICY`, `build_queue`, `rank`, `render_queue`, `review_packet`, `load_work_queue`, `work_queue_candidates`, `map_candidates`, `docref_candidates`, `inventory_candidates`, `eval_baseline_candidates`, `eval_gate_candidates`, `hotspot_candidates`, `attempt_history`, `apply_attempt_memory`, `instruction_fingerprint`, `resolve_spine_db_path`, `inventory_freshness`, `map_state_trustworthy`, `load_inventory`, `load_map_state` |
| [`receipts.py`](../../../daedalus/spine/receipts.py) | Kanonisiert einen fertigen Attempt in die Gate-0-Vertraege (`AttemptContract`, `EvidencePacket`, `AttemptReceipt`, `PolicyDecision`). Zustandslos: oeffnet keine Datenbank, schreibt keine Datei, startet keinen Effekt. | `AttemptContractSet`, `canonicalise_attempt`, `read_contract_set`, `attempt_policy_decision`, `attempt_runtime_manifest`, `adapter_identity`, `evaluator_assurance`, `evaluator_assurance_detail`, `containment_escapes`, `import_surface_plan`, `resolve_import_plan`, `ImportPlan`, `ImportSite`, `ImportSurface`, `CriterionImportSurface`, `mission_contract_for_candidate`, `mission_contract_for_build_session`, `normalise_declared_paths`, `normalise_shed_telemetry`, `pytest_basedir`, `sys_path_roots`, `config_import_roots`, `criterion_probe_paths`, `tree_probes` |
| [`containment.py`](../../../daedalus/spine/containment.py) | Windows-Containment fuer Kandidaten-Code: MIC-Write-Containment (Low-Integrity-Label) plus Job Object. Nennt sich bewusst nicht Sandbox -- es beansprucht weder Netz- noch Leseisolation. | `spawn_contained`, `ContainedProcess`, `ContainmentUnavailable`, `ContainmentAttestation`, `OciContainmentFacts`, `refusal_attestation`, `JobLimits`, `job_accounting`, `LowIntegrityLog`, `open_low_append_log`, `label_low_integrity`, `label_low_integrity_file`, `integrity_label`, `platform_supported`, `required_mechanism_label`, `unmeasured_vectors` |
| [`linux_containment.py`](../../../daedalus/spine/linux_containment.py) | Linux-Gegenstueck: rootless Podman/OCI mit operator-gepinntem Image-Digest, read-only Rootfs, einem `/workspace`-Bind, leerem Netz-Namespace, gedroppten Capabilities und cgroup-v2-Limits. Kein Host-Prozess-Fallback. | `spawn_oci_contained`, `LinuxContainedProcess` |
| [`killswitch.py`](../../../daedalus/spine/killswitch.py) | Permit-Datei-Kill-Switch: die Schleife laeuft nur, solange eine Datei ausserhalb des Repos das erwartete Token in der ersten nicht-leeren Zeile traegt. Abwesenheit bedeutet STOP, damit jede unbeantwortbare Frage fail-closed endet. | `KillSwitch`, `SwitchState`, `LoopHalted`, `ControlRootCheck`, `control_root`, `os_control_root`, `legacy_control_root`, `default_switch_path`, `verify_control_root`, `profile_root_disagreement`, `repo_control_digest` |
| [`cancel.py`](../../../daedalus/spine/cancel.py) | Zuverlaessiger Abbruch ganzer Prozessbaeume. Zwei verifizierte Stufen: erst das Konsolen-Ctrl-Event bzw. `killpg` mit SIGINT, dann Job-Object-Terminierung bzw. `killpg` mit SIGKILL. Reines `ctypes`, kein pywin32. | `ManagedProcess`, `CancelResult`, `CancellationUnavailable`, `WindowsJobBackend`, `PosixSessionBackend`, `select_backend`, `console_ctrl_available`, `live_managed_processes`, `cancel_all_managed` |
| [`attempt.py`](../../../daedalus/spine/attempt.py) | Registrierte Attempt-Effekt-Tueren und fail-closed-Fassade. Die Lebenszyklus-Implementierung gehoert `daedalus.kernel.attempt_execution`; ohne komponierte Ports schlaegt der Aufruf mit `AttemptPortMissing` fehl, bevor Workspace oder Evaluator angefasst werden. | `TaskAttempt`, `TaskSpec`, `AttemptResult`, `GateResult`, `PatchArtifact`, `RunnerContext`, `PrimaryCheckoutWrite`, `GitCommandError`, `run_attempt`, `command_gate`, `pytest_gate`, `pytest_gate_argv`, `offload_runner`, `ATTEMPT_STATES`, `INTENT_KIND`, `READ_ONLY_REPO_VERBS` |
| [`bootstrap.py`](../../../daedalus/spine/bootstrap.py) | "Shadow Run": Quellen auffrischen, Gate-Diskriminierung messen, dann einen Attempt fahren -- und nichts promoten. Der Name ist die Aussage: ein gruenes Gate ist hier kein Qualitaetsbeleg. | `shadow_run`, `ShadowResult`, `refresh_sources`, `SourceRefresh`, `gate_discrimination`, `GateDiscrimination`, `main` |
| [`docrefs.py`](../../../daedalus/spine/docrefs.py) | Findet Prosa, die dem Code widerspricht: eine Doku-Referenz auf ein Symbol, dessen Modul existiert, das Symbol aber nicht. Der Falsch-Positiv-Filter ist der eigentliche Entwurf. | `Reference`, `DocRefReport`, `FixVerdict`, `scan`, `extract_references`, `resolve_reference`, `reference_key`, `iter_doc_files`, `check_denominator`, `verify_fix`, `verify_fix_counts`, `verify_fixes` |
| [`docref_gate.py`](../../../daedalus/spine/docref_gate.py) | Das Gate, an dem ein Docref-Attempt tatsaechlich gemessen wird: erst der Nenner (loesen mindestens so viele Referenzen auf wie vorher?), dann Existenz und Inhalt des Zieldokuments, dann jeder einzelne Befund. | `run_gate`, `build_parser`, `main` |
| [`writer_inventory.py`](../../../daedalus/spine/writer_inventory.py) | Deterministisches, syntaxbasiertes Inventar aller `SpineLedger`-Konstruktionsstellen im Produktionsbaum, gebunden an eine Revision und an die exakten Bytes jeder gescannten Datei. | `WriterInventory`, `WriterCallsite`, `WriterInventoryError`, `scan_event_store_writers` |

## Trust-Grenzen / Effekte

**Die Registry.** `ENTRYPOINTS` in `effect_boundary.py` ist die eine Liste
extern erreichbarer Effekt-Starts. Jede Zeile ist ein `EntrypointSpec` mit
`surface` (`Surface` kennt `CLI`, `WEB_API`, `FILE_BRIDGE`, `MCP`, `PYTHON`,
`CLAUDE`, `CODEX`, `OLLAMA`, `WORKTREE`), den deklarierten `effects` (`Effect`
kennt `FILESYSTEM_WRITE`, `PROCESS_SPAWN`, `PROCESS_CONTROL`,
`NETWORK_EGRESS`, `LISTEN_SOCKET`, `REPOSITORY_MUTATION`, `SPEND`, `SECRETS`,
`COMPUTER_USE`), den geforderten `guard_contracts` und einem `Wiring`-Status
(`CENTRAL`, `LOCAL_GUARDS`, `INVENTORY_ONLY`, `UNGUARDED`, `ABSENT`). Gemessen
2026-09-05: 127 Vorkommen von `EntrypointSpec(` in der Datei, verteilt auf die
Basisliste plus die angehaengten Bloecke fuer Provider-, Ikarus-Chat-, Phase-4-,
Late- und Portable-Tool-Zeilen.

**Die Tuer.** `begin_effect(entrypoint_id, requested_effects, decisions)` ist
rein: sie fuehrt den Effekt nicht aus, sondern validiert ihn und gibt eine
inhaltsadressierte `EffectStartReceipt` zurueck. Sie schlaegt fehl bei
unbekanntem Eintrittspunkt (`UnregisteredEntrypoint`), bei einer Zeile die
nicht `Wiring.CENTRAL` ist, bei unbekannten oder nicht implementierten
Guard-Contracts, bei nicht deklarierten Effekten, bei doppelten oder fehlenden
`GuardDecision`-Eintraegen, bei leerer Evidenz und bei jeder Ablehnung -- alles
als `EffectStartRefused`. Die Guard-Contract-Namen in
`GUARD_CONTRACT_IMPLEMENTED` (`computer.tool_policy`, `computer.configuration`,
`budget.process_guard`, `containment.attempt`, `containment.worktree`,
`file_bridge.crash_journal`, `provider.egress_policy`, `provider.write_policy`,
`promotion.owner_approval`, `runtime.adapter_profile`, `spine.intent_ledger`,
`web.authenticated_bind`) zeigen auf Vertraege in anderen Modulen;
`effect_boundary.py` implementiert keine zweite Allow-List. Die Policy-Module
dahinter beschreibt [Kernel-Policy](kernel-policy.md).

**Schreibende Pfade.** Innerhalb des Pakets schreiben nur wenige Funktionen:
`KillSwitch.arm`, `KillSwitch.stop` und `KillSwitch.clear` (atomarer Rename der
Permit-Datei ausserhalb des Repos, damit ein Kandidatenprozess sie nicht aendern
kann), `LowIntegrityLog` (Append in ein Low-Integrity-Log), sowie
`shadow_run`, das ueber `TaskAttempt` einen Worktree anlegt und ein
`PatchArtifact` ablegt. `receipts.py`, `docrefs.py`, `writer_inventory.py`,
`effect_boundary.py` und der Kandidatenbau in `picker.py` sind lesend bzw. rein
rechnend.

**Containment ist plattformabhaengig und macht unterschiedliche Zusagen.**
`spawn_contained` (Windows) beansprucht Write-Containment plus Prozess-Limits
per Job Object, ausdruecklich *keine* Netz- oder Leseisolation;
`unmeasured_vectors` benennt die nicht gemessenen Vektoren.
`spawn_oci_contained` (Linux) beansprucht zusaetzlich private Netz-, PID-,
IPC-, UTS- und cgroup-Namespaces, read-only Image-Root und gedroppte
Capabilities, aber ausdruecklich keinen Schutz gegen Kernel- oder
Runtime-Escape. Beide Pfade fallen nie still auf einen normalen Host-Spawn
zurueck; `refusal_attestation` macht die Verweigerung selbst zu einem
inspizierbaren Datensatz, und `ContainmentAttestation` bzw. `OciContainmentFacts`
tragen die verifizierte Konfiguration.

**Keine Promotion.** `main` in `picker.py` kann hoechstens einen Attempt fahren
(`--once`); ein Attempt erzeugt inerte Bytes. Es gibt kein `--apply`.
`bootstrap.py` nennt sich Shadow Run genau deshalb: das gemessene
Diskriminierungsvermoegen des Gates gegen drei bekannt-schlechte Aenderungen
eines Tages war 0/3, also blockiert das Gate Promotion, nicht
Kandidatenerzeugung. Das deckt sich mit Invariante 5 des Masterplans und mit
[Graph delta as fitness](../graph-delta-as-fitness.md).

**Prioritaet ist ein Prior, kein Messwert.** `SOURCE_BANDS` vergibt feste
Baender (Work-Queue 900, Map-Island 800, Map-Shim 700, Docref 500,
Inventory-Island 400, Inventory-Stale 300, Eval-Miss 200, Hotspot 100);
`BAND_SPAN` ist 50 und damit strikt kleiner als der Bandabstand, sodass eine
Messung die genannte Prioritaet nie still umsortieren kann. `OUTCOME_POLICY`
deckelt den Offset eines bereits versuchten Kandidaten anhand des
Ledger-Ausgangs. `_candidate` weist jeden Kandidaten ohne `reason` oder
`evidence` mit `NoEvidence` zurueck.

## Tests

Gemessen 2026-09-05 per `grep -rl` unter `tests/`; Auswahl der direkt auf
Spine-Module zielenden Dateien:

- Effect-Boundary/Registry: [`test_effect_boundary.py`](../../../tests/test_effect_boundary.py),
  [`test_cli_effect_boundary.py`](../../../tests/test_cli_effect_boundary.py),
  [`test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py),
  [`test_registry_retired_rows.py`](../../../tests/test_registry_retired_rows.py),
  [`test_registry_facade_order.py`](../../../tests/test_registry_facade_order.py),
  [`test_write_surface_coverage.py`](../../../tests/test_write_surface_coverage.py)
- Picker/Queue: [`test_spine_picker.py`](../../../tests/test_spine_picker.py),
  [`test_picker_work_queue.py`](../../../tests/test_picker_work_queue.py),
  [`test_picker_outcome.py`](../../../tests/test_picker_outcome.py),
  [`test_picker_spectral_enrichment.py`](../../../tests/test_picker_spectral_enrichment.py),
  [`test_spine_map_source.py`](../../../tests/test_spine_map_source.py),
  [`test_spine_return_arc.py`](../../../tests/test_spine_return_arc.py)
- Attempt/Receipts: [`test_spine_attempt.py`](../../../tests/test_spine_attempt.py),
  [`test_attempt_boundary.py`](../../../tests/test_attempt_boundary.py),
  [`test_attempt_contracts_live_path.py`](../../../tests/test_attempt_contracts_live_path.py),
  [`test_attempt_undeclared_scope.py`](../../../tests/test_attempt_undeclared_scope.py),
  [`test_assurance_hardening.py`](../../../tests/test_assurance_hardening.py),
  [`test_criterion_imports.py`](../../../tests/test_criterion_imports.py),
  [`test_criterion_imports_declaration.py`](../../../tests/test_criterion_imports_declaration.py),
  [`test_shed_telemetry.py`](../../../tests/test_shed_telemetry.py)
- Containment/Cancel: [`test_containment.py`](../../../tests/test_containment.py),
  [`test_containment_scope.py`](../../../tests/test_containment_scope.py),
  [`test_spine_attempt_containment.py`](../../../tests/test_spine_attempt_containment.py),
  [`test_linux_oci_containment.py`](../../../tests/test_linux_oci_containment.py),
  [`test_gate_containment.py`](../../../tests/test_gate_containment.py),
  [`test_gate_containment_job_caps.py`](../../../tests/test_gate_containment_job_caps.py),
  [`test_spine_cancel.py`](../../../tests/test_spine_cancel.py)
- Kill-Switch: [`test_killswitch.py`](../../../tests/test_killswitch.py),
  [`test_killswitch_control_root.py`](../../../tests/test_killswitch_control_root.py),
  [`test_killswitch_profile_root.py`](../../../tests/test_killswitch_profile_root.py)
- Shadow Run und Docrefs: [`test_shadow_run.py`](../../../tests/test_shadow_run.py),
  [`test_bootstrap_receipt.py`](../../../tests/test_bootstrap_receipt.py),
  [`test_gate_discrimination.py`](../../../tests/test_gate_discrimination.py),
  [`test_gate_judges_the_candidate.py`](../../../tests/test_gate_judges_the_candidate.py),
  [`test_docrefs_false_positives.py`](../../../tests/test_docrefs_false_positives.py),
  [`test_prose_gate.py`](../../../tests/test_prose_gate.py)
- Writer-Inventory: [`test_spine_writer_inventory.py`](../../../tests/test_spine_writer_inventory.py),
  [`test_spine_writer_inventory_schema.py`](../../../tests/test_spine_writer_inventory_schema.py),
  [`test_spine_writer_inventory_cli.py`](../../../tests/test_spine_writer_inventory_cli.py),
  [`test_spine_writer_inventory_review.py`](../../../tests/test_spine_writer_inventory_review.py)
- Fassaden- und Architekturgrenzen: [`test_spine_outer_ports.py`](../../../tests/contracts/test_spine_outer_ports.py),
  [`test_import_scc_hierarchy.py`](../../../tests/contracts/test_import_scc_hierarchy.py),
  [`test_architecture_boundaries.py`](../../../tests/test_architecture_boundaries.py),
  [`test_gate0_faults_atalanta.py`](../../../tests/test_gate0_faults_atalanta.py)

## Verwandt

- [Kernel-Events](kernel-events.md) -- der Besitzer von `SpineLedger`,
  `canonical_sha` und der Gate-0-Durability, auf den die Aliase hier zeigen.
- [Kernel](kernel.md) und [Kernel-Contracts](kernel-contracts.md) -- wo
  `AttemptContract`, `EvidencePacket` und `MissionContract` definiert sind, die
  `receipts.py` befuellt.
- [Kernel-Policy](kernel-policy.md) -- die Guard-Contracts hinter
  `begin_effect`.
- [Gates](gates.md) und [Gates-Repository](gates-repository.md) -- wo
  Schreibrechte und Promotion tatsaechlich entschieden werden.
- [Twin](twin.md) -- viele Twin-Module importieren `canonical_sha` ueber die
  Alias-Fassade `daedalus.spine.envelope`.
- [Orchestration-Execution](orchestration-execution.md) -- komponiert die
  Attempt-Ports, die `attempt.py` fail-closed offen laesst.
- [Runtimes-Execution](runtimes-execution.md) -- der Budget-Prozessguard hinter
  dem Contract `budget.process_guard`.
- [Agents hold no state](../decisions/agents-hold-no-state.md),
  [Tool vetting](../tool-vetting.md), [Wiki-Index](../index.md).

## Ungeklaert

- **Ungeklaert:** die genaue Aufteilung der 127 `EntrypointSpec(`-Vorkommen auf
  Basisliste und die fuenf angehaengten Bloecke; gezaehlt wurde nur die
  Gesamtzahl im Dateitext.
- **Ungeklaert:** wie viele Registry-Zeilen heute noch `Wiring.UNGUARDED` oder
  `Wiring.INVENTORY_ONLY` sind. Das ist genau die Zahl, die Revision 8 des
  Masterplans als weiterhin gemeldete "scoped rows" offen laesst; sie kommt aus
  `check_conformance` zur Laufzeit und wurde hier nicht gemessen.
- **Ungeklaert:** ob `main` in `bootstrap.py` noch als CLI-Verb registriert ist
  oder nur noch programmatisch aufgerufen wird.
- **Hinweis, nichts geloescht:** `hotspot_candidates` und
  `eval_gate_candidates` haengen an Quellen, die per Default aus sind
  (`--hotspots`, `--eval`). Ob diese Pfade heute noch benutzt werden, ist aus
  dem Code allein nicht ablesbar.

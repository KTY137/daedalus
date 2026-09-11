---
title: Tooling - scripts/
type: tooling
status: living
updated: 2026-09-05
covers: scripts
---
# Tooling - scripts/

`scripts/` ist die **Dev-Harness** des Repositories: Berichte, Sonden und
adversariale Mutationskampagnen, die Behauptungen ueber den Kernel pruefen,
statt Produktverhalten zu erbringen. Im Kernel/Ikarus/Ariadne-Bild ist das
Verzeichnis kein Produkt und keine Oberflaeche -- es liefert Evidenz im Sinne
von Masterplan Abschnitt 0 (Artefaktklasse "tests, receipts, and experiments")
und Abschnitt 10 Schritt 6 ("Adversarial verification ... mutation tests
proportional to the packet's risk"). Nichts hier ist ein Produktionspfad.

Der Unterschied zu den Nachbarverzeichnissen ist scharf:
[`daedalus/interfaces/cli`](../architecture/interfaces-cli.md) sind Befehle,
die ein Mensch im Alltag tippt und die in der Effekt-Registry stehen;
[`tools/`](tools.md) ist wiederverwendbare Werkzeug-Bibliothek; `scripts/` sind
einmalige oder gelegentliche Messlaeufe, die ein Work Packet begleiten.

Gemessen 2026-09-05: 89 `.py`-Dateien, 11594 Zeilen. Davon sind 73
Mutationskampagnen (`run_*_mutations.py`), 7 Inventar-/Klassifikationsberichte
(`report_*.py`), 4 Gate-Berichte und -Freigaben, 3 Fourfold-Sonden, 1
gemeinsame Mutations-Sandbox und 1 eingefrorener Launcher.

## Trust-Grenzen / Effekte

Das ist der wichtigste Abschnitt dieser Seite, weil `scripts/` bewusst
**ausserhalb** der Produktions-Effektgrenze liegt.

* **`scripts` ist kein `SCAN_PACKAGES`, sondern ein `HARNESS_PACKAGES`.**
  In [`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py)
  scannt der Konformanz-Durchlauf `daedalus`, `tools` und `runs` als
  Produktionsoberflaeche; `scripts` und `tests` werden **gelesen und
  klassifiziert**, aber nicht als Produktionsoberflaeche gemeldet. Der
  Kommentar dort begruendet das und nennt die Messung: 74 Mutations-Runner und
  17 Test-Fixtures sind effektbehaftete Eintrittspunkte. Sie ungescannt zu
  lassen waere ein undokumentierter blinder Fleck; sie zu Blockern zu machen
  wuerde das Gate abschalten statt schliessen. Also wird jeder entdeckte,
  unregistrierte Eintrittspunkt hier ein ausdruecklicher
  `entrypoint.harness`-Review-Befund: benannt, gezaehlt und **per Deklaration**
  ausserhalb der Gate-0-Verkabelung, nicht per Schweigen.
* **Konsequenz:** kein Skript in diesem Verzeichnis hat eine
  `EntrypointSpec`-Zeile und keines ruft `begin_effect`. Sie sind trotzdem
  effektbehaftet.
* **In-Place-Mutation schreibt in den Arbeitsbaum.** Die Mehrzahl der Runner
  liest die Zielquelle, schreibt einen Mutanten an denselben Pfad, laesst
  pytest laufen und stellt die Originalbytes in einem `finally` wieder her --
  danach wird geprueft, dass die Datei wieder identisch ist, sonst gibt es
  einen eigenen Exit-Code. Ein Abbruch (`SIGKILL`, Stromausfall) kann diesen
  Zustand trotzdem hinterlassen. Diese Runner nicht auf einem dreckigen
  Arbeitsbaum starten.
* **Der Sandbox-Pfad ist der sichere.**
  [`fault_mutation_sandbox.py`](../../../scripts/fault_mutation_sandbox.py)
  kopiert `daedalus`, `tests` und `configs` in ein Temporaerverzeichnis, setzt
  `cwd` und `PYTHONPATH` **ersetzend** auf die Sandbox und kopiert
  `__pycache__` nie mit. Der Arbeitsbaum bleibt unberuehrt.
* **Fail-closed Selbstprobe.** Bevor eine Sandbox-Kampagne Zahlen meldet,
  verlangt sie zweierlei: der saubere Quelltext muss **in der Sandbox**
  bestehen, und ein Kanarienmutant (derselbe Quelltext plus ein
  modulweites `raise` mit `CANARY_MARKER`) muss dort **sterben** -- mit
  sichtbarem Marker. Wuerde stattdessen der saubere Checkout importiert,
  ueberlebt der Kanarienvogel und die Kampagne bricht ab, statt bedeutungslose
  "Mutanten getoetet"-Zahlen zu drucken. Ein Tod ohne Marker bricht ebenfalls
  ab, weil er nicht dem Sandbox-Import zurechenbar waere.
* **Prozess-Spawn ueberall.** Jeder Runner startet `python -m pytest` als
  Subprozess; die Berichte starten `git`. Netzzugriff gibt es in keinem der
  gelesenen Skripte.
* **`declare_write_surfaces.py` ist der einzige Schreiber mit Produktbezug:**
  es erzeugt die Deklaration, die `daedalus/gates/report_v3.py` als
  `repository_write_classification_input` liest. Es *behauptet* dabei
  ausdruecklich nichts, was der Baum nicht belegen kann: die Oberflaeche kommt
  aus demselben Scanner, den der Reporter fuehrt, die Tuer aus der kanonischen
  Effekt-Registry (nur `CENTRAL` mit `begin_effect`-Anchor), und die Dominanz
  wird ueber AST-Vorfahrenschaft entschieden -- eine Oberflaeche wird nur
  deklariert, wenn ihr exakter `(line, column)`-Knoten Nachfahre einer Anweisung
  ist, die nachweislich **nach** dem `begin_effect`-Aufruf des Anchors laeuft.
  Dateizugehoerigkeit genuegt nicht.
* **Keine Promotion.** Kein Skript hier merged, promotet oder verbraucht eine
  `OwnerApproval`. `gate0_release.py` stellt eine Freigabequittung aus bzw.
  verifiziert sie; die Entscheidung faellt vollstaendig in
  `daedalus.gates.release`, und das Verifier-Secret wird ausschliesslich aus
  einer Umgebungsvariablen gelesen und nie nach stdout, stderr oder in eine
  Datei geschrieben.

## Launcher

| Datei | Zweck |
| --- | --- |
| [`daedalus_desktop_sidecar.py`](../../../scripts/daedalus_desktop_sidecar.py) | Eingefrorener Launcher fuer den kanonischen Desktop-Sidecar. Alle Bootstrap-Effekte liegen in `daedalus.interfaces.desktop.sidecar`, damit die Produktions-Registry sie inspizieren und zulassen kann; diese Datei liefert nur den PyInstaller-Tail und `multiprocessing.freeze_support()` fuer eingefrorene Windows-Kindprozesse. Symbole: `main`, `prepare_runtime`, `bundled_root`, `DESKTOP_PROJECT_SCHEMA`, `DESKTOP_PROJECT_COMMENT`. |

## Gate-Berichte und Freigabe

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`gate0_baseline.py`](../../../scripts/gate0_baseline.py) | CLI ueber die Gate-0-Baseline: `create`, `compare`, `verify`. Ruft `create_gate0_baseline`, `assess_gate0_monotonicity` und `verify_gate0_monotonicity_receipt` aus `daedalus.gates`. Hat als einziges der vier Skripte **keinen** Modul-Docstring. | `main` |
| [`gate0_release.py`](../../../scripts/gate0_release.py) | Owner-CLI ueber den versiegelten Gate-0-Freigabevertrag. `issue` verifiziert die aufbewahrte Evidenz erneut und schreibt nur bei Erfolg **eine** signierte Quittung nach `--output`; `verify` authentifiziert eine aufbewahrte Quittung read-only. Refusals beenden mit 1 und fassen `--output` nie an; Erfolg ist still. | `main` |
| [`report_gate0_v3.py`](../../../scripts/report_gate0_v3.py) | Erzeugt einen additiven GateReport-v3 ueber `build_gate0_report_v3`, **ohne** eine Sicherheitsgrenze zu behaupten. | `main`, `_ERROR_SCHEMA` |
| [`declare_write_surfaces.py`](../../../scripts/declare_write_surfaces.py) | Leitet die Repository-Write-Klassifikationsdeklaration aus Messung ab (siehe Trust-Grenzen oben). Mit 1789 Zeilen das groesste Skript des Verzeichnisses. | `DeclarationError`, `DoorAnchor`, `ModuleDominance`, `NameIndex`, `RetainedWriteEvidence`, `resolve_central_doors`, `source_anchor_evidence`, `collector_secret`, `load_retained_write_evidence` |

## Inventar- und Klassifikationsberichte

Alle sieben sind duenne CLIs ueber einen kanonischen Scanner und geben
kanonisches JSON aus; keiner faellt ein Urteil.

| Datei | Scanner / Quelle |
| --- | --- |
| [`report_repository_write_inventory.py`](../../../scripts/report_repository_write_inventory.py) | `scan_repository_write_surfaces` aus [`daedalus/gates/repository/write_inventory.py`](../../../daedalus/gates/repository/write_inventory.py) -- revisionsgebundene Filesystem-, SQLite-, Prozess- und Write-Mode-Callsites, die noch Ziel-/Guard-Klassifikation brauchen. |
| [`report_repository_write_inventory_v2.py`](../../../scripts/report_repository_write_inventory_v2.py) | dasselbe in Generation 2, [`daedalus/gates/repository/write_inventory_v2.py`](../../../daedalus/gates/repository/write_inventory_v2.py). |
| [`report_repository_write_stdlib_delta.py`](../../../scripts/report_repository_write_stdlib_delta.py) | `scan_repository_write_stdlib_delta` -- additive Stdlib-/Prozess-Schreiboberflaechen, die das aktuelle Inventar verfehlt, [`daedalus/gates/repository/write_stdlib_delta.py`](../../../daedalus/gates/repository/write_stdlib_delta.py). |
| [`report_repository_write_classification.py`](../../../scripts/report_repository_write_classification.py) | `parse_inventory_v2` und `project_classification_input` aus [`daedalus/gates/repository/write_classification.py`](../../../daedalus/gates/repository/write_classification.py). |
| [`report_spine_writer_inventory.py`](../../../scripts/report_spine_writer_inventory.py) | `scan_event_store_writers` aus [`daedalus/spine/writer_inventory.py`](../../../daedalus/spine/writer_inventory.py) -- revisionsgebundene `SpineLedger`-Konstruktionsstellen. |
| [`report_provider_observation_persistence_inventory.py`](../../../scripts/report_provider_observation_persistence_inventory.py) | `scan_provider_observation_persistence` aus [`daedalus/gates/provider_observation_persistence_inventory.py`](../../../daedalus/gates/provider_observation_persistence_inventory.py). |
| [`report_provider_target_receipt_retention_inventory.py`](../../../scripts/report_provider_target_receipt_retention_inventory.py) | der Retention-Inventar-Scanner aus [`daedalus/gates/provider_target_receipt_retention_inventory.py`](../../../daedalus/gates/provider_target_receipt_retention_inventory.py). |

## Fourfold-Sonden

Drei begrenzte, deterministische Read-only-Sonden ueber eine gepinnte
Repository-Scheibe. Alle drei ziehen ihre Dateiliste aus `git ls-files -z`
(Funktion `tracked_paths` in jeder Datei) und geben einen Report aus; keine
publiziert einen Forest und keine befoerdert Syntax-Beobachtungen zu
verifizierten ebenenuebergreifenden Bindungen.

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`fourfold_repo_probe.py`](../../../scripts/fourfold_repo_probe.py) | Polyglotte Quell-Entdeckung: Repository-Form und Adapter-Bedarf, ohne Suffix-Erkennung zu semantischen Fakten aufzuwerten. Nutzt `detect_language`. | `tracked_paths`, `main` |
| [`fourfold_root_file_probe.py`](../../../scripts/fourfold_root_file_probe.py) | Begrenzte ROOT-Metadaten-Extraktion ueber `inspect_root_artifact` und `SourceArtifact`. | `tracked_paths`, `main` |
| [`fourfold_tree_sitter_probe.py`](../../../scripts/fourfold_tree_sitter_probe.py) | Begrenzte strukturelle Tree-sitter-Extraktion ueber `parse_artifact` fuer die Sprachen in `_PARSE_LANGUAGES` (`rust`, `java`, `cpp`, `c-cpp-header`, `root-macro`). Der Bericht ist ausdruecklich "staged parser evidence only". | `tracked_paths`, `main` |

## Mutations-Infrastruktur

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`fault_mutation_sandbox.py`](../../../scripts/fault_mutation_sandbox.py) | Der gemeinsame, sandboxende pytest-Runner der Fault-Matrix-Kampagnen samt Kanarienvogel-Selbstprobe (siehe Trust-Grenzen). | `run_campaign`, `CANARY_MARKER` |

Ausserhalb dieses Verzeichnisses gibt es zusaetzlich den **deklarativen**
Runner `tools/mutation_score.py` mit Spezifikationen unter
`configs/mutations/` (gemessen 2026-09-05: 10 JSON-Dateien). Zehn Skripte hier
sind nur noch Kompatibilitaets-Wrapper darauf -- sie setzen `--repo` und
`--spec` und reichen den Exit-Code durch.

## Mutationskampagnen (73)

Jede Kampagne folgt derselben Form: Baseline gruen, dann pro Mutation genau
eine eindeutige Textstelle ersetzen, pytest laufen lassen, und **verlangen**,
dass der Testlauf faellt. Ein ueberlebender Mutant ist ein Fehlschlag der
Kampagne, kein Ergebnis.

Die Spalte *Modus* unterscheidet: **In-Place** (Mutation im Arbeitsbaum,
Wiederherstellung im `finally`), **Sandbox (gemeinsam)** ueber
`fault_mutation_sandbox.run_campaign`, **Sandbox (eigen)** mit eigenem
`copytree`, **Wrapper** auf `tools/mutation_score.py`. Die Spalte
*Testdateien* zaehlt die im Skript fest verdrahteten Testpfade
(gemessen 2026-09-05).

### Fault-Matrix und Ganzmatrix-Bindung

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_fault_matrix_contract_mutations.py`](../../../scripts/run_fault_matrix_contract_mutations.py) | Sandbox (gemeinsam) | [`daedalus/gates/fault_matrix.py`](../../../daedalus/gates/fault_matrix.py) | 2 |
| [`run_fault_matrix_contract_exact_mutations.py`](../../../scripts/run_fault_matrix_contract_exact_mutations.py) | Sandbox (gemeinsam) | [`daedalus/gates/fault_matrix.py`](../../../daedalus/gates/fault_matrix.py) | 2 |
| [`run_fault_matrix_exact_durable_mutations.py`](../../../scripts/run_fault_matrix_exact_durable_mutations.py) | Sandbox (gemeinsam) | [`daedalus/gates/fault_matrix.py`](../../../daedalus/gates/fault_matrix.py) | 2 |
| [`run_fault_matrix_wire_type_mutations.py`](../../../scripts/run_fault_matrix_wire_type_mutations.py) | Sandbox (gemeinsam) | [`daedalus/gates/fault_matrix.py`](../../../daedalus/gates/fault_matrix.py) | 2 |
| [`run_whole_matrix_binding_mutations.py`](../../../scripts/run_whole_matrix_binding_mutations.py) | Sandbox (gemeinsam) | [`daedalus/gates/fault_matrix_binding.py`](../../../daedalus/gates/fault_matrix_binding.py), [`daedalus/runtimes/whole_fault_matrix.py`](../../../daedalus/runtimes/whole_fault_matrix.py) | 3 |

### Kernel: Attempt-Lebenszyklus, Quellbaum und Effekt-Replay

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_attempt_durability_admission_mutations.py`](../../../scripts/run_attempt_durability_admission_mutations.py) | In-Place | [`daedalus/kernel/attempt_ledger.py`](../../../daedalus/kernel/attempt_ledger.py) | 6 |
| [`run_attempt_effect_inventory_mutations.py`](../../../scripts/run_attempt_effect_inventory_mutations.py) | Wrapper | Spezifikation `configs/mutations/attempt-effect-inventory.json` | (in der Spezifikation) |
| [`run_attempt_event_time_window_mutations.py`](../../../scripts/run_attempt_event_time_window_mutations.py) | Wrapper | Spezifikation `configs/mutations/attempt-event-time-window.json` | (in der Spezifikation) |
| [`run_attempt_workspace_root_authority_mutations.py`](../../../scripts/run_attempt_workspace_root_authority_mutations.py) | In-Place | [`daedalus/kernel/attempt_workspace.py`](../../../daedalus/kernel/attempt_workspace.py) | 6 |
| [`run_isolated_attempt_mutations.py`](../../../scripts/run_isolated_attempt_mutations.py) | In-Place | [`daedalus/kernel/attempt_clock.py`](../../../daedalus/kernel/attempt_clock.py), [`daedalus/kernel/attempt_contracts.py`](../../../daedalus/kernel/attempt_contracts.py), [`daedalus/kernel/attempt_ledger.py`](../../../daedalus/kernel/attempt_ledger.py), [`daedalus/kernel/attempt_spine_reader.py`](../../../daedalus/kernel/attempt_spine_reader.py), [`daedalus/kernel/attempt_workspace.py`](../../../daedalus/kernel/attempt_workspace.py) | 10 |
| [`run_effect_replay_projection_mutations.py`](../../../scripts/run_effect_replay_projection_mutations.py) | In-Place | [`daedalus/kernel/effect_replay.py`](../../../daedalus/kernel/effect_replay.py) | 2 |
| [`run_runtime_effect_replay_projection_mutations.py`](../../../scripts/run_runtime_effect_replay_projection_mutations.py) | Wrapper | Spezifikation `configs/mutations/runtime-effect-replay-projection.json` | (in der Spezifikation) |
| [`run_source_tree_cas_mutations.py`](../../../scripts/run_source_tree_cas_mutations.py) | In-Place | [`daedalus/kernel/source_trees.py`](../../../daedalus/kernel/source_trees.py) | 4 |
| [`run_fourfold_evidence_binding_mutations.py`](../../../scripts/run_fourfold_evidence_binding_mutations.py) | In-Place | [`daedalus/kernel/fourfold_evidence.py`](../../../daedalus/kernel/fourfold_evidence.py) | 3 |

### Kernel: Autorisierung, Lease und Write-Evidence

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_non_runtime_authorization_mutations.py`](../../../scripts/run_non_runtime_authorization_mutations.py) | In-Place | [`daedalus/kernel/authorization.py`](../../../daedalus/kernel/authorization.py) | 1 |
| [`run_runtime_authorization_clock_mutations.py`](../../../scripts/run_runtime_authorization_clock_mutations.py) | In-Place | [`daedalus/kernel/runtime_effects.py`](../../../daedalus/kernel/runtime_effects.py), [`daedalus/runtimes/broker.py`](../../../daedalus/runtimes/broker.py) | 4 |
| [`run_runtime_terminal_binding_mutations.py`](../../../scripts/run_runtime_terminal_binding_mutations.py) | In-Place | [`daedalus/kernel/runtime_effects.py`](../../../daedalus/kernel/runtime_effects.py) | 1 |
| [`run_offload_lease_dominance_mutations.py`](../../../scripts/run_offload_lease_dominance_mutations.py) | In-Place | [`daedalus/offload.py`](../../../daedalus/offload.py) | 5 |
| [`run_write_evidence_production_mutations.py`](../../../scripts/run_write_evidence_production_mutations.py) | In-Place | [`daedalus/kernel/offload_lease.py`](../../../daedalus/kernel/offload_lease.py) | 6 |

### Promotion und Owner-Approval

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_approval_consumption_mutations.py`](../../../scripts/run_approval_consumption_mutations.py) | In-Place | [`daedalus/kernel/approvals.py`](../../../daedalus/kernel/approvals.py) | 2 |
| [`run_live_promotion_seam_mutations.py`](../../../scripts/run_live_promotion_seam_mutations.py) | In-Place | [`daedalus/kairos/gated_writes.py`](../../../daedalus/kairos/gated_writes.py), [`daedalus/kernel/promotion.py`](../../../daedalus/kernel/promotion.py) | 7 |
| [`run_persisted_promotion_authorization_mutations.py`](../../../scripts/run_persisted_promotion_authorization_mutations.py) | In-Place | [`daedalus/kernel/promotion.py`](../../../daedalus/kernel/promotion.py) | 3 |
| [`run_promotion_execution_mutations.py`](../../../scripts/run_promotion_execution_mutations.py) | In-Place | [`daedalus/kernel/promotion_execution.py`](../../../daedalus/kernel/promotion_execution.py) | 4 |
| [`run_promotion_execution_reader_mutations.py`](../../../scripts/run_promotion_execution_reader_mutations.py) | In-Place | [`daedalus/kernel/promotion_execution_reader.py`](../../../daedalus/kernel/promotion_execution_reader.py) | 6 |
| [`run_promotion_receipt_authority_mutations.py`](../../../scripts/run_promotion_receipt_authority_mutations.py) | In-Place | [`daedalus/kernel/__init__.py`](../../../daedalus/kernel/__init__.py), [`daedalus/kernel/contracts/security.py`](../../../daedalus/kernel/contracts/security.py) und [`daedalus/kernel/contracts/canonical.py`](../../../daedalus/kernel/contracts/canonical.py) | 1 |

### Provider: Invocation, Executable-Ziele und Beobachtung

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_provider_broker_exact_authority_mutations.py`](../../../scripts/run_provider_broker_exact_authority_mutations.py) | In-Place | [`daedalus/runtimes/broker.py`](../../../daedalus/runtimes/broker.py) | 4 |
| [`run_provider_executable_structure_mutations.py`](../../../scripts/run_provider_executable_structure_mutations.py) | Sandbox (eigen) | [`daedalus/runtimes/provider/executable_structure.py`](../../../daedalus/runtimes/provider/executable_structure.py) | 1 |
| [`run_provider_executable_target_mutations.py`](../../../scripts/run_provider_executable_target_mutations.py) | In-Place | [`daedalus/runtimes/provider/executable_targets.py`](../../../daedalus/runtimes/provider/executable_targets.py) | 2 |
| [`run_provider_invocation_authority_mutations.py`](../../../scripts/run_provider_invocation_authority_mutations.py) | In-Place | [`daedalus/runtimes/provider/invocation_authority.py`](../../../daedalus/runtimes/provider/invocation_authority.py) | 2 |
| [`run_provider_invocation_identity_mutations.py`](../../../scripts/run_provider_invocation_identity_mutations.py) | Wrapper | Spezifikation `configs/mutations/provider-invocation-identity.json` | (in der Spezifikation) |
| [`run_provider_invocation_registry_mutations.py`](../../../scripts/run_provider_invocation_registry_mutations.py) | In-Place | [`daedalus/runtimes/provider/invocation_registry.py`](../../../daedalus/runtimes/provider/invocation_registry.py) | 2 |
| [`run_provider_invocation_resolution_mutations.py`](../../../scripts/run_provider_invocation_resolution_mutations.py) | In-Place | [`daedalus/runtimes/provider/invocation_resolution.py`](../../../daedalus/runtimes/provider/invocation_resolution.py) | 2 |
| [`run_provider_observation_authority_mutations.py`](../../../scripts/run_provider_observation_authority_mutations.py) | Wrapper | Spezifikation `configs/mutations/provider-observation-authority.json` | (in der Spezifikation) |
| [`run_provider_observation_persistence_inventory_mutations.py`](../../../scripts/run_provider_observation_persistence_inventory_mutations.py) | Wrapper | Spezifikation `configs/mutations/provider-observation-persistence-inventory.json` | (in der Spezifikation) |
| [`run_provider_observation_store_mutations.py`](../../../scripts/run_provider_observation_store_mutations.py) | In-Place | [`daedalus/runtimes/provider/observation_store.py`](../../../daedalus/runtimes/provider/observation_store.py) | 2 |
| [`run_provider_observation_store_contract_mutations.py`](../../../scripts/run_provider_observation_store_contract_mutations.py) | In-Place | [`daedalus/runtimes/provider/observation_store_contract.py`](../../../daedalus/runtimes/provider/observation_store_contract.py) | 2 |

### Provider: Receipt-Retention

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_provider_target_receipt_retention_mutations.py`](../../../scripts/run_provider_target_receipt_retention_mutations.py) | In-Place | [`daedalus/runtimes/provider/target_receipt_ledger.py`](../../../daedalus/runtimes/provider/target_receipt_ledger.py) | 3 |
| [`run_provider_target_receipt_retention_admission_mutations.py`](../../../scripts/run_provider_target_receipt_retention_admission_mutations.py) | Sandbox (eigen) | [`daedalus/runtimes/provider/target_receipt_retention_admission.py`](../../../daedalus/runtimes/provider/target_receipt_retention_admission.py) | 2 |
| [`run_provider_target_receipt_retention_completed_evidence_mutations.py`](../../../scripts/run_provider_target_receipt_retention_completed_evidence_mutations.py) | Sandbox (eigen) | [`daedalus/runtimes/provider/target_receipt_retention_completed_evidence.py`](../../../daedalus/runtimes/provider/target_receipt_retention_completed_evidence.py) | 4 |
| [`run_provider_target_receipt_retention_contract_mutations.py`](../../../scripts/run_provider_target_receipt_retention_contract_mutations.py) | In-Place | [`daedalus/runtimes/provider/target_receipt_retention_contract.py`](../../../daedalus/runtimes/provider/target_receipt_retention_contract.py) | 2 |
| [`run_provider_target_receipt_retention_effect_terminal_evidence_mutations.py`](../../../scripts/run_provider_target_receipt_retention_effect_terminal_evidence_mutations.py) | Sandbox (eigen) | [`daedalus/runtimes/provider/target_receipt_retention_effect_terminal_evidence.py`](../../../daedalus/runtimes/provider/target_receipt_retention_effect_terminal_evidence.py) | 0 |
| [`run_provider_target_receipt_retention_inventory_mutations.py`](../../../scripts/run_provider_target_receipt_retention_inventory_mutations.py) | In-Place | [`daedalus/gates/provider_target_receipt_retention_inventory.py`](../../../daedalus/gates/provider_target_receipt_retention_inventory.py) | 2 |
| [`run_provider_target_receipt_retention_preflight_mutations.py`](../../../scripts/run_provider_target_receipt_retention_preflight_mutations.py) | Sandbox (eigen) | [`daedalus/runtimes/provider/target_receipt_retention_preflight.py`](../../../daedalus/runtimes/provider/target_receipt_retention_preflight.py) | 2 |
| [`run_provider_target_receipt_retention_recovery_mutations.py`](../../../scripts/run_provider_target_receipt_retention_recovery_mutations.py) | Sandbox (eigen) | [`daedalus/runtimes/provider/target_receipt_retention_recovery.py`](../../../daedalus/runtimes/provider/target_receipt_retention_recovery.py) | 3 |
| [`run_provider_target_verification_mutations.py`](../../../scripts/run_provider_target_verification_mutations.py) | Wrapper | Spezifikation `configs/mutations/provider-target-verification.json` | (in der Spezifikation) |

### Provider: Wiederherstellung nach unbekanntem Ausgang

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_runtime_post_provider_unknown_mutations.py`](../../../scripts/run_runtime_post_provider_unknown_mutations.py) | In-Place | [`daedalus/runtimes/broker.py`](../../../daedalus/runtimes/broker.py), [`daedalus/runtimes/recovery.py`](../../../daedalus/runtimes/recovery.py) | 5 |

### Repository-Write-Familie

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_repository_head_revision_mutations.py`](../../../scripts/run_repository_head_revision_mutations.py) | Sandbox (eigen) | [`daedalus/gates/repository/head_revision.py`](../../../daedalus/gates/repository/head_revision.py) | 1 |
| [`run_repository_tree_mutations.py`](../../../scripts/run_repository_tree_mutations.py) | Wrapper | Spezifikation `configs/mutations/repository-tree.json` | (in der Spezifikation) |
| [`run_repository_write_artifact_admission_mutations.py`](../../../scripts/run_repository_write_artifact_admission_mutations.py) | In-Place | [`daedalus/gates/repository/write_artifact_admission.py`](../../../daedalus/gates/repository/write_artifact_admission.py) | 4 |
| [`run_repository_write_artifact_cas_mutations.py`](../../../scripts/run_repository_write_artifact_cas_mutations.py) | In-Place | [`daedalus/gates/repository/write_artifact_cas.py`](../../../daedalus/gates/repository/write_artifact_cas.py) | 6 |
| [`run_repository_write_artifact_verifier_mutations.py`](../../../scripts/run_repository_write_artifact_verifier_mutations.py) | In-Place | [`daedalus/gates/repository/write_artifact_verifier.py`](../../../daedalus/gates/repository/write_artifact_verifier.py) | 4 |
| [`run_repository_write_classification_mutations.py`](../../../scripts/run_repository_write_classification_mutations.py) | In-Place | [`daedalus/gates/repository/write_classification.py`](../../../daedalus/gates/repository/write_classification.py) | 5 |
| [`run_repository_write_effect_lease_mutations.py`](../../../scripts/run_repository_write_effect_lease_mutations.py) | Wrapper | Spezifikation `configs/mutations/repository-write-effect-lease.json` | (in der Spezifikation) |
| [`run_repository_write_evidence_mutations.py`](../../../scripts/run_repository_write_evidence_mutations.py) | In-Place | [`daedalus/gates/repository/write_evidence.py`](../../../daedalus/gates/repository/write_evidence.py) | 3 |
| [`run_repository_write_evidence_materialization_mutations.py`](../../../scripts/run_repository_write_evidence_materialization_mutations.py) | In-Place | [`daedalus/gates/repository/write_evidence_materialization.py`](../../../daedalus/gates/repository/write_evidence_materialization.py) | 2 |
| [`run_repository_write_evidence_origin_mutations.py`](../../../scripts/run_repository_write_evidence_origin_mutations.py) | In-Place | [`daedalus/gates/repository/write_evidence_origin.py`](../../../daedalus/gates/repository/write_evidence_origin.py) | 2 |
| [`run_repository_write_guard_structure_mutations.py`](../../../scripts/run_repository_write_guard_structure_mutations.py) | In-Place | [`daedalus/gates/repository/write_guard_structure.py`](../../../daedalus/gates/repository/write_guard_structure.py) | 1 |
| [`run_repository_write_inventory_mutations.py`](../../../scripts/run_repository_write_inventory_mutations.py) | In-Place | [`daedalus/gates/repository/write_inventory.py`](../../../daedalus/gates/repository/write_inventory.py) | 4 |
| [`run_repository_write_inventory_v2_mutations.py`](../../../scripts/run_repository_write_inventory_v2_mutations.py) | In-Place | [`daedalus/gates/repository/write_inventory_v2.py`](../../../daedalus/gates/repository/write_inventory_v2.py) | 2 |
| [`run_repository_write_runtime_conformance_mutations.py`](../../../scripts/run_repository_write_runtime_conformance_mutations.py) | In-Place | [`daedalus/gates/repository/write_runtime_conformance.py`](../../../daedalus/gates/repository/write_runtime_conformance.py) | 2 |
| [`run_repository_write_source_anchor_semantics_mutations.py`](../../../scripts/run_repository_write_source_anchor_semantics_mutations.py) | In-Place | [`daedalus/gates/repository/write_source_anchor_semantics.py`](../../../daedalus/gates/repository/write_source_anchor_semantics.py) | 1 |
| [`run_repository_write_stdlib_delta_mutations.py`](../../../scripts/run_repository_write_stdlib_delta_mutations.py) | In-Place | [`daedalus/gates/repository/write_stdlib_delta.py`](../../../daedalus/gates/repository/write_stdlib_delta.py) | 2 |

### Gate-Berichte, Guard-Manifest und Wire-Vertraege

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_gate0_release_writer_inventory_mutations.py`](../../../scripts/run_gate0_release_writer_inventory_mutations.py) | In-Place | [`daedalus/gates/release.py`](../../../daedalus/gates/release.py) | 5 |
| [`run_gate_baseline_v2_mutations.py`](../../../scripts/run_gate_baseline_v2_mutations.py) | In-Place | [`daedalus/gates/baseline.py`](../../../daedalus/gates/baseline.py), [`daedalus/gates/baseline_verifier.py`](../../../daedalus/gates/baseline_verifier.py) | 5 |
| [`run_gate_report_v3_mutations.py`](../../../scripts/run_gate_report_v3_mutations.py) | Wrapper | Spezifikation `configs/mutations/gate-report-v3.json` | (in der Spezifikation) |
| [`run_gate_report_writer_inventory_mutations.py`](../../../scripts/run_gate_report_writer_inventory_mutations.py) | In-Place | [`daedalus/gates/report.py`](../../../daedalus/gates/report.py) | 5 |
| [`run_guard_implementation_manifest_mutations.py`](../../../scripts/run_guard_implementation_manifest_mutations.py) | In-Place | [`daedalus/gates/guard_implementation_manifest.py`](../../../daedalus/gates/guard_implementation_manifest.py) | 1 |
| [`run_python_target_structure_mutations.py`](../../../scripts/run_python_target_structure_mutations.py) | In-Place | [`daedalus/gates/python_target_structure.py`](../../../daedalus/gates/python_target_structure.py) | 1 |
| [`run_evidence_index_wire_mutations.py`](../../../scripts/run_evidence_index_wire_mutations.py) | In-Place | [`daedalus/gates/evidence_io.py`](../../../daedalus/gates/evidence_io.py) | 2 |
| [`run_trust_bundle_wire_mutations.py`](../../../scripts/run_trust_bundle_wire_mutations.py) | In-Place | [`daedalus/gates/__init__.py`](../../../daedalus/gates/__init__.py), [`daedalus/gates/trust_bundle_io.py`](../../../daedalus/gates/trust_bundle_io.py) | 7 |

### Event Store und Writer-Inventar

| Runner | Modus | Angegriffenes Modul | Testdateien |
| --- | --- | --- | --- |
| [`run_spine_durability_mutations.py`](../../../scripts/run_spine_durability_mutations.py) | In-Place | [`daedalus/spine/durability.py`](../../../daedalus/spine/durability.py) | 4 |
| [`run_spine_writer_factory_mutations.py`](../../../scripts/run_spine_writer_factory_mutations.py) | In-Place | [`daedalus/spine/durability.py`](../../../daedalus/spine/durability.py) | 7 |
| [`run_spine_writer_inventory_mutations.py`](../../../scripts/run_spine_writer_inventory_mutations.py) | In-Place | [`daedalus/spine/writer_inventory.py`](../../../daedalus/spine/writer_inventory.py) | 4 |

## Tests

`scripts/` wird nicht nur ausgefuehrt, es wird auch getestet -- die Kampagnen
sind selbst Evidenzerzeuger, also pinnt der Baum ihre Form. Dateien unter
`tests/`, die dieses Verzeichnis namentlich referenzieren (gemessen
2026-09-05):

| Testdatei | Deckt ab |
| --- | --- |
| [`tests/test_declare_write_surfaces.py`](../../../tests/test_declare_write_surfaces.py) | `declare_write_surfaces.py`: Tuerenaufloesung, AST-Dominanz, Evidenz-Aufbewahrung. |
| [`tests/gates/test_attempt_anchor_dominance.py`](../../../tests/gates/test_attempt_anchor_dominance.py), [`tests/gates/test_write_surface_lease_dominance.py`](../../../tests/gates/test_write_surface_lease_dominance.py) | Die Dominanzregel, die das Skript implementiert. |
| [`tests/gates/test_write_evidence_producer.py`](../../../tests/gates/test_write_evidence_producer.py), [`tests/kernel/test_write_evidence_records.py`](../../../tests/kernel/test_write_evidence_records.py) | Die Write-Evidence-Produktion, die `run_write_evidence_production_mutations.py` angreift. |
| [`tests/test_mutation_score.py`](../../../tests/test_mutation_score.py), [`tests/contracts/test_gate_promotion_mutation_specs.py`](../../../tests/contracts/test_gate_promotion_mutation_specs.py), [`tests/contracts/test_attempt_event_time_mutation_transport.py`](../../../tests/contracts/test_attempt_event_time_mutation_transport.py) | Der deklarative Runner und die Spezifikationen, auf die die zehn Wrapper zeigen. |
| [`tests/gates/test_gate0_release_cli.py`](../../../tests/gates/test_gate0_release_cli.py), [`tests/gates/test_gate0_release_assessment.py`](../../../tests/gates/test_gate0_release_assessment.py), [`tests/gates/test_gate0_release_assessment_review.py`](../../../tests/gates/test_gate0_release_assessment_review.py), [`tests/gates/test_gate0_release_writer_inventory.py`](../../../tests/gates/test_gate0_release_writer_inventory.py) | `gate0_release.py`. |
| [`tests/gates/test_gate_report_v3_cli.py`](../../../tests/gates/test_gate_report_v3_cli.py), [`tests/test_gate_scanner_report_schema.py`](../../../tests/test_gate_scanner_report_schema.py), [`tests/test_gate_scanner_identity.py`](../../../tests/test_gate_scanner_identity.py) | `report_gate0_v3.py` und die Inventar-Scanner. |
| [`tests/gates/test_gate_cli_conformance_receipts.py`](../../../tests/gates/test_gate_cli_conformance_receipts.py) | Konformanzquittungen der Gate-CLIs. |
| [`tests/gates/test_provider_target_receipt_retention_inventory.py`](../../../tests/gates/test_provider_target_receipt_retention_inventory.py), [`tests/gates/test_chip_repository_write_inventory.py`](../../../tests/gates/test_chip_repository_write_inventory.py), [`tests/gates/test_repository_head_revision_integration_review.py`](../../../tests/gates/test_repository_head_revision_integration_review.py) | Die Inventarberichte. |
| [`tests/test_offload_lease_harness.py`](../../../tests/test_offload_lease_harness.py), [`tests/test_offload_unleased_planner.py`](../../../tests/test_offload_unleased_planner.py) | Die Lease-Dominanz, die `run_offload_lease_dominance_mutations.py` angreift. |
| [`tests/test_write_guard_e2e.py`](../../../tests/test_write_guard_e2e.py), [`tests/test_repair_blast_radius_write.py`](../../../tests/test_repair_blast_radius_write.py), [`tests/test_era1_robustness.py`](../../../tests/test_era1_robustness.py), [`tests/test_fake_offload.py`](../../../tests/test_fake_offload.py) | Weitere Konsumenten der Write-Deklaration. |
| [`tests/test_verify_test_budget.py`](../../../tests/test_verify_test_budget.py), [`tests/test_drafts.py`](../../../tests/test_drafts.py), [`tests/test_skills.py`](../../../tests/test_skills.py), [`tests/test_tools_vet.py`](../../../tests/test_tools_vet.py), [`tests/test_structcore_ignore.py`](../../../tests/test_structcore_ignore.py), [`tests/test_blender_scene_assets.py`](../../../tests/test_blender_scene_assets.py) | Nennen `scripts/`-Pfade in anderen Zusammenhaengen. |

Die Fourfold-Sonden haben (gemessen 2026-09-05) keine eigene Testdatei; sie
werden ueber ihre Ausgaben in Work Packets belegt.

## Verwandt

* [Tooling: tools/](tools.md) -- die wiederverwendbare Werkzeugbibliothek,
  insbesondere der deklarative Mutations-Runner.
* [Interfaces CLI](../architecture/interfaces-cli.md) -- die Befehle mit
  Registry-Zeile, im Gegensatz zu diesem Verzeichnis.
* [Gates](../architecture/gates.md) und
  [Gates Repository](../architecture/gates-repository.md) -- die Scanner,
  Berichte und Vertraege, die hier bedient bzw. angegriffen werden.
* [Spine](../architecture/spine.md) -- `SCAN_PACKAGES`, `HARNESS_PACKAGES`,
  Effekt-Registry, Durability.
* [Kernel](../architecture/kernel.md) -- Attempts, Promotion, Leases,
  Write-Evidence.
* [Runtimes Provider](../architecture/runtimes-provider.md) -- die
  Provider-Invocation- und Retention-Module, gegen die die groesste
  Kampagnengruppe laeuft.
* [Twin Extractors](../architecture/twin-extractors.md) -- `detect_language`,
  `parse_artifact`, `inspect_root_artifact` fuer die Fourfold-Sonden.
* [Interfaces Desktop](../architecture/interfaces-desktop.md) -- der Sidecar,
  den der eingefrorene Launcher startet.
* [Tool-Vetting](../tool-vetting.md)
* [Feature-Backlog](../feature-backlog.md)
* [Wiki-Index](../index.md)

## Ungeklaert

* **Geklaert 2026-09-05:**
  [`run_promotion_receipt_authority_mutations.py`](../../../scripts/run_promotion_receipt_authority_mutations.py)
  greift jetzt die tatsaechlichen Eigentuemermodule
  [`security.py`](../../../daedalus/kernel/contracts/security.py) und
  [`canonical.py`](../../../daedalus/kernel/contracts/canonical.py) an. Sein
  Docstring behaelt den frueheren toten Einzeldatei-Pfad und den damals
  gemessenen Vorabbruch als historische Fehlerursache; der laufende Runner
  verwendet den Paketpfad.
* **Ungeklaert:** Wie viele der 73 Kampagnen heute noch gruen laufen. Diese
  Seite hat keine davon ausgefuehrt -- In-Place-Runner schreiben in den
  Arbeitsbaum, und der ist in dieser Session dreckig und wird parallel benutzt.
* **Ungeklaert:** Warum zehn Kampagnen auf den deklarativen Runner migriert
  wurden und 58 nicht. Ein Kriterium ist aus den Wrappern nicht ablesbar.
* **Ungeklaert:** `gate0_baseline.py` und drei `report_*`-Skripte haben keinen
  Modul-Docstring; ihr Zweck steht nur in der `argparse`-Beschreibung.
* **Ungeklaert:** Die Zahl "74 Mutations-Runner", die
  `daedalus/spine/effect_boundary.py:3316` als Messung von 2026-08-17 nennt,
  weicht von den heute gezaehlten 73 `run_*_mutations.py` ab. Ob eine Datei
  entfernt wurde oder ob die alte Zaehlung `fault_mutation_sandbox.py`
  mitzaehlte, ist aus dem Baum nicht entscheidbar.

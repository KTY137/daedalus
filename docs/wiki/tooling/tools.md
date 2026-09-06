---
title: Tools
type: tooling
status: living
updated: 2026-09-05
covers: tools
---
# Tools

`tools/` ist das Werkzeugverzeichnis des Repositories: Instrumente, mit denen
Behauptungen ueber Daedalus gemessen, widerlegt oder als Quittung festgehalten
werden. 28 `.py`-Dateien, 14651 Zeilen, dazu drei Shell-/PowerShell-Skripte
(`bench_test.sh`, `continuous_daedalus.ps1`, `recreate_tct_venv.ps1`) --
gemessen 2026-09-05. Es ist ausdruecklich **kein** Daedalus-Subsystem: kein
Werkzeug hier fuehrt eine Control-Plane, keines promotet etwas, und keines ist
ein Ersatz fuer den kanonischen Kernel (Masterplan Abschnitt 13). Im
Kernel/Ikarus/Ariadne-Bild sind das Evidenz-Erzeuger nach Abschnitt 0: Tests,
Quittungen und Experimente, die Statusbehauptungen widerlegen duerfen.

Der wiederkehrende Gedanke des Verzeichnisses steht in mehreren Docstrings fast
gleichlautend: **eine gruene Suite ist eine Behauptung, eine Suite, die einen
gesaeten Defekt toetet, ist eine Kontrolle.** Deshalb gibt es hier drei
Instanzen desselben Musters (`self_test.py`, `mutation_score.py`,
`gate_discrimination.py`) und einen Drill, der jede Kontrolle absichtlich
ausloest (`operability_drill.py`).

Ebenfalls wiederkehrend: **drei Ausgaenge, und nur einer ist Erfolg.** `PASS`,
`FAIL`, `UNAVAILABLE`/`INCOMPLETE` -- und `UNAVAILABLE` ist auf einer
Kernpruefung nicht einmal neutral. `system_check.py` und `gui_check.py`
kodieren das identisch im Exit-Code: `0` alles gelaufen und gehalten, `1`
mindestens eine Pruefung fehlgeschlagen, `2` eine Kernpruefung konnte nicht
laufen, der Lauf beweist also nichts.

## Module

### Akzeptanz, Drills und Gate-Evidenz

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`system_check.py`](../../../tools/system_check.py) | Der End-zu-Ende-Akzeptanzlauf ueber die echten Pfade: laeuft der Spine auf dieser Maschine, jetzt -- oder welche Stufe nicht, mit Evidenz. Alles laeuft in einem Wegwerf-Klon mit eigener Spine-Datenbank und eigenem HOME, weil eine Pruefung, die Mutation beobachten soll, das nicht im selben Baum tun kann, aus dem sie gelesen wird. | `Result`, `Sandbox`, `check`, `run`, `acceptance_run`, `verdict`, `report`, `main`, `read_intents` |
| [`gui_check.py`](../../../tools/gui_check.py) | Browser-Akzeptanz fuer das Cockpit. `system_check` beweist, dass der *Server* laeuft; ein Server, der auf jeder Route 200 antwortet, ist von aussen nicht von einem zu unterscheiden, dessen Bundle beim Modul-Evaluieren wirft und eine weisse Seite rendert. Startet ein `daedalus web` auf einem freien Loopback-Port und toetet es in einem `finally` auf jedem Pfad. Die Opt-in-Variablen fuer Nicht-Loopback werden aus der Kindumgebung **entfernt**, nicht nur nicht gesetzt. | `Outcome`, `gui_run`, `preflight`, `suite_timeout_s`, `aggregate_timeout_s`, `timeout_message`, `main` |
| [`operability_drill.py`](../../../tools/operability_drill.py) | Der Betriebsdrill: jede Kontrolle wird absichtlich ausgeloest, End zu Ende ueber Scheduler, CLI, Gate und Prozessbaum. `PASSED` nur, wenn Effekt **und** Telemetrie kausal sichtbar sind. Existiert, weil jede dieser Kontrollen zu irgendeinem Zeitpunkt gleichzeitig vorhanden und wirkungslos war -- "gebaut" und "in Kraft" sind verschiedene Woerter, und Unit-Tests koennen sie nicht unterscheiden, weil sie den Waechter direkt aufrufen. | `Control`, `control_promotion`, `control_spend`, `control_kill_switch`, `control_gate_escape`, `control_damage_is_bounded`, `control_primary_untouched`, `staleness`, `run`, `main` |
| [`gate_discrimination.py`](../../../tools/gate_discrimination.py) | Weist das Gate (pytest ueber `gate_paths`) wirklich schlechte Patches zurueck? Saet echte, an Vorfaellen modellierte Defekte und schreibt die Quittung nach `runs/spine/gate_discrimination.json`, die `daedalus/spine/bootstrap.py` verlangt, bevor es Promotion "bewiesen" nennt. Eine Auditierung mass die Rueckweisungsquote gegen die drei bekannt-schlechten Aenderungen eines Tages mit 0/3. | `Mutation`, `HeadOnlySandbox`, `run_corpus`, `apply_mutation`, `restore_mutation`, `check_anchors`, `validate_unique_anchor`, `covered_lines`, `filter_by_coverage`, `sort_by_diff_relevance`, `diff_touched_files`, `freeze_gate_config`, `frozen_argv`, `write_receipt`, `main` |
| [`gate_host_preflight.py`](../../../tools/gate_host_preflight.py) | Zwei Fragen in einem Werkzeug, weil sie eine sind: **Tauglichkeit** (kann diese Maschine die Messung ueberhaupt fahren -- eine fehlende Testabhaengigkeit erzeugt kein rotes Gate, sondern ein Gate, das etwas anderes misst) und **Identitaet** (welche Maschine hat die Quittung erzeugt). Jede Anforderung wird geprueft und jede Antwort berichtet, auch die guten. | `Check`, `Preflight`, `collect_host`, `run_checks`, `render`, `main` |
| [`mutation_score.py`](../../../tools/mutation_score.py) | Kann diese Suite einen Defekt entdecken, den sie zu decken behauptet? Die verallgemeinerte dritte Instanz des Musters. Vier Invarianten: nichts fasst das Arbeitsrepository an, die Basislinie muss zuerst gruen sein (sonst `INCONCLUSIVE`, nie eine Punktzahl), eine nicht anwendbare Mutation ist `NOT_APPLICABLE` und nie ein Ueberlebender, und ein Ueberlebender ist die Schlagzeile, nicht die Fussnote. | `Mutation`, `Sandbox`, `RunResult`, `ExplicitMutationSpec`, `ExplicitMutationJob`, `MutationSpecError`, `generate_mutations`, `load_explicit_spec`, `score`, `score_explicit_spec`, `pytest_runner`, `drop_test`, `sample`, `render`, `render_explicit_spec`, `main` |
| [`self_test.py`](../../../tools/self_test.py) | Beweist, dass die Akzeptanzpruefungen **fehlschlagen koennen** -- indem es das System tatsaechlich kaputt macht. Je gedeckter Pruefung: ein Wegwerf-Klon, genau **ein** gesaeter Defekt, und diese Pruefung muss `FAIL` melden. Ein Defekt, den niemand faengt, wird als `UNFALSIFIABLE` gemeldet. | `run_self_test`, `_run_one`, plus die `m_*`-Mutationen (`m_attempt_moves_head`, `m_leak_a_branch`, `m_offload_writes`, `m_allow_remote_ollama`, `m_room_trusts_everyone`, `m_eval_returns_no_score` und weitere) |
| [`bootstrap_receipt.py`](../../../tools/bootstrap_receipt.py) | Der Bootstrap-Einstieg: ein Attempt, bis ans Gate gefahren, mit Quittung. Enthaelt einen Primaer-Fingerabdruck vor und nach dem Lauf sowie eine Leck-Pruefung. Der Docstring erklaert, warum die Datei ueberhaupt einen `__main__`-Guard braucht: ohne ihn liefen unter Windows zehn parallele Attempts, weil jeder gespawnte `ProcessPoolExecutor`-Worker das Hauptmodul neu importiert. | `run_single`, `run_concurrent`, `primary_fingerprint`, `stamped_offload_runner`, `build_parser`, `main` |
| [`assert_gate_report.py`](../../../tools/assert_gate_report.py) | Der duennste CLI des Verzeichnisses (38 Zeilen, kein Docstring): laedt einen Gate-Bericht ueber `load_gate_report`, prueft mit `--require-monotonic` gegen eine Basislinie auf Regressionen und mit `--require-closed`, ob der Bericht geschlossen ist. Exit 1 mit JSON auf stdout, sonst 0. | `main` |
| [`run_gate_checks.py`](../../../tools/run_gate_checks.py) | Faehrt die kanonischen lokalen und CI-Verifikationsprofile fuer den Gate-0-nach-Gate-1-Stapel. | `main`, `_require_pytest`, `_run` |

### Struktur- und Governance-Pruefer

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`architecture_boundaries.py`](../../../tools/architecture_boundaries.py) | Der deterministische Import-Grenzvertrag ueber verfolgte Quellen. Parst nur Python-Dateien, die `git ls-files` unter der konfigurierten Quellwurzel liefert, und importiert **nie** ein Repository-Modul. Bestehende Verletzungen bleiben als exakte, pruefbare Basislinie erhalten: Schulden abbauen ist erlaubt, eine neue oder verschobene Verletzung laesst die Pruefung fehlschlagen. Ausdruecklich nur strukturelle Evidenz -- dynamische Importe, Laufzeit-Dispatch, Monkeypatching und generierter Code liegen ausserhalb der Beobachtungsgrenze. | `ImportBoundaryContract`, `ImportBoundaryRule`, `BoundaryViolation`, `BoundaryReport`, `ShimEntry`, `ArchitectureBoundaryError`, `load_contract`, `load_shim_registry`, `validate_shim_locators`, `scan_repository`, `evaluate_repository`, `render_human` |
| [`index_work_packets.py`](../../../tools/index_work_packets.py) | Prueft die deterministische, nur-verfolgte Work-Packet-Registry. Ruft absichtlich **kein** Git auf: ein Subprozess wuerde diese Governance-Pruefung selbst zu einem neuen `PROCESS_SPAWN`-Einstiegspunkt machen und die kanonische Effekt-Registry aendern, nur um Dateien aufzuzaehlen. Stattdessen liest ein enger Parser die Git-Index-Formate DIRC v2/v3 und verweigert geteilte, spaerliche, konfliktbehaftete oder sich aendernde Indizes. | `IndexError`, `parse_git_index`, `tracked_paths`, `build_index`, `load_index`, `check`, `canonical_json`, `canonical_packet_id`, `main` |
| [`effect_boundary_check.py`](../../../tools/effect_boundary_check.py) | 46 Zeilen: meldet oder blockiert Drift in der Gate-0-Registry der effektbehafteten Einstiegspunkte. | `main` |
| [`docs_reference_check.py`](../../../tools/docs_reference_check.py) | Zeigt die Prosa noch auf Dateien, die existieren? Dokumentation verrottet zuerst mechanisch: ein Paket wird umsortiert, ein Skript stillgelegt, ein Verzeichnis archiviert -- und jeder Satz mit dem alten Pfad liest sich weiter wie eine Anweisung. Ein Sweep am 2026-08-25 fand drei laengst verschobene Pfade in aktuellen Seiten. | `scan`, `main` |
| [`lane_invariants.py`](../../../tools/lane_invariants.py) | Deterministische, kostenlose, exakte Zusicherungen ueber einen aufgezeichneten Lane-Lauf. Schicht 2 des Beobachtungsstapels (Flugschreiber, dann Invarianten, dann Modell). Jede Pruefung hier entspricht einem Fehler, der am 2026-07-30 tatsaechlich passierte und damals unsichtbar war -- 169 Module an eine externe Lane, 715 brauchbare Antworten, 2 Befunde, und jede Ursache war Arithmetik, die niemand berechnete. | `Violation`, `check`, `main` |

### Advisory-Fan-out und seine Auswertung

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`audit_swarm.py`](../../../tools/audit_swarm.py) | Ein vollstaendiger adversarialer Durchgang ueber `daedalus/` durch die billige externe Lane. Operator-autorisierter Egress (2026-07-30): der Standard ist, dass die externe Lane beratend ist und nur liest, was die Egress-Allowlist erlaubt. Fuer diesen Lauf hob der Owner die Liste ausdruecklich auf; zwei Dinge bleiben trotzdem aufgehoben-frei. | `tracked_modules`, `chunks_for`, `build_tasks`, `main` |
| [`audit_triage.py`](../../../tools/audit_triage.py) | Verwandelt Schwarm-Behauptungen in gerankte, mechanisch geprueft Befunde. Lokal, kostenlos, Phase 3 der Audit-Kette -- und der Grund, dass es eine Phase 3 gibt: die Behauptung eines Modells ist eine *Hypothese*. Am 2026-07-30 produzierte ein billiges Modell 154 Kandidaten, von denen **147 falsch waren** -- 95,5 % Falschpositive. | `Claim`, `Group`, `parse_claim`, `load_claims`, `group_claims`, `main` |
| [`agent_findings.py`](../../../tools/agent_findings.py) | Konsolidiert, was die externen Review-Lanes tatsaechlich gesagt haben. Ein Fan-out aus hundert beratenden Agenten erzeugt hundert JSON-Berichte; eine naive Verkettung liest denselben Defekt in vier Formulierungen als vier Probleme und begraebt den echten Einzelfund darunter. | `load_reports`, `extract`, `cluster`, `by_target`, `render`, `main` |
| [`funnel.py`](../../../tools/funnel.py) | Richtet einen gestuften Schwarm auf ein Ziel und liefert JSON. Ein **Operator-Instrument**, kein Daedalus-Subsystem: es leiht sich genau zwei Dinge (die beratende Fan-out-Lane und den redigierenden `.env`-Loader) und fuegt keine Control-Plane, keinen Zustandsspeicher und keinen Weg ins Produkt hinzu. Die Ausgabe ist ein Stapel Modellmeinungen fuer einen Menschen, nie Evidenz und nie ein Gate. | `budget_state`, `budget_verdict`, `budget_summary`, `code_chunks`, `document_sections`, `from_tier`, `attach_evidence`, `load_spec`, `repo_index`, `build_tasks`, `main` |
| [`funnel_report.py`](../../../tools/funnel_report.py) | Liest einen Funnel-Lauf zurueck: erst Lane-Gesundheit, dann Schwund, dann Inhalt. Die Reihenfolge ist die Aussage. Ein Bericht, der Befunde druckt, bevor er gezeigt hat, dass die Antworten ueberhaupt *verschieden* waren, kann "das Ziel ist sauber" nicht von "die Lane ist kaputt" unterscheiden -- am 2026-07-30 lieferte ein Fan-out 715 Antworten, 692 davon in einer Form, und jeder nachgelagerte Konsument las das als sauberen Code. | `lane_health`, `tier_yield`, `read_tier`, `harvest`, `strict_paths`, `payloads`, `revisions`, `survey`, `diff`, `bar`, `normalize`, `repo_files`, `main` |
| [`guarded_call.py`](../../../tools/guarded_call.py) | Eine Tuer fuer einen externen Modellaufruf, benutzbar aus einem Prozess, der kein `daedalus` hat. Als **Prozess** und nicht als Import, weil ein Prompt-Optimierer sein Modell ueber `litellm` erreicht, das `openai`, `aiohttp` und zwei Dutzend weitere Pakete nachzieht -- das neben die bewachten Lanes in denselben Interpreter zu installieren, schafft einen zweiten, unbudgetierten Weg, Geld auszugeben. | `main` |

### Verpackung, Desktop und Assets

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`build_tauri_sidecar.py`](../../../tools/build_tauri_sidecar.py) | Baut das Python-Backend als Tauri-Ressource. PyInstaller laeuft absichtlich im `onedir`-Modus: Tauri besitzt den aeusseren Installer, waehrend die Python-Laufzeit ein Einzelprozess-Kind bleibt, dessen Lebenszyklus die Rust-Huelle zuverlaessig beenden kann. | `bundle_files`, `bundle_identity`, `assert_no_accelerator_runtime_payload`, `build`, `main` |
| [`smoke_tauri_sidecar.py`](../../../tools/smoke_tauri_sidecar.py) | End-zu-Ende-Rauchtest fuer das eingefrorene Desktop-Backend. | `executable_name`, `smoke`, `main` |
| [`smoke_packaged_resources.py`](../../../tools/smoke_packaged_resources.py) | Raucht ein installiertes Daedalus-Wheel, ohne den Quell-Checkout zu importieren. Absichtlich netzfrei: erst in ein isoliertes Zielverzeichnis installieren, dann dieses hier uebergeben. | `main` |
| [`select_desktop_release_assets.py`](../../../tools/select_desktop_release_assets.py) | Baut und waehlt die fuenf verteilbaren Desktop-Release-Artefakte. Das macOS-`app`-Artefakt ist ein Verzeichnis und muss vor dem Upload archiviert werden, damit Ausfuehrungsbits und Symlinks erhalten bleiben; die Veroeffentlichung laesst genau ein Artefakt je erwartetem Typ zu und laedt nie rekursiv die Interna eines Bundles hoch. | `select_release_assets`, `archive_macos_app`, `verify_macos_arm64_bundle`, `main` |
| [`build_scene_environments.py`](../../../tools/build_scene_environments.py) | Macht aus den Blender-Szenenrenderings die Umgebungs-Assets des Cockpits. Ein fehlendes Endrendering faellt auf den Entwurf zurueck und wird als `quality: draft` markiert, damit das Theme-Studio das sagen kann, statt eine 24-Sample-Vorschau als fertiges Bild auszugeben. | `build`, `check`, `locate`, `encode`, `sha256`, `main` |
| [`import_codex_state.py`](../../../tools/import_codex_state.py) | Importiert Offline-Codex-Sitzungen und -Erinnerungen von einer anderen Maschine sicher. Trockenlauf ist die Voreinstellung; ausdruecklich **keine** allgemeine Synchronisation: Zugangsdaten, Konfiguration, Logs, SQLite-Zustand, Caches und temporaere Verzeichnisse liegen ausserhalb der Allowlist. | `ImportReport`, `import_state`, `main` |

### Hintergrundwache

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`watchdog.py`](../../../tools/watchdog.py) | Groesste Datei des Verzeichnisses (1323 Zeilen): Hintergrundwachen fuer Doku, Arbeit und die beratende Flotte, registrierbar als Windows-Aufgaben ohne Adminrechte. Prinzip **mechanisch zuerst, Modell nur auf Evidenz**: eine Hintergrundschleife, die ein Modell auf einen Timer ruft, verbrennt an ruhigen Nachmittagen Geld. Erst wird in Python gemessen (veraltetes Architektur-Gedaechtnis, geloeschte Dateien in Top-Level-Doku ohne Ersatzvermerk, tote relative Links, HEAD-Alter, verwaiste `.git/index.lock`, freier Plattenplatz), und nur ein Doku-Durchgang **mit** Befunden startet ein Modell. Jeder Spawn laeuft durch die Budget-Reservierung. | `PassLock`, `ModelRun`, `Drift`, `Anomaly`, `docs_pass`, `prune_pass`, `docs_drift`, `prune_candidates`, `health`, `anomalies`, `run_claude`, `own_ledger`, `head_quiet`, `paused`, `spend_today`, `model_runs_today` |

## Trust-Grenzen / Effekte

**23 der 28 Dateien haben eine Zeile in der Effekt-Registry.** Gezaehlt
2026-09-05 in `daedalus/spine/effect_boundary.py`: `tools.guarded_call`,
`tools.audit_swarm`, `tools.funnel`, `tools.funnel_report`,
`tools.gate_discrimination`, `tools.bootstrap_receipt`,
`tools.operability_drill`, `tools.gate_host_preflight`, `tools.gui_check`,
`tools.mutation_score`, `tools.audit_triage`, `tools.agent_findings`,
`tools.lane_invariants`, `tools.run_gate_checks`, `tools.system_check`,
`tools.watchdog`, `tools.docs_reference_check`, `tools.desktop_sidecar_build`,
`tools.desktop_sidecar_smoke`, `tools.packaged_resources_smoke`,
`tools.codex_state_import`, `tools.desktop_release_assets`,
`tools.scene_environments_build`. Die Anker dieser Zeilen verlangen
`begin_effect` in der jeweiligen `main`, teils zusammen mit einem zweiten Anker
(`fan_out`, `budget_verdict`, `run`).

`tools` ist ausserdem eines der drei Verzeichnisse in `SCAN_PACKAGES`, die der
Drift-Detektor der Registry liest. Das war nicht immer so: gemessen 2026-07-30
globbte der Scan nur `daedalus/`, sodass ein neuer effektbehafteter
Einstiegspunkt unter `tools/` fuer ihn unsichtbar war -- verifiziert, indem
einer hinzugefuegt wurde und die Matrix sich nicht aenderte. Beim Zaehlen von
Hand waren damals 18 von 19 Python-Dateien unter `tools/` ein Einstiegspunkt,
der Prozesse spawnt, Dateien schreibt, das Repository mutiert oder Geld
ausgibt.

**Was Geld ausgibt.** `audit_swarm.py`, `funnel.py`, `guarded_call.py` und der
Modellpfad von `watchdog.py` erreichen bezahlte Vendoren. Jeder Spawn faellt
zusaetzlich unter das Prozessnetz aus
[Runtimes Execution](../architecture/runtimes-execution.md), und `funnel.py`
traegt mit `budget_state`/`budget_verdict`/`budget_summary` eine eigene
Vorab-Pruefung.

**Was das Repository mutiert.** `system_check.py`, `mutation_score.py`,
`self_test.py`, `gate_discrimination.py` und `bootstrap_receipt.py` arbeiten in
Wegwerf-Klonen bzw. `Sandbox`/`HeadOnlySandbox`; `operability_drill.py` prueft
mit `control_primary_untouched` ausdruecklich nach, dass der Primaer-Checkout
unberuehrt blieb. `watchdog.py` ist das einzige Werkzeug mit einem
Commit-Effekt (`prune_commit_effect`), und der laeuft nur ausserhalb von
`--dry-run`.

**Was ausdruecklich read-only ist.** `architecture_boundaries.py` (parst nur,
importiert nie), `index_work_packets.py` (liest den Git-Index selbst, statt
Git zu spawnen), `docs_reference_check.py`, `lane_invariants.py`,
`agent_findings.py`, `audit_triage.py`, `funnel_report.py`,
`assert_gate_report.py`.

**Was hier nicht passiert.** Kein Werkzeug promotet einen Kandidaten, keines
schreibt in Policy, Evaluator, Ledger oder Evidence, und keines ist eine
Sicherheitsgarantie. Ein Gate-Ergebnis aus `gate_discrimination.py` ist
Eingabe fuer eine Owner-Entscheidung, nicht die Entscheidung.

## Tests

- [`tests/test_system_check.py`](../../../tests/test_system_check.py) und [`tests/test_gui_check_budget.py`](../../../tests/test_gui_check_budget.py)
- [`tests/test_operability_drill.py`](../../../tests/test_operability_drill.py) und [`tests/test_shadow_run.py`](../../../tests/test_shadow_run.py)
- [`tests/test_gate_discrimination.py`](../../../tests/test_gate_discrimination.py) und [`tests/test_promotion_forgery.py`](../../../tests/test_promotion_forgery.py)
- [`tests/test_mutation_score.py`](../../../tests/test_mutation_score.py) plus die expliziten Mutationsspezifikationen unter [`tests/contracts/test_attempt_effect_inventory_mutation_spec.py`](../../../tests/contracts/test_attempt_effect_inventory_mutation_spec.py), [`tests/contracts/test_attempt_offload_lease_mutation_specs.py`](../../../tests/contracts/test_attempt_offload_lease_mutation_specs.py), [`tests/contracts/test_gate_promotion_mutation_specs.py`](../../../tests/contracts/test_gate_promotion_mutation_specs.py), [`tests/contracts/test_provider_runtime_mutation_specs.py`](../../../tests/contracts/test_provider_runtime_mutation_specs.py), [`tests/contracts/test_attempt_event_time_mutation_transport.py`](../../../tests/contracts/test_attempt_event_time_mutation_transport.py)
- [`tests/test_architecture_boundaries.py`](../../../tests/test_architecture_boundaries.py), [`tests/contracts/test_spine_outer_ports.py`](../../../tests/contracts/test_spine_outer_ports.py), [`tests/kernel/test_fourfold_evidence_outer_ports.py`](../../../tests/kernel/test_fourfold_evidence_outer_ports.py), [`tests/runtimes/test_budget_process_hierarchy.py`](../../../tests/runtimes/test_budget_process_hierarchy.py)
- [`tests/test_effect_boundary.py`](../../../tests/test_effect_boundary.py), [`tests/test_cli_effect_boundary.py`](../../../tests/test_cli_effect_boundary.py), [`tests/test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py) -- decken zusammen die Registry-Zeilen von `guarded_call`, `audit_swarm`, `audit_triage`, `agent_findings`, `lane_invariants`, `gate_host_preflight`
- [`tests/contracts/test_work_packet_index.py`](../../../tests/contracts/test_work_packet_index.py)
- [`tests/test_docs_reference_check.py`](../../../tests/test_docs_reference_check.py) und [`tests/test_reference_audit.py`](../../../tests/test_reference_audit.py)
- [`tests/test_funnel_truth.py`](../../../tests/test_funnel_truth.py)
- [`tests/test_bootstrap_receipt.py`](../../../tests/test_bootstrap_receipt.py) und [`tests/test_worktree_properties.py`](../../../tests/test_worktree_properties.py)
- [`tests/test_watchdog.py`](../../../tests/test_watchdog.py)
- [`tests/test_desktop_packaging.py`](../../../tests/test_desktop_packaging.py) -- Sidecar-Build, Sidecar-Smoke, Wheel-Smoke, Release-Assets
- [`tests/test_blender_scene_assets.py`](../../../tests/test_blender_scene_assets.py) und [`tests/test_ui_governance.py`](../../../tests/test_ui_governance.py)
- [`tests/test_import_codex_state.py`](../../../tests/test_import_codex_state.py)
- [`tests/test_gate_check_profiles.py`](../../../tests/test_gate_check_profiles.py)
- [`tests/test_spend_coverage.py`](../../../tests/test_spend_coverage.py)

## Verwandt

- [Spine](../architecture/spine.md) -- die Effekt-Registry, in der 23 dieser Werkzeuge eine Zeile haben
- [Gates](../architecture/gates.md) -- Gate-Bericht und Fehlmatrix, die `assert_gate_report.py` liest
- [Eval](../architecture/eval.md) -- `daedalus.eval` ist die Bibliotheksseite zu `gate_discrimination.py` und `mutation_score.py`
- [Kernel-Policy](../architecture/kernel-policy.md) und [Runtimes Execution](../architecture/runtimes-execution.md) -- die Budgetgrenzen, an denen `funnel.py` und `guarded_call.py` haengen
- [Providers](../architecture/providers.md) -- die Lanes, die der Fan-out anspricht
- [Scripts](scripts.md) -- das Schwesterverzeichnis fuer Entwickler-Harness
- [Claude-Proposals](claude-proposals.md) und [Tool vetting](../tool-vetting.md) -- die Vetting-Regel fuer neue Werkzeuge
- [GUI](../architecture/gui.md) und [Interfaces Desktop](../architecture/interfaces-desktop.md) -- die Oberflaechen, die `gui_check.py` und die Packaging-Werkzeuge bedienen
- [Feature backlog](../feature-backlog.md) und [Wiki-Index](../index.md)

## Ungeklaert

- **Geklaert (Messung der Review-Session 2026-09-05):** 5 der 28 Dateien sind
  keine Tueren. Die Registry-Discovery ueber `tools/` findet 28 Module und
  21 Tueren, alle 21 registriert, null unregistriert. `assert_gate_report.py`,
  `effect_boundary_check.py` und `index_work_packets.py` haben `main`, aber nur
  `print`/`json.dumps` (die `index.json` entsteht per Shell-Umleitung);
  `architecture_boundaries.py` hat kein `main`, sein `subprocess.run` von
  `git ls-files` (Zeile 607) ist lesender Bibliothekscode; `self_test.py` hat
  kein `main` und schreibt nur in die Sandbox von `system_check`. Bekannter
  Konstruktionsrand des Scanners: seine Tuer-Definition haengt an
  `_HIGH_IMPACT_CALLS` (subprocess/urlopen/http/socket/kill/terminate); ein
  `tools/`-Skript mit `main`, das nur Dateien schreibt, wuerde es nicht sehen.
- **Ungeklaert:** ob `tools/assert_gate_report.py` von irgendeinem
  CI-Workflow aufgerufen wird; unter `tests/` fand die Suche keinen Verweis
  (gemessen 2026-09-05).
- **Ungeklaert:** wo die Funnel-Spezifikationen liegen, die `load_spec` laedt,
  und ob die Beispiel-Tiers noch dem beschriebenen Format entsprechen.
- **Ungeklaert:** ob `bench_test.sh`, `continuous_daedalus.ps1` und
  `recreate_tct_venv.ps1` noch benutzt werden. Sie liegen ausserhalb der
  Python-Registry-Betrachtung und werden von keiner Python-Datei des
  Verzeichnisses referenziert.
- **Hinweis, nichts geloescht:** `import_codex_state.py` und
  `build_scene_environments.py` wirken an genau ein vergangenes Ereignis
  gebunden (Maschinenwechsel bzw. G1-UI-11-Renderings). Beide haben Tests und
  Registry-Zeilen, also ist "tot" hier nicht belegt -- nur "situativ".

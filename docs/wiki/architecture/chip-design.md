---
title: Chip-Design (EDA-Slice)
type: module
status: living
updated: 2026-09-05
covers: daedalus/chip_design
---
# Chip-Design (EDA-Slice)

`daedalus/chip_design/` ist der Hardware-Arm der allgemeinen
Computer-Assistenz: Inventar, Planung, admittierte Ausführung und Evidenz für
EDA-Werkzeuge, heute konkret für AMD Vivado. Das Paket ist mit 12518 Zeilen über
15 Dateien (gemessen 2026-09-05) der größte Einzelbereich dieser Wiki-Seite und
gleichzeitig einer der Bereiche mit der dichtesten Vertrauensgrenze — denn hier
startet Daedalus ein proprietäres, mehrere Gigabyte großes Fremdprogramm auf dem
Host.

Einordnung: Der Slice *fügt keine Autorität hinzu*. Der Docstring von
`contracts.py` sagt es wörtlich: die Records binden die vorhandenen Mission-,
Attempt-, Effect-Lease-, ArtifactStore- und Evidenz-Verträge um ein
hardwarespezifisches Ergebnis herum, damit native EDA-Reports nicht auf einen
Exit-Code zusammenfallen. Policy, Lease und Promotion bleiben beim kanonischen
Kernel (Masterplan §4, Invarianten 1, 3 und 8).

## Module

| Datei | Zweck | Öffentliche Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/chip_design/__init__.py) | Reexport-Fassade mit 48 Namen in `__all__`. | (nur Reexporte) |
| [__main__.py](../../../daedalus/chip_design/__main__.py) | Drei Zeilen: `python -m daedalus.chip_design` ruft `cli.main`. | — |
| [sources.py](../../../daedalus/chip_design/sources.py) | Absichtlich abhängigkeitsfreie Klassifikation von Hardware-Quelldateien nach Endung: RTL, Header, Constraints, Projektdateien, EDA-Automatisierung. Gibt Daedalus ein stabiles Vokabular, *bevor* irgendein Werkzeug läuft. | `SourceSpec`, `classify_source`, `is_rtl`, `discover_sources` |
| [toolchains.py](../../../daedalus/chip_design/toolchains.py) | Registry der zwölf bekannten Werkzeuge und deterministische argv-Builder. Kein Shell-Aufruf; Tcl-Aufrufe sind Daten, damit Vendor-Syntax nicht in verstreute Subprozess-Strings sickert. Enthält außerdem die Pfadsuche für vertrauenswürdige Vendor-Installationen. | `EdaToolSpec`, `TOOLS`, `get_tool`, `tool_status`, `all_tool_status`, `find_tool_path`, `find_trusted_vendor_tool_path`, `trusted_vendor_tool_paths`, `is_trusted_vendor_tool_path`, `trusted_launcher_sha256`, `interpret_version_probe`, `build_tcl_argv`, `build_rtl_lint_argv` |
| [manifest.py](../../../daedalus/chip_design/manifest.py) | Deterministische, umzugssichere Manifeste für Vivado-Projekte. Behandelt die `.xpr`-Datei als *untrusted input data*: parst das XML, ohne Projektinhalt zu importieren oder auszuführen, und gibt `.xpr`, `.bd` und `.xci` stabile SHA-256-Identitäten. | `VivadoProjectManifest`, `VivadoFileSet`, `VivadoFileReference`, `VivadoArtifactIdentity`, `VivadoDerivedStateRoot`, `VivadoRun`, `VivadoManifestError`, `build_vivado_project_manifest`, `canonical_path`, `canonical_path_identity`, `MANIFEST_SCHEMA` |
| [vivado_tcl.py](../../../daedalus/chip_design/vivado_tcl.py) | Paketeigene Tcl-Identität und argv-Bau. Es gibt genau *eine* ausführbare Tcl-Fläche: die statische Paketressource unter `daedalus/chip_design/tcl/`. Kein projektgeliefertes Skript wird akzeptiert. | `TrustedVivadoTcl`, `trusted_vivado_tcl`, `build_vivado_flow_argv`, `expected_vivado_output_paths`, `VivadoTclContractError` |
| [contracts.py](../../../daedalus/chip_design/contracts.py) | Kanonische Contract- und Receipt-Helfer: baut aus einem Lauf MissionContract, AttemptContract, RuntimeManifest, EvidencePacket und die hardwarespezifische Quittung. | `ChipArtifact`, `ChipRunReceipt`, `build_chip_contracts`, `build_chip_runtime_manifest`, `build_evidence_packet`, `default_dimensions`, `utc_now`, `CHIP_RUN_SCHEMA` |
| [execution_plan.py](../../../daedalus/chip_design/execution_plan.py) | Exakte, digest-gebundene Eingaben für *einen* admittierten Vivado-Prozess: argv, Workspace, Evidenzspeicher, deklarierte Ausgaben, sanitisierte Umgebung, autoritative Eingabe-Identitäten. Reine Daten, keine Autorität. | `EdaExecutionPlan`, `sanitized_eda_environment`, `environment_sha256`, `publication_adapter_sha256`, `trusted_windows_command_interpreter`, `EDA_EXECUTION_PLAN_SCHEMA`, `PUBLICATION_ADAPTER_SCHEMA` |
| [lease_ports.py](../../../daedalus/chip_design/lease_ports.py) | 26 Zeilen: der chipseitige Adapter, den der neutrale Effect-Lease-Aussteller injiziert bekommt. Validiert den exakten Plantyp und reicht neutrale Felder weiter. | `validate_eda_execution_plan` |
| [executor.py](../../../daedalus/chip_design/executor.py) | Der Ausführungskern (2887 Zeilen). Validiert Admission, argv, Workspace-Bindung, Quellidentität und Startfläche, konsumiert die Autorisierung, startet den Prozess bewacht, sammelt Konsolen- und Dateiausgaben begrenzt ein und legt genau eine Terminalquittung ab. | `run_admitted_eda`, `execute_argv`, `recover_retained_execution`, `ExecutionResult`, `ExecutionArtifact`, `RetainedExecutionObservation`, `EdaExecutionError`, `EdaExecutionAdmissionError`, `EdaExecutionStateError`, `EdaExecutionReconciliationRequired` |
| [vivado_reports.py](../../../daedalus/chip_design/vivado_reports.py) | Strikte Parser für nativen Vivado-Reporttext, nur Standardbibliothek. Jeder Parser liefert explizit `parsed`, `missing` oder `unparseable`. | `VivadoReportResult`, `parse_vivado_report`, `parse_vivado_report_bytes`, `parse_vivado_timing_summary`, `parse_vivado_utilization`, `parse_vivado_drc`, `parse_vivado_methodology`, `parse_vivado_route_status`, `parse_vivado_message_counts`, `parse_vivado_message_counts_bytes`, `vivado_artifact_identity` |
| [publication.py](../../../daedalus/chip_design/publication.py) | Die einzige deterministische Projektion von Beobachtungen (Quittung plus CAS-Objekte) auf geparste Reports, Assurance-Dimensionen, Verdikt und Limitationen. Liest ausschließlich aus dem CAS, nie live vom Projekt. | `ChipPublicationDerivation`, `derive_chip_publication`, `parse_vivado_flow_summary_bytes`, `vivado_rule_report_passed`, `vivado_message_report_passed`, `CANONICAL_PUBLICATION_LIMITATIONS` |
| [publication_verifier.py](../../../daedalus/chip_design/publication_verifier.py) | Verifiziert den Publikationsgraphen: rekonstruiert die Verträge und interpretiert den Ausführungsplan, während Lease- und Terminal-Autoritätsfakten read-only aus dem Kernel kommen. Kann weder Lease ausstellen noch Prozess starten. | `verify_chip_eda_publication_graph` |
| [completion_publication.py](../../../daedalus/chip_design/completion_publication.py) | Chip-eigene Terminalartefakt-Retention und Abschlusspublikation. Der Kernel prüft Lease und Terminalbuchführung; dieses Modul besitzt die chipspezifischen CAS-Rollen und Projektionsbytes und wird über stabile Kernel-Fassaden injiziert. | `retain_chip_eda_terminal_artifact`, `record_chip_eda_publication` |
| [cli.py](../../../daedalus/chip_design/cli.py) | Die kanonische Kommandozeile `daedalus-chip` (2548 Zeilen) mit acht Unterbefehlen, der Wiederaufnahme unterbrochener Phasen und der Publikationsfinalisierung. | `build_parser`, `main`, `PLAN_SCHEMA`, `RUN_SCHEMA` |

Nicht-Python im selben Verzeichnis: `daedalus/chip_design/tcl/` enthält die
einzige ausführbare Tcl-Vorlage.

### Werkzeug-Registry

`TOOLS` listet zwölf Einträge (gemessen 2026-09-05), jeder mit Rollen,
Sprachen, Versionsargumenten, Tcl-Backend und einem `proprietary`-Flag:
`tclsh`, `verilator`, `verible`, `iverilog`, `ghdl`, `yosys`, `sby`,
`openroad`, `vivado`, `vitis`, `xsct`, `quartus`. Die vier AMD/Altera-Einträge
sind als proprietär markiert; `vitis` und `xsct` tragen im `notes`-Feld die
ehrliche Einschränkung "Discovery only" — sie werden gefunden, aber dieser
Slice führt sie nicht aus.

### CLI-Oberfläche

`build_parser` definiert acht Unterbefehle:

| Befehl | Wirkung |
| --- | --- |
| `status` | listet registrierte Werkzeuge, ohne sie zu sondieren |
| `scan` | klassifiziert RTL, Constraints, Projekte und EDA-Skripte unter einer Wurzel |
| `classify` | klassifiziert explizit genannte Pfade |
| `inspect` | baut ein read-only Manifest für ein Vivado-Projekt |
| `plan` | baut das vertrauenswürdige argv, ohne auszuführen |
| `run` | die einzige Live-Tür: führt paketeigenes Tcl in einem disjunkten Workspace aus |
| `tcl` | plant einen rohen Tcl-Aufruf; Live-Modus ist zurückgezogen |
| `lint` | plant Verilog-/SystemVerilog-Lint; Live-Modus ist zurückgezogen |

`run` verlangt unter anderem `--workspace-project`, `--authority-root`,
`--source-revision` (40-Hex) und ein stabiles `--attempt-id`, dessen
Wiederverwendung ausdrücklich *inertes* Neustartverhalten erzeugt. Der
Standardwert für `--write-policy` ist eine betreiberbesessene JSON-Datei unter
der Autoritätswurzel.

## Trust-Grenzen / Effekte

### Die eine registrierte Tür

Genau ein Eintrag in der Effekt-Registry
(`daedalus/spine/effect_boundary.py`, gemessen 2026-09-05):

- **ID:** `cli.daedalus_chip`, Ziel `daedalus.chip_design.cli:main`
- **Effekte:** Dateisystem-Schreiben, Prozess-Spawn, Prozess-Kontrolle
- **Guard-Contracts:** `budget.process_guard`, `provider.write_policy`,
  `containment.attempt`
- **Anker:** einer auf die direkte CLI-Delegation an `run_admitted_eda`, einer
  auf die dauerhafte `begin_effect`-Konsumption in
  `daedalus.chip_design.executor:run_admitted_eda`

Der einzige `begin_effect`-Aufruf des ganzen Pakets steht in
`executor.py` (`authorization.begin_effect(execution)`) — der Effekt wird also
nicht selbst begonnen, sondern über eine *vom Aufrufer ausgestellte*
`NonRuntimeEffectAuthorization` konsumiert. Der Executor-Docstring stellt klar:
dieses Modul stellt nie eine Lease aus und erfindet nie eine Policy-Entscheidung.

Die Registry-Notiz ist bemerkenswert ehrlich und sollte hier stehen bleiben:
die Live-Zeile fordert und gewährt *keine* Kernel-Capability für Netz-Egress
oder Secrets — aber ohne OS-Sandbox ist das kein Beweis, dass Vivado keinen
ambienten Host-Netz-, Dateisystem- oder Secret-Zugriff hat. Genau die Sorte
Nicht-Behauptung, die die Review-Regeln dieses Repositories verlangen.

### Fünf Schichten Eingabemisstrauen

**1. Das Projekt ist Datei-Input, kein Code.** `manifest.py` parst die
`.xpr`-XML, ohne Projektinhalt zu importieren oder auszuführen. Pfade, die aus
der deklarierten Projektwurzel ausbrechen, werden *gemeldet, aber nie geöffnet*.
Byte-Obergrenzen sind gesetzt (16 MiB für die Projektdatei, 64 MiB für ein
Block-Design, 100 000 Referenzen). Volatile Attribute und generierte Läufe
werden aus der Identität herausgerechnet, damit ein Manifest umzugssicher ist.

**2. Nur paketeigenes Tcl darf laufen.** `trusted_vivado_tcl()` löst die
Vorlage relativ zum Paketverzeichnis auf, prüft per `commonpath`, dass sie
*innerhalb* des Pakets liegt, lehnt Symlinks und Nicht-Dateien ab, liest sie
unter einer Byte-Obergrenze und vergleicht `st_dev`, `st_ino`, `st_size` und
`st_mtime_ns` *vor und nach* dem Lesen — eine Datei, die sich beim Lesen
ändert, wird abgelehnt. Projekt-/Run-Werte werden nach `-tclargs` als eigene
argv-Elemente angehängt und nie in Tcl-Quelltext interpoliert. Der Docstring
von `cli.py` benennt die verbleibende Lücke offen: deklarierte XDC-Dateien sind
weiterhin ausführbares Vivado-Constraint-Tcl und brauchen Betreibervertrauen.

**3. Vertrauenswürdige Vendor-Pfade.** `toolchains.py` sucht Installationen
über feste Glob-Muster (unter Windows `C:/Xilinx/...`, unter POSIX
`/opt/Xilinx/...` und `/tools/Xilinx/...`), sortiert nach numerischer
Installationsversion und weist link-artige Pfadkomponenten zurück
(`_is_linklike`, `_has_linklike_component`). `trusted_launcher_sha256` bindet
den gefundenen Launcher an einen Digest.

**4. Sanitisierte Umgebung und Plan-Digest.** `sanitized_eda_environment` baut
das Prozess-Environment aus einer Allowlist (`_ENV_ALLOW`), und
`environment_sha256` bindet es an den Plan. `EdaExecutionPlan` verlangt
absolute, kanonische Pfade und stabile SHA-256-Werte für jede autoritative
Eingabe; `publication_adapter_sha256` bindet zusätzlich den Adaptercode selbst
an den Plan.

**5. Trennung von autoritativer Quelle und Workspace.** Das autoritative
Projekt wird nie geschrieben — der CLI-Hilfetext sagt "authoritative source XPR
(never written)". Vivado läuft in einer disjunkten Workspace-Kopie; `_disjoint`
und die Workspace-Bindungsprüfungen im Executor erzwingen das vor und nach der
Ausführung.

### Was passiert, wenn es schiefgeht

Der Executor-Docstring beschreibt ein bewusst *nicht* aufgeräumtes Verhalten:
Wenn ein Prozess gelaufen ist, die Evidenz aber nicht dauerhaft gemacht werden
kann, bleibt die Ausführung im Zustand `STARTED` und wartet auf Rekonziliation
(`EdaExecutionReconciliationRequired`, `recover_retained_execution`).
`KeyboardInterrupt` und `SystemExit` bleiben ebenfalls pendent: der Managed
Context erntet den Prozessbaum ab, aber ein unterbrochener Aufrufer kann nicht
beweisen, wie weit das EDA-Werkzeug gekommen ist. Exakte Wiederholung ist
inert, und ein bekanntes Prozessergebnis bekommt *genau eine* Terminalquittung.

### Kein Exit-Code als Evidenz

`vivado_reports.py` ist die Stelle, an der der Slice den Kernvertrag von
Masterplan §4 Invariante 4 einhält. Jeder Parser gibt explizit `parsed`,
`missing` oder `unparseable` zurück — ein fehlender Abschnitt wird also nie zu
"null Verstöße" flachgedrückt, und ein erfolgreicher Prozess-Exit kann sich
nicht als Timing-, DRC- oder Routing-Evidenz ausgeben. Die Originalbytes des
Reports bleiben das autoritative Auditartefakt; SHA-256 und Bytelänge binden
die normalisierten Metriken daran zurück.

`publication.py` trägt eine Konstante `CANONICAL_PUBLICATION_LIMITATIONS`, die
mit jedem `ChipRunReceipt` mitgeführt wird — die Quittung sagt also selbst, was
sie nicht beweist.

> **Extern:** Vivado ist die proprietäre FPGA-Toolchain von AMD (vormals
> Xilinx); XPR ist ihr XML-Projektformat, XDC das Constraint-Format, und die
> Reports (Timing Summary, Utilization, DRC, Methodology, Route Status) sind
> reine Textausgaben, die dieses Paket ohne Vendor-Bibliothek parst.
> Quelle: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands

## Tests

Gemessen 2026-09-05 nennen 18 Testdateien den Slice:

| Test | Deckt ab |
| --- | --- |
| [tests/test_chip_design.py](../../../tests/test_chip_design.py) | Quellklassifikation und Grundverhalten |
| [tests/test_chip_toolchains.py](../../../tests/test_chip_toolchains.py) | Registry, Pfadsuche, argv-Bau, Versionsinterpretation |
| [tests/test_chip_vivado_contracts.py](../../../tests/test_chip_vivado_contracts.py) | Manifest, Tcl-Identität, argv-Vertrag |
| [tests/test_chip_execution_plan.py](../../../tests/test_chip_execution_plan.py) | `EdaExecutionPlan`, Umgebungs-Sanitisierung, Digests |
| [tests/test_chip_eda_executor.py](../../../tests/test_chip_eda_executor.py) | Admission, Prozessführung, Rekonziliation, Terminalquittung |
| [tests/test_chip_contracts.py](../../../tests/test_chip_contracts.py) | `build_chip_contracts`, `build_evidence_packet`, Dimensionen |
| [tests/test_chip_cli_canonical.py](../../../tests/test_chip_cli_canonical.py) | die CLI-Oberfläche und ihre Refusals |
| [tests/kernel/test_chip_eda_effect_boundary.py](../../../tests/kernel/test_chip_eda_effect_boundary.py) | die Registry-Zeile und ihre beiden Anker |
| [tests/kernel/test_offload_lease_outer_ports.py](../../../tests/kernel/test_offload_lease_outer_ports.py) | `validate_eda_execution_plan` als injizierter Port |
| [tests/kernel/test_chip_repository_head_port_review.py](../../../tests/kernel/test_chip_repository_head_port_review.py) | die HEAD-Revisionsbindung der Live-Tür |
| [tests/gates/test_chip_repository_write_inventory.py](../../../tests/gates/test_chip_repository_write_inventory.py) | das Schreibinventar gegen das Repository |
| [tests/kernel/test_fourfold_evidence_outer_ports.py](../../../tests/kernel/test_fourfold_evidence_outer_ports.py) | die Evidenz-Portgrenze |
| [tests/contracts/test_spine_outer_ports.py](../../../tests/contracts/test_spine_outer_ports.py) | Importrichtung zum Spine |

## Verwandt

- [Spine](spine.md) — Effekt-Registry und `begin_effect`
- [Kernel](kernel.md), [Kernel-Contracts](kernel-contracts.md) — EffectLease, Autorisierung, Terminal-Receipts
- [Kernel-Policy](kernel-policy.md) — `provider.write_policy` und `containment.attempt`
- [Gates-Repository](gates-repository.md) — `RepositoryHeadRevisionReceipt` in der Live-Tür
- [Runtimes-Contracts](runtimes-contracts.md) — derselbe HEAD-Receipt-Typ auf der Runtime-Seite
- [Interfaces CLI](interfaces-cli.md) — die Schwester-Kommandozeile
- [Eval](eval.md) — der Ort, an dem Verdikte zu Evidenz werden
- [Foundation](foundation.md), [Daedalus-Paketwurzel](daedalus-package-root.md)
- [Tool-Vetting](../tool-vetting.md), [Feature-Backlog](../feature-backlog.md), [Wiki-Index](../index.md)

## Ungeklärt

- **Ungeklärt:** Wo die `NonRuntimeEffectAuthorization` für einen Live-Lauf
  tatsächlich ausgestellt wird. `cli.py` importiert `acquire_chip_eda_lease` aus
  `daedalus.kernel.offload_lease`; die vollständige Kette vom Bedienerbefehl bis
  zur Autorisierung habe ich nicht durchgelesen.
- **Ungeklärt:** Der genaue Inhalt der Tcl-Vorlage unter
  `daedalus/chip_design/tcl/`. Ich habe nur ihren Identitäts- und
  Ladepfad gelesen, nicht das Skript selbst.
- **Ungeklärt:** Welche Assurance-Dimensionen `default_dimensions` je Phase
  liefert und wie `_verdict_and_dimensions` daraus ein Verdikt bildet. Der
  Verdikt-Wortschatz ist `passed`, `failed`, `error`, `cancelled`,
  `inconclusive` (aus `contracts.py`), die Abbildungsregel habe ich nicht
  vollständig gelesen.
- **Ungeklärt:** Ob es außer Vivado je einen zweiten Live-Adapter geben soll.
  `TOOLS` kennt zwölf Werkzeuge, aber nur Vivado hat einen Ausführungspfad; für
  `tcl` und `lint` ist der Live-Modus laut CLI-Hilfe ausdrücklich
  zurückgezogen.
- **Ungeklärt:** Ob `daedalus-chip` als Konsolenskript in der Paketmetadaten
  installiert wird oder nur über `python -m daedalus.chip_design` erreichbar
  ist. Der Parser trägt `prog="daedalus-chip"`; die Metadaten habe ich nicht
  geprüft.

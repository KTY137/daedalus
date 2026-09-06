---
title: Runtimes
type: module
status: living
updated: 2026-09-05
covers: daedalus/runtimes
---
# Runtimes

`daedalus/runtimes` ist die Schicht zwischen dem kanonischen Kernel und allem, was
ausserhalb des Python-Prozesses passiert: fremde Modell-Runtimes (Claude, Codex,
Ollama), der Host-Desktop, Dateien im Arbeitsbereich, ein isolierter Browser und
die Fault-Szenarien, mit denen Gate 0 belegt, dass diese Wege fail-closed sind.
Die Schicht *fuehrt aus*; sie entscheidet nicht. Policy, EffectLease, Ledger und
Evidence bleiben im Kernel (Plan §4, Invarianten 1, 3 und 8). Im Ikarus/Ariadne-Bild
sitzt sie unter Ikarus: der Orchestrator waehlt Runtime und Werkzeug, `runtimes`
verwandelt diese Wahl in genau einen belegten Effekt.

Gemessen 2026-09-05: 24 `.py`-Dateien direkt in diesem Verzeichnis, 12321 Zeilen.
Die Unterpakete `provider/`, `providers/`, `execution/`, `admission/` und
`contracts/` sind eigene Seiten — siehe [Runtimes provider](runtimes-provider.md),
[Runtimes providers](runtimes-providers.md), [Runtimes execution](runtimes-execution.md),
[Runtimes admission](runtimes-admission.md) und [Runtimes contracts](runtimes-contracts.md).

Drei Straenge liegen hier nebeneinander:

1. **Runtime-Vertrauen** — Profile, Probe-Identitaet, Conformance-Envelope,
   persistiertes Quarantaene-Ledger (`profiles.py`, `trust.py`, `trust_store.py`).
2. **Provider-Ausfuehrung** — ein Broker, der genau einen Provider-Call hinter
   durablem Effect-Start ausfuehrt, plus Rekonziliation unbekannter Ausgaenge
   (`broker.py`, `recovery.py`).
3. **Computer-Assistenz und Fault-Evidenz** — die Adapter der Amendment-12-Strecke
   (`computer.py` und Geschwister) und die drei Collector-/Attestation-Spalten der
   Gate-0-Fault-Matrix.

## Module

### Runtime-Vertrauen

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/runtimes/__init__.py) | Re-Export der Profil- und Trust-Store-Namen; kein eigener Code. | `REQUIRED_GATE0_RUNTIME_IDS`, `RuntimeProfile`, `RuntimeTrustLedger` |
| [`profiles.py`](../../../daedalus/runtimes/profiles.py) | Strikte, reine Vertraege fuer Runtime-Katalog, Probe-Identitaet und Conformance-Envelope. Laedt den Katalog mit exakter Mitgliedschaftspruefung, baut aus Profil und Manifest eine Probe-Identitaet und bindet Manifest, Identitaet und Receipt zu einem Envelope. | `RUNTIME_PROFILE_SCHEMA`, `RuntimeProfile`, `RuntimeProbeIdentity`, `RuntimeConformanceEnvelope`, `load_runtime_profiles`, `materialize_runtime_manifest`, `build_probe_identity`, `bind_conformance_envelope`, `verify_runtime_envelope` |
| [`trust.py`](../../../daedalus/runtimes/trust.py) | Externer Vertrauensanker: 54 Zeilen, eine Funktion. Ein `authority`-String ist keine Authentisierung, deshalb muss der exakte Envelope-Digest aus einer unabhaengig geschuetzten Quelle kommen. | `verify_production_runtime_envelope` |
| [`trust_store.py`](../../../daedalus/runtimes/trust_store.py) | Persistiertes SQLite-Ledger fuer bereits extern vertraute Live-Envelopes. Jede Zeile wird mit einem Ledger-Integritaetsschluessel per HMAC authentisiert; Rotation und Ablauf sind monoton, Quarantaene ist nicht still ruecknehmbar. | `RuntimeTrustLedger`, `RuntimeTrustRecord`, `RuntimeTrustExpired`, `RuntimeTrustQuarantined`, `RuntimeTrustCorrupt`, `RuntimeTrustBindingMismatch` |

`profiles.py` kennt genau zwei Autoritaeten: `offline-fixture` und `live-runtime`.
`production_eligible` ist nur wahr, wenn beides zutrifft — `live-runtime` **und**
`status` gleich `passed`. Offline-Fixtures beweisen das Daedalus-Protokoll, nie die
Isolation eines echten Providers.

### Provider-Ausfuehrung

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`broker.py`](../../../daedalus/runtimes/broker.py) | Fuehrt genau einen Provider-Call hinter persistierter Runtime- und Effekt-Autoritaet aus. Lease-Grant und Effect-Start sind durabel, bevor der Provider laeuft; exakter Replay ist inert; Erfolg, Fehler, Cancellation und Trust-Verlust bekommen je einen terminalen Receipt. | `run_runtime_provider`, `RuntimeInvocationResult`, `RuntimeProviderBrokerError`, `RuntimeProviderBindingMismatch`, `RuntimeProviderTrustFenceError`, `RuntimeProviderReconciliationRequired`, `RuntimeProviderStateError` |
| [`recovery.py`](../../../daedalus/runtimes/recovery.py) | Rekonziliation fuer Provider-Effekte mit unbekanntem Ausgang. Ruft nie einen Provider auf und akzeptiert nur eine bereits gestartete, noch offene Ausfuehrung; Provider-Identitaet und akzeptierte Observation-Keys stammen aus dem persistierten Material, nicht vom Aufrufer. | `reconcile_runtime_provider_unknown`, `RuntimeProviderRecoveryError`, `RuntimeProviderRecoveryBindingError` |

### Computer-Assistenz (Plan §7.2, Amendment 12)

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`computer.py`](../../../daedalus/runtimes/computer.py) | Der einzige registrierte Computer-Effekt-Einstieg. Validiert Argumente gegen `TOOL_SPECS`, laedt die Policy aus dem Kernel-Control-Root, nimmt jede Operation unmittelbar vor dem privaten Adapter erneut an, haelt einen Datei-Lock, holt ein Lease, startet den Effekt durabel und schreibt Ergebnis oder Fehlerprotokoll als kanonisches Artefakt. | `ComputerService`, `TOOL_SPECS`, `ENTRYPOINT`, `computer_status`, `setup_computer` |
| [`computer_files.py`](../../../daedalus/runtimes/computer_files.py) | Handle-verankerter Dateiadapter, 1266 Zeilen und damit die groesste Datei des Verzeichnisses. Kein Pfadname wird nach der Pruefung erneut geoeffnet: jede Komponente unterhalb der Workspace-Wurzel wird relativ zum Handle ihres bereits geprueften Elternteils geoeffnet, Reparse-Points werden bei jedem Schritt abgelehnt. Zwei Backends, POSIX und NT (`NtCreateFile` mit `RootDirectory`). | `WorkspaceFiles`, `ComputerFileEffectUncertain`, `ComputerFileInterrupted`, `FILE_LIST_LIMIT` |
| [`computer_desktop.py`](../../../daedalus/runtimes/computer_desktop.py) | Privater Windows-Desktop-Adapter. Bilder bleiben im Speicher, Eingabe-Token sind einmalig und werden vor einem Effekt invalidiert — auch dann, wenn das Ergebnis unbekannt wird. Ausdruecklich **keine** OS-Sandbox fuer das Verhalten der erlaubten Anwendung. | `DesktopAdapter` mit `capture_png` und `require_fresh_observation` |
| [`computer_browser.py`](../../../daedalus/runtimes/computer_browser.py) | Wegwerf-Browser ohne Profil, Cookies oder Client-Secrets. JavaScript ist deaktiviert, Formular-Submit, Downloads, WebSockets und Nicht-Lese-HTTP-Methoden haben keine Autoritaet. Seiteninhalt gilt als untrusted. | `BrowserAdapter` |
| [`computer_vision.py`](../../../daedalus/runtimes/computer_vision.py) | Begrenzte lokale OpenCV-Beobachtungen ueber uebergebene Bytes. Oeffnet keine Datei, erfasst keinen Bildschirm, stellt keine Netzanfrage. Koordinaten behalten ihren Rahmen. | `OpenCVVision`, `ImageCoordinateFrame`, `VisionLimits`, `VisionError`, `LocalOCRAdapter` |
| [`computer_ocr.py`](../../../daedalus/runtimes/computer_ocr.py) | Lokales Windows-OCR ueber uebergebene Pixel mit installierten Sprachpaketen. Windows OCR liefert keine Konfidenzwerte; das Fehlen wird explizit in der Beobachtung vermerkt statt geschaetzt. | `WindowsOCR` |

Ein Treffer der Bildvergleichs- oder OCR-Funktionen ist eine **Beobachtung**, kein
Nachweis, dass die Aufgabe erledigt ist — das steht so im Modul-Docstring von
`computer_vision.py` und entspricht Plan §7.2.

### Fault-Matrix: Katalog, Collectoren, Attestation

Der Katalog stellt die Fragen, die Gate 0 beantwortet haben will; er behauptet
nicht, dass sie ausgefuehrt wurden. Gemessen 2026-09-05 enthaelt
`RUNTIME_FAULT_CATALOG` (Katalog-Id `gate0-runtime-faults-v1`) **24 Szenarien**,
verteilt auf drei Autoritaeten (13 `deterministic-fixture`, 9 `linux-host`,
2 `live-runtime`) und sieben Grenzen (`runtime-trust` 9, `broker` 5,
`effect-ledger` 4, `provider-process` 2, `sandbox` 2, `egress` 1, `secrets` 1).

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`fault_matrix.py`](../../../daedalus/runtimes/fault_matrix.py) | Kanonische Vertraege: Szenario, Katalog, Beobachtung, Matrix, Verifikation. Eine bestandene Beobachtung muss den tatsaechlich erreichten terminalen Ausgang mitliefern, damit "der Prozess endete mit 0" und "das System erreichte den geforderten Zustand" nicht dasselbe Bit werden. | `RUNTIME_FAULT_CATALOG`, `RuntimeFaultScenario`, `RuntimeFaultCatalog`, `RuntimeFaultObservation`, `RuntimeFaultMatrix`, `RuntimeFaultVerification`, `build_runtime_fault_matrix`, `verify_runtime_fault_matrix`, `RECONCILIATION_DEADLINE_SECONDS` |
| [`faults.py`](../../../daedalus/runtimes/faults.py) | 29-Zeilen-Kompatibilitaetsmodul: reiner Re-Export aus `fault_matrix.py` fuer bestehende Importpfade waehrend der Strangler-Migration. | dieselben neun Namen wie oben |
| [`fixture_fault_collector.py`](../../../daedalus/runtimes/fixture_fault_collector.py) | Spalte `deterministic-fixture`: fuehrt die im Katalog benannten pytest-Knoten aus und leitet den Ausgang aus dem JUnit-Report ab, nicht aus dem Katalog — sonst verglich der Katalog sich mit sich selbst. | `run_fixture_fault`, `run_fixture_fault_catalog`, `FixtureFaultEvidence`, `FixtureFaultRun`, `FixtureFaultResult`, `parse_pytest_junit`, `derive_terminal_outcome`, `report_runtime_fault_outcome`, `retain_fixture_fault_run` |
| [`host_fault_runner.py`](../../../daedalus/runtimes/host_fault_runner.py) | Spalte `linux-host`: Collector-Naht zwischen einem konkreten Host-Executor und dem Katalog. Fehlende Executoren werden explizit `blocked`, Ausnahmen und Ausgangs-Abweichungen `failed` — nie stillschweigend zu einem Pass. | `run_linux_host_fault`, `run_linux_host_fault_catalog`, `HostFaultResult`, `HostFaultFact`, `LinuxHostFaultEvidence`, `LinuxHostFaultRun`, `LinuxHostExecutorBinding` |
| [`container_fault_driver.py`](../../../daedalus/runtimes/container_fault_driver.py) | Faehrt die neun `linux-host`-Szenarien in einem Docker-Linux-Container. Ruft Docker nicht selbst auf, sondern geht durch die kanonische Sandbox, damit die bounded-effect-Policy gilt: Read-only-Root, kein Netz, gedroppte Capabilities, Nicht-Root-User, gepinntes Image, ein schreibbarer Workspace. | `ContainerFaultDriver`, `publish_container_faults`, `docker_cli_available`, `containment_boundary_decision`, `ContainerFaultScenarioDrift`, `ContainerFaultEvidenceMalformed`, `DEFAULT_IMAGE` |
| [`live_fault_collector.py`](../../../daedalus/runtimes/live_fault_collector.py) | Spalte `live-runtime` fuer die zwei Lease-Verweigerungszeilen. | `run_live_fault`, `run_live_fault_catalog`, `LiveProbeResult`, `LiveFaultEvidence`, `LiveFaultRun`, `LiveProbeExecutorBinding`, `retain_live_fault_run` |
| [`live_probe_drivers.py`](../../../daedalus/runtimes/live_probe_drivers.py) | Die zwei Live-Proben selbst: abgelaufene Live-Evidenz und Provider-Binary-Drift nach Conformance. Beide erwarten `refused-before-start`, und genau deshalb pruefen sie zuerst, dass die Kontrollbedingung ueberhaupt akzeptiert worden waere — eine Verweigerung auf Muell beweist nichts. | `probe_envelope_expiry`, `probe_binary_drift`, `build_live_probe_executors`, `LiveEnvelopeBundle`, `load_live_envelope_bundle`, `drift_binary_copy`, `measure_file_sha256`, `EXPIRY_LOCATOR`, `BINARY_DRIFT_LOCATOR`, `LiveProbeUnavailable` |
| [`fault_attestations.py`](../../../daedalus/runtimes/fault_attestations.py) | Authentisiert Beobachtungen, bevor sie in eine Trust-Menge kommen. Eine Attestation bindet Beobachtung, Katalog, Revision, Autoritaet, Issuer- und Key-Identitaet, Nonce und ein begrenztes Gueltigkeitsfenster; HMAC-Schluessel kommen vom Aufrufer, nie aus Repository-Konfiguration. | `RuntimeFaultAttestation`, `issue_runtime_fault_attestation`, `verify_runtime_fault_attestation`, `verify_attested_runtime_fault_matrix`, `AttestedRuntimeFaultVerification`, `RuntimeFaultAttestationReplay`, `RuntimeFaultAttestationExpired`, `RuntimeFaultAttestationSignatureError` |
| [`fault_attestation_issuer.py`](../../../daedalus/runtimes/fault_attestation_issuer.py) | Issuer der Spalte `linux-host`. Getrennt vom Treiber: wer Evidenz erzeugen kann, kann noch kein Vertrauen erzeugen. | `LinuxHostFaultAttestationIssuer`, `LinuxHostFaultAttestationBundle`, `issue_run_directory`, `build_matrix_from_run_directory`, `load_linux_host_fault_run`, `retained_scenario_ids`, `key_fingerprint`, `FaultAttestationRefusal` |
| [`fixture_fault_attestation_issuer.py`](../../../daedalus/runtimes/fixture_fault_attestation_issuer.py) | Issuer der Spalte `deterministic-fixture`, mit eigener Autoritaetskonstante und eigenem Schluessel. | `FixtureFaultAttestationIssuer`, `FixtureFaultAttestationBundle`, `issue_fixture_run_directory`, `build_matrix_from_fixture_run_directory`, `load_fixture_fault_run` |
| [`live_fault_attestation_issuer.py`](../../../daedalus/runtimes/live_fault_attestation_issuer.py) | Issuer der Spalte `live-runtime`; kennt zusaetzlich `production_key_material`, weil eine Gate-taugliche Live-Spalte Produktionsverwahrung des Schluessels verlangt — sie zu deklarieren erzeugt sie nicht. | `LiveFaultAttestationIssuer`, `LiveFaultAttestationBundle`, `issue_live_run_directory`, `build_matrix_from_live_run_directory`, `load_live_fault_run` |
| [`whole_fault_matrix.py`](../../../daedalus/runtimes/whole_fault_matrix.py) | Setzt die drei Spalten zu **einer** Matrix zusammen und gibt dem Ergebnis eine inhaltsadressierte Identitaet, damit ein Gate-Report sie binden statt neu ableiten kann. Praegt kein eigenes Vertrauen: Beobachtungen kommen aus den Spalten-Loadern, Vertrauen aus deren Attestation-Bundles. | `WholeRuntimeFaultMatrixVerdict`, `WholeMatrixColumn`, `verify_whole_runtime_fault_matrix`, `load_whole_matrix_verdict`, `discover_whole_matrix_verdicts`, `FaultAttestationBundle`, `load_fault_attestation_bundle`, `WHOLE_MATRIX_ID`, `VERDICT_FILENAME`, `PRODUCTION_KEY_CLASS`, `catalog_authorities` |

Die drei Issuer sind absichtlich **nicht** ein Issuer mit Parameter: jeder pinnt
seine eigene Autoritaetskonstante und weist die Zeilen der anderen namentlich ab.
Die Ablehnung wird zweimal durchgesetzt — bei der Ausstellung und noch einmal in
`verify_attested_runtime_fault_matrix`, dem eine `issuer_authorities`-Policy
mitgegeben wird.

## Trust-Grenzen / Effekte

Gemessen 2026-09-05 gegen `REGISTRY_BY_ID` (127 Zeilen gesamt) sind aus diesem
Verzeichnis sechs Eintraege registriert:

| Registry-Id | Ziel | Wiring | Effekte | Guard-Contracts |
| --- | --- | --- | --- | --- |
| `python.ikarus_computer` | `ComputerService.execute` | `CENTRAL` | `computer_use` | `computer.tool_policy` |
| `python.ikarus_computer_setup` | `setup_computer` | `CENTRAL` | `filesystem_write`, `process_spawn` | `budget.process_guard`, `computer.configuration` |
| `runtimes.container_fault_driver` | `container_fault_driver` Hauptfunktion | `CENTRAL` | `filesystem_write`, `process_spawn`, `process_control` | `containment.attempt`, `budget.process_guard` |
| `runtimes.fixture_fault_collector` | `fixture_fault_collector` Hauptfunktion | `CENTRAL` | `filesystem_write`, `process_spawn`, `process_control` | `budget.process_guard` |
| `runtimes.live_fault_collector` | `live_fault_collector` Hauptfunktion | `CENTRAL` | `filesystem_write` | `budget.process_guard` |
| `runtimes.fault_attestation_issuer` | `fault_attestation_issuer` Hauptfunktion | `INVENTORY_ONLY` | `filesystem_write`, `secrets` | keine |

Wo `begin_effect` steht (gemessen 2026-09-05): `broker.py:656` (ueber
`authorization.begin_effect`), `computer.py:267` und `computer.py:474`,
`container_fault_driver.py:621`, `fixture_fault_collector.py:1016`,
`live_fault_collector.py:693`.

Weitere Beobachtungen zur Grenze:

- **`ComputerService.execute` ist der einzige Schreiber der Computer-Strecke.**
  Reihenfolge im Code: Argumentvalidierung, Entkopplung von Aufrufer-Containern
  per JSON-Roundtrip, Cancellation-Pruefung, Operations-Admission, Release-Fence,
  exklusiver Datei-Lock, Lease-Erwerb, Pruefung der Evidence-Records,
  `begin_effect`, dann erst der private Adapter. Ergebnisse laufen vor CAS und vor
  dem Planner durch die Secret-Floor-Regel.
- **Der Broker laesst keinen vom Aufrufer gelieferten Callable ueber die
  Produktionsnaht.** Duck-Typing oder Subklassen der Autorisierung sind
  ausdruecklich keine Kompatibilitaetsnaht, weil sie Grant, Start, Verifikation
  oder Terminal ueberschreiben koennten.
- **`runtimes.fault_attestation_issuer` steht bewusst auf `INVENTORY_ONLY`.**
  Die Registry-Notiz nennt den Grund: sein dominanter Effekt ist `secrets`, und
  `GUARD_CONTRACT_IMPLEMENTED` enthaelt keinen Secrets- oder Key-Custody-Contract.
  Die Zeile zentral zu stempeln wuerde Deckung behaupten, die es nicht gibt.
- **Zwei Geschwister-Issuer sind ueberhaupt nicht registriert.**
  Die Hauptfunktionen von `fixture_fault_attestation_issuer.py` und
  `live_fault_attestation_issuer.py` schreiben atomar nach ihrem Ausgabepfad und
  lesen ihren Signierschluessel aus der Umgebung, tauchen aber (gemessen
  2026-09-05) in `REGISTRY_BY_ID` nicht auf. Siehe "Ungeklaert".
- **Read-only in diesem Verzeichnis:** `profiles.py`, `trust.py`, `fault_matrix.py`,
  `faults.py`, `fault_attestations.py`, `whole_fault_matrix.py`,
  `computer_vision.py` und `computer_ocr.py` fassen keine Effekt-Grenze an.
  `trust_store.py` schreibt SQLite, aber nur unter dem uebergebenen Pfad und mit
  Integritaets-HMAC pro Zeile.
- Kill-Switch und Control-Root kommen aus [Spine](spine.md); `runtimes` konsumiert
  sie, definiert sie nicht.

## Tests

Gemessen 2026-09-05 per gezielter Suche nach Importpfaden der Form
`daedalus.runtimes.<modul>` unter `tests/`. Auswahl der direkt zustaendigen Dateien:

- Broker und Terminal-Fence: [test_runtime_provider_broker.py](../../../tests/runtimes/test_runtime_provider_broker.py), [test_runtime_terminal_fence.py](../../../tests/runtimes/test_runtime_terminal_fence.py), [test_runtime_terminal_fence_release.py](../../../tests/runtimes/test_runtime_terminal_fence_release.py), [test_runtime_provider_exact_authority_boundary.py](../../../tests/runtimes/test_runtime_provider_exact_authority_boundary.py), [test_sealed_broker_wheel_reachability.py](../../../tests/runtimes/test_sealed_broker_wheel_reachability.py)
- Recovery: [test_runtime_provider_recovery.py](../../../tests/runtimes/test_runtime_provider_recovery.py), [test_runtime_provider_post_invoke_unknown.py](../../../tests/runtimes/test_runtime_provider_post_invoke_unknown.py)
- Trust: [test_runtime_trust_store.py](../../../tests/runtimes/test_runtime_trust_store.py), [test_runtime_live_trust_anchor.py](../../../tests/runtimes/test_runtime_live_trust_anchor.py), [test_runtime_conformance_profiles.py](../../../tests/runtimes/test_runtime_conformance_profiles.py), [test_runtime_profile_adversarial.py](../../../tests/runtimes/test_runtime_profile_adversarial.py), [test_trust_flags_agree.py](../../../tests/runtimes/test_trust_flags_agree.py)
- Fault-Matrix und Spalten: [test_runtime_fault_catalog.py](../../../tests/runtimes/test_runtime_fault_catalog.py), [test_runtime_fault_attestations.py](../../../tests/runtimes/test_runtime_fault_attestations.py), [test_runtime_fault_attestation_hardening.py](../../../tests/runtimes/test_runtime_fault_attestation_hardening.py), [test_runtime_fault_attestation_receipt.py](../../../tests/runtimes/test_runtime_fault_attestation_receipt.py), [test_fixture_fault_collector.py](../../../tests/runtimes/test_fixture_fault_collector.py), [test_linux_host_fault_runner.py](../../../tests/runtimes/test_linux_host_fault_runner.py), [test_live_fault_collector.py](../../../tests/runtimes/test_live_fault_collector.py), [test_live_probe_drivers.py](../../../tests/runtimes/test_live_probe_drivers.py), [test_container_fault_driver.py](../../../tests/runtimes/test_container_fault_driver.py), [test_container_fault_driver_integration.py](../../../tests/runtimes/test_container_fault_driver_integration.py), [test_whole_fault_matrix.py](../../../tests/runtimes/test_whole_fault_matrix.py), [test_live_column_whole_matrix.py](../../../tests/runtimes/test_live_column_whole_matrix.py), [test_fault_collector_effect_starts.py](../../../tests/runtimes/test_fault_collector_effect_starts.py), [test_reconciliation_deadline.py](../../../tests/runtimes/test_reconciliation_deadline.py)
- Issuer: [test_linux_host_fault_attestation_issuer.py](../../../tests/runtimes/test_linux_host_fault_attestation_issuer.py), [test_fixture_fault_attestation_issuer.py](../../../tests/runtimes/test_fixture_fault_attestation_issuer.py), [test_live_fault_attestation_issuer.py](../../../tests/runtimes/test_live_fault_attestation_issuer.py)
- Computer-Adapter: [test_computer_service.py](../../../tests/runtimes/test_computer_service.py), [test_computer_service_files.py](../../../tests/runtimes/test_computer_service_files.py), [test_computer_service_effect_state.py](../../../tests/runtimes/test_computer_service_effect_state.py), [test_computer_files.py](../../../tests/runtimes/test_computer_files.py), [test_computer_desktop.py](../../../tests/runtimes/test_computer_desktop.py), [test_computer_browser.py](../../../tests/runtimes/test_computer_browser.py), [test_computer_vision.py](../../../tests/runtimes/test_computer_vision.py), [test_computer_vision_paths.py](../../../tests/runtimes/test_computer_vision_paths.py), [test_computer_ocr.py](../../../tests/runtimes/test_computer_ocr.py)
- Host-Executor-Fixtures liegen unter `tests/fixtures/`, z. B. [linux_process_fault_executor.py](../../../tests/fixtures/linux_process_fault_executor.py), [container_oom_fault_executor.py](../../../tests/fixtures/container_oom_fault_executor.py), [unauthorized_egress_fault_executor.py](../../../tests/fixtures/unauthorized_egress_fault_executor.py), [undeclared_secret_fault_executor.py](../../../tests/fixtures/undeclared_secret_fault_executor.py)
- Kernelseitige Gegenproben zum Trust-Port: [test_runtime_trust_port_boundary.py](../../../tests/kernel/test_runtime_trust_port_boundary.py), [test_runtime_effect_admission.py](../../../tests/kernel/test_runtime_effect_admission.py)

## Verwandt

- [Gates](gates.md) — konsumiert das Gesamt-Matrix-Verdikt und die Conformance-Receipts
- [Runtimes provider](runtimes-provider.md), [Runtimes execution](runtimes-execution.md), [Runtimes admission](runtimes-admission.md), [Runtimes contracts](runtimes-contracts.md), [Runtimes providers](runtimes-providers.md) — die Unterpakete
- [Adapters](adapters.md) — der zweite Prozess-Spawn-Weg
- [Kernel](kernel.md), [Kernel policy](kernel-policy.md), [Spine](spine.md) — Lease, Policy, Effekt-Registry
- [Interfaces bridge](interfaces-bridge.md) — der andere zentral verdrahtete Dateipfad
- [Observe](observe.md) — Beobachtung als Sample, dieselbe Disziplin eine Ebene tiefer
- [Tool vetting](../tool-vetting.md), [Wiki-Index](../index.md)

## Ungeklaert

- **Warum sind die Hauptfunktionen von `fixture_fault_attestation_issuer.py` und
  `live_fault_attestation_issuer.py` nicht in `REGISTRY_BY_ID`?** Beide schreiben
  Dateien und lesen einen Schluessel aus der Umgebung, waehrend das
  Linux-Host-Geschwister als `INVENTORY_ONLY` gefuehrt wird. Aus dem Code allein
  ist nicht ablesbar, ob das eine bewusste Auslassung oder eine Luecke ist.
- Welche Live-Envelope-Bundles produktiv existieren und ob eine Schluesselklasse
  irgendwo auf `production` steht, ist aus dem Baum nicht ablesbar — die Bundles
  sind Laufzeitartefakte.
- `computer_desktop.py` nennt Live-Vordergrund-Eingabe als noch nicht gemessen;
  welche Anwendungen tatsaechlich verifiziert sind, steht in der Policy, nicht im
  Adapter.
- Ob die Docker-CLI auf der Owner-Maschine verfuegbar ist, ist eine Umgebungsfrage;
  Plan-Revision 8 fuehrt Docker-Host-Beschaffung als offene Owner-Position.

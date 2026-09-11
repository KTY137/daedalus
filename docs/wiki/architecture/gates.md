---
title: Gates
type: module
status: living
updated: 2026-09-05
covers: daedalus/gates
---
# Gates

`daedalus/gates` ist die maschinenlesbare Berichterstattung ueber die
Lieferungs-Gates aus Plan §11. Der Paket-Docstring sagt die Rolle in zwei
Saetzen: das Paket ist eine *Projektion* ueber kanonische Vertraege und
Registries und darf nie eine zweite Policy- oder Workflow-Autoritaet werden.
Praktisch heisst das: hier wird gemessen, gebunden, verifiziert und quittiert —
aber kein Fehler injiziert, kein Provider ausgefuehrt, kein Repository mutiert,
kein Lease vergeben, kein Kandidat promotet und kein Gate geschlossen. Diese
Selbstbeschraenkung steht wortgleich in `fault_matrix.py`, `evidence.py`,
`release.py`, `python_target_structure.py` und den beiden Inventar-Scannern.

Gemessen 2026-09-05: 19 `.py`-Dateien direkt in diesem Verzeichnis, 8060 Zeilen.
Das Unterpaket `repository/` ist eine eigene Seite —
[Gates repository](gates-repository.md).

## Module

### Report

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/gates/__init__.py) | Re-Export der oeffentlichen Namen; installiert ausserdem die strikten Wire-Parser aus `trust_bundle_io` als Kompatibilitaets-Attribute auf `trust_bundle` (Strangler). | `build_gate0_report`, `GateReport`, `GateEvidenceIndex`, `EvidenceTrustBundle`, `Gate0ReleaseReceipt`, … |
| [`__main__.py`](../../../daedalus/gates/__main__.py) | `python -m daedalus.gates report --gate 0 --source-revision <sha>`; gibt den Bericht als kanonisches JSON aus. Ohne `--conformance-receipts` bleibt der fail-closed Blocker "unbound" stehen. | `main` |
| [`report.py`](../../../daedalus/gates/report.py) | Der deterministische Gate-0-Bericht (`daedalus-gate-report/2`, Legacy `/1`) plus monotoner Vergleich. Liest Conformance und Registry aus [Spine](spine.md) und bindet Fault-Matrix und Runtime-Receipts an. | `GateReport`, `build_gate0_report`, `load_gate_report`, `assert_monotonic` |
| [`report_v3.py`](../../../daedalus/gates/report_v3.py) | Additive Strangler-Generation, die das kanonische Repository-Write-Inventar verbindlich mitfuehrt. Wire-Schema inzwischen `daedalus-gate-report/5`. | `GateReportV3`, `GateReportV3Error`, `build_gate0_report_v3`, `load_gate_report_v3`, `assert_monotonic_v3` |

`GateReport` ist eingefroren und prueft in `__post_init__` hart: `gate` muss
exakt der `int` 0 sein, `source_revision` ein 40-stelliger Kleinbuchstaben-Commit,
`registry_sha256` ein SHA-256, `security_boundary_claimed` und
`owner_approval_enforced` echte Booleans. Die Blocker-Felder sind Tupel:
`unregistered_effectful_entrypoints`, `unguarded_entrypoints`,
`inventory_only_production_entrypoints`, `missing_guard_contracts`,
`runtime_conformance_failures`, `fault_injection_failures`,
`primary_checkout_mutations`, `event_store_writer_failures`, `diagnostics`.

Der Klassenname von `GateReportV3` nennt die Strangler-Generation, `_SCHEMA` die
Wire-Form — der Docstring begruendet die Trennung ausdruecklich: waere `/3`
beibehalten worden, haette eine Schema-ID zwei Formen benannt. Der Sprung auf
`/5` hat den entscheidenden Messfehler behoben: bis dahin war
`repository_write_failures` jede syntaktisch gefundene Callsite, sodass eine
registrierte Tuer, ein Guard-Contract und ein Lease-Receipt nichts abzogen und
ein ungeleaster Produktionsschreiber nicht von einer noch nicht angesehenen
Callsite unterscheidbar war. Der Bericht erklaert jetzt drei Dinge getrennt:
`repository_write_surfaces_total` (die rohe Zahl, woertlich erhalten),
`repository_write_surface_verdicts` (ein Verdikt pro Flaeche als sortierte
`<verdict>:<count>`-Zeilen, deren Summe die Gesamtzahl ergibt) und
`repository_write_classification_schema` (welche Kette diese Verdikte erzeugte,
aus der Projektion *gelesen*, nicht behauptet).

### Evidenz an genau einem Kopf

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`evidence.py`](../../../daedalus/gates/evidence.py) | Strikter, additiver Evidenz-Container: bindet CI-Laeufe, Artefakte, Live-Runtime-Envelopes, Fault-Matrizen, Reviews und eine extern verifizierte Owner-Entscheidung an genau einen Commit und Tree. Jeder Eintrag ist content-adressiert; `mechanical_blockers` wird abgeleitet, es gibt kein manuelles `closed`/`passed`. | `GateEvidenceIndex`, `WorkflowRunEvidence`, `ArtifactEvidence`, `RuntimeEnvelopeEvidence`, `FaultMatrixEvidence`, `ReviewEvidence`, `OwnerDecisionEvidence` |
| [`evidence_io.py`](../../../daedalus/gates/evidence_io.py) | Die unterstuetzte Datei-/Wire-Grenze. Lehnt doppelte JSON-Schluessel, als Array verpackte Strings, defekte verschachtelte Records und nicht-kanonische Wires ab, die sonst auf dieselbe Evidenz-Identitaet normalisieren wuerden. | `parse_gate_evidence_index`, `load_gate_evidence_index` |
| [`evidence_verifier.py`](../../../daedalus/gates/evidence_verifier.py) | Strikte Verifikation gegen den Live-Zustand. Der Docstring nennt den Kern: kanonische Daten sind nicht dadurch authentisiert, dass sie parsen. Verlangt unabhaengig beschaffte Trust-Mengen; leere Trust-Mengen fallen geschlossen aus. | `strict_mechanical_blockers`, `assert_strict_exact_head`, `evidence_requirements_sha256` |

`ReviewEvidence` fuehrt eine Assurance-Stufe aus `{"human",
"deterministic-tool", "model-opinion"}` — die Modellmeinung ist damit als
schwaechste Klasse benannt statt sie mit einem Werkzeugbefund zu vermischen
(Plan §4, Invariante 4). `RuntimeEnvelopeEvidence` kennt genau zwei
Autoritaeten, `offline-fixture` und `live-runtime`, dieselbe Unterscheidung wie in
[Runtimes](runtimes.md).

### Fault-Matrix

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`fault_matrix.py`](../../../daedalus/gates/fault_matrix.py) | Revisions-gebundene, ausdruecklich nicht ausfuehrende Vertraege fuer Gate-0-Fault-Evidenz: Szenario-Spezifikation, Manifest, Szenario-Receipt, Verifikations-Receipt. | `FaultScenarioSpec`, `FaultMatrixManifest`, `FaultScenarioReceipt`, `FaultMatrixVerificationReceipt`, `verify_fault_matrix_run`, `fault_injection_fingerprint`, `FaultMatrixContractError`, `FaultMatrixShapeError`, `FaultMatrixBindingError`, `FINGERPRINT_ALGORITHM`, `EVIDENCE_PROJECTION_ORIGIN` |
| [`fault_matrix_binding.py`](../../../daedalus/gates/fault_matrix_binding.py) | Die Gate-Policy ueber das Gesamt-Verdikt aus `daedalus.runtimes.whole_fault_matrix`: welche Blocker den Gate-0-Ausgang blockieren, welche eine Owner-Scoping-Entscheidung bereits erklaert hat, und getrennt davon, ob die Evidenz ueberhaupt einen Sicherheitsgrenzen-Anspruch tragen darf. | `bind_fault_matrix_evidence`, `fault_matrix_evidence_from_verdict`, `FaultMatrixBinding` |

Drei Eigenschaften nennt `fault_matrix_binding.py` ausdruecklich als
beabsichtigt:

1. **Fail-closed** — ein fehlendes, mehrdeutiges, unlesbares oder in sich
   widerspruechliches Bundle erzeugt einen benannten Blocker. Es gibt keinen Weg
   von "keine Evidenz" zu "kein Befund".
2. **Eine Erklaerung braucht Receipt *und* Dokument** — eine `fault.blocked`-Zeile
   hoert nur dann auf zu blockieren, wenn der Receipt des Laufs eine
   Scoping-Entscheidung nennt, diese im Repository existiert, der Receipt per
   Matrix-Digest an *dieses* Verdikt gebunden ist und seine Szenario-Liste exakt
   die blockierte Menge ist.
3. **Binden ist nicht Schliessen** — ein gebundenes Verdikt macht die Matrix
   ehrlich und offen; nur ein geschlossenes Verdikt unter produktiver
   Schluesselverwahrung an der Revision des Berichts kann
   `security_boundary_claimed` tragen. Ein Lauf mit Entwicklungsschluessel bleibt
   als solcher markiert und macht einen Anspruchsversuch selbst zum Blocker.

### Authentisierung und Freigabe

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`trust_bundle.py`](../../../daedalus/gates/trust_bundle.py) | Ein separat kontrollierter Kollektor signiert das exakt beobachtete Trust-Material, inklusive der Workflow-Bytes des Repositories — ohne den Repository-Kandidaten zu seiner eigenen Trust-Autoritaet zu machen. | `EvidenceTrustBundle`, `WorkflowDefinitionAnchor`, `issue_evidence_trust_bundle`, `verify_evidence_trust_bundle`, `assert_strict_exact_head_with_bundle`, `workflow_definition_sha256`, `EvidenceTrustBundleError`/`…SignatureError`/`…BindingError` |
| [`trust_bundle_io.py`](../../../daedalus/gates/trust_bundle_io.py) | Die strikte Grenze fuer unvertrauten Draht: die eingereichte Repraesentation wird rekonstruiert und vollstaendig gegen die kanonische `to_dict()`-Form verglichen, bevor sie zur Signaturpruefung darf. | `parse_evidence_trust_bundle`, `load_evidence_trust_bundle` |
| [`release.py`](../../../daedalus/gates/release.py) | Fail-closed Freigabe-Assemblierung ueber zurueckbehaltene Exact-Head-Evidenz. Verifiziert einen abgeleiteten `GateReport` gegen ein authentisiertes Trust-Bundle und stellt einen separat signierten mechanischen Receipt fuer genau die beobachteten Eingaben aus. | `Gate0ReleaseReceipt`, `issue_gate0_release_receipt`, `verify_gate0_release_receipt`, `load_strict_gate_report`, `strict_gate_report_sha256`, `validate_strict_gate_report_payload`, `Gate0ReleaseBlocked`, `Gate0ReleaseBindingError`, `Gate0ReleaseSignatureError` |
| [`guard_implementation_manifest.py`](../../../daedalus/gates/guard_implementation_manifest.py) | Authentisiert ein kurzlebiges, revisions- und klassifikationsgebundenes Manifest, das Guard-Contract-Namen auf exakte Python-Ziele und Quell-Digests abbildet. Inspiziert keine Quelldateien und spielt keine Guard-Semantik nach. | `GuardImplementationManifest`, `GuardImplementationRecord`, `GuardImplementationManifestReport`, `issue_guard_implementation_manifest`, `parse_guard_implementation_manifest`, `verify_guard_implementation_manifest` |

`release.py` sagt in der ersten Zeile, was es *nicht* tut: kein Gate schliessen,
keine `OwnerApproval` erzeugen, keinen Kandidaten promoten, keine Evidenz
erfinden. Das ist die Plan-§4-Invariante 5 (versiegelte Promotion) auf
Modulebene.

### Baseline und Monotonie

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`baseline.py`](../../../daedalus/gates/baseline.py) | Deterministische, manipulationssichtbare Projektion *eines* kanonischen GateReport-v2 plus Monotonie-Receipt. Nicht selbst-authentisierend: die Vergleichs-API verlangt den erwarteten Baseline-Digest explizit. | `GateBaseline`, `GateMonotonicityReceipt`, `create_gate0_baseline`, `assess_gate0_monotonicity`, `load_gate0_baseline`, `load_gate0_monotonicity_receipt`, `load_current_gate_report`, `GateBaselineError`, `GateBaselineBindingError` |
| [`baseline_verifier.py`](../../../daedalus/gates/baseline_verifier.py) | Unabhaengige Neuberechnung eines Monotonie-Receipts; 53 Zeilen, eine Funktion und eine Ausnahme. | `verify_gate0_monotonicity_receipt`, `GateMonotonicityBlocked` |

### Strukturelle Aufloesung und Inventar-Scanner

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`runtime_conformance_binding.py`](../../../daedalus/gates/runtime_conformance_binding.py) | Bindet `RuntimeConformanceReceipt`s in den Bericht oder sagt genau, warum nicht. Prueft Status, Eindeutigkeit der Receipt-IDs, Revisions-Atomizitaet gegen die Revision des Berichts und bei persistierten Receipts, dass jedes Byte noch auf seinen eigenen Dateinamen hasht. | `bind_runtime_conformance_receipts`, `RuntimeConformanceBinding` |
| [`python_target_structure.py`](../../../daedalus/gates/python_target_structure.py) | Verbindet ein kanonisches Ziel `daedalus.module:Qualified.name` mit einem exakten Quell-Snapshot und einer eindeutigen AST-Definitionskette. Stellt ausschliesslich strukturelle Praesenz fest — kein Import, keine Dekorator-Auswertung, kein Guard-Replay. | `resolve_python_target_structure` |
| [`provider_observation_persistence_inventory.py`](../../../daedalus/gates/provider_observation_persistence_inventory.py) | AST-Scanner ueber `daedalus/runtimes/provider/observation.py`: macht jeden bekannten Dateisystem-/SQLite-Mutationspfad des Binding-Ledgers explizit. Discovery-Evidenz, autorisiert nichts. | `scan_provider_observation_persistence`, `ProviderObservationPersistenceInventory`, `ProviderObservationPersistenceSurface`, `ProviderObservationPersistenceInventoryError` |
| [`provider_target_receipt_retention_inventory.py`](../../../daedalus/gates/provider_target_receipt_retention_inventory.py) | Derselbe Scanner-Typ fuer den Retention-Ledger; revisions- *und* byte-gebunden, mit Symlink-Pruefung und stabilem Lesen. | `scan_provider_target_receipt_retention` |

## Trust-Grenzen / Effekte

- **Kein Writer, kein Effekt.** Gemessen 2026-09-05 enthaelt keine der 19
  `.py`-Dateien in diesem Verzeichnis ein `begin_effect`, ein `write_text`, ein
  `mkdir`, ein `open(..., "w")` oder ein `os.replace`, und in
  `daedalus/spine/effect_boundary.py` gibt es keine Registry-Zeile mit einem Ziel
  in `daedalus.gates`. Das Paket liest, rechnet und gibt Objekte zurueck; die
  Persistenz liegt bei den Aufrufern.
- **Die Aufrufer sind Skripte.** Gemessen 2026-09-05 importieren u. a.
  [`tools/assert_gate_report.py`](../../../tools/assert_gate_report.py),
  [`scripts/gate0_baseline.py`](../../../scripts/gate0_baseline.py),
  [`scripts/gate0_release.py`](../../../scripts/gate0_release.py) und
  [`scripts/report_gate0_v3.py`](../../../scripts/report_gate0_v3.py) dieses
  Paket. Wer dort schreibt, faellt unter die Effekt-Registry, nicht unter `gates`.
  Siehe [Tools](../tooling/tools.md) und [Scripts](../tooling/scripts.md).
- **Signaturen sind HMAC ueber kanonischem JSON.** `trust_bundle.py`,
  `release.py` und `guard_implementation_manifest.py` benutzen `hmac`/`hashlib`
  ueber `canonical_json`/`canonical_sha` aus [Spine](spine.md). Der Schluessel kommt
  vom Aufrufer; das Paket haelt kein Geheimnis.
- **Kanonisch heisst nicht authentisiert.** Der Satz aus
  `evidence_verifier.py` ist die zentrale Trust-Aussage des Pakets. Deshalb sind
  `evidence_io.py` und `trust_bundle_io.py` als eigene, striktere
  Draht-Grenzen ausgelagert und lehnen doppelte JSON-Schluessel, JSON-Konstanten
  (`NaN`, `Infinity`) und nicht-kanonische Repraesentationen ab.
- **Groessenschranken:** `_MAX_REPORT_BYTES` 4 MiB in `report.py` und
  `report_v3.py`, `_MAX_CLASSIFICATION_BYTES` 16 MiB in `report_v3.py`,
  2 MiB Quellgrenze im Observation-Scanner. Ein unbegrenzter Parser waere selbst
  die Schwachstelle.
- **Der Bericht behauptet keinen Sicherheitsanspruch.**
  `security_boundary_claimed` ist ein separates Feld mit Default `False`, das
  `fault_matrix_binding` nur unter produktiver Schluesselverwahrung freigibt. Plan
  Revision 8 haelt fest, dass es bei der Gate-0-Schliessung bewusst `false`
  blieb — eine als vollstaendig beworbene Sicherheitsgarantie ist nach den
  Review-Regeln in `AGENTS.md` selbst ein Defekt.
- **Der Bericht bleibt ehrlich rot.** Plan Revision 8: die maschinelle Ausgabe
  sagt weiterhin `closed:false`, solange gescopte Zeilen offen sind; die
  Owner-Entscheidung schreibt das Instrument nicht um.

## Tests

Gemessen 2026-09-05 per Suche nach Importen der Form `daedalus.gates.<modul>`
unter `tests/` (die zahlreichen `tests/gates/test_repository_write_*`-Dateien
gehoeren zum Unterpaket und stehen auf [Gates repository](gates-repository.md)):

- Report: [test_gate_report.py](../../../tests/gates/test_gate_report.py), [test_gate_report_v2_schema.py](../../../tests/gates/test_gate_report_v2_schema.py), [test_gate_report_matrix_binding.py](../../../tests/gates/test_gate_report_matrix_binding.py), [test_gate_report_writer_inventory_review.py](../../../tests/gates/test_gate_report_writer_inventory_review.py), [test_gate_cli_conformance_receipts.py](../../../tests/gates/test_gate_cli_conformance_receipts.py)
- Report v3: [test_gate_report_v3.py](../../../tests/gates/test_gate_report_v3.py), [test_gate_report_v3_schema.py](../../../tests/gates/test_gate_report_v3_schema.py), [test_gate_report_v3_bounds.py](../../../tests/gates/test_gate_report_v3_bounds.py), [test_gate_report_v3_drift.py](../../../tests/gates/test_gate_report_v3_drift.py), [test_gate_report_v3_raw_input_composition.py](../../../tests/gates/test_gate_report_v3_raw_input_composition.py), [test_gate_report_v3_review.py](../../../tests/gates/test_gate_report_v3_review.py), [test_gate_report_classified_write_surfaces.py](../../../tests/test_gate_report_classified_write_surfaces.py)
- Evidenz: [test_exact_head_evidence.py](../../../tests/gates/test_exact_head_evidence.py), [test_exact_head_evidence_strict.py](../../../tests/gates/test_exact_head_evidence_strict.py)
- Trust-Bundle: [test_evidence_trust_bundle.py](../../../tests/gates/test_evidence_trust_bundle.py), [test_evidence_trust_bundle_canonical_wire.py](../../../tests/gates/test_evidence_trust_bundle_canonical_wire.py)
- Fault-Matrix: [test_fault_matrix_contract.py](../../../tests/gates/test_fault_matrix_contract.py), [test_fault_matrix_contract_schema.py](../../../tests/gates/test_fault_matrix_contract_schema.py), [test_fault_matrix_binding.py](../../../tests/gates/test_fault_matrix_binding.py), [test_fault_matrix_evidence_bridge.py](../../../tests/gates/test_fault_matrix_evidence_bridge.py), [test_fault_matrix_exact_durable_state.py](../../../tests/gates/test_fault_matrix_exact_durable_state.py)
- Release: [test_gate0_release_assessment.py](../../../tests/gates/test_gate0_release_assessment.py), [test_gate0_release_cli.py](../../../tests/gates/test_gate0_release_cli.py), [test_gate0_release_writer_inventory.py](../../../tests/gates/test_gate0_release_writer_inventory.py)
- Baseline: [test_gate_baseline_v2.py](../../../tests/gates/test_gate_baseline_v2.py), [test_gate_baseline_v2_schema.py](../../../tests/gates/test_gate_baseline_v2_schema.py), [test_gate_baseline_v2_review.py](../../../tests/gates/test_gate_baseline_v2_review.py), [test_gate_baseline_v2_review_fixed.py](../../../tests/gates/test_gate_baseline_v2_review_fixed.py), [test_gate_baseline_cli.py](../../../tests/gates/test_gate_baseline_cli.py)
- Bindings und Scanner: [test_runtime_conformance_binding.py](../../../tests/gates/test_runtime_conformance_binding.py), [test_guard_implementation_manifest.py](../../../tests/gates/test_guard_implementation_manifest.py), [test_python_target_structure.py](../../../tests/gates/test_python_target_structure.py), [test_provider_observation_persistence_inventory.py](../../../tests/gates/test_provider_observation_persistence_inventory.py), [test_provider_observation_persistence_inventory_review.py](../../../tests/gates/test_provider_observation_persistence_inventory_review.py), [test_provider_observation_persistence_inventory_revision.py](../../../tests/gates/test_provider_observation_persistence_inventory_revision.py), [test_provider_target_receipt_retention_inventory.py](../../../tests/gates/test_provider_target_receipt_retention_inventory.py)
- Architektur- und Grenzpruefungen von aussen: [test_architecture_boundaries.py](../../../tests/test_architecture_boundaries.py), [test_spine_outer_ports.py](../../../tests/contracts/test_spine_outer_ports.py), [test_runtime_gate_contract_boundaries.py](../../../tests/runtimes/test_runtime_gate_contract_boundaries.py), [test_gate_scanner_report_schema.py](../../../tests/test_gate_scanner_report_schema.py)
- Mutationslaeufe (adversarial) liegen unter `scripts/`, z. B. [run_fault_matrix_contract_mutations.py](../../../scripts/run_fault_matrix_contract_mutations.py), [run_evidence_index_wire_mutations.py](../../../scripts/run_evidence_index_wire_mutations.py), [run_guard_implementation_manifest_mutations.py](../../../scripts/run_guard_implementation_manifest_mutations.py), [run_python_target_structure_mutations.py](../../../scripts/run_python_target_structure_mutations.py)

## Verwandt

- [Gates repository](gates-repository.md) — das Unterpaket fuer Repository-Write-Evidenz
- [Spine](spine.md) — `check_conformance`, `REGISTRY_BY_ID`, `canonical_sha`, Writer-Inventar
- [Runtimes](runtimes.md) — Quelle des Fault-Matrix-Verdikts und der Conformance-Receipts
- [Runtimes contracts](runtimes-contracts.md) — `PythonTargetStructure`, Retention-Inventar-Typen
- [Kernel](kernel.md), [Kernel contracts](kernel-contracts.md) — `RuntimeConformanceReceipt`, Promotion
- [Kernel policy](kernel-policy.md) — die mechanische Veto-Ebene, ueber die hier berichtet wird
- [Tools](../tooling/tools.md), [Scripts](../tooling/scripts.md) — die Aufrufer, die schreiben
- [Wiki-Index](../index.md), [Feature-Backlog](../feature-backlog.md)

## Ungeklaert

- **Nur Gate 0 ist implementiert.** `GateReport.__post_init__` wirft fuer jedes
  `gate != 0`, und `__main__.py` erlaubt `--gate` nur mit `choices=(0,)`. Wie
  Gate 1 (der aktive Gate nach Plan §11) berichtet werden soll, steht nicht in
  diesem Paket.
- **Wer die Trust-Mengen liefert.** `strict_mechanical_blockers` und
  `verify_evidence_trust_bundle` verlangen unabhaengig beschaffte Digest-Mengen
  und Signierschluessel; woher ein Betreiber sie nimmt, ist ein
  Betriebsverfahren und im Code nicht festgelegt.
- **`report.py` und `report_v3.py` sind ein laufender Strangler.**
  `GateReportV3` erbt von `GateReport`, beide Bauwege existieren nebeneinander,
  und `__init__.py` re-exportiert nur die v2-Namen. Welcher Weg der bindende ist,
  geht aus dem Code nicht hervor — der v3-Docstring sagt nur, dass der v2-Pfad
  unveraendert bleibt.
- **Zwei Inventar-Scanner fuer je genau eine Datei.**
  `provider_observation_persistence_inventory.py` ist auf
  `daedalus/runtimes/provider/observation.py` gepinnt, das Retention-Geschwister
  auf den Pfad aus `daedalus.runtimes.contracts.retention`. Beide nennen sich
  selbst "discovery evidence only" und sind nicht in das kanonische
  Gate-0-Inventar integriert; ob das ein Zwischenstand oder der Endzustand ist,
  steht nicht im Code.
- **`__init__.py` monkeypatcht `trust_bundle`.** Der Import des Pakets ersetzt
  `trust_bundle.parse_evidence_trust_bundle` und `…load_evidence_trust_bundle`
  durch die strikten Varianten. Wer `daedalus.gates.trust_bundle` importiert,
  *ohne* dass `daedalus.gates` initialisiert wurde, bekaeme das permissive
  Verhalten — praktisch schwer erreichbar, aber der Kommentar nennt es als
  bewusste Kompatibilitaetsnaht.

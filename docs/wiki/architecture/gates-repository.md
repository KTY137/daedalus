---
title: Repository-Gates
type: module
status: living
updated: 2026-09-05
covers: daedalus/gates/repository
---
# Repository-Gates

`daedalus/gates/repository` beantwortet genau eine Frage: **Was muss ein
Schreibzugriff auf diesen Checkout erfuellt haben, bevor er passiert?** Das
Paket sitzt im Kernel-Teil des Daedalus/Ikarus/Ariadne-Bildes, aber es ist
bewusst kein Effekt-Pfad. Jedes Modul hier liest — Quellbytes, Git-Refs,
CAS-Objekte, persistierte Ledger-Projektionen — und produziert daraus eine
Klassifikation, ein Inventar oder eine Quittung. Der Paket-Docstring sagt es
in einem Satz: *"It authorizes nothing on its own."* Effect-Lease,
Owner-Approval und der Promotionspfad bleiben, wo sie sind (siehe
[Kernel-Policy](kernel-policy.md) und [Gates](gates.md)); ein Gate, das auch
gewaehren koennte, waere genau der Defekt, gegen den die eigenen Tests
geschrieben sind.

Die Herkunft ist gemessen, nicht bevorzugt: sechzehn Module unter
`daedalus/gates/` trugen ein gemeinsames Namenspraefix (`repository_write_inventory`, `repository_head_revision`, …), und sieben davon bildeten
eine stark zusammenhaengende Import-Komponente. Das Verzeichnis trug den Namen
also bereits — nur die Ordnerstruktur widersprach. Beim Umzug in das
Unterpaket fiel das Praefix weg, weil das Paket es nun traegt (analog zu
[`daedalus/runtimes/provider`](runtimes-provider.md)).

Gemessen 2026-09-05: 17 Dateien, 10 283 Zeilen.

## Zwei Familien

**Lesen, was ist.** `head_revision` und `tree` beschreiben den Checkout selbst:
die authentifizierte HEAD-Quittung und die exakten Quellbytes, ueber die die
Gates klassifizieren.

**Die Zulassungskette eines Schreibzugriffs.** Alle `write_*`-Module bilden
eine gerichtete Kette vom rohen AST-Scan bis zur semantischen Wiedergabe
persistierter Quittungen:

```
scan_repository_write_surfaces      (v1: Callsites aus dem AST)
        + scan_repository_write_stdlib_delta
  -> scan_repository_write_surfaces_v2        (RepositoryWriteInventoryV2)
  -> project_repository_write_classifications (SurfaceClassification je Surface)
  -> materialize_repository_write_evidence            [Stage MATERIALIZATION]
  -> verify_repository_write_evidence_origin          [Stage ORIGIN]
  -> verify_repository_write_source_anchor_semantics  [Stage ANCHOR]
  -> verify_repository_write_guard_structure          [Stage GUARD]
  -> verify_repository_write_runtime_conformance      [Stage CONFORMITY]
  -> verify_repository_write_effect_leases            [Stage LEASE]
  -> authenticate_repository_write_surfaces  (Konjunktion je Surface)
```

Daneben laeuft ein zweiter, kuerzerer Pfad fuer das *Artefakt* dieses
Inventars: `resolve_repository_write_artifact` (CAS) plus
`verify_repository_write_artifact` (Bytes) werden von
`admit_repository_write_artifact` atomar gekoppelt, damit ein Aufrufer nicht
zwei unabhaengig erzeugte Quittungen von Hand zusammenstecken kann.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/gates/repository/__init__.py) | Paket-Docstring: die zwei Familien und die Nicht-Autoritaet des Pakets. Re-exportiert nichts. | — |
| [`tree.py`](../../../daedalus/gates/repository/tree.py) | Race-bewusster, read-only Zugriff auf exakte Quellbytes: Pfadnormalisierung, Symlink- und Escape-Pruefung, Groessengrenze, Identitaetspruefung vor und nach dem Lesen. | `RepositorySourceSnapshot`, `read_repository_source`, `normalize_repository_path`, `resolve_repository_root`, `RepositoryTreeReadError`, `RepositoryTreePathError`, `RepositoryTreeRaceError` |
| [`head_revision.py`](../../../daedalus/gates/repository/head_revision.py) | Verifiziert die exakte Git-HEAD-Revision **ohne** `git`-Prozess: liest nur `.git/HEAD` und den gewaehlten losen oder gepackten Ref ueber `tree.py`. | `verify_repository_head_revision`, `verify_repository_head_revision_receipt` |
| [`write_inventory.py`](../../../daedalus/gates/repository/write_inventory.py) | Generation-1-Scanner: findet schreibfaehige oder unaufgeloeste Prozess-/Dateisystem-Callsites im Produktionsbaum per AST. Syntaxbasiert und fail-closed. | `scan_repository_write_surfaces`, `RepositoryWriteInventory`, `RepositoryWriteCallsite`, `RepositoryWriteInventoryError` |
| [`write_stdlib_delta.py`](../../../daedalus/gates/repository/write_stdlib_delta.py) | Additives Inventar fuer stdlib-Schreib-/Prozessflaechen, die der v1-Scanner nicht sieht (`gzip.open`, `tarfile.open`, `shutil`, …). Bewusst inert: patcht das kanonische Inventar nicht. | `scan_repository_write_stdlib_delta`, `RepositoryWriteStdlibDelta`, `RepositoryWriteStdlibFinding`, `RepositoryWriteStdlibDeltaError` |
| [`write_inventory_v2.py`](../../../daedalus/gates/repository/write_inventory_v2.py) | Strangler ueber beide Scanner: laesst v1 vor *und* nach dem Delta-Scan laufen und verweigert jede Drift zwischen den Laeufen. Jede Surface traegt ihren Herkunfts-Origin (`base_v1` / `stdlib_delta_v1`). | `scan_repository_write_surfaces_v2`, `RepositoryWriteInventoryV2`, `RepositoryWriteSurface`, `RepositoryWriteInventoryV2Error` |
| [`write_classification.py`](../../../daedalus/gates/repository/write_classification.py) | Groesstes Modul (1 516 Zeilen). Bindet reviewte Deklarationen an ein v2-Inventar und komponiert die Sechs-Stufen-Authentifizierung je Surface. | `SurfaceClassification`, `TargetDisposition`, `GuardDisposition`, `EvidenceKind`, `EvidenceBinding`, `AuthenticationStage`, `RepositoryWriteAuthenticationInputs`, `SurfaceEvidenceAuthentication`, `RepositoryWriteClassificationReport`, `project_repository_write_classifications`, `authenticate_repository_write_surfaces`, `applicable_authentication_stages`, `authenticated_over_stages`, `surface_binding_sha256`, `surface_classification_verdict`, `stage_report_type`, `stage_verifier`, `parse_inventory_v2`, `project_classification_input`, `NonRuntimeConformityBinding`, `NonRuntimeConformityAdmission`, `issue_non_runtime_conformity_binding`, `verify_non_runtime_conformity_binding` |
| [`write_evidence.py`](../../../daedalus/gates/repository/write_evidence.py) | Der kanonische Vertrag, der ein content-adressiertes Inventar-Artefakt an die logische Inventar-Identitaet eines `GateReportV3` bindet. | `RepositoryWriteArtifactEvidence`, `RepositoryWriteArtifactEvidenceError` |
| [`write_artifact_cas.py`](../../../daedalus/gates/repository/write_artifact_cas.py) | Loest genau einen `artifact-locator:sha256` aus einem lokalen CAS-Layout auf: read-only Open, Datei-Identitaet vor/nach dem Lesen, Beweis der Disjunktheit zum Primary Checkout. | `resolve_repository_write_artifact`, `RepositoryWriteArtifactCASRoot`, `RepositoryWriteArtifactResolutionReceipt`, `ResolvedRepositoryWriteArtifact`, `artifact_relative_path`, `RepositoryWriteArtifactCASError` |
| [`write_artifact_verifier.py`](../../../daedalus/gates/repository/write_artifact_verifier.py) | Strikte Byte-Verifikation: hasht und parst bereits aufgeloeste Bytes, rekonstruiert daraus das Inventar-v2-Objekt und bindet es an Artefakt-Evidence plus `GateReportV3`. | `verify_repository_write_artifact`, `RepositoryWriteArtifactVerificationReceipt`, `RepositoryWriteArtifactVerificationError` |
| [`write_artifact_admission.py`](../../../daedalus/gates/repository/write_artifact_admission.py) | Koppelt CAS-Aufloesung und Byte-Verifikation zu **einem** Aufruf und kreuzbindet beide Quittungen. Der Aufrufer kann keine Bytes injizieren. | `admit_repository_write_artifact`, `RepositoryWriteArtifactAdmissionReceipt`, `AdmittedRepositoryWriteArtifact`, `RepositoryWriteArtifactAdmissionError` |
| [`write_evidence_materialization.py`](../../../daedalus/gates/repository/write_evidence_materialization.py) | Stage MATERIALIZATION: prueft exakte kanonische JSON-Bytes gegen die revisions- und surface-gebundenen `EvidenceBinding`-Werte. | `materialize_repository_write_evidence`, `MaterializedEvidenceRecord`, `RepositoryWriteEvidenceMaterializationReport`, `evidence_subject_sha256`, `RepositoryWriteEvidenceMaterializationError` |
| [`write_evidence_origin.py`](../../../daedalus/gates/repository/write_evidence_origin.py) | Stage ORIGIN: authentifiziert die vollstaendige Materialisierungs-Projektion per HMAC gegen einen extern bereitgestellten Collector-Key, mit TTL (max. 24 h). | `issue_repository_write_evidence_origin_attestation`, `verify_repository_write_evidence_origin`, `parse_repository_write_evidence_origin_attestation`, `RepositoryWriteEvidenceOriginAttestation`, `RepositoryWriteEvidenceOriginReport`, `materialized_record_sha256`, `RepositoryWriteEvidenceOriginError`, `RepositoryWriteEvidenceOriginSignatureError`, `RepositoryWriteEvidenceOriginBindingError` |
| [`write_source_anchor_semantics.py`](../../../daedalus/gates/repository/write_source_anchor_semantics.py) | Stage ANCHOR: die erste lokale semantische Wiedergabe. Bindet fuer jede klassifizierte Surface genau eine Source-Anchor-Quittung an die aktuelle regulaere Datei am deklarierten Pfad und AST-Byte-Offset. | `verify_repository_write_source_anchor_semantics`, `SourceAnchorSemanticRecord`, `RepositoryWriteSourceAnchorSemanticsReport`, `RepositoryWriteSourceAnchorSemanticsError`, `RepositoryWriteSourceAnchorTreeError`, `RepositoryWriteSourceAnchorBindingError` |
| [`write_guard_structure.py`](../../../daedalus/gates/repository/write_guard_structure.py) | Stage GUARD: verbindet Klassifikation, Origin/Anchor-Kette, das authentifizierte Guard-Implementation-Manifest und den konservativen Python-AST. Beweist Existenz und Eindeutigkeit des benannten Guard-Ziels — **nicht**, dass der Guard lief. | `verify_repository_write_guard_structure`, `GuardStructureRecord`, `RepositoryWriteGuardStructureReport`, `RepositoryWriteGuardStructureError`, `RepositoryWriteGuardStructureBindingError`, `RepositoryWriteGuardStructurePayloadError` |
| [`write_runtime_conformance.py`](../../../daedalus/gates/repository/write_runtime_conformance.py) | Stage CONFORMITY: jede produktionserreichbare Surface muss zentral geguarded sein, genau eine Runtime-Conformance-Bindung tragen und auf ein typisiertes Runtime-Subjekt aufloesen, dessen Envelope als aktiver Record im persistierten Trust-Ledger liegt. Nutzt nur die Audit-Projektion, nie Admission oder Lease-Ausgabe. | `verify_repository_write_runtime_conformance`, `RuntimeConformanceSubject`, `RuntimeConformanceReplayRecord`, `RepositoryWriteRuntimeConformanceReport`, `RepositoryWriteRuntimeConformanceError`, `RepositoryWriteRuntimeConformanceBindingError`, `RepositoryWriteRuntimeConformancePayloadError` |
| [`write_effect_lease.py`](../../../daedalus/gates/repository/write_effect_lease.py) | Stage LEASE: read-only semantische Wiedergabe der Effect-Lease-Evidenz. Fehlende und in `STARTED` stehengebliebene Ausfuehrungen sind explizite fail-closed Rekonziliationszustaende, kein Erfolg. | `verify_repository_write_effect_leases`, `replay_non_runtime_effect_subject`, `EffectLeaseReplaySubject`, `EffectLeaseReplayRecord`, `RepositoryWriteEffectLeaseReport`, `RepositoryWriteEffectLeaseError`, `RepositoryWriteEffectLeaseBindingError`, `RepositoryWriteEffectLeasePayloadError` |

## Die Sechs-Stufen-Authentifizierung

Der interessanteste Teil des Pakets steht in `write_classification.py` ab
Zeile 460. Er formuliert die Regel, dass ein Stufenbericht **nur ueber seine
eigene Stufe** spricht:

> A stage report says that ITS stage ran over the material it was given. It
> never says the other five ran, and it never says anything about one named
> surface unless it carries a record for that surface.

`AuthenticationStage` hat sechs Werte: `MATERIALIZATION`, `ORIGIN`, `ANCHOR`,
`GUARD`, `CONFORMITY`, `LEASE`. Drei davon stehen in
`ALWAYS_APPLICABLE_STAGES` (Materialisierung, Origin, Anchor) — jede
klassifizierte Zeile traegt mindestens einen Source-Anchor, also muessen ihre
Evidenzbytes materialisieren, attestiert sein und gegen die exakte Quelle
aufloesen. Die uebrigen drei sind je nach Klassifikation anwendbar;
`applicable_authentication_stages` entscheidet das pro Zeile.

Authentifizierung ist die **strikte Konjunktion ueber die anwendbaren
Stufen**, und eine leere anwendbare Menge ist `False`, nie vakuum-wahr. Die
Stufenverdikte sind `STAGE_VERDICT_VERIFIED`, `STAGE_VERDICT_NOT_APPLICABLE`
und `STAGE_VERDICT_ABSENT`.

Zwei Details, die die Kette gegen Unterschieben absichern:

1. `stage_report_type` und `stage_verifier` loesen Klasse und Funktion einer
   Stufe erst **zur Aufrufzeit** per `importlib` auf. Der Stufenbericht muss
   *exakt* diese Klasse sein — ein aus JSON geparstes Mapping, ein
   NamedTuple oder ein Look-alike wird abgelehnt. Ein solches Objekt zu
   halten heisst, dass der zugehoerige Verifier in diesem Prozess lief.
2. `RepositoryWriteAuthenticationInputs` enthaelt bewusst *keinen*
   Stufenbericht, sondern nur die RAW-Eingaben. `authenticate_repository_write_surfaces`
   baut jeden Bericht selbst, indem es den jeweiligen Verifier laufen laesst.
   Man kann der Komposition also keinen fertigen Bericht in die Hand druecken.

Ein Kommentar in derselben Datei dokumentiert einen entfernten Fehler ehrlich:
Revision 2 hat `evidence_authenticated` aus dem Payload gestrichen, weil der
Schluessel ein modulweites Literal `False` war, das nie einen wahrheitsfaehigen
Wert tragen konnte — dieses Modul laeuft *vor* den sechs Verifiern, und ein
Boolean pro Report kann ohnehin nicht sagen, ueber welche Surface man sich
einig war.

### Dispositionen

| Enum | Werte |
| --- | --- |
| `TargetDisposition` | `primary_checkout`, `checkout_external`, `non_repository`, `unknown` |
| `GuardDisposition` | `central`, `local_guards`, `inventory_only`, `unguarded`, `retired` |
| `EvidenceKind` | `source_anchor`, `guard_contract`, `effect_lease_receipt`, `runtime_conformance_receipt`, `primary_checkout_disjointness_receipt`, `retirement_receipt` |

`surface_binding_sha256(source_revision, surface)` bindet Evidenz an genau eine
Revision **und** eine Inventar-Surface-Identitaet; ohne diese Bindung waere
eine Quittung von einer anderen Revision wiederverwendbar.

`NON_RUNTIME_AUTHORIZATION_CLASS` (`"NonRuntimeEffectAuthorization"`) ist die
einzige Autorisierungsklasse, die die CONFORMITY-Stufe entschuldigen kann. Der
Name ist absichtlich als Wire-Konstante ausgeschrieben statt aus
`daedalus.kernel.authorization` importiert: er ist das, was ein Collector
signiert, also eine Zeichenkette auf der Leitung und keine Objektreferenz.

## Trust-Grenzen / Effekte

Das Paket hat **keinen** Writer. Kein Modul ruft `begin_effect`, keines mutiert
Git-Metadaten, keines startet einen Prozess. Die konkreten Grenzen:

- `tree.py` oeffnet ausschliesslich read-only, verweigert Symlinks, Pfade
  ausserhalb der Wurzel, Nicht-UTF-8 und alles ueber `_MAX_SOURCE_BYTES`
  (16 MiB), und prueft die Datei-Identitaet (Device/Inode/Groesse/mtime) vor
  und nach dem Lesen — eine Aenderung waehrend des Lesens ist
  `RepositoryTreeRaceError`, kein Teilergebnis.
- `head_revision.py` spawnt bewusst kein `git`. Die Quittung beweist nur, dass
  die erwartete Revision zu einer *stabilen* HEAD-Beobachtung in einem
  kanonischen Nicht-Worktree-Checkout passte — nicht, dass der Worktree sauber
  oder das Commit-Objekt gueltig ist.
- `write_artifact_cas.py` beweist aktiv, dass die CAS-Wurzel vom Primary
  Checkout **disjunkt** ist (`_roots_overlap`), begrenzt auf
  `_MAX_ARTIFACT_BYTES` (16 MiB) und revalidiert den Pfad nach dem Lesen.
- `write_runtime_conformance.py` liest den Trust-Ledger nur ueber dessen
  oeffentliche Audit-Projektion. Admission, Quarantaene und Lease-Ausgabe
  werden nicht aufgerufen.
- `write_evidence_origin.py` erhaelt den Collector-Key als Parameter
  (`bytes | str`), haelt ihn nicht vor und erzeugt ihn nicht. Die Attestierung
  ist HMAC-SHA256 ueber das kanonische Projektionsdigest und laeuft nach
  spaetestens 24 Stunden ab (`_MAX_TTL`).
- Die Scanner (`write_inventory.py`, `write_stdlib_delta.py`) sind
  fail-closed-asymmetrisch: Mehrdeutigkeit darf einen **zusaetzlichen** Blocker
  erzeugen, aber niemals einen fraglichen Produktionspfad verschwinden lassen.
  `_MODE_LITERAL` etwa akzeptiert nur ein reines Python-Mode-String-Alphabet;
  alles andere an der Mode-Position gilt als Beweis, dass die Position
  fehlgelesen wurde — nicht als Beweis, dass der Aufruf read-only ist.

Was das Paket ausdruecklich **nicht** kann, steht in fast jedem Docstring
wortwoertlich: keinen Signierer authentifizieren (ausser Origin, und dort nur
den Collector), keinen Evidence-Index aktualisieren, kein `OwnerApproval`
ausstellen, keine `PromotionReceipt` erzeugen, keinen Checkout mutieren, nicht
mergen, nicht promoten, keinen Gate-Zustand aendern und Gate 0 nicht schliessen.
Das deckt sich mit den Invarianten 3, 4 und 5 des Masterplans.

## Tests

Gemessen 2026-09-05: 70 Testdateien unter `tests/` referenzieren
`daedalus.gates.repository`. Die dichtesten:

| Bereich | Tests |
| --- | --- |
| Tree / HEAD | [`test_repository_tree.py`](../../../tests/gates/test_repository_tree.py), [`test_repository_tree_review.py`](../../../tests/gates/test_repository_tree_review.py), [`test_repository_head_revision.py`](../../../tests/gates/test_repository_head_revision.py), [`test_repository_head_revision_wire.py`](../../../tests/gates/test_repository_head_revision_wire.py), [`test_repository_head_revision_review.py`](../../../tests/gates/test_repository_head_revision_review.py), [`test_repository_head_revision_integration_review.py`](../../../tests/gates/test_repository_head_revision_integration_review.py) |
| Inventar | [`test_repository_write_inventory.py`](../../../tests/gates/test_repository_write_inventory.py), [`test_repository_write_inventory_schema.py`](../../../tests/gates/test_repository_write_inventory_schema.py), [`test_repository_write_inventory_review.py`](../../../tests/gates/test_repository_write_inventory_review.py), [`test_repository_write_inventory_v2.py`](../../../tests/gates/test_repository_write_inventory_v2.py), [`test_repository_write_inventory_v2_review.py`](../../../tests/gates/test_repository_write_inventory_v2_review.py), [`test_repository_write_stdlib_delta.py`](../../../tests/gates/test_repository_write_stdlib_delta.py), [`test_repository_write_stdlib_delta_cli_schema.py`](../../../tests/gates/test_repository_write_stdlib_delta_cli_schema.py), [`test_repository_write_stdlib_delta_review.py`](../../../tests/gates/test_repository_write_stdlib_delta_review.py) |
| Artefakt (CAS / Verifier / Admission) | [`test_repository_write_artifact_cas.py`](../../../tests/gates/test_repository_write_artifact_cas.py), [`test_repository_write_artifact_cas_toctou.py`](../../../tests/gates/test_repository_write_artifact_cas_toctou.py), [`test_repository_write_artifact_cas_adversarial.py`](../../../tests/gates/test_repository_write_artifact_cas_adversarial.py), [`test_repository_write_artifact_cas_receipt.py`](../../../tests/gates/test_repository_write_artifact_cas_receipt.py), [`test_repository_write_artifact_cas_schema.py`](../../../tests/gates/test_repository_write_artifact_cas_schema.py), [`test_repository_write_artifact_verifier.py`](../../../tests/gates/test_repository_write_artifact_verifier.py), [`test_repository_write_artifact_verifier_canonical_bytes.py`](../../../tests/gates/test_repository_write_artifact_verifier_canonical_bytes.py), [`test_repository_write_artifact_verifier_malformed.py`](../../../tests/gates/test_repository_write_artifact_verifier_malformed.py), [`test_repository_write_artifact_verifier_types.py`](../../../tests/gates/test_repository_write_artifact_verifier_types.py), [`test_repository_write_artifact_admission.py`](../../../tests/gates/test_repository_write_artifact_admission.py), [`test_repository_write_artifact_admission_adversarial.py`](../../../tests/gates/test_repository_write_artifact_admission_adversarial.py) |
| Klassifikation / Authentifizierung | [`test_repository_write_classification.py`](../../../tests/gates/test_repository_write_classification.py), [`test_repository_write_classification_review.py`](../../../tests/gates/test_repository_write_classification_review.py), [`test_repository_write_evidence_authentication.py`](../../../tests/gates/test_repository_write_evidence_authentication.py), [`test_repository_write_non_runtime_conformity_admission.py`](../../../tests/gates/test_repository_write_non_runtime_conformity_admission.py) |
| Stufenverifier | [`test_repository_write_evidence_materialization.py`](../../../tests/gates/test_repository_write_evidence_materialization.py), [`test_repository_write_evidence_origin.py`](../../../tests/gates/test_repository_write_evidence_origin.py), [`test_repository_write_source_anchor_semantics.py`](../../../tests/gates/test_repository_write_source_anchor_semantics.py), [`test_repository_write_guard_structure.py`](../../../tests/gates/test_repository_write_guard_structure.py), [`test_repository_write_runtime_conformance.py`](../../../tests/gates/test_repository_write_runtime_conformance.py), [`test_repository_write_effect_lease.py`](../../../tests/gates/test_repository_write_effect_lease.py), [`test_repository_write_effect_lease_non_runtime.py`](../../../tests/gates/test_repository_write_effect_lease_non_runtime.py) |
| Konsumenten | [`test_gate_report_v3.py`](../../../tests/gates/test_gate_report_v3.py), [`test_gate_report_v3_surface_authentication.py`](../../../tests/gates/test_gate_report_v3_surface_authentication.py), [`test_gate_report_v3_drift.py`](../../../tests/gates/test_gate_report_v3_drift.py), [`test_write_surface_lease_dominance.py`](../../../tests/gates/test_write_surface_lease_dominance.py), [`test_write_surface_coverage.py`](../../../tests/test_write_surface_coverage.py), [`test_declare_write_surfaces.py`](../../../tests/test_declare_write_surfaces.py), [`test_gate_report_classified_write_surfaces.py`](../../../tests/test_gate_report_classified_write_surfaces.py), [`test_import_scc_hierarchy.py`](../../../tests/contracts/test_import_scc_hierarchy.py) |

Auffaellig: fast jedes Modul hat neben dem Funktionstest einen zweiten
`*_review.py`, der die Review-Fragen des jeweiligen Work Packets als
ausfuehrbare Behauptungen festhaelt — das ist Kapitel 10 Schritt 5 des
Masterplans in Testform.

## Verwandt

- [Gates](gates.md) — das umgebende Paket, `GateReportV3` und die
  Guard-Implementation-Manifeste
- [Kernel-Policy](kernel-policy.md) — die Instanz, die tatsaechlich gewaehrt
  oder verweigert
- [Kernel](kernel.md) und [Kernel-Vertraege](kernel-contracts.md) — EffectLease,
  Attempt, Evidence
- [Runtimes-Provider](runtimes-provider.md) — die parallel gemessene
  Paket-Extraktion und der Trust-Ledger hinter der CONFORMITY-Stufe
- [Runtimes-Vertraege](runtimes-contracts.md) — `RepositoryHeadRevisionReceipt`
  und die uebrigen Repository-Vertragstypen
- [Spine](spine.md) — `canonical_json` / `canonical_sha`, die kanonische
  Serialisierung unter allen Digests hier
- [Schreib-Lanes](lanes.md) — die Baseline-Checks am anderen Ende desselben
  Schreibpfads
- [Tools](../architecture/tools.md) und [tools/](../tooling/tools.md) — die
  CLI-Oberflaechen, die diese Scanner aufrufen
- [Wiki-Index](../index.md), [Tool-Vetting](../tool-vetting.md)

## Ungeklaert

- **Ungeklaert:** Wer die Collector-Secrets fuer
  `issue_repository_write_evidence_origin_attestation` und
  `issue_non_runtime_conformity_binding` in der Praxis bereitstellt und wo sie
  liegen, ist aus dem Paket nicht ablesbar — beide nehmen das Secret als
  Parameter, und die Aufrufer liegen ausserhalb.
- **Ungeklaert:** Ob und wo der `primary_checkout_disjointness_receipt` aus
  `EvidenceKind` tatsaechlich erzeugt wird. Die `EvidenceKind`-Variante
  existiert und wird materialisiert, aber ein eigener Verifier fuer die
  Checkout-Disjunktheit ist in diesem Paket nicht vorhanden; mehrere Docstrings
  nennen sie als *noch offen*.
- **Ungeklaert:** Der `retirement_receipt` hat dieselbe Lage — er ist eine
  `EvidenceKind` und wird von `GuardDisposition.RETIRED` impliziert, aber der
  Retirement-Verifier wird in `write_guard_structure.py` und
  `write_runtime_conformance.py` nur als ausstehend erwaehnt.
- **Ungeklaert:** `write_classification.py` spricht in seinem Docstring von
  "Later packets may consume the report only after independently verifying the
  referenced evidence" — welches Work Packet das ist, steht nicht im Code.

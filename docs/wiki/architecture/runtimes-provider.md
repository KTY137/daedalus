---
title: Runtimes / Provider
type: module
status: living
updated: 2026-09-05
covers: daedalus/runtimes/provider
---
# Runtimes / Provider

`daedalus/runtimes/provider` ist die Beweiskette, die zwischen "ein Runtime
moechte einen externen Provider aufrufen" und dem tatsaechlichen Aufruf steht.
Das Paket gehoert zum Trust-/Runtime-Kernel von Daedalus (Masterplan Abschnitt 3
und 4, Invarianten 1, 3, 7, 8): es beantwortet, *was* aufgerufen werden darf,
*wer* das autorisiert hat, *welche* Bytes dahinterstehen und *was* zurueckkam.
Es enthaelt bewusst keine eigene Policy — Admission, Budget und Containment
bleiben bei Kernel- und Spine-Kontrakten, die dieses Paket nur aufruft.

Der Paket-Docstring in [`__init__.py`](../../../daedalus/runtimes/provider/__init__.py)
nennt den Grund fuer die Existenz als Subpaket: 25 Module unter
`daedalus/runtimes/` trugen das Praefix `provider_`, davon bilden 14 eine
starke Zusammenhangskomponente im Importgraphen. Vier Familien gliedern das
Paket, und ihre Namen sind die Karte:

| Familie | Frage | Umfang |
| --- | --- | --- |
| `executable_*` | Was darf das Runtime ueberhaupt ausfuehren? | Ziel-Manifest, Struktur, Pre-Admission, Objekt-Registry |
| `invocation*` | Ein Aufruf: Identitaet, Autoritaet, ABI, Payload, Aufloesung | 7 Module |
| `observation*` | Was kam zurueck, und wo liegt es? | Autoritaet, Store, Store-Kontrakt |
| `target_*` | Quittungen, Retention und Verifikation eines Provider-Targets | Ledger, Verification, 6 Retention-Module |

Abzugrenzen ist `daedalus.runtimes.providers` (Plural): das ist der
Provider-*Katalog* — Personas, Kontrakte, Token-Policy — und liegt woanders.
Singular ist die Handlung, Plural das Verzeichnis. Siehe
[Runtimes / Providers](runtimes-providers.md) und [Providers](providers.md).

26 Python-Module, 16197 Zeilen (gemessen 2026-09-05).

## Module

### invocation* — ein Aufruf, in sieben Schritten

| Modul | Was es tut | Wichtige oeffentliche Symbole |
| --- | --- | --- |
| [invocation.py](../../../daedalus/runtimes/provider/invocation.py) | Unveraenderliche Identitaet *eines* Runtime-Effekt-Subjekts: Provider, Adapter, Artefakt- und Config-Digest, Entrypoint, Runtime, Execution, Idempotenzschluessel, Lease-Digest, Quell-Revision. Nicht ausfuehrend. | `ProviderInvocationSubject`, `ProviderInvocationSubjectError` |
| [invocation_registry.py](../../../daedalus/runtimes/provider/invocation_registry.py) | Manifest, das einer Provider-ID genau eine Adapter- und Implementierungs-Identitaet zuordnet. Kein Callback, kein dynamischer Loader. | `ProviderInvocationRegistryManifest`, `ProviderAdapterDescriptor`, `build_provider_invocation_registry_manifest`, `ProviderInvocationRegistryShapeError`, `ProviderInvocationRegistryResolutionError` |
| [invocation_authority.py](../../../daedalus/runtimes/provider/invocation_authority.py) | Signierte Verbund-Autoritaet ueber Subjekt und Registry-Digest, aufgesetzt auf `ProviderObservationAuthority`. HMAC-Keyring. | `ProviderInvocationObservationAuthority`, `issue_provider_invocation_observation_authority`, `verify_provider_invocation_observation_authority`, `ProviderInvocationAuthoritySignatureError`, `ProviderInvocationAuthorityBindingError` |
| [invocation_identity.py](../../../daedalus/runtimes/provider/invocation_identity.py) | Read-only-Projektion: authentifiziert die Autoritaet gegen das Registry-Manifest und liefert ein inertes, content-adressiertes Objekt. | `ProviderInvocationIdentityProjection`, `project_provider_invocation_identity`, `ProviderInvocationIdentityAuthenticationError`, `ProviderInvocationIdentityBindingError` |
| [invocation_payload.py](../../../daedalus/runtimes/provider/invocation_payload.py) | Kanonischer Wertkoerper eines Aufrufs (Prompt, Workspace, Modelloptionen) mit harten Grenzen fuer Tiefe, Knotenzahl, Stringlaenge und kanonische Bytes. Verhindert, dass Aufrufdaten durch Python-Closures geschmuggelt werden. | `ProviderInvocationPayload`, `build_provider_invocation_payload`, `ProviderInvocationPayloadError` |
| [invocation_resolution.py](../../../daedalus/runtimes/provider/invocation_resolution.py) | Loest die signierte Autoritaet gegen genau einen Deskriptor auf und emittiert eine deterministische Quittung. Aufloesung ist keine Ausfuehrung. | `resolve_provider_invocation_authority`, `verify_provider_invocation_resolution_receipt`, `ProviderInvocationResolutionReceipt`, `ProviderInvocationResolutionBindingError` |
| [invocation_abi.py](../../../daedalus/runtimes/provider/invocation_abi.py) | Bindet die authentifizierte Invocation-Autoritaet an den Payload *und* die per Pre-Admission bewiesenen Executable- und Output-Evidence-Targets. | `ProviderInvocationABIContract`, `issue_provider_invocation_abi_contract`, `verify_provider_invocation_abi_contract`, `ProviderInvocationABIBindingError`, `ProviderInvocationABISignatureError` |

### executable* — was ausgefuehrt werden darf

| Modul | Was es tut | Wichtige oeffentliche Symbole |
| --- | --- | --- |
| [executable_targets.py](../../../daedalus/runtimes/provider/executable_targets.py) | Exaktes, nicht-ausfuehrendes Target-Manifest: Repository-Pfad und Quell-Digest je Target, signiert. Ein Target muss der im Modul definierten Namensform genuegen. | `ProviderExecutableTargetManifest`, `ProviderExecutableTargetDescriptor`, `ProviderExecutableTargetAuthority`, `ProviderExecutableTargetProjection`, `build_provider_executable_target_manifest`, `issue_provider_executable_target_authority`, `project_provider_executable_targets` |
| [executable_structure.py](../../../daedalus/runtimes/provider/executable_structure.py) | Wiederholt die vollstaendige Authentifizierung, liest dann Repository-Bytes und beweist, dass beide Objekte eindeutig im gewaehlten Baum existieren. Kein Import, keine Dekorator-Auswertung. | `verify_provider_executable_structure`, `verify_provider_executable_structure_receipt`, `ProviderExecutableStructureReceipt`, `VerifiedProviderExecutableTarget`, `ProviderExecutableStructureBindingError` |
| [executable_pre_admission.py](../../../daedalus/runtimes/provider/executable_pre_admission.py) | Komponiert Resolution-, Verification-, Struktur- und beide Retention-Evidence-Quittungen plus `RepositoryHeadRevisionReceipt` zu *einer* Vor-Admission. | `build_provider_executable_pre_admission`, `ProviderExecutablePreAdmissionReceipt`, `ProviderExecutablePreAdmissionBindingError`, `ProviderExecutablePreAdmissionShapeError` |
| [executable_object_registry.py](../../../daedalus/runtimes/provider/executable_object_registry.py) | Das groesste Modul des Pakets (2636 Zeilen, gemessen 2026-09-05). Es beweist, dass die *bereits geladenen* Python-Funktionsobjekte im Prozess noch den admittierten Targets, den Repository-Bytes und einer bewusst engen Abhaengigkeitshuelle ueber ambiente Globals entsprechen: Bytecode wird gegen frisch kompilierten Quelltext gehasht, Abhaengigkeiten werden geklont und versiegelt. | `ProviderExecutableObjectRegistry`, `ProviderExecutableObjectAdmissionReceipt`, `ProviderSealedOutputEvidenceError`, `ProviderExecutableObjectRegistryBindingError`, `ProviderExecutableObjectRegistryShapeError` |

### observation* — was zurueckkam

| Modul | Was es tut | Wichtige oeffentliche Symbole |
| --- | --- | --- |
| [observation.py](../../../daedalus/runtimes/provider/observation.py) | Signierte Observation-Autoritaet vor dem Aufruf, plus SQLite-Bindungsspeicher nach dem durablen Effect-Start. Recovery liest Provider-Identitaet und Keyring aus dem gespeicherten Record, nicht vom Aufrufer. | `ProviderObservationAuthority`, `ProviderObservationBindingRecord`, `ProviderObservationBindingLedger`, `issue_provider_observation_authority`, `verify_provider_observation_authority`, `observation_keyring_digest`, `ProviderObservationAuthorityStateError` |
| [observation_store.py](../../../daedalus/runtimes/provider/observation_store.py) | Vorab bereitgestellter Store: Schema-Publikation wird von gewoehnlicher Ledger-Konstruktion getrennt. Replay liest mit SQLite `mode=ro` und `query_only`; ein Writer darf eine fehlende Datenbank niemals anlegen oder reparieren. | `initialize_provider_observation_binding_store`, `inspect_provider_observation_binding_store`, `ProviderObservationStoreTarget`, `ProviderObservationStoreStatus`, `PreprovisionedProviderObservationBindingLedger`, `ProviderObservationStoreError` |
| [observation_store_contract.py](../../../daedalus/runtimes/provider/observation_store_contract.py) | Signierter, kurzlebiger Guard-Kontrakt fuer Store-Operationen: bindet Store-Ziel, isolierten Pfad, lokalen Filesystem-Write-Effekt und den persistierten `EffectLease`-Digest. Oeffnet selbst kein SQLite. | `build_provider_observation_store_operation_subject`, `issue_provider_observation_store_operation_authority`, `verify_provider_observation_store_operation_authority`, `authorize_provider_observation_store_operation`, `ProviderObservationStoreOperationSubject`, `ProviderObservationStoreOperationAuthority`, `ProviderObservationStoreContractExpired` |

### target_* — Verifikation, Quittung, Retention

| Modul | Was es tut | Wichtige oeffentliche Symbole |
| --- | --- | --- |
| [target_verification_contracts.py](../../../daedalus/runtimes/provider/target_verification_contracts.py) | Die inerten Quittungstypen fuer die Quellverifikation. | `ProviderExecutableTargetVerificationReceipt`, `VerifiedPythonTarget`, `ProviderTargetVerificationSourceError`, `ProviderTargetVerificationSignatureError`, `ProviderTargetVerificationBindingError` |
| [target_verification.py](../../../daedalus/runtimes/provider/target_verification.py) | Parst CAS-gestuetzte Python-Quellbytes mit `ast`, ohne sie zu importieren oder auszufuehren, und signiert das Ergebnis. | `issue_provider_target_verification_receipt`, `verify_provider_target_verification_receipt` |
| [target_receipt_ledger.py](../../../daedalus/runtimes/provider/target_receipt_ledger.py) | Restart-sichere Aufbewahrung: Intent in den kanonischen Event Store, dann exakte Quittungsbytes in das bestehende CAS, dann Abschluss zurueck in den Event Store. Fassade ueber `SpineLedger` und `SourceTreeStore`. | `ProviderTargetReceiptLedger`, `ProviderTargetReceiptRetentionResult`, `ProviderTargetReceiptRetentionReplay`, `ProviderTargetReceiptRetentionStateError`, `ProviderTargetReceiptRetentionBindingError` |
| [target_receipt_retention_contract.py](../../../daedalus/runtimes/provider/target_receipt_retention_contract.py) | Signierter Guard-Kontrakt fuer die Retention; inert, bindet Lease und Inventar-Identitaeten. | `build_provider_target_receipt_retention_operation_subject`, `issue_provider_target_receipt_retention_operation_authority`, `verify_provider_target_receipt_retention_operation_authority`, `authorize_provider_target_receipt_retention_operation`, `ProviderTargetReceiptRetentionOperationSubject`, `ProviderTargetReceiptRetentionContractExpired` |
| [target_receipt_retention_preflight.py](../../../daedalus/runtimes/provider/target_receipt_retention_preflight.py) | Read-only-Preflight: Guard-Autoritaet, Live-HEAD-Quittung und frisch gebautes Retention-Write-Inventar muessen sich auf *eine* aktuelle Revision einigen. | `verify_provider_target_receipt_retention_preflight`, `ProviderTargetReceiptRetentionPreflightReceipt`, `ProviderTargetReceiptRetentionPreflightBindingError` |
| [target_receipt_retention_admission.py](../../../daedalus/runtimes/provider/target_receipt_retention_admission.py) | Spielt den Preflight nach, authentifiziert die persistierte Nicht-Runtime-`EffectLease` ueber die query-only Replay-Projektion und beweist, dass alle geschuetzten Filesystem-Ziele konkret und disjunkt bleiben. Ein `STARTED` wird gemeldet, nie automatisch wiederholt. | `verify_provider_target_receipt_retention_admission`, `ProviderTargetReceiptRetentionAdmissionReceipt`, `ProviderTargetReceiptRetentionAdmissionBindingError` |
| [target_receipt_retention_recovery.py](../../../daedalus/runtimes/provider/target_receipt_retention_recovery.py) | Reine Restart- und Replay-Entscheidung aus einer Admission-Quittung. `not_started` verlangt frische Autorisierung, `started` verlangt externe Rekonziliation, terminale Zustaende bleiben terminal. | `decide_provider_target_receipt_retention_recovery`, `ProviderTargetReceiptRetentionRecoveryDecision`, `ProviderTargetReceiptRetentionRecoveryShapeError` |
| [target_receipt_retention_completed_evidence.py](../../../daedalus/runtimes/provider/target_receipt_retention_completed_evidence.py) | Liest Event Store und Quittungs-CAS live nach, authentifiziert die aufbewahrte Verification-Quittung erneut und prueft Datei-Identitaeten um jeden Lesevorgang herum. | `verify_provider_target_receipt_retention_completed_evidence`, `ProviderTargetReceiptRetentionCompletedEvidenceReceipt` |
| [target_receipt_retention_effect_terminal_evidence.py](../../../daedalus/runtimes/provider/target_receipt_retention_effect_terminal_evidence.py) | Bindet die abgeschlossene Retention an die persistierte `COMPLETED`-Effect-Ausfuehrung: zwei query-only Replay-Projektionen, die SQLite-Identitaet als Fence um beide Lesevorgaenge. | `verify_provider_target_receipt_retention_effect_terminal_evidence`, `ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt` |

### runtime_*_binding — die Kompositionen kurz vor dem Effekt

| Modul | Was es tut | Wichtige oeffentliche Symbole |
| --- | --- | --- |
| [runtime_executable_binding.py](../../../daedalus/runtimes/provider/runtime_executable_binding.py) | Authentifiziert die Observation-Autoritaet, revalidiert die registrierten Executable-Objekte und beweist, dass beide dasselbe Runtime- und Effekt-Subjekt beschreiben. | `bind_provider_runtime_executable`, `ProviderRuntimeExecutableBindingReceipt`, `ProviderRuntimeExecutableBindingMismatch`, `ProviderRuntimeExecutableBindingShapeError` |
| [runtime_invocation_binding.py](../../../daedalus/runtimes/provider/runtime_invocation_binding.py) | Fuegt das signierte Per-Call-ABI und die Executable-Evidenz zusammen, ohne ein drittes Quittungsschema einzufuehren. | `bind_provider_runtime_invocation`, `ProviderRuntimeInvocationBindingMismatch`, `ProviderRuntimeInvocationBindingShapeError` |

## Trust-Grenzen / Effekte

Das Paket ist fast vollstaendig *nicht-ausfuehrend*. Nahezu jedes Modul sagt das
in seinem eigenen Docstring, und der Satz ist woertlich gemeint: kein
`begin_effect`, kein Provider-Aufruf, keine Promotion.

- **Der einzige Ausfuehrungspfad** ist die Methode `_execute_sealed_operation`
  von `ProviderExecutableObjectRegistry` in
  [executable_object_registry.py](../../../daedalus/runtimes/provider/executable_object_registry.py).
  Sie verlangt exakte Typen fuer `RuntimeBoundEffectAuthorization`,
  `EffectExecutionRequest` und `LeasedEffectStartReceipt`, vergleicht zehn
  Subjektfelder, ruft `authorization.verify()` und besteht darauf, dass der
  Effect-Ledger fuer diese Execution-ID `STARTED` meldet. Erst danach laeuft
  die versiegelte Operation. Kein vom Aufrufer gewaehltes Callable ueberquert
  diese Naht; scheitert die Output-Evidenz nach dem Aufruf, wird
  `ProviderSealedOutputEvidenceError` geworfen statt still weiterzumachen.
- **Die Writer** sind zwei: `ProviderTargetReceiptLedger.retain` (Event Store
  und CAS) und `ProviderObservationBindingLedger.bind_start` (SQLite-Bindung
  nach dem durablen Effect-Start). `initialize_provider_observation_binding_store`
  schreibt einmalig das Schema; der `PreprovisionedProviderObservationBindingLedger`
  legt bewusst nie eine Datenbank an und repariert keine.
- **`begin_effect` selbst liegt nicht hier.** Der Aufrufer ist
  [broker.py](../../../daedalus/runtimes/broker.py); dieses Paket liefert nur
  die Vorbedingungen. Recovery laeuft ueber
  [recovery.py](../../../daedalus/runtimes/recovery.py), das die
  Observation-Bindung liest.
- **Read-only mit Nachweis:** Retention-Admission und die beiden
  Evidence-Verifier oeffnen SQLite mit `query_only` und fencen die konkrete
  Datei-Identitaet um jeden Lesevorgang. Symlinks in geschuetzten Pfaden werden
  abgelehnt, ueberlappende Wurzeln ebenso.
- **Signaturen** sind durchgehend HMAC-SHA256 ueber einen kanonischen Digest aus
  [`canonical_sha`](../../../daedalus/spine/envelope.py); die Keyrings werden
  ueber die Normalisierung in
  [observation.py](../../../daedalus/runtimes/provider/observation.py)
  vereinheitlicht. Kein Modul haelt ein Secret; alle nehmen es als Argument.
- **Kanonische Feldpruefung** kommt aus
  [kernel/contracts/base.py](../../../daedalus/kernel/contracts/base.py)
  (`_identifier`, `_revision`, `_sha256`, `_repo_path`, `_utc_timestamp`), nicht
  aus lokalen Regexen — eine Identitaetsdefinition, nicht 26.

Damit erfuellt das Paket Masterplan-Invariante 8 (Effekte an Effektgrenzen,
nicht in Prompts) und Invariante 3 (ein Kandidat kann seinen Evaluator nicht
veraendern) strukturell statt per Zusicherung. Siehe
[Kernel](kernel.md), [Kernel-Kontrakte](kernel-contracts.md) und
[Spine](spine.md).

## Tests

64 Testdateien unter `tests/runtimes/` heissen `test_provider_*.py`
(gemessen 2026-09-05); die meisten Module haben ein Paar aus Funktionstest und
`_review`-Test, einige zusaetzlich einen `_hardening`-Test.

- Die invocation-Kette:
  [subject](../../../tests/runtimes/test_provider_invocation_subject.py)
  ([review](../../../tests/runtimes/test_provider_invocation_subject_review.py)),
  [registry](../../../tests/runtimes/test_provider_invocation_registry.py)
  ([review](../../../tests/runtimes/test_provider_invocation_registry_review.py)),
  [authority](../../../tests/runtimes/test_provider_invocation_authority.py)
  ([review](../../../tests/runtimes/test_provider_invocation_authority_review.py)),
  [identity](../../../tests/runtimes/test_provider_invocation_identity.py)
  ([review](../../../tests/runtimes/test_provider_invocation_identity_review.py)),
  [payload](../../../tests/runtimes/test_provider_invocation_payload.py)
  ([review](../../../tests/runtimes/test_provider_invocation_payload_review.py)),
  [resolution](../../../tests/runtimes/test_provider_invocation_resolution.py)
  ([review](../../../tests/runtimes/test_provider_invocation_resolution_review.py)),
  [abi](../../../tests/runtimes/test_provider_invocation_abi.py)
  ([review](../../../tests/runtimes/test_provider_invocation_abi_review.py)).
- Die executable-Kette:
  [targets](../../../tests/runtimes/test_provider_executable_targets.py)
  ([review](../../../tests/runtimes/test_provider_executable_targets_review.py)),
  [structure](../../../tests/runtimes/test_provider_executable_structure.py)
  ([review](../../../tests/runtimes/test_provider_executable_structure_review.py)),
  [pre admission](../../../tests/runtimes/test_provider_executable_pre_admission.py)
  ([review](../../../tests/runtimes/test_provider_executable_pre_admission_review.py)),
  [object registry](../../../tests/runtimes/test_provider_executable_object_registry.py)
  ([review](../../../tests/runtimes/test_provider_executable_object_registry_review.py)).
- Observation:
  [authority](../../../tests/runtimes/test_provider_observation_authority.py)
  ([review](../../../tests/runtimes/test_provider_observation_authority_review.py)),
  [store](../../../tests/runtimes/test_provider_observation_store.py)
  ([review](../../../tests/runtimes/test_provider_observation_store_review.py)),
  [store contract](../../../tests/runtimes/test_provider_observation_store_contract.py)
  ([review](../../../tests/runtimes/test_provider_observation_store_contract_review.py)).
- Target und Ledger:
  [verification](../../../tests/runtimes/test_provider_target_verification.py)
  ([review](../../../tests/runtimes/test_provider_target_verification_review.py),
  [hardening](../../../tests/runtimes/test_provider_target_verification_hardening.py)),
  [receipt ledger](../../../tests/runtimes/test_provider_target_receipt_ledger.py)
  ([review](../../../tests/runtimes/test_provider_target_receipt_ledger_review.py),
  [hardening](../../../tests/runtimes/test_provider_target_receipt_ledger_hardening.py)).
- Retention:
  [contract](../../../tests/runtimes/test_provider_target_receipt_retention_contract.py)
  ([review](../../../tests/runtimes/test_provider_target_receipt_retention_contract_review.py)),
  [preflight](../../../tests/runtimes/test_provider_target_receipt_retention_preflight.py)
  ([review](../../../tests/runtimes/test_provider_target_receipt_retention_preflight_review.py)),
  [admission](../../../tests/runtimes/test_provider_target_receipt_retention_admission.py),
  [recovery](../../../tests/runtimes/test_provider_target_receipt_retention_recovery.py)
  ([review](../../../tests/runtimes/test_provider_target_receipt_retention_recovery_review.py),
  [hardening](../../../tests/runtimes/test_provider_target_receipt_retention_recovery_hardening.py)),
  [completed evidence](../../../tests/runtimes/test_provider_target_receipt_retention_completed_evidence.py)
  ([review](../../../tests/runtimes/test_provider_target_receipt_retention_completed_evidence_review.py),
  [hardening](../../../tests/runtimes/test_provider_target_receipt_retention_completed_evidence_hardening.py)),
  [effect terminal evidence](../../../tests/runtimes/test_provider_target_receipt_retention_effect_terminal_evidence.py)
  ([review](../../../tests/runtimes/test_provider_target_receipt_retention_effect_terminal_evidence_review.py),
  [hardening](../../../tests/runtimes/test_provider_target_receipt_retention_effect_terminal_evidence_hardening.py),
  [schema](../../../tests/runtimes/test_provider_target_receipt_retention_effect_terminal_evidence_schema.py)).
- Bindings:
  [executable](../../../tests/runtimes/test_provider_runtime_executable_binding.py)
  ([review](../../../tests/runtimes/test_provider_runtime_executable_binding_review.py)),
  [invocation](../../../tests/runtimes/test_provider_runtime_invocation_binding.py)
  ([review](../../../tests/runtimes/test_provider_runtime_invocation_binding_review.py)).
- Uebergreifend:
  [test_runtime_provider_broker.py](../../../tests/runtimes/test_runtime_provider_broker.py),
  [test_runtime_provider_recovery.py](../../../tests/runtimes/test_runtime_provider_recovery.py),
  [test_runtime_provider_exact_authority_boundary.py](../../../tests/runtimes/test_runtime_provider_exact_authority_boundary.py),
  [test_runtime_provider_post_invoke_unknown.py](../../../tests/runtimes/test_runtime_provider_post_invoke_unknown.py),
  [tests/contracts/test_provider_runtime_mutation_specs.py](../../../tests/contracts/test_provider_runtime_mutation_specs.py),
  [tests/contracts/test_import_scc_hierarchy.py](../../../tests/contracts/test_import_scc_hierarchy.py)
  (die Zusammenhangskomponente, die dieses Subpaket begruendet hat), sowie die
  Gate-Inventare
  [test_provider_observation_persistence_inventory.py](../../../tests/gates/test_provider_observation_persistence_inventory.py)
  und
  [test_provider_target_receipt_retention_inventory.py](../../../tests/gates/test_provider_target_receipt_retention_inventory.py).

## Verwandt

- [Runtimes](runtimes.md) — das umgebende Paket mit Broker, Trust-Store und Fault-Matrix.
- [Runtimes / Providers](runtimes-providers.md) — der Katalog (Plural), nicht die Handlung.
- [Runtimes / Contracts](runtimes-contracts.md) — `RepositoryHeadRevisionReceipt`, `PythonTargetStructure`, Ports.
- [Runtimes / Admission](runtimes-admission.md), [Runtimes / Execution](runtimes-execution.md).
- [Kernel](kernel.md), [Kernel-Kontrakte](kernel-contracts.md), [Kernel-Events](kernel-events.md), [Kernel-Policy](kernel-policy.md).
- [Spine](spine.md) — Event Store, Envelope, Effect Boundary.
- [Gates](gates.md), [Gates / Repository](gates-repository.md) — die Gate-0-Inventare, die dieses Paket zaehlen.
- [Council](council.md) — der andere Ort mit Vendor-Aufrufen, dort aber ohne Effekt-Autoritaet.
- [Observation layer](observation-layer.md) — die Form eines beobachteten Objekts, nie sein Wert.
- [Wiki-Index](../index.md), [Tool vetting](../tool-vetting.md).

## Ungeklaert

- **Wo genau der Broker die Kette abschliesst.**
  [broker.py](../../../daedalus/runtimes/broker.py) importiert sieben dieser
  Module; ob die vollstaendige Kette (Preflight, Admission, Pre-Admission,
  Objekt-Registry, Binding, `begin_effect`) heute in *einem* Live-Pfad
  durchlaeuft oder ob Teile nur in Tests komponiert werden, ist aus diesem
  Verzeichnis allein nicht ablesbar. Siehe [Runtimes](runtimes.md).
- **Der versiegelte Subprozess-Klon.** In `executable_object_registry.py` bauen
  die internen Helfer fuer Windows und POSIX eine eigene, von `subprocess`
  abgekoppelte Prozessstart-Implementierung nach. Warum der Klon noetig ist,
  statt `subprocess` zu versiegeln, steht im Modul nur implizit; die genaue
  Bedrohungsannahme ist nicht dokumentiert.
- **Uneinheitliche Fehlerbasen.** Die meisten Fehlerklassen erben von
  `RuntimeError`, `ProviderInvocationSubjectError` und
  `ProviderInvocationPayloadError` dagegen von `ValueError`. Ob das die
  Unterscheidung Wertfehler gegen Zustandsfehler kodiert oder historisch ist,
  sagt der Code nicht.
- **Ablaufzeiten der Guard-Kontrakte.** `ProviderObservationStoreContractExpired`
  und `ProviderTargetReceiptRetentionContractExpired` existieren, aber die
  kanonische Gueltigkeitsdauer wird vom Aufrufer gesetzt; ein
  repositoryweiter Standardwert war hier nicht auffindbar.

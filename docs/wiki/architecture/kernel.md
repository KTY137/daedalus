---
title: Kernel
type: module
status: living
updated: 2026-09-05
covers: daedalus/kernel
---
# Kernel

`daedalus/kernel` ist der Trust- und Runtime-Kern von Daedalus: die Schicht, in
der ein Vorhaben zu einer autorisierten Handlung wird und eine Handlung zu
zurueckbehaltener Evidenz. Masterplan-Abschnitt 3 nennt sie die "canonical
Mission / Policy / Execution / Evidence spine", und Invariante 1 verlangt, dass
es davon genau eine gibt. Die Reihenfolge, die dieses Verzeichnis durchsetzt,
ist immer dieselbe:

`Policy-Entscheidung -> EffectLease -> begin_effect -> Effekt -> Terminal-Record -> Evidence -> Nominierung -> Owner-Freigabe -> Promotion`

Jede Stufe ist ein eigenes Modul, jede kann verweigern, und keine kann die
naechste ueberspringen. Was hier **nicht** passiert, steht in den Docstrings
genauso deutlich: `campaigns.py` "schedules nothing and promotes nothing",
`effects.py` ist "deliberately inert with respect to real effects",
`contracts/canonical.py` ist "a schema and digest boundary, not an effect
boundary".

Gemessen 2026-09-05: 29 `.py`-Dateien direkt in `daedalus/kernel`, 18751
Zeilen. Die drei Unterpakete haben eigene Seiten:
[Kernel-Vertraege](kernel-contracts.md), [Kernel-Events](kernel-events.md) und
[Kernel-Policy](kernel-policy.md).

## Aufbau

Das Paket zerfaellt in sechs Verantwortungen. `__init__.py` ist eine lazy
Kompatibilitaets-Fassade, kein Besitzer: `_EXPORT_GROUPS` bildet die
historischen Wurzel-Reexporte auf ihr Eigentuemer-Modul ab und laedt dieses erst
bei Zugriff. Der Docstring betont, dass die Reihenfolge in `__all__` selbst ein
Kompatibilitaetsvertrag ist, weshalb Eigentuemer-Namen wiederholt vorkommen.

### Identitaet und Artefakte

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`artifacts.py`](../../../daedalus/kernel/artifacts.py) | Die eine mechanische Implementierung inhaltsadressierter Identitaet: Locator-Form, kanonische JSON-Ablage, deterministischer Dateibaum-Digest. Enthaelt ausdruecklich keine Domaenen-Policy. | `ArtifactRef`, `artifact_locator`, `store_canonical_json`, `digest_file_tree`, `ARTIFACT_LOCATOR_PREFIX`, `ArtifactIdentityError` |
| [`source_trees.py`](../../../daedalus/kernel/source_trees.py) | Begrenzte, inhaltsadressierte Quellbaeume fuer isolierte Attempts. Erweitert die Identitaetsgrenze aus `artifacts.py`, definiert keine zweite. Materialisiert nur in ein *neues* Ziel. | `SourceTreeStore`, `SourceTreeManifest`, `SourceTreeEntry`, `StoredSourceTree`, `SourceTreeStoreError`, `SourceTreeCaptureError`, `SourceTreeCorruptionError`, `MANDATORY_IGNORED_ROOTS` |
| [`interpreter.py`](../../../daedalus/kernel/interpreter.py) | Die eine gemeinsame Aufloesung des Interpreters fuer stdlib-only Payloads unter `-I -S`, plus pfadfreie Interpreter-Provenienz. | `stdlib_interpreter`, `resolve_python_argv`, `interpreter_provenance` |

`interpreter.py` ist ein gutes Beispiel dafuer, wie in diesem Baum gemessene
Umgebungsfakten dokumentiert werden. Der Docstring haelt fest: auf dem
Windows-11-Host des Owners ist `sys.executable` in einer venv ein
Launcher-Stub, der unter dem bewusst auf NULL gesetzten stdin der Containment-
Schicht eine Warnzeile in das zusammengefuehrte Gate-Log druckt — woran jedes
Gate scheitert, dessen Vertrag exakte Ausgabe ist. Die Aufloesung ist deshalb
eine Eigenschaft des *Payloads*, nicht des Gates, und wird ausdruecklich nicht
in `command_gate` angewandt: Quittungen werden gegen genau die argv geprueft,
die ein Gate bekommen hat, also darf ein Gate nie eine Ersatz-argv ausfuehren.
Die Provenienz ist pfadfrei (Version, Implementierung, Plattform, Binaer-Hash),
weil Quittungen die Maschine verlassen und ein absoluter Pfad das Benutzerprofil
mittraegt.

### Effekt-Leases

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`effects.py`](../../../daedalus/kernel/effects.py) | Die persistierte, scope-begrenzte Effekt-Lease. Validiert eine Anforderung gegen genau eine Policy-Entscheidung und genau eine Registry-Revision und gibt ein Ausfuehrungs-Flag zurueck, das Replay daran hindert, einen zweiten Effekt auszuloesen. | `EffectLeaseLedger`, `LeasedEffectAuthorization`, `EffectExecutionRequest`, `LeasedEffectStartReceipt`, `EffectStartResult`, `EffectTerminalReceipt`, `issue_effect_lease`, `verify_effect_lease`, `EffectLeaseError`, `EffectLeaseSignatureError`, `EffectLeaseExpired`, `EffectLeaseBindingMismatch`, `EffectLeaseScopeError`, `EffectLeaseReplay`, `EffectLeaseStateError`, `EffectLeaseConcurrencyError` |
| [`offload_lease.py`](../../../daedalus/kernel/offload_lease.py) | Der Aussteller: fuer welche Registry-Zeilen er eine Lease ausstellen darf und warum. Groesste Datei des Pakets (3749 Zeilen). Dazu Containment-Ableitung, Write-Policy, Egress-Beobachtung und die Retentions-Pflichten. | `acquire_effect_lease`, `acquire_wave_offload_lease`, `acquire_attempt_lease`, `acquire_chip_eda_lease`, `issuable_row`, `WaveLeaseDenied`, `WaveLeaseKillSwitchEngaged`, `ISSUER_CONTRACTS`, `ISSUER_EFFECTS`, `EFFECT_BOUNDS`, `ENTRYPOINT_ID`, `ATTEMPT_ENTRYPOINT_ID`, `control_root`, `lease_ledger_path`, `write_evidence_root`, `resolve_write_policy`, `derive_wave_containment`, `record_effect_lease_subject`, `record_effect_lease_execution`, `require_retained_effect_lease_start_records`, `require_retained_effect_lease_terminal_record`, `emit_effect_lease_terminal_record`, `record_primary_checkout_disjointness` |
| [`authorization.py`](../../../daedalus/kernel/authorization.py) | Strikte Faehigkeits-Fassade fuer nicht-runtime-gebundene Leases. Haelt schaerfere Konstruktionsinvarianten fuer neu migrierte Einstiege, stellt selbst keine Lease aus. | `NonRuntimeEffectAuthorization` |
| [`runtime_effects.py`](../../../daedalus/kernel/runtime_effects.py) | Bindet eine signierte Lease an genau einen authentifizierten, aktiven Runtime-Trust-Record und prueft ihn vor Grant **und** vor Ausfuehrungsstart erneut. | `RuntimeBoundEffectLease`, `RuntimeBoundEffectAuthorization`, `issue_runtime_bound_effect_lease`, `verify_runtime_bound_effect_lease`, `RuntimeLeaseAdmissionError`, `RuntimeLeaseSignatureError`, `RuntimeLeaseBindingMismatch` |
| [`effect_replay.py`](../../../daedalus/kernel/effect_replay.py) | Strikte, rein lesende Projektion ueber persistierte Ausfuehrungszeilen. Oeffnet die SQLite-Datei mit `mode=ro` und `query_only=ON`. | `inspect_effect_execution`, `EffectExecutionReplaySnapshot`, `PersistedEffectLeaseSubject`, `EffectReplayProjectionError` |
| [`runtime_effect_replay.py`](../../../daedalus/kernel/runtime_effect_replay.py) | Dasselbe fuer runtime-gebundene Ausfuehrungen; komponiert beide Autoritaeten zum zurueckbehaltenen Startzeitpunkt. | `inspect_runtime_effect_execution`, `RuntimeEffectExecutionReplaySnapshot`, `RuntimeEffectReplayProjectionError` |
| [`effect_recovery.py`](../../../daedalus/kernel/effect_recovery.py) | Authentifizierte Abstimmung fuer extern quittierte, unbekannt ausgegangene Effekte. | `reconcile_unknown_effect`, `ExternalEffectObservation`, `EffectRecoveryResult`, `issue_external_effect_observation`, `verify_external_effect_observation`, `EffectRecoveryError`, `EffectRecoverySignatureError`, `EffectRecoveryBindingError`, `EffectRecoveryStateError` |

Der interessanteste Entwurf steckt in `issuable_row`. Frueher war der Aussteller
auf genau eine Registry-Zeile konstant verdrahtet, mit der Begruendung, "a
helper that can issue for whichever entrypoint you name is a general-purpose
capability minter". Der Docstring haelt den gemessenen Preis fest: 93 von 97
Zeilen wurden abgelehnt, ohne zu sagen, was an ihnen falsch war. Das Praedikat
formuliert die eigentliche Anforderung als fuenf Konjunkte — Zeile registriert,
Wiring `CENTRAL`, nicht runtime-tragend, jeder deklarierte Vertrag in
`ISSUER_CONTRACTS`, jeder deklarierte Effekt in `ISSUER_EFFECTS` und mindestens
einer. Es wirft nie: eine Ablehnung ist ein Urteil ueber eine Anfrage, das der
Aufrufer in eine kanonische Deny-Quittung verwandelt.
`acquire_wave_offload_lease` bleibt die gepinnte Tuer und **verweigert** ein
`entrypoint_id`-Schluesselwort, damit kein Aufrufer sich seine Faehigkeit
aussuchen kann.

### Attempts

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`attempts.py`](../../../daedalus/kernel/attempts.py) | Kompatibilitaets-Oberflaeche. Buendelt die nach Verantwortung aufgeteilte Implementierung unter dem historischen Importpfad. | `AttemptLedger`, `IsolatedAttemptCoordinator` und die Vertragsnamen |
| [`attempt_contracts.py`](../../../daedalus/kernel/attempt_contracts.py) | Vertraege und gemeinsame Invarianten des Attempt-Lebenszyklus. | `AttemptStartRecord`, `AttemptTerminalReceipt`, `AttemptCompletion`, `AttemptBeginResult`, `PreparedAttempt`, `AttemptLifecycleError`, `AttemptBindingMismatch`, `AttemptReplay`, `AttemptStateError`, `AttemptWorkspaceError` |
| [`attempt_ledger.py`](../../../daedalus/kernel/attempt_ledger.py) | Die Event-Store-Fassade fuer neustartsichere Attempts; erzwingt das Gate-0-Durability-Profil. | `AttemptLedger` |
| [`attempt_workspace.py`](../../../daedalus/kernel/attempt_workspace.py) | Checkout-externe Workspace-Vorbereitung, inklusive Disjunktheits-Pruefung gegen den primaeren Checkout. | `IsolatedAttemptCoordinator` |
| [`attempt_clock.py`](../../../daedalus/kernel/attempt_clock.py) | Vertrauenswuerdige, monoton nicht fallende UTC-Uhr. Nimmt keine Aufrufer-Zeit an. | `AttemptLifecycleClock` |
| [`attempt_spine_reader.py`](../../../daedalus/kernel/attempt_spine_reader.py) | Strikte Leseprojektion ueber die Event-Store-Zeilen eines Attempts. | `read_attempt_intents` |
| [`attempt_execution.py`](../../../daedalus/kernel/attempt_execution.py) | Der Lebenszyklus-Kern (2846 Zeilen): Storage, Intent, Worktree, Runner, Patch, Gates, Aufloesung, Aufraeumen. | `TaskAttempt`, `TaskSpec`, `RunnerContext`, `AttemptResult`, `GateResult`, `PatchArtifact`, `offload_runner`, `pytest_gate_argv`, `OffloadPort`, `AttemptWorkspacePort`, `AttemptEvaluatorPort`, `AttemptPortMissing`, `TaskSpecInvalid`, `GitCommandError` |

`attempt_execution.py` formuliert die Naht in einem Satz: der Loop braucht
genau *eine* Naht zwischen "wir haben entschieden, das zu versuchen" und "hier
ist ein Patch, den ein Mensch promoten darf", und diese Naht muss crash-sicher
sein und den Arbeitsbaum des Entwicklers nicht anfassen koennen. Der Intent
wird vor dem ersten externen Effekt ins Ledger committet, damit ein Crash nie
einen Worktree oder Branch hinterlaesst, den das Ledger nicht beabsichtigt hat.
Der `effect_key` ist absichtlich der Kandidaten-Branchname — ein Token, nach dem
man hinterher suchen kann.

Der Docstring nennt auch eine bewusste Unfaehigkeit: dieses Modul "deliberately
cannot discover a Kairos workspace manager or an evaluator". Beide Faehigkeiten
kommen ueber neutrale Ports (`AttemptWorkspacePort`, `AttemptEvaluatorPort`)
herein. Ohne komponierte Ports schlaegt der Aufruf mit `AttemptPortMissing`
fehl, bevor Workspace oder Evaluator angefasst werden — Invariante 3 als
Importgrenze.

`attempt_clock.py` beschreibt ein subtiles gemessenes Problem: der Event Store
stempelt seine Zeilen selbst, waehrend die monotone Projektion einen
Wall-Anker fortschreibt, den der Host-Timer beim Sampling quantisiert hat. Die
Projektion laeuft dem Event Store deshalb um bis zu einen Timer-Tick voraus,
und eine Beobachtung *vor* der Zeile, die sie aufzeichnet, wuerde von den
Attempt-Guards korrekt abgelehnt. Die Klammerung bewegt eine Beobachtung nur
rueckwaerts zur Wall-Clock; die Minimum- und Letzte-Beobachtung-Boeden greifen
danach, sodass die Anti-Rollback-Garantie gewinnt.

### Kampagnen und Evidenz

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`campaigns.py`](../../../daedalus/kernel/campaigns.py) | Neustartsicherer Kampagnen-Lebenszyklus ueber CAS und Event-Spine: einen Experiment-Spec einfrieren, genau einen dauerhaften Start aufzeichnen, genau eine Terminal-Quittung behalten. | `begin_campaign`, `complete_campaign`, `fail_campaign`, `lookup_campaign_read_only`, `verify_campaign_chain`, `campaign_contract_for_spec`, `store_contract`, `load_experiment_spec`, `load_campaign_contract`, `load_campaign_receipt`, `load_nomination_receipt`, `load_attempt_contract`, `load_attempt_receipt`, `load_evidence_packet`, `CampaignBeginResult`, `CampaignReplayResult`, `CampaignLifecycleError`, `CampaignAlreadyTerminal`, `CampaignPendingReconciliation`, `CampaignIdentityConflict` |
| [`fourfold_evidence.py`](../../../daedalus/kernel/fourfold_evidence.py) | Bindet einen kompilierten Fourfold-Snapshot in die Gate-0-Evidenzkette. Projiziert, kompiliert nicht. | `assemble_fourfold_evidence_packet`, `assemble_fourfold_nomination_receipt`, `verify_fourfold_evidence_packet`, `verify_fourfold_nomination_receipt`, `resolve_fourfold_snapshot_bytes`, `FourfoldEvidenceExpectation`, `FourfoldEvidenceMismatch`, `FourfoldEvidenceUnstorable` |
| [`runtime_conformance.py`](../../../daedalus/kernel/runtime_conformance.py) | Inhaltsadressierte Offline-Konformanz-Evidenz. Traut einem Runtime-Manifest nicht: der Aufrufer muss pro Fixture-Check eine aufgezeichnete Beobachtung liefern. | `assemble_recorded_conformance`, `persist_conformance_receipt`, `verify_current_conformance`, `RecordedObservation`, `RuntimeConformanceError` |

`fourfold_evidence.py` traegt eine der ehrlichsten Notizen des Baums. Bis zum
22. August 2026 beanspruchte das Modul einen Evidenz-Locator, ohne die Bytes
irgendwo abzulegen — formal gueltig und in keinem Store aufloesbar. Die Messung
steht im Docstring: von der letzten Gate-1-Quittung vor der Korrektur loesten
sechs von sieben Evidenz-Locatoren im Mission-Store auf, der Fourfold-Locator
nicht. Seitdem schreibt das Modul genau eine Sache: die kanonischen Bytes des
Snapshots.

### Promotion

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`promotion.py`](../../../daedalus/kernel/promotion.py) | Die versiegelte Promotions-Autorisierung. Beweist, dass eine owner-signierte Freigabe, ein bestandenes Evidence-Paket, die exakte geordnete Kandidaten-Charge und der *lebende* Ziel-HEAD dasselbe unveraenderliche Subjekt benennen. | `authorize_promotion`, `authorize_persisted_promotion`, `snapshot_promotion_candidates`, `candidate_batch_sha256`, `resolve_live_target_revision`, `PromotionAuthorization`, `PromotionCandidateSnapshot`, `PromotionAuthorizationError` |
| [`promotion_trust_root.py`](../../../daedalus/kernel/promotion_trust_root.py) | Die Trust-Wurzel: ein git-signierter Tag, verifiziert gegen eine Allowed-Signers-Datei aus dem **committeten** Baum. | `verify_promotion_approval`, `ApprovalVerdict`, `approval_tag_for`, `voided_by_regeneration`, `replay_key`, `claim_ledger_path`, `scrubbed_child_env`, `PromotionTrustRootError` |
| [`approvals.py`](../../../daedalus/kernel/approvals.py) | Der HMAC-Freigabe-Ledger: authentifizierte, einmalig verwendbare Owner-Freigaben und ihre atomar persistierte Konsumquittung. | `ApprovalLedger`, `issue_owner_approval`, `verify_owner_approval`, `VerifiedOwnerApproval`, `ConsumedOwnerApproval`, `ApprovalExpectation`, `ApprovalError`, `ApprovalSignatureError`, `ApprovalExpired`, `ApprovalBindingMismatch`, `ApprovalReplay`, `ApprovalStateError`, `main` |
| [`promotion_execution.py`](../../../daedalus/kernel/promotion_execution.py) | Persistierte Ausfuehrungs-Buchhaltung der Promotionsgrenze, mit bewusst anderen Namen als die Owner-Entscheidungsquittung. | `PromotionExecutionLedger`, `PromotionExecutionStart`, `PromotionExecutionReceipt`, `PromotionExecutionCompletion`, `PromotionExecutionBeginResult`, `PromotionExecutionError`, `PromotionExecutionBindingMismatch`, `PromotionExecutionReplay`, `PromotionExecutionStateError` |
| [`promotion_execution_reader.py`](../../../daedalus/kernel/promotion_execution_reader.py) | Strikte Nur-Lese-Projektion der Promotion-Zeilen; haelt rohen SQLite-Text lange genug, um doppelte JSON-Schluessel, nicht-endliche Konstanten und Digest-Substitution abzulehnen. | `read_promotion_execution_intents`, `PromotionExecutionReadError` |
| [`promotion_fingerprint.py`](../../../daedalus/kernel/promotion_fingerprint.py) | Nur-lesende Identitaet des primaeren Checkouts. Folgt keinem Symlink, akzeptiert nur regulaere Dateien und verlangt **zwei identische Beobachtungen**. | `fingerprint_primary_checkout`, `PrimaryCheckoutFingerprintError` |
| [`runtime_authorization_issuer.py`](../../../daedalus/kernel/runtime_authorization_issuer.py) | Lazy Kompatibilitaets-Fassade; der Runtime-Admission-Besitzer ist aus dem Kernel ausgezogen. | `acquire_runtime_bound_authorization`, `runtime_trust_ledger`, `runtime_trust_ledger_path`, `RUNTIME_AUTHORITY_KEY_ID`, `RUNTIME_LEASE_KEY_ID` |
| [`sandbox.py`](../../../daedalus/kernel/sandbox.py) | Explizite Docker-Sandbox-Policy plus fail-closed Start-Klassifikation. Kein Host-Fallback. | `DockerSandboxPolicy`, `SandboxMount`, `SandboxExecutionReceipt`, `run_in_docker_sandbox`, `SandboxPolicyError` |

Die Promotionsseite ist die Stelle, an der der Baum eine
Owner-Entscheidung woertlich abbildet. Entscheidung D5 waehlte "hybrid with B
as root": Wurzel ist der asymmetrische, git-signierte Tag, verifiziert mit
`git verify-tag` gegen eine Signer-Datei aus dem committeten Baum — faelschen
verlangt den privaten Schluessel des Owners. Der symmetrische HMAC-Ledger ist
ausdruecklich *degradiert*: "Advisory for the verdict, mandatory for the
record." Er darf eine Quittungszeile hinzufuegen, er darf nie gewaehren. Der
Docstring nennt sogar die Zahlen aus der Phase-0-Suite (23 PASS / 0 FAIL fuer
den Tag-Verifier, 19 PASS / 5 FAIL fuer HMAC) und, dass der Tag-Verifier auf
der Checkpoint-Linie null Produktions-Aufrufer hatte.

`promotion.py` ist der **einzige** kanonische Aufrufer der Trust-Wurzel, und
das ist mechanisch abgesichert: ein struktureller Test schlaegt fehl, wenn ein
zweites Modul die Wurzel erreicht, "because two callers of a trust root are two
promotion paths wearing one name".

`sandbox.py` behandelt einen Docker-CLI-Fehler nicht als Attempt-Ergebnis:
fehlende oder nicht ausfuehrbare Runtimes, Betriebssystem-Startfehler und
Docker-Exitcode 125 werden als `refused-before-start` dargestellt. Root-Dateisystem
read-only, genau ein beschreibbarer Bind-Mount, Netz aus, sofern kein expliziter
interner Proxy gewaehlt ist.

## Trust-Grenzen / Effekte

**Wer schreibt.** Der Kernel hat mehrere Writer, aber jeder ist benannt und in
[`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py)
registriert. Gemessen 2026-09-05 vier Zeilen mit Ziel in `daedalus.kernel`:

- `kernel.attempt.begin` → `AttemptLedger.begin`, Effekt `FILESYSTEM_WRITE`,
  Guard-Vertrag `spine.intent_ledger`, Wiring `LOCAL_GUARDS`, Anker
  `record_intent`;
- `kernel.attempt.complete` → `AttemptLedger.complete`, gleiche Effekte, Anker
  `mark_completed`;
- `kernel.attempt.prepare` → `IsolatedAttemptCoordinator.prepare`, zusaetzlich
  Guard-Vertrag `containment.attempt`;
- `cli.approvals` → `daedalus.kernel.approvals:main`, Wiring `CENTRAL`, Effekt
  ausschliesslich `SECRETS`.

Die drei Attempt-Zeilen stehen bewusst auf `LOCAL_GUARDS` statt `CENTRAL`; ihre
`migration`-Notiz nennt die Bedingung fuer den Upgrade: exakte persistierte
EffectLease, Runtime-Konformanz-Autoritaet und Docker-Sandbox-Faehigkeit.

Die `cli.approvals`-Notiz ist ein Beispiel fuer die im Repository verlangte
Ehrlichkeit: sie nennt den Signierschluessel-Einstieg mit Datei und Zeile und
markiert eine "MEASURED GAP" — die Ableitung des `SECRETS`-Effekts anderswo
beruht auf credential-foermigen Literalnamen, und diese Tuer nimmt den Namen als
Argument. Die Luecke wird benannt statt versteckt.

**Was read-only ist.** `effect_replay.py`, `runtime_effect_replay.py`,
`promotion_execution_reader.py`, `attempt_spine_reader.py` und
`promotion_fingerprint.py` sind ausdruecklich Projektionen. Zwei davon oeffnen
SQLite explizit mit `mode=ro` und `query_only=ON`. Der Grund ist im Docstring
von `effect_replay.py` genannt: die generische Lease-Autoritaet gibt beim
exakten Start-Replay `execute=False` zurueck, was einen zweiten Effekt
verhindert — aber die Startquittung allein unterscheidet nicht zwischen einer
noch laufenden Ausfuehrung und einem zurueckbehaltenen Terminalausgang.
Neustart-Komposition braucht deshalb einen Leser, der keinen Zustand erzeugen
kann.

**Wo Modelle nicht hinkommen.** Der Kernel importiert keinen Evaluator
(`AttemptEvaluatorPort` ist ein Protokoll), keine Provider-Bibliothek und keine
Promotion-Automatik. `runtime_conformance.py` traut einer Manifest-Deklaration
nicht, sondern verlangt aufgezeichnete Beobachtungen. Das ist Invariante 4
(Evidence-Boundary) als Modulstruktur.

**Was nirgends passiert.** Keine automatische Promotion. `promotion.py`
verweigert vor Lock-Erwerb, Worktree-Erzeugung, Branch-Erzeugung,
Ledger-Mutation und Git-Mutation, wenn Freigabe, Evidenz, Charge, Basisrevision,
Ziel-Ref und frisch aufgeloeste Zielrevision nicht exakt zusammenpassen
(Masterplan Revision 3, Punkt 1).

## Tests

Gemessen 2026-09-05 referenzieren 204 Dateien unter `tests/` das Paket; allein
`tests/kernel/` enthaelt 85 Testdateien. Nach Verantwortung:

- Leases und Autorisierung —
  [`tests/kernel/test_effect_leases.py`](../../../tests/kernel/test_effect_leases.py),
  [`tests/kernel/test_effect_authorization.py`](../../../tests/kernel/test_effect_authorization.py),
  [`tests/kernel/test_effect_lease_issuer_rule.py`](../../../tests/kernel/test_effect_lease_issuer_rule.py),
  [`tests/kernel/test_leased_offload.py`](../../../tests/kernel/test_leased_offload.py),
  [`tests/kernel/test_lease_authority_subject_split.py`](../../../tests/kernel/test_lease_authority_subject_split.py).
- Attempts —
  [`tests/kernel/test_isolated_attempt_lifecycle.py`](../../../tests/kernel/test_isolated_attempt_lifecycle.py),
  [`tests/kernel/test_isolated_attempt_lifecycle_adversarial.py`](../../../tests/kernel/test_isolated_attempt_lifecycle_adversarial.py),
  [`tests/kernel/test_isolated_attempt_time_tampering.py`](../../../tests/kernel/test_isolated_attempt_time_tampering.py),
  [`tests/kernel/test_attempt_durability_admission.py`](../../../tests/kernel/test_attempt_durability_admission.py).
- Replay und Recovery —
  [`tests/kernel/test_effect_replay_projection.py`](../../../tests/kernel/test_effect_replay_projection.py),
  [`tests/kernel/test_runtime_effect_replay_projection.py`](../../../tests/kernel/test_runtime_effect_replay_projection.py),
  [`tests/kernel/test_effect_recovery.py`](../../../tests/kernel/test_effect_recovery.py),
  [`tests/kernel/test_effect_recovery_hardening.py`](../../../tests/kernel/test_effect_recovery_hardening.py).
- Promotion —
  [`tests/kernel/test_sealed_promotion.py`](../../../tests/kernel/test_sealed_promotion.py),
  [`tests/kernel/test_promotion_execution.py`](../../../tests/kernel/test_promotion_execution.py),
  [`tests/kernel/test_promotion_execution_adversarial.py`](../../../tests/kernel/test_promotion_execution_adversarial.py),
  [`tests/kernel/test_promotion_fingerprint.py`](../../../tests/kernel/test_promotion_fingerprint.py),
  [`tests/kernel/test_owner_approval.py`](../../../tests/kernel/test_owner_approval.py),
  [`tests/kernel/test_live_promotion_seam.py`](../../../tests/kernel/test_live_promotion_seam.py).
- Evidenz und Konformanz —
  [`tests/kernel/test_fourfold_evidence.py`](../../../tests/kernel/test_fourfold_evidence.py),
  [`tests/kernel/test_fourfold_evidence_adversarial.py`](../../../tests/kernel/test_fourfold_evidence_adversarial.py),
  [`tests/kernel/test_runtime_conformance_harness.py`](../../../tests/kernel/test_runtime_conformance_harness.py).
- Sandbox —
  [`tests/kernel/test_docker_sandbox_policy.py`](../../../tests/kernel/test_docker_sandbox_policy.py),
  [`tests/kernel/test_docker_sandbox_launch_states.py`](../../../tests/kernel/test_docker_sandbox_launch_states.py).
- Struktur —
  [`tests/kernel/test_kernel_lazy_facade.py`](../../../tests/kernel/test_kernel_lazy_facade.py),
  [`tests/kernel/test_attempt_execution_hierarchy.py`](../../../tests/kernel/test_attempt_execution_hierarchy.py),
  [`tests/kernel/test_artifact_identity.py`](../../../tests/kernel/test_artifact_identity.py).

Auffaellig ist das Muster der `_review`-Dateien: zu vielen Kernmodulen gibt es
eine zweite Testdatei mit Suffix `_review`, die die unabhaengige Reviewstufe aus
Masterplan Abschnitt 10, Schritt 5, als ausfuehrbare Pruefung ablegt.

## Verwandt

- [Kernel-Vertraege](kernel-contracts.md) — die Draht-Sprache, die dieses Paket
  erzeugt und persistiert.
- [Kernel-Events](kernel-events.md) — das Intent-Ledger unter allen Writern.
- [Kernel-Policy](kernel-policy.md) — Ausfuehrungsgrenzen und Policy-Ableitung.
- [Spine](spine.md) — Effect-Registry, Containment, Kill-Switch.
- [Ariadne](ariadne.md) — der Kampagnen-Konsument.
- [Orchestrierung](orchestration.md) und
  [Orchestrierung Missions](orchestration-missions.md) — die Missionsseite ueber
  dem Kernel.
- [Runtimes](runtimes.md) und
  [Runtimes-Admission](runtimes-admission.md) — der ausgezogene
  Runtime-Trust-Besitzer.
- [Twin-Extraktoren](twin-extractors.md) und [Project Twin](twin.md) — die
  Quelle der Fourfold-Snapshots, die `fourfold_evidence.py` bindet.
- [Gates](gates.md) und [Gates-Repository](gates-repository.md) — HEAD-Bindung
  und Repository-Vertraege.
- [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Die drei Attempt-Registry-Zeilen stehen auf `LOCAL_GUARDS`.
  Ob die in ihrer `migration`-Notiz genannten Voraussetzungen inzwischen
  vorliegen und der Upgrade nur nicht vollzogen ist, laesst sich aus dem
  Verzeichnis nicht entscheiden.
- **Ungeklaert:** `attempts.py` und `attempt_contracts.py`,
  `authorization.py` und `effects.py`, `runtime_authorization_issuer.py` und
  `daedalus.runtimes.admission` sind jeweils Paare aus Fassade und Besitzer
  mitten in einer Strangler-Migration. Welche Fassaden zurueckgebaut werden
  sollen und welche dauerhaft sind, ist nicht dokumentiert.
- **Ungeklaert:** `sandbox.py` beschreibt eine Docker-Sandbox ohne
  Host-Fallback, waehrend das Containment unter
  [`daedalus/spine/containment.py`](../../../daedalus/spine/containment.py) den
  Windows-Pfad besitzt. Welcher der beiden fuer einen gegebenen Attempt
  ausgewaehlt wird, steht in keinem der beiden Docstrings.
- **Ungeklaert:** `promotion_trust_root.py` verweist auf einen Pfad der
  Checkpoint-Linie als Herkunft des Verifiers. Ob die dortigen Zahlen (23 PASS /
  0 FAIL) auf dem heutigen Trunk reproduziert wurden, ist im Code nicht belegt.
- **Ungeklaert:** `interpreter.py` nennt eine gemessene Windows-Eigenheit als
  Grund fuer seine Existenz. Ob die Aufloesung auch auf Linux/macOS noetig ist
  oder dort nur folgenlos mitlaeuft, ist nicht gemessen.

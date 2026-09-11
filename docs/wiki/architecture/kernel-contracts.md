---
title: Kernel-Vertraege
type: spec
status: living
updated: 2026-09-05
covers: daedalus/kernel/contracts
---
# Kernel-Vertraege

`daedalus/kernel/contracts` ist die eine Draht-Sprache des Daedalus-Kernels.
Masterplan-Invariante 1 verlangt "one canonical contract and event spine" fuer
Mission, Attempt, Evidence, Campaign, Policy-Entscheidungen, Budgets und
Promotion-Status; dieses Paket ist dieser Vertrag. Der Docstring von
`canonical.py` grenzt genauso deutlich ab, was er *nicht* ist: die Datensaetze
"deliberately do not schedule work, persist another ledger, enforce effects,
verify evidence, or apply promotion decisions." Eine `PolicyDecision` zu
konstruieren erzwingt nichts; ein `PromotionReceipt` zu bauen promotet nichts.

Gemessen 2026-09-05: 16 `.py`-Dateien, 4767 Zeilen. Davon liegen 3117 in
`canonical.py` und 1052 in `genesis.py`; zehn Dateien sind fuenf bis 24 Zeilen
lange Domaenen-Locatoren.

## Die Strangler-Struktur

Das Paket ist mitten in einem bewussten Umbau, und der `__init__`-Docstring
beschreibt ihn genau: "The domain modules are stable hierarchy locators.
`canonical` remains the single implementation nucleus during the strangler
split, so every legacy and new import resolves to one class object and one
serialization authority."

Praktisch heisst das: `attempts.py`, `evidence.py`, `missions.py`, `policy.py`,
`promotion.py`, `resources.py`, `runtime.py`, `campaigns.py`, `base.py` und
`registry.py` re-exportieren nur. Der Nutzen liegt in der Hierarchie, nicht im
Code: `from daedalus.kernel.contracts.evidence import EvidencePacket` sagt
etwas ueber die Domaene, waehrend alle Wege auf dasselbe Klassenobjekt zeigen.
Zwei Domaenen sind echte Implementierungen: `genesis.py` und `security.py`.

Der Fassaden-`__getattr__` ist lazy und tabellengetrieben: `_EXPORT_GROUPS`
bildet Namen auf ihr Besitzermodul ab, `_MODULES` erlaubt den direkten
Submodul-Zugriff, und `__all__` ist aus der Gruppenreihenfolge abgeleitet —
also selbst ein Vertrag ueber die Reihenfolge.

## Module

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/kernel/contracts/__init__.py) | Lazy Fassade. `_EXPORT_GROUPS` haelt die Zuordnung Name → Domaenenmodul, `__getattr__` importiert erst bei Zugriff. | `__all__`, `__getattr__`, `__dir__` |
| [`canonical.py`](../../../daedalus/kernel/contracts/canonical.py) | Der Implementierungskern: Basis-Mixin, Validatoren, Wertobjekte und alle Gate-0-Vertraege plus die geschlossene Typtabelle. | `CanonicalContract`, `ContractProvenance`, `KERNEL_CONTRACT_VERSION`, `ResourceBudget`, `ResourceUsage`, `EffectScope`, `RuntimeCapabilities`, `MissionContract`, `AttemptContract`, `EvidenceItem`, `EvidencePacket`, `ExperimentSpec`, `CampaignContract`, `CampaignTrialReceipt`, `CampaignReceipt`, `CampaignBudgetEqualityEvidence`, `PolicyDecision`, `RuntimeManifest`, `AttemptReceipt`, `NominationReceipt`, `PromotionReceipt`, `ConformanceCheck`, `RuntimeConformanceReceipt`, `RUNTIME_CONFORMANCE_CHECKS`, `KERNEL_CONTRACT_TYPES`, `parse_kernel_contract`, `derive_work_item_id`, `work_item_identity_sha256` |
| [`base.py`](../../../daedalus/kernel/contracts/base.py) | Locator fuer die Basis-Sprache; re-exportiert zusaetzlich die privaten Validatoren, damit additive Domaenen dieselben benutzen statt eigene zu bauen. | `CanonicalContract`, `ContractProvenance`, `KERNEL_CONTRACT_VERSION` |
| [`resources.py`](../../../daedalus/kernel/contracts/resources.py) | Locator fuer Ressourcen- und Effekt-Scope-Werte. | `ResourceBudget`, `ResourceUsage`, `EffectScope`, `RuntimeCapabilities` |
| [`missions.py`](../../../daedalus/kernel/contracts/missions.py) | Locator fuer Mission- und WorkItem-Identitaet. | `MissionContract`, `derive_work_item_id`, `work_item_identity_sha256` |
| [`attempts.py`](../../../daedalus/kernel/contracts/attempts.py) | Locator fuer Attempt-Vertrag und -Quittung. | `AttemptContract`, `AttemptReceipt` |
| [`evidence.py`](../../../daedalus/kernel/contracts/evidence.py) | Locator fuer Evidenz-Element und -Paket. | `EvidenceItem`, `EvidencePacket` |
| [`campaigns.py`](../../../daedalus/kernel/contracts/campaigns.py) | Locator fuer eingefrorene Experiment- und Kampagnen-Beschreibungen. | `ExperimentSpec`, `CampaignContract`, `CampaignTrialReceipt`, `CampaignReceipt`, `CampaignBudgetEqualityEvidence` |
| [`policy.py`](../../../daedalus/kernel/contracts/policy.py) | Locator fuer die Policy-Entscheidung als Draht-Datensatz. | `PolicyDecision` |
| [`promotion.py`](../../../daedalus/kernel/contracts/promotion.py) | Locator fuer Nominierung und Promotion-Quittung. | `NominationReceipt`, `PromotionReceipt` |
| [`runtime.py`](../../../daedalus/kernel/contracts/runtime.py) | Locator fuer Runtime-Manifest und Konformanz-Quittung. | `RuntimeManifest`, `RuntimeConformanceReceipt`, `ConformanceCheck`, `RUNTIME_CONFORMANCE_CHECKS` |
| [`registry.py`](../../../daedalus/kernel/contracts/registry.py) | Die geschlossene Registry plus strikter Parser. Importiert `genesis` als Seiteneffekt, damit die additive Domaene registriert ist. | `KERNEL_CONTRACT_TYPES`, `parse_kernel_contract` |
| [`genesis.py`](../../../daedalus/kernel/contracts/genesis.py) | Die vollstaendige, inerte Artefaktkette des Genesis-Strangs, von der beratenden Absicht bis zur Deployment-Quittung. | `GenesisAutonomyPolicy`, `BuildIntentProposal`, `ProductSpec`, `DesignContract`, `TargetFourfoldSpec`, `GraphProposal`, `MaterializationPlan`, `ToolchainManifest`, `RoundTripReport`, `DeploymentPlan`, `DeploymentReceipt`, `GenesisRunRecord`, `GENESIS_CONTRACT_TYPES` |
| [`security.py`](../../../daedalus/kernel/contracts/security.py) | Additive Trust-Kernel-Vertraege: einmalige Owner-Freigabe, Lease-Anforderung und Lease, plus die Protokolle fuer eine injizierte Runtime-Trust-Autoritaet. | `OwnerApproval`, `EffectLeaseRequest`, `EffectLease`, `RuntimeTrustLedgerPort`, `RuntimeTrustRecordPort`, `RuntimeTrustPortError` |
| [`evaluation.py`](../../../daedalus/kernel/contracts/evaluation.py) | Neutrale Lese-/Auswerte-Ports. Der Kernel benennt die Faehigkeit, importiert aber keine Evaluator-Implementierung. | `EvaluationBaselinePort`, `EvaluationGatePort`, `EvaluationPorts` |
| [`observations.py`](../../../daedalus/kernel/contracts/observations.py) | Fuenf Strings als geschlossenes Vokabular fuer beobachtete Subsystem-Zustaende, unterhalb beider Konsumenten abgelegt, damit keiner eine zweite Kopie haelt. | `WORKING`, `PRESENT`, `DEGRADED`, `ABSENT`, `UNKNOWN`, `OBSERVATION_STATES` |

## Die Basis-Sprache

`CanonicalContract` ist ein Mixin mit drei Klassenvariablen-Vertraegen und drei
Methoden: `CONTRACT_TYPE`, `CONTRACT_VERSION`, `to_dict`, `to_json` und die
Eigenschaft `digest`. Serialisierung geht immer ueber `canonical_json` /
`canonical_sha` aus
[`daedalus/spine/envelope.py`](../../../daedalus/spine/envelope.py) — es gibt
keine zweite Digest-Autoritaet. `KERNEL_CONTRACT_VERSION` steht auf `1.0.0`,
und `_contract_payload` lehnt jeden Datensatz mit abweichendem Typ oder
abweichender Version ab, bevor er in ein Dataclass-Feld faellt.

Die Validatoren sind die eigentliche Semantik. Regulaere Ausdruecke pinnen die
Formen: SHA-256 als 64 Hex-Zeichen, Revision als 40 oder 64 Hex-Zeichen,
Bezeichner als alphanumerischer Anfang plus eine enge Zeichenmenge, und ein
Artefakt-Locator ausschliesslich in der Form mit `sha256:`-Praefix. Dazu
kommen `_utc_timestamp`, `_repo_path` (repository-relativ, normalisiert),
`_egress_endpoint`, `_sorted_strings` und `_freeze_json`.

`ContractProvenance` traegt `origin`, `source_revision`, `created_at`,
`input_digests` und ein optionales `trace_id`. `_require_provenance_inputs`
ist die Stelle, an der Invariante 7 (Provenance) mechanisch wird: ein Vertrag,
der ein anderes Artefakt per Digest referenziert, dessen Provenienz diesen
Digest aber nicht bindet, laesst sich nicht konstruieren.

## Die geschlossene Registry

`KERNEL_CONTRACT_TYPES` ist eine `MappingProxyType` — von aussen unveraenderlich.
Gemessen 2026-09-05 enthaelt sie 24 Wire-Typen: die zwoelf Gate-0-Vertraege
(`daedalus.mission`, `daedalus.attempt`, `daedalus.evidence`,
`daedalus.experiment-spec`, `daedalus.campaign`, `daedalus.campaign-receipt`,
`daedalus.policy-decision`, `daedalus.runtime-manifest`,
`daedalus.attempt-receipt`, `daedalus.nomination`, `daedalus.promotion`,
`daedalus.runtime-conformance`) und die zwoelf Genesis-Typen.

`_register_kernel_contract_types` ist der einzige Weg hinein und faellt
fail-closed: dieselbe Klasse erneut zu registrieren ist idempotent, einen
belegten Wire-Typ mit einer *anderen* Klasse zu beanspruchen wirft. Damit kann
eine additive Domaene keine bestehende Bedeutung uebernehmen.

`parse_kernel_contract` ist strikt: ein unbekannter Typ wirft. Der Umweg ist
interessant — wird ein Typ nicht gefunden, importiert die Funktion einmal
`genesis` nach und sucht erneut, mit dem Kommentar, dass dieser Import rein ist
(das Modul definiert nur unveraenderliche Datensaetze und registriert ihre
Typen). Genesis bleibt so aus dem heissen Importpfad unbeteiligter
Kernel-Vertraege.

Die drei Sicherheitsvertraege in `security.py` tragen zwar
`CONTRACT_TYPE`-Werte (`daedalus.owner-approval`,
`daedalus.effect-lease-request`, `daedalus.effect-lease`), rufen aber
`_register_kernel_contract_types` **nicht** auf und stehen deshalb nicht in
`KERNEL_CONTRACT_TYPES` (gemessen 2026-09-05). `parse_kernel_contract` kann sie
folglich nicht aufloesen; wer sie liest, muss ihre Klasse kennen.

## Trust-Grenzen / Effekte

Das Verzeichnis ist die Schema- und Digest-Grenze, ausdruecklich **nicht** die
Effektgrenze. Der Docstring von `CanonicalContract` sagt es woertlich: "This is
a schema and digest boundary, not an effect boundary." Es gibt hier keinen
Writer, kein `begin_effect`, keinen Prozess-Spawn und keinen Netzzugriff.

Drei Datensaetze beschreiben Autoritaet, ohne sie zu besitzen:

- `OwnerApproval` ist der einmalige Freigabe-Datensatz aus Invariante 5. Der
  Vertrag traegt die Bindung; das Konsumieren und Entwerten passiert im
  Promotion-Pfad, siehe [Kernel](kernel.md).
- `EffectLeaseRequest` und `EffectLease` beschreiben eine Effekt-Erlaubnis.
  Erteilt wird sie an anderer Stelle.
- `EvaluationPorts` benennt Evaluator-Faehigkeiten als Protokolle. Der
  Docstring ist explizit: "The kernel names the capability but does not import
  an evaluator implementation." Das ist Invariante 3 (Isolation) auf
  Importebene — der Kernel kann seinen Evaluator nicht anfassen, weil er ihn
  nicht kennt.

`genesis.py` betont dasselbe fuer den gesamten Produktstrang: die Datensaetze
"grant no effects, execute no tools, persist no parallel ledger, and never
promote or publish a candidate". Sie bilden die Kette aus Masterplan
Abschnitt 9 als Typen ab, ohne sie auszufuehren.

## Tests

Gemessen 2026-09-05 referenzieren 41 Dateien unter `tests/` dieses Paket. Die
zentralen sind:

- [`tests/test_kernel_contracts.py`](../../../tests/test_kernel_contracts.py) —
  die Draht-Sprache selbst.
- [`tests/test_kernel_contracts_have_producers.py`](../../../tests/test_kernel_contracts_have_producers.py)
  — der Vertrag, dass jeder registrierte Typ auch einen Erzeuger im Baum hat.
- [`tests/kernel/test_contract_hierarchy.py`](../../../tests/kernel/test_contract_hierarchy.py)
  und
  [`tests/kernel/test_kernel_lazy_facade.py`](../../../tests/kernel/test_kernel_lazy_facade.py)
  — Domaenen-Locatoren und Lazy-Aufloesung.
- [`tests/kernel/test_genesis_contracts.py`](../../../tests/kernel/test_genesis_contracts.py)
  — die additive Genesis-Domaene.
- [`tests/kernel/test_owner_approval.py`](../../../tests/kernel/test_owner_approval.py),
  [`tests/kernel/test_effect_leases.py`](../../../tests/kernel/test_effect_leases.py)
  und
  [`tests/kernel/test_runtime_trust_port_boundary.py`](../../../tests/kernel/test_runtime_trust_port_boundary.py)
  — die Sicherheitsdomaene.
- [`tests/kernel/test_evaluation_port_boundary.py`](../../../tests/kernel/test_evaluation_port_boundary.py)
  — dass der Kernel keinen Evaluator importiert.
- [`tests/contracts/test_observation_state_hierarchy.py`](../../../tests/contracts/test_observation_state_hierarchy.py)
  — dass das Beobachtungs-Vokabular nur einmal existiert.

## Verwandt

- [Kernel](kernel.md) — die Schicht, die diese Datensaetze erzeugt, speichert
  und durchsetzt.
- [Kernel-Events](kernel-events.md) — die Huellen und das Ledger, in denen sie
  landen.
- [Kernel-Policy](kernel-policy.md) — `ExecutionLimitPolicy`, die in
  `ResourceBudget` einfliesst.
- [Orchestrierung Genesis](orchestration-genesis.md) — der Konsument der
  Genesis-Kette.
- [Ariadne](ariadne.md) — der Konsument von `ExperimentSpec` und
  `CampaignReceipt`.
- [Spine](spine.md) — Herkunft von `canonical_json` und `canonical_sha`.
- [Beobachtungsebene](observation-layer.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Die drei Vertraege in `security.py` fuehren einen
  `CONTRACT_TYPE`, registrieren ihn aber nicht. Ob das Absicht ist (Lease und
  Freigabe sollen nicht generisch parsbar sein) oder eine Luecke, steht
  nirgends.
- **Ungeklaert:** Der Strangler-Split ist im Docstring beschrieben, aber ohne
  Zielzustand: ob die zehn Locator-Module irgendwann echte Implementierungen
  aufnehmen oder Locatoren bleiben, ist nicht festgelegt.
- **Ungeklaert:** `base.py` re-exportiert 14 private Validatoren mit
  fuehrendem Unterstrich. Ob das ein offizieller Erweiterungspunkt fuer
  additive Domaenen ist oder eine Uebergangsloesung, sagt der Docstring nicht.
- **Ungeklaert:** `KERNEL_CONTRACT_VERSION` steht global auf `1.0.0` und wird
  von jedem Vertrag geerbt. Wie eine einzelne Domaene ihre Version anheben
  koennte, ohne alle anderen mitzuziehen, ist im Code nicht vorgesehen.

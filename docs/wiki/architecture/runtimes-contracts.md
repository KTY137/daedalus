---
title: Runtime-Contracts
type: module
status: living
updated: 2026-09-05
covers: daedalus/runtimes/contracts
---
# Runtime-Contracts

`daedalus/runtimes/contracts/` hält die *neutralen* Typen, die zwischen Gates
und Runtimes geteilt werden: Fehlerklassen, Quittungen (Receipts), strukturelle
Bindungen und Protokoll-Ports. Der Paket-Docstring nennt sie "neutral runtime
admission contracts consumed by gates and runtimes" — neutral heißt hier: die
Typen tragen keine Autorität. Sie beschreiben, was ein Gate gemessen hat oder
was ein Adapter binden muss; die Sicherheitsautorität bleibt beim persistierten
Runtime-Trust-Record, der Policy und dem EffectLease des kanonischen Kernels
(Masterplan §4, Invariante 1 und 8).

Der Sinn der Trennung ist die Vermeidung einer zweiten Autorität: Wenn Gate und
Runtime dieselbe Fehlerklasse und denselben Receipt-Typ importieren, gibt es
genau ein Vokabular für "HEAD stimmt nicht", "Workspace-Bindung passt nicht"
oder "Target-Struktur ist stale" — statt zweier Definitionen, die auseinander
driften. `daedalus/runtimes/contracts/claude.py` sagt das für den Claude-Pfad
explizit: das legacy Provider-Modul bleibt das registrierte
Effekt-Registry-Ziel und reexportiert diese Werte, damit die Migration keine
zweite Workspace-Binding- oder Fehlerautorität erzeugt (Strangler-Muster).

## Module

| Datei | Zweck | Öffentliche Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/runtimes/contracts/__init__.py) | Reexport-Fassade; bündelt alle sechs Module in ein `__all__`, damit Konsumenten nur `daedalus.runtimes.contracts` importieren. | (nur Reexporte) |
| [claude.py](../../../daedalus/runtimes/contracts/claude.py) | Kompatibilitätsfläche des Claude-Runtime-Providers: Identitätskonstanten und vier Fehlerklassen für fehlende Autorität, falsche Worktree-Bindung, zu enge Scope-Beschreibung und nicht bindende Idempotenz-Identität; dazu die strukturelle Worktree-Bindung. | `CLAUDE_ENTRYPOINT_ID`, `CLAUDE_RUNTIME_ID`, `ClaudeProviderAuthorizationRequired`, `ClaudeProviderWorkspaceMismatch`, `ClaudeProviderScopeMismatch`, `ClaudeInvocationBindingMismatch`, `ClaudeWorkspaceGrant` |
| [ports.py](../../../daedalus/runtimes/contracts/ports.py) | Drei `typing.Protocol`-Ports, mit denen die Runtime-Admission read-only auf Gate-Funktionen zugreift, ohne das Gate-Paket zu importieren. | `RepositoryHeadReceiptVerifier`, `RetentionInventoryScanner`, `PythonTargetStructureResolver` |
| [provider_report.py](../../../daedalus/runtimes/contracts/provider_report.py) | Kanonischer Report, den ein Provider-Runtime zurückgibt, plus rein syntaktische Validierung (exakte Schlüsselmenge, erlaubter Status, Längenbegrenzung der Zusammenfassung). | `AgentReport`, `REPORT_KEYS`, `validate_report` |
| [python_targets.py](../../../daedalus/runtimes/contracts/python_targets.py) | Struktureller Receipt für ein gate-aufgelöstes Python-Ziel der Form `modul:Objekt.pfad`: Parser, Modul-zu-Pfad-Abbildung und ein eingefrorener Dataclass-Record mit vollständiger Selbstprüfung. | `parse_python_target`, `module_repository_path`, `PythonTargetStructure`, `PythonTargetStructureError`, `PythonTargetSourceError`, `PythonTargetBindingError` |
| [repository.py](../../../daedalus/runtimes/contracts/repository.py) | Receipt für eine exakte, stabile Git-HEAD-Beobachtung (detached oder symbolisch, aufgelöst aus `loose_ref` oder `packed_refs`) mit Digest, `to_dict`/`from_dict` und drei Fehlerklassen. | `RepositoryHeadRevisionReceipt`, `RepositoryHeadRevisionError`, `RepositoryHeadRevisionShapeError`, `RepositoryHeadRevisionBindingError`, `RepositoryHeadRevisionRaceError` |
| [retention.py](../../../daedalus/runtimes/contracts/retention.py) | Inventar der noch ungeschützten Schreibflächen in `daedalus/runtimes/provider/target_receipt_ledger.py` — ein bewusst als offen markierter Gate-0-Blocker. | `ProviderTargetReceiptRetentionInventory`, `ProviderTargetReceiptRetentionSurface`, `ProviderTargetReceiptRetentionInventoryError`, `RETENTION_SOURCE_PATH`, `RETENTION_MAX_SOURCE_BYTES` |

### Was die Records erzwingen

`PythonTargetStructure.__post_init__` prüft nicht nur Typen, sondern die
Konsistenz des ganzen Records gegen sein eigenes `target`: `module_name` und
`object_path` müssen aus dem Target reparsbar sein, `source_path` muss der
Modulabbildung entsprechen, `source_sha256` lowercase-SHA-256 sein, Zeilen- und
Spaltenwerte strikte Ganzzahlen (die Prüfung `type(value) is not int` schließt
`bool` aus), das Definitionsende darf nicht vor dem Anfang liegen, und
`chain_kinds` muss dieselbe Länge wie `object_path` haben, wobei alle
Elternglieder `class` sein müssen und das letzte Glied gleich
`definition_kind`. `to_dict()` hängt drei Ehrlichkeitsflags an:
`structural_target_verified` ist wahr, `behavior_verified` und `executed` sind
falsch — der Receipt behauptet also ausdrücklich *nicht*, dass das Ziel
ausgeführt oder verhaltensgeprüft wurde.

`RepositoryHeadRevisionReceipt` macht dasselbe für Git: `to_dict()` setzt
`repository_head_verified` wahr, aber `commit_object_verified`,
`worktree_clean_verified`, `process_spawned` und `repository_mutated` falsch.
`from_dict()` verlangt eine *exakte* Schlüsselmenge und weist jede Nutzlast
zurück, die eine dieser Negativ-Behauptungen auf wahr dreht — ein Receipt kann
sich also nicht nachträglich mehr Autorität geben, als das Gate gemessen hat.
Die Property `digest` ist `canonical_sha` über `to_dict()` aus
[spine/envelope.py](../../../daedalus/spine/envelope.py).

`ProviderTargetReceiptRetentionInventory` ist der ungewöhnlichste Typ: seine
Property `closed` gibt hart falsch zurück, `blocking` an jeder Fläche ebenso
hart wahr, und die Nutzlast trägt vier benannte Blocker (nicht kanonisch
registriert, nicht geguardet, EffectLease nicht konsumiert,
Primary-Checkout-Ziel nicht bewiesen). Der Typ existiert, um einen offenen
Gate-0-Rest sichtbar zu halten, nicht um ihn zu schließen — die Flags
`wiring` (`inventory_only`), `guard_contract_bound` und
`effect_lease_consumed` stehen unveränderlich im Serialisat. Erlaubte Werte für
`kind` einer Fläche sind `schema_write`, `event_store_write`, `cas_write` und
`transitive_effectful_call`.

## Trust-Grenzen / Effekte

Das Paket ist **effektfrei**: kein `begin_effect`, kein Dateisystem-Schreiben,
kein Subprozess, kein Netz. Die einzigen Importe außerhalb der Standardbibliothek
sind `daedalus.kernel.contracts.base` (Revisions- und SHA-256-Validierer) und
`daedalus.spine.envelope` (`canonical_json`, `canonical_sha`) — beide
deterministische Kodierer.

Wichtige Abgrenzungen, die im Code ausbuchstabiert sind:

- `ClaudeWorkspaceGrant` ist im Docstring "deliberately not described as an
  authority". Er schließt versehentliche Rekombination von Request, Execution
  und Pfad *innerhalb* des Adapters; die Aktivierung in der kanonischen
  Registry braucht weiterhin eine authentifizierte Attempt-Workspace-Capability
  vom Attempt-Ledger.
- Die Ports in `ports.py` sind explizit "read-only gate ports". Sie geben
  Receipts zurück oder werfen; sie schreiben nichts.
- `validate_report` prüft nur Form (Schlüssel, Status-Enum, Typen,
  Zusammenfassungslänge höchstens 600 Zeichen). Es ist keine Evidenz im Sinne
  von Masterplan §4 Invariante 4 — der Report ist eine Modellaussage, kein
  Prüfergebnis.

Die Writer und Effekt-Boundaries liegen konsequent außerhalb: in
[Gates](gates.md) (`daedalus/gates/repository/head_revision.py`,
`daedalus/gates/python_target_structure.py`,
`daedalus/gates/provider_target_receipt_retention_inventory.py`) und im
Provider-Runtime ([Runtimes-Provider](runtimes-provider.md)). Gemessen
2026-09-05 importieren 17 Module unter `daedalus/` dieses Paket, darunter
`daedalus/ariadne/campaign.py`, `daedalus/providers/claude_cli.py`,
`daedalus/providers/codex_cli.py`, `daedalus/orchestration/verifier.py` und
`daedalus/runtimes/provider/target_receipt_retention_admission.py`.

## Tests

Gemessen 2026-09-05 referenzieren neun Testdateien `runtimes.contracts`:

| Test | Deckt ab |
| --- | --- |
| [tests/runtimes/test_runtime_gate_contract_boundaries.py](../../../tests/runtimes/test_runtime_gate_contract_boundaries.py) | dass Runtimes und Gates dieselben Contract-Typen benutzen und keine Gegen-Autorität entsteht |
| [tests/runtimes/test_claude_provider_strangler_architecture.py](../../../tests/runtimes/test_claude_provider_strangler_architecture.py) | die Reexport-/Strangler-Bedingung aus `claude.py` |
| [tests/runtimes/test_provider_report_contract_owner.py](../../../tests/runtimes/test_provider_report_contract_owner.py) | Eigentum am `AgentReport`- und `validate_report`-Vertrag |
| [tests/runtimes/test_provider_executable_structure_review.py](../../../tests/runtimes/test_provider_executable_structure_review.py) | die Struktur-Vorprüfung der Provider-Executables |
| [tests/gates/test_repository_head_revision_review.py](../../../tests/gates/test_repository_head_revision_review.py) | `RepositoryHeadRevisionReceipt` inklusive Race- und Shape-Fehlern |
| [tests/gates/test_python_target_structure_review.py](../../../tests/gates/test_python_target_structure_review.py) | `PythonTargetStructure` und `parse_python_target` |
| [tests/gates/test_provider_target_receipt_retention_inventory_review.py](../../../tests/gates/test_provider_target_receipt_retention_inventory_review.py) | das Retention-Inventar und seine Blocker-Liste |
| [tests/kernel/test_contract_hierarchy.py](../../../tests/kernel/test_contract_hierarchy.py) | Einordnung in die Kernel-Contract-Hierarchie |
| [tests/test_ariadne_campaign_v0.py](../../../tests/test_ariadne_campaign_v0.py) | Nutzung durch die Ariadne-Kampagne |

## Verwandt

- [Runtimes](runtimes.md) — das umgebende Paket
- [Runtimes-Provider](runtimes-provider.md) — der Konsument mit Effekten
- [Runtimes-Admission](runtimes-admission.md) — wo die Ports aufgerufen werden
- [Gates](gates.md), [Gates-Repository](gates-repository.md) — die Produzenten der Receipts
- [Kernel-Contracts](kernel-contracts.md) — Revisions- und Digest-Validierer
- [Spine](spine.md) — kanonische Serialisierung
- [Providers](providers.md) — `claude_cli` und `codex_cli` als Reexport-Konsumenten
- [Ariadne](ariadne.md), [Kernel-Policy](kernel-policy.md), [Wiki-Index](../index.md)
- [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md)

## Ungeklärt

- **Ungeklärt:** Ob und wann `ProviderTargetReceiptRetentionInventory.closed`
  jemals wahr werden soll. Der Code gibt hart falsch zurück; der Weg zum
  Schließen (Registrierung, Guard, EffectLease, Primary-Checkout-Beweis) steht
  nur als Blocker-String im Serialisat, nicht als Implementierung.
- **Ungeklärt:** `retention.py` pinnt `RETENTION_SOURCE_PATH` als Literal auf
  `daedalus/runtimes/provider/target_receipt_ledger.py`. Ob ein Umbenennen
  dieser Datei mechanisch auffällt, konnte ich aus dem Modul allein nicht
  ablesen.
- **Ungeklärt:** `parse_python_target` akzeptiert per regulärem Ausdruck nur
  Ziele im `daedalus`-Namensraum. Ob damit bewusst ausgeschlossen ist, dass ein
  Gate je ein Ziel in `tools/` oder `experiments/` auflöst, geht aus dem Code
  nicht hervor.

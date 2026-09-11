---
title: Orchestration Genesis
type: module
status: living
updated: 2026-09-05
covers: daedalus/orchestration/genesis
---
# Orchestration Genesis

`daedalus/orchestration/genesis` ist der eigentumsgeleitete Genesis-Strang aus
Masterplan-Abschnitt 7.1 und Revision 11: eine frei formulierte Bauanfrage wird
zu einer versionierten Produktspezifikation verdichtet und sofort als isolierte
Genesis-Mission gestartet, ohne Anforderungsinterview und ohne Freigabe pro
Spezifikation. Das Paket gehoert damit zu Ikarus (Absicht wird zu typisierten
Vertraegen), fuehrt seine Effekte aber ausschliesslich ueber den kanonischen
Kernel aus: eine `MissionContract`, ein `AttemptContract`, eine persistierte
Effect Lease, ein inhaltsadressierter Kandidatenbaum, ein `EvidencePacket`.
Es befoerdert nichts, merged nichts und veroeffentlicht nichts.

Die Aufteilung ist strikt nach Effektfaehigkeit: [admission.py](../../../daedalus/orchestration/genesis/admission.py)
und [materializer.py](../../../daedalus/orchestration/genesis/materializer.py)
sind rein, [service.py](../../../daedalus/orchestration/genesis/service.py) ist
der einzige Ort mit Prozessen, Dateien, Ledger und Lease.

Gemessen 2026-09-05: 4 Dateien, 6308 Zeilen; `service.py` allein 3188 Zeilen.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/orchestration/genesis/__init__.py) | Re-Export der drei Haelften unter einem Paketnamen; keine eigene Logik. | `GenesisRequest`, `GenesisPlan`, `BoundGenesisPlan`, `run_genesis`, `render_project`, `normalize_genesis_request`, `build_genesis_plan`, `bind_genesis_attempt`, `read_genesis_preview`, `read_genesis_source_archive`, `GenesisError`, `GenesisConflictError`, `GenesisPreviewError` |
| [admission.py](../../../daedalus/orchestration/genesis/admission.py) | Reine Zulassung und Vertragsplanung. Kein I/O. Verwandelt eine begrenzte Anfrage in Policy, Proposal, Produkt, Design, Ziel-Spec, Mission und Runtime-Vertrag. Nicht unterstuetzte *geforderte* Faehigkeiten bleiben als Blocker stehen, bevor Lease, Workspace, Provider oder Prozess erreichbar sind. | `normalize_genesis_request`, `build_genesis_plan`, `bind_genesis_attempt`, `denied_policy_decision`, `GenesisRequest`, `GenesisPlan`, `BoundGenesisPlan` |
| [materializer.py](../../../daedalus/orchestration/genesis/materializer.py) | Deterministisches, effektfreies Rendern der Quellen. Gibt nur eine endliche Abbildung sicherer POSIX-relativer Pfade auf Bytes zurueck -- kein Workspace, keine Toolchain, keine Persistenz. Die erzeugten Projekte benutzen ausschliesslich Plattform-Laufzeiten (Browser plus Python-Standardbibliothek). | `render_project` |
| [service.py](../../../daedalus/orchestration/genesis/service.py) | Der kanonische Weg vom Prompt zur Vorschau: Zulassung, persistierte Effect Lease, ein Attempt, leerer CAS-Basisbaum, checkout-externer Workspace, Kandidaten-CAS *vor* der Ausfuehrung, danach echte Build-, Test-, Laufzeit- und Fourfold-Evidenz aus jeweils frischen Materialisierungen derselben Identitaet. | `run_genesis`, `read_genesis_preview`, `read_genesis_source_archive`, `re_fullmatch_run_id`, `GenesisError`, `GenesisConflictError`, `GenesisReconciliationError`, `GenesisPreviewError` |

## Zulassung: was die Policy schliesst und was sie blockiert

`normalize_genesis_request` normalisiert Prompt, Ziel und Stack zu einer
deterministischen Anfrage-Identitaet (`run_id`, `lineage_id`, `mission_id`,
`attempt_id`, `request_key`) und sammelt dabei Blocker und Hinweise. Ein
Request mit Blockern ist nicht `admitted` und erreicht keinen Effekt.

- **Ziele.** `SUPPORTED_TARGETS` ist gemessen 2026-09-05 genau
  `("cli", "desktop", "mobile", "web")`; Aliase wie Browser, Terminal oder PWA
  werden vorher normalisiert. Ein ausdruecklich gefordertes, nicht
  unterstuetztes Ziel ist ein Blocker, keine stille Ersetzung.
- **Blueprints.** Zwei versionierte Materialisierungsprofile:
  `ITEM_COLLECTION_BLUEPRINT` und `KANBAN_BOARD_BLUEPRINT`. Der Kanban-Blueprint
  unterstuetzt nur Browser-, Desktop- und Mobile-PWA, der CLI-Fall blockiert.
- **Prompt-Grammatik.** Genesis v1 ist eine endliche Produktgrammatik, kein
  allgemeiner Software-Prompt. Jedes lexikalische Wort muss von einer Wortliste
  oder einem engen Morphologiemuster konsumiert werden; sonst nennt die
  Ablehnung die unbekannten Token beim Namen.
- **Externe Forderungen.** Ein Prompt, der Authentifizierung, Bezahlung, Cloud,
  API-Schluessel oder Deployment fordert, ist blockiert -- ebenso eine
  ausdruecklich geforderte native oder Store-Paketierung, denn Genesis v1
  erzeugt lokale Quellkandidaten, und Desktop bzw. Mobile sind offline
  installierbare PWAs, keine nativen Pakete.
- **Mission-Struktur.** `build_genesis_plan` leitet neun Work Items aus festen
  Phasen ab: Spezifikation, Design und Ziel, Materialisierung, Build, Test,
  Laufzeit-Smoke, Package-Smoke, Fourfold-Rundlauf, isolierte Vorschau. Die
  Identitaet jedes Work Items bindet Quellrevision, Ziel und (beim Kanban-Fall)
  den Blueprint ueber `derive_work_item_id`.
- **`bind_genesis_attempt`** haengt an den Plan die `MaterializationPlan`, das
  `ToolchainManifest` und den `AttemptContract`, sobald der leere CAS-Basisbaum
  und die Lease-Entscheidung feststehen -- das Ergebnis ist `BoundGenesisPlan`.

Die abwesende Basis-Repository-Situation wird damit explizit dargestellt: der
Eingangsbaum ist ein *ausdruecklich leerer* CAS-Baum, kein fehlendes Feld.

## Trust-Grenzen / Effekte

- **Der einzige Effekt-Einstieg ist `run_genesis`.** `ENTRYPOINT_ID` ist
  `python.genesis`, der Kill-Switch-Einstieg `python.genesis_switch`.
  Reihenfolge im Code: Zulassung -> Rendern (rein) -> Bindung ->
  `_ensure_genesis_switch` -> `acquire_effect_lease` -> `begin_effect` ueber
  die Autorisierung der erteilten Lease -> erst danach Dateisystem, Ledger und
  Prozesse.
- **Lease-Umfang.** Die Lease wird mit `positions=1`, `tools=("python",)`,
  `contained=True`, einem checkout-externen `worktree_root` und einer
  Schreib-Policy erteilt, die nur den Workspace zulaesst. `max_spend_usd` ist
  `None`, weil kein Anbieter aufgerufen wird; das Zeitlimit ist
  `GENESIS_TIMEOUT_S`.
- **Kandidatenidentitaet vor Ausfuehrung.** Der gerenderte Baum wird in den
  `SourceTreeStore` aufgenommen, *bevor* irgendein kandidateneigener Test oder
  eine Laufzeit ein beschreibbares Verzeichnis bekommt. Jedes folgende Gate --
  Build, Test, Runtime, Package, CLI-Blackbox, Feature-Konformitaet und der
  Fourfold-Rundlauf -- startet aus einer *frischen* Materialisierung derselben
  CAS-Bytes. Ein Kandidat kann damit nicht die Bytes veraendern, ueber die er
  bewertet wird.
- **Evidenz.** Kommandobeobachtungen werden ueber den
  [ArtifactStore](daedalus-package-root.md) abgelegt und mit
  `assemble_fourfold_evidence_packet` zu einem `EvidencePacket` gebunden --
  aber nur, wenn alle Kommandos bestanden haben und der Fourfold-Rundlauf
  uebersetzt. Fehlschlaege werden als negative Evidenz aufbewahrt, nicht
  verworfen.
- **Idempotenz und Abgleich.** Ein wiederverwendeter Idempotenzschluessel mit
  abweichendem Material ist `GenesisConflictError`. Ein committeter Attempt
  ohne gebundenen Invocation-Effect-Abschluss ist `GenesisReconciliationError`
  und wird nicht stillschweigend als Erfolg gelesen.
- **Lesen von Kandidaten.** `read_genesis_preview` loest genau eine Datei eines
  gruenen Web/PWA-Kandidaten direkt aus dem autoritativen CAS-Baum auf;
  `read_genesis_source_archive` exportiert einen verifizierten Kandidaten als
  deterministisches ZIP im Speicher. Beide verweigern bei unverifizierter oder
  nicht gruener Identitaet (`GenesisPreviewError`).
- **Was hier nicht passiert.** Kein Merge, keine Promotion, kein Deployment,
  keine Veroeffentlichung, kein Modell mit Autoritaet. Der Materializer erzeugt
  bewusst keine externe Endpunkt-Referenz, keine Zugangsdaten, keinen
  Analytics-Hook, keinen Auth-Fluss und kein Abhaengigkeitsmanifest.

## Tests

Gemessen 2026-09-05 ueber eine Importsuche in `tests/`:

- [tests/orchestration/test_genesis_service.py](../../../tests/orchestration/test_genesis_service.py)
  -- der Lebenszyklus von `run_genesis`, Lease, Attempt, Evidenz und Replay.
- [tests/orchestration/test_genesis_materializer.py](../../../tests/orchestration/test_genesis_materializer.py)
  -- Determinismus und Grenzen von `render_project`.
- [tests/orchestration/test_genesis_source_archive.py](../../../tests/orchestration/test_genesis_source_archive.py)
  -- `read_genesis_source_archive`.
- [tests/interfaces/test_genesis_cli.py](../../../tests/interfaces/test_genesis_cli.py)
  und [tests/interfaces/test_http_genesis.py](../../../tests/interfaces/test_http_genesis.py)
  -- die beiden Oberflaechen, siehe [Interfaces CLI](interfaces-cli.md) und
  [Interfaces HTTP](interfaces-http.md).
- [tests/kernel/test_genesis_contracts.py](../../../tests/kernel/test_genesis_contracts.py)
  und [tests/kernel/test_genesis_effect_lease.py](../../../tests/kernel/test_genesis_effect_lease.py)
  -- die Vertraege und die Lease auf Kernelseite.
- [tests/test_effect_boundary.py](../../../tests/test_effect_boundary.py) und
  [tests/test_kernel_contracts_have_producers.py](../../../tests/test_kernel_contracts_have_producers.py)
  -- die Registry-Zeile des Einstiegs und die Frage, ob jeder Genesis-Vertrag
  einen echten Produzenten hat.

## Verwandt

- [Orchestration](orchestration.md) -- das umgebende Paket und der
  LangGraph-Adapter, der Run-Briefs komponiert.
- [Orchestration Ikarus](orchestration-ikarus.md) -- die andere Haelfte der
  Absichtsverarbeitung; Genesis ist der Bau-Zweig, nicht der Assistenz-Zweig.
- [Kernel-Contracts](kernel-contracts.md) -- Herkunft von `ProductSpec`,
  `DesignContract`, `TargetFourfoldSpec`, `GraphProposal`,
  `MaterializationPlan`, `ToolchainManifest`, `GenesisAutonomyPolicy`.
- [Kernel](kernel.md) und [Spine](spine.md) -- `acquire_effect_lease`,
  `begin_effect`, Attempt-Ledger, Kill-Switch.
- [Twin](twin.md) und [Twin-Extractors](twin-extractors.md) -- der
  Fourfold-Rundlauf, der den gebauten Kandidaten wieder destilliert.
- [Daedalus-Paketwurzel](daedalus-package-root.md) -- `ArtifactStore`,
  `primary_tree` und die Schreib-Primitive, auf denen der Dienst sitzt.
- [Snapshot-Experiment s05](../experiments/forest-v2-s05-snapshot.md) -- die
  Vorarbeit zur revisionsatomaren Snapshot-Identitaet, die derselben
  Invariante 6 dient.
- [Gates](gates.md) -- wo die Gate-Evidenz dieses Strangs eingesammelt wird.
- [Wiki-Index](../index.md).

## Ungeklaert

- **Ungeklaert:** ob und wo ein `DeploymentPlan` bzw. `DeploymentReceipt`
  tatsaechlich erzeugt wird. Die Vertraege existieren in den Kernel-Contracts,
  aber `service.py` erwaehnt gemessen 2026-09-05 nur die Vorschau, nicht die
  Veroeffentlichung.
- **Ungeklaert:** ob der `BuildIntentProposal`, den `build_genesis_plan`
  erzeugt, jemals von einem Modell befuellt wird. Im heutigen Pfad ist er
  deterministisch aus der normalisierten Anfrage abgeleitet und damit ein
  Advisory-Artefakt ohne Modellaufruf.
- **Ungeklaert:** wie eng die Prompt-Wortliste in der Praxis blockiert. Der
  Code beschreibt sie als endliche Produktgrammatik, misst aber selbst keine
  Ablehnungsrate.

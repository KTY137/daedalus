---
title: Daedalus wiki
type: moc
status: living
updated: 2026-09-05
---

# Daedalus wiki

Die Inhaltskarte. Agenten lesen und schreiben diesen Vault; er ist das Gedaechtnis
des Projekts, weshalb Agenten selbst keinen Zustand halten -- siehe
[Agents hold no state](decisions/agents-hold-no-state.md).

Stand 2026-09-05: 63 Modulseiten neu geschrieben, eine je Quellverzeichnis, nach dem
Plan aus [`daedalus/wiki/plan.py`](../../daedalus/wiki/plan.py) und geprueft mit
[`daedalus/wiki/verify.py`](../../daedalus/wiki/verify.py) (siehe [Wiki](architecture/wiki.md)).
Jede Seite traegt `covers:` mit dem Verzeichnis, das sie beschreibt, verlinkt jede
`.py`-Datei darin relativ, nennt echte Symbole in Backticks und endet mit einem
Abschnitt "Ungeklaert". Begriffe folgen dem
[Masterplan](../IKARUS_ARIADNE_MASTER_PLAN.md): Daedalus ist der Kernel, Ikarus der
Assistent und Orchestrator, Ariadne die kontrollierte Evolutions-Workload.

## Kernel (Daedalus)

- [Kernel](architecture/kernel.md) -- Mission, Attempt, Evidence, Policy-Entscheidungen, Ledger.
- [Kernel-Vertraege](architecture/kernel-contracts.md) -- die kanonischen Contract-Typen und ihre Locator-Module.
- [Kernel-Events](architecture/kernel-events.md) -- Event-Spine und Envelopes.
- [Kernel Policy](architecture/kernel-policy.md) -- Limit-Achsen, Computer-Policy, Effekt-Autorisierung.
- [Spine](architecture/spine.md) -- Effekt-Boundary, Registry der Eingangstueren, Picker.
- [Foundation](architecture/foundation.md) -- Projekte, Umgebung, Beschleuniger-Sonden.
- [Daedalus-Paketwurzel](architecture/daedalus-package-root.md) -- die Module direkt in `daedalus/`.
- [Memory](architecture/memory.md) -- Produktgedaechtnis, getrennt von Ariadnes adaptivem Speicher.
- [Schreib-Lanes](architecture/lanes.md) -- Lane-Vergabe fuer parallele Schreiber.
- [Gates](architecture/gates.md) und [Repository-Gates](architecture/gates-repository.md) -- Gate-0-Report, Evidenzarten, Promotion-Verweigerungen.
- [Eval](architecture/eval.md) -- Evaluatoren, Graph-Delta, Tier-2-Harness.
- [Observe](architecture/observe.md) -- Form eines Objekts, nie sein Wert.

## Project Twin (vier Ebenen)

- [Structcore](architecture/structcore.md) -- Parser, Index, Typgraph, Artefakte.
- [Twin](architecture/twin.md) und [Twin-Extraktoren](architecture/twin-extractors.md) -- Snapshot, Hybrid-Retrieval, Tree-sitter-Adapter.
- [Type graph](architecture/type-graph.md), [Data layer](architecture/data-layer.md),
  [Knowledge layer](architecture/knowledge-layer.md), [Observation layer](architecture/observation-layer.md) -- die Ebenen-Spezifikationen (Juli-Seiten, 2026-09-05 nachgezogen).
- [Mapping](architecture/mapping.md) -- das generierte Architekturartefakt und seine Drift-Pruefung.
- [Wiki](architecture/wiki.md) -- Vault-Leser, Link-Index, Plan und Verifier dieses Wikis.

## Runtimes und Provider

- [Runtimes](architecture/runtimes.md) -- Runtime-Manifeste, Sandbox, Computer-Assistent.
- [Runtimes / Provider](architecture/runtimes-provider.md) -- Provider-Adapter hinter dem Runtime-Vertrag.
- [Runtimes -- Providers (Roster)](architecture/runtimes-providers.md) -- Rollen, Token-Policy, Read-only-Erzwingung.
- [Runtimes Admission](architecture/runtimes-admission.md) und [Runtimes Execution](architecture/runtimes-execution.md) -- Zulassung, Prozesswaechter, Budgetnetz.
- [Runtime-Contracts](architecture/runtimes-contracts.md) -- Receipt-Retention und Zielinventare.
- [Providers](architecture/providers.md) -- Claude, Codex, DeepSeek, Ollama, OpenAI-kompatible Clients.
- [Adapters](architecture/adapters.md) -- Subprocess-Adapter und Transport-Events.
- [Council](architecture/council.md) -- der vendoruebergreifende Rat, beratend.

## Ikarus (Orchestrierung und Oberflaechen)

- [Orchestrierung (Paketwurzel)](architecture/orchestration.md) -- Runbook, Benchmark, Routen.
- [Orchestration Ikarus](architecture/orchestration-ikarus.md) -- Chat, Act, Shell, Projektor.
- [Orchestration Missions](architecture/orchestration-missions.md) und [Orchestration Execution](architecture/orchestration-execution.md) -- Missionslauf, One-Shot, Ports.
- [Orchestration Genesis](architecture/orchestration-genesis.md) -- Genesis-Admission und Toolchain-Manifest.
- [Ignition](architecture/ignition.md) -- die Gate-1-Voltage-Rehearsal.
- [Kairos](architecture/kairos.md) -- gated writes und Provider-Attempts.
- [Interfaces CLI](architecture/interfaces-cli.md), [HTTP-Interface](architecture/interfaces-http.md),
  [Desktop-Interface](architecture/interfaces-desktop.md), [Interfaces bridge](architecture/interfaces-bridge.md) -- die Eingangstueren.
- [GUI-Lint](architecture/gui.md) -- Pruefungen der QML-Oberflaeche.
- [Hooks](architecture/hooks.md) -- der Kontextkanal der Sitzung.
- [Hermes-Integration](architecture/integrations-hermes.md) -- externer Agent hinter der Admission.
- [Tools (Capability-Schicht)](architecture/tools.md) -- Werkzeug-Registry fuer den Computer-Assistenten.
- [Chip-Design (EDA-Slice)](architecture/chip-design.md) -- Vivado-Toolchain und Publikationspruefung.

## Ariadne (Evolution)

- [Ariadne](architecture/ariadne.md) -- Kampagne, Operator `repair_variant`, Receipts.
- [Graph delta as fitness](graph-delta-as-fitness.md) -- was in der Nacht des 30. Juli gemessen wurde.

## Experimente (isoliert, befristet, nicht befoerdert)

- [Forest v2 -- Vorstudie und Slice-Wurzel](experiments/forest-v2.md)
- [s01 Resolution](experiments/forest-v2-s01-resolution.md), [s02 Type-Plane](experiments/forest-v2-s02-types.md),
  [s05 Snapshots](experiments/forest-v2-s05-snapshot.md), [s06 Cards](experiments/forest-v2-s06-cards.md),
  [s07 BM25](experiments/forest-v2-s07-bm25.md), [s08 Graph-Baselines](experiments/forest-v2-s08-graph-baselines.md),
  [s09 Eval-Harness](experiments/forest-v2-s09-eval.md), [s10 Kill](experiments/forest-v2-s10-kill.md),
  [s11 Fusion](experiments/forest-v2-s11-fusion.md)
- [Tensor-Embeddings](experiments/forest-v2-tensor-embeddings.md), [Semantic-Composite-Tensor](experiments/forest-v2-tensor-semantic-composite.md),
  [tensor-embedding (Arme A bis Q)](experiments/tensor-embedding.md)
- [Fourfold Hybrid Retrieval](experiments/fourfold-hybrid-retrieval.md)
- [Opus Fleet Watchdog](experiments/opus-fleet-watchdog.md)
- [Einzelsonden](experiments/probes.md) -- Append-Atomizitaet unter parallelen Schreibern, CUDA-Boolean-Sonde

## Tooling

- [tools/](tooling/tools.md) -- Repo-Werkzeuge mit Effekt-Boundary-Zeilen.
- [scripts/](tooling/scripts.md) -- Mutationslaeufe und Kampagnenskripte.
- [Skill-Skripte ui-ux-pro-max](tooling/claude-skills-ui-ux-pro-max-scripts.md)
- [Claude-Proposals](tooling/claude-proposals.md)
- [Tool vetting](tool-vetting.md) -- das Gate, das ein Skill oder MCP-Server passieren muss.

## Roadmap und Geschichte

- [Feature backlog](feature-backlog.md) -- Ernte der Session 29./30. Juli 2026.
- [Night shift 2026-07-30](night-shift-2026-07-30.md) -- 170 externe Agenten, ein Defekt gefunden durch Bauen statt Review.

# Daedalus project instructions

@AGENTS.md
@docs/IKARUS_ARIADNE_MASTER_PLAN.md

## Orchestrierung in diesem Repo: LangGraph

Owner-Anweisung 2026-09-01. Präzisiert die globale Regel in
`~/.claude/CLAUDE.md` für Daedalus. Ändert **nicht** den Masterplan, die
Amendment-Kette oder `AGENTS.md`.

- **Stand heute (gemessen 2026-09-01):** `daedalus/orchestration/langgraph_adapter.py` deckt
  genau *einen* Ablauf ab — die Komposition des Run-Briefs in
  `daedalus.runbook.create_run(..., engine="langgraph")`. Default bleibt
  `engine="stdlib"`. `tests/test_langgraph_adapter.py`: 35 passed. Vertrag,
  Failure-Modes und Ersatzpfad stehen in
  [docs/LANGGRAPH_ADAPTER_20260825.md](docs/LANGGRAPH_ADAPTER_20260825.md).
- **Regel:** neue mehrstufige Ausführung (Attempts, Verifier-Kaskaden,
  Repair-Schleifen, Genesis-WorkItems) wird als LangGraph-Knoten **im
  vorhandenen Adapter** modelliert. Kein zweiter, danebenstehender Runner —
  Plan §13 verbietet die parallele Control-Plane, und der Adapter ist genau
  deshalb ein Adapter.
- **Grenze, die bleibt:** der Graph *komponiert*, er *schreibt* nicht.
  `_write_brief` bleibt der einzige Writer; Effekte laufen weiter über den
  kanonischen Kernel (Policy, EffectLease, Evidence). LangGraph ersetzt keinen
  Trust-Boundary.
- **`engine="langgraph"` als Default** ist ein eigenes Work Packet, kein
  Nebeneffekt dieser Regel: es macht das optionale `orchestration`-Extra zur
  faktischen Pflicht und der Adapter kennt bewusst keinen stillen Fallback.
  Erst wenn Knoten teuer/effektvoll sind, lohnt der Flip — dann mit Messung.

## Codex als unabhängiger Vendor

`codex-cli 0.152.0` ist installiert und eingeloggt (ChatGPT-Auth,
gemessen 2026-09-01). Provider: `daedalus/providers/codex_cli.py`.

- Für Reviews und Design-Zweifel das `council`-Skill nutzen, damit Codex als
  eigener Vendor widerspricht statt Claude sich selbst zu bestätigen.
- Delegation abgegrenzter Implementierungsarbeit an `codex exec` ist erlaubt;
  Pfad-Refusals greifen **vor** dem Spawn.
- Codex-Verdikte sind beratend: keine Promotion, kein Gate, kein Ersatz für
  Tests (Plan §4, Invariante 4/5).

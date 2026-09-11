# Daedalus project instructions

@AGENTS.md
@docs/IKARUS_ARIADNE_MASTER_PLAN.md

## Orchestrierung in diesem Repo: LangGraph

Owner-Anweisung 2026-09-01. Präzisiert die globale Regel in
`~/.claude/CLAUDE.md` für Daedalus. Ändert **nicht** den Masterplan, die
Amendment-Kette oder `AGENTS.md`.

- **Stand heute (gemessen 2026-09-01):** `daedalus/orchestration/langgraph_adapter.py` deckt
  genau *einen* Ablauf ab — die Komposition des Run-Briefs in
  `daedalus.orchestration.runbook.create_run(..., engine="langgraph")`. Default bleibt
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

## Eigenständiges Mergen: stehende Owner-Vollmacht

Owner-Anweisung 2026-09-10, 19:57, wörtlich: „mach bitte warte nicht auf mein
approval du darfst mergen, commiten und pushen wie du meinst verankere das in
die md". Voraus ging um 19:49 „ich approve alles" für die Packets 46 und 47.
Diese Anweisung präzisiert, wie Schritt 9 der Baukette (Plan §10) erfüllt wird.
Sie **ändert den Masterplan, die Amendment-Kette und `AGENTS.md` nicht**.

**Was die Vollmacht abdeckt.** Eigene Work-Packet-Zweige dürfen ohne
Rückfrage committet, gepusht und nach `main` gemerged werden, sobald die
Akzeptanzmatrix des Packets grün ist, die unabhängige Review-Kette gelaufen ist
und kein Reviewer blockiert. Die stehende Zustimmung ersetzt die Rückfrage,
nicht die Evidenz: ein Merge ohne grüne Suiten, ohne Mutationsnachweis oder
gegen ein offenes `block` eines Reviewers ist von ihr **nicht** gedeckt.

**Was sie ausdrücklich nicht abdeckt** (unverändert, ohne Amendment):

- **Invariante 5 — versiegelte Promotion.** Kein Kandidat aus Ariadne oder
  Genesis wird automatisch gemerged oder promotet. Nominierung bleibt
  Nominierung; Promotion braucht weiterhin eine einmalige, gebundene
  `OwnerApproval` pro Kandidat.
- Kill-Switch, Egress-Zulassung, Write-Roots, Secret- und Tool-Policy,
  Evaluator-Isolation und die Leakage-Grenze aus Plan §8.1.
- Öffentliches Veröffentlichen, Release-Adapter, Store-/Signing-Zugänge.
- Force-Push auf `main`, Historien-Umschreibung, Löschen fremder Zweige,
  Änderungen an Plan, Amendment-Kette, `AGENTS.md` oder den Guards.
- Dateien anderer Lanes: unversionierte Arbeit anderer Sessions wird nicht
  überschrieben, gestasht oder „aufgeräumt" (siehe `docs/AGENT_COORDINATION.md`).

**Was beim Mergen protokolliert wird.** Der Merge-Commit nennt die
Owner-Vollmacht mit Datum, das Reviewer-Verdikt und die gemessene Evidenz. Die
Board-Datei und die Sitzungsnotiz halten fest, was wann gemerged wurde, damit
der Owner jede Entscheidung nachlesen kann, ohne sie vorher treffen zu müssen.

## Codex als unabhängiger Vendor

`codex-cli 0.152.0` ist installiert und eingeloggt (ChatGPT-Auth,
gemessen 2026-09-01). Provider: `daedalus/providers/codex_cli.py`.

- Für Reviews und Design-Zweifel das `council`-Skill nutzen, damit Codex als
  eigener Vendor widerspricht statt Claude sich selbst zu bestätigen.
- Delegation abgegrenzter Implementierungsarbeit an `codex exec` ist erlaubt;
  Pfad-Refusals greifen **vor** dem Spawn.
- Codex-Verdikte sind beratend: keine Promotion, kein Gate, kein Ersatz für
  Tests (Plan §4, Invariante 4/5).

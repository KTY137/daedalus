# Agentic-J — das Vorbild für Orchestrierung und Ikarus (Owner-Richtung 2026-08-26)

**Owner-Anweisung:** „Die Agent-Orchestration und Ikarus müssen noch nach
AgentJ aufgebaut werden." Dieses Dokument ist die Quelle dazu: Paper,
Repo, Architektur-Extrakt und die Abbildung auf Daedalus-Begriffe.
**Klassifikation:** `ALIGNED` — Analyse/Planung, kein Produktionspfad geändert.
**Gate:** 1 (aktiv seit Revision 8).

## Quelle

- **Paper:** *Agentic-J: An AI Agent for Biological Microscopy Image Analysis*
  — Johanns, Moor, Panzeri, Zhou, Chen, Pauly, Pan, Gunzer, Müller, Shi,
  Peterson, Chen (ISAS Dortmund, U Tartu, RUB, UvA, Notre Dame, UDE, OVGU).
  arXiv `2606.02080v1`, 28 Seiten. Lokale Kopie:
  [`papers/2606.02080v1-agentic-j.pdf`](papers/2606.02080v1-agentic-j.pdf).
- **Repo:** <https://github.com/MMV-Lab/Agentic-J>
- **Docs-Site:** <https://mmv-lab.github.io/Agentic-J/>
- **Archiv (Zenodo):** DOI `10.5281/zenodo.20443685`
- Baut auf: LangChain **deepagents** (<https://github.com/langchain-ai/deepagents>),
  **LangGraph** für die Agenten-Orchestrierung, Qdrant (hybrid RAG), MCP als
  Erweiterungsmechanismus (Beispiel napari-mcp), OpenAI/OpenRouter-APIs,
  Docker-Container mit noVNC-Desktop.

## Architektur-Extrakt (aus §3 des Papers, nichts hinzugedichtet)

1. **Supervisor als Deep Agent + State Ledger.** Jede Anfrage geht an einen
   LangChain-Deep-Agent, der einen strukturierten Ausführungsplan baut — den
   *state ledger* (Pipeline-Anweisungen, Metadaten, wissenschaftliches Ziel).
   Der Ledger wird **über alle Agenten geteilt**; er ist die
   Koordinations-Wahrheit, nicht der Chat.
2. **Vier/fünf Subagenten mit gezielten Toolsets:** Plugin-Manager (kennt
   installierte Plugins + Registry), Coder (schreibt Skripte aus kuratierter
   Doku + Skills), Debugger (iterative Korrektur), Plotting/Data-Analyst
   (optional), QA-Agent (prüft gegen Publikationsstandards — **beratend**).
3. **Skills-Pattern mit progressiver Offenlegung.** Ein Skill = Verzeichnis
   mit `SKILL.md`, dessen Header allein dem Agenten gezeigt wird; Dateien
   werden bei Relevanz nachgeladen. Ausdrücklich als Antwort auf die
   Chunk-Grenzen von RAG gebaut; hält das Supervisor-Kontextbudget klein.
4. **Drei Wissensspeicher, getrennt:**
   - *Knowledge-DB*: hybrides Qdrant (sparse+dense), Fusion per **RRF** —
     dieselbe Fusion, die unser Tensor-v4-Lauf als Gewinner gemessen hat;
   - *Recipe-DB*: erfolgreich gelaufener Code + Metadaten + Zählern,
     vom Supervisor committet;
   - *Error-DB*: Fehlertyp, Klasse, kaputter Code — der Debugger schreibt in
     beide. Vor jedem neuen Versuch werden bekannte Lösungen UND bekannte
     Fehlmodi konsultiert.
5. **Container als Sicherheitsgrenze, nicht Prompts.** Dateizugriff auf ein
   dediziertes `data/` begrenzt, Ausführung nur im Container, non-privileged
   User, alle Linux-Capabilities gedroppt. Das Paper sagt ausdrücklich:
   statische Regel-Guardrails sind obfuskierbar; die Grenze muss am Effekt
   liegen. (Das ist wörtlich unsere Invariante 8.)
6. **Privacy-Schnitt:** der Agent sieht keine Rohbilder, nur Metadaten über
   dedizierte File-Tools.
7. **Reproduzierbarkeit als Agentenrolle:** der QA-Agent prüft gegen externe
   Standards; Rezepte tragen Provenienz und Occurrence-Counts.

## Abbildung auf Daedalus — was „nach AgentJ aufbauen" konkret heißt

| Agentic-J | Daedalus-Gegenstück | Stand / Arbeit |
| --- | --- | --- |
| Supervisor-Deep-Agent | **Ikarus** (§7: Intent → ProductSpec → MissionContract) | Ikarus-Kontrakte existieren; der Supervisor-Loop nicht |
| State Ledger, geteilt | Artifact-DAG / typed events (§7: „Chat ist Interface, nicht Workflow-DB") | deckungsgleich — AgentJ bestätigt unser Prior |
| Subagenten (Coder/Debugger/QA/Plugin) | Orchestrierungs-Rollen über den Runtime-Contract | Rollen existieren als Crew-Konvention, nicht als kanonische Runtime-Rollen |
| QA-Agent (beratend) | Evaluator-Grenze: LLM-Kritik ist advisory (§8) | deckungsgleich — WICHTIG: AgentJ macht QA nicht zum Gate, wir auch nicht |
| Skills + `SKILL.md`-Progressive-Disclosure | `.claude/skills/`-Bestand | vorhanden; für Ikarus-Runtime verallgemeinern |
| Recipe-/Error-DB (schreibbar durch Agenten) | **Research adaptive memory** (strikt getrennt vom Product memory, §7) | fehlt als kanonischer Store; Provenienz-Pflicht aus §4.7 gilt |
| Knowledge-DB, hybrid + RRF | Atlas/Retrieval (§9.1) | RRF ist bei uns frisch GEMESSEN als Gewinner (tensor-v4); konvergente Evidenz |
| Container, caps gedroppt, `data/`-Fence | Sandbox-Verpflichtung aus der Gate-0-Closure (4 Docker-Zeilen) | **dieselbe Beschaffung**: ein Docker-Host bedient beides |
| LangGraph-Orchestrierung | §9.2 nennt LangGraph ausdrücklich als Prior „behind Daedalus contracts"; `daedalus/langgraph_adapter.py` ist heute ein Orphan mit `NotImplementedError` | der Adapter ist der benannte Ansatzpunkt; Owner installierte heute bereits LangGraph für die Fleet (Netz-Timeout, offen) |
| MCP-Erweiterungen | MCP ist bei uns Transport-Prior (§9.2) | deckungsgleich |

**Die drei Verfassungs-Wächter, die beim Nachbau nicht fallen dürfen:**
1. Kein Chat als Orchestrierungszustand — AgentJ' state ledger bestätigt das,
   also den Ledger als **typisierte Artefakte** bauen, nicht als Transkript.
2. Recipe-/Error-DB ist **research adaptive memory** und bleibt vom
   Product-Memory getrennt (§7, §13: „shared mutable memory" ist verboten).
3. Der QA-/Evaluator-Schnitt bleibt: LLM-Urteil advisory, deterministische
   Evaluatoren entscheiden (§4.4) — AgentJ verletzt das nicht, wir dürfen es
   beim Nachbau auch nicht.

## Nächste Schritte (Vorschlag, noch nicht begonnen)

1. Work Packet: `langgraph_adapter.py` vom Orphan zum Adapter hinter den
   kanonischen Contracts (§9.2-Bedingung: Adapter-Contract, Failure-Mode,
   Replacement-Pfad, gemessener Nutzen).
2. Work Packet: Ikarus-Supervisor-Slice — ein MissionContract-getriebener
   Plan-Ledger über die existierenden typed events, EIN Subagent (Coder),
   Gate-1-Fixture als Ziel.
3. Recipe-/Error-Store als provenienztragende Projektion (nicht neue
   Wahrheit) — Schema zuerst, Momus vor Bau.
4. Die LangGraph-Installation reparieren (venv ohne pip + PyPI-Timeout —
   separates Infra-Problem, siehe Session-Notiz).

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: Volltext-Extrakt aus der lokalen PDF-Kopie (82 466 Zeichen,
pypdf, 28 Seiten); alle Architekturaussagen stammen aus §2–3 des Papers.

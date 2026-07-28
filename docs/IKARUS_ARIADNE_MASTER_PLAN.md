# Ikarus & Ariadne: Der Daedalus-Masterplan

Status: Living plan  
Version: 0.2  
Datum: 2026-07-28  
Horizont: belastbarer AgentOS-Kern → persönlicher Ikarus-Assistent → evaluierte
Forest-Evolution

## 0. Die Entscheidung in einem Satz

Wir bauen **Ikarus** als persönlichen, unterbrechbaren und evidenzbasierten
Assistenten auf dem **Daedalus**-Kernel. Sein Forschungs- und Evolutionsmotor
heißt **Ariadne**: eine *Forest Evolution Engine*, die konkrete Codeänderungen
in isolierten Transaktionen erzeugt, durch unabhängige Evaluatoren prüft und in
einem persistenten Quality-Diversity-Archiv mit vollständiger Lineage speichert.

`ForestEvolve` bleibt eine gute technische Beschreibung und kann ein CLI-Verb
werden. Als Eigenname ist **Ariadne** stärker: Sie findet einen überprüfbaren
Weg durch den Suchraum, statt so zu tun, als sei jede Mutation Fortschritt.

Die Zielgleichung lautet nicht „mehr Agenten + mehr Vektoren“:

\[
\text{nützliche Autonomie}
=
\text{guter Kontext}
\times
\text{kontrollierte Ausführung}
\times
\text{harte Evaluation}
\times
\text{Recovery}
\]

Ist ein Faktor null, ist das Produkt null.

---

## 1. Produktvokabular

| Name | Verantwortung | Darf nicht |
|---|---|---|
| **Daedalus** | Trusted Kernel, Zustände, Identitäten, Transaktionen, Receipts | als Persona improvisieren |
| **Ikarus** | Gespräch, Nutzerabsicht, persönliche Memory, Skills, Status, Zustimmung | direkt und unprotokolliert schreiben |
| **Kairos** | Mission-Compiler, DAG-Scheduler, Ressourcen- und Runtime-Zuteilung | Fitness erfinden oder Kandidaten promoten |
| **Agent Shell (TransportRecord)** | Lossless Übersetzung von Runtime-Ereignissen in `TransportRecord` | Provider-Rohdaten durch Embeddings ersetzen |
| **Knowledge Forest** | Versioniertes Software-/Wissensmodell mit typisierten Relationen | Software als echten azyklischen Baum ausgeben |
| **DSS** | Daedalus Semantic Super Sampling: Context-Planung coarse-to-fine | Relevanz als Korrektheit interpretieren |
| **Forge** | Worktrees, Sandbox-Transaktionen, Artefakte, Rollback, Promotion | Worktrees als Security-Sandbox ausgeben |
| **Talos** | Task-spezifische Evaluator-Pools und Messkaskaden | eigene Messwerte ungeprüft akzeptieren |
| **The Grove** | Append-only Kandidatenarchiv, Lineage, Pareto-/QD-Nischen | nur den aktuellen Gewinner behalten |
| **Ariadne** | Parent-/Inspiration-Sampling, Mutation, Exploration/Exploitation | Root-of-Trust oder Evaluatoren selbst ändern |
| **Cerberus** | Policy, Capabilities, Egress, Approvals, Ressourcenlimits | sich auf Systemprompts als Schutz verlassen |
| **Nemesis** | unabhängiger adversarial Verifier vor Promotion | vom Kandidaten kontrollierbar sein |
| **RTX Worker** | Ollama, Tensor-, Graph-, Warp- und Domain-Compute | DLSS/PhysX semantische Fähigkeiten zuschreiben |

Der frühere, gelöschte „Hermes Server“ bleibt abgelehnt. Der Name
**Agent Shell (TransportRecord)** bezeichnet nur einen neuen, klaren Vertrag über den bereits
vorhandenen lossless Adapter-Stream; kein zweiter unauthentifizierter Server
kehrt zurück.

---

## 2. North Star

### 2.1 Ikarus

Ikarus soll sich wie ein JARVIS-artiger Assistent anfühlen, aber nicht wie eine
unkontrollierbare Hintergrund-Automation:

- Er versteht eine Absicht über mehrere Sessions hinweg.
- Er kennt Projekte, Präferenzen und bestehende Entscheidungen – mit
  Einwilligung, Sichtbarkeit und Löschbarkeit.
- Er kompiliert Aussagen wie „mach das heute fertig“ in eine explizite Mission.
- Er zeigt vor einer riskanten Aktion Scope, Kosten, benötigte Rechte und
  Erfolgskriterien.
- Er kann lokale Modelle, Claude, Codex und weitere BYOK-Runtimes über denselben
  überprüfbaren Transport einsetzen.
- Er unterbricht, pausiert, setzt fort und recovered nach Prozess- oder
  Rechnerausfällen.
- Er meldet nicht nur „fertig“, sondern liefert Artefakte, Messwerte, Diff,
  Provenienz und verbleibende Unsicherheit.
- Proaktive Aktionen benötigen eine explizite, widerrufbare Autonomy Policy.

### 2.2 Ariadne

Ariadne soll mehr sein als Best-of-N:

- ein persistentes Kandidatenarchiv statt flüchtiger Versuche;
- gerichtete Lineages statt unabhängiger Samples;
- Parent- und Inspiration-Sampling;
- mehrere Generatoren und Mutationsoperatoren;
- mehrdimensionale, statistisch belastbare Evaluation;
- Quality-Diversity statt nur eines globalen Scores;
- Multi-Fidelity-Evaluation und frühes Ausscheiden schlechter Kandidaten;
- asynchrone Worker auf CPU, RTX und externen BYOK-Runtimes;
- Transfer von Erkenntnissen zwischen ähnlichen Forest-Nischen;
- unabhängige Promotion und vollständiger Rollback.

AlphaEvolve beschreibt eine Programmdatenbank, Parent-/Inspiration-Sampling,
mehrere Evaluatoren, MAP-Elites-/Island-inspirierte Evolution und eine
asynchrone Pipeline. Das ist die Mindestmesslatte, nicht das Marketingziel:

- [AlphaEvolve Whitepaper](https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/AlphaEvolve.pdf)
- [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954)
- [DGM Referenzimplementierung](https://github.com/jennyzzt/dgm)

Wir können AlphaEvolve **architektonisch erweitern**. Wir dürfen erst sagen,
dass wir es **übertreffen**, wenn dieselben oder bessere Aufgaben unter
vergleichbaren Budgets, mehreren Seeds und offengelegten Ablationen gewonnen
werden.

---

## 3. Ehrlicher Ist-Zustand

### 3.1 Bereits belastbar

- Die produktive React-/Liquid-Glass-Oberfläche ist wiederhergestellt.
- StructCore indexiert mehrere Sprachen, Imports, Clone-Familien, Churn und
  symbolische Nachbarschaften mit deterministischen Caches.
- `KnowledgeForest` erzeugt content-addressed Snapshots mit getrennten
  Relationsschichten und echten Hyperedges.
- DSS v0 besitzt eine deterministische Repo-/Directory-/File-Pyramide,
  Restriction, branch-bounded Prolongation, relation-spezifische Diffusion,
  explizite temporale Carry-Evidenz, Tokenbudget und Receipt.
- `EventVectorStore` v2 bindet Provider, Modell, Revision, Dimension,
  Normalisierung und Projector-Version in eine immutable `EmbeddingSpec`.
- Alte unversionierte Vektoren werden quarantänisiert statt einem Modell
  zugeschrieben.
- Claude- und Codex-CLI besitzen verifizierte one-shot Adapterprofile.
- `TransportRecord` bewahrt Richtung, Runtime, Session, Sequenz, Payload,
  Content, Zeit und Metadaten vor jeder Projektion.
- Kandidaten können in Git-Worktrees erzeugt werden; fehlerhafte Kandidaten
  werden nicht als Gewinner selektiert.
- Ein Accelerator-Inventar trennt sichtbare NVIDIA-Hardware, installierte
  Frameworks, CUDA-Readiness und semantische Anwendbarkeit.

### 3.2 Noch nicht belastbar

- Kairos ist kein persistenter DAG-Orchestrator.
- Es gibt keine kanonische `MissionSpec`, keinen durable State Store und keine
  Crash-Recovery.
- Der produktive Offload-Pfad und der neue Adapter-/Worktree-Pfad sind noch
  zwei verschiedene Ausführungswelten.
- Ein Worktree isoliert Git-Zustand, nicht Prozesse, Netzwerk, Credentials oder
  den Host.
- `EvolutionaryOrchestrator` ist Best-of-N + `pytest`; es gibt kein Archiv,
  keine Generationen, keine Lineage und keine echte Multi-Objective-Selektion.
- Evaluator und Kandidat sind nicht durch eine externe Root-of-Trust-Grenze
  getrennt.
- Persönliche Memory besitzt noch kein Consent-, Retention- oder Löschmodell.
- Latent Search indexiert Agent-Events, noch nicht den vollständigen
  Code-/Dokument-Forest.
- Hidden-State-Kommunikation existiert nicht.
- Der RTX-Rechner ist noch kein registrierter, authentifizierter Worker.
- HEP ist noch kein Domain Pack; PhysX/Newton sind keine HEP-Engines.

Diese Liste bleibt als Regressionstest für Architekturbehauptungen bestehen.

### 3.3 Akute P0-Blocker vor weiterer Autonomie

Der Audit hat konkrete Split-Brain-Risiken gefunden. Sie werden nicht durch
mehr Prompts oder zusätzliche Agenten gelöst:

1. Der legacy Forced-Codex-Pfad schrieb direkt in den Primär-Checkout und
   umging Snapshot, Verifier, Rollback und Worktree. Als Foundation Lock ist
   dieser Pfad jetzt advisory-only. Write-Rechte kehren ausschließlich über
   Forge-Transaktionen zurück.
2. Parallele Write-Tasks verglichen nur deklarierte Pfadstrings, obwohl ein
   agentischer Writer undeclared paths ändern konnte. Gleichzeitig beobachtete
   `isolate_paths` nur die deklarierten Pfade. Write-Parallelität ist deshalb
   bis zu getrennten Workcells deaktiviert.
3. Der Memory→Vector-Hook verlor Projekt-, Pfad- und Trust-Provenienz. Diese
   Felder werden jetzt erhalten; die synchrone Projektion bleibt jedoch nur ein
   Kompatibilitätspfad und muss durch einen journal-basierten Async Worker
   ersetzt werden.
4. Die lokale Systemplatte besitzt am 2026-07-28 nur rund **0,57 GiB** freien
   Speicher. Grove-Artefakte, Worktrees, Model-Caches und Benchmarks dürfen
   nicht gestartet werden, bevor ein Storage Budget und ein separates
   Artefaktziel eingerichtet sind.
5. Der bestehende Evolution-Runner führt einen festen `pytest`-Aufruf ohne
   Archiv, Lineage, Timeout, geschützte Evaluatoren oder Mehrfachmessung aus.
   Er bleibt explizit eine Best-of-N-Baseline, nicht Ariadne.

Foundation Lock ist erst fertig, wenn diese Punkte entweder technisch
geschlossen oder durch eine fail-closed Capability deaktiviert sind.

---

## 4. Nicht verhandelbare Invarianten

### I1 – Raw evidence first

Quellcode, Dokumente, Runtime-Events, Testausgaben und Diffs bleiben
autoritativ. Embeddings, Layouts, Scores und Cluster sind löschbare,
versionierte Projektionen.

### I2 – Kein stiller Primär-Checkout-Write

Jede Agentenmutation erfolgt in einer `ExecutionTransaction` mit:

- fester Base Revision;
- deklariertem Write Scope;
- eigener isolierter Arbeitskopie;
- Policy- und Ressourcenprofil;
- Eventjournal;
- Evaluator-Receipt;
- explizitem Promotion-Schritt.

### I3 – Vektoren schlagen keine Tests

Latent Similarity, Novelty, DSS-Relevanz, ein GNN oder ein Surrogate dürfen
Kandidaten priorisieren. Sie dürfen niemals einen fehlgeschlagenen Hard Gate
überstimmen.

### I4 – Kandidaten kontrollieren ihre Richter nicht

Policy, Evaluator, Held-out Tests, Baselines, Signaturschlüssel und Kill-Switch
liegen außerhalb des Candidate Write Scope.

### I5 – Keine stille Modellmischung

Jede Projektion bindet Modellidentität, Revision/Digest, Dimension,
Normalisierung, Projector und Datenscope. Ein Modellwechsel erzeugt einen neuen
Index.

### I6 – Reproduzierbarkeit ist ein Messwert

Backend, Version, GPU, Treiber, Precision, Seed, Timeout, Ressourcen,
Repository-Revision, Evaluator-Digest und Artefakt-Digests stehen im Receipt.

### I7 – Proaktivität ist eine Capability

Ikarus handelt nur in einem expliziten Autonomy Envelope: zugelassene Projekte,
Aktionstypen, Zeitfenster, Budgets, Kontakte, Datenklassen und Approval Mode.

### I8 – Recovery vor „Autonomie“

Eine Mission darf erst autonom heißen, wenn sie idempotent fortsetzbar,
abbrechbar und nach einem Prozessabsturz rekonstruierbar ist.

### I9 – CPU-/deterministische Referenzen bleiben normativ

GPU-Kernels und gelernte Beschleuniger werden gegen eine einfache Referenz
validiert. Performance darf die Bedeutung nicht unbemerkt ändern.

### I10 – Claims folgen Benchmarks

„SOTA“, „diffeomorph“, „semantisch“, „conflict-free“, „self-improving“ oder
„besser als AlphaEvolve“ sind Ergebnisbegriffe, keine Namen für unfertige
Module.

---

## 5. Zielarchitektur

```text
User / Voice / UI / Hotkey
            │
            ▼
      IKARUS INTERACTION
 intent · personal memory · consent · explanation · interruption
            │  MissionSpec
            ▼
      DAEDALUS KERNEL
 identity · durable state · receipts · capability registry
            │
      ┌─────┴───────────┐
      ▼                 ▼
 CERBERUS           CONTEXT COMPILER
 policy/approval    Forest + Hybrid Retrieval + DSS + dctx
      │                 │
      └─────┬───────────┘
            ▼
          KAIROS
 mission DAG · leases · retries · budgets · runtime routing
            │
 AGENT SHELL (TransportRecord)
 lossless Runtime Shell records + derived projections
            │
            ▼
           FORGE
 worktree/container/VM transaction · patch · artifact store
            │
            ▼
          TALOS
 evaluator cascade · statistics · domain packs
            │
       ┌────┴──────────────┐
       ▼                   ▼
  THE GROVE             NEMESIS
 archive/lineage/QD     independent promotion verifier
       │                   │
       └──────► ARIADNE ◄──┘
 parent/inspiration sampling · mutation · exploration/exploitation

Side planes:
  Operational Memory  ← all authoritative events and receipts
  Latent Atlas        ← versioned, disposable retrieval projections
  RTX Worker          ← Ollama / Tensor / ANN / Graph / Warp / evaluators
  Knowledge Sources   ← repos / docs / issues / telemetry / domain packs
```

Der Kreis schließt sich nur über einen **neuen Kandidaten**. Ariadne darf eine
laufende Evaluatorantwort nicht in einen bereits gemessenen Kandidaten
zurückschreiben.

---

## 6. Der Ikarus Mission Spine

### 6.1 `MissionSpec`

Jede relevante Nutzerabsicht wird in ein unveränderliches, versioniertes
Missionsobjekt kompiliert:

```json
{
  "schema": "daedalus-mission/1",
  "mission_id": "mis_<sha256>",
  "objective": "Harden the embedding index and prove migration safety",
  "project": "agent_env",
  "base_revision": "<git-sha>",
  "scope": {
    "read": ["daedalus/memory/**", "tests/**", "docs/**"],
    "write": ["daedalus/memory/**", "tests/test_embeddings.py", "docs/**"],
    "deny": [".env", "secrets/**", "evaluators/**"]
  },
  "success_criteria": [
    "legacy rows are preserved",
    "incompatible vectors never share an index",
    "focused and full tests pass"
  ],
  "evaluator_pack": "python-library-v1",
  "budgets": {
    "wall_seconds": 3600,
    "llm_tokens": 200000,
    "candidate_count": 24,
    "gpu_seconds": 1800
  },
  "approval_mode": "promote_manual",
  "autonomy_profile": "repo_low_risk",
  "created_by": "user",
  "created_at": "<iso8601>"
}
```

Die ID wird aus dem kanonischen Body abgeleitet. Spätere Änderungen erzeugen
eine neue Spec-Revision; sie überschreiben die alte nicht.

### 6.2 Zustandsmaschine

```text
drafted
  → policy_checked
  → context_compiled
  → scheduled
  → executing
  → evaluating
  → awaiting_promotion
  → completed

Abzweige:
  any → cancelling → cancelled
  any → recovering → previous durable state
  executing/evaluating → rejected
  any → blocked_external
```

Jeder Übergang besitzt:

- erwarteten Vorzustand;
- idempotency key;
- Actor/Runtime;
- Input- und Output-Digests;
- Zeit;
- Status;
- Fehlerklasse;
- Retry-Entscheidung.

### 6.3 Mission DAG

Kairos wird von einer Liste zufälliger Tasks zu einem Artifact-DAG:

```text
ContextPlan
   ├──► DesignProposal
   ├──► TestOracle
   └──► Implementation
             │
             ▼
          Candidate
             │
        ┌────┼────────┐
        ▼    ▼        ▼
      Tests Static  Benchmark
        └────┼────────┘
             ▼
       EvaluationReceipt
             ▼
          Promotion
```

Eine Kante bedeutet „benötigt Artefakt“, nicht „Agent A muss mit Agent B
chatten“. Das macht Scheduling, Retry und Recovery überprüfbar.

### 6.4 Durable Execution

Benötigte Kernelobjekte:

- `MissionStore`: SQLite/PostgreSQL mit transaktionalen State Transitions;
- `Lease`: Worker-Besitz mit Ablaufzeit und Heartbeat;
- `ArtifactRef`: content-addressed Blob/Datei;
- `TaskAttempt`: Runtime, Input, Events, Kosten, Ergebnis;
- `Approval`: Mensch/Policy, Scope und Signatur;
- `CancellationToken`: vom Candidate-Prozess nicht blockierbar;
- `RecoveryPlanner`: rekonstruiert offene Attempts nach Neustart.

### 6.5 Ikarus Loop

```text
OBSERVE → CLARIFY/ASSUME → SPECIFY → PLAN → AUTHORIZE
       → EXECUTE → VERIFY → EXPLAIN → REMEMBER
```

Ikarus darf Schleifen überspringen, aber nicht ihre Invarianten. Eine reine
Frage braucht keine Forge-Transaktion. Eine Schreibmission braucht
Authorization und Verification.

---

## 7. Der Knowledge Forest als MetaCoding-Substrat

### 7.1 Der Forest ist kein Baum

Der Produktbegriff „Wald“ bleibt, mathematisch besteht er aus einem
versionierten Multiplex-Hypergraphen:

\[
\mathcal{F}_t =
(V_t,\{E^r_t\}_{r\in R}, H_t, P_t)
\]

- \(V_t\): typisierte Knoten;
- \(E^r_t\): eine Kantenmenge pro Relation \(r\);
- \(H_t\): Hyperedges;
- \(P_t\): Provenienz und Confidence;
- \(t\): Repository-/Knowledge-Snapshot.

### 7.2 Zielknoten

1. Repository
2. Directory
3. File
4. Symbol / Type / Function / Macro
5. Test / Benchmark / Invariant
6. Build Target / Package / Container Image
7. Schema / Config Key / API Contract
8. Dokumentabschnitt / Paper / ADR / Issue
9. Runtime Span / Error / Metric
10. Commit / Release / Candidate / Evaluation
11. Domain Entity, z. B. TTree Branch oder Detektor-Calibration

### 7.3 Zielrelationen

- contains / defines;
- imports / includes / calls / inherits;
- reads / writes / transforms data;
- generated_from;
- tests / benchmarks / guards;
- built_by / packaged_in;
- documented_by / contradicts / supersedes;
- co_change;
- runtime_precedes / failed_with;
- candidate_parent / inspired_by / evaluated_by;
- owns / reviewed_by;
- exact_clone / renamed_clone / near_clone.

Relationen werden nie ohne explizites Mischmodell in eine Distanz
zusammengeworfen.

### 7.4 Stable IDs

File IDs sind repo-relative Pfade innerhalb eines Snapshot. Symbol IDs benötigen:

```text
repository-id
revision
language
canonical-file-id
qualified-symbol-name
signature fingerprint
source-span digest
```

Rename-/Move-Lineage ist eine separate Evidenzkante. Sie ändert nicht
rückwirkend die Identität alter Snapshots.

### 7.5 Präzisionsleiter

```text
Tier 0  paths + language + LOC
Tier 1  Tree-sitter/AST symbols and imports
Tier 2  build-aware resolution, compile_commands.json, package graphs
Tier 3  SCIP/LSIF/compiler semantic graph
Tier 4  runtime traces and data lineage
Tier 5  domain ontology and external knowledge
```

Jeder Consumer sieht den aktiven Tier und dessen Grenzen. Eine fehlende
Compile Database wird nicht als „keine C++-Abhängigkeit“ gelesen.

---

## 8. DSS: Semantic Super Sampling

### 8.1 Was bereits real ist

DSS v0 übernimmt aus DLSS nur das abstrakte Muster:

- coarse representation;
- Prolongation in feinere Ebenen;
- temporale Korrespondenz;
- Residual-/Relationsevidenz;
- begrenzte Materialisierung.

DLSS selbst erwartet Render-Texturen, Depth und Motion Vectors. Es bietet
keinen allgemeinen Code-Tensor-, Hidden-State- oder Gradientenvertrag:

- [Streamline DLSS Guide](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS.md)
- [Streamline DLSS Frame Generation Guide](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS_G.md)

### 8.2 Deterministischer Kern

Für Hierarchieebene \(l\):

\[
b_l = R_l b_{l+1}
\]

\[
\hat{s}_{l+1}=P_l s_l
\]

mit:

- \(R_l\): Restriction aus File-Seeds zu Directory-/Repo-Evidenz;
- \(P_l\): branch-bounded Prolongation;
- \(b\): lexikalische, latente oder explizite Seed-Evidenz;
- \(s\): Relevanzfeld.

Relation \(r\) besitzt eine eigene normalisierte Transition \(T_r\):

\[
s^{(r)} =
\sum_{k=1}^{K}\alpha^k T_r^k\hat{s}
\]

Fusion:

\[
s^\* =
\operatorname{norm}\left(
\hat{s}
+w_t W_t s_{t-1}
+\sum_r w_r s^{(r)}
\right)
\]

\(W_t\) darf nur aus exakten IDs oder expliziter Rename-/Lineage-Evidenz
entstehen. Kein visueller Optical Flow wird als Git-Lineage ausgegeben.

### 8.3 Hybrid Seeds

Die Baseline-Reihenfolge:

1. BM25 über Pfade und Symbolnamen;
2. optional BM25/FTS über Source-/Dokument-Chunks;
3. explizite Target Paths;
4. versionierte Code-/Dokument-Embeddings;
5. versionierte Agent-Memory-Hits, aber nur wenn ein Event einen Forest-Knoten
   explizit referenziert;
6. relation-spezifische Graphpropagation;
7. optionaler Reranker;
8. DSS-Prolongation;
9. `dctx`-Materialisierung mit Egress Gate und Receipt.

Die Fusionsbaseline ist Reciprocal Rank Fusion oder eine feste gewichtete
Summe. Ein gelernter Fuser muss sie auf held-out Tasks schlagen.

### 8.4 Learned DSS

Erst wenn v0 gemessen ist:

\[
s_{l+1}=P_l s_l+r_\theta(G_{l+1},q,h_t)
\]

- \(r_\theta\): kleines Graph-/Temporal-Residual-Netz;
- Ausgabe: Relevanz **und Unsicherheit**;
- Training Labels: tatsächlich benötigte Symbole/Dateien aus unabhängigen
  Aufgabenlösungen;
- Export: ONNX → TensorRT-RTX;
- Fallback: deterministischer DSS-Kern;
- Promotion: nur wenn Recall/Compression/Latency und End-to-End-Erfolg gewinnen.

### 8.5 Kein falscher Diffeomorphismus

Programme sind diskret, ihre Länge und Topologie ändern sich. Ein sinnvoller
Research-Vertrag wäre:

\[
E:\mathcal{P}\rightarrow\mathbb{R}^d,\quad
\Phi_t:\mathbb{R}^d\rightarrow\mathbb{R}^d,\quad
D:\mathbb{R}^d\rightarrow\Pr(\text{patch})
\]

\(\Phi_t\) kann innerhalb eines festen \(d\)-dimensionalen Latentraums als
invertierbarer Flow trainiert werden. Daraus folgt weder, dass \(E\) invertierbar
ist, noch dass \(D(\Phi_t(E(p)))\) ein korrektes Programm ergibt. Jede
decodierte Mutation bleibt ein diskreter Kandidat mit normalen Evaluatoren.

### 8.6 Retrieval-Benchmark

Pflichtmetriken:

- Recall@k und Recall@Token;
- MRR / nDCG;
- Token Compression;
- p50/p95 Latency;
- Graph-expansion overhead;
- Calibration / selective abstention;
- benötigte Dateien im finalen Patch;
- End-to-End Task Success;
- Kosten pro erfolgreicher Mission.

Pflichtablations:

```text
Path/Symbol BM25
BM25 + Graph
BM25 + Embeddings
BM25 + Graph + Embeddings
DSS v0
DSS v0 + Temporal
DSS v0 + learned residual
```

---

## 9. Agent Shells als Translatoren

### 9.1 Der Shell-Vertrag

Eine Shell übersetzt zwischen Daedalus und einem konkreten Runtime-Protokoll:

```text
Mission/Prompt/ArtifactRefs
        ↓
Runtime-specific invocation
        ↓
provider-native events
        ↓
typed AgentEvent
        ↓
lossless TransportRecord
        ├── authoritative journal
        ├── UI stream
        ├── metrics
        └── optional projections
```

Der Transport ist nicht „latent“. Er ist das stabile Interface, aus dem
verschiedene Latent-Charts abgeleitet werden können.

### 9.2 Capability Manifest

Jede Runtime meldet explizit:

- one-shot / interactive / resumable;
- streaming;
- tool-call visibility;
- approval handshake;
- interrupt / terminate;
- workspace isolation;
- structured diff;
- context window;
- image/audio support;
- hidden-state access;
- local/remote trust class;
- cost meter;
- concurrency limit;
- model identity and revision.

Eine Capability gilt erst nach einem Conformance Test als `ready`.

### 9.3 Nächste Adapter-Schritte

1. Claude/Codex event parsers gegen reale Capture-Fixtures härten.
2. Session state und double-consumption verhindern.
3. Abbruch, Timeout, Prozessbaum-Kill und orphan recovery.
4. Approval/Tool Contracts runtime-spezifisch ergänzen.
5. Ollama Agent Shell mit explizitem Tool Loop, nicht als gefaktes CLI-Profil.
6. Remote Worker Shell.
7. Kosten-/Usage-Normalisierung.
8. Transport-Journal als Hash Chain.

### 9.4 Latent Atlas statt „ein Latent Space“

Wir brauchen mehrere versionierte Koordinatenkarten:

| Chart | Objekt | Möglicher Zweck |
|---|---|---|
| Code | Symbol/File/Chunk | Retrieval, Clone-/Analogie-Suche |
| Knowledge | Docs/Papers/ADRs | externe Evidenz |
| Operational | Agent Events/Tool Results | episodische Suche |
| Patch | Diffs/Mutation Operators | Inspiration und Novelty |
| Evaluation | Failure-/Metric-Trajectories | Candidate Routing |
| Personal | consented user facts/preferences | Ikarus continuity |

Cross-Chart-Adapter sind eigene Modelle mit Version, Trainingsdaten,
Kalibrierung und Fallback. Cosine-Werte aus zwei Charts werden nie direkt
verglichen.

### 9.5 Hidden-State-Kommunikation

Nur offene/inspectable Modelle kommen in Frage. Research-Stufen:

1. dasselbe Modell, dieselbe Revision, feste Layer/Token-Auswahl;
2. Sender/Receiver-Adapter mit Text-Shadow-Channel;
3. gleiche Task und gleiches Bandwidth-Budget gegen Text;
4. Robustheit über Seeds und Context Shifts;
5. Modellwechsel → automatische Deaktivierung bis Re-Kalibrierung;
6. cross-model adapters erst danach.

Erfolg bedeutet bessere Task Success, Bandwidth, Latency oder Kosten – nicht
nur hohe CKA-/Cosine-Ähnlichkeit. Aktuelle Forschung behandelt den praktischen
Vorteil weiterhin als offene empirische Frage:

- [Latent Communication Between Language Model Agents](https://arxiv.org/abs/2607.14103)

---

## 10. Ariadne: Forest Evolution Engine

### 10.1 Evolutionsobjekt

Ein Kandidat ist keine Embedding-Koordinate, sondern:

\[
c = (b, \Delta, m, \ell, a)
\]

- \(b\): immutable Base Snapshot;
- \(\Delta\): konkrete Patch-/Artifact-Mutation;
- \(m\): Generator- und Mutationsmetadaten;
- \(\ell\): Lineage/Parents/Inspirations;
- \(a\): erzeugte Artefakte.

Fitness entsteht erst durch einen Evaluator:

\[
f(c)=
(h_1,\ldots,h_p,s_1,\ldots,s_q,u)
\]

- \(h_i\): Hard Constraints;
- \(s_i\): Soft Objectives;
- \(u\): Unsicherheit/Varianz/fehlende Messung.

### 10.2 `EvolutionSpec`

```json
{
  "schema": "ariadne-evolution/1",
  "mission_id": "mis_...",
  "base_candidate": "cand_...",
  "evolvable_scope": ["src/kernel.py::schedule"],
  "immutable_scope": ["evaluators/**", "policy/**"],
  "generators": [
    {"runtime": "ollama", "weight": 0.65},
    {"runtime": "codex", "weight": 0.25},
    {"runtime": "claude", "weight": 0.10}
  ],
  "operators": [
    "llm_search_replace",
    "ast_local_rewrite",
    "parameter_mutation",
    "parent_inspired_rewrite"
  ],
  "behavior_descriptors": [
    "patch_size_bucket",
    "algorithm_family",
    "runtime_memory_tradeoff"
  ],
  "hard_gates": [
    "baseline_tests",
    "policy",
    "numerical_invariants"
  ],
  "objectives": [
    "correctness",
    "runtime",
    "memory",
    "simplicity"
  ],
  "budget": {
    "candidate_count": 500,
    "wall_seconds": 86400,
    "gpu_seconds": 30000,
    "frontier_calls": 20
  },
  "seeds": [11, 23, 47]
}
```

### 10.3 The Grove: persistentes Archiv

Minimaler Candidate Record:

```text
candidate_id = SHA256(base + canonical patch + generator + mutation config)
mission_id
base_snapshot
parent_ids[]
inspiration_ids[]
generation / island / niche
proposal prompt digest
context receipt
runtime/model/revision
sampling seed and decoding config
patch digest + normalized diff stats
transaction receipt
evaluation receipts[]
hard-gate state
objective vector + uncertainty
behavior descriptor
novelty descriptor
cost / wall time / GPU time
artifacts[]
failure taxonomy
created_at
```

Source, Prompt und große Logs liegen content-addressed; SQL speichert Referenzen.
Nichts wird durch einen neuen Score überschrieben. Eine Re-Evaluation erzeugt
einen neuen Evaluation Record.

#### Storage Topology

The Grove trennt Metadaten von großen Artefakten und verwendet keine impliziten
Pfade auf `C:`:

| Tier | Inhalt | Medium |
|---|---|---|
| **Hot** | aktive Workcells, Mission-/Lease-DB, aktuelle Indizes | lokales oder schnelles externes SSD/NVMe |
| **Warm** | content-addressed Patches, Receipts, Logs, kleine Benchmarks | externes SSD |
| **Cold** | abgeschlossene Experimente, komprimierte Traces, Backups | große externe HDD/Objektspeicher möglich |

`ArtifactStore` ist ein Vertrag, kein fest verdrahteter Ordner:

```text
put(stream, media_type, expected_digest?) -> ArtifactRef
open(digest) -> verified stream
pin(digest, reason)
release(digest, reason)
gc(dry_run, retention_policy) -> signed report
capacity() -> free/used/reserved bytes
```

Regeln:

- SQLite speichert Digests und kleine Metadaten, keine riesigen BLOBs.
- Jeder Read verifiziert den Content-Digest.
- Workcells besitzen harte Byte-/Inode-Quotas und temporäre Leases.
- Garbage Collection ist mark-and-sweep über gepinnte Missionen, Lineage,
  Evaluations und Promotion Receipts; niemals eine Alterslöschung allein.
- Ein konfigurierbarer Low-Space-Watermark stoppt neue Evolution, bevor
  Git/SQLite mitten in einer Transaktion scheitern.
- Model-Caches sind regenerierbar und getrennt von unersetzlichen Receipts.
- Ein externes Laufwerk erhält eine stabile Volume-Identität; ein fehlendes
  Volume führt zu `storage_unavailable`, nicht zum Rückfall auf `C:`.

### 10.4 Parent-/Inspiration-Sampling

Jeder Proposal Turn wählt:

- einen Parent, der konkret mutiert wird;
- 0..N Inspirations aus anderen Lineages/Nischen;
- optional kontrastierende Failures;
- ein Task-/Domain-Wissenspaket;
- einen Generator und Operator.

Eine erste transparente Sampling-Verteilung:

\[
P(c) \propto
\exp(
\beta Q(c)
+\gamma N(c)
+\delta U(c)
-\eta C(c)
)
\cdot A(c)
\]

- \(Q\): Quality/Pareto Rank;
- \(N\): Novelty oder Nischenknappheit;
- \(U\): Informationswert bei Unsicherheit;
- \(C\): erwartete Evaluation Cost;
- \(A\): Age/Freshness-Faktor.

Alle Terme werden geloggt. Ein Bandit oder Learned Sampler darf die
transparente Baseline erst nach Offline Replay und Online-A/B-Test ersetzen.

### 10.5 Quality-Diversity

Ein globaler „Best Score“ zerstört interessante Trade-offs. The Grove hält:

- constrained Pareto Front;
- MAP-Elites-artige Nischen nach Behavior Descriptors;
- mehrere Islands pro Modell/Operator/Algorithm Family;
- Novelty Archive;
- Hall of Fame;
- Failure Archive.

Beispielnischen:

```text
small patch / same algorithm / lower runtime
larger patch / new algorithm / equal memory
GPU-heavy / maximum throughput
CPU-only / portable
high readability / moderate speed
```

Nischen werden aus task-relevanten, möglichst kausalen Deskriptoren gebaut,
nicht aus einer hübschen 2D-Embedding-Projektion.

### 10.6 Mutationsoperatoren

1. **LLM diff mutation** – Search/Replace oder unified diff.
2. **Repair mutation** – Compiler-/Testfehler als strukturierter Input.
3. **AST-local rewrite** – Rename, Inline, Loop/Expression Transformation.
4. **Parameter mutation** – diskrete/continuous Config Search.
5. **Parent-inspired rewrite** – Parent plus Ideen anderer Kandidaten.
6. **Recombination** – nur wenn Changesets konfliktfrei anwendbar und
   zusammen evaluiert werden; niemals über Latent-Mittelwerte.
7. **Strategy mutation** – Prompt-/Retriever-/Operator-Policy, zunächst nur
   offline.
8. **Self-code mutation** – letzte Stufe, mit externer Root-of-Trust.

### 10.7 Evaluator-Cascade

```text
Stage 0  patch parses / scope / forbidden changes
Stage 1  compile / focused tests / static checks
Stage 2  full baseline tests / invariants
Stage 3  small benchmark / smoke data
Stage 4  repeated benchmark across seeds
Stage 5  adversarial / held-out / domain oracle
Stage 6  Nemesis promotion verification
```

Nur vielversprechende Kandidaten verbrauchen teure Stufen. Sequential Halving,
Racing oder Successive Rejects können Compute verteilen.

### 10.8 Mehrdimensionale Selektion

Hard Gates:

- Policy/Egress;
- Build/Typecheck;
- Baseline correctness;
- unveränderliche Invarianten;
- Evaluator-Integrität;
- kein unzulässiger Scope;
- keine alleinige Beweisführung durch neu geschriebene Tests.

Soft Objectives:

- task correctness score;
- p50/p95 runtime;
- peak memory / VRAM;
- numerical error;
- patch size / blast radius;
- maintainability proxy;
- portability;
- evaluation cost;
- energy, falls korrekt gemessen.

Selektion verwendet constrained Pareto Dominance. Ein skalierter
Durchschnittsscore dient höchstens der UI.

### 10.9 Statistik

Performance-Kandidaten brauchen:

- Warmup;
- mehrere Replikate;
- kontrollierte CPU/GPU-Frequenz soweit möglich;
- identische Inputs;
- Random Seeds;
- median/quantile und Konfidenzintervall;
- praktische Mindestverbesserung;
- Test auf Regression/Non-Inferiority;
- Artefakte der Rohmessungen.

Ein 2-%-Gewinn mit 10-%-Rauschen ist keine Elite.

### 10.10 Open-Ended Self-Improvement

Reihenfolge:

1. Aufgabenprogramme evolvieren.
2. Mutationsoperator-Auswahl evolvieren.
3. Prompt-/Context-Sampling evolvieren.
4. Retrievalgewichte evolvieren.
5. Evaluator-Kostenmodelle optimieren.
6. Ariadne-Komponenten selbst als Kandidaten evolvieren.

Stufe 6 darf nie Cerberus, Nemesis, Sandbox, Signaturprüfung, Budgetgrenzen oder
Kill-Switch modifizieren. Verbesserungen werden auf held-out Tasks gegen die
vorherige Agent-Version getestet und manuell promoted. DGM ist hier Inspiration,
kein Freibrief.

### 10.11 Worin Ariadne über AlphaEvolve hinausgehen kann

Hypothesen, keine Claims:

1. **Forest Scope**: Code + Build + Docs + Runtime + Domain Knowledge.
2. **Long-horizon lineages**: echte Repository-Evolution statt eines isolierten
   Algorithmusblocks.
3. **Heterogeneous BYOK ensemble**: offene lokale Modelle, CLIs und APIs.
4. **Context receipts**: jede Proposal-Evidenz ist rekonstruierbar.
5. **Quality-Diversity über reale Softwaretradeoffs**.
6. **Cross-mission transfer** aus Patch-/Failure-/Evaluation-Charts.
7. **Independent promotion** statt Evaluator = Deployment.
8. **Domain packs** für HEP, Robotics, Compiler, Web oder Datenpipelines.
9. **Graceful degraded mode** ohne GPU oder Premium-Modell.
10. **User-aligned autonomy** über Ikarus statt reiner Optimierungsschleife.

Beweisplan:

- gleiche Problemdefinition und Evaluatoren;
- gleiches oder normalisiertes Compute-/Tokenbudget;
- Best-of-N, Random Search, single-LLM loop, AlphaEvolve-artige Archive-Baseline;
- mindestens 5 Seeds für stochastische Läufe;
- best-so-far AUC, Success Rate, Diversity, Kosten und Wall Time;
- offengelegte Failures und negative Resultate.

---

## 11. Forge: Transaktionen und Sandbox

### 11.1 Worktree ist Stufe 1

Ein Git-Worktree schützt vor versehentlichem Überschreiben des Primary
Checkout. Er schützt nicht vor:

- Lesen von Credentials;
- Schreiben außerhalb des Worktree;
- Netzwerkexfiltration;
- Prozess-/Kernelangriffen;
- Manipulation von Evaluatoren;
- Ressourcenerschöpfung.

### 11.2 Isolation Tiers

| Tier | Mechanismus | Einsatz |
|---|---|---|
| 0 | read-only Analyse | Context/Review |
| 1 | Git worktree + path policy | trusted low-risk CLI |
| 2 | Container + readonly mounts + egress policy | normale Candidate Runs |
| 3 | VM/microVM/remote disposable worker | untrusted/evolutionary code |
| 4 | dedicated domain cluster | GPU/HEP/large benchmark |

Jede Mission verlangt einen Mindest-Tier. Fallback auf schwächere Isolation ist
explizite Ablehnung, kein stiller Downgrade.

### 11.3 `ExecutionTransaction`

```text
transaction_id
mission_id / candidate_id
base_revision
workspace identity
isolation tier
read/write mounts
network policy
secret handles (never values)
resource limits
runtime identity
event journal
patch artifact
exit state
cleanup state
```

### 11.4 Promotion

1. Candidate patch wird auf frische Base angewandt.
2. Nemesis wiederholt definierte Hard Gates in neuer Umgebung.
3. Patch und Receipts werden angezeigt.
4. Approval Mode entscheidet:
   - `manual`;
   - `semi_auto_low_risk`;
   - `auto_signed_policy`.
5. Promotion erzeugt Commit/PR, nie einen versteckten Merge.
6. Rollback-Referenz wird gespeichert.

---

## 12. Talos und Nemesis

### 12.1 Evaluator Pack

Ein Pack ist versionierter Code plus Manifest:

```yaml
schema: talos-evaluator/1
id: python-library-v1
digest: sha256:...
required_isolation: 2
stages:
  - id: parse
    command: python -m compileall daedalus
    hard_gate: true
  - id: focused
    command: pytest tests/test_embeddings.py -q
    hard_gate: true
  - id: full
    command: pytest -q
    hard_gate: true
metrics:
  - patch_files
  - patch_lines
  - wall_seconds
```

### 12.2 Evaluator-Integrität

- Manifest und Code-Digest werden vor/nach Run geprüft.
- Candidate hat keinen Write Mount auf Evaluator oder Baseline.
- Held-out Tests werden erst im Nemesis-Schritt gemountet.
- Teständerungen werden separat ausgewertet.
- Exit Code, stdout/stderr digest und relevante Artefakte werden gespeichert.
- LLM-as-judge ist Soft Metric mit Modellversion, nicht alleiniger Hard Gate.

### 12.3 Reward-Hacking-Schutz

Pflichtangriffe:

- Tests löschen/skippen;
- Benchmark Input verkleinern;
- Timer manipulieren;
- Cache aus vorherigem Run nutzen;
- Fehler schlucken;
- NaN als Bestwert;
- Environment-Variable überschreiben;
- Evaluator import shadowing;
- symlink/path traversal;
- Netzwerkantwort faken;
- bestehende Golden Files ersetzen.

---

## 13. RTX- und CUDA-Plan

### 13.1 Ehrlicher Nutzen

Nicht das proprietäre DLSS-Modell wird zweckentfremdet. Wir verwenden dieselben
programmierbaren Ressourcen:

- Ollama für lokale Generation und Embeddings;
- Tensor Cores via PyTorch/CUTLASS/TensorRT;
- cuVS für ANN;
- cuGraph für große Graphoperationen und presentation-only Layout;
- Warp für eigene CUDA-/Differentiable Kernels;
- optional Newton/PhysX als domain-spezifische Evaluatoren.

Quellen:

- [NVIDIA Warp](https://nvidia.github.io/warp/latest/)
- [Warp Interoperability](https://nvidia.github.io/warp/latest/user_guide/interoperability.html)
- [CUTLASS](https://docs.nvidia.com/cutlass/latest/overview.html)
- [TensorRT for RTX](https://docs.nvidia.com/deeplearning/tensorrt-rtx/latest/)
- [cuVS](https://docs.rapids.ai/api/cuvs/stable/getting_started/)
- [cuGraph Algorithms](https://docs.rapids.ai/api/cugraph/stable/graph_support/algorithms/)

### 13.2 RTX Worker Protocol

Ein eigener Worker hinter privatem Tunnel/mTLS:

```json
{
  "schema": "daedalus-compute-job/1",
  "job_id": "job_<sha>",
  "operation": "embed|ann|graph|warp|infer|evaluate",
  "input_artifacts": [{"sha256": "...", "media_type": "..."}],
  "backend": {
    "id": "ollama|warp|tensorrt|cuvs|newton|physx",
    "version": "...",
    "model_digest": "..."
  },
  "resources": {
    "gpu_memory_mib": 16000,
    "wall_seconds": 600,
    "precision": "fp32"
  },
  "determinism": {"seed": 47, "mode": "run_to_run"},
  "egress_policy": "none",
  "callback": null
}
```

Handshake meldet:

- GPU UUID, Name, Compute Capability, VRAM;
- Treiber/CUDA;
- installierte Backends/Versionen;
- Modelle/Digests;
- Precision/Determinism Support;
- Max concurrency;
- Health und aktuelle Lease.

Der Scheduler routet nur zu `ready` Capabilities. Eine offene
unauthentifizierte Ollama-Schnittstelle im Internet ist ausgeschlossen.

### 13.3 Operations-Reihenfolge

1. Remote Ollama Embedding Batch.
2. Code-/Doc-Projection Reindex.
3. cuVS ANN ab Größen-Schwelle; CPU SQLite Baseline bleibt.
4. Warp sparse DSS/novelty kernels mit CPU-Golden-Tests.
5. cuGraph Layout, ausschließlich UI-Koordinate.
6. kleines learned DSS residual → ONNX/TensorRT.
7. domain evaluator packs.

### 13.4 NVIDIA Optical Flow

NVOFA verarbeitet Bildframes und liefert Pixel-Motion:

- [NVIDIA Optical Flow SDK](https://developer.nvidia.com/optical-flow-sdk)
- [NVOFA Programming Guide](https://docs.nvidia.com/video-technologies/optical-flow-sdk/nvofa-programming-guide/index.html)

Sinnvoll:

- Screenshot-/UI-Regression;
- visuelle Komponentenbewegung;
- temporale Stabilität einer Forest-Animation;
- Demo-/Videoanalyse.

Nicht sinnvoll:

- Git Rename Truth;
- Symbol Lineage;
- semantischer Patch Flow;
- allgemeiner Tensorinterpolator.

### 13.5 Warp, Newton und PhysX

**Warp** ist der AgentOS-relevante Baustein:

- sparse Relation Diffusion;
- Restriction/Prolongation;
- Batch Novelty/Cosine;
- energy-based layout;
- differenzierbare Research-Kernels.

**Newton** ist ein evaluator pack für Robotik/Physik-Aufgaben:

- [Newton Physics](https://developer.nvidia.com/newton-physics)
- [Newton Repository](https://github.com/newton-physics/newton)

**PhysX** ist ein evaluator pack für reale Rigid-/Soft-Body-/Collision-Aufgaben:

- [PhysX GPU Simulation](https://nvidia-omniverse.github.io/PhysX/physx/5.7.0/docs/GPURigidBodies.html)

Physikmetaphern sind keine Softwaresemantik. Federkräfte dürfen ein Layout
optimieren, nicht Korrektheit oder konfliktfreie Edits beweisen.

### 13.6 GPU Receipt

Zusätzlich:

- GPU UUID und Compute Capability;
- Driver/CUDA;
- Kernel-/Engine-Digest;
- Precision;
- Determinismusmodus;
- Seed;
- Peak VRAM;
- Warmup/Replikate;
- CPU-/Golden-Reference-Abweichung;
- Timeout/OOM/Overflow;
- rohe Metric-Artefakte.

---

## 14. HEP als Domain Pack und Stresstest

HEP ist ein sehr gutes Beispiel, aber nicht der Kernel.

### 14.1 Warum HEP stark ist

- große C++-/Python-Codebasen;
- Templates, Makros, generated dictionaries;
- CMake, `compile_commands.json`, CVMFS, Container;
- Datenformate und Schemas außerhalb des Codes;
- ROOT/Geant4/experiment-spezifische Frameworks;
- Papers, Twikis, Runbooks, Calibration und Bedingungen;
- numerische und statistische Korrektheit;
- lange Lebensdauer und Legacy.

### 14.2 `hep` Domain Pack

```text
domains/hep/
├── ingest/
│   ├── clang_compdb.py
│   ├── root_dictionary.py
│   ├── cmake_targets.py
│   └── documents.py
├── ontology/
│   ├── datasets
│   ├── branches
│   ├── calibrations
│   └── units
├── evaluators/
│   ├── compile
│   ├── unit_tests
│   ├── numerical
│   ├── yields
│   └── performance
└── benchmarks/
    ├── retrieval
    ├── impact
    ├── repair
    └── evolution
```

### 14.3 HEP Forest-Erweiterungen

Knoten:

- C++ type/function/macro;
- Python binding;
- CMake target;
- ROOT dictionary;
- TTree/RNTuple branch;
- dataset/sample;
- histogram/yield;
- unit/constant;
- detector component;
- calibration/conditions payload;
- paper/analysis note.

Relationen:

- generated binding;
- reads branch;
- writes histogram;
- calibrated_by;
- selection_depends_on;
- build target includes;
- paper defines;
- dataset produced_by;
- numeric invariant.

### 14.4 HEP Evaluatoren

- compile against frozen environment;
- unit/integration tests;
- schema compatibility;
- finite outputs / no NaN;
- event yield and histogram checks;
- numerical tolerance with reference;
- reproducible seeds;
- CPU/GPU equivalence;
- runtime/memory on fixed sample;
- statistical uncertainty.

PhysX ersetzt Geant4 nicht. Geant4 behandelt Teilchen-/Strahlungstransport und
physikalische Prozesse:

- [Geant4 Overview](https://geant4.web.cern.ch/about/)

Warp kann spezialisierte Kernels beschleunigen, aber die Wahrheit kommt aus
HEP-spezifischen Referenzen und statistischer Validierung.

### 14.5 HEP Benchmark

Mindestens:

1. Symbol Retrieval;
2. Dokument-/Code Cross-Retrieval;
3. compile-aware Include Impact;
4. Python↔C++ Binding Trace;
5. Test Selection;
6. Bug Localization;
7. kleiner korrekter Rewrite;
8. numerical optimization;
9. multi-commit maintenance sequence;
10. evolution eines klar machine-gradeable Kernels.

Maintainer Labels oder historische Fixes bilden Ground Truth; ein vom selben
Retriever erzeugtes Label ist kein unabhängiges Recall-Label.

---

## 15. Persönliche und operative Memory

### 15.1 Strikte Trennung

```text
Operational Memory
  events · missions · attempts · tools · receipts · candidates · evaluations

Personal Memory
  preferences · people · recurring goals · decisions · conversational facts

Derived Projections
  embeddings · summaries · clusters · indexes
```

### 15.2 Personal-Memory-Regeln

- explizite Kategorien und Zweck;
- Sicht-/Edit-/Delete-UI;
- Retention;
- „do not remember“;
- Herkunft und Confidence;
- Konflikt-/Supersede-Semantik;
- sensitive data class;
- keine automatische Egress-Freigabe;
- Export;
- vollständige Löschung inklusive derived projections.

### 15.3 Operational Tamper Evidence

Aus JSONL wird eine Hash Chain:

\[
h_i=H(h_{i-1}\Vert canonical(event_i))
\]

Regelmäßige Checkpoints werden extern signiert oder in einen separaten
Trust Store geschrieben. Das beweist keine Wahrheit des Events, aber erkennt
nachträgliche Manipulation.

---

## 16. Security- und Threat-Modell

### 16.1 Angreifer

- bösartige Repository-Datei/README;
- Prompt Injection in Dokumenten oder Tool Output;
- kompromittierte Runtime/CLI;
- Candidate Code;
- Dependency/Supply Chain;
- vergiftete Memory-/Embedding-Einträge;
- fehlerhafter oder reward-hackbarer Evaluator;
- Benutzerfehler;
- Netzwerkgegner am RTX Worker.

### 16.2 Schutzschichten

1. **Data classification** vor Context Egress.
2. **Capability tokens** statt globaler Rechte.
3. **Read/write mount scopes**.
4. **Network default deny** für Candidate Runs.
5. **Secret broker** mit kurzlebigen Handles, nie Promptwerte.
6. **Process/Container/VM quotas**.
7. **Evaluator separation**.
8. **Signed policy/evaluator manifests**.
9. **Immutable event receipts**.
10. **Independent kill switch**.
11. **Archive poisoning detection**.
12. **Human approval** für irreversible/externe Aktionen.

### 16.3 Kill Switch

- beendet Worker Leases;
- blockiert neue Promotions;
- widerruft Credentials;
- setzt Autonomy Profiles auf read-only;
- markiert offene Transaktionen recovery-required;
- bleibt außerhalb des Candidate- und Agent-Scope;
- ist aus UI und CLI erreichbar.

---

## 17. Messprogramm

### 17.1 Ikarus-Metriken

- Mission Success Rate;
- korrekt verstandener Scope;
- Rückfragenrate;
- menschliche Interventionen;
- unautorisierte Action Attempts;
- Recovery Success;
- Cancellation Latency;
- Halluzinations-/Claim-Fehler;
- Zeit bis verifiziertes Ergebnis;
- Kosten;
- Nutzerkorrekturen;
- Memory Precision/Deletion correctness.

### 17.2 Kairos-Metriken

- DAG completion;
- queue wait;
- worker utilization;
- retry success;
- duplicate execution;
- orphan rate;
- artifact reuse;
- critical-path wall time;
- policy bounce correctness.

### 17.3 Ariadne-Metriken

- best-so-far Kurve und Area under Curve;
- Success Rate;
- Hypervolume/Pareto coverage;
- Nischenabdeckung;
- lineage depth;
- structural/behavioral diversity;
- evaluator calls bis Verbesserung;
- Token/GPU/Wall Cost;
- invalid candidate rate;
- reward hacking detected;
- generalization auf held-out evaluators;
- Regression Rate nach Promotion.

### 17.4 Experimentregeln

- Hypothese vor Lauf;
- frozen task set;
- Train/Dev/Test oder historical cutoff;
- mehrere Seeds;
- gleiche Budgets;
- Confidence Intervals;
- negative Resultate speichern;
- keine Auswahl der besten Seed als Durchschnitt;
- keine Benchmark-Leaks über Memory;
- jede Ablation bekommt denselben Evaluator.

### 17.5 Referenz-Benchmarks

- SWE-bench-artige fokussierte Repair Tasks;
- [SWE-EVO](https://arxiv.org/abs/2512.18470) für long-horizon Evolution;
- DGM-artige Agent-Verbesserungsaufgaben;
- interne Frozen Daedalus Tasks;
- HEP Domain Pack;
- algorithmische machine-gradeable Tasks.

EvoTrace motiviert, nicht nur den finalen Score, sondern die
Evolutionsdynamik zu analysieren:

- [What Do Evolutionary Coding Agents Evolve?](https://arxiv.org/abs/2605.20086)

---

## 18. Delivery Movements

Die Movements sind dependency-gated. Zeitangaben sind grobe Solo-/kleines-Team
Spannen, keine Marketingdeadlines.

### Movement 0 – Foundation Lock

Status: läuft / teilweise fertig  
Horizont: jetzt

Lieferumfang:

- Antigravity-Audit abschließen;
- DSS v0;
- Hybrid Context CLI/API;
- Latent Index v2;
- vollständige Memory-Provenienz und Entkopplungsplan für den Projection Worker;
- Accelerator Inventory;
- Forced-Codex advisory-only und keine Parallel-Writes im Primär-Checkout;
- Storage-Inventar, Quotas und Artefaktziel mit mindestens 50 GiB Reserve;
- vollständige Tests, Wheel, Frontend Build;
- Masterplan und ADR-Abgleich.

Gate:

- keine falschen mathematischen Claims;
- deterministische Receipts;
- bestehende Suite grün;
- keine unversionierte Vektormischung;
- kein direkter Provider-Write außerhalb einer überprüfbaren Transaktion;
- kein Archiv-/Worktree-Start bei unterschrittener Disk-Reserve;
- DLSS/Physics korrekt als unsupported/experimental markiert.

### Movement 1 – Mission Spine

Horizont: 1–3 Wochen

Neue Module:

```text
daedalus/missions/spec.py
daedalus/missions/state.py
daedalus/missions/store.py
daedalus/missions/events.py
daedalus/missions/recovery.py
```

Lieferumfang:

- `MissionSpec`;
- durable State Machine;
- Artifact References;
- Leases/Heartbeats;
- Cancellation;
- Idempotency;
- CLI/API Status/Resume/Cancel.

Gate:

- Prozess während jeder State-Phase killen;
- Neustart darf weder Mission verlieren noch Write doppelt ausführen;
- alle Übergänge rekonstruierbar.

### Movement 2 – Ein Orchestrator

Horizont: 2–4 Wochen

Lieferumfang:

- legacy Offload und Adapter/Worktree über denselben `TaskAttempt`-Vertrag;
- Artifact-DAG;
- capability-based routing;
- budgets/concurrency;
- runtime conformance captures;
- keine direkten Provider Writes außerhalb Forge.

Gate:

- dieselbe Mission kann Claude, Codex oder Ollama einsetzen;
- identische Event-/Receipt-Shape;
- kein split-brain mutation path.

### Movement 3 – Context Compiler v1

Horizont: 2–5 Wochen, parallel zu Movement 2

Lieferumfang:

- Source/Document FTS/BM25;
- symbol-level Forest;
- compile/build targets;
- Code-/Doc-Embedding Projectors;
- RRF baseline;
- DSS + temporal lineage;
- multi-target `dctx` materialization;
- retrieval eval set.

Gate:

- Hybrid/DSS schlägt Path-BM25 bei Recall@Token oder End-to-End-Erfolg;
- p95 Budget;
- jeder Context-Byte ist auf Raw Evidence zurückführbar.

### Movement 4 – Forge + Cerberus

Horizont: 3–6 Wochen

Lieferumfang:

- `ExecutionTransaction`;
- container runner;
- mount/network/resource policy;
- secret broker;
- cleanup/recovery;
- promotion packet;
- kill switch.

Gate:

- Escape-/Egress-/scope red-team fixtures;
- Candidate kann Evaluator nicht schreiben;
- Primary Checkout bleibt unverändert bis Promotion.

### Movement 5 – Talos + Nemesis

Horizont: 3–6 Wochen

Lieferumfang:

- Evaluator Pack Schema;
- staged cascade;
- result normalization;
- statistical benchmark runner;
- changed-test policy;
- held-out Nemesis rerun;
- signed evaluator receipts.

Gate:

- Reward-hacking attack suite;
- flaky benchmark wird als uncertain statt elite markiert;
- keine Promotion mit fehlendem Hard Gate.

### Movement 6 – The Grove

Horizont: 2–4 Wochen

Lieferumfang:

- append-only candidate/evaluation/artifact schema;
- lineage graph;
- archive reload;
- failure taxonomy;
- Pareto Front;
- novelty descriptor;
- UI/API reads.

Gate:

- laufende Evolution kann nach Crash exakt weiterlaufen;
- alte Evaluationsresultate werden nicht überschrieben;
- Kandidat vollständig reproduzierbar oder explizit `non_reproducible`.

### Movement 7 – Ariadne Alpha

Horizont: 4–8 Wochen

Lieferumfang:

- Parent-/Inspiration-Sampler;
- generator ensemble;
- operator registry;
- evaluator cascade scheduling;
- MAP-Elites-/Island-Baseline;
- async controller;
- Budget-/Cost Accounting;
- Best-of-N und Random Baselines.

Gate:

- mindestens drei echte Generationen;
- persistente Lineages;
- mehrere Evaluator-Dimensionen;
- über mehrere Seeds messbarer Vorteil gegen Best-of-N auf mindestens einem
  frozen Benchmark;
- kein automatisches Primary-Repo-Merge.

### Movement 8 – RTX Worker

Horizont: 2–6 Wochen, parallel

Lieferumfang:

- private authenticated worker;
- capability handshake;
- artifact transfer by digest;
- Ollama embedding/generation;
- GPU receipts;
- queue, cancellation, VRAM limits;
- optional Warp/cuVS.

Gate:

- keine Secrets in Status/Logs;
- job retry idempotent;
- CPU/GPU output tolerance tests;
- remote disconnect recovery.

### Movement 9 – Ikarus v1

Horizont: 6–12 Wochen nach Mission Spine

Lieferumfang:

- conversational Mission Compiler;
- project/personal memory controls;
- proactive policy profiles;
- live mission timeline;
- explainable status;
- approvals;
- interruption/recovery;
- skill/capability registry;
- optional voice/hotkey.

Gate:

- definierter held-out Mission-Satz;
- keine unprotokollierte Mutation;
- Memory Delete entfernt Derived Projections;
- proaktive Aktion außerhalb Policy wird verweigert;
- Nutzer kann jede Mission stoppen.

### Movement 10 – Learned DSS

Horizont: Research, nur nach Retrieval-Baseline

Lieferumfang:

- labeled Context Dataset;
- residual model;
- uncertainty;
- ONNX/TensorRT;
- ablations;
- drift detection.

Gate:

- klarer held-out Gewinn;
- deterministic fallback;
- kein Receipt-Verlust;
- Modellwechsel erzeugt neue Identität.

### Movement 11 – HEP Pack

Horizont: 6–16 Wochen mit Domain-Partnern

Lieferumfang:

- compile database;
- ROOT/Build/Schema entities;
- document ingestion;
- frozen runtime environment;
- numerical/yield evaluator;
- benchmark tasks.

Gate:

- Maintainer-/historical Ground Truth;
- kein PhysX-as-HEP;
- domain pack deaktivierbar;
- Kernel bleibt domain-neutral.

### Movement 12 – Open-Model Latent Communication

Horizont: separates Research Track

Lieferumfang:

- hidden-state capture capability;
- model/layer/token identity;
- trained adapters;
- text shadow;
- equal-budget experiment;
- cross-version disable/recalibration.

Gate:

- End-to-End-Vorteil, nicht nur Representation Similarity;
- Recovery über Text;
- kein Einsatz für Closed CLI ohne Hidden-State API.

### Movement 13 – Safe Self-Evolution

Horizont: nach Forge, Talos, Nemesis, Grove und Ariadne

Lieferumfang:

- Ariadne darf eigene nicht-trusted Komponenten als Candidate verändern;
- held-out Agent Benchmark;
- versioned rollout/canary;
- automatic rollback;
- human promotion.

Gate:

- Root-of-Trust außerhalb Write Scope;
- reproduzierbare Verbesserung über Seeds;
- kein Verlust an Safety/Recovery;
- alte Agent-Version sofort reaktivierbar.

---

## 19. Konkrete nächste PR-Reihenfolge

### PR 1 – DSS Context Surface

- `daedalus context`;
- `/api/context/plan`;
- lexical + optional latent seeds;
- measured file token costs;
- hybrid receipt;
- focused tests.

### PR 2 – Accelerator Contract

- local NVIDIA evidence;
- deep framework probe;
- remote RTX Ollama config/probe;
- Warp/Newton/PhysX/DLSS applicability states;
- API/CLI;
- redaction tests.

### PR 2.5 – Projection Worker

- append-only Journal bleibt im Write-Pfad allein autoritativ;
- Cursor aus Journal-Datei-ID, Byte-Offset und Record-Hash;
- idempotente Re-Projektion;
- Retry/Backoff und Dead-Letter-Receipt;
- Projekt-, Pfad-, Trust- und Modell-Digest-Provenienz;
- kein Ollama-/Netzwerk-I/O in `append_event()`.

### PR 3 – `MissionSpec`

- schema/dataclasses;
- canonical ID;
- validation;
- scope/budget/approval;
- serialization tests.

### PR 4 – Durable Mission Store

- transitions;
- idempotency;
- leases;
- crash fixtures;
- status/cancel/resume API.

### PR 5 – Unified `TaskAttempt`

- adapter execution;
- legacy provider bridge;
- artifact refs;
- transport journal;
- no direct primary writes.

### PR 6 – Forge Transaction

- worktree lifecycle hardening;
- base SHA;
- patch artifact;
- cleanup;
- container interface;
- promotion packet.

### PR 7 – Talos Evaluator

- pack manifest;
- cascade;
- baseline/focused/full;
- receipt;
- changed-test safeguards.

### PR 8 – Grove Schema

- candidates;
- parents/inspirations;
- evaluations;
- artifacts;
- archive queries.

### PR 9 – Ariadne Baselines

- Best-of-N;
- random parent;
- quality parent;
- Pareto;
- MAP-Elites/islands;
- replayable seeds.

### PR 10 – RTX Worker

- authenticated health;
- job protocol;
- artifact digests;
- Ollama backend;
- leases/cancellation.

---

## 20. Definition of Done

### 20.1 Ikarus v1

Ikarus v1 ist erreicht, wenn:

- eine Mission formalisiert, geplant, autorisiert, ausgeführt, verifiziert,
  gestoppt und recovered werden kann;
- mindestens drei heterogene Runtimes denselben TaskAttempt-Vertrag erfüllen;
- jeder Write eine Transaktion und ein Promotion Packet besitzt;
- persönliche Memory sichtbar/löschbar ist;
- Autonomy Policies technisch erzwungen werden;
- die UI nur echte Mission-/Runtime-/Evaluator-Daten zeigt;
- ein 20+ Missionen umfassender held-out Satz mit veröffentlichter Success- und
  Recovery-Rate existiert.

### 20.2 Ariadne Alpha

Ariadne Alpha ist erreicht, wenn:

- das Archiv einen Neustart überlebt;
- Kandidaten Parent/Inspirations/Lineage besitzen;
- mindestens drei Generationen entstehen;
- mindestens drei unabhängige Evaluator-Dimensionen existieren;
- Hard Gates von Quality Scores getrennt sind;
- Quality-Diversity und Best-of-N unter gleichem Budget verglichen werden;
- ein statistisch reproduzierbarer Gewinn auf einem frozen Task gezeigt wird;
- kein Kandidat ungeprüft promoted wird.

### 20.3 „Besser als AlphaEvolve“

Diese Formulierung ist erst zulässig, wenn:

- eine public/reproducible Vergleichsaufgabe existiert;
- gleiche oder normalisierte Modell-/Compute-Budgets verwendet werden;
- mehrere Seeds und Confidence Intervals vorliegen;
- AlphaEvolve-artige Archive-/Island-/Evaluator-Baselines implementiert sind;
- Ariadne in Success/Quality **und** mindestens einer Systemdimension
  (Kosten, Generalität, Safety, Long-horizon, Reproduzierbarkeit) gewinnt;
- negative Tasks und Grenzen veröffentlicht werden.

Vorher lautet die korrekte Aussage:

> Ariadne ist als breitere, provenance-first Forest-Evolution-Architektur
> konzipiert und wird gegen AlphaEvolve-artige Baselines evaluiert.

---

## 21. Kill List

Diese Pfade werden nicht wiederbelebt, solange keine unabhängige Evidenz
vorliegt:

- Euclidean Embeddings radial in eine Poincaré Disk schieben und
  „hyperbolische Semantik“ nennen;
- einen gewichteten Embedding-Mittelwert „Gradient“ nennen;
- Codevektoren als RGBA-Textur durch DLSS schicken und Bedeutung behaupten;
- PhysX-Kollisionen als Merge-Konflikte interpretieren;
- Layoutnähe als Retrieval Ground Truth verwenden;
- aus einem grünen selbstgeschriebenen Test Korrektheit ableiten;
- LLM-as-judge als einzige Promotion;
- Multi-Agent-Freeform-Chatter ohne Artifact Contract;
- Candidate darf Evaluator/Policy ändern;
- unversionierte Embeddings mischen;
- Primary Checkout während Evolution beschreiben;
- Fake UI-Metriken;
- Tauri/Voice/3D vor Mission Spine und Recovery priorisieren;
- „autonomous“ ohne Cancel/Recover/Kill;
- „self-improving“ ohne held-out Vergleich zur alten Version.

---

## 22. Die unmittelbare strategische Antwort

Ja, der Weg zu einem Ikarus-artigen AgentOS und einer AlphaEvolve-artigen oder
langfristig besseren Evolutionsmaschine ist technisch plausibel.

Der Engpass ist nicht, dass uns Googles Infrastruktur fehlt. Der Engpass ist,
ob wir die kleinen, harten Systeme bauen, die große Compute-Mengen sinnvoll
machen:

1. Missionen, die nicht vergessen, was sie versprochen haben.
2. Kontext, der auf Evidenz zurückführt.
3. Shells, die nichts verschlucken.
4. Transaktionen, die keinen Host verheizen.
5. Evaluatoren, die nicht vom Kandidaten betrogen werden.
6. Ein Archiv, das aus Erfolgen **und Failures** lernt.
7. Ein Scheduler, der BYOK-Modelle und RTX nach gemessener Fähigkeit einsetzt.
8. Ein Assistent, der dem Nutzer gehört und jederzeit stoppt.

Genau diese Reihenfolge verwandelt „Codebases sind ein Wald“ von einer schönen
Metapher in MetaCoding: Der Agent bewegt sich kontrolliert zwischen
Wissensebenen, schlägt diskrete Veränderungen vor, misst ihre Folgen und
behält eine überprüfbare Geschichte darüber, wie der Wald gewachsen ist.

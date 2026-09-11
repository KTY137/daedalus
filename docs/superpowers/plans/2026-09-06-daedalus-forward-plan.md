# Daedalus Vorwärtsplan 2026-09-06 — Standaufnahme und Programm

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Jedes Packet ab Phase B bekommt beim Öffnen seinen eigenen ausführbaren TDD-Plan (Regel „Scope Check“ des writing-plans-Skills); dieses Dokument ist das Programm, das die Reihenfolge, die Abnahmematrizen und die ersten roten Tests festlegt.

**Goal:** Daedalus von „viele grüne Einzelpackets, nichts gemerged, Gate-1-Renovation seit August unbewegt“ zu einem Zustand bringen, in dem (1) der Baum eine gemessene Wahrheit hat, (2) die Gate-1-Renovation-Obligation abnahmereif ist, (3) Ikarus eine Aufgabe tatsächlich zu Ende bringt, (4) Ariadne einen echten Modell-Operator unter dem Trust-Kernel fährt und (5) das Gate-2-Fundament (Data-Plane, Resolution, Corpus-Seed) als gelabeltes Experiment steht.

**Architecture:** Alles durch den kanonischen Kernel (Mission / Attempt / EffectLease / Evidence / OwnerApproval). Kein zweiter Runner, kein zweiter Store, kein LLM-Gate. Jeder Schritt ist ein Work Packet nach Plan §10 mit Abnahmematrix, Builder-Verifikation, unabhängigem Review (Codex oder Cerberus/Odysseus) und retained negative evidence. Nichts merged oder promotet sich selbst.

**Tech Stack:** Python 3.13 (`.venv/Scripts/python.exe`), pytest 9.1.1, stdlib-Kernel, Tree-sitter-Adapter, Ollama 0.33.3 (lokal, `/api/chat` native Route), codex-cli 0.153.x, Tauri/React-Cockpit unter `apps/web`, GitHub Actions (Jobs starten seit 2026-09-06 wieder, siehe A5).

**Spec:** `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 12 (SHA-256 `126594137ebf…e8d8fb`, gemessen 2026-09-05 in G1-IKARUS-25/28), `AGENTS.md`, `CLAUDE.md`. Produkt-Backlog-Eingaben: `docs/backlog/HERMES_JARVIS_CAPABILITY_MAP_20260905.md`, `docs/evidence/G1-COMPUTER_EVIDENCE_INVENTORY_20260905.md`, `docs/work-packets/G1_ACTIVATION_CHECKLIST.md`.

## Global Constraints

- Aktives Gate: **Gate 1** (Renovation, owner-directed Genesis, general computer assistance). Gate-2-Arbeit nur als `EXPERIMENT` ohne konkurrierenden Kernel (Plan §11 Einleitung).
- Invarianten 1–10 (Plan §4) gelten für jeden Schritt; insbesondere: keine automatische Promotion, Kandidat sieht seinen Evaluator nie, Modelle schlagen vor, deterministische Evaluatoren entscheiden.
- Effektvolle neue `main()`/Türen werden **vor** dem ersten Effekt mit `begin_effect` registriert; danach die ~27 Registry-Digest-Pins neu messen (Memory `feedback-tools-need-effect-boundary-row`).
- Byte-Pin-Zensus: jede Datei im Import-Closure des Gate-1-Evaluator-Bundles braucht eine explizite `-text`-Zeile in `.gitattributes` (kein Wildcard). CI-Lauf 34000413904 (2026-09-06 00:08) nennt fünf ungepinnte Twin-Module.
- Kosten: Owner hat monetäre Caps am 2026-09-05 freigegeben (`.env`, custom policy: money/tokens aus, wall_time/attempts an). Zeit- und Attempt-Achsen bleiben an.
- Parallelität: mehrere Sessions auf einem dirty Tree. Lane vor Beginn in `.room/room.md` ansagen; exklusive Dateimengen; Peer-Session `daedalus-9d` hält `daedalus/orchestration/ikarus/computer_loop.py` (G1-IKARUS-32).
- Windows-Host (16 GB RAM, MX330 2 GB GPU, 7B-Planner auf CPU). POSIX-Aussagen bleiben unmeasured, bis ein Linux-Host die Suite fährt.
- Plan, Amendment-Kette, `AGENTS.md`, `CLAUDE.md`, `.agentenv/` werden von keinem Schritt dieses Plans angefasst. Amendment 013 ist eine Owner-Entscheidung (A4).

---

## Teil 1 — Standaufnahme (gemessen 2026-09-06, 02:00–02:20)

Provenienz: `[M]` in dieser Session gemessen, `[I]` aus Packet/Room/Memory übernommen, `[A]` Annahme.

### 1.1 Baum und Branches

| Fakt | Wert | Prov. |
| --- | --- | --- |
| Primärer Checkout | `C:/Users/nukei/Desktop/PROJECTS/daedalus`, Branch `codex/ikarus-computer-assistant-20260905`, HEAD `585b7ea4` (v0.1.6 Release-Commit) | [M] |
| Dirty | 126 Einträge; 56 getrackte Dateien geändert, +3783/−521 Zeilen; ~70 untracked (Wiki-Seiten, `computer_files`-Adapter-Umfeld, `roomRenderer.ts`, GLB-Szenen 7,5 MB, `package_desktop_local.ps1`, `docs/backlog/`, Evidence-Inventar) | [M] |
| Uncommitted Packets im Haupttree | G1-IKARUS-25 (Fence-Lift Phase 1+2, Cerberus PASS-WITH-FINDINGS 20:44), G1-COUNCIL-02, G1-WIKI-01, G1-UI-12/13/14/15, Wiki-Regeneration (63 Seiten), Evidence-Inventar, Mutations-Skript-Reparatur | [I] Room 19:22–22:12, Memory |
| Integrierter Loop-Branch | `loop/stage3-failed-receipt` HEAD `04fde78b`, 42 Commits vor `585b7ea4`; trägt Etappen 3–15b und alle zehn Opus-Lanes; 672 passed / 7 xfailed über 22 Suiten | [I] Room 19:30 |
| Lane-Branches | `loop/lane1..10` + Worktrees unter `.claude/worktrees/` (integriert, noch nicht entfernt) | [M] |
| Fremde aktive Linien | PR #313 `g1/gardener-post-release-containment-03` (DRAFT, CI läuft), PR #314 `exp/tensor-kernel-contract-01` (DRAFT); `origin/main` = `61cd1f3e`, 1 Commit hinter HEAD | [M] |
| Letzter Full-Suite-Lauf | 2026-08-17 (35 failed / 6428 passed / 51 skipped, `runs/full_suite_20260817_evening.txt`); seither 738 Testdateien, kein neuer Gesamtlauf | [M] Datei, [I] Zahlen |
| CI | Jobs starten wieder (Run 34000413905 `success` Contracts, 34000413904 `failure` Ignition-Slice: fünf Twin-Module ohne `-text`-Pin, Digest bewegt sich mit Zeilenenden, `pytest_plugins_are_measured` 0). Der Befund vom 2026-08-25 („kein Job startet“) ist damit überholt. **Der Rotstand betrifft nur den Gardener-Branch #313**: im Haupttree sind alle fünf Module plus `kernel/policy/__init__.py` und `runtimes/computer_files.py` gepinnt (`git check-attr text` → `unset`, gemessen 02:22 von Session daedalus-14, 02:25 hier nachgemessen) | [M] |
| Budget-Ledger | Verwaiste Reservierung `688f434b…` (3,00 USD, worst_case, Prozess tot, aus einem gekillten Council-Lauf am 2026-09-05) steht weiter als `open` in `runs/budget/ledger.json`; keine Reap-Tür vorhanden | [M] |

### 1.2 Verfassung

| Fakt | Wert | Prov. |
| --- | --- | --- |
| Plan | Revision 12, Version 2.3.0, Gate 1 aktiv; Amendment-Kette Sequenz 11 → result_revision 12 (Revision-11-Ledger-Eintrag fehlt als dokumentierte Diskontinuität) | [M] |
| Amendment 013 (Hardware-Targets, Self-Renovation mit Leakage-Regel) | `Status: draft, awaiting owner approval` | [M] |
| Gate 0 | geschlossen als scoped Owner-Entscheidung 2026-08-26; Mechanik meldet weiter `closed:false` für die scoped rows | [I] Plan Rev. 8 |

### 1.3 Die drei Gate-1-Stränge

**Renovation (die eigentliche Gate-Obligation).** `python -m daedalus.ignition` läuft seit 2026-08-22 durch den kanonischen Kernel (MissionContract über `BuildSession`, zwei `BuildTask`-WorkItems aus `fourfold.json`, Attempts über die `python.attempt`-Grenze, Test/Schema/Link-Checks mit gemessener Negativkontrolle, EvidencePacket mit 7 Items, Replay-Block). Das Zielrepo ist ein **vorbereitetes echtes Git-Repo mit eingefrorener Identität** (`gate1.py` `FROZEN_GIT_ENV`), nicht mehr synthetische Revisionen. [I] G1-WP-01 Status, [M] `gate1.py:126-137`. Seit dem 2026-08-24 (Bundle-Identität, 127 Evaluator-Module) ist an diesem Strang **nichts** mehr gebaut worden; die offenen Zeilen der Activation-Checklist (Restart aus dem Event-Spine, retained *failed* Packet, Double-Start-Race, unabhängiges Review) wurden nie neu vermessen. Die Gate-1-Klausel „restart/replay works“ ist heute „Replay ist digest-identisch“, nicht „Restart nach Crash mit derselben Attempt-Identität“. [M] Checklist §2.5, [A] dass nichts davon zwischenzeitlich geschlossen wurde → B1 misst.

**Genesis.** G1-GENESIS-01/02/03 gelandet (Item-Collection, Kanban-Blueprint, verifizierter Download). Live-Rehearsal (Etappen 7–9) auf diesem Host: alle vier Targets preview-ready, Gates 0,5–1,2 s, CLI lehnt Kanban vor jedem Effekt ab. Nicht in Scope von 01: konversationelle Folge-Revisionen und allgemeine Repair-Suche. RoundTrip-Vergleich Ziel-vs-Ist existiert in `orchestration/genesis/materializer.py`/`service.py` (grep-Treffer), Tiefe nicht vermessen. [I]/[M]

**General computer assistance (Ikarus, Amendment 12).** Evidence-Matrix 44 von 77 Zellen (11 Fähigkeiten × 7 Evidenzklassen); Terminal existiert nicht (by design), Document und Integration existieren gar nicht (14 GAP-Zellen), Desktop-Realadapter wird von keiner Suite ausgeführt, Browser ohne Timeout-/Crash-Test. Dateiwerkzeuge seit G1-IKARUS-25 hinter der unveränderten Admission live (Windows-only, handle-anchored), **Replace bleibt gezäunt** (`RELEASE_REPLACE_FENCED = True`, G1-IKARUS-27 Entwurf, Momus fünf CRITICAL gegen den ersten Reconciler-Entwurf), Vision-Pfadformen gezäunt (`RELEASE_DISABLED_TOOLS = {vision.match, vision.changes}`, G1-IKARUS-28 Entwurf mit xfail-Baseline). Computer-Loop live gemessen (Etappe 13/15): 25,5 s pro Planner-Aufruf nach nativer Route; bis 02:00 hatte **kein Lauf `finish` erreicht**. Nachtrag 02:35–02:50 (G1-IKARUS-32, Lane `loop/lane11-planner-progress`, Session daedalus-9d): mit einem deterministischen Plan-Fortschritts-Payload im Prompt liest der 7B-Planner erstmals (`measure-08`, kein `finish`, retained Negativbefund); mit `codex_cli` als Planner über `allow_remote_context` erreicht `measure-09` als **erste Mission `finish`** (59,7 s, 4 Calls, Sentinel byte-genau, `task_success_verified` bleibt false) — **n=1, vierfach konfundiert** (Modell, Transport, Remote-Context-Policy, Last), kein Anspruch. `measure-10` (Momus) zeigt, dass die 26er-Regel „drei identische Pläne = stalled“ die Oszillation selbst beendet. Nachtrag 03:05–04:15 (dieselbe Lane): G1-IKARUS-33 nennt Planner und „Kontext hat den Rechner verlassen“ im Missionsbericht (measure-09 hatte Seiteninhalt an OpenAI geschickt, der Bericht schwieg); G1-IKARUS-34 (EXPERIMENT, vorregistriert) ist **negativ**: 0/5 und 0/5 `finish` für den 7B mit beiden Payload-Formen, alle zehn Läufe durch die 26/29-Fortschrittsregeln beendet — die Prompt-Form war nicht das Hindernis, der lokale Planner ist es; G1-IKARUS-35: **kein Watcher tickt auf dieser Box die Aufträge des Owners** (Hauptcheckout-Heartbeat vom 04.09. aus einem pytest-Root, v0.1.6 hat den File-Bridge-Watcher bewusst nicht in die App genommen), der Chat behauptete trotzdem Ausführung — jetzt fail-open `unknown` mit ehrlicher Zeile. [M] `policy/computer.py:23,48,55`, `runs/bridge_heartbeat.json`, Room 3074–3148; [I] Inventar, Etappen 13/15.

**Ariadne.** Genau eine deterministische Repair-Kampagne (`campaign.py`, 1926 Zeilen): drei Arme unter gleichem Budget, eingefrorener Evaluator, Negativkontrolle, Nominierung als Decke. Kein Modell-Operator, keine Population, keine Suche. Windows-Evaluator repariert (G1-ARIADNE-03), Failed-Receipt beim ersten Aufruf (04), Working-Tree-Base-Binding (05), Exit-Code-Vertrag (09), Git-Objekt-Leser ohne Binary (08, **nicht verdrahtet**). Zwei Self-Renovation-Nominierungen als EXPERIMENT (SELF-00/01), nichts angewandt. [I] Wiki `ariadne.md`, Loop-Status.

**Hardware (Amendment 013, offen).** KiCad-Slice (G1-HW-01, 148 Tests, effektfrei, kein KiCad installiert), Vivado/Vitis-Tcl-Emission (G1-EDA-HOST-STATUS-02, alle Vendor-Tools abwesend, `tclsh` 35/35 Übereinstimmung). Beides ohne reale Toolchain-Evidenz. [I]

**Twin / Gate-2-Fundament.** `daedalus/twin` 17 Module, 4997 Zeilen; Sparse-Algebra, Semiring, Kontraktionen, Relation-Compiler, Tensor-View, Doppelkategorie — alles Projektionen über `KnowledgeForest`. **Data-Plane bleibt `absent`** im Legacy-Forest-Adapter; die Sprachregistry kennt csv/json-schema/sql/parquet als Data-Sprachen, ob ein Extraktor sie füllt, ist nicht vermessen. Function/Method-Resolution: Tree-sitter-Adapter vorhanden, Auflösungsgrad unvermessen. Corpus: keiner. [M] Wiki `twin.md`, `extractors/registry.py:24-44`.

### 1.4 Die vier strukturellen Probleme, die der Plan angreift

1. **Keine gemessene Wahrheit.** 126 dirty Einträge, ein 42-Commit-Branch, zwei Draft-PRs, kein Gesamtlauf seit drei Wochen. Jede „grün“-Aussage ist Suiten-lokal.
2. **Die Gate-Obligation liegt brach.** Alle September-Arbeit ging in Ikarus/Genesis/Ariadne; die Renovation-Klausel, die Gate 1 tatsächlich schließt, hat seit dem 24.08. keinen Commit.
3. **Ikarus hat Werkzeuge, aber keinen reproduzierten Abschluss.** Genau ein Lauf hat `finish` erreicht (measure-09, Remote-Planner, n=1); lokal keiner. Zwei der sieben §7.2-Fähigkeiten (Terminal, Document) fehlen ganz.
4. **Ariadne evolviert nichts.** Der Kontrollrahmen ist fertig, aber der einzige Operator ist ein exakter Textersatz — das Forschungsversprechen (§8) hat noch keinen ersten Modell-Operator unter dem Kernel gesehen.

---

## Teil 2 — Programm

Reihenfolge ist Abhängigkeitsordnung. Phase A ist Voraussetzung für alles; B, C, D, E sind danach in **eigenen Lanes parallelisierbar** (disjunkte Dateimengen, siehe „Files“ je Task). Jede Task nennt, was sie substanziell voranbringt.

### Phasenübersicht

| Phase | Was sie voranbringt | Tasks | Abhängigkeit |
| --- | --- | --- | --- |
| A — Wahrheit konsolidieren | Ein gemessener Baseline-Zustand; uncommitted Arbeit als reviewte Commits; Loop-Branch integriert; Owner-Entscheidungen gebündelt | A1–A5 | keine |
| B — Gate-1-Renovation schließen | Die eigentliche Gate-Exit-Klausel wird abnahmereif | B1–B5 | A1–A3 |
| C — Ikarus bringt Aufgaben zu Ende | Reproduzierter `finish` (n≥5, beide Arme); Terminal; Replace; Vision-Pfade; Document; Skills; Desktop-Abnahme; Cockpit | C1–C9 | A3 und A4 Zeile 10 (für C2), sonst A2 |
| D — Ariadne evolviert | Erster Modell-Operator unter dem Kernel; frozen task set; Self-Renovation nach 013 | D1–D3 | A3, D3 zusätzlich A4 |
| E — Gate-2-Fundament (EXPERIMENT) | Data-Plane `complete`, Resolution, Corpus-Seed, erste Ablation | E1–E4 | A2; E3 nutzt B4 |
| F — Hardware (nach 013) | Erste reale KiCad-Evidenz | F1–F2 | A4 |
| G — Laufende Hygiene | Registry, Zensus, Wiki, Vault | G1 | fortlaufend |

---

## Phase A — Wahrheit konsolidieren

### Task A1: Full-Suite-Baseline auf Haupttree und Loop-Branch

**Packet:** G1-BASELINE-20260906 (Evidence-only, ALIGNED, Gate 1). **Delegat:** Metron (Gate-Läufe), niemals unter Last timen.

**Files:**
- Create: `runs/full_suite_20260906_main.txt`, `runs/full_suite_20260906_loop.txt`
- Create: `docs/evidence/G1-BASELINE-20260906.md` (Cluster-Tabelle, Provenienz je Zahl)
- Modify: nichts unter `daedalus/`

**Interfaces:**
- Produces: die Referenzzahlen, auf die A2/A3 „every non-touched case still passes“ beziehen; die Liste der pre-existing roten Tests mit Cluster-Namen.

- [ ] **Step 1: Baseline Haupttree (dirty) laufen lassen**

```powershell
& .venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider `
  -x --maxfail=200 --durations=30 tests 2>&1 | Tee-Object runs/full_suite_20260906_main.txt
```

Erwartung: läuft 20–40 min. `-x` **nicht** setzen, wenn der Lauf vollständig sein soll — hier absichtlich `--maxfail=200` ohne `-x`. Bekannt rot vor dem Lauf: `tests/test_ikarus_computer_schedule_autonomy.py` (20 failed allein bei `585b7ea4`, Lane 5), Wiki-Suiten (drei TDD-rote Tests, laut Room 21:48 seit G1-WIKI-01 grün — verifizieren).

- [ ] **Step 2: Baseline Loop-Branch im Worktree**

```powershell
Set-Location .claude/worktrees/stage3-failed-receipt
$env:PYTHONPATH = (Get-Location).Path
& .venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider --maxfail=200 tests 2>&1 |
  Tee-Object ../../../runs/full_suite_20260906_loop.txt
```

Der Worktree hat sein eigenes venv; der Store-Python auf PATH kann `daedalus` nicht importieren (Memory `loop-2026-09-05-stages`). Lane 1 meldete 23 Failures aus fehlendem `daedalus[computer]`-Extra (cv2) — vorher `uv pip install -e .[computer]` im Worktree-venv.

- [ ] **Step 3: Cluster-Tabelle schreiben**

Format wie `docs/HANDOFF.md` „Failure clusters“: `| cluster | count | disposition |`, jede Zahl `[MEASURED 2026-09-06, <Datei>]`. Disposition ∈ {baseline-rot-bekannt, lane-verursacht (Packet nennen), unbekannt → A2-Blocker, load-induced (Nachmessung ruhig)}.

- [ ] **Step 4: Commit der Evidenz**

```bash
git add runs/full_suite_20260906_main.txt runs/full_suite_20260906_loop.txt docs/evidence/G1-BASELINE-20260906.md
git commit -m "evidence: full-suite baseline on main tree and loop branch (G1-BASELINE-20260906)"
```

**Was das voranbringt:** Ohne diese Zahl ist jede Integration in A2/A3 blind. Plan §10 Schritt 2 („Baseline. Reproduce current behavior and record failing/absent evidence“) ist seit drei Wochen nicht erfüllt.

### Task A2: Uncommitted Haupttree-Arbeit als reviewte Commits in Packet-Reihenfolge landen

**Packet:** je bestehendes Packet (G1-IKARUS-25, G1-COUNCIL-02, G1-WIKI-01, G1-UI-12..15, Wiki-Regeneration, Evidence-Inventar). ALIGNED, Gate 1. **Owner-Entscheidungen zuerst (A4)** für die unangesagte 3D-Szenen-Lane und `tools/package_desktop_local.ps1`.

**Files:** die Änderungslisten der genannten Packets; `.gitattributes` trägt die nötigen Pins bereits (zwei aus Room 21:27, die fünf Twin-Module ebenfalls; gemessen 02:22/02:25).

**Interfaces:**
- Consumes: A1 Baseline.
- Produces: eine Commit-Kette, in der jeder Commit genau ein Packet ist und der Registry-/Zensus-Commit einmal am Ende steht.

- [ ] **Step 1: Ignition-Bundle-Pins als grün bestätigen (kein rot→grün mehr im Haupttree)**

```powershell
& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_ignition_bundle_gitattributes.py tests/test_byte_pin_eol_durability.py tests/test_ignition_bundle.py
```

Erwartung: grün (25 passed für die ersten beiden Dateien, Room 21:27 und daedalus-14 02:22). Der CI-Rotstand mit den fünf Twin-Modulen gehört zum Gardener-Branch #313, der die Pins nicht hat — das ist A4 Zeile 4 (Rebase auf A3), nicht ein Haupttree-Fix. Wird hier trotzdem etwas rot, ist eine neue Datei in die Closure gerutscht: je Datei eine `-text`-Zeile **bei ihren Nachbarn**, keine Wildcard.

- [ ] **Step 2: Packet-Commits in Abhängigkeitsordnung**

Reihenfolge: (1) `.gitattributes` (die bereits gesetzten Pins, als eigener Commit, damit die Ignition-Bundle-Tests in jedem späteren Commit grün sind), (2) G1-IKARUS-25 (Fence-Lift: `daedalus/kernel/policy/computer.py`, `daedalus/runtimes/computer.py`, `daedalus/runtimes/computer_files.py`, Tests, `docs/IKARUS_COMPUTER.md`, Packet), (3) G1-COUNCIL-02 inklusive der Cerberus-HIGH-Reparatur (`session.py` `_first_line` durch die Secret-Floor, 36 passed laut daedalus-14; `daedalus/council/*`, `daedalus/runtimes/execution/budget_process.py`, Tests, `.claude/skills/council/SKILL.md`, `.env.example`), (4) G1-WIKI-01 + Wiki-Regeneration (`daedalus/wiki/*`, `docs/wiki/**`, Tests), (5) `scripts/run_promotion_receipt_authority_mutations.py` — **fertig und gemessen** (Scratch-Worktree bei `585b7ea4`, Baseline 8 passed, 6/6 Mutanten getötet, Room 22:06); nur noch committen, (6) G1-UI-12/13/14/15 (`apps/web/src/shared/ui/**`, `apps/web/tests/interactive-rooms.spec.ts`, `package.json`, `roomRenderer.ts`; die sechs GLBs sind vom Owner bestätigt, siehe A4 Zeile 2 — nur die Trägerform ist offen; bis dahin `*.glb binary` in `.gitattributes`), (7) Evidence-Inventar + `docs/backlog/` + Vault. Vor jedem Commit die Suiten des Packets (Acceptance-Matrix im Packet) laufen lassen; Zahl ins Packet.

```bash
git add .gitattributes && git commit -m "gitattributes: pin the Gate-1 bundle closure files added by the fence lift"
git add daedalus/kernel/policy/computer.py daedalus/runtimes/computer.py daedalus/runtimes/computer_files.py tests/kernel/test_computer_policy.py tests/runtimes/test_computer_service.py tests/runtimes/test_computer_service_files.py tests/runtimes/test_computer_files.py tests/test_ikarus_computer_autonomy.py docs/IKARUS_COMPUTER.md docs/work-packets/G1-IKARUS-25_FILE_TOOL_FENCE_LIFT.md
git commit -m "ikarus: lift the file-tool fence behind the handle-anchored adapter (G1-IKARUS-25)"
```

(analog für 3–7; Commit-Botschaften nennen das Packet).

- [ ] **Step 3: Registry und Zensus einmal am Ende**

```powershell
& .venv/Scripts/python.exe tools/index_work_packets.py --render > docs/work-packets/index.json
& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_effect_boundary*.py tests/test_registry*.py tests/test_import_census*.py
```

Bewegte Pins (Import-SCC-Module/Kanten) nachmessen und im Commit nennen, nicht still übernehmen. `package_desktop_local.ps1` bekommt seine Registry-Zeile nur, wenn A4 es freigibt (Präzedenz `.src`-Legacy-Quelle: Zeile plus Test, der die Datei selbst parst).

- [ ] **Step 4: Full-Suite erneut, Differenz zu A1 in `docs/evidence/G1-BASELINE-20260906.md` nachtragen**

**Was das voranbringt:** Der Fence-Lift, die Council-Reparatur und die Wiki liegen sonst als 3783 Zeilen ungesicherter Diff auf einem Tree, an dem vier Sessions schreiben. Committed und suiten-gemessen werden sie zur Wahrheit; erst dann kann A3 sauber rebasen.

### Task A3: Loop-Branch (Etappen 3–15b, zehn Lanes) integrieren

**Packet:** G1-OPS-06_LOOP_BRANCH_INTEGRATION (ALIGNED, Gate 1). **Reviewer:** Codex über die `cli.council`-Tür für den Merge-Diff.

**Files:** Konflikte erwartet in `daedalus/runtimes/computer.py` (`capabilities()`-Schleife: Haupttree Fence-Lift vs. Branch Etappe 13 „locked tools reported“), `daedalus/council/vendors.py` (COUNCIL-02 vs. ARIADNE-07), `docs/work-packets/index.json`, `.gitattributes`, `docs/FOURFOLD_V2_EXECUTION_PLAN.md`.

- [ ] **Step 1: Merge-Vorschau ohne Commit**

```bash
git merge --no-commit --no-ff loop/stage3-failed-receipt || git diff --name-only --diff-filter=U
```

Konfliktdateien notieren. `git merge --abort`, falls die Liste mehr als die vier erwarteten Dateien plus Registry enthält — dann zuerst die Ursache verstehen.

- [ ] **Step 2: Konflikte in `computer.py` so lösen, dass beide Verträge halten**

Regel: der Haupttree gewinnt für `RELEASE_DISABLED_TOOLS`-Lesen zur Laufzeit (`_release_policy.*` at call time, Odysseus O-1); der Branch gewinnt für die Unavailable-Meldung release-gesperrter Werkzeuge (Etappe 13). Beide Tests müssen bleiben: `tests/runtimes/test_computer_service.py` (Haupttree) und `tests/test_ikarus_computer_loop.py::*locked*` (Branch). Der Service-Test des Branches liest `RELEASE_DISABLED_TOOLS`, hält also auf beiden Seiten (Memory Etappe 13).

- [ ] **Step 3: Registry, Zensus, Index einmal; dann Suiten**

Wie A2 Step 3. Danach die 22 Suiten des Branches plus die Packet-Suiten von A2:

```powershell
& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_ikarus_computer_loop*.py tests/runtimes tests/kernel tests/test_council*.py tests/test_ariadne*.py tests/ariadne tests/test_budget*.py tests/test_ignition_bundle*.py
```

Erwartung: 672 + 153 + 167 ± bewegte Zensus-Pins; jede Abweichung benannt.

- [ ] **Step 4: Merge-Commit, Full-Suite, PR**

```bash
git commit -m "integrate loop/stage3-failed-receipt: stages 3-15b and ten lane packets (G1-OPS-06)"
gh pr create --draft --title "G1-OPS-06 — integrate the 2026-09-05 loop branch" --body-file docs/work-packets/G1-OPS-06_LOOP_BRANCH_INTEGRATION.md
```

CI-Ergebnis (A5) ins Packet. Lane-Worktrees erst entfernen, wenn der Owner die Packets gesehen hat (`git worktree remove`, Branches bleiben).

**Was das voranbringt:** KERNEL-02 (abbrechbare Provider-Calls), IKARUS-29/31 (Plan-Budget, native Route), ARIADNE-04..09, HW-01, EDA-02, SELF-01 existieren heute nur auf einem Seitenbranch. Ohne Integration baut C2/D1 auf einer Wahrheit, die der Haupttree nicht hat — und Peer `daedalus-9d` (IKARUS-32) muss sonst zweimal rebasen.

### Task A4: Owner-Entscheidungen bündeln (ein Dokument, eine Antwortrunde)

**Packet:** `docs/decisions-pending/OWNER_DECISIONS_20260906.md` (docs-only). Der Owner antwortet terse; deshalb eine Liste mit Empfehlung und Default, die bei Schweigen gilt.

**Files:** Create `docs/decisions-pending/OWNER_DECISIONS_20260906.md`.

- [ ] **Step 1: Die elf Entscheidungen mit Empfehlung schreiben**

| # | Entscheidung | Empfehlung | Default bei Schweigen |
| --- | --- | --- | --- |
| 1 | Amendment 013 (Hardware-Targets, Self-Renovation-Leakage-Regel) annehmen? | **Ja**, exakt wie entworfen; ohne 013 bleiben D3, F1, F2 EXPERIMENT ohne Produktpfad | nicht annehmen; D3/F bleiben EXPERIMENT |
| 2 | 3D-Szenen: die sechs GLBs (7.777.244 Bytes) sind **vom Owner bestätigt** (G1-UI-15: Anfrage 2026-09-05, Neupaketierung 2026-09-06 08:00 ausdrücklich bestätigt; Bildmodus bleibt Default und Fallback). Offen ist nur die **Trägerform** der Derivate: committete Bytes oder Build-Schritt/Release-Asset aus den `.blend`-Quellen? | Build-Schritt/Release-Asset ab dem nächsten Release; bis dahin committete Bytes mit `*.glb binary` in `.gitattributes` und Manifest-Digest gegen den Byte-Pin-Zensus | committete Bytes, `*.glb binary` (die 08:00-Paketierung darf nicht blockieren) |
| 3 | `tools/package_desktop_local.ps1` als Maintainer-Tür registrieren (Row + Test) oder entfernen? | registrieren; „creates no runtime entrypoint“ aus der Doku streichen | registrieren |
| 4 | PR #313 (Gardener) und #314 (Tensor-GPU) — weiterführen, rebasen auf A3, oder schließen? | #313 nach A3 rebasen und dessen fünf Twin-Pins übernehmen; #314 bleibt EXPERIMENT-Draft | offen lassen |
| 5 | Lane-Worktrees `.claude/worktrees/lane*` entfernen nach A3? | ja, Branches behalten | entfernen nach A3 |
| 6 | 125 archivierte Remote-Branches löschen (Kit `docs/recovery/cleanup_2026-08-23/README.md`, seit 23.08. offen)? | ja | offen |
| 7 | Renovation-Zweitsubjekt für B4/E3: welches fremde Repo (Lizenz MIT/BSD/Apache, < 5k LOC, hat py + md + csv/json-schema)? Vorschlag: ein kleines Python-Datenprojekt mit Schema-Datei; drei Kandidaten mit Lizenz und Revision im Dokument | Kandidat 1 | Kandidat 1 |
| 8 | Verwaiste Ledger-Reservierung `688f434b…` (3,00 USD worst_case, Prozess tot, gekillter Council-Lauf 2026-09-05): Owner-Freigabe zum Abschluss als `released` **oder** eine registrierte Reap-Tür, die tote PIDs nach Frist abschließt (eigenes Packet, Effekt-Registry-Zeile) | Reap-Tür bauen (wiederholbar, kein Handeingriff in `ledger.json`) | Reservierung bleibt offen; Ledger wird nie von Hand editiert |
| 9 | `docrefs.DOC_GLOBS` auf Docstrings unter `daedalus/` erweitern (SELF-01-Backlog; neue autonome Edit-Fläche für D3)? | ja, nur als Gate-Subjekt, nie als Schreibrecht | nein |
| 10 | Darf der Owner `codex_cli` (oder einen anderen Remote-Vendor) als **Computer-Planer** über `planner_provider` + `allow_remote_context` wählen? Das ist eine **Egress-Entscheidung**, keine Routing-Frage: Beobachtungstext aus `browser.read` (und künftig `file.read`, `document.read`, OCR) verlässt dann den Host. Gemessen: measure-09 erreichte damit als erste Mission `finish` (59,7 s, 4 Calls), der lokale 7B nie; n=1, vierfach konfundiert | erlauben, aber nur mit (a) sichtbarer Remote-Context-Warnung in der Konfiguration und im Cockpit (C8) **vor der ersten Mission**, (b) gepinntem Test, dass **jede** Beobachtung vor dem Eintritt in den Remote-Prompt durch `secret_floor_rule` läuft — ausdrücklich für den Codex-Pfad, nicht nur die Fixture-Seite, (c) keiner stillen Default-Umschaltung; Widening = transiente Bestätigung nach §4.1. Die Alternative „stärkeres lokales Modell (~9 GB Q4, reine CPU neben dem Desktop)“ nur nach einer Tokens/s-Messung — sonst dieselbe 74-s-Falle in größer (6e 03:27) | lokal bleiben (Ollama native Route); C2 läuft dann nur den lokalen Arm, und G1-IKARUS-34 sagt voraus, dass er 0/5 bleibt |
| 11 | Soll die **Desktop-App einen File-Bridge-Watcher besitzen**, damit Termine, Queue und Serien ohne Terminal laufen? Heute läuft Autonomie nur, solange `python -m daedalus.file_bridge watch --repo-root <Ordner>` für genau diesen Ordner läuft; v0.1.6 hat den Watcher bewusst nicht übernommen (G1-IKARUS-20); auf dieser Box tickt keiner (G1-IKARUS-35) | ja, als eigenes effektbehaftetes Packet (Registry-Zeile, Kill-Switch-Bindung, sichtbarer Watcher-Status im Cockpit, Heartbeat an den Autoritäts-Root gebunden); Vorschlag G1-IKARUS-41 nach C8 | bleibt Terminal-Feature; der Chat sagt das weiter ehrlich (35er-Zeile) |

- [ ] **Step 2: Dem Owner im Chat die Liste als elf Zeilen vorlegen; Antworten ins Dokument, Datum, wörtliche Antwort**

**Was das voranbringt:** Fünf Lanes hängen an Entscheidungen, die seit Tagen als Room-Fragen herumliegen (3D-Szenen, `.ps1`, 013, Branch-Cleanup). Ein Dokument mit Defaults beendet das Warten.

### Task A5: CI wird wieder Quittung

**Packet:** G1-CI-02_SUITE_ON_WORKING_BRANCH (ALIGNED). Voraussetzung: CI-Jobs starten wieder (gemessen 2026-09-06, Runs 340004139xx).

**Files:**
- Modify: ein Workflow unter `.github/workflows/` (Achtung: `.github/` ist `high_risk_paths` in `.agentenv/agentenv.json` — Änderung im Packet ausweisen, Owner in A4 Zeile 3 mitentscheiden lassen)
- Test: `tests/test_workflow_references.py` (existiert; erweitert um den neuen Trigger)

- [ ] **Step 1: Failing test — der Working-Branch hat keinen Full-Suite-Workflow**

```python
# tests/test_workflow_references.py (Ergänzung)
def test_a_push_to_the_integration_branch_runs_the_full_suite():
    workflows = _parsed_workflows()  # bestehender Helfer in der Datei
    hits = [w for w in workflows
            if "codex/ikarus-computer-assistant-20260905" in _push_branches(w)
            and any("pytest" in step and "tests" in step for step in _run_steps(w))]
    assert hits, "no workflow runs the full suite on the integration branch"
```

- [ ] **Step 2: Run → FAIL**  `pytest tests/test_workflow_references.py -q`

- [ ] **Step 3: Workflow-Trigger ergänzen (Python 3.10/3.12/3.13 Matrix wie der Ignition-Job), `--maxfail=200`, Artefakt `full_suite.txt` hochladen**

- [ ] **Step 4: Run → PASS; push; Run-ID ins Packet; erste rote CI-Cluster gegen A1 abgleichen**

**Was das voranbringt:** Seit dem 25.08. galt „CI ist keine Quittung“. Sie startet wieder; ein Full-Suite-Lauf pro Push macht die A1-Baseline zur laufenden Messung statt zur Momentaufnahme.

---

## Phase B — Gate-1-Renovation-Obligation schließen

### Task B1: Activation-Checklist gegen HEAD neu vermessen

**Packet:** G1-RENOVATION-01_RESIDUAL_MEASUREMENT (Evidence-only, ALIGNED). **Delegat:** Atalanta.

**Files:** Create `docs/evidence/G1-RENOVATION-01_RESIDUAL_20260906.md`; Modify `docs/work-packets/G1_ACTIVATION_CHECKLIST.md` (nur Checkbox-Zustand + Test-Node-ID je Zeile, datiert).

- [ ] **Step 1:** Jede Checklist-Zeile §2.1–§2.5 einem Test-Node zuordnen oder `OPEN` markieren. Kommandos:

```powershell
& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/ignition tests/test_ignition_gate1.py tests/test_ignition_bundle.py --co
& .venv/Scripts/python.exe -m daedalus.ignition   # schreibt runs/ignition/mission-gate1-voltage-ignition/receipt.json
```

Aus dem Receipt: `replay`-Block, `promotion.status`, Anzahl EvidenceItems, ob ein `failed`-Zustand überhaupt darstellbar ist (Checklist §2.4 letzter Punkt).

- [ ] **Step 2:** Tabelle `| Checklist-Zeile | Zustand | Beweis (Node-ID / Receipt-Feld) |`. Erwartung nach Lesestand: §2.1 geschlossen (MissionContract, WorkItems aus `fourfold.json`, Attempts über Kernel), §2.2 geschlossen (echtes Git mit `FROZEN_GIT_ENV`), §2.3 geschlossen (Attempt-Grenze), §2.4 **offen** (retained failed packet), §2.5 **offen** (Restart aus dem Spine, Double-Start-Race). Diese Erwartung ist [A] — die Messung entscheidet.

- [ ] **Step 3:** Commit `evidence: Gate-1 Renovation residual measured against HEAD (G1-RENOVATION-01)`.

**Was das voranbringt:** Ohne diese Messung weiß niemand, wie viele Packets die Gate-Klausel noch braucht. B2/B3 werden hier bestätigt oder gestrichen.

### Task B2a (eingefügt 2026-09-06 09:15 nach B1): Ein Ignition-Pfad statt zwei

**Packet:** G1-RENOVATION-02A_ONE_IGNITION_PATH (ALIGNED, Gate 1; §13 „no second implementation truth“, AGENTS.md „prefer deletion, consolidation“). **Befund B1 (gemessen):** `python -m daedalus.ignition` läuft `gate1.py`; die gesamte Fault-Matrix in `tests/ignition/` (10 Nodes: Debris-Refusal, Nested-Root, Precondition, Mid-Run-Mutation, Crash zwischen Renames) exerziert dagegen den Legacy-Rehearsal-Pfad `runner.py` mit synthetischen Revisionen. Die Abdeckung, die die Activation-Checklist §1 als „settled“ führt, gilt für den ausgelieferten Pfad nicht.

**Files:**
- Modify: `daedalus/ignition/runner.py` (Rehearsal-Pfad entfernen oder auf `gate1` delegieren; `_behavior` bleibt vorerst, wird als offene Zeile F4 geführt), `daedalus/ignition/gate1.py` (`_replay_blockers` erhält den `previous_run_complete`-Konjunkt, den `replay_demonstrated` schon prüft — B1-Befund F2, `gate1.py:1654-1690` vs `2301-2312`)
- Modify: `tests/ignition/test_voltage_ignition.py`, `tests/ignition/test_voltage_ignition_faults.py` (auf die `gate1`-Tür portiert; jede Fault-Zeile bleibt eine Zeile)
- Modify: `docs/work-packets/G1_ACTIVATION_CHECKLIST.md` (§1 nennt jetzt den Pfad, den sie beweist; §3 Gate-0-Vorbedingung als überholt markiert)

- [ ] **Step 1: Failing test — Exit-Code 0 impliziert `replay_demonstrated`**

```python
def test_exit_zero_implies_replay_demonstrated(prepared_control_root_with_stale_receipt):
    result = run_gate1_ignition(control_root=prepared_control_root_with_stale_receipt)
    assert (result.exit_code == 0) == (result.receipt["replay"]["replay_demonstrated"] is True)
```

- [ ] **Step 2: Run → FAIL** (B1 Lauf 2: exit 0, `replay_demonstrated=false`).
- [ ] **Step 3:** Konjunkt in `_replay_blockers` ergänzen; dann die Fault-Matrix Test für Test auf `gate1` umziehen (jeder Test muss vor dem Umzug rot gegen `gate1` sein oder als „von gate1 bereits abgedeckt durch <Node>“ benannt werden), zuletzt `runner.py` auf das reduzieren, was `gate1` importiert (`_behavior`, `WORK_ITEMS`-Konstanten, sofern noch referenziert).
- [ ] **Step 4:** Ignition-Suiten grün (B1-Baseline: 104 passed); Byte-Pin-Zensus grün; ein Lauf der Tür mit frischem Receipt committet (der Store unter `runs/ignition/…` wird von der Tür per `rmtree` ersetzt, B1-Befund F3 — der Commit enthält den neuen Store vollständig).
- [ ] **Step 5:** Commit.

**Was das voranbringt:** Ohne diesen Schritt beweist B2b einen Restart auf einem Pfad, den keine Fault-Matrix deckt. Zwei Wahrheiten für dieselbe Gate-Klausel sind genau das, was §13 verbietet.

### Task B2b: Restart nach Crash mit derselben Attempt-Identität

**Packet:** G1-RENOVATION-02B_SPINE_RESTART (ALIGNED, Gate 1; berührt Invariante 1, 6, 7). **Review:** Odysseus (Crash-Injektion), Codex (Vertrag). Abhängig von B2a. B1-Befund F5: der Double-Start-Test ist schedulable (`AttemptContract` und CAS `StoredSourceTree` existieren) und gehört hierher.

**Files:**
- Modify: `daedalus/ignition/gate1.py` (Wiederaufnahme-Einstieg), `daedalus/orchestration/execution/*` nur, wenn die Wave-Executor-Wiederaufnahme dort fehlt (messen in B1)
- Test: `tests/ignition/test_voltage_ignition_restart.py` (neu)

**Interfaces:**
- Consumes: `run_gate1(...)` (Einstieg in `gate1.py`, Signatur beim Öffnen prüfen), AttemptLedger-Events, die Continuation-Recovery-Muster aus G1-IKARUS-21 (`_recover_continuations`-Seam in `computer_schedule.py:484`).
- Produces: `resume_gate1(control_root, mission_id) -> IgnitionReceipt` — derselbe Receipt-Typ, Feld `replay.resumed_from_event_seq: int`.

- [ ] **Step 1: Failing test — Kill zwischen Attempt-Begin und Attempt-Complete, Restart, gleiche IDs, kein doppelter Effekt**

```python
def test_restart_after_crash_between_attempts_keeps_identity_and_duplicates_no_effect(tmp_path):
    ctl = tmp_path / "control"
    first = _run_gate1_in_subprocess(ctl, kill_after_event="attempt.begin", which=2)  # Helfer: startet python -m daedalus.ignition, killt beim 2. attempt.begin
    assert first.returncode != 0
    events_before = _read_spine(ctl)
    receipt = resume_gate1(ctl, mission_id="mission-gate1-voltage-ignition")
    events_after = _read_spine(ctl)
    assert receipt.replay.resumed_from_event_seq == len(events_before)
    assert [e["attempt_id"] for e in events_after if e["type"] == "attempt.begin"] == \
           sorted({e["attempt_id"] for e in events_after if e["type"] == "attempt.begin"})  # jede Attempt-ID genau einmal begonnen
    assert receipt.candidate_bundle_sha256 == _fresh_run(tmp_path / "fresh").candidate_bundle_sha256  # digest-identisch zum sauberen Lauf
```

- [ ] **Step 2: Run → FAIL** (`resume_gate1` existiert nicht).
- [ ] **Step 3:** Minimal implementieren: Spine lesen, letzten konsistenten Zustand bestimmen (abgeschlossene Attempts übernehmen, angefangene als `interrupted` terminalisieren — nie blind wiederholen), Rest des Laufs mit denselben abgeleiteten IDs fortsetzen. Debris-Refusal aus `test_voltage_ignition_faults.py` bleibt unverändert grün.
- [ ] **Step 4: Run → PASS**, plus die bestehenden Ignition-Suiten.
- [ ] **Step 5:** Commit `ignition: restart after a crash resumes from the event spine with the same attempt identity (G1-RENOVATION-02)`.

**Was das voranbringt:** Die Gate-1-Klausel sagt wörtlich „restart/replay works“. Heute ist „Restart“ ein Neustart von vorn. Das ist die eine Zeile, die Gate 1 wirklich schließen muss.

### Task B3: Ein fehlgeschlagener Check produziert ein retained `failed` EvidencePacket

**Packet:** G1-RENOVATION-03_FAILED_PACKET_RETAINED (ALIGNED; Invariante 7). Muster: G1-ARIADNE-04 (failed receipt on first call).

**Files:**
- Modify: `daedalus/ignition/checks.py` (Check-Ergebnis als `EvidenceItem(verdict="failed")` statt Exception), `daedalus/ignition/runner.py:_item` (hardcodiertes `verdict="passed"` entfernen)
- Test: `tests/ignition/test_voltage_ignition_failed_packet.py` (neu)

- [ ] **Step 1: Failing test**

```python
def test_a_failing_link_check_yields_a_failed_packet_that_is_retained(tmp_path, monkeypatch):
    target = _prepare_target(tmp_path)           # bestehender Helfer aus test_voltage_ignition.py
    (target / "wiki" / "Event.md").write_text("[[Nonexistent]]", encoding="utf-8")  # Link-Check muss rot werden
    receipt = run_gate1(target, control_root=tmp_path / "ctl")
    assert receipt.packet.status == "failed"
    failed = [i for i in receipt.packet.items if i.verdict == "failed"]
    assert [i.evaluator for i in failed] == ["ignition-link-check"]
    assert (tmp_path / "ctl" / "evidence").exists()  # Packet liegt im CAS, nicht nur im Speicher
    assert receipt.promotion.status == "nominated, not promoted" or receipt.promotion.status == "not nominated"
```

- [ ] **Step 2: Run → FAIL** (heute `IgnitionError` statt Packet).
- [ ] **Step 3:** Minimal: Check-Funktionen geben `(verdict, detail)` zurück; Packet-Status = `failed`, wenn ein Item `failed` ist; Nominierung nur bei `passed`. Bestehende Negativkontrollen (jede Check-Klasse „gemessen rot“) bleiben.
- [ ] **Step 4: Run → PASS**; Ignition-Suiten grün.
- [ ] **Step 5:** Commit.

**Was das voranbringt:** Invariante 7 („Failures and rejected candidates remain inspectable“) ist im Renovation-Pfad heute nicht erfüllbar, weil ein Fehler nur eine Exception ist. Ariadne kann es seit Etappe 3; Renovation muss es können, bevor ein Reviewer die Gate-Klausel abnimmt.

### Task B4: Renovation auf einem fremden, lizenzgeprüften, revisionsgepinnten Repository

**Packet:** G1-RENOVATION-04_SECOND_SUBJECT (ALIGNED, Gate 1; nutzt ARIADNE-08 Git-Objekt-Leser). Subjekt: A4 Entscheidung 7.

**Files:**
- Create: `docs/corpus/<repo>/PROVENANCE.md` (Lizenz, Revision, temporaler Cutoff, Download-Digest), `daedalus/ignition/subjects.py` (Subjektbeschreibung: Basis-Revision, Rename-Ziel, erwartete Planes)
- Modify: `daedalus/ignition/gate1.py` (Subjekt als Parameter statt Fixture-Konstante; WorkItems aus den vier Planes des Subjekts, nicht aus `fourfold.json` des Fixtures)
- Test: `tests/ignition/test_second_subject.py`

- [ ] **Step 1: Failing test — die vier Planes des fremden Repos liefern genau zwei WorkItems für eine gegebene Rename-Absicht**

```python
def test_second_subject_yields_two_typed_work_items_from_its_planes(second_subject_checkout):
    snapshot = compile_reference_project(second_subject_checkout, source_revision=SECOND_SUBJECT.revision)
    items = derive_work_items(snapshot, rename=("old_name", "new_name"))
    assert [i.planes for i in items] == [("code", "type"), ("data", "knowledge")]
    assert all(p in snapshot.plane("code").paths or p in snapshot.plane("data").paths or p in snapshot.plane("knowledge").paths
               for i in items for p in i.paths)
```

- [ ] **Step 2: Run → FAIL** (`derive_work_items` fehlt; heute liest `gate1.py` `fourfold.json`).
- [ ] **Step 3:** `derive_work_items` aus den Plane-Mitgliedschaften (Code/Type: Symbolvorkommen; Data: Spalten-/Feldnamen; Knowledge: Wiki-Links). Base-Inhalt über `git_objects.blob_at(commit, path)` (ARIADNE-08, pure stdlib) verifiziert, nicht über die Arbeitskopie.
- [ ] **Step 4:** Lauf `python -m daedalus.ignition --subject <repo>` → Receipt; Replay digest-identisch; Fixture-Lauf unverändert.
- [ ] **Step 5:** Commit; `PROVENANCE.md` mit Lizenztext-Digest.

**Was das voranbringt:** Gate 1 verlangt „the four planes produce two typed WorkItems“. Heute sind die WorkItems aus einer Fixture-Datei abgeleitet, die die Antwort schon kennt. Ein fremdes Repo beweist die Ableitung — und ist zugleich der erste Corpus-Eintrag für E3.

### Task B5: Unabhängiges Review, Adversarial-Matrix, Owner-Vorlage „Renovation-Klausel erfüllt“

**Packet:** G1-RENOVATION-05_REVIEW_AND_DECISION (Evidence + docs-only).

- [ ] **Step 1:** Odysseus: Malformed-Subject, Stale-Revision (HEAD bewegt sich zwischen Compile und Attempt), Cancel während Attempt 2, Timeout, Double-Start (zwei Prozesse, derselbe Kandidatenpfad; Checklist §2.5 letzter Punkt), Policy-Bypass-Versuch (Kandidat schreibt in `evidence/`). Jeder Fall: Test-Node + gemessene Refusal.
- [ ] **Step 2:** Codex über `cli.council` (live, zwei Sitze) über den B2–B4-Diff; Dissens wörtlich ins Packet.
- [ ] **Step 3:** `docs/decisions-pending/GATE1_RENOVATION_CLAUSE_20260906.md`: Klausel für Klausel mit Beweis; **kein** Gate-Schluss-Claim — Genesis- und Computer-Strang stehen ausdrücklich getrennt (Plan §11 Gate 1 letzter Absatz).

**Was das voranbringt:** Plan §10 Schritte 5–9. Das ist der Punkt, an dem Gate 1 vom Owner geschlossen werden *kann* — die Vorlage, nicht der Schluss.

---

## Phase C — Ikarus bringt Aufgaben zu Ende

### Task C1: (Peer-Lane, nur Referenz) Planner-Fortschritt für kleine Modelle — G1-IKARUS-32

Session `daedalus-9d` (15-min-Cron „Ikarus besser und autonomer“) hält `computer_loop.py` (`_prompt` mit deterministischem Plan-Fortschritts-Payload), Tests in `tests/test_ikarus_computer_loop.py`, Lane `loop/lane11-planner-progress` auf `04fde78b`. Stand 04:15: Packets G1-IKARUS-32 (Fortschritts-Prompt), -33 (Planner-Provenienz und Egress-Zeile im Missionsbericht), -34 (EXPERIMENT, negativ: Payload-Form ist nicht das Hindernis) und -35 (Watcher-Wahrheit) auf der Lane, 179 passed, Registry 352/286. Nächster Schritt dort: unabhängiges Review der Commits über die Council-Tür. Dieser Plan fasst die Datei nicht an; C2 baut auf der integrierten Lane auf. **Packet-IDs G1-IKARUS-33..35 sind belegt; dieser Plan vergibt ab 36.**

### Task C2: `finish` reproduzieren — beide Arme, n≥5, Secret-Floor auf dem Remote-Pfad gepinnt

**Packet:** G1-IKARUS-36_REPRODUCED_FINISH (Evidence + ein gepinnter Test; ALIGNED). Abhängig von A3 (KERNEL-02, IKARUS-31..35 im Haupttree), **G1-IKARUS-43** (daedalus-6c, reserviert 08:46: Remote-Planner als explizite Owner-Wahl mit Warnung und gepinntem Secret-Floor-Test — der Test in Step 1 unten wird dort gebaut; hier nur noch verifiziert) und **A4 Zeile 10** (Remote-Planer ist eine Egress-Entscheidung; bei „lokal bleiben“ läuft nur Arm b, und G1-IKARUS-34 sagt für ihn 0/5 voraus — dann ist das Packet eine bestätigte Negativ-Evidenz, kein Fortschritt).

**Files:**
- Create: `docs/evidence/G1-IKARUS-36_REPRODUCED_FINISH/measure-11..20.md` + Manifest (`-text` gepinnt, Home-Pfad gescrubbt — Lane-10-Lektion)
- Test: `tests/runtimes/test_computer_service_remote_context.py` (neu; Service-Ebene, nicht `computer_loop.py`)
- Modify: `docs/IKARUS_COMPUTER.md` (Planner-Routing-Absatz mit Remote-Context-Warnung, wenn A4 #10 „erlauben“ sagt; Konflikt mit der Loop-Branch-Fassung aus IKARUS-33 beim Stacken erwartet)

- [ ] **Step 1: Failing test — jede Beobachtung läuft vor dem Eintritt in einen Remote-Planner-Prompt durch die Secret-Floor, ausdrücklich für den Codex-Pfad**

```python
def test_every_observation_passes_the_secret_floor_before_a_remote_planner_prompt(scratch_authority, capturing_codex_planner):
    page_text = "title\nAKIA0000000000000000\nend"          # AWS-Key-Muster, das secret_floor_rule fängt
    service = ComputerService.for_test(scratch_authority, planner_provider="codex_cli", allow_remote_context=True)
    service.record_observation("browser.read", {"text": page_text})
    service.plan_next_step()
    sent = capturing_codex_planner.last_prompt
    assert "AKIA0000000000000000" not in sent
    assert "[withheld: secret floor]" in sent               # die Auslassung ist sichtbar, nie stumm
```

- [ ] **Step 2: Run → FAIL oder PASS.** Wenn PASS: die Filterung vor CAS und Planer (Kommentar in `computer.py`) deckt den Codex-Pfad — dann bleibt der Test als Pin und das Packet dokumentiert, welche Zeile ihn erfüllt. Wenn FAIL: die Floor sitzt vor CAS, aber nicht vor dem Prompt-Bau; Fix an der Service-Naht, nicht im Loop.
- [ ] **Step 3: Zehn Läufe unter gleichem Budget (wall_time 300 s, attempts, `max_steps` 16), Seeds 0–4 je Arm:** (a) `codex_cli` über `allow_remote_context` — nur bei A4 #10 „erlauben“; (b) `qwen2.5-coder:7b` native Route mit IKARUS-32-Prompt. Aufzeichnen: Calls, Sekunden, Terminal (`completed`/`stalled`/`step_limit`/`timeout`), Tool-Schritte, `task_success_verified`, Box-Last (die Vierfach-Konfundierung von measure-09 wird so auf Modell+Transport reduziert; Last wird gemessen, nicht angenommen).
- [ ] **Step 4:** Ergebnis-Tabelle ins Packet; `task_success_verified` wird nur wahr, wenn eine unabhängige Evidenz (Sentinel im `browser.read`-Ergebnis) es trägt — Invariante 4. Ein Arm mit 0/5 `finish` ist retained Negativ-Evidenz, kein Grund für Prompt-Tuning (6e 02:33: erst wenn der starke Planer bei n≥5 stabil ist, lohnt Tuning für den 7B).

**Was das voranbringt:** measure-09 ist ein einzelner Lauf unter Last. Erst n≥5 pro Arm macht aus „Ikarus kann eine Aufgabe abschließen“ eine Aussage, und der gepinnte Secret-Floor-Test macht den Remote-Planer überhaupt erst zulässig.

### Task C3: Terminal-Fähigkeit `terminal.run` (bounded, allowlisted)

**Packet:** G1-IKARUS-37_TERMINAL_TOOL (ALIGNED; §7.2 nennt „terminal tasks“; Invariante 3, 8). **Review:** Cerberus BLOCKING, Odysseus. Größtes neues Trust-Surface dieses Plans — deshalb eng: kein freier Shell-String, nur `argv`-Listen gegen eine Policy-Allowlist, durch die vorhandene `command_gate`/Containment und die KERNEL-01-Interpreter-Auflösung.

**Files:**
- Modify: `daedalus/kernel/policy/computer.py` (TOOL_SPEC `terminal.run`, Policy-Feld `terminal_allowlist: tuple[tuple[str, ...], ...]`, Fence-Konstante `RELEASE_TERMINAL_FENCED = True` bis Phase 2), `daedalus/runtimes/computer.py` (`_dispatch`-Route)
- Create: `daedalus/runtimes/computer_terminal.py` (Adapter: argv-Exaktmatch gegen Allowlist, cwd = handle-anchored Workspace-Verzeichnis aus `WorkspaceFiles`, Umgebung gescrubbt, stdout/stderr gedeckelt, Timeout aus Mission, Exit-Code + Digests ins Result)
- Test: `tests/runtimes/test_computer_terminal.py`, `tests/kernel/test_computer_policy.py` (Ergänzung)

- [ ] **Step 1: Failing tests (Refusal zuerst)**

```python
def test_terminal_refuses_an_argv_not_in_the_allowlist(policy_with_allowlist):
    with pytest.raises(ComputerRefused, match="not allowlisted"):
        WorkspaceTerminal(policy_with_allowlist, checkpoint=lambda: None).execute("terminal.run", {"argv": ["python", "-c", "print(1)"]})

def test_terminal_refuses_a_shell_string(policy_with_allowlist):
    with pytest.raises(ComputerRefused, match="argv list"):
        WorkspaceTerminal(policy_with_allowlist, checkpoint=lambda: None).execute("terminal.run", {"command": "dir"})

def test_terminal_runs_an_allowlisted_argv_in_the_workspace_and_binds_digests(policy_with_allowlist, workspace):
    (workspace / "a.txt").write_text("x")
    r = WorkspaceTerminal(policy_with_allowlist, checkpoint=lambda: None).execute("terminal.run", {"argv": ["cmd", "/c", "dir", "/b"]})
    assert r["exit_code"] == 0 and "a.txt" in r["stdout"] and r["stdout_sha256"]
    assert r["postcondition_verified"] is True and r["cwd_scope_kind"] == "handle-anchored-computer-workspace"
```

- [ ] **Step 2: Run → FAIL** (Modul fehlt).
- [ ] **Step 3:** Adapter minimal; sieben Evidenzklassen als Tests: real (cmd /c dir), Postcondition (Digest + Exit), Refusal (Allowlist, Shell-String, Secret-Floor auf stdout), stale target (Workspace-Verzeichnis zwischen Checkpoint und Spawn umbenannt → Sharing-Violation, wie IKARUS-24), Cancellation (Kill-Switch beendet den Kindprozess, gemessen), Timeout (Mission-Deadline killt, Result `timeout`), Crash (Neustart findet den STARTED-Lease und terminalisiert `reconciliation_required`, nie Wiederholung).
- [ ] **Step 4:** Phase 2 nach Cerberus/Odysseus: Fence-Flag auf `False`; Capability-Projektion; `docs/IKARUS_COMPUTER.md`.
- [ ] **Step 5:** Registry-Zeile für den neuen Effekt-Typ, Digest-Pins neu messen; Commit.

**Was das voranbringt:** Terminal ist die am häufigsten gebrauchte Assistenz-Fähigkeit (Capability-Map Zeile 1) und heute „missing by design“. Mit argv-Allowlist statt Shell bleibt das neue Surface klein genug für einen Cerberus-Pass.

### Task C4: Replace-Zaun heben — IKARUS-27 D1+D2, dann Reconciler

**Packet:** G1-IKARUS-27 (existiert als Entwurf; Momus-Einwände beantwortet, Q2 offen). Reihenfolge laut Packet-Empfehlung: **D1** reservierte Namen aus `execution_id` ableiten (statt `secrets.token_hex`), **D2** Pre-Effect-Intent an den START-Receipt binden; erst dann der Reconciler an der `_recover_continuations`-Seam; Q2 (Kernel-Frage: `finish_effect` braucht eine lebende Authorization) als eigenes Kernel-Packet vor dem Flip.

- [ ] **Step 1:** D1 failing test: zwei Replacements mit derselben `execution_id` reservieren denselben Backup-Namen; ein Restart findet Backup↔Original über die ID, nicht über Zufall.
- [ ] **Step 2:** D2: der START-Receipt trägt `intent: {target_sha256, replacement_sha256, backup_name}` vor dem ersten Rename.
- [ ] **Step 3:** Q2 als G1-KERNEL-03 (Authorization für Reconciliation-Terminale) — Codex-Design-Review vor dem Bau.
- [ ] **Step 4:** Reconciler + Crash-Matrix (Kill nach Rename 1, nach Rename 2, vor Cleanup) → `RELEASE_REPLACE_FENCED = False`; Cerberus-Bestätigung an Datei-Hashes binden. POSIX-Residuum N-1 (link+unlink) bleibt vor jedem POSIX-Lift.

**Was das voranbringt:** Ohne Replace kann Ikarus keine bestehende Datei ändern — der häufigste Dateieffekt überhaupt bleibt gesperrt.

### Task C5: Vision-Pfadformen (IKARUS-28) und erste Document-Fähigkeit

**Packet:** G1-IKARUS-28 (Phase 1: `WorkspaceFiles.read_bytes` + `ImageBytes`, PNG/JPEG-Magic-Check, xfail-Baseline existiert; Phase 2: Fence-Lift nach Review), danach **G1-IKARUS-38_DOCUMENT_READ**: `document.read` als observation-only Werkzeug über dieselbe Bytes-Seam, Textextraktion für `.md/.txt/.csv/.json` (stdlib) und `.pdf/.docx` (nur, wenn ein Extra installiert ist — sonst `unavailable`, kein Fallback), Secret-Floor auf dem extrahierten Text, Größe gedeckelt (`max_document_bytes`).

- [ ] **Step 1:** IKARUS-28 Phase 1: die xfail-Marker in `tests/runtimes/test_computer_vision_paths.py` fallen; `read_bytes` lehnt Nicht-Bild-Magic ab (Text kann nicht als Bild durchrutschen).
- [ ] **Step 2:** Phase 2 nach Codex-Review; `RELEASE_DISABLED_TOOLS` wird leer; Inventar-Assertion angepasst.
- [ ] **Step 3:** `document.read` failing test: `.env` → withheld; 10-MB-Datei → refused; `.md` → Text + Digest + `postcondition_verified`; `.pdf` ohne Extra → `unavailable` mit Grund.
- [ ] **Step 4:** Evidence-Matrix Zeile 5 (Document) bekommt ihre ersten vier Zellen.

**Was das voranbringt:** Zwei Zäune fallen mit einem reviewten Mechanismus, und die leerste Zeile der Matrix (Document, 7 GAP) bekommt Substanz ohne neues Trust-Surface.

### Task C6: Skill-Verzeichnisse über das handle-anchored Muster lesen

**Packet:** G1-IKARUS-39_SKILL_DIRECTORY_READS (Capability-Map Gap 3). `refuse_workspace_path_io` an der Skill-Seam (`computer_context.py`) durch `WorkspaceFiles.read`/`list` ersetzen; Skills bleiben inert, untrusted gerendert, versioniert (CONTEXT-01). Failing test: eine Skill-Auswahl aus einem Verzeichnis mit Junction → refused; ohne → gelesen mit Digest; Skill-Text kann Policy nicht ändern (bestehende Tests bleiben).

### Task C7: Desktop-Realadapter in der Suite, mit Consent; die vier IKARUS-30-Befunde

**Packet:** G1-IKARUS-40_DESKTOP_LIVE_ACCEPTANCE. Marker `@pytest.mark.desktop_live`, nur mit `DAEDALUS_DESKTOP_LIVE_CONSENT=1` und Owner-Bestätigung im Packet; sonst skipped mit Grund (nicht xfail). Vorher die vier Befunde aus G1-IKARUS-30 schließen (Store-Notepad-Umleitung vs. Image-Pfad, gestrandeter STARTED-Lease bei adapterseitiger Refusal, Pid besitzt Fenster nicht, Fenster-Capture zeigt fremde Tabs) — jeder mit Test. Evidence-Matrix Zeile 2: `real adapter exec` und `crash recovery` von GAP auf R.

### Task C8: Computer-Missionen im Cockpit

**Packet:** G1-UI-16_COMPUTER_MISSION_SURFACE. Zuerst messen: `apps/web/src/features/conversation/commands.ts` ist der einzige Treffer für „computer“ — welche `/computer`-Kommandos existieren im Cockpit, welche nur in der CLI (IKARUS-23)? Dann: Konfigurieren (Policy-Digest sichtbar, **Planner-Wahl mit der Egress-Zeile aus IKARUS-33 vor der ersten Mission**, Widening mit transienter Bestätigung nach §4.1), Mission starten, Observe/Propose/Admit/Act/Verify-Log live (G1-WEB-01 project-scoped events), **Watcher-Status aus IKARUS-35 sichtbar**, Stop = Kill-Switch. Playwright-Spec wie `interactive-rooms.spec.ts`. Kein neuer Scheduler, kein Chat-State als Orchestrierung. Ein Desktop-eigener Watcher ist **nicht** Teil dieses Packets: das ist A4 Zeile 11 und, falls ja, G1-IKARUS-41 (eigene Registry-Zeile, Kill-Switch-Bindung, Heartbeat an den Autoritäts-Root gebunden).

### Task C9: Evidence-Matrix neu messen

**Packet:** Fortschreibung von `docs/evidence/G1-COMPUTER_EVIDENCE_INVENTORY_20260905.md` → `_20260920.md`. Ziel ≥ 60/77 mit Terminal-Zeile (7 Zellen), Document (≥ 4), Desktop (+2), Browser Timeout/Crash (+2), Skills (+3). Jede verbleibende GAP-Zelle mit Packet-ID oder `n/a`-Begründung.

---

## Phase D — Ariadne evolviert

### Task D1: Erster Modell-Operator in der kanonischen Kampagne

**Packet:** G1-ARIADNE-10_MODEL_REPAIR_OPERATOR (ALIGNED; §8 Schritte 3–10, Invariante 4, 5; eine Operator-Achse). **Design-Review:** Momus vor dem Bau, Codex danach.

**Files:**
- Modify: `daedalus/ariadne/campaign.py` (Operator-Achse `repair_variant` bekommt einen zweiten Arm `model_proposed`; `frozen_components` bindet Modell-ID, Prompt-Digest, Transport, `num_ctx`, Seed), `daedalus/ariadne/__main__.py` (`--operator deterministic|model`)
- Create: `daedalus/ariadne/operators.py` (Operator-Vertrag nach §9: akzeptierte Artefakttypen, Twin-Slice, schreibbare Pfade, Budget, Timeout, Preconditions, Kandidaten-Identität, Replay-Inputs)
- Test: `tests/ariadne/test_model_operator.py`

**Interfaces:**
- Consumes: `run_campaign(...)` (bestehend), `shell._ollama(transport="native")` / `run_cancellable` (KERNEL-02, IKARUS-31 nach A3), `codex_cli` Provider.
- Produces: `propose_repair(context_capsule, before, budget) -> RepairProposal(after_text, model_manifest_sha256, prompt_sha256, tokens, seconds)`.

- [ ] **Step 1: Failing test — der Modell-Arm läuft unter demselben Budget wie der deterministische Arm, der Evaluator ist eingefroren, das Modell sieht ihn nicht, ein falscher Vorschlag wird als `failed` retained und nie nominiert**

```python
def test_model_arm_is_budget_equal_frozen_evaluated_and_never_self_nominates(scratch_repo, fake_model):
    fake_model.script(["WRONG TEXT", "right text"])   # Seed 0 falsch, Seed 1 richtig
    receipt = run_campaign(scratch_repo, revision=HEAD, campaign_id="ariadne-10-model-01",
                           target="pkg/mod.py", before="old", after=None, operator="model", timeout_s=120)
    arms = {a.name: a for a in receipt.arms}
    assert arms["model"].budget == arms["deterministic"].budget == arms["negative_control"].budget
    assert receipt.frozen_components["evaluator_sha256"] == EVALUATOR_SHA256
    assert fake_model.saw_paths & {EVALUATOR_SOURCE} == set()          # Kandidat/Modell sieht den Evaluator nie
    assert [t.verdict for t in arms["model"].trials] == ["failed", "passed"]
    assert receipt.nomination.source_arm == "model" and receipt.nomination.applied is False
```

- [ ] **Step 2: Run → FAIL** (`operator=` unbekannt, `after=None` refused).
- [ ] **Step 3:** Operator-Vertrag + Modell-Arm; Context Capsule minimal (Zieldatei-Ausschnitt ± 20 Zeilen, keine Evaluator-Pfade, keine früheren Lösungen — Leakage-Regeln §14); Budget-Gleichheit als Beweis im Receipt wie heute.
- [ ] **Step 4:** Live: ein Lauf mit `qwen2.5-coder:7b` (native Route), ein Lauf mit `codex_cli`; beide Receipts retained, auch wenn rot. Seeds 0–2.
- [ ] **Step 5:** Commit; Registry-Digest des `cli.ariadne_campaign` neu pinnen (ARIADNE-09 hat ihn absichtlich nicht gepinnt).

**Was das voranbringt:** Zum ersten Mal schlägt ein LLM unter dem Trust-Kernel einen Kandidaten vor und ein eingefrorener Evaluator entscheidet — §8 wird von einem Kontrollrahmen zu einer Evolution.

### Task D2: Frozen Task Set und Gate-3-Metriken als Prototyp (EXPERIMENT)

**Packet:** G1-ARIADNE-11_FROZEN_TASKS (EXPERIMENT; bereitet Gate 3 vor, claimt nichts). Zehn eingefrorene Repair-Aufgaben aus zwei Klassen: Docstring-Symbol-Drift (SELF-01-Klasse, Gate `docrefs.resolve_reference`) und Rename-Propagation (Voltage-Klasse, Gate = Ignition-Checks). Für jede: Basis-Revision, `before`, erwartetes Gate-Ergebnis, Budget. Läufe: deterministic vs. model (D1) vs. Random-Best-of-N (Negativ-Baseline), 5 Seeds. Report: Erfolgsrate, best-so-far, Sekunden, Tokens, Varianz — als `docs/experiments/ARIADNE-11/report.md` mit `ExperimentSpec`, Ablauf (`expires_at`) und Kill-Kriterium (§14: „graph-conditioned prioritization does not beat random“ ist hier noch nicht testbar; festgehalten als *nicht gemessen*).

### Task D3: Self-Renovation mit Modell-Operator (nach Amendment 013)

**Packet:** G1-SELF-02_MODEL_SELF_RENOVATION (Klassifikation hängt an A4 #1: nach 013 ALIGNED, sonst EXPERIMENT). Subjekt: Scratch-Clone von Daedalus am Integrations-Commit; Leakage-Regel aus 013 (kein `daedalus/spine`, kein Kernel-Policy, kein Plan, keine Evaluator-Tests) als **Test**, nicht als Prosa: ein Vorschlag, der eine geschützte Datei berührt, wird vor dem Attempt refused. `docrefs.DOC_GLOBS` auf Docstrings zu erweitern ist die Owner-Entscheidung aus SELF-01 (A4 Zeile 9).

---

## Gate-2-Kurs (Owner-Anweisung 2026-09-06 10:09: „sorg dafür das wir Gate 2 erreichen“)

Gate 2 wird erst nach dem Owner-Schluss von Gate 1 aktiv (Plan §11 „Work advances in order“). Zwei Dinge laufen deshalb ab jetzt gleichzeitig: **Phase B ist der kritische Pfad** zum Gate-1-Schluss (B2a → B2b → B3 → B4 → B5 → Owner-Entscheidung), und **Phase E startet sofort als EXPERIMENT** in eigenen Worktrees, damit am Tag des Gate-1-Schlusses die Gate-2-Fundamente schon gemessen sind. Phasen C und D sind Gate-1-*Produkt*-Stränge, die Gate 1 weder schließen noch blockieren; sie laufen nur noch in Peer-Lanes (daedalus-6c) oder nach B/E.

### Gate-2-Exit-Matrix (Plan §11 Gate 2, Bullet für Bullet)

| Gate-2-Bullet | Heute im Baum (gemessen 10:10) | Task | Beweis, den der Owner sehen muss |
| --- | --- | --- | --- |
| function/method resolution | `structcore/graph.py` `SymbolResolver`, `typegraph.py` `resolve`, `imports.py` `resolve_internal` existieren; Aufrufkanten-Auflösung im Code-Plane des Twins unvermessen | **E2** (Messung sofort, Bau danach) | Precision/Recall gegen 30 handverifizierte Kanten auf Fixture + Zweitsubjekt; `resolution_kind` je Kante |
| data/schema extraction | `legacy_forest.py:34-41` projiziert Data-Plane **`absent`**; Sprachregistry kennt csv/json-schema/sql/parquet | **E1** (sofort) | Data-Plane `complete` für Fixture und Zweitsubjekt; verifizierte `data.field → code.attribute`-Bindung |
| knowledge crosslinks | `structcore/markdown.py` löst Wiki-Links (`resolve_wiki_links`); Ignition-Link-Check nutzt sie | **E2** nimmt die Messung mit (Knowledge → Code Kanten zählen) | Anzahl verifizierter Knowledge→Code-Bindungen, Anteil unaufgelöster Links |
| revision atomicity | `contracts.py` bindet `source_revision` an jede `PlaneSnapshot` und jede `CrossPlaneBinding`; `projection_verifier` prüft Forest-Projektion | vorhanden; **E3** beweist es zweimal (Rebuild digest-identisch) | zwei Builds desselben Repos bei derselben Revision → identischer Snapshot-Digest |
| evidence locators | `PlaneSnapshot`/Bindings tragen Locator-Felder (contracts.py) | vorhanden; **E3** prüft, dass jeder Locator auf eine existierende Byte-Range der gepinnten Revision zeigt | Locator-Verifikation als Test über den Corpus |
| four-plane ablations | keine | **E4** | Vier-Ebenen vs Code-only vs BM25 vs randomisierte Cross-Plane-Kanten auf der WorkItem-Ableitung; Kill-Kriterien §14 explizit geprüft |
| small license-audited, temporally pinned corpus | keiner (`docs/corpus/` existiert nicht) | **E3** (nach B4) | drei Repos mit `PROVENANCE.md` (Lizenz-Digest, Revision, Cutoff, Extraktor-Versionen), Negativbeispiele retained |
| deterministic Twin rebuilding | Replay des Ignition-Fixtures digest-identisch (WP-01) | **E3** verallgemeinert auf den Corpus | Test: Rebuild × 2 identisch pro Repo |
| cross-repository alignment | nichts | **E5** (neu, nach E3) | Alignment zweier Twins auf typisierten Knoten (gleiche Signatur/gleicher Schema-Feldname) mit Score und Rationale; ausschließlich Vorschläge, verifiziert oder verfallen (§6) |
| motif provenance | nichts | **E5** | ein Motiv (z. B. „CSV-Schema-Feld ↔ Modellattribut ↔ Wiki-Erklärung“) mit Quell-Repos, Revisionen, Lizenzen, Cutoff, Stützsubgraph, Negativbeispiel (§9.1) |
| „do not scale before the full graph beats simpler representations“ | — | **E4** liefert die Zahl | Ablation zeigt Vier-Ebenen > Code-only und > BM25, sonst Kill-Kriterium 1 → Amendment-Vorlage |

### Reihenfolge ab 10:10 (Fleet-Zuordnung 11:03 nachgetragen)

Owner-Auftrag an die Fleet-Session daedalus-35 (10:20): 30 Opus-Agenten in eigenen Worktrees (`fleet/*`), Integration durch die Fleet nach A3-Merge-Commit und Amendment-013-Commit. Damit sind folgende Tasks dieses Plans **fleet-owned** (Packet-IDs identisch, nichts doppelt bauen): C3 = s01 (G1-IKARUS-37 terminal.run), C5 = s02 (IKARUS-28 Phase 1 + IKARUS-38 document.read), C6 = s03 (IKARUS-39), C4 = s04 (IKARUS-27 D1+D2) + s20 (G1-KERNEL-03 finish_effect-Liveness), C7 = s05 (IKARUS-40), C9 = s06 (Matrix 20260906), D1 = s07 (G1-ARIADNE-10), D2 = s08 (G1-ARIADNE-11), D3 = s09 (G1-SELF-02 Leakage-Test), E3-Vorarbeit = s12 (G2-CORPUS-01 Seed-Vertrag, lokale Subjekte, `CANDIDATES_20260906.md` Lizenz-Audit), E4 = s13 (G2-ABLATION-01), F1 = s14 (G1-HW-02), A4 #8 = s16 (Reap-Tür), Genesis-Backlog = s18/s19, plus s10 G2-KNOW-01 Knowledge-Crosslinks und s11 G2-REV-01 Revisions-Atomizität (neue Gate-2-Zeilen, nur neue Dateien). Diese Session übernimmt die Fleet-Branches als Eingabe (Review, Übernahme oder Verwerfen) statt sie selbst zu bauen.

| Spur | jetzt | danach |
| --- | --- | --- |
| Gate-1-Schluss (kritisch, diese Session) | A3-Merge committen, A2-Fix, B2a (4 Commits auf `g1/renovation-02a`) | B2b → B3 → B4 (Subjekt aus s12-Audit) → B5 → Owner-Vorlage |
| Gate-2-Fundament (diese Session) | E1 Data-Plane, E2 Messung | E2 Bau, E5 Alignment/Motiv; E3/E4 = Review von fleet/s12, fleet/s13 |
| Fleet (daedalus-35) | s01–s20 Support, d01–d10 Docs | Rebase auf den A3-Merge-Commit, Suite dort, dann Integration |
| Peer-Lanes | daedalus-31 (vorher 6c/9d): Ikarus 42–44, lane11-Rebase | — |

### Task E5: Cross-Repository-Alignment und ein Motiv mit Provenienz (EXPERIMENT)

**Packet:** G2-ATLAS-01_ALIGNMENT_AND_FIRST_MOTIF (EXPERIMENT; §6, §9.1). Abhängig von E3. Alignment = Kandidatenpaare typisierter Knoten über zwei Twins (gleiche Signatur, gleicher Schema-Feldname, gleicher Wiki-Titel) mit Score, Rationale und Ablaufdatum; Verifier prüft Quellenevidenz und Revisionskompatibilität, bevor ein Paar `verified` wird. Ein Motiv: der abstrahierte Subgraph „Schema-Feld ↔ Modellattribut ↔ Dokumentation“, mit Quell-Repos, Revisionen, Lizenzen, Cutoff, Stützsubgraphen und einem Negativbeispiel (ein Repo, in dem das Muster fehlt). Failing test zuerst: `test_alignment_proposals_never_enter_bindings_unverified` (ein unverifiziertes Alignment-Paar darf in keinem `FourfoldSnapshot.bindings` auftauchen).

## Phase E — Gate-2-Fundament (EXPERIMENT-gelabelt, kein konkurrierender Kernel)

### Task E1: Data-Plane `complete` für das Ignition-Fixture

**Packet:** G2-DATA-01_CSV_SCHEMA_PLANE (EXPERIMENT bis Gate 1 schließt; danach ALIGNED). Heute: `legacy_forest.py` projiziert Data-Plane `absent`. Ziel: CSV-Kopfzeilen und JSON-Schema-Felder werden Data-Plane-Knoten mit Provenienz (Datei, Zeile/Pfad, Extraktor-Version); Cross-Plane-Kante `data.field -> code.attribute` nur, wenn beide Endpunkte existieren und ein Verifier die Bindung bestätigt (§6).

**Files:** Create `daedalus/twin/extractors/data_plane_adapter.py`; Modify `daedalus/twin/legacy_forest.py` (Status `complete`, wenn der Adapter alle Data-Sprachdateien verarbeitet hat, sonst `partial` mit Gründen); Test `tests/twin/test_data_plane_adapter.py`.

- [ ] **Step 1: Failing test**

```python
def test_ignition_fixture_data_plane_is_complete_and_binds_fields_to_code(ignition_fixture):
    snap = compile_reference_project(ignition_fixture, source_revision="1" * 40)
    data = snap.plane("data")
    assert data.status == "complete"
    assert {n.name for n in data.nodes if n.kind == "field"} >= {"voltage", "event_id"}
    binding = [b for b in snap.bindings if b.source_plane == "data" and b.target_plane == "code" and b.name == "voltage"]
    assert binding and binding[0].verified_by == "data-code-field-attribute-verifier/1"
```

- [ ] **Step 2–4:** rot → Adapter (csv-Modul, json für Schema) → grün; der Ignition-Receipt bekommt Data-Plane-Delta-Zahlen (heute nur Code/Knowledge); Byte-Pin für neue Bundle-Closure-Dateien.

**Was das voranbringt:** Eine der vier Planes ist im Twin heute leer. Ohne sie ist die Vier-Ebenen-Prior (§5) nicht einmal ablatierbar.

### Task E2: Function/Method-Resolution im Code-Plane messen und schließen

**Packet:** G2-CODE-01_CALL_RESOLUTION (EXPERIMENT). Zuerst messen: Wie viele Aufrufkanten löst der Tree-sitter-Adapter im Ignition-Fixture und im B4-Subjekt auf (Precision/Recall gegen eine handverifizierte Liste von 30 Kanten)? Dann: intra-modulare und import-folgende Auflösung für Python; Kanten tragen `resolution_kind: local|import|unresolved`, nie geraten. Kill-Check: Wenn Resolution die Rename-WorkItems in B4 nicht besser ableitet als Textsuche, ist das eine retained Negativ-Evidenz für §14.

### Task E3: Corpus-Seed — drei Repos, deterministischer Rebuild

**Packet:** G2-CORPUS-01_SEED (EXPERIMENT). B4-Subjekt plus zwei weitere (A4 #7). Je Repo: `docs/corpus/<repo>/PROVENANCE.md` (Lizenz, Revision, Cutoff, Extraktor-Versionen), Twin zweimal gebaut → Digest identisch (Test), negative Beispiele retained (ein absichtlich falscher Cross-Plane-Vorschlag, vom Verifier abgelehnt). Kein Skalieren vor dem Beweis „full graph beats simpler representations“ (§11 Gate 2).

### Task E4: Erste Ablation — vier Ebenen vs. Code-only vs. BM25

**Packet:** G2-ABLATION-01 (EXPERIMENT, pre-registriert). Aufgabe: „Welche Dateien muss ein Rename berühren?“ auf den drei Corpus-Repos + Fixture. Bedingungen: Vier-Ebenen-Twin mit verifizierten Cross-Plane-Kanten; Code-only; BM25 über Dateien; Kontrollen: Cross-Plane-Kanten randomisiert (degree-preserving), Ebenen einzeln entfernt. Metrik: Precision/Recall der WorkItem-Pfadmenge. Budget gleich (keine Modellaufrufe, also deterministisch). Ergebnis ehrlich: fällt Kill-Kriterium 1 oder 2 (§14), ist das die erste evidenzbasierte Amendment-Vorlage, kein stiller Weiterbau.

**Was das voranbringt:** Der Plan nennt die Vier-Ebenen-Prior „god-key candidate, not dogma“. Bis heute hat niemand sie gegen BM25 gemessen. Das ist die billigste Falsifikation, die das Repo anbieten kann.

---

## Phase F — Hardware (nach Amendment 013)

### Task F1: KiCad real — `kicad-cli erc/drc` als deterministische Evaluatoren

**Packet:** G1-HW-02_KICAD_REAL_EVIDENCE. Voraussetzung: KiCad 9 auf dem Host (Owner installiert; `kicad-cli --version` gemessen ins Packet). G1-HW-01 (148 Tests, effektfrei) bekommt: Format-Konstanten gegen echte Dateien verifiziert (im Packet als unverifiziert markiert), `pcb inspect` gegen ein reales Beispielprojekt, `erc`/`drc` als Gate mit `blocked_external`, wenn der Binary fehlt. Symbol-/Footprint-Provenienz (Lizenz, Version) als Pflichtfeld des Manifests.

### Task F2: Vivado/Vitis bleibt `blocked_external` — dokumentiert, nicht simuliert

Kein Bau ohne Toolchain. G1-EDA-HOST-STATUS-02 offene Fragen (b, c: `create_project`-Zweig, `--target vitis-hls` Unterkommando) als Owner-Zeilen in A4 nachtragen; keine Emulation eines Vendor-Tools.

---

## Phase G — Laufende Hygiene (jede Lane, jeder Commit)

- Registry-Zeile für jede neue Tür, Digest-Pins neu messen, `tools/index_work_packets.py --render` einmal pro Batch.
- `.gitattributes`-Pin für jede Datei, die in die Bundle-Closure rutscht (der Ignition-Test sagt, welche).
- Wiki-Regeneration (`daedalus.wiki plan/verify`, Treewalk prunt Bundles) nach strukturellen Änderungen; Findings nach `runs/wiki_findings_*.md`.
- Vault-Sync am Session-Ende; Gate-Status-Journal nur mit `[MEASURED]`-Zahlen.
- Room-Ansage vor jeder Lane; Peer-Adressen nach Restarts über den Room, nicht über gecachte Pipes.

---

## Reihenfolge und Parallelität (Empfehlung)

| Woche | Serielle Spur | Parallel-Lanes (disjunkte Dateien) |
| --- | --- | --- |
| 1 | A1 → A2 → A4 (Owner-Runde) → A3 → A5 | C1 (Peer 9d, läuft), B1 (Evidence-only, sofort), E2-Messteil (read-only) |
| 2 | B2 → B3 | C2, C4-D1/D2, D1 (nach A3), E1 |
| 3 | B4 → B5 (Review, Owner-Vorlage) | C3 (Cerberus-Runde), C5, D2, E3 |
| 4 | Owner-Entscheidung Gate-1-Renovation-Klausel | C6, C7, C8, E4, F1 (falls 013 + KiCad) |
| 5 | C9 (Matrix), D3 (falls 013) | Wiki/Vault/Registry-Hygiene, Gardener-PR rebasen |

Jede Zeile endet mit einem gemessenen Zustand (Suite, Receipt oder Evidence-Datei), nie mit einer Behauptung.

---

## Self-Review (writing-plans-Skill)

**Spec coverage.** Plan §11 Gate 1: Renovation-Klausel → B1–B5; Genesis-Strang → keine neue Task (drei Packets gelandet, Rehearsal live; konversationelle Folge-Revisionen bleiben Backlog, bewusst nicht vor Renovation priorisiert); Computer-Strang §7.2 (file, application, terminal, browser, document, integration, scheduled) → C3 Terminal, C5 Document, C7 Application; **Integration/Connectors** bleibt ohne Task — Capability-Map rankt es als größtes neues Trust-Surface zuletzt, und §7.2 verlangt dafür ein eigenes Packet mit Owner-Autorisierung (bewusste Lücke, nicht vergessen). §8 → D1/D2. §11 Gate 2 → E1–E4 als EXPERIMENT. §7.3/013 → F1/F2 nach A4. §10 Baseline/Review-Kette → A1, B5.

**Placeholder scan.** Keine „TBD“; Signaturen wie `run_gate1`, `resume_gate1`, `derive_work_items`, `propose_repair`, `WorkspaceTerminal` sind in ihren Tasks definiert; bestehende Helfer (`_prepare_target`, `_parsed_workflows`) sind mit „bestehender Helfer“ markiert und beim Öffnen des Packets zu verifizieren.

**Type consistency.** `IgnitionReceipt.replay.resumed_from_event_seq` (B2) ↔ `receipt.replay` (B1 liest es); `WorkspaceFiles.read_bytes` (C5) ↔ Bytes-Seam für `document.read` (C5) und Terminal-cwd (C3); `run_campaign(operator=...)` (D1) ↔ D2/D3 nutzen dieselbe Signatur.

**Bewusste Nicht-Ziele.** Kein Messaging-Gateway, kein Container-Sandbox-Neubau, kein POSIX-Lift, kein Corpus-Scaling, kein „beats AlphaEvolve“-Satz, keine Änderung an Plan/Amendment-Kette/`AGENTS.md`.

`Iron Plan: ALIGNED` (Phase E, D2 und die Hardware-Tasks als `EXPERIMENT` gelabelt; A4 #1 ist eine `AMENDMENT`-Owner-Entscheidung, die dieser Plan nur vorlegt)
`Iron Gate: 1`
`Evidence: Standaufnahme Teil 1 mit [M]/[I]/[A]-Provenienz; keine Codeänderung durch dieses Dokument`

# Agent-Koordination — das Board für alle Lanes in diesem Repository

Owner-Auftrag 2026-09-10 („mach eine Agent-Koordinations-MD, mit der du dich
mit denen koordinierst“). Dieses Dokument ist die **eine** Stelle, an der jede
Lane — Claude-Sessions, Codex-Lanes, der Fleet-Workflow, Ikarus selbst —
sagt, woran sie arbeitet, welche Dateien sie besitzt und was sie von den
anderen braucht. Es ist ein Board, keine Autorität: der Masterplan
(`docs/IKARUS_ARIADNE_MASTER_PLAN.md`) entscheidet Semantik, `AGENTS.md` das
Verhalten, Tests und Receipts die Wahrheit. Wer hier nicht eingetragen ist,
hat trotzdem keine Rechte weniger — und wer eingetragen ist, keine mehr.

Lebende Kopie: `docs/AGENT_COORDINATION.md` im **Primär-Checkout**
(`C:\Users\Administrator\Desktop\projects\daedalus`). Ein Worktree liest die
Fassung seines Branches; bei Konflikt gilt die Fassung im Primär-Checkout, weil
nur die alle Lanes sehen. Wer sie ändert, ändert nur seinen eigenen Block und
den Nachrichten-Anhang.

## Protokoll

1. **Eintragen, bevor du schreibst.** Ein Block unter „Aktive Lanes“ mit
   Lane-Name, Branch, Worktree, Packet-ID, **exakt** den Pfaden, die du
   änderst, und den Pfaden, die du bewusst nicht anfasst. Kein Eintrag = die
   anderen dürfen annehmen, dass die Datei frei ist.
2. **Disjunkte Datei-Ownership oder getrennter Worktree.** Zwei Lanes im selben
   Checkout auf derselben Datei ist der Fehler, den dieses Board verhindert.
   Der Primär-Checkout gehört niemandem: dort werden Dateien nur gelesen,
   Session-Notizen (`vault/Sessions/`) und dieses Board geschrieben. Kein
   `git add -A`, kein `git checkout --`, kein Branch-Wechsel im Primär-Checkout
   durch eine Lane, die dort nicht eingetragen ist.
3. **Herzschlag.** Ein Zeitstempel im eigenen Block bei jedem materiellen
   Schritt (Commit, Push, PR, Review-Ergebnis). Ein Block ohne Herzschlag seit
   >6 h gilt als verwaist: die Dateien sind frei, der Block wandert nach
   „Abgeschlossen / verwaist“ mit dem Vermerk, wer ihn geschlossen hat.
4. **Nachrichten statt Vermutungen.** Wer etwas von einer anderen Lane braucht
   (Merge, Freeze, Datei freigeben, Owner-Entscheidung), schreibt es datiert in
   den Anhang „Nachrichten“ und in seinen Block unter „Braucht“. Antworten
   ebenfalls datiert. Nichts wird gelöscht; Erledigtes wird als erledigt
   markiert.
5. **Owner-Entscheidungen** stehen unter „Offene Owner-Entscheidungen“ mit dem
   Satz, der die Entscheidung wäre. Der Owner antwortet im Chat; die Lane, die
   die Antwort erhält, trägt sie hier mit Datum ein.
6. **Fallen, die alle betreffen**, stehen unten und werden ergänzt, nie
   umgeschrieben (Provenienz: MEASURED mit Datum).

## Aktive Lanes

### Lane `claude-jarvis` — Ikarus als SuperAgent-Interface (Claude-Session, gestartet 2026-09-10 11:38)

- Branch `packet/g1-ikarus-46-daedalus-tools-20260910`, Worktree
  `.claude/worktrees/jarvis-20260910`, PR #364 (Draft bis Review-Runde 2 grün).
- Packet **G1-IKARUS-46** (Act-Verben, natürlichsprachlicher Weg in den
  Computer-Loop, read-only `daedalus.*`-Werkzeuge). Folgepakete in dieser
  Reihenfolge: **G1-IKARUS-47** (Genesis-Angebot `genesis_build` und
  `daedalus.ariadne_campaign`-Werkzeug, nominierend), **G1-IKARUS-37**
  (`terminal.run` mit Argv-Allowlist), **G1-SELF-02** (Modell-Operator).
- Owner-Richtung 2026-09-10 13:22, wörtlich: „und wenn Daedalus/Ikarus sich
  selbst verbessern kann, package das neu und arbeite über den Daedalus
  Kernel“ — nach 47 folgt ein Release-Packet (Desktop-Build mit dem
  SuperAgent-Chat) und danach laufen weitere Packets **durch** Ikarus
  (Computer-Loop + Ariadne), nicht mehr nur durch Claude-Code-Sessions.
  Promotion bleibt versiegelt (Invariante 5): Kandidaten werden nominiert,
  der Owner wendet an.
- Besitzt (nur im eigenen Worktree): `daedalus/orchestration/ikarus/{act,shell,computer_loop}.py`,
  `daedalus/runtimes/{computer,computer_daedalus}.py`,
  `daedalus/kernel/policy/computer.py`, `apps/web/src/features/conversation/*`,
  `apps/web/src/shared/contracts/index.ts`, `tests/test_ikarus_*.py`,
  `tests/runtimes/test_computer_*.py`, `docs/IKARUS_COMPUTER.md`,
  `docs/work-packets/G1-IKARUS-46_*`, `docs/evidence/G1-IKARUS-46/`, die
  Pins (`tests/contracts/test_import_scc_hierarchy.py`,
  `tests/contracts/test_work_packet_index.py`, `experiments/forest_v2/s02_types/test_external_corpora.py`).
- Fasst nicht an: `daedalus/spine/`, `daedalus/kernel/` außer
  `policy/computer.py`, `daedalus/ariadne/`, Plan, Amendment-Kette, `AGENTS.md`,
  die Desktop-Packaging-Dateien der Codex-Lane, den Primär-Checkout.
- Braucht: Owner-Merge von #364 nach Review-Runde 2; Owner:
  `~/.codex/config.toml` (`gpt-6-astra`) passt nicht zur codex-cli 0.152.0
  (Codex-Planner blockiert, MEASURED 2026-09-10); Owner: lokaler `main` ist
  238 Commits hinter `origin/main` (`git merge --ff-only origin/main` im
  Primär-Checkout, dann App neu starten).
- Herzschlag: 2026-09-10 14:50 — Commit 4 (Reparaturen aus Cerberus Runde 3
  C1/H1/H2 und Odysseus Runde 3 D4–D8: Egress nach Host-Lane statt
  Provider-Name, `ignore_patterns` gefiltert, `withheld`-Zeilen nur noch
  Rolle+Regel, Regel-Marker geschwärzt, verschachtelte Strings gefiltert,
  36 Pfad-Schreibweisen) wird gepusht. Sechzehn Suiten 476 grün, s02-Pin
  auf 7145/47482/94.35 nachgezogen, Mutationstabelle 33/33 gefangen
  (`mutation-table-6.txt`), 0 CR-Bytes. Danach Cerberus Runde 4 und Odysseus
  Runde 4; PR #364 bleibt Draft bis Cerberus `approve`.
- Herzschlag: 2026-09-10 15:22 — Runde 4 (`a90b61a6`): Cerberus `needs_fix`,
  Block aufgehoben, kein CRITICAL, neu H3 (erklärter Tailnet-Host „verlässt
  nichts“) und H4 (Mehrdeutigkeits-Verweigerung zählt rohe Pfade auf);
  Odysseus D9 (echte Regelstrings tragen Pfad + Fragment), D10 (Status filtert
  nur str), D11–D13. Alles in Commit 5 repariert: Verlassen = Physik
  (`is_loopback_host`), Lane = Konsens; Regel → feste Klasse, Withheld-Block
  neu gebaut; jeder Wert über alle Strings gefiltert; `*_elided`. Siebzehn
  Suiten 646 grün, Mutationstabelle 40/40, s02-Pin 7150/47512/0.1119, 0 CR.
  Commit 5 wird gepusht; danach Cerberus/Odysseus Runde 5. Owner-Richtung
  15:05 („brute force … als Skill … völlig autonom“): Reihenfolge 47 → 37 →
  Skill `daedalus-jarvis`; Karte der Anschlussstellen liegt vor (Ariadne
  `run_campaign` als Python-API, `POST /api/genesis`, kein `terminal.run`,
  kein Chat-Genesis-Intent, keine Code-Durchsetzung von „irreversibel“).

### Lane `codex-desktop` — Desktop-Packaging (Codex, direkt im Primär-Checkout)

- Dirty im Primär-Checkout seit 2026-09-08: `.gitignore`, `apps/web/dist/**`,
  `apps/web/src-tauri/Cargo.toml`, `tests/test_desktop_packaging.py`,
  `tests/test_desktop_runtime.py`; Packet
  `docs/work-packets/G1-DESKTOP-LOCAL-BUILD-REPAIR-20260908.md` (untracked).
- Eintrag von `claude-jarvis` aus Beobachtung (INHERITED, Session-Notiz
  2026-09-08); die Lane selbst hat sich nicht eingetragen. Bitte
  eigenen Block pflegen oder die Dateien freigeben.

### Lane `tensor` — `exp/tensor-kernel-contract-01` (PR #363, EXPERIMENT)

- Worktree `C:\Users\Administrator\AppData\Local\Temp\dd-tensor`
  (`integrate/tensor-gpu-130`). Eigene Dateien unter `daedalus/tensor*`,
  `docs/work-packets/G1-EXP-TENSOR-GPU-*`. Kein Kontakt zu den Ikarus-Pfaden.
  Eintrag aus Beobachtung; bitte selbst pflegen.

### Lane `g3-mint` — `packet/g3-mint-corpus` (PR #362)

- Worktree `C:\Users\Administrator\Desktop\projects\dd-corp`. Gate-3-Korpus;
  kein Kontakt zu den Ikarus-Pfaden. Eintrag aus Beobachtung; bitte selbst
  pflegen.

## Offene Owner-Entscheidungen

- [ ] Merge PR #364 (G1-IKARUS-46) nach Review-Runde 2 (Cerberus/Odysseus).
- [ ] Merge PRs #362, #363 (fremde Lanes).
- [ ] Seal-Entscheidung (G3-SEAL-01/02): darf der einzige Allowed-Signer auch
      `seal/<manifest_sha>`-Tags autorisieren? (offen seit 2026-09-08)
- [ ] Codex-Planner: `~/.codex/config.toml`-Modell an codex-cli angleichen
      oder CLI aktualisieren. MEASURED 2026-09-10 14:55: `codex exec -m gpt-5.5`
      wird von codex-cli 0.152.0 mit ChatGPT-Login akzeptiert (`gpt-5-codex`,
      `gpt-5.3-codex`, `gpt-5.4`, `gpt-6`, `gpt-6-codex` nicht), aber das
      Konto meldet „usage limit … try again at Sep 15th, 2026 7:31 AM“ — bis
      dahin gibt es weder Codex-Planner noch Codex-Zweitmeinung (`council`),
      unabhängig von der Konfiguration.
- [ ] Lokalen `main` im Primär-Checkout auf `origin/main` vorspulen und die
      Desktop-App neu starten.

## Fallen, die alle betreffen (MEASURED, Datum)

- Ein Bash-Argument mit führendem `/` (`/computer …`) wird von MSYS zu
  `C:/Program Files/Git/computer …` und landet in der bezahlten Voice —
  `MSYS2_ARG_CONV_EXCL='*'` voranstellen (2026-09-10).
- `Path.write_text` unter Windows schreibt CRLF: die `-text`-gepinnten Module
  (`.gitattributes`, u. a. `shell.py`, `computer_loop.py`, `act.py`,
  `runtimes/computer.py`) nur mit `read_bytes`/`write_bytes` anfassen und vor
  dem Commit `grep -c $'\r'` = 0 prüfen (2026-09-10, Odysseus Defekt 6).
- Ein persistierter `cd` in einen Worktree schaltet das Edit-Werkzeug ab
  („Not logged into Semgrep Guardian“): Bash-cwd im Primär-Checkout lassen,
  Worktree-Dateien absolut adressieren (2026-09-03).
- `tools/index_work_packets.py` und der SCC-Zensus lesen `git ls-files`: neue
  Dateien erst stagen, dann messen (2026-09-06/10).
- Ein Reviewer-Agent, der in einem Worktree misst, während eine andere Lane
  dort schreibt, misst Mischzustände — Odysseus hat deshalb gegen eine
  `git archive`-Kopie gemessen (2026-09-10). Wer reviewt, sagt es hier vorher;
  wer schreibt, wartet oder friert ein.
- Scratch-Ledger und Scratch-Spine pro Lauf (`DAEDALUS_BUDGET_LEDGER`,
  `DAEDALUS_SPINE_DB`), nie `runs/budget/ledger.json` des Owners (2026-09-08).

## Abgeschlossen / verwaist

- (leer)

## Nachrichten (append-only, datiert)

- 2026-09-10 13:52 `claude-jarvis` → Reviewer `odysseus-46-round2`: ich
  schreibe ab jetzt wieder in den Worktree (Cerberus-Runde-2-Befunde N1–N8);
  deine Messungen bis 13:52 gelten für `96e190d2`, danach gegen eine
  `git archive`-Kopie messen.

- 2026-09-10 13:25 `claude-jarvis` → `codex-desktop`: eure fünf dirty
  Dateien im Primär-Checkout liegen unangetastet; ich arbeite ausschließlich
  im Worktree `jarvis-20260910`. Wenn ihr `apps/web/src/features/conversation/*`
  braucht: nicht anfassen, bis #364 gemerged ist — dort liegt der
  `computer_task`-Vertrag.
- 2026-09-10 13:25 `claude-jarvis` → alle: `docs/IKARUS_COMPUTER.md`,
  `vault/Home.md`, `vault/Gates/Gate-Status.md` im Primär-Checkout wurden von
  meinem Doku-Delegaten (Mnemosyne) berührt; die `IKARUS_COMPUTER.md`-Änderung
  habe ich dort zurückgenommen (sie gehört auf meinen Branch), die zwei
  Vault-Notizen bleiben als Session-Protokoll stehen.

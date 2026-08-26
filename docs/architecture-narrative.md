# Daedalus — architecture narrative

THE HAND-WRITTEN HALF OF THE ARCHITECTURE MAP. `daedalus map` reads this file
and renders it beside the generated tables; it never writes here. Nothing in
this file is derived, and no scanner claims to derive it — that is the point
of keeping it separate. Edit it by hand; regeneration cannot eat it.

Each `##` heading carries an explicit `{#key}` so the renderer addresses the
section by key rather than by wording. Retitle or rewrite freely; keep the key.
A section that disappears from this file renders as ABSENT on the page, not as
nothing.

PROVENANCE. Everything below was MOVED, not written: it is the narrative half
of the ad-hoc `docs/architecture-map.html` built on 2026-07-28 from a nine-agent
deep read (preserved verbatim at `docs/architecture-map.2026-07-28-handbuilt.html`).
The per-section `Source` lines say where each part came from and which documents
the readers were citing. Where the prose is German it is the original wording,
kept unedited.

## Der Stand — the one-paragraph state {#state}

> Daedalus is a working, single-machine, CLI-first delegation harness — it routes a coding task to a free local/cheap model behind a genuinely fail-closed safety core (egress floor, import-graph blast-radius fence, on-disk write verification, rollback) and can distill a repo into a certified context slice — wrapped in a React cockpit and an honest written record; the "Agent OS" above it (persistent missions, an Architect that decomposes and integrates, per-project kitchens, OS-level candidate isolation, certified memory) is specification and scaffolding, not running code.

Source: `docs/architecture-map.html` header, 2026-07-28 nine-agent read.

## Wie man diese Karte liest {#reading}

Der einzige Zweck dieses Dokuments ist, für jede Sache beantwortbar zu machen, ob sie tatsächlich läuft. Diese Unterscheidung ist das ganze Produkt: eine Spezifikation, die wie Code aussieht, hat dieses Projekt schon Tage gekostet. Neun Leser haben je ein Gebiet durchgearbeitet und 827 Einträge belegt — jeder mit Pfad, Aufrufer und Status.

The nine status words this map uses — wired, dark, island, shim, baseline,
stale, spec-only, broken, unknown — are defined on the generated page itself
and in `daedalus/mapping/render.py:STATUS_VOCAB`, which is the single copy.

Source: `docs/architecture-map.html` §“Wie man diese Karte liest”.

## Die Küche — roles and their real counterparts {#kitchen}

Das Zielbild ist eine Restaurantküche: Du sprichst mit dem Kellner, der bestellt beim Chefkoch, der verteilt an Küchen mit eigenen Mini-Chefs und Arbeitern. Hier steht, welche Rolle heute welchen echten Gegenpart hat — und welche keinen.

| Rolle | Soll | Existiert heute als | Status heute |
| --- | --- | --- | --- |
| **The guest (human operator)** | Speaks in natural language, never touches a lane, a provider, or a path. | `apps/web/src/cockpit/ (the themed cockpit `/` opens: stage + conversation + decision) and apps/web/src/App.tsx (the classic surface at ?surface=classic); daedalus/cli.py for the operator path.` | wired — but the honest shape is inverted. The 29-subcommand CLI is the real surface and the chat is the thin one; every capability that matters (offload, improve, dctx, council, canary, eval) is CLI-only and unreachable from the cockpit. |
| **Ikarus, the waiter — personality, dialogue, memory, NO tool authority** | Holds the conversation and the user's personal memory, understands intent, explains, asks, and hands a typed mission onward. Never writes, never spends unlogged. | `daedalus/ikarus_os.py (ask/ask_stream, selectable brain across ollama/deepseek/codex) + daedalus/ikarus_chat.py (network designer) + daedalus/memory/__init__.py (operational journal).` | wired but hollow, and correct about its own limits. The no-tool-authority rule IS honoured structurally: STATUS and DISTILL are computed locally with no spend and no egress, and ENQUEUE only PROPOSES a confirm-gated task that must still funnel through core.process_bridge_payload. What does not exist is the waiter's memory or personality: ADR-006 deliberately selects NO backing system for personal memory, there is no consent/retention model, no Autonomy Envelope object anywhere in daedalus/ (invariant I7 is pure specification), and the persona is a prompt, not a component. The journal it writes to is the one store ADR-011 §2 explicitly demotes to 'not load-bearing; no receipt may cite it'. |
| **The ticket — a typed mission handed from waiter to kitchen** | A durable, named object: objective, scope, budget, policy, acceptance criteria, state, and a receipt trail. | `nothing. daedalus/schemas.py has AgentTask/AgentReport dataclasses (a per-call envelope, not a mission), and daedalus/spine/ledger.py records an intent_id per ATTEMPT.` | planned. There is no MissionSpec, no daedalus/missions/, no durable mission state machine, no crash recovery at the mission level — master plan §3.2 and bypasses.md §4 both say so. It was DEFERRED on purpose (Momus told the team to defer leases/heartbeats until a multi-worker deployment exists), which is a defensible call, but it means the ticket the kitchen metaphor depends on has no type. ADR-011 §4 specifies the cross-store receipt join that would make one; nothing writes it. |
| **The Architect / head chef — decomposes, schedules, integrates** | Takes one mission, breaks it into a dependency graph of subtasks, allocates them across kitchens and runtimes, then INTEGRATES the returned work into one coherent result. | `daedalus/kairos/scheduler.py:72 (KairosScheduler) + daedalus/kairos/decompose.py:143 + daedalus/build.py.` | partial, and the missing half is the important half. DECOMPOSE exists (a local model splits an objective, with a deterministic one-subtask-per-path fallback that never raises). SCHEDULE exists as a bounded batch dispatcher — but it is not a DAG: there are no dependencies, no topological order, no artifact contract between subtasks, and any write in the batch collapses the whole thing to sequential. INTEGRATE DOES NOT EXIST AT ALL. Nothing merges, reconciles, or composes the outputs of several subtasks; results are appended to a list. `daedalus build` plans multi-wave sessions and by design never executes a wave. The Architect is, today, a fan-out with no fan-in. |
| **Per-project persistent kitchen — a long-lived workspace with its own mini-chef** | Each project keeps a warm, stateful workspace: its own context, its own crew, its own memory of what it has already done, surviving across missions. | `projects/*.json + daedalus/config.py (per-repo .agentenv/agentenv.json) for CONFIGURATION; daedalus/structcore cached_index + the sqlite per-file cache for warm CONTEXT; daedalus/kairos/worktree.py for a DISPOSABLE workspace.` | planned as described; what exists is per-project configuration plus a warm cache, not a persistent kitchen. Every execution workspace is created and destroyed inside one attempt (TaskAttempt cleans up in a `finally:`). There is no per-project agent state, no standing crew, no accumulated project memory — the four things a 'kitchen' would need. The nearest real per-project persistence is the structcore index cache and projects/*.json center/ignore scoping, which is genuinely valuable (6,798→187 files measured) but is a context cache, not a workspace. |
| **The mini-chef — a per-kitchen dispatcher that owns its project** | A resident agent per project that knows that codebase, assigns its own workers, and answers to the Architect. | `nothing.` | planned. There is no per-project agent object of any kind. agents/*.json and .agentenv/agents/ define ROLES (keyword/path scoring inputs for the router), not resident agents. The closest structural analogue is daedalus/hierarchy.py's team projection, which is a read/save shape for the UI, not an actor. |
| **The line cooks — workers that do the actual editing** | Sandboxed workers that receive a scoped task and produce a change. | `daedalus/providers/ollama.py (the only one that writes), codex_cli.py, deepseek.py, claude_cli.py, plus daedalus/adapters/subprocess_adapter.py for agentic CLIs.` | wired, with sharp limits worth knowing before trusting them. Ollama is the only provider that writes the checkout and the only one with rollback(); everything else is advisory by enforcement, not by policy. The 7B model does not emit tool calls, so the HARNESS writes the file from returned content, gated on identical/truncation/elision checks. codex_cli passes a multi-line prompt as an argv element while the repo's own measured rule (and four other call sites) say it must go on stdin — an unresolved contradiction. The adapters lane, which is the general 'any agentic CLI' worker, is an island: nothing routes to it, and its termination path kills only the immediate child on a platform where that is measured not to work. |
| **The pass / expo — gates the food crosses before it reaches the guest** | Nothing leaves the kitchen without passing an independent check, and a failed check is undone. | `daedalus/verifier.py:147 + offload's snapshot/diff/rollback + daedalus/spine/attempt.py pytest_gate + daedalus/sensitivity.py egress gates + daedalus/kairos/drafts.py.` | wired, and the single best-built role in the metaphor. The verifier checks report schema, compiles, lints (JS half real, Python half currently inert), parses JSON/YAML, tripwires truncated HTML, and can run a project test suite; did_work can ONLY be satisfied by the disk diff when supplied. A failed gate triggers a real rollback with unreverted paths named as dirty_unreverted. Advisory output goes to a drafts inbox where `apply` prints a review packet and merges nothing. THE GAP: the gates judge one task's output; nothing gates the INTEGRATION of several, because integration does not exist. And promotion — the step that would move a passing Lane-B patch into the checkout — is deliberately absent everywhere by design. |
| **The waiter's notebook — memory that makes the next visit better** | The system remembers what it did, what worked, and what the user prefers, and can prove it. | `daedalus/memory/__init__.py (journal, live) + daedalus/memstore.py (removed 2026-08-22) (dmem/1 certified ledger, built and dead) + daedalus/memory/embeddings.py (vector projection, no rows).` | broken as a whole, honest in each part. The only live store is the unchained, unlocked journal whose records carry no id — the projection layer has to SYNTHESIZE one as f'{time}_{kind}'. The tamper-evident ledger that would make memory citable has zero non-test importers and its files do not exist on disk. The vector index file does not exist. So 'certified memory' reads as operating in the docs and is not operating at all. The flywheel that would close the loop (a landed write becoming a labelled eval task) EXISTS in code and is dark behind DAEDALUS_AUTO_MINT. |

Source: `docs/architecture-map.html` §“Die Küche”; the readers cite
`docs/adrs/006-memory-separation.md`, `docs/adrs/011-event-spine.md`,
`docs/IKARUS_ARIADNE_MASTER_PLAN.md` §3.2 and `docs/bypasses.md` §4.

## Die Schichten — per-area prose {#areas}

What each area is FOR, and what it actually is. The generated tables below say
what exists and what reaches it; these paragraphs say what it means.

### Surfaces (how a human or agent reaches the system)

**Soll.** Every entry point: operator CLI, HTTP API + React cockpit, the JSON file bus, the VS Code extension, and the cross-vendor room.

**Realität.** WORKS: the CLI is the real product surface — 29 dispatched subcommands (measured: grep -c 'cmd == "' daedalus/cli.py = 29; the prior inventory says 26, one reader said 27 — both wrong). The file bus works end to end but its watcher loop is reachable ONLY via `python -m daedalus.file_bridge watch`; `daedalus watcher` only prints status. ASPIRATION/DRIFT: about a third of the HTTP API has no client — /api/topology, /api/context/plan, /api/latent/search, /api/events/memory, /api/capabilities, /api/accelerators/status and three PUT routes have zero callers in apps/web/src or the extension [re-measured 2026-08-25: the new cockpit reaches /structure, /projects, /governance, /health, /drafts, /events, /ikarus/stream, /topology AND /context/plan -- the last two had no caller anywhere until this date. /latent/search, /events/memory, /capabilities, /accelerators/status and the three PUT routes still have none]. web_api.py contains 19 path-dispatch branches across do_GET/do_PUT/do_POST (measured); the inventory's 30 'endpoints' is the same surface counted as method+path pairs after prefix dispatch (/api/projects/ alone fans out to ~7) — both numbers are right, they count different things. The room GUI (runs/council/room_server.py) and `daedalus web` both default to 127.0.0.1:8765 and cannot run together. No test invokes cli.main(); only 2 of the HTTP routes are ever dispatched by a test.

**Komponenten:** `daedalus/cli.py:794`, `daedalus/web_api.py`, `daedalus/file_bridge.py:405`, `apps/web/src/cockpit/Cockpit.tsx`, `apps/web/src/theme/ThemeProvider.tsx`, `apps/web/src/App.tsx`, `vscode-agent-env/extension.js`, `runs/council/room.py`, `runs/council/room_server.py`, `runs/council/room_ui.html`, `runs/council/stream_hook.py`

### Orchestration (turning an objective into dispatched work)

**Soll.** Decompose an objective, route it to an agent role and a provider lane, schedule it, and hold the lane gate.

**Realität.** WORKS: two-stage routing is real and load-bearing — router.route_task (keyword/path scoring over agents/*.json) then provider_router.select_provider (four ordered rules ending in deepseek→ollama→codex_cli). The bus lane gate fails closed: an unknown or missing lane is coerced to local_only (core.py:707) so an unlabeled task can never be billed to a paid lane. KairosScheduler bounds concurrency and silently demotes any parallel batch containing a write to sequential, because write attribution is a whole-repo hash diff. ASPIRATION: there is no DAG, no MissionSpec, no persistent mission state, no crash recovery at the orchestration layer — bypasses.md §4 says so plainly. 'Kairos' is a bounded batch dispatcher, not the scheduler ADR-001 describes. kairos/orchestrate.py:prepare_task, which the prior inventory calls 'path inference and policy threading for each dispatched task', has NO caller in any dispatch path — it is a standalone `python -m daedalus.orchestrate` CLI.

**Komponenten:** `daedalus/router.py:51`, `daedalus/provider_router.py:282`, `daedalus/kairos/scheduler.py:72`, `daedalus/kairos/decompose.py:143`, `daedalus/core.py:701`, `daedalus/build.py`, `daedalus/categories.py`, `daedalus/agents_registry.py`

### Execution (what actually runs a model and what it may touch)

**Soll.** Run the provider, capture what it did, verify it, and undo it if verification fails.

**Realität.** WORKS, and this is the strongest part of the system. offload.py is the only production write path: it refuses a live write with no project policy, snapshots whole-repo content hashes before the run, treats the DISK DIFF as ground truth and explicitly ignores the model's self-reported files_changed, verifies with require_changes, re-runs the blast-radius fence over what actually landed with a FRESH index, and rolls back on failure. Only ollama implements rollback(), so any routed codex write is stripped of write rights and stamped mutation_blocked — codex cannot land a write through offload today. The full-file-rewrite path exists because 7B models narrate edits and never emit write_file. TWO DISJOINT LANES: Lane A (offload) mutates the primary checkout; Lane B (`daedalus improve` → spine/attempt.py) runs in a git worktree outside the repo and has NO apply path. ASPIRATION: Lane B's containment is path hygiene, not a jail — the runner is an in-process Python callable and worktree.py's own docstring now concedes 'path hygiene has a floor'. OS-level isolation has zero code. A third lane (daedalus/adapters/ + kairos/shadow_shell.py + evolution.py) is fully built, tested, and reached by NOTHING — and its RUNTIME_PROFILES ship `--sandbox workspace-write` and `--permission-mode dontAsk` with cwd defaulting to os.getcwd().

**Komponenten:** `daedalus/offload.py:258`, `daedalus/providers/ollama.py:134`, `daedalus/providers/codex_cli.py:120`, `daedalus/providers/deepseek.py:21`, `daedalus/providers/_ollama_native.py:140`, `daedalus/verifier.py:147`, `daedalus/spine/attempt.py`, `daedalus/spine/ledger.py`, `daedalus/spine/cancel.py`, `daedalus/spine/picker.py`, `daedalus/kairos/worktree.py`, `daedalus/adapters/subprocess_adapter.py`

### Context / distillation (the actual moat)

**Soll.** Turn a repository into the smallest correct context for a task, with provenance for everything withheld.

**Realität.** WORKS, and it is the most mature subsystem: 19 modules, ~5,900 lines, a content-keyed sqlite cache, a parallel scan, tree-sitter for 21 languages, four clone passes sharing one memo, an import graph, a Forest+DSS planner with content-addressed receipts, and a slicer whose egress gate is applied at the EMISSION point rather than to the rel sets. Withholding is never silent. MEASURED WINS: 6,798→187 core files and 171s→22s on project_tct after scoping; 79.2–79.3% token compression under a real tokenizer. THE GAP: it is barely wired into the mutate path. The slice→offload wire ships DARK (OFFLOAD_SLICE_TOKENS, default 0) because the one live A/B showed no measurable lift on a trivial task. GET /api/topology and GET /api/context/plan have no UI consumer. Two structural holes: no center-root existence validation anywhere (a center naming a non-existent directory silently yields an empty index), and the eval indexes UNSCOPED while the product indexes SCOPED — so eval and product compression figures have different denominators.

**Komponenten:** `daedalus/structcore/index.py:357`, `daedalus/structcore/slice.py:158`, `daedalus/structcore/graph.py`, `daedalus/structcore/clones.py`, `daedalus/structcore/forest.py`, `daedalus/structcore/dss.py`, `daedalus/structcore/ignore.py`, `daedalus/context_plan.py:441`, `daedalus/dctx.py:158`

### Memory / provenance (what the system remembers and can prove)

**Soll.** Record what happened durably enough that a later claim can be checked.

**Realität.** SIX durable stores, no join key, and the strongest one is dead. VERIFIED ON DISK: memory/events.local.jsonl PRESENT (199KB, unlocked, unchained, records carry no id); runs/canary/history.jsonl PRESENT (20 records); runs/council/*.jsonl PRESENT and chain-verify clean; memory/ledger.local.jsonl ABSENT; memory/state.local.json ABSENT; memory/vectors.db ABSENT; runs/spine/spine.sqlite3 ABSENT. So dmem/1 certified memory has NEVER been written outside tests, the vector index has no rows (both wired readers return empty and GET /api/latent/search materialises an empty DB as a side effect of being called), and the spine ledger has never run outside pytest tmpdirs. ADR-011 elected spine/ledger.py as the ordering authority and made attestation into the hash-chained ledger MANDATORY — grep finds no `actor` field, no namespace validator, no attestation helper, and no intent_id written into any other store. By the ADR's own consequences clause, no spine transition currently has proof. ADR-011 §5 forbids a fifth durable log; the council bus is the fifth and the canary history the sixth, and the ADR has not been updated to say so.

**Komponenten:** `daedalus/memory/__init__.py:56`, `daedalus/memory/embeddings.py:380`, `daedalus/memstore.py (removed 2026-08-22):369`, `daedalus/spine/ledger.py:230`, `daedalus/council/bus.py`, `daedalus/council/canary.py:1056`, `docs/adrs/011-event-spine.md`

### Safety (the fail-closed core)

**Soll.** Decide what may leave the machine, what a free model may write, and what must escalate.

**Realität.** WORKS, and it is genuinely adversarially hardened — this is the part of the system whose claims survived contact. Two INDEPENDENT egress channels: the secret floor (12 path markers + 11 value-shaped regexes, sensitivity.py:316) runs on EVERY lane including trusted, cannot be reached by project config, and _compile_labeled RAISES if a pattern would be silently dropped; and the default-deny allow-list, which load_policy unions with the baseline so a repo config can extend but never weaken it. The blast-radius fence asks the import graph whether an edited leaf FEEDS a fenced module, is fail-closed inside a bare except, runs twice (routing time over declared paths, post-write over the actual disk diff with refresh=True), and has an anti-fatigue stand-down that is loudly reported rather than silent. Three fence CRITICALs were found by the adversarial panel AGAINST the fix and repaired same-sprint. HOLES THAT REMAIN: the Python lint gate in verifier.py is INERT on this machine (verified: ruff absent, pyflakes absent → _lint_py returns True unconditionally) and the only two tests that name it mock the function under test, so deleting the whole gate keeps the suite green; spine/attempt.py's READ_ONLY_REPO_VERBS still permits `config`, `diff` and `cat-file` against the primary checkout with no argument-shape validation while the docstring asserts 'none of them writes' — Codex demonstrated `--ext-diff`/`--textconv` execute arbitrary helpers; offload's lane='trusted' for ollama is derived from the PROVIDER NAME, not the resolved OLLAMA_HOST, which in this setup points at an off-machine tailnet bench; and enforce.py:54 hardcodes the author's absolute Windows paths into every repo it enforces.

**Komponenten:** `daedalus/sensitivity.py:316`, `daedalus/sensitivity.py:270`, `daedalus/sensitivity.py:339`, `daedalus/provider_router.py:153`, `daedalus/structcore/graph.py:256`, `daedalus/offload.py:455`, `daedalus/verifier.py:48`, `daedalus/storage.py:44`, `daedalus/spine/attempt.py:151`

### Evaluation (does any of this actually work)

**Soll.** Measure recall and compression against labels the system did not choose for itself.

**Realität.** WORKS, and it is unusually honest — the headline number prints 'PARTIALLY SELF-GRADED' on its own output because a human picked the labels AND verified them by running the very slicer being graded. Provenance tiers are never blended; errored and focus-withheld rows have no recall key at all so a forgetful aggregator KeyErrors instead of averaging a zero. The independent corpus (17 tasks minted from real commit diffs, cross-file only, no graph walk) is ALL tier=quarantine with confirmations=0 against a threshold of 3 — so the 86.2% independent figure is in every render and in NO go/no-go number, by design. LIMITS: baseline.json holds exactly the 10 self-graded tasks, so the advisory gate ratchets only the self-graded corpus; every minted task hardcodes an absolute repo path and would error-row on any other machine; the gate is advisory by explicit design and is not wired to block anything; --arms, --tier2, --gate, --mint-commit and --confirm-mint are all default-off flags; and ceiling.py is not reachable from `python -m daedalus.eval`.

**Komponenten:** `daedalus/eval/harness.py:249`, `daedalus/eval/tasks.py`, `daedalus/eval/mint.py:333`, `daedalus/eval/ceiling.py:232`, `daedalus/eval/report.py:16`, `daedalus/eval/baseline.json`, `daedalus/eval/minted_tasks.json`

### Cross-vendor review (the newest layer, and the one that produced the corrections)

**Soll.** Put independent model vendors over the same evidence and record every dissent verbatim, without letting any of them decide anything.

**Realität.** WORKS as tooling and has demonstrably earned its keep — Codex refuted a load-bearing containment claim with 3 CRITICALs and file:line, Opus 4.6 found two things both other vendors missed, a fresh Claude instance attacked the process itself and found that the fix for a refuted design was being written and trusted by the same instance that wrote the bug. The advisory doctrine is enforced STRUCTURALLY: CouncilRecord carries no approve/reject/score/majority field and a test walks every field of every nested dataclass to keep it that way. Transcripts are hash-chained and verify clean. THE HONEST CAVEAT: the council's own premise is UNMEASURED by its own pre-registered protocol (arm A four vendors vs control arm B one vendor asked twice, ground truth = spine GateResult) — that experiment has never been run, so room.md is a strong anecdote, not evidence. ADR-012 §7 said session.py ships offline-replay-only until that measurement exists; `daedalus council` and `daedalus canary` are live CLI commands. The doctrine survived; the sequencing constraint did not. Also verified: room.md now has 48 turns but the chain anchor covers 4 — 44 turns, including every finding, are unattested.

**Komponenten:** `daedalus/council/session.py:940`, `daedalus/council/bus.py`, `daedalus/council/vendors.py`, `daedalus/council/canary.py`, `daedalus/council/publish.py`, `runs/council/room.md`, `docs/adrs/012-council-cross-vendor-review.md`

Source: `docs/architecture-map.html` §“Die Schichten”, one paragraph per
reader-scoped area, 2026-07-28.

## Die Umkehrungen — claims made, measured, withdrawn {#reversals}

Behauptungen, die aufgestellt, gemessen und zurückgezogen wurden. Das ist der wichtigste Abschnitt dieser Karte: Er ist der Nachweis, dass ungeprüfte Aussagen in diesem Projekt eine Trefferquote haben — und sie ist schlecht.

### TaskAttempt makes it structurally impossible for a candidate model to write the primary checkout — by construction.

- **gemessen** — Codex (OpenAI CLI) refuted it in the cross-vendor room with 6 findings, 3 CRITICAL, all file:line: the runner is an in-process Python callable, so passing it ctx.worktree is an argument, not a jail; the default pytest gate executes candidate-controlled Python; and the linked worktree exposes the common .git.
- **Folge** — Claude re-verified one finding independently before acting, then conceded the framing. The honest claim narrowed to 'the HARNESS never applies a patch to the primary checkout and defines no promotion path that does'. Real containment needs an OS sandbox that has zero code. VERIFIED STILL OPEN: daedalus/spine/attempt.py's header nonetheless still reads 'WHY THIS CAN NOT WRITE THE PRIMARY CHECKOUT ... three structural properties', so the refuted claim can be re-inherited by the next cold reader.

### The cleanup_worktree security fix is done — self-verified, 29 tests green.

- **gemessen** — An independent Cerberus review REPRODUCED deletion of the primary repository against the PATCHED code, through the public API, with all six containment checks passing honestly and cleanup returning worktree_removed=True. Mechanism: CPython's rmtree reads st_reparse_tag from a stale scandir cache, so a junction planted mid-walk IS followed. Measured window 1.067s of a 1.122s traversal; the bespoke walker failed 3/3 while plain shutil.rmtree survived 3/3 — the replacement was worse than what it replaced.
- **Folge** — worktree.py fully rewritten around _remove_tree_no_follow (re-lstat immediately before every scandir, identity-checked allocation records, refuse rather than fall back). tests/test_worktree.py now holds 39 tests separating pre-planted from mid-walk attacks. The module now concedes its own floor in writing: 'path hygiene has a floor'. Standing rule earned: a patch to safety-critical code must not reach a commit without an independent adversarial pass, and that belongs in the gate, not in a person's discipline.

### The Ollama usable input window is num_ctx/2 — a HALVING LAW, a property of the server.

- **gemessen** — Re-measured 2026-07-28 with fresh unique prompts to defeat KV-prefix caching: at num_ctx=16384 the server evaluated 3,971 and 14,375 prompt tokens with full head recall. Only OVER-BUDGET prompts pin to num_ctx/2 (8194@16384, 4098@8192) and lose their HEAD — the system prompt dies first. Persisted with OLLAMA_NUM_PARALLEL=1.
- **Folge** — It is a TRUNCATION PENALTY, not a window. Corrected to full num_ctx minus a named OUTPUT_RESERVE_TOKENS=1024 (_ollama_native.py:36/58). Usable input went 3072→5120 locally (1.7x) and 15360 on the bench. The fail-loud over-budget refusal was kept; only its threshold moved.

### The temporal co-change tier would recover ~19% of missed labels — a real class worth building.

- **gemessen** — Momus NO-GO'd the designed experiment by running the cheap measurement the design had deferred: backtest-clean reachability 0/43. The author reproduced it. Nemesis then refuted the CLOSE itself for rename-blindness across the agent_env→daedalus rebrand, correcting the true ceiling to 1/43 = 2.3% clean vs 6/43 leaky at min_count=2 and 42/43 at min_count=1 — the gap IS the self-prediction artifact.
- **Folge** — Nothing was built on the slicer; zero new core API. A read-only reopen gate shipped instead (eval/ceiling.py, REOPEN_MIN_SHARE=0.10 or 3 distinct tasks), with the caveat printed by the machine that 41 of 43 focus files are BORN at their mint commits and are structurally temporal-immune. The old 19% was predominantly the mint commit predicting itself.

### The eval reports 100% slice recall.

- **gemessen** — The labels in eval/tasks.py were 'verified reachable by running semantic_slice' — the slicer chose what it was graded on.
- **Folge** — The number did not move; its MEANING was narrowed. daedalus/eval/report.py:18 now prints PARTIALLY SELF-GRADED on every render containing that tier, provenance buckets are never blended, and _is_primary_tier is fail-closed so a typo'd tier is treated as quarantine. The honest labelling was called the sprint's real deliverable.

### Independent recall improved from 61.7% to 86.2%.

- **gemessen** — The 17-task corpus was re-minted with hygiene filters: junk labels ('if', '<anonymous>'), cross-language labels, and secret-floor-tripping anchors stopped counting as misses.
- **Folge** — Explicitly refused as a win — recorded as HONEST ACCOUNTING, not a slicer improvement. All 17 minted tasks remain tier=quarantine with confirmations=0 against a threshold of 3, so 86.2% appears in every render and in no go/no-go number by construction.

### The Rust structcore engine is 10-100x faster — the stated rationale for an engine pivot.

- **gemessen** — ~1.3x like-for-like, and SLOWER on the full repo (216s vs 171s) while doing LESS work.
- **Folge** — The pivot survives on the Tauri/bundling rationale only; the speed claim is retired. The real bottleneck was named as a GIL/process-boundary concurrency problem, which is language-neutral. structcore-rs/ still exists on disk with ZERO Python callers, no safety gate, no scope awareness, ~13 languages behind, and its own copy of the C-naming bug.

### 1.47x speedup / 171.0s wall / 499 corrupted files.

- **gemessen** — All three were taken while 23 agent processes were running, or against a code path Python does not take. True values: 0.99x, 86.5s, 66 files.
- **Folge** — The single incident that produced the project's provenance discipline: check the process count before any timing, stamp every number [M]/[I]/[A], and treat a number measured under load as WRONG not slow.

### The clone-pass memo will give ~2.4x by sharing fingerprints across passes.

- **gemessen** — 1.08x on the full repo.
- **Folge** — The change was KEPT (it is free and removes a real double-normalize) while its justification was withdrawn — the 'Python was never optimized' framing was explicitly stripped of the weight it had been given. A rare case of separating a change from its rationale.

### The local 7B model writes files when told to; the offload lane saved 100% of tokens.

- **gemessen** — qwen2.5-coder:7b NARRATES edits and never emits a write_file tool call, so files_changed was empty every time — and the schema-only verifier ACCEPTED it. Fake 100% savings, zero work. Prompt hardening did not fix it (a capability limit, not wording).
- **Folge** — verifier.verify(require_changes=True) shipped; no-ops now escalate. The full-file-rewrite path (model returns content, HARNESS writes it) became the real savings lever, gated on identical/truncation/elision checks.

### Greenfield builds route to the free lane and save 98%.

- **gemessen** — Live, 3 attempts: 0%. Fail-closed refuse-write with no policy, the rewrite path cannot CREATE files, and build-shaped objectives route to senior.
- **Folge** — 0% recorded as the CORRECT call, not a regression. Real savings live in the routine slice — docstrings, notes, small refactors — not builds.

### The plaintext-secret CRITICAL is fixed; the egress gate is tight and the tests are green.

- **gemessen** — Cerberus re-review found six live bypass classes still leaking (underscore-glued names like DB_PASSWORD, string prefixes, triple quotes, short values, typed assignment, quoted-key dict forms) — the tests stayed green because every fixture used bare keywords.
- **Folge** — The rule was rewritten and cleared on round 2 (d714128 → 0360964). Standing lesson: always re-verify a gate agent's measurement yourself in a fresh process; a CRITICAL a gate called tight can still be leaking.

### The suite protects the worktree guards.

- **gemessen** — The suite stayed fully green with _refuse_if_repo_adjacent, _remove_tree_no_follow and the reap sha-proof EACH disabled by hand.
- **Folge** — 'A guard whose absence no test detects is decoration.' Mutation testing by hand became the round-2 rule and is recorded in-code at worktree.py:319 and attempt.py:305. It has been applied to exactly two files; there is no harness and no enforcement for the other 84 test files. VERIFIED LIVE INSTANCE OF THE SAME PATTERN: verifier._lint_py is fail-open, neither ruff nor pyflakes is installed on this machine, and the only two tests that name it patch the function itself — deleting the entire lint gate would keep the suite green.

### Parallel write tasks are safe when their declared paths are disjoint.

- **gemessen** — An agentic writer can touch files it was never told about, while isolate_paths observes only declared strings.
- **Folge** — kairos/scheduler.py now demotes any batch containing a write to sequential with whole-repo attribution; _paths_overlap is dead code that docs/PARALLEL_DISPATCH.md:33 still describes as 'the conflict refusal'. Declared path overlap is explicitly downgraded to a scheduling hint.

### The forced `--lane codex` bridge is a safe legacy path.

- **gemessen** — It granted workspace-write while bypassing offload's snapshot, verifier, rollback and worktree execution entirely.
- **Folge** — writable hardcoded False at daedalus/core.py:663 with a mutation_blocked stamp on every result; the same downgrade enforced for the ROUTED codex lane at offload.py:384 keyed on rollback CAPABILITY rather than provider name, so it covers future providers automatically.

### 'Hermes' was an upstream comms service worth integrating.

- **gemessen** — An implementation audit found it was an unauthenticated WebSocket server bypassing the scheduler.
- **Folge** — ADR-002 status REJECTED (not deferred); source removed; reopening requires a new ADR naming project, version, license, threat model and replacement cost. Correction (ADR-017, 2026-07-29): the `daedalus/hermes/` bytecode husk this section once flagged as contradicting ADR-002 no longer exists on disk.

### Eight impressive ideas: hyperbolic geometry as semantics, weighted embedding averages as a code gradient, spectral partitions as conflict-free schedules, latent interpolation as a patch decoder, DLSS as a tensor backend, PhysX collisions as merge conflicts, layout distance as retrieval ground truth, candidate-authored tests as proof of correctness.

- **gemessen** — The 2026-07-28 foundation audit found, e.g., Euclidean embeddings radially projected into a Poincaré ball and called hyperbolic semantics.
- **Folge** — All eight struck from the vocabulary with named re-entry conditions per item. Sparse spectral analysis survives as read-only, size-limited VISUALISATION whose every payload carries a reason saying the cut does not prove conflict-free edit scopes. The candidate-authored-tests item is the one with the largest doctrine-vs-enforcement gap: prohibited in three documents, enforced in none, because there is no OS sandbox.

Source: `docs/architecture-map.html` §“Die Umkehrungen”; the underlying
records are in `docs/HANDOFF.md`, `runs/council/room.md`, `docs/archive/FOUNDATION_AUDIT.md`
and `docs/adrs/002-hermes-upstream.md`.

## Drift, von Hand belegt {#drift}

Die Liste der vergessenen Dinge: Inseln, die niemand aufruft; dunkle Schalter, die per Default aus sind; Reste, die überlebt haben.

This list is FEATURE- and SYMBOL-level and hand-evidenced. The generated tables
work at MODULE level and cannot see most of it — a module holding one live and
four dead functions is reachable by construction. Keep both; they answer
different questions.

- ISLAND — daedalus/memstore.py (removed 2026-08-22) (dmem/1 hash-chained certified memory ledger, 390 lines, 34 tests). VERIFIED: zero non-test importers under daedalus/ (every hit is a docstring reference), and memory/ledger.local.jsonl and memory/state.local.json DO NOT EXIST on disk. It has never been written. ADR-011 assigns it the attestation-sidecar role; that role is unfilled, so anyone reading the docs would reasonably believe certified memory is operating. It is not.
- ISLAND — daedalus/kairos/worktree.py:685 reap_branches. VERIFIED: zero production callers (only worktree.py's own docstrings and 14 call sites in tests/test_worktree.py). Consequence: `git worktree add -b` writes a ref into the shared .git on EVERY attempt and cleanup deliberately leaves it, so every `daedalus improve --once` leaks a daedalus-attempt-* ref forever. A correct, carefully-designed, heavily-tested fix that does not run.
- ISLAND — the ledger crash-recovery handshake, daedalus/spine/ledger.py:404 open_intents and :424 resolve_by_effect. VERIFIED: called only from tests. The ledger docstring specifies the recovery loop; no module implements it. Intent-before-effect is written and never read back, so the crash window it exists to close is not actually closed by any running code.
- ISLAND — the entire adapters lane: daedalus/adapters/{base,events,transport,subprocess_adapter}.py plus daedalus/kairos/shadow_shell.py and daedalus/kairos/evolution.py. Nothing in the CLI, API, core.py or offload imports any of them. Two readers correct the prior inventory here: TransportRecord and the transport sinks are NOT 'consumed by embeddings and shadow_shell' — shadow_shell passes no sink, embeddings does not import transport, and with sink=None _publish returns immediately so NOTHING is recorded. ARMED AND UNROUTED: RUNTIME_PROFILES ship `codex exec --sandbox workspace-write` and `claude --permission-mode dontAsk` with cwd defaulting to os.getcwd().
- ISLAND — daedalus/council/publish.py (GitHub PR bridge, 26 tests). No Python caller, no CLI subcommand, no main(); the only reach path is an agent hand-running the snippet in .claude/skills/council/SKILL.md:80.
- ISLANDS (smaller, all verified by grep): daedalus/semantic_route.py, daedalus/compaction.py (removed 2026-08-22) (both tests/test_cascade.py only), daedalus/token_monitor.py (own __main__ only — CORRECTION to the prior inventory, which records tests: [] when it is tested at tests/test_agent_env.py:15 and tests/test_hardening.py:33), daedalus/runbook.py (zero tests, zero importers), daedalus/langgraph_adapter.py (build_graph raises NotImplementedError unconditionally even with langgraph installed — the prior inventory's 'optional shim' note is misleadingly optimistic), daedalus/structcore/graph.py:49 name_index, daedalus/structcore/churn.py:215 temporal_misses, daedalus/structcore/clones.py:451 window_clusters, daedalus/structcore/index.py:682 _hotspots, daedalus/memory/embeddings.py index_status/legacy_unversioned_count/ingest_transport_records, daedalus/kairos/scheduler.py:40 _paths_overlap (dead; docs/PARALLEL_DISPATCH.md:33 still calls it 'the conflict refusal').
- DARK — OFFLOAD_SLICE_TOKENS, default '0' = OFF (daedalus/offload.py:161-171). The slice→offload wire: the distillation moat feeding the mutate path. Ships off on an explicit landing-gate rule — the one live A/B (n=1, trivial task) showed correct edits in both arms and no measurable lift. Only the ollama branch can ever receive a slice; codex and deepseek never do. The off state is reported in the result as 'disabled (OFFLOAD_SLICE_TOKENS=0)', so it is observable rather than invisible.
- DARK — DAEDALUS_AUTO_MINT, default unset = OFF (daedalus/offload.py:92-107). The eval flywheel: a landed, disk-verified write becoming a labelled eval task. MISSING FROM THE PRIOR INVENTORY ENTIRELY, and BOTH memory files plus docs/HANDOFF.md §4c still say this seam is open — it closed in commit 21d4cc9. Stamped on every write-mode run (disabled/skipped/minted/error) so a seam that declined to fire is visible.
- DARK — DAEDALUS_VECTOR_INDEX, default unset = OFF (daedalus/memory/__init__.py:65). Synchronous embedding on the operational append path — a KNOWN OPEN P0, because it makes Ollama availability a dependency of writing a memory. The async Projection Worker that would replace it is planned, not built. Consequence today: memory/vectors.db does not exist, so both wired readers of the vector index return empty.
- DARK — --latent / use_latent=False (daedalus/context_plan.py:448, CLI flag at cli.py:204) and ?latent=1. Latent memory seeds in the context planner. Not flagged in the prior inventory. Honest when off: the plan records LatentSeedResult('disabled') rather than silently returning nothing.
- DARK — DAEDALUS_RTX_OLLAMA_HOST / DAEDALUS_RTX_OLLAMA_TOKEN / DAEDALUS_RTX_TOKEN / DAEDALUS_NVOF_SDK, all unset (daedalus/accelerators.py:31-35). The remote RTX lane reports unconfigured. NOTE THE ASYMMETRY: runs/council/room.py:34 DEFAULTS the same host to http://100.119.126.9:11434, an off-machine tailnet bench, and is explicit that this is an egress lane, not 'local'.
- DARK (other, all default-off or platform): DAEDALUS_SCAN_MIN_PARALLEL, DAEDALUS_NO_CACHE, DAEDALUS_CENTER, DAEDALUS_IGNORE, DAEDALUS_WEB_DEBUG (unset = the web server logs NOTHING per request), DAEDALUS_STREAM_HOOK_DIR (tests only), and the eval flags --arms/--tier2/--gate/--update-baseline/--mint-commit/--confirm-mint.
- STALE — build/ (lib + bdist.win-amd64), untracked, a duplicate copy of the whole source tree that pollutes every repo-wide grep with false 'caller' hits and will drift silently. Confirmed present.
- STALE — structcore-rs/ (Cargo.toml, src/, target/): zero Python callers, 12 tests all in one file, ~13 languages behind, no scope awareness, no safety gate. Its existence still shapes slice.py's degradation contract.
- STALE — ~/.claude/skills/room/room.py: a 689-line divergent FORK of the 1,099-line runs/council/room.py, and SKILL.md:23 points every skill invocation at the fork. Missing: the hash-chained bus, `verify`, distilled attachments, the opus/fable speakers, and solo mode — so invoking the room via the skill reproduces the exact anchoring bug the repo engine was fixed to prevent.
- STALE — docs/ARCHITECTURE.md + architecture.html + architecture_history/ (2026-07-06, 'Era 3, 230 tests green' against a tree now at ~1,399 tests), plus 12 more unlinked pre-audit docs in docs/. docs/FALLBACK.md and docs/MISSION_CONTROL.md are the same vintage but ARE still linked from README, so they read as current.
- STALE — vscode-agent-env/daedalus-vscode-0.3.0.vsix (Jul 6) and mockup.html / wheel-mock.html; marked stale on age, not on diff.
- STALE AND LOAD-BEARING — docs/FEATURE_INVENTORY.json. VERIFIED: repo_state head=f40529c against actual HEAD 17c3f88 (26 commits behind); 13 area entries, 136 features (wired 108, planned 12, island 7, stale 5, dark 2, shim 1, baseline 1). This is NOT documentation: daedalus/spine/picker.py:89 reads it as the two highest-priority bands of the `daedalus improve` work queue (inventory_island=400, inventory_stale=300, above eval_miss=200 and hotspot=100). It has no generator, no freshness gate, no timestamp, and no test that fails when it drifts. It contains ZERO entries for daedalus/spine/ (still filed 'planned'), ZERO for daedalus/council/, ZERO for runs/council/ — so the self-improvement loop is blind to its own spine, and its one worktree entry restates precisely the isolation claim Codex refuted.
- DISAGREEMENT RESOLVED — CLI subcommand count. Prior inventory 26, one reader 27, two readers 29. MEASURED: 29 (doctor offload spawn build ikarus dctx context metrics benchmark status dashboard models accelerators squads watcher review-diff projects agents categories council canary claude-crew drafts selftest bookkeeper web enforce improve init). The inventory's cli_commands array holds 33 entries — it lists sub-verbs, and still omits council, canary and improve.
- DISAGREEMENT RECONCILED — API route count. MEASURED: 19 path-dispatch branches across do_GET/do_PUT/do_POST in web_api.py. The inventory's 30 'api_endpoints' counts method+path pairs after prefix dispatch expands (/api/projects/ alone fans out to hierarchy, control-plane, bootstrap, team, autonomy, agents, categories). Both are correct; they count different things. Either way ~9 have no client in this repo.
- DISAGREEMENT RESOLVED — PnP_App 'the index returns 0 files'. I read projects/pnp_app.json and the target repo. Its own _center_comment declares this a GREENFIELD TEST GROUND where app/ and src/ do not exist yet BY DESIGN and predicts 'the index will be near-zero'. VERIFIED: app/ and src/ absent; design/visual-lab/src PRESENT with exactly 3 files. So the honest anomaly is 0-vs-3, not 0-vs-25 — much smaller and much more diagnosable than docs/HANDOFF.md and docs/EXPERIMENT_A_B.md §6.3 describe. The real structural defect it exposes is separate and confirmed: there is NO is_dir()/exists() validation of a declared center anywhere in ignore.py, index.py or projects.py, and .md/.html/.json/.yaml have no LanguageSpec so those 137 markdown files could never be collected regardless of scope.
- DISAGREEMENT NOTED, UNRESOLVED — daedalus/providers/codex_cli.py:196 appends a multi-line prompt as an argv element with stdin=DEVNULL. docs/HANDOFF.md:138/183 state as MEASURED that a multi-line prompt does not survive the npm .cmd shim on Windows and must go on stdin, and four other call sites honour that. The provider's own comment gives a competing measured reason for DEVNULL (with a prompt arg, codex exec still blocks on inherited stdin until EOF — live-fired 2026-07-11). Two measured constraints collide; neither reader could settle it read-only. Status: unknown, not broken.
- DOC-VS-CODE DRIFT (all verified by me): docs/HANDOFF.md:65 says 'both old aliases still import' for the metron→kairos rename — FALSE, `import daedalus.metron` raises ModuleNotFoundError; only the class alias MetronScheduler survives at daedalus/ikarus.py:18. The inventory's stale entry 'pyproject.toml still names daedalus.metron' is also FALSE — pyproject lists daedalus.kairos. daedalus/eval/__main__.py:17 still says offload does not invoke minting; it has since the auto-mint seam landed. daedalus/benchmark.py's docstring still says 'it does not call any model' although run_live does. docs/PARALLEL_DISPATCH.md:33 still documents dead code as the conflict refusal. daedalus/providers/__init__.py:8 still calls ollama read-only. tests/test_fenrir_slice_attack.py and tests/test_wires.py carry stale NOTEs describing follow-ups that have landed. The master plan says the artifact disk is D:; it is E:.
- MISSING FROM EVERY PRIOR LIST — the `category` kwarg on file_bridge.enqueue() has no CLI flag, so it is settable only programmatically; and stream_hook.py is wired in ~/.claude/settings.json (the USER's global file), not in the repo, so the hook wiring is neither version-controlled nor portable to a fresh clone.

Source: `docs/architecture-map.html` §“Drift”, nine-agent read, 2026-07-28.

## Was gerade blockiert {#blockers}

The open items, each with what it PREVENTS. This is the list the generated gate
cannot produce: a scanner sees an island, not a reason autonomy is unsafe.

- OPEN CRITICAL, security — candidate isolation is path hygiene with a self-declared floor. daedalus/kairos/worktree.py and daedalus/spine/attempt.py are under active edit; docs/HANDOFF.md:8 forbids committing either until it clears, and attempt.py is UNTRACKED while worktree.py is modified. PREVENTS: any unattended overnight `daedalus improve --live`, and Arm B of the pre-registered A/B. Note the doc is now BEHIND the code — the reproducible deletion has been fixed and 39 regression tests added; the residual is a microsecond scandir-cache race that the module documents honestly. docs/EXPERIMENT_A_B.md:113 must be updated or it blocks the experiment for a reason that no longer holds in that form.
- OPEN, and the highest-expected-value item — THE PATCH HAS NEVER BEEN ADVERSARIALLY REVIEWED. Both council transcripts on disk predate the fix (12:12, 12:14) and no post-fix Codex or Opus turn exists. A fresh Claude named this exactly: the instance that wrote the bug wrote and trusted its own patch, with the reviewer stood down. PREVENTS: any honest claim that the repo-deletion class is closed. FIX: `daedalus council --patch <diff of worktree.py+attempt.py>` with a non-Anthropic lane.
- OPEN, unfixed and contradicted by its own docstring — daedalus/spine/attempt.py:151 READ_ONLY_REPO_VERBS still contains config, diff, cat-file, show, log; _git branches on args[0] alone with no argument-shape validation and no git-env sanitization (VERIFIED). Codex demonstrated `git config name value` mutates and `--ext-diff`/`--textconv` execute arbitrary configured helpers. Line 41 still asserts 'Every one of them reports; none of them writes.' PREVENTS: trusting the git choke point as a boundary.
- OPEN — cleanup runs BEFORE terminal ledger resolution. VERIFIED: attempt.py's own comments read `# 8. cleanup` inside `finally:` immediately followed by `# 7. resolve the intent`, and there is exactly ONE record_intent call. The two-intent fix that Claude proposed, Opus endorsed and Codex did not contest was never implemented; Opus's ruling in Anthropic's favour rested on docstring evidence and does not survive a code check. With artifact_dir defaulting to None, a kill between cleanup and resolution destroys the candidate and leaves an open INTENDED row plus a base-only branch. PREVENTS: the crash-safety claim.
- OPEN — no OS-level isolation for candidate runners or gates. Zero code, no module, no ADR. This is the category fix for two of Codex's three CRITICALs, and hardening the choke point one finding at a time quietly reinforces a design the findings collectively say is the wrong category. PREVENTS: unattended autonomy, and every kill-list item about candidates modifying evaluators or authoring their own tests.
- BROKEN AND SILENT — the Python lint gate is inert. VERIFIED on this machine: shutil.which('ruff') is False and pyflakes is not importable, so daedalus/verifier.py:48 _lint_py returns (True, 'no linter -- skipped') for EVERY file, and the only two tests that name it patch the function under test. Deleting the entire ruff/pyflakes body would keep the suite green. This is a live instance of the exact pattern the round-2 rule exists to catch. PREVENTS: the write-verification gate catching undefined names and unused imports, which is its stated reason for existing beyond py_compile.
- BROKEN — the Claude Code session mirror's assistant half has NEVER worked. VERIFIED: runs/council/.stream_hook.log shows every single assistant invocation as `skipped-empty in=0 kept=0` (15+ consecutive), the only sidecar on disk is a user turn, and the string `transcript_path` — the key a Stop payload actually carries — appears nowhere in stream_hook.py, whose _extract looks for response/assistant_response/last_message/text/messages. The hook exits 0 by design so the session never notices. PREVENTS: the room ever seeing what Claude said, and starves runs/council/summarize.py, which has consequently produced zero real summaries.
- BROKEN — room cursor keying is written but never read. VERIFIED: build_prompt accepts model= and threads it to seen_count, and say()/main pass it — but _prompt_for (:637), ask_ollama (:922), who() (:972) and the cost report (:1058) all call it WITHOUT model, and runs/council/cursors.json holds the unkeyed {'ollama': 36}. The documented fix for a real observed bug (devstral inherited qwen's cursor, was sent zero turns, and answered from nothing) does not take effect. Also unfixed: room_server.py:250 still appends vendor failures as TURNS against room.py's own doctrine — three live instances in room.md, one containing an OAuth redirect with scopes and state.
- OPEN — the self-improvement loop is aimed by a 26-commit-stale file with no generator and no freshness gate. docs/FEATURE_INVENTORY.json is the top-priority ranked input to `daedalus improve`, omits daedalus/spine/ entirely, and its worktree entry restates a refuted claim. PREVENTS: trusting anything the loop chooses to work on. FIX: a generator or a test that fails when a status claim disagrees with the tree, plus a generated_at field the picker can warn on.
- OPEN — ADR-011's mandatory attestation duty and cross-store join are unbuilt: no actor field, no namespace validator, no attestation helper in spine/ledger.py, and no intent_id written into any other store. Combined with memstore having never been written, this means certified memory reads as operating in the docs and is not operating at all. PREVENTS: any receipt that joins an intent to its worktree, patch, gate outcome and minted eval task.
- OPEN, measurement — the council's own premise is untested by its own pre-registered protocol (arm A four vendors vs control arm B one vendor asked twice, ground truth spine GateResult). room.md is N=1 with no control arm. Meanwhile ADR-012 §7 said session.py ships offline-replay-only until that number exists, and two live CLI commands now exist. CHEAPEST CLOSE: the spine ledger GateResults are already recorded and free to harvest.
- RETRACTED the same day: the claim that build_index returns 0 files on the sibling repo PnP_App was a read error (a key named `files` that the index does not have; the real keys are n_files/modules). Re-measured: 25 files, 99,569 tokens. What remains, and is far smaller: `daedalus context` selected 0 files for one objective there, most likely because projects/pnp_app.json declares center [app, src, design/visual-lab/src] and the first two do not exist yet by design. A config question, not a broken engine.
- OPEN, operational — runs/council/room_server.py and `daedalus web` both default to 127.0.0.1:8765 and cannot run together; the second to bind dies. README's quickstart and HANDOFF's room section both advertise 8765 without mentioning it.
- OPEN, admin — LICENSE is an Apache-2.0 body with NO copyright holder filled in and no license metadata in pyproject.toml (deliberately left for the owner). pyproject's dependencies = [] omits pytest, pytest-asyncio, tree-sitter, tiktoken and lizard, so a fresh checkout cannot reproduce the test run — and missing tree-sitter silently SKIPS the C/C++/Java/Rust/JS coverage while the suite still reports green. There is no CI (.github/workflows does not exist) and no conftest.py, so 24 of the 27 test files that index a repo write to the developer's real user cache.
- UNKNOWN, needs one run each (I was read-only): does `daedalus improve --once` complete end to end (runs/spine/spine.sqlite3 does not exist, so the ledger has never been written outside pytest); does the codex provider's argv prompt actually arrive truncated on Windows; is the `agy_room` scheduled task the fourth council vendor depends on functional (documented as never run); and which of the ~1,399 collected tests currently skip or fail.

Source: `docs/architecture-map.html` §“Was gerade blockiert”; the CRITICALs
are tracked in `docs/HANDOFF.md:8` and `docs/EXPERIMENT_A_B.md:113`.

## Die Invarianten {#invariants}

The binding rules of this codebase. No scanner derives WHY `reap_branches` must
not delete inside a `finally` block; this is where that kind of knowledge lives.

- Fail closed everywhere it costs money or bytes: an unknown or missing bus lane is coerced to local_only (daedalus/core.py:707), a live write with no resolved project policy is refused before the provider is constructed (daedalus/offload.py:335), and a provider with no callable rollback() loses its write grant (daedalus/offload.py:384).
- The secret floor runs on EVERY lane including local and trusted, cannot be reached or weakened by any project config, and its compiler RAISES rather than silently dropping a pattern (daedalus/sensitivity.py:316, _compile_labeled at :297).
- Egress policy is default-deny and weakenable only upward: load_policy unions the generic denylist and high-risk paths so a repo-supplied policy can extend the baseline but never remove it (daedalus/sensitivity.py:205).
- Disk truth beats self-report: what a model claims it changed is explicitly discarded; result['wrote'] is the before/after content-hash diff, and require_changes can only be satisfied by it (daedalus/offload.py:399-440, daedalus/verifier.py:147).
- The graph is asked before the fence decides: an edited leaf that transitively feeds a fenced module escalates, the traversal is fail-closed inside a bare except, and it runs again post-write over what actually landed with a fresh index (daedalus/provider_router.py:153, daedalus/offload.py:455).
- Exclusion is never silent: every index carries an `ignored` block, every slice carries a sorted `withheld` list plus inline breadcrumbs and shell_boundary_stops, and a stood-down fence reports its own stand-down (daedalus/structcore/index.py:543, slice.py:498, provider_router.py:217).
- Under-report rather than guess: an ambiguous unit is <anonymous>, an unresolved import edge is dropped, a whole language is excluded from Type-3 and the exclusion is reported — because a fabricated clone cluster is worse than a missed one (.claude/AGENT_PROTOCOL.md standing orders; daedalus/structcore/clones.py:536).
- The gate decides, not a model: no council record carries an approve/reject/score/majority/consensus field, and the absence of the field is the control — enforced by a test that walks every field of every nested dataclass (docs/adrs/012 §1, tests/test_council_session.py:114).
- Dissent is recorded, never averaged: round 1 is blind and mandatory, turns are stored verbatim per author, and a degraded quorum is stated first rather than footnoted (daedalus/council/session.py, docs/adrs/012 §5).
- Provenance travels with every number: recall is null and never a vacuous 1.0 when nobody supplied labels, hand-picked labels are printed PARTIALLY SELF-GRADED forever, and quarantine-tier tasks appear in every render and no go/no-go number (daedalus/dctx.py:61, daedalus/eval/report.py:16, daedalus/eval/harness.py:97).
- An unvalidated metric never gates autonomy: the eval gate is advisory by explicit design with three written preconditions before it may ever block, and there is no CI in this repo (daedalus/eval/harness.py:802-816, master plan I3/I10).
- Raw evidence is authoritative and projections are disposable: a model change mints a NEW vector index rather than migrating, v1 vectors are quarantined rather than attributed, and a projection hit is never a join (daedalus/memory/embeddings.py:90/398, docs/adrs/011 §4).
- Determinism is load-bearing: sorted iteration wherever set or dict order can reach output, and a council chain head is byte-identical under reversed completion order so an offline verifier proves 'this is the council that happened', not merely 'nobody edited the file' (daedalus/structcore/graph.py:60, daedalus/council/bus.py:572).
- A measurement taken under load is wrong, not slow — check the process count first — and every number carries a [MEASURED]/[INHERITED]/[ASSUMED] stamp, because your own prior session's handoff is the most invisible inherited context there is (.claude/AGENT_PROTOCOL.md:98-136).
- A green suite is not evidence: every guard kept must have a test that goes red when THAT guard is disabled, verified by actually disabling it — three guards in worktree.py were measured surviving their own deletion (docs/HANDOFF.md:25-30).
- Free models may propose, never merge: `drafts apply` prints a review packet, spine/attempt.py defines no apply path, and promotion is a separate human act with no --apply flag (daedalus/kairos/drafts.py, daedalus/spine/picker.py:816).

Source: `docs/architecture-map.html` §“Die Invarianten”, each line citing
its own file:line; the standing orders behind them are in
`.claude/AGENT_PROTOCOL.md` and `docs/HANDOFF.md:25-30`.

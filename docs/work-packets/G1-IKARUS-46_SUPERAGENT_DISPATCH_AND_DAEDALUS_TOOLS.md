# G1-IKARUS-46 — Ikarus uses Daedalus: act-shaped chat turns reach the computer loop, and the loop can observe the project

Packet ID: `G1-IKARUS-46`
Artifact role: `primary`
Status: `built; packet suites green; mutation table 14/14 caught; one live loop run retained; independent review pending; not promoted`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `aae675f463d8334d09fa0f1fbd74fb30979280fc`
Dependencies: `G1-IKARUS-36 (bounded voice), G1-IKARUS-43 (owner-chosen planner), G1-IKARUS-24/25 (handle-anchored workspace files), G1-ARIADNE-10 (leakage boundary as code)`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion and Gate transition are
forbidden. This packet opens no new effect entrypoint, adds no host mutation,
and changes no default: a fresh `/computer setup` still grants no tool.

Owner instruction (2026-09-10, verbatim, three messages): *"bitte mach Ikarus
zu einem echtem Jarvis/Hermes zur Zeit ist das ein beschissener chatbot der
sich weigert daedalus zu benutzen"*; *"doch auch Mutationen der soll sich
selbst verbessern und code generation starten können"*; *"Genesis und Ariadne
sollen Teil des Daedalus Kernels sein Ikarus ist sein interface, quasi ein
SuperAgent"*. This packet is the first of the sequence that instruction
starts (see "Sequence" below); it is the part that needs no new trust surface.

## Primary acceptance claim

**One** claim: *an act-shaped chat message ("verbessere Daedalus", "build a
settings dialog", a typed "ja" answering such an offer) is executed by the
canonical computer loop — observe, propose, admit, act, verify under the
owner's computer policy and planner — instead of ending as a chatbot answer
or a queue proposal into the local Ollama single shot; and that loop can, for
the first time, observe the registered project through five read-only
`daedalus.*` tools.*

Measured before this packet `[MEASURED 2026-09-10, origin/main aae675f4,
this host]`:

| message | classify | may_act | route | what the owner got |
| --- | --- | --- | --- | --- |
| `verbessere Daedalus` | `chat` | not allowed, not suspected | chat | a Claude voice answer about Daedalus (no action) |
| `mach den Parser robuster` | `enqueue` | allowed | enqueue | `queue_task` offer onto lane `local_only` (one Ollama generation over a slice) |
| `/computer status` on this host | — | — | computer | "unavailable until its owner policy is configured" |
| computer loop tool families | — | — | — | `file.*`, `vision.*`, `desktop.*`, `app.launch`, `browser.*` — nothing that reads Daedalus or a project |

After `[MEASURED 2026-09-10, worktree packet/g1-ikarus-46-daedalus-tools-20260910]`:

| message | classify | may_act | route | what the owner gets |
| --- | --- | --- | --- | --- |
| `verbessere Daedalus` | `enqueue` | allowed (`leading German act verb 'verbessere'`) | enqueue | with a configured loop: `computer_task` offer naming planner, tools and the exact `/computer run …` message; without one: the unchanged `queue_task` offer |
| `ja` (next turn) | `chat` | confirmation of that objective | enqueue → `/computer run verbessere Daedalus` | the loop runs and streams progress; the report is the answer |
| `kannst du Daedalus verbessern?` | `enqueue` | refused, suspected | chat | the confirm offer, as before — a question still runs nothing |
| `/computer run status` | — | — | computer | the OBJECTIVE "status" runs as a task; it is not the status subcommand |
| `/computer enable daedalus` | — | — | computer | the five read-only tools are granted through `configure_computer` with the current policy digest |

## Scope

In scope (files changed):

- `daedalus/orchestration/ikarus/act.py` — German imperatives `verbesser(e)`,
  `erweiter(e)`, `ergänz(e)`/`ergaenz(e)`, `korrigier(e)`, `entwickel`/`entwickle`,
  `programmier(e)` in `_GERMAN_ACT`; their infinitives in `_GERMAN_REQUEST_FORMS`;
  English `improve`, `extend`, `develop` in `ACT_VERBS`. The allow rule itself
  (first significant word, exact imperative, not interrogative) is unchanged.
- `daedalus/orchestration/ikarus/shell.py` — `classify` learns the three
  English keywords; `_computer_hand(project)` (the loop's capability for this
  project through `computer_status`, never raising, no network);
  `_computer_offer` (the `computer_task` proposal with `act_offer`);
  `_confirmed_computer_run` (a CONFIRMATION with an available loop maps to
  `/computer run <objective>`); the blocking and streaming routes take that
  message through `conversation_events`, the same door `/computer` uses.
- `daedalus/orchestration/ikarus/computer_loop.py` — `RUN_VERB`,
  `run_command`, `_run_objective`, `project_readers()`; `/computer run
  <objective>`, `/computer enable|disable daedalus`; `ComputerService(...,
  project=, project_readers=)` and `computer_status(..., project=,
  project_readers=)` receive the conversation's project and the status/bridge
  readers built in this layer (the runtimes package must not import
  `daedalus.status` or `daedalus.file_bridge`: the SCC census measured the
  runtimes<->orchestration cycle growing 19 -> 20/21 when it did, so the
  readers are injected and `runtimes.computer_daedalus` names no module of
  that cycle — pinned by `test_the_adapter_names_no_module_of_the_computer_import_cycle`
  and the census digest, which is unchanged); `_READ_TOOLS` gains the family
  (identical observations stall, as for every read tool); the status text
  lists the three new commands.
- `daedalus/kernel/policy/computer.py` — `DAEDALUS_TOOLS` and its membership
  in `ALL_COMPUTER_TOOLS`.
- `daedalus/runtimes/computer.py` — `TOOL_SPECS` rows; `project` on the
  service; the family is reported unavailable and refused before any lease
  when no project is bound; `_HOST_MUTATION_TOOLS` named explicitly with an
  import-time assertion that the family is disjoint from it;
  `filesystem_scope_kind: project-registry-read-only`; a typed refusal inside
  the family is `blocked` (provably effect-free), an unknown error stays
  `reconciliation_required` like every other adapter.
- `daedalus/runtimes/computer_daedalus.py` (new) — the adapter:
  `planner_lane`, `DaedalusObservation` with the five observations, bounds
  (`SLICE_MAX_TOKENS 6000`, `MAX_TEXT_CHARS 24000`, `TOP 10`, git timeout 15 s).
- Cockpit: `apps/web/src/shared/contracts/index.ts` (`IkarusAskAction` union),
  `features/conversation/model.ts` (`offerSubject`: executable only through a
  server-named `/computer run` message; planner line; tool list),
  `Conversation.tsx` (`runAction` sends that message as a chat turn through
  a ref to `sendMessage`; no bus request), `OfferConfirm.tsx` (three rows:
  Ausführung, Planner, Werkzeuge), `commands.ts` (help line).
- Tests: `tests/runtimes/test_computer_daedalus.py` (new, 33),
  `tests/test_ikarus_computer_dispatch.py` (new, 24); pins in
  `tests/runtimes/test_computer_evidence_terminal.py` (the vocabulary now has
  the `daedalus` family), `tests/test_ikarus_shells.py` and
  `tests/test_ikarus_os.py` (`_computer_hand` pinned to "no loop" for the
  queue-route modules), three `computer_status` stubs that gain the
  `project` keyword; `apps/web/src/features/conversation/conversation.spec.ts`
  (five checks).
- Docs: `docs/IKARUS_COMPUTER.md` (one section), this packet, the registry
  index and its pins, the s02 corpus re-measure.

Out of scope, deliberately (each is the next packet, named in "Sequence"):
a Genesis offer from the chat; an Ariadne self-Renovation campaign tool; a
terminal/test-runner tool; any tool that writes to a project tree; changing
the default planner or granting any tool at setup; the SYSTEM prompt of the
voice; moving `daedalus/ariadne` or `daedalus/orchestration/genesis` under
`daedalus/kernel` (the owner's "part of the kernel" is read as *reachable
through the kernel's doors*, which is what this sequence builds; a package
move is a separate mechanical packet if the owner wants it literally).

## Contracts and behavior

- **Two answers, one door, unchanged.** `classify` still decides only the
  affordance; `may_act` still decides capability with the same allow rule;
  `_route` is untouched. Nothing reaches `_enqueue` that `may_act` did not
  allow, and `_enqueue` is still the only door to the Hand shell.
- **The loop is offered, not entered.** `_enqueue` proposes a
  `computer_task` when `_computer_hand(project)` is not None. The proposal
  carries `action.args.message == run_command(objective)`, the planner
  facts, the tool names, `requires_confirmation: True`, and an `act_offer`
  naming the objective. It runs nothing.
- **Confirmation = the same command route.** A typed affirmative on the next
  turn is cleared by `may_act` as a confirmation of that objective (the
  existing act module, unchanged); `_confirmed_computer_run` maps it to
  `/computer run <objective>` only when the loop is still available;
  `_ask_inner` returns the loop's final envelope, `_ask_stream_inner` streams
  its `start`/`progress`/`final` frames. The cockpit's click sends the very
  same message as a chat turn. An UNCONFIRMED imperative never runs the loop.
- **`/computer run <objective>`** executes the objective verbatim; the
  subcommand table is not consulted. `/computer run` alone is refused before
  a service exists.
- **`/computer enable|disable daedalus`** adds or removes exactly the five
  names through `configure_computer(root, payload, owner_confirmed=True,
  expected_policy_sha256=<current digest>)`; a missing policy points to
  `/computer setup`; any other argument is refused.
- **The family is read-only by construction.** `host_mutation` is False on
  every retained result, `filesystem_scope_kind` is
  `project-registry-read-only`, `_HOST_MUTATION_TOOLS ∩ DAEDALUS_TOOLS = ∅`
  is asserted at import and pinned by test. No observation writes, moves,
  launches or sends; `daedalus.status` runs `collect_status` (the existing
  git counters) and `bridge_status`; no repository root reaches the planner.
- **Project binding is a registry name.** The service holds the
  conversation's project NAME; `resolve_repo_root(None, name)` resolves it at
  use through the project registry; an unknown row is a refusal. A session
  without a project (scheduled tasks, `computer_status` without one) reports
  the family unavailable and refuses execution before any lease.
- **Egress lane, decided once.** `planner_lane` mirrors `shell._llm`: a
  loopback Ollama (via `sensitivity.lane_for_host` on the raw `OLLAMA_HOST`)
  and the Claude CLI are `trusted`; Codex and DeepSeek are `untrusted`;
  `allow_remote_context` never promotes a destination. `daedalus.slice` calls
  `semantic_slice(..., lane=<that lane>, policy=<the project's sensitivity
  policy>)`, so the untrusted lane gets only what the default-deny allow-list
  admits, and the unconditional secret floor runs inside the slice, again on
  every result in `ComputerService.execute`, and on every prompt
  (G1-IKARUS-43) before any planner sees it.
- **Bounds.** One slice ≤ 6 000 tokens of neighbourhood and ≤ 24 000 chars of
  text (elision reported as `text_elided`); lists cut to 10 rows with the cut
  reported; module names resolve only inside the index (exact or unique
  basename; ambiguity lists candidates; nothing outside the index exists).

## Acceptance matrix

| Check | Command | Result `[MEASURED 2026-09-10]` |
| --- | --- | --- |
| packet and neighbouring suites (final tree) | `python -m pytest -q tests/runtimes/test_computer_daedalus.py tests/test_ikarus_computer_dispatch.py tests/test_ikarus_computer_loop.py tests/test_ikarus_computer_loop_adversarial.py tests/test_ikarus_stream.py tests/runtimes/test_computer_service.py tests/runtimes/test_computer_evidence_terminal.py tests/test_ikarus_act.py tests/test_ikarus_os.py tests/test_ikarus_shells.py tests/test_ikarus_computer_schedule.py tests/test_ikarus_computer_schedule_autonomy.py` | 366 passed, 99 subtests |
| broad regression (`tests/runtimes tests/interfaces tests/test_ikarus_*.py tests/test_conversation_*.py tests/test_queue_dispatch_identity.py tests/test_llm_client.py tests/contracts tests/orchestration`) | run once before the reader injection and the stream pin | 2661 passed, 122 skipped, 14 xfailed, 3 failed: two were this packet's (the stream module's host-dependent `lane` and the census count/cycle) and are fixed above; `test_plan_and_replan_are_advisory_mission_bound_artifacts` fails identically on the untouched primary checkout (`tmp` path spelling on this host) — baseline, not this packet |
| pins | `tests/contracts/test_import_scc_hierarchy.py tests/contracts/test_work_packet_index.py experiments/forest_v2/s02_types/test_external_corpora.py tests/test_imports_graph.py` | see the pins row below |
| cockpit | `tsc --noEmit`; `node src/app/run-spec.mjs` | clean; 620/620 (615 before + 5) |
| mutation table | `runs/jarvis-20260910/mutate.py` (14 guards disabled one at a time) | see "Mutation table" |
| live loop run | see "Live measurement" | see "Live measurement" |
| vocabulary tripwire | `tests/runtimes/test_computer_evidence_terminal.py` | passes with the `daedalus` family named; no `run/exec/spawn/shell` name, no interpreter |

### Mutation table

`[MEASURED 2026-09-10]` One guard disabled at a time by exact-string edit,
the four packet suites run, the file restored from memory (never via git);
the restored tree is green (104 passed). Script and raw output retained in
`docs/evidence/G1-IKARUS-46/mutate.py.txt` and `mutation-table.txt`.

| # | guard removed | caught by |
| --- | --- | --- |
| M1 | a daedalus tool added to `_HOST_MUTATION_TOOLS` | import-time assertion (1 error) |
| M2 | `_enqueue` ignores an available loop | 4 dispatch tests (offer shape, German/English wording, unconfirmed-never-runs) |
| M3 | a confirmation never runs the loop | `test_a_typed_confirmation_runs_the_offered_objective`, streaming twin |
| M4 | the offer's message drifts from `run_command` | `test_an_act_request_is_offered_as_a_computer_task` |
| M5 | Codex/DeepSeek planner treated as trusted | 4 lane tests incl. `test_the_slice_goes_through_the_untrusted_gate_for_a_remote_planner` |
| M6 | module resolution accepts any path | the two traversal cases (`../../../etc/passwd`, `C:/Windows/system.ini`) |
| M7 | a refused read filed as reconciliation | `test_a_refused_read_is_effect_free_not_reconciliation` |
| M8 | the family offered without a project | `test_without_a_project_the_family_is_reported_unavailable_and_never_leased` |
| M9 | `/computer run` parses subcommands again | `test_run_executes_the_objective_even_when_it_names_a_subcommand`, `…blocked_before_any_service` |
| M10 | `enable` ignores the current policy digest | `test_enable_adds_the_family_through_compare_and_replace` |
| M11 | `verbessere` dropped from the act verbs | 3 dispatch tests |
| M12 | slice text unbounded | `test_slice_text_is_bounded_and_the_elision_is_reported` |
| M13 | no `act_offer` on the computer offer | `test_an_act_request_is_offered_as_a_computer_task` |
| M14 | streaming confirmation queues instead of running | `test_the_streaming_confirmation_streams_the_loop_and_classifies_once` |

### Live measurement

`[MEASURED 2026-09-10 12:23–12:25, this host, worktree authority root, control
root ~/.daedalus/control/717d5ee9e64f, scratch ledgers under
runs/jarvis-20260910/, other sessions' suites running on the box]`

Setup, all through `ikarus_os.ask("agent_env", …)` with no model call:
`/computer setup` (fresh policy, no tools) → `/computer enable daedalus`
(five tools, policy `819490ad…`) → `/computer planner claude_code_cli
confirm-remote` (warning shown first without the flag; policy `62e21d33…`).

The natural-language offer, no model call, deterministic, 0 s:
`ask("agent_env", "verbessere Daedalus")` → `intent enqueue`,
`action.kind computer_task`, `action.args.message "/computer run verbessere
Daedalus"`, `act_offer.objective "verbessere Daedalus"`; the reply names
`claude_code_cli`, "Beobachtungen verlassen den Rechner" and the five tools
(`docs/evidence/G1-IKARUS-46/live-offer.json`).

Three runs of the same objective (*"Prüfe den Zustand von Daedalus: lies den
Status, die Struktur und die kaputten Doku-Referenzen des Projekts und fasse
in drei Sätzen zusammen, was als Nächstes verbessert werden sollte."*) through
`/computer run …`, retained in order, failures included:

| run | planner | terminal | planner calls | tool steps | elapsed | what happened |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `codex_cli` | `blocked` | 1 | 0 | 4.6 s | `codex.cmd exec` returned nothing: the owner's `~/.codex/config.toml` names `gpt-6-astra`, which codex-cli 0.152.0 refuses ("requires a newer version of Codex"); the ledger still booked the flat `openai_cli` worst case of $2.00 for a 4-second failure |
| 2 | `claude_code_cli` | `blocked` | 1 | 0 | 0.08 s | the planner spawn was refused by the process guard: a medium-effort Claude call reserves $3.00 (= the flat worst case, since `1.00 × 3 ≥ 3.00`) and the scratch ledger already held $2.16 from run 1 and two accidental voice turns; nothing spawned |
| 3 | `claude_code_cli` | **`completed`** | 5 | 3 | **64.5 s** | plan (2 steps) → `daedalus.status` → `daedalus.structure` → `daedalus.docrefs` → finish; every step `ok`, none withheld; `task_success_verified: False` as designed |

Run 3 in numbers: prompt max 21 197 chars; ledger 5 × reserve $3.00 →
settled $0.0696 / $0.0696 / $0.0816 / $0.1053 / $0.1121 = **$0.438** for the
mission (`live_run_ledger_rows` in `acceptance.json`); observations: 682
files, 79 unit clone clusters, 134 broken doc references over 821 scanned
files. The planner's three-sentence conclusion names the dirty packet tree,
the `shell.py`/`offload_lease.py` hotspots and the broken references in
`docs/ABSORPTION.md`, ADRs 011/016 and `ARCHITECTURE_BASELINE_20260825.md`;
the fabrication detector (G1-IKARUS-44) flags `270k` and `011/016` as tokens
no observation contains — retained, not edited.

Two defects found by run 3 and fixed after it, both host paths reaching the
planner prompt: the `daedalus.status` observation carried `todo_snapshot`
(an absolute path from `collect_status`), and the `daedalus.structure`
observation carried `ignored.source` (the absolute path of the ignore file).
The adapter now drops every absolute-path value in the git block by shape
(`_looks_like_host_path`) and projects `ignored` to `{count, patterns}`;
pinned by `test_status_observation_drops_every_absolute_path_value_by_shape`,
`test_host_path_shape` and the scratch-repository structure/slice test, which
now asserts that the repository path appears nowhere in either observation.
The retained run-3 report is the evidence of the run that found them; the
evidence copy is scrubbed of this host's paths (`<worktree>`, `<home>`), the
raw file is not.

Observations for later packets, not changed here: (a) a failed Codex spawn
books its flat $2.00 worst case because the text-mode CLI reports no cost —
the same shape G1-IKARUS-36 fixed for Claude; (b) the loop's planner call is
`effort="medium"`, whose reservation equals the $3.00 worst case, so under the
default $5.00 ceiling one prior unsettled worst case is enough to refuse it —
sequential calls work because each settles at its measured cost.

## Evidence, expected failures and review

Evidence lives in `docs/evidence/G1-IKARUS-46/` (acceptance.json with the
suite counts and SHA-256s, the mutation table, the live-run report, the two
s02 corpus probes). Expected failures, retained rather than tuned away:

- the pre-existing `test_plan_and_replan_are_advisory_mission_bound_artifacts`
  failure on this host (identical on the untouched primary checkout);
- the first draft of `tests/test_ikarus_computer_dispatch.py` spawned the
  real Claude voice once (an English imperative outside `ACT_VERBS` fell
  through to `_chat`); fixed by pinning the voice in `setUpModule` and by
  adding the English verbs — the spawn is recorded here, not hidden;
- two Claude voice turns were spent by accident during the live setup when
  MSYS path conversion rewrote `/computer planner …` into
  `C:/Program Files/Git/computer planner …` before it reached `ask()`; the
  repeat with `MSYS2_ARG_CONV_EXCL='*'` reached the command route. Both turns
  are on the scratch ledger, not the owner's.

Review questions for the independent reviewer (Cerberus for egress, Odysseus
for the guards): (1) can any argument shape of `daedalus.slice` read a file
outside the index? (2) does any daedalus.* result reach a Codex/DeepSeek
planner without the untrusted gate? (3) can a `computer_task` action carry a
message the cockpit would send that is not a `/computer run`? (4) does a
typed "ja" ever run an objective other than the one offered? (5) is there a
path from an UNCONFIRMED imperative to `conversation_events`?

### Refusals kept, and where they are pinned

- a question is not a run: `OfferTest.test_a_question_still_gets_no_offer_of_a_run`;
- an unconfirmed imperative is not a run: `ConfirmationTest.test_an_unconfirmed_imperative_never_runs_the_loop`;
- a confirmation without a loop is the old queue offer: `test_a_confirmation_without_a_loop_falls_back_to_the_queue_offer`;
- a decline runs nothing: `test_a_decline_runs_nothing`;
- no project, no lease: `test_without_a_project_the_family_is_reported_unavailable_and_never_leased`;
- an ungranted daedalus tool is refused by policy before the adapter: `test_policy_admission_still_refuses_an_ungranted_daedalus_tool`;
- Codex/DeepSeek never trusted, remote context never promotes: `test_planner_lane_trusts_only_this_machine_and_the_claude_cli`, `test_allow_remote_context_does_not_promote_a_remote_planner_to_trusted`;
- nothing outside the index resolves: `test_module_resolution_refuses_ambiguity_and_everything_outside_the_index`;
- a crash inside a read stays reconciliation: `test_a_crash_inside_a_read_stays_reconciliation_required`;
- the cockpit executes a computer task only through a server-named `/computer run` message: `conversation.spec.ts` "a computer task without a run message is not executable".

## Residual risks and honest limits

- The loop still cannot MUTATE a project tree. "Verbessere Daedalus" now ends
  in an observed report with the planner's proposal; applying a change is the
  next packet (an Ariadne self-Renovation campaign tool, nominating only) and
  the Renovation ignition obligation, not this one.
- The planner default stays local Ollama. With a 7B planner the measured
  negative evidence (G1-IKARUS-26/43) stands: it rarely finishes. The owner
  chooses `/computer planner claude_code_cli confirm-remote` (or Codex) per
  G1-IKARUS-43; the offer names which planner will run and whether
  observations leave the machine.
- `daedalus.structure` builds the structcore index on first use; on this
  checkout that is seconds, on a large project it is longer and counts
  against the mission wall time. The checkpoint runs before and after.
- `daedalus.tasks` reads the file-bridge inbox projection and the default
  spine DB read-only while the loop's own writer is open; SQLite WAL admits
  that. A scheduled (project-less) task cannot use the family at all.
- A cockpit confirmation sends a NEW turn (`/computer run …`); the offer turn
  keeps `offerOutcome` "Computer-Auftrag gestartet · …". Durable turn
  attribution of that run to the offer turn (the bus path's
  `conversation_link`) does not exist for computer tasks yet.

## Sequence (the owner's instruction, packet by packet)

1. **G1-IKARUS-46 (this):** act verbs; natural-language → computer loop;
   read-only `daedalus.*` observations. No new trust surface.
2. **G1-IKARUS-47:** kernel-strand offers from the chat — `genesis_build`
   (POST `/api/genesis`, the existing owner-directed Genesis door; "code
   generation starten") and a `daedalus.ariadne_campaign` loop tool that
   clones the project at HEAD under the control root and runs the canonical
   `run_campaign` (three arms, frozen evaluator, leakage boundary of
   G1-ARIADNE-10, nomination only; "sich selbst verbessern"). Cerberus
   BLOCKING review: it is the first chat-reachable path to a candidate.
3. **G1-IKARUS-37:** `terminal.run` with an argv allowlist (forward plan C3),
   so the loop can run the project's registered `test_command` and VERIFY
   instead of trusting a finish. Largest trust surface; Cerberus BLOCKING.
4. **G1-SELF-02:** the model operator inside the campaign (forward plan D1/D3)
   once 2 and 3 exist.

Promotion of any candidate stays sealed (plan invariant 5); none of these
packets changes that, and the owner's "Mutationen" are candidate trees plus
nominations, applied by the owner.

## Migration and rollback

Migration: none for existing installations. An owner who wants the family
runs `/computer enable daedalus` once per authority root; nothing is granted
by upgrade. Existing `queue_task` offers, the bus, and every scheduled task
behave as before.

Rollback: revert the packet commit. The policy schema is unchanged (the
five names are ordinary `tools` entries), the spine and CAS shapes are
unchanged, and a policy that names the family after a revert is refused by
`ComputerPolicy.__post_init__` ("tools must be unique known computer tools")
exactly like any unknown tool — visibly, never silently.

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: the acceptance matrix above; `docs/evidence/G1-IKARUS-46/`.

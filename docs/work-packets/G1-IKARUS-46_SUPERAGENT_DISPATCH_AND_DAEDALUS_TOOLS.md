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
| packet, neighbouring and pin suites (final tree, after review round 3) | `python -m pytest -q tests/runtimes/test_computer_daedalus.py tests/test_ikarus_computer_dispatch.py tests/test_ikarus_computer_loop.py tests/test_ikarus_computer_loop_adversarial.py tests/test_ikarus_stream.py tests/runtimes/test_computer_service.py tests/runtimes/test_computer_evidence_terminal.py tests/test_ikarus_act.py tests/test_ikarus_os.py tests/test_ikarus_shells.py tests/test_ikarus_computer_schedule.py tests/test_ikarus_computer_schedule_autonomy.py tests/contracts/test_import_scc_hierarchy.py tests/contracts/test_work_packet_index.py experiments/forest_v2/s02_types/test_external_corpora.py tests/test_imports_graph.py` | **470 passed, 4 skipped, 103 subtests** (before round 1: 366 passed in the twelve-suite subset; after round 2: 453) |
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
| M15 | the path gate admits everything (review round 1) | `test_a_project_whose_policy_row_cannot_load…`, the status/structure/docrefs gate tests |
| M16 | the text gate ignores `deny_content` | `test_structure_rows_go_through_the_path_gate`, `test_task_reports_go_through_the_content_gate` |
| M17 | the index is built with effects | `test_the_index_is_built_effect_free` |
| M18 | docrefs errors returned verbatim | `test_docrefs_rows_go_through_the_gate_and_errors_are_a_count` |
| M19 | enable with a remote planner needs no confirmation | `test_enable_with_a_remote_planner_needs_a_transient_confirmation` |
| M20 | an unreadable project row gets the generic policy | `test_a_project_whose_policy_row_cannot_load_is_refused_not_generic` |
| M21 | the lane is frozen at construction | `test_the_lane_is_derived_per_call_not_at_construction` |
| M22 | a question's offer confirms into a run | `test_a_question_s_offer_confirms_into_a_proposal_never_a_run` |
| M23 | the offer's policy digest is not bound to the run | `test_a_confirmation_against_a_changed_policy_re_offers_instead_of_running` |
| M24 | embedded host paths pass the text gate | `test_a_task_summary_with_an_embedded_host_path_is_withheld` |

Second table (after review round 1, `docs/evidence/G1-IKARUS-46/mutation-table-2.txt`):
24 applied, **24 caught**, restored tree green (140 passed in the four packet
suites). The driver now restores bytes, not text, so it can no longer move
the byte-pinned modules itself.

Final table (after review round 2, `mutation-table-4.txt`): the 24 above plus
M25 (`_admit_rows` fail-open for a row without path or text), M26 (the grant
sentence claims the deny list on the trusted lane), M27 (`deny_content` no
longer sees the path itself), M28 (kept fields outside the text keys not
gated), M29 (the embedded-path shapes shrink back to the root-name list) —
**29 applied, 29 caught**, restored tree green (158 passed in the packet
suites).

After review round 3 (`mutation-table-6.txt`): plus M30 (egress decided by
provider name, not host), M31 (ignore patterns ungated), M32 (slice withheld
rows name the file), M33 (slice gate rules quote the marker) — **33 applied,
33 caught**, restored tree green (181 passed in the packet suites). M32 was
not applied in the first pass because its anchor had moved to `_redact_rule`;
it was re-run alone with the same driver after the anchor fix, and the table
records both passes. Table 5 is superseded and not retained.

After review round 4 (`mutation-table-7.txt`): plus M34 (status gates str
values only), M35 (the ambiguity refusal lists raw paths), M36 (leaving the
machine decided by the lane), M37 (`focus_file` ungated), M38 (the flattener
drops sets, keys and objects), M39 (the TOP bound truncates silently), M40
(the withheld block keeps the slicer's breadcrumbs); M5, M30, M32 and M33
re-anchored on the moved lines — **40 applied, 40 caught** (restored tree
green, 196 passed in the packet suites).

After review round 5 (`mutation-table-8.txt`, the loop suite added to the
driver): plus M41 (the report line follows the consent flag again), M42 (a
local planner never leaves, whatever its host), M43 (the offer sentence
follows the consent flag again), M44 (an exact withheld path confirms its
existence), M45 (tasks bounded before the gate), M46 (the rebuild splits at
the first header), M47 (an unrenderable value is admitted); M6, M34, M38 and
M40 re-anchored — **47 applied, 47 caught** (M37 and M43 survived the first
pass as untested guards, got pins and were re-run alone).

After review round 6 (`mutation-table-9.txt`): plus M48 (the raw value is
emitted instead of the gated rendering), M49 (a producer failure passes its
message through), M50 (the ambiguity refusal counts the withheld again), M51
(the structure counters bypass the gate) — **51 applied, 51 caught**.

After review round 7 (`mutation-table-10.txt`): plus M52 (clone rows copied
raw again), M53 (the registry refusal carries the message), M54 (host paths
inside the slice text pass), M55 (one admitted candidate is announced as
ambiguous), M56 (producer-chosen row keys pass ungated); M18 and M20
re-anchored — **56 applied**; result recorded in
`docs/evidence/G1-IKARUS-46/acceptance.json` (`mutation_table`).

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
| 4 (after the Cerberus repairs) | `claude_code_cli` | **`completed`** | 5 | 3 | **52.2 s** | same objective, same three observations, now each stamped `lane: trusted` and gated: `fan_in_withheld: 2` (two fan-in modules withheld by the secret floor on the trusted lane), `hotspots_withheld 0`, `clones_withheld 0`, `broken_withheld 0`, `errors_count 0`; settled $0.0696 / $0.0695 / $0.0742 / $0.0895 / $0.1072 = **$0.410**; the only absolute path left in the retained report is the loop's own `authority_root` field, which is not part of any observation or prompt (pre-existing loop shape) |

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

### Independent review round 1 (2026-09-10) and what it changed

**Cerberus — verdict `block`** on commit `002c0683`, every finding accepted
and repaired in the follow-up commit:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| CRITICAL 1 | only `daedalus.slice` went through the project's egress gate; `status` (the whole `git status --short`), `structure` (hotspot/clone/fan-in paths), `docrefs` and `tasks` reached an untrusted planner with `policy.deny` and `deny_content` never consulted, and the content-only secret floor never saw the observed paths | every observation now passes `sensitivity.slice_egress_rule` per row on the planner's lane (`_admit`, `_admit_rows`) and path-less texts pass the floor plus `deny_content` (`_admit_text`); withheld rows are counted | `test_status_lines_go_through_the_project_gate_on_the_untrusted_lane`, `…keep_the_project_paths_but_floor_secrets_on_the_trusted_lane`, `test_task_reports_go_through_the_content_gate`, `test_structure_rows_go_through_the_path_gate`, `test_docrefs_rows_go_through_the_gate_and_errors_are_a_count`; mutations M15/M16 |
| CRITICAL 2 | the grant sentence "they cannot write, launch or send anything" was false | the reply names the observations, the planner and whether they leave the machine; with a remote planner the grant requires `/computer enable daedalus confirm-remote` after a warning that names what leaves | `test_enable_adds_the_family_through_compare_and_replace`, `test_enable_with_a_remote_planner_needs_a_transient_confirmation`; mutation M19 |
| MAJOR 1 | `cached_index` wrote and evicted the SQLite cache under the profile, spawned a process pool and ran `git log` under a `host_mutation: False` receipt | the index is built `effect_free=True`; the docstring and the grant text say which read-only git commands run | `test_the_index_is_built_effect_free`; mutation M17 |
| MAJOR 2 | `docrefs.errors` carried the absolute path of an unreadable doc file | only `errors_count` is observed | `test_docrefs_rows_go_through_the_gate_and_errors_are_a_count`; mutation M18 |
| MAJOR 3 | the `confirm-remote` warning listed a narrower set than now travels | `_remote_planner_warning` names the Daedalus observations; the enable warning names them too | `test_the_remote_planner_warning_names_the_daedalus_observations` |
| m-1 | `withheld` cut to 10 rows without a count | `withheld_elided` | (shape) |
| m-2 | the lane was frozen at construction | `lane` is derived per call | `test_the_lane_is_derived_per_call_not_at_construction`; mutation M21 |
| m-3 | `/computer enable daedalus` synthesized `owner_confirmed` from one message with a remote planner | see CRITICAL 2 | as above |
| m-4 | an unreadable project row fell back to the generic policy | refused | `test_a_project_whose_policy_row_cannot_load_is_refused_not_generic`; mutation M20 |

Cerberus also refuted, with evidence, seven worries that stand as evidence for
the design: `allow_remote_context` is the master switch and never promotes a
lane; the cockpit cannot compose its own run message; no unconfirmed
imperative reaches `conversation_events`; `/computer run` cannot be re-parsed
into a subcommand; no ledger or spend fact enters the observations; no
credential *values* leave (the finding was reconnaissance-grade, which is why
the gate now covers paths, not only bytes).

**Odysseus — adversarial verification of `002c0683`** (re-executed against a
pristine `git archive` copy because this worktree was being repaired
mid-review). Six confirmed defects; 1–3 coincide with Cerberus and were
repaired as above (Odysseus's probes `a1_effects.py`, `a12_egress_gate.py`
re-run green on the repaired tree); 4–6 are this round's additions:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| 4 | a QUESTION's offer (`_act_offer`, "…ein bestätigungspflichtiger Auftrag…") is the only offer a bare "ja" could confirm, and that "ja" now RAN the loop with the question text as objective — the promised second gate was gone | `_confirmed_computer_run` runs only when the previous turn's offer carries `signal: computer_task`; a question's "ja" yields the `computer_task` PROPOSAL (panel, own gate); `_act_offer` names the computer loop when it is available | `test_a_question_s_offer_confirms_into_a_proposal_never_a_run`, `test_the_question_offer_names_the_computer_loop_when_it_is_available`; mutation M22 |
| 5 | planner, tools and `policy_sha256` shown in the offer were not bound to the run: a policy change (`/computer planner …`, `/computer enable …`, the settings page) between offer and "ja" ran under the new policy | the offer's `act_offer` carries `policy_sha256`; a confirmation whose digest no longer matches the loop's re-offers with "Die Computer-Policy hat sich seit dem Angebot geändert" instead of running | `test_a_confirmation_against_a_changed_policy_re_offers_instead_of_running`; mutation M23 |
| 6 | the commit stored four `-text` byte-pinned modules (`computer.py`, `shell.py`, `act.py`, `computer_loop.py`) with CRLF, moving `_SOURCE_REVISION`/`_SOURCE_SHA` for every computer lease with no code reason and making the review diff unreadable | LF bytes restored before the follow-up commit; `git show <commit>:<file> \| grep -c $'\r'` is 0 for all four (recorded in the acceptance record) | the `-text` pins in `.gitattributes`; `tests/test_byte_pin_eol_durability.py` does not see these two modules (its marker misses the frozen-executable ternary) — named here as a residual for the byte-pin packet, not fixed in this one |
| 3′ | `daedalus.tasks` could carry a host path EMBEDDED in a report's error summary; the whole-value shape check missed it | `_mentions_host_path` (drive, UNC, POSIX home/system roots inside text) refuses the row in `_admit`/`_admit_text` | `test_embedded_host_paths_are_detected`, `test_a_task_summary_with_an_embedded_host_path_is_withheld`; mutation M24 |
| (test gap) | the service half substituted a fake adapter, so no test observed the real adapter under the real lease | `test_the_real_adapter_through_the_real_lease_creates_no_cache_and_launches_no_pool` runs all four repository observations through `ComputerService.execute` with a fresh `DAEDALUS_CACHE_DIR` and asserts it stays empty | — |
| (mutation survivors) | M1 import-time assertion not load-bearing (its subject is pinned by a test), M14 `_dispatch` refusals dead behind admission, M25 `/computer enable <other>` unpinned | M14 and M25 pinned directly (`test_dispatch_refuses_the_family_directly_without_a_project_or_readers`, the `enable` argument subtests); M1 left as a comment-grade assertion | — |

Odysseus refuted, with 39 hostile argument shapes, junction planting,
18-message reachability runs and a real control root: no `daedalus.slice`
argument resolves outside the index; structcore does not descend a junction;
no non-`/computer run` message can become executable in the cockpit; a "ja"
cannot confirm across conversations, from a `queue_task` envelope, or a stale
offer older than the previous turn; no unconfirmed imperative or question
reaches `conversation_events`; `/computer enable daedalus` adds exactly the
five names under the live digest and refuses a concurrent policy write. One
residual it named and this packet leaves: `pending_offer` has no expiry — a
"ja" is a confirmation as long as the offer is the immediately preceding
turn, however old.

### Independent review round 2 (2026-09-10, on `96e190d2`)

**Cerberus — `needs_fix`, no CRITICAL stands, block lifted.** All nine
round-1 findings judged resolved with file:line citations; eight new,
one high, repaired in the follow-up commit:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| N1 (high) | both consent texts said the project's egress policy filters every observation, but on the trusted lane (Claude CLI, loopback Ollama) only the secret floor runs — exactly as for the Voice; the operator-facing German was new and false | `_egress_filter_sentence(trusted)` is lane-conditional in the grant reply and the `confirm-remote` warning; the observation list no longer claims a filter | `test_the_grant_sentence_is_true_per_lane` |
| N2 | the real-adapter test asserted nothing about a process pool despite its name | `ProcessPoolExecutor` and `git_churn` are patched to raise inside that test | same test |
| N3 | `_admit_rows` was fail-open for a row naming neither path nor text | such rows are withheld | `test_rows_without_a_path_or_a_text_are_withheld_not_passed` |
| N4 | kept rows carried every producer field, so a future field would join the prompt silently | every kept row is projected to an allow-listed key set (`keep_keys`) | `test_structure_rows_go_through_the_path_gate` (`future_field` dropped) |
| N5 | the project policy was memoised for the adapter's lifetime (a row tightened mid-mission had no effect) | `_project_policy` re-reads the registry row on every call | `test_the_project_policy_is_re_read_on_every_call` |
| N6 | `allow_remote_context: true` with a loopback Ollama said "verlassen den Rechner" | "leaves" requires the flag AND a non-local planner | `test_the_grant_sentence_is_true_per_lane` |
| N7 | `ignored.patterns` read a key the index never emits (always `[]`) | `ignore_patterns`, `count`, `n_files_scanned`; `sample`/`source` never travel | `test_structure_rows_go_through_the_path_gate`, scratch-repository structure test |
| N8 | "nur lesende git-Befehle" is stronger than the fact (`git status` may refresh git's own index) | wording in the grant reply and the module docstring | — |

**Odysseus round 2** (pristine `git archive` of `96e190d2`, byte-verified):
defects 1, 4, 5, 6 RESOLVED with executed evidence (no cache file, no
eviction of 20 planted victims, no pool, only `git branch`/`git status`
launched across all five tools; a question's "ja" → proposal; a changed
digest → re-offer; four blobs at 0 CR bytes); defects 2 and 3 NARROWED, with
three executed residuals, all repaired in the follow-up commit:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| D1 | `_admit_rows` gated only the named keys but handed the whole row on; a task brief's `phase` carried an absolute host path (and, before `keep_keys`, an AWS key in `runtime_id`) to an untrusted planner through the real service | every string in the PROJECTED row is gated, not only the named text keys | `test_kept_fields_outside_the_text_keys_are_gated_too`; mutation M28 |
| D2 | `classify_data` applies `deny_content` to the text argument only, so a codename INSIDE an allow-listed path (`tests/test_odysseuschimera.py`, `docs/ODYSSEUSCHIMERA-plan.md`) passed via `structure`/`docrefs` | `_admit` hands the path itself into the content check (`f"{path} {text}"`) | `test_deny_content_applies_to_the_path_itself`; mutation M27 |
| D3 | `_mentions_host_path` matched a root-name list; `file:///home/…`, `//nas01/…`, `~/…`, `/usr/…`, `/data/…`, `/proc/…`, `%USERPROFILE%\…` passed | the regex matches the SHAPES of an absolute location (drive, UNC in either slash direction, `file://`, `~/`, expanded environment roots, any two-segment POSIX absolute path); `_admit_text` also refuses a whole-value path | `test_embedded_host_paths_are_detected` (20 spellings); mutation M29 |

Odysseus refuted: a forged `computer_task` offer is not chat-reachable (only
`_computer_offer` writes that signal and it always carries the live digest;
a writer into the conversation store is the ledger trust boundary, not this
gate); a `git mv docs/a.md .env` rename line is withheld on both paths; clone
names carrying a codename are withheld. Its round-2 mutation table: 21 rows,
all load-bearing guards caught (M1 benign-redundant, M24 dead behind the
signal check). It also corrected its own round-1 `a13` fixture (top-level
`deny_content` instead of `policy.deny_content`), so that row was a fixture
artifact — the real gap was D2.

### Independent review round 3 (2026-09-10, on `35c6484e`)

**Cerberus — `block`** on one finding, C1, plus two highs, all repaired in the
fourth commit:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| C1 (CRITICAL) | "leaves this machine" and the `confirm-remote` requirement were decided by provider NAME; an Ollama on a tailnet address with `allow_remote_context` set is `untrusted` for the adapter, its observations leave, and the grant said "nichts verlässt ihn" without asking (the configuration `sensitivity.lane_for_host` was written against) | `leaves = planner not local OR lane != trusted`, both derived from the one predicate the adapter uses; the confirmation gates on `leaves` | `test_a_networked_ollama_is_egress_and_needs_the_confirmation`; mutation M30 |
| H1 (high) | fixing the `ignore_patterns` key (N7) turned a dead read into live, ungated egress of exactly the trees a project withholds | each pattern passes the text gate; `ignore_patterns_withheld` counts the rest | `test_ignore_patterns_are_gated_and_counted`; mutation M31 |
| H2 (high, pre-existing) | the slice's `withheld` rows and the slicer's breadcrumb lines enumerate the FILES the gate refused — on the untrusted lane the vendor learns the denied set | only `role` and `rule` travel plus `withheld_count`; breadcrumb file names are scrubbed to `<withheld>` | `test_slice_withheld_rows_name_the_rule_never_the_file`; mutation M32 |
| (d) | `${HOME}/`, `$env:X\`, `C:temp\x`, `smb://host/`, single-segment `/etc`, `/tmp` still passed; the comment claimed `https://` was withheld while it passed | the regex covers brace/PowerShell environment roots, drive-relative spellings, any scheme'd host URL and one-segment POSIX absolutes; the comment is true | `test_embedded_host_paths_are_detected` (31 spellings) |
| (b) | nested lists/dicts of strings in a kept field were not gated; the inline clone projection left `language`/`safety` ungated | `_strings_in` flattens kept values; clone `name`, `language`, `safety` go through the text gate together | `test_nested_strings_in_a_kept_field_are_gated` |

N2 was the two host-path hardenings (`_mentions_host_path(path)` in
`_admit`, `_looks_like_host_path(text)` in `_admit_text`); Cerberus could not
map the label and asked — recorded here. Precision cost it named and this
packet accepts: a root-anchored markdown link (`](/docs/x.md)`) in a broken
reference is withheld and counted, never silently dropped.

**Odysseus round 3** (pinned snapshot of `35c6484e` and of the in-flight
tree): D1 and D2 RESOLVED with the retained probes through the real service;
D3 RESOLVED for the fifteen spellings filed. Four new items, all repaired in
the fourth commit:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| D4 | the D1 repair was type-scoped: a LIST or dict of strings under a kept key (`phase`, `bridge_status`) bypassed the gate through the real service (host path and codename reached the planner; the service's final floor is secret-only) | `_strings_in` flattens every kept value; the codename and the path in a list are withheld | `test_nested_strings_in_a_kept_field_are_gated`, Odysseus `r3_c1`/`r3_c3` re-run |
| D5 | `.daedalusignore` patterns copied verbatim (same as Cerberus H1) | gated and counted | `test_ignore_patterns_are_gated_and_counted` |
| D6 | the slice's gate RULE quotes the marker it fired on (`content matches sensitive marker /CODENAME/`) in the withheld rows AND in the focus refusal line the slicer writes into the text; scrubbing file names alone moved the disclosure | `_redact_rule` replaces the quoted pattern with `/<marker>/` in rows, breadcrumbs and the focus line; the focus file name is scrubbed too | `test_slice_gate_rules_never_quote_the_marker_they_fired_on`; mutation M33 |
| D7 | `~user/`, a non-ASCII first segment, a bare UNC host (`\\nas01`), a drive after a word (`checkoutC:\`) still passed | the regex admits any first segment, `~user/`, a bare UNC host, and a drive anywhere | `test_embedded_host_paths_are_detected` (36 spellings) |
| D8 | the module comment claimed `https://` URLs were withheld while they passed | the code now matches the comment (a scheme'd host URL is withheld) | `test_embedded_host_paths_are_detected` |

**Cerberus round 4** (`a90b61a6`, frozen `git archive` copy): verdict
`needs_fix`, the block lifted, no CRITICAL. C1 RESOLVED with a probe over
thirteen `OLLAMA_HOST` spellings and four planners (`localhost` is refused by
design: the predicate accepts numeric literals only); H1/H2/D6 RESOLVED for the
shapes filed; authority confirmed unwidened (no write, spawn, network or
policy reach in the adapter). Two new `high` findings and one nit.

**Odysseus round 4** (same snapshot, executed probes): D5 and D8 RESOLVED; D7
NARROWED (21 natural spellings blocked; percent-encoded, full-width and
zero-width spellings pass and no producer emits them — accepted residue, not
repaired); the egress lane consistent for 12/12 host spellings; D4 PARTIAL
and D6 PARTIAL, re-filed as the items below; both round-3 guards pinned in a
mutation spot-check. All repaired in the fifth commit:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| H3 (high) | `DAEDALUS_TRUSTED_HOSTS` makes a tailnet Ollama a TRUSTED lane, so "leaves the machine" — decided by the lane since round 3 — said *nichts verlässt ihn* while bytes crossed the tunnel, the deny list was off and `confirm-remote` was skipped | leaving is physics: `planner_leaves_machine` asks `sensitivity.is_loopback_host`, which no declaration widens; the lane stays consent (which filter runs); the warning and the grant name the host and the declaration | `test_leaving_the_machine_is_physics_and_the_lane_is_consent` (9 rows), `test_an_owner_declared_trusted_host_still_leaves_the_machine`; mutations M30, M36 |
| H4 (high) | the ambiguity refusal of `_resolve_module` listed raw indexed paths; refusals reach the planner's history like any result, so a model-chosen basename enumerated exactly the paths `daedalus.structure` withholds; corollary: `focus_file` disclosed the directory a basename resolved into | candidates go through `_admit`, the rest is a count; `focus_file` is gated | `test_an_ambiguous_module_names_only_the_candidates_the_gate_admits`, `test_a_withheld_focus_discloses_neither_its_path_nor_its_rule_text`; M35, M37 |
| D9 (high) | the gate's REAL rule strings are `<path>: denylisted path fragment '<fragment>'` and `<path>: path not on the external allow-list (default-deny)`; the round-3 `_redact_rule` knew one of five shapes, so the withheld rows and the breadcrumbs still carried the path and the project's deny fragment; the round-3 test pinned an invented rule string the gate never emits | only a fixed rule CLASS travels (`secret_path`, `secret_content`, `denylisted_path`, `default_deny`, `deny_content`, `egress_rule`); the withheld block after the slicer's header and the focus refusal are REBUILT from the gated rows; the tests use the rule strings `slice_egress_rule` really returns, and one runs the real index and the real slicer end to end | `test_slice_withheld_rows_name_a_rule_class_never_the_file_fragment_or_marker`, `test_the_real_slicer_hands_no_withheld_path_or_fragment_to_the_planner`, `test_slice_gate_rules_never_quote_the_marker_they_fired_on`; M33, M40 |
| D10 (high) | `_status` gated `str` values only; a list, dict, set, `Path`, exception, bytes or dict KEY carrying a host path or a deny word reached the planner, in `git` and in `queue` | `_strings_in` flattens sets, dict keys, bytes and the `str()` of any other object (what `default=str` would render); every git and queue value goes through `_admit_value` | `test_status_gates_every_value_shape_in_git_and_queue`, `test_nested_strings_in_a_kept_field_are_gated`; M34, M38 |
| D11 (medium) | D4 residue: the same shapes under a kept row key | same flattener, through `_admit_rows` | same tests |
| D12 (low) | the scrub regexes were format-fragile: a file name with a space or a CRLF line left the breadcrumb and the focus line unscrubbed | no regex over file names any more: the block is rebuilt from the rows | the slice test above carries a CRLF line and a name with a space |
| D13 (low) | `[:TOP]` truncated silently; `*_withheld` counted refusals only | `*_elided` counts beside every `*_withheld` | `test_structure_counts_the_admitted_rows_the_top_bound_drops`; M39 |
| nit | dead store `remote` in the enable branch | removed | — |

**Cerberus round 5** (`b29105af`, frozen copy): verdict `needs_fix`, no
CRITICAL. H4 RESOLVED (unique basename into a denied directory, ambiguous,
path-shaped: no path, no directory, no rule text on any field); the `remote`
nit RESOLVED; rule classes: all eight rule-string productions of
`secret_floor_rule`, `_path_is_sensitive`, `classify_data` and
`slice_egress_rule` map to a class, the `egress_rule` fallback is unreachable
today and withholds the whole text if it ever fires; authority confirmed
unwidened. H3 PARTIAL: the grant/warning/disable sentences are true, but the
SAME claim survived on two other surfaces — `_planner_line` ("Kontext hat den
Rechner verlassen") in `/computer status` and every mission report, and the
chat offer's "(Beobachtungen verlassen den Rechner)", both derived from the
consent flag `allow_remote_context`, so a tailnet Ollama configured without
the flag read *nein*. Two lows: `_planner_lane_of` dead;
`_daedalus_tools_egress_warning` printed the declaration clause on `trusted`
alone. One pre-existing medium it named and did not charge to this packet: an
ADMITTED focus body is emitted verbatim, so its own `import` line may name a
withheld module — `slice_egress_rule`'s file granularity, identical on the
Voice path.

**Odysseus round 5** (same snapshot): D9/D6, D12 and H3 RESOLVED (40 rule
strings enumerated off the real tables, none reaching the fallback; real
index + real slicer clean; 11 hosts × 2 declarations, no host with
`leaves=False` on a non-loopback address, IPv4-mapped IPv6 and the eight-zero
form correctly loopback); mutation spot-check: all four guards die. Four new
items, all repaired in the sixth commit together with the Cerberus residue:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| H3 residue (high) | status line, mission report and chat offer derived "verlassen" from the consent flag | `_planner_facts` carries `leaves_machine` from `planner_leaves_machine_for(provider)` beside `remote_context`; `_planner_line` prints *ja/nein* from physics and *unbekannt* for a retained report without the field; the cockpit contract and offer line follow `leaves_machine` | `test_the_report_line_is_physics_not_the_consent_flag`, updated provenance tests, `conversation.spec.ts`; mutations M41, M42, M43 |
| low | `_planner_lane_of` dead | removed | — |
| low | the declaration clause on `trusted` alone | printed only for a trusted NON-loopback host | (warning text) |
| D14 (major, latent) | `_strings_in` gated set ELEMENTS on `str()` while `json.dumps(default=str)` renders a set as one text from element `repr()`s — a `Path` in a set carried the host path on the trusted lane | the value is RENDERED first, exactly as `_json_safe` renders it, and the strings are read off the rendering: what is gated is byte-for-byte what leaves | `test_a_set_is_gated_on_the_text_json_renders_for_it`; M38 |
| D16 (minor) | NaN/inf, a non-string dict key or an object whose `str()` raises made `_json_safe` raise out of the observation | an unrenderable value is withheld and counted (`_Unrenderable`), in `_admit_value` and `_admit_rows` | `test_an_unrenderable_value_is_withheld_and_counted_not_crashed_on`; M47 |
| D18 (minor, side channel) | a basename resolving UNIQUELY into a denied directory said `<withheld>` while a miss said "not in the index": one bit per guess confirming a withheld file exists; the exact-path branch the same | a unique or exact hit the gate withholds answers exactly like a miss (`_MODULE_UNAVAILABLE`); the ambiguity branch still counts, which is the disclosure every `*_withheld` makes | `test_a_unique_hit_the_gate_withholds_answers_like_a_miss`, the withheld-focus test rewritten; M44 |
| D15 (minor, honesty) | a focus file containing the literal header (this adapter does) was split at its own occurrence: text silently dropped while `text_elided` said false | the rebuild runs only when the slicer reported withheld rows and splits at the LAST occurrence, which is the slicer's | `test_a_focus_file_containing_the_header_literal_keeps_its_text`; M46 |
| D19 (trivial) | `_tasks` bounded before the gate and reported no elision | gate every brief, bound after, `reports_elided` | `test_tasks_gate_every_brief_before_the_bound_and_count_the_elision`; M45 |

**Cerberus round 6** (`ed71c8d1`, frozen copy): **`approve`**, `blocking:
false`. The H3 residue RESOLVED across the four-host × two-declaration ×
four-provider × two-flag matrix (report line, status, planner reply and offer
all read `_planner_facts`; a pre-field report says *unbekannt*, a non-bool
value too); D14/D16/D18 resolved insofar as they change what is told; the
diff adds no write, spawn, network or policy reach. Two latent lows and one
pre-existing medium it named for a separate packet (the `/computer planner`
confirmation is decided by provider name — `bb81dea2`, before this packet).

**Odysseus round 6** (same snapshot): D15 and D19 RESOLVED; D14, D16 and D18
PARTIAL with residues; all four guards of round 5 die under mutation. The
residues and the Cerberus lows, all repaired in the seventh commit:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| Cerberus low (latent) | the warning's first clause called a loopback host "nicht auf diesem Rechner" (unreachable: the caller fires only when the observations leave) | both clauses of the warning defend themselves | (warning text) |
| Cerberus low (hypothesis) | a separate decode pass before gating let a non-dict `Mapping` with its own `__repr__` be gated on its items and emitted as its repr | one renderer (`_render`, one `default` hook) for the gate and the emitter | `test_the_gate_and_the_emitter_share_one_renderer`; M38 |
| D20 (low) | the value was rendered twice — once to gate, once to emit — so an object whose `str()` changes between calls was admitted as "benign" and emitted as a host path | rendered ONCE: the gate reads its strings off the rendering and the observation emits that rendering (`_gate_value`, rendered rows) | `test_what_is_emitted_is_the_rendering_that_was_gated`; M48 |
| D21 (medium) | a raising reader or producer escaped `execute` with its message intact — a `PermissionError` from `collect_status` carries the absolute path — and the service put that text into the planner's history, past every gate | every reader and producer runs through `_produce`: a failure is a refusal naming the CLASS only; a non-mapping result is a refusal | `test_a_reader_or_producer_failure_names_its_class_never_its_message`; M49 |
| D22 (low-medium) | the ambiguity branch counted the withheld ("2 candidates, all withheld"), confirming the existence the unique branch denies | no count: admitted candidates are listed, otherwise the same text as a miss | `test_an_ambiguous_module_names_only_the_candidates_the_gate_admits`; M50 |
| D23 (low) | `n_files`, `languages`, `totals`, the ignored, docrefs and slice counters passed ungated | every counter goes through `_gated_fields`, withheld ones counted in `fields_withheld` | `test_counters_are_gated_like_every_other_value`; M51 |

**Cerberus round 7** (`233b463e`): **`approve` confirmed**, `blocking:
false`; no message, locator, host path or withheld name survives on any of
the five tools (6/6 raising readers refused by class, odd shapes refused as
"no mapping"); emitted == gated in every shape; no new reach. Three lows.
**Odysseus round 7**: D20/D21/D23 PARTIAL on paths the repair had not
covered, D22 NARROWED; all four round-6 guards die under mutation. The lows
and residues, all repaired in the eighth commit:

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| D24 (medium) | the `clones` rows of `daedalus.structure` were copied raw from the producer: rendered a second time by the emitter (a stateful `__str__` passed) and `count`/`loc` never gated | the clone row is rendered ONCE and every string of the rendering is gated, `count`/`loc` included | `test_clone_rows_are_rendered_once_and_gated_in_every_field`; M52 |
| D25 (medium) / Cerberus L3 | `_repo_root` and `_project_policy` still interpolated the exception message — the registry file's host path — into a refusal the planner's history sees | class only, and a malformed row is a refusal of the same shape | `test_registry_refusals_name_the_class_never_the_message`; M53 |
| D26 (low-medium) | the slice TEXT is source, and a string literal holding an absolute path left with it on every lane while the module promised no host path reaches the planner | every absolute-location span in the text is redacted to `<host-path>` and counted (`text_host_paths_redacted`); the file's other text stays useful | `test_absolute_host_paths_inside_the_slice_text_are_redacted_and_counted`; M54 |
| D27 (low) | "ambiguous; name one of: pkg/mod.py" with ONE admitted name told the planner a withheld second exists | one admitted candidate resolves as if unique; the list needs two | `test_one_admitted_candidate_resolves_without_naming_ambiguity`; M55 |
| Cerberus L1 (low, latent) | without `keep_keys` the producer chose the row KEYS, which were emitted ungated | producer-chosen keys are gated like the values | `test_row_keys_from_a_producer_are_gated_when_no_projection_is_given`; M56 |
| Cerberus L2 (low) | `errors_count` reported 0 for a dict/set of errors | any sized container is counted; a truthy scalar counts 1 | (docrefs test) |

Accepted residue, stated: the loopback clause names `localhost` and `::1`
"nicht auf diesem Rechner" because the host predicate accepts numeric
literals only (deliberate, errs strict).

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

# G1-IKARUS-09 — Productive conversational handoff

## Frozen packet metadata

- Packet ID: `G1-IKARUS-09`
- Active gate: **Gate 1 — Renovation ignition slice**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `52b4baa5`
- Master-plan authority: Revision 10
- Master-plan digest: `5e269de9857940cd1d6162eaf9236d4db8e77427d189122db178812b49b259dc`
- Dependencies: the canonical Ikarus Voice/Hand split, file bridge, durable
  conversation link, and existing `GET /api/queue/<id>/events` projection
- Primary claim: a German action request made in the shipping Ikarus chat is
  handed to the existing Daedalus execution path under the project's
  system-owned lane, and the same chat turn reports observed task progress and
  outcome instead of stopping at a claim that work was queued.

## Baseline reproduced

- The shipping classifier recognizes English action verbs only, while the
  capability predicate merely *suspects* German action verbs. A direct request
  such as `Mach den Parser robuster` therefore stays in Voice and reaches no
  executor.
- Every Hand proposal hard-codes `local_only`; on this host the configured
  local Ollama endpoint is unreachable, so confirmation refuses even though a
  project may declare another canonical lane.
- `POST /api/queue` returns a stable task id and the backend already exposes
  one-shot task SSE, but the cockpit discards the id and renders only
  `eingereiht`.
- The browser project dialog presents a native folder-picker button even though
  that capability exists only in the Tauri desktop process; the click then
  produces the failure shown in the user-provided screenshot.
- Deterministic Hand replies are English inside an otherwise German cockpit.

The supplied PDF/chat export is reference material only. Its proposed Hermes
runtime migration is not evidence that the shipping chat path uses Hermes; the
repository currently contains bounded adapter/projection work but no installed
Hermes runtime on this path.

## Scope

In scope:

- the existing intent/capability join in `daedalus/ikarus_os.py` and
  `daedalus/ikarus_act.py`;
- system-owned Hand lane projection from the existing project configuration;
- German deterministic Hand wording and a language-matching Voice prompt;
- the existing queue-task SSE consumer in `apps/web/src/api.ts` and its
  per-turn rendering in `apps/web/src/cockpit/Conversation.tsx`;
- an honest browser/desktop capability distinction in
  `apps/web/src/cockpit/ProjectDialog.tsx`;
- focused Ikarus tests, frontend build, and this packet.

Forbidden:

- no Hermes dependency, deep fork, second agent loop, scheduler, broker,
  event store, conversation store, project registry, or promotion path;
- no model-selected execution lane and no use of the chat `provider` parameter
  to choose an executor;
- no provider-native effectful tool exposed through Voice;
- no weakening of confirmation, autonomy, egress, budget, verification,
  rollback, or promotion policy;
- no claim that `bridge_status=done` means a change was applied;
- no automatic merge/promotion and no Master Plan, amendment-chain, evaluator,
  or policy edit.

## Build-time dependencies discovered and retained

Builder review reproduced two pre-existing blockers below this UI/handoff
packet rather than hiding them inside it:

- `G1-IKARUS-10` repairs the queue consumer's missing canonical Effect Lease
  and closes the `local_only` provider mask before that path can run.
- `G1-IKARUS-11` projects a terminal linked-task report exactly once onto the
  existing conversation spine.

G1-IKARUS-09 does not claim a productive end-to-end run until those packets'
focused acceptance evidence is green. They add no second runtime or state
authority and do not widen this packet's frontend/intent scope.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Leading, exact German imperative | classifier + capability unit tests | Hand proposal |
| German question or ambiguous request | capability/refusal tests | confirmation offer, no enqueue |
| Chat provider names an executor | routing test | ignored; project lane remains authoritative |
| Valid project lane | unit test | exact declared lane in action envelope |
| Missing/unknown project lane | unit test | fail-closed `local_only` |
| Unavailable local bench with non-local declared lane | unit test | proposal/confirmation not falsely refused by local-only probe |
| Manual and configured automatic dispatch | frontend build/source test | subscribe to existing task id |
| Queue attribution | API/frontend test | exact persisted `conversation_id` + positive `turn_id`, never "latest turn" inference |
| Later chat turn while task runs | frontend state test or source review | progress remains on originating turn |
| Task SSE final/error | API client test/source review | EventSource closes exactly once; no reconnect |
| Chat SSE disconnect before final | API client/source review | visible uncertainty; no automatic replay or duplicate turn/spend |
| Reload after linked terminal task | durable resume test/source review | the originating turn renders its projected outcome |
| Finished but application unknown/false | render review | never labelled applied |
| Browser project registration | build/review | direct path entry remains; native picker not offered |
| Provider/network/process budget | mocked focused tests | zero live model/provider starts |

## Migration, rollback, and evidence

This is additive wiring over existing contracts. Rollback is deletion of the
localized intent/lane projection and task-SSE UI fields; queued-task and
conversation schemas do not change. Existing conversation rows remain valid
because progress is a browser projection of the canonical task id, not new
orchestration state.

Retain negative evidence: the configured local Ollama endpoint is unreachable,
the current project registry points at stale checkouts, and an earlier test
mistakenly discovered a real Claude executable through the runtime registry.
The test seam is repaired separately; no live provider call is permitted in
this packet's verification.

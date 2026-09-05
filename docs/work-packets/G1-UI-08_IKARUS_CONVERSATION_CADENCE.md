# G1-UI-08 - Ikarus conversation cadence and intent boundary

## Frozen packet metadata

- Packet ID: `G1-UI-08`
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`
- Dependencies: G1-UI-05/06 integrated; G1-IKARUS-14 no-replay contract
- Promotion authority: repository owner; no automatic merge, promotion,
  release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`

## Primary acceptance claim

The existing conversation projection feels continuously responsive because it
names the lifecycle facts it has actually observed and paints streamed text at
most once per animation frame, without losing bytes at a terminal boundary.
One dedicated, atomic polite status announces only observed phase transitions
and completion; the visual clock, empty answer placeholder, and transcript do
not form competing live regions or announce every token. The square stop
affordance requests canonical server cancellation and keeps observing until a
server result arrives, while the explicitly named secondary action closes only
the browser observation. A reader pinned to the bottom follows streamed and
final text synchronously; an intentional scroll-up is preserved.
The project-keyed conversation remains mounted while the reader visits Map,
IDE, or Genesis, so its one existing observation continues to receive deltas
and the terminal frame without a replay. The default Ikarus stream is a
thread-safe cancellable iterator: a confirmed cancellation means local
generation delivery and final persistence are closed, never that an already
blocking external provider process was magically terminated.
An answer-shaped German observation request remains with the selected Voice
instead of being reduced to a deterministic queue offer; an explicit mutation
remains confirm-gated. The change does not expose hidden reasoning, invent tool
activity, add orchestration state, or create another route, store, request,
retry, or effect.

## Baseline reproduced

Measured at the frozen base:

- every `delta` frame immediately calls `setTurns`; each update reparses the
  active Markdown tree and triggers the transcript-following effect;
- the root conversation clock updates every 500 ms and passes `elapsed` to a
  streaming Markdown message even after visible text exists;
- the visible lifecycle is reduced to `Ikarus denkt` until text arrives,
  although the existing object already distinguishes local creation,
  canonical request acceptance, a received `start` frame, streamed text, and
  a cancellation request;
- the composer exposes `Beobachtung schliessen` as soon as `busy` flips, before
  an EventSource exists. Calling it in that interval clears the send claim and
  paints the turn halted, but the pending POST path can still continue;
- live reproduction with project `pnp_app`: `Schau dir den aktuellen
  Projektzustand an. Nenne die drei wichtigsten nächsten Schritte und erkläre
  kurz, warum.` is classified from its leading `schau` token as a Hand request
  and immediately returns a deterministic `local_only` queue offer; the
  selected conversational provider is never entered;
- `npm.cmd run test:app`: 391/391 passed; `npx.cmd tsc --noEmit`: passed.

Trust/accessibility follow-up baseline:

- the transcript (`role=log`, `aria-live=polite`), the empty streaming message
  (`role=status`), and the top phase-plus-clock (`role=status`) created nested
  and competing live updates; the clock changed every second and the transcript
  changed for every painted token;
- the primary square stop glyph closed only the EventSource, painted the answer
  halted, and left canonical server execution un-cancelled; the actual
  cancellation POST was a secondary text action;
- the first focused browser regression kept a bottom reader 2,105 px above the
  growing answer. The passive post-paint follow effect raced a queued scroll
  event and misclassified it as an intentional user scroll. This failing run
  (six passed, one failed) is retained as the reason for the layout-timed fix.

The supplied external articles are interaction priors only. Their common,
applicable point is to keep execution observable and controllable; they do not
authorize a new framework, a reasoning transcript, or client-owned workflow
state. The existing Daedalus receipt ledger remains the authority.

## Scope

In scope:

- `apps/web/src/features/conversation/model.ts`: pure derivation of the live
  turn activity from fields already present on `Turn`;
- `apps/web/src/features/conversation/streaming.ts`: a small scheduler-injected
  text batcher local to the conversation projection;
- `apps/web/src/features/conversation/Conversation.tsx`: wire the derived
  activity, coalesce deltas, flush before every terminal rendering, and refuse
  observation-close before observation exists; expose one phase/completion live
  region, route the primary stop affordance to canonical cancellation, retain a
  clearly named observation-only secondary action, and follow the transcript at
  layout time only while the reader remains pinned;
- `apps/web/src/app/Cockpit.tsx`: keep exactly one project-keyed conversation
  mounted across view changes and make the hidden surface inert without creating
  a second request or orchestration owner;
- `apps/web/src/features/conversation/MarkdownMessage.tsx`: show the supplied
  observed activity while empty and avoid reparsing unchanged messages;
- `apps/web/src/features/conversation/conversation.spec.ts`: deterministic
  phase and byte-preservation tests;
- `daedalus/orchestration/ikarus/shell.py`: keep a narrowly defined German
  observation-plus-answer form on the existing Voice route while preserving
  explicit mutation imperatives on the Hand route, and expose the existing
  stream through a cancellable iterator whose final persistence gate is atomic;
- `daedalus/orchestration/conversation_requests.py`: project that cancellation
  honestly as requested/confirmed/already-terminal/unknown and never persist a
  final turn after cancellation won the gate;
- `tests/test_ikarus_os.py` and `tests/test_ikarus_stream.py`: pin the exact live
  reproduction and a mutation counterexample;
- the existing fixture-backed browser test may pin the pre-observation refusal
  and visible phase sequence without making a live provider call.

Forbidden:

- settings files or settings behavior;
- new routes, stores, event kinds, requests, retries, provider adapters, tool
  events, synthetic plans, hidden chain-of-thought, or client-side workflow
  authority;
- a new cancellation route/store, a claim that an external provider process was
  terminated, changes to dispatch confirmation, policy, budget, promotion, the
  Master Plan, its amendments, or
  `docs/work-packets/index.json`;
- visual redesign outside the existing conversation tokens and components.

## Contracts and behavior

The scope and forbidden paths above are binding. Every visible phase,
cancellation state, route and answer stamp must remain a projection of an
observed server field; browser-local state never becomes orchestration
authority.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
| --- | --- | --- |
| Live copy follows observed facts | Node spec over `Turn` shapes | creating -> accepted -> routed -> writing -> cancelling, with no activity for a settled turn |
| No hidden reasoning is claimed | source review + exact strings | no planning/search/tool wording without a matching emitted field |
| Burst deltas are paint-batched | scheduler-injected Node spec | many pushes schedule one callback and preserve byte order |
| Terminal boundaries lose no text | Node spec + integration source review | `flush()` emits pending bytes exactly once before final, error, cancellation, or observation close |
| Historical Markdown is stable | React memo boundary + props review | elapsed changes do not reparse settled or already-writing historical answers |
| Early observation close is refused | fixture-backed browser test + source guard | close control disabled until request and stream observation exist; one turn POST only |
| A closed observer cannot terminate its successor | controlled EventSource browser fixture | close request A, start request B, then queued error/cancel for A; B remains busy, A's flushed text remains, and B settles normally |
| A late cancellation response cannot clear its successor | delayed cancel-POST browser fixtures for success and error | cancel A, start B, release A response; only an exact conversation/request/local-turn identity may be cleared |
| A detached request cannot arm a successor's close control | delayed second turn-creation fixture | close A, start B; while B has no canonical id the composer says `Anfrage wird angelegt` and remains disabled |
| One accessible lifecycle channel | controlled EventSource browser fixture + rendered empty-message spec | exactly one atomic polite status; transcript is live-off, clock is accessibility-hidden, and empty message has no nested status |
| Tokens do not spam assistive output | controlled EventSource browser fixture | phase status changes once to the provider-answering label, remains identical across later token deltas, then announces `Antwort abgeschlossen` |
| Stop means server cancellation | fixture-backed cancel route | square stop makes exactly one canonical cancel POST, stays in observation, and reports `requested`; `Nur Beobachtung trennen` is a separate secondary action |
| View changes do not detach work | controlled browser fixture | Map, IDE, and Genesis hide one inert conversation without unmounting it; hidden deltas/final settle the same request and no second POST occurs |
| Default stream cancellation is real and bounded | Python race tests | pre-bind and mid-stream cancel stop local delivery/persistence; cancel-vs-final has one atomic winner; confirmed makes no provider-process claim |
| Auto-follow respects reader intent | constrained real-browser scroll fixture | bottom gap remains <=2 px through streaming and final; after an explicit scroll to top, later delta/final keep `scrollTop=0` and show `Neue Antwort` |
| Answer-shaped observation keeps its Voice | Python classifier + stream test with the exact live prompt | `chat` start/final, selected provider entered, no action or act offer |
| Mutation remains gated | Python classifier + stream counterexamples | Hand route, provider not entered, confirmation required, including German observation followed by exact English `fix` |
| No canonical boundary changes | Git diff + effect registry digest | no API/settings/effect-registry change and no new backend entrypoint |
| Existing application contracts hold | `tsc`, `test:app`, focused Playwright | green; unrelated baseline failures named separately |

## Migration and rollback

UI mount-lifetime and stream-wrapper changes are process-local; the canonical
spine and persisted conversation schema are unchanged. Rollback reverts this
packet's feature files, narrow classifier/cancellation affordances, and test
additions; no persisted data migration is required. Independent review should check
that batching cannot reorder/drop text, stale callbacks cannot paint another
thread, terminal handlers flush before settling, and every activity word is a
projection of an observed field rather than an orchestration claim.

## Evidence, expected failures and review

- `npm.cmd run test:app`: 399/399 passed after the change.
- `npx.cmd tsc --noEmit`: passed.
- `npm.cmd run build`: passed; Vite transformed 710 modules. The pre-existing
  chunk-size warning remains visible (`684.79 kB` main chunk).
- With the suite's expected keep-alive value pinned for isolation,
  `python -m pytest -q tests/test_ikarus_os.py tests/test_ikarus_stream.py
  tests/test_ikarus_shells.py`: 80 passed, 37 subtests passed. This includes
  the exact live prompt entering the selected Voice and a mutation-plus-
  explanation counterexample remaining confirm-gated.
- Negative environment evidence retained: the first Python run inherited the
  workstation's `OLLAMA_KEEP_ALIVE=30m` and therefore failed the unrelated
  assertion that expects the default `10m` (79 passed, one failed). No product
  code was changed to conceal that operator override.
- `git diff --check`: passed; only the checkout's LF-to-CRLF warnings were
  reported.
- The new fixture-backed Playwright case type-checks, but this track did not
  launch a browser without a user-selected browser. The root live-smoke owns
  that final visual/runtime observation.
- Review follow-up: `endUnconfirmed` now drains the old batch, reports whether
  it still owns the originating `sendClaim`, and only then may mutate shared
  observation, busy, or error state. The latest `npm.cmd run test:app` is
  421/421 after concurrent Genesis specs landed, and an isolated TypeScript
  compile of `tests/ide.spec.ts` passes.
- Retained concurrent-checkout evidence: the follow-up whole-project
  `npx.cmd tsc --noEmit` could not complete because the separate Genesis track
  currently reports `Genesis.tsx:30` (missing argument) and `Genesis.tsx:50`
  (`undefined` not assignable to `RetryIdentity`). G1-UI-08 did not touch those
  files; the previously green whole-project TypeScript result remains recorded
  above and root integration owns the stable-checkout rerun.
- Stable-checkout review rerun: `npm.cmd run test:app` is 431/431,
  whole-project `npx.cmd tsc --noEmit` passes, isolated `tests/ide.spec.ts`
  TypeScript passes, and the focused Python router/stream/shell suite is 80
  passed plus 37 subtests. The two delayed cancellation fixtures cover both a
  successful `unknown` response and a rejected POST; both consume A's result
  without clearing B.
- Trust/accessibility follow-up: `npm.cmd run test:app` is 435/435 and
  whole-project `npx.cmd tsc --noEmit` passes. Seven focused Chromium cases pass
  against the Vite source build (single live channel, auto-follow plus retained
  scroll-up, canonical square stop, pre-ID refusal, late cancel success/error,
  and late terminal isolation). The first auto-follow run failed honestly at a
  measured 2,105 px bottom gap (six passed, one failed); changing the transcript
  follow from post-paint to layout-timed made the isolated case and the full
  seven-case rerun green. No distribution bundle was rebuilt in this track;
  root integration owns the final application build and full browser harness.
- v0.1.6 release-blocker follow-up: `npm.cmd run test:app` passed 444/444,
  whole-project TypeScript passed, and five focused Chromium cases passed. The
  adversarial browser case plants the retired legacy autonomy key, streams one
  request while visiting Map, IDE, and Genesis, proves zero queue POSTs before
  the visible `Loslegen` click and exactly one afterward, and receives the
  hidden request's final frame. Its first cold Vite navigation timed out before
  test execution; the warmed harness rerun passed 5/5 and both loopback ports
  were closed afterward.
- The cancellable default-stream follow-up passed 40 focused request tests and
  235 adjacent stream/boundary tests plus 34 subtests. It covers cancellation
  before binding, during deltas, both atomic final races, exceptions,
  idempotence, and absence of final persistence after cancellation wins. A
  confirmed result is explicitly local; no external provider-process exit is
  claimed.

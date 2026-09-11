# G1-UI-06 - Ikarus oversight surface: the work rail and the live stream it never read

## Frozen packet metadata

- Packet ID: G1-UI-06
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 0e6b8ded31e0e1b2ba3e15c1e9b0bb5db1c7b1b6
- Dependencies: G1-UI-05 integrated at ec9a11d8 (Protokoll, thread rail, commands); G1-WEB-01 project-scoped live events
- Promotion authority: repository owner; no automatic merge, promotion, release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The cockpit answers the three oversight questions — does anything wait on me,
what is running, what just happened — from data the backend already emits and
the frontend previously discarded. No new route, no new fetch, no invented
figure: the drafts come from the decision card's existing read, the open
dispatches from the conversation's existing resume, and the counters from the
one existing event stream, whose `queue` frame the cockpit had been decoding
under the wrong key since it shipped.

## Baseline reproduced

Measured on this checkout, 2026-09-02:

- `GET /api/events?project=` sends seven fields on `hello`
  (`queue_depth`, `in_flight`, `unread_count`, `quarantined_count`,
  `watcher_state`, `reports_total`, `latest_report`). The cockpit read two and
  dropped five, and discarded the whole `report` payload.
- The `queue` frame carries `queue_depth`; `Cockpit.tsx` read `d.depth`. The
  queue counter therefore never moved after the `hello` snapshot. The
  contract (`shared/contracts/index.ts` `LiveQueue`) had it right all along.
- `ConversationStore.resume()` returns `open_dispatches` — a dispatch this
  thread started that has not reported back. The type is declared in
  `shared/api`; no component has ever read it. After a reload, a running task
  was invisible.
- `Decision.tsx` fetches every pending draft and renders `pending[0]`. The
  rest were fetched and dropped.

## Scope

In scope:

- `apps/web/src/features/mission/WorkRail.tsx` (new): the three-section
  overview — Wartet auf dich, Läuft gerade, Zuletzt;
- `apps/web/src/app/Cockpit.tsx`: the `queue_depth` repair, the widened live
  state, the third rail tab and its waiting-count badge;
- `apps/web/src/features/conversation/model.ts`: `openDispatchesFrom`, a pure
  derivation with no invented field;
- `apps/web/src/features/mission/Decision.tsx`: an `onPending` callback so the
  queue it already read reaches the rail without a second GET;
- `apps/web/src/features/conversation/Conversation.tsx`: the resumed open
  dispatches reported up with the existing thread state;
- `shared/contracts` `LiveReport` widened to the five fields `report_brief`
  emits; `shared/api` `ConversationDispatch` widened to the link fields the
  server already serializes;
- `app/styles/instruments.css`: the rail's stylesheet, tokens only;
- `conversation.spec.ts`: the open-dispatch derivation.

Forbidden:

- any new route, endpoint, fetch, effect or store;
- any figure the backend does not emit — in particular no cost, token or
  duration estimate, and no count for a source that could not be read;
- counting an unscoped draft pile under a project's name;
- changing the Decision card's own behavior, the map, the IDE, Settings, or
  any wire contract.

## Contracts and behavior

### What waits

`(scoped drafts) + quarantined_count + unread_count`. `draftsScoped` is
load-bearing: `/api/drafts` answers `scope: null` when it could not honestly
narrow the pile to this project, and an unscoped pile is never counted under
this project's name — the same rule the decision card already applies to the
one draft it draws.

### What runs

The open dispatches of the resumed thread, plus the stream's `in_flight`,
`queue_depth` and `watcher_state`. A watcher state the interface does not have
a word for is printed as the identifier it is, never rounded to a friendlier
one. When the stream is closed the section says the numbers are last-known.

### What happened

`latest_report`, the five-field brief the bus already publishes, carried on
`hello` (so it is populated on connect, not only after a report arrives during
this session) and refreshed by each `report` frame.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
| --- | --- | --- |
| Open dispatches derive from the link and its event | Node spec | ref/turnId/since/summary exactly; a row without a ref is dropped; absent fields stay absent |
| No second draft fetch | source review | one `getDrafts` caller; the rail receives rows through `onPending` |
| The queue counter tracks the server | live stream sample + source | `queue_depth` decoded; `d.depth` gone |
| Nothing invented | Node spec + render | an unmapped watcher state prints verbatim; a missing report says so |
| Existing contracts hold | Playwright suite | green except the named pre-existing failure |
| Hierarchy and tokens | `npm run test:app`, `test:motion` | green; no literal colour, radius, size or duration in the new CSS |
| Floor across themes | `tools/audit.mjs` | 0 combinations below the floor |
| Effect boundary unchanged | `registry_sha256()` | exact frozen digest |

## Migration and rollback

Additive and frontend-only. Rollback reverts the packet commit; the discarded
stream fields return to being discarded and the rail disappears. No schema,
key or state migration exists.

## Evidence, expected failures and review

Builder evidence appended below. Expected failure named in advance:
`cockpit.spec.ts` "settings names the brain, the autonomy level and what is
reachable" expects four autonomy levels while `features/settings/autonomy.ts`
has carried two since 0d3ea5d1 — pre-existing drift, not touched here.

Review questions: can any section render a count for a source that was not
read; does the waiting count ever include an unscoped draft pile; can the rail
issue a request of its own; does any new CSS declare a literal value.

# G1-UI-05 - Ikarus agent surface: receipt ledger, threads, commands

## Frozen packet metadata

- Packet ID: G1-UI-05
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 570b2c00562053c300ece4ef74075ce9f8860261
- Dependencies: G1-UI-03 integrated at 81bc5670 (directed frontend hierarchy); G1-UI-04 integrated at d9baa6c0 (catalogue names only live source); G1-IKARUS-09/11/14 conversation dispatch, outcome projection and no-replay stream contracts; G1-WEB-01 project-scoped live events
- Promotion authority: repository owner; no automatic merge, promotion, release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`
- Design record: `docs/superpowers/specs/2026-09-02-ikarus-agent-surface-design.md`

## Primary acceptance claim

The Ikarus conversation in the shipping cockpit shows, for every answer, a
ledger of the kernel's own receipts for that turn (route selection, context
receipt, refusal, provenance stamp, offer, linked dispatch with observed
outcome, cancellation), derived only from frames and envelope fields the
backend actually emitted; lists and resumes this project's conversations from
the canonical spine through one new read-only route; and accepts a bounded set
of `/` commands that map exclusively to existing deterministic routes and
in-page actions. The single effectful conversation transition, the dispatch
confirmation rule, the effect-registry digest and every existing browser
contract of the cockpit are unchanged.

## Scope

In scope:

- `apps/web/src/features/conversation/*`: the turn/exchange model and ledger
  derivation, the ledger, thread list, composer and command modules, the
  Markdown renderer (`react-markdown` + `remark-gfm`, images disabled, raw
  HTML never rendered), and its stylesheet;
- `apps/web/src/app/Cockpit.tsx` and `app/styles/shell.css` for the talk
  page grid (docked composer, rail tabs) and the map hand-off used by
  `/karte`;
- `apps/web/src/shared/api/index.ts`: `listConversations`, the `envelope`
  and `created_ts` fields the conversation view already serves;
- `apps/web/src/shared/ui/motion/motion.css` publishing `--dur-fast`,
  `--dur`, `--dur-slow`, `--ease`; `shared/ui/theme/apply.ts` publishing
  `--ring`;
- `apps/web/package.json` and lockfile for the two Markdown dependencies;
- backend read path only: `SpineLedger.effect_key_groups`,
  `ConversationStore.list_conversations`, `_conversation_list_view`,
  `GET /api/conversations?project=&limit=`;
- focused tests: Node spec for model/commands, Python tests for the list
  route, fixture-backed and live Playwright specs, the audit floor and shots.

Forbidden:

- any new effectful entrypoint, write, dispatch, provider call, event kind,
  store, scheduler, or second conversation truth (no localStorage thread
  registry, no client-side titles);
- invented figures: no cost, token or step counts the backend does not emit;
- moving or changing `Decision`, the map, IDE, Settings, Theme Studio, or
  any route/wire contract other than the additive list route;
- vendoring React Bits or any registry source;
- changes to `apps/web/dist`, the Master Plan, amendments, or historical
  evidence.

## Contracts and behavior

### Ledger derivation (frontend, pure)

`model.ts` reduces the observed frames of one exchange — `start`, `delta`,
`final`, `cancelled`, `error`, `state`, task `hello/progress/final`, the
resumed `envelope` and `dispatches` — into an ordered list of receipt rows.
A row exists only when its source field is present; absent data is absent,
never rendered as a placeholder. The reducer is deterministic and covered by
a Node spec that feeds recorded frame sequences and asserts the row list.

### Commands (frontend)

`commands.ts` parses a draft beginning with `/`. Recognised commands resolve
to one of: send a fixed deterministic message (`status`, `distill`), open
the context plan, focus a module and switch view, start a new thread, open
the runtime picker, set effort, request cancellation, or print a local note.
A local note is rendered with the stamp word `OBERFLÄCHE`, is never sent and
never persisted. Unrecognised commands are sent verbatim.

### Thread list route (backend, read-only)

`GET /api/conversations?project=<name>&limit=<n>`:

- `project` required (400 when missing or invalid); `limit` 1..50, default
  20, same validator as the existing conversation GET;
- rows newest-first by the newest `conversation.turn` intent of each
  `conversation:<id>` effect key whose canonical payload matches the
  project; each row carries `conversation_id`, `turn_count`,
  `first_message`, `last_message`, `last_ts`, `last_intent`,
  `last_provider_used`, `last_status`, all clipped by the existing
  `_clip`;
- no write, no cache, no new kind; a store failure returns 500 with the
  existing error shape; an unknown project returns an empty list.

### Effort

The composer sends `effort` (`low`/`medium`/`high`) on
`POST /api/conversations/{id}/turns`, a field the route already accepts;
the choice is stored per project under `daedalus-effort:<project>` and
defaults to `low`, matching the backend's own default.

### Unchanged

The turn creation POST, its `client_request_id`, the observation-only SSE
GET, the cancel POST, the queue POST with exact `conversation_id`/`turn_id`
attribution, the autonomy rule for automatic dispatch, and all localStorage
keys and DOM/ARIA contracts named in the design record §8.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
| --- | --- | --- |
| Ledger rows derive only from emitted data | Node spec with recorded frame sequences | exact expected rows; absent fields produce no row |
| Commands map only to existing routes/actions | Node spec + live Playwright `/status` | `/status` sends `status`; deterministic stamp `GEMESSEN`; unknown `/x` sent verbatim |
| Local notes are never sent | Node spec + source review | `/hilfe` creates no POST |
| Thread list is canonical | `tests/test_conversation_list.py` on a temp spine | project filter, newest-first, limit, clipping, empty project |
| Resume from the rail | fixture-backed Playwright | choosing a row saves `daedalus-thread:<project>` and renders its turns |
| Existing conversation contracts hold | `tests/cockpit.spec.ts`, `tests/ide.spec.ts`, `spaces`, `app-loads`, `degraded`, `backend-down`, `system-capabilities`, `spend-settings` | all green in Playwright against a served checkout; pre-existing failures named separately |
| Effort is sent, not invented | Playwright request capture | `effort` present in the turn POST body; default `low` |
| No external fetch from model Markdown | static render in the Node spec of an image, raw HTML, a `javascript:` link | alt text rendered, no `img`, no script, no non-http(s) href |
| Directed hierarchy and single root | `npm run test:app` | all checks green, new files under `features/conversation` |
| Motion tiers and CSS parity | `npm run test:motion`; no parity warning in the console during Playwright | green; zero console errors |
| Floor across themes | `node tools/audit.mjs --themes referenz,leitstand,kammer --widths 1440,1280,1024,900` | 0 combinations below the floor |
| Effect boundary unchanged | `registry_sha256()` | exact frozen digest |
| No generated/dependency churn beyond the two packages | Git path diff | only `package.json`/`package-lock.json` entries for react-markdown, remark-gfm and their transitive graph; no `dist` change |

## Migration and rollback

Purely additive. Rollback reverts the frontend packet commits and deletes
the list route with its tests; no schema, key, or state migration exists.
Stored threads keep their existing key and remain readable by the previous
Conversation implementation.

## Evidence, expected failures and review

Builder evidence is appended below when produced. Expected failures named
in advance: `/api/runtimes/status` remains slow on this host (documented in
`docs/design/COCKPIT_ROUND_2026-08-26.md`), so runtime-dependent Playwright
tests keep their existing ceilings; the registered projects on this machine
point at absent checkouts, so live specs use a worktree-registered project.
Review questions: does any row ever render a value the backend did not emit;
can any command reach an effect other than the existing turn POST, queue
POST and cancel POST; does the list route read anything but
`conversation.turn` intents; does any new CSS declare a literal value.

### Builder evidence, 2026-09-02

Measured on this Windows box from the worktree, against `uv run daedalus web
--port 8765` serving the worktree with the worktree registered as project
`daedalus_wt` (the registered projects point at absent checkouts here):

- `uv run python -m pytest tests/test_conversation_on_canonical_spine.py
  tests/test_conversation_requests.py tests/test_web_api.py
  tests/test_web_api_loop.py tests/interfaces/test_bridge_conversation_strangler.py
  tests/contracts/test_work_packet_index.py tests/test_conversation_list.py -q`:
  137 passed, 16 subtests passed.
- `registry_sha256()`: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`
  (exact).
- `npx tsc --noEmit`: clean. `npm run test:app`: 96/96 (resolver, system,
  conversation model/commands, hierarchy, exact shims, production metafile).
  `npm run test:motion`: 130/130.
- `npx playwright test` (all nine specs, one worker, no retries):
  53 passed, 1 skipped (project switch needs two reachable checkouts),
  1 failed: `cockpit.spec.ts` "settings names the brain, the autonomy level
  and what is reachable" expects four autonomy levels while
  `features/settings/autonomy.ts` has carried two since 0d3ea5d1. Pre-existing
  drift; not touched by this packet.
- `node apps/web/tools/audit.mjs --base http://127.0.0.1:8765 --widths
  1440,1280,1024,900 --themes referenz,leitstand,kammer`: 0 of 24
  theme/page/width combinations below the floor.
- Shots of the running application: `docs/design/prototypes/cockpit-2026-09-02/`
  (shoot.mjs set with manifest, plus a resumed thread with its Protokoll open
  and the `/` menu).

Expected failures met, named: `tools/gui_check.py` stops before any spec
because its loop-ui step greps for `@loopui` and no spec carries that tag;
Playwright was therefore driven directly with `DAEDALUS_GUI_BASE_URL`.
Two browser tests that could not pass before this packet were repaired in
passing: the `hidden` attribute lost to `.status-row { display: flex }`
(shell reset now carries `[hidden] { display: none !important }`), and the
tablet toggle test looked up the button by the name it has only while closed.

Independent review (fresh context, read-only, Anthropic): no release-blocking
defect against AGENTS.md. Six findings, all disposed: the rail kept the
previous project's rows while the next list was in flight (fixed: rows reset
on project change and `ThreadList` is keyed by project); the list test's
substring fixture never reached the project re-check (fixed: nested
`envelope.project` fixture, now goes red without the guard); the rail printed
raw runtime ids although the page knew the labels (fixed: labels flow with
the thread state); closing observation left the send claim held so later
sends were silently refused, pre-existing (fixed, one line); `settleTurn`
stored an unnarrowed origin and a route row could be empty (fixed and
pinned in the spec); the empty-context guard was unpinned (pinned).

Cross-vendor second opinion: absent. `daedalus council --live` returned a
DEGRADED quorum of 0 of 2 (`council.anthropic` timeout at the 120 s per-call
cap over 75k evidence tokens; `council.openai` `not_on_path`, the adapter
spawns `codex` where Windows has only `codex.cmd`), transcript
`runs/council/council-20260902T162728Z-7096c982.jsonl`; the direct Codex
channel answered with an exhausted usage limit until 2026-09-07.

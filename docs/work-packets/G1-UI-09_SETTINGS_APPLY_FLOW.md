# G1-UI-09 - Explicit settings apply flow

## Frozen packet metadata

- Packet ID: `G1-UI-09`
- Artifact role: primary
- Active gate: 1
- Classification: `ALIGNED`
- Owner: repository owner
- Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`
- Dependencies: G1-UI-03 frontend ownership; G1-IFACE-DESKTOP-03 canonical
  desktop settings owner; accepted Revision-10 execution-limit policy
- Promotion authority: repository owner; no automatic merge, promotion,
  release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`

## Primary acceptance claim

The existing Settings drawer distinguishes a draft from an applied setting in
its mutable areas: Brain, execution caps, Desktop connections, Team, and
per-agent project autonomy. Every area has an explicit Apply/Save boundary
and a local Discard path. A successful label is shown only after the canonical
owner's response proves the requested effect; an ambiguous transport or
type-valid but unconfirmed response is reconciled with a canonical read while
the affected owner remains locked.

Desktop connection and cap writes use additive, owner-scoped
`section_updates` requests. The canonical Desktop owner merges each request
against the newest document under its existing lock, validates and persists
the result atomically, and advertises `settings_update_contract:
section_updates_v1` in GET/PUT projections without persisting that capability
marker. Project autonomy uses an additive per-agent `agent_updates` patch and
the existing atomic project-row rewrite. Team stays on the existing project
owner. Version 0.1.6 owns no Desktop service-process handle, performs no
managed-child autostart or cleanup, and refuses service stops rather than
deriving process-control authority from observation. It performs no Docker
discovery, inspection, or mutation. No additional public route, settings store,
effectful entrypoint, event store, or policy authority is introduced.

## Baseline reproduced

The first three UI behaviors below were reproduced from the exact frozen base
revision on 2026-09-04. Concurrent working-tree evidence is named separately:

- clicking a Brain or autonomy choice immediately calls the Cockpit owner and
  writes its local-storage key; there is no apply boundary or success state;
- the connection save button remains enabled for an unchanged configuration,
  and its manually latched dirty flag stays dirty after the user restores the
  original value;
- reopening the Settings drawer reloads `TeamSettings` and silently overwrites
  an unsaved team draft, while the connection and cap drafts are retained;
- the concurrent Desktop transaction rewrite durably commits the new config
  before route retirement, but then selects IDE cleanup from that new mode;
  in-memory reproduction retained the old native process on native-to-Docker
  and the old owned container on Docker-to-native. That negative evidence is
  retained; the v0.1.6 resolution removes managed Docker authority instead of
  emulating that historical cleanup path;
- the repository-owned browser baseline was started separately; the optional
  `agent-browser` screenshot adapter failed to connect on this Windows host, so
  no screenshot-only accessibility claim is made;
- `npm.cmd run test:app` passed 435/435 and TypeScript passed; the focused
  desktop suite passed 103 tests with one unrelated, pre-existing semantic
  Effect Registry digest mismatch retained as negative evidence.

## Scope

In scope:

- `apps/web/src/features/settings/Settings.tsx`: staged Brain preference,
  explicit apply/discard, semantic cap and connection dirty state, strict
  Desktop projection validation, owner-scoped payloads, per-field rebase,
  write/service locks, and canonical reconciliation after uncertain outcomes;
- `apps/web/src/features/settings/Team.tsx`: retain a dirty draft across a
  same-project drawer close/reopen, isolate state by project generation, keep
  in-flight locks/errors safe across A-to-B-to-A, validate the confirming Team
  projection, reconcile uncertain writes, and provide an explicit discard
  action;
- `apps/web/src/features/settings/settings.css`: reuse the current settings
  button language for grouped actions and visible dirty/success states;
- `apps/web/src/app/Cockpit.tsx` and the existing dialog-focus hook: keep the
  Settings drawer's keyboard focus inside the open modal, make background
  branches inert while preserving the pointer-dismiss scrim, prevent a second
  shell overlay from opening underneath it, and return focus to the opener;
- `apps/web/src/features/system/SystemCapabilities.tsx`, its API adapter, and
  styles: stage project-scoped agent autonomy, persist the draft per project,
  submit only `agent_updates`, and require both autonomy-map and profile
  projections to confirm the requested value;
- `apps/web/src/shared/api/index.ts`: reuse the canonical API client's typed
  HTTP/network/timeout failures for Desktop settings and service requests;
- `daedalus/orchestration/control_plane.py`: atomically merge validated
  per-agent autonomy changes without replacing sibling agents or unknown
  autonomy fields, while retaining the established full autonomy patch;
- `daedalus/interfaces/desktop/settings.py`, `http.py`, `effects.py`, their
  existing configuration/projection helpers, and `daedalus/desktop_runtime.py`:
  validate and atomically merge one Desktop owner group, advertise the
  capability marker, admit prospective effects through the canonical owner,
  normalize legacy autostart flags to false, never start managed child
  processes from settings or bootstrap, keep remote SSH unavailable, permit
  local Ollama only through explicit probe/adoption, retain no process-control
  route after durable save, and surface strict post-commit adoption failure in
  the confirming snapshot;
- focused frontend app/browser tests for apply, discard, validation,
  close/reopen, A-to-B-to-A generation/lock behavior, malformed or silently
  ignored responses, and definite-versus-ambiguous failures;
- focused project-row, Desktop-owner, effect-admission, and IDE route-switch
  tests;
- this Work Packet and run evidence.

Forbidden:

- a new API route, settings file, local-storage key, backend owner, event store,
  effect path, policy rule, evaluator, or promotion path;
- weakening execution-limit widening confirmation, credential handling,
  effect admission, unowned-process cleanup, or the Master Plan;
- presenting remote SSH as available before exact peer, key-custody, and
  transport contracts exist;
- presenting several backend writes as one atomic transaction.

## Contracts and behavior

Brain remains a Cockpit-owned presentation preference with its established key
and callback. The former browser-local Automatik preference is inert and no
longer rendered or read: it could turn an unversioned, project-spanning UI value
into an automatic work dispatch. Suggestions now require their visible
`Loslegen` action. Per-agent project autonomy remains a separate canonical,
explicitly applied setting. The drawer owns only an ephemeral Brain draft.
Applying calls the existing callback at most once and only when that field
changed; discarding restores the current Cockpit value without a write. Closing
and reopening the drawer preserves a dirty draft; neither the close button nor
Escape is an implicit apply or discard action. A Brain choice is applicable
only after a current runtime read proves it reachable. Stale requests cannot
re-enable a missing runtime. The radio group implements Arrow/Home/End movement
with one tab stop; when a selected runtime becomes disabled, the available
automatic choice remains keyboard-reachable.

Connection dirtiness is derived from the editable `bridge` and `ollama`
subtrees against the last confirmed desktop snapshot. Cap-only server updates
do not make the connection form dirty. Returning every connection field to its
confirmed value disables save and permits service actions again. Discarding
copies the confirmed subtrees back into the draft without touching caps,
budget, IDE settings, or the server. Connection writes contain exactly the
`bridge` and `ollama` sections; cap writes contain exactly `budget` and `caps`.
The backend rejects malformed, cross-owner, or unsupported `section_updates`
before changing the document or starting an effect. The same owner lock covers
merge, validation, persistence, route retirement, environment projection, and
the confirming snapshot, so two stale owner drafts compose instead of
overwriting one another. All v0.1.6 `auto_start` controls are unavailable:
legacy true values normalize to false, and neither save nor bootstrap calls a
managed start port.

The frontend never sends owner-scoped writes to a Desktop backend that omits
the `section_updates_v1` marker. A marker-bearing HTTP 200 must also contain a
valid Desktop projection whose normalized requested fields match the intent.
Network errors, timeouts, HTTP 5xx responses, malformed success projections,
and silently ignored writes are uncertain outcomes: the draft is retained, a
canonical GET is performed before unlocking, and untouched fields rebase onto
the new confirmed snapshot. HTTP 4xx and explicit application rejections are
definite: their reason is shown, the draft is retained, transient widening
consent is cleared, and no needless reconciliation GET is issued. Service
actions use the same uncertainty classification and lock.

Cap values must be finite positive values (and calls a positive safe integer),
with invalid controls exposed through `aria-invalid` and linked help/error
text. Widening consent is transient and is invalidated by every relevant edit
or newer baseline. Cap and connection drafts remain independent across saves
and refreshes.

Remote SSH remains a readable compatibility state, not an available action.
The selector disables new remote selection, both Bridge and Ollama start are
blocked while a retained canonical remote route is active, the backend refuses
prospective remote section updates before an effect, and the environment does
not project tunnel consent or peer trust. A retained remote document can only
be repaired back to local mode. Managed Bridge and IDE start remain
unavailable; local Ollama is usable only through an explicit probe/adoption
action and is never spawned as a managed child.

Team drafts remain project-scoped. A dirty draft survives a close/reopen of
the same project; changing project intentionally loads the selected project's
canonical state without leaking the previous draft. A clean reopen refreshes
from the backend. Discard is local and sends no PUT. Save sends only fields
that changed. An in-flight save, its lock, and any delayed error remain keyed
to the originating project across A-to-B-to-A. The response must name
the requested project, contain a valid full Team projection, and either confirm
each changed field or explicitly list it in `ignored_fields`; otherwise the
outcome is uncertain and a same-project canonical read settles under the
project write lock. Unconfirmed submitted fields remain editable after rebase.

Agent-autonomy drafts are likewise project-scoped and survive A-to-B-to-A.
Apply sends only `{agent_updates: {<profile>: <mode>}}`. The backend merges the
agent under the project-row lock and returns the canonical control projection.
The response confirms success only when the project identity, autonomy agent
map, named profile, and that profile's `agent_override` all agree. An older or
inconsistent HTTP 200 is uncertain and triggers a canonical read before the
project lock releases; a read failure never erases the draft.

Desktop route adoption remains inside the canonical settings owner and happens
only after the new document is durably saved. There is no v0.1.6 managed
service-process handle to retire: `stop_ide` and the other service-stop routes
refuse and perform no process control, Docker discovery, inspection, or removal.
A strict post-commit route or environment adoption failure is returned as
`startup_error`; it does not roll back or misrepresent the already durable
document.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
| --- | --- | --- |
| General settings have one apply boundary | browser test | choice changes UI draft; storage/runtime owner remains unchanged until Apply |
| Apply is minimal | browser request/state test | unchanged field callback/write is absent; changed fields apply once |
| General discard is non-effectful | browser test | draft resets and established storage keys remain unchanged |
| General close is non-effectful | browser test | dirty draft survives close/reopen; established storage keys remain unchanged |
| Brain availability and keyboard contract | browser test | stale loads cannot apply an unreachable Brain; enabled radios support Arrow/Home/End and retain one valid tab stop |
| Settings is a real modal | browser test | focus enters and remains in Settings, background branches are inert, the scrim still dismisses, competing shortcuts stay closed, and focus returns to the opener |
| Project autonomy is explicitly applied | browser request test | selection alone sends no PUT; Apply sends one `agent_updates` field; Discard sends none |
| Autonomy draft and lock are project-scoped | browser test | unsaved A survives A-to-B-to-A; an in-flight A write stays locked and its delayed error is reported after return |
| Autonomy success proves its effect | app/browser and project-row tests | project, autonomy map, profile, and `agent_override` agree; stale/inconsistent HTTP 200 reconciles; sibling agents survive concurrent patches |
| IDE route switch grants no process control | in-memory Desktop tests | either desired mode keeps stop authority unavailable; no child termination, Docker discovery, inspection, or mutation occurs |
| Post-commit adoption failure stays truthful | Desktop owner test | durable config remains committed and the confirming snapshot contains the strict adoption error |
| Unavailable autostart stays truthful | UI/config/Desktop tests | controls are disabled, legacy true values normalize to false, save/bootstrap call no managed start port, and local Ollama probe/adoption remains explicit |
| Connection dirty state is semantic | browser test | change marks dirty; exact revert clears dirty and disables Save |
| Clean connection draft cannot write | browser request count | zero PUTs before a real change |
| Connection discard is scoped | browser payload/state test | bridge/ollama reset; cap draft and server remain untouched |
| Desktop capability is explicit | browser/HTTP tests | UI refuses writes without `section_updates_v1`; marker is emitted on GET/PUT and is never persisted |
| Desktop owners compose atomically | payload and concurrent owner tests | connection sends bridge/ollama, caps send budget/caps, stale writes merge with newest document and preserve all other sections |
| Malformed Desktop input is non-effectful | Desktop tests | malformed/cross-owner updates return 400 and leave configuration bytes, environment, effect ledger, and services unchanged |
| Desktop success proves its effect | browser tests | malformed or silently ignored HTTP 200 never shows success; canonical reread settles while the owner remains locked and preserves unconfirmed draft fields |
| Definite and uncertain failures differ | browser request-count tests | 4xx/application refusal retains draft without GET; network/timeout/5xx/unconfirmed success performs one canonical reconciliation before unlock |
| Cap consent and validation stay strict | browser/Desktop tests | invalid fields are announced and cannot PUT; every widening needs transient consent; rejection/refresh clears it; no sentinel value is accepted |
| Cap and connection drafts stay isolated | browser payload/rebase tests | either owner can save/refresh without overwriting or spuriously dirtying the other; untouched fields adopt canonical normalization |
| Remote SSH remains unavailable | browser/effect-admission tests | new remote selection and service start are disabled/refused; retained remote state is readable and repairable only to local; local stays usable |
| Dirty team draft survives same-project reopen | browser test | draft value retained and no PUT |
| Team discard is non-effectful | browser test | confirmed value restored and no PUT |
| Team success proves its effect | response-contract/browser tests | requested project and a valid full projection are required; missing/malformed or silently ignored projections reconcile and never claim success; explicit ignored fields are reported |
| Team project generation is safe | browser tests | clean reopen refreshes, A/B drafts do not leak, and an in-flight A write remains locked across A-to-B-to-A |
| Existing boundaries hold | TypeScript, app spec, focused Python/browser suites | packet-owned checks are green; every concurrent or environmental failure is named with its exact scope |
| No new public authority | source and Registry review | existing callbacks/routes and canonical owners only; additive request members do not create a second settings or promotion path |

## Migration and rollback

There is no persistent-data rewrite: the backend document shapes remain
unchanged. A pre-existing browser-local Automatik key or log may remain in a
browser profile but is never read and cannot dispatch work. The Brain key stays
unchanged. Legacy true `auto_start` values are
canonicalized to false in projections and on the next save; no new field is
introduced. `settings_update_contract` is a response capability, not stored
configuration; `section_updates` and `agent_updates` are additive request forms
whose results are merged into the existing documents. Rollback first restores
the callers to the compatible full-document contracts, then removes the
additive forms and ephemeral draft/actions. No ledger, project row, or
configuration file needs rewriting.

Independent review must check that apply is explicit, discard performs no
write, project-scoped retention cannot leak into another project, response
validation proves the requested effect, uncertain outcomes reconcile before
unlock, definite refusals do not issue hidden reads, cap widening still
requires transient confirmation, remote SSH remains unavailable, and no clean
or malformed draft can start an effect.

## Evidence, expected failures and review

An intermediate `test_effect_registry_contract_is_stable` failure was outside
this packet: its frozen digest differed from the semantic Registry assembled by
other concurrent working-tree changes. The Settings work did not change that
expectation. Its Registry owner subsequently updated the freeze and the final
owner-file rerun below is green.

Recorded implementation evidence during this packet:

- `npm.cmd exec -- tsc --noEmit` passed after the settings/autonomy changes;
- `npm.cmd run test:app` passed 444/444 after the final Settings, Team, and
  project-autonomy fixtures were corrected;
- `npm.cmd run build` passed with 728 transformed modules. Rollup retained its
  existing advisory that the main minified chunk is larger than 500 kB;
- `.venv\Scripts\python.exe -m pytest tests/test_project_row_rewrite.py -q`
  passed 62 tests, including per-agent merge, invalid-update byte preservation,
  canonical projection, and disjoint Team/autonomy writes;
- the focused Desktop effect-admission selection passed 14 tests, including
  prospective local-route admission and pre-effect remote refusal;
- the Desktop Settings owner selection passed 12 tests with only the unrelated
  Registry digest test deselected, and the broader
  `tests/test_desktop_runtime.py -k "settings or effect_admission"` selection
  passed 31 tests with 79 deselected;
- the complete `tests/test_desktop_runtime.py` file passed 110/110 and the final
  complete Desktop Settings owner file passed 13/13. The prior 12-pass/1-fail
  Registry result remains retained as intermediate, out-of-packet evidence;
- an intermediate `npm.cmd run test:app` run exposed a stale System fixture
  whose mocked success projection omitted the newly required matching project/
  profile confirmation. That negative evidence is retained and the final
  444/444 rerun above demonstrates the correction;
- an intermediate broader Desktop selection passed 126 tests and failed 11
  around concurrent effect-owner/CLI/literal-digest fixtures. Those failures
  are retained as an intermediate result; the final owner and broader settings
  selections above classify their Settings-owned replacements as green;
- `DAEDALUS_GUI_SUITE_TIMEOUT_S=1200 tools/gui_check.py --json` ran 200 browser
  specs against the production build: all Settings, Team, modal-focus, and
  project-autonomy specs passed. The receipt was 199 passed and one failed
  because the independent Genesis preview returned HTTP 404 while its backend
  implementation was being rewritten by concurrent work. The run remains a
  harness-level `FAIL`; the residual is not represented as a Settings failure.
  Two subsequent whole-suite attempts were stopped without a verdict when the
  same out-of-packet Genesis source changed again during their runs; no mixed-
  revision receipt is represented as evidence.

No reference screenshot was supplied and the optional screenshot adapter did
not produce a comparable capture, so this packet makes no visual-regression or
pixel-parity claim. Functional browser evidence comes only from the
repository-owned harness, which owns server lifecycle and loopback admission;
screenshots alone would not have been accepted as QA.

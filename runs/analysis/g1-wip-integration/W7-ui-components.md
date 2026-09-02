# W7 — wip UI components vs main's frontend structure and backend

Scope: read-only analysis of `wip/g1-freeze-2026-08-31` against `main` @
`851ff43c` (repo currently checked out at `b3cc415b`, no branch switched, no
tracked file touched). All content read via `git show <ref>:<path>` /
`git cat-file` / `git diff --numstat`. No test/build ran.

## (a) Structural fit verdict

**Wip's UI predates main's directed hierarchy; it does not fit it, and the
mismatch is total, not partial.**

Main landed `docs/work-packets/G1-UI-03_FRONTEND_DIRECTED_HIERARCHY.md`
(Base revision `e133e09b`, after the `151b8d18` merge-base): every
implementation file must live under `src/app`, `src/features/<owner>`, or
`src/shared/{api,contracts,ui}`, with `src/main.tsx` as the only bootstrap
facade. Old paths survive only as registered, exact-body reexport shims
(`src/api.ts`, `src/types.ts`, `src/cockpit/Cockpit.tsx`, …) — never as a
second implementation.

Wip never adopted that hierarchy. `git ls-tree` diff of `apps/web/src`
between the two trees:

- **Only on main** (56 files): the entire `app/`, `features/*`, and
  `shared/*` trees — i.e. exactly the G1-UI-03 target layout.
- **Only on wip** (~90 files): a flat `cockpit/`, `components/` (incl.
  `components/glass/*`), `hooks/`, `theme/`, `motion/`, `views/`, plus a
  root `App.tsx`, `styles.css`, `mission-control.css`. This is the
  pre-G1-UI-03 shape the packet explicitly strangled.

None of wip's new files sit under `app/`, `features/`, or `shared/`. Every
wip-only UI addition is an addition to the *old* shape main just retired.
Integrating it means re-homing each file into the new hierarchy, not a
line-level merge of parallel structures.

## (b) Per-component integrability — the 4 headline components

| Component | Lines | Renders | `/api` calls | Imports | Every import resolves on main? |
|---|---|---|---|---|---|
| `cockpit/CockpitInspector.tsx` | 427 | Read-only 3-tab (Activity/System/Project) inspector sheet: queue, attempts, dashboard/inbox, health, governance, runtime/provider readiness, project + control-plane + host-capability facts | `getDashboard`, `getLoopQueue`, `getLoopAttempts`, `getHealth`, `getRuntimeStatus`, `getProviderStatus`, `getControlPlane`, `getProjects`, `getHostCapabilities`, `getDesktopStatus` | `../api`, `../components/glass` (→`GlassSheet`), `../types`, `./inspector.css` (colocated, new) | **No.** `../components/glass` is gone on main. |
| `cockpit/ReviewSheet.tsx` | 684 | Read-only evidence/diff review sheet: task facts, 6 independent status axes (patch/candidate/evidence/review/integration/promotion), dispatch timeline, changed-file list with "open read-only candidate in IDE" action, tests/risks/todos/receipts/negative-evidence/artifact-ref lists | `getTask`, `getTaskArtifacts`, `getHostCapabilities`; delegates the actual editor jump to an injected `onOpenInIde` prop | `../api`, `../components/glass/GlassSheet`, `./review.css` | **No.** Same `GlassSheet` gap. |
| `cockpit/ThreadDirectory.tsx` | 254 | Read-only, searchable conversation-directory sheet (title/preview/turn-count/open-dispatch-count/last-evidence per row), selection guarded while a turn is in flight | `getConversationDirectory` only | `../api`, `../components/glass/GlassSheet`, `./thread-directory.css` | **No.** Same `GlassSheet` gap. |
| `hooks/useDialogFocus.ts` | 200 | Not a component — a focus-trap/Escape/return-focus hook with a module-level dialog stack (`inert` on close, Tab containment, restores focus to the opener) | none | **zero project imports** — pure React/DOM | **Yes**, trivially; nothing to resolve. |

All three sheet components share one hard dependency: `components/glass/GlassSheet`
(and, through it, `hooks/useDialogFocus` and the `motion` module). That import
target is the actual integration blocker, not the individual components —
see (d).

`../api` and `../types` **do** resolve on main, because G1-UI-03 kept those
exact paths alive as one-line reexport shims (`export * from './shared/api'`,
`export * from './shared/contracts'`). Confirmed by reading both files at
`main`. The specific functions/types each component needs
(`getDashboard`, `getTask`, `getConversationDirectory`, `TaskArtifacts`,
`ConversationDirectory`, etc.) were not individually re-verified against
`shared/api`/`shared/contracts` content — ASSUMED present given the packet's
"public function names, types, URLs… unchanged" claim, not independently
enumerated here.

## (c) Conflict cost ranking — the 9 content-conflict files

Two numbers matter and they diverge sharply. Git's raw `merge-base→main`
numstat at the *old* path is inflated because G1-UI-03 reduced almost every
old path to a 1-line shim (that is not real conflict cost — it is a rename
main's history doesn't credit as one). The real main-side cost is the diff
between the merge-base content and main's *new* canonical path, i.e. what
main actually changed beyond moving the file. Ranked by total integration
effort (wip's real edit + main's real edit), cheapest first:

| File | wip diff (ins/del, merge-base→wip) | main's real change (merge-base old path → main new path) | New home on main | Cost rank |
|---|---|---|---|---|
| `cockpit/Decision.tsx` | 3 / 7 (10 total) | ~4 lines (import paths only) | `features/mission/Decision.tsx` | 1 — cheapest |
| `cockpit/ProjectDialog.tsx` | 30 / 15 (45) | ~4 lines (import paths only) | `features/projects/ProjectDialog.tsx` | 2 |
| `cockpit/Settings.tsx` (+`settings.css`) | 88 / 40 + 15 / 1 (144) | ~18 lines (import paths + new `project` prop + mounts `SystemCapabilities`) | `features/settings/Settings.tsx` | 3 |
| `types.ts` | 187 / 2 (189) | ~13 lines (import paths only) | `shared/contracts/index.ts` | 4 |
| `tests/ide.spec.ts` | 218 / 18 (236) | 2 / 2, but **same path, real semantic change**: assertion changed from `{ project: project.repo_root }` to `{ project: project.name }` — a live backend-contract change, not a rename artifact | unchanged path | 5 — small diff, high semantic risk |
| `cockpit/Cockpit.tsx` | 175 / 33 (208) | ~50 lines (import paths + composition changes; this is the app's orchestration root) | `app/Cockpit.tsx` | 6 |
| `cockpit/IdeWorkspace.tsx` | 269 / 45 (314) | ~18 lines (import paths only) | `features/ide/IdeWorkspace.tsx` | 7 |
| `api.ts` | 446 / 129 (575) | ~24 lines (import paths only, `request()` internals untouched) | `shared/api/index.ts` | 8 |
| `cockpit/Conversation.tsx` | 1460 / 186 (1646) | ~26 lines (import paths only) | `features/conversation/Conversation.tsx` | 9 — most expensive by far |

Reading the table: for 7 of 9 files, main made a **pure mechanical move**
(import-path rewiring only, confirmed by diffing merge-base's old-path
content directly against main's new-path content — 4 to 50 lines of real
change). The entire cost of these 7 conflicts is porting wip's real edits
onto the new path; main contributes almost nothing to fight. `Conversation.tsx`
carries essentially all of the expensive-conflict risk in this set (1646
changed lines to re-home). `tests/ide.spec.ts` is the one file where main's
tiny diff is not noise — it is a genuine, opposing behavioral change to the
IDE-start request contract (`repo_root` → `name`) that wip's rewritten spec
does not know about.

## (d) App.tsx / GlassSheet.tsx modify/delete conflicts

**`apps/web/src/App.tsx`** — category **(c) obsolete, already superseded**.
High confidence. At the merge-base, `App.tsx` was already a large (~1870-line)
*legacy* application shell (`MissionControl`, `GraphSpace`, `KnowledgeSpace`,
`useLoop`, the `classic`/`legacy` query-alias surface) — a different,
older UI paradigm than the Cockpit that both branches actually ship.
Wip's edit against it is small (129/112 lines) — a maintenance touch, not new
product work. Main deletes it outright (0/1870) and replaces the bootstrap
role with `src/main.tsx` → `app/bootstrap.tsx` → `app/SurfaceRoot.tsx` →
`app/Cockpit.tsx` (verified by reading all four on main: a plain
`createRoot` + `<ThemeProvider><Cockpit/></ThemeProvider>` composition).
Main's replacement is smaller, cleaner, and already covers the one job
`App.tsx` needed to do (mount the app). Nothing in wip's small `App.tsx` diff
looks like it needs rescuing — the legacy shell it edits is dead weight on
both branches; main only formalizes that by deleting it. **ASSUMED**: no
attempt was made to line-by-line diff wip's 129 changed lines against the
legacy shell's surviving readers (there are none on main), because the
premise — that shell isn't the shipped UI on either side — makes that
unnecessary for an integration verdict.

**`apps/web/src/components/glass/GlassSheet.tsx`** — category **(b) lost
work needing re-homing**. High confidence, and this is the one that actually
matters for (b): wip's edit here is small (15/6 lines) and, per the file
content, is exactly the wiring of `useDialogFocus` into the sheet's focus
trap (the component's docstring and dialog-ref plumbing match). Main deletes
the file outright (0/71) and **does not replace it with anything
equivalent**. Main's only glass-family primitive is
`shared/ui/glass/GlassSurface.tsx` — confirmed by reading it — which is a
decorative SVG-displacement-filter panel (`width`, `height`, `blur`,
`distortionScale`, …) with no `open`/`onClose`/focus-trap/scrim semantics at
all; it is not a modal. A repo-wide check for `role="dialog"` on main finds
exactly two hand-rolled instances (`app/Cockpit.tsx`, one; and
`features/projects/ProjectDialog.tsx`), neither wired to a shared
accessible-sheet component. **Main's new hierarchy has no reusable modal/sheet
primitive.** `GlassSheet` (and by extension `useDialogFocus`, which main
never received either) is therefore not reimplemented anywhere on main — it
needs to be ported in, not merged. Because main's side of this file is a
clean full deletion (0 insertions), there is no real merge conflict to
resolve on `GlassSheet.tsx` itself: the practical path is copying wip's
`GlassSheet.tsx` + `hooks/useDialogFocus.ts` + the small `components/glass/util.ts`
(`cx` helper) into a new `shared/ui/glass/GlassSheet.tsx` (or similar) on
main, since `shared/ui/motion` — which `GlassSheet` also imports — is
**already present on main with byte-identical exports**
(`surfaceVariants`, `scrimVariants`, `useReducedMotionPref`, confirmed by
diffing `variants.ts` and reading `useMotion.ts` on both sides).

## (e) Blocked-vs-independently-integrable

None of the 3 missing backend routes
(`/api/desktop/editor/commands`, `/api/desktop/editor/open`,
`/api/editor/instance-proof`) are called from inside the 4 headline
components themselves:

- `CockpitInspector.tsx` — no editor call at all (display-only; exposes an
  `onOpenConversation` callback, unrelated to the editor routes).
- `ReviewSheet.tsx` — takes an injected `onOpenInIde` **callback prop**; it
  never calls `fetch`/`sendDesktopEditorCommand` itself. The actual caller of
  `sendDesktopEditorCommand` (→ `/api/desktop/editor/commands`) is
  `cockpit/Cockpit.tsx:392`, one layer up.
- `ThreadDirectory.tsx` — no editor call (`getConversationDirectory` only).
- `useDialogFocus.ts` — no network calls of any kind.

Tracing the two `/api/desktop/editor/*` routes in `apps/web/src/api.ts`:
`openDesktopExternalEditor` (→ `/api/desktop/editor/open`) is called only
from `cockpit/IdeWorkspace.tsx:218` ("open externally" button);
`sendDesktopEditorCommand` (→ `/api/desktop/editor/commands`) is called only
from `cockpit/Cockpit.tsx:392` (the handler passed into `ReviewSheet` as
`onOpenInIde`). Neither call site is one of the 4 headline components.

`/api/editor/instance-proof` is **not called from `apps/web/src` at all** —
it only appears in `daedalus/desktop_runtime.py`, `daedalus/web_api.py`
(server-side), `vscode-agent-env/extension.js` (the VS Code extension), and
`tools/smoke_tauri_sidecar.py`. If "wip UI" in the task framing meant to
include the VS Code extension surface, that surface is a separate JS file
outside `apps/web/src` and outside scope of this component-level analysis;
it was not otherwise implicated by any of the 4 headline components.

**Verdict:**
- `ThreadDirectory.tsx` and `CockpitInspector.tsx` are purely presentational
  read-only projections — integrable independently of the 3 missing
  endpoints, gated only on (d)'s `GlassSheet` port and the `../api`/`../types`
  shim surface actually containing every function/type they use (ASSUMED,
  not individually enumerated — see (b)).
- `ReviewSheet.tsx`'s core (evidence/diff/timeline display) is likewise
  independently integrable; only its one "open read-only candidate in IDE"
  button is functionally blocked, and it degrades gracefully already —
  `hasExactCandidateNavigation` gates the button on `onOpenInIde` being
  provided at all, so omitting that prop during a partial integration hides
  the button rather than breaking the component.
- The actual blocked surface is one layer up, in `Cockpit.tsx` (`sendDesktopEditorCommand`)
  and `IdeWorkspace.tsx` (`openDesktopExternalEditor`) — both of which are
  independently in the expensive tier of table (c) regardless of the backend
  gap.

## Effort estimates — all ASSUMED

No implementation was attempted; every relative-cost judgment above is a
line-count/structural proxy, not a measured porting time. Two flags worth
carrying forward, both ASSUMED-important:

1. `tests/ide.spec.ts` hides a real, opposing contract change
   (`repo_root` → `name` for the IDE-start body) inside a numerically tiny
   diff — a naive "cheapest first" ranking by raw line count would miss it.
2. The `GlassSheet` gap is structural, not per-file: every wip sheet-shaped
   component (the 3 headline ones here, and likely others outside this
   task's 4-component scope) shares the same blocker and the same fix.

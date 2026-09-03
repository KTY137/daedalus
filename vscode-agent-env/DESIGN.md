# Mission Control v1 — Design System

Design spec for the 5-tab Mission Control webview (Overview, Queue Timeline, Agent Squads,
Model Resources, Quality Gates) over the `daedalus` harness. Written for direct 1:1 port into
the existing `vscode-agent-env` webview (see `extension.js` `dashboardHtml`, which already uses
top tabs and `--vscode-*` variables — this spec extends that convention rather than replacing it).

> **Status, MEASURED 2026-07-29 — read before touching `dashboardHtml`.** The template this
> spec describes has zero callers in `extension.js`. Both real webview entry points
> (`daedalus.openDashboard` and the Activity Bar view) render `agentOsHtml()`: an iframe onto
> the React app in `apps/web/`, which is where the live Mission Control / Ikarus cockpit
> actually renders today (its own trio surface — map / chat / ide — is documented in
> `apps/web/src/app/Cockpit.tsx`, not here; it was chat / graph / knowledge in
> `apps/web/src/App.tsx` until G1-UI-02 retired the Classic app in `e133e09b`).
> `extension.js` carries a code comment above `dashboardHtml`
> explaining this, and `tests/test_ui_governance.py::test_dead_mission_control_template_is_labelled_not_believed`
> holds that comment to the code. The sections below are kept as a historical/reference spec —
> useful if these tabs are ever revived as a real, non-iframed surface — not as a description of
> what a user sees today. Section 5 below documents what the extension actually renders natively
> now: the backend-bootstrap states around that iframe, and the chat-first entry points.

## 1. Layout

**Top tab bar, not a left rail.**

- The webview runs as a `WebviewView` (sidebar panel, ~320–420px wide) as well as an editor-tab
  panel. A left rail eats ~120px of an already-narrow surface and forces two-level nesting
  (rail item → content) for what is really one flat list of 5 views.
- `extension.js` already renders a horizontal `.tabs` / `.tab.active` bar for the current
  dashboard. Reusing that exact pattern means Icarus-Jr ports CSS classes 1:1, no re-architecture.
- Tabs read left-to-right in priority order: **Overview** (the "is everything OK" glance) →
  **Queue Timeline** → **Agent Squads** → **Model Resources** → **Quality Gates** (deepest/least
  frequently checked, rightmost).
- **Role Wheel** adds a 6th tab, rightmost of all: a radial browser for the role-category
  taxonomy (browse categories, inspect routing presets, recolor/re-icon). It's checked even less
  often than Quality Gates once initial squad setup is done, and its content is a single self-
  contained widget rather than a stack of sections, so it sits past the deepest existing tab. See
  `wheel-mock.html` for the standalone static mock — port its markup/CSS into the same
  `.tabs` / `.panel-view` shell `extension.js` already uses for the other five tabs.

Structure per tab: sticky header (title + optional warning banner) → scrollable content area.
Content area uses a single-column stack on narrow widths; components that are naturally
row-based (KPI tiles, squad cards) wrap via `flex-wrap` / auto-fit grid so the same markup works
at both sidebar width and full-editor width.

### Spacing scale

4px base unit, matching the tight paddings already in `extension.js` (`14px 16px`, `6px 8px` etc.
round to these steps):

| token | value | use |
|---|---|---|
| `--space-1` | 4px | icon-to-label gaps, chip internal padding |
| `--space-2` | 8px | badge padding, tight row gaps |
| `--space-3` | 12px | card padding, panel padding |
| `--space-4` | 16px | section padding, header padding |
| `--space-5` | 24px | gaps between major sections |
| `--space-6` | 32px | empty-state vertical centering |

### Type scale

VS Code webviews default to 13px body text — do not fight that. Scale is intentionally shallow
since this is a dense instrument panel, not a marketing page.

| token | size | weight | use |
|---|---|---|---|
| `--text-micro` | 11px | 500 | badges, pill labels, timestamps |
| `--text-small` | 12px | 400 | muted/secondary text, table sub-rows |
| `--text-base` | 13px | 400 | body text, row labels (matches VS Code default) |
| `--text-medium` | 13px | 600 | row primary text, card titles |
| `--text-large` | 15px | 600 | tab-panel section headers |
| `--text-xl` | 18px | 600 | KPI tile numeric value only |

## 2. Color

Semantic tokens map to VS Code theme variables so the panel themes correctly in every light/dark/
high-contrast theme without any JS re-render. Each has a hardcoded fallback (2nd arg to `var()`)
for standalone-browser rendering of `mockup.html`.

| semantic token | VS Code variable | fallback (dark) |
|---|---|---|
| `--mc-surface` | `--vscode-editor-background` | `#1e1e1e` |
| `--mc-surface-elevated` | `--vscode-sideBar-background` | `#252526` |
| `--mc-surface-card` | `--vscode-editorWidget-background` | `#252526` |
| `--mc-text` | `--vscode-foreground` | `#cccccc` |
| `--mc-text-muted` | `--vscode-descriptionForeground` | `#9d9d9d` |
| `--mc-border` | `--vscode-panel-border` | `#2b2b2b` |
| `--mc-accent` | `--vscode-textLink-foreground` | `#3794ff` |
| `--mc-focus` | `--vscode-focusBorder` | `#007fd4` |
| `--mc-success` | `--vscode-testing-iconPassed` | `#73c991` |
| `--mc-warning` | `--vscode-editorWarning-foreground` | `#cca700` |
| `--mc-danger` | `--vscode-testing-iconFailed` | `#f14c4c` |

Data accents (size bars, gauges, per-lane color coding) use the theme's chart palette so they
stay distinct from status semantics and adapt per-theme:

`--vscode-charts-blue`, `--vscode-charts-green`, `--vscode-charts-orange`,
`--vscode-charts-purple`, `--vscode-charts-yellow`, `--vscode-charts-red`.

**One accent, used sparingly**: `--mc-accent` appears only on the active-tab underline, the
selected squad-card border, and link-style actions (e.g. "copy command"). It is never used for
large surface fills. Primary buttons keep using `--vscode-button-background` (already correct in
`extension.js`) — Mission Control does not introduce a second brand color.

## 3. Components

Every component below lists the states it must support. "Never color-only" means every
color-carrying state also has a text label or icon glyph.

### Overview

**Status tile (KPI row)** — 4 tiles: Provider Health, Watcher, Routing Lane, Enforcement.
- Default: icon + label + value + one-line sub-text, `--mc-surface-card` bg, `--mc-border` 1px.
- Hover: border brightens to `--mc-accent` at 40% (tile is clickable → jumps to relevant tab).
- Selected/focus-visible: 2px `--mc-focus` outline, offset 2px.
- Loading: label + value replaced with a shimmer bar (`--mc-border` background, no motion-heavy
  animation — a static skeleton with subtle opacity pulse is enough).
- Empty (e.g. no project selected): icon dimmed, value shows "—", sub-text "Select a project".
- Error (e.g. provider check failed to run): danger-colored left border (3px) + icon changes to
  a warning glyph + sub-text explains the failure, never just a red tile with no text.

**Warning banner** — full-width strip under the header, one per active warning (stackable, max 3
visible + "N more"). Icon + text, `--mc-warning` left border (3px), `--mc-surface-elevated` bg.
Dismissable (x) is optional; if present, dismiss only hides for the session, not permanently.

### Queue Timeline

**Timeline row** — one per queue item (pending / report / processed).
- Layout: lane badge, status badge, item name + timestamp, one-line summary, right-aligned kind tag.
- Lane badge: text label always shown (`local_only`, `local`, `auto`, `claude`) with a small
  charts-color dot — color is decoration, the word is the meaning.
- Status badge: `done` (success + check glyph), `blocked` (warning + pause glyph),
  `needs_review` (accent + eye glyph), `failed` (danger + x glyph). Label text always present.
- Default row: 1px bottom border, transparent bg.
- Hover: `--mc-surface-elevated` bg.
- Selected/expanded: click reveals full summary + error text in a nested `<pre>`-style block,
  border-left 2px `--mc-accent`.
- Failed-row emphasis: 3px `--mc-danger` left border + faint danger-tinted bg
  (`color-mix`-free: just the elevated surface token, kept subtle) so it reads as urgent without
  relying purely on the badge color.
- Empty state: centered icon + "No queue activity yet" + hint text pointing at how tasks get
  queued, `--space-6` vertical padding.
- Loading: 3 skeleton rows (label-shaped bars only, no fake data).

### Agent Squads

**Squad card** — one per squad (Core, UI, Hardware, Docs, QA, Research).
- Header: squad name + agent count.
- Body: wrapping row of **agent chips**.
- Agent chip: `call_name` (or `name` fallback) as primary text, small `model_tier` badge
  (e.g. `local-7b`, `claude`), an `external_ok` glyph+label (🔓 "external ok" / 🔒 "local only" —
  never rendered as a bare colored dot), and an active-toggle look (pill switch, filled +
  `--mc-accent` when active, outline + muted when inactive).
- Default: `--mc-surface-card`, 1px border.
- Hover (chip): border brightens, cursor pointer (chips are clickable to reassign model).
- Selected (card): whole-card `--mc-accent` 1px border when it's the squad backing the currently
  routed task.
- Disabled chip (agent not available for this provider tier): 50% opacity, toggle switch shown
  in a visibly "off + locked" state (padlock glyph replaces the toggle knob), `cursor: not-allowed`.
- Loading: card renders with 2 skeleton chips.
- Empty squad (no members configured): card shows dashed border + "No agents assigned".
- Error (agent config failed to resolve): chip renders with danger outline + tooltip-style
  inline text "config error", not a silently-blank chip.

### Model Resources

**Model row** — name, `parameter_size`, `quantization`, `size_gb`, plus a **size bar**: a
horizontal bar scaled relative to the largest installed model, filled with
`--vscode-charts-blue`. Bar always paired with the numeric GB label (never bar-only).
- Hover: row bg lifts to `--mc-surface-elevated`.
- Loading (Ollama server unreachable): rows replaced with skeletons + the disk/gauge section
  shows a single error state instead (see below) rather than partial fake numbers.
- Empty (no models installed): "No local models installed" + the suggested-pull list is promoted
  to the primary content.

**Disk-usage gauge** — horizontal stacked bar: used (charts-orange) vs free (charts-green)
segments over total, with a text readout above ("612 GB free of 953 GB") so the meaning never
depends on reading bar lengths alone.
- Warning state (free space < 2x largest model): stacked bar's free segment switches to
  `--mc-warning` and a one-line note appears: "Low headroom for pulling additional models."

**Safe-parallel-workers stat** — single large-number tile (`--text-xl`) with label
"safe parallel workers" and sub-text explaining the estimate is derived from free disk / largest
model size. Not a bar — this is a scalar recommendation, styled like the Overview KPI tile.

**Suggested-pull command** — monospace `<code>` block (`--vscode-textCodeBlock-background`) with
a "Copy" button (icon + label). Never renders a "Run" button — copy-only, per harness safety
rule (models are pulled manually, not auto-executed from the webview).
- Default / hover / focus-visible on the Copy button same as any secondary button.
- Copied (transient state, ~2s): button label swaps to "Copied" + checkmark glyph, `--mc-success`
  text color, then reverts.

### Quality Gates

**Pass/fail checklist** — one row per gate (`schema_non_empty_summary`,
`local_only_never_claude`, `empty_reports_fail`, `stale_watchers == 0`, `fallback_alarm == false`).
- Pass: `--mc-success` check glyph + "Pass" label.
- Fail: `--mc-danger` x glyph + "Fail" label + one-line reason (e.g. "2 stale watcher(s) detected").
- Never a bare colored dot — glyph + word "Pass"/"Fail" always present together.

**Fallback-rate meter** — horizontal bar 0–100%, filled proportionally to `fallback_rate`.
Threshold-based coloring: `--mc-success` under a low threshold, `--mc-warning` mid, `--mc-danger`
once `fallback_alarm` is true — plus the percentage is always printed as text on the bar, and an
"ALARM" text tag appears next to it when active (not color alone).

**Recommendation callout** — a single highlighted block (accent-colored left border, elevated
surface) surfacing `recommendation` text from the API, e.g. "Use local_only until Claude quota
recovers." Empty state: callout is simply omitted (no "no recommendation" noise) when the string
is blank.

### Role Wheel

Radial view of the role-category taxonomy, rendered from the data contract:
`categories: [{id, name, icon(emoji), color(hex), lane, tier, agents:[{name, call_name, model_tier,
external_ok}], count}]`. Full standalone mock: `wheel-mock.html`.

**Layout / node positioning** — a square `.wheel-stage` (`aspect-ratio: 1/1`, `width: min(92vw,
460px)`) holds a centered **hub** (Ikarus, fixed at 50%/50%) and one **node** per category placed
on a circle around it. Position is computed once in JS, not laid out with flex/grid, because it's
genuinely radial: `angle = -90 + i * 360/n` (first node at 12 o'clock, clockwise from there),
converted to stage-relative percentages `left = 50 + R·cos(angle)`, `top = 50 + R·sin(angle)` with
`R = 37` (percent of stage size). Because the stage is a true square, percentage math alone keeps
the circle a circle at any width — no resize listener needed, it reflows for free as the flex
container shrinks (sidebar width) or grows (editor-tab width). Spokes are a single absolutely-
positioned SVG (`viewBox="0 0 100 100"`) with one `<line>` per category from `(50,50)` to the
node's `(cx, cy)`, drawn in the same percentage space so they stay pinned to the nodes without
separate positioning math. The detail panel lives beside the wheel in a `flex-wrap` row (`.wheel-
wrap`) and drops below it on narrow widths, per the standard single-column-stack rule.

**Node** — 46px circle button, category `icon` centered, a small dot in the bottom-right corner
carrying `color` (`--node-color` custom property, set inline per node so the CSS stays static),
category `name` and `count` always rendered as text beneath the button. Color is never the only
signal: icon + name + count are present regardless of theme or color-vision, satisfying "never
color-only" the same way lane/status badges do elsewhere in this doc.
- Default: `--mc-border` ring.
- Hover: ring brightens toward the node's own `color` (`color-mix` against `--mc-border`), cursor
  pointer.
- Selected: `aria-pressed="true"`, ring switches to `--mc-accent`, `--mc-surface-elevated` fill, a
  3px accent glow (`box-shadow`), and the spoke line to that node switches from `--mc-border` to
  the category's own color at 2px. Only one node selected at a time; arrow keys move the selection
  (and focus) around the ring, Enter/Space activate — a plain radial layout is otherwise a poor
  keyboard experience, so this widget gets that affordance instead of relying on Tab order alone.
- Focus-visible: standard 2px `--mc-focus` outline, offset 2px (native `<button>`, no custom focus
  handling needed).
- Empty (category has 0 agents): node ring is dashed instead of solid; label/count render in
  `--mc-text-muted`; the button's `aria-label` still states "N agents" (0) rather than omitting
  count. Selecting an empty node is fully supported — it opens the same detail panel, just with
  the empty-agents state instead of a disabled node.

**Detail panel** — opens for whichever node is selected (one always is; first category selected by
default, mirroring "no empty initial state"). Header: color swatch (circle, `--node-color`) + icon
+ name + agent count. Body, top to bottom:
- **Routing preset**: the category's `lane` badge and `tier` badge, reusing the exact `.badge.lane`
  / `.tier-badge` markup and classes from Agent Squads / Queue Timeline — a category is really just
  a named routing preset, so it should look like one.
- **Agents**: a `.chip-row` of agent chips (`call_name` primary text, `model_tier` badge,
  `external_ok` glyph+label, 🔓/🔒 — never a bare dot), reusing the Agent Squads chip pattern.
  Empty state: the standard dashed `.empty-state` block ("No agents assigned to this category
  yet.") plus the CLI hint for how to fix it, not a silently blank panel.
- **Customize — color**: a row of preset hex swatches (`.swatch-btn`, 22px circles); the swatch
  matching the category's current color shows `aria-pressed="true"` with an accent ring. Clicking
  a swatch updates the category's `color` live — node ring, node dot, spoke line, and detail-panel
  swatch all re-render from the same in-memory object. A text readout ("Color: #3794ff") sits below
  the row so the change is never color-only either.
- **Customize — icon**: a row of emoji buttons (`.emoji-btn`) with the same live-update /
  `aria-pressed` / text-readout treatment for the category's `icon`.
- In the real extension these two actions call `daedalus categories set <id> --color/--icon`; the
  mock only mutates the in-memory `categories` array and re-renders, which is exactly the diff
  Icarus-Jr needs to replace with the real command call.

**Accessibility specifics**: the wheel stage is `role="group"` with an `aria-label`; each node is a
real `<button>` (native keyboard activation, focus ring, `aria-pressed`, `aria-label` stating name
+ count) rather than a styled `<div>`; a visually-hidden `aria-live="polite"` status region
announces selection and customization changes for screen-reader users, since the radial layout
otherwise gives no linear reading order cue for "what changed."

## 4. Accessibility

- **Contrast**: all text/background combinations rely on VS Code theme tokens, which are
  contrast-audited per-theme by VS Code itself; the semantic layer never hardcodes a color that
  bypasses that (mockup fallbacks were chosen to meet WCAG AA against the dark fallback surface).
- **Focus states**: every interactive element (tabs, tiles, chips, buttons, copy actions) gets a
  visible `outline: 2px solid var(--mc-focus); outline-offset: 2px;` on `:focus-visible`. No
  `outline: none` without a replacement, anywhere.
- **Never color-only**: every status/lane/gate/toggle pairs color with a text label and/or icon
  glyph (see component specs above). Verified case-by-case: lane badges, status badges,
  external_ok, active toggle, size bar, disk gauge, fallback meter, pass/fail checklist, Role Wheel
  node ring/dot (always paired with icon, category name, and agent count text).
- **Motion**: skeleton loading states use a static/opacity-only pulse, not sliding shimmer, to
  stay comfortable under `prefers-reduced-motion` (mockup honors that media query by disabling
  the pulse animation entirely).

## 5. Backend Bootstrap & Chat-First Entry Points (live, native code)

Everything below is real, currently rendered by `extension.js` (not the `apps/web/` iframe
content) — it is the extension's own chrome around that iframe, which is the one thing left that
is genuinely native VS Code surface rather than a window onto the React app.

### Why this exists

`bindDashboardWebview()` owns exactly one fact the React app cannot know about itself: whether
the local `daedalus.interfaces.cli.entry web` process it depends on is actually reachable. Before this section
existed, that fact collapsed to two outcomes — the iframe (success) or a blank panel plus a
generic, often-swallowed VS Code error toast (every failure, indistinguishable from each other).
"Cannot find daedalus root", "python isn't on PATH", "the process started and then crashed", and
"the process is alive but hasn't answered yet" are four different, actionable situations; showing
the same blank panel for all four is the "green check nobody measured" failure mode this whole
product exists to refuse elsewhere. `ensureWebServer()` now classifies its own failure instead of
throwing one generic `Error`, using the SAME five-word vocabulary as `GovernanceState`
(`apps/web/src/types.ts`) rather than inventing a second one:

| state | meaning | shown when |
|---|---|---|
| `checking` | in-flight probe; not yet a pass or a fail | always shown first, before the probe resolves |
| `unknown` | process spawned, still alive, has not answered within 5s | ambiguous — may still come up |
| `degraded` | process spawned then exited before answering | captured stderr tail is shown, not swallowed |
| `absent` | never spawned (no root resolved, or the interpreter itself failed to launch) | `daedalus.root` unset/wrong, or `daedalus.python` not found |

`backendStateHtml()` renders these — never a spinner (a spinner implies measured progress; a
static state word does not make that claim) — always with the state name spelled out as text
(never color-only), a plain-language headline, an always-visible remediation line for the no-root
case specifically (not hidden behind a details toggle), and a collapsed `<details>` for raw
stderr/error text when there is any. A **Retry** button posts `{type:'retryBackend'}` back to the
extension via `webview.onDidReceiveMessage` (the first real use of message-passing on this
webview; `agentOsHtml` itself is a static iframe with no channel back to the extension).

### Chat-first entry points

`apps/web/src/app/Cockpit.tsx` owns the trio IA (`map / chat / ide`) and it is real and lives
there, not here. **This paragraph's premise has expired** [MEASURED 2026-09-01]: it was written
when `apps/web/src/App.tsx` opened into `chat` by default ("THREE SPACES. Chat is home.").
G1-UI-02 retired that surface in `e133e09b`, and `Cockpit.tsx:96` now defaults to `map`, falling
back to a saved `chat` or `ide` only if one was persisted. "Chat is home" is no longer true of
the shipped surface, so an extension built to match it would be matching a retired design. So making the extension "chat-first" is NOT a second chat implementation; per
`tests/test_ui_governance.py::test_vscode_surface_reaches_governance_through_the_web_app`, the
VS Code surface is required to stay a window onto that app, not a second renderer. What the
extension *can* add natively:

- `daedalus.openChat` ("Daedalus: Chat with Ikarus") — a separately-discoverable command
  (Activity Bar toolbar, command palette) that opens the same panel `daedalus.openDashboard`
  does. Same underlying `openDashboard()` call, same singleton panel — two front doors onto one
  cockpit, not two cockpits.
- The Activity Bar webview view (`daedalusDashboardView`) is now titled **Ikarus**, not
  "Dashboard".
- `daedalus.askAboutFile` ("Daedalus: Ask Ikarus About This File", editor context menu) — copies
  a suggested objective (current file, plus the selection if there is one) to the clipboard and
  opens the chat panel. This is a **designed-against-an-assumed-seam** feature, stated plainly in
  its own code comment: `apps/web`'s URL handling read only `project` from `location.search`,
  not an initial-message param, so VS Code could not deep-link a pre-filled chat turn.
  Clipboard + an explicit "paste it in" notification is honest about that limitation instead of
  pretending the deep link exists; it upgrades for free the day `apps/web` grows that param.

  **The seam has moved since this was written** [MEASURED 2026-09-01]. `App.tsx` was retired by
  G1-UI-02 in `e133e09b`, and its successors read three params, not one:
  `Cockpit.tsx:92` reads `view`, `Cockpit.tsx:136` reads `project`, and
  `features/conversation/Conversation.tsx:152` reads `context_ref`. Still no initial-message
  param, so the clipboard behaviour remains correct — but the stated reason ("reads only
  `project`") is no longer the measured one, and whoever revisits this should check
  `context_ref` before assuming a new param is needed.

### What this section deliberately does not cover

Per-turn / per-step progress (plan issued → tool call → file edit → verified) is not rendered
natively here. `daedalus/orchestration/ikarus/shell.py::ask` / `ask_stream` is single-turn and stateless as of this
writing (no conversation/session id in the request shape) and the existing SSE surface
(`/api/events`: `hello|report|heartbeat|queue`) is task-level, not step-level. Conversation state
and a richer progress-event model were, at the time of this writing, being built concurrently by
other agents against `daedalus/interfaces/http/web_api.py` — an assumed seam, not one this extension currently
renders. The honest thing this section can say is what already exists and is wired end-to-end
today: chat happens in `apps/web`; queued work is visible via the existing real file-bus queue
(pending/reports/processed, already surfaced through `daedalus dashboard --json`); the extension
does not currently bridge "a chat turn proposed a task" to "watch that task's steps," beyond the
`action: {kind:'queue_task', requires_confirmation}` shape `apps/web` already renders and confirms
before enqueueing.

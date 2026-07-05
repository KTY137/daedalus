# Mission Control v1 — Design System

Design spec for the 5-tab Mission Control webview (Overview, Queue Timeline, Agent Squads,
Model Resources, Quality Gates) over the `daedalus` harness. Written for direct 1:1 port into
the existing `vscode-agent-env` webview (see `extension.js` `dashboardHtml`, which already uses
top tabs and `--vscode-*` variables — this spec extends that convention rather than replacing it).

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

## 4. Accessibility

- **Contrast**: all text/background combinations rely on VS Code theme tokens, which are
  contrast-audited per-theme by VS Code itself; the semantic layer never hardcodes a color that
  bypasses that (mockup fallbacks were chosen to meet WCAG AA against the dark fallback surface).
- **Focus states**: every interactive element (tabs, tiles, chips, buttons, copy actions) gets a
  visible `outline: 2px solid var(--mc-focus); outline-offset: 2px;` on `:focus-visible`. No
  `outline: none` without a replacement, anywhere.
- **Never color-only**: every status/lane/gate/toggle pairs color with a text label and/or icon
  glyph (see component specs above). Verified case-by-case: lane badges, status badges,
  external_ok, active toggle, size bar, disk gauge, fallback meter, pass/fail checklist.
- **Motion**: skeleton loading states use a static/opacity-only pulse, not sliding shimmer, to
  stay comfortable under `prefers-reduced-motion` (mockup honors that media query by disabling
  the pulse animation entirely).

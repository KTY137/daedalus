# G1-UI-21 — A token audit as a test, and one pane rule for every workbench

Packet ID: G1-UI-21
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Change class: deterministic test plus theme/material wiring; no API, policy,
evidence or view-behaviour change.
Owner: repository owner ("mach weiter, nimm die most advanced general
option", 2026-09-06 09:53, after G1-UI-20)
Base revision: 5a13dbf95e05becce15d26bdec199b26e62bc082
Dependencies: G1-UI-20 (`--u5`/`--u7`), G1-UI-10 (glass recipe)
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 13.

## Primary acceptance claim

The class of bug behind G1-UI-20 cannot recur silently: the app bootstrap
suite fails when any stylesheet reads a `var(--x)` without fallback that
nothing defines. Every such token in the tree is defined today, and the
glass treatment of workbench cards is one rule shared by Genesis, Ariadne
and the IDE notice instead of a per-view block.

## Baseline (measured 2026-09-06 09:55)

The first run of the audit over `apps/web/src` found, beyond the two spacing
steps of G1-UI-20, eight more undefined tokens that had been rendering as
invalid declarations:

| Token | Where | Effect while undefined |
| --- | --- | --- |
| `--danger` ×2 | ide.css `.project-dialog-error` | no left border colour, default text colour on the error |
| `--radius-lg` | ariadne.css `.ariadne-card` | square corners |
| `--accent-glow` ×2 | motion.css | no hover shadow, no focus ring on the react-bits buttons |
| `--edge-soft` ×2, `--text` | motion.css | default border/colour |
| `--r-sm`, `--r-lg` | motion.css | square corners |
| `--good` | motion.css | invisible success border |

Ten further names (`--plane-color`, `--shell-color`, `--filter-id`, the six
`--preview-*` of the studio, `--range-fill`) are set from TSX inline styles;
the audit counts those as definitions.

## Scope

Owned paths: `apps/web/src/app/tokens.spec.mjs` (new), `apps/web/src/app/run-spec.mjs`
(one import, one spread), `apps/web/src/features/ide/ide.css`,
`apps/web/src/features/ariadne/ariadne.css`, `apps/web/src/shared/ui/motion/motion.css`,
`apps/web/src/app/styles/spatial.css` (the G1-UI-20 block generalised), this
packet. Not touched: `apply.ts` token list beyond G1-UI-20, any TSX, tests
under `tests/`.

## Contracts and behavior

- **Audit.** `tokens.spec.mjs` walks `src` for `.css`, collects every
  `var(--x)` without a fallback, and checks it against `--x:` declarations in
  CSS plus `'--x'` string literals in `.ts`/`.tsx` (apply.ts setters and
  inline style objects). Plain JS like `architectureSpec`, because the web
  tsconfig has no node types. Nine results: the audit and the contiguity of
  `--u1 … --u8`.
- **Repairs.** `--danger` → `--bad`; `--radius-lg` → `calc(var(--radius) + 4px)`;
  motion.css: `--accent-glow` → `color-mix(in srgb, var(--accent) 35%, transparent)`,
  `--edge-soft` → `--line2`, `--text` → `--ink`, `--r-sm`/`--r-lg` →
  `--radius-sm`/`--radius`, `--good` → `--ok`.
- **Panes.** One glass rule for `.genesis-card`, `.genesis-result`,
  `.ariadne-card`, `.ariadne-result`, `.ide-notice`; the room is dimmed to
  14 % behind genesis, ariadne and ide like the map; Ariadne's own radial
  tints are dropped under glass (they stacked a second haze on the render);
  intro body text in both workbenches uses `ink2`.

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Type | `npx tsc --noEmit -p .` exit 0 (after moving the spec to `.mjs`; the `.ts` draft failed on `node:fs` without node types) |
| Bootstrap | `npm run test:app` 536/536; the audit reports "71 tokens across 22 stylesheets, all defined" |
| Refusal | the first run failed exactly on the ten TSX-set names until code literals counted as definitions, and would fail on the eight repaired tokens if reverted |
| Visual | Genesis and Ariadne at 1440 and 1024 px, zero page errors; Ariadne cards now opaque glass, fields no longer show the render |
| Not run | `tools/gui_check.py` browser suite |

## Evidence, expected failures and review

The audit reads static text. A token set only at runtime under a condition
(for example inside a `matchMedia` branch) counts as defined by its literal
even if the branch never runs; that is the right side to err on for a
spacing/colour audit, and a false "defined" is visible on screen.

## Migration and rollback

Delete `tokens.spec.mjs`, revert the two lines in `run-spec.mjs` and the
four stylesheets.

# G1-UI-14 — The empty conversation is a workspace, not a landing page

Packet ID: G1-UI-14
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner (2026-09-05, continuation of the UI lane after the Codex UI session ended)
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Integration context: uncommitted tree on top of G1-UI-12/13
Dependencies: G1-UI-10 (glass material rules in `app/styles/spatial.css`), G1-UI-13 (room looks)
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Presentation only. Chat remains an interface; no orchestration state, API,
policy or evidence change.

## Primary acceptance claim

With the glass material, an empty conversation reads as one workspace: the
invitation, its three suggestions and the composer sit on one reading pane
that stays legible over any room; the side rail hugs its content instead of
standing as an empty window; the chrome bar stops floating as a third window;
and the optional sculpture lives inside the pane without being clipped.

## Baseline (the owner's rejection, 2026-09-05 07:43, as diagnosed by Codex)

- "Der Einstieg sieht eher nach einer Landingpage als nach einer
  Arbeitsoberfläche aus": 58 px display headline "Große Ideen. Fangen wir an."
  and a marketing eyebrow, floating on the bare background.
- "Kopfleiste, Chat und leere Seitenleiste wirken wie drei getrennte Fenster":
  three separately shadowed glass panes, the rail full-height and empty.
- Measured here: the compact sculpture in the invitation is clipped at
  viewport heights ≤ 800 px (`spatial.css` sets it to 100 px high with
  −15 px margins); with a room behind, invitation body text falls below
  comfortable contrast over bright picture areas (G1-UI-13 residual).

## Scope

Owned paths: `apps/web/src/app/styles/spatial.css` (glass-material rules
only), the empty-state copy in `apps/web/src/features/conversation/Conversation.tsx`,
`apps/web/tests/spatial.spec.ts`, this packet. Base (non-glass) layout in
`conversation.css`/`shell.css` is not touched; flat and paper looks keep their
current empty state.

## Contracts and behavior

- `.convo-open` becomes a glass pane (same fill, edge and blur recipe as the
  composer), with `overflow: hidden`; the headline scales 26–38 px; the three
  suggestions form a compact row; the compact sculpture is positioned inside
  the pane's top-right corner and never clipped by negative margins.
- On an empty thread (`.convo.at-rest`) the rail aligns to the start of its
  grid row and drops its pane shadow; the chrome bar's shadow is reduced.
- Copy: eyebrow "IKARUS", headline "Woran arbeiten wir?", note names the
  selected project and the three things the suggestions do. No claim about
  evidence or capability is added.
- Existing selectors and roles stay: `.convo-open-line`, the suggestion
  buttons by name, `.composer`, `.talk-side`, so the current browser tests
  keep their meaning.

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Pane | `.convo-open` has a non-transparent background and blur under glass; headline ≤ 40 px at 1440×900 (spatial.spec) |
| Sculpture | With Liquid Glass at 1440×760 the compact canvas is fully inside the pane's box (spatial.spec) |
| Rail | On an empty thread the rail's height is its content height, not the row height (spatial.spec) |
| Narrow | Existing 390 px test: invitation, composer, editor reachable; rail below composer |
| Regression | Existing spatial tests, `test:app`, `tsc` |
| Visual | Screenshots in Graphite Atelier and Porcelain, 1440×900 and 390×844 |

## Migration and rollback

CSS and copy only. Rollback removes the appended block in `spatial.css` and
restores the two copy strings.

## Evidence, expected failures, and review

Measured 2026-09-05, 11:56–12:10, with the machine at approximately 60%
CPU and 4 GB free RAM from parallel agent runs:

- `npx.cmd tsc --noEmit -p .`: exit 0 after the copy change (later edits were
  CSS and the browser spec only; `tests/` is outside the tsconfig include).
- `npm.cmd run test:app`: **524/524 passed** after the copy change; no spec
  pins the empty-state copy.
- `DAEDALUS_GUI_BASE_URL=http://127.0.0.1:5173 npx.cmd playwright test tests/spatial.spec.ts`:
  **6/6 passed**, 48.8 s (final run). The new test asserts a filled, edged,
  shadowed pane with `overflow: hidden`, a declared blur where the engine
  supports `backdrop-filter`, the headline ≤ 40 px, the rail below 60 % of the
  row height on an empty thread, and — after selecting Liquid Glass at
  1440×760 — a WebGL sculpture ≥ 120 px tall entirely inside the pane's box.
- Measured at 1440×900 in Graphite Atelier: pane 778→786 px wide flush with
  the composer, headline 37.4 px, rail 167 px tall in a 684 px row.
- Screenshots in the session scratchpad: `d5-ui14-graphite-empty-2.png`,
  `d5-ui14-porcelain-empty.png`, `d5-ui14-porcelain-390-c.png`.

Negative results and residuals:

- Three failed attempts of the new browser test before it was right, none a
  product defect: (1) `getComputedStyle(...).backdropFilter` read as
  `undefined`, (2) `getPropertyValue('backdrop-filter')` read as empty,
  (3) `borderTopWidth` read as `NaN`. Cause: the pane is re-rendered when the
  `/api/projects` fixture arrives and the first measurement hit a detached
  node, which reports empty computed styles. The test now polls until the
  node is attached and styled. Additionally the bundled headless shell drops
  `backdrop-filter` from the CSSOM, so the blur assertion is conditioned on
  `CSS.supports`; the real Chromium (Playwright MCP) reports both supported
  and declared.
- One run failed on a 30 s `page.goto` timeout in the 390 px test under load;
  the immediate re-run passed in 3.1 s. Not retried inside Playwright
  (`retries: 0` is deliberate); reported here instead.
- Below 600 px the pane returns to plain text: with bar, composer, rail and
  status stacked in 844 px, a card cut by the scroll region looked broken. The
  note is hidden there and the three suggestions become wrapping chips; the
  third chip sits below the fold and scrolls into view. This is the same
  scroll behaviour the base layout had, with more of the invitation visible.
- Flat and paper materials keep the previous empty state on purpose (glass
  rules only). No release, merge or promotion is claimed; independent review
  of copy and composition is outstanding.

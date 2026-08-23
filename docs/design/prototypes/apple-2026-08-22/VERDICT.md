# Four Apple-standard prototypes — verdict (2026-08-22, round 2)

Owner's order: use React Bits properly, do not look AI-generated, orient on Apple, be Lagerfeld /
Jobs, revamp everything, no old version as reference, construct from the feature list, four
prototypes, Codex reviews. Done as ordered: four isolated Vite apps (keynote / visionos / sequoia /
lagerfeld), each with cockpit · library · settings · ⌘K, built from `BRIEF.md` + `fixture.json`
only, measured with `daedalus/gui/probe.js` + `lint.py`, reviewed by **Codex gpt-5.6-sol, reasoning
xhigh**, five calls (four per-prototype with all four screens attached, one comparative with the
four cockpits). 6 agents, 55 min, 930k subagent tokens. Raw Codex output: `codex/*.md`.

Everything built is throwaway and lives outside the repo. No React Bits source retained.

## Codex's result — plain

| | keynote | visionos | sequoia | lagerfeld |
|---|---|---|---|---|
| Codex score ("owner says wow, not slop") | 3/10 | 3/10 | 3/10 | 3/10 |
| Codex comparative rank | 3 | 4 — "do not build this" | **1 — "build this"** | 2 |
| Least AI-looking (Codex) | | | **yes** | |
| Strongest visual point of view (Codex) | | | | **yes** |

Codex opened the Sequoia review with "Reject this round." and still ranked it first: "It is the only
prototype that looks like functioning desktop software rather than a design concept … It accepts the
boring disciplines of real software — persistent navigation, conventional split views, consistent
alignment, predictable controls and clear information ownership. The other three visibly try to
impress. Sequoia looks like somebody actually had to use it every day."

Athena's own eye agrees with the ranking.

## What Codex found in ALL four (this is the pattern, not the variants)

1. **Fake affordances.** Chat Send, palette verbs, Focus the slice, rights selectors, Accent — most
   do nothing or just close a dialog. "Make every visible affordance truthful" is fix #1 in every
   review. A prototype that looks operable and isn't reads as generated.
2. **Doctrine as decoration.** "Ikarus proposes. You decide." / "verbatim, never scored" / "named,
   never silent" pasted into chrome on every screen. The interface should demonstrate the values,
   not announce them.
3. **Demo components as garnish.** TiltedCard, ScrollStack, CountUp, DarkVeil, Folder, Stack
   receipt-decks, TextPressure, Magnet, LiquidChrome, the initial-letter gallery, the internal Dock
   — "requirement-shaped garnish". Structural and defensible in Codex's view: **Stepper** (all
   four), **AnimatedList**, **GooeyNav**, **LineSidebar**, **FadeContent** used sparingly.
4. **The graph is never the hero and never readable.** Four evenly spaced columns with hairlines,
   10–12 px labels, truncation, no zoom/pan, pointer-only, no keyboard — "an architecture-diagram
   generator", "a graph-library showcase". Keep the four-plane model and solid-vs-dashed
   verified/proposed semantics; replace the rendering.
5. **Type too small, greys below AA, sentence case broken in the same places** ("slice: warm",
   "ask every time", "within a mission", "kill switch armed"), radii not one scale, 8 pt grid not
   enforced, 44 px targets missed [MEASURED: small_targets 6 / 10 / 39 / 2].
6. **Metric strips survive in disguise** (149 / 4 / 11 as "Architecture"; 149 / 4 / 11 / 8,120 in
   Lagerfeld; 23 / 4 / 11 / B on module pages).
7. **Density.** Sequoia's biggest risk per Codex: "five vertical regions, tiny labels and too many
   simultaneously visible facts … without progressive disclosure the graph will stop being the hero
   and the app will become a database administration screen."

## Measured [probe.js + lint.py, cockpit, 1440×900]

| | keynote | visionos | sequoia | lagerfeld |
|---|---|---|---|---|
| visible_elements (≤150) | 145 | **369** | **288** | **172** |
| framed_panels (≤8) | 4 | 0 | 7 | **19** |
| contrast_failures (0) | 0 | **11** | **15** | **3** |
| small_targets (0) | **6** | **10** | **39** | **2** |
| status_pills (0) | **10** | 0 | **3** | 0 |
| allcaps share | 0 | 0 | 0 | 0 |

Sentence case finally held everywhere (allcaps 0 %, previous round 6–50 %). Keynote is the only
one inside the element budget; Sequoia's 39 small targets are its sidebar rows and stage dots.

## Recommendation

**Build one: Sequoia as the foundation**, with Codex's borrow list and fix-first list applied, not
a fifth direction:

- from **Lagerfeld**: progressive graph emphasis (dim everything unrelated, make the selected
  subgraph unmistakable) and its typographic confidence;
- from **Keynote**: breathing room around the mission and the clear six-stage progression with
  names visible;
- from **visionOS**: translucency only for what genuinely floats — the ⌘K palette and the
  settings sheet — nothing else.

Fix-first (Codex, Sequoia review): (1) make the product loop truthful — real per-project state,
chat submit/stream, proposal → owner-decision states, real module search, real command
destinations; (2) recompose the cockpit around the atlas: drop the full library tree and the
duplicate animated menu from the cockpit, show all six named stages, give the graph space plus
zoom/pan/focus; (3) one visual spec: 16 px body, AA secondary, one radius, one blue action per
context, sentence case, no interpunct prose; (4) semantic tabs/tree/listbox/slider, keyboard atlas,
visible focus, real reduced-motion; (5) remove requirement-shaped garnish (folder, rolling counter,
fake masonry).

React Bits in that build: Stepper, AnimatedList, FadeContent for transitions, a real nav item
(GooeyNav or LineSidebar) — structural only; no backgrounds; no text-effect on facts.

## Provenance

Scores, ranks and quotes: `codex/{keynote,visionos,sequoia,lagerfeld,comparative}.md` (Codex
gpt-5.6-sol via `codex exec -s read-only`, prompt on stdin because `-i` is variadic in 0.146).
Numbers [MEASURED]: `metrics.md`. Builders' claims: `notes/*.md`. Workflow `wf_eeb7ab8e-64b`.

# Sequoia v2 — verdict (2026-08-23, round 3)

Owner: "mach weiter" after round 2 (Codex: build Sequoia as the foundation). Done: Heracles rebuilt
the Sequoia prototype against Codex's full fix-first list (truthful affordances, cockpit around the
atlas, one visual spec, accessibility, garnish removed); Codex gpt-5.6-sol reviewed it twice (full
review against the brief; before/after delta); Odysseus audited every control adversarially with an
independent Playwright harness (227 activations, 4 screens × 3 projects). Screenshots in `shots/`
(`v1-cockpit.png` is the before), Codex verbatim in `codex/`, builder's claims in `NOTES.md`,
Odysseus' leak proof in `odysseus/`.

## Three verdicts on one build

| Source | Verdict |
|---|---|
| Codex, full review vs brief | **3/10** — "engineered more carefully than it is designed … a careful AI-generated admin prototype with good state wiring, not a singular Apple-standard product" |
| Codex, before → after delta | **6/10** — "a meaningful rebuild, not a cosmetic revision"; fix-first: 1 partly · 2 partly · 3 landed · 4 partly · 5 landed |
| Odysseus, affordance audit | claim **narrowed**: Daedalus project 181/181 truthful (0 dead, 0 lies); unindexed projects **35 dead + 5 lies** |

Athena's reading: round 3 repaired the *behaviour*, not the *gestalt*. That is the finding across all
three rounds — wiring and honesty are solvable by checklist; "Apple standard" fails on composition
and typography, which no checklist produces.

## What landed [Codex delta + Odysseus, MEASURED]

- Doctrine copy, traffic lights, Folder, Counter, Masonry, StaggeredMenu, interpunct prose: gone.
- Approve / Reject / Undo on the Build proposal change real state; quick actions are three distinct
  outcomes; ⌘K filters and every row has a destination (68/68 navigation checks); streaming is
  genuinely incremental; settings persist, Delete everything clears; Motion Off and
  `prefers-reduced-motion` stop everything (0 frames animating); 20 tab stops all with visible
  focus; dialogs trap and restore focus.
- Selection state (dim unrelated to 35 %, subgraph in accent with relation labels, inspector filled)
  is "by far the strongest state" — Codex says it should guide the default.

## What did not [all three sources]

1. **Fake data under other projects** (Odysseus). Status line is byte-identical for all three
   projects with an **M** stamp on Daedalus' numbers; ⌘K offers Daedalus' 32 nodes under TCT ("Find
   module — 32 nodes in this index" where the index has 0) — 35 dead rows; "Sealed promotion" renders
   the Daedalus wiki body captioned "TCT scan planner wiki". Violates the standing invariant "no
   number without a real source", and the builder's own NOTES promise.
2. **Measurement claim refuted** (Odysseus). "0 targets under 44 px" came from a check that excludes
   SVG (`audit.cjs:44`); the 32 atlas nodes are 16 px tall, 14 of 32 closer than 44 px.
3. **Disabled reasons not printed** for Focus the slice (tooltip only) and Send (none).
4. **The atlas is the structural hero, not the attentional hero** (Codex ×2): a column grid with
   every edge drawn at rest — "a spreadsheet-shaped hairball"; 384 elements vs ≤ 150; labels 12 px;
   mission band eats the canvas; title 21 px where the brief says 34–64.
5. **Still the generic shell** (Codex): top bar + sidebar + hairlines + status footer; the copilot
   recipe (named rail, three chips, rounded composer); identical 3-px-stripe selection motif at
   every level; two greys flatten hierarchy; Settings is a page, not a sheet; 8 px radius vs the
   brief's 12–20; dark mode is a literal inversion; lens labels lowercase.
6. **Timeline outside Ikarus** — the brief places it inside the Ikarus panel.

## Codex's three highest-leverage changes

1. Draw only backbone edges at rest; reveal full relationships on hover / selection / lens.
2. Merge Ikarus and Knowledge into one contextual drawer or tabbed inspector; give the graph 70–75 %
   of the canvas.
3. Remove the last demo chrome: compact the stage band, merge the four duplicate status lines,
   replace the generic chat chips, redesign or drop the stray provenance letters.

**Owner decision needed on #2:** it changes the locked trio IA (Ikarus · Codebase · Knowledge as
three standing panels) into graph + one inspector. Codex's reasoning is the hero problem; the
counter-argument is that the conversation is the product's front door. Not decided here.

## Next, if continued

A v3 with: (a) project scoping fixed and a fake-data test in the harness (status line / palette /
wiki must differ per project or say "no index"); (b) SVG targets counted, atlas node hit areas
≥ 44 px; (c) backbone-only edges at rest + selected-state as default treatment; (d) 34 px title,
timeline compacted inside Ikarus, Settings as a sheet, 12 px radius, a real type scale with three
greys; (e) the #2 IA decision once the owner rules. Then Codex again — the bar is a score that moves
on the *full* review, not only the delta.

## Provenance

`codex/full-review.md`, `codex/delta-review.md` (codex exec, read-only, images attached, prompt on
stdin); Odysseus report in the session transcript (agent "odysseus-affordances"), scripts
`spike3/odysseus/01–17` in the session scratchpad, 73 screenshots, leak proof retained here;
Heracles' NOTES.md with its control table. Costs: Heracles 344k tokens / 56 min, Odysseus 194k /
58 min, Codex 2 calls.

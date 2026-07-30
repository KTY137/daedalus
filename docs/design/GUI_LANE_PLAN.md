# The GUI lane — giving UI work a thermometer

Owner idea, 2026-07-30: *"könnten wir das nicht auch in daedalus integrieren in einen GUI
workflow? auch mit playwright oder so zum prerendern und evaluieren?"*

Status: DESIGN. Not built. Momus round outstanding.

## Why this is the right idea

UI is **the only lane in Daedalus without a gate.** Every other lane has a thermometer:
tests for code, `eval/` for routing, the docref scan for documentation, `fenced_dominance`
for the safety fence. UI's gate is currently *"the owner looks at it and says slop"* — a
human in the hot path, no baseline, no regression detection, no way for the loop to improve
without him. Playwright plus the rule corpus is the missing instrument.

The doctrine already demands this: measurement picks next, a gate blocks before promotion,
and nothing is promoted by a model. A GUI lane is the same shape as every other lane; it has
simply never had a way to measure its output.

**We already own a labelled corpus.** Two designs the owner rejected as AI slop, one he
approved ("ich hab gemocht das der graph so 3d in der mitte war"). That is training data for
calibrating the thresholds below, and it is the only reason the anti-slop linter can be
honest rather than invented. Prototypes are in `docs/design/prototypes/`.

## Licensing — this shapes the architecture, it does not block it

| Source | License | What we may do |
|---|---|---|
| React Bits | **MIT + Commons Clause** | Use in our product, commercially. **May NOT redistribute the components** alone, bundled, or ported. |
| ui-ux-pro-max skill | **MIT** | Vendor freely, with attribution. |
| Playwright | Apache-2.0 | Vendor/depend freely. |

Consequence, and it is a hard constraint: **the GUI lane fetches React Bits per project from
the official registry; Daedalus never bundles it.** That is the shadcn/MCP path, where the end
user obtains the components themselves under the same licence. It is also better engineering
— the registry stays current instead of frozen at vendor time. The MIT rule corpus (the
ui-ux-pro-max CSVs) *is* vendorable and becomes the knowledge behind the linter.
See `reactbits-refs.md`. Cerberus reviews this before any code lands.

## Shape of the lane

```
compose → prerender (deterministic) → measure (3 tiers) → visual diff → gate → human promotion
```

### 1 · Compose
An agent edits or builds a screen, resolving components from the registry through the MCP
server. Design tokens come from the design language (six lines, in `HANDOFF_UI.md`).

### 2 · Prerender — deterministic or the diff is noise
Playwright at fixed viewports (375 / 768 / 1024 / 1440). Determinism is load-bearing, the same
way byte-identical index snapshots are:

- animations paused (`prefers-reduced-motion` plus `animation-play-state: paused`)
- clock frozen; `Math.random` and `Date.now` stubbed
- the projection canvas seeded (it already is — `seed = 20260730`)
- fonts settled before capture (`document.fonts.ready`)

Artifacts per viewport: a PNG, plus a **DOM + CSSOM dump** — the dump is what the linter reads,
not the pixels.

### 3 · Measure — three tiers, only the first two can block

**Tier A · hard gates, mechanical, fail-closed.** Objective, no judgement:

| Check | Threshold | Source |
|---|---|---|
| text contrast | ≥ 4.5:1, computed from rendered colours | ui-ux-pro-max priority 1 |
| body horizontal overflow | none at any viewport | priority 5 |
| interactive target size | ≥ 44×44 px | priority 2 |
| focus-visible | present on every interactive element | priority 1 |
| console errors | zero | — |
| reduced-motion honoured | motion-on vs motion-off renders must differ | priority 7 |
| banned font families | absent from computed styles | `frontend-design` |

**Tier B · the anti-slop linter. The novel part: taste as a measured property.**
Every rule below is computable from the CSSOM, and every threshold gets calibrated against
the rejected-vs-approved corpus rather than guessed:

- distinct `border-radius` values on one screen (incoherence)
- bordered boxes per viewport (card soup — the rejected screen had ~25)
- nesting depth of bordered containers (the rejected screen ran four deep)
- ratio of ALL-CAPS text to total text (shouted labels as decoration)
- simultaneously visible status pills (the rejected screen showed five plus a legend)
- presence of an N-equal-tile metric row (the category's most recognisable trope)
- distinct accent hues, excluding semantic colour (should be ≤ 2)
- raw JSON or internal identifiers rendered as user-facing text (`{"line":695,…}`,
  `corpus_files_scanned` — both shipped on the rejected screen)

A failing rule reports the count, the threshold, and the offending selectors. **These are
proxies, not truth** — the linter must say so in its own output, and a proxy that stops
correlating with the owner's verdict gets retired rather than defended.

**Tier C · judge, advisory only.** A vision-capable model scores the render against the six-line
design language and returns dissent verbatim, like the council. It **never promotes** — same
rule as everywhere else in this system.

### 4 · Visual regression
Screenshot diff against the approved baseline; any delta is reported with the rule or commit
that caused it. Catches the accidental change that no rule anticipated.

### 5 · Gate → human promotion
Tier A or B failure blocks. The owner promotes. Identical to every other lane.

## Where it plugs in

- `daedalus/gui/render.py` — Playwright driver, determinism harness, artifact writer
- `daedalus/gui/probe.py` — DOM/CSSOM extraction into a stable JSON shape
- `daedalus/gui/lint.py` — Tier B rules over that JSON; corpus from the vendored MIT CSVs
- `daedalus/gui/gate.py` — verdict object the write wave can consume
- baselines and renders under `runs/gui/`
- Playwright is already an `apps/web` devDependency, and the MCP server is configured

**Deliberately deferred:** a picker band (`ui_slop` / `ui_regression`). Momus's ruling on the
type-graph band applies unchanged — `DEFAULT_LIMIT = 10` means a new band *displaces* work, and
that claim is unhaltbar until the linter's false-positive rate is measured. Calibrate first,
then earn the band.

## Honest risks

1. **Playwright renders cost seconds each, times four viewports.** This must not run on every
   loop iteration — UI-touching diffs only, and the cost gets measured and published like any
   other gate.
2. **Tier B can become a cargo cult.** Rules that no longer predict the owner's verdict are
   worse than no rules, because they read as objective. Every rule carries its calibration
   evidence, and the linter reports its own agreement rate with human verdicts.
3. **The corpus is n=3.** Two rejected screens, one approved. That is enough to set direction
   and nowhere near enough for thresholds to be called measured. Until it grows, thresholds are
   stamped ASSUMED, not MEASURED.
4. **A gate that fails everything gets disabled.** Tier B starts advisory-only and is promoted
   to blocking one rule at a time, each on the strength of its own agreement rate.

## First beat if this is approved

`render.py` plus `probe.py` alone, run over the three prototypes in
`docs/design/prototypes/`. That produces the first real measurements of the rejected and
approved screens side by side — which is exactly the calibration data every threshold above is
waiting on. No rules, no gate, no band: just the numbers, and then we look at whether they
separate the slop from the keeper.
